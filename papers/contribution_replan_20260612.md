# AQUA-FE 创新点规划与执行方案

Date: 2026-06-12
约束:**全部贡献只依赖现有数据集与已有 logs,零实机实验、零新数据采集。**
本地数据:AQUALOC H06/H07/A06/A08/A09、AFRL-FL/FR、NTNU Fjord、Tank、UVVID;已有 VINS 重放结果与反例审计(`logs/backend_evidence_compact.md`、`logs/agent_counterexample_gate_audit_20260608.md`)。

---

## 1. 论文统一叙事线

> **把水下混合前端中所有"手工启发式决策"替换成带统计保证的决策**:
> 测量层(C1,σ_i 带覆盖率保证)→ 帧层(C2,退化连续后验)→ 决策层(C3,导出门带风险上界)。
> 学习模块(XFeat / SP+LG / LoFTR / TAP)永远是受这三层保护的 sidecar,KLT 始终是后端可见的时间骨干。

三个核心贡献共享同一套统计语言(校准、覆盖率、风险控制),且各自直接回应一个评审必问的问题:

| 评审必问 | 回应 |
|---|---|
| "q_i 在 H07 上训的,放到 A06/AFRL 还可信吗?" | C1 给出分布无关的覆盖率保证 |
| "调度阈值 0.82 / 0.55 凭什么?" | C2 把阈值替换为可学习、可评估的连续后验 |
| "导出门 '≥2 新网格' 的 2 凭什么?" | C3 把 2 替换为风险上界 α 下拟合出的 τ |

与既有两 claim 框架(`papers/frontend_baseline_protocol.md`)的关系:C1–C3 不改变 claim 结构,而是把 "normal-texture no-harm + low-texture improvement" 的证据从经验结论升级为带统计保证的结论。

---

## 2. C1 — Mondrian Conformal 特征可靠性校准(σ_i 带覆盖率保证)

### 2.1 创新点表述(paper-ready)

> 我们提出**特征级 Mondrian conformal 可靠性校准**:在留出的水下校准序列上,按几何退化模式分桶拟合非一致分数,把逻辑回归点估计 `q_i` 升级为带覆盖率保证的视觉残差权重 `σ_i`——对任意名义置信度 1−α,"特征未来存活 / 重投影残差落入 k·σ_i" 的经验覆盖率分布无关地成立,并在跨水下域(港口 → 深海考古平面 → AFRL 退化场景)验证覆盖率保持。

**Related work 定位**(三句话):pose 级 conformalized VO(arXiv 2303.02207)只给整条轨迹的位姿区间,不进入优化器;MAC-VO(ICRA 2025 Best Paper, arXiv 2409.09479)用 NLL 学 per-feature covariance,是点估计,跨域无保证、需训练网络;我们在**测量层**给出分布无关保证,基础模型仅为逻辑回归 + conformal 包装,可解释、零训练成本、面向水下退化分层。

### 2.2 方法

1. **基模型**:现有 `ReliabilityCalibrator`(逻辑回归,28 维 `RELIABILITY_FEATURE_NAMES`,future-survival 标签)不动。
2. **Nonconformity score**:`s_i = |y_i − q̂_i|`(存活标签残差),或重投影残差版 `s_i = r_i / σ̂_i`。当前第一版主文采用 survival-conformal,因为 `epipolar_score` proxy 的 residual-ratio 版本在 AFRL-FR 上仍明显 under-cover; residual-ratio 先作为附录负结果/后续改进方向。
3. **Split conformal**:校准集上取 s 的 ⌈(n+1)(1−α)⌉/n 分位数 Q̂,新特征的保证区间为 `q̂_i ± Q̂`(或 `r_i ≤ Q̂·σ̂_i`)。
4. **Mondrian 分桶**:按 `geometry_mode`(过渡期用现有 4 态硬模式;C2 落地后切换为后验软分桶)各桶独立拟合 Q̂_mode,保证逐场景覆盖而非平均覆盖。severe 桶样本不足时与 degraded 合并并在论文中说明。
5. **σ 映射**:`σ_i = σ_base · Q̂_mode · f(q̂_i)`,f 沿用现有 `1/√(q+ε)` 形式,保持后端接口不变。

### 2.3 实现任务清单

| # | 任务 | 文件 | 量级 |
|---|---|---|---|
| 1 | conformal 校准器(split + Mondrian,fit/predict/save/load JSON) | `uw_frontend/quality/conformal_calibrator.py`(新) | ~250 行 |
| 2 | 覆盖率评测:名义 vs 经验覆盖率表、reliability diagram、按模式 ECE/Brier 分解 | `uw_frontend/evaluation/evaluate_conformal_coverage.py`(新) | ~200 行 |
| 3 | σ 重写闭环:把 conformal σ 写回 feature bag 重放 VINS | 复用 `scripts/fourpoint_q_rewrite_feature_bag.py` + `scripts/fourpoint_run_vins_existing_feature_bag.sh` | 改参数即可 |
| 4 | 汇总报告 | `logs/conformal_calibration/` 下 CSV + MD | — |

数据已全部现成:`--reliability-log-csv` 导出的 per-feature 特征 + 标签(`logs/qgeo_train/` 等),无需重跑前端。

### 2.4 实验矩阵

- **划分**:校准 = H07;测试 = A06、AFRL-FL/FR、H06、NTNU Fjord、Tank、UVVID(留一数据集交叉再做一轮,挡过拟合质疑)。
- **对照**:raw q / logistic q(现状)/ 温度缩放 / conformal(本工作),名义覆盖 80% / 90% / 95%。
- **闭环(APE)**:仅用重复稳定窗口——H07 no-harm(constq 0.1026 → tempered 0.0860,n=5 稳)、AFRL-FL/FR no-harm。**A06 单窗口 VINS APE 不可复现(同 bag/alpha 重放跨度 0.05-0.30m,0.99 档发散至 56m),已移出 APE 证据,改前端指标 only**(见 `logs/conformal_calibration/c1_a06_frontend_only_evidence_20260615.md`)。
- **A06 前端指标(与重放无关)**:dropout 24.35→8.16(-66%)、track age 22→45(2×)、epipolar 0.1538→0.1475,作平面低纹理前端鲁棒性证据。

### 2.5 验收标准与降级路径

- 验收:测试域经验覆盖率与名义偏差 < 5pp(logistic 基线预期显著更差);A9 消融表新增 conformal 列;闭环两窗口达标。
- 降级:若覆盖率保持但轨迹无增益 → 写成"校准安全性分析"小节(raw q 有害的既有证据使该小节独立成立),σ 重写闭环改为 no-harm 论证。

### 2.6 论文产出

方法子节(~1.5 页)+ 主表(序列 × 名义/经验覆盖率 × 4 方法)+ reliability diagram + 按模式 ECE/Brier 表。

### 2.7 当前验证状态(2026-06-14)

H07 的旧 `geometry_mode` 标注把高 dropout 的 identity-churn 帧误放进 `planar_near_wall`,导致 Mondrian held-out 表失真。已完成两项修正:

1. gate 使用 raw-degradation quality,跟踪仍使用 adaptive CLAHE;
2. `planar_near_wall` 增加稳定性条件 `dropout_ratio <= 0.20`,把“Homography 像平面但 KLT 身份在跳”的 H07 帧归回 degraded,保留 A06 稳定平面。

新 mode 分布:

| window | normal | degraded | planar | severe |
|---|---:|---:|---:|---:|
| H06 2280-2490 | 100.0% | 0.0% | 0.0% | 0.0% |
| H07 1660-1950 | 30.6% | 59.8% | 0.0% | 9.6% |
| A06 2210-2460 | 0.0% | 6.0% | 94.0% | 0.0% |
| AFRL-FL 80-319 | 50.0% | 49.6% | 0.0% | 0.4% |
| AFRL-FR 5-410 | 37.9% | 58.4% | 0.0% | 3.7% |

新 leave-one survival-conformal 95% coverage(Mondrian):

| held-out | empirical coverage | error |
|---|---:|---:|
| H07 | 94.69% | -0.31 pp |
| H06 | 97.30% | +2.30 pp |
| A06 | 98.73% | +3.73 pp |
| AFRL-FL | 92.79% | -2.21 pp |
| AFRL-FR | 95.45% | +0.45 pp |

可写结论:在修正 stable-planar/identity-churn 混淆后,95% survival-conformal 达到跨数据集近似名义覆盖。不能写:80/90% 档全域都达标,或 Mondrian 在所有置信度上都优于 global。详细报告见 `logs/conformal_calibration/c1_dropstable_update_20260614.md`。

### 2.8 当前验证状态(2026-06-15)

C1 的主结果现在可以直接写进论文正文,但只写 95% 档。

新总结见 `logs/conformal_calibration/c1_paper_ready_95_summary_20260615.md`。最稳妥的主写法是:

> After separating stable planar scenes from high-dropout identity churn, the 95% Mondrian conformal calibration achieves near-nominal feature survival coverage on held-out AQUALOC and AFRL underwater windows.

可直接引用的结果:

| held-out | Mondrian 95% |
|---|---:|
| H07 | 94.69% |
| H06 | 97.30% |
| A06 | 98.73% |
| AFRL-FL | 92.79% |
| AFRL-FR | 95.45% |

该结果说明两件事:

1. C1 已经不是“实验想法”,而是可以作为主文方法结果写出来。
2. 80%/90% 档仍然不稳,不要硬写成全面成功; residual-ratio 继续放附录。

---

## 3. C2 — 信息感知连续几何模式后验(调度器升级)

### 3.1 创新点表述(paper-ready)

> 我们提出**质量加权的信息感知连续退化后验**:用 q 加权空间分布、网格覆盖、H/F 几何残差构成可观性代理,在其上训练轻量多标签 sigmoid 后验 `p_planar / p_degraded / p_severe / p_normal`,以连续预算函数调度 learned sidecar、LoFTR 平面补点与 Homography recovery,替代脆弱的硬阈值触发——消除边界抖动、允许模式共存、并为每次触发提供信心刻度。

**Related work 定位**:退化感知自适应在 LiDAR 圈已成熟(LODESTAR、AdaLIO、chi-square 退化检测),但被动视觉前端的连续退化后验调度无先例;与 RL 调度路线(Messikommer ECCV 2024)相比,本方法 model-based、可解释、可离线验证。**不写"首次 FIM 用于 VO"**——第一版是 FIM-inspired observability proxy,真 6DoF FIM 作为增强版/附录。

### 3.2 方法、实现与实验

**完整技术方案、伪标签构造、shadow-mode → posterior-gated 三阶段路线、决策门槛见 `papers/information_aware_continuous_mode_posterior_plan.md`(2026-06-12),以该文档为执行基准。** 摘要:

| 阶段 | 内容 | 文件 |
|---|---|---|
| 1 | shadow-mode 信息代理,只记日志不改调度 | `uw_frontend/geometry/information_proxy.py`、`uw_frontend/configs/experiments/information_posterior_shadow.yaml` |
| 2 | 历史正反例伪标签 + 线性 sigmoid 后验,留出验证 AUC/jitter | `uw_frontend/scheduler/continuous_mode_posterior.py`、`scripts/train_mode_posterior.py`、`scripts/evaluate_mode_posterior.py` |
| 3 | posterior 作为 budget multiplier 接入 XFeat/LoFTR/H-recovery,不替代安全门控 | 调度器接入 + VINS 闭环 |

### 3.3 与 C1/C3 的接口(本规划新增的执行约定)

- C1 校准后的 q 进入信息代理权重(`q_weighted_spread`、`W_i = 1/σ_i²`);
- C2 输出的 `p_mode` 是 C1 的 Mondrian 软分桶变量、C3 的风险分桶变量;
- 写作时 C1/C2/C3 合并为 "Calibrated Trust Pipeline" 一章三节。

### 3.4 验收标准

按原规划文档 §7:低纹理窗口触发 AUC 高于硬阈值、正常纹理 false trigger 不升、posterior jitter 低于硬模式 jitter、ablation 证明后验调度优于硬 4 态;VINS 闭环不达标则降级为"调度诊断与可解释性模块"。

---

## 4. C3 — Conformal Risk Control 导出门(风险受控的后端接口)

### 4.1 创新点表述(paper-ready)

> 我们首次把 **conformal risk control**(Bates/Angelopoulos)用于 SLAM 测量导出决策:以 backend APE 退化量为损失 `loss(τ) = max(0, APE_export − APE_baseline − ε)`,在 no-harm 校准窗口集上按退化模式拟合导出阈值 `{τ_normal, τ_degraded, τ_planar, τ_severe}`,使学习特征导出造成的期望轨迹损失被控制在用户指定的 α 之下——把 "≥2 新网格" 硬启发式替换为带上界保证的自适应门,并用 A09 反例 / A08 中性例做验证。

**Related work 定位**:CRC 已用于 HRI 规划(IROS 2025, arXiv 2603.10392)和医学分割 FDR 控制(arXiv 2504.04482),SLAM/VIO 测量门控无先例。本项目的独有优势:反例(A09)、中性例(A08)、重复稳定 no-harm 窗口(H07、AFRL-FL/FR)窗口库齐备,反例审计(2026-06-08)直接成为 CRC 校准素材——**负结果档案升格为方法论组件**。
> **APE 损失表准入闸(2026-06-15)**:只有 baseline 重复方差(max/median)低于固定阈值的窗口才能进入 APE 风险表。H07/AFRL-FL/FR 通过;**A06 不通过(单窗口 APE 重放跨度 0.05-0.30m),只能经前端指标损失进入,不进 APE 损失表**。

### 4.2 方法

1. 第一阶段先做**窗口级 no-harm 风险审计**:用已有闭环结果评估策略是否会让 APE 相对 baseline 增大超过 ε。**前置:每个窗口先跑 ≥3 次 baseline 重复,方差超阈(max/median ≥ 1.5×)的窗口(如 A06)只进前端指标损失,不进 APE 损失表。**
2. 第二阶段再做正式导出阈值族:τ ∈ {new-cell 数 1/2/3/4} × {导出比例上限} × {初始 q 上限}(先只做 new-cell 一维,够主表)。
3. 校准:对每个 τ,在校准窗口集上用 VINS 重放结果计算经验风险 R̂(τ);选满足 `R̂(τ) ≤ α − 修正项` 的最宽松 τ(Learn-then-Test 流程)。
4. Mondrian:按 C2 模式(过渡期用硬模式)分桶各自拟合 τ_mode。
5. 风险粒度:**窗口级**(非帧级)——VINS 窗口有限,论文按 window-level CRC + bootstrap 置信区间诚实报告,并以此与逐时刻 CRC(HRI 圈)区分。

### 4.3 实现任务清单

| # | 任务 | 文件 | 量级 |
|---|---|---|---|
| 1 | 离线 CRC 拟合器:窗口级风险表、bootstrap CI、策略/alpha 选择器;后续接 τ 扫描 | `uw_frontend/evaluation/conformal_risk_export_gate.py` | 已完成第一版 |
| 2 | 窗口库整理:每窗口 {导出统计, APE_export, APE_baseline, mode} 汇总 CSV | 从 `logs/backend_evidence_compact.md`、`tmp_jun06/07_*_summary.csv`、反例审计提取 | 脚本 ~100 行 |
| 3 | 验证:CRC τ 在测试窗口的违反率、A06 放行 / A09 拦截复检 | 同文件 1 的 evaluate 子命令 | — |
| 4 | (验证通过后)τ 以配置项进入 `export_vins_features.py` | 只加配置读取,**不改既有门逻辑结构**(CLAUDE.md 红线) | 最小 diff |

### 4.4 实验矩阵

- 校准集:H07 / A08 等 no-harm 与中性窗口;测试集:A06(应放行)、A09(应拦截)、NTNU Fjord、Tank。
- 主表:{固定 τ=2(现状), CRC 全局, CRC Mondrian} × {经验违反率, 平均 APE 退化, 平均导出特征数}。

### 4.5 验收标准与降级路径

- 验收:测试窗口经验违反率 ≤ α;A09 负例被拦截;A06 的 learned sidecar 导出**准入决策**仍可复检(feature 流确定性,jaccard 1.0),但 A06 不参与 APE 违反率统计;拟合出的 τ 若恰为 2,则"≥2"获得理论解释(同样是发表点)。
- 降级:窗口数不足以支撑分桶 → 只报全局 CRC + 把 Mondrian 列为 future work;风险界写成 bootstrap 区间。

### 4.6 论文产出

方法子节(~1 页)+ 违反率主表 + 风险曲线图 R̂(τ) + 正反例双向案例段。

### 4.7 当前验证状态(2026-06-14)

已完成 C3 第一阶段离线实现:`uw_frontend/evaluation/conformal_risk_export_gate.py`。该脚本读取现有窗口库,计算

`loss = max(0, APE_candidate - APE_baseline - ε)`

并输出 clean/appendix 分组、平均损失、违反率、bootstrap CI、策略选择器结果。当前报告见 `logs/conformal_calibration/c3_crc_initial_20260614/c3_crc_initial_report.md`。

当前 clean 库包含 7 个候选窗口/方法;`NTNU Fjord4 0-30` 因 solver failure 被排除出主表,只可作附录诊断。

| ε(no-harm 容忍) | n | mean relative delta | worst relative delta | mean excess loss | violation rate | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 2% | 7 | -1.78% | +3.20% | 0.17% | 14.29% | 只能作敏感性分析 |
| 5% | 7 | -1.78% | +3.20% | 0.00% | 0.00% | 可作主 no-harm 容忍度 |

关键解释:

- A06 2210-2460 的 conformal95 blend0.85 相对 baseline 是 `+3.20%`,所以不能宣称全库满足 2% no-harm。
- H07、AFRL-FL、AFRL-FR clean 窗口均满足 2%/5% no-harm;AFRL-FR 85-105 目前是 single run,补重复后再放主表更稳。
- `alpha_scan_vins_curve.csv` 的单次扫描显示 `blend alpha=0.85/0.90` 风险最低,但 A06 在 0.70/0.80/0.95/0.99 有大幅尖峰,更像 VINS replay/初始化敏感。alpha 不能用单次扫描写成理论最优,下一步必须补 3-5 次重复。
- 当前 C3 还不是正式的 `new-cell τ` CRC claim,因为窗口库不是 τ 扫描矩阵。下一步是生成 `{new-cell τ, export-ratio, initial-q}` 扫描表,再用同一个脚本选择风险受控阈值。

### 4.8 当前验证状态(2026-06-15)

C3 现在已经从“只有经验风险审计”推进到“有 tau 扫描读入能力”,但还没到正式结论。

新补的脚本能力:

- `uw_frontend/evaluation/conformal_risk_export_gate.py` 现在支持 `--tau-scan-csv`。
- 它能从 `run` / `run_dir` 里自动识别 `nc0/nc1/nc2/nc3`，把 tau 扫描和已有风险审计放到同一个表里。
- 它会输出 `c3_tau_scan_risk_rows.csv`、`c3_tau_scan_risk_summary.csv`、`c3_tau_scan_risk_by_dataset.csv`。

当前可直接说的结论:

1. tau 扫描入口已经接上了，后面可以直接喂 tau×budget 的矩阵。
2. 现在还没有正式的 tau×budget VINS 矩阵，所以不能写“CRC 已经选出最终 tau”。
3. 下一步要跑的是最小矩阵：A06、H07、A09 各自扫 `tau = 0/1/2/3`，再看不同 budget 下的 no-harm 和正收益边界。

---

## 5. C4 — TAP(any-point tracker)作为 severe-only 恢复层:首个水下系统评测

### 5.1 创新点表述(paper-ready)

> 我们提供 transformer any-point tracker(CoTracker3)作为 VIO 恢复层的**首个水下系统评测**:仅在退化后验 `p_severe` 高时按需调用 16 帧时间窗重建失追/被遮挡轨迹,与 XFeat / SP+LG / LoFTR 恢复层在同一调度框架下诚实对照,并给出浑浊水体与平坦底质下 TAP 的失败模式分析(悬浮颗粒误判遮挡、低纹理可见性头失效等)。

**Related work 定位**:LEAP-VO(CVPR 2024)与 CoTracker 系列均无水下评测;本贡献允许且预期可能为部分负结果——"TAP 在水下何时有效"本身是清晰的实验贡献,与本项目负结果档案传统一致。

### 5.2 实现任务清单

| # | 任务 | 文件 | 量级 |
|---|---|---|---|
| 1 | CoTracker3 适配器(实现 `BaseMatcher`,lazy-load 官方权重,维护 16 帧环形缓冲) | `uw_frontend/matchers/cotracker_adapter.py`(新) | ~250 行 |
| 2 | 触发接入:`p_severe > τ`(C2 未就绪时用现有 `severe_low_texture` 硬模式) | `hybrid_tracker.py` 现有 `learned_matcher` 插槽,零框架改动 | 配置 + 少量胶水 |
| 3 | 实验配置 | `uw_frontend/configs/experiments/cotracker_severe_only.yaml`(新) | — |
| 4 | 救回率/误接率分析脚本 | `scripts/analyze_tap_recovery.py`(新) | ~150 行 |

### 5.3 实验矩阵

- 序列:A06、AFRL-FL/FR、Tank、UVVID(+H07 作 no-harm 对照)。
- 大表:{KLT, +XFeat, +SP+LG, +LoFTR, +CoTracker(severe-only)} × {dropout, median track age, grid coverage, epipolar median, runtime ms/frame}。
- 分析图:severe 帧上"成功救回率 vs 误接率";失败案例蒙太奇(颗粒遮挡误判、平坦区漂移)。

### 5.4 验收标准

正负结果均可发表:若 severe 窗口 dropout/track age 改善 → 进方法章;若不改善 → 写失败模式分析 + selective-trigger 必要性论证,放实验章。唯一不可接受的结局是"没跑完对照矩阵"。

---

## 6. 附录级加分项(不进主线,时间富余再做)

| 项 | 内容 | 工时 |
|---|---|---|
| Good-Features 对比消融 | 把 max-logdet 子模贪心选点(Zhao & Vela, ICRA'19/T-RO'20)接到 `select_backend_measurements` 作对照,σ 用 C1 校准值;挡"为什么不用信息论选点"的问题 | 3–4 天 |
| Enhancement-invariance q_i | 对现有 bag 离线跑多种增强(WB/CLAHE 等),检验 q_i 跨增强稳定性,并入 C1 训练细节附录 | 3–4 天 |
| MeasurementSelection 参数扫描 | 3–5 组关键参数组合小消融,挡参数敏感性质疑 | 2 天 |

---

## 7. 执行路线图(总计 5–7 周,全部离线)

| 顺序 | 项 | 工时 | 依赖 | 可并行 |
|---|---|---|---|---|
| 1 | C1 conformal 校准器 + 覆盖率评测 | 1–1.5 周 | 无(数据现成) | 与 2、3 并行 |
| 2 | C2 阶段一 shadow-mode | 1 周 | 无 | ✓ |
| 3 | C3 窗口库整理 + CRC 拟合 | 1 周 | 无 | ✓ |
| 4 | C2 阶段二/三(伪标签后验 + posterior-gated) | 1.5–2 周 | 建议接入 C1 的 σ | — |
| 5 | C4 CoTracker 适配器 + 评测矩阵 | 1–2 周 | C2 的 p_severe(可先用硬模式) | 与 4 部分并行 |
| 6 | 三层联合 VINS 闭环重放 + 论文图表 | 1 周 | 1–4 | — |

裁剪原则:时间不够先砍 C4(独立成章,可留作下一篇);**C1 + C3 性价比最高**——各 ~250 行代码、数据全现成、直接挡评审两大必问,务必保住。

### 7.1 现在最短的下一步

1. 把 C1 的 95% 主表、reliability diagram、按模式分解图整理成论文图。
2. 用新加的 `--tau-scan-csv` 跑 A06/H07/A09 的 tau 扫描汇总表。
3. 再把 tau 扫描接到一小轮 VINS 重放,先看 no-harm,再看 A06 是否还能保正收益。
4. 先不碰 80%/90% 和 residual-ratio 主结论,它们现在还不稳。

---

## 8. 论文骨架映射

| 章节 | 内容 | 图表 |
|---|---|---|
| Method-A Calibrated Measurement | C1 Mondrian conformal σ_i | 覆盖率主表、reliability diagram、按模式 ECE/Brier |
| Method-B Degradation Posterior | C2 连续模式后验 | p_mode 时间序列叠加图、ROC/PR、jitter 对比表 |
| Method-C Risk-Controlled Interface | C3 CRC 导出门 | 违反率主表(H07/AFRL 稳定窗口)、R̂(τ) 风险曲线、A09 反例案例、A06 前端指标准入案例 |
| Experiments(补充研究) | C4 TAP 水下评测 | 5 配置 × 5 指标大表、救回率/误接率图、失败案例 |
| Appendix | Good-Features 消融、enhancement-invariance、参数扫描、真 6DoF FIM 增强版 | — |

## 9. 关键引用清单(related work 必引)

- arXiv 2303.02207 — Conformalized VO(pose 级,与 C1 区分层级)
- arXiv 2409.09479 — MAC-VO, ICRA 2025 Best Paper(C1 最近竞品)
- arXiv 2510.01648 — Statistical Uncertainty Learning for VIO(C1 对照叙事)
- arXiv 2311.03722 — Inertial-guided correspondence uncertainty
- arXiv 2401.01887 — LEAP-VO, CVPR 2024(C4 的空白依据)
- arXiv 1905.07807 / 2001.00714 — Good Feature Selection / Matching(附录消融引用)
- arXiv 2603.10392 — CRC for HRI planning, IROS 2025(C3 区分应用域)
- arXiv 2504.04482 — CRC for medical segmentation FDR(决策级 CRC 先例)
- LODESTAR / AdaLIO 等退化感知 LiDAR 工作(C2 衬托视觉空白)
- Messikommer et al., ECCV 2024 — RL 前端调度(C2 的可解释性对照)

## 10. 下一步执行表

下面这张表按“先消反例,再补重复,再固化正例/no-harm,最后做后端外推”的顺序排。主后端仍然是 VINS-Fusion; OpenVINS 和 ORB-SLAM3 作为同窗口的 portability check 一起跑,不单独另起一套叙事。

| 优先级 | 任务 | 代表窗口 | 后端安排 | 验收标准 |
|---|---|---|---|---|
| P0 | 反例清理/隔离 | A09 5920-6060、A05 2800-3300、AFRL FR120-150 | 先跑 VINS 修复前后对照,再补 OpenVINS 和 ORB-SLAM3 交叉复核 | 这些窗口要么被 gate 挡住,要么被明确降级为边界样本,不进入主结果 |
| P0 | no-harm 收口 | H07 1660-1950、Tank short、AFRL FL 230-260 | VINS 3 次重复中位数 + OpenVINS 1 次 + ORB-SLAM3 1 次 | 正常纹理下 learned export 维持零或近零,APE/RPE 不劣于 baseline |
| P1 | 正例窗口固化 | A06 2210-2460/2700/2900、AFRL FR70-100/80-110/110-140 | VINS 3 次重复中位数 + OpenVINS 1 次 + ORB-SLAM3 1 次 | 低纹理窗口里 learned sidecar 必须稳定带来正收益,且跨后端方向一致 |
| P1 | 跨数据集重复 | AQUALOC + AFRL + Tank/NTNU/UVVID 中已筛出的窗口 | 每个数据集至少保留 1 个正例或 no-harm 例,都按 VINS / OpenVINS / ORB-SLAM3 跑一轮 | 不是只在单一数据集成立,而是在多个数据域上都能复现同类结论 |
| P2 | 后端迁移检查 | 从上面各挑 1 个正例 + 1 个 no-harm | 只看 OpenVINS 和 ORB-SLAM3 的结果是否跟 VINS 同方向 | 如果外部后端不一致,只把它写成“后端敏感性分析”,不扩成主结论 |

### 后端补跑顺序

| 后端 | 角色 | 先跑的窗口 |
|---|---|---|
| VINS-Fusion | 主后端,主表结果来源 | A06、H07、AFRL FR70-100、A09 5920-6060 |
| OpenVINS | 交叉验证后端 | A06、H07、AFRL FR80-110、Tank short |
| ORB-SLAM3 | 交叉验证后端 | A06、H07、AFRL FR110-140、Tank short |
