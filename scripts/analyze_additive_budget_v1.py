#!/usr/bin/env python3
"""Full-denominator evidence tables; never impute an unavailable trajectory."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import numpy as np

from run_additive_budget_v1 import ROOT,PAPER,RUNTIME,sha,save

ARMS=['B','L6','L-all','C-all']
PAIRS=[('L-all','L6'),('L6','B'),('L-all','B'),('C-all','B'),('L-all','C-all')]


def table(path, rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)


def verify_artifacts(receipt):
    for p,h in receipt['artifacts'].items():
        if sha(p)!=h:raise RuntimeError('artifact changed '+p)


def backend_stats(target):
    import rosbag
    receipt=json.loads((target/'receipt.json').read_text());verify_artifacts(receipt)
    result={k:receipt[k] for k in ['run_slug','arm','repeat','status','wall_s','peak_node_rss_bytes','feature_bag_sha256','binary_sha256']}
    result['run_dir']=str(target)
    result['receipt_emitted_at']=receipt['started_at']
    result['exact_wall_clock_start']='Unknown'
    log=(target/'vins.log').read_text(errors='replace')
    result['initialization_count']=log.count('Initialization finish!')
    result['failure_detection_count']=log.count('failure detection!')
    result['initialization_visual_imu_misalignment_count']=log.count('misalign visual structure with IMU')
    result['initialization_sfm_solver_timing']='Unknown'
    result['reset_count_proxy']=log.count('system reboot!')
    result['lost_tracking_count']='Unknown'
    init=[line for line in log.splitlines() if 'Initialization finish!' in line]
    result['initialization_log_first']=init[0] if init else ''
    result['initialization_log_first']=re.sub(r'\x1b\[[0-9;]*m','',result['initialization_log_first'])
    clock_match=re.search(r'\[(\d+\.\d+),\s*(\d+\.\d+)\]',result['initialization_log_first'])
    result['initialization_finish_first_ros_clock_s']=clock_match.group(2) if clock_match else 'Unknown'
    use=Counter();idsets=defaultdict(set);times=defaultdict(Counter);max_solver=0.;solver_calls=0;solver_near_limit=0;solver_sum=0.;solver_at_limit=0
    solver_budgets=Counter();solver_iterations=Counter();solver_terminations=Counter()
    if (target/'backend_use.csv').exists():
        for row in csv.reader((target/'backend_use.csv').open()):
            kind=row[0]
            if kind=='solver':
                elapsed,limit=float(row[2]),float(row[3]);solver_calls+=1
                max_solver=max(max_solver,elapsed);solver_near_limit+=elapsed>=.95*limit
                solver_sum+=elapsed;solver_at_limit+=elapsed>=limit
                solver_budgets[row[3]]+=1;solver_iterations[row[4]]+=1;solver_terminations[row[5]]+=1
            elif kind in ('received','eligible','residual'):
                tid=int(row[2]);n=int(row[3]);label='candidate' if tid>=10_000_000 else 'KLT'
                use[kind+'_'+label]+=n if kind in ('received','residual') else 1
                idsets[kind+'_'+label].add(tid)
                if kind=='eligible':times[kind][row[1]]+=1
    for kind in ['received','eligible','residual']:
        for label in ['KLT','candidate']:
            result[kind+'_'+label]=use[kind+'_'+label]
            result[kind+'_'+label+'_unique_ids']=len(idsets[kind+'_'+label])
    result.update(solver_calls=solver_calls,solver_near_time_limit_count=solver_near_limit,
                  solver_at_or_above_time_limit_count=solver_at_limit,solver_total_s=solver_sum,
                  solver_mean_s=solver_sum/solver_calls if solver_calls else '',
                  solver_near_limit_fraction=solver_near_limit/solver_calls if solver_calls else '',
                  solver_at_or_above_limit_fraction=solver_at_limit/solver_calls if solver_calls else '',
                  solver_budget_histogram_json=json.dumps(solver_budgets,sort_keys=True),
                  solver_iteration_histogram_json=json.dumps(solver_iterations,sort_keys=True),
                  solver_termination_integer_histogram_json=json.dumps(solver_terminations,sort_keys=True),
                  exact_solver_stop_reason='Unknown',
                  solver_diagnostic_scope='estimator.optimization nonlinear solve; initialization SfM solve not instrumented',
                  max_solver_s=max_solver,max_actual_eligible=max(times['eligible'].values(),default=0))
    source_counts=Counter()
    with rosbag.Bag(receipt['feature_bag']) as bag:
        topics=bag.get_type_and_topic_info().topics
        ref_topic='/afrl/colmap_gt' if '/afrl/colmap_gt' in topics else '/aqualoc/colmap_gt'
        stamps=[m.header.stamp.to_sec() for _,m,_ in bag.read_messages(topics=[ref_topic])]
        for _,m,_ in bag.read_messages(topics=['/feature_tracker/feature']):
            source_counts.update('candidate' if int(t)>=10_000_000 else 'KLT' for t in m.channels[0].values)
    result['received_complete']=all(use['received_'+k]==source_counts[k] for k in ['KLT','candidate'])
    result['reference_start_sensor_s']=str(stamps[0])
    vio=target/'vins_output/vio.csv'
    result.update(poses=0,trajectory_coverage=0.,trajectory_length_m='',first_pose_sensor_s='')
    if vio.exists() and vio.stat().st_size:
        from evaluate_vins_common_support import load_vins_body_csv
        poses=load_vins_body_csv(vio)
        result.update(poses=len(poses.stamps),first_pose_sensor_s=str(poses.stamps[0]),
            first_pose_delay_from_reference_start_s=float(poses.stamps[0]-stamps[0]),
            trajectory_length_m=float(np.linalg.norm(np.diff(poses.positions,axis=0),axis=1).sum()),
            trajectory_coverage=float((min(poses.stamps[-1],stamps[-1])-max(poses.stamps[0],stamps[0]))/(stamps[-1]-stamps[0])))
    result['runability']=('PASS' if receipt['status']=='COMPLETE' and result['poses']>=30
        and result['trajectory_coverage']>=.7 and result['initialization_count']>=1
        and result['received_complete'] else 'FAIL')
    return result


def evaluate(w,arms,backend):
    name='all_four' if len(arms)==4 else arms[0]+'_vs_'+arms[1]
    out=PAPER/'common_support'/w['run_slug']/name
    targets=[(arm,r) for arm in arms for r in range(1,4)]
    if any((w['run_slug'],arm,r) not in backend for arm,r in targets):return None,'Not evaluated.'
    if any(backend[(w['run_slug'],arm,r)]['runability']!='PASS' for arm,r in targets):return None,'INVALID_RUNABILITY'
    if not (out/'evaluation_receipt.json').exists():
        if out.exists():raise RuntimeError('unreceipted evaluator output '+str(out))
        for p,h in json.loads((PAPER/'evaluation_lock.json').read_text()).items():
            if sha(ROOT/p)!=h:raise RuntimeError('evaluation lock changed '+p)
        command=[sys.executable,str(ROOT/'scripts/evaluate_additive_budget_v1.py'),
                 '--reference-bag',w['baseline_bag'],'--reference-topic',
                 '/afrl/colmap_gt' if w['family']=='afrl' else '/aqualoc/colmap_gt',
                 '--evaluation-rate-hz','1','--max-reference-gap-s','2.5','--max-estimate-gap-s','.25',
                 '--output-dir',str(out),'--run-evo']
        input_hashes={}
        for arm,r in targets:
            target=RUNTIME/'backend'/w['run_slug']/arm/f'repeat{r}'
            alias=arm+'_r'+str(r)
            command+=['--arm',alias+'='+str(target/'vins_output/vio.csv'),'--arm-config',alias+'='+str(target/'vins.yaml')]
            input_hashes[str(target/'vins_output/vio.csv')]=sha(target/'vins_output/vio.csv')
        proc=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        out.mkdir(parents=True,exist_ok=True);(out/'evaluator.log').write_text(proc.stdout)
        save(out/'evaluation_receipt.json',dict(command=command,returncode=proc.returncode,input_hashes=input_hashes,
            artifacts={str(p):sha(p) for p in out.rglob('*') if p.is_file()}))
    receipt=json.loads((out/'evaluation_receipt.json').read_text());verify_artifacts(receipt)
    if receipt['returncode']!=0:return None,'INVALID_COMMON_SUPPORT_OR_EVALUATOR'
    evo=json.loads((out/'evo_crosscheck.json').read_text())
    if any(m['ape_abs_diff_m']>1e-6 or m['rpe_abs_diff_m']>1e-6
           for a in evo['arms'].values() for m in a.values()):
        return None,'INVALID_EVO_CROSSCHECK'
    summary=json.loads((out/'common_support_summary.json').read_text())
    support=summary['support']
    if not support['ape_valid'] or not support['rpe_valid']:return None,'INVALID_COMMON_SUPPORT'
    return summary,'PASS'


def median_range(summary,arm,key):
    vals=[summary['arms'][f'{arm}_r{r}'][key] for r in [1,2,3]]
    return float(np.median(vals)),float(max(vals)-min(vals)),float(min(vals)),float(max(vals))


def main():
    source=json.loads((PAPER/'source_and_backend_lock.json').read_text());front=[];back=[];backend={};comparisons=[];supports=[];resources=[];life=[]
    for w in source['windows']:
        slug=w['run_slug'];path=RUNTIME/'frontend'/slug/'receipt.json'
        receipt=json.loads(path.read_text()) if path.exists() else None
        if receipt:verify_artifacts(receipt)
        for arm in ARMS:
            f=dict(run_slug=slug,arm=arm,status='Not evaluated.')
            if receipt:
                f.update(status='COMPLETE',**receipt['arms'][arm]);f['image_shape']=json.dumps(receipt['image_shape'])
                s='xfeat' if arm.startswith('L') else 'classical_gftt'
                if arm!='B':f['source_counters_json']=json.dumps(receipt['source_counters'][s],sort_keys=True)
                f['frontend_receipt']=str(path);f['frontend_receipt_sha256']=sha(path)
                resources.append(dict(run_slug=slug,arm=arm,stage='frontend',wall_s=receipt['generation_wall_s'] if arm!='B' else 'REUSED',
                    merge_wall_s=f['merge_wall_s'],peak_rss_kib=receipt['peak_rss_kib'],
                    timing_scope='shared two-source generation; L6 and L-all share one inference stream',
                    timing_breakdown=json.dumps(receipt['timings'],sort_keys=True)))
            front.append(f)
            for r in [1,2,3]:
                target=RUNTIME/'backend'/slug/arm/f'repeat{r}'
                b=dict(run_slug=slug,arm=arm,repeat=r,status='Not evaluated.')
                if (target/'receipt.json').exists():
                    b=backend_stats(target);backend[(slug,arm,r)]=b
                    resources.append(dict(run_slug=slug,arm=arm,stage='backend',repeat=r,wall_s=b['wall_s'],
                        peak_rss_kib=b['peak_node_rss_bytes']/1024,solver_calls=b['solver_calls'],
                        solver_near_time_limit_count=b['solver_near_time_limit_count'],max_solver_s=b['max_solver_s']))
                back.append(b)
        if receipt:
            path=RUNTIME/'frontend'/slug/'candidate_lifecycle.csv'
            if path.exists():
                # Compact per-public-ID life; every observation mapping remains in immutable runtime CSV.
                groups={}
                for r in csv.DictReader(path.open()):
                    if r['event']=='reject':continue
                    key=(r['arm'],r['public_id'])
                    g=groups.setdefault(key,dict(run_slug=slug,arm=r['arm'],public_id=r['public_id'],source_id=r['source_id'],
                         first_frame=r['frame'],last_frame=r['frame'],public_observations=0,termination='window_end_or_source_end'))
                    if r['event'] in ['admit','continue']:g['public_observations']+=1;g['last_frame']=r['frame']
                    else:g['termination']=r['reason']
                life.extend(groups.values())
        for arms in [ARMS,*[list(p) for p in PAIRS]]:
            summary,status=evaluate(w,arms,backend)
            comparison='all_four' if len(arms)==4 else arms[0]+'_vs_'+arms[1]
            supports.append(dict(run_slug=slug,comparison=comparison,status=status,
                support_json=json.dumps(summary['support'],sort_keys=True) if summary else '',
                artifact=str(PAPER/'common_support'/slug/comparison)))
            if len(arms)==4:
                for arm in arms:
                    for repeat in [1,2,3]:
                        row=backend.get((slug,arm,repeat))
                        if row is not None:
                            row['all_four_metric_status']=status
                            if summary:
                                v=summary['arms'][f'{arm}_r{repeat}']
                                row.update(all_four_APE_rmse_m=v['fixed_se3_ape_rmse_m'],
                                    all_four_RPE_rmse_m=v['fixed_se3_rpe_rmse_m'],all_four_sim3_scale=v['sim3_scale'])
                if summary:
                    for row in front:
                        if row['run_slug']==slug:
                            for key,label in [('fixed_se3_ape_rmse_m','APE'),('fixed_se3_rpe_rmse_m','RPE'),('sim3_scale','sim3_scale')]:
                                med,spread,low,high=median_range(summary,row['arm'],key)
                                row[label+'_median']=med;row[label+'_min']=low;row[label+'_max']=high
                continue
            a,b=arms;result=dict(run_slug=slug,comparison=comparison,status=status,primary='fixed_scale_SE3_APE',artifact=str(PAPER/'common_support'/slug/comparison))
            if receipt:
                da,db=receipt['arms'][a],receipt['arms'][b]
                result.update(dose_a=da['total_published'],dose_b=db['total_published'],dose_ratio=da['total_published']/db['total_published'] if db['total_published'] else '',
                    dose_contrast_sufficient=receipt['arms']['L6']['frames_at_six']>=10 and receipt['arms']['L-all']['frames_over_six']>=10
                        and receipt['arms']['L-all']['total_published']>=1.25*receipt['arms']['L6']['total_published'])
            if summary:
                ae,asp,alo,ahi=median_range(summary,a,'fixed_se3_ape_rmse_m');be,bsp,blo,bhi=median_range(summary,b,'fixed_se3_ape_rmse_m')
                ar,ars,_,_=median_range(summary,a,'fixed_se3_rpe_rmse_m');br,brs,_,_=median_range(summary,b,'fixed_se3_rpe_rmse_m')
                ape_delta=ae-be;rpe_delta=ar-br;noise=max(asp,bsp);rnoise=max(ars,brs)
                improvement=-ape_delta>=max(.05*be,.01) and -ape_delta>noise
                regression=ape_delta>=max(.05*be,.01) and ape_delta>noise
                guard=max(.05*br,.005,rnoise)
                practical='PRACTICAL_GAIN' if improvement and rpe_delta<=guard else ('PRACTICAL_LOSS' if regression or rpe_delta>guard else 'SMALL_OR_UNCERTAIN')
                result.update(APE_a=ae,APE_b=be,APE_a_min=alo,APE_a_max=ahi,APE_b_min=blo,APE_b_max=bhi,
                    RPE_a=ar,RPE_b=br,APE_delta_m=ape_delta,APE_delta_pct=100*ape_delta/be if be else '',
                    RPE_delta_m=rpe_delta,RPE_delta_pct=100*rpe_delta/br if br else '',
                    APE_repeat_range_threshold=noise,RPE_repeat_range_threshold=rnoise,
                    direction='BOTH_LOWER' if ape_delta<0 and rpe_delta<0 else ('BOTH_HIGHER' if ape_delta>0 and rpe_delta>0 else 'MIXED_OR_EQUAL'),
                    practical=practical,severe_regression=(ape_delta>max(.1*be,.01,noise) or rpe_delta>max(.1*br,.005,rnoise)))
            comparisons.append(result)
    table(PAPER/'frontend_audit.csv',front);table(PAPER/'backend_results.csv',back);table(PAPER/'comparisons.csv',comparisons);table(PAPER/'common_support_status.csv',supports)
    if resources:table(PAPER/'resource_usage.csv',resources)
    if life:table(PAPER/'candidate_lifecycle.csv',life)
    completed=sum(r['status']=='COMPLETE' for r in back);attempted=sum(r['status']!='Not evaluated.' for r in back)
    fe=sum(r['status']=='COMPLETE' for r in front)
    qty=[r for r in comparisons if r['comparison']=='L-all_vs_L6'];gains=sum(r.get('practical')=='PRACTICAL_GAIN' for r in qty)
    decision=dict(status='COMPLETE' if attempted==72 and fe==24 else 'IN_PROGRESS',frontend_completed=fe,frontend_total=24,
        backend_attempted=attempted,backend_completed=completed,backend_planned=72,reused_replays=0,
        quantity_contrast_sufficient_windows=sum(bool(r.get('dose_contrast_sufficient')) for r in qty),
        quantity_practical_gain_windows=gains,quantity_practical_loss_windows=sum(r.get('practical')=='PRACTICAL_LOSS' for r in qty),
        results_boundary='six outcome-known development windows; three technical repeats are not independent samples; COLMAP/proxy reference',
        answer='Unknown; full matrix pending' if attempted<72 else 'See full registered quantity contrasts; no automatic expansion',
        next_step='完成同一冻结合同的剩余矩阵。' if attempted<72 else '依据完整剂量/效果对照选择唯一后续研究，不自动扩展。')
    (PAPER/'decision.json').write_text(json.dumps(decision,indent=2,ensure_ascii=False)+'\n')
    lines=['对同一份合格 XFeat 候选流，取消 6 条并发配额是否增加实际剂量并改善后端净收益：'+decision['answer']+'。','',
        '| 窗口 | 臂 | 候选总发布 / 最大并发 | 公开寿命中位 / 最长 | APE / RPE 中位(m) | 后端完成 | 前端/合并(s) |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in front:
        slug=r['run_slug'];arm=r['arm'];n=sum(b['status']=='COMPLETE' for b in back if b['run_slug']==slug and b['arm']==arm)
        dose=f"{r.get('total_published','Unknown')} / {r.get('max_concurrent','Unknown')}"
        lifetime=f"{r.get('lifetime_median','Unknown')} / {r.get('lifetime_max','Unknown')}"
        metric=f"{r['APE_median']:.6g} / {r['RPE_median']:.6g}" if 'APE_median' in r else 'Not evaluated.'
        lines.append(f"| {slug} | {arm} | {dose} | {lifetime} | {metric} | {n}/3 | {r.get('merge_wall_s','Unknown')} |")
    lines+=['',f"前端完成 {fe}/24；新后端尝试 {attempted}/72，成功输出 {completed}/72。没有将技术重复当独立窗口。",'',
        'all 仅针对冻结 top_k=2048、每次60种子/800私有池。GFTT原生供给设置与XFeat不同，不能声称等资源学习来源更强。冻结vins_safe函数还包含来源权重分支，C-all/XFeat不是完全相同的q映射；L6/L-all仍共享完全相同的XFeat质量值。见[实现审计](implementation_audit_notes.md)。',
        '所有已完成合并均检验去掉候选后逐消息重建原始B，并核对非feature消息；L6按source_id/精确时间戳是L-all子集。',
        '完整剂量、源码/输入哈希及运行路径见 [frontend_audit.csv](frontend_audit.csv)；[后端逐次结果](backend_results.csv)、[预注册30对比](comparisons.csv)、[资源](resource_usage.csv)、[共同支撑](common_support_status.csv)。',
        '主表精度采用四臂十二轨迹共同支撑；每项两臂比较另外在其六条轨迹共同支撑上判断。表间口径不得拼接。',
        '后端 residual 计数为多次优化中实际建立的投影残差块次数，可重复利用同一视觉观测；不是独立新观测总数。solver接近上限定义 elapsed>=95%当前上限，不能独凭此判定停止原因。',
        '逐链终止的精确私有tracker原因未逐ID保存，Unknown；源流记录按类累计 FB/NCC/border/几何/质量/去重原因，不能把所有缺失都归因数量门。',
        '当前唯一下一步：'+decision['next_step']]
    (PAPER/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(decision,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
