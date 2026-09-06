# Project Context

Last updated: 2026-09-05

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

Latest completed confirmatory branch: lineage_early_seed_churn_guard_v3, which conditionally allows an early XFeat replacement path based on the causal GFTT-birth ratio and otherwise closes to KLT. Its 12-sequence frontend matrix and all eligible backend replays are complete. XFeat acts in only 1/12 windows, so the branch remains a selective development mechanism rather than a generally superior main method.

Latest development branch: `lineage_early_seed_geometry_router_v1`. It
structurally protects tracked KLT and limits learned exchange to startup age-1
GFTT births, but its frozen six-window export-only result is `SAFE_NULL`: all
safety checks pass, while only one observation on one A09 frame is admitted.
It is default-off and not adopted.

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
- Confirmatory-v3 same-backend matrix: 7/12 windows pass exact all-nine common support. XFeat-v3 has one attributable KLT window (APE -3.36%, RPE -7.20%, overlapping repeat ranges, p=1.0). SP+LG has seven active contrasts with 3 joint wins, 3 joint losses, and 1 mixed result; median APE/RPE changes are -0.069%/+0.257%. Evidence: papers/frontend_same_backend_confirmatory_v3/report.md.

Primary evidence authority for these boundaries: papers/final_claim_evidence.md and docs/RESEARCH_LOG.md.

## Known Problems

- Final proposed P took zero learned action on all 20 frozen P07 windows; confirmatory learned contribution is not established there.
- Learned replacement can delete future long-lived KLT births and destabilize scale.
- Direct transfer of the External-KLT temporal-collapse gate is rejected: it missed 2/2 known positives and opened on a known harmful window.
- q_i has a reliability meaning and backend interface, but general trajectory benefit is not established.
- Cross-dataset end-to-end superiority over strong KLT is not established.
- Unconditional learned-source expansion is rejected by confirmatory-v3: the tested SP+LG arm alternates between rescue and harm, including an A08 median regression and one divergent AFRL Cemetery replay.
- Geometry-maturity router v1 is safe but null: its global 10% birth-ratio and
  exact same-cell-victim requirements suppress A02 and AFRL Bus opportunity,
  so no backend continuation is authorized.
- Coverage-monotone router v2 passes its frontend safety/opportunity contract
  but fails backend no-harm. The frozen backend is complete: 42/42 replays,
  4/4 active common supports, and 2 WIN / 2 LOSS versus KLT. Eight additional
  learned arm-windows are exact-fallback ties, not independent replays. A02
  XFeat and SP+LG both regress from 0.141 m KLT APE to about 1.09--1.11 m.
  Route-D deletion-only attribution reproduced the harm (1.073 m APE, scale
  0.514) by removing only eight startup donor observations, so occupied-track
  donor replacement is rejected as no-harm. Ten of 14 learned lineages remain
  single-observation, none reaches four observations, and per-ID backend
  residual use remains Unknown.
- Positive-window donor-delete controls completed 6/6 new replays. A09
  deletion-only remains at the KLT divergent scale; Bus deletion-only has two
  divergent repeats. Both learned and matched-GFTT insertion recover the two
  windows. Insertion is therefore required relative to the registered deletion
  controls, but learned-source necessity remains unestablished.
- Many experiment generations coexist; the 2026-08-06 experiment_status.md is stale relative to the 2026-08-08 final claim map and September work.
- Proxy trajectories, fixed-scale metrics, and Sim(3) diagnostics require explicit labels.
- The repository has no declared open-source license.
- Large data/log/tool paths depend on external storage.

## Active Research Questions

- Does the unchanged VINS backend expose a real-time initialization-complete
  signal that could causally protect the startup prefix?
- Which causal frontend-only geometry signals identify action-positive cases without opening on harmful windows?
- Can learned-sidecar benefit be separated from dense-KLT/classical rescue?
- Can a multi-sequence, valid-common-support end-to-end learned contribution be demonstrated?
- Does calibrated q_i change backend trajectory quality at meaningful scale?

## Current Priorities

1. Honor the protected-prefill `NO_EXPANSION`; perform a read-only online-init
   interface audit before considering any separate post-init method.
2. Preserve exact KLT behavior when learned recovery is inactive.
3. Keep unconditional SP+LG expansion and the failed External-KLT direct-transfer result as negative evidence; any geometry-aware replacement is a new branch.
4. Include a matched classical-candidate control and freeze before new-window backend outcomes.
5. Require accepted learned-born lineage and valid common support before making learned-contribution claims.

## Recent Progress

- 2026-09-06: protected pre-refill slot `EXP-20260906-009` completed. All
  carried observations are exact and only age-1 GFTT births are omitted, but
  active results are 1 WIN/1 TIE/2 LOSS. A09 retains a strong XFeat positive;
  A02 still selects the wrong scale branch and Bus becomes an exact tie. Frozen
  decision is `NO_EXPANSION`.
- 2026-09-05: A09/Bus donor-delete-only controls completed 6/6 PASS. Deletion
  does not reproduce either meaningful win; insertion is required, but matched
  GFTT also works, so the evidence supports an observation/initialization
  intervention rather than learned-source necessity.
- 2026-09-05: completed all 42 frozen v2 backend replays. Active learned cells
  are 2 wins and 2 losses versus KLT; repeated A02 regressions reject v2 as a
  no-harm unified method.
- 2026-09-05: route-D A02 counterfactual removed only the eight registered
  donor observations and added nothing. Three replays and all-12 common support
  pass; APE/RPE worsens +659%/+349% and initialization occurs 0.785 s earlier,
  confirming donor deletion is sufficient for the tested scale failure.
- 2026-09-05: exact v2 bag diagnosis found 10/14 single-observation lineages,
  0/14 nonlinear-residual-eligible lineages by the locked >=4 rule, and only one
  actually missing donor observation per exchange (21 total), not deletion of
  later donor continuations.
- 2026-09-05: completed the preregistered geometry-maturity router v1
  export-only matrix (18/18 PASS). Seven safety checks pass, both opportunity
  checks fail, and the branch is classified `SAFE_NULL`; backend is Not
  evaluated.
- 2026-09-04: completed confirmatory-v3: 72/72 eligible backend replays, 7 exact common-support windows, XFeat-v3 attributable n=1, and SP+LG joint outcomes 3 win/3 loss/1 mixed. Unconditional source expansion was rejected.
- 2026-09-04: export-only action-frame audit found that grid gain alone does not separate rescue from harm; KLT maturity at action is a plausible but post-hoc routing signal.
- 2026-09-04: froze a 12-sequence same-backend confirmatory experiment for KLT, SP+LG, and XFeat churn-guard v3; execution notes record infrastructure recovery and an A04 archive-layout correction. Terminal results were not confirmed in this inspection.
- 2026-09-04: External-KLT gate-transfer quick probe returned NO-GO and stopped before VINS replay.
- 2026-09-04: initialized the standalone Git repository, added publication-safe ignore rules, and published the initial code/research-evidence snapshot to the public GitHub main branch.
- 2026-09-03: churn-guard v3 repaired a known harmful startup while retaining two historical positive feature bags on a locked n=4 development set; this remains development evidence.
- 2026-08-08: final claim-evidence map narrowed the submission story to exact fallback/no-harm, development-only selective rescue, a scoped XFeat initialization-failure result, and an M2 diagnostic negative-accuracy result.

## Next Experiments

- Do not tune a second prefill budget/order/timing variant. Audit whether the
  unchanged backend exposes a real-time initialization-complete state; if it
  does, separately preregister one causally post-init admission test. If it
  does not, stop this line rather than use outcome-known timing.
- Use A02/A09/AFRL Bus only as development opportunity controls and A08 plus
  AFRL Cemetery/H07 as mandatory harm/stability controls; require an untouched
  roster for any confirmation.
- Freeze the router before evaluating a new non-overlapping confirmation roster.
- For learned attribution, compare protected KLT, dense-KLT rescue, learned without LoFTR, and learned with LoFTR on action-positive low-texture windows.
- For no-harm, verify exact or near-exact KLT behavior and actual learned/LoFTR export counts on normal-texture windows.

## September 2026 delayed-intervention decision

`EXP-20260905-008` is complete with `NO_EXPANSION`. An exact KLT prefix through
selected frame 31 eliminates the tested A02 catastrophic regression, but A09
and Bus do not retain the required joint >=10% rescue. All 42 new replays,
12 exact KLT mappings, and seven common supports pass. Directional 6 WIN/1 MIXED
labels are mostly small and do not establish no-harm, learned necessity, or
superiority to KLT/modern learned frontends.

## September 2026 protected-prefill decision

`EXP-20260906-009` is complete with `NO_EXPANSION`. Its 18/18 frontend cells
preserve every carried observation and omit only same-frame age-1 GFTT births.
All 24 new and 18 identity-reused backend replays and all four common supports
pass. A09/XFeat retains a strong convergence event and beats matched GFTT under
fixed scale, but A02/XFeat and A02/SP+LG remain severe wrong-scale losses and
Bus is an exact tie. The 12-arm denominator is 1 WIN/9 TIE/2 LOSS/0 FAIL. This
invalidates mature-track protection as a sufficient no-harm rule and does not
support superiority over KLT or a modern learned frontend.

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
