# Statistical appendix

## 分析单位

闭环分析单位是窗口，`n=4`：正例 2、伤害/混合 2。每条 track 的 streak 共享同一视频、前端状态与闭环结果，不满足独立同分布假设，因此不将 7、12、43、49 条 KLT track 当作样本量做显著性检验。

## 描述统计

完整寿命用每条 unique track 在冻结 feature bag 中的最长连续 backend-visible 发布帧串计算。主表报告中位数、IQR、范围以及 common-language effect size `P(S_x>S_k)+0.5P(S_x=S_k)`。四窗 effect size 分别为 1.000、0.583、0.033、0.259。

窗口按既有闭环 outcome 分成正/负组，这是题设要求的历史归因集合，不是对结果盲的随机样本。因此“4/4 的寿命中位数方向与 outcome 一致”只能作为机制一致性证据，不能计算为无偏的 p 值或用于总体泛化。

## 因果证据层级

1. `a09` source-drop 是既有 bag 上的单变量干预：仅 3 个 `source_code=20` 观测被删除，其余 header、record time、points、channel schema/order 和所有 channel 值均精确相同。这支持“这三个观测对该 epoch 收敛是必要组成”，不单独证明任意 XFeat 都充分。
2. `a06/h07` 独立 mirror 使输入差异只存在于列出的 3/3/6 个 feature 帧，提供强时序定位，但没有逐个恢复 victim 的闭环消融，因此证据为关联加机制一致性。
3. 安全 v4 与 KLT 整 bag 同哈希，是输入等价反事实。它证明 v4 不保留旧正例贡献；其闭环数值来自冻结 KLT 三重复，而不是新增 backend 运行。

## 测量限制

- APE/RPE 均是与 COLMAP/proxy 的一致程度，不能写成独立 GT 绝对精度。
- `a09` 2026-07-07 消融和 2026-08-30 正式结果的 quality-weight epoch 不同，绝对数值不合并。
- `a09` shared tracker 在三个 XFeat 事件后改变后续 classical state；`a06/h07` 是 final-mirror 局部替换。二者支持同一“替换持久性”机制，但不是完全同构实现。
- 轨迹的末端会受窗口截断；表中保留 censor 标志，结论以组间数量级方向和精确事件定位为主。

