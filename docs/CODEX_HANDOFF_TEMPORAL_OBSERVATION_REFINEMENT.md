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
