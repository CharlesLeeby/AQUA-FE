---
type: final-claim-evidence
date: 2026-08-08
project: AQUA-FE
status: CONDITIONAL_READY
authority: papers/2026-08-08--codex-STOP-and-redirect.md
---

# Final claim–evidence map

## 结论先行

当前投稿判定为 **CONDITIONAL_READY**。已经成立的主结果是：在冻结的 P07 20 窗矩阵中，P 臂 20/20 均为 `ZERO_ACTION`，且 P 与 B1 的实际 feature bag 在每窗都大小相同、SHA-256 相同，即 **20/20 byte-identical no-harm**。这比“轨迹退化不超过 5%”更强：在相同冻结 replay 合约下，两臂代表同一个后端观测输入，因此继续执行 P-vs-B1 replay 不会产生新的算法信息。

选择性改善目前只由开发期、history-excluded 案例支持。CIRS `s575,d30` 是具有有效 G0 APE/RPE 的强 VINS existence proof；A09 `6000-6200` 是 support 不足的探索性 headline case；A02 `2800-3200` 是 ORB-v23 后端特定案例。它们证明“某些特定退化窗口可以被救回”，但不估计盲选成功率、触发率或总体平均改善。

B1-vs-M 已完成全部 20 窗（10 low + 10 normal）。在相同固定 VINS 后端配置下，B1 20/20 成功初始化并产生非空轨迹，其 B1-only G0 APE/RPE 均有效；当前固定的 modern XFeat baseline M 则 20/20 初始化失败并产生空轨迹。由于 M 没有轨迹，pairwise common-support APE/RPE、跨窗胜负和均值均不可计算；这个 failure-mode 结果说明当前 XFeat-to-VINS 配置在该矩阵上的初始化鲁棒性不足，但不能泛化为所有 learned 方法。

与原 M 完全分离的诊断臂 `M2_XFeatPersistent_v2` 进一步定位了该 failure mode。persistent-ID repair bundle 在两个预指定 full windows（A02 与 NTNU）上都使 VINS 完成初始化并产生 G0-valid 轨迹，但精度远差于 B1：M2 的 APE/RPE RMSE 分别为 `138.588486/13.968817 m` 与 `492.846198/67.439196 m`。这支持“跨帧 ID 持久性不足是原 M 初始化失败的至少一个因果贡献因素”，但不证明 learned accuracy；M2 不替换原 M、不进入原 20 窗结果，也不扩跑 20 窗。

## Claim–evidence 对齐

| Claim | 直接证据 | 状态 | 论文允许的落点 |
| --- | --- | --- | --- |
| 冻结 P07 矩阵上的 exact no-harm | `papers/p07_noharm_byte_identity.csv`：20/20 `byte_identical=TRUE`，20/20 `p_action=ZERO_ACTION`，20/20 accepted lineage count 为 0，20/20 output feature-bag binding 已验证 | **SUPPORTED，主结论** | P 在这些冻结输入上精确回退到 B1；P-vs-B1 无算法差异 |
| 零动作回退实现具有字节级一致性 | 同一 CSV：20/20 `PASS_BYTE_IDENTICAL_TO_B1`；P/B1 feature bag 每行大小与 SHA-256 相同 | **SUPPORTED，机制证据** | “当门控不采取动作时，回退路径保持 B1 observation stream 不变” |
| 存在窗口特定的 selective rescue | `papers/selective_case_studies.md`；其中 CIRS `s575,d30` 的 G0 APE/RPE 均有效 | **SUPPORTED AS EXISTENCE PROOF** | 作为单独 case-study 小节，不进入 confirmatory 分母 |
| A09 展示 `4.70 -> 0.11 m` 救回 | legacy-support fresh replay 有效，但后续 G0 common support 给出 `ape_valid=false`、`rpe_valid=false` | **EXPLORATORY ONLY** | 可作醒目案例，但必须紧邻标注 legacy-support 与 G0 无效 |
| A02 展示另一种后端中的 lineage 救回 | ORB-v23 online APE/RPE `0.066472/0.032750 -> 0.022080/0.018213 m`；4 次为确定性复现 | **BACKEND-SPECIFIC EXISTENCE PROOF** | 只放跨后端机制证据或补充材料；不得写成 VINS 结果或 4 个独立样本 |
| 当前固定 modern XFeat baseline M 相对 B1 的初始化鲁棒性 | `papers/b1_vs_m_results.csv`：B1 20/20 成功且 B1-only G0 APE/RPE 双 valid；M 20/20 初始化失败且轨迹为空 | **SUPPORTED WITH SCOPE LIMIT** | 在该固定同后端配置与 20 窗矩阵中，B1 产生可评估轨迹，而 M 未通过初始化；不计算 pairwise APE/RPE 均值 |
| M2 persistent-ID diagnostic repair | `papers/2026-08-08--xfeat-persistent-v2-repair.md`；A02 与 NTNU 两个预指定 full windows 均初始化且 pairwise G0 APE/RPE 双 valid，但 M2 精度分别为 `138.588486/13.968817 m` 与 `492.846198/67.439196 m`，远差于 B1 | **SUPPORTED AS DIAGNOSTIC ROOT-CAUSE EVIDENCE** | 说明 ID 持久性不足是原 M 初始化失败的至少一个贡献因素；不作 learned accuracy、M2 优越性或 20 窗泛化 claim |
| learned 普遍优于或劣于 KLT、对所有来源均有效或低纹理普遍改善 | 当前证据没有 confirmatory 正例或总体效应估计；M 结果只绑定当前 XFeat profile 与 VINS 配置 | **NOT SUPPORTED** | 删除或明确否定此类表述 |

## 主证据：20/20 byte-identical no-harm

`papers/p07_noharm_byte_identity.csv` 共 20 行，覆盖 10 个 low 窗与 10 个 normal 窗；数据域包括 AFRL、AQUALOC archaeology、AQUALOC harbor 和 NTNU。机器可读汇总如下：

- `byte_identical=TRUE`：20/20；
- `p_accepted_lineage_count=0`：20/20；
- `p_action=ZERO_ACTION`：20/20；
- `p_zero_action_identity_status=PASS_BYTE_IDENTICAL_TO_B1`：20/20；
- D resolution/status 为 `NOT_APPLICABLE` / `PASS_NOT_APPLICABLE`：20/20；
- output manifest 的实际 feature-bag binding 已验证：20/20；
- `trajectory_outcome_read=FALSE`：20/20。

最后一项是有意的结果边界，而不是证据缺口。P 与 B1 的序列化 observation stream 已逐字节相同；在同一冻结 replay 合约下再为两个标签分别跑轨迹，只会重复同一个算法输入，不能检验 P 的新增作用。因此原 240-replay P-vs-B1 队列保留但冻结，不执行，也不再扩建相关治理基础设施。

该结论的作用域必须保持精确。修正后的 split-role 字段显示，20 窗中 19 个是 `HISTORY_EXCLUDED_WINDOW_WITHIN_DEVELOPMENT_EXPOSED_SEQUENCE`，1 个是 `SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW`。因此这里证明的是冻结 20 窗上的 exact no-harm 和零动作回退正确性，不是 20 个外部 held-out 独立样本，也不支持总体部署 no-harm 率。

## 次证据：selective rescue existence proofs

### 首选 VINS 案例：CIRS `s575,d30`

CIRS 是当前最强的 selective-improvement 论文案例。统一 G0 common-support 审计中，KLT 的 APE/RPE 为 `2.224181/0.304697 m`，full profile 为 `1.091415/0.270008 m`；APE 和 RPE 分别降低约 `50.93%` 与 `11.39%`。该比较具有 252/310 个 common grid 点、`25.10 s` common span、242 个 RPE pairs，且 `ape_valid=true`、`rpe_valid=true`。

这个案例仍是 `DEVELOPMENT_ONLY` 且 history-excluded，并记录了各臂 solver-failure mentions。它支持窗口特定的精度救回，不证明 final P 能盲选该窗口，也不证明 learned 提高数值稳定性。主证据路径为：

- `papers/e3_g0_common_support/cirs_s575_d30/common_support_summary.json`
- `papers/e3_g0_common_support/cirs_s575_d30/common_support_metrics.csv`
- `papers/e3_g0_common_support/cirs_s575_d30/common_grid_audit.csv`
- `papers/selective_case_studies.md`

### 辅助案例的强制限定

A09 `6000-6200` 的 legacy-support fresh replay 给出 KLT `4.702022/3.393186 m`、full `0.111514/0.078392 m`，但统一 G0 重算只有 8/10 common grid、`7.0 s` common span 和 7 个 RPE pairs，最终 `ape_valid=false`、`rpe_valid=false`。它只能作为探索性案例，不能作为正式 G0 endpoint。

A02 `2800-3200` 的严格正例来自 ORB-SLAM3 external-lineage bridge，而不是 VINS-Fusion。其 4 次复跑用于确定性复现，不构成 4 个统计独立样本。VINS 主文若篇幅有限，应优先报告 CIRS；A02 放入跨后端机制讨论或补充材料。

## B1-vs-M：完整 20 窗结果

该对照比较 B1（KLT baseline）与 M（当前固定的 modern XFeat baseline）的不同 feature streams，并使用相同固定 VINS 后端配置。最终证据表 `papers/b1_vs_m_results.csv` 包含 20 个唯一窗口、49 个字段、10 个 low 窗和 10 个 normal 窗；其 SHA-256 为 `61ac31343ab7ac0bb278c8a4a4feb98d3d7e2367e8cc207da77d3eeacdee5c3e`。

| 观察项 | B1 | M | 可比较性结论 |
| --- | ---: | ---: | --- |
| runner return/classification | 20/20 `0 / SUCCESS` | 20/20 `1 / INITIALIZATION_FAILURE` | 成功/失败状态可直接报告 |
| initialization finish | 20/20 | 0/20 | M 未进入可评估轨迹阶段 |
| 非空 VIO 轨迹 | 20/20 | 0/20；20/20 为零字节、零行 | M 没有轨迹 endpoint |
| G0 APE/RPE validity | B1-only `ape_valid=true`、`rpe_valid=true` 均为 20/20 | 无可计算轨迹指标 | 只能报告 B1-only G0，不是 pairwise 比较 |
| pairwise validity | — | — | `pair_ape_valid=false`、`pair_rpe_valid=false` 均为 20/20 |

20 个 M 日志均记录 `NOT_ENOUGH_FEATURES_OR_PARALLAX` 与 `IMU_EXCITATION_NOT_ENOUGH`，且 `comparison_status=M_INITIALIZATION_FAILURE`。因此不能把 B1-only APE/RPE 与缺失的 M 指标拼成胜负、差值或均值；`B1_ONLY_NOT_PAIRWISE_COMMON_SUPPORT` 是结果作用域，而不是待补的数值。

这个结果本身具有信息量：在本研究冻结的 feature bags、20 窗矩阵和相同 VINS 初始化配置下，当前 modern XFeat baseline 没有表现出 B1 的初始化鲁棒性。它不证明 XFeat 在其他后端、其他配置或调参后必然失败，也不证明 SP-LG、LoFTR、受门控 learned sidecar 或所有 learned frontend 缺乏价值。

## M2 diagnostic repair：初始化根因证据，而非精度正例

`M2_XFeatPersistent_v2` 是在原 M 之外新增的诊断臂；原 M 的配置、20/20 初始化失败记录和空轨迹均未被改写。M2 使用 persistent-ID repair bundle 修复跨帧 identity contract，并只在两个预指定、跨数据集的 full windows 上进行验证。

| full window | M2 initialization / poses | common support | B1 G0 APE / RPE RMSE (m) | M2 G0 APE / RPE RMSE (m) | 诊断结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| AQUALOC archaeology `A02:0005` | PASS / 393 | 39/45；`ape_valid=true`、`rpe_valid=true` | `0.441820/0.044751` | `138.588486/13.968817` | ID 持久性修复足以使该窗初始化，但轨迹精度不可用 |
| NTNU `fjord_6:0001` | PASS / 430 | 429/451；`ape_valid=true`、`rpe_valid=true` | `0.133959/0.039282` | `492.846198/67.439196` | 跨数据集复现相同边界：能初始化，不等于几何可信 |

直接证据路径为：

- `papers/2026-08-08--xfeat-persistent-v2-repair.md`
- `papers/p07_b1_vs_m2_common_support/aqualoc_archaeology_A02_0005_r2/common_support_summary.json`
- `papers/p07_b1_vs_m2_common_support/ntnu_fjord_6_0001_r1/common_support_summary.json`

这项干预使原本确定性的 no-initialization failure 在两个预指定 full windows 上消失，因此支持跨帧 ID 持久性不足是原 M failure mode 的至少一个因果贡献因素。它同时给出明确的负面精度结果：持久轨迹本身不足以保证 pairwise matches 的几何一致性或可用定位精度。M2 只保留为 diagnostic sensitivity result，不替换 M、不进入 `papers/b1_vs_m_results.csv` 的 20 窗分母、不作为 learned accuracy 正例，也不扩展为 20 窗 endpoint。

## 诚实边界

1. P07 的 20/20 零动作直接证明 exact fallback/no-harm，但没有提供 final P 的正触发样本，因此不能估计 final P 的救回率、precision、recall 或 selective-improvement 频率。
2. P07 的 10 个 low 窗是冻结分层中的 low 标签，不等于 10 个已验证的后端真实退化正例；开发期已知的强退化窗因 history exposure 被排除在 confirmatory 效应估计之外。
3. selective cases 使用开发期 profile，不能反向声称 final P 会在这些窗口采取相同动作或复现相同改善。
4. CIRS 是 G0-valid VINS existence proof；A09 是 G0-invalid exploratory VINS case；A02 是 ORB-v23 backend-specific case。三者不能合并成同一统计样本集。
5. 当前不支持 learned 必需、learned 普遍优于或劣于 KLT、source-agnostic、低纹理普遍改善或外部总体 no-harm 等表述。
6. B1-vs-M 的 20/20 M 初始化失败只适用于当前冻结 XFeat profile、feature bags 和 VINS 配置。M 空轨迹使 pairwise APE/RPE 与跨窗均值在定义上不可计算；B1-only G0 数值不得被重命名为 B1-vs-M 数值优势。
7. M2 是与原 M 分离的 diagnostic repair。两个 full-window G0-valid 负面精度结果只支持 ID 持久性是原 M 初始化失败的至少一个贡献因素；它们不证明 learned accuracy，不把原 M 的空轨迹改写成成功，也不提供 20 窗 M2 总体效应。

## 投稿判定

当前判定：**CONDITIONAL_READY — 核心证据项已闭合，但仍受 confirmatory 与 case-study 边界限制**。

| 投稿条件 | 当前状态 | 判定 |
| --- | --- | --- |
| 20/20 P-vs-B1 byte-identical no-harm | 已完成 | PASS |
| 至少 1 个可信 selective rescue existence proof | CIRS G0 APE/RPE 双有效 | PASS |
| B1-vs-M 有信息量对照 | 完整 20 窗：B1 20/20 成功，M 20/20 初始化失败；不可计算 pairwise APE/RPE | PASS AS FAILURE-MODE FINDING |
| 原 M 初始化 failure mode 是否可诊断 | M2 在两个预指定 full windows 上均恢复初始化并产生 G0-valid 轨迹，但精度远差于 B1 | PASS AS DIAGNOSTIC ROOT-CAUSE EVIDENCE；NOT AN ACCURACY CLAIM |
| 论文采用上述诚实边界 | 本页已给出，仍需同步至正文 | CONDITIONAL PASS |

核心证据条件均已闭合，可按以下定位收敛投稿：**conservative gated frontend with exact no-harm under zero action, development-only selective rescue case studies, a VINS initialization-robustness comparison against a fixed modern XFeat baseline, and a separate persistent-ID diagnostic showing that initialization recovery does not imply learned accuracy**。M2 的诊断闭环不提升 selective-rescue 或 learned-accuracy 证据等级，因此投稿状态保持 `CONDITIONAL_READY`；正文仍必须保留 split-role、case-study、M non-comparability 和 M2 diagnostic-only 边界。

## 可直接复用的论文表述

> Across the frozen 20-window P07 matrix, the proposed arm took zero action and produced feature bags that were byte-identical to the KLT baseline in all 20 cases, establishing exact no-harm for these inputs. Development-only, history-excluded case studies provide existence proofs of selective rescue, but they do not estimate blind-selection success or population-level improvement. Under the same fixed VINS backend configuration, B1 produced non-empty trajectories with valid B1-only G0 APE and RPE in all 20 windows, whereas the fixed modern XFeat baseline failed initialization and produced empty trajectories in all 20. Because M yielded no trajectory, pairwise common-support APE/RPE and cross-window win or mean summaries are undefined; this finding identifies an initialization-robustness limitation of this specific XFeat-to-VINS configuration, not of learned frontends in general. In a separate diagnostic arm, a persistent-ID repair enabled initialization and G0-valid trajectories on two prespecified full windows, implicating insufficient cross-frame ID persistence as one contributor to the original M failure mode. However, M2 remained far less accurate than B1 (`138.588/13.969 m` APE/RPE on A02 and `492.846/67.439 m` on NTNU), so it is not evidence of learned accuracy, does not replace M, and was not expanded to the 20-window endpoint.

## Reviewer-facing 自审

| 维度 | 当前判断 | 尚需处理 |
| --- | --- | --- |
| Contribution | PASS WITH SCOPE | 将贡献写成“exact fallback/no-harm + selective existence proof”，不恢复 P07 原 H1 |
| Writing clarity | PASS | 正文统一 P、B1、M、development-only、history-excluded 和 G0-valid 的定义 |
| Experimental strength | PASS WITH SCOPE | CIRS 提供 G0-valid 强案例；B1-vs-M 完整 20 窗给出一致的初始化 failure-mode 结果；M2 两窗只提供根因诊断和负面精度边界 |
| Evaluation completeness | PASS WITH NONCOMPARABILITY LIMIT | `papers/b1_vs_m_results.csv` 已闭合且原 M 不可比性保持不变；M2 仅作为分离的两窗 G0-valid diagnostic，不进入 20 窗分母 |
| Method soundness | PASS WITH LIMITATION | 零动作路径已字节验证；M2 表明恢复 ID 持久性不足以保证几何精度；正触发的盲选可靠性仍未由 confirmatory 正例建立 |
