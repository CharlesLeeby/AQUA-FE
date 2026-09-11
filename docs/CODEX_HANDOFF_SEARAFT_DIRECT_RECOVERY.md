# SEA-RAFT direct recovery ablation — COMPLETE

**UNSAFE_OR_UNRESOLVED. 当前SEA-RAFT当帧恢复组合线结束。**

分支 `exp/searaft-direct-recovery-v1-20260911`；冻结基点 `1138fab635910d3e1c34d57f99dab84c6ff8e9f5`；协议/前端源码 `4b74161e178ef37e1c39d140b3240303921f984b`。最终发布为包含本文件的commit。

D只删除强LK重试，普通KLT失败直接用冻结SEA-RAFT恢复，独立因果轨迹；强LK调用0，原q/证据门/时间/速度/公开合同不变。

- H02未保住收益：APE中位D0.350326m、本轮B0.102702m、旧R0.026602m。
- A02仅缓解旧R退化：D0.506198m、旧R1.157391m，但仍严重差于本轮B0.145545m。
- 两窗D全部重复的APE/RPE均差于本轮B最差重复，六次D均触发单次严重护栏；H02 D另有重复不稳定。
- 12次全新B/D回放，0历史B复用，0旧C/R重跑，0追加重复。新增1069对/2138方向调用，完整缓存660对；一次实际模型加载。前端1093.51s，预测采样232.27s（含加载），后端合计779.89s。
- 12次接收完整、初始化一次，无failure/reset；共同支撑/evo通过。运行正常不等于定位正确。逐点物理真值Unknown，初始化/GFTT未隔离，COLMAP/proxy非独立GT，旧C/R比较跨批次。

[报告](../papers/frontend_searaft_direct_recovery_v1/report.md) · [全部比较内重复](../papers/frontend_searaft_direct_recovery_v1/results.csv) · [比较](../papers/frontend_searaft_direct_recovery_v1/comparison.csv) · [决策](../papers/frontend_searaft_direct_recovery_v1/decision.json) · [任务与冻结协议](../papers/frontend_searaft_direct_recovery_v1/protocol.md)

运行目录 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_direct_recovery_v1`，缓存/12次运行/原始日志全部保留在本地。前端和后端均已结束；不要重新启动。旧实验、18次运行及CONTROLLED_GAIN_ONLY/EVIDENCE_GATE_NOT_SUPPORTED/REFERENCE_PENDING均冻结不变。

唯一下一步：封存此消融并结束当前当帧恢复组合线；不自动改顺序、添门、调参、换模型/窗口或要求人工标注。
