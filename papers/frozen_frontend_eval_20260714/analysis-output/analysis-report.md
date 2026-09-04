# 冻结前端统一三路评测分析

## 分析问题与口径

- 比较：fresh full、从同一 full bag 删除 whole learned lineage 的 drop、独立 fresh KLT。
- 主要指标：SE(3) 对齐 APE RMSE；次要指标：1 s 平移 RPE RMSE；时间匹配上限 0.6 s。
- 独立单位：manifest 中不重叠的时间窗口簇。fresh 队列共 20 簇；AFRL FR70-100 仅作 existing-bag replay。
- 主胜定义：full 有效且 APE 不差于 drop 和 KLT；no-harm 定义：full 相对 KLT 的 APE 退化不超过 5%。

## 关键结果

1. 预选主队列为 9/9 (100.0%, 95% CI 70.1-100.0%) APE 胜，双指标胜 9/9。其中 A02_2800-3200 未触发 learned lineage，是 no-harm tie；其余 8/8 learned-active 主窗口均严格优于 KLT 与 drop。
2. 所有 learned-active fresh 窗口中，full 相对 KLT 的 APE 胜率为 10/11 (90.9%, 95% CI 62.3-98.4%)，双指标胜率为 9/11。APE 相对改善中位数为 25.3%，簇 bootstrap 95% CI 为 3.8% 至 61.0%。
3. full 相对 whole-lineage drop 在 learned-active fresh 窗口上为 11/11 APE 改善；中位改善 40.6%，bootstrap 95% CI 14.5% 至 93.1%。
4. 唯一超过 5% 的 fresh 反例是 A09_5000-5400：full/KLT APE 为 1.360408/1.082993 m，full 退化 25.6%。因此证据支持“不弱于 KLT，且经常改善”，不支持“普遍优于 KLT”。
5. learned-inactive fresh 窗口 no-harm 为 9/9。A02_8600-9000、A08_4480-4680 和 H02_2400-2800 的并发/时序异常 run 已保留审计，并由空闲、同配置 replay 替换；最终三路结果收敛。
6. 全部 fresh arm 的 hard failure 为 full/drop/KLT = 0/20、0/20、0/20。但 solver-risk 窗口率分别为 10/20、9/20、10/20，不能宣称系统已普遍稳定。
7. AFRL existing-bag full/drop/KLT APE 为 0.189273/0.189303/0.189304 m，无 solver failure；差异仅 0.016%，作为 no-harm 控制，不作为 fresh 学习正例。

## 队列汇总

| 队列 | n | APE 胜 | 双指标胜 | no-harm | full hard failure | full solver risk |
| --- | --- | --- | --- | --- | --- | --- |
| 主队列 | 9 | 9/9 | 9/9 | 9/9 | 0/9 | 4/9 |
| Secondary | 3 | 2/3 | 1/3 | 2/3 | 0/3 | 3/3 |
| Fresh stress | 8 | 7/8 | 6/8 | 8/8 | 0/8 | 3/8 |
| 全部 fresh | 20 | 18/20 | 16/20 | 19/20 | 0/20 | 10/20 |
| Learned-active fresh | 11 | 10/11 | 9/11 | 10/11 | 0/11 | 6/11 |
| Learned-inactive fresh | 9 | 8/9 | 7/9 | 9/9 | 0/9 | 4/9 |

## Learned-active 逐簇结果

| 窗口 | 数据族 | learned IDs | full APE | drop APE | KLT APE | full vs KLT | 双指标胜 | full solver risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a05_3300_3700 | aqualoc_archaeo | 8 | 0.358970 | 0.604050 | 0.373172 | 3.8% | 是 | 否 |
| a07_10800_11200 | aqualoc_archaeo | 10 | 0.126737 | 0.351417 | 0.410703 | 69.1% | 是 | 是 |
| a08_4500_4660 | aqualoc_archaeo | 2 | 0.149770 | 0.179440 | 0.200567 | 25.3% | 是 | 否 |
| a09_6000_6200 | aqualoc_archaeo | 1 | 0.110516 | 27.369146 | 4.702022 | 97.6% | 是 | 否 |
| fjord1_s83_d10 | ntnu | 3 | 0.072807 | 1.059293 | 0.186594 | 61.0% | 是 | 否 |
| mclab1_s60_d15 | ntnu | 8 | 0.440272 | 14.873224 | 0.500314 | 12.0% | 是 | 否 |
| cirs_s575_d30 | cirs | 5 | 1.092839 | 2.388024 | 2.410345 | 54.7% | 是 | 是 |
| cirs_s900_d30 | cirs | 19 | 0.876939 | 1.025768 | 0.926658 | 5.4% | 是 | 是 |
| a09_5000_5400 | aqualoc_archaeo | 7 | 1.360408 | 1.394116 | 1.082993 | -25.6% | 否 | 是 |
| a02_7600_8000 | aqualoc_archaeo | 13 | 0.066754 | 0.067313 | 0.095743 | 30.3% | 否 | 是 |
| mclab2_s110_d10 | ntnu | 20 | 0.024429 | 0.034513 | 0.025279 | 3.4% | 是 | 是 |

## Fresh stress / no-harm

| 窗口 | 实际 profile | learned IDs | full APE | KLT APE | no-harm | solver failures F/D/K |
| --- | --- | --- | --- | --- | --- | --- |
| h02_2400_2800 | klt_safe_fallback | 0 | 0.225773 | 0.225773 | 是 | 3/3/3 |
| a09_4000_4400 | klt_safe_fallback | 0 | 1.062559 | 1.062574 | 是 | 0/0/0 |
| a02_8600_9000 | klt_safe_fallback | 0 | 0.089505 | 0.089505 | 是 | 11/11/11 |
| a08_4480_4680 | klt_safe_fallback | 0 | 0.298231 | 0.298233 | 是 | 0/0/0 |
| fjord5_s110_d10 | klt_safe_fallback | 0 | 6.929610 | 6.929610 | 是 | 0/0/0 |
| cirs_s450_d30 | klt_safe_fallback | 0 | 1.271667 | 1.271667 | 是 | 0/0/0 |
| cirs_s840_d30 | klt_safe_fallback | 0 | 1.482677 | 1.482677 | 是 | 2/2/2 |
| cirs_s960_d30 | klt_safe_fallback | 0 | 1.831380 | 1.831380 | 是 | 0/0/0 |

## Claim Candidates

- Claim:
  - Source evidence: learned-active fresh 10/11 APE 胜；覆盖 AQUALOC、NTNU、CIRS 三个数据族。
  - Allowed wording: “在预先选定的低纹理水下窗口中，learned-seeded KLT 前端通常不弱于 KLT，并经常降低 VINS APE。”
  - Forbidden stronger wording: “learned features broadly/universally improve VINS”或“所有低纹理场景都优于 KLT”。
  - Uncertainty: 主队列经过历史筛选，且每簇只有一次有效 replay；A09_5000-5400 为真实反例。
  - Next check: 在未参与 profile 设计的新数据或整段序列上盲测。
  - Decision: keep with weakened wording

- Claim:
  - Source evidence: learned-active fresh 11/11 的 full APE 低于 whole-lineage drop。
  - Allowed wording: “在本评测矩阵的 learned-active 窗口中，保留 learned lineage 比删除完整 lineage 获得更低 APE。”
  - Forbidden stronger wording: “任意 learned 点都会改善后端”。
  - Uncertainty: drop 会删除后续 KLT 传播的整条 lineage，表示轨迹级贡献，不是单点质量因果。
  - Next check: 增加等数量随机 KLT lineage 删除对照。
  - Decision: keep

- Claim:
  - Source evidence: learned-inactive fresh 9/9 满足 5% no-harm。
  - Allowed wording: “冻结 arbitration 在未接受 learned lineage 的控制窗口中保持 KLT 级表现。”
  - Forbidden stronger wording: “所有普通场景绝对无害”。
  - Uncertainty: solver-risk 仍存在，且 no-harm 是窗口级 APE 定义。
  - Next check: 增加长序列和跨运行重复。
  - Decision: keep
