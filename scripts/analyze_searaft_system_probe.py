#!/usr/bin/env python3
"""Reuse fixed common-support metrics and retain every technical repeat."""
import csv,json
from collections import Counter
import numpy as np
from run_searaft_system_probe import ROOT,PAPER,RT,table,save
import analyze_additive_budget_v1 as base


def compare(summary,control):
    m={}
    for arm in ('R',control):
        for metric,key in [('APE','fixed_se3_ape_rmse_m'),('RPE','fixed_se3_rpe_rmse_m')]:
            vals=[summary['arms'][f'{arm}_r{r}'][key] for r in (1,2,3)]
            m[arm+'_'+metric]=float(np.median(vals))
            m[arm+'_'+metric+'_min']=min(vals);m[arm+'_'+metric+'_max']=max(vals)
            m[arm+'_'+metric+'_range']=max(vals)-min(vals)
    a,b=m['R_APE'],m[control+'_APE'];ar,br=m['R_RPE'],m[control+'_RPE']
    noise=max(m['R_APE_range'],m[control+'_APE_range'])
    rn=max(m['R_RPE_range'],m[control+'_RPE_range'])
    gain=b-a>=max(.05*b,.01) and b-a>noise
    loss=(a-b>=max(.05*b,.01) and a-b>noise) or ar-br>max(.05*br,.005,rn)
    severe=a-b>max(.1*b,.01,noise) or ar-br>max(.1*br,.005,rn)
    outliers=[]
    for r in (1,2,3):
        v=summary['arms'][f'R_r{r}']
        if v['fixed_se3_ape_rmse_m']-b>max(.1*b,.01) or v['fixed_se3_rpe_rmse_m']-br>max(.1*br,.005):outliers.append(r)
    unstable=m[control+'_APE_range']>max(.1*b,.01) or m[control+'_RPE_range']>max(.1*br,.005)
    return dict(**m,APE_delta_m=a-b,RPE_delta_m=ar-br,
        practical='PRACTICAL_GAIN' if gain and not loss else ('PRACTICAL_LOSS' if loss else 'SMALL_OR_UNCERTAIN'),
        severe_regression=severe,severe_R_repeats=json.dumps(outliers),control_unstable=unstable)


def attribution(target,public):
    # Microsecond key tolerates only epoch floating-point serialization error;
    # frames are ~50 ms apart. This does not interpolate observations.
    keys={(round(int(r['stamp_ns'])*1e-9,6),int(r['track_id'])) for r in public if r['arm']=='R' and r['has_S_history']=='True'}
    seen=set();count=Counter();ids={k:set() for k in ('received','eligible','residual')}
    for r in csv.reader((target/'backend_use.csv').open()):
        if r[0] not in ids:continue
        key=(round(float(r[1]),6),int(r[2]))
        if key in keys:
            count[r[0]]+=int(r[3]) if r[0]!='eligible' else 1
            ids[r[0]].add(key[1])
            if r[0]=='received':seen.add(key)
    return dict(S_history_public_observations=len(keys),S_history_received_observations=len(seen),
        S_history_missing_received=len(keys-seen),S_history_eligible_id_times=count['eligible'],
        S_history_residual_blocks_by_id_time=count['residual'],S_history_residual_unique_ids=len(ids['residual']),
        attribution_scope='received matches public ID/time; eligible/residual identify a recovered-history track at solve time, not the specific recovered observation factor')


def main():
    base.ROOT,base.PAPER,base.RUNTIME=ROOT,PAPER,RT
    windows=json.loads((PAPER/'input_manifest.json').read_text())['windows']
    plan=json.loads((RT/'backend_plan.json').read_text());backend={};back=[];results=[];comparisons=[]
    for w in windows:
        slug=w['run_slug'];public=list(csv.DictReader((RT/'frontend'/slug/'public_tracks.csv').open()))
        for arm in ('B','C','R'):
            for rep in (1,2,3):
                item=next(p for p in plan if (p['run_slug'],p['arm'],p['repeat'])==(slug,arm,rep))
                target=RT/'backend'/slug/item['mapped_to']/f'repeat{rep}'
                b=base.backend_stats(target)
                b.update(sequence=w['sequence'],arm=arm,mapped_to=item['mapped_to'])
                if arm=='R':b.update(attribution(target,public))
                backend[slug,arm,rep]=b;back.append(b)
        for control in ('B','C'):
            summary,status=base.evaluate(w,['R',control],backend)
            row=dict(sequence=w['sequence'],comparison='R_vs_'+control,status=status)
            if summary:
                row.update(compare(summary,control),support=json.dumps(summary['support'],sort_keys=True))
            comparisons.append(row)
            for arm in ('R',control):
                for rep in (1,2,3):
                    b=backend[slug,arm,rep]
                    r=dict(sequence=w['sequence'],comparison='R_vs_'+control,arm=arm,repeat=rep,metric_status=status,
                        replay_status=b['status'],runability=b['runability'],received_complete=b['received_complete'],poses=b['poses'],
                        trajectory_coverage=b['trajectory_coverage'],trajectory_length_m=b['trajectory_length_m'],initialization_count=b['initialization_count'],
                        failure_detection_count=b['failure_detection_count'],reset_count_proxy=b['reset_count_proxy'],run_dir=b['run_dir'])
                    if summary:r.update(summary['arms'][f'{arm}_r{rep}'])
                    results.append(r)
    table(PAPER/'results.csv',results);table(PAPER/'backend_results.csv',back);table(PAPER/'comparison.csv',comparisons)
    fronts=[json.loads((RT/'frontend'/w['run_slug']/'receipt.json').read_text()) for w in windows]
    intervention=any(f['C_R_different_feature_frames']>0 for f in fronts)
    bad=any(c['status']!='PASS' or c.get('severe_regression') or c.get('control_unstable') or c.get('severe_R_repeats','[]')!='[]' for c in comparisons)
    bad=bad or any(b['failure_detection_count'] or b['reset_count_proxy'] for b in back)
    joint=any(all(c.get('practical')=='PRACTICAL_GAIN' for c in comparisons if c['sequence']==w['sequence']) for w in windows)
    no_loss=all(c.get('practical')!='PRACTICAL_LOSS' for c in comparisons)
    only_B=any(c['comparison']=='R_vs_B' and c.get('practical')=='PRACTICAL_GAIN' for c in comparisons) and not any(c['comparison']=='R_vs_C' and c.get('practical')=='PRACTICAL_GAIN' for c in comparisons)
    decision=('NO_LEARNED_INTERVENTION' if not intervention else 'UNSAFE_OR_UNRESOLVED' if bad else 'PROMISING_SYSTEM_COMPONENT' if joint and no_loss else 'CLASSICAL_RECOVERY_EXPLAINS_GAIN' if only_B else 'NO_SYSTEM_INCREMENT')
    result=dict(status='COMPLETE',decision=decision,new_replays=sum(p['arm']==p['mapped_to'] for p in plan),historical_replays_reused=0,
        identical_input_mappings=sum(p['arm']!=p['mapped_to'] for p in plan),window_count=2,technical_repeats=3,network=json.loads((RT/'frontend_complete.json').read_text()),
        severe_or_unresolved=bad,physical_correspondence_correctness='Unknown',old_conclusions=['CONTROLLED_GAIN_ONLY','EVIDENCE_GATE_NOT_SUPPORTED','REFERENCE_PENDING'],
        next_step='Stop this fixed probe; no automatic expansion or tuning. Return system evidence to the user.')
    save(PAPER/'decision.json',result)
    recovery=list(csv.DictReader((PAPER/'recovery_summary.csv').open()))
    timing=list(csv.DictReader((RT/'network_timing.csv').open()))
    lines=['# SEA-RAFT system probe v1', '', '**'+decision+'**。两个已知开发窗，本次固定矩阵已结束。', '',
        f"实际新跑 {result['new_replays']} 次后端，复用历史结果 0 次；相同输入映射 {result['identical_input_mappings']} 次。全部技术重复保留。",
        '系统是否变好、学习是否超过强传统恢复：', '']
    for c in comparisons:
        lines.append(f"- {c['sequence']} {c['comparison']}: {c.get('practical',c['status'])}；严重回归={c.get('severe_regression','Unknown')}，异常R重复={c.get('severe_R_repeats','Unknown')}，对照不稳定={c.get('control_unstable','Unknown')}。")
    net=result['network']
    lines+=['',f"代价：新推理 {net['new_network_pairs']} 对，正反向合计 {net['forward_calls']} 次网络调用；复用 {net['reused_network_pairs']} 对精确查询缓存。查询提供器总耗时 {sum(float(t['wall_s']) for t in timing):.2f}s（含首次加载、坐标采样及小缓存写入）；非在线实时速度测定。",
        f"严重风险/未决条件：{'存在，见上列及全部重复表。' if bad else '本固定矩阵未触发冻结严重护栏；未评估窗口仍未知。'}",
        '是否值得继续：'+('仅值得交回主规划作后续完整验证决策。' if decision=='PROMISING_SYSTEM_COMPONENT' else '本轮不支持继续扩展这条组合。'),
        '', '## 绝对误差与技术重复', '', '单位m；中位数 [最小,最大]。R/B和R/C分别使用各6条轨迹共同支撑，不混合支撑比较。fixed-scale proper SE(3) APE；严格1秒平移RPE。', '',
        '|窗口/共同支撑比较|臂|APE|RPE|', '|---|---|---|---|']
    for c in comparisons:
        if c['status']!='PASS':
            lines.append(f"|{c['sequence']} / {c['comparison']}|全部|{c['status']}|Not evaluated.|");continue
        for arm in ('R',c['comparison'][-1]):
            def fmt(metric):return f"{c[arm+'_'+metric]:.6f} [{c[arm+'_'+metric+'_min']:.6f},{c[arm+'_'+metric+'_max']:.6f}]"
            lines.append(f"|{c['sequence']} / {c['comparison']}|{arm}|{fmt('APE')}|{fmt('RPE')}|")
    lines+=['', '完整24条比较内重复记录见 results.csv；18条实际/映射运行身份、初始化、接收、求解和覆盖见 backend_results.csv；冻结护栏判定见 comparison.csv。', '',
        '## 实际介入与代价', '', '|窗口|R中的强LK恢复|学习恢复|至少1次/4次后续公开|新推理对/缓存对|R前端耗时s|改变GFTT的raw帧|', '|---|---:|---:|---:|---:|---:|---:|']
    for r in recovery:
        if r['arm']=='R':lines.append(f"|{r['sequence']}|{r['C_recoveries']}|{r['S_recoveries']}|{r['S_recoveries_public_ge1']}/{r['S_recoveries_public_ge4']}|{r['network_new_pairs']}/{r['network_reused_pairs']}|{float(r['frontend_wall_s']):.2f}|{r['C_R_different_GFTT_frames']}|")
    lines+=['', '恢复为事件数，同ID可多次恢复。前端耗时包含该臂跟踪和恢复，不含三臂共享预处理；逐臂详情见 recovery_summary.csv。',
        '接收诊断通过公开ID与时间关联；eligible/residual只能证明具有恢复历史的轨迹在该求解时刻进入相应层，不能将同ID的每个因子归因给某一次学习恢复。个别对应的物理正确性仍为 Unknown。', '',
        '## 边界和复现', '',
        '包含初始化影响；恢复改变后续GFTT集合。COLMAP/proxy参考不是独立真值，本次不是held-out或机器人部署验证。即使轨迹改善也不证明逐点正确，不作为SEA-RAFT+NCC论文创新声明。',
        '旧 CONTROLLED_GAIN_ONLY、EVIDENCE_GATE_NOT_SUPPORTED、REFERENCE_PENDING 保持不变。旧92点及人工页面未修改。',
        f'输入、模型与后端见本目录冻结文件；协议实现提交1d677b7；运行材料本地目录 `{RT}`。',
        '执行入口：`scripts/run_searaft_system_probe.py frontend` → `scripts/run_searaft_system_backend.py` → `scripts/analyze_searaft_system_probe.py`。已完成的推理与运行不可重新启动；后端runner仅允许读取既有receipt。',
        '', '**唯一下一步：停止本轮，将上述系统证据交回用户；不自动扩窗、调参或追加人工标注。**', '']
    (PAPER/'report.md').write_text('\n'.join(lines))
    print(decision,flush=True)


if __name__=='__main__':main()
