#!/usr/bin/env python3
"""Post-hoc birth-only ablation of saved observations. NumPy only; no model calls.

Run from the worktree root. Inputs are the original run's cache metadata,
trajectory arrays and saved evaluation observations. Outputs refuse overwrite.
Missing validation predictions stay missing; scalar validation scores cannot
reconstruct observation-level predictions. No patch bank or checkpoint is loaded.
"""
import argparse
import csv
import json
from pathlib import Path
import numpy as np

ARMS = ['B', 'P', 'T', 'P-anchor', 'T-anchor']
BASE = 'cd615f039d7e7daa75ab5cc1b217283846d86dc8'
FIELDS = ['id', 'frame', 'sequence', 'age', 'baseline', 'truth',
          'label_valid', 'patch_valid', 'q', 'sigma']


def read_cache(path):
    with np.load(path, allow_pickle=False) as src:
        data = {key: src[key] for key in FIELDS}
    return data


def lineage(data):
    """Use complete B history and recorded tracker age, never truth/validity."""
    seq, ids, frame, age = (data[k] for k in ['sequence', 'id', 'frame', 'age'])
    assert all(np.issubdtype(x.dtype, np.integer) for x in [ids, frame, age])
    assert np.all(age >= 0)
    order = np.lexsort((frame, ids, seq))
    same = (seq[order][1:] == seq[order][:-1]) & (ids[order][1:] == ids[order][:-1])
    birth_frame = frame - age  # cache stores tracker.ages-1, incremented per frame
    assert np.all(birth_frame[order][1:][same] == birth_frame[order][:-1][same])
    assert np.all(np.diff(frame[order])[same] > 0), 'duplicate/nonincreasing ID frame'
    first = order[np.r_[True, ~same]]
    truncated = int(np.sum(frame[first] > birth_frame[first]))
    birth = frame == birth_frame
    assert int(birth.sum()) + truncated == len(first)
    consecutive = same & (np.diff(frame[order]) == 1)
    pairs = np.column_stack([order[:-1][consecutive], order[1:][consecutive]])
    return birth, pairs, dict(rows=len(frame), tracks=len(first),
                             actual_birth_rows=int(birth.sum()), left_truncated_tracks=truncated)


def stats(values, prefix):
    if not len(values):
        return {}
    return {prefix + key: float(value) for key, value in zip(
        ['mean_px', 'median_px', 'p90_px', 'p95_px', 'sum_px'],
        [np.mean(values), *np.quantile(values, [.5, .9, .95]), np.sum(values, dtype=np.float64)])}


def saved_predictions(folder, data):
    """Names are the original evaluator's observed output contract, not guesses."""
    out = {'B': (data['baseline'].copy(), np.zeros_like(data['baseline']))}
    if folder is None:
        return out
    for arm in ['B', 'P', 'T']:
        path = folder / (arm + '_observations.npz')
        with np.load(path, allow_pickle=False) as src:
            for key in ['id', 'frame', 'sequence', 'q', 'sigma']:
                assert np.array_equal(src[key], data[key]), (arm, key)
            pixel, delta = src['pixel'], src['delta']
            assert np.array_equal(pixel, data['baseline'] + delta)
            assert np.isfinite(delta).all() and np.all(abs(delta) <= 2)
            assert np.all(delta[~data['patch_valid']] == 0)
            if arm == 'B':
                assert np.all(delta == 0)
            out[arm] = (pixel, delta)
    return out


def measure(role, data, predictions, birth, pairs, cache_path, prediction_dir):
    valid = data['label_valid']
    assert np.isfinite(data['truth'][valid]).all()
    pairs = pairs[valid[pairs].all(axis=1)]
    for arm in ['P', 'T']:
        if arm in predictions:
            pixel, delta = [x.copy() for x in predictions[arm]]
            delta[birth] = 0
            pixel[birth] = data['baseline'][birth]
            assert np.array_equal(pixel[~birth], predictions[arm][0][~birth])
            assert np.array_equal(delta[~birth], predictions[arm][1][~birth])
            predictions[arm + '-anchor'] = (pixel, delta)
    groups = [('all', np.ones(len(birth), bool)), ('birth', birth), ('nonbirth', ~birth)]
    # Original windows start at 0; retain every original 100-frame block.
    for start in range(0, int(data['frame'].max()) + 1, 100):
        groups.append((f'block_{start}:{start+100}', (data['frame'] >= start) & (data['frame'] < start+100)))
    pairgroups = [('temporal_all', np.ones(len(pairs), bool)),
                  ('temporal_birth_next', birth[pairs[:, 0]]),
                  ('temporal_nonbirth_nonbirth', ~birth[pairs[:, 0]] & ~birth[pairs[:, 1]])]
    assert sum(int(mask.sum()) for _, mask in pairgroups[1:]) == len(pairs)
    rows = []
    for arm in ARMS:
        available = arm in predictions
        error = predictions[arm][0] - data['truth'] if available else None
        source = str(cache_path) if arm == 'B' else (
            str(prediction_dir / (arm.split('-')[0] + '_observations.npz')) if prediction_dir else
            'Not saved: original training/ contains checkpoint, curve and summary only')
        common = dict(role=role, sequence=str(data['sequence'][0]), arm=arm,
                      status='COMPUTED' if available else 'MISSING_PREDICTIONS', source=source)
        for name, query in groups:
            v = query & valid
            row = dict(common, group=name, observations=int(query.sum()), valid_labels=int(v.sum()),
                       valid_tracks=len(np.unique(data['id'][v])))
            if available:
                epe = np.linalg.norm(error[v], axis=1)
                delta_norm = np.linalg.norm(predictions[arm][1][query], axis=1)
                row.update(stats(epe, 'epe_'))
                row.update(stats(delta_norm, 'correction_all_'))
                row.update(over_1px_ratio=float(np.mean(epe > 1)), over_2px_ratio=float(np.mean(epe > 2)))
                row['zero_correction_ratio_all'] = float(np.mean(delta_norm == 0))
            rows.append(row)
        for name, query in pairgroups:
            row = dict(common, group=name, temporal_pairs=int(query.sum()))
            if available:
                change = np.linalg.norm(error[pairs[:, 1]] - error[pairs[:, 0]], axis=1)
                row.update(stats(change[query], 'temporal_'))
            rows.append(row)
    return rows


def get(rows, role, arm, group):
    return next(r for r in rows if r['role'] == role and r['arm'] == arm and r['group'] == group)


def gates(rows, suffix):
    b, p, t = [get(rows, 'test', arm, 'all') for arm in ['B', 'P'+suffix, 'T'+suffix]]
    pp, tp = [get(rows, 'test', arm+suffix, 'temporal_all') for arm in ['P', 'T']]
    blockb = [r for r in rows if r['role'] == 'test' and r['arm'] == 'B' and r['group'].startswith('block_')]
    blockt = [get(rows, 'test', 'T'+suffix, r['group']) for r in blockb]
    return dict(common_support=b['valid_tracks'] >= 100 and all(r['valid_labels'] >= 100 for r in blockb),
                t_vs_b_p95_20pct=t['epe_p95_px'] <= .8*b['epe_p95_px'],
                t_vs_b_over2_no_increase=t['over_2px_ratio'] <= b['over_2px_ratio'],
                t_vs_p_temporal_p95_5pct=tp['temporal_p95_px'] <= .95*pp['temporal_p95_px'],
                t_vs_p_epe_p95_no_increase=t['epe_p95_px'] <= p['epe_p95_px'],
                all_fixed_blocks=all(t['epe_p95_px'] <= 1.05*b['epe_p95_px'] and
                                     t['over_2px_ratio']-b['over_2px_ratio'] <= .01 for b, t in zip(blockb, blockt)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assert not (args.output/'comparison.csv').exists() and not (args.output/'report.md').exists(), 'refuse overwrite'
    frozen = json.loads((args.root/'evaluation/evaluation.json').read_text())
    assert frozen['decision'] == 'NO_TEMPORAL_REFINEMENT_GAIN'
    rows, births = [], {}
    for role in ['train', 'validation', 'test']:
        path = args.root/'cache'/(role+'.npz')
        meta = json.loads(path.with_suffix('.json').read_text())
        assert meta['role'] == role
        data = read_cache(path)
        birth, pairs, births[role] = lineage(data)
        if role == 'train':
            continue  # identity completeness only; no new training metric/search
        folder = args.root/'evaluation' if role == 'test' else None
        predictions = saved_predictions(folder, data)
        rows.extend(measure(role, data, predictions, birth, pairs, path, folder))
    for arm in ['B', 'P', 'T']:
        r = get(rows, 'test', arm, 'all')
        old = frozen['test_summary'][arm]
        for key in ['epe_median_px', 'epe_p90_px', 'epe_p95_px', 'over_1px_ratio', 'over_2px_ratio']:
            assert r[key] == old[key], (arm, key, 'original metric mismatch')
        assert get(rows, 'test', arm, 'temporal_all')['temporal_p95_px'] == old['temporal_error_change_p95_px']
        if arm != 'B':
            for group, key in [('nonbirth', 'epe_p95_px'), ('temporal_nonbirth_nonbirth', 'temporal_p95_px')]:
                assert get(rows, 'test', arm, group)[key] == get(rows, 'test', arm+'-anchor', group)[key]
    original, anchor = gates(rows, ''), gates(rows, '-anchor')
    assert original == frozen['gates']
    for label, values in [('original', original), ('anchor', anchor)]:
        for name, passed in values.items():
            rows.append(dict(role='test', group='gate_'+name, arm=label, status='PASS' if passed else 'FAIL'))
    # Full requested validation+test decomposition cannot be reconstructed from scalars.
    outcome = 'DIAGNOSTIC_UNRESOLVED'  # Frozen run never persisted validation predictions.
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (args.output/'comparison.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    report = [f'# 出生参考消融：{outcome}', '',
              f'基于 `{BASE}` 的事后开发诊断；原NO_TEMPORAL_REFINEMENT_GAIN及MIMIR SUPERVISION_UNAVAILABLE不变。更新/网络推理/VINS/下载：**0/0/0/0**。', '',
              '**缺失边界**：`training/`只存P/T_best.pt、P/T_curve.csv、P/T_summary.json，没有验证逐观测预测；`evaluation/`三预测仅含测试序列。验证P/T及anchor均标MISSING_PREDICTIONS，不能用验证p95反推。', '',
              '**唯一干预**：按完整B历史的(sequence,id,frame−age)确定出生，仅出生delta=0；非出生预测、真值、patch有效性及观测集合不变。三分割左截断均0。测试出生111,694条（84,061有效），非出生82,730有效；验证出生49,491条（19,282有效）。', '',
              '测试endofworld/Easy/P000[0,600)，同一209,862观测/166,791有效标签；验证carwelding/Easy/P001[0,600)仅B可分解。完整数值见[comparison.csv](comparison.csv)。', '',
              '| 测试臂 | EPE median/p90/p95 px | >1/>2 % | 非出生p95 | 完整时序p95 |',
              '|---|---|---|---:|---:|']
    for arm in ARMS:
        r = get(rows, 'test', arm, 'all')
        non = get(rows, 'test', arm, 'nonbirth')
        tmp = get(rows, 'test', arm, 'temporal_all')
        report.append(f"| {arm} | {r['epe_median_px']:.4f}/{r['epe_p90_px']:.4f}/{r['epe_p95_px']:.4f} | {100*r['over_1px_ratio']:.3f}/{100*r['over_2px_ratio']:.3f} | {non['epe_p95_px']:.4f} | {tmp['temporal_p95_px']:.4f} |")
    report += ['', '**出生贡献**：P/T全部出生修正median/p95为0.1567/0.6930、0.1742/0.6563px；有效出生引入误差median/p95为0.1784/0.7205、0.1966/0.6729px，anchor归零。P/T总EPE和减少19.71%/20.01%，完全来自出生恢复；整体p95仅降0.0200/0.0075px。分位数不可加，不能称跟踪能力提升。',
               '**非出生已有局部尾部收益，但非稳定净收益**：T/B p95降低6.95%，median却0.3960→0.5019、mean 0.9425→1.0005px，>1比例20.066%→22.739%；两端非出生时序也劣于B。T/P该时序p95仅降低1.55%，anchor完整时序T/P仅降低2.34%<5%。', '',
               '| 时序变化p95 px | 对数 | B | P | T | P-anchor | T-anchor |',
               '|---|---:|---:|---:|---:|---:|---:|']
    for group, label in [('temporal_birth_next','出生→相邻有效帧'), ('temporal_nonbirth_nonbirth','两端非出生')]:
        rr = [get(rows, 'test', a, group) for a in ARMS]
        report.append('| '+label+' | '+str(rr[0]['temporal_pairs'])+' | '+' | '.join(f"{r['temporal_p95_px']:.4f}" for r in rr)+' |')
    report += ['', '| 原冻结测试门 | 原/anchor |', '|---|---|']
    labels = ['≥100有效轨迹、每块≥100查询','T/B总体p95下降≥20%','T/B >2比例不增',
              'T/P完整时序p95下降≥5%','T/P坐标p95不增','各100帧块p95比≤1.05且>2增量≤.01']
    for label, name in zip(labels, anchor):
        report.append(f"| {label} | {'PASS' if original[name] else 'FAIL'}/{'PASS' if anchor[name] else 'FAIL'} |")
    report += ['', '**六块全部保留**；[500,600) B/P/T/P-anchor/T-anchor p95=1.0449/1.3743/1.3236/1.3625/1.3173px，T-anchor仍退化26.07%。出生置零还增大出生→下一帧的误差变化；不是所有退化都由出生引起。',
               '**唯一决定**：验证预测缺失，完整请求DIAGNOSTIC_UNRESOLVED；可计算的测试侧已表明出生修复仍不满足原门。结束此次计算，不自动补推理/重训/VINS，不产生水下或独立泛化结论。', '',
               '**读取文件**：R=`'+str(args.root)+'`；`cache/{train,validation,test}.{npz,json}`的轨迹/标签列、`evaluation/evaluation.json`和`evaluation/{B,P,T}_observations.npz`。出生识别不读取GT；原B/P/T指标及六项门重算一致。复现：在此目录执行`python3 analyze.py --root R`（R替换为上述路径，输出拒绝覆盖）。']
    with (args.output/'report.md').open('x') as f:
        f.write('\n'.join(report)+'\n')
    print(json.dumps(dict(decision=outcome, births=births, original_gates=original, anchor_gates=anchor)))


if __name__ == '__main__':
    main()
