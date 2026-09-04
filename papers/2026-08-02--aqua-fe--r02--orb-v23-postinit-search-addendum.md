---
type: results-report
date: 2026-08-02
experiment_line: aqua-fe
round: 2
purpose: orb-v23-postinit-search-addendum
status: complete
source_artifacts:
  - orb_v23_postinit_followup_20260802/analysis-output/analysis-report.md
  - orb_v23_postinit_followup_20260802/analysis-output/stats-appendix.md
  - orb_v23_postinit_followup_20260802/analysis-output/figure-catalog.md
  - orb_v23_postinit_followup_20260802/analysis-output/window_roster.csv
  - orb_v23_postinit_followup_20260802/analysis-output/formal_summary.csv
  - orb_v23_postinit_followup_20260802/analysis-output/texture_denominator.csv
  - orb_v23_postinit_followup_20260802/analysis-output/provenance.json
  - ../logs/orb_v23_mclab1_action_search_20260802.md
  - ../logs/orb_v23_mclab2_action_search_20260802.md
  - ../logs/history_scan_candidates_20260801.md
linked_experiments:
  - orb_v23_postinit_action_search_20260731/2026-08-01--orb-v23-postinit-action-search--handoff.md
linked_results:
  - 2026-07-31--aqua-fe--r01--project-progress-addendum.md
---

# AQUA-FE / Round 02 / ORB-v23 post-init search addendum / 2026-08-02

> 本文只记录 8 月 2 日 ORB-v23 后续搜索与审计。工作区未绑定 Obsidian，未执行 write-back。

## 1. Executive Summary

NTNU mclab1 `s60,d15` 在冻结 v23 合同下形成新的独立 strict trajectory-positive：n3
selector 的五臂四重复为 `20/20 status=ok`，reconstructed/online directional checks
为 `64/64`。NTNU mclab2 `s110,d10` 形成稳定 action-positive，但四项轨迹指标混合，
不能升格为 strict。

按唯一图像窗口去重，当前 ORB mechanism/action-positive 共 `5` 个：A10 `2400-2800`、
A02 `2800-3200`、A08 `4500-4660`、NTNU mclab2 `s110,d10`、NTNU mclab1 `s60,d15`。
其中 operational degraded/planar/low-grid 为 A02、A08，共 `2/5 = 40%`。若严格把低纹理
定义为 base KLT 明显低于 350 上限，则 `0/5`，不能把这五个窗口写成真正稀疏低纹理正例。

## 2. Experiment Identity and Decision Context

本轮回答两个问题：

1. post-init MapPoint -> assisted match -> natural assisted outlier -> pre-KF purge 是否能
   在第二个 NTNU 图像窗口中闭合；
2. selector/rearm 变体是否应继续扩大独立窗口分母。

答案分别是“mclab1 n3 可以闭合并改善四项轨迹指标”和“停止重复变体”。

## 3. Setup and Evaluation Protocol

所有运行固定 binary/library/runner、`q >= 0.9`、projection `4 px`、Hamming `100`、
pre-KF purge、CPU2、双后台 barrier、deterministic gate、ASLR off、audit capacity
`131072` 和 online export。每个正式候选使用五臂四重复，r4 交换 `full` 与
`full_unbounded` 顺序；APE/RPE 使用 `max_time_diff=0.06 s`、RPE `delta=1`。

独立统计单位是固定图像窗口，不是 selector、不重复的 seed 文件，也不是四次运行。

## 4. Main Findings

### mclab1 strict case

- n3: `39/39` accepted 且全部 post-init；`3/3` lineage 形成 MapPoint；7 assisted matches；
  2 assisted outliers；pre-KF `1/1` purge；145 scans。
- reconstructed full: APE/RPE `0.018007/0.062446`，native/drop `0.018122/0.062520`。
- online full: APE/RPE `0.035048/0.062985`，native/drop `0.052752/0.063240`。
- 相对 native/drop 的改善为 reconstructed `0.635%/0.118%`、online `33.561%/0.403%`；
  相对 unbounded 的四项也都下降；`64/64` directional checks 通过。

n6 是同一窗口的 robustness variant：虽然 action-positive，但 online metric-mixed，
不进入第二个独立窗口。

### mclab2 action case

- n3: `108/108` post-init；`3/3` MapPoint lineages；45 matches；16 outliers；`8/8` purge。
- reconstructed APE 改善但 RPE 恶化；online APE/RPE 均恶化相对 native/drop。
- n6 同一窗口，action `41/13/7`，只作为 selector robustness。

因此 mclab2 证明了跨数据 action reachability，不证明 strict trajectory accuracy。

## 5. Statistical Validation

每个窗口只有 `n=1` 独立 interval。四重复只描述 deterministic branch reproducibility；
不执行 t-test、Wilcoxon、置信区间或人口效应量。机器可读完整数值见
`orb_v23_postinit_followup_20260802/analysis-output/formal_summary.csv`。

## 6. Texture Denominator

| 分母口径 | 窗口数 | operational degraded/low-grid | sparse base-KLT |
|---|---:|---:|---:|
| 全部 mechanism-positive | 5 | 2 (`40%`) | 0 (`0%`) |
| 项目 promoted strict label（含 A10） | 3 | 1 (`33.3%`) | 0 (`0%`) |
| 更严格 all-control repeatwise audit | 2 | 1 (`50%`) | 0 (`0%`) |

A02/A08 的“低纹理”是 operational degraded/planar/low-grid 标签；它们的 base KLT 仍
接近饱和上限，不能与 Cave/AFRL 稀疏 base-KLT regime 混称。

## 7. Failure Cases / Limitations

- action 不充分保证精度：A08、mclab2 都有稳定 purge 但轨迹混合。
- mclab2/mclab1 的 n3/n6 是同一图像区间的 selector 对照，不增加窗口分母。
- 搜索队列按机制条件筛选，`3/5` 或 `2/5` 都不是部署成功概率；它们是不同 strict 口径下的描述性计数。
- 稀疏 GT、地图分支和 RPE 的 `delta=1` 解释边界仍需在论文中明确。
- mclab2 的 `seed_export_stats.json` 记录 feature-to-image 最大时间差 `49,999,500 ns`；
  ORB `cam0_times` 选中的时间仍精确匹配，保留该对齐 caveat。
- 既有最终 roster 把 A10 标成 strict，A10 原始 formal 报告对 unbounded 是 `3/4`；本 addendum
  保留项目 promoted 标签，同时公开更严格 all-control audit 分母为 2。

## 8. What Changed Our Belief

这轮把先前“NTNU 只有 reachability/null 边界”的判断推进为：同一冻结机制在 NTNU 的另一
独立窗口可以闭合 purge 链并产生严格轨迹改善。但 mclab2 的混合结果同时说明：
`MapPoint + assisted match + purge` 是必要的作用机会，不是充分的精度保证。当前证据也
不支持“ORB v23 解决真正稀疏低纹理”这一更强主张。

## 9. Next Actions

1. 停止 mclab1/mclab2 的 rearm、dose 和 selector 变体重复。
2. 将 mclab1 加入正式 ORB strict evidence；将 mclab2、A08、A10 作为 graded action/aggregate
   boundary evidence。
3. 论文正文同时报告 `5` 个 mechanism-positive、项目 strict `3`、all-control audit `2`，以及
   A10 的 `3/4` caveat，避免混淆分母。
4. 不再把这些窗口包装为 sparse-base low-texture positive；低纹理主张需要独立的稀疏
   base-KLT 候选和同一冻结合同。

## 10. Artifact and Reproducibility Index

- [follow-up analysis bundle](orb_v23_postinit_followup_20260802/)
- [mclab1 report](../logs/orb_v23_mclab1_action_search_20260802.md)
- [mclab2 report](../logs/orb_v23_mclab2_action_search_20260802.md)
- [deduplicated roster snapshot](../logs/orb_v23_postinit_search_20260802_final.md)
- [roster audit note](../logs/orb_v23_postinit_search_20260802_audit_note.md)
- [historical candidate scan](../logs/history_scan_candidates_20260801.md)
