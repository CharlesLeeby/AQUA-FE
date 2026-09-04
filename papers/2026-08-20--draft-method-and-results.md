---
type: draft-prose
date: 2026-08-20
project: AQUA-FE
target_venue: IEEE Sensors Journal
authority:
  - papers/2026-08-20--section-evidence-story-map.md
  - papers/final_claim_evidence.md
status: DRAFT — numbers locked to verified CSV/JSON on 2026-08-20
note: 正文英文(ISJ),中文旁注给作者。所有数值已核(p07/b1_vs_m/cirs_s575_d30)。占位引用用 [CIT:xxx]。
---

# §II Related Work (RU-SLAM 差异化) + §III Method (draft) + §IV Experiments main table (draft)

---

## §II. RELATED WORK — differentiation from RU-SLAM

> 中文旁注:RU-SLAM(Sensors 2024, Harbin Eng. Univ, [CIT:ruslam])是最贴身对手——同一目标域(弱纹理水下 learned SLAM)。必须硬差异化,否则 reviewer 会问"你和 RU-SLAM 差别在哪"。事实已核:UWNet 自监督知识蒸馏(改进水下成像物理模型)训练,**替换** ORB-SLAM3 的特征提取器;local+global 特征分别用于跟踪与回环;评测 EuRoC+AQUALOC+自采 Pool(seq01/02/03)。

The most directly comparable prior work is **RU-SLAM** [CIT:ruslam], which also targets weakly-textured underwater environments with learned features. RU-SLAM trains a dedicated feature generator (UWNet) in a self-supervised manner via knowledge distillation over an improved underwater imaging physical model, and **replaces the ORB-SLAM3 feature extractor** with it; its local and global descriptors feed feature tracking and loop closure respectively. Our approach differs along four axes that are central to our claims:

1. **Carry vs. replace.** RU-SLAM replaces the classical extractor outright, so the learned network is on the critical path of *every* track. We instead keep KLT as the *persistent carrier* and let the learned network propose *seeds only*, admitted through a gate. This is what makes our **provable byte-exact no-harm** property (Sec. IV-A) possible: when the gate is inactive the exported feature stream is bit-identical to the pure-KLT baseline. A full-replacement design has no such classical fallback — if the learned extractor degrades, the entire frontend degrades with it.

2. **New trained network vs. training-free gating + estimator coupling.** RU-SLAM's contribution is a *newly trained network* (UWNet). The contribution of this paper is a **training-free composition and gating** of an off-the-shelf detector over a KLT carrier, plus a per-feature **quality-to-σ coupling into the VIO estimator** (Sec. III-C). We modify *how measurements are weighted*, not only how features are extracted; RU-SLAM leaves the estimator's weighting unchanged.

3. **Feature-based back-end vs. optimization/optical-flow VIO.** RU-SLAM is built on ORB-SLAM3 (feature-descriptor matching); our KLT-carried seeding is native to the optical-flow VINS-Fusion lineage, and our per-feature σ is consumed directly by the tightly-coupled sliding-window estimator.

4. **Claim strength.** RU-SLAM reports high accuracy and robustness on EuRoC, AQUALOC, and a self-collected pool set. We make a deliberately **narrower, provable** pair of claims — byte-exact no-harm plus selective rescue existence proofs — with explicit scope limits (Sec. IV-A, IV-D), and we do *not* claim universal superiority or loop-closure gains.

> ⚠️ 诚实边界:我们**不**在"整体精度全面超过 RU-SLAM"上竞争(没有同后端复现 RU-SLAM,不 claim);差异化卖的是**架构性质(可证 no-harm 回退)+ 贡献类型(免训练门控+估计器耦合)+ 更窄可证 claim**,不是"我们数字更好"。

| 维度 | RU-SLAM [CIT:ruslam] | 本文 |
|---|---|---|
| learned 角色 | UWNet **替换** ORB 提取器,在每条轨迹关键路径 | 仅**提议 births**,KLT 承载,门控准入 |
| 经典回退 | 无(替换式,无 fallback) | **逐字节 no-harm**(门控零动作时 ≡ KLT) |
| 贡献类型 | 训练新网络(自监督蒸馏+水下物理模型) | 免训练组合/门控 + **q→σ 估计器耦合** |
| 估计器权重 | 不改(沿用 ORB-SLAM3) | per-feature `σ_i=σ_base/√(q_i+ε)`,conformal 校准 |
| 后端 | ORB-SLAM3(特征匹配) | VINS-Fusion(光流/优化 VIO) |
| 回环 | 有(global 描述子) | 无(前端/VO 范围,更窄) |
| claim | 高精度+鲁棒(3 数据集) | 可证 no-harm + 选择性救回(带 scope 边界) |

---

## §III. METHOD

### A. Overview

> 中文旁注:开门见山点系统三件套 = learned seed + KLT carrier + gated admission。只写系统真用到的组件。

We adopt a **KLT-carried, learned-seeded frontend with gated admission**. A Kanade–Lucas–Tomasi (KLT) tracker is the *persistent carrier* of all feature tracks; a learned detector (XFeat [CIT:xfeat]) proposes *new seed points only*, and a scheduler gates whether and which recovery layer is invoked per frame. Unlike frontends that replace tracking with per-frame learned matching, the learned network here never owns a track's identity across frames — it only nominates births, which the KLT carrier then propagates. This design is a direct response to a failure mode we characterize in Sec. IV-C: naively promoting per-frame learned correspondences to persistent VINS landmarks is unreliable on underwater sequences.

### B. Confidence-ordered seeding

> 中文旁注:这段=xfeat-confidence-ordering-births 记忆。系统隐式真用(top-N by score),诚实写"排序准入",不写"新增门控"。探针数据 1.25–1.82× 已核。

At each frame the detector emits up to `K` candidate keypoints, each with a native detection confidence `s_i`. Because the number of open slots is bounded by the feature budget minus the currently tracked count, only the top-scoring candidates are admitted as births — the seeding is therefore **implicitly ordered by learned detection confidence**, admitting the highest-confidence candidates first. We verify that this ordering is well-motivated with a ground-truth-free probe: high-confidence seeds survive markedly longer under subsequent KLT tracking than low-confidence ones, with a high/low median-survival ratio of **1.25×–1.82×** across three underwater/low-texture scenes (AQUALOC archaeology, NTNU fjord, NTNU indoor tank). The effect is directional across all three scenes and strengthens in textured/degraded regions while weakening on uniform indoor texture — an honest scene-dependent detail, not a defect.

> ⚠️ 诚实边界:此处只 claim "confidence-ordered admission(系统真用)+ 探针合理性",**不 claim** 新增显式 τ 门控(那是既有 top-N 的重述)。

### C. Per-feature quality-to-sigma coupling

> 中文旁注:q→σ。定位=水下+conformal+KLT-carrier 组合,非首创。必须避让 MAC-VO [CIT:macvo]。

Standard tightly-coupled VIO back-ends such as VINS-Mono [CIT:vinsmono] weight every visual residual equally (unit information matrix), regardless of illumination, feature distinctiveness, or geometry; scale-based weighting in the ORB-SLAM family is the main classical exception. We instead expose a **per-feature visual sigma** `σ_i = σ_base / sqrt(q_i + ε)`, where `q_i` is a *conformally calibrated* lower-bound reliability score. Learned per-keypoint covariance has been explored for stereo VO [CIT:macvo]; our contribution is not a new covariance primitive but its **coupling of a coverage-guaranteed conformal quality score to the residual weight, within an underwater KLT-carried frontend**.

---

## §IV. EXPERIMENTS

> 中文旁注:主表只放强项区。M/M2 负结果不在这,进 §IV-C Motivation。

### A. Provable no-harm under a frozen replay contract (main result)

> 数值已核:p07_noharm_byte_identity.csv,20/20 全 TRUE,10 low+10 normal,4 域。

Our strongest guarantee is a **provable, byte-exact no-harm** property. On a frozen 20-window confirmatory matrix (10 low-texture + 10 normal-texture windows spanning four domains: AFRL, AQUALOC archaeology, AQUALOC harbor, and NTNU), the gated frontend (P) takes **zero action in all 20/20 windows**: its exported feature bag is **byte-identical (identical size and SHA-256) to the pure-KLT baseline (B1)** in every window, with zero accepted learned lineages. This is a stronger statement than "trajectory degradation ≤ 5%": under the same frozen replay contract, P and B1 serialize the *identical* observation stream, so the back-end trajectories are provably equal and no per-window trajectory replay is required to establish equality.

> 诚实边界(必写):19/20 是 history-excluded window(真退化窗都被开发期排除),1/20 是 outcome-blind。因此证明的是"冻结 20 窗上的 exact no-harm + 零动作回退正确性",不是 20 个外部独立样本,也不估计部署 no-harm 率。

**Scope.** The corrected split-role audit shows 19/20 windows are history-excluded within development-exposed sequences and 1/20 is an outcome-blind window. This establishes exact no-harm and correct zero-action fallback *on the frozen matrix*; it is not a claim over 20 independent held-out samples.

### B. Modern learned-baseline initialization robustness (B1 vs. M)

> 数值已核:b1_vs_m_results.csv,B1 20/20 有轨迹(438+ rows),M 20/20 m_trajectory_rows=0 且 init_finish=0。

Under a fixed, matched same-back-end configuration (identical image scale, feature budget, VINS config, constant back-end weighting, and G0 evaluation), the pure-KLT baseline B1 successfully initialized and produced non-empty trajectories in **20/20 windows** (all with valid B1-only G0 APE/RPE). The current fixed modern XFeat baseline M **failed to initialize in 20/20 windows**, producing empty trajectories. Because M yields no trajectory, pairwise common-support APE/RPE and cross-window win/loss are undefined; this is reported as a **failure-mode / scope-limited** result about the initialization robustness of *this fixed XFeat-to-VINS configuration on this matrix*, not a claim over all learned methods. This observation is consistent with the independent finding that learned frontends are viable but not universally superior to classical tracking [CIT:dlvinsfactory].

### C. Motivation: why a KLT carrier and gating (not per-frame learned landmarks)

> 中文旁注:把 M/M2 负结果写成动机。M2 数值已核过(final_claim_evidence):A02 138.6/13.97m, NTNU 492.8/67.4m。

A separated diagnostic arm (M2, persistent-ID repair) isolates the cause of M's initialization failure. Adding cross-frame ID persistence lets VINS initialize and produce G0-valid trajectories on two pre-specified full windows (A02 and NTNU), but at accuracy far worse than B1 — APE/RPE RMSE of **138.59 / 13.97 m** and **492.85 / 67.44 m** respectively. Together, M and M2 show that (i) without persistent IDs the learned frontend fails to initialize, and (ii) with naive persistent IDs the chained mismatches diverge. This is precisely why our design keeps KLT as the identity carrier and admits learned seeds only through gating — the negative results *motivate* the architecture rather than constitute a limitation of it.

### D. Selective rescue (existence proof)

> 数值已核:cirs_s575_d30/common_support_summary.json。KLT 2.2242→full 1.0914 (-50.93%); RPE 0.30470→0.27001 (-11.39%); ape_valid&rpe_valid=true; grid 310/matched 252/span 25.1s/rpe_pairs 242/coverage 0.813.

On CIRS window `s575,d30` — our strongest closed-loop VINS existence proof — the full profile reduces APE RMSE from **2.224 m to 1.091 m (−50.9%)** and RPE RMSE from **0.3047 m to 0.2700 m (−11.4%)** under a G0 common-support audit that is valid on both metrics (252/310 common grid points, 25.1 s common span, 242 RPE pairs, 81.3% coverage). This window is development-only and history-excluded; it demonstrates that specific degraded windows *can* be rescued, but does not estimate a blind-selection success rate, trigger rate, or average improvement.

> 附加 case studies(§附录/补充材料,非主表):A09 6000 (4.70→0.11 m, 但 legacy-support + G0 ape_valid=false,必须紧邻标注);A02 2800 (ORB-v23 backend-specific,不写成 VINS 结果、不写成 4 独立样本)。

---

## 待办(写正文时补)
- [CIT:*] 换真实 bib key(xfeat/macvo/vinsmono/dlvinsfactory + AQUALOC/FLSea GT caveat for §V)
- §III-A 补一张系统框图(carrier/seed/scheduler/admission 数据流)
- §IV 主表做成一张正式 Table:列=window_id/domain/texture/B1 APE/P APE/byte_identical
- §V Evaluation Protocol 单独写(水下伪 GT 挡枪①,引 AQUALOC/FLSea 原文)
