#!/usr/bin/env python3
"""Direct-ablation analysis: reuse frozen metrics, with explicit old targets."""
import csv,json
from pathlib import Path
import numpy as np
from run_searaft_direct_recovery import ROOT,PAPER,OLD_PAPER,RT,OLD_RT,sha,save,BASE_COMMIT
import analyze_additive_budget_v1 as base
from analyze_searaft_system_probe import compare,attribution


def table(path,rows):
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)),lineterminator='\n');w.writeheader();w.writerows(rows)


def comparison(summary,control):
    # Reuse the exact existing decision arithmetic; R is only its local alias.
    mapped=dict(arms={k.replace('D_r','R_r'):v for k,v in summary['arms'].items()})
    values=compare(mapped,control)
    result={(('D_'+k[2:]) if k.startswith('R_') else k.replace('severe_R_repeats','severe_D_repeats')):v for k,v in values.items()}
    result['D_repeat_unstable']=result['D_APE_range']>max(.1*result['D_APE'],.01) or result['D_RPE_range']>max(.1*result['D_RPE'],.005)
    return result


def main():
    base.ROOT,base.PAPER,base.RUNTIME=ROOT,PAPER,RT
    windows=json.loads((PAPER/'input_manifest.json').read_text())['windows']
    plan=json.loads((RT/'backend_plan.json').read_text());backend={};back=[];results=[];comparisons=[]
    old_stats={(r['run_slug'],r['arm'],int(r['repeat'])):r for r in csv.DictReader((OLD_PAPER/'backend_results.csv').open())}
    new_lock=json.loads((PAPER/'backend_execution_lock_v2.json').read_text())
    for w in windows:
        slug=w['run_slug'];paths={}
        public=list(csv.DictReader((RT/'frontend'/slug/'public_tracks.csv').open()))
        # Existing attribution helper's R label is not a source-ID bucket.
        direct_public=[dict(r,arm='R' if r['arm']=='D' else r['arm']) for r in public]
        for arm in ('B','D'):
            for rep in (1,2,3):
                item=next(p for p in plan if (p['run_slug'],p['arm'],p['repeat'])==(slug,arm,rep))
                target=RT/'backend'/slug/item['mapped_to']/f'repeat{rep}';paths[arm,rep]=target
                b=base.backend_stats(target)
                for k in list(b):
                    if '_candidate' in k:del b[k]
                    elif '_KLT' in k:b[k.replace('_KLT','_original_ids')]=b.pop(k)
                b.update(sequence=w['sequence'],arm=arm,batch='DIRECT_NEW',mapped_to=item['mapped_to'])
                if arm=='D':b.update(attribution(target,direct_public))
                backend[slug,arm,rep]=b;back.append(b)
        old_receipt=json.loads((OLD_PAPER/'common_support'/slug/'R_vs_C/evaluation_receipt.json').read_text())
        for old_arm in ('R','C'):
            arm='OLD_'+old_arm
            for rep in (1,2,3):
                target=OLD_RT/'backend'/slug/old_arm/f'repeat{rep}';paths[arm,rep]=target
                assert sha(target/'vins_output/vio.csv')==old_receipt['input_hashes'][str(target/'vins_output/vio.csv')]
                rec=json.loads((target/'receipt.json').read_text())
                assert rec['binary_sha256']==new_lock['files'][new_lock['binary']]
                assert rec['canonical_source_sha256']==w['backend_config_source_sha256']
                b=dict(old_stats[slug,old_arm,rep],arm=arm,batch='SYSTEM_PROBE_1138fab',sequence=w['sequence'])
                backend[slug,arm,rep]=b;back.append(b)
        for control in ('B','OLD_R','OLD_C'):
            summary,status=base.evaluate(w,['D',control],backend,target_paths=paths)
            c=dict(sequence=w['sequence'],comparison='D_vs_'+control,role='PRIMARY' if control=='B' else 'AUXILIARY_CROSS_BATCH',status=status)
            if summary:c.update(comparison(summary,control),support=json.dumps(summary['support'],sort_keys=True))
            comparisons.append(c)
            for arm in ('D',control):
                for rep in (1,2,3):
                    b=backend[slug,arm,rep]
                    r=dict(sequence=w['sequence'],comparison=c['comparison'],role=c['role'],arm=arm,repeat=rep,batch=b['batch'],metric_status=status,
                        replay_status=b['status'],runability=b['runability'],received_complete=b['received_complete'],poses=b['poses'],trajectory_coverage=b['trajectory_coverage'],
                        trajectory_length_m=b['trajectory_length_m'],initialization_count=b['initialization_count'],failure_detection_count=b['failure_detection_count'],
                        reset_count_proxy=b['reset_count_proxy'],run_dir=str(paths[arm,rep]))
                    if summary:r.update(summary['arms'][f'{arm}_r{rep}'])
                    results.append(r)
    table(PAPER/'results.csv',results);table(PAPER/'comparison.csv',comparisons);table(PAPER/'backend_results.csv',back)
    primary=[c for c in comparisons if c['role']=='PRIMARY'];aux=[c for c in comparisons if c['comparison']=='D_vs_OLD_R']
    fronts=[json.loads((RT/'frontend'/w['run_slug']/'receipt.json').read_text()) for w in windows]
    intervention=any(f['B_D_different_feature_frames'] for f in fronts)
    unsafe=any(c['status']!='PASS' or c.get('severe_regression') or c.get('severe_D_repeats','[]')!='[]' or c.get('D_repeat_unstable') for c in primary)
    unsafe=unsafe or any(int(b['failure_detection_count']) or int(b['reset_count_proxy']) for b in back if b['batch']=='DIRECT_NEW')
    gain=any(c.get('practical')=='PRACTICAL_GAIN' for c in primary)
    helps=any(c.get('practical')=='PRACTICAL_GAIN' for c in aux) and all(c['status']=='PASS' and not c.get('severe_regression') for c in aux)
    decision=('NO_LEARNED_INTERVENTION' if not intervention else 'UNSAFE_OR_UNRESOLVED' if unsafe else 'DIRECT_RECOVERY_PROMISING' if gain else 'REMOVING_CLASSICAL_RETRY_HELPS_BUT_NO_GAIN' if helps else 'NO_DIRECT_LEARNED_INCREMENT')
    timing=list(csv.DictReader((RT/'network_timing.csv').open()));recovery=list(csv.DictReader((PAPER/'recovery_summary.csv').open()))
    loading=json.loads((RT/'model_loading.json').read_text()) if (RT/'model_loading.json').exists() else None
    for r in recovery:
        tt=[t for t in timing if t['sequence']==r['sequence']] if r['arm']=='D' else []
        r.update(cached_queries=sum(int(t['cached_queries']) for t in tt),new_queries=sum(int(t['new_queries']) for t in tt),
            pairs_with_cached_queries=sum(int(t['cached_queries'])>0 for t in tt),prediction_sampling_wall_s=sum(float(t['wall_s']) for t in tt),strong_lk_calls=0)
        pub=list(csv.DictReader((RT/'frontend'/next(w['run_slug'] for w in windows if w['sequence']==r['sequence'])/'public_tracks.csv').open()))
        r['S_history_public_observations']=sum(x['arm']==r['arm'] and x['has_S_history']=='True' for x in pub)
        r['cpu_tracking_recovery_wall_excluding_provider_s']=float(r['frontend_wall_s'])-r['prediction_sampling_wall_s']
        event_path=RT/'frontend'/next(w['run_slug'] for w in windows if w['sequence']==r['sequence'])/'recovery_events.csv'
        lengths=[int(e['public_observations_after']) for e in csv.DictReader(event_path.open()) if e['arm']==r['arm'] and e['source']=='S']
        for stat,value in [('min',min(lengths) if lengths else ''),('median',float(np.median(lengths)) if lengths else ''),('max',max(lengths) if lengths else '')]:
            r['S_event_public_continuation_'+stat]=value
    table(PAPER/'recovery_summary.csv',recovery)
    d=dict(status='COMPLETE',decision=decision,base_commit=BASE_COMMIT,new_backend_replays=sum(p['arm']==p['mapped_to'] for p in plan),
        identical_input_mappings=sum(p['arm']!=p['mapped_to'] for p in plan),historical_baselines_in_primary=0,auxiliary_old_C_R_replays_read=12,
        network=json.loads((RT/'frontend_complete.json').read_text()),cached_queries=sum(int(t['cached_queries']) for t in timing),new_queries=sum(int(t['new_queries']) for t in timing),
        prediction_sampling_wall_s=sum(float(t['wall_s']) for t in timing),model_load_s=loading['loading']['load_s'] if loading else 0,
        frontend_total_wall_s=sum(f['wall_s'] for f in fronts),physical_correspondence_correctness='Unknown',
        ordinary_B_repeat_variation='Reported and used in practical-range threshold; not alone classified as implementation failure',
        next_step='Stop this ablation. If unsupported, close current SEA-RAFT same-frame recovery combination line; no tuning, expansion or annotation.')
    d['backend_total_wall_s']=sum(float(b['wall_s']) for b in back if b['batch']=='DIRECT_NEW')
    d['current_same_frame_recovery_line_closed']=decision!='DIRECT_RECOVERY_PROMISING'
    save(PAPER/'decision.json',d)
    save(PAPER/'execution_provenance.json',dict(frontends=fronts,network=d['network'],model_loading=loading,base_commit=BASE_COMMIT,runtime=str(RT)))
    lines=['# SEA-RAFT direct recovery ablation','',f"**{decision}**。固定两窗消融已结束。",'']
    for c in primary:
        lines.append(f"- {c['sequence']} D/B：{c.get('practical',c['status'])}；严重回归={c.get('severe_regression','Unknown')}，D严重重复={c.get('severe_D_repeats','Unknown')}，D重复不稳定={c.get('D_repeat_unstable','Unknown')}。")
    for c in aux:lines.append(f"- {c['sequence']} 删除强LK后相对旧R：{c.get('practical',c['status'])}（重新计算共同支撑，跨批次辅助）。")
    lines+=['',f"新后端 {d['new_backend_replays']} 次；主比较不复用历史B；旧C/R各三次仅用于辅助，未重新回放。新推理 {d['network']['new_network_pairs']} 对 / {d['network']['forward_calls']} 方向调用；完全缓存 {d['network']['reused_network_pairs']} 对，精确命中 {d['cached_queries']} 个查询、新增 {d['new_queries']} 个查询。",
        f"模型加载 {d['network']['model_loads']} 次 / {d['model_load_s']:.2f}s；预测采样 {d['prediction_sampling_wall_s']:.2f}s（含加载/缓存I/O）；两个窗口前端总墙钟 {d['frontend_total_wall_s']:.2f}s。没有下载或重新编译。",
        '是否继续：'+('仅有开发支持，交回用户决定后续完整验证。' if decision=='DIRECT_RECOVERY_PROMISING' else '不支持扩展，结束当前SEA-RAFT当帧恢复组合线。'),
        '', '## 绝对APE/RPE及全部技术重复', '', '单位m，min / median / max。fixed-scale proper SE(3) APE和严格1秒平移RPE；每个比较独立重算六轨共同支撑。', '',
        '|窗口/比较|臂|APE|RPE|','|---|---|---|---|']
    for c in comparisons:
        if c['status']!='PASS':lines.append(f"|{c['sequence']}/{c['comparison']}|全部|{c['status']}|Not evaluated.|");continue
        for arm in ('D',c['comparison'][5:]):
            fmt=lambda m:f"{c[arm+'_'+m+'_min']:.6f} / {c[arm+'_'+m]:.6f} / {c[arm+'_'+m+'_max']:.6f}"
            lines.append(f"|{c['sequence']}/{c['comparison']}|{arm}|{fmt('APE')}|{fmt('RPE')}|")
    lines+=['','[results.csv](results.csv)保留36条比较内重复记录；D在不同支撑中重复出现不算新回放。[comparison.csv](comparison.csv)保留冻结门判定及支撑；[backend_results.csv](backend_results.csv)区分本轮与旧批次。',
        '', '## 介入和边界', '', '|窗口|学习事件/不同ID|至少1次/4次后续公开|带S历史公开观测|GFTT变化raw帧|', '|---|---:|---:|---:|---:|']
    for r in recovery:
        if r['arm']=='D':lines.append(f"|{r['sequence']}|{r['S_recoveries']}/{r['S_recovery_unique_ids']}|{r['S_recoveries_public_ge1']}/{r['S_recoveries_public_ge4']}|{r['S_history_public_observations']}|{r['B_D_different_GFTT_frames']}|")
    lines+=['','D强LK调用0。完整B序列化、非feature一致性、有限通道和原容量检查通过；接收/残差计数见backend_results。事件不是独立点，带恢复历史ID的残差不等于每个因子来自某次S恢复；逐点正确性Unknown。',
        '旧C/R只作跨批次辅助，旧H02 C数量级异常原样保留，不能凭胜过发散C宣布成功。普通B波动进入极差门并报告；初始化和未来GFTT变化未分离。COLMAP/proxy非独立GT，两个窗口非held-out；本轮不能证明泛化、实时、部署或论文创新。',
        '旧UNSAFE_OR_UNRESOLVED及全部旧筛选/参考结论不变。唯一下一步：停止此消融；不自动扩窗、调门、换模型、改执行顺序或要求人工标注。',
        f'运行目录：`{RT}`；冻结基点：`{BASE_COMMIT}`。','']
    (PAPER/'report.md').write_text('\n'.join(lines));print(decision,flush=True)


if __name__=='__main__':main()
