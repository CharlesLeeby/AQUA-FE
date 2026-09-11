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

## 2026-09-11 — 离线点选与直接评价已就绪

当前用户入口改为 [annotate.html](../papers/frontend_searaft_real_correspondence_v1/annotate.html)，下载/本地双击打开；不再要求手填 CSV。18 张原 PNG 和固定 92 项已嵌入，无网络、模型或 bag 依赖；页面只含源点和人工参考，按原 manifest 顺序展示。先输入标注者，右图点选并给出原像素不确定性，或明确标不可见/无法判断，再人工确认本项。支持缩放平移、清除、保存、CSV 导出和导入恢复。实际标注条件会记录用户已看汇总数量及其声明的逐点图查看情况，不宣称严格双盲。

使用步骤及完整命令：[annotation_usage.md](../papers/frontend_searaft_real_correspondence_v1/annotation_usage.md)；本轮恢复入口：[annotation_task.md](../papers/frontend_searaft_real_correspondence_v1/annotation_task.md)。导出的 `reference_annotations.user.csv` 放在实验目录，与 annotate.html 同级，保留原空模板。

```bash
python3 /home/ma/AQUA-FE_WS_searaft_screening_v1/scripts/evaluate_searaft_annotations.py --annotations /home/ma/AQUA-FE_WS_searaft_screening_v1/papers/frontend_searaft_real_correspondence_v1/reference_annotations.user.csv
```

评价入口不导入推理模块：先将用户 CSV 原字节保存到新的 `annotation_evaluations/<UTC时间>/reference_snapshot.csv`，再读取保存预测。逐点误差、保守范围、接受状态以及完整/分组分母写入独立结果目录。部分标注输出 PARTIAL，未知/AMBIGUOUS 不当作 TIE、安全或失败；独有正确接受与位移增量分开。新脚本替代旧 summarize 的人工参考阻止分支，无需改动原脚本。

已完成必要软件检查：原图坐标经留白/缩放/平移往返与 DPI=2 实际点击、CSV 导出导入、草稿恢复；误差区间和 PARTIAL/快照检查通过。所有假坐标仅存在临时测试样本。本轮 0 模型加载、0 新预测、0 VINS，尚无真实人工标注，旧 REFERENCE_PENDING 和原始文件不变。唯一下一步为用户点选确认，然后执行上述命令；不自动轮询或扩大实验。
