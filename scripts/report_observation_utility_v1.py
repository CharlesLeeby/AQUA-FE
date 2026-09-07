#!/usr/bin/env python3
"""Complete six-window audit report; all summaries descriptive, no fitted rule."""
import json,subprocess,os
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_observation_utility_v1 import ROOT,PAPER,OLD,RUNTIME,rows,table,save,sha

COLORS={'L-all':'#D55E00','C-all':'#0072B2','B':'#555555'}
NEXT='先做冻结 B 的回放确定性与日志侵入性审计，查清本次 A08 冻结版异常后再恢复初始化内部诊断；暂不开发新的 admission/router。'
def f(x):return f'{float(x):.6g}' if x not in ['',None] else 'Unknown'
def mdtable(headers,data):return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+''.join('| '+' | '.join(map(str,r))+' |\n' for r in data)
def main():
 audit_commit=os.environ.get('OBSUTILITY_ANALYSIS_COMMIT',subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
 script_paths=sorted(ROOT.glob('scripts/*observation_utility*.py'))
 script_hashes={str(p.relative_to(ROOT)):sha(p) for p in script_paths}
 source_matches=True
 for p in script_paths:
  stored=subprocess.run(['git','show',audit_commit+':'+str(p.relative_to(ROOT))],capture_output=True)
  if stored.returncode or stored.stdout!=p.read_bytes():source_matches=False
 if not source_matches:
  assert 'OBSUTILITY_ANALYSIS_COMMIT' not in os.environ,'Explicit source commit does not match all audit scripts'
  audit_commit='UNCOMMITTED supplement; base HEAD='+audit_commit+'; exact script hashes recorded'
 windows=rows(OLD/'windows.csv');slugs=[w['run_slug'] for w in windows];names=['A09','A02','Bus','A08','Cemetery','H07'];labels=dict(zip(slugs,names));key=['a02_0_900','a08_2700_3600','afrl_bus_s180_d045']
 src=rows(PAPER/'candidate_source_comparison.csv');info=rows(PAPER/'information_geometry_summary.csv');ini=rows(PAPER/'existing_initialization_summary.csv');comp=rows(OLD/'comparisons.csv');aa=rows(PAPER/'diagnostic_aa.csv');avail=rows(PAPER/'first_admission_availability.csv')
 assert {r['run_slug'] for r in src}==set(slugs);assert len(ini)==72 and len(aa)==3;assert len(avail)==18
 sd={(r['run_slug'],r['arm']):r for r in src if r['phase']=='all'};idict={(r['run_slug'],r['arm'],r['model'],r['weighting']):r for r in info if r['phase']=='all'}
 def ss(w,a,k):return float(sd[w,a][k])
 def ii(w,a,m,k,q='unit_q'):return float(idict[w,a,m,q][k])
 def initial(w,a,k):return [float(r[k]) for r in ini if r['run_slug']==w and r['arm']==a]
 mechanism=[]
 for w in slugs:
  r=dict(run_slug=w,scientific_role='outcome_known_development_mechanism_discovery',L_all_vs_B=next(z['practical'] for z in comp if z['run_slug']==w and z['comparison']=='L-all_vs_B'),C_all_vs_B=next(z['practical'] for z in comp if z['run_slug']==w and z['comparison']=='C-all_vs_B'))
  for a,prefix in [('L-all','X'),('C-all','C')]:
   for k in ['observation_rows','q_median','final_public_lifetime_median','final_tracks_ge10','added_cells_mean','rotation_compensated_parallax_norm_median','local_motion_residual_norm_median','global_corrected_patch_abs_delta_median']:
    r[prefix+'_'+k]=sd[w,a][k]
   for model in ['unit_depth_flow','imu_epipolar_translation']:
    for k in ['logdet_gain_median','individual_logdet_median_median','condition_change_median','weak_direction_gain_median']:
     r[prefix+'_'+model+'_'+k]=ii(w,a,model,k)
  r['X_over_C_motion_residual_ratio']=ss(w,'L-all','local_motion_residual_norm_median')/ss(w,'C-all','local_motion_residual_norm_median')
  for a in ['B','L-all','C-all']:
   for metric in ['first_pose_delay_s','alignment_rejections','all_four_sim3_scale']:
    vals=initial(w,a,metric);r[a+'_'+metric+'_min']=min(vals);r[a+'_'+metric+'_median']=float(np.median(vals));r[a+'_'+metric+'_max']=max(vals)
  r.update(internal_initialization_scale='Unknown: diagnostic A/A failed',gravity_and_spectrum='Unknown: diagnostic A/A failed',actual_initialization_source_fraction='Unknown: old log absent; new logger invalid',underwater_physical_validity_label='Unknown',pointwise_causal_utility='Not evaluated.',mechanism='PARTIAL_INITIALIZATION_ASSOCIATION' if w in [key[0],key[2]] else ('SHADOW_INFORMATION_COUNTEREXAMPLE' if w==key[1] else 'UNRESOLVED_CONTROL'))
  mechanism.append(r)
 table(PAPER/'window_mechanism_summary.csv',mechanism)
 # All figures show within-window distributions or technical ranges, never independent-sample CIs.
 dest=PAPER/'analysis-output';figdir=dest/'figures';figdir.mkdir(parents=True,exist_ok=True)
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
 fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
 for ax,(metric,title) in zip(axes.flat,[('observation_rows','Published candidate observations'),('final_public_lifetime_median','Median final public lifetime (future only)'),('local_motion_residual_norm_median','Median local KLT motion residual'),('global_corrected_patch_abs_delta_median','Median corrected patch intensity change')]):
  vals=[ss(w,'L-all',metric)/ss(w,'C-all',metric) for w in slugs];ax.bar(names,vals,color='#777777');ax.axhline(1,color='black',ls='--',lw=1);ax.set_yscale('log');ax.set_ylabel('XFeat / classical');ax.set_title(title);ax.tick_params(axis='x',rotation=25)
  for i,v in enumerate(vals):ax.annotate(f'{v:.2f}',(i,v),ha='center',va='bottom',fontsize=8,xytext=(0,3),textcoords='offset points')
 fig.suptitle('Source differences are not a single quality ordering — six known windows');fig.savefig(figdir/'01-source-contrasts.png',dpi=170);plt.close(fig)
 fig,axes=plt.subplots(2,3,figsize=(12,7),constrained_layout=True)
 for row,model in enumerate(['unit_depth_flow','imu_epipolar_translation']):
  for col,w in enumerate(key):
   ax=axes[row,col]
   for x,a in enumerate(['L-all','C-all']):
    d=idict[w,a,model,'unit_q'];med=float(d['logdet_gain_median']);lo=float(d['logdet_gain_p10']);hi=float(d['logdet_gain_p90']);ax.errorbar(x,med,yerr=[[med-lo],[hi-med]],fmt='o',color=COLORS[a],capsize=4,ms=7)
   ax.set_xticks([0,1]);ax.set_xticklabels(['XFeat','classical']);ax.set_xlim(-.5,1.5);ax.set_ylim(bottom=0);ax.set_title(labels[w]+' / '+('unit-depth flow' if row==0 else 'IMU epipolar'));ax.set_ylabel('Marginal logdet gain (q=1)')
 fig.suptitle('Larger shadow information does not establish better localization\nMedian and p10–p90 across frames; not confidence intervals');fig.savefig(figdir/'02-shadow-information.png',dpi=170);plt.close(fig)
 fig,axes=plt.subplots(2,3,figsize=(12,7),constrained_layout=True)
 for col,w in enumerate(key):
  for row,(metric,title) in enumerate([('first_pose_delay_s','First output delay (s)'),('all_four_sim3_scale','Final fitted Sim(3) scale')]):
   ax=axes[row,col]
   for x,a in enumerate(['B','L-all','C-all']):
    vals=initial(w,a,metric);ax.scatter(x+np.array([-.08,0,.08]),vals,c=COLORS[a],s=35);ax.vlines(x,min(vals),max(vals),colors=COLORS[a],alpha=.6)
   ax.set_xticks([0,1,2]);ax.set_xticklabels(['B','XFeat','classical']);ax.set_title(labels[w]);ax.set_ylabel(title)
   if row:ax.set_yscale('log');ax.axhline(1,color='grey',ls='--',lw=1)
 fig.suptitle('Existing frozen runs: same first-output time need not imply same scale behavior\nThree technical repeats; fitted trajectory scale is NOT initialization scale');fig.savefig(figdir/'04-initialization-association.png',dpi=170);plt.close(fig)
 numeric=mdtable(['窗口','X/C发布量','X/C寿命中位','X/C运动偏差','X/C光度变化','X/C flow logdet(q=1)','X/C epi logdet(q=1)'],[[labels[w],f(ss(w,'L-all','observation_rows'))+'/'+f(ss(w,'C-all','observation_rows')),f(ss(w,'L-all','final_public_lifetime_median'))+'/'+f(ss(w,'C-all','final_public_lifetime_median')),f(ss(w,'L-all','local_motion_residual_norm_median')/ss(w,'C-all','local_motion_residual_norm_median')),f(ss(w,'L-all','global_corrected_patch_abs_delta_median')/ss(w,'C-all','global_corrected_patch_abs_delta_median')),f(ii(w,'L-all','unit_depth_flow','logdet_gain_median'))+'/'+f(ii(w,'C-all','unit_depth_flow','logdet_gain_median')),f(ii(w,'L-all','imu_epipolar_translation','logdet_gain_median'))+'/'+f(ii(w,'C-all','imu_epipolar_translation','logdet_gain_median'))] for w in slugs])
 questions='''1. **为什么C-all在A02/Bus能比KLT好？** 因果原因仍Unknown。A02 classical的公开寿命更长、对邻域KLT的运动偏差更小，且保留B的对齐拒绝次数/首输出时刻；这些与正向整体干预一致。Bus classical中位寿命却只有1次，不能把两窗收益统一解释为长轨迹。没有逐候选beneficial标签。
2. **为什么L-all在A02/A08/A09没有净收益？** 剂量不足、删除KLT、未进残差已被原审计排除。A02初始化接受路径改变；A08首输出时刻相同仍退化；A09连B也严重尺度失配。新增几何shadow信息不能保护估计状态，具体scale/gravity根因仍未有效测得。
3. **数量、寿命、覆盖、parallax能解释差异吗？** 只能部分描述。XFeat在A02/A08有更多发布、更大覆盖增量，且实际长链绝对数更多，仍无净收益；C的寿命优势不跨Bus成立。不能单靠这些量推出准入规则。
4. **信息增益/冗余能解释吗？** 未得到一致的有用/有害分界。A02/A08中XFeat的两种集合shadow logdet更大，q=1后仍如此；两源都有高行方向重合与边际收益递减。残差偏差也会增加epipolar Gram的秩/谱，所谓信息增加不保证静态、无偏或完整VIO有效信息。
5. **初始化scale/gravity/alignment路径能解释吗？** 旧日志确认A02/Bus的alignment路径关联，不能跨A08归结为早/晚初始化。三组新B A/A均失败，故0/27正式诊断；新内部scale/gravity/条件谱不用于机制结论。最终Sim3拟合不能替代初始scale。
6. **有水下特有motion/photometric reliability证据吗？** 六窗XFeat相对邻域KLT的运动偏差中位数都更大（包括无实用退化的Cemetery/H07），但邻域距离、真实深度、零偏/同步是混杂。A02/A08的XFeat光度变化反而更小。静态图/patch变化无法识别颗粒、焦散或折射；真实标签Unknown，只能称UNDERWATER_RELIABILITY_HYPOTHESIS。
7. **有准入前、跨关键窗一致的风险/价值信号吗？** 尚未建立。局部运动偏差是小而可解释的候选线索，但多数双帧量来自已经公开的续传记录，首次准入私有历史缺失；有效初始化状态反馈也未获得。不能声称在线判别或泛化。
8. **下一项最小算法实验是什么？** 当前不建议算法实验。唯一下一步：'''+NEXT+'\n'
 analysis='''# 严格分析包 / observation utility audit v1

科学单位：六物理development窗；原72次技术重复日志、2439个共同输出时刻、B与两来源观测。新6次B A/A为工程验证，正式机制diagnostic replay=0。没有训练、阈值搜索或新候选生成。

'''+numeric+'''
## Claim Candidates

- Claim：可跟踪性/更多几何shadow信息不足以保证集合干预收益。
  - Source evidence：candidate_source_comparison.csv、information_geometry_summary.csv、原comparisons.csv；图01/02。
  - Allowed wording：在当前六个开发窗观察到信息proxy与终局结果不一致。
  - Forbidden stronger wording：XFeat没有信息；所有XFeat点有害；shadow等于VIO Fisher。
  - Uncertainty：真实深度/IMU先验/相关噪声/动态有效性未建模。
  - Next check：有效初始化状态与回放确定性。
  - Decision：keep（描述性）。
- Claim：A02/Bus存在观测集合与初始化接受路径变化的关联。
  - Source evidence：72日志身份核验、existing_initialization_summary.csv、图04。
  - Allowed wording：A02/Bus的对齐拒绝及接受路径改变，不能统一为提前接受。
  - Forbidden stronger wording：已证明scale、gravity或某个候选单独致因；A08同一机制已确认。
  - Uncertainty：诊断A/A失败，内部状态无有效补充。
  - Next check：冻结B重放确定性与日志侵入性。
  - Decision：weaken（PARTIAL_MECHANISM）。
- Claim：局部KLT运动偏差是后续研究线索。
  - Source evidence：underwater_reliability_audit.csv与first_admission_availability.csv。
  - Allowed wording：三个关键窗集合中位排序一致，仍有距离/深度及记录可得性混杂。
  - Forbidden stronger wording：识别颗粒/焦散；已有可泛化router或逐点真值。
  - Uncertainty：实际first-admission motion缺失，静态真值Unknown。
  - Next check：同上，先取得有效机制证据。
  - Decision：weaken。
'''
 (dest/'analysis-report.md').write_text(analysis)
 (dest/'stats-appendix.md').write_text('''# 统计附录

6个目的性、已知结果物理窗口，非随机样本；三solver repeats仅技术波动。原pair-specific common support全部PASS，精度判定只引用原30行；新A/A未做APE/RPE比较。

source表为观测级n/min/p10/median/p90/max/mean；最终寿命按公开ID、窗口右截断。information表按帧聚合，individual_logdet_median_median是“先帧内候选中位，再跨帧中位”，不能当成全部候选混合中位。每窗各源和每技术重复pre/post-init均给全分布；阶段标签为事后分组。

主effect size使用窗口内X/C倍率及原对比APE/RPE差，技术重复给全范围。巨大观测N高度相关，不计算显著性、bootstrap CI或独立成功率；这些统计Not evaluated.且不适合此发现集。没有多重检验p值可校正，也不从多个矩阵指标中选取赢家；两模型×两q映射×trace/logdet/min-eigen/weak-direction/condition全部保留。

单位深度假设、ridge公式、gyro时间/零偏、缺失值、first-admission可用性与q模型差异见research_questions.md、feature_dictionary.md和analysis_limitations.md。
'''+numeric)
 (dest/'figure-catalog.md').write_text('''# 图目录与解释

- 01-source-contrasts.png：来源的数量、寿命、运动、光度倍率；data=candidate_source_comparison.csv/all。读者应注意指标排序相互冲突，尤其Bus寿命与A02/A08光度；削弱单一quality排序。对数轴，虚线1，无CI，绝对数见表。
- 02-shadow-information.png：三个关键窗两模型q=1的集合logdet；data=information_geometry_summary.csv/all/unit_q。点为帧中位，须注明p10–p90非CI。XFeat信息proxy更大仍未净收益，说明模型缺少无偏/真实性/初始化状态约束，不证明零信息。
- 03-fixed-image-audit.png：固定output10及中点原图和候选位置；data=image_audit_identity.json及锁定原bag/source。不是按效果挑图；可见照明/空间分布差异，但无真实颗粒/焦散标签。静态图不能证明非刚体运动。
- 04-initialization-association.png：原三技术重复首输出延迟与最终Sim3拟合；data=existing_initialization_summary.csv。A02/Bus路径变化而A08时刻相同；同一时刻不代表同一数值初始化。最终拟合scale绝不是内部scale。

图的作用是呈现机制反例与证据缺口，不是证明在线分类准确率。审阅需检查窗口/来源、每根误差线含义、q/阶段/单位及否定强结论。
''')
 provenance={str(p.relative_to(ROOT)):sha(p) for p in PAPER.glob('*.csv')};provenance.update({str(p.relative_to(ROOT)):sha(p) for p in figdir.glob('*.png')})
 save(dest/'provenance.json',dict(audit_source_commit=audit_commit,initial_extraction_and_diagnostic_commit='07e59b5933ca6c7b1c19906a19ff1f5adf30c3a2',report_script_sha256=sha(__file__),audit_script_sha256=script_hashes,base_commit='49c02471716e8ac960e35dd9dd44ef6fbb1428c6',artifacts=provenance,window_unit=6,new_formal_diagnostic_replays=0,new_aa_engineering_replays=6))
 decision=dict(status='COMPLETE',decision='PARTIAL_MECHANISM',explanation_category='E',online_admission_evidence='F: not established',provisional=False,scientific_windows=6,existing_logs=72,aa_engineering_replays=6,aa_pass_pairs=0,aa_fail_pairs=3,formal_diagnostic_replays=0,formal_max=27,algorithm_changes=0,new_windows=0,new_candidate_sources=0,threshold_searches=0,per_candidate_causal_labels='Unknown',underwater_physical_labels='Unknown',internal_initialization_state='Not evaluated: A/A gate failed',minimum_algorithm_evidence_met=False,risk_aware_admission_recommended=False,next_step=NEXT,source_commit=audit_commit,initial_extraction_and_diagnostic_commit='07e59b5933ca6c7b1c19906a19ff1f5adf30c3a2',limitations='six outcome-known windows; technical repeats not independent; no valid full-VIO information or initialization-state attribution')
 save(PAPER/'decision.json',decision)
 init_table=mdtable(['窗口/臂','首输出延迟min–max(s)','对齐拒绝min–max','最终Sim3 min–max'],[[labels[w]+'/'+a,f(min(initial(w,a,'first_pose_delay_s')))+'–'+f(max(initial(w,a,'first_pose_delay_s'))),f(min(initial(w,a,'alignment_rejections')))+'–'+f(max(initial(w,a,'alignment_rejections'))),f(min(initial(w,a,'all_four_sim3_scale')))+'–'+f(max(initial(w,a,'all_four_sim3_scale')))] for w in key for a in ['B','L-all','C-all']])
 report=questions+'''

## 身份、范围与机制差异图

2026-09-08；observation utility audit v1。源证据49c0247、旧A02初始化补充54cc31f；本轮审计/诊断源码07e59b5；报告发布commit与源身份分开。本任务不修改任何旧源流、权重、算法/门/预算或六窗原结论。

```mermaid
flowchart LR
 S[来源供给与轨迹] --> G[覆盖 / 几何 / 运动一致性]
 S --> Q[q 映射]
 G --> K[关键帧 / relativePose / SfM]
 K --> I[视觉 IMU 对齐与尺度接受]
 I --> O[常规优化与边缘化]
 Q --> O
 O --> R[最终轨迹 / proxy APE RPE]
 G -. 几何 shadow 仅近似 .-> H[边际信息量]
 H -. 不能保证 .-> R
```

完整保留KLT不会固定关键帧、SfM或初始化分支。冻结源码中初始relativePose/SfM/alignment不直接读取q，q在后续投影优化/边缘化生效；故q不是前优化路径差异的直接输入，但最终轨迹仍有q混杂。[源码审计](source_code_mechanism_audit.md)。

## 完整六窗来源与信息结果

'''+numeric+'''
表中motion/photometric列为X/C中位倍率；两个logdet列为X与C各自跨帧中位，统一q=1。全部原q、trace、min eigen、weak direction、condition变化和per-candidate边际量在[information_geometry_summary.csv](information_geometry_summary.csv)；没有事后选择矩阵指标。q/长链/覆盖/视差及每次pre/post-init分布见[candidate_source_comparison.csv](candidate_source_comparison.csv)。

![来源差异](analysis-output/figures/01-source-contrasts.png)

此图说明四种来源排序互不等同。A02/A08 classical中位寿命较长，但XFeat的>=10次长链绝对数量仍更多；“XFeat都不持久”不准确。Bus C寿命并不更长，排除统一长寿命解释。所有候选均为原门筛过的合格集，未观察的被拒候选真实性不能倒推。

![信息shadow](analysis-output/figures/02-shadow-information.png)

q=1后A02/A08的XFeat集合信息proxy仍更高，不能归因于仅q增大。errorbar为帧p10–p90而非独立样本CI。最近Jacobian行高度重合不代表零信息；PSD增量可在约束带偏或相关时“变好”而轨迹变坏。真实VIO Fisher、scale-sensitive Schur信息和prior稳定性尚未取得。

## 初始化路径与诊断失败

'''+init_table+'''

![既有初始化关联](analysis-output/figures/04-initialization-association.png)

旧A02 replacement/delete提前约.898443s；新additive L-all反而更晚，不能套同一“早初始化有害”规则。Bus三次L-all同一首输出时刻而结果仍有23m级异常，时间戳/拒绝次数不能区分该异常；原日志中的线性求解失败也出现在B和C，次数不是干净的二值有害标签。A08相同时刻不同终局误差；内部scale/gravity仍Unknown。

只读日志后端先做A02/A08/Bus各1对新B A/A，总6次工程验证，0对通过；完整数值见[diagnostic_aa.csv](diagnostic_aa.csv)、[工程结果](diagnostic_engineering_results.csv)。按冻结容差停止27次正式诊断。A08本次发散发生在冻结版B，不能归因日志补丁；不能挑选更好重放替换原结果。新日志即使有内部值，也被证据门禁用。[失败说明](diagnostic_gate_report.md)。

## 水下真实性与在线可得性

![固定图像检查](analysis-output/figures/03-fixed-image-audit.png)

固定帧可见明显非均匀照明与不同空间分布，但没有独立场景标签。局部光度变化包含曝光、视点与纹理；gyro剩余flow包含真实平移和零偏/同步误差，距离B更远也可能使局部motion偏差更大。真实颗粒/焦散/折射类别Unknown。详[underwater_reliability_audit.csv](underwater_reliability_audit.csv)。

[first_admission_availability.csv](first_admission_availability.csv)表明首次公开/重入没有前一帧合格记录，双帧运动量缺失，不能填零；只有后续观测可计算本轮的双帧量。虽然在线私有tracker原则上可保存历史，本轮没有验证这些量在首次准入的判别性。单帧unit-depth信息在首次准入可算，单独结果见[first_admission_information_summary.csv](first_admission_information_summary.csv)，仍不是实际估计器风险。

## 统计、文献与算法进入门

本轮为描述性机制发现；六物理窗已知结果、三技术重复、COLMAP/proxy非独立GT。无p值、预测准确率、独立样本CI或泛化声明。原30对比的common support及胜负不变；新A/A未做APE/RPE比较。[统计附录](analysis-output/stats-appendix.md)、[分析限制](analysis_limitations.md)。

小型一手文献核查已经确认information-aware selection、normal-epipolar selection、初始化谱稳定性、IMU prior拒绝、水下patch/descriptor真实性分类、sensor reliability及深度不确定性先例；不能把age+parallax或logdet本身称创新。[literature_gap.md](literature_gap.md)给出逐项链接与访问边界；未搜索到同一组合不等于首创。

进入新risk-aware admission的五项门当前未同时满足：跨三个关键窗的统一机制未证；first-admission因果输入存在缺失；只有近似几何shadow、无有效内部状态；来源差异只部分解释；终局q混杂未剥离。局部motion一致排序不足以覆盖这些门，且同一排序也出现在无实用退化的控制窗，缺乏结果特异性。

## 结论与复查入口

解释选项以**E：多因素共同作用、六窗尚不能可靠分解**最符合证据；对已验证在线准入量则仍是F边界。已有部分初始化路径关联与信息proxy反例，故不是完全无数据，但不构成已确认的单一因果机制。

DECISION：**PARTIAL_MECHANISM**。

唯一下一步：'''+NEXT+'''

复查：[问题冻结](research_questions.md)、[一页事实表](evidence_boundary.md)、[特征字典](feature_dictionary.md)、[六窗机制表](window_mechanism_summary.csv)、[原日志事件](initialization_attempts.csv)、[分析包](analysis-output/analysis-report.md)、[决策](decision.json)。主提取脚本[analyze_observation_utility_v1.py](../../scripts/analyze_observation_utility_v1.py)，补充[admission审计](../../scripts/audit_observation_utility_admission.py)，[复现说明](reproduction.md)。大日志/逐观测gzip/二进制仅在本地runtime；未作Obsidian写回。
'''
 report=report.replace('报告发布commit与源身份分开。','补充分析源码'+audit_commit+'；报告发布commit与源身份分开。')
 (PAPER/'report.md').write_text(report)
 handoff='''# Observation utility / risk 独立交接

2026-09-08；COMPLETE；DECISION=PARTIAL_MECHANISM。

六个development窗只读机制审计完成，原72日志身份有效；2439共同输出帧，B/L-all/C-all观测级诊断、原q/q=1两套shadow信息、首次准入可得性和水下光度/运动检查均已归档。

核心：A02/Bus有初始化路径关联，但不能跨A08简化为时机机制；A02/A08 XFeat的shadow信息量较高仍退化；三关键窗局部motion偏差更高仅为线索，首次准入历史、真实场景标签及有效内部scale/gravity仍缺失。不推荐开发router。

6次新B A/A（3对）全部FAIL，0次正式diagnostic replay；A08这次发散的是冻结版B，不能单归因新增日志。原72结果未覆盖或改胜负，新6次工程失败单独保留。唯一下一步：'''+NEXT+'''

分支：exp/observation-utility-audit-v1-20260908；worktree：/home/ma/AQUA-FE_WS_observation_utility_v1；runtime：/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_observation_utility_audit_v1。
源证据：49c02471716e8ac960e35dd9dd44ef6fbb1428c6；旧A02补充：54cc31fa2ef455ac1e13cdb120cf4b4a2ed15731；审计/诊断源码：07e59b5（完整SHA见reproduction.md）；报告发布身份为本文件所属commit，不冒充运行源码。

[报告](../papers/frontend_observation_utility_audit_v1/report.md)、[decision](../papers/frontend_observation_utility_audit_v1/decision.json)、[六窗表](../papers/frontend_observation_utility_audit_v1/window_mechanism_summary.csv)、[A/A门](../papers/frontend_observation_utility_audit_v1/diagnostic_gate_report.md)、[字典](../papers/frontend_observation_utility_audit_v1/feature_dictionary.md)、[复现与限制](../papers/frontend_observation_utility_audit_v1/reproduction.md)。

没有新网络、增强、门、预算或新窗口；无原workspace/旧分支/外部后端写入，无merge/force push。所有本任务后端进程已结束；不得重放以选择更好结果。
'''
 handoff=handoff.replace('报告发布身份为本文件所属commit','补充分析源码：'+audit_commit+'；报告发布身份为本文件所属commit')
 (ROOT/'docs/CODEX_HANDOFF_OBSERVATION_UTILITY.md').write_text(handoff)
 print('REPORT_COMPLETE',len(src),'source rows',len(info),'info rows',flush=True)
if __name__=='__main__':main()
