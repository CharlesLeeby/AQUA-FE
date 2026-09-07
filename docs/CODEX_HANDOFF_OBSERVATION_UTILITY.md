# Observation utility / risk 独立交接

2026-09-08；COMPLETE；DECISION=PARTIAL_MECHANISM。

六个development窗只读机制审计完成，原72日志身份有效；2439共同输出帧，B/L-all/C-all观测级诊断、原q/q=1两套shadow信息、首次准入可得性和水下光度/运动检查均已归档。

核心：A02/Bus有初始化路径关联，但不能跨A08简化为时机机制；A02/A08 XFeat的shadow信息量较高仍退化；三关键窗局部motion偏差更高仅为线索，首次准入历史、真实场景标签及有效内部scale/gravity仍缺失。不推荐开发router。

6次新B A/A（3对）全部FAIL，0次正式diagnostic replay；A08这次发散的是冻结版B，不能单归因新增日志。原72结果未覆盖或改胜负，新6次工程失败单独保留。唯一下一步：先做冻结 B 的回放确定性与日志侵入性审计，查清本次 A08 冻结版异常后再恢复初始化内部诊断；暂不开发新的 admission/router。

分支：exp/observation-utility-audit-v1-20260908；worktree：/home/ma/AQUA-FE_WS_observation_utility_v1；runtime：/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_observation_utility_audit_v1。
源证据：49c02471716e8ac960e35dd9dd44ef6fbb1428c6；旧A02补充：54cc31fa2ef455ac1e13cdb120cf4b4a2ed15731；审计/诊断源码：07e59b5（完整SHA见reproduction.md）；补充分析源码：54ac8850121ecae38289b629bd19310b4fdc0426；报告发布身份为本文件所属commit，不冒充运行源码。

[报告](../papers/frontend_observation_utility_audit_v1/report.md)、[decision](../papers/frontend_observation_utility_audit_v1/decision.json)、[六窗表](../papers/frontend_observation_utility_audit_v1/window_mechanism_summary.csv)、[A/A门](../papers/frontend_observation_utility_audit_v1/diagnostic_gate_report.md)、[字典](../papers/frontend_observation_utility_audit_v1/feature_dictionary.md)、[复现与限制](../papers/frontend_observation_utility_audit_v1/reproduction.md)。

没有新网络、增强、门、预算或新窗口；无原workspace/旧分支/外部后端写入，无merge/force push。所有本任务后端进程已结束；不得重放以选择更好结果。
