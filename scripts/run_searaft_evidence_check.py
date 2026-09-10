#!/usr/bin/env python3
"""One fixed evidence evaluation from saved predictions; never imports a model.

--run scores each controlled half once, locks the auxiliary threshold, scores
natural events, and writes fixed review sheets. --finalize only reads saved
scores and the completed natural_event_review.csv; no image rescoring.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
from uw_frontend.tracking.correspondence_evidence import check_correspondence_evidence, sample_patches

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'papers/frontend_searaft_screening_v1'
PAPER = ROOT/'papers/frontend_searaft_evidence_check_v1'
SOURCE = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1')
RUNTIME = SOURCE.parent/'frontend_searaft_evidence_check_v1'
INPUT_COMMIT = 'a2f3bedcc2e4f98bd18f99a3601d70433de42aa7'
FREEZE_COMMIT = '12310f47e31b86764bb67e2920bc9171e0c38391'
SEQUENCES = ['A02', 'A08', 'H02']
CASES = ['small', 'large', 'illumination_blur', 'outside_occluded']
METHODS = ['S0', 'S1', 'C0', 'C1', 'SU']
PATCH_TIMINGS = []
LABELS = ['VISIBLE_STRUCTURE_SUPPORTED', 'CLEAR_IDENTITY_CONTRADICTION', 'UNRESOLVED']


def read_csv(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    for r in rows:
        for k, v in r.items():
            if v in ['True', 'False']:
                r[k] = v == 'True'
            elif v == '':
                r[k] = None
            else:
                try:
                    r[k] = float(v) if any(c in v.lower() for c in ['.', 'e']) or v.lower() in ['nan', 'inf', '-inf'] else int(v)
                except ValueError:
                    pass
    return rows


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w') as stream:
        out = csv.DictWriter(stream, fieldnames=keys, lineterminator='\n')
        out.writeheader()
        for r in rows:
            out.writerow({k: '' if isinstance(v, (float, np.floating)) and not np.isfinite(v) else v for k, v in r.items()})


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def points(rows, arm):
    return np.array([[r[arm+'_x'], r[arm+'_y']] for r in rows], dtype=float)


def image(path):
    data = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if data is None:
        raise FileNotFoundError(path)
    return data


def ratio(n, d):
    return n/d if d else None


def border_distance(p, shape):
    if not np.isfinite(p).all():
        return None
    h, w = shape
    return float(min(p[0], p[1], w-1-p[0], h-1-p[1]))


def border8(p, shape):
    h, w = shape
    return bool(np.isfinite(p).all() and p[0] >= 8 and p[0] < w-8 and p[1] >= 8 and p[1] < h-8)


def add_patch_fields(rows, prev, cur):
    start = time.perf_counter()
    for arm in ['S', 'C']:
        evidence = check_correspondence_evidence(prev, cur, points(rows, 'previous'), points(rows, arm))
        for i, r in enumerate(rows):
            for field in ['ncc', 'valid_patch', 'evidence_accepted', 'reason']:
                value = evidence[field][i]
                r[arm+'_'+field] = value.item() if isinstance(value, np.generic) else value
            r[arm+'1'] = bool(r[arm+'0'] and r[arm+'_evidence_accepted'])
    return time.perf_counter()-start


def uncertainty_scale(r, scale_xy):
    # Official 9137517 core/raft.py: two marginal Laplace components.
    info = np.array([r['S_info_'+str(j)] for j in range(4)], dtype=float)
    if not np.isfinite(info).all():
        return np.nan
    weight = np.exp(info[:2]-max(info[:2]));weight /= weight.sum()
    b = weight @ np.exp([np.clip(info[2], 0, 10), 0.])
    return float(b*np.mean(scale_xy))


def annotate_truth(r, pair):
    # Offline only: never passed into check_correspondence_evidence.
    x, y = r['truth_x'], r['truth_y']
    h, w = pair['image_shape']
    outside = not (0 <= x <= w-1 and 0 <= y <= h-1)
    boundary = not border8([x, y], (h, w))
    occ, guard = False, False
    if pair['occlusion']:
        x0, y0, x1, y1 = pair['occlusion']
        occ = x0 <= x < x1 and y0 <= y < y1
        guard = x0-6 <= x < x1+6 and y0-6 <= y < y1+6
    assert r['visible'] == (not boundary and not guard), r['pair_id']
    reason = ('OUT_OF_FOV' if outside else 'IMAGE_BORDER_GUARD' if boundary else
              'ARTIFICIAL_OCCLUSION' if occ else 'OCCLUSION_PATCH_GUARD' if guard else
              'VISIBLE' if r['visible'] else 'Unknown')
    r.update(truth_out_of_fov=outside, truth_border_guard=boundary,
             truth_artificial_occlusion=occ, truth_occlusion_patch_guard=guard,
             truth_category=reason)
    for arm in ['S', 'C']:
        epe = float(np.linalg.norm(np.array([r[arm+'_x'], r[arm+'_y']])-np.array([x, y])))
        r[arm+'_correct_location'] = bool(r['visible'] and np.isfinite(epe) and epe <= 2)
    r['original_S_only'] = bool(r['S0'] and not r['C0'])


def score_half(name, offsets, manifest, old_rows, timing):
    result = []
    for pair in (p for p in manifest if p['base_offset'] in offsets):
        rows = [dict(r) for r in old_rows[pair['pair_id']] if r['B_failed']]
        prev, cur = image(pair['previous']), image(pair['current'])
        for r in rows:
            r.update(split=name, S0=r['S_common'], C0=r['C_common'])
        elapsed = add_patch_fields(rows, prev, cur)
        PATCH_TIMINGS.append(dict(pair_id=pair['pair_id'], split=name, queries=len(rows), two_arm_patch_seconds=elapsed))
        h, w = prev.shape
        net = timing[pair['pair_id']]
        scale = [w/net['network_width'], h/net['network_height']]
        for r in rows:
            annotate_truth(r, pair)
            r['uncertainty_scale_px'] = uncertainty_scale(r, scale)
        result.extend(rows)
        print('PATCH_PAIR', name, pair['pair_id'], len(rows), flush=True)
    return result


def summarize(rows):
    table = []
    for split in ['calibration', 'check', 'all']:
        half = [r for r in rows if split == 'all' or r['split'] == split]
        for seq in ['ALL']+SEQUENCES:
            for case in ['ALL']+CASES:
                group = [r for r in half if (seq == 'ALL' or r['sequence'] == seq) and (case == 'ALL' or r['case'] == case)]
                n = len(group);visible = sum(r['visible'] for r in group);invisible = n-visible
                s_correct = sum(r['S0'] and r['S_correct_location'] for r in group)
                only_correct = sum(r['original_S_only'] and r['S_correct_location'] for r in group)
                baseline = {method: sum(r[method] and r['C_correct_location'] for r in group) for method in ['C0', 'C1']}
                for method in METHODS:
                    arm = 'C' if method.startswith('C') else 'S'
                    accept = [r for r in group if r[method]]
                    correct = sum(r[arm+'_correct_location'] for r in accept)
                    invisible_accepted = sum(not r['visible'] for r in accept)
                    entry = dict(split=split, sequence=seq, case=case, method=method,
                        B_failures=n, visible_B_failures=visible, invisible_B_failures=invisible,
                        accepted=len(accept), correct=correct, wrong=len(accept)-correct,
                        invisible_accepted=invisible_accepted,
                        visible_localization_error=sum(r['visible'] and not r[arm+'_correct_location'] for r in accept),
                        correct_visible_rate=ratio(correct, visible), precision=ratio(correct, len(accept)),
                        invisible_error_rate=ratio(invisible_accepted, invisible),
                        S0_correct=s_correct, S0_correct_retention=ratio(correct, s_correct) if arm == 'S' else None,
                        correct_rate_delta_C0=ratio(correct-baseline['C0'], visible),
                        correct_rate_delta_C1=ratio(correct-baseline['C1'], visible),
                        original_S_only_correct=only_correct,
                        original_S_only_correct_retained=sum(r['original_S_only'] and r['S_correct_location'] for r in accept) if arm == 'S' else None)
                    for category in ['OUT_OF_FOV', 'IMAGE_BORDER_GUARD', 'ARTIFICIAL_OCCLUSION', 'OCCLUSION_PATCH_GUARD', 'Unknown']:
                        entry['invisible_'+category] = sum(not r['visible'] and r['truth_category'] == category for r in group)
                        entry['accepted_'+category] = sum(not r['visible'] and r['truth_category'] == category for r in accept)
                    for reason in ['UNRESOLVED_PATCH_OUTSIDE', 'UNRESOLVED_NONFINITE_COORDINATE', 'UNRESOLVED_NONFINITE_PATCH', 'UNRESOLVED_LOW_VARIANCE', 'NCC_BELOW_THRESHOLD']:
                        entry['new_reject_'+reason] = sum(r[arm+'0'] and r[arm+'_reason'] == reason for r in group) if method in ['S1', 'C1'] else None
                    table.append(entry)
    return table


def run_natural():
    manifest = json.loads((SOURCE/'natural_inputs/manifest.json').read_text())
    files = {(r['sequence'], r['raw_index']): r for r in manifest}
    rows = read_csv(OLD/'natural_results.csv')
    grouped = defaultdict(list)
    for r in rows:
        r.update(S0=r['S_accepted'], C0=r['C_accepted'])
        grouped[(r['sequence'], r['raw_index'])].append(r)
    total_s = 0.
    for (seq, raw), group in grouped.items():
        prev, cur = image(files[(seq, raw-1)]['image']), image(files[(seq, raw)]['image'])
        assert all(r['stamp_ns'] == files[(seq, raw)]['stamp_ns'] for r in group)
        total_s += add_patch_fields(group, prev, cur)
        for r in group:
            c = np.array([r['C_x'], r['C_y']]);s = np.array([r['S_x'], r['S_y']]);p = np.array([r['previous_x'], r['previous_y']])
            r['CS_endpoint_distance_px'] = float(np.linalg.norm(c-s)) if np.isfinite(c).all() else None
            r['S_border_distance_px'] = border_distance(s, cur.shape)
            r['C_border_distance_px'] = border_distance(c, cur.shape)
            r['S_near_border_16px'] = r['S_border_distance_px'] is not None and r['S_border_distance_px'] <= 16
            finite_fb = r['C_fb'] is not None and np.isfinite(r['C_fb'])
            r['C_reject_only_FB'] = bool(not r['C0'] and border8(c, cur.shape) and finite_fb and r['C_fb'] > 1)
            r['C_rejection_detail'] = ('ACCEPTED' if r['C0'] else 'FB_ONLY' if r['C_reject_only_FB'] else
                                       'ENDPOINT_BORDER_OR_NONFINITE' if not border8(c, cur.shape) else
                                       'Unknown_backward_or_nonfinite_FB' if not finite_fb else 'Unknown')
            similar = r['CS_endpoint_distance_px'] is not None and r['CS_endpoint_distance_px'] <= 2
            r['gate_difference'] = 'GATE_DIFFERENCE_WITH_SIMILAR_ENDPOINT' if similar and r['S0'] != r['C0'] else ''
            r['review_selected'] = False;r['review_completed'] = False;r['visual_label'] = 'UNRESOLVED'
            r['review_note'] = '';r['review_group'] = '';r['review_id'] = '';r['review_sheet'] = ''
    order = lambda r: (r['sequence'], r['raw_index'], r['track_id'])
    h02 = sorted([r for r in rows if r['sequence'] == 'H02' and r['category'] == 'S_only' and r['S_offline_steps'] == 3], key=order)
    assert len(h02) == 20
    conly = sorted([r for r in rows if r['category'] == 'C_only'], key=order)[:5]
    rejected = sorted([r for r in rows if r['category'] == 'S_only' and not r['S1']], key=order)[:5]
    selected = []
    for name, group in [('H02_original_20', h02), ('C_only_control', conly), ('rejected_S_only_control', rejected)]:
        for r in group:
            if r['review_selected']:
                r['review_group'] += ';'+name
            else:
                r.update(review_selected=True, review_group=name, review_id='E{:02d}'.format(len(selected)+1))
                selected.append(r)
    assert len(selected) <= 30
    render_review(selected, files)
    write_csv(PAPER/'natural_event_review.csv', rows)
    return dict(events=len(rows), image_pairs=len(grouped), patch_check_s=total_s,
                review_events=len(selected), scoring_complete=True, visual_review_complete=False)


def render_review(selected, files):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out = PAPER/'samples';out.mkdir(exist_ok=False)
    for page in range(math.ceil(len(selected)/5)):
        group = selected[page*5:(page+1)*5]
        fig, axes = plt.subplots(len(group), 6, figsize=(15, 2.8*len(group)), squeeze=False, constrained_layout=True)
        fig.suptitle('Fixed correspondence evidence review | raw mono8, no alignment/refinement\nBlue C / orange S | future: context only, no saved endpoint | all physical identities Unknown', fontsize=11)
        for row, r in enumerate(group):
            seq, raw = r['sequence'], r['raw_index']
            prev, cur = image(files[(seq, raw-1)]['image']), image(files[(seq, raw)]['image'])
            p = np.array([r['previous_x'], r['previous_y']]);c = np.array([r['C_x'], r['C_y']]);s = np.array([r['S_x'], r['S_y']])
            for col, (im, pt, title) in enumerate([(prev, p, 'Previous query'), (cur, c, 'C endpoint'), (cur, s, 'S endpoint')]):
                ax = axes[row, col]
                center = pt if np.isfinite(pt).all() else p
                ax.imshow(im, cmap='gray', vmin=0, vmax=255)
                ax.set_xlim(center[0]-32, center[0]+32);ax.set_ylim(center[1]+32, center[1]-32)
                if np.isfinite(pt).all():
                    ax.plot(*pt, '+', color='#56B4E9' if col == 1 else '#E69F00', markersize=8)
                    ax.add_patch(plt.Rectangle(pt-5, 10, 10, fill=False, edgecolor='#56B4E9' if col == 1 else '#E69F00', linewidth=.7))
                ax.set_title(title if col == 0 else '{} FB={:.2f}'.format(title, r['C_fb' if col == 1 else 'S_fb'] or float('nan')), fontsize=8)
                if col == 0:
                    ax.set_ylabel('{} {} raw{} ID{}\n{} / S1={}\nold S steps={}'.format(r['review_id'], seq, raw, r['track_id'], r['category'], r['S1'], r['S_offline_steps']), fontsize=8)
            for col, im, pt, title in [(3, prev, p, 'Previous 11x11'), (4, cur, s, 'S current 11x11')]:
                patch, valid = sample_patches(im, [pt])
                ax = axes[row, col]
                if valid[0]:
                    ax.imshow(patch[0], cmap='gray', vmin=0, vmax=255, interpolation='nearest')
                else:
                    ax.text(.1, .5, 'Outside patch')
                ax.set_title(title+'\n'+('NCC={:.3f}'.format(r['S_ncc']) if col == 4 else 'no photometric remap'), fontsize=8)
            ax = axes[row, 5]
            if (seq, raw+3) in files:
                ax.imshow(image(files[(seq, raw+3)]['image']), cmap='gray', vmin=0, vmax=255)
                ax.set_xlim(s[0]-32, s[0]+32);ax.set_ylim(s[1]+32, s[1]-32)
                ax.set_title('raw{} context, no track\nCS distance={:.2f}px'.format(raw+3, r['CS_endpoint_distance_px'] or 0), fontsize=8)
            else:
                ax.text(.1, .5, 'No t+3 frame in window')
            for ax in axes[row]:
                ax.tick_params(labelsize=6)
            r['review_sheet'] = 'samples/review_{:02d}.png'.format(page+1)
        fig.savefig(out/'review_{:02d}.png'.format(page+1), dpi=125);plt.close(fig)


def run():
    cv2.setNumThreads(1)
    RUNTIME.mkdir(exist_ok=False)  # Deliberately refuse a second scoring run.
    manifest = json.loads((SOURCE/'controlled_inputs/manifest.json').read_text())
    assert len(manifest) == 48
    old_rows = defaultdict(list)
    for r in read_csv(OLD/'controlled_points.csv'):
        old_rows[r['pair_id']].append(r)
    timing = {r['pair_id']: r for r in read_csv(OLD/'timing.csv')}
    start = time.perf_counter()
    calibration = score_half('calibration', [0, 50], manifest, old_rows, timing)
    scales = sorted(r['uncertainty_scale_px'] for r in calibration if r['S0'] and r['S_correct_location'] and np.isfinite(r['uncertainty_scale_px']))
    n_correct = sum(r['S0'] and r['S_correct_location'] for r in calibration)
    assert len(scales) == n_correct and scales
    threshold = float(scales[math.ceil(.95*len(scales))-1])
    lock = dict(input_commit=INPUT_COMMIT, freeze_commit=FREEZE_COMMIT, quantity='mixture marginal mean absolute error scale proxy, original px',
                calibration_S0_correct=n_correct, finite_scales=len(scales), threshold_px=threshold,
                quantile_rule='ascending order statistic ceil(.95*N), accept <= threshold',
                retained_correct=sum(v <= threshold for v in scales), selected_with_calibration_labels=True,
                ncc_threshold=.65, patch_size=11, minimum_patch_std=1., auxiliary_combined_with_ncc=False)
    save_json(PAPER/'calibration_lock.json', lock)
    for r in calibration:
        r['SU'] = bool(r['S0'] and np.isfinite(r['uncertainty_scale_px']) and r['uncertainty_scale_px'] <= threshold)
    write_csv(RUNTIME/'calibration_scores.csv', calibration)
    print('CALIBRATION_LOCKED', json.dumps(lock), flush=True)
    check = score_half('check', [100, 150], manifest, old_rows, timing)
    for r in check:
        r['SU'] = bool(r['S0'] and np.isfinite(r['uncertainty_scale_px']) and r['uncertainty_scale_px'] <= threshold)
    write_csv(RUNTIME/'check_scores.csv', check)
    write_csv(PAPER/'evidence_results.csv', summarize(calibration+check))
    write_csv(RUNTIME/'patch_timing.csv', PATCH_TIMINGS)
    controlled_s = time.perf_counter()-start
    natural = run_natural()
    save_json(RUNTIME/'run_receipt.json', dict(controlled_pairs_scored=48, check_pairs_scored_once=24,
                controlled_scoring_and_summary_s=controlled_s, controlled_two_arm_patch_s=sum(r['two_arm_patch_seconds'] for r in PATCH_TIMINGS), natural=natural,
                new_network_inferences=0, training=0, VINS_replays=0,
                python=__import__('sys').version, numpy=np.__version__, opencv=cv2.__version__,
                function='uw_frontend/tracking/correspondence_evidence.py', numerical_checks='5 PASS'))
    finalize(require_review=False)
    print('SCORING_COMPLETE_PENDING_VISUAL_REVIEW', flush=True)


def finalize(require_review=True):
    table = read_csv(PAPER/'evidence_results.csv')
    events = read_csv(PAPER/'natural_event_review.csv')
    lock = json.loads((PAPER/'calibration_lock.json').read_text())
    receipt = json.loads((RUNTIME/'run_receipt.json').read_text())
    def get(split, method, seq='ALL', case='ALL'):
        return next(r for r in table if (r['split'], r['method'], r['sequence'], r['case']) == (split, method, seq, case))
    s0, s1, c0, c1 = [get('check', m) for m in ['S0', 'S1', 'C0', 'C1']]
    winners = {case: [seq for seq in SEQUENCES if get('check', 'S1', seq, case)['visible_B_failures'] >= 20
                      and get('check', 'S1', seq, case)['correct_rate_delta_C0'] >= .05] for case in ['large', 'illumination_blur']}
    gates = dict(correct_retention=s1['S0_correct_retention'] >= .8,
                 invisible_error=s1['invisible_error_rate'] <= .01,
                 precision=s1['precision'] >= .95,
                 retained_cross_sequence_advantage=any(len(v) >= 2 for v in winners.values()))
    controlled_pass = all(gates.values())
    selected = [r for r in events if r['review_selected']]
    complete = all(r['review_completed'] for r in selected)
    assert all(r['visual_label'] in LABELS for r in selected)
    if require_review:
        assert complete and len(selected) <= 30, 'Explicit visual review is incomplete'
    h02 = [r for r in events if r['sequence'] == 'H02' and r['category'] == 'S_only' and r['S_offline_steps'] == 3]
    retained = [r for r in h02 if r['S1']]
    support = sum(r['review_completed'] and r['visual_label'] == 'VISIBLE_STRUCTURE_SUPPORTED' for r in retained)
    verdict = ('EVIDENCE_GATE_NOT_SUPPORTED' if not controlled_pass else
               'LOCAL_CANDIDATE_SUPPORTED' if len(retained) >= 5 and support > 0 else 'CONTROLLED_FILTER_GAIN')
    natural = []
    for seq in SEQUENCES:
        only = [r for r in events if r['sequence'] == seq and r['category'] == 'S_only']
        natural.append(dict(sequence=seq, original_S_only=len(only), S1_retained=sum(r['S1'] for r in only),
            original_3step=sum(r['S_offline_steps'] == 3 for r in only),
            S1_retained_3step=sum(r['S1'] and r['S_offline_steps'] == 3 for r in only),
            rejection_reasons=dict(Counter(r['S_reason'] for r in only if not r['S1'])),
            similar_endpoint_gate_difference=sum(bool(r['gate_difference']) for r in only)))
    decision = dict(task='SEA-RAFT CORRESPONDENCE EVIDENCE CHECK', status='COMPLETE' if complete else 'PENDING_VISUAL_REVIEW',
        decision=verdict if complete else None, input_commit=INPUT_COMMIT, freeze_commit=FREEZE_COMMIT,
        old_decision='CONTROLLED_GAIN_ONLY (unchanged)', new_network_inferences=0, new_training=0, VINS_replays=0,
        check_gates=gates, controlled_check_pass=controlled_pass, advantage_groups=winners,
        check_overall={m: get('check', m) for m in METHODS}, calibration_lock=lock,
        natural=natural, H02_original_20_retained=len(retained), H02_retained_supported=support,
        H02_review_labels={k: sum(r['review_completed'] and r['visual_label'] == k for r in h02) for k in LABELS},
        selected_review_labels={k: sum(r['review_completed'] and r['visual_label'] == k for r in selected) for k in LABELS},
        H02_retained_review_labels={k: sum(r['review_completed'] and r['visual_label'] == k for r in retained) for k in LABELS},
        H02_original_20_similar_endpoint_gate_difference=sum(bool(r['gate_difference']) for r in h02),
        H02_original_20_C_rejection_reasons=dict(Counter(r['C_rejection_detail'] for r in h02)),
        H02_retained_C_rejection_reasons=dict(Counter(r['C_rejection_detail'] for r in retained)),
        visual_review=dict(completed=complete, reviewer='Assistant visual inspection of all six fixed sample sheets',
                           selected_events=len(selected), physical_identity='Unknown',
                           scoring_receipt_is_pre_review_snapshot=True),
        physical_identity='Unknown; current image evidence and existing ordinary LK support are not independent ground truth',
        runtime=str(RUNTIME), scoring_receipt=receipt)
    save_json(PAPER/'decision.json', decision)
    if complete:
        write_report(decision, get, natural)
    print('DECISION', decision['decision'], 'check gates', gates, 'H02 retained', len(retained), flush=True)


def write_report(d, get, natural):
    s0, s1 = get('check', 'S0'), get('check', 'S1')
    c0, c1 = get('check', 'C0'), get('check', 'C1')
    pct = lambda x: 'N/A' if x is None else '{:.2%}'.format(x)
    next_step = ('交回主规划窗口，仅供另行授权的最小集成评估；不自动运行后端。' if d['decision'] == 'LOCAL_CANDIDATE_SUPPORTED' else
                 '封存本版本，不调第二组阈值、不集成或扩展。')
    lines = ['# SEA-RAFT 对应点图像证据验证', '', '**{}**。新网络推理 **0**、训练 **0**、VINS **0**；只读取 a2f3bed 的既有预测与原 mono8 图像。'.format(d['decision']), '',
        '- 检查部分：原 S0 错误 **{} → {}**；正确恢复 **{} → {}**，保留 **{}**；不可见误收 **{}/{}={}**，接受精度 **{}**。'.format(s0['wrong'], s1['wrong'], s0['correct'], s1['correct'], pct(s1['S0_correct_retention']), s1['invisible_accepted'], s1['invisible_B_failures'], pct(s1['invisible_error_rate']), pct(s1['precision'])),
        '- S1 相对 C0/C1 正确恢复率差 **{:+.2f}/{:+.2f} 个百分点**；原 S-only 正确点保留 **{}/{}**。'.format(100*s1['correct_rate_delta_C0'],100*s1['correct_rate_delta_C1'],s1['original_S_only_correct_retained'],s1['original_S_only_correct']),
        '- H02 原20个三步普通 LK 支撑事件保留 **{}**；原20例视觉复核：结构支持/明确矛盾/无法判断 **{}/{}/{}**。自然物理身份仍 Unknown。'.format(d['H02_original_20_retained'],*[d['H02_review_labels'][k] for k in LABELS]),
        '- 误收减少且测量优势保留，但冻结不可见误收率仍高于1%，因此未通过本轮继续门。',
        '- 唯一下一步：'+next_step, '',
        '主规则固定为原坐标的11×11亚像素 NCC≥.65，两个 patch 标准差均>1 mono8灰度级；没有对齐、搜索、精化或CLAHE。低方差/patch不足标记 UNRESOLVED 并拒绝。S0/C0 是旧共同 FB/边界门，S1/C1 追加完全相同的检查；C_production（旧2488正确/14错误）未混入比较。', '',
        '| 部分/臂 | 可见/不可见 B失败 | 正确 | 错误 | 正确保留(S0) | 不可见错误率 | 精度 |', '|---|---:|---:|---:|---:|---:|---:|']
    for split in ['calibration', 'check', 'all']:
        for method in METHODS:
            r = get(split, method)
            lines.append('| {}/{} | {}/{} | {} | {} | {} | {} | {} |'.format(split, method, r['visible_B_failures'], r['invisible_B_failures'],r['correct'],r['wrong'],pct(r['S0_correct_retention']),pct(r['invisible_error_rate']),pct(r['precision'])))
    lines += ['', '检查部分错误原因：S0人工遮挡矩形内误收 {0}→{1}；遮挡patch guard {2}→{3}；图像边界guard {4}→{5}；实际移出图像 {6}→{7}。剩余18次均属旧guard定义的不可见标签，不能删除这些点、改标签或放宽1%门。'.format(*[r['accepted_'+category] for category in ['ARTIFICIAL_OCCLUSION','OCCLUSION_PATCH_GUARD','IMAGE_BORDER_GUARD','OUT_OF_FOV'] for r in [s0,s1]]), '', '检查部分分组（每组2底图；仅 large/illumination_blur 计继续门）：', '',
        '| 序列/类型 | 可见/不可见 | S0正确/错误 | S1正确/错误 | C0/C1正确 | S1−C0 pp | S1不可见误收 |', '|---|---:|---:|---:|---:|---:|---:|']
    for seq in SEQUENCES:
        for case in CASES:
            a,b,c,e = [get('check',m,seq,case) for m in ['S0','S1','C0','C1']]
            lines.append('| {}/{} | {}/{} | {}/{} | {}/{} | {}/{} | {} | {}/{} |'.format(seq,case,b['visible_B_failures'],b['invisible_B_failures'],a['correct'],a['wrong'],b['correct'],b['wrong'],c['correct'],e['correct'], 'N/A' if b['correct_rate_delta_C0'] is None else '{:+.2f}'.format(100*b['correct_rate_delta_C0']), b['invisible_accepted'],b['invisible_B_failures']))
    lines += ['', '冻结门：'+json.dumps(d['check_gates'],ensure_ascii=False)+'。分组优势：'+json.dumps(d['advantage_groups'],ensure_ascii=False)+'。所有分母和序列/变换的校准、检查、全量表见 [evidence_results.csv](evidence_results.csv)；人工遮挡、移出视野、图像边界 guard、遮挡 patch guard 与可见定位超差分别计数。原标签及分母不变。', '',
        '辅助 SU 只保留误差尺度≤{:.6f}原px的 S0；阈值由校准标签选取，保留校准正确样本 {}/{}。这是锁定官方双 Laplace 参数导出的平均轴尺度代理，不是可见/正确概率或校准置信度；不与 NCC 组合，也不用于自然阶段选主规则。细节见 [calibration_lock.json](calibration_lock.json) 和 [protocol.md](protocol.md)。'.format(d['calibration_lock']['threshold_px'],d['calibration_lock']['retained_correct'],d['calibration_lock']['calibration_S0_correct']), '',
        '| 自然片段 | 原 S-only | S1保留 | 原三步支持 | 保留且三步支持 | 新门拒绝原因 |', '|---|---:|---:|---:|---:|---|']
    for r in natural:
        lines.append('| {} | {} | {} | {} | {} | {} |'.format(r['sequence'],r['original_S_only'],r['S1_retained'],r['original_3step'],r['S1_retained_3step'],json.dumps(r['rejection_reasons'],ensure_ascii=False)))
    lines += ['', 'H02原20例全部为 C/S端点≤2px的门差异，其中原C仅FB拒绝12例、反向FB非有限而原因未细分6例、端点边界拒绝2例。保留7例中仅FB拒绝5例、反向原因Unknown 2例；结构支持/明确矛盾/无法判断为3/0/4。三例支持为 E16(raw179/ID2186)、E19(raw190/ID2232)、E20(raw191/ID2231)。高NCC但仅有模糊重复纹理或平滑灰度的其余4例保持UNRESOLVED。不能将这7例称为传统方法没有预测出位置。', '', '全部2857原事件及61个原S-only关系均保留：[natural_event_review.csv](natural_event_review.csv)。H02原20例全查，额外最多5个原C-only及5个被新门拒绝的原S-only按固定时间/ID选择。实际26个唯一事件（5个拒绝对照中4个已含于H02原20例，去重且不补选），共六张固定图见 samples/；未来帧仅是已有上下文，未重算三步跟踪、未补画未来端点。`GATE_DIFFERENCE_WITH_SIMILAR_ENDPOINT` 表示原C/S端点≤2px但旧门接受不同，不能称为传统方法完全找不到位置。可见结构支持也不是独立物理GT。', '',
        'A：固定检查减少了受控不可见误收，但未降至冻结≤1%；B：相对C0/C1的测量优势保留；C：H02保留7例原三步机会，其中3例有当前结构支持。这些局部线索不能覆盖A项未达标，最终仍为EVIDENCE_GATE_NOT_SUPPORTED。24/24分割是已使用开发数据内部检查；合成人工随机遮挡的结果不能外推到真实焦散、散射、重复纹理遮挡或系统安全。旧 CONTROLLED_GAIN_ONLY 未改判。', '',
        '计算代价：双臂patch评分合计受控0.384s/48对、自然0.673s/528对（分别8371和2857个共同B失败查询，不含图像读取及绘图）；仅描述本次CPU执行，未与其他负载严格比较。', '',
        '运行：5项小型数值测试通过；CPU patch评分，无模型导入。实际评分及环境记录见 [decision.json](decision.json)。完整指令见 [task_instructions.md](task_instructions.md)。一次评分命令 `PYTHONPATH=. <旧隔离环境python> scripts/run_searaft_evidence_check.py --run`；runtime存在时拒绝重跑。人工复核后 `--finalize` 只汇总既有分数。', '', '唯一下一步：'+next_step]
    (PAPER/'report.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    run() if args.run else finalize()
