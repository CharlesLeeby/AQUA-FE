# SEA-RAFT 真实对应验证 — REFERENCE_PENDING

**推理与材料完成：12/12对、92个固定查询；独立参考确认0。** 完整任务：[task_instructions.md](../papers/frontend_searaft_real_correspondence_v1/task_instructions.md)；固定协议：[protocol.md](../papers/frontend_searaft_real_correspondence_v1/protocol.md)。查询/盲态材料在新预测前冻结于 `637322c3c1b3c4450610b16b669a4c6840a8e0c0`。旧 CONTROLLED_GAIN_ONLY 和 EVIDENCE_GATE_NOT_SUPPORTED 保持不变。

同一spring-M实际加载一次，472状态张量完整匹配，新增12对正反向推理共24次forward；复用a2f3bed模型设置及4d061b8原patch函数。0训练/新权重/VINS/合成测试。输入、旧结果均未改；推理进程已退出，没有运行阻塞。

原相邻t+1所有46查询均被C1/S1接受；A02/A08的t+10各15查询也共同接受。H02 t+10为C1接受9/16、S1接受12/16，其中C1独有1、S1独有4；一例是端点≤2px的接受门差异。**接受不等于正确**：没有独立参考时EPE/正确率/误收/独有正确全部Not evaluated.，comparison留空而非填0或TIE。本批追加patch门没有改变原C0/S0接受集合。

用户待核对：[reference_annotations.csv](../papers/frontend_searaft_real_correspondence_v1/reference_annotations.csv) 的92行。六张盲态图与待核对ID：

| 源组 | 源query ID | 目标offset | 盲态图 |
|---|---|---|---|
| A02_s040 | q1–q8 | 41、50 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/A02_s040.png) |
| A02_s120 | q2–q8 | 121、130 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/A02_s120.png) |
| A08_s040 | q2–q8 | 41、50 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/A08_s040.png) |
| A08_s120 | q1–q8 | 121、130 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/A08_s120.png) |
| H02_s040 | q1–q8 | 41、50 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/H02_s040.png) |
| H02_s120 | q1–q8 | 121、130 | [图](../papers/frontend_searaft_real_correspondence_v1/blind/H02_s120.png) |

A08原raw索引为2700+offset。A02_s120_q1和A08_s040_q1为空格，不补选。填写 reference_status=VISIBLE_CORRESPONDENCE / OCCLUDED_OR_OUT_OF_VIEW / AMBIGUOUS、annotator_identity、annotation_kind、human_confirmed；可见时填原图target_x/y及uncertainty_px。原PNG位置见pair_query_manifest的target_image；不要使用拼图截图像素坐标。盲态参考完成前避免查看algorithm/对照图。现有空坐标不是模型标注提议，更不是人工GT。

结果：[report.md](../papers/frontend_searaft_real_correspondence_v1/report.md)、[predictions.csv](../papers/frontend_searaft_real_correspondence_v1/predictions.csv)、[comparison.csv](../papers/frontend_searaft_real_correspondence_v1/comparison.csv)、[decision.json](../papers/frontend_searaft_real_correspondence_v1/decision.json)。真实dt逐对记录，t+1约49–52ms、t+10约499–502ms；后者是人为降低取样频率条件，不能包装成相邻帧收益。S正反向首对2932.6ms含冷启动，其余11对中位254.5ms；C raw中位2.3ms，传统预处理另列。

工作区 `/home/ma/AQUA-FE_WS_searaft_screening_v1`；分支 `exp/searaft-real-correspondence-v1-20260911`；本地稀疏缓存 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_real_correspondence_v1`。源输出只存奇数公开帧，故从39/119原B点各恢复一次源帧KLT/GFTT；原网格选择不读取目标输赢，源内补点局部ID不冒充旧未公开ID。

当前无推理可恢复。仅重新生成待确认汇总的命令：`PYTHONPATH=.:scripts /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/env/bin/python scripts/run_searaft_real_correspondence.py summarize`；predict拒绝重复已存在缓存。获得人工参考后应直接评价保存预测及标注不确定性，脚本会阻止静默沿用待确认结果，不重新推理。

唯一下一步：人工盲态核对这些固定点，然后判断真实位移增量；不换图、不追加网络运行、不自动接入VINS。
