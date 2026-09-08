# Learned-guided same-frame KLT recovery v1

2026-09-09，状态PROTOCOL_FROZEN，实验尚未运行。独立分支exp/learned-klt-recovery-v1-20260909，worktree=/home/ma/AQUA-FE_WS_learned_recovery_v1；runtime=/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_learned_klt_recovery_v1。

本轮用户授权实现原KLT点的学习运动初值+LK精化；不是重开q消融或添加更多学习新点。现有邻近匹配端点关联及旧SP/LG occurrence-preserving适配器均不等价。复用lost入口与原补点，独立模块不修改旧KLT实现。五个关键测试通过；结果Not evaluated.。

先跑固定A02/A08/H02各200raw帧的受控正确性与自然片段比较，门限见[protocol](../papers/frontend_learned_klt_recovery_v1/protocol.md)和input_manifest.json。前端没有学习增量立即结束；通过才允许A02/H02三臂各三重复、最多18次后端。其他窗口不重复开发；只有最终PROMISING_LEARNED_RECOVERY才交给验证窗口。当前发现外部VINS作业，本任务不启动或终止其后端。
