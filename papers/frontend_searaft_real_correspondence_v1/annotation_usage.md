# 点选与评价

1. 双击本目录的 **annotate.html**，用 Chrome/Firefox/Edge 打开。18 张原 PNG 已嵌入，无需网络、服务器或安装环境。
2. 输入标注者及此前是否看过逐点算法图。左侧黄色点是当前查询；右侧点选同一位置，选原像素不确定性（1/2/4 或自定义），点击“人工确认本项并下一项”。两侧可滚轮缩放、拖动平移、“全幅”复位。不能确认或只是没找到时选 AMBIGUOUS；仅确知遮挡/移出画面时选 OCCLUDED_OR_OUT_OF_VIEW。下一项按钮不会自动确认。
3. 随时“保存进度到本机”；关闭前必须“导出 CSV”。导入已导出的 CSV 可继续。清除当前标注会撤回本项确认。完整 92 项始终保留，未确认项不参与准确率评价；未填完整的可见草稿导出为 PENDING，并保留说明。
4. 将下载的 **reference_annotations.user.csv** 保存到本实验目录，与 annotate.html 同级。不要覆盖原始 reference_annotations.csv 空模板。
5. 运行以下一条命令（系统 Python 3 即可，无模型或第三方依赖）：

```bash
python3 /home/ma/AQUA-FE_WS_searaft_screening_v1/scripts/evaluate_searaft_annotations.py --annotations /home/ma/AQUA-FE_WS_searaft_screening_v1/papers/frontend_searaft_real_correspondence_v1/reference_annotations.user.csv
```

结果写入本目录 `annotation_evaluations/<UTC时间>/`；命令打印具体 report.md 路径。先保存 reference_snapshot.csv，再读原 predictions.csv；输出 per_query.csv、comparison.csv、decision.json、report.md，不覆盖旧结果。每次运行新建目录，不静默覆盖人工快照。若换工作区，可从仓库根运行 `python3 scripts/evaluate_searaft_annotations.py --annotations papers/frontend_searaft_real_correspondence_v1/reference_annotations.user.csv`。

误差区间为 [max(0,e−u),e+u]，u 是人工定位范围而非置信区间。区间跨 2 px 或 C/S 差异无法超出标注不确定性时，保留不确定。部分标注输出 PARTIAL / REFERENCE_PENDING，不能作完整实验结论。独有正确接受与真实位移增量分列；近端点门差异不作位移收益。完整标注后的自动决定采用保守局部口径，不自动升级为全面有效或接入 VINS。

本页不读 predictions.csv 或 algorithm/。按原 manifest 顺序展示 92 项，新增 annotation_conditions / human_confirmed_at 字段，其余参考字段兼容。用户已看汇总数量，逐项记录人工声明的逐点图查看情况，不称严格双盲。

已用独立临时样本验证：含留白、缩放和平移的坐标往返及高 DPI 点击；CSV 下载/导入、带逗号与换行的记录、本机草稿恢复；2 px 边界、不确定区间、快照先于预测读取及 PARTIAL 分母。测试数据没有进入正式参考。HTML 生成入口为 `python3 scripts/build_searaft_annotation_page.py`，交付页已生成，用户无需运行它。
