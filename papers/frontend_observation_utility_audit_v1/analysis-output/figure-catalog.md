# 图目录与解释

- 01-source-contrasts.png：来源的数量、寿命、运动、光度倍率；data=candidate_source_comparison.csv/all。读者应注意指标排序相互冲突，尤其Bus寿命与A02/A08光度；削弱单一quality排序。对数轴，虚线1，无CI，绝对数见表。
- 02-shadow-information.png：三个关键窗两模型q=1的集合logdet；data=information_geometry_summary.csv/all/unit_q。点为帧中位，须注明p10–p90非CI。XFeat信息proxy更大仍未净收益，说明模型缺少无偏/真实性/初始化状态约束，不证明零信息。
- 03-fixed-image-audit.png：固定output10及中点原图和候选位置；data=image_audit_identity.json及锁定原bag/source。不是按效果挑图；可见照明/空间分布差异，但无真实颗粒/焦散标签。静态图不能证明非刚体运动。
- 04-initialization-association.png：原三技术重复首输出延迟与最终Sim3拟合；data=existing_initialization_summary.csv。A02/Bus路径变化而A08时刻相同；同一时刻不代表同一数值初始化。最终拟合scale绝不是内部scale。

图的作用是呈现机制反例与证据缺口，不是证明在线分类准确率。审阅需检查窗口/来源、每根误差线含义、q/阶段/单位及否定强结论。
