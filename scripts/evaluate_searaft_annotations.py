#!/usr/bin/env python3
"""Evaluate saved predictions against a sealed human reference CSV; stdlib only.

No inference imports. All output goes to a new directory. The reference snapshot
is written before opening the predictions. Partial annotation never yields a
complete experiment decision. Radius u is a bound, not a confidence interval.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'papers/frontend_searaft_real_correspondence_v1'
TOL = 2.0
STATES = {'PENDING', 'VISIBLE_CORRESPONDENCE', 'OCCLUDED_OR_OUT_OF_VIEW', 'AMBIGUOUS'}


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def key(row):
    return row['pair_id'], row['query_id']


def indexed(rows):
    out = {key(r): r for r in rows}
    if len(out) != len(rows):
        raise ValueError('Duplicate pair_id + query_id')
    return out


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def truth(value):
    v = str(value).lower()
    if v not in ('true', 'false'):
        raise ValueError('Boolean must be True/False: ' + str(value))
    return v == 'true'


def error_interval(px, py, ax, ay, u):
    if px is None or py is None:
        return '', '', '', 'NO_FINITE_PREDICTION'
    e = math.hypot(px - ax, py - ay)
    lo, hi = max(0.0, e - u), e + u
    status = 'WITHIN_2PX' if hi <= TOL else ('OUTSIDE_2PX' if lo > TOL else 'UNCERTAIN_2PX')
    return e, lo, hi, status


def validate_references(refs, manifest):
    lookup = indexed(refs)
    if len(refs) != 92 or set(lookup) != {key(m) for m in manifest}:
        raise ValueError('Reference must preserve all 92 fixed joint keys; use PENDING for unprocessed items.')
    for m in manifest:
        r = lookup[key(m)]
        for f in ('sequence', 'source_raw', 'target_raw', 'gap_frames'):
            if r.get(f) != m[f]:
                raise ValueError('Reference identity differs: {} {}'.format(key(m), f))
        for f in ('source_x', 'source_y'):
            if number(r.get(f)) is None or abs(float(r[f]) - float(m[f])) > 1e-6:
                raise ValueError('Source coordinate changed: ' + str(key(m)))
        status = r.get('reference_status')
        if status not in STATES:
            raise ValueError('Unknown reference status: ' + str(status))
        confirmed = truth(r.get('human_confirmed'))
        if status == 'VISIBLE_CORRESPONDENCE':
            x, y, u = (number(r.get(f)) for f in ('target_x', 'target_y', 'uncertainty_px'))
            if x is None or y is None or u is None or u <= 0 or not (0 <= x <= int(m['width'])-1 and 0 <= y <= int(m['height'])-1):
                raise ValueError('Visible annotation needs in-image coordinates and positive finite uncertainty: ' + str(key(m)))
        elif any(r.get(f, '') != '' for f in ('target_x', 'target_y', 'uncertainty_px')):
            raise ValueError('Nonvisible/pending reference must not contain target coordinates: ' + str(key(m)))
        if confirmed:
            kind = r.get('annotation_kind', '').lower()
            if status == 'PENDING' or not r.get('annotator_identity', '').strip() or not kind.startswith(('human', 'manual')) or any(s in kind for s in ('proposal', 'model', 'assistant')):
                raise ValueError('Confirmed reference requires explicit human identity and human/manual annotation kind: ' + str(key(m)))
    return lookup


def evaluate_row(m, ref, pred):
    confirmed = truth(ref['human_confirmed'])
    state = ref['reference_status'] if confirmed else 'PENDING'
    row = {f: m[f] for f in ['pair_id', 'query_id', 'sequence', 'source_raw', 'target_raw', 'gap_frames', 'delta_time_s', 'source_x', 'source_y']}
    row.update(reference_status=state, submitted_status=ref['reference_status'], human_confirmed=confirmed,
               target_x=ref.get('target_x', ''), target_y=ref.get('target_y', ''), uncertainty_px=ref.get('uncertainty_px', ''),
               annotator_identity=ref.get('annotator_identity', ''), annotation_kind=ref.get('annotation_kind', ''),
               annotation_conditions=ref.get('annotation_conditions', '') or 'Unknown', human_confirmed_at=ref.get('human_confirmed_at', ''), notes=ref.get('notes', ''))
    for arm in ('C0', 'S0', 'C1', 'S1'):
        row[arm] = truth(pred[arm])
    for method in ('C', 'S'):
        x, y = number(pred[method+'_x']), number(pred[method+'_y'])
        row[method+'_x'], row[method+'_y'] = pred[method+'_x'], pred[method+'_y']
        if (row[method+'0'] or row[method+'1']) and (x is None or y is None):
            raise ValueError('Accepted prediction has nonfinite endpoint: ' + str(key(m)))
        values = ('', '', '', 'NOT_EVALUATED')
        if state == 'VISIBLE_CORRESPONDENCE':
            values = error_interval(x, y, float(ref['target_x']), float(ref['target_y']), float(ref['uncertainty_px']))
        for name, value in zip(('error_px', 'error_lower_px', 'error_upper_px', 'tolerance_status'), values):
            row[method+'_'+name] = value
    coords = [number(pred[k]) for k in ('C_x', 'C_y', 'S_x', 'S_y')]
    distance = math.hypot(coords[0]-coords[2], coords[1]-coords[3]) if all(v is not None for v in coords) else ''
    near_gate = distance != '' and distance <= TOL and row['C1'] != row['S1']
    row.update(CS_endpoint_distance_px=distance, similar_endpoint_gate_difference=near_gate,
               C_minus_S_error_px='', C_minus_S_error_lower_px='', C_minus_S_error_upper_px='', accuracy_order='NOT_EVALUATED')
    if row['C_error_px'] != '' and row['S_error_px'] != '':
        lo = row['C_error_lower_px'] - row['S_error_upper_px']
        hi = row['C_error_upper_px'] - row['S_error_lower_px']
        row.update(C_minus_S_error_px=row['C_error_px']-row['S_error_px'], C_minus_S_error_lower_px=lo, C_minus_S_error_upper_px=hi,
                   accuracy_order='S_MORE_ACCURATE' if lo > 0 else ('C_MORE_ACCURATE' if hi < 0 else 'UNRESOLVED_WITHIN_ANNOTATION_UNCERTAINTY'))
    for method, other in [('S', 'C'), ('C', 'S')]:
        if state != 'VISIBLE_CORRESPONDENCE':
            row[method+'1_unique_correct'] = ''
            row[method+'1_positional_increment'] = ''
            continue
        correct = row[method+'1'] and row[method+'_tolerance_status'] == 'WITHIN_2PX'
        # Unique usable correct acceptance is distinct from a displacement gain.
        other_absent_or_wrong = not row[other+'1'] or row[other+'_tolerance_status'] in ('OUTSIDE_2PX', 'NO_FINITE_PREDICTION')
        row[method+'1_unique_correct'] = correct and other_absent_or_wrong
        row[method+'1_positional_increment'] = correct and not near_gate and (
            row['accuracy_order'] == method+'_MORE_ACCURATE' or
            row[other+'_tolerance_status'] == 'NO_FINITE_PREDICTION')
    return row


def quantile(values, q):
    if not values:
        return ''
    a = sorted(values)
    pos = (len(a)-1)*q
    i = int(pos)
    return a[i] + (a[min(i+1, len(a)-1)]-a[i])*(pos-i)


def summaries(rows):
    groups = [('overall', 'ALL', rows)]
    groups += [('sequence', s, [r for r in rows if r['sequence'] == s]) for s in ('A02', 'A08', 'H02')]
    groups += [('gap', 't+'+str(g), [r for r in rows if int(r['gap_frames']) == g]) for g in (1, 10)]
    groups += [('sequence_gap', s+'_t+'+str(g), [r for r in rows if r['sequence'] == s and int(r['gap_frames']) == g]) for s in ('A02', 'A08', 'H02') for g in (1, 10)]
    groups += [('pair', p, [r for r in rows if r['pair_id'] == p]) for p in dict.fromkeys(r['pair_id'] for r in rows)]
    output = []
    for level, name, rs in groups:
        visible = [r for r in rs if r['reference_status'] == 'VISIBLE_CORRESPONDENCE']
        invisible = [r for r in rs if r['reference_status'] == 'OCCLUDED_OR_OUT_OF_VIEW']
        pending = sum(r['reference_status'] == 'PENDING' for r in rs)
        s = dict(level=level, group=name, status='PARTIAL' if pending and pending < len(rs) else ('REFERENCE_PENDING' if pending else 'ANNOTATION_COMPLETE'),
                 queries=len(rs), image_pairs=len({r['pair_id'] for r in rs}), human_visible=len(visible), human_invisible=len(invisible),
                 human_ambiguous=sum(r['reference_status']=='AMBIGUOUS' for r in rs), pending=pending)
        for method in ('C', 'S'):
            errors = [r[method+'_error_px'] for r in visible if r[method+'_error_px'] != '']
            s[method+'_raw_finite_visible'] = len(errors)
            for suffix in ('', '_lower', '_upper'):
                values = [r[method+'_error'+suffix+'_px'] for r in visible if r[method+'_error_px'] != '']
                s[method+'_raw_error'+suffix+'_median_px'] = quantile(values, .5)
                s[method+'_raw_error'+suffix+'_p95_px'] = quantile(values, .95)
            for label, suffix in [('WITHIN_2PX','within'), ('OUTSIDE_2PX','outside'), ('UNCERTAIN_2PX','uncertain'), ('NO_FINITE_PREDICTION','missing')]:
                s[method+'_raw_'+suffix] = sum(r[method+'_tolerance_status']==label for r in visible)
            s[method+'_within_2px_fraction_lower_visible'] = s[method+'_raw_within']/len(visible) if visible else ''
            s[method+'_within_2px_fraction_upper_visible'] = (s[method+'_raw_within']+s[method+'_raw_uncertain'])/len(visible) if visible else ''
        for arm in ('C0','S0','C1','S1'):
            method = arm[0]
            s[arm+'_accepted_all'] = sum(r[arm] for r in rs)
            s[arm+'_coverage_all'] = s[arm+'_accepted_all']/len(rs)
            s[arm+'_accepted_visible'] = sum(r[arm] for r in visible)
            for label, suffix in [('WITHIN_2PX','correct_accepted'), ('OUTSIDE_2PX','wrong_visible_accepted'), ('UNCERTAIN_2PX','uncertain_visible_accepted')]:
                s[arm+'_'+suffix] = sum(r[arm] and r[method+'_tolerance_status']==label for r in visible) if visible else ''
            s[arm+'_invisible_false_accepted'] = sum(r[arm] for r in invisible) if invisible else ''
            s[arm+'_accepted_ambiguous'] = sum(r[arm] and r['reference_status']=='AMBIGUOUS' for r in rs)
            s[arm+'_accepted_pending'] = sum(r[arm] and r['reference_status']=='PENDING' for r in rs)
        for f in ('S1_unique_correct','C1_unique_correct','S1_positional_increment','C1_positional_increment'):
            s[f] = sum(r[f] for r in visible) if visible else ''
        s['similar_endpoint_gate_difference'] = sum(r['similar_endpoint_gate_difference'] for r in rs)
        output.append(s)
    return output


def decision(rows, overall):
    n = overall['queries'] - overall['pending']
    # Never promote results from an early prefix of the fixed manifest.
    if n < 92:
        return dict(status='PARTIAL' if n else 'REFERENCE_PENDING', decision='REFERENCE_PENDING', reason='Only {}/92 items have explicit human confirmation; no complete experiment conclusion.'.format(n))
    if not overall['human_visible']:
        return dict(status='REFERENCE_INSUFFICIENT', decision='REFERENCE_PENDING', reason='No confirmed visible correspondences support endpoint accuracy evaluation.')
    if overall['S1_positional_increment']:
        return dict(status='ANNOTATION_COMPLETE', decision='LOCAL_OR_MIXED_GAIN', reason='Conservative local evidence on these fixed development pairs only. Positional increments exclude close-endpoint gate-only differences; inspect losses and uncertainty. No automatic integration.')
    # Inconclusive annotations at potential accepted measurements cannot certify no gain.
    unresolved = any((r['S1'] or r['C1']) and (r['reference_status']=='AMBIGUOUS' or
        (r['reference_status']=='VISIBLE_CORRESPONDENCE' and (r['S_tolerance_status']=='UNCERTAIN_2PX' or r['C_tolerance_status']=='UNCERTAIN_2PX'))) for r in rows)
    if unresolved:
        return dict(status='REFERENCE_INSUFFICIENT', decision='REFERENCE_PENDING', reason='No supported positional gain yet; relevant ambiguous/uncertain references remain. No forced accuracy winner.')
    return dict(status='ANNOTATION_COMPLETE', decision='NO_REAL_INCREMENT', reason='No supported extra positional measurement on the fixed evaluable correspondences. Gate-only unique accepts remain separate; unevaluable rows do not establish safety.')


def run(reference, predictions, output):
    manifest = [r for r in read_csv(PAPER/'pair_query_manifest.csv') if r['cell_status']=='SELECTED']
    raw = Path(reference).read_bytes()
    refs = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    refmap = validate_references(refs, manifest)
    # This is the boundary: seal the supplied human answers BEFORE opening predictions.
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output/'reference_snapshot.csv'
    snapshot.write_bytes(raw)
    stamp = dict(reference_source=str(Path(reference).resolve()), reference_sha256=hashlib.sha256(raw).hexdigest(),
                 snapshot_created_utc=datetime.now(timezone.utc).isoformat(), prediction_source=str(Path(predictions).resolve()),
                 frozen_contract_commit='26bc69edffa03da3bfb82f7408c4d384fa2d55ba', snapshot_before_prediction_read=True)
    (output/'reference_snapshot.json').write_text(json.dumps(stamp, indent=2)+'\n')
    preds = read_csv(predictions)
    predmap = indexed(preds)
    if len(preds)!=92 or set(predmap)!=set(refmap):
        raise ValueError('Prediction joint-key support differs from fixed 92 queries; snapshot retained.')
    for m in manifest:
        p = predmap[key(m)]
        for f in ('sequence','source_raw','target_raw','gap_frames','source_stamp_ns','target_stamp_ns'):
            if p[f] != m[f]:
                raise ValueError('Prediction identity mismatch: '+str(key(m)))
        for f in ('source_x','source_y'):
            if number(p[f]) is None or abs(float(p[f])-float(m[f]))>1e-6:
                raise ValueError('Prediction source coordinate mismatch: '+str(key(m)))
    rows = [evaluate_row(m, refmap[key(m)], predmap[key(m)]) for m in manifest]
    grouped = summaries(rows)
    result = decision(rows, grouped[0])
    result.update(reference_confirmed=92-grouped[0]['pending'], reference_pending=grouped[0]['pending'], queries=92,
                  threshold_px=TOL, radius_interpretation='Human localization uncertainty bound; not a 95% confidence interval.',
                  accuracy_difference='C/S interval separation required; overlapping ranges do not establish a winner.',
                  unique_correct_definition='Accepted and certainly within 2 px; the other arm has no accepted measurement or is certainly outside 2 px.',
                  positional_increment_definition='Certainly correct accepted point whose error range is below the other raw endpoint error range, or the other endpoint is missing; exclude close-endpoint gate-only differences. Both may be within tolerance: this is precision advantage, not unique correctness.',
                  old_reports_unchanged=True, auto_integration=False, reference_snapshot=stamp)
    write_csv(output/'per_query.csv', rows)
    write_csv(output/'comparison.csv', grouped)
    (output/'decision.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 人工参考与保存预测评价', '', '**{} / {}**'.format(result['status'],result['decision']), '', result['reason'], '',
             '完整分母为 92 项。仅人工确认可见项用于端点误差；不可见误收须有人确认；AMBIGUOUS 与 PENDING 均不当作 TIE、安全或算法失败。', '',
             '| 组 | 全部 | 可见 | 不可见 | 无法判断 | 待确认 | C1/S1 确定正确接受 | C1/S1 独有正确 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for g in grouped:
        if g['level'] in ('overall','sequence','gap','sequence_gap'):
            lines.append('| {} | {} | {} | {} | {} | {} | {}/{} | {}/{} |'.format(g['group'],g['queries'],g['human_visible'],g['human_invisible'],g['human_ambiguous'],g['pending'],g['C1_correct_accepted'],g['S1_correct_accepted'],g['C1_unique_correct'],g['S1_unique_correct']))
    lines += ['', '逐点误差、[max(0,e−u),e+u]、接受状态及 C−S 差异范围见 per_query.csv；原始中位/p95 及其保守范围、≤2 px 比例上下界和 C0/S0/C1/S1 错误接受见 comparison.csv。u 是人工定位范围，不是 95% 置信区间。', '',
              '精度差异范围跨零时不宣称谁更准。原端点≤2 px 且接受不同单列为门差异；独有正确接受不自动等于额外位移精度。', '',
              't+10 为人为降低取样频率条件。查询点彼此相关，不能视为独立场景或推断总体成功率。人工参考在读取预测前保存于 reference_snapshot.csv；后续修改须另存新快照并说明原因。', '',
              '当前状态不会覆盖旧 report/decision。PARTIAL 仅是已确认子集的描述，不能作完整结论。工具按上述保守规则给出局部或待确认决定；不自动提升为 REAL_MEASUREMENT_GAIN_SUPPORTED，不自动接入 VINS 或追加实验。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, default=PAPER/'predictions.csv')
    parser.add_argument('--output', type=Path, help='New directory; refuses overwrite. Default: timestamped annotation_evaluations subdirectory.')
    args = parser.parse_args()
    output = args.output or PAPER/'annotation_evaluations'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    result = run(args.annotations, args.predictions, output)
    print('{} / {}: {} human-confirmed, {} pending. {}'.format(result['status'],result['decision'],result['reference_confirmed'],result['reference_pending'],output/'report.md'))


if __name__ == '__main__':
    main()
