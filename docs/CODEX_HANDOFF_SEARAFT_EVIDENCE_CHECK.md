# SEA-RAFT 对应点图像证据验证 — 完成

**EVIDENCE_GATE_NOT_SUPPORTED**。新网络推理0、训练0、VINS0；旧 `CONTROLLED_GAIN_ONLY` 保持不变。完整独立任务：[task_instructions.md](../papers/frontend_searaft_evidence_check_v1/task_instructions.md)；冻结协议：[protocol.md](../papers/frontend_searaft_evidence_check_v1/protocol.md)。输入 commit `a2f3bedcc2e4f98bd18f99a3601d70433de42aa7`；本轮协议冻结 commit `12310f47e31b86764bb67e2920bc9171e0c38391`。

完成48对既有图像的固定patch评分：24对校准、24对检查，检查仅执行一次。原预测、FB、真值和分母不变；原2857个自然事件全部检查，原61个S-only关系不重定义；26个固定唯一事件完成视觉复核。执行进程已结束，无数据阻塞。

检查部分 S0→S1：错误199→18，正确3321→3276（保留98.64%），接受精度99.45%；S1相对C0/C1正确恢复率增加61.49/61.82个百分点，large与illumination_blur仍在三序列保有优势。但不可见误收18/940=1.91%，超过固定1%门，故结束本版本。人工遮挡矩形内误收160→0，剩余18为14个遮挡patch guard与4个图像边界guard；不更改旧标签或放宽门。

自然原S-only保留 A02/A08/H02=8/5/32；原三步支撑保留0/0/7。H02原20例复核结构支持/明确矛盾/无法判断=3/0/17；保留7例中为3/0/4。这20例全部是C/S端点≤2px但旧门接受不同，不能写成传统方法没有预测出位置。结构支持、三步普通LK与没有明确矛盾均不是独立物理GT；自然身份、真实漂移 Unknown，后端收益和系统安全 Not evaluated.。

结果：[报告](../papers/frontend_searaft_evidence_check_v1/report.md)、[受控表](../papers/frontend_searaft_evidence_check_v1/evidence_results.csv)、[自然事件/复核](../papers/frontend_searaft_evidence_check_v1/natural_event_review.csv)、[决定](../papers/frontend_searaft_evidence_check_v1/decision.json)。固定函数：`uw_frontend/tracking/correspondence_evidence.py:check_correspondence_evidence`。5项数值检查及既有坐标/标签/三步记录一致性检查通过。

工作区 `/home/ma/AQUA-FE_WS_searaft_screening_v1`；分支 `exp/searaft-evidence-check-v1-20260910`。独立本地分数缓存 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_evidence_check_v1`；原图从旧runtime只读复用，未上传图像bag、权重或密集flow。

唯一汇总恢复命令（不重新评分）：在上述工作区执行 `PYTHONPATH=. /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/env/bin/python scripts/run_searaft_evidence_check.py --finalize`。`--run` 因runtime已存在而拒绝再次执行。

唯一下一步：封存本版本，保留减少误收、保住测量优势与H02局部结构线索；不调第二组阈值、不直接集成、不扩展。
