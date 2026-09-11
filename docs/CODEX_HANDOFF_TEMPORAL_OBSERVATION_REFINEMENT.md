# 水下时序观测坐标精化 v1

新任务独立于已停止的 SEA-RAFT 当帧恢复线。

- [报告](../papers/frontend_temporal_observation_refinement_v1/report.md)
- [决策](../papers/frontend_temporal_observation_refinement_v1/decision.json)
- [冻结协议](../papers/frontend_temporal_observation_refinement_v1/protocol.md)
- [数据划分](../papers/frontend_temporal_observation_refinement_v1/data_split.json)

工作区 `/home/ma/AQUA-FE_WS_temporal_observation_refinement_v1`；分支 `exp/temporal-observation-refinement-v1-20260911`。

最终状态：**SUPERVISION_UNAVAILABLE**。小模型211,554参数、7项关键测试通过；有效标签0、P/T训练0、VINS回放0。训练/推理内核已实现，未产生可运行的已训练方法。

- [训练状态表](../papers/frontend_temporal_observation_refinement_v1/training_summary.csv)
- [测量状态表](../papers/frontend_temporal_observation_refinement_v1/measurement_results.csv)

唯一下一步：取得并验证MIMIR深度编码/几何修复后再训练。原始补取与诊断留在 `/mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1`；没有上传原始数据或模型权重。


## 2026-09-12：替代监督来源（TartanAir V1）
用户明确授权监督来源替换，算法合同不变。新分支exp/temporal-observation-refinement-tartanair-v1-20260912，新工作区/home/ma/AQUA-FE_WS_temporal_refinement_tartanair_v1。原MIMIR SUPERVISION_UNAVAILABLE不覆盖。

[新协议](../papers/frontend_temporal_observation_refinement_tartanair_v1/protocol.md) · [新划分](../papers/frontend_temporal_observation_refinement_tartanair_v1/data_split.json) · [新决策](../papers/frontend_temporal_observation_refinement_tartanair_v1/decision.json)。最终状态：**NO_TEMPORAL_REFINEMENT_GAIN**。替代监督已可用，原模型完成P/T各一次5,000更新（验证最优step4000/4500）。训练279,305有效标签/68,302不同轨迹；固定测试166,791有效标签/84,061不同轨迹，B/P/T EPEp95=1.6136/1.6895/1.6312px。T/P时序变化p95仅下降1.24%，未到5%；末100帧块也回归，原系统进入条件未通过。新增VINS=0，真实feature-bag适配/APE/RPE **Not evaluated.**

[实际训练报告](../papers/frontend_temporal_observation_refinement_tartanair_v1/report.md) · [训练表](../papers/frontend_temporal_observation_refinement_tartanair_v1/training_summary.csv) · [测量表](../papers/frontend_temporal_observation_refinement_tartanair_v1/measurement_results.csv) · [学习曲线](../papers/frontend_temporal_observation_refinement_tartanair_v1/learning_curves.csv)。可用缓存生成器 scripts/prepare_tartanair_temporal_cache.py，模型和通用推理脚本相对39d1662不变；本地权重、完整曲线、缓存、三臂观测位于 /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/{training,cache,evaluation}。

实际几何12组检查与11项关键测试通过；首次几何诊断分母错误及修正完整保留，未更换序列或调整判据。B/P/T209,862条观测的ID/帧序/q/sigma一致性与误差重算通过。较老轨迹局部p95改善与总体失败均保留；模拟数据不构成水下实测证据。

唯一下一步：停止并归档本固定版本；不自动第二轮训练、改损失/数据或进行A02/H02回放。上方旧MIMIR SUPERVISION_UNAVAILABLE及其历史下一步原样保留，不代表本轮仍等待MIMIR修复。
