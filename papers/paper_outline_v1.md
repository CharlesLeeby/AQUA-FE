# Paper Outline (academic-paper skill · Phase 2 / structure_architect)

Generated: 2026-06-17 · Mode: outline-only
Structure pattern: **Pattern 1 (IMRaD) — Conference/Letter variant**

---

## Paper Configuration Record (confirmed defaults)

| 字段 | 值 |
|---|---|
| Paper type | Methods/Systems (robotics) |
| Target venue | IEEE RA-L (8-page IEEE two-column; trim path to IROS 6-page) |
| Citation format | IEEE |
| Output format | LaTeX (.tex + .bib) |
| Language | English main text + bilingual abstract (EN + zh) |
| Length budget | ~6,500 words main text + 4 figures + 6 tables |
| Thesis | Calibration + risk-control machinery makes heterogeneous learned features **safe** to use in an underwater VIO frontend (C1/C2/C3); **not** an accuracy-SOTA claim |
| Working title | *Trustworthy Learned-Feature Sidecars for Underwater VIO: Distribution-Free Confidence and Risk-Controlled Backend Export* |

**GLOBAL CLAIM GUARDS (apply to every section — IRON RULES):**
1. No "learned features improve trajectory accuracy in general." Small AFRL-FR gains (2–7%) only, repeat-pending.
2. No "DL rescues the system from failure." No clean rescue case; closed-loop results contradictory/config-dependent.
3. A06 = FRONTEND METRICS ONLY (deterministic; feature-bag jaccard=1.0). Never A06 VINS APE.
4. C1 coverage claimed **at 95% nominal only** (5/5 held-out near-nominal). Not 80/90% cross-domain; not "Mondrian uniformly > global."
5. Every VINS APE = ≥3-repeat median + min/max; only variance-stable windows (H07, AFRL-FL/FR) enter APE evidence.
6. Prior-work boundaries: conformalized VO = pose-level; MAC-VO = NLL/stereo/no-guarantee; LEAP-VO/CoTracker = no underwater eval; CRC = never used for SLAM measurement gating.

---

## Section-by-Section Outline + Evidence Map

### §I. Introduction — ~700 words (1 col)
**Purpose:** establish the underwater degradation problem, the learned-feature temptation-and-danger, the gap, and the three contributions.
- I-A Underwater degradation breaks KLT photometric consistency + GFTT corner detectability.
- I-B Learned matchers tempting but **harmful if naively injected** (hook: raw-q backend APE 0.588 vs constq 0.103).
- I-C Gap: no distribution-free, safety-guaranteed way to use heterogeneous learned features in an underwater VIO frontend.
- I-D Contributions C1/C2/C3 + honest empirical characterization.
**Evidence:** safety-ladder hook (Table III); CLAUDE.md framing.
**Figures:** Fig.1 pipeline teaser referenced here.
**Claim guard:** Frame contribution as *safety/calibration*, not accuracy. State the non-claims explicitly in I-D (one sentence: "we do not claim learned features improve accuracy or rescue failures; we make them safe to use").

### §II. Related Work — ~600 words (1 col)
- II-A Underwater VO/VIO (AQUALOC/Ferrera; 2025 system-level GeVI-SLAM/UniVIO/DVL) — none calibrate frontend confidence.
- II-B Learned matchers (XFeat, SP+LG, LoFTR) as sidecars.
- II-C VO uncertainty: MAC-VO (NLL, stereo, no guarantee), conformalized VO (pose-level), Statistical-UQ-VIO, inertial-guided correspondence uncertainty → C1 boundary.
- II-D Conformal prediction / risk control (Bates/Angelopoulos; HRI, medical FDR) → C3 boundary.
- II-E Degeneracy/observability (LODESTAR/AdaLIO LiDAR; active-SLAM FIM; Messikommer RL) → C2 boundary.
**Claim guard:** each subsection ends with the explicit "we differ by…" so novelty is positional, not overclaimed.

### §III. System Overview — ~450 words (0.7 col) + **Fig.1**
KLT/GFTT backbone (backend-visible) + classical recovery (relaxed-LK/ORB) + learned sidecar; the "Calibrated Trust Pipeline": feature → C1 σ → C2 posterior-scheduled recovery → C3 risk-gated export → VINS.
**Fig.1:** pipeline block diagram marking the 3 decision points (measurement/frame/decision) and the heuristic each replaces.

### §IV. Method — ~1,900 words (≈3 col)
- **IV-A Quality-Guided Hybrid Frontend** (~350w): geometry-mode structure; hard-mode is C2's transitional baseline.
- **IV-B C1 — Mondrian Conformal Feature Reliability** (~650w): logistic q_i → split+Mondrian conformal → tempered σ injection `q_backend=α+(1−α)q_conf`. **Guard:** present α as *safety injection strength*, not optimum; defer α selection to C3 / sensitivity appendix.
- **IV-C C2 — Information-Aware Continuous Degradation Posterior** (~450w): q-weighted observability proxy → multi-label sigmoid posterior → continuous recovery budget. **Guard:** "FIM-inspired observability proxy"; true 6-DoF FIM = appendix/future.
- **IV-D C3 — Conformal Risk-Controlled Export Gate** (~450w): loss(τ)=max(0,APE_exp−APE_base−ε); Learn-then-Test τ s.t. R̂(τ)≤α; window-level + bootstrap. **Guard:** APE-loss-table admission gate (variance-stable windows only).
**Equations:** conformal quantile ⌈(n+1)(1−α)⌉/n; σ map; CRC risk. 

### §V. Experiments — ~2,000 words (≈3 col)
- **V-A Setup / Protocol / Reproducibility** (~350w): two-claim protocol; datasets (AQUALOC H06/H07/A06, AFRL-FL/FR main; NTNU/Tank/UVVID appendix). **Reproducibility statement (load-bearing):** frontend metrics deterministic (feature-bag jaccard=1.0); single-window VINS APE replay-sensitive → all APE = ≥3-repeat median+min/max + variance gate.
- **V-B C1 Coverage** (~400w) → **Table I** (95% coverage 5/5), **Fig.2** (reliability diagram), **Table II** (ECE/Brier by mode). **Guard:** 95% only; 80/90% AFRL-FR failure = exchangeability discussion, not hidden.
- **V-C Safety Ladder + No-Harm Closed Loop** (~350w) → **Table III** (raw 0.588 → naked-lower 0.30 → tempered 0.086, H07 n=5; AFRL-FL/FR no-harm repeat-stable). Message: calibration is a *necessary condition* for backend safety.
- **V-D Why Learned Features? (config-matched frontend ablation)** (~450w) → **Table IV** (KLT vs classical-only vs +learned; A06 dropout 24.35→22.05→8.16, track age 22→45; AFRL-FR coverage 0.5→1.0). **Pending downstream anchor:** AFRL-FR small-APE repeat OR C2 FIM conditioning — must land ≥1 before submission.
- **V-E C2 Posterior** (~250w) → **Table V** (hard-4-state vs posterior: trigger AUC/precision/jitter/no-harm-false-trigger), **Fig.3** (p_mode time series). [pending C2 shadow-mode]
- **V-F C3 Risk Control** (~250w) → **Table VI** (fixed τ=2 vs CRC-global vs CRC-Mondrian: violation rate / mean APE degradation / exported count), **Fig.4** (R̂(τ) curve); A09 negative blocked, A08 neutral passed. [pending C3 risk table]
- **V-G Negative Results & Honesty** (~150w): LoFTR flooding harmful; raw-q harmful; A06 APE non-reproducible; learned ≠ rescue (closed-loop both-directions, config-dependent); single-dataset-family small-positive limit. Framed as *motivation* for C1/C2/C3.

### §VI. Limitations & Discussion — ~350 words
Single-window VINS APE noise (mitigated by frontend + repeats + variance gate; end-to-end cross-dataset accuracy claims kept conservative); conformal exchangeability approximation + 80/90% failure; learned benefit scoped to degraded-window frontend continuity; true 6-DoF FIM / residual-ratio conformal / TAP underwater eval = future (C4).

### §VII. Conclusion — ~150 words
Restate: not "learned features are good underwater" but "we make risky learned features *safe and guaranteed* to use." 

### Mandatory back-matter (skill IRON RULE)
Data Availability · Ethics Declaration (n/a human subjects; public datasets) · Author Contributions (CRediT) · Conflict of Interest · Funding · **AI-usage disclosure** (run `disclosure` mode at submission for RA-L/IROS).

---

## Figure / Table Master Plan

| ID | Content | Source artifact | Status |
|---|---|---|---|
| Fig.1 | Calibrated Trust Pipeline block diagram | — | draw |
| Fig.2 | Reliability diagram (base vs logistic vs conformal) | `c1_leave_one_dropstable_*/reliability_diagram_bins.csv` | data ready |
| Fig.3 | p_mode time series + dropout/coverage overlay | C2 shadow-mode | pending C2 |
| Fig.4 | R̂(τ) risk curve | C3 fitter | partial |
| Table I | 95% coverage, 5/5 held-out | `c1_paper_ready_95_summary_20260615.md` | ✅ ready |
| Table II | ECE/Brier by geometry-mode | C1 output | ✅ ready |
| Table III | Safety ladder + no-harm closed loop | `c1_paper_facing_closure_table.csv` | ✅ ready |
| Table IV | Why-learned frontend ablation | `component_ablation/a06_*`, `afrl_v31_frontend/*` | ✅ ready (rerun ×2 to certify determinism) |
| Table V | C2 hard vs posterior | C2 eval | pending C2 |
| Table VI | C3 violation rate | C3 fitter | partial |

---

## Word/Page Budget (RA-L 8-page IEEE two-column ≈ 6,500 words)

| Section | Words | Share |
|---|---|---|
| I Intro | 700 | 11% |
| II Related | 600 | 9% |
| III System | 450 | 7% |
| IV Method | 1,900 | 29% |
| V Experiments | 2,000 | 31% |
| VI Limitations | 350 | 5% |
| VII Conclusion | 150 | 2% |
| Abstract+back-matter | 350 | 5% |
**IROS trim path:** cut II to 350w, merge V-E/V-F prose, move ECE/Brier (Table II) + negative-results detail to appendix.

---

## Pre-Submission Gating Items (must close before drafting Experiments)
1. **AFRL-FR small-positive repeat ×3** (FR70-100/80-110/110-140 + FR120-150) — certifies V-D downstream anchor above replay noise.
2. **A06 frontend ablation rerun ×2** — certifies "deterministic frontend gain" wording (Table IV).
3. **C2 shadow-mode outputs** — unlocks Table V / Fig.3.
4. **C3 window-level risk table + bootstrap CI** — unlocks Table VI / Fig.4.

(1 & 2 are half-day each and unlock the V-D "why learned features" result — top priority.)

---

## Next skill steps available
- `full` mode → draft sections (gated: needs 1–4 closed for Experiments; Intro/Related/Method/System draftable now).
- `abstract-only` → bilingual abstract once results frozen.
- `format-convert` → IEEE LaTeX scaffold (.tex + .bib) anytime.
Recommend: draft **Intro + Related + Method + System now** (evidence-independent), hold Experiments until gating items 1–2 land.
