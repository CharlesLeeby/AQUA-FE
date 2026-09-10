# SEA-RAFT 真实对应验证 — 查询已冻结

完整任务：[task_instructions.md](../papers/frontend_searaft_real_correspondence_v1/task_instructions.md)；设置：[protocol.md](../papers/frontend_searaft_real_correspondence_v1/protocol.md)。分支 `exp/searaft-real-correspondence-v1-20260911`；工作区 `/home/ma/AQUA-FE_WS_searaft_screening_v1`。

12对真实帧、92个查询已冻结：[pair_query_manifest.csv](../papers/frontend_searaft_real_correspondence_v1/pair_query_manifest.csv)。A02 offset120与A08 offset40的q1为空格，两种gap均不补选。旧输出仅含奇数公开帧，源点从39/119的已存B状态各恢复一步原KLT/GFTT，未用目标预测选点。盲态图和空参考模板已在新C/S预测前落盘。

阶段：正式推理尚未启动。独立人工/标靶参考尚未找到，不能由旧Assistant判断或算法输出替代。旧CONTROLLED_GAIN_ONLY与EVIDENCE_GATE_NOT_SUPPORTED不变。

唯一下一步：运行`scripts/run_searaft_real_correspondence.py predict`完成12对，再交付具体盲态核对文件；不追加合成测试或后端。
