---
type: experiment-closure-plan
date: 2026-07-31
project: AQUA-FE
target_venue: IEEE Sensors Journal
publication_model: traditional
paper_scope: underwater-vins-learned-seed-frontend
status: ready-for-selector-prototype
version: v3
---

# AQUA-FE IEEE Sensors Journal 投稿实验闭环方案

## Material Passport

- Origin skills: `underwater-slam-frontend-research`, `academic-research-suite/experiment-agent`
- Origin mode: experiment planning
- Origin date: 2026-07-31
- Verification status: `METHOD-UPGRADE-CONTRACT-AUDITED`; selector prototype and experiment outcomes pending
- Version label: `isj_experiment_plan_v3`
- Workspace: `/home/ma/AQUA-FE_WS`
- VINS workspace: `/home/ma/SLAM/VINS-Fusion-origin`
- Historical reference workspace: `/home/ma/SLAM/VINS-Fusion_3-15-WS`

## 1. 投稿目标与论文范围

### 1.1 目标

以 IEEE Sensors Journal 的 Traditional publication 为投稿方向，完成一篇聚焦水下视觉传感退化与 VINS 前端增量测量选择的系统方法论文。论文集中回答以下问题：

> 在低纹理、低照度、散射和近壁水下图像中，能否将学习特征作为候选种子，经 KLT 多帧验证后，依据校准可靠性和相对现有 KLT 测量集的边际几何支撑价值，在固定预算内形成更有效的 VINS 增量测量集？

### 1.2 冻结后的论文主线

```text
underwater image degradation
  -> quality/health trigger
  -> learned seed proposal
  -> KLT multi-frame probation
  -> survival + motion + F/H correctness eligibility
  -> source-neutral calibrated reliability q_i^-
  -> KLT-conditional marginal geometric-support selection
  -> bounded feature export
  -> VINS-Fusion
```

`lineage` 在本文中承担 track provenance、accepted-track persistence 与完整删除消融。标题和贡献集中于 **reliability-calibrated marginal geometric-support selection**：在已有 KLT 测量集上评估 learned-seeded KLT 候选的增量支撑价值。MSCKF、ORB v23、历史 conformal-risk 变体和 LoFTR 优化作为机制背景与扩展证据。

### 1.3 拟验证的四个主张

跨 profile 简写固定为：`P*` 表示 promoted 的 P 或 legacy 的 P_legacy，`D*` 与 `C*` 同理映射到当前 profile 的 drop 和 matched-classical control。C2 只属于 promoted profile。

| ID | 主张 | 主证据 | 论文表述 |
|---|---|---|---|
| C1 | 在预注册低纹理水下窗口中，所提前端相对强 KLT 基线改善共同时间支持上的 VINS 轨迹 | held-out 主矩阵，`P*` vs B1 | 报告 sequence-equal 效果、置信区间与完整窗口分布 |
| C2 (promoted only) | 校准可靠性与 KLT 条件边际支撑的联合选择，在同一 master stream 和同一最大预算下优于现有距离/网格启发式及单因素选择 | P vs H confirmatory contrast；R/Q/G/QG development 的 admission-count-matched 排序消融；轨迹-测量成本 Pareto | 贡献对象是最大预算约束下的增量测量集合选择目标 |
| C3 | 通过选择的 learned proposal 提供 classical proposal 难以替代且具有轨迹价值的新测量 | exact `D*` lineage drop、matched classical `C*`、ungated learned seed | 贡献对象是 learned proposal、KLT temporal carrier 与冻结准入机制组成的测量生成系统 |
| C4 | 在预注册正常纹理窗口中，系统保持 KLT 级初始化、覆盖率和轨迹精度 | `P*` vs B1 normal no-harm 矩阵，包括零动作和非零动作案例 | 表述为预注册协议下的 operational no-harm |

### 1.4 主稿聚焦范围

- A06 mirror-inject 与 sparse LoFTR 结果作为 development profile 和评测诊断材料。
- `q_i^-` 用于前端候选效用；主实验后端统一使用 `q=1`，backend weighting 归入 appendix ablation。
- 完整 conformal-risk 控制、MSCKF 与 ORB 归入后续扩展。
- VINS-Fusion 是本文唯一主后端。
- 系统运行属性依据 H5 结果表述为 `real-time`、`selective` 或 `offline-capable`。

### 1.5 论文定位与创新边界

建议工作标题为 **Reliability-Calibrated Marginal Measurement Selection for Degradation-Triggered Underwater VINS**。方法新意不是新的 detector、matcher 或 KLT carrier，而是在退化触发、learned proposal 和多帧正确性验证之后，以“保守可靠性 × 相对当前已保留测量集的边际视域支撑”决定哪些 lineage 进入 VINS。

| 邻近方向 | 本文的区分点 | 禁止越界的表述 |
|---|---|---|
| classical/learned feature ranking | 在固定 selector-blind candidate stream 上，评估候选相对已有 KLT 和 active accepted lineage 的边际价值 | 不宣称新的 detector 或通用 learned feature score |
| scene-adaptive frontend/matcher selection | trigger 只决定何时产生候选；本文方法决定候选 lineage 的增量准入 | 不宣称完整的场景级 frontend architecture search |
| uncertainty/quality weighting | `q_i^-` 仅进入前端选择，主后端所有受控 arms 均使用 `q=1` | 不把轨迹改善归因于 backend residual weighting |
| FIM/observability-aware selection | 3x3 目标是 image-plane support surrogate，用于比较视域支撑的边际增益 | 不称为 6DoF FIM、位姿可观测性或后端协方差最优化 |

Related Work 必须显式对照 Shi-Tomasi/Good Features to Track、Learned Good Features to Track、SuperPoint/LightGlue、XFeat、LoFTR、CHAMELEON-SLAM 与 CF2-SLAM，但主张区分点固定为“相对 selector-independent KLT master stream、经多帧验证的 learned lineage 边际准入”。正式稿件使用经核验的一手文献和准确引文，本计划的方向名称不代替 citation verification。

分支合同固定如下：`PROMOTE` profile 使用上述标题和 C1-C4；`BASELINE_ROUTE` profile 改用 selective learned-seeded KLT system 定位，只保留 C1/C3/C4，QG、C2、P-H 与 HU 全部标记为 development-only，不使用 marginal-selection 标题。

### 1.6 与现有工作的可检验区分

本文不把 XFeat、SuperPoint、LightGlue 或 LoFTR 的 detector/matcher 本身包装成新方法。论文的决策单元是 **一个可能进入 VINS 的 persistent feature lineage**，而不是单帧 keypoint、pairwise match 或后端 residual。统一定位句为：

> 我们提出面向水下退化的、可因果审计的 learned-seeded KLT 测量生成与有界准入机制：learned 模块只负责发现 KLT 未覆盖的候选 lineage，KLT 负责身份承载和短期连续性，可靠性、几何支撑与预算共同决定候选是否进入 VINS。

下表规定 Related Work 的比较轴。每一行都必须对应一个实际对照或明确的 scope boundary，不能只用“更鲁棒”作结论。

| 现有路线 | 它通常优化的对象 | 本文填补的具体缺口 | AQUA-FE 的可检验对照 |
|---|---|---|---|
| Shi--Tomasi/GFTT + KLT | 便宜、连续的局部跟踪 | 低纹理/近平面时缺少新的可追踪出生点 | B1 vs P：KLT 仍是 carrier；报告新增 lineage 的 survival、novelty 和 VINS 贡献 |
| Learned Good Features to Track | 训练 detector/feature 使 tracking error 或 trackability 更好 | 其决策对象是 detector/feature 学习；本文进一步规定“一个 learned 点何时有资格成为长期 VINS 测量”的在线、可审计 admission contract | B2、H、P；同一 master stream 上比较 ungated、heuristic 和 QG admission |
| SuperPoint+LightGlue、XFeat、LoFTR 等 learned matcher | 单帧/成对检测与匹配精度或覆盖 | pairwise match 不等于长期 VINS 约束，短 burst 可能污染后端 | M vs B1/P；匹配图像尺度、预算、backend、`q=1` 和 evaluator，M 的 carrier/measurement formation 作为目标变量；报告 lineage age、exact drop 和成本 Pareto，不做匹配排行榜 |
| 场景自适应/混合前端（如 CHAMELEON-SLAM） | 在场景间切换 feature family，或对后端因子降权 | 该类工作主要处理场景级模式/权重；本文单独回答候选 lineage 的边际准入，因而可隔离 learned lineage 的价值 | trigger 只决定是否提候选；H/P 共享 selector-blind KLT master stream，P 只改变 admission |
| 不确定性/保形校准 SLAM（如 CF2-SLAM） | 因子形成后校准协方差或调整图优化权重 | 校准位置在 factor 形成之后；本文把 source-neutral reliability 用在测量导出前的 lineage admission | `q_i^-` 只用于前端选择，主后端统一 `q=1`；报告 calibration coverage/ECE 与 P/D/C-QG |
| FIM/observability-aware selection | 直接优化后端信息矩阵、可观测性或协方差 | 通用后端目标代价高且难与现有 KLT 集合作增量准入 | 只主张 3x3 image-plane support surrogate；H vs P、Q/G/QG 和运行时 Pareto，禁止 6DoF FIM 表述 |

因此，本文的“优越性”不是“learned 点更多”或“网络匹配更准”，而是以下四个可分解层级：

1. **可归因的后端贡献**：在相同 master stream 和 VINS 合同下，`P` 相对 exact whole-lineage drop `D` 仍改善，并相对 matched-classical `C-QG` 保留 learned-specific 增益。对应 C2/C3、H2/H3；没有这些对照时不得把 full-vs-KLT 差异归因给 learned。
2. **选择性和 no-harm**：退化触发才运行 learned proposal；正常纹理可以是 zero-action、byte-identical KLT fallback，非零动作也必须不超过预注册损失。对应 C4/H4a/H4b；zero-action 只能证明 fallback 合同，不能单独证明 active learned 安全。
3. **固定预算下的几何效率**：相对当前 KLT 与 active lineage 选择非冗余、可靠的增量支撑，而不是最大化候选数。对应 H/P、R/Q/G/QG 的 admission-count-matched Pareto、coverage 和 exported dose；若 `PROMOTE` 不成立，该层降为 development-only。
4. **工程可部署性**：复用 VINS-Fusion、保留 KLT 的时间语义、限制 learned 调用和输出剂量，并记录 deterministic lineage/selection hash。对应 H5、运行时资源表和 clean-room reproduction；未完成 profiling 前只能称 `selective` 或 `offline-capable`，不能称 `real-time`。

主文应按“pairwise learned match 不能直接转化为 VINS 长期约束 -> learned seed 经 KLT probation 变成 lineage -> reliability/geometry/budget 决定准入 -> exact-drop 与 no-harm 证明收益边界”的顺序展开。这样网络来源可以替换，论文贡献仍保持不变；这也是 source-neutral calibrator 和同一 selector API 必须冻结的原因。

### 1.7 优越性主张的证据门槛与措辞锁

下列措辞可以作为稿件摘要/引言的候选句，但只有右侧证据齐全时才能升级为 confirmatory claim：

| 可用主张 | 证据门槛 | 未达标时的降级表述 |
|---|---|---|
| “在低纹理水下窗口中改善 VINS 轨迹” | H1 的 sequence-equal P*--B1 common-support 结果、完整 failure 分母和 held-out manifest | “在若干预注册低纹理窗口显示改善，跨序列效果待确认” |
| “选择器本身优于现有启发式” | G2A `PROMOTE`、H/P selector-only master-stream equality、HU 和 Q/G/QG Pareto | “提出并审计一个候选选择器；选择器优势属于 development evidence” |
| “learned proposal 带来本体贡献” | exact `D*`、matched `C*`、lineage survival/novelty 与 H2/H3 | “系统包含 learned proposal；full-vs-baseline 差异不能单独归因” |
| “保持正常纹理无损” | 全部 normal 分母、active/non-active 分层、至少 3 个非零动作窗和 H4a/H4b | “提供 zero-action fallback 和有限 no-harm 证据” |
| “可在线运行” | H5 达到 `PROFILED_REAL_TIME`，且报告 P95、queue drop=0 和硬件 | “selective” 或 “offline-capable” |

在任何版本中禁止使用以下表述：`new detector/matcher`、`first conformal SLAM`、`6DoF FIM optimality`、`all learned points are useful`、`LoFTR explains mirror-inject gain`、`universally superior across domains`。A06 mirror-inject 的大幅改善必须与 sparse LoFTR 三路结果分开；若 G2A 走 `BASELINE_ROUTE`，标题和摘要回退到 `selective learned-seeded KLT system`，C2/P-H/HU/QG 只作 development 机制结果。

### 1.8 最小差异化证据包

为让上述区分在审稿中可验证，主分析 bundle 至少新增/显式汇总：

- `B1/B2/H/P/D/C-QG/M` 的同 backend、同预算、`q=1`、common-mask 比较；M 必须是实际可运行的 direct/periodic learned baseline，而不是离线匹配分数；
- P 与 H 的逐帧 candidate-pool hash、selection hash、实际 admission/export dose 和 P95 latency；
- `P-D` 的 whole-lineage drop、`P-C-QG` 的 matched-dose balance，以及 birth--survival--export--drop 事件链；
- low/normal、active/non-active 四象限的 APE/RPE、coverage、init、solver-risk、learned count 和 first/last gap；
- APE/观测剂量/learned 调用成本的 Pareto 图，并标出 H5 的 profile label；
- Related Work 中每个近邻方向对应的一手引用、机制差异和“本文不主张什么”列。

这些资产分别落到现有 `selector_ablation.csv`、`selector_pareto.csv`、`matched_control_balance.csv`、`failure_table.csv` 和 `runtime_summary.csv`，不另设一个无法回溯的“优势分数”。

### 1.9 当前证据锚点与可用边界

已有结果可用于说明机制方向，但不能替代冻结后的 confirmatory 矩阵。主文可优先使用下表的“支持”列，并在结果中同时展示“不能支持”列：

| 证据锚点 | 当前结果 | 可以支持 | 不能支持 |
|---|---|---|---|
| AQUALOC A06 sparse/degraded 三路 | sparse KLT `0.265652/0.113263`；SP-LG no-LoFTR `0.255863/0.108435`；+LoFTR `0.118616/0.062520`，确认 LoFTR 10 observations | 极端低纹理/近平面中，少量经 KLT 验证的 LoFTR sidecar 能形成后端可见的增量约束 | LoFTR 普遍优于 KLT；或把 mirror-inject 的大幅改善全部归因给 10 条 LoFTR |
| AQUALOC H07 normal no-harm | KLT `0.050207/0.113417`；proposed `0.050207/0.113416`；LoFTR export `0` | 退化触发与 exact KLT fallback 可以避免正常纹理的额外扰动 | 有动作时在所有正常场景都无损；需补至少 3 个 active-normal 窗 |
| 冻结 learned-active development 窗 | full 相对 KLT APE 胜 `10/11`，相对 whole-lineage drop 胜 `11/11`（历史开发统计） | lineage 归因和选择性增量观测是值得进入 confirmatory 的机制假设 | 跨域普遍优于、无筛选泛化或最终显著性；这些数字仍受 development/窗口身份约束 |
| A09 反例与 solver-risk 审计 | 存在 full APE 劣于 KLT 的窗口，历史 full 还出现 solver-risk | 方法必须以 selective/no-harm 和失败分母为一等结果，避免 cherry-pick | “所有 learned 候选都有效”或“只要更多点就更稳” |

因此，优越性应写成**条件性、可归因、带成本和失败边界的优越性**：在预注册退化窗口、相同后端和最大预算下，系统能否用更少而更可靠的新增 lineage 改善 VINS；在正常纹理中则保持 KLT 行为。该句比“学习前端全面超过现有方法”更窄，但正好对应可复核的实验合同。

## 2. 当前证据如何使用

### 2.1 Development 与机制证据

以下资产已经参与窗口搜索、参数选择、profile 设计或结果解释，统一归入 development 集；confirmatory 胜率与显著性统计使用新冻结矩阵：

- `papers/frozen_frontend_eval_20260714/manifest.csv` 中全部 21 个 case；
- `logs/jul21_final_online_master_status.csv` 中全部窗口；
- AQUALOC A06 `2210-2460`、A07 `10800-11200`、A09 `4000-4400/6000-6200`、A10 `2400-2800`；
- NTNU fjord/mclab 已扫描窗口；
- UVVID Orientkaj 全时段扫描；
- CIRS `s450/s575/s840/s900/s960`；
- AFRL Cave/Bus/Gennie/Cemetery 已扫描窗口；
- Tank short、UMA-VI sample 和当前 H07 no-harm 窗口。

这些结果用于说明方法发现过程、选择冻结参数、展示窗口级结果、调试评测器和构建消融。

### 2.2 当前最可靠但仍需重评的资产

- final-online A10 `2400-2800` 和 A09 `4000-4400`：验证评测修正前后的方向稳定性。
- frozen 20-cluster：提供历史描述性结果和窗口分布。
- H07 mirror no-harm：提供 exact fallback 单元案例。
- 历史 q reliability/C1 轨迹与 full conformal-risk 结果：作为 development 证据保留；当前 `q_i^-` calibration 由 P03B 冻结。

## 3. 总体阶段与验收标准

| 阶段 | 任务 | 通过条件 | 下一步 |
|---|---|---|---|
| G0 | 修复轨迹评测合同 | 唯一/插值关联、公共时间支持、`evo` 交叉验证完成 | G0 完成后启动数据冻结 |
| G1 | 历史排除、数据资格与选窗协议 | history/eligibility manifest 完成，选窗规则在 development 上确定并 hash | external 阶段先完成 metadata/reference 审计 |
| G2 | 上游方法、对照和环境候选冻结 | trigger、proposal、KLT probation、correctness gates、classical proposer/calibration adapter、runner、VINS source hash 和 bag schema 明确 | G2A selector shadow |
| G2A | 边际支撑选择器 shadow 与晋级 | 合成测试、6 个 development 窗口、排序审计和 `PROMOTE/BASELINE_ROUTE/REVISE` 决策完成 | PROMOTE 后进入 G2B；BASELINE_ROUTE 进入 P04/P05 legacy integration |
| G2B | canonical selector migration | pooled reliability calibration、H/P master-stream audit、selector hash 和接口探针完成 | 进入 P04/P05 controls/baseline integration，通过后再进入 G3 |
| G3 | contract probe、最终方法锁与数据冻结 | arm 合同通过；随后用冻结 KLT-only 规则生成 confirmatory manifest/arm order 并 hash | 合同更新时创建新候选版本 |
| G4 | confirmatory 主矩阵 | manifest 全部完成，所有运行状态均保留 | 全量完成预注册队列 |
| G5 | 统计、运行时和图表 | 单一机器表生成所有数字，统计单位正确 | 生成 Results 资产 |
| G6 | 投稿验收 | claim-evidence、复现、scope 和图表检查全部通过 | 确定 READY、CONDITIONAL 或 REVISE |

## 4. G0：轨迹评测合同修正

这是本计划的第一优先级。后续结果统一使用修正后的 evaluator。

### 4.1 GT 与估计轨迹关联

主评测统一使用 **reference-timestamp resampling**：

1. 对 reference trajectory 去重并按时间排序；令 `evaluation_rate_hz` 为集合 `{1,2,5,10}` 中低于或等于 metadata nominal reference rate 的最大值，以预注册 window start 为锚点生成 uniform grid `t_k=start+k/rate`；nominal reference rate >=1 Hz 的数据进入 primary trajectory table；
2. 将 reference 和每个 arm 的 translation 线性插值、orientation 用 quaternion SLERP 插值到同一 uniform grid；插值范围由有效左右 bracket 界定；只有位置 reference 时使用 translation 指标；
3. 左右 bracket 齐全且 bracket gap 位于相应 max gap 内的 grid point 标记为有效；reference 或 estimate 的长 gap 形成 invalid mask；
4. `nominal_reference_rate_hz`、`evaluation_rate_hz`、`max_reference_gap_s`、`nominal_estimate_rate_hz`、`max_estimate_interp_gap_s`、window-start anchor 和 tie-break 按 dataset 写入 `evaluator_protocol_v1.md`，默认 gap 上限为对应 nominal period 的 2.5 倍；
5. legacy monotonic one-to-one nearest association 用于旧指标诊断，双方索引唯一，采用全局最小总时间差 assignment，并以较早 timestamp 作为等距 tie-break。

评测合同：

- 每个稀疏 GT pose 在 legacy association 中最多使用一次；
- 报告 raw/unique reference pose 数、evaluation-grid 数、每个 arm 的 valid grid 数、bracket gap P50/P95/max 和被拒绝原因；
- 坐标轴、单位、timestamp offset 和 reference-to-camera/body transform 来自 calibration/provenance，并在 dataset manifest 冻结；
- 只有位置参考时报告 translation APE/RPE，并在数据表注明 reference 类型。

### 4.2 公共时间支持

每个 `window x repeat x preregistered contrast` 内，参与该 contrast 的 arms 在同一 reference grid 和 valid mask 上计算：

```text
valid_common(t) = valid_reference(t)
                  AND all(valid_arm(t) for arm in contrast)
```

相邻有效 grid timestamp 的间隔大于 `max_reference_gap_s` 或任一 arm 的插值 gap 上限时划分为不同 segment。RPE pair 位于同一 segment。APE contrast 的有效标准为至少 30 个唯一 grid poses、time span >=10 秒且 valid-mask coverage >=原窗口的 70%；1 s RPE 的有效标准为 10 个同 segment pairs。其余情况标记 `INSUFFICIENT_COMMON_SUPPORT`，并保留在预注册分母中。

promoted profile 的预注册 support group 为：`H1/H4a/H4b: P-B1`、`HU: P-H`、`H2: P-C-QG`、`H3: P-D`、system reference `P-B0`、controlled modern comparison `P-M`，core support 为 `B1-B2-H-P`。legacy profile 明确为 `H1/H4a/H4b: P_legacy-B1`、`H2: P_legacy-C_legacy`、`H3: P_legacy-D_legacy`、system reference `P_legacy-B0`、controlled modern comparison `P_legacy-M`，core support 为 `B1-B2-P_legacy`，HU=`NOT_APPLICABLE`。每个 contrast 同时报告各 arm 的完整 coverage、first output delay、last output drop 和 gap。

### 4.3 双实现交叉验证

- primary evaluator：修正后的项目 evaluator；APE 使用每个 arm 在相同 common mask 上独立估计的固定尺度 SE(3) rigid alignment；RPE 定义为对齐后 global-frame positional delta 的 1 s 差，并在同一 valid segment 内配对；
- reference evaluator：标准 `evo_ape` / `evo_rpe`，输入以 17 significant digits 序列化。APE 使用 timestamp 完全相同的 common-grid TUM pairs；RPE 将每个 valid segment 分别写为“aligned position + identity quaternion”TUM，执行 `evo_rpe ... -r trans_part -d evaluation_rate_hz -u f`，再按全部 segment error 样本汇总。该写法与 positional-delta 定义一致，并保持 timestamp tolerance <=1e-6 s；
- 在 A10、A09、A06、一个 NTNU/UVVID 和一个正常窗口上交叉验证；
- 实际 evo version、完整命令和 config 写入 protocol；当前脚本中的 `10 frames` RPE 标记为 legacy metric，论文主指标采用 1 s RPE；
- 同一 common-grid pairs 和相同公式上两实现的 RMSE 绝对差应小于 `max(1e-6 m, 1e-6 * RMSE)`；达到该数值条件后 G0 完成。

### 4.4 G0 资源决策

使用冻结旧 bag 重算 A10/A09/A06 等 development 结果，保持原 export 与 gate。G0 技术状态由 evaluator 合同、测试和 evo 数值交叉验证决定。

资源决策使用机器判据：历史 full arm 记为 `H_legacy`，对应 whole-lineage-drop 记为 `D_Hlegacy`。对 A10 和 A09 final-online，分别计算旧启发式结果的 corrected common-mask `gain(H_legacy,X)=1-APE_Hlegacy/APE_X`，其中 `X in {D_Hlegacy,B1}`。两例四个 gains 全部 `>=1%` 且 H_legacy 无 differential hard failure 时记 `HISTORICAL_SIGNAL_PRESERVED`；其余可评估/支持不足情形记 `HISTORICAL_SIGNAL_REVIEW`；两例的 H_legacy-D_Hlegacy gain 均 `<=-1%` 或 H_legacy 出现 differential hard failure 时记 `HISTORICAL_SIGNAL_REDIRECT`，转向方法复核。A06 profile 作为诊断材料。各状态沿用同一冻结 threshold。

历史报告保留，并新增 `legacy_metric`、corrected full-support、corrected common-mask 对照表；论文数字采用 corrected metric。

## 5. G1：数据身份、资格与选窗预注册

### 5.1 三层数据身份

| 层级 | 定义 | 可以支持什么 |
|---|---|---|
| Development | 任何已经看过 learned/VINS 结果或参与调参的窗口 | 方法开发、消融解释、case analysis |
| Sequence-held-out | 历史未出现的 sequence/window，在 manifest freeze 后首次运行 proposed | 冻结后的序列外推 |
| External-held-out | 最终 method/threshold hash 前只允许 metadata、许可、reference provenance 和 checksum 资格审计；首次解码/检查图像内容或运行 frontend 必须在方法冻结后，且有独立参考轨迹 | 跨域主张 |

具备 external-held-out 数据时使用“cross-domain evaluation”；其余方案使用“multi-sequence evaluation”。

### 5.2 历史排除审计

在任何新 proposed run 前生成：

```text
papers/ieee_sensors_journal_experiments/history_exclusion_manifest.csv
```

至少包含：

```text
dataset_family, sequence, start, end, prior_artifact_count,
prior_learned_seen, prior_vins_seen, prior_parameter_use,
allowed_role, evidence_paths, decision_reason
```

审计范围包括 `logs/`、`papers/`、`正反例窗口整理/`、runner 默认窗口和已有 bag 名称。

### 5.3 确认性矩阵最低规模

- 至少 3 个数据域；
- 至少 6 条独立序列；
- 目标 20 个非重叠窗口：10 个 low-texture/degraded，10 个 normal/moderate；
- 每窗同时满足至少 200 个输入图像帧和 reference-rate-aware 时长下限：`duration >= max(20 s, (ceil(30/0.70)-1)/evaluation_rate_hz)`；1 Hz reference 对应至少 42 秒，目标长度 45-60 秒；
- 每条序列最多贡献 4 个窗口，保持 sequence 权重均衡；
- H1 至少覆盖 6 条含 low-texture 窗口的独立 sequence，H4a/H4b 的 normal 集至少覆盖 6 条独立 sequence；两组 sequence 可以重叠；
- low/normal 两个 strata 各覆盖至少 2 个数据域；若保留 cross-domain claim，external-held-out 域应同时贡献至少一个 low 和一个 normal 窗口；
- cross-domain 完整版本包含至少一个 external-held-out 数据域；multi-sequence 版本进入 CONDITIONAL 路线。

### 5.4 与结果无关的窗口选择

窗口 screening 使用 KLT-only 与图像质量。score 公式、窗口长度、percentile 和 tie-break 在 development 数据上制定，并在解码 external 图像内容前 hash；external 候选在 G2 方法和 G3 contract probe 完成后执行 screening。

固定流程：

1. 将每条候选序列切成固定长度、互不重叠窗口；
2. 最终方法锁定后运行冻结的 strong KLT frontend，screening 输出仅包含 KLT/image-quality 指标；
3. score 由 KLT grid coverage、dropout ratio、flat-region ratio 和 image degradation 构成；feature scaling、绝对 `tau_low/tau_normal` 和序列内 percentile 在 development 上冻结；
4. low 窗同时满足 `score>=tau_low` 和序列高 percentile，normal 窗同时满足 `score<=tau_normal` 和序列低 percentile；中间区归入 unclassified pool；
5. 每序列在满足绝对+相对规则的集合中各选 1-2 窗；缺少某一类的 sequence 贡献已有类别；
6. GT 缺失、数据损坏或传感器时间不同步时按预注册替换规则处理，并在 manifest 记录原因；
7. manifest freeze 后按完整清单执行。

G1 生成 `data_eligibility_manifest.csv` 和 `window_selection_protocol.md`，记录用于制定 score 的 B1 candidate source/config hash。B1 hash 更新时，在 development 上同步更新 G1 选窗协议。G3 在 method hash 冻结后应用该规则，生成 `dataset_manifest.csv`、`window_selection_audit.csv` 和 `arm_order.csv`，再封存 `protocol_v1.md`。第一次 held-out proposed run 位于这些文件的 hash 时间之后。

### 5.5 外部数据优先顺序

1. 新下载且此前未进入本项目开发的 FLSea-VI，或其他公开 underwater camera-IMU-reference 数据域；独立 reference、同步和标定合同通过后标记为 external-held-out。
2. 完整 UMA-VI 新序列：确认独立 reference trajectory 后进入 APE 主表；由于 UMA-VI sample 已用于开发，完整 UMA-VI 标记为 sequence-held-out。
3. 新 Tank/UVVID/NTNU sequence：这些数据域已经参与开发，因此标记为 sequence-held-out。

缺少独立 GT 的数据进入 frontend/runtime 补充实验；轨迹精度总体统计使用带独立 reference 的数据。

## 6. G2：方法、环境与比较 arm 冻结

### 6.1 主实验 arm

| ID | Arm | 作用 | 运行范围 |
|---|---|---|---|
| B0 | Native VINS-Fusion frontend | 标准系统参考 | 全部 confirmatory 窗口 |
| B1 | Strong KLT + adaptive CLAHE + same exporter | primary classical baseline | 全部 confirmatory 窗口 |
| B2 | Ungated learned seed + KLT | 验证严格 admission 是否必要 | 全部 confirmatory 窗口 |
| H_confirmatory | Frozen learned seed + KLT + distance/grid heuristic | 现有启发式选择对照 | 全部 confirmatory 窗口 |
| P | Frozen learned seed + KLT + calibrated marginal-support selector | proposed | 全部 confirmatory 窗口 |
| D | Whole-lineage drop from the same P bag | 轨迹级 contribution control | 所有 P 有 accepted lineage 的窗口 |
| C-QG | Matched classical seed + identical QG selector | learned-specific control | 所有 P 有 accepted lineage 的窗口 |
| M | Controlled same-backend modern learned frontend | 现代 learned system reference | 全部 confirmatory 窗口 |

下文 `H` 是 `H_confirmatory` 的简写；历史开发结果使用 `H_legacy`，对应删除控制使用 `D_Hlegacy`。H 与 P 消费同一份 selector-independent master candidate stream，共享 trigger、proposal、KLT probation、survival、motion、F/H correctness gate、KLT base set、concurrent active-lineage cap、total feature cap、exporter 和后端；最终排序/停止策略是两者的唯一方法差异。candidate generation、probation 与 correctness gate 不接受 arm-specific admission/export 反馈；若 canonical 实现不能保持逐帧 candidate-pool hash 一致，P-H 不得表述为 selector-only contrast。C-QG 使用独立 classical candidate pool，并调用与 P 完全相同的 pooled reliability schema、边际支撑矩阵和贪心选择器。

该表定义 promoted profile。BASELINE_ROUTE 使用 `P_legacy=H_confirmatory`、D_legacy、C_legacy 和 M，不再创建独立 H/P 两个 arm。

所有使用 external-feature interface 的 arms（B1/B2/H/P/D/C-QG/M）采用一致的 constant `q=1`，以单独识别 seed/admission/selection 的贡献。B0 保持 native VINS 行为。`q_i^-` 仅在前端选择阶段使用；backend weighting 作为 appendix ablation 单独报告。

### 6.2 可靠性校准的边际几何支撑选择

在时刻 `t`，定义三个 ID 互斥集合：`K_t^0` 是 B1 native KLT base，`L_t` 是此前已准入且仍 active 的 lineage，`E_t` 是从未准入且已通过 survival、motion 与 F/H correctness eligibility 的新候选。master stream 逐帧固定 `K_t^0`、`E_t` 及其时序证据；`L_t` 只是 arm-specific admission state。每个 track 使用归一化图像平面向量：

\[
z_i=\begin{bmatrix}1 & 2u_i/W-1 & 2v_i/H-1\end{bmatrix}^{T}.
\]

令 `Y_{i,t}^{(h)}=1` 表示 track 在未来固结的 `h` 帧 horizon 内持续 KLT-valid 且满足几何正确性合同。校准单位是一个 `track-lineage x decision time` row，同一 lineage 的 rows 不得跨 train/calibration split，split 同时保持 sequence-disjoint。基础模型给出 `p_hat_{i,t}`；在 calibration split 上以 `s=|Y-p_hat|` 得到有限样本 conformal quantile `Q_(1-alpha)`，并定义：

\[
q_{i,t}^- = \operatorname{clip}(\hat p_{i,t}-Q_{1-\alpha},0,1).
\]

`q_i^-` 固定称为 **conservative conformalized reliability score**，不称为条件生存概率的置信下界，selector 也不使用 backend `min_quality` floor。`K_t^0`、`L_t` 与 `E_t` 共用同一 pooled base model 和 calibration protocol；source 只用于 KLT/learned/classical 分组 coverage/ECE 审计，不进入模型、blend 或 conformal bucket。selector-specific feature schema 只使用 age、NCC、forward-backward error、multi-frame survival 和不晚于 `t-1` 的 residual history statistics；明确排除现有 `base_quality`、detector confidence、source one-hot 和当前帧 residual。`h`、`alpha`、split、模型和 subgroup calibration gates 在 development 上冻结，任一预注册 source/geometry stratum 校准失败则进入 `REVISE`。

当前帧几何残差与时序可靠性分离。selector 调用前，只用排序固定的 `K_t^0` correspondences 估计有效模型集 `M_t`，固定 RANSAC seed、输入顺序和 F/H arbitration，加入候选后不重估模型。对每个模型用其冻结 correctness threshold `T_m` 归一化：

\[
e_{i,t}=\min_{m\in\mathcal M_t}\operatorname{clip}\left(\frac{r_{m,t}(i)}{T_m},0,e_{\max}\right),
\qquad
w_{i,t}=q_{i,t}^-\exp(-e_{i,t}/\tau_e).
\]

`e_i` 与 `tau_e` 均无量纲；历史 residual 只通过 `<=t-1` 的统计进入 `q_i^-`，当前 `e_i` 只在指数项中出现一次。`M_t` 无有效模型时默认不准入新 lineage 并记录 `NO_VALID_BASE_MODEL`；任何其他 fallback 必须在 G2 作为新方法版本预注册。

\[
A_t^0=\lambda_A I+\sum_{i\in K_t^0\cup L_t}w_i z_i z_i^T,\qquad
A_t(S)=A_t^0+\sum_{j\in S}w_j z_j z_j^T.
\]

其中 `S` 是本次 admission 已选的新候选集，`lambda_A>0` 是固定正则项。已准入 lineage 只在 `L_t` 中计算一次，不再出现于 `E_t` 或 `S`。候选 `c` 相对当前 base、active lineage 与已选候选的边际效用为：

\[
\Delta(c\mid S)=\log\det A_t(S\cup\{c\})-\log\det A_t(S)
=\log\left(1+w_c z_c^T A_t(S)^{-1}z_c\right).
\]

`B_active` 是 concurrent accepted-lineage cap，本次新准入槽位为 `b_t=max(0,B_active-|L_t|)`；total exported-feature cap 另行冻结并对 H/P 相同。P 以稳定 tie-break 的贪心策略依次选择最大 `Delta` 的 candidate，直到达到 `b_t`、候选耗尽或剩余 gain 低于冻结 `min_gain`。accepted ID 不重排、不被新候选驱逐、不得重复准入；仅按 H/P 共用的 carrier termination contract 在 LK failure、出界或预注册的持续正确性终止条件下离开 `L_t`。

在固定决策事件和固定权重下，上述 log-determinant 目标对 PSD rank-one increments 是单调次模的，cardinality-constrained greedy 因而有标准 `1-1/e` 近似保证；这不将该 3x3 代理量提升为 FIM 或 6DoF observability。实现使用 float64 Cholesky/linear solve、rank-one update 和 `log1p`，不显式求逆。论文术语固定为 **marginal geometric-support gain** 与 **quality-weighted view-space conditioning**。

H 使用现有 distance/grid ranking，在完全相同的 master candidate stream、correctness gates、`B_active` 和 total feature cap 下运行。由于 P 的 `min_gain` 可以提前停止，confirmatory H/P 实际 exported observation dose 不强制相等，必须作为结果报告；development 另以 QG 实际新准入数 `n_t` 构造 per-event admission-count-matched 排序消融，用于单独识别 ranking 价值。

selector 参数为 `lambda_A>0`、`tau_e>0`、`B_active`、total feature cap 和 `min_gain>=0`；`tau_e` 属于 selector，不属于 conformal calibrator，也与选窗的 `tau_low/tau_normal` 无关。这些值在 inner-development 上联合确定，6 窗 route audit 启动后不再调参；F/H arbitration 与 `T_m` 属于上游 candidate contract。`method_lock.json` 记录 pooled model/calibration、selector config 和 golden-vector hash；每帧 chain hash 覆盖规范排序后的 `K^0/L/E` IDs、`z/q/e`、image shape、model-fit hash/seed、active slots、ordered decisions/gains/reasons 及对应 config/model hash，浮点按冻结 IEEE bytes 或 17-digit serialization 序列化。

### 6.3 现代 learned baseline

范围修正（2026-08-11）：论文的 **外部现代 learned baseline** 必须来自已经正式发表的论文及作者官方完整实现，不能用项目自行拼装的 `SuperPoint+LightGlue`、`XFeat+LK` 或 paper-style carrier 替代。科学优先级冻结为 SuperVINS 1.0（IEEE Sensors Journal 2025，mono+IMU、VINS-Fusion系）、Rover-SLAM（IEEE TIM 2025，mono-inertial）和 AirSLAM（IEEE T-RO 2025，VI-SLAM）。只有通过 stock-artifact/runtime 预检的方法才进入实验；运行时只允许 topic、标定、输入布局、launch/config 和输出格式转换，网络、匹配/跟踪、feature budget 和后端不得为本项目改写。若官方 artifact 缺失、包含阻断性源码缺陷或运行栈不可部署，则如实列为不可执行文献系统，不得用本地重实现填补该行。

原 `M` 类 same-backend 本地实现保留为 **controlled internal ablation**，不再占用已发表论文基线的名称或主表行。外部官方系统由于 feature budget、后端和运行栈并非完全相同，应在 whole-system 表中与 B1/P 并列，报告实际 feature count、runtime、初始化/失败率和严格公共支撑 APE/RPE；不得把这种比较写成只改变前端的一变量消融。纯视觉官方系统另用 camera-only/Sim(3) 表，禁止与 metric VIO SE(3) 结果混排。完整选择与排除依据见 `papers/2026-08-11--published-learned-slam-baseline-selection.md`。

### 6.4 Matched classical seed 规则

classical proposer 的 GFTT/FAST 唯一 identity、参数和 adapter 在 G2/P03 冻结，并在 P03B 冻结 pooled calibrator 之前生成 calibration-only classical tracks；P04 不得重新选择 detector。该 proposer 在与 learned trigger 相同的帧产生独立 classical candidate stream，随后经过完全相同的 KLT propagation、survival、motion、F/H correctness eligibility、reliability schema、QG marginal-support selection 和 export gate。

由于 lifetime/export dose 只能在 frontend track 结束后获得，C-QG 定位为 **trajectory-outcome-blind offline matched-dose attribution control**，不称为随机化或无条件 causal control。匹配在完整 frontend track log 生成后、读取任何 VINS trajectory metric 之前完成；online/runtime 比较由 B1 与 M 承担。C-QG 先在独立 classical pool 上完整执行冻结 QG selector，matching 只能对已准入 classical lineages 配对或子采样，不得提升、重排或挽回被 QG 拒绝的候选。

对每条 accepted learned lineage，classical control 需尽量匹配：

- birth/trigger frame；
- activation frame；
- grid cell 或最近空间区域；
- lifetime 和实际 exported observations；
- backend q、marginal gain 和 measurement budget。

匹配规则在 development 上冻结，至少满足：

- trigger frame 完全相同，activation frame 差 <=1 帧；
- 同 grid cell，或归一化图像距离 <=0.10 diagonal；
- `abs(lifetime_C-lifetime_P) <= max(2 frames, 0.10*lifetime_P)`，且 `abs(obs_C-obs_P) <= max(2 observations, 0.10*obs_P)`；
- 每窗 C-QG/P 总 exported dose 和 peak feature budget 差 <=5%；
- 连续 matching covariates 使用 development candidate pool 冻结的 scale 参数，absolute standardized mean difference <=0.10；
- unmatched learned lineage <=20%，且其 observations 不超过 learned exported dose 的 10%。

所有 learned lineage 均进入 balance 分母，未匹配项保留为 unmatched。每个 confirmatory 窗只有在 P-active、C-QG deterministic、全部 hard balance gates 达标且 P-C-QG common support 通过时才记为 `H2_ELIGIBLE`；其余保留在完整 activity/balance 分母中并标记不可判定原因。caliper 采用 development 阶段冻结值。

legacy profile 的 C_legacy 不计算 `q_lower` 或 marginal gain；它与 P_legacy 共享 trigger、KLT carrier、correctness gates、冻结 heuristic admission、maximum caps、exporter 和 backend `q=1`，匹配 birth、activation、grid/position、lifetime、observations、budget 与冻结 heuristic score。其 hard balance、determinism、common-support 和 `H2_ELIGIBLE` 规则与 promoted profile 同构。

### 6.5 公平性锁定

公平性分成四层，每层对应明确的比较目标：

1. **受控归因 arms（B1/B2/H/P/D/C-QG）**：共享 raw image/IMU/GT、时间范围、preprocessing、KLT carrier、feature cap、initialization、VINS config、`multiple_thread`、playback、CPU affinity、ROS scheduling、constant backend q、evaluator 和 common-support。H/P 的 selector-independent master stream、correctness gates、`B_active`、total feature cap 和 KLT base 完全一致；C-QG 使用独立 classical pool，只共享 calibrator/selector/export function。proposal/admission/drop/control/selector 是对应 pair 的目标变量。
2. **M controlled modern baseline**：共享 raw input、窗口、标定、图像尺度、feature budget、VINS config、constant q、硬件、失败和 common-mask evaluator；modern feature carrier 是目标变量。
3. **B0 native VINS system reference**：共享 raw input、窗口、标定、VINS backend config、硬件、执行和评测合同；同时报告其 native frontend、preprocessing 和内部 feature budget。
4. **官方 end-to-end baseline**：共享 raw input、兼容窗口、标定、硬件、失败和评测合同；同时报告自身 backend、preprocessing、budget 和线程配置，并采用独立表格呈现。

B0 保持原生 quality 行为；B1/B2/H/P/D/C-QG/M 使用 constant q。

legacy profile 将第 1 层映射为 B1/B2/P_legacy/D_legacy/C_legacy，P_legacy/C_legacy 共用冻结 heuristic admission；其余公平性层保持一致。

### 6.6 冻结产物

```text
papers/ieee_sensors_journal_experiments/protocol_v1.md
papers/ieee_sensors_journal_experiments/protocol_v1_legacy.md  # BASELINE_ROUTE only
papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md
papers/ieee_sensors_journal_experiments/window_selection_protocol.md
papers/ieee_sensors_journal_experiments/dataset_manifest.csv
papers/ieee_sensors_journal_experiments/window_selection_audit.csv
papers/ieee_sensors_journal_experiments/method_lock.json
papers/ieee_sensors_journal_experiments/reliability_calibration_protocol.md
papers/ieee_sensors_journal_experiments/selector_config.yaml
papers/ieee_sensors_journal_experiments/selector_decision.md
papers/ieee_sensors_journal_experiments/environment_manifest.txt
papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml
papers/ieee_sensors_journal_experiments/arm_order.csv
papers/ieee_sensors_journal_experiments/arm_applicability.csv
papers/ieee_sensors_journal_experiments/run_registry.csv
```

`method_lock.json` 至少记录前端源码、config、runner、evaluator、VINS source tree、模型权重、reliability calibration、selector config 和 calibration 文件的 SHA-256。第一次 held-out proposed export 后，方法更新对应新的 protocol version，各版本结果分别汇总。

### 6.7 G2A：边际支撑选择器 shadow 与晋级

G2A 在 development 数据上判断新的 selector 是否形成与 H 有可观测差异的选择行为。它记录 H 与 QG 的 shadow 排序，保持现有 export bag、VINS 结果和 confirmatory 数据身份。

固定使用 6 个已经登记的 development 窗口：A10 `2400-2800`、A09 `4000-4400` 两个强正例，A10 `400-800`、A08 `7200-7600` 两个已知反例，H07 `1660-1720` 与 Tank `short_test 0-15 s / 300 frames` 两个正常纹理窗口。窗口、候选池和上游 gates 在首轮 shadow 前写入 `selector_shadow_manifest.csv`。

G2A 的实现与判定如下：

1. 新增纯函数 `uw_frontend/geometry/marginal_support.py`，输入 `K_t^0`、`L_t`、`E_t`、image shape、base-model residuals 与 frozen config，输出 selected IDs、`q_lower`、normalized residual、marginal gain、rank、rejection reason 和 deterministic hash；
2. 在 `causal_lineage_shadow_node.py` 接入 shadow mode，记录五个完整 ranking：R 是以固定 seed `20260730` 在网格内作 stable pseudorandom 排序的无质量对照；H 是冻结 distance/grid heuristic；Q 按 `(-q_lower, canonical_id)` 排序且不使用几何增益；G 对 `K_t^0 union L_t union E_t` 全部令 `q_lower=1` 后使用 residual-weighted marginal gain；QG 使用完整权重；
3. 完成合成测试：冗余候选获得更低 gain、新区域候选获得更高 gain、低可靠性权重下降、分辨率缩放保持排序、stable tie-break 产生相同 hash；
4. 对 6 个窗口进行 export-only shadow，生成逐 candidate 和逐 frame 的 R/H/Q/G/QG rank、selected/rejected reason、actual admission count、exported-observation dose、gain、H-QG overlap，并分别报告 calibration、selection kernel、combined 的 invoked-frame P50/P95 及 all-frame amortized latency；
5. 以完整 QG policy 在每个共同 decision event 的实际新准入数 `n_t=|S_QG,t|` 为参考，R/H/Q/G 分别从各自完整 ranking 取前 `n_t` 个，构造 **per-event admission-count-matched** development bags；这不强制后续 lifetime/exported observations 相等。每窗 R/Q/G 总计各 1 次 diagnostic replay，H/QG 总计各 3 次，不是 `1+3`；
6. 输出 `shadow_rank_comparison.csv`、`selector_development_results.csv`、`selector_synthetic_test_report.md`、`selector_runtime_probe.csv` 和 `selector_decision.md`。

rank percentile 归一化到 `[0,1]`，`0` 表示最高优先级。在 `n_t>0` 的共同 decision events 上定义 admission-count-matched overlap `o_t=|S_H,t intersect S_QG,t|/n_t`，以 event median 为 `o`；`n_t=0` 只进入 zero-action 分母，不进入 overlap median。对每个已知正/反例窗，取 H policy 原本会准入的 lineage ID，在其首个 eligibility event 记录 H 与 QG 排名分位；`m=median(r_negative)-median(r_positive)`，`Delta_m=m_QG-m_H`。正例 selected-dose retention 是“正例中同时被 QG 准入的 H-lineage 实际 exported observations / 全部 H-lineage exported observations”；反例 rank increment 是反例 H-lineage 的 `median(r_QG-r_H)`。

QG 的单因素门槛在 admission-count-matched bags 上对 `X in {Q,G}` 分别计算：4 个 low/boundary development 窗口的 median APE 至少改善 2%，或 APE degradation 不超过 2% 且 learned observations/visual-factor cost 至少降低 20%；同时至少 3/4 个窗口的 APE degradation 不超过 2%。完整 H/QG policy 另要求两个 normal 窗口中 QG 相对 H 的 APE degradation 不超过 5%。

- `PROMOTE`：合成合同和 calibration audit 通过；QG 同时通过对 Q、G 的单因素门槛；正例 selected-dose retention >=90%；negative rank percentile 相对 H 增加 >=0.10；并满足 `o<0.90` 或 `Delta_m>=0.10`。
- `BASELINE_ROUTE`：合成合同和 calibration audit 均通过，且 `o>=0.90`、negative rank percentile 增量 `<0.10`。该分支生成 `protocol_v1_legacy_candidate.md`：`P_legacy=H_confirmatory`，主矩阵为 B0/B1/B2/P_legacy/D_legacy/C_legacy/M 共 7 arms、最多 420 replays；HU/P-H、QG 主创新和 C2 selector claim 从 confirmatory protocol 移入 development Discussion。P03B 跳过，P04 以 legacy admission 构造 C_legacy，P05 仍完成 M integration，后续 P06-P11 使用 legacy profile。
- `REVISE`：其余组合，包括合成/calibration 合同未通过、QG 单因素门槛未通过但排序已显著改变、正例 retention 不足或反例优先级升高。该状态调整 selector/calibration 后创建新的 G2A candidate version。

### 6.8 G2B：正式迁移与方法锁

`PROMOTE` 后，将 selector 迁移到唯一 canonical hybrid/export 路径。P03B 冻结 `lambda_A`、`tau_e`、`B_active`、total feature cap、`min_gain`、pooled `temporal_reliability_calibrator` 的 `h/alpha/split/model` hash、selector config 和 stable tie-break。只有当 KLT base、learned-seeded KLT 与已冻结 classical proposer 的 calibration rows 均存在时才能冻结 pooled model；三类 track 共享同一 selector-specific feature schema 和 calibration model。主实验在 frontend 内计算 `q_i^-`，export 前统一写入 backend constant `q=1`。

迁移验收包括：H/P selector-independent master stream hash 逐帧一致；selector API 接受 source-neutral temporal track evidence，P04 再完成冻结 classical proposer 的 C-QG matched-dose 全路径验证；accepted lineage 按冻结 termination contract 持续；冻结模型仍满足 G2A `PROMOTE` 条件；selector-invoked frames 的 calibration+selection combined P95 不超过 `1 ms/frame`。对 `d=3`，报告建矩阵 `O((|K^0|+|L|)d^2)`、greedy `O(b_t|E|d^2)` 与内存 `O(|E|d+d^2)` 的实测对应项。通过后生成新的 `method_lock_candidate.json` 和 `protocol_v1_candidate.md`，再完成 P04/P05 control 与 baseline integration，全部通过后进入 G3。

## 7. G3：小规模 contract probe

仅使用 development 数据，选择：

- 一个已知 active positive；
- 一个已知 active negative；
- 一个 normal zero-action；
- 一个 normal nonzero-action：在 development inventory 中仅用冻结 image/KLT stratum 与 `P* accepted_lineage_count>0` 选出 degradation score 最低的窗，以 dataset/sequence/start/end registry key 写入 probe manifest 后才运行 probe metric；若无符合项，记 `NO_ELIGIBLE_NORMAL_NONZERO_ACTION`，只可用冻结 boundary-active case 做 integration smoke，不得充当 normal no-harm 证据；
- 一个来自 development/auxiliary domain 的跨格式 integration smoke window。

external-held-out 域在 P06/G3 最终方法封存前完成许可、文件完整性、reference provenance、标定/同步元数据和 checksum 审计。方法封存后按冻结规则运行 KLT-only screening；第一次 learned/P/VINS evaluation 位于 G4。

每个窗口先以 `RUN_VINS=0` 完成 export-only probe，随后核验：

- topic、channel、feature ID 和时间戳完整；
- B0 native contract，promoted profile 的 B1/B2/H/P/D/C-QG/M，以及 legacy profile 的 B1/B2/P_legacy/D_legacy/C_legacy/M，均符合各自冻结合同；
- promoted profile 中 H/P 的 selector-independent master stream 等价，P/C-QG 共用 marginal-support function 但 candidate pool 独立；legacy profile 中 P_legacy/C_legacy 共用 legacy admission function 但 candidate pool 独立；
- master candidate-pool hash、`q_lower/e/gain`、selected/rejected reason 和 frame-chain hash 可逐帧回溯；
- D 覆盖完整 learned-born lineage，包括后续 KLT observations；
- selected profile 的 classical control 完成 dose/lifetime/activation 与 selector-score balance；
- zero-action P 与 B1 bag 在 feature stream 上 byte-identical 或逐点等价；
- ROS/VINS 进程状态清晰；
- 每个 run 使用唯一目录。

G3 先在 development/auxiliary data 上检查合同，并沿用冻结 threshold。合同通过并冻结 method hash 后，对 eligible confirmatory sequences 应用预注册 KLT-only screening，生成最终 dataset/window manifest 和 arm order。每个窗口的 D/C-QG（legacy 为 D_legacy/C_legacy）在此时仅预注册为 `CONDITIONAL_ON_PROPOSED_ACTIVE` 的 3-replay slots，applicability rule 固定为 `accepted_lineage_count>0`；不在看到 confirmatory proposed export 前猜测 `APPLICABLE/NOT_APPLICABLE`。方法更新时回到 G2 创建新版本；对应数据身份同步写入 history manifest。

## 8. G4：主实验矩阵

### 8.1 重复与执行顺序

以下统一记 `P*` 为 selected profile 的 proposed arm：promoted 时 `P*=P`，legacy 时 `P*=P_legacy`；`D*` 和 `C*` 分别映射到 D/C-QG 或 D_legacy/C_legacy。`H` 和 `selection-active` 仅适用于 promoted profile。

- frontend export 若确定性，应每个 arm 导出一次并做 hash；
- 每个冻结 feature bag 串行 replay VINS 3 次，用于估计 backend replay stability；
- promoted profile 的每个窗口必须登记 B0/B1/B2/H_confirmatory/P/M，legacy profile 必须登记 B0/B1/B2/P_legacy/M；两种 profile 的 `D*/C*` 条件槽位在 G3 已预分配；
- `P*` export 完成后、读取任何 VINS trajectory metric 前，按冻结 rule 生成 append-only `arm_applicability.csv`：active 窗的 `D*/C*` 解析为 `APPLICABLE` 并各执行 3 次 replay，zero-action 窗解析为 `NOT_APPLICABLE`；该解析不修改 `arm_order.csv` 的 counterbalancing hash；
- replay 用于稳定性汇总，sequence 是主统计单位；
- `D*` 从同一 `P*` bag 派生；`C*` 不从 `P*` measurements 派生，而是在 `P*` identity/dose 冻结后从独立 frozen classical candidate log 构造并匹配。该 dependency order 只用于 bag 构造；所有可用冻结 bags 的 **VINS replay order** 使用预生成 counterbalancing；
- VINS/roscore 实例采用串行执行；
- crash、empty trajectory、solver failure 和 timeout 均作为结果保留；
- 因基础设施故障需要重跑时，保留原 run 并记录 replacement reason；基础设施 replacement 不占用预注册的 3 个 algorithmic replay slots；
- replay reducer 固定为两层：每个 `window x arm` 至少 2/3 个 algorithmic replays 可评估时，数值指标对可评估 repeats 取 median；少于 2/3 时记 `WINDOW_ARM_HARD_FAILURE`。`any_repeat_hard_failure` 另行保留，`window_arm_solver_risk` 按 3 次中 any-of-3 保守归并。

promoted profile 的预计核心规模：

```text
20 windows x up to 8 arms x 3 backend replays = up to 480 VINS replays
```

这里的 8 arms 包括 B0/B1/B2/H_confirmatory/P/D/C-QG/M。P 的 accepted lineage count 为零时，D/C-QG 解析为 `NOT_APPLICABLE`，因此实际 algorithmic replay 数通常低于上限；窗口仍进入 no-harm 分母。legacy profile 为 7 arms、最多 420 algorithmic replays。这两个上限不包括有证据的 infrastructure replacements 和可选 official SuperVINS subset。

### 8.2 Confirmatory activity adequacy

窗口按冻结 manifest 保持不变；learned-specific 与 lineage contrasts 使用以下有效样本量：

- `active` 在读取 VINS trajectory metric 前，由冻结 `P*` bag 中 `accepted_lineage_count>0` 定义并写入 `arm_applicability.csv` 和 registry；
- promoted profile 的 `selection-active` 由同一 frozen master stream 下 H/P 的 selected lineage ID set 不同定义。HU 的主 estimand 始终使用全部 10 个预注册 low windows 及其完整 failure denominator；`>=6/10` selection-active、`>=3` sequences 和 `>=2` domains 只是方法对比的 adequacy gate，不用于事后筛掉 zero-difference 窗口；
- `P*` 应在至少 6/10 个 low-texture 窗口产生 accepted lineage，且覆盖至少 3 条 sequence 和 2 个数据域；
- `H2_ELIGIBLE` 逐窗定义为 `P*`-active + `C*` balance PASS + deterministic PASS + P*-C* common support PASS；`H3_ELIGIBLE` 逐窗定义为 `P*`-active + exact whole-lineage-drop audit PASS + P*-D* common support PASS。H2/H3 各自至少需要 6/10 low windows、`>=3` sequences 和 `>=2` domains 达到对应 eligibility，不以单纯 P-active 替代 control-specific 资格；
- H4a 始终在全部 10 个预注册 normal windows 及全部 normal sequences 上独立判定；insufficient support、proposed-only failure 或无可评估 pair 的窗口不得从 `9/10` 分母删除，也不记为 no-harm success。当至少 3/10 normal windows、覆盖至少 2 sequences 为 `P*`-active 时额外判定 H4b；否则 H4b=`INCONCLUSIVE_ACTIVITY`，不影响 H4a 独立判定；
- P/H/C-QG 或 P_legacy/C_legacy 通过 stable sort/tie-break 和 deterministic settings 得到各 arm 内重复一致的 export/selection hash；promoted H/P hash 允许因 selected IDs 不同而不同，并单独报告 overlap。P 的 frame-chain hash 按第 6.2 节合同生成。`C*` deterministic check 未达标时 H2 标记 `INCONCLUSIVE`。

### 8.3 Development ablation 子矩阵

在 G2A 的 4 个低纹理/边界窗口与 2 个正常窗口上，先运行 selector ablation：

| Ablation | 问题 |
|---|---|
| R | 冻结 seed 的 grid-balanced pseudorandom ranking 是否缺少定向选择价值 |
| H | 当前 distance/grid heuristic 的基准行为 |
| Q | 仅按校准可靠性 `q_i^-` 排序 |
| G | 对 base、active lineage 和 candidates 全部令 `q_i^-=1`，仅按当前 normalized residual 加权的 marginal geometric-support gain 排序 |
| QG / P | 完整 reliability-calibrated marginal-support selector |
| C-QG | classical proposal 在同一 QG selector 下的选择结果 |

R/H/Q/G/QG 共享完全相同的 learned eligible candidate pool、KLT base set、`n_t` admission-count schedule、correctness gates、exporter 和 evaluator；Q 不使用 `min_gain`，R/H/Q/G 均只从完整 ranking 取前 `n_t`。C-QG 使用独立 classical candidate pool，共享 pooled calibrator、correctness schema、QG selector、最大预算、exporter 和 evaluator，并按第 6.4 节执行 matched-dose balance；它是 learned-specific attribution control，不进入 R/H/Q/G/QG 的单因素 synergy 消融。development report 同时给出 QG 对 Q、G 的量化轨迹/观测成本 Pareto 和 H07/Tank normal no-harm。

在 selector 晋级后，补充运行系统 ablation：

| Ablation | 问题 |
|---|---|
| P without learned proposal | 完整系统相对纯 KLT 的差异 |
| P without multi-frame survival | 多帧确认是否必要 |
| P without motion/geometry eligibility | 正确性门对困难窗口的作用 |
| P with 0.5x/1x/2x budget | 默认 budget 是否位于稳定区间 |
| Periodic learned trigger with matched trigger count | quality trigger 是否优于固定频率 |

消融作为 development evidence，使用相同 evaluator 和 machine-table pipeline。

## 9. 指标合同

### 9.1 Primary metric

- contrast-specific common-support SE(3)-aligned translational APE RMSE；
- 每个 `window x contrast x arm` 按第 8.1 节 reducer 对至少 2/3 个可评估 replay 取中位数，再在 sequence 内等权聚合；sequence 是主推断单位。

### 9.2 Secondary trajectory metrics

- common-support 1 s translational RPE RMSE；
- APE/RPE median 和 max；
- full-window output coverage；
- first output delay、last output drop、max gap；
- initialization success；
- tracking-lost proxy；
- linear solver failures、failure mentions、restart/reset；
- common-support duration 和 matched pose count。

### 9.3 Frontend metrics

- KLT/classical track count、grid coverage、track age、dropout；
- learned candidates、confirmed、accepted lineages、exported observations；
- trigger/admission/rejection reason histogram；
- `q_lower`、overall/source/geometry-stratum conformal coverage 与 base-model ECE、normalized F/H residual、marginal gain、selector rank 和 selected/rejected reason；
- H/P selected-set overlap、master candidate-pool hash、frame-chain/selection hash、selection-active rate；
- motion ratio、homography/epipolar residual；
- matched classical control balance；
- zero-action exact fallback；
- per-frame and amortized runtime。

### 9.4 运行时指标

固定硬件、模型、图像尺度和线程数，报告：

- image preprocessing；
- KLT tracking；
- learned inference/matching；
- eligibility、reliability calibration 和 marginal-support selection；
- export；
- frontend total；
- VINS backend；
- learned observations、visual factor count、visual-factor/backend processing time；
- calibration/kernel/combined selector overhead、end-to-end throughput、P50/P95 latency、GPU/CPU memory、queue drops。

在线运行时主表包含 B1/H/P/M（legacy 为 B1/P_legacy/M）；C-QG/C_legacy 的 offline track construction 和 matching cost 单列，不进入 online throughput 门。运行属性按结果分级：amortized end-to-end throughput 达到数据输入频率且 sustained queue drop=0 时记 `PROFILED_REAL_TIME`并使用 `real-time`；其余依实际记 `PROFILED_SELECTIVE` 或 `PROFILED_OFFLINE`。H5 是必须完成的 runtime characterization，不把低吞吐本身作为拒稿门；但只有 `PROFILED_REAL_TIME` 允许 real-time claim。

### 9.5 运行状态与失败定义

以下定义在 `protocol_v1.md` 固定，所有阈值相对 window start 计算：

- `valid pose`：timestamp 严格递增、数值有限、位于预注册 window 内；
- `initialization failure`：开始 10 秒内没有 valid pose；
- `output segment`：相邻 valid poses 的 gap <=1.0 秒；`full-window coverage` 是各 segment 时长之和除以 window duration；
- `replay hard failure`：process crash/non-zero exit、timeout、空/非有限/非单调 trajectory、initialization failure 或 full-window coverage <50% 中任一成立；
- `window-arm hard failure`：排除有证据的 infrastructure replacements 后，3 个预注册 algorithmic replays 中少于 2 个可评估；完整保留 `0/3`、`1/3`、`2/3`、`3/3` 可评估数和 `any_repeat_hard_failure`；
- `contrast insufficient support`：第 4.2 节 common-mask 的 pose/span/coverage 门槛未满足，状态进入该 contrast 的预注册分母；
- `solver-risk`：冻结的 VINS log signature 中出现 linear solver failure、reset/restart 或数值异常；signature 列表从 backend 源码/历史日志在 development 上冻结，`window_arm_solver_risk` 按所有 3 次 algorithmic replays 的 any-of-3 记一次 binary event；
- `queue drop`：输入消息数与实际处理数不一致；`sustained queue drop` 定义为窗口 drop rate >1%，或可观测 queue backlog 连续增长 >=5 秒；
- `infrastructure failure`：ROS master 冲突、文件/磁盘/权限/硬件中断等有外部证据的运行故障；原 run 保留，并按 replacement 规则建立替代 run。

主分析的失败编码：所有预注册窗口都进入分母；`P*`-only window-arm hard failure 且 B1 成功时记 proposed automatic loss；B1-only hard failure 且 `P*` 成功时记 proposed failure-win；双边 hard failure 记 failure-tie；共同支持不足记 `INCONCLUSIVE_PAIR`。数值 APE effect 在双方可评估的 pairs 上计算，并配套报告全分母 failure table。H1 的可评估规模为至少 8/10 low-texture windows 且覆盖 >=6 sequences；H4a 的 `9/10` 和 sequence 成功率分母始终是全部预注册 normal windows/sequences，不由可评估子集缩小。

## 10. 统计分析

### 10.1 统计单位

- primary independent unit：独立 sequence；
- replay 用于稳定性汇总；
- frame、observation 和 feature track 用于前端描述性统计；
- 每个 window 计算 `r_w=log(APE_(P*)/APE_comparator)`，再在 sequence 内取等权 median 得到 `r_s`；总体 improvement 定义为 `100*(1-exp(median_s(r_s)))`，每条 sequence 权重相同；
- 95% CI 使用固定 seed `20260730` 的 10,000 次 percentile hierarchical bootstrap：先有放回抽 sequence，再在被抽中的 sequence 内抽 window；小样本显著性使用 sequence effects 的 exact two-sided sign test；domain 作为分层描述；
- window-level ratio、win count 和完整窗口图作为描述性证据，主检验 `n` 为 sequence 数。

### 10.2 Primary contrasts

promoted profile 预注册：

1. low-texture：P vs B1；
2. all-low intent-to-evaluate selection contrast：P vs H；
3. H3-eligible low-texture：P vs D；
4. H2-eligible low-texture：P vs C-QG；
5. normal texture：P vs B1 的预注册 operational no-harm。

legacy profile 将上述映射为 `P_legacy-B1`、`P_legacy-D_legacy`、`P_legacy-C_legacy`、`P_legacy-B0`、`P_legacy-M` 和 normal `P_legacy-B1`；P-H/HU=`NOT_APPLICABLE`。

H1 是唯一 primary confirmatory superiority contrast。HU 是预注册的关键方法 contrast，H2/H3 是 conditional mechanistic contrasts。promoted profile 的 Holm family 固定为 `{HU,H2,H3}`，legacy 为 `{H2,H3}`，family-wise `alpha=0.05`；adjusted p 与 CI 作支持性统计报告，PASS 由预注册 practical-effect 和 adequacy/safety gates 决定。adjusted p 未通过时不得写“statistically significant”。报告 sequence-equal paired relative improvement、median、IQR、预注册 bootstrap 95% CI、window/sequence win count 和 sequence-level paired rank-biserial effect。

HU 的 APE estimand 使用全部预注册 low windows。成本路径使用完全相同的 all-low window set：先在每条 sequence 内分别求和 `cost_P` 与 `cost_H`，再计算 `1-cost_P/cost_H`，最后对 sequence 等权取 median。`cost_H=cost_P=0` 记为 neutral 且不能单独满足成本成功路径；`cost_H=0,cost_P>0` 记为成本恶化。learned observations 与 visual-factor processing cost 分别计算，不事后选择更好的分母。

### 10.3 预注册成功标准

| Hypothesis | 最低实际意义门槛 | 统计/安全门槛 |
|---|---|---|
| H1 low-texture effectiveness | sequence-equal `P*` vs B1 median APE improvement >=5% | >=8/10 windows 和 >=6 sequences 可评估；sequence-level 95% CI lower bound >0 或 exact test `p<0.05`；proposed-only window-arm hard failure=0 |
| HU selector value (promoted only) | all-low sequence-equal P vs H median APE improvement >=3%，或 APE degradation <=2% 且预注册的 learned-observation 或 visual-factor cost reduction >=30% | >=6/10 low windows selection-active，覆盖 >=3 sequences/2 domains；master candidate stream、maximum caps、correctness gate 和 backend q 相同；combined calibration+selection P95 <=1 ms/invoked frame；within-arm frame-chain hash 一致 |
| H2 learned specificity | H2-eligible 集上 sequence-equal `P*` vs matched `C*` median APE improvement >=3% | >=6/10 H2-eligible low windows、>=3 sequences/2 domains；全部 hard balance/determinism gates 满足；方向在多数独立 sequence 一致 |
| H3 accepted-seed contribution | H3-eligible 集上 sequence-equal `P*` vs whole-lineage-drop `D*` median APE improvement >=3% | >=6/10 H3-eligible low windows、>=3 sequences/2 domains；exact whole-lineage deletion 审计通过；方向在多数独立 sequence 一致；完整报告 D*-vs-B1 stream gap 和 budget |
| H4a overall normal no-harm | 全部预注册分母中至少 9/10 normal windows 可评估且 APE degradation <=5%；至少 80% normal sequences（最少 5 条）的 `r_s<=log(1.05)` | 无可评估 pair 的窗/序列不记 success；proposed-only window-arm hard failure=0；coverage sequence-median 损失 <=2 percentage points；solver-risk event rate 不增加 |
| H4b active-normal no-harm | 至少 3 个 `P*`-active normal windows，覆盖 >=2 sequences；全部 active windows 可评估且 APE degradation <=5% | active subset proposed-only window-arm hard failure=0；coverage loss 每窗 <=2 percentage points；solver-risk 增量=0；activity 不足时记 `INCONCLUSIVE_ACTIVITY` |
| H5 runtime characterization | 冻结硬件上完成 online 与 offline-control profiling | 给出 `PROFILED_REAL_TIME/PROFILED_SELECTIVE/PROFILED_OFFLINE`、P50/P95、实际 throughput、queue drop 和硬件；仅 `PROFILED_REAL_TIME` 允许 real-time claim |

development selector ablation 同时验证 QG 相对 Q、G 的一致优势与成本 Pareto。HU、H1-H4 和 H5 profiling completeness 用于 READY、CONDITIONAL 与 REVISE 判定。方法更新进入新 protocol version，原 confirmatory 结果按既定版本归档。

## 11. 结果与产物组织

### 11.1 单一分析 bundle

```text
papers/ieee_sensors_journal_experiments/
  protocol_v1.md                         # promoted only
  protocol_v1_legacy.md                  # BASELINE_ROUTE only
  evaluator_protocol_v1.md
  history_exclusion_manifest.csv
  data_eligibility_manifest.csv
  window_selection_protocol.md
  dataset_manifest.csv
  window_selection_audit.csv
  method_lock.json
  reliability_calibration_protocol.md    # promoted only
  selector_config.yaml                    # promoted only
  environment_manifest.txt
  failure_taxonomy_v1.yaml
  arm_order.csv
  arm_applicability.csv
  run_registry.csv
  execution_ledger.jsonl
  candidate_pool_log.csv
  selector_decisions.csv
  reliability_calibration.csv             # promoted only
  shadow_rank_comparison.csv
  selector_development_results.csv
  selector_shadow_manifest.csv
  selector_runtime_probe.csv
  development_control_balance.csv
  selector_ablation.csv
  selector_pareto.csv
  results_long.csv
  contrast_results_long.csv
  case_summary.csv
  sequence_summary.csv
  matched_control_balance.csv
  runtime_long.csv
  runtime_summary.csv
  resource_summary.csv
  selector_runtime.csv
  failure_table.csv
  failure_sensitivity.csv
  hypothesis_decisions.csv
  statistics.json
  statistics_report.md
  failures_and_replacements.md
  claim_evidence_matrix.md
  figures/
  tables/
```

promoted 的 `reliability_calibration.csv` 由 P03B 生成；legacy 将该文件及 `reliability_calibration_protocol.md/selector_config.yaml` 标为 `NOT_APPLICABLE`，但保留 P03A provisional calibration audit 作 development 路线证据。`selector_decisions.csv` 由 P09 从冻结的 per-run decision logs 汇总，`development_control_balance.csv` 由 P04 生成，`matched_control_balance.csv` 由 P09 在 confirmatory 分母上生成；`selector_runtime_probe.csv` 属于 P03A，`selector_runtime.csv` 属于 P08。所有裸文件名默认位于上述 bundle root。`results_long.csv` 保存每个 run 的 full-support 和原始评测；`contrast_results_long.csv` 保存每个预注册 contrast 的 common mask 与 paired metrics。所有表格和数字从这两张长表、`case_summary.csv`、`sequence_summary.csv`、`failure_table.csv`、`runtime_summary.csv` 自动生成；Markdown 表格作为渲染结果。

### 11.2 每个 run 的最低产物

- exact command 和 environment；
- raw/feature/GT/config/model/source hash；
- frontend metrics、candidate-pool log、selector decision log 和 lineage decision log；
- reliability model/config hash、`q_lower`、marginal gain、selection hash 和 selected/rejected reason；
- VINS log 和 trajectory；
- legacy/full-support/common-support evaluation；
- init、coverage、solver/failure summary；
- completion status 和 anomaly/replacement reason。

### 11.3 论文主表和主图

| Artifact | 内容 |
|---|---|
| Table I | datasets、split、window count、duration、reference、texture strata |
| Table II | confirmatory common-support APE/RPE、coverage、init、failure |
| Table III | promoted：P-H selector contrast、Q/G/QG development ablation、exact drop、C-QG attribution；legacy：P_legacy-D_legacy/C_legacy confirmatory，QG/P-H 仅作 development |
| Table IV | frontend/end-to-end runtime 与资源 |
| Figure 1 | selective learned-seed sensing pipeline |
| Figure 2 | per-window `P*`/B1 APE ratio，显示全部窗口和 5% no-harm line |
| Figure 3 | promoted 的 H/Q/G/QG 边际支撑选择与 candidate funnel；legacy 标为 development-only |
| Figure 4 | APE-观测数/visual-factor cost Pareto；promoted 突出 P-H，legacy 突出 P_legacy-D_legacy/C_legacy |
| Figure 5 | promoted 显示同一帧 B1/H/P；legacy 显示 B1/P_legacy/C_legacy 的选择与轨迹局部图 |

## 12. 复现与治理规则

- 为本项目建立独立 Git repository 或 canonical release snapshot；
- 记录 Python/ROS/CUDA/PyTorch/OpenCV/evo 版本和 GPU/CPU；
- 保存模型权重及 hash，形成固定 release asset；
- dataset manifest 记录原始文件 hash、许可和 reference provenance；
- 每个 run 使用唯一目录，negative result 完整归档；
- 每个派生 bag 生成独立 audit stats；
- 并发污染、异常回放和 replacement 统一进入 append-only ledger；
- 提交前从 release snapshot 完成至少一个窗口的 clean-room reproduction。

## 13. IEEE Sensors Journal 投稿前验收清单

### 完整投稿版本

- [ ] G0 evaluator 修正和旧证据重评通过；
- [ ] G2A selector shadow 的 `PROMOTE` 决策、合成测试与 6 窗排序审计完成；
- [ ] G2B pooled calibration、canonical migration、H/P contract 与 selector hash 完成；
- [ ] history exclusion、dataset manifest 和 protocol freeze 完成；
- [ ] 至少 3 域、20 windows，且 low/normal 各覆盖至少 6 sequences 的 confirmatory 矩阵完成；
- [ ] 至少一个 external-held-out 域有独立 reference；
- [ ] B0/B1/B2/H/P/D/C-QG/M 合同和分层公平性审计完成；
- [ ] 至少一个现代 learned VINS baseline 完成；
- [ ] matched classical C-QG control 完成；
- [ ] `q_lower` calibration、H/P master-stream equality、frame-chain hash 和 `<=1 ms/invoked frame` combined calibration+selection overhead 审计完成；
- [ ] P-H selector contrast 与 Q/G/QG development Pareto 完成；
- [ ] normal no-harm 包含足够长窗口，并有至少 3 个跨 2 sequences 的 P-active 非零动作案例；activity 规模较小时报告 zero-action fallback；
- [ ] common-support APE/RPE、coverage、init、failure 和 H5 runtime characterization 完整；
- [ ] 主推断以 sequence 等权，window 只作序列内重复/完整展示，并包含全部预注册窗口；
- [ ] 单一 analysis bundle 能重新生成所有表图；
- [ ] 独立 repo/snapshot、environment 和 clean-room reproduction 完成。

具备真正 external-held-out 域，且 HU/H1/H2/H3/H4a/H4b、H5 profiling 与复现合同通过时形成 cross-domain 完整版本；其余根据数据身份和 H2/H4b activity 形成 multi-sequence 条件版本。

### Legacy system profile

- [ ] G2A=`BASELINE_ROUTE`，`protocol_v1_legacy_candidate.md` 记录 H-QG shadow 与路线证据；
- [ ] `P_legacy=H_confirmatory`，D_legacy/C_legacy/M 和 7-arm/420-replay 上限写入 method lock、registry 与 arm order；
- [ ] H1/H2/H3/H4a、modern baseline、normal no-harm、H5 profiling 与 clean-room reproduction 完成；H4b 达标或按冻结 activity rule 记 `INCONCLUSIVE_ACTIVITY`；
- [ ] 稿件以 learned-seeded KLT selective system 为主线，QG、P-H 与 HU 作为 development 方法探索呈现。

### 投稿判断

| 状态 | 决策 |
|---|---|
| HU/H1/H2/H3/H4a/H4b 均达到，H5 profiling 完整，外部域成立 | READY：按 IEEE Sensors Journal Regular Paper 投稿 |
| HU/H1/H2/H3/H4a/H4b 均达到，H5 profiling 完整，采用 multi-sequence 数据身份 | CONDITIONAL：以 multi-sequence system paper 表述投稿 |
| HU/H1/H3 成立，H2 为 INCONCLUSIVE | CONDITIONAL：聚焦 reliability-calibrated selective measurement system，H2 作为后续机制验证 |
| G2A=BASELINE_ROUTE，legacy profile 的 H1/H2/H3/H4a 达到且 H5 profiling 完整，H4b 达标或为 `INCONCLUSIVE_ACTIVITY` | CONDITIONAL：按 selective learned-seeded KLT system paper 表述投稿 |
| H1/H3 仍处于 development 证据层级 | REVISE：先完成冻结 confirmatory 矩阵 |
| H4a 处于 INCONCLUSIVE | REVISE：补齐 overall normal no-harm 证据 |
| H4a 成立，H4b activity 规模较小 | CONDITIONAL：报告 zero-action fallback 与 overall normal 结果 |
| H5 profiling 完整但 throughput 低于输入频率 | 不改变方法效果决策；禁止 real-time claim，改用 `selective` 或 `offline-capable` |
| G0 机器判据为 HISTORICAL_SIGNAL_REDIRECT | REVISE：转向方法复核并保留完整诊断资产 |

## 14. 实现与脚本入口

优先复用并审计以下入口：

- `scripts/run_xfeat_seedchain_arbitrated_eval.sh`
- `scripts/run_learned_seedchain_eval.sh`
- `uw_frontend/geometry/marginal_support.py`  # P03A 计划新增
- `uw_frontend/quality/conformal_calibrator.py`
- `uw_frontend/ros/xfeat_seed_sidecar_node.py`
- `uw_frontend/ros/causal_lineage_shadow_node.py`
- `uw_frontend/tracking/hybrid_tracker.py`
- `uw_frontend/ros/export_vins_features.py`
- `scripts/filter_feature_bag_by_channel.py`
- `scripts/run_aqualoc_archaeo_vins_eval.sh`
- `scripts/run_aqualoc_real_vins_eval.sh`
- `scripts/run_ntnu_vins_eval.sh`
- `scripts/run_uvvid_orientkaj_vins_eval.sh`
- `scripts/run_tank_vins_eval.sh`
- `scripts/run_afrl_cave_vins_eval.sh`
- `scripts/run_uma_vi_vins_eval.sh`
- `scripts/summarize_run_evidence.py`
- `scripts/evaluate_vins_sim_ape.py`
- `scripts/evaluate_vins_tum.py`

正式执行以脚本当前 `--help`、usage 和源码为准；本文档定义科学合同，runner 审计负责参数映射。

## 15. 建议执行顺序

1. G0 evaluator 修正与 development 重评；
2. 历史排除、reference/许可/同步资格审计，并在 development 上冻结 window-selection 规则；
3. 在 external screening 前冻结 B0/B1/B2/H 的上游方法、classical proposer identity/calibration adapter 和 environment candidate hash；
4. 在 3 天 G2A shadow 中比较 H/R/Q/G/QG，形成 `PROMOTE/BASELINE_ROUTE/REVISE` 路线决策；
5. `PROMOTE` 后进入 G2B，迁移并冻结 canonical P、pooled calibration 和 selector config；两条路线都必须完成 P04 selected-profile classical control 和 P05 M baseline，再进入 G3/P06；`REVISE` 迭代新的 G2A candidate；
6. development export-only contract probe，通过后封存最终 method/config/source/environment hash；
7. 用冻结 KLT-only 规则筛选 eligible sequences，生成并封存 dataset manifest 和 arm order；
8. confirmatory 主矩阵；
9. runtime、selector ablation 和 Pareto 汇总；
10. 统计、图表、claim audit、clean-room reproduction 与投稿 READY/CONDITIONAL/REVISE 判定。

方法更新时创建新的 protocol version，并将已查看数据登记为 development；新版本使用新的 confirmatory data。

## 16. 最短可信工期与优先级

### 16.1 核心投稿实验包

为尽快形成 IEEE Sensors Journal 完整投稿版本，核心实验包括：

1. 修正 evaluator，关闭 GT 复用和 common-mask 漏洞，并按机器判据重评旧强正例；
2. 冻结后的 held-out 数据矩阵，包含独立 reference、低纹理与正常纹理；
3. B1/B2/H/P/D/C-QG 受控比较，以及覆盖全矩阵的 controlled modern learned baseline M；
4. G2A shadow、reliability calibration、P-H selector contrast 与 Q/G/QG development ablation；
5. initialization、coverage、failure/solver-risk、APE/RPE 和完整窗口结果；
6. 固定硬件上的 runtime/resource 测量；
7. sequence-equal 主统计、window-level 完整展示和 clean-room reproduction。

### 16.2 后续扩展

- MSCKF、ORB-SLAM3 跨后端扩展；
- 连续风险后验与后端质量权重优化；
- raw `q_i` 后端 weighting 优化；
- 新网络训练和大规模 matcher 搜索；
- 额外阈值敏感性 sweep。

### 16.3 现实排期

| 周期 | 主任务 | 可并行项 | 出口条件 |
|---|---|---|---|
| 第 1 周 | G0 evaluator、历史重评、external metadata/reference 核验、G2A shadow | history exclusion、checksum、合成测试和环境盘点 | G0 technical PASS、selector route 与数据资格可用 |
| 第 2-3 周 | canonical P 迁移、reliability calibration、C-QG、M baseline | development contract probes、runner 审计 | method hash 冻结，再完成 KLT-only manifest freeze |
| 第 4 周 | 20-window confirmatory export/replay | 已完成 run 的评测与 registry 审计 | G4 矩阵无缺项 |
| 第 5 周 | runtime、统计、图表、clean-room reproduction | claim-evidence audit | G5/G6 投稿决策 |

G2A 的最小路线确认约 3 天；selector 正式迁移与 development 证据约增加 10-14 个工作日。完整路线约 5 周，适用于 external-held-out 数据已就绪且 VINS 回放稳定的情况。
