# Information-aware Continuous Geometry-Mode Posterior 研发规划

Date: 2026-06-12

## 1. 目标

当前 AQUA-FE 前端已经形成了两条主线：

1. `proposed_safe`：KLT/GFTT 主干保持稳定，SuperPoint+LightGlue、XFeat、LoFTR 作为严格门控的 learned sidecar，在正常纹理下尽量不影响 VINS。
2. `contribution_sparse`：人为暴露 KLT 退化，让 learned sidecar 在低纹理、低覆盖、近壁和平面场景中体现贡献。

下一步的目标是把目前基于阈值的 `geometry_mode` 调度器升级为一个连续、可解释、可验证的退化后验：

```text
p_planar, p_degraded, p_severe, p_normal
```

它不直接替代所有安全门控，而是先作为信息论/可观性信号进入日志和调度强度控制，用来回答三个问题：

1. 哪些帧真的需要 learned sidecar 或 LoFTR？
2. 哪些触发会破坏 VINS 初始化或轨迹稳定性，应该被抑制？
3. 低纹理正收益和正常纹理 no-harm 是否可以用同一个可解释信号统一解释？

## 2. 创新定位

建议论文中暂时命名为：

```text
Information-aware Continuous Geometry-Mode Posterior
```

或者更保守地写作：

```text
FIM-inspired Quality-weighted Observability Proxy
```

原因是第一版实现很可能还不是严格意义上的 6DoF Fisher Information Matrix。真正的 FIM 需要位姿状态、深度或三维路标，以及重投影 Jacobian：

```text
F = J^T Sigma^{-1} J
```

其中 `J` 应该是特征重投影对 SE(3) 位姿扰动的 Jacobian，而不是 KLT 图像梯度本身。因此建议分两步：

1. 第一阶段实现 FIM-inspired observability proxy，用现有前端可获得的 `q_i`、网格覆盖、特征空间分布、H/F 几何残差等构造信息健康指标。
2. 第二阶段在 VINS 端或带深度估计的轨迹重放中实现真正的 6DoF FIM，并作为增强版实验。

论文创新点的重点不应写成“首次把 FIM 用于 VO”，而应写成：

> 面向水下低纹理 VIO 前端，我们提出一种质量加权的信息感知连续退化后验，用于调度 learned sidecar、LoFTR 平面补点和 Homography recovery，从而替代脆弱的硬阈值触发。

这个定位更稳，也更贴合当前系统已有证据。

## 3. 当前硬阈值调度器的问题

现有 `geometry_mode` 类似以下离散决策：

```text
normal
degraded_texture
planar_near_wall
severe_low_texture
```

它的问题主要有四个：

1. 阈值可解释性弱。例如 `h_inlier_ratio > 0.82` 很难说明为什么不是 0.80 或 0.85。
2. 边界抖动明显。接近阈值的帧可能在 normal 和 degraded 之间反复切换。
3. 模式互斥过强。实际水下场景经常同时低纹理、近壁、低覆盖。
4. 缺少信心刻度。调度器只输出模式，不输出“有多像退化”。

连续后验的目的不是让系统更复杂，而是把这些 if-else 背后的判断变量显式化，并且让 learned/LoFTR 的触发强度随退化程度平滑变化。

## 4. 技术方案

### 4.1 第一阶段：Shadow-mode 信息代理

先新增一个只记录、不影响调度的 shadow-mode 模块。每帧输出如下信息：

```text
info_proxy_min
info_proxy_condition
q_weighted_spread_x
q_weighted_spread_y
q_weighted_grid_coverage
hf_residual_ratio
hf_inlier_ratio
p_planar
p_degraded
p_severe
p_normal
posterior_entropy
posterior_jitter
```

候选输入特征包括：

| 类型 | 变量 | 作用 |
|---|---|---|
| 质量 | `mean_q`, `median_q`, `low_q_ratio` | 判断当前视觉观测可信度 |
| 数量 | `track_count`, `dropout`, `median_track_age` | 判断 KLT 主干是否退化 |
| 覆盖 | `grid_coverage`, `new_cell_gain`, `q_weighted_spread` | 判断是否存在空间分布退化 |
| 几何 | `fundamental_inlier_ratio`, `homography_inlier_ratio` | 判断 F/H 模型支持程度 |
| 残差 | `median_epipolar_error`, `median_homography_error` | 判断 learned 候选是否几何干净 |
| 平面性 | `H/F residual ratio`, `H/F inlier ratio` | 判断是否近似平面或近壁 |

第一阶段不改变任何导出逻辑，只把这些字段加入 frontend metrics CSV。

### 4.2 第二阶段：离线伪标签与后验模型

不建议一开始就用互斥 softmax。水下低纹理经常和平面近壁共存，所以第一版推荐使用多标签 sigmoid：

```text
p_degraded = sigmoid(w_d^T x)
p_planar   = sigmoid(w_p^T x)
p_severe   = sigmoid(w_s^T x)
p_normal   = 1 - max(p_degraded, p_planar, p_severe)
```

伪标签来源：

| 标签 | 构造方式 |
|---|---|
| degraded positive | KLT dropout 高、grid coverage 低、learned sidecar 后轨迹或前端指标改善 |
| planar positive | H residual 不劣于 F、LoFTR 或 H recovery 提供 new cell gain |
| severe positive | KLT 初始化失败、track age 短、低纹理触发后恢复成功 |
| normal/no-harm | 正常纹理窗口中 learned/LoFTR 不触发或触发后无 APE/RPE 下降 |
| boundary/ignore | 时间边界、非因果窗口、GT 不可靠或 bag 截断导致的假反例 |

训练模型应保持轻量：

```text
Logistic regression / calibrated linear sigmoid
```

暂时不使用复杂网络，避免评审认为调度器本身又变成黑箱。

### 4.3 第三阶段：Posterior-gated 调度

当 shadow-mode 验证通过后，再把后验接入正式调度。接入原则：

1. 正常纹理下 `p_normal` 高，则 learned/LoFTR 默认不导出，只作为候选或完全不运行。
2. KLT 退化但非平面时，优先提高 XFeat 或 SuperPoint+LightGlue 的补点预算。
3. 极低纹理、低覆盖、近似平面时，才允许 LoFTR proposal。
4. LoFTR 只产生候选，不立即进入 VINS；必须通过 LK、NCC、FB error、F/H RANSAC、残差稳定性和 2-3 帧 pending 确认。
5. 后端导出保持小比例、低初始 `q_i`，并保留 full-mirror no-harm 兜底。

可采用连续预算函数：

```text
xfeat_budget = base_xfeat_budget * p_degraded * motion_safety
loftr_budget = base_loftr_budget * p_severe * p_planar * geometry_safety
h_recovery_budget = base_h_budget * p_planar
```

### 4.4 第四阶段：True FIM 增强版

如果 VINS replay 中可以获得深度、三维点或可靠三角化结果，再实现真正的 6DoF FIM：

```text
F = sum_i J_i^T W_i J_i
W_i = 1 / sigma_i^2
sigma_i = sigma_base / sqrt(q_i + eps)
```

输出：

```text
lambda_min
condition_number
translation_observability
rotation_observability
dominant_degenerate_direction
```

这一版可以作为论文中的增强实验或附录，不阻塞第一版连续后验。

## 5. 代码实现计划

建议新增或修改以下文件：

| 文件 | 作用 |
|---|---|
| `uw_frontend/geometry/information_proxy.py` | 计算质量加权空间分布、信息代理矩阵和退化指标 |
| `uw_frontend/scheduler/continuous_mode_posterior.py` | 计算 `p_planar/p_degraded/p_severe/p_normal` |
| `uw_frontend/configs/experiments/information_posterior_shadow.yaml` | shadow-mode 实验配置，默认不改变导出 |
| `scripts/train_mode_posterior.py` | 从已有 logs 构造伪标签并训练线性后验 |
| `scripts/evaluate_mode_posterior.py` | 输出 AUC、trigger precision、jitter、no-harm 指标 |
| `scripts/summarize_information_posterior_runs.py` | 汇总跨数据集结果表 |

第一阶段应只修改 metrics 输出，不改变默认实验配置。所有新配置默认显式 opt-in。

## 6. 实验计划

### 6.1 Shadow-mode 诊断

先在已有正例、反例和 no-harm 窗口上跑，不做 VINS 改动。

| 数据/窗口 | 目的 |
|---|---|
| AQUALOC A06 低纹理/平面窗口 | 验证 `p_planar/p_severe` 是否能捕捉 LoFTR 正收益 |
| AFRL FR20-40, FR30-50, FR75-95 | 验证 XFeat sparse sidecar 的低纹理正收益和高运动 no-harm |
| H07 identity churn 窗口 | 检查 posterior 是否能提前识别 learned 导出风险 |
| A09 / Tank / NTNU Fjord | 检查跨数据集泛化和正常纹理 no-harm |

核心指标：

```text
AUC(degraded prediction)
AUC(planar prediction)
trigger precision
trigger recall
mode jitter rate
posterior entropy
learned positive prediction accuracy
normal-texture false trigger rate
```

### 6.2 调度接入后的前端验证

对比：

1. Hard 4-state scheduler
2. Shadow posterior only
3. Posterior-gated XFeat
4. Posterior-gated LoFTR
5. Posterior-gated XFeat + LoFTR + motion-adaptive mirror refill

前端指标：

```text
grid coverage
new cell gain
median track age
dropout
F/H inlier ratio
median epipolar error
median homography error
learned exported ratio
LoFTR exported ratio
```

### 6.3 VINS 轨迹闭环验证

对可跑 VINS 的数据包做 APE/RPE、初始化、lost tracking 和导出统计。

比较对象：

1. VINS-Fusion original frontend
2. KLT + adaptive CLAHE
3. proposed_safe hard scheduler
4. proposed_safe posterior scheduler
5. contribution_sparse posterior scheduler

轨迹指标：

```text
APE RMSE / mean / median
RPE translation / rotation
init_success
lost_tracking_count_proxy
feature export count
learned export count
LoFTR export count
solver instability / NaN / reset
```

## 7. 决策门槛

### 7.1 进入调度器的门槛

只有满足以下条件，posterior 才从 shadow-mode 进入正式调度：

1. 对低纹理/低覆盖窗口的触发 AUC 明显高于现有硬阈值。
2. 正常纹理窗口 false trigger rate 不高于 hard scheduler。
3. H07/A09/Tank 等 no-harm 窗口没有新增真反例。
4. posterior jitter 低于硬模式切换 jitter。

### 7.2 作为论文主创新点的门槛

只有满足以下条件，才把它写成主创新点：

1. 至少两个非 A06 数据集或窗口上能解释 learned sidecar 正收益。
2. 正常纹理长窗口中 APE/RPE 不劣于 KLT + adaptive CLAHE。
3. 低纹理窗口中 APE/RPE 或前端关键指标优于 KLT + adaptive CLAHE。
4. ablation 能证明 posterior scheduler 优于 hard 4-state scheduler，而不是只靠更保守的 safety gate。

如果只满足前端指标，不满足 VINS 轨迹提升，则作为“调度诊断与可解释性模块”写入方法或附录，不作为最强主贡献。

## 8. 主要风险和应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 信息代理只学习到数据集差异 | 跨数据集失效 | 训练/验证按数据集划分，留一数据集测试 |
| 伪标签由实验结果反推，存在泄漏 | 过拟合已有窗口 | 只用历史窗口训练，新窗口验证 |
| posterior 触发更准但 APE 不提升 | 论文贡献变弱 | 保留为解释性诊断，主张前端鲁棒性而非轨迹绝对精度 |
| LoFTR 触发过多导致 identity churn | VINS 变差 | 保持 pending、多帧确认、小比例导出和低初始 `q_i` |
| true FIM 需要深度且噪声大 | 实现周期变长 | 第一版只做 proxy，true FIM 作为增强路线 |

## 9. 论文产出形式

建议准备四类图表：

1. 时间序列图：`p_planar/p_degraded/p_severe` 与 dropout、grid coverage、learned export 叠加。
2. ROC/PR 曲线：posterior 对退化帧、LoFTR 正收益帧、no-harm 帧的预测能力。
3. Ablation 表：hard scheduler vs posterior scheduler 的前端指标和 VINS 指标。
4. 触发分布图：不同数据集上 XFeat、SP+LG、LoFTR 的触发率和成功率。

论文表述建议：

```text
We introduce an information-aware continuous geometry-mode posterior that
turns discrete underwater frontend recovery triggers into calibrated,
quality-weighted probabilities. The posterior schedules learned sidecars and
planar semidense recovery only when the KLT backbone becomes geometrically or
texturally under-constrained, while preserving a KLT-dominant export policy in
normal-texture sequences.
```

## 10. 推荐执行顺序

1. 实现 `information_proxy.py`，只输出 proxy 指标。
2. 在 A06、AFRL FR、H07、A09、Tank、NTNU 上跑 shadow-mode 日志。
3. 写 `evaluate_mode_posterior.py`，先不训练模型，只评估 proxy 指标和现有 hard mode 的关系。
4. 基于历史正例/反例构造伪标签，训练线性 sigmoid 后验。
5. 对新窗口做留出验证，确认 AUC、precision 和 no-harm。
6. 把 posterior 作为 budget multiplier 接入 XFeat 和 LoFTR，不替代安全门控。
7. 跑短窗口 VINS，确认没有新增反例。
8. 跑长窗口 VINS，验证低纹理提升和正常纹理不下降。
9. 整理论文图表和 ablation。

## 11. 第一轮最小可交付

第一轮不要追求完整 true FIM，目标是 3 个文件和 1 张诊断表：

1. `uw_frontend/geometry/information_proxy.py`
2. `uw_frontend/scheduler/continuous_mode_posterior.py`
3. `uw_frontend/configs/experiments/information_posterior_shadow.yaml`
4. `logs/information_posterior_shadow_summary.csv`

验收标准：

```text
normal-texture false trigger 不上升
low-texture positive windows 的 p_degraded/p_severe 明显高于 normal windows
planar windows 的 p_planar 明显高于 non-planar windows
posterior jitter 低于 hard geometry_mode jitter
```

达到这个标准后，再进入正式调度接入。
