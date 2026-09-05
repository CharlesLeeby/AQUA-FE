# Research Log

This is an append-only record of research questions, hypotheses, method decisions, evidence interpretation, and open questions. It is not a substitute for experiment artifacts or a code changelog.

## Project Status Snapshot — 2026-09-04

### Research Goal

Confirmed fact:

The workspace studies a quality-guided underwater visual VO/VIO frontend. Its durable design goal is to preserve a strong GFTT/KLT temporal backbone on healthy imagery while selectively introducing classical recovery or learned sidecars when underwater degradation, spatial coverage, temporal continuity, or geometry indicates that the backbone is weak. The frontend exports metrics, per-track reliability, and ROS feature bags for evaluation by external SLAM/VIO backends.

The intended paper claims are deliberately split:

1. normal/moderate texture: no harm relative to a strong KLT-based baseline;
2. low-texture, low-coverage, or near-planar scenes: selective recovery or improvement;
3. q_i: a reliability/interface claim unless trajectory benefit is directly demonstrated.

### Evidence Basis for This Snapshot

Confirmed fact:

- Canonical package overview: uw_frontend/README.md.
- Workspace and architecture guidance: CLAUDE.md.
- Default/candidate/rejected profile map: uw_frontend/configs/README_recommended.md.
- Baseline taxonomy: papers/frontend_baseline_protocol.md.
- Frozen August claim boundary: papers/final_claim_evidence.md.
- Latest development repair: papers/frontend_persistence_churn_guard_v3/report.md.
- Latest confirmatory registration: papers/frontend_same_backend_confirmatory_v3/preregistration.md.
- Latest transfer probe: papers/external_klt_dynamic_gate_quick_probe_v1/report.md.

Known inconsistency:

papers/ieee_sensors_journal_experiments/experiment_status.md was last updated on 2026-08-06 and still reports P07 as 3/60 exports complete, while papers/final_claim_evidence.md dated 2026-08-08 reports the final 20-window no-harm and B1-vs-M evidence as complete. The later claim-evidence map is used for completed August conclusions, but the status files should be reconciled before treating either as the sole live dashboard.

### Current Pipeline

Confirmed implementation flow:

1. Input
   - Frontend-only: image directory, image file, tar/tar.gz archive, or rosbag-exported frames through uw_frontend/datasets/image_sequence.py.
   - Closed-loop runs: dataset-specific image/IMU/reference material is converted into or combined with a feature bag by scripts and uw_frontend/ros/export_vins_features.py.
2. Preprocessing
   - none, histogram equalization, CLAHE, or adaptive CLAHE.
3. Quality and geometry assessment
   - underwater image-quality terms, grid coverage, KLT diagnostics, Fundamental/Homography consistency, and geometry-mode classification.
4. Frontend
   - GFTT/KLT is the protected temporal carrier.
   - relaxed LK, ORB, learned sparse matchers (XFeat or SuperPoint+LightGlue), and restricted LoFTR may act as gated recovery/proposal layers.
   - pending learned tracks may require KLT confirmation and geometry/coverage checks before export.
5. Reliability and measurement selection
   - per-feature q_i can be calibrated from future survival and mapped to visual sigma;
   - optional geometry/quality-aware selection creates a bounded backend-facing set.
6. Pose estimation / backend
   - not implemented in this package;
   - exported sensor_msgs/PointCloud feature bags are consumed by an external fixed VINS-Fusion backend for the main same-backend studies;
   - additional comparison/diagnostic scripts exist for ORB-SLAM3, HFNet/SuperVINS, AnyFeature, and MSCKF/DVIO-related workflows.
7. Loop closure
   - not part of uw_frontend;
   - the recent fixed same-backend VINS comparison explicitly used loop_closure: 0, so its results are not loop-closure results.
8. Output
   - frontend_metrics.csv, track/reliability logs, visualizations, feature bags, run receipts/manifests/hashes, VINS trajectories, and APE/RPE/common-support reports.

### Important Modules

| Module | Confirmed role |
| --- | --- |
| uw_frontend/datasets/image_sequence.py | Streams images from supported local inputs and archives. |
| uw_frontend/quality/image_quality.py | Computes underwater image-quality and degradation cues. |
| uw_frontend/tracking/klt_tracker.py | GFTT detection, KLT propagation, forward-backward/NCC filtering, replenishment, and persistent IDs. |
| uw_frontend/tracking/hybrid_tracker.py | KLT backbone plus classical, learned, memory, homography, and semidense recovery/confirmation logic. |
| uw_frontend/matchers/ | Classical GFTT, XFeat, SuperPoint+LightGlue, and LoFTR adapters. |
| uw_frontend/scheduler/hybrid_scheduler.py | Combines image, track, grid, and geometry diagnostics into recovery decisions and geometry modes. |
| uw_frontend/quality/feature_confidence.py | Reliability calibration and q_i-to-sigma mapping. |
| uw_frontend/evaluation/measurement_selection.py | Optional geometry/quality-aware bounded measurement selection with validation/fallback. |
| uw_frontend/evaluation/run_frontend_eval.py | Frontend-only CLI, layered YAML loading, tracker assembly, logging, and visual output. |
| uw_frontend/evaluation/frontend_metrics.py | Per-frame frontend metric schema and track visualizations. |
| uw_frontend/ros/export_vins_features.py | Large ROS/VINS exporter and paper-facing export gates. |
| uw_frontend/geometry/ | Grid, F/H residuals, validation, marginal-support ranking, and candidate-stream logic. |
| scripts/ | 754 top-level files and 1004 total non-cache files for dataset, runner, export, audit, freeze, evaluation, and reporting workflows at inspection time. |
| tests/ | 21 unittest-style test files at inspection time, mainly for export, audit, evaluator, and runner contracts. |
| papers/ieee_sensors_journal_experiments/ | Append-only governance registries, frozen protocols, applicability decisions, and failure records. |

### Current Experimental Setup

Confirmed:

- The datasets symlink resolves to /mnt/data/AQUA-FE_WS/datasets.
- Local dataset namespaces visible at inspection include AQUALOC, AFRL, NTNU, Tank, UVVID, MIMIR-Underwater, FLSea-VI, and official EuRoC material. CIRS support is confirmed by dataset adapters, configurations, and experiment artifacts.
- Direct frontend evaluation requires images. Closed-loop scripts use feature observations and IMU data; reference trajectories may be COLMAP, ReAqROVIO, dataset ground truth, or another explicitly labelled proxy depending on the experiment.
- The usual VINS test backend is /home/ma/SLAM/VINS-Fusion-origin. /home/ma/SLAM/VINS-Fusion_3-15-WS is out of scope and must not be modified.
- Primary trajectory metrics include fixed-scale APE/ATE and translation RPE, with initialization, coverage, lost-tracking/solver diagnostics, pose/span/common-support validity, and runtime where available.
- Primary frontend metrics include feature count, grid coverage, track age/dropout, FB error, NCC, F/H inlier ratios and residuals, learned candidate/confirmed/export counts, source histograms, gate reasons, q_i, and runtime.
- logs/, datasets/, and external_tools/ are external-storage symlinks. experiments/, artifacts/, and papers/ contain additional local run artifacts and evidence.
- There is no root README. uw_frontend/README.md is the canonical package README.
- The workspace was initialized later on 2026-09-04 as a standalone Git repository on branch main with origin https://github.com/CharlesLeeby/AQUA-FE.git. Large datasets, run artifacts, caches, and reproducible per-frame intermediates are excluded by .gitignore.

Unknown / not fully audited:

- A single authoritative table of every dataset's exact sensor suite, calibration, synchronization quality, licensing status, and independent-GT status.
- Which historical run directories are currently reproducible without restaging external mounts or model environments.
- Whether every one of the 754 scripts remains canonical, superseded, or runnable.
- A single reconciled live status after the September development and confirmatory branches.

### Current Baseline

Confirmed fact:

The durable baseline is GFTT/Shi-Tomasi plus KLT optical flow, forward-backward checking, patch NCC, persistent IDs, and usually adaptive CLAHE for paper comparisons. The common KLT configuration caps the frontend at 350 features with 18 px minimum spacing, a 21 px LK window, three pyramid levels, 1 px FB threshold, and 0.65 minimum NCC.

External VINS-Fusion's original frontend, fixed-CLAHE KLT, ORB, pairwise SP+LG, pairwise XFeat, and pairwise LoFTR are separate baseline roles under papers/frontend_baseline_protocol.md. Adaptive-CLAHE KLT is an internal strong control when its adaptive trigger uses project-specific quality logic.

### Current Method

Confirmed fact:

The stable architectural commitment is a protected KLT/GFTT backbone with sparse, confirmed, geometry-gated learned sidecars. LoFTR is restricted to extreme low-texture/near-planar support and is not a general replacement. The repository retains separate safe/no-harm and sparse-contribution profiles.

The latest named development method found during inspection is lineage_early_seed_churn_guard_v3, selected by papers/frontend_same_backend_confirmatory_v3/preregistration.md for a 12-sequence outcome-blind confirmatory continuation. It conditionally preserves a previously tested XFeat replacement path only when the first eligible frame shows a sufficiently high GFTT-birth ratio; otherwise it closes to the KLT mirror.

Important boundary:

uw_frontend/configs/isj_p03_core_method_candidate.yaml explicitly says P03_CANDIDATE_NOT_YET_CANONICAL. Multiple paper generations coexist, so no other experimental YAML should be called the current main method solely because its filename contains paper, final, or proposed.

### Selected Current Evidence

These results have different protocols and are not a global leaderboard.

1. Frozen P07 exact fallback/no-harm
   - papers/final_claim_evidence.md reports 20/20 windows with P action ZERO_ACTION and feature bags byte-identical to B1.
   - This supports exact fallback on those inputs, not learned contribution or population-level no-harm.
2. Development-only CIRS selective rescue
   - KLT APE/RPE: 2.224181 / 0.304697 m.
   - full profile APE/RPE: 1.091415 / 0.270008 m.
   - G0 common support is reported valid, but this is a development-only, history-excluded existence proof.
   - Evidence: papers/e3_g0_common_support/cirs_s575_d30/common_support_summary.json.
3. AQUALOC A06 2210-2460 mirror-inject evidence
   - KLT APE/RPE: 0.268486 / 0.113326 m.
   - mirror KLT plus 10 LoFTR observations: 0.058071 / 0.048803 m.
   - This is strong window-specific evidence, not a cross-dataset average.
   - Run: logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460.
4. AQUALOC H07 1660-1720 normal/no-harm
   - KLT: 0.050207 / 0.113417 m.
   - proposed_safe: 0.050207 / 0.113416 m with zero LoFTR exports.
   - Runs: logs/aqualoc_real_vins/external_klt_every2_may22_mirrorinject_h07_1660_1720_klt and logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_h07_1660_1720_loftr.
5. Fixed modern XFeat baseline M
   - In the frozen 20-window comparison, B1 initialized and produced trajectories in 20/20; M failed initialization and produced empty trajectories in 20/20.
   - Pairwise APE/RPE is therefore undefined. This finding is limited to that XFeat-to-VINS configuration.
   - Evidence: papers/b1_vs_m_results.csv.
6. M2 persistent-ID diagnostic
   - Initialization was recovered on two prespecified windows, but reported errors were 138.588486/13.968817 m and 492.846198/67.439196 m APE/RPE.
   - This supports ID persistence as one contributor to initialization failure while providing negative evidence for usable accuracy.
   - Evidence: papers/2026-08-08--xfeat-persistent-v2-repair.md.
7. Churn-guard v3 development repair
   - On four locked known-outcome windows, the guard closed to byte-identical KLT on the harmful startup, retained byte-identical historical positive inputs on two windows, and stayed KLT-identical on H07.
   - This is n=4 development evidence using proxy references, not confirmatory generalization.
   - Evidence: papers/frontend_persistence_churn_guard_v3/report.md.
8. External-KLT gate transfer
   - The 2026-09-04 quick probe rejected direct transfer: it missed both known positives and activated on the known harmful window.
   - No VINS replay was run because the preregistered frontend stop rule fired.
   - Evidence: papers/external_klt_dynamic_gate_quick_probe_v1/report.md.

### Current Research Questions

Confirmed unresolved questions:

- Can a frozen, outcome-blind learned-sidecar policy produce action-positive gains across multiple independent underwater sequences while preserving KLT runability?
- Can lineage_early_seed_churn_guard_v3 generalize beyond its four known-outcome development windows?
- Which frontend-only geometric observability signals distinguish scale/geometry failure from mere temporal support collapse?
- Does q_i improve closed-loop trajectory metrics, rather than only calibrating frontend reliability and providing a backend interface?
- Can learned-sidecar benefits be separated from dense-KLT rescue and other classical recovery effects?
- Can cross-dataset end-to-end evidence be established with valid common support and correctly labelled references?

Codex inference:

- The next useful trigger family is more likely to combine persistent-cell coverage, parallax/bearing diversity, homography dominance, and candidate grid gain than raw track-count collapse alone. This is motivated by the failed External-KLT gate transfer, but it is not yet validated.
- The large number of overlapping experiment generations creates a provenance/navigation risk. A reconciled status index would reduce the chance of treating an archived profile or stale dashboard as current.

### Potential Failure Cases

- Learned branch produces zero accepted learned-born observations, yielding only a no-action result.
- A small number of replacements removes future long-lived KLT births and sends VINS into a wrong-scale basin.
- Pairwise learned features initialize VINS after ID repair but remain geometrically inconsistent.
- Feature budgets exceed 350, invalidating frontend integrity before backend evaluation.
- Proxy trajectories are mistaken for independent ground truth.
- Fixed-scale and Sim(3) results are conflated.
- Common-support gates fail, making APE/RPE comparisons invalid.
- Dataset or outcome exposure leaks into threshold/window selection.
- External-storage or ROS runtime failures are mistaken for algorithm failures.

### Current Assessment

Confirmed conclusion:

The repository strongly supports protected-KLT fallback behavior and contains several valuable window-specific selective-rescue results. It does not yet support a universal learned-frontend superiority claim, a population-level no-harm theorem, or a general q_i trajectory-gain claim. The August paper status is CONDITIONAL_READY only under the narrow claim boundaries recorded in papers/final_claim_evidence.md.

### Open Questions

- What is the terminal status and formal result of frontend_same_backend_confirmatory_v3?
- Which document should be the single live status authority after the August P07 program?
- Is the intended submission story still the August exact-fallback/selective-case-study framing, or will the September churn-guard confirmatory branch replace or supplement it?
- Which dataset references qualify as independent ground truth versus proxy trajectories?
- Which compact evidence artifacts must remain versioned as future experiments grow, and which reproducible run-scale artifacts should remain external with hashes/manifests only?

### Next Experiment

The latest frozen next experiment already present in the repository is frontend_same_backend_confirmatory_v3: 12 outcome-blind sequence-level windows, three frontend arms (KLT, SP+LG, XFeat churn-guard v3), three serial fixed-backend repeats, runability first, and common-support fixed-scale APE plus 1 s RPE second. Its completion status was not confirmed during this documentation-only task.

Any new geometry-observability gate should be a separate development branch, use export-only probes first, preserve exact KLT output when inactive, and be frozen before evaluation on new windows.

## Reasoning Entry Template

## YYYY-MM-DD — Research Question

### Question

### Motivation

### Current Baseline

### Hypothesis

### Proposed Idea

### Why It Might Work

### Assumptions

### Potential Failure Cases

### Evidence

### Current Assessment

### Open Questions

### Next Experiment

## 2026-09-04 — Can geometry-risk source routing expand positive-window coverage?

### Research Question

Can a frontend-only geometry-risk trigger and source router increase the
outcome-blind action-positive window proportion over XFeat churn-guard v3 while
preserving exact KLT fallback when inactive?

### Hypothesis

Hypothesis / Inference: GFTT birth reserve protects against harmful replacement
but does not observe scale geometry. Persistent-cell support, non-homographic or
rotation-compensated parallax/bearing diversity, and candidate geometry gain may
detect full-count but poorly observable KLT streams. Source-specific routing
between XFeat, SP+LG, and restricted planar LoFTR may expand coverage across
different degradation regimes.

### Motivation

Confirmed fact: the current 12-window confirmatory frontend matrix has XFeat-v3
action in only 1/12 windows (two observations), so its maximum attributable
positive-window rate is 8.3% before backend evaluation. SP+LG is active in 8/12
windows, providing a no-retuning test of whether candidate supply/source is the
immediate bottleneck.

### Related Baseline

Protected KLT/GFTT, XFeat lineage early-seed churn-guard v3, and the frozen
SP+LG early seed-chain arm under the same VINS-Fusion-origin backend contract.

### Proposed Idea

First finish the existing KLT/SP+LG/XFeat-v3 backend matrix. Only if needed,
open a separate development branch for a geometry-risk opportunity detector
and conservative source router. Keep the inactive stream byte-identical to KLT,
use hidden candidate probation, cap action dose, and include a matched
dense/classical candidate control.

### Why It Might Work

The failed External-KLT transfer showed that temporal-count collapse misses the
known positives and selects the known harmful startup. Those positives instead
look like scale/geometry failures in feature-count-saturated KLT streams.
SP+LG's 8/12 frontend action rate shows that the frozen window set contains
substantially more learned candidate supply than XFeat-v3 currently admits.

### Assumptions

- Frontend-only geometry signals correlate with backend scale observability.
- Candidate probation can produce persistent sidecars without evicting critical
  KLT tracks.
- Source-specific routing generalizes across sequences without dataset-specific
  thresholds.

### Potential Failure Cases

- More SP+LG action produces no backend benefit or creates regressions.
- Geometry signals repeat the prior QG failure because real candidates are
  homogeneous or supply-limited.
- A small replacement still pushes VINS into a scheduling-sensitive wrong-scale
  basin.
- Classical candidates equal or beat learned candidates, removing
  learned-specific novelty.
- Thresholds overfit known A06/A09/H07 windows.

### Evidence

Confirmed facts are recorded in:

- `papers/frontend_same_backend_confirmatory_v3/frontend_runability.csv`
- `papers/frontend_persistence_churn_guard_v3/report.md`
- `papers/external_klt_dynamic_gate_quick_probe_v1/report.md`
- `papers/2026-08-02--aqua-fe--qg-selector-and-persistent-anchor-investigation.md`
- `uw_frontend/configs/README_recommended.md`

### Current Conclusion

Confirmed conclusion: simply relaxing the current replacement gate or copying
the External-KLT temporal gate is not supported. Hypothesis / Inference: a
geometry-risk source router is the most plausible expansion direction, but its
first decision point is the already-generated SP+LG-active matrix, not a new
tuning loop.

### Open Questions

- Do SP+LG's eight active windows yield valid common-support wins?
- Which geometry signals separate positive and harmful startup regimes?
- Does any gain require learned sources after a matched classical control?
- What untouched roster remains available for a new frozen confirmation?

### Next Experiment

Complete the existing 12-window, three-arm, three-repeat same-backend replay and
report all windows. If source supply looks promising, perform a frontend-only
geometry opportunity audit before creating a separately preregistered method.

## 2026-09-05 — Does startup deletion explain both v2 harm and apparent rescue?

### Research Question

Are the two v2 positive windows improvements from learned candidates, from
removing particular KLT observations, or from their joint intervention?

### Hypothesis

A02 proves registered deletion can switch initialization into a bad scale
basin. The A09/Bus wins may likewise be deletion-driven; only positive-window
donor-delete controls can separate this from candidate addition.

### Motivation

Learned and matched GFTT have the same direction in all four active cells, and
the A02 deletion-only trajectory nearly reproduces both replacements.

### Related Baseline

Fresh KLT, v2 XFeat/SP+LG, and same-ID/frame/dose matched GFTT.

### Proposed Idea

For A09/XFeat and AFRL Bus/XFeat, construct KLT minus exactly the registered
donor observations, add nothing, replay three times, and evaluate all four
arms on one recomputed common support per window.

### Why It Might Work

It isolates the one intervention shared by learned and matched replacements
without changing the backend, threshold, timing, or dose.

### Assumptions

The frozen action audit accurately identifies timestamp, feature ID, and
camera identity; the proxy supports within-window consistency comparisons.

### Potential Failure Cases

Deletion and insertion can interact non-additively; technical phase sensitivity
can overlap repeat ranges; sufficiency of a deletion set does not prove any
single donor is causal.

### Evidence

Confirmed fact: v2 is 2 WIN / 2 LOSS on active cells. Confirmed fact: A02
deletion-only is +659.4% APE and advances accepted initialization 0.785 s.
Confirmed fact: ten of fourteen learned lineages have one published
observation. Per-ID hidden survival and residual use are Unknown.

### Current Conclusion

The paper can claim a sensitive observation/initialization intervention, not
yet learned persistent-anchor enhancement. Positive-window mechanism remains
Unknown until the two deletion controls complete.

### Open Questions

- Does deletion alone reproduce the A09 order-of-magnitude rescue?
- Does Bus require insertion for its smaller improvement?
- Is premature sidecar-budget accounting an implementation error or only a
  policy limitation?

### Next Experiment

Preregister and run exactly six new donor-delete-only replays: A09 and Bus,
three each. Do not select a new method before this and the budget audit finish.

## 2026-09-05 — Do the two v2 wins require insertion?

### Research Question

Can registered donor deletion alone reproduce A09/Bus wins, or must a
replacement observation be inserted?

### Hypothesis

If deletion-only remains divergent or regresses while both learned and matched
classical replacements recover, the supported mechanism is an observation and
initialization intervention rather than deletion-only or learned persistence.

### Motivation

A02 established harm from deletion but did not explain the positive cells.

### Related Baseline

Fresh KLT, v2 XFeat replacement, and same-timestamp/ID/dose matched GFTT.

### Proposed Idea

Remove exactly the registered donors from fresh KLT, insert nothing, replay
three times per positive window, and compare all four arms on one support.

### Why It Might Work

It isolates deletion while retaining the same backend, timing, and baseline.

### Assumptions

The action audit identifies exact donor observations; proxy supports
within-window comparison; repeats characterize technical variability only.

### Potential Failure Cases

Deletion and insertion can interact nonlinearly. A successful matched
classical replacement cannot prove the learned source has no smaller effect.

### Evidence

Confirmed fact: A09 B-D remains at APE 1242.135 m while learned/matched converge
to 0.732/1.082 m. Confirmed fact: Bus B-D median APE is 53.052 m with two
divergent repeats, while learned/matched are 0.0423/0.0442 m. Both all-12 common
supports and 6/6 new receipts pass. Confirmed fact: matched classical produces
the same rescue direction. Backend per-ID residual use remains Unknown.

### Current Conclusion

Both positives require insertion relative to deletion-only, but learned is not
shown necessary. Together with A02, startup replacement is a high-leverage,
bidirectional initialization intervention and cannot be called no-harm.

### Open Questions

- Does moving the same intervention after a fixed startup protection horizon
  eliminate A02 harm while retaining A09/Bus benefit?
- Do any post-protection candidates publish for at least four observations?
- Can the later intervention avoid a new severe loss without per-window tuning?

### Next Experiment

Freeze one delayed newborn-slot version on the existing six development
windows. Shift only the five-selected-frame intervention interval; leave
source, thresholds, donor ranking, capacities, and continuation policy fixed.
