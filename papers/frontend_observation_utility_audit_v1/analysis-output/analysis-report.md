# 严格分析包 / observation utility audit v1

科学单位：六物理development窗；原72次技术重复日志、2439个共同输出时刻、B与两来源观测。新6次B A/A为工程验证，正式机制diagnostic replay=0。没有训练、阈值搜索或新候选生成。

| 窗口 | X/C发布量 | X/C寿命中位 | X/C运动偏差 | X/C光度变化 | X/C flow logdet(q=1) | X/C epi logdet(q=1) |
|---|---|---|---|---|---|---|
| A09 | 42018/22392 | 7/4 | 1.34592 | 0.857167 | 3.12958/1.32871 | 0.953621/0.619298 |
| A02 | 116129/41339 | 5/15 | 1.66452 | 0.79424 | 6.1644/2.42763 | 2.50309/1.09441 |
| Bus | 2963/2305 | 2/1 | 2.3537 | 1.58435 | 0.183774/0.143073 | 0.0700311/0.0638832 |
| A08 | 130866/87401 | 8/18 | 1.22185 | 0.80699 | 5.41922/3.55727 | 2.07912/1.60534 |
| Cemetery | 10977/6656 | 2/2 | 1.16334 | 0.653469 | 0.462909/0.329521 | 0.133514/0.162671 |
| H07 | 20346/6422 | 3/2 | 1.53643 | 0.69881 | 1.47383/0.255816 | 0.485371/0.0844755 |

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
