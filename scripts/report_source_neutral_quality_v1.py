#!/usr/bin/env python3
"""Evaluate the two prespecified contrasts; report every run and one decision."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from convert_source_neutral_quality_v1 import ROOT, PAPER, OLD, RUNTIME, SLUGS, sha
from run_source_neutral_quality_v1 import ARMS
from analyze_additive_budget_v1 import backend_stats, table, median_range


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def evaluate(window, arms, backend):
    name = 'all_three' if len(arms) == 3 else arms[0] + '_vs_' + arms[1]
    out = RUNTIME / 'evaluation' / window['run_slug'] / name
    targets = [(a, r) for a in arms for r in [1, 2, 3]]
    if any((window['run_slug'], a, r) not in backend for a, r in targets):
        return None, 'Not evaluated.'
    if any(backend[window['run_slug'], a, r]['runability'] != 'PASS' for a, r in targets):
        return None, 'INVALID_RUNABILITY'
    if not (out / 'evaluation_receipt.json').exists():
        assert not out.exists(), 'Unreceipted evaluation exists: ' + str(out)
        for p, h in json.loads((OLD / 'evaluation_lock.json').read_text()).items():
            assert sha(ROOT / p) == h
        command = [sys.executable, str(ROOT / 'scripts/evaluate_additive_budget_v1.py'),
                   '--reference-bag', window['baseline_bag'], '--reference-topic', '/aqualoc/colmap_gt',
                   '--evaluation-rate-hz', '1', '--max-reference-gap-s', '2.5',
                   '--max-estimate-gap-s', '.25', '--output-dir', str(out), '--run-evo']
        for arm, repeat in targets:
            target = RUNTIME / 'backend' / window['run_slug'] / arm / f'repeat{repeat}'
            alias = f'{arm}_r{repeat}'
            command += ['--arm', alias + '=' + str(target / 'vins_output/vio.csv'),
                        '--arm-config', alias + '=' + str(target / 'vins.yaml')]
        process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'evaluator.log').write_text(process.stdout)
        write_json(out / 'evaluation_receipt.json', dict(command=command, returncode=process.returncode,
                   artifacts={str(p): sha(p) for p in out.rglob('*') if p.is_file()}))
    receipt = json.loads((out / 'evaluation_receipt.json').read_text())
    for p, h in receipt['artifacts'].items():
        assert sha(p) == h, p
    if receipt['returncode']:
        return None, 'INVALID_COMMON_SUPPORT_OR_EVALUATOR'
    summary = json.loads((out / 'common_support_summary.json').read_text())
    cross = json.loads((out / 'evo_crosscheck.json').read_text())
    assert all(v['ape_abs_diff_m'] <= 1e-6 and v['rpe_abs_diff_m'] <= 1e-6
               for a in cross['arms'].values() for v in a.values())
    write_json(PAPER / 'receipts' / f'{window["run_slug"]}_{name}.json', dict(summary=summary, receipt=receipt))
    return (summary, 'PASS') if summary['support']['ape_valid'] and summary['support']['rpe_valid'] else (None, 'INVALID_COMMON_SUPPORT')


def comparison(summary, slug, proposed, baseline, status):
    row = dict(run_slug=slug, comparison=proposed + '_vs_' + baseline, status=status,
               common_support_artifact=str(RUNTIME / 'evaluation' / slug / (proposed + '_vs_' + baseline)))
    if not summary:
        return row
    ae, asp, alo, ahi = median_range(summary, proposed, 'fixed_se3_ape_rmse_m')
    be, bsp, blo, bhi = median_range(summary, baseline, 'fixed_se3_ape_rmse_m')
    ar, ars, arlo, arhi = median_range(summary, proposed, 'fixed_se3_rpe_rmse_m')
    br, brs, brlo, brhi = median_range(summary, baseline, 'fixed_se3_rpe_rmse_m')
    delta, rdelta, noise, rnoise = ae - be, ar - br, max(asp, bsp), max(ars, brs)
    gain = -delta >= max(.05 * be, .01) and -delta > noise
    loss = delta >= max(.05 * be, .01) and delta > noise
    guard = max(.05 * br, .005, rnoise)
    row.update(APE_neutral_m=ae, APE_reference_m=be, APE_neutral_min=alo, APE_neutral_max=ahi,
               APE_reference_min=blo, APE_reference_max=bhi, APE_delta_m=delta,
               APE_delta_pct=100 * delta / be if be else None,
               RPE_neutral_m=ar, RPE_reference_m=br, RPE_neutral_min=arlo, RPE_neutral_max=arhi,
               RPE_reference_min=brlo, RPE_reference_max=brhi, RPE_delta_m=rdelta,
               APE_repeat_range_threshold=noise, RPE_repeat_range_threshold=rnoise,
               practical='PRACTICAL_GAIN' if gain and rdelta <= guard else ('PRACTICAL_LOSS' if loss or rdelta > guard else 'SMALL_OR_UNCERTAIN'),
               severe_regression=delta > max(.1 * be, .01, noise) or rdelta > max(.1 * br, .005, rnoise),
               common_poses=summary['support'].get('common_count', 'see receipt'))
    return row


def main():
    plan = json.loads((PAPER / 'run_plan.json').read_text())
    result, backend, run_receipts = [], {}, []
    for slug in SLUGS:
        for arm in ARMS:
            for repeat in [1, 2, 3]:
                target = RUNTIME / 'backend' / slug / arm / f'repeat{repeat}'
                row = dict(run_slug=slug, arm=arm, repeat=repeat, status='Not evaluated.', run_dir=str(target))
                if (target / 'receipt.json').exists():
                    rec = json.loads((target / 'receipt.json').read_text())
                    check = json.loads((target / 'task_check.json').read_text())
                    row.update(status=rec['status'], source_commit=check['source_commit'],
                               severe_anomaly=check['severe_anomaly'], excursion_m=check['raw_motion']['excursion_m'],
                               received_per_ID_complete=check['received_per_ID_complete'])
                    if check['raw_motion']['finite']:
                        stats = backend_stats(target)
                        if check['severe_anomaly']:
                            stats['runability'] = 'FAIL'
                        backend[slug, arm, repeat] = stats
                        for key in ['runability', 'poses', 'trajectory_length_m', 'trajectory_coverage',
                                    'first_pose_delay_from_reference_start_s', 'initialization_count',
                                    'initialization_visual_imu_misalignment_count', 'reset_count_proxy',
                                    'failure_detection_count', 'received_KLT', 'received_candidate',
                                    'residual_candidate', 'wall_s', 'peak_node_rss_bytes']:
                            row[key] = stats.get(key, 'Unknown')
                    else:
                        row['runability'] = 'FAIL'
                        backend[slug, arm, repeat] = row
                    run_receipts.append(dict(receipt=rec, task_check=check))
                result.append(row)
    completed = sum(r['status'] != 'Not evaluated.' for r in result)
    stopped = (RUNTIME / 'stopped.json').exists()
    comparisons = []
    for window in plan['windows']:
        slug = window['run_slug']
        for arms in [ARMS, ['L-neutral', 'L-original'], ['L-neutral', 'B']]:
            summary, status = (None, 'EVALUATION_BLOCKED') if stopped else evaluate(window, arms, backend)
            if len(arms) == 3:
                for row in result:
                    if row['run_slug'] == slug:
                        row['all_three_common_support'] = status
                        if summary:
                            v = summary['arms'][f'{row["arm"]}_r{row["repeat"]}']
                            row.update(APE_m=v['fixed_se3_ape_rmse_m'], RPE_1s_m=v['fixed_se3_rpe_rmse_m'], diagnostic_sim3_scale=v['sim3_scale'])
            else:
                comparisons.append(comparison(summary, slug, *arms, status))
    table(PAPER / 'results.csv', result)
    table(PAPER / 'comparison.csv', comparisons)
    anomalies = [dict(run_slug=r['run_slug'], arm=r['arm'], repeat=r['repeat'], status=r['status']) for r in result if r.get('severe_anomaly')]
    baseline_ok = all(r.get('runability') == 'PASS' for r in result if r['arm'] == 'B')
    gain_b = [r for r in comparisons if r['comparison'].endswith('_vs_B') and r.get('practical') == 'PRACTICAL_GAIN']
    gain_old = [r for r in comparisons if r['comparison'].endswith('_vs_L-original') and r.get('practical') == 'PRACTICAL_GAIN']
    no_b_severe = all(r['status'] == 'PASS' and not r.get('severe_regression', True) for r in comparisons if r['comparison'].endswith('_vs_B'))
    if stopped or (completed == 18 and not baseline_ok):
        decision = 'EVALUATION_BLOCKED'
        next_step = '停止精度优劣结论；交付本次具体基线异常与已完成的可靠度转换，不扩大确定性研究。'
    elif completed < 18:
        decision = 'NOT_EVALUATED'
        next_step = '按冻结顺序完成本轮18次正式回放。'
    elif gain_b and no_b_severe and not anomalies:
        decision = 'PROMISING_DEVELOPMENT_RESULT'
        next_step = '固定统一通用映射，先冻结六个新且不重叠窗口，再执行授权的B/L-neutral验证。'
    elif gain_old:
        decision = 'SOURCE_MAPPING_MATTERS_BUT_NO_NET_GAIN'
        next_step = '保留来源映射的实现修正及“缓解退化、未形成净收益”的结论，停止本轮权重试验，不自动扩窗。'
    else:
        decision = 'SOURCE_MAPPING_NOT_MAIN_EXPLANATION'
        next_step = '停止来源映射权重排查；下一项开发应改变候选坐标集合或准入条件，而非继续扫描q常数。'
    payload = dict(decision=decision, formal_replays_completed=completed, formal_replays_planned=18,
                   baseline_usable=baseline_ok, severe_anomalies=anomalies,
                   new_window_replays=0, extension_started=False, source_commits=sorted({r['source_commit'] for r in result if 'source_commit' in r}),
                   internal_cause='Unknown', next_step=next_step)
    write_json(PAPER / 'decision.json', payload)
    write_json(PAPER / 'receipts' / 'runs.json', run_receipts)
    if stopped:
        write_json(PAPER / 'receipts' / 'stopped.json', json.loads((RUNTIME / 'stopped.json').read_text()))
    def fmt(value):
        return f'{float(value):.6g}' if value is not None else 'Unknown'
    text = f'''本轮实际完成 **{completed}/18次正式replay**，其中B基线{sum(r['status'] != 'Not evaluated.' for r in result if r['arm'] == 'B')}/6次。DECISION：**{decision}**。

- 基线是否足够可靠：{str(baseline_ok) if completed else 'Not evaluated.'}；沿用有效轨迹、接收完整性和重复范围，未要求旧A/A的1e-5m一致。
- 唯一改动：同一L-all候选的quality与派生sigma；锁定源码的通用映射，原始质量/年龄/FB/NCC不变，真实XFeat标签不变。
- 相对L-original：见下表两窗的全部实用判定及误差变化；不以较低中位数替代重复范围门。
- 相对KLT净收益：{len(gain_b)}个窗口通过实用收益门（完整分母2；未评估槽位不能视为失败或成功）。
- 严重异常：{len(anomalies)}次，全部列入results.csv；内部原因Unknown。
- 新窗口：未启动，0/36；仅首轮PROMISING允许扩展。
- 唯一下一步：{next_step}

| 窗口 | 比较 | neutral APE(m) | 参考APE(m) | APE变化(m/%) | RPE变化(m) | 判定 |
|---|---|---:|---:|---|---:|---|
'''
    for r in comparisons:
        text += '| ' + ' | '.join([r['run_slug'], r['comparison'], fmt(r.get('APE_neutral_m')), fmt(r.get('APE_reference_m')),
                   fmt(r.get('APE_delta_m')) + ' / ' + fmt(r.get('APE_delta_pct')), fmt(r.get('RPE_delta_m')), r.get('practical', r['status'])]) + ' |\n'
    text += '\n| 窗口 | 臂 | 重复 | APE(m) | 严格1s RPE(m) | Sim3诊断尺度 | 状态 |\n|---|---|---:|---:|---:|---:|---|\n'
    for r in result:
        text += '| ' + ' | '.join([r['run_slug'], r['arm'], str(r['repeat']), fmt(r.get('APE_m')), fmt(r.get('RPE_1s_m')),
                   fmt(r.get('diagnostic_sim3_scale')), r.get('runability', r['status'])]) + ' |\n'
    text += '''
逐次表采用三臂九轨迹共同支撑；两项主比较采用各自六轨迹共同支撑，精确min/max/极差与有效性见[comparison.csv](comparison.csv)。原始未对齐位移、初始化/接收/残差计数、覆盖与运行时间见[results.csv](results.csv)，全部运行receipts见[receipts/runs.json](receipts/runs.json)。

这是两个已知结果development窗上的实现混杂消融。三次技术重复不是独立科学样本；COLMAP/proxy非独立GT。q改变常规优化及边缘化，不能归因于初始SfM/视觉IMU对齐的直接q作用。没有C-all配对臂，不能宣称学习来源优于传统来源。旧A/A失败与旧72结果保持原样。

[冻结协议](protocol.md) · [输入/运行计划](run_plan.json) · [决策](decision.json)。大bag/日志只留本任务runtime；报告发布commit为本文件所属版本，实验源码见decision.json/source_commits。
'''
    (PAPER / 'report.md').write_text(text)
    handoff = f'''# Fast learned test / source-neutral quality v1

原则：结果优先、审计有上限、一个任务一个可检验问题。

{completed}/18正式回放；DECISION={decision}；新窗口0次。
唯一下一步：{next_step}

分支exp/source-neutral-quality-v1-20260908；worktree={ROOT}；runtime={RUNTIME}。
实验源码commit：{', '.join(payload['source_commits']) or '待协议冻结提交'}；报告发布为本文件所属commit。
原additive二进制只读复用；没有新诊断构建、router或常数扫描。

[报告](../papers/frontend_source_neutral_quality_v1/report.md) · [对比](../papers/frontend_source_neutral_quality_v1/comparison.csv) · [逐次结果](../papers/frontend_source_neutral_quality_v1/results.csv) · [协议](../papers/frontend_source_neutral_quality_v1/protocol.md)。
'''
    (ROOT / 'docs/CODEX_HANDOFF_FAST_LEARNED_TEST.md').write_text(handoff)
    print('REPORT', completed, decision, flush=True)


if __name__ == '__main__':
    main()
