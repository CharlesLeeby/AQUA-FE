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

## 2026-09-06 — Delayed intervention removes harm and meaningful rescue

### Research Question

Can an exact KLT prefix remove A02 harm while retaining A09/Bus benefit?

### Hypothesis

If only startup deletion causes harm, moving unchanged action to frames 32--36
should preserve a later candidate benefit.

### Motivation

A02 deletion was harm-sufficient; A09/Bus needed insertion for rescue.

### Related Baseline

Frozen v2, fresh KLT, and new same-ID/frame/dose matched GFTT.

### Proposed Idea

Change only the global action interval from 0--4 to 32--36.

### Why It Might Work

All baseline development repeats logged initialization before frame 31.

### Assumptions

This is an offline development diagnostic; repeats are technical and reference
trajectories are proxies.

### Potential Failure Cases

Initialization can stay fragile, candidate leverage can vanish, or classical
controls can reproduce learned behavior.

### Evidence

All 54 backend plan rows and seven common supports pass. A02 returns within
1.2% of KLT, but A09 remains near 1242 m and Bus has no joint >=10% rescue.
Active directions are 6 WIN/1 MIXED, mostly small; matched controls compete.

### Current Conclusion

The hypothesis is half supported: delay removes tested harm but not while
retaining meaningful benefit. Learned persistent-anchor gain is unproven.

### Open Questions

- Can an online-observable state separate helpful and harmful intervention?
- Can learned candidates show value under a shared initialized state?

### Next Experiment

None in this protocol. `NO_EXPANSION`; a new mechanism needs a new freeze.

## 2026-09-06 — Is carried-track protection sufficient for no-harm?

### Research Question

Can A09/Bus benefit survive without A02 harm if candidates compete only with
newborn GFTT and never delete carried observations?

### Hypothesis

If mature deletion causes A02 harm, pre-refill admission should retain the
useful early candidate schedule while removing the wrong-scale failure.

### Motivation

v2 insertion was required relative to deletion-only for positives, while
delayed v3 protected A02 but suppressed meaningful rescue.

### Related Baseline

Fresh KLT, v2, delayed v3, and same-ID/frame/dose matched GFTT.

### Proposed Idea

Keep v2 candidate production/timing; preserve carried mirror observations and
spend only deterministic newborn-GFTT capacity.

### Why It Might Work

It retains the early candidate schedule but removes mature-track deletion.

### Assumptions

Source/age identify births; newborn opportunity cost is explicit; proxy
evaluation is valid only within the frozen development contract.

### Potential Failure Cases

Newborn identity may itself control initialization; candidates may be too short;
learned content may matter only in one sequence.

### Evidence

All frontend, matched, backend, and support gates pass. All 21 omissions are
age-1 GFTT with zero carried mismatch. A09 XFeat converges and beats matched.
A02 learned and matched both select scale near 0.50 versus KLT 0.899 and suffer
>6.7x APE. Bus is backend-inert.

### Current Conclusion

The hypothesis is rejected. Carried-track protection is insufficient; startup
newborn scheduling alone can flip scale. A09 remains one development positive,
but the unified method is unsupported.

### Open Questions

- Is a real-time initialization-complete signal already exposed?
- After a shared initialized prefix, can a multi-frame learned lineage affect
  residuals without steering initialization?
- Should this line stop if no causal online signal exists?

### Next Experiment

No new variant under `EXP-20260906-009`. Perform a read-only backend-interface
audit first.

## 2026-09-06 — Can the unchanged backend provide a causal init boundary?

### Research Question

Does locked VINS-Fusion expose an online initialization-complete signal that
can separate KLT initialization from later learned admission?

### Hypothesis

An existing backend output may mark nonlinear operation without backend changes
or future information.

### Motivation

Early substitutions rescue A09 but destabilize A02; an online boundary was the
only remaining justification for a post-init variant.

### Related Baseline

Protected prefill EXP-20260906-009 and delayed-v3 EXP-20260905-008.

### Proposed Idea

Audit the interface before implementing anything.

### Why It Might Work

VINS begins odometry publication only after successful initialization.

### Assumptions

Locked hashes and default node name match the inspected code.

### Potential Failure Cases

No typed status, stale reset state, offline export, or a signal too late for
initialization.

### Evidence

`solver_flag` changes before guarded odometry publication; private naming gives
`/vins_estimator/odometry`. No explicit status/reset event exists. Delayed-v3
already acted after all development KLT initializations and failed expansion.

### Current Conclusion

The signal exists but is scientifically insufficient: it cannot alter the
initialization decision that generates it.

### Open Questions

- Could a future system paper justify live feedback for post-init tracking?
- What genuinely new pre-init evidence could predict safe learned admission?

### Next Experiment

None on this line; preserve the negative result and do not create another
timing variant from the same six windows.


## 2026-09-06 — A stopping decision is not an impossibility claim

- Research question: does observing initialization completion imply subsequent scale correction is impossible?
- Hypothesis: the earlier interface audit conflated unchanged historical inputs with fixed future state estimates.
- Motivation: preserve a defensible causal interpretation of the failed delayed intervention.
- Related baseline: EXP-20260905-008 delayed-v3 and EXP-20260906-009 protected-prefill.
- Proposed idea: inspect the current optimization path and narrow the claim in an append-only supplement.
- Why it might work: code can establish which states remain optimized, while experiments bound demonstrated recovery.
- Assumptions: the inspected source identity matches the prior interface audit; no additional runtime evidence is inferred.
- Potential failure cases: treating NON_LINEAR as a quality certificate, fitted alignment scale as an internal initializer variable, or a single timing test as proof about every post-init policy.
- Evidence: processImage continues triangulation and optimization; Ceres uses visual/IMU residuals and writes back pose/speed/bias states. The frozen delayed-v3 failed its expansion gate.
- Current conclusion: Confirmed fact — tested delayed-v3 did not recover A09; Hypothesis / Inference — different later observations might change scale error. General recovery efficacy is Not evaluated.
- Open questions: future live-feedback efficacy and actual arrival ordering remain unmeasured.
- Next experiment: none under the current stopping rules; scientific uncertainty does not authorize another parameter variant.

## 2026-09-06 — Short publication is not a single-budget failure

- Research question: can an accounting-only fix explain and repair the short v2 learning lineages?
- Hypothesis: the upstream reservation counter and undifferentiated admission/continuation gates both truncate publication.
- Motivation: avoid changing multiple policies under the label of a bookkeeping bug.
- Related baseline: v2, delayed-v3 and protected-prefill; all outcome-known development windows.
- Proposed idea: rejoin all 14 lineages to identity-verified next-output metrics and reproduce gate behavior in the archived v2 code. The five partial-budget cases were already distinguished by the September 5 publication-only audit; restoring that missing local context prevents rediscovery being misreported as a new result.
- Why it might work: aggregate tags can be disambiguated by actual surviving candidate counts and source branches without rerunning a dataset.
- Assumptions: original metric receipts match; function tests establish behavior, not the hidden survival of any historical ID.
- Potential failure cases: partial-budget tags misread as full blockage; aggregate live counts misread as same-ID survival; output eligibility misread as actual residual use.
- Evidence: A02/SP+LG five singletons precede a row still forwarding 23 candidates, three precede zero; Bus two precede no learned output. A09 uses three reservations then microburst closes. Five synthetic frozen-code tests pass.
- Current conclusion: Confirmed fact — final rejection does not refund reservation; existing IDs re-enter donor/horizon checks. Exact hidden survival remains Unknown. These observed first-publication times permit only two or three observations under frame-4 cutoff, so an unchanged-horizon budget-only repair cannot establish a four-observation nonlinear chain from the same starts.
- Open questions: whether specific candidates survive internally, whether separating continuation has net backend benefit, and whether longer chains justify the extra classical-observation opportunity cost.
- Next experiment: none within the stopped stage; separately authorize and freeze any new admission/continuation experiment. Do not infer that the whole method class is impossible.

## 2026-09-07 — Test published-ID continuation as one separately authorized policy

- Research question: does allowing genuinely published, currently valid IDs to continue produce usable chains and net backend benefit?
- Hypothesis: first-admission policy is one publication bottleneck; removing that bottleneck may help but may also alter harmful initialization inputs.
- Motivation: accounting-only changes cannot overcome the v2 frame-4 cutoff; user explicitly authorized a separate lifecycle experiment after the diagnostic.
- Related baseline: frozen v2, delayed-v3, protected-prefill and EXP-011; all six windows are development data.
- Proposed idea: unchanged first admission, explicit public-ID state, validity-based consecutive continuation, carried-classical protection and newborn refill capacity; retain upstream reservations and cap actual publication separately at 50.
- Why it might work: a valid public chain can exceed the original horizon without repeatedly seeking admission donors, making longer observations available to VINS.
- Assumptions: candidate existence before online-seed gating is only stage-level evidence; backend actual residual use remains Unknown.
- Potential failure cases: candidates disappear upstream, newborn capacity runs out, cap closes chains, repeated newborn omissions change initialization, or matched classical explains the same gain.
- Evidence: eight minimal tests pass; A09 KLT export completed, XFeat probe incomplete. No new backend evidence.
- Current conclusion: Confirmed fact — policy is frozen and execution began; Hypothesis / Inference — longer publication may help VINS. Effectiveness is Not evaluated. This is not a behavior-preserving bookkeeping fix or a no-harm theorem.
- Open questions: A02 risk, A09/Bus retained gain, chain termination reasons and learned versus matched benefit.
- Next experiment: only EXP-012, with frozen six-window denominator and new matched controls; no second continuation variant if expansion criteria fail.

### EXP-20260906-012 probe completion checkpoint — 2026-09-07

Confirmed fact: both A09 probe receipts are complete and actual-bag audits PASS.
The same public XFeat ID 10000000 appears consecutively at output frames 2–12,
11 observations versus original v2's three. Frame 13 still contains raw ID 734,
but quality 0.0827817 is below unchanged 0.1, so continuation terminates normally.
Eleven newborn observations were omitted; carried classical changes are zero;
IMU/non-feature stream, time axis and retained fields/points match fresh KLT.
Matrix resumed at A09/SP+LG, skipping both identity-valid probes: 2/18 completed.
This confirms publication behavior only. New backend, A02 no-harm, A09/Bus gain,
and new-window results remain Not evaluated. No runtime source changes followed
the method freeze; the only next step is the remaining frozen matrix and controls.

## 2026-09-07 — Completed files and live progress are different evidence

- Research question: can an interrupted exporter or a stale RUNNING progress file be treated as a valid completed cell?
- Hypothesis / motivation: process lifetime failures can leave plausible full-length metrics while omitting the successful-exit receipt.
- Related baseline: EXP-012's two receipt-backed A09 probes.
- Proposed idea / why it might work: use exact completion receipts as the scientific ledger and a bounded, separately release-locked user service for execution; keep partial attempts.
- Assumptions / potential failure cases: active service does not imply later success; signal source is Unknown; a full metrics row count is insufficient to infer exit code zero.
- Evidence: original SP+LG had 400 metrics frames without a receipt; after preserved recovery it completed, and its bag equals fresh KLT. A monitored controller later returned SIGTERM/143. Current user service completed A02 KLT and continued the registered order.
- Current conclusion: Confirmed fact — four frontend receipts at 15:51; no new backend result. Infrastructure recovery cannot strengthen a scientific effectiveness claim.
- Open questions: A02 risk and A09/Bus retained backend benefit remain Not evaluated.
- Next experiment: none additional; finish only the already frozen lifecycle experiment.

## 2026-09-07 — Longer published chains yield local benefit, not no-harm

- Research question: does separating continued publication from first admission expand attributable backend improvement without severe regressions?
- Hypothesis / motivation: v2 could stop already admitted, still valid candidates; repairing the publication lifecycle might restore useful temporal constraints.
- Related baseline: frozen v2, exact fresh KLT and newly same-ID/frame/dose matched GFTT on the six outcome-known development windows.
- Proposed idea / why it might work: continue only truly public IDs while protecting mirror-carried classical tracks, without changing first admission, source, geometry, total cap or backend.
- Assumptions: internal presence is not residual use; omitting age-1 GFTT has opportunity cost; solver repeats are not independent windows. A continuation policy also changes donor omissions and may change subsequent first admissions.
- Potential failure cases: early measurement changes can alter initialization despite carried-track protection; mirror points never previously published can consume protected capacity.
- Evidence — Confirmed facts: 33 actual observations across 11 lineages, A09 length3→11; 24 new replays plus18 KLT reuse all runnable; full outcome2W/8T/2L. A09 fixed-scale -12.44%/-16.47% against same-grid v2, but Sim(3) APE/RPE increase ~41.4%/~3.4%. Both A02 arms remain severely worse than KLT. Bus input unchanged, no new intervention. Donor377 loses one observation, not104.
- Current conclusion: published-ID continuation has a local fixed-scale effect at A09 but fails the registered no-severe-regression and net-win conditions. There is no newly positive physical window and no evidence for overall superiority or no-harm.
- Hypothesis / Inference: A09 change is consistent with improved scale agreement, not uniformly improved shape. Eight A02 chains are capacity-limited under protection of all mirror-carried tracks; restricting protection to previously public tracks would be a different, untested policy with additional opportunity cost.
- Open questions: per-ID backend use, exact Bus tracker termination, generalization and independent GT accuracy remain Unknown / Not evaluated. Original DELETE_SUFFICIENT does not transfer automatically to this new donor set.
- Next experiment: none under the current freeze. NO_EXPANSION; do not try a second lifecycle variant or search until a desired win count.

## 2026-09-07 — 添加式预算独立研究
- Research question: 完整KLT上更多合格XFeat是否增加有效剂量与净收益？
- Hypothesis: 小并发限制可能抑制贡献；额外传统点也可能有同类收益。
- Motivation: 旧删除/续传结果不能隔离数量问题。
- Related baseline: 相同原始KLT350。
- Proposed idea: B/L6/L-all/C-all，共享源流与加法合并。
- Why it might work: 不损失任何基线观测，扩大可用持续约束。
- Assumptions: 时间、身份、有效性、去重和后端容量正确；非线性优化仍可能受害。
- Potential failure cases: 重复、错误约束、初始化扰动、求解时间预算不足、上游有限供给。
- Evidence: Confirmed fact: 原代码存在公开前 promotion 与容量限制；实测效果 Not evaluated。
- Current conclusion: Hypothesis / Inference，未获得支持或反证。
- Open questions: 剂量差、残差真实使用和端到端作用。
- Next experiment: 预注册固定六窗四臂，不新增扫描。

## 2026-09-07 — A09添加式剂量差与负收益
- Research question: 同一合格XFeat流解除6并发配额，更多实际剂量能否改善A09？
- Hypothesis: 完整KLT上的更高剂量可能补足约束。
- Motivation: 区分旧replacement与纯加法/数量。
- Related baseline: 锁定B及L6，全部同一诊断后端、三重复。
- Proposed idea: 冻结L-all相对L6数量对照。
- Why it might work: 扩大持续观测及后端实际残差。
- Assumptions: 固定支撑和尺度；这是开发窗、非独立GT。
- Potential failure cases: 初始化尺度错误、非线性求解、观测错误及solver时间预算。
- Evidence: Confirmed fact: L-all42018次对L62251次；残差建立次数也明显增加；38共同poses/37s/95%支撑、evo通过。APE中位L-all1451.201568m、L61415.067546m、B1242.139997m。详见checkpoint_a09.md和共同支撑CSV。
- Current conclusion: A09高剂量未提供净收益；对L6差异SMALL_OR_UNCERTAIN，对B两学习添加臂PRACTICAL_LOSS。Hypothesis / Inference: 尺度异常/初始化可能主导，但未完成因果归因。
- Open questions: 其余固定五窗、候选使用率与成本的差异。
- Next experiment: 按原合同完成剩余五窗；不围绕A09调参。


## 2026-09-07 — A02添加数量与求解压力
- Research question: 取消6条公开配额是否把有效观测剂量转成更好轨迹？
- Hypothesis: 更多持续观测可能增加约束，也可能改变初始化或在固定solver预算下增加风险。
- Motivation / related baseline: A02同一原B，源流及XFeat q完全共享。
- Proposed idea / why it might work: 本轮只加不删数量对照，长链应有机会提供更多优化约束。
- Assumptions: 原B精确保留、无未来选择、同二进制与共同支撑；技术重复不独立。
- Potential failure cases: 初始化、错误/相关约束、来源权重及求解时间混杂。
- Evidence: Confirmed fact：L-all实际残差中位598167，L6为14340；数量比较SMALL_OR_UNCERTAIN；学习两臂对B实用退化，C-all对B改善。L-all接近预算401/412、400/412、365/391；详checkpoint_a02.md。
- Current conclusion: 该窗不支持“只因加得少所以未获益”；精确退化机制为Hypothesis / Inference。
- Open questions: 何种初始化/约束/求解变化解释现象？其余四窗结果尚未齐备。
- Next experiment: 不新增实验，只完成冻结六窗四臂矩阵。


## 2026-09-08 — 输入身份需保留帧索引
- Research question: 同stamp能否唯一确定Cemetery原B所对应图像？
- Hypothesis: CSV冻结帧索引才是存在重复stamp时的输出语义。
- Motivation / related baseline: B严格357唯一时刻，源出现358记录且合并拒绝。
- Proposed idea / why it might work: 仅补原generate条件，从帧索引选择已冻结图像；不改变逐raw跟踪或候选门。
- Assumptions: 原CSV语义可信，B由该stride生成。
- Potential failure cases: 仅删源行会把后续私有previous_output保留在错误图片上；重新生成须披露成本和偏差。
- Evidence: Confirmed fact：全部357B stamp精确等于713raw按2/0选择；raw190/191同stamp、异像素，只有190应导出。见cemetery_duplicate_input_audit.json。
- Current conclusion: 结构错误而非效果结果；首尝试无效保留。修复后效果Not evaluated.。
- Open questions: 修复后的完整映射、容量和后端是否全部有效？
- Next experiment: 按恢复锁生成唯一正式共同流，继续原Cemetery四臂；无新参数/窗口。


## 2026-09-08 — 数量效果与净收益分开
- Research question: 更多同源合格点改善L6时，是否也超过完整KLT？
- Hypothesis: 小配额可能压低局部约束作用，但更大的添加剂量仍可能带来初始化/尺度风险。
- Motivation / related baseline: 原B不变的添加式四臂，六窗固定。
- Proposed idea / why it might work: 共享源流单独取消并发配额，使数量对比有明确控制。
- Assumptions: 全24输入身份读回通过；Cemetery一次无效尝试与修复明确保留；技术重复不独立。
- Potential failure cases: 中位数掩盖不稳定重复，来源q/代价不等，阶段性solver日志覆盖不全。
- Evidence: Confirmed fact：A08 L-all/L6达到实用改善，但L-all/B实用退化；Bus L-all首重复APE23.25m而另两次约.043m；H07全五对比不确定。详checkpoint_a08/bus/h07.md及comparisons.csv。
- Current conclusion: 局部数量效应成立不能替代端到端净收益判断；不存在当前五窗L-all/B实用改善。完整六窗结论待Cemetery。
- Open questions: 更多观测如何改变初始化与尺度，哪些实际残差参与风险？仅现有日志不足作纯因果归因。
- Next experiment: 仅完成Cemetery固定12次，然后给出一个后续方向，不自动扩展。


## 2026-09-08 — 添加式数量假设的完整六窗结论
- Research question: 完整保留KLT后，六条并发配额是否压低当前合格XFeat流的后端净收益？
- Hypothesis: 放开公开配额应形成更大实际剂量；若六条是主要瓶颈，应在完整B上形成稳健收益。
- Motivation / related baseline: 避免replacement删除KLT混杂；同一B、同一正式XFeat源及同二进制。
- Proposed idea / why it might work: 仅公开配额不同，持续有效链可提供更多视觉约束。
- Assumptions: 全24输入和72接收核对；固定六开发窗、三技术重复、COLMAP/proxy支撑；Cemetery结构修复及额外源尝试明确披露。
- Potential failure cases: 初始化/尺度变化、错误或相关约束、时间预算、来源q差异及宿主调度；不能从已加残差数推独立信息。
- Evidence: Confirmed fact：六窗发布和后端候选残差剂量均显著数值增加（倍率见CSV，不是统计显著性）；数量对比只有A08达到实用改善，L-all/B零改善、A09/A02/A08三退化；C-all/B在A02/Bus改善。Bus异常重复完整保留，最大资格834且无容量裁剪。证据report.md/comparisons.csv/backend_results.csv/source_supply.csv/36组common_support。
- Current conclusion: 当前有限生成器的剂量问题已有效检验；“此前只是六条太少”不足以解释完整KLT条件下的净收益缺失。局部数量效应与总体添加机制支持必须分开。不提升C-all为主方法，不改变protected KLT主线。
- Open questions: 哪些初始化/尺度和约束使用变化导致学习添加风险？当前非共享初始化/非等资源来源比较不足以作纯因果归因，相关解释为Hypothesis / Inference。
- Next experiment: 本轮停止。唯一后续建议为现有逐ID、初始化与尺度日志的失稳归因审计；新增预算/窗口/时机变体Not evaluated.且不自动执行。

## 2026-09-08 — Independent classical additive opportunity question

- Research question: can fixed C-all produce practical VIO benefits outside its six development windows with limited severe regressions?
- Hypothesis: useful additional classical observations may create reproducible end-to-end opportunities without learned-source necessity.
- Motivation: old C-all positives A02/Bus and the sufficiently dosed L-all negatives warrant mechanism cases, not detector tuning.
- Related baseline: complete KLT B, frozen additive-budget C-all at 49c0247.
- Proposed idea: two prospectively fixed batches of 12 windows, 12 physical sequences, all outcomes retained.
- Why it might work: Hypothesis / Inference — additional valid constraints may improve geometry or initialization; they may also destabilize it.
- Assumptions: same input/backbone, unchanged source/q/backend contracts; COLMAP is a proxy and old project exposure persists outside the C development set.
- Potential failure cases: cold-start failure, scale anomaly, sparse reference/common support, candidate capacity failure, severe single-repeat instability, foreign host load.
- Evidence: Confirmed fact — old C-all/B counts 2 gain/0 loss/4 uncertain; new 112-candidate structural roster and two fixed 12-window batches. New accuracy: Not evaluated.
- Current conclusion: Unknown; neither confirmation nor lack of generalization is established. Old NO_EXPANSION decisions are unchanged.
- Open questions: cross-sequence repeatability, candidate lifetime/initialization differences, negative case mechanisms.
- Next experiment: full frozen Batch A B/C three technical repeats, followed only by the preregistered conditional Batch B.

## 2026-09-08 — A01 adds a classical-additive risk case

- Research question: can useful extra observations be harmful despite full backbone preservation?
- Hypothesis: initialization/scale sensitivity may make an otherwise valid additive candidate set harmful.
- Motivation: first new fixed-C comparison is severely worse, unlike old A02/Bus positives.
- Related baseline: fresh complete KLT B on A01[0,900), three technical repeats.
- Proposed idea: retain the window for subsequent observation-utility/risk analysis; do not tune C here.
- Why it might work: Hypothesis / Inference — risk models could distinguish candidate-set or initialization contexts; this experiment does not identify per-feature utility.
- Assumptions: serialized preservation, exact delivery, fixed backend/evaluation and common-support gates hold.
- Potential failure cases: proxy reference bias, initialization stochasticity, solver timing, scale ambiguity; larger candidate count/lifetime alone is not sufficient.
- Evidence: Confirmed fact — A01 C50545 extra observations,1017 IDs, lifetime median26; APE median0.5550m vsB0.1550m, RPE0.07013 vs0.02066; six-supportPASS. Init delay+1.0006s, misalignment rejections2→7 and fitted-scale changes co-occur. Artifacts: new case_registry.csv/backend_results.csv/common_support/coe1_a01_00000_00900.
- Current conclusion: a new severe classical-additive negative is established within this window/proxy contract. Root cause Unknown; general expansion decision Unknown.
- Open questions: whether new positives also appear, and which initialization/utility signals distinguish outcomes.
- Next experiment: continue the unchanged remaining Batch A matrix, then apply its frozen gate.


## 2026-09-08 — Prospective comparison versus globally unseen data
- Research question: what independence does this opportunity-expansion roster actually support?
- Hypothesis: a prospective fixed-C comparison outside its six development cases can test that limited transfer question even when other project lines have used some physical intervals.
- Motivation: avoid inflating sequence-held-out into a claim that no project member has ever evaluated these data.
- Related baseline: the old six outcome-known C-all controls and the unchanged fresh-B contract.
- Proposed idea: keep the already frozen roster and add a separate broader-history exposure audit, without outcome-driven exclusions.
- Why it might work: explicit provenance keeps the prospective comparison and prior project exposure distinguishable.
- Assumptions: the two inspected historical manifests are informative but not an exhaustive record of every historical run.
- Potential failure cases: missing historical records; ambiguous inclusive endpoints; falsely treating the remaining windows as universally unseen.
- Evidence: Confirmed fact. broader_history_exposure_audit.csv records A 7/12 and B 7/12 interior overlaps with identified source rows; provenance JSON pins source hashes. The preregistration already restricted heldout scope to six C-all development windows.
- Current conclusion: no change to roster or practical classifications; broad unseen-data generalization is Unknown. This audit does not estimate a natural positive rate.
- Open questions: mechanisms causing case-level gains/losses are Not evaluated. by this provenance audit.
- Next experiment: finish the existing frozen B/C matrix and transfer its set-level outcomes to observation-utility / risk research only.


## 2026-09-08 — A03 severe numerical degradation despite receipt completeness
- Research question: can frozen extra classical observations damage an otherwise initialized VIO trajectory outside the C-all development set?
- Hypothesis: initialization-sensitive or poorly useful added constraints may amplify trajectory scale/path error even when all messages arrive intact.
- Motivation: distinguish structural delivery success from geometric utility and risk.
- Related baseline: fresh complete KLT on A03[0,900); old A02/Bus remain outcome-known controls.
- Proposed idea: retain the fixed intervention and characterize the new set-level negative for downstream mechanisms.
- Why it might work: the unchanged B/C contract provides a concrete contrast while complete receipts exclude silent dropping as the explanation.
- Assumptions: same frozen backend and evaluator identities; timing diagnostics are descriptive rather than causal.
- Potential failure cases: attributing the effect to initialization without a controlled initialization study, or using Sim3 to hide metric scale failure.
- Evidence: Confirmed fact. A03 own-support CAPE median2854.46348m versus B0.85802846m; CRPE277.286662m versus B0.07895172m; all6exactreceipts/runabilityPASS;42commonposes,41RPEpairs,evoPASS. Exact paths in the corresponding EXPERIMENTS entry and case_registry.csv. Firstpose delay is equal; fitted scales differ sharply.
- Current conclusion: second severe C-all regression outside its six developers. Mechanistic explanation remains Hypothesis / Inference. No acceptable-generalization confirmation can meet the frozen severe-count bound after this result; complete Batch A is still needed for honest case counts.
- Open questions: which set-level temporal/geometric properties distinguish any later positive/neutral cases from A01/A03?
- Next experiment: finish remaining frozen Batch A windows; do not activate B; pass complete evidence to observation-utility / risk mechanism research.


## 2026-09-08 — A04 opportunity exists as a baseline-anomaly rescue
- Research question: do new fixed-C positive opportunities appear after the first two severe negatives?
- Hypothesis: extra constraints can rescue some cold-start configurations while destabilizing others.
- Motivation: characterize the positive set faithfully instead of hiding its pathological baseline behind a large percentage gain.
- Related baseline:fresh completeKLT on A04[0,900);oldA02/Busremain development controls.
- Proposed idea:keep the registered robust label and attach baseline/initialization/common-support context for mechanism research.
- Why it might work:range separation plus preserved receipts identifies a reproducible set-level contrast even when absolute baseline quality is poor.
- Assumptions:own support/evo valid;fittedscale is diagnostic;technicalrepeat stability is not independent replication.
- Potential failure cases:claiming routine tracking improvement from rescue of a diverged baseline, overlooking later C initialization or marginal support, assigning each C feature a positive utility label.
- Evidence:Confirmed fact.A04CAPE median0.113799mversusB743.154136m;CRPE0.137633mversusB90.424742m;three C repeats narrowly stable. Support31/44poses=70.4545%,29RPEpairs,evoPASS. See case_registry.csv/common_support and case_mechanism_handoff.md.
- Current conclusion:a new robust/practical candidate-set positive exists outside sixCdevelopers;acceptable-risk generalization remains unsupported by the2severe cases. Cause of opposite outcomes acrossA03/A04isHypothesis / Inference.
- Open questions:which initialization/observation-utility properties distinguish the rescue and harm cases?
- Next experiment:finish remaining frozenBatchA;then observation-utility/risk analysis only,without newC tuning or BatchB.


## 2026-09-08 — A05 reference-limited case remains in the denominator
- Research question:what conclusion is allowed when both arms run successfully but their common reference grid is too short?
- Hypothesis:operational backend success can coexist with insufficient evidence for a comparative accuracy conclusion.
- Motivation:prevent an apparent full-coverage percentage from hiding the absolute support-count requirement.
- Related baseline:freshKLT B and unchangedC-all on A05[0,900).
- Proposed idea:retain NOT_EVALUABLE and publish the exact failed condition,without substituting a different window or metric.
- Why it might work:keeps the frozen scientific denominator honest and avoids unsupported utility labels.
- Assumptions:the inherited own-support evaluator's minimum30poses remains binding even when26RPE pairs are available.
- Potential failure cases:reporting unmatched accuracy,using only validRPE to claim victory,or dropping the case from the denominator.
- Evidence:Confirmed fact. common_support/coe1_a05_00000_00900/C-all_vs_B/common_support_summary.json records27matchedposes/27gridpoints,26s,ape_validFalse,rpe_validTrue;all6receipts/runabilityPASS.
- Current conclusion:APE/RPE comparison Not evaluated. Reference-limited,not a confirmed positive/negative candidate set.
- Open questions:per-feature utility and this window's true relative accuracy remain Unknown.
- Next experiment:continue the already frozen remaining8BatchA windows;no replacement of A05.


## 2026-09-08 — A06 demonstrates why direction and practical status stay separate
- Research question:how should a large favorable median difference be treated when the baseline varies even more across technical repeats?
- Hypothesis:unstable cold-start baselines can create large apparent median gains that fail the inherited conservative evidence threshold.
- Motivation:keep the preregistered practical classification independent of desirable-looking results.
- Related baseline:fresh fullKLT on A06[0,900);A04 is a separate numerically abnormalbaseline rescue positive.
- Proposed idea:retain directional improvement as a descriptive tier and put A06 in the uncertain list,with allrepeat ranges.
- Why it might work:preserves traceable evidence without turning technicalvariation into independent replication or overriding the frozen range guard.
- Assumptions:the unchanged maximum-arm-range condition is binding even when allCvalues are below allBvalues.
- Potential failure cases:calling every median decline a practicalgain,ignoring baseline instability,or introducing a new rule because A06 looks favorable.
- Evidence:Confirmed fact.APE medianreduction150.835229m<repeat-range181.441203m;B2.050386–183.491589m,C0.948918–0.970376m. Own support37poses/36RPEpairs,evoPASS;see common_support/coe1_a06_00000_00900/C-all_vs_B and case_registry.csv.
- Current conclusion:SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN. Initialization delay increases coexist with both negative A01 and positive A04 outcomes,so delay direction alone does not distinguish these cases;this is a descriptive observation,not a tested risk predictor.
- Open questions:which observation/backend-state mechanisms explain the different outcomes and baseline instability?
- Next experiment:finish remaining7registeredA windows;then handoff to observation-utility/risk research only.


## 2026-09-08 — Cross-sequence positive opportunity coexists with unacceptable registered risk
- Research question:does positive fixed-C opportunity recur beyond one new sequence,and does that suffice for confirmation?
- Hypothesis:some cold-start cases benefit repeatedly while other cases suffer severe harm;positive recurrence and acceptable risk are different requirements.
- Motivation:avoid either erasing positive evidence because of negatives or relaxing the severe bound after obtaining positives.
- Related baseline:freshKLT onA07[0,900);prior newpositiveA04 and severe negativesA01/A03.
- Proposed idea:retain A07 as the second robust positive and preserve the already failed severe-risk gate.
- Why it might work:separates the existence of local opportunity from the registered claim of acceptable-risk transfer.
- Assumptions:window-level effects only;three technicalrepeats do not establish independent replication;COLMAP proxy and broader project history remain disclosed.
- Potential failure cases:interpreting2gains as overallconfirmation,calling2severe cases acceptable after fixing<=1before results,or claiming no opportunity exists despite observed positives.
- Evidence:Confirmed fact.A07APE3.044412m→0.173396mmedian,RPE0.682203m→0.106705mmedian,narrowranges;36commonposes/34RPEpairs,evo/receiptsPASS. A04/A07 form2positive sequences;A01/A03 remain2severe negatives.
- Current conclusion:local positive opportunity recurs across two sequences,but the registered acceptable-risk condition is not met. Final full-denominator decision still awaits the remaining6A windows.
- Open questions:what utility/risk mechanisms separate positives from negatives without merely adding more candidates?
- Next experiment:complete A10/H01–H05 under frozen contract,then only observation-utility/risk mechanism research;no BatchB or C-all tuning.


## 2026-09-08 — A10 supplies a stable small-change neutral contrast
- Research question:does frozen C addition yield a practical benefit when the fresh baseline is already stable and close to the reference scale?
- Hypothesis:extra received observations can produce small mixed changes without meaningful overall improvement.
- Motivation:complement pathologicalbaseline/negative cases with a stable neutral case and preserve the absolute practical threshold.
- Related baseline:fresh fullKLT onA10[0,900);A06 is a different uncertainty case driven by extreme baseline variance.
- Proposed idea:retain A10 as SMALL_OR_UNCERTAIN,with directionalAPE tier and RPE increase visible.
- Why it might work:separates small changes from the larger but unstable A06 contrast,without claiming all neutral cases share one mechanism.
- Assumptions:the inherited0.01m absoluteAPE floor applies even when relative reduction exceeds5%;RPEguard unchanged.
- Potential failure cases:reporting percentage-only improvement,ignoring slightRPEworsening,or treating extra residual count as proof of utility.
- Evidence:Confirmed fact.A10APEmedian0.06007548→0.05661839m,RPE0.05224253→0.05369101m;40commonposes/39RPEpairs,evo/receiptsPASS;C8287publishedobservations and28898actualresidualblocks perrepeat. Exact ranges in case_registry.csv/common_support.
- Current conclusion:stable small-change neutral case,not a practicalpositive. Per-feature utility is Not evaluated.
- Open questions:which candidate-set or backend-state signals distinguish neutral from useful/harmful additions?
- Next experiment:complete fixed H01–H05 windows;then utility/risk research only.


## 2026-09-08 — H01 separates action dose from practical benefit
- Research question:can substantial received classical candidate action yield a neutral backend accuracy outcome?
- Hypothesis:many eligible/residual observations need not change the set-level error meaningfully when the baseline is already stable.
- Motivation:avoid equating candidate receipt or residual count with utility.
- Related baseline:freshKLT Harbor01[0,900),same frozen Harbor family backend.
- Proposed idea:retain the nonzero-action neutral contrast and its actual receipt/residual evidence.
- Why it might work:provides a concrete counterexample to interpreting an active sidecar as an effective sidecar.
- Assumptions:fixed accuracy contract,proxy reference and technicalrepeat limitations remain binding.
- Potential failure cases:calling neutral zero-action,claiming every receivedcandidate helped,or hiding the small error increases.
- Evidence:Confirmed fact.H01C20127publishedobservations/2498IDs and124110actualresidualblocks eachrepeat;APE median increases0.000758894m,RPE0.000134727m;ownsupport42poses/41RPEpairs,evo/receiptsPASS. Exact paths in case_registry.csv and common_support/coe1_h01_00000_00900/C-all_vs_B.
- Current conclusion:SMALL_OR_UNCERTAIN with stable baseline and substantial action. Per-feature utility remains Not evaluated.
- Open questions:which candidate/state properties distinguish this neutral case from the positive and severe-negative sets?
- Next experiment:finish remaining4frozenA windows;then utility/risk mechanism analysis only.


## 2026-09-08 — H02 broadens the positive case type without changing the risk decision
- Research question:are new positive opportunities limited to rescue of numerically extreme baselines?
- Hypothesis:fixed additional observations can also improve a moderate-error baseline in some cold-start windows.
- Motivation:avoid overgeneralizing the A04 failure-rescue context to every positive.
- Related baseline:freshKLT Harbor02[0,900),plus earlier A04/A07 positives and A01/A03 severe negatives.
- Proposed idea:retain H02 as a third robust positive and compare dose/lifetime/initialization context with old A02/Bus and the new positives.
- Why it might work:provides a distinct positive case while leaving the harmful cases and fixed severe bound unchanged.
- Assumptions:own-support accuracy validity and exact receipts;firstpose/initialization observations are descriptive,not mediation evidence.
- Potential failure cases:attributing the gain solely to earlier initialization,calling three positives overallconfirmation despite2severe cases,or assigning positive labels to allH02candidates.
- Evidence:Confirmed fact.H02APEmedian0.10939183→0.02941242m,RPE0.03621206→0.00768786m;41commonposes/40RPEpairs,evo/receiptsPASS;Cfirstposeabout1.599425searlier. Bfittedscale1.045307,C0.980834. Exact ranges and artifacts in case_registry.csv/common_support.
- Current conclusion:positive opportunity spans A04/A07/H02 and is not confined to A04-style baseline numerical explosion. Registered acceptable-risk transfer remains unsupported with2severe cases;complete denominator still pending.
- Open questions:which utility/risk properties distinguish these heterogeneous positives from neutral and severe-negative cases?
- Next experiment:finish remaining3frozenA windows;then observation-utility/risk mechanism research,without BatchB or tuning.


## 2026-09-08 — H03 warns against conflating relative neutrality with absolute reliability
- Research question:what does a neutral relative label mean when the baseline is badly inaccurate and C technical repeats split between accurate and inaccurate outputs?
- Hypothesis:initialization/solver sensitivity can produce radically different outcomes from one identical feature bag.
- Motivation:retain the best,median and worst outputs and avoid interpreting relative neutrality as reliable operation.
- Related baseline:fresh fullKLT Harbor03[0,900),plus earlier baseline-instabilityA06 and robust positives.
- Proposed idea:tag H03 in mechanism prose as a numerical-anomaly/repeat-instability case while preserving the frozen SMALL_OR_UNCERTAIN classification.
- Why it might work:separates delivery/runability validity,absolute error and relative evidence strength.
- Assumptions:three technicalrepeats are not independent scientific samples;all source/bag/binary identities stay fixed.
- Potential failure cases:promoting the single C0.0715mrepeat to a positive,omitting the two approximately838mCoutcomes,or treating runabilityPASS as numerical success.
- Evidence:Confirmed fact.H03BAPE848.004–848.385m,C0.071467/837.927196/838.008913m(min/median/max),43commonposes/42RPEpairs,evo/receiptsPASS. Actual C residual counts and firstpose timings vary across the same-bag repeats. Exact artifacts in case_registry.csv/common_support.
- Current conclusion:uncertain relative effect with severe absolute numerical pathology;cause remains Hypothesis / Inference. The registered relative severe flag is false because C is not worse than B by its frozen criteria,not because the outputs are operationally good.
- Open questions:what backend-state sensitivity explains the divergent C repeats,and can utility/risk research predict it without using future outcomes as per-feature labels?
- Next experiment:complete fixed H04/H05 only;then mechanism handoff,without extra replays or tuning.


## 2026-09-08 — H04 retains sub-threshold harm direction without relabeling
- Research question:how should small error increases be represented when they fail the registered practicalloss conditions?
- Hypothesis:neutral case pools can include small adverse directions as well as small favorable directions or technical uncertainty.
- Motivation:avoid interpreting the neutral label as exactly zero effect.
- Related baseline:fresh fullKLT Harbor04[0,900),plus nonzero-action neutralH01.
- Proposed idea:retain the frozen class and expose exact metric changes/receipt evidence.
- Why it might work:preserves useful mechanism context without introducing a new threshold.
- Assumptions:the unchanged absolute/relative/range/RPE criteria remain binding.
- Potential failure cases:calling every positive C-B difference a practicalloss,or suppressing the direction because it is below threshold.
- Evidence:Confirmed fact.H04APEmedian0.16890639→0.17110605m,RPE0.02455506→0.02463187m;43commonposes/42RPEpairs,evo/receiptsPASS;C5714publishedobservations/residual34968perrepeat.
- Current conclusion:SMALL_OR_UNCERTAIN with small adverse direction;candidate-specific utility Not evaluated.
- Open questions:which utility/risk signals distinguish small neutral changes from registered severe losses?
- Next experiment:finish H05 only,then final case-pool handoff and registered decision.


## 2026-09-08 — Full Batch A opportunity and risk boundary
- Research question: does the frozen classical additive control provide practical benefits beyond the old six developer windows while staying within the registered severe-risk bound?
- Hypothesis: extra classical observations can help in some cases, but observation utility and risk are heterogeneous.
- Motivation: finish the fixed denominator and provide genuine positive, negative and neutral mechanism cases.
- Related baseline: old C/B 2 gain/0 loss/4 small and L/B 0 gain/3 loss/3 small remain unchanged; fresh full KLT is the new-window comparator.
- Proposed idea: no method change; transfer this complete set-level case pool to observation-utility/risk research.
- Why it might work: comparisons include contrasting actual backend outcomes under the same additive contract, including moderate-error baseline gains and severe negatives.
- Assumptions: each valid comparison uses its own six trajectories and the frozen proxy-reference contract; technical repeats measure execution variation only.
- Potential failure cases: unfiltered additive admission causes large errors in A01/A03; A04 baseline rescue and H03 unstable numerical states could mislead an overly simple utility model; A05 has inadequate common-pose count.
- Evidence: Confirmed fact. Batch A has 12 windows/72 formal replays, 3 practical/robust gains across A04/A07/H02, 2 severe practical losses, 6 small/uncertain, 0 FAIL and 1 NOT_EVALUABLE. H05 closes the denominator with stable small C-B increases despite 8610 published candidates and exact backend receipts. Inspect expansion case_registry.csv, backend_results.csv and own common_support directories.
- Current conclusion: local positive opportunity is observed, but the <=1 severe-regression bound is violated. ADDITIVE_OPPORTUNITY_NOT_GENERALIZED and EXPANSION_STOPPED_AFTER_BATCH_A are required. This does not erase positive cases or authorize more window searching.
- Open questions: which pre-outcome observations predict utility versus initialization/trajectory risk? Causation and individual feature utility remain Unknown / Not evaluated.
- Next experiment: only observation-utility/risk mechanism research, separately designed and authorized; these outcome-known windows are development cases for any mechanism informed by them, requiring fresh independent confirmation later.


## 2026-09-08 — Final inference boundary after complete classical opportunity expansion
- Research question: can the fixed classical additive probe retain useful benefits beyond six developer windows while avoiding unacceptable severe regressions?
- Hypothesis: set-level benefit may transfer locally, while harmful observations or vulnerable numerical states require a utility/risk mechanism.
- Motivation: use a prospectively frozen full denominator to prevent favorable-case searching and preserve real negatives for mechanism research.
- Related baseline: fresh complete KLT B and old outcome-known C-all A02/Bus controls; prior continuation and additive-budget outcomes unchanged.
- Proposed idea: conclude the bounded probe and transfer a structured outcome-known case pool; no new method or admission threshold is proposed here.
- Why it might work: contrasting stable positive, severe negative, small-change, baseline-anomaly and initialization/repeat-instability cases can test future explanations against evidence that already includes failures.
- Assumptions: the cold-start intervention includes initialization; own-six support and frozen SE(3)/RPE rules apply; proxy reference and deterministic sequence roster bound inference; repeats are technical only.
- Potential failure cases: treating A04 baseline rescue as ordinary good-baseline gain; treating H03's single good C repeat as success; promoting A06 beyond its frozen range threshold; using A05 invalid accuracy; labeling every candidate from window class; reusing outcome-known mechanism-development cases as independent confirmation.
- Evidence: Confirmed fact. 12 windows/72 replays, 3 robust practical gains across A04/A07/H02, 2 severe practical losses A01/A03, 6 small/uncertain, 0 FAIL, 1 NOT_EVALUABLE. Artifact identity/receipts/evo/classification audit PASS. Published dose and lifetime vary across both gains and losses; new positive first-pose delays can increase or decrease. Exact numbers and boundaries are in expansion report, case_registry, per-repeat backend table and case_interpretation.
- Current conclusion: Confirmed fact. Local practical opportunity exists outside the six developer windows, but acceptable-risk generalization does not meet the frozen contract. ADDITIVE_OPPORTUNITY_NOT_GENERALIZED; EXPANSION_STOPPED_AFTER_BATCH_A. Hypothesis / Inference. A single dose/lifetime/initialization-delay descriptor is unlikely to suffice for safe utility prediction; no causal rule has been demonstrated.
- Open questions: individual candidate utility, causal sources of numerical divergence, role of timing and optimization budget, generalization to independently unseen data and independent GT remain Unknown / Not evaluated.
- Next experiment: only a separately specified observation-utility/risk mechanism study; current cases are outcome-known development evidence for a mechanism informed by them. Stop additive-observation primary-hypothesis expansion; no further C-all tuning/window search/learned expansion in this task.


## 2026-09-09 — Original-point same-frame recovery hypothesis
- Research question: can XFeat motion initialize LK at a genuinely lost old point better than ordinary larger-window retry?
- Hypothesis: local verified correspondences may move LK into the correct basin without transferring another keypoint's identity.
- Motivation: require direct pixel correctness evidence instead of merely longer ID lifetime.
- Related baseline: original KLT350 and existing31/4 traditional retry; old endpoint-association recovery and fail-open SP/LG coordinate adapter are distinct.
- Proposed idea: local affine initial motion, original-point LK refinement, common FB/NCC/border/identity/geometry gate, then normal GFTT.
- Why it might work: broad learned matches may guide large-motion/appearance-change failures while subpixel refinement preserves the original query.
- Assumptions: verified local motion is coherent, original point remains visible, raw frames adjacent.
- Potential failure cases: parallax boundaries, repetitive texture, occlusion, insufficient support, wrong geometric references; surviving IDs alone are not proof.
- Evidence: unit behavior checks pass; formal controlled/natural/backend results Not evaluated.
- Current conclusion: Hypothesis / Inference. No efficacy or novelty claim.
- Open questions: controlled false accepts, incremental recovery beyond C, natural chain persistence and backend net gain.
- Next experiment: fixed A02/A08/H02200-frame frontend contract, then at most A02/H02 B/C/L×3 only if all entry conditions pass.


## 2026-09-09 — Original-point learned recovery: no increment over conventional retry
- Question / hypothesis: can frozen XFeat local motion recover the original failed KLT point beyond a larger-window LK retry? Motivation was recovery correctness rather than more learned births or q tuning. Baseline B original KLT; comparator C fixed31/4 retry; L uses a local affine initial guess then the same final checks.
- Why it might work / assumptions: local correspondences could disambiguate motion while seeded LK retains original-point identity; assumes enough consistent local support and observable original texture. Failure cases include occlusion, boundary, mixed/insufficient motion support, or C already solving recoverable cases.
- Confirmed facts: frozen48 synthetic pairs give L835/C2488 correct recoveries from6532 visible B failures; L0 wrong accepts. Paired natural C148/L8, L-only0; actual L11 events with3 reaching4 public outputs. Gates fail. Exact evidence: papers/frontend_learned_klt_recovery_v1/report.md, frontend_results.csv, recovery_events.csv and decision.json.
- Inference / evidence boundary: this version rejects many natural supports and contributes no measured increment beyond C. Gate reason names do not independently prove physical cross-surface motion. Natural identity correctness and backend effect remain Unknown / Not evaluated.; synthetic evidence cannot establish them.
- Current conclusion / open questions: NO_LEARNED_INCREMENT; secondary REAL_RECOVERY_NOT_ESTABLISHED. Does not disprove every learned recovery mechanism, but no tuning/alternate mechanism is justified within this closed task. Old classical/q/continuation conclusions unchanged.
- Next experiment: none authorized automatically; archive this version, no candidate for validation window.


## 2026-09-10 — Newly authorized SEA-RAFT direct-measurement screening pending contract
Research question / hypothesis: does direct SEA-RAFT displacement offer measurement capability beyond KLT and strong LK retry on identical queries? Motivation: separately test network predictions before any recovery design or VINS integration. Proposed idea: compare raw flow and fixed-check usable measurements on48fixed controlled pairs, then conditionally three natural fragments; no LK-refined output substituted for raw network flow. It could help if direct dense correspondence resolves motion outside LK capture; assumes correct checkpoint/input-coordinate handling, with occlusion and domain shift as failure cases. Confirmed evidence currently only preparation: official source acquired, weights not loaded,0real pairs. Performance and identity accuracy Unknown / Not evaluated. Current conclusion: no capability conclusion; prior specified model/settings/gates missing. Open question/next experiment: obtain that original contract before weight/coordinate verification and the authorized screen. Old recovery conclusions unchanged.


## 2026-09-10 — SEA-RAFT capability found; usable natural increment remains limited
研究问题/假设：直接稠密光流能否在相同查询点上恢复强 LK 无法恢复的位移？动机是在开发恢复 ID 或接入 VINS 前，先检验测量能力。基线 B 为原 21/3 KLT，C 为 31/4 强 LK；方案为官方 spring-M 的直接预测及共同 FB/边界门。可能奏效的原因是学习对应可以覆盖局部 LK 难以处理的大位移和光度变化；前提是尺度正确且点可见，主要失败风险为遮挡、推断出的不可见位置及自然片段中的短暂可见性。
Confirmed facts: 固定 48 对中，S 原始预测在 6532 个可见 B 失败点上全部 ≤2px；过滤后 S 正确 6525，C 正确 2672，同时 S 误收不可见点 309 次。指定 large 和 illumination 分组通过，outside_occluded 全部失败。自然 S-only 通过三步普通 LK 的数量为 A02/A08/H02 = 0/0/20，持续的独有机会仅出现在 H02。证据位于 papers/frontend_searaft_screening_v1/ 的报告、CSV 和 decision.json。
解释/推断：受控变换证明了直接预测能力，但 FB 加边界不能可靠排除遮挡。H02 有局部测量机会；其他片段未达到预先冻结的持续性门。三步 LK 和图像上的合理性不是物理真值或真实漂移控制证据。当前结论 CONTROLLED_GAIN_ONLY；自然身份 Unknown，后端收益和系统安全 Not evaluated.。开放问题为 H02 机会能否被可靠利用，超出本轮范围。下一实验：不自动启动；封存正负证据，不调参或扩展。

## 2026-09-10 — Current-image evidence helps, but the frozen invisible-error target fails
Research question/hypothesis: can fixed local image support make already accurate SEA-RAFT displacements into more credible observations without sacrificing gains over strong LK? Motivation: the previous screen accepted invisible points despite good raw displacement. Baselines are old S_common/C_common; proposed check is an existing zero-mean11×11 patch NCC at unchanged endpoints, with exact subpixel sampling. It might reject predictions over unrelated random occluder texture while retaining visible correspondence; it assumes local appearance consistency. Expected failures include low texture, photometric change, repeated structure, border support and ambiguous visibility guards.
Confirmed facts: on the fixed24-pair check half, S correct3321→3276, wrong199→18; artificial-occlusion rectangle false accepts160→0. Remaining14 occlusion-patch-guard and4 image-border-guard accepts still count as errors under the unchanged contract (18/940=1.91%>1%). Correct retention98.64% and gains over C0/C1 survive. H02 retains7/20 old three-step events, with3 current-structure-supported and4 unresolved; C/S endpoints for all20 differ≤2px. Evidence: papers/frontend_searaft_evidence_check_v1/report.md, evidence_results.csv and natural_event_review.csv.
Interpretation/inference: cheap local photometric evidence addresses much of the synthetic random-occlusion error, but cannot certify visibility or identity near fixed guards. The natural clues often concern accepting nearby classical and learned endpoints differently, not a location classical flow failed to predict. High NCC on smooth/repeated texture is not identity truth. Conclusion EVIDENCE_GATE_NOT_SUPPORTED; retain partial capability findings, leave old CONTROLLED_GAIN_ONLY unchanged. Open question is reliable interpretation of boundary/occlusion support under real underwater appearance changes; beyond this run. Next experiment: none automatically, no threshold adjustment or backend integration.

## 2026-09-11 — Real correspondence question isolated from synthetic gates
Research question/hypothesis: does the fixed learned displacement reach the same real physical location more accurately than strong LK when both use the unchanged image-evidence check? Motivation: prior synthetic gains and H02 gate-only differences did not establish real positional advantage. Baseline C1 is original strong LK plus the fixed patch check; S1 is original direct SEA-RAFT plus that same check. Learned dense correspondence could help under longer actual motion; assumptions are independent physical correspondence reference and unchanged inputs. Repeated/blurred texture, occlusion, source-selection bias and annotation uncertainty are failure cases.
Confirmed fact: source-grid queries were frozen before prediction across 12 fixed real pairs, with 92 queries. At t+1 both C1 and S1 accept 46/46; A02/A08 t+10 queries are also all accepted. H02 t+10 has C1=9/S1=12 of 16, including 4 S-only and 1 C-only; one discrepancy has endpoints within 2 px. No independent human pixel references are available; blind full-target materials and a blank 92-row reference form were saved before prediction. Accuracy remains Not evaluated. See papers/frontend_searaft_real_correspondence_v1/report.md and comparison.csv.
Hypothesis / Inference: larger gaps produce some different algorithm outputs on H02, but neither acceptance nor endpoint separation establishes which reaches the same physical point. Current conclusion is REFERENCE_PENDING. The t+10 condition deliberately lowers the sampling frequency and does not establish an original adjacent-frame benefit. The open question is real endpoint accuracy relative to independent manual reference with recorded uncertainty. Next: human blind review of the fixed query set, then evaluate saved predictions; no further inference, replacement images or backend integration in this run.

## 2026-09-11 — SEA-RAFT after classical recovery, system probe
Research question/hypothesis: can SEA-RAFT recover same-frame tracks missed by strong LK and improve system trajectory beyond both KLT and classical recovery? Motivation: prioritize system evidence without waiting for human92-point labels. Baselines B=KLT,C=KLT+31/4 retry; R adds frozen direct SEA-RAFT plus existing patch gates only after C failure. Potential benefit: longer useful tracks; assumptions/failures: patch evidence is not physical truth, false recovery and altered GFTT can hurt initialization/trajectory. Confirmed fact: integration priority test and initial baseline serialization checks passed. System effect Not evaluated. Current conclusion: old screening/reference conclusions unchanged. Open question/next experiment: one frozen H02/A02 three-arm matrix, no expansion or parameter search.

## 2026-09-11 — SEA-RAFT system increment decision
Research question/hypothesis: does SEA-RAFT add trajectory benefit after strong classical recovery? Motivation: prioritize a concrete system experiment without waiting for human92-point truth. Baselines: original KLT B and31/4 strong-LK recovery C; idea R recovers only remaining same-frame failed original IDs with fixed direct flow and patch checks. It might preserve useful tracks; assumptions/failure cases include false recovery, initialization scale failure and changed future GFTT.
Confirmed facts:18 fresh replays and complete receipt/support gates; H02 R APE0.026602m versus B0.111301m, but C APE1017.99–1030.08m. A02 R1.157391m versus B0.065202m and C1.153630m, severe R/B loss and no practical R/C increment. Repeat instability retained. Recovery events1135/33, public continuation1055/15. See system_probe_v1 results and comparison.
Evidence interpretation: H02 local improvement is real within this frozen proxy comparison; C anomaly prevents calling it robust increment over healthy classical recovery. Cross-window combination is UNSAFE_OR_UNRESOLVED. Runability and residual participation do not establish correspondence truth. Cause of C anomaly Unknown; no isolated runtime mechanism demonstrated because initialization and GFTT changes remain.
Current conclusion/open questions: this combination fails the finite development screen; per-point truth remains Unknown, and old CONTROLLED_GAIN_ONLY/EVIDENCE_GATE_NOT_SUPPORTED/REFERENCE_PENDING remain unchanged. Next experiment: none authorized by this completed probe; stop and return evidence to user, with no automatic expansion or retuning.

## 2026-09-11 — Direct SEA-RAFT deletion ablation closes recovery line
Research question/hypothesis: removing strong LK before SEA-RAFT might retain H02 gain and remove A02 severe harm. Motivation: answer one system-design question through deletion, with no changed gates/model/reliability. Baseline fresh original KLT; D sends ordinary failures directly to frozen SEA-RAFT and advances its own causal trajectory/GFTT. Assumptions/failure cases: strong LK may select a different survival set; false recovery, altered GFTT and initialization remain possible, physical truthUnknown.
Confirmed facts:12fresh B/D replays complete; D/B medianAPE H02 0.350326/0.102702m,A02 0.506198/0.145545m. Every D repeat has higherAPE/RPE than worst corresponding B. OldR re-evaluation H02 0.026602m,A02 1.157391m: deletion loses H02 gain, alleviates A02 old harm but not net loss to freshB. Recovery10360/71events reaches public support10214/44; input/receive/common-support gates pass. See direct_recovery_v1 report/results/comparison.
Interpretation: UNSAFE_OR_UNRESOLVED; the proposed deletion does not solve the design problem. Exact causal reason remainsUnknown because initialization and futureGFTT are not isolated; event count or residual participation is not a substitute for system gain. Cross-batch comparisons cannot independently isolate LK causality. Current conclusion: close this SEA-RAFT same-frame recovery combination line; preserve all old negative/reference results. Open question: general learned-measurement utility is not settled by two development windows. Next experiment: none; no automatic order/gate/model/window search or annotation.


## 2026-09-11 — New authorized temporal observation refinement hypothesis
- Research question: can bounded coordinate correction on identical KLT tracks improve real correspondence error and fixed VINS?
- Hypothesis: temporal error supervision reduces accumulated measurement error beyond per-frame supervision.
- Motivation: user closes same-frame recovery and requests a small supervised prototype.
- Related baseline: unchanged B KLT; P same network with per-frame supervision only; KLTNet prior reference-patch refinement.
- Proposed idea: zero initialized shared patch residual encoder, fixed ±2px per-axis corrections; T adds error-difference loss.
- Why it might work: fixed identity reference may retain information lost in successive KLT updates (Hypothesis / Inference).
- Assumptions: trustworthy static 3D correspondence, causal inputs, no feedback to B state.
- Potential failure cases: incorrect depth/pose semantics, occlusion, nonrigid algae, baseline errors beyond range, sim-to-real gap.
- Evidence: Confirmed fact: local MIMIR subset omitted depth/segmentation. Official sources describe available depth and segmentation; verification pending.
- Current conclusion: no effectiveness conclusion; all previous stop decisions remain.
- Open questions: valid supervision and independent sequence gain.
- Next experiment: frozen protocol in papers/frontend_temporal_observation_refinement_v1/protocol.md.


## 2026-09-11 — Temporal refinement supervision stop
- Research question: can unchanged KLT observations benefit from time-consistent learned coordinate correction?
- Hypothesis: T improves true correspondence over B and P; remains untested.
- Motivation: avoid learning against a visually plausible but geometrically false label.
- Related baseline: planned B KLT and P framewise shared-patch network; KLTNet prior art acknowledged.
- Proposed idea: same frozen ±2px prototype, no research-direction change within this task.
- Why it might work: fixed-reference appearance and error-change supervision may constrain accumulated measurement drift (Hypothesis / Inference).
- Assumptions: valid depth-to-metric conversion, correct camera/world transform, static visibility masks.
- Potential failure cases: constant/saturated/otherwise encoded depth produces fictional points; apparent alignment could be fitted rather than verified.
- Evidence: Confirmed fact:12/15 downloaded depth samples are constant1.0; three diagnostics mostly1; retained SHA/CRC/extrema in decision. Unknown: physical encoding and cause. Zip signature counts do not prove byte identity of every unextracted file. Official issues are third-party reports without a verified fix.
- Current conclusion: SUPERVISION_UNAVAILABLE for fixed candidates; zero valid labels means no temporal-refinement performance inference. Synthetic projection tests passed, real projections Not evaluated. Earlier SEA-RAFT closure untouched.
- Open questions: usable metric decoding or corrected depth source and real camera-pose convention.
- Next experiment: only after verified MIMIR correction, check actual static multi-frame projections; no automatic alternative dataset, parameter search or VINS replay.


## 2026-09-12 — Authorized supervision-source substitution
- Research question: unchanged bounded temporal coordinate refinement on KLT tracks.
- Hypothesis: temporal supervision improves real3D correspondence beyond framewise fit.
- Motivation: user explicitly substitutes TartanAirV1 for unavailableMIMIR without changing algorithm.
- Related baseline: originalKLT B and originalshared-patch P; oldMIMIR result staysSUPERVISION_UNAVAILABLE.
- Proposed idea: same model/loss, verifiedV1 depth/pose/static-mask labels.
- Why it might work: trustworthygeneric3D labels enable the originally planned test; underwater transfer remains a separate hypothesis.
- Assumptions: V1depth=metricplanez, cameraNED→world, exactrow/index alignment, officialmask semantics with geometric visibility cross-check.
- Potential failure cases: coordinateaxis error, occlusion/dynamicmask imperfections, model limits, sim-to-real gap.
- Evidence: Confirmed fact: officialV1 format/ZIP member names support fixed4scene subset; actualgeometry pending.
- Current conclusion: no method gain yet; data authorization supersedes oldMIMIR-only restriction.
- Open questions: validlabels and T/P incremental gain.
- Next experiment: papers/frontend_temporal_observation_refinement_tartanair_v1/protocol.md; no additional source or hyperparameter search.


## 2026-09-12 — Verified alternative supervision, unchanged hypothesis
- Research question / hypothesis: does the original temporal loss improve fixed KLT correspondence beyond the same pointwise model?
- Motivation / related baseline: execute the previously blocked B/P/T experiment using authorized generic simulation labels.
- Proposed idea / why it might work: original bounded shared-patch correction; no algorithm redesign. Hypothesis / Inference: reference appearance may constrain KLT drift.
- Assumptions / potential failure cases: official flow masks and depth consistency identify usable static points; approximate masks, depth boundaries, model correction range and domain transfer remain limits.
- Evidence: Confirmed fact: all12 fixed actual V1 pair checks pass after correcting a diagnostic denominator bug; actual cache smoke has finite loss/nonzero gradient and zero model exactlyB. Old MIMIR failure is unchanged.
- Current conclusion: supervision blocker removed for this separate TartanAir task only; method effectiveness Not evaluated pending formal training.
- Open questions / next experiment: single frozen P/T training and held-out six-block measurement; no new dataset or hyperparameter search.
