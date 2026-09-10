#!/usr/bin/env python3
"""Finalize existing measurements and an explicit fixed-sample visual review; no inference."""
import csv
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'papers/frontend_searaft_screening_v1'

def read(path):
    with path.open() as f:return list(csv.DictReader(f))

def ms(rows,key):
    return float(np.median([float(r[key])*1000 for r in rows]))

def main():
    d=json.loads((P/'decision.json').read_text());lock=json.loads((P/'model_lock.json').read_text())
    rows=read(P/'controlled_results.csv');gates=read(P/'controlled_comparison.csv');times=read(P/'timing.csv')
    assert d['controlled_pairs_completed']==48 and len(times)==48
    assert len(set(r['pair_id'] for r in times))==48
    assert d['backend_replays']==0 and d['training_steps']==0 and d['checkpoint_count']==1
    natural=d['natural']
    if natural is not None:
        review=json.loads((P/'visual_review.json').read_text())
        assert review['review_completed'] and len(review['panels'])==3
        no_clear_error=not any(r['clear_identity_error'] for r in review['panels'])
        natural.update(visual_review=review,opportunity_pass=bool(natural['opportunity_count_pass'] and no_clear_error))
        d['decision']='PROMISING_MEASUREMENT_CAPABILITY' if natural['opportunity_pass'] else 'CONTROLLED_GAIN_ONLY'
    d['freeze_commit']='2833851648e84cf0c1bf0cd1f10406455878331e'
    d['finalized']=True
    (P/'decision.json').write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
    status=json.loads((P/'status.json').read_text());status.update(decision=d['decision'],phase='FINALIZED',status='COMPLETE')
    (P/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    def metric(method,scope='B_failures'):
        return next(r for r in rows if r['level']=='group' and r['sequence']=='ALL' and r['case']=='ALL' and r['method']==method and r['scope']==scope)
    c,s,raw=metric('C_common'),metric('S_common'),metric('S_raw')
    filtered=[g for g in gates if g['stage']=='filtered_gate']
    sonly=sum(int(g['S_only']) for g in filtered)
    sonly_correct=sum(int(g['S_only_correct']) for g in filtered)
    group_lines=[]
    for g in filtered:
        invisible=int(g['S_invisible_accepted'])/int(g['invisible_B_failures']) if int(g['invisible_B_failures']) else None
        verdict='PASS' if g['pass_group']=='True' else '样本不足' if g['sufficient']=='False' else '错误护栏未过'
        group_lines.append('| {sequence}/{case} | {visible_B_failures}/{invisible_B_failures} | {C_correct} | {S_correct} | {S_wrong}/{S_accepted} | {S_only} | '.format(**g)
                           +('{:.2%}'.format(invisible) if invisible is not None else 'N/A')+' | '+verdict+' |')
    raw_lines=[]
    for scope in ['all_queries','B_failures','C_common_not_correct']:
        for method in ['C_raw','S_raw']:
            r=metric(method,scope)
            raw_lines.append('| {} | {} | {}/{} | {:.3f}/{:.3f}/{:.3f} | {:.2%}/{:.2%} | {}/{} |'.format(scope,method,r['visible_count'],r['query_count'],
                float(r['visible_epe_median']),float(r['visible_epe_p90']),float(r['visible_epe_p95']),float(r['visible_le1_rate']),float(r['visible_le2_rate']),r['finite_count'],r['outside_count']))
    pair_cost=[sum(float(r[k]) for k in ['preprocess_s','forward_gpu_s','backward_gpu_s','restore_transfer_s','sampling_s','fb_checks_s']) for r in times]
    cost=np.percentile(np.array(pair_cost)*1000,[50,95])
    peak=max(int(float(r['peak_allocated_bytes'])) for r in times)/1024**2
    reserved=max(int(float(r['peak_reserved_bytes'])) for r in times)/1024**2
    if natural:
        natural_events=read(P/'natural_results.csv')
        summaries=[dict(r,C_only_3steps=sum(e['sequence']==r['sequence'] and e['category']=='C_only' and int(e['C_offline_steps'])==3 for e in natural_events)) for r in natural['sequence_summaries']]
        natural_answer='已执行A02/A08/H02各200 raw帧，{}个需要的相邻对各一次正反向推理；S-only/C-only/共同接受/共同拒绝为{}/{}/{}/{}。S-only通过3步离线普通LK的事件为{}（A02/A08/H02）。物理身份与自然逐点正确率仍Unknown。'.format(natural['model_pairs'],
            *[sum(r[k] for r in summaries) for k in ['S_only','C_only','both','neither']],'/'.join(str(r['S_only_3steps']) for r in summaries))
        natural_table='\n\n| 片段 | B失败事件 | S-only | C-only | 共同接受 | 共同拒绝 | S-only通过3步 | C-only通过3步 |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'+'\n'.join('| {sequence} | {B_failure_events} | {S_only} | {C_only} | {both} | {neither} | {S_only_3steps} | {C_only_3steps} |'.format(**r) for r in summaries)
        nat_times=read(P/'natural_timing.csv')
        nat_cost=[sum(float(r[k]) for k in ['preprocess_s','forward_gpu_s','backward_gpu_s','restore_transfer_s','sampling_s','fb_checks_s'])*1000 for r in nat_times]
        natural_table+='\n\n冻结自然机会门要求至少2序列各有≥5个S-only端点完成3步检查。本轮仅H02满足（20例），A02/A08均为0，因此跨片段门未过；H02局部机会保留。'
        natural_table+='\n\n自然正反向测量端到端中位/p95为{:.1f}/{:.1f}ms；C原始重试中位{:.1f}ms。均为当次顺序测量，不作不同负载的严格性能排名。'.format(float(np.median(nat_cost)),float(np.percentile(nat_cost,95)),ms(nat_times,'C_raw_s'))
        natural_table+='\n\n固定样例：[A02](samples/A02_natural_samples.png)、[A08](samples/A08_natural_samples.png)、[H02](samples/H02_natural_samples.png)。按冻结哈希每序列每组1例，缺组空白；复核记录[visual_review.json](visual_review.json)。未来3帧仅用于离线连续性/位移检查，不改变接受，不是独立GT；记录的位移量不能当作真实漂移误差。没有正式feature bag、公开ID恢复系统或VINS。'
    else:
        natural_answer='未运行，Not evaluated.；受控过滤门未通过。'
        natural_table=''
    next_step='仅发布有条件的测量能力候选，交主规划窗口决定下一项验证；本轮不直接集成VINS。' if d['decision']=='PROMISING_MEASUREMENT_CAPABILITY' else '封存本轮结果，不直接集成或追加模型/阈值/窗口。'
    report='''# SEA-RAFT measurement capability screening v1

**{decision}。** 本轮1个指定checkpoint、0训练、0后端replay；以下是新的SEA-RAFT实际推理结果。

1. **权重真正加载：是。** 官方spring-M / MemorySlices/Tartan-C-T-TSKH-spring540x960-M，FP32、iters4、scale−1、单GPU/batch1；472个状态张量完整匹配。原评价尺寸可运行，未使用640备用方案。首次HF strict共享BN别名兼容失败保留；同一权重仅补齐同值别名转为官方本地pth加载，所有实际推理复用一个成功实例。
2. **完成数：48/48受控对**，另2对恒等/平移接口检查；12底图×4类型，3条来源序列，无更换或删除。接口误差中位0.00448/0.02563原px，属于接口检查而非正式能力样本。
3. **优势条件：** large在A08/H02、illumination_blur在A02/A08/H02通过冻结开发门。A02-large虽有正确率优势，但不可见错误2/68越1%护栏；outside_occluded三序列均未过护栏。small不作为预注册困难类型的胜出条件，分组不足/失败均保留。不能写成全部类型可靠。
4. **同B失败集：** S_common正确{sc}、错误{sw}，C_common正确{cc}、错误{cw}；分母为6532可见/8371全部B失败。S-only接受{so}次，其中受控真对应正确{soc}次。S的309次错误全部来自不可见点，整体不可见接受309/1839=16.80%，整体错误护栏未通过；仅按通过分组限定结果，不能声称整体安全。
5. **原始与过滤：** S_raw在6532个可见B失败上全部≤2px，EPE中位/p95为0.093/0.230px；过滤后正确6525，仍误收309个不可见点。直接预测有能力，FB+边界不能充分排除遮挡下的推断位置。C旧生产门另列（正确2488/错误14），不与C_common的共同门混同；没有用LK精化替代S原始预测。
6. **自然阶段：** {natural_answer}
7. **集成与代价：** {next_step} 受控正反向S测量端到端中位/p95为{cost0:.1f}/{cost1:.1f}ms，峰值PyTorch allocated/reserved={peak:.1f}/{reserved:.1f}MiB（不含驱动上下文）；预热单列。收益与风险均不能外推到VINS定位或系统安全。

冻结组判定（每组4个固定底图，错误=不可见或>2原px；C为共同FB/有限/边界门）：

| 序列/类型 | 可见/不可见B失败 | C正确 | S正确 | S错误/接受 | S-only | S不可见错误率 | 结果 |
|---|---:|---:|---:|---:|---:|---:|---|
{group_table}

原始预测能力（EPE仅在有限、可见预测上统计，有限但越界仍计误差；≤1/≤2使用全部可见查询作分母，缺失不会从覆盖中消失）：

| 查询集合 | 臂 | 可见/全部查询 | EPE中位/p90/p95 px | ≤1/≤2 | 有限数/越界数 |
|---|---|---:|---|---|---:|
{raw_table}

过滤判据B的共同可见接受交集大小及两臂p95、各自完整覆盖均在[controlled_comparison.csv](controlled_comparison.csv)和[controlled_results.csv](controlled_results.csv)，没有只用交集误差隐藏覆盖损失。逐点输入、直接预测、FB、接受与真值见[controlled_points.csv](controlled_points.csv)。B原KLT和C原始预测均重新在同一图像/查询上计算；B/C adaptive CLAHE，S原mono8复制RGB三通道，不是仅改变网络的隔离消融。合成变换检验测量能力，不是自然水下效果真值。
{natural_table}

计时拆分：受控每对S预处理/正向GPU/反向GPU/恢复与传输/采样/FB中位分别{parts}ms；B/C_raw/C_production分别{bc}ms，共同传统预处理及质量评分{pre:.1f}ms另列。这些是顺序诊断测量，C的查询数与S整图成本不同，不能把旧日志耗时混入严格排名。GPU调用前后同步；首次预热在model_lock.json，正式完整逐对时间在timing.csv。

复现入口：[完整合同](task_instructions.md)、[冻结协议](protocol.md)、[模型身份](model_lock.json)、[最终决定](decision.json)。协议/模型锁定commit2833851648e84cf0c1bf0cd1f10406455878331e；官方源码9137517、HF revision eb97ef34，精确SHA在model_lock。原始检查点与首次加载失败保留；未扫描模型、参数或片段。所有数据为开发数据，SEA-RAFT是既有通用光流方法，名称SEA不构成水下创新依据。

唯一下一步：{next_step}
'''.format(decision=d['decision'],sc=s['correct'],sw=s['wrong_accepted'],cc=c['correct'],cw=c['wrong_accepted'],so=sonly,soc=sonly_correct,
           natural_answer=natural_answer,next_step=next_step,cost0=cost[0],cost1=cost[1],peak=peak,reserved=reserved,
           group_table='\n'.join(group_lines),raw_table='\n'.join(raw_lines),natural_table=natural_table,
           parts='/'.join('{:.2f}'.format(ms(times,k)) for k in ['preprocess_s','forward_gpu_s','backward_gpu_s','restore_transfer_s','sampling_s','fb_checks_s']),
           bc='/'.join('{:.2f}'.format(ms(times,k)) for k in ['B_s','C_raw_s','C_production_s']),pre=ms(times,'classical_preprocess_quality_s'))
    (P/'report.md').write_text(report)
    print(d['decision'],natural_answer,'S-only controlled',sonly,'correct',sonly_correct)

if __name__=='__main__':main()
