# Learned-guided same-frame KLT recovery v1 — 完成

2026-09-09，分支 `exp/learned-klt-recovery-v1-20260909`；独立worktree `/home/ma/AQUA-FE_WS_learned_recovery_v1`。用户本轮明确授权最小实现和验证，替代前一轮仅接收候选的任务范围；旧实验不改。

**NO_LEARNED_INCREMENT；停止本版本，不交跨案例验证。** 48个受控图像对与三个200-raw自然片段全部完成，0次执行失败、0次后端新跑/复用。L受控正确835，C2488；L错误接受0/8371、不可见错误接受0/1839。自然同B失败事件C148/L8，L-only 0；L实际流11次恢复（10条ID），只有3次达到4次输出，另记REAL_RECOVERY_NOT_ESTABLISHED。自然物理身份Unknown，APE/RPE Not evaluated.。

协议及可执行恢复模块在冻结commit `915716d5e4d56bc4663125db061c5acc35ddadf9`；实现是局部XFeat运动预测＋原KLT点seeded LK，未复制邻近XFeat端点为旧ID，未改q。唯一前端版本，五项行为测试通过；原始失败与未来链均保留，没有阈值调整或选择性重跑。

入口：[短报告](../papers/frontend_learned_klt_recovery_v1/report.md)、[前端结果](../papers/frontend_learned_klt_recovery_v1/frontend_results.csv)、[完整事件](../papers/frontend_learned_klt_recovery_v1/recovery_events.csv)、[决定](../papers/frontend_learned_klt_recovery_v1/decision.json)、[冻结协议](../papers/frontend_learned_klt_recovery_v1/protocol.md)。三个固定样例面板保留空L-only组。运行明细仅本机 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_learned_klt_recovery_v1/`。

唯一下一步：封存本版本并结束。无PROMISING候选，不自动验证更多案例、调参、换网络或开启后端。Classical仍保留ADDITIVE_OPPORTUNITY_NOT_GENERALIZED / EXPANSION_STOPPED_AFTER_BATCH_A；旧source-neutral q/additive/continuation结果及停止规则保持冻结。
