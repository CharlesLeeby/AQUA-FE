---
type: experiment-plan
date: 2026-08-03
project: AQUA-FE
target_venue: IEEE Sensors Journal (Regular Paper)
paper_stance: honest incremental system paper — gated persistent-measurement frontend for churny underwater VIO (VINS-primary)
supersedes: papers/2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md (QG-headline version retired)
related:
  - papers/2026-08-02--aqua-fe--qg-selector-and-persistent-anchor-investigation.md
  - memory: qg-selector-supply-bottleneck, positives-not-lowtexture-regime, a06-ape-not-evidence
---

# AQUA-FE 诚实增量论文:补实验计划与验收目标

## 0. 为什么是这个定位(承接本轮全部验证)

本轮系统验证否决了以 QG / learned-necessity 为头条的强创新叙事:QG 选择器跨 regime 不 pay off;既有 A06/Cave proxy 不能作为同 pipeline 的 C-QG 因果证据;正例集中在 churny-but-feature-rich 的 AQUALOC 窗、不泛化真低纹理;单窗 APE 因稀疏 GT 失效。A03 `5000-5900` 的严格 G0 结果给出 classical-positive 反例:同剂量、同 ID/slot 的 retrospective GFTT 控制在 1 s RPE 上低于 learned。随后完成的 NTNU Fjord1 `s83,d30` native-q 扩窗又给出严格 learned-positive 反例:learned RPE median `0.038135 m`,低于 KLT `0.065728 m` 和 retrospective GFTT `0.091582 m`。prior-art 检索显示"learned 用于匹配/重定位"也是红海。

因此论文重定位为**诚实增量系统论文**,贡献 = **系统(退化触发候选 + KLT 多帧 probation + 冻结准入 + native reliability interface + external-feature 导出)+ 严谨多序列/多数据域 VINS 评测 + 诚实刻画(含 learned/classical 双向反例与 count-persistence 脱节)**。**不主打 learned 必需、一般优越或 source-agnostic;当前证据只允许把 learned-seeded admission 保留为待 held-out 验证的方法组件。** 中稿杠杆是 rigor,不是新颖性。

### 0.1 当前执行状态(2026-08-04)

- `P00/P01/G0/P02/G1`: 保留既有 PASS 与冻结哈希,不重写。
- July 30 的 `P03`/QG-headline candidate: 退役为 development/future-work,不得覆盖原失败记录。
- A03 `5000-5900`: **已完成 development attribution**。G0 `rpe_valid=true`,32 common poses/31 RPE pairs; learned median `0.078869 m`, GFTT median `0.020439 m`,GFTT 低 74.1%。该 control 是 retrospective full-interval survival/proximity match,不是 online C-QG。
- A06: 保留为一个有效 learned-positive development event; A08: 只保留 directional diagnostic,严格 G0 support invalid。
- NTNU Fjord1 `s83,d30`: **已完成 development attribution 和质量合同消融**。27-arm 共同支撑为 269 poses/259 RPE pairs; native-q learned median `0.038135 m`,KLT `0.065728 m`,GFTT `0.091582 m`,exact drop `5.113238 m`。XFeat-only q=1 与 native-q 等价;global q=1 learned 为 `10.599716 m`,只能解释为完整 reliability interface/backend interaction。online GFTT 是 zero-action supply result,不冒充 geometry comparison。
- 当前下一执行入口: **冻结 native-q learned method candidate 与哈希,随后执行 P05 modern baseline M 和 P06 KLT/image-only outcome-blind screening**。NTNU `s83` 保持 development-only,不得进入 confirmatory denominator。

### 0.2 July 30 与 August 3 的保留/替代映射

| July 30 contract | August 3 handling |
|---|---|
| P00/P01/P02, G0/G1, history/reference/eligibility | 保留；作为所有后续实验的治理和评测地基 |
| P03A/P03B QG、C2/QG headline | 退役；只保留为未验证 development ablation，不再作为投稿 gate |
| P04 classical control | 保留问题，重写为独立 classical proposer 的 `C_legacy`/C-QG attribution；A03 结果不冒充 online causal control |
| P05 modern learned baseline M | 保留为 P0，要求同后端、同预算、完整矩阵对比，不要求击败 M |
| P06/P07 export/replay governance | 保留；先 method freeze，再 KLT/image-only screening，再 confirmatory replay |
| P09 sequence statistics and no-harm | 保留；主指标 1 s translation RPE，sequence 为独立单位，APE 仅在 G0 support 有效时作为 secondary |

## 1. 可主张 / 不可主张(claim 合同)

| 可以 claim | 必须诚实标注 / 不可 claim |
|---|---|
| 少量持久测量(经种子-probation 准入)在 churny 水下 VIO 改善 RPE/抑制发散 | ❌ 不 claim "learned 特征必需"或"learned 一般优于经典"(A03 反例) |
| 冻结方法在多序列/多数据域、VINS-primary 评测中改善或不伤害后端 | ❌ 在 held-out 完成前不 claim multi-sequence 泛化;不 claim "广义低纹理改善" |
| count/coverage 掩盖持久性崩塌(诊断,跨数据集 robust) | ❌ 不用单窗绝对 APE 当 load-bearing(转 RPE/聚合) |
| `C_legacy` attribution:检验 proposer-source specificity并报告 learned/classical 双向反例 | ❌ 不 claim source-agnostic 或三后端 portability(除非跨数据集补齐;否则 VINS 为主、其余 preliminary) |
| operational no-harm(正常纹理保持 KLT 级) | ⚠️ H07 −9.4% 隐忧须诚实处理 |

## 2. 需要补的实验与验收目标

优先级:**P0=投稿必需(不做则拒),P1=显著抬升概率,P2=加分/防御**。

### E1 [P0] Modern learned baseline M(同后端)
- **目的**:审稿人必问"你只比了 KLT,没比现代 learned 前端"。缺 M = 高拒稿风险。
- **方法**:项目已实现并冻结的 `SuperPoint+LightGlue` 或 `XFeat` 同后端(external-feature 接口,匹配图像尺度/feature budget/VINS config/**同一冻结 native reliability contract**),在**全部** confirmatory 窗运行。global q=1 只作 sensitivity ablation,不得替代主合同。官方 SuperVINS 作增强 system reference(适用子集)。
- **验收目标**:M 在全部窗跑通并对比。**PASS 不要求"击败 M"**,要求(a) 正常纹理**不劣于 M**;(b) churn 窗**与 M 可比或更好**;(c) 若 M 在某些窗更好,**诚实报告**并据此收窄 claim。运行时/资源一并报告(你的 KLT 主干应更省)。

### E2 [P0] 独立 classical proposer attribution(原 C-QG,头条退役)
- **目的**:把 classical-positive 结果作为诚实 ablation,检验 gated persistence 的 backend value 是否依赖 proposer source；不把 control 误写成因果或在线随机化。
- **方法**:`classical_gftt.py` 走与 learned 相同的 trigger、LK、correctness gate、admission、budget 和 export/VINS 接口，仅 classical candidate pool 独立。A03 和 NTNU 的 same-ID/same-slot/same-dose GFTT 均为 retrospective attribution,只能作 development counterexample；NTNU online GFTT 因 frozen gate zero-action,只报告 supply failure。
- **当前结果/验收**:A06 与 NTNU 是 valid-RPE learned-positive,A03 是 valid-RPE classical-positive,A08 仅方向性；三次 replay 只作技术稳定性。该异质结果已写入 claim-evidence audit,足以否决 source-universal 和 learned-necessity,也足以保留 learned candidate 进入 held-out。**不得**从 retrospective control 推导 online proposer 因果优越性。

### E3 [P0] 主指标迁移:RPE + sequence 级聚合
- **目的**:单窗 AQUALOC APE 因稀疏 1Hz GT 失效(G0 已证 A10/A09 APE INVALID,仅 15 共同位姿);必须换主指标。
- **方法**:全窗用 G0 修正评测器重算;**主指标 = 1s 平移 RPE(稀疏 GT 上有效)+ sequence 级 win-rate + exact sign test**;单窗绝对 APE 仅描述性附录。
- **验收目标**:sequence 级 RPE 改善(哪怕温和)带 bootstrap 95% CI,覆盖 **≥6 序列 / ≥3 数据域**;方向在多数独立序列一致。A10/A09 的旧方向只作历史 diagnostic，不能替代新 contract 下的共同支持结果。

### E4 [P1] Held-out 验证(先冻方法,再选窗)
- **目的**:消除"预选正例 = cherry-picking"质疑(现主队列是历史预选 + 单 replay)。
- **方法**:冻结方法/阈值 → 用 **KLT-only + 图像质量**的窗筛规则(不看 learned/VINS 结果)选窗 → proposed **首次**运行。优先 sequence-held-out(完整 NTNU/UVVID/CIRS 新窗),有条件再 external-held-out(FLSea-VI)。
- **验收目标**:held-out 窗方向与 development 一致(RPE 改善不翻符号);≥1 个 held-out 域成立 → 支撑"multi-sequence"表述;external-held-out 成立 → 可用"cross-domain"。

### E5 [P1] 多 replay 后端稳定性
- **目的**:现为单窗单 replay,无后端方差;frozen 20 簇 solver-risk 达 50%。
- **方法**:每 `窗×arm` **3 次** VINS replay,数值指标取中位;报告 replay 方差 + solver-risk 率。
- **验收目标**:效应在 replay 方差内稳健(中位改善 > replay 抖动);solver-risk 如实报告、proposed 不比 baseline 更差。

### E6 [P1] 持久性/churn 诊断(GT-free,论文的"why")
- **目的**:解释 gated persistent measurements 的机制；在 matched proposer attribution 完成前，不把它写成 source-agnostic 因果机制。
- **方法**:复用本轮工具,报告 KLT track-age/churn 分布 vs 锚点寿命,跨 AQUALOC/NTNU/CIRS。
- **验收目标**:定量展示"count 饱和(350)但单 track 中位 1-2 帧"跨数据集一致;锚点(任意来源)提供长基线。已有数据即可(KLT 中位 1 帧 vs 锚点 30-97 帧)。

### E7 [P2] 三后端 generality(诚实收窄)
- **目的**:portability 卖点,但避免第五次塌方。
- **方法**:要么补 MSCKF/ORB **非 AQUALOC** 干净正例(已知 ORB 在 NTNU 低纹理 formal 负、MSCKF 未外推),要么**收窄为"VINS 主、MSCKF/ORB preliminary/discussion"**。
- **验收目标**:若跨数据集三后端一致 → 可写 portability;否则如实标 VINS-primary,其余作机制背景。**不得**用 AQUALOC-only 三后端一致冒充跨范式 portability。

### E8 [P2] 正常纹理 no-harm 补强
- **目的**:C4/H07 −9.4% 隐忧。
- **方法**:多个正常纹理长窗 + 零动作 byte-identical fallback 验证;active-normal 案例。
- **验收目标**:≥9/10 正常窗 APE/RPE 退化 ≤5%;零动作精确回退;solver-risk 不增。

## 3. 投稿就绪判据(overall gate)

| 状态 | 条件 |
|---|---|
| **READY** | E1–E3(P0)完成;E4/E5/E6(P1)完成;≥6 序列/3 域;≥1 held-out 域;claim 与证据一致(诚实框架);rigor 资产齐(多数据集/多后端/诚信审计/C-QG ablation/负结果披露) |
| **CONDITIONAL** | P0 完成但 held-out 仅 sequence-held-out / 三后端仅 VINS → 以 "multi-sequence, VINS-primary system paper" 表述投 |
| **REVISE** | P0 未齐(无 M baseline、方法/质量合同未冻结、或仍以单窗 APE/开发正例为主) |

## 4. 现实排期(建议)

| 周 | 任务 | 出口 |
|---|---|---|
| 1 | E3 evaluator/G0 + E2 NTNU attribution + quality interaction | **已完成**:主指标与 development source-specificity 边界 |
| 2 | 冻结 native-q method + E1 modern baseline M + P06 blind screening | M 对比 + frozen held-out manifest |
| 3 | E4 held-out(冻方法→选窗→首跑)+ E8 no-harm | held-out 方向确认 |
| 4 | E7 收窄决定 + 统计/图表 + claim-evidence audit + 诚实重写 | 投稿判定 |

## 5. 关键提醒(避免重蹈本轮覆辙)

1. **每个实验先看方向回不回正,再决定 claim**——别下注即写。
2. **C-QG 结果无论如何都要写进去**;藏它 = 被审稿人一击。
3. **不主打 learned 一般优越**;learned 保留为冻结系统组件,主打 gated admission + native reliability + rigor + 诚实异质结果。
4. 新代码(本轮):`uw_frontend/matchers/classical_gftt.py`、`uw_frontend/geometry/marginal_support.py`(QG 降级为 ablation 组件)、`shadow_rankings.py`、`scripts/selector_qg_validate.py`、`scripts/cqg_classical_persistence.py`。
