# SEA-RAFT screening v1 — 完成：CONTROLLED_GAIN_ONLY

当前任务已完成并停止，不再等待任何“上一份提示词”。完整独立合同：[task_instructions.md](../papers/frontend_searaft_screening_v1/task_instructions.md)；冻结判据：[protocol.md](../papers/frontend_searaft_screening_v1/protocol.md)。旧7d44681阻塞检查点保存在本实验checkpoints/目录。

**指定权重实际加载：是；正式受控48/48对、自然528个需要的相邻对（3×200raw）、接口2对均完成。** 一个成功模型实例完成1156次正/反向forward，0训练/0VINS/1checkpoint。FP32、iters4、scale−1、batch1、GPU0，原尺寸未启用640备用。首次HF strict的共享BN别名兼容失败有日志，同一HF权重恢复同值别名后由官方本地入口加载，全部472状态张量精确匹配。实际模型身份及两种文件SHA见model_lock.json。

受控large在A08/H02、illumination_blur在三序列通过；outside_occluded全部失败。共同B失败集S正确6525/错误309，C_common正确2672/错误66；S全部错误均为不可见点（309/1839）。自然S-only A02/A08/H02=9/5/47，三步离线连续性通过0/0/20；H02局部机会保留，但预冻结≥2序列各≥5门未过，最终CONTROLLED_GAIN_ONLY。自然物理身份、真实漂移、VINS收益和系统安全Unknown / Not evaluated.，不能把S-only或三步普通LK当真值。

入口：[短报告](../papers/frontend_searaft_screening_v1/report.md)、[受控结果](../papers/frontend_searaft_screening_v1/controlled_results.csv)、[逐组判定](../papers/frontend_searaft_screening_v1/controlled_comparison.csv)、[自然事件](../papers/frontend_searaft_screening_v1/natural_results.csv)、[决定](../papers/frontend_searaft_screening_v1/decision.json)。原始预测与过滤后结果分开，逐点稀疏值/计时及12固定样例均保留。

工作区`/home/ma/AQUA-FE_WS_searaft_screening_v1`；分支`exp/searaft-screening-v1-20260910`。模型/协议冻结commit2833851648e84cf0c1bf0cd1f10406455878331e。推理进程已退出；全部本地缓存及失败日志在`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1`，未上传模型/图像/密集flow。

唯一汇总复现命令（无需推理）：在此worktree执行`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/env/bin/python scripts/finalize_searaft_screening.py`。可执行推理接口为uw_frontend/matchers/searaft_points.py:SeaRaftPoints.predict_points；正式runner保留已完成目录防覆盖，不重复启动。

唯一下一步：封存本轮结果，不直接系统集成、不追加模型/阈值/片段。既有受控能力及H02局部机会可供主规划窗口读取，但本轮没有PROMISING发布条件。旧XFeat与classical等实验保持封存。

另行授权的新任务：[SEA-RAFT 对应点图像证据验证](CODEX_HANDOFF_SEARAFT_EVIDENCE_CHECK.md)。旧筛选结果与 CONTROLLED_GAIN_ONLY 保持不变。
