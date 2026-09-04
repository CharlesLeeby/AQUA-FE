# Project Context

Last updated: 2026-09-04

## Research Topic

Quality-guided underwater visual SLAM/VO/VIO frontend: protected GFTT/KLT tracking with selectively gated classical and learned recovery.

## Research Objective

Maintain KLT-level behavior on healthy underwater imagery while recovering useful, geometrically safe support in low-texture, low-coverage, illumination-degraded, or near-planar scenes. Evaluate frontend behavior and closed-loop impact without overstating window-specific or proxy-reference evidence.

## Current System

Images enter through ImageSequence, may receive CLAHE/adaptive CLAHE, and are scored for underwater degradation and spatial texture. A GFTT/KLT tracker supplies persistent temporal tracks. Grid, track-health, image-quality, and Fundamental/Homography diagnostics drive optional relaxed-LK, ORB, XFeat, SuperPoint+LightGlue, homography, or restricted LoFTR recovery. Learned proposals can require KLT confirmation, geometry checks, spatial benefit, and export-budget checks. Per-feature reliability q_i and visual sigma can be logged or sent to an external backend.

This repository does not contain the main pose-estimation backend. It exports ROS PointCloud feature bags to an external VINS-Fusion workspace and contains adapters/evaluators for several other research backends. The recent fixed VINS comparison disabled loop closure.

## Repository Structure

- uw_frontend/: executable frontend research package.
- uw_frontend/configs/: layered YAML defaults, ablations, and experimental profiles.
- scripts/: 754 top-level files and 1004 total non-cache files for run/export/materialization/audit/evaluation/report workflows at inspection time.
- tests/: 21 unittest-style contract/evaluator/runner tests at inspection time.
- papers/: protocols, preregistrations, freezes, claim-evidence maps, reports, and negative results.
- papers/ieee_sensors_journal_experiments/: append-only experiment governance.
- experiments/ and artifacts/: local run-scale and publication artifacts.
- datasets, logs, external_tools: symlinks into /mnt/data/AQUA-FE_WS/.
- CLAUDE.md: existing workspace guidance.
- docs/: shared Codex/ChatGPT research memory established on 2026-09-04.

README.md provides the repository entrypoint; uw_frontend/README.md contains the detailed package recipes. The workspace is a standalone Git repository on branch main, published at https://github.com/CharlesLeeby/AQUA-FE with SSH origin git@github.com:CharlesLeeby/AQUA-FE.git.

## Current Baseline

Strong reference: GFTT/Shi-Tomasi + KLT + forward-backward checking + patch NCC + persistent IDs, generally with adaptive CLAHE. The common KLT cap is 350 features. External VINS-Fusion original tracking, fixed-CLAHE KLT, ORB, pairwise SP+LG, pairwise XFeat, and pairwise LoFTR have separate baseline roles.

## Current Method

Durable main design: protected KLT/GFTT backbone plus sparse, confirmed, geometry-gated learned sidecars. LoFTR is an extreme low-texture/near-planar supplement, not a general matcher. Keep two evidence profiles distinct:

- proposed_safe: full/protected KLT mirror plus strictly gated sidecar injection.
- contribution_sparse: deliberately sparse/degraded backbone used to expose learned contribution.

Latest development/confirmatory branch found: lineage_early_seed_churn_guard_v3, which conditionally allows an early XFeat replacement path based on the causal GFTT-birth ratio and otherwise closes to KLT. Its 12-sequence confirmatory result was not yet found as complete.

## Datasets

Local namespaces confirmed through the external data mount include AQUALOC, AFRL, NTNU, Tank, UVVID, MIMIR-Underwater, FLSea-VI, and official EuRoC material. CIRS support is present in adapters/configs/artifacts. Exact sensors, reference quality, calibration, synchronization, and licensing must be checked per dataset and per frozen protocol; no single fully reconciled inventory was confirmed.

## Evaluation Metrics

- Trajectory: fixed-scale APE/ATE, translation RPE, initialization, output coverage, first-output delay, pose count/span, lost-tracking and solver diagnostics; Sim(3) only when explicitly labelled diagnostic.
- Frontend: feature count, grid coverage, track age/lifetime, dropout, FB error, NCC, F/H inlier ratios and residuals, learned/LoFTR candidates-confirmed-exported, source histograms, q_i, runtime/FPS.
- Validity: feature-budget/integrity checks, exact input identity, common support, reference type, and runability gates.

## Current Best Results

There is no single globally comparable best result. Strong scope-limited evidence includes:

- Frozen P07: 20/20 proposed bags were ZERO_ACTION and byte-identical to KLT B1. This is exact fallback/no-harm on those inputs, not learned contribution. Evidence: papers/p07_noharm_byte_identity.csv.
- Development-only CIRS s575,d30: KLT 2.224181/0.304697 m versus full profile 1.091415/0.270008 m APE/RPE with valid G0 common support. Evidence: papers/e3_g0_common_support/cirs_s575_d30/common_support_summary.json.
- AQUALOC A06 2210-2460: KLT 0.268486/0.113326 m versus protected mirror plus 10 LoFTR observations 0.058071/0.048803 m. Run: logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460.
- H07 1660-1720: KLT 0.050207/0.113417 m versus proposed_safe 0.050207/0.113416 m with zero LoFTR exports. Runs: logs/aqualoc_real_vins/external_klt_every2_may22_mirrorinject_h07_1660_1720_klt and logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_h07_1660_1720_loftr.
- Fixed modern XFeat M failed VINS initialization in 20/20 frozen windows; pairwise APE/RPE is undefined. Persistent-ID repair restored initialization on two diagnostic windows but produced very large errors, so it is not a learned-accuracy result. Evidence: papers/b1_vs_m_results.csv and papers/2026-08-08--xfeat-persistent-v2-repair.md.

Primary evidence authority for these boundaries: papers/final_claim_evidence.md and docs/RESEARCH_LOG.md.

## Known Problems

- Final proposed P took zero learned action on all 20 frozen P07 windows; confirmatory learned contribution is not established there.
- Learned replacement can delete future long-lived KLT births and destabilize scale.
- Direct transfer of the External-KLT temporal-collapse gate is rejected: it missed 2/2 known positives and opened on a known harmful window.
- q_i has a reliability meaning and backend interface, but general trajectory benefit is not established.
- Cross-dataset end-to-end superiority over strong KLT is not established.
- Many experiment generations coexist; the 2026-08-06 experiment_status.md is stale relative to the 2026-08-08 final claim map and September work.
- Proxy trajectories, fixed-scale metrics, and Sim(3) diagnostics require explicit labels.
- The repository has no declared open-source license.
- Large data/log/tool paths depend on external storage.

## Active Research Questions

- Does churn-guard v3 generalize on the frozen 12-sequence outcome-blind roster?
- Which causal frontend-only geometry signals identify action-positive cases without opening on harmful windows?
- Can learned-sidecar benefit be separated from dense-KLT/classical rescue?
- Can a multi-sequence, valid-common-support end-to-end learned contribution be demonstrated?
- Does calibrated q_i change backend trajectory quality at meaningful scale?

## Current Priorities

1. Audit or complete frontend_same_backend_confirmatory_v3 without changing its frozen contracts.
2. Preserve exact KLT behavior when learned recovery is inactive.
3. Keep the failed External-KLT direct-transfer result as a negative result; any geometry-aware replacement is a new branch.
4. Require accepted learned-born lineage and valid common support before making learned-contribution claims.
5. Reconcile the live experiment-status index and clarify the intended submission narrative.

## Recent Progress

- 2026-09-04: froze a 12-sequence same-backend confirmatory experiment for KLT, SP+LG, and XFeat churn-guard v3; execution notes record infrastructure recovery and an A04 archive-layout correction. Terminal results were not confirmed in this inspection.
- 2026-09-04: External-KLT gate-transfer quick probe returned NO-GO and stopped before VINS replay.
- 2026-09-04: initialized the standalone Git repository, added publication-safe ignore rules, and published the initial code/research-evidence snapshot to the public GitHub main branch.
- 2026-09-03: churn-guard v3 repaired a known harmful startup while retaining two historical positive feature bags on a locked n=4 development set; this remains development evidence.
- 2026-08-08: final claim-evidence map narrowed the submission story to exact fallback/no-harm, development-only selective rescue, a scoped XFeat initialization-failure result, and an M2 diagnostic negative-accuracy result.

## Next Experiments

- Finish/audit the already frozen confirmatory-v3 matrix: 12 sequence-level windows × 3 frontend arms × 3 serial backend repeats, with runability first and common-support fixed-scale APE plus 1 s RPE second.
- If developing a new trigger, use persistent-cell coverage, parallax/bearing diversity, homography dominance, and candidate grid gain as hypotheses; freeze it before new-window outcomes.
- For learned attribution, compare protected KLT, dense-KLT rescue, learned without LoFTR, and learned with LoFTR on action-positive low-texture windows.
- For no-harm, verify exact or near-exact KLT behavior and actual learned/LoFTR export counts on normal-texture windows.

## Important Files

- AGENTS.md — long-term Codex working and logging rules.
- README.md — public repository overview and quick start.
- .gitignore — publication boundary for data, models, runs, caches, and large reproducible intermediates.
- docs/CODEX_WORKLOG.md — task-level engineering/research work history.
- docs/EXPERIMENTS.md — standard experiment ledger.
- docs/RESEARCH_LOG.md — detailed project snapshot and research reasoning.
- CLAUDE.md — pre-existing workspace architecture guidance.
- uw_frontend/README.md — canonical package usage and metric overview.
- uw_frontend/configs/README_recommended.md — default/candidate/rejected profile map.
- papers/frontend_baseline_protocol.md — baseline/proposed/ablation taxonomy.
- papers/final_claim_evidence.md — frozen August claim-evidence boundary.
- papers/frontend_persistence_churn_guard_v3/report.md — latest completed development repair.
- papers/frontend_same_backend_confirmatory_v3/preregistration.md — latest confirmatory contract.
- papers/external_klt_dynamic_gate_quick_probe_v1/report.md — latest negative transfer result.
- uw_frontend/evaluation/run_frontend_eval.py — frontend-only entrypoint.
- uw_frontend/tracking/hybrid_tracker.py — hybrid frontend core.
- uw_frontend/ros/export_vins_features.py — VINS feature export and gating path.
