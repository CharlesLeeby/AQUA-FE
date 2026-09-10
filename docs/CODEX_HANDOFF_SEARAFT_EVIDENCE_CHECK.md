# SEA-RAFT 对应点图像证据验证 — 协议冻结

完整任务：[task_instructions.md](../papers/frontend_searaft_evidence_check_v1/task_instructions.md)；固定主规则及划分：[protocol.md](../papers/frontend_searaft_evidence_check_v1/protocol.md)。输入 commit `a2f3bedcc2e4f98bd18f99a3601d70433de42aa7`；旧 CONTROLLED_GAIN_ONLY 不变。

阶段：协议落盘，尚未进行正式 patch 评分。已定位全部图像和预测缓存；新网络推理0、训练0、VINS0。工作区 `/home/ma/AQUA-FE_WS_searaft_screening_v1`；分支 `exp/searaft-evidence-check-v1-20260910`。

下一步：数值检查后执行固定24对校准/24对检查，主规则用于全部原自然事件，完成最多30例图像复核。入口脚本将为 `scripts/run_searaft_evidence_check.py`；不得调用旧网络 runner。结果当前 Not evaluated.；自然物理身份 Unknown。
