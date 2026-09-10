# SEA-RAFT correspondence evidence check v1 — 冻结协议

2026-09-10；完整授权见 [task_instructions.md](task_instructions.md)。输入固定于 `a2f3bedcc2e4f98bd18f99a3601d70433de42aa7`，旧 `CONTROLLED_GAIN_ONLY` 保留。本轮新网络推理、训练、VINS、模型、窗口均为 0。沿用已有空闲工作区，新分支 `exp/searaft-evidence-check-v1-20260910`。旧结果和源缓存只读。

**输入与划分。** 旧实验 `controlled_points.csv` / `natural_results.csv` 是唯一预测、接受及三步检查来源；原图从 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/{controlled_inputs,natural_inputs}/manifest.json` 定位，缓存已存在，无需重建。48 对原 mono8、原查询、坐标、FB 和可见性不变；A02[0,200)、A08[2700,2900)、H02[0,200)。各序列底图 offset 0/50 的全部四变换为校准 24 对，100/150 为检查 24 对。全部是开发数据，无新序列泛化含义。检查部分仅评分一次；最终报告可从已保存分数重复汇总。

**唯一主规则。** `check_correspondence_evidence(prev,cur,p,pred)` 在原 mono8 上，以两个既有中心作精确双线性采样，提取 11×11 patch；减均值，计算内积除以两 L2 范数，固定 NCC≥0.65。旧 `_patch_ncc` 使用取整中心，不符合亚像素合同，因此仅复用其归一化公式，新增独立函数，不改旧函数。完整采样域必须在各自图像 [0,W−1]×[0,H−1] 内；每张 patch 的灰度标准差必须 >1.0 mono8 灰度级（预先固定的低纹理下限，不调参）。非有限、patch 不足、低方差均拒绝并标记 `UNRESOLVED_*`，NCC 留空；可计算但低于 .65 为 `NCC_BELOW_THRESHOLD`，通过为 `SUPPORTED_BY_NCC`。`valid_patch` 表示完整、有限且非低方差。无图像增强、附近搜索、几何对齐、坐标精化、真值/遮挡/未来信息输入。数值检查覆盖同 patch、亮度平移/高低对比度、常量、边界、亚像素、非有限。

**比较和分母。** 仅在原共同 B 失败集比较 S0=原 S_common、S1=S0∧patch、C0=原 C_common、C1=C0∧同一 patch 规则；C_production 只引用旧背景。正确=旧可见标签且原端点 EPE≤2px；不可见或定位超差为错误。校准、检查、全量分别按总体、序列、变换、序列×变换列接受/正确/错误、正确保留率、原完整不可见分母、精度、相对 C0/C1 的正确恢复率差、原 S-only 正确点保留数。原 S-only 永远由 S0∧¬C0 定义。用旧 truth 与 manifest 的矩形/guard 仅作离线原因分解：实际移出图像、8px 图像边界 guard、人工遮挡矩形、6px 遮挡 patch guard；保留重叠标志，优先顺序如上，无法归因记 Unknown。可见定位超差独立计数；拒绝理由不冒充不可见标签。

**辅助量（与 NCC 分开）。** 锁定官方源码 `core/raft.py:145–156` 将 info[0:2] 作为两 Laplace 分量的 logits，info[2:4] 是 log_b；本模型 var_min=0、var_max=10。因此取 `b=sum(softmax(logits)*exp([clip(info2,0,10),0]))`，即模型混合分布单轴绝对误差尺度。已有 info 在原图插值并采样，未缩放数值；按旧模型输入半尺度，用实际 W/Wnet、H/Hnet 的平均比例（本数据均为 2）恢复原像素平均轴尺度。此量是插值参数导出的模型尺度代理，不是实测误差、可见概率、正确概率或已校准置信度。[官方固定源码](https://github.com/princeton-vl/SEA-RAFT/blob/9137517ba24e628442aec097d3afe71d03503b75/core/raft.py)。仅用校准部分 S0 正确接受的有限尺度，升序第 ceil(.95*N) 个值确定一个全局上限，边界含等号，保留至少95%（并报告并列）。阈值写入 calibration_lock.json 后才读取检查部分标签用于评分；SU=S0∧尺度≤阈值单列，不与 NCC 组合。若缺字段/语义不成立则 UNAVAILABLE，不加载模型。

**检查通过门。** 检查总体同时满足 S1/S0 正确保留≥80%、S1 不可见接受/原不可见 B 失败≤1%、S1 接受精度≥95%；同一种 large 或 illumination_blur 在至少两序列仍有 S1−C0 正确恢复率≥5个百分点。分组可见 B 失败至少20才计入跨序列门；所有小/零分母及 outside_occluded 单独完整列出。不改变阈值或用辅助规则替换主规则。

**自然及有限复核。** 对原全部 2857 事件应用主规则，单列全部原61个 S-only，直接读原三步普通 LK 支撑，绝不重算。H02 原20个 S-only 三步事件全部复核；另按 (sequence,raw_index,track_id) 升序固定选最多5个原 C-only、最多5个被 S1 拒绝的原 S-only，去重且不补选，共≤30。显示原查询、C/S 当前端点及11patch、已有 t+3 图像上下文；无已保存未来端点时不画推断轨迹。记录距边界数值（≤16px 标记 near_border）、C/S 距离、C 拒绝是否仅有限 FB>1 导致（非有限反向状态记 Unknown）。C/S 距离≤2原px且原接受不同，单列 `GATE_DIFFERENCE_WITH_SIMILAR_ENDPOINT`，不宣称 C 找不到位置。视觉标签只能为 VISIBLE_STRUCTURE_SUPPORTED / CLEAR_IDENTITY_CONTRADICTION / UNRESOLVED；前者仅当前图像结构支持，物理身份仍 Unknown。未来图像只供离线解释。

**决定与发布。** 受控门失败→EVIDENCE_GATE_NOT_SUPPORTED；通过但自然不足→CONTROLLED_FILTER_GAIN；通过且 H02 原20事件至少5个被 S1 保留、其中有限复核至少1例有可见结构支持→LOCAL_CANDIDATE_SUPPORTED（所有明确矛盾仍逐例报告，绝非物理 GT）。关键输入不能恢复→DATA_BLOCKED。唯一后续：有支持则交付小函数供下一次另行授权的最小集成评估，否则结束本版本。无自动后端/新窗口/第二阈值。同步仅本协议冻结和最终完成/阻塞两个检查点；失败记 SYNC_BLOCKED。本地稀疏分数与计时存于独立 runtime `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_evidence_check_v1`，不上传权重/大缓存。
