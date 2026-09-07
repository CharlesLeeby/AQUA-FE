# 统计附录

6个目的性、已知结果物理窗口，非随机样本；三solver repeats仅技术波动。原pair-specific common support全部PASS，精度判定只引用原30行；新A/A未做APE/RPE比较。

source表为观测级n/min/p10/median/p90/max/mean；最终寿命按公开ID、窗口右截断。information表按帧聚合，individual_logdet_median_median是“先帧内候选中位，再跨帧中位”，不能当成全部候选混合中位。每窗各源和每技术重复pre/post-init均给全分布；阶段标签为事后分组。

主effect size使用窗口内X/C倍率及原对比APE/RPE差，技术重复给全范围。巨大观测N高度相关，不计算显著性、bootstrap CI或独立成功率；这些统计Not evaluated.且不适合此发现集。没有多重检验p值可校正，也不从多个矩阵指标中选取赢家；两模型×两q映射×trace/logdet/min-eigen/weak-direction/condition全部保留。

单位深度假设、ridge公式、gyro时间/零偏、缺失值、first-admission可用性与q模型差异见research_questions.md、feature_dictionary.md和analysis_limitations.md。
| 窗口 | X/C发布量 | X/C寿命中位 | X/C运动偏差 | X/C光度变化 | X/C flow logdet(q=1) | X/C epi logdet(q=1) |
|---|---|---|---|---|---|---|
| A09 | 42018/22392 | 7/4 | 1.34592 | 0.857167 | 3.12958/1.32871 | 0.953621/0.619298 |
| A02 | 116129/41339 | 5/15 | 1.66452 | 0.79424 | 6.1644/2.42763 | 2.50309/1.09441 |
| Bus | 2963/2305 | 2/1 | 2.3537 | 1.58435 | 0.183774/0.143073 | 0.0700311/0.0638832 |
| A08 | 130866/87401 | 8/18 | 1.22185 | 0.80699 | 5.41922/3.55727 | 2.07912/1.60534 |
| Cemetery | 10977/6656 | 2/2 | 1.16334 | 0.653469 | 0.462909/0.329521 | 0.133514/0.162671 |
| H07 | 20346/6422 | 3/2 | 1.53643 | 0.69881 | 1.47383/0.255816 | 0.485371/0.0844755 |
