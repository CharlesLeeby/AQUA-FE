# AQUA-FE 历史 XFeat 正例的替换归因

## 结论先行

历史正例不是“安全 v4 在 KLT 上额外贡献了学习特征”。安全 v4 在 `a09_6000_6800` 中虽然产生了 24 个候选、确认了 17 个候选，并有 3 个 sidecar 到达最终器，但最终保留/发布均为 0；生成的 `features.bag` 与冻结 KLT bag 的 SHA-256 完全相同，8,533 条 ROS 消息流也逐字节相同。因此安全 v4 的闭环反事实就是已有的三次 KLT 复放：APE 中位数 1234.132 m（范围 1230.939–1296.254），RPE 中位数 150.056 m（149.679–156.965），原来 XFeat 的收敛正例消失。这里的 APE/RPE 是与 COLMAP/proxy 的一致程度，不是独立 GT 绝对误差。

旧路径能够赢 KLT 的原因是它改变了 350 预算中的出生/替换组成。在两个冻结正例中，被牺牲 KLT 的完整后验寿命中位数分别为 1、1 个发布帧，而替换 XFeat 为 3、2 帧；在两个无害违例/混合窗中，顺序反过来，KLT 为 15、3 帧，XFeat 为 1、2 帧。`a09` 还有已有 bag 的严格 source-drop 消融：仅删除 3 个 `source_code=20` 观测，其他 header、记录时间、points 与所有 channel 值完全不变，闭环由 APE/RPE 0.579/0.080 变为 1072.548/127.180。该消融属于 2026-07-07 的质量权重 epoch，不能与 2026-08-30 正式结果混合取均值，但能证明那三个学习来源观测是该 epoch 收敛的必要组成。

一句话因果结论：**在已冻结、已审计的历史窗口中，旧路径的收益来自少量 XFeat 替换了本来会快速 churn 的 KLT/GFTT 轨迹并改变初始化历史；当同一策略误删了在纯 KLT 反事实中会继续长寿的轨迹时，收益转为伤害，而安全 v4 通过完全禁止满预算驱逐同时消除了两者。**

## 分析边界

- 本轮只读取冻结的 `frontend_metrics.csv`、feature bag、命令/receipt 和既有闭环结果；没有改门、阈值、后端、export gate 或历史文件。
- 唯一新增执行是 `a09_6000_6800` 的安全 v4 **前端 export-only** 反事实；`RUN_VINS=0`，没有新闭环复放，也没有“制造正例”。原始 bag 只读，并以同哈希副本放到根分区运行，未写 `/mnt/data`。
- 寿命单位是 backend-visible 发布帧（`every_n=2`），不是原始相机帧。完整寿命来自同一冻结 bag 内相邻发布帧的 track ID 串。
- 轨迹不是独立实验单位；逐轨迹分布只用于机制诊断。窗口数为 4（正例 2、伤害/混合 2），不据此做总体显著性声明。
- `a02_4500_6300` 因三臂 feature bag 完全相同而排除；无有效 A10 正例。完整、不静默删窗的历史清单见 [historical_window_roster.csv](historical_window_roster.csv)。

## 冻结 lineage 与窗口全集

四个纳入窗均明确使用旧 `lineage_early_seed_scan` 与 `P_legacy_nativeq_xfeat_seedchain_v3` 配置族，而不是 `lineage_early_seed_noharm_v4`：

| 窗口 | 组别 | 旧替换实现 | 冻结闭环结局 |
|---|---|---|---|
| `a09_6000_6800` | 正例 | shared-tracker 出生竞争；早期 XFeat 写入 tracker 后改变后续 ID/出生状态 | XFeat 收敛；KLT 尺度数量级发散 |
| `a06_s045_d045` | 正例 | legacy final mirror，sidecar 优先、一对一删除 KLT | XFeat APE/RPE 均下降 |
| `a06_s000_d045` | 混合/无害违例 | 同一 legacy final mirror | APE 变差，RPE 略好 |
| `h07_s000_d050` | 有害 | 同一 legacy final mirror | APE/RPE 均变差 |

正式 `a09` 使用 exporter SHA-256 `68453b...12d`；supplement 三窗使用 `fdb624...c04`。逐窗命令/receipt、bag 路径与哈希见 [window_lineage_and_outcome.csv](window_lineage_and_outcome.csv)，所有依赖见 [source_artifacts.sha256.csv](source_artifacts.sha256.csv)。

`a09_4000_4400` 和 `a10_2400_2800` 因 runability/budget 失败排除，`a10_4800_5200` 只有 16 个 common poses、低于冻结的 30-pose 门，A10 same-history v4 的 APE 门关闭且 KLT 执行完整性失败；这些不是隐藏负结果，而是不满足原冻结合同。`afrl_fl_s180_d045` 近似平局，但旧 runner 没有激活可审计的一对一 mirror 替换，因此作为中性窗保留在 roster，不拿来检验本假设。

## 驱逐量与持久性对照

下表的 KLT 与 XFeat 数量为 unique track；“驱逐观测”另列，因为同一 KLT 可在多个事件帧被计数。IQR 与范围都是描述性统计。

| 窗口 | 驱逐观测 / KLT unique | XFeat unique | 被驱逐 KLT 完整寿命，中位 [IQR] (范围) | XFeat 完整寿命，中位 [IQR] (范围) | P(XFeat>KLT)，平局计 0.5 | APE/RPE 变化 |
|---|---:|---:|---:|---:|---:|---:|
| `a09_6000_6800` | 7 / 7（全为 fresh GFTT） | 1 | 1 [1, 1] (1–2) | 3 [3, 3] (3–3) | 1.000 | −99.94% / −99.95%，由尺度发散转为收敛 |
| `a06_s045_d045` | 12 / 12 | 6 | 1 [1, 3.5] (1–31) | 2 [2, 2] (1–3) | 0.583 | −19.88% / −21.37% |
| `a06_s000_d045` | 50 / 43 | 30 | 15 [8, 27] (2–44) | 1 [1, 2.75] (1–3) | 0.033 | +7.78% / −4.83%（混合） |
| `h07_s000_d050` | 50 / 49 | 20 | 3 [2, 8] (1–55) | 2 [1, 2.75] (1–6) | 0.259 | +8.54% / +13.76% |

四个窗口的寿命中位数方向都与闭环类别一致，见 [track_persistence_comparison.csv](track_persistence_comparison.csv) 和 [寿命分布图](analysis-output/figures/figure-01-track-lifetime-contrast.pdf)。但这不是无偏泛化检验：分组本身来自冻结闭环结局，因此不能把“4/4 同号”转成推断性 p 值。

## 逐帧定位与闭环时序

| 窗口 | 替换 raw frame | 每帧 XFeat / 被删 KLT | 相对初始化 | 输入差异范围 |
|---|---|---|---|---|
| `a09_6000_6800` | 5, 7, 9 | 1/2, 1/1, 1/4 | 最后一次替换早于 init finish 0.956 s | 前两条 feature 消息相同；第 2–399 条不同 |
| `a06_s045_d045` | 5, 7, 9 | 1/1, 5/5, 6/6 | 早 1.883 s | 仅消息 2–4 不同 |
| `a06_s000_d045` | 3, 5, 7 | 12/12, 29/29, 9/9 | 早 4.308 s | 仅消息 1–3 不同 |
| `h07_s000_d050` | 883–893，步长 2 | 11/11, 8/8, 5/5, 5/5, 14/14, 7/7 | 晚 43.351 s | 仅消息 441–446 不同 |

完整帧表见 [frontend_frame_evidence.csv](frontend_frame_evidence.csv)，事件—初始化表见 [replacement_closed_loop_timing.csv](replacement_closed_loop_timing.csv)，事件图见 [replacement timeline](analysis-output/figures/figure-02-replacement-timeline.pdf)。

`a09` 与另外三窗的实现细节不同。它只发布了同一条 XFeat track 的三个连续观测，但 shared tracker 的出生竞争使 7 个 GFTT 观测缺失，并从事件后持续改变 KLT ID/出生状态，所以 400 条 feature 消息中有 398 条不同。这说明历史胜利不是“后端持续吃到大量 XFeat”，而是极小的早期输入扰动把初始化送到了另一条状态轨迹。

三个 supplement 窗采用独立 KLT mirror：除明确替换帧外，其余 feature 消息逐字节相同。因此 `a06_s000` 与 `h07` 的劣化不能归因于长期任意前端漂移；差异被定位到 3 或 6 个替换事件帧。

## 原假设中被证伪的部分

“有害窗删的是删除当下已经成熟的 KLT”不成立。被删 KLT 在事件时的 backend-visible age 中位数为：`a09=1`、`a06_s045=1`、`a06_s000=2`、`h07=2` 帧；各组高度重叠。真正区分正负的是纯 KLT 分支中的**未来寿命**：`a06_s000` 被删轨迹之后本可再活很多帧，完整寿命中位数达到 15。

现有 backend quality 也不能直接解决问题。supplement 中无论正例还是有害窗，被删 KLT 的质量中位数都在 `0.80` floor 附近，而 XFeat 为约 `0.857–0.868`；按当前 q 大小驱逐仍会在 `a06_s000/h07` 做出错误选择。换言之，“当前 age + 当前 q”不是未来持久性的可靠代理。

## 安全 v4 反事实

安全 v4 的前端运行结果见 [safe_v4_counterfactual.csv](safe_v4_counterfactual.csv)：

- 候选 24、confirmed 17、finalizer 输入 sidecar 3；kept sidecar 0、实际发布 XFeat 0。
- v4 bag 与冻结 KLT bag 的完整文件 SHA-256 都为 `6de8ffe9226c...171884ff`。
- 8,533 条 backend message stream 的 SHA-256 都为 `3e5f57cac473...9b95ed8`。
- 因输入逐字节相同，不运行新后端也能确定 v4 属于已有 KLT 三重复的同一反事实输入；其正例收益为零。

这验证了“永不驱逐”同时消除风险和旧收益，但不说明应恢复无条件驱逐。

## 质量条件驱逐判据雏形

推荐保持安全 v4 为默认，只把 learned track 放在不占后端预算的 shadow/probation 阶段。为 learned 候选 `x` 与拟驱逐 KLT `k` 估计未来剩余可见寿命分布，定义：

`LCB(S_x | shadow re-observation, visible streak, FB/NCC, motion consistency, geometry)`

`UCB(S_k | age, FB/NCC, motion consistency, cell support, initialization role)`

仅在下列条件同时成立时允许一对一替换：

1. `LCB(S_x) > UCB(S_k) + margin`，且模型在 leave-window-out 数据上校准；
2. `k` 是该 cell 内预测剩余寿命最低、非保护的轨迹，不是初始化/尺度可观的唯一几何支撑；
3. `x` 已在 shadow 中重复观测并提供新 cell、视差或几何条件数增益；
4. 任一证据不足时回退到 v4，不驱逐。

一个更保守但能力有限的即时规则是“只允许替换同帧出生的 GFTT”。它能保留 `a09` 的机制，却会放弃 `a06_s045` 这类 KLT-source 正例。因此最终判据必须预测未来持久性，而不能只看 source、当前 age 或当前 q。本报告只给判据雏形，没有用这些四个 outcome-defined 窗调阈值，也没有声称它已经通过 no-harm 验证。

## 可复现产物

- 逐帧： [frontend_frame_evidence.csv](frontend_frame_evidence.csv)
- 被驱逐 KLT： [displaced_klt_observations.csv](displaced_klt_observations.csv)
- 插入 XFeat： [inserted_xfeat_observations.csv](inserted_xfeat_observations.csv)
- 逐窗寿命与闭环： [track_persistence_comparison.csv](track_persistence_comparison.csv)
- lineage/命令/bag： [window_lineage_and_outcome.csv](window_lineage_and_outcome.csv)
- 已有 bag source-drop 因果消融： [existing_bag_causal_ablation.csv](existing_bag_causal_ablation.csv)
- 安全 v4 反事实： [safe_v4_counterfactual.csv](safe_v4_counterfactual.csv)
- 输入哈希： [source_artifacts.sha256.csv](source_artifacts.sha256.csv)
- 分析脚本： [analyze_xfeat_replacement_attribution.py](../../scripts/analyze_xfeat_replacement_attribution.py)

