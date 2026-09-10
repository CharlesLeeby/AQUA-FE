# SEA-RAFT real correspondence check v1 — 固定协议

2026-09-11；完整任务见 task_instructions.md。只问真实图像中 S1 是否比强 LK C1 更准确地定位同一物理位置。旧 a2f3bed 的 CONTROLLED_GAIN_ONLY、4d061b8 的 EVIDENCE_GATE_NOT_SUPPORTED 保持不变。新分支 exp/searaft-real-correspondence-v1-20260911，沿用空闲工作区；0训练/新权重/新窗口/VINS，不运行原48对合成测试。

**输入。** 只读旧 `papers/frontend_searaft_screening_v1/controlled_pair_source.json` 与旧 runtime `natural_inputs/manifest.json`。A02[0,200)、A08[2700,2900)、H02[0,200)，源 offset40/120，每源分别配对+1/+10，共12对真实mono8图像。纳秒时间戳决定真实时间差；t+10是人为降低取样频率条件，不当作原相邻帧收益。原缓存齐全，不变换、不增强S图像、不换缺失对。

**源点与冻结。** 原 B 输出点缓存位于旧 recovery runtime 的 `{sequence}/{sequence}_actual_output_tracks.csv`，只公开奇数帧。因此对每个源用其前一帧39/119的全部原B点、年龄和图像，调用同配置 KltTracker 恢复一次原跟踪和原GFTT补点；不读目标帧或未来结果来选择。原坐标可恢复，旧未公开补点的全局ID无法确定，故仅分配源帧内局部ID并记录可追溯旧ID，不宣称重建公开ID生命周期。选点仅在源图：距边界≥16原px（坐标范围[16,W−1−16]、[16,H−1−16]），4列×2行，每格取距格心最近点；并列按源局部ID。空格明确记录、不补选。相同源的两种gap共享点，最多96查询。先写pair_query_manifest.csv和盲态材料、再计算新C/S预测。

**固定测量。** 直接复用 a2f3bed 的 SeaRaftPoints、官方源码9137517、spring-M和既有本地权重；原scale−1、iters4、FP32、eval/inference_mode、GPU0/batch1、单线程、TF32关闭，无新备用尺度。既有真实自然缓存仅存旧B失败子集稀疏预测，密集flow未保留，不能覆盖本次固定查询，因此预计12对各一次正反向，1次模型加载、24次forward；不逐点推理。首个正式图像对计时包含冷启动，不额外运行预热/合成检查。C调用旧strong_lk（31/4/40，原adaptive CLAHE），S使用原mono8复制RGB；预处理不同如实记录。C0/S0完全复用旧common_mask（有限、FB≤1原px、端点8px边界）；C1/S1追加4d061b8原函数（11×11原mono8双线性patch、NCC≥.65、std>1灰度级、完整/有限采样域）。不改坐标、不精化S、不调门。逐对稀疏缓存和预测表保留，完成对不得重复。

**独立参考与盲态。** 已检查三个相关旧实验的本地表/清单，没有适用的人工/标靶像素对应标注；旧人工字段为Unknown，旧Assistant图像判断不是独立人工GT。参考模板每个固定查询一行：PENDING、VISIBLE_CORRESPONDENCE、OCCLUDED_OR_OUT_OF_VIEW、AMBIGUOUS；后3项也须记录是否人工确认。可见对应需原图目标x/y、标注者身份及原px不确定性。源图仅画固定query ID，目标图全幅、无C/S端点，也不按预测裁剪；参考与算法图分目录。盲态图与空模板在预测前产生。没有人工核验时坐标留空，不由模型猜测填成GT，不把同一模型复看当独立标注者。

**评价与决定。** 主比较C1/S1；同时保留C0/S0全部预测。按序列、gap、全量报告完成/确认/待确认及接受数。没有确认参考时误差、正确/错误和独有正确均留空，comparison状态REFERENCE_PENDING。若日后获得人工参考，仅从保存预测评价：可见点误差e及区间[max(0,e−u),e+u]；区间上界≤2才确定正确，下界>2才确定超差，跨2或标注不确定性接近2px均不硬判。只有人工确认的不可见可计误收；AMBIGUOUS保留且不当错。C/S端点≤2px且接受不同只记门差异诊断，不是位移优势。真实参考不足则REFERENCE_PENDING，明确待核对文件与ID；不依据接受数输出NO_REAL_INCREMENT或收益结论。本次无自动扩大或接入后端。

**产物与执行。** 新目录保留task/protocol、pair_query_manifest、predictions、reference_annotations、comparison、decision/report及少量blind/和algorithm/图。一个脚本分prepare/predict/summarize；prepare不加载网络，predict只用冻结清单，summarize不推理。新runtime `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_real_correspondence_v1`；旧图/模型缓存只读。正常显式commit/push并读回主要表和报告；缺参考不妨碍完成12对与核对材料，不伪造准确率。
