# Experiment Log

This is the append-only index for formal experiments, benchmarks, ablations, parameter sweeps, frontend evaluations, and trajectory evaluations. Existing run-scale artifacts under logs/, experiments/, artifacts/, and papers/ remain authoritative; new entries here point to those artifacts rather than replacing them.

Rules:

- Never delete failed or negative experiments.
- Record measured values only. Use Not evaluated or Unknown for missing values.
- Record exact paths, configurations, commands, hashes, and validity gates whenever available.
- Treat a dataset sequence/window as the scientific unit unless a preregistration states otherwise. Technical replay repeats are not independent samples.
- Keep fixed-scale SE(3), Sim(3), proxy-reference, and ground-truth results explicitly distinguished.

## Entry template

## EXP-YYYYMMDD-001 — Experiment Name

### Objective

### Hypothesis

### Status and Scientific Role

Status:

Role: exploratory / development / confirmatory / ablation / diagnostic / negative result

### Code Version

Commit:

Branch:

Project Git status:

### Dataset

Dataset:

Sequence / window:

Input paths:

Reference / ground truth:

Sensors:

Environment:

### Configuration

Config files:

Overrides:

Random seeds:

Backend and binary/config hashes:

### Baseline

### Modification

### Commands and Artifacts

Command:

Run directory:

Primary metrics artifact:

Logs / receipts / manifests:

### Metrics

| Metric | Baseline | Proposed | Difference |
| ------ | -------: | -------: | ---------: |
| ATE / APE | Not evaluated | Not evaluated | Not evaluated |
| RPE | Not evaluated | Not evaluated | Not evaluated |
| Initialization / tracking success | Not evaluated | Not evaluated | Not evaluated |
| Lost tracking count | Not evaluated | Not evaluated | Not evaluated |
| Output coverage | Not evaluated | Not evaluated | Not evaluated |
| Runtime / FPS | Not evaluated | Not evaluated | Not evaluated |
| Feature count | Not evaluated | Not evaluated | Not evaluated |
| Inlier ratio | Not evaluated | Not evaluated | Not evaluated |
| Trajectory length | Not evaluated | Not evaluated | Not evaluated |

### Validity Checks

Input identity:

Run integrity:

Common support:

Metric validity:

### Results

### Observations

### Failed Attempts

### Interpretation

State what the evidence supports and what it does not support.

### Conclusion

### Follow-up

## EXP-20260905-005 — Frozen coverage-monotone-router-v2 backend completion

### Objective

Complete the preregistered same-backend comparison for all valid v2 inputs.

### Hypothesis

Sparse, coverage-monotone learned replacement may preserve KLT runability and
improve trajectories on opportunity windows without harming controls.

### Status and Scientific Role

Status: `COMPLETE_REJECT_NOHARM`

Role: outcome-known development evidence and negative no-harm result.

### Code Version

Commit: `f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` plus locked file hashes.

Branch: `main` at experiment time.

Project Git status: dirty; exact exporter/runner/config/backend identities are
recorded in the published locks.

### Dataset

Six development windows: AQUALOC A09/A02/A08, AFRL Bus/Cemetery, and Harbor
H07. Reference: COLMAP/proxy, not independent ground truth.

### Configuration

Feature cap 350; measurement selection disabled; every_n=2; frozen v2 donor
contract; one VINS-Fusion-origin backend YAML per window shared by all arms.

### Baseline

Fresh KLT feature bag.

### Modification

XFeat or SP+LG v2 replacement and same-ID/frame/dose matched GFTT controls.

### Commands and Artifacts

Published report: `papers/frontend_coverage_monotone_router_v2/backend_completion_report.md`.
Compact repeats and identities: `docs/research_sync/EXP-20260905-005_v2_backend/`.

### Metrics

Runability first; exact common support; proper fixed-scale SE(3) APE; strict
1 s translation RPE; Sim(3) scale as diagnostic; independent evo cross-check.

### Validity Checks

Input/config identity 17/17; repeat runability 42/42; active common support
4/4; evo maximum absolute discrepancy below 5e-7 m.

### Results

Active learned arm-windows: 2 WIN / 2 LOSS. Full 12 arm-window denominator:
2 WIN / 8 exact-fallback TIE / 2 LOSS / 0 FAIL. A09 and Bus improve; A02
XFeat and SP+LG regress severely. Runtime/FPS, lost tracking, and inlier ratio:
Not evaluated.

### Observations

Matched GFTT reproduces each KLT-relative direction, so candidate source is
not established as necessary. Repeats are stability checks, not samples.

### Failed Attempts

Earlier disk blocks and wrapper failures are preserved in the full local
record; no terminal result was discarded.

### Interpretation

V2 has safe frontend action supply but is not backend no-harm and does not
support general superiority over KLT or a modern learned frontend.

### Conclusion

Reject v2 as the unified method.

### Follow-up

Donor-delete-only attribution, initially on A02 and then on both positive
windows.

## EXP-20260905-007 — A09/Bus positive donor-delete attribution

### Date

2026-09-05

### Status and Scientific Role

`COMPLETE_INSERTION_REQUIRED`; outcome-known two-window mechanism diagnostic,
not held-out validation or a natural positive-rate estimate.

### Git Commit and Branch

Experiment base `f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` on `main`, plus
the published execution lock and script/file hashes; report publication uses a
later dedicated branch commit and is not the experiment-time source identity.

### Dataset and Sequence / Window

AQUALOC A09 frames 6000--6800 and AFRL Bus s180 d45; two physical development
windows, three new deletion-only replays each.

### Environment and Exact Configuration

ROS Noetic, unchanged VINS-Fusion-origin binaries, same canonical per-window
YAML/camera, KLT bag, proxy, time axis, 350 cap, evaluator, and repeat count as
v2. Execution identity 17/17 PASS.

### Baseline

B fresh KLT. Existing B-D+L XFeat and B-D+C matched-GFTT replays were reused
only under exact identity and recomputed common support.

### Proposed Modification

B-D removes only the preregistered three A09 or two Bus donor observations at
their exact timestamp/ID/camera; it inserts nothing and changes no other
message or observation.

### Commands and Artifact / Run Paths

Builders/runners/analyzer are `scripts/build_frontend_v2_positive_delete_controls.py`,
`scripts/run_frontend_v2_positive_delete_backend.py`, and
`scripts/analyze_frontend_v2_positive_delete_backend.py`. Primary compact
artifacts are under `papers/frontend_v2_positive_delete_diagnostic/`; run-scale
artifacts remain in the offload root listed by the manifest.

### Metrics

Structural input identity, initialization and coverage, all-12 common support,
proper fixed-scale SE(3) APE, strict 1 s RPE, diagnostic Sim(3), and repeat
range.

### Results

Six of six new replays PASS; both all-12 supports PASS. A09 B versus B-D APE /
RPE is 1242.140002/150.846817 versus 1242.135147/150.843919 m, while B-D+L
and B-D+C converge at 0.732414/0.073563 and 1.082355/0.116941 m. Bus B versus
B-D is 0.060301/0.037071 versus median 53.052375/6.980129 m; B-D+L and B-D+C
are 0.042258/0.026681 and 0.044229/0.026862 m. Runtime/FPS, inlier ratio, and
lost tracking count are Not evaluated.

### Validity Checks and Common-Support Status

A09: 38 common poses, 37 s, 95% coverage, 37 RPE pairs. Bus: 41 poses, 40 s,
91.11% coverage, 40 RPE pairs. An interrupted unreceipted Bus repeat was
quarantined and rerun; completed receipts are 6/6.

### Interpretation

Deletion-only does not reproduce either meaningful win. Candidate insertion is
required for both registered positive outcomes, but matched GFTT is also
effective, so learned necessity is unproven.

### Conclusion

Proceed only to one startup-protected intervention version; do not claim
learned persistent anchors or expand v2.

### Follow-up

Preregister the six-window delayed newborn-slot version and its newly matched
classical control; expand to 12 new windows only if the frozen development gate
passes.

## EXP-20260905-006 — A02 donor-delete-only route-D attribution

### Objective

Test whether the eight registered A02/XFeat donor deletions are sufficient for
the observed initialization/scale failure without adding any candidate.

### Hypothesis

If KLT minus only those observations reproduces the failure, occupied-track
deletion is sufficient for the tested harm.

### Status and Scientific Role

Status: `DELETE_SUFFICIENT`

Role: one-window, outcome-known mechanism diagnostic.

### Code Version

Commit: experiment base `f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` plus
the route-D execution lock; backend node/library hashes are published.

### Dataset

AQUALOC Archaeology A02 frames [0,900); COLMAP/proxy reference.

### Configuration

Same frozen A02 backend/config/evaluator as v2; three serial new replays.

### Baseline

Fresh KLT, with existing v2 XFeat and matched-GFTT trajectories reused only
under exact identity and recomputed four-arm common support.

### Modification

Delete exactly eight registered donor observations on three feature frames;
insert zero candidates and preserve all other messages/observations.

### Commands and Artifacts

Published report and protocol:
`papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/`.

### Metrics

Initialization, coverage, fixed-SE(3) APE, 1 s RPE, diagnostic Sim(3), and
four-arm exact common support.

### Validity Checks

Execution identity 15/15; 3/3 new replay PASS; 42 common poses, 41 s,
93.33% coverage, and 41 RPE pairs.

### Results

KLT APE/RPE 0.141317/0.022697 m; deletion-only 1.073158/0.102008 m
(+659.4%/+349.4%). Sim(3) scale falls 0.898634 to 0.513513 and accepted
initialization occurs 0.785 s earlier. Runtime/FPS, inlier ratio, and lost
tracking count: Not evaluated.

### Observations

Deletion-only closely follows learned/matched failure. This demonstrates
sufficiency for this registered deletion set, not candidate irrelevance,
necessity, single-donor causality, or population prevalence.

### Failed Attempts

The first wrapper checked the wrong scratch output after a successful replay;
the run was preserved and recovered by identity without replay.

### Interpretation

Startup donor deletion is sufficient for the tested A02 failure; the detailed
backend causal chain remains Hypothesis / Inference.

### Conclusion

Occupied-track replacement cannot be called no-harm.

### Follow-up

Run predeclared A09 and Bus donor-delete-only controls before choosing one
repair.

## EXP-20260905-008 — Delayed newborn-slot router v3

### Date

2026-09-06

### Status and Scientific Role

`COMPLETE_NO_EXPANSION`; outcome-known six-window development test, not held-out.

### Git Commit and Branch

Experiment base `f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` on `main` plus
the exact locks/amendments. The publication commit is reporting identity only.

### Dataset and Sequence / Window

A09 6000--6800, A02 0--900, A08 2700--3600, H07 0--1000, AFRL Bus s180 d45,
and Cemetery s135 d45: six windows, 12 learned arm-windows, seven active.

### Environment and Exact Configuration

ROS Noetic, unchanged VINS-Fusion-origin, per-window YAML/camera, IMU/time axis,
proxy, every-n 2, and cap 350. Profile `lineage_delayed_newborn_slot_v3` keeps
frames 0--31 exact KLT and permits unchanged exchange only on 32--36.

### Baseline

Fresh KLT, reused only under exact bag/config/binary/receipt identity.

### Proposed Modification

Move only the v2 action interval from 0--4 to 32--36.

### Commands and Artifact / Run Paths

See v3-named scripts and `papers/frontend_delayed_newborn_slot_v3/`;
`artifacts.sha256` uses stable symbolic roots for run-scale artifacts.

### Metrics

Initialization, coverage, all-nine support, fixed-SE(3) APE, strict 1 s RPE,
diagnostic Sim(3), repeat median/range, and evo cross-check.

### Results

Frontend 18/18, matched 7/7, backend 54/54, and common support 7/7 PASS.
Active outcomes: 6 WIN/1 MIXED/0 LOSS/0 FAIL; five exact TIE mappings complete
the 12-arm denominator. A02 returns within 1.2% of KLT; A09 remains divergent;
Bus has no joint >=10% rescue.

### Validity Checks and Common-Support Status

Supports contain 38--43 poses, 37--42 s, and 93.33%--95.56% coverage; max evo
difference is 4.997e-7 m. Nine unreceipted wrapper attempts are quarantined.

### Interpretation

Delay removes tested A02 harm but also the meaningful A09 rescue. Matched GFTT
remains competitive; learned necessity is Unknown.

### Conclusion

`NO_EXPANSION`; the joint >=10% A09/Bus rescue criterion is false.

### Follow-up

Do not try a second horizon or start the 12-window extension in this protocol.

## EXP-20260906-009 — Protected pre-refill slot admission v1

### Date

2026-09-06

### Status and Scientific Role

`COMPLETE_NO_EXPANSION`; outcome-known six-window mechanism-development test,
not held-out validation.

### Git Commit and Branch

Experiment base `f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` on `main`, plus
the exact method/backend locks. Publication commit is reporting identity.

### Dataset and Sequence / Window

AQUALOC A09 6000--6800, A02 0--900, A08 2700--3600, Harbor H07 0--1000,
AFRL Bus s180 d45, and AFRL Cemetery s135 d45: six windows and 12 learned arms.

### Environment and Exact Configuration

ROS Noetic, unchanged `VINS-Fusion-origin`, same YAML/camera/proxy, IMU/time
bounds, every-n 2, cap 350, and `lineage_protected_prefill_slot_v1`. Exact
hashes are in the locks and `artifacts.sha256`.

### Baseline

Fresh KLT; backend results reused only under exact identity.

### Proposed Modification

Preserve every carried observation and admit candidates only at the expense of
same-frame age-1 GFTT births; candidate gates, timing, and budgets are unchanged.

### Commands and Artifact / Run Paths

Scripts named `frontend_protected_prefill_slot_v1`; compact evidence under
`papers/frontend_protected_prefill_slot_v1/`; run paths use manifest aliases.

### Metrics

Frontend safety, runability, all-nine support, fixed-scale SE(3) APE, strict 1 s
RPE, diagnostic Sim(3), repeat median/range, and evo.

### Results

18/18 frontend, 4/4 matched controls, 24/24 new backend, 18/18 reused KLT, and
4/4 supports PASS. Active results are 1 WIN/1 TIE/2 LOSS/0 FAIL; full results
are 1 WIN/9 TIE/2 LOSS/0 FAIL. A09 XFeat improves fixed APE/RPE from
1242.140/150.847 to 0.733/0.0736 m and beats matched by 32.31%/37.10%. A02
XFeat/SP+LG worsen APE by 674.27%/699.46% and RPE by 361.03%/359.66%. Bus is
an exact tie. Runtime/FPS and lost tracking count are Not evaluated.

### Validity Checks and Common-Support Status

All structural/config/common-support audits pass; evo discrepancy is below
`5e-7` m. One interrupted unreceipted directory is quarantined and excluded.

### Interpretation

Startup newborn identity can flip scale even when all carried tracks are exact.
One A09 positive does not offset two A02 losses or prove general superiority.

### Conclusion

`NO_EXPANSION`; no-regression-over-10% and win-dominance gates fail.

### Follow-up

No second budget/order/timing variant. First audit for a causal online
initialization-complete interface.

## EXP-20260906-010 — VINS initialization-state interface audit

### Date

2026-09-06

### Status and Scientific Role

`COMPLETE_READ_ONLY`; causal-feasibility audit, not a trajectory benchmark.

### Git Commit and Branch

Unchanged external VINS source; exact source/binary hashes are in the report.
The AQUA-FE publication commit is reporting identity only.

### Dataset and Sequence / Window

No new run. Existing A09, A02, and AFRL Bus repeat-1 artifacts were used only
for code-path corroboration.

### Environment and Exact Configuration

ROS Noetic and the locked node/library from EXP-20260906-009; no YAML, bag,
gate, backend, or evaluator changed.

### Baseline

Locked VINS behavior and current offline AQUA-FE exporter.

### Proposed Modification

None; read-only interface audit.

### Commands and Artifact / Run Paths

Source inspection in the locked VINS workspace; compact results in
`papers/frontend_init_state_interface_audit/`.

### Metrics

Signal existence, semantics, ordering, namespace, reset behavior, and causal
consumability.

### Results

No explicit status exists. First `/vins_estimator/odometry` is an implicit
post-init edge. Existing buffered header lags are 0.145338--0.442001 s.

### Validity Checks and Common-Support Status

Not applicable: no new replay or APE/RPE comparison. Source and binary hashes
were recorded; backend remained unchanged.

### Interpretation

The edge exists, but the offline exporter cannot consume it and it occurs after
the target initialization decision.

### Conclusion

`DO_NOT_IMPLEMENT_POST_INIT_VARIANT`; delayed-v3 already failed the post-init
expansion gate and lost A09 rescue.

### Follow-up

Stop the replacement/admission line rather than tune another slot or horizon.

## EXP-20260906-011 — Frozen v2 budget and continuation characterization

- Date: 2026-09-06.
- Status / scientific role: COMPLETE_READ_ONLY; post-hoc accounting diagnosis and synthetic source-behavior tests, not a new method or held-out evaluation.
- Git / branch: original run base f6f8feec66c2faf1f59cdb67c1e817028a3bccaf on main plus method_lock_recovery1.json; exact v2 exporter later archived at 3c50b742d6e0c69796a69813e42823e9895ed684 (SHA bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d). Publication branch codex/aqua-fe-evidence-20260905 is not the runtime source identity.
- Dataset/window: every v2 active cell: A09 6000–6800/XFeat, A02 0–900/XFeat and SP+LG, AFRL Bus s180 d45/XFeat; all 14 published lineages.
- Environment/configuration: local ROS Noetic, system Python, frozen exporter loaded from a verified Git object; no runtime configuration changes. Synthetic gate isolation is not a dataset configuration.
- Baseline: original lineage_diagnostic.csv and v2 metrics/receipts.
- Proposed modification: executable reproduction of the partial-budget distinction already documented in the September 5 publication-only lineage_budget_audit; no frontend algorithm modification. The prior two audit files were restored to the main workspace unchanged.
- Commands/artifacts: audit_frontend_v2_budget_continuation.py --paper papers/frontend_coverage_monotone_router_v2 --output papers/frontend_coverage_monotone_router_v2/budget_continuation_audit_20260906.csv; ROS-sourced /usr/bin/python3 -m unittest discover -s tests -p test_v2_budget_continuation_characterization.py -v; see budget_continuation_addendum.md.
- Metrics/results: 4/4 original metrics hashes verified, 46 compact rows, 5/5 tests PASS after correcting three initial fixture-construction errors. Ten singletons: five next-output partial budget cases, three budget-tag/no-prefinal cases, two no-pregate cases; exact per-ID causes Unknown.
- Validity/common support: no new APE/RPE calculation; common support not applicable to this diagnostic. All earlier repeats, failures, gates, original CSVs and decisions remain unchanged.
- Interpretation: A09 stops with 47/50 reservations unused; v2 publication continuation also depends on donor availability and final horizon. Refunding reservations alone is not evidence of a useful persistent constraint.
- Conclusion: current NO_EXPANSION retained; new strategy effectiveness Not evaluated.
- Follow-up: no more automatic slot/order/timing variants; separately scope any future admission/continuation strategy before implementation.

## EXP-20260906-012 — Admission/continuation separation v1

- Date: 2026-09-07; preregistration September 6, source freeze 2026-09-07T00:01:03.672243+08:00.
- Status / scientific role: PARTIAL / FRONTEND_PROBE_RUNNING; user-authorized development experiment, not held out.
- Git / branch: main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf plus method_lock.json; frozen v2 exporter Git object 3c50b742d6e0c69796a69813e42823e9895ed684, SHA bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d. Reporting branch differs from runtime identity.
- Dataset / windows: fixed A09 6000–6800, A02 0–900, Bus s180 d45, A08 2700–3600, Cemetery s135 d45, H07 0–1000; KLT/XFeat/SP+LG, 18 frontend cells.
- Environment / configuration: ROS Noetic, current locked v2 source/dependencies, original lineage_early_seed_coverage_monotone_v2, every_n=2, 350 total / six sidecars, original first-admission horizon and reservation cap retained.
- Baseline: fresh same-contract KLT; only identity-valid v2 backend reuse. Proposed: published-ID lifecycle continuation, current-valid observations and newborn-slot opportunity cost; actual final publication capped at 50.
- Commands / artifacts: ROS-sourced /usr/bin/python3 scripts/run_frontend_admission_continuation_v1.py --probe-pair; source-frozen artifacts in papers/frontend_admission_continuation_v1 and runtime at /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_admission_continuation_v1.
- Metrics / results: 8/8 synthetic tests PASS; A09 KLT complete with 400 frames / 99.7506% coverage / max350, XFeat running. New matched and backend results Not evaluated.
- Validity / common support: full bag safety audit pending. Backend contract unchanged: all-nine common support, 30 poses / 10 s / 70%, strict 1 s RPE, fixed-scale proper SE(3) primary, Sim(3) diagnostic and evo. Proxy is not independent GT.
- Interpretation / conclusion: no new WIN or safety-effectiveness claim. Prior negative results remain unchanged; current progress is one valid frontend receipt, not a completed matrix.
- Follow-up: finish the probe and matrix, new matched controls, all active three-repeat backend cells; apply frozen stop/expansion criteria without retuning.

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

### EXP-20260906-012 — Interrupted-execution recovery checkpoint

- Date / status: 2026-09-07 afternoon; PARTIAL / FRONTEND_RUNNING.
- Scientific role / identity: continuation of the same six-window development experiment, not new samples. Runtime main base f6f8feec66c2faf1f59cdb67c1e817028a3bccaf plus the original method lock; published source snapshot 16aad555a1ab617a2aed7260126243111be0a4a0 is not a replacement runtime commit.
- Dataset / baseline / modification: unchanged registered six windows, fresh KLT versus the sole published-ID continuation policy; no experimental parameter change.
- Environment / commands: ROS Noetic environment forwarded to user systemd unit aquafe-exp012-bounded-20260907.service; /usr/bin/python3 -u scripts/run_aquafe_v2_bounded_continuation.py. Original stage scripts and release identities are checked before execution.
- Artifacts: continuation_runtime:bounded_execution/{release_lock.json,progress.json,frontend.log,controller_service.log}; two incomplete frontend attempts preserved under continuation_runtime:quarantine/.
- Results at 15:51: four valid frontend receipts; A09 SP+LG feature SHA equals KLT, A02 KLT passes; 0 new VINS replays. Failed infrastructure attempts remain visible; they are not successful repeats or additional physical windows.
- Validity / common support: full frontend structural audit and all-nine backend common support pending; no current APE/RPE comparison. Fixed denominator 18 frontend cells / 12 learned arm-windows / six physical windows.
- Interpretation / conclusion: the restart changes process lifetime management only. New-method backend effectiveness is Not evaluated.
- Follow-up: finish the frozen matrix and permitted stages, retaining every failure and applying the original stopping criteria.

### EXP-20260906-012 — Complete admission/continuation development result

- Date / status / role: 2026-09-07; COMPLETE / NO_EXPANSION; outcome-known six-window development study.
- Git identity: runtime main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf plus method-lock file hashes; v2 exporter archived at 3c50b742d6e0c69796a69813e42823e9895ed684. Report publication is a separate commit on codex/aqua-fe-evidence-20260905.
- Dataset/windows: A09 6000–6800, A02 0–900, Bus s180 d45, A08 2700–3600, Cemetery s135 d45, H07 0–1000; no added/replaced window.
- Environment/config/baseline: fixed VINS-Fusion-origin, original YAML/camera/node/library, 350 total / six sidecars per frame / 50 actual learned observations, every_n=2. Fresh KLT bags exactly match reused v2 KLT inputs; all 42 environment audits pass. Proxy, not independent GT.
- Modification: only already-public IDs may continue on current valid observations without first-admission horizon/microburst/reservation checks. All mirror-carried classical observations protected; newborn opportunity cost remains.
- Commands/artifacts: scripts/run_aquafe_v2_bounded_continuation.py invokes frozen stages; scripts/analyze_admission_continuation_v1_{lineages,environment,v2_comparison}.py and build_admission_continuation_v1_manifest.py reduce evidence. papers/frontend_admission_continuation_v1/; continuation_runtime: under Data storage offload; actual bags/vio/log/receipt paths are in the published tables and manifest.
- Results: 18/18 frontend PASS; 4/4 new matched controls PASS; 24/24 new VINS replays completed, 18 KLT reused; 42/42 init+coverage PASS. Full learned denominator 2 WIN / 8 TIE / 2 LOSS / 0 MIXED / 0 FAIL, active 2 WIN / 2 LOSS. No new physical positive window; no new-window validation.
- Metrics: A09 learned fixed APE/RPE 0.641290/0.061445 m versus KLT 1242.140/150.847 and matched 1.653014/0.166323. A02 XFeat 0.979235/0.091623 and SP+LG 0.996579/0.092403 versus KLT 0.141317/0.022697. Bus learned median 0.042794/0.026725, same bag as old v2, APE range 0.042794–0.065287. Full ranges/Sim(3) in accuracy.csv.
- Frontend diagnostics: 11 lineages / 33 observations, four singletons; eight capacity terminations, one quality rejection, two absent pre-online stage. A02 donor 377 baseline105/current104, missing frame4 only. Future lifetime never used online.
- Validity: 4/4 all-nine common supports, 38–42 poses / 37–41 s / 93.33%–95% / strict 1 s RPE; evo delta <5e-7 m. Same-grid v2/current/KLT comparison also 4/4 PASS. No parameter/gate/backend change.
- Interpretation: A09 fixed-scale versus v2 improves 12.44%/16.47%, while Sim(3) errors increase; A02 improves about 10% relative to v2 but retains severe KLT regression. Learned is not proven necessary; matched also improves the positive-window baseline.
- Conclusion/follow-up: frozen NO_EXPANSION; stop this single policy experiment, preserve negative/partial history and publish. No additional parameter variant or twelve-window extension.

## EXP-20260907-ADDITIVE-BUDGET-V1 — A09 结构探针检查点
- Date: 2026-09-07。
- Status and scientific role: A09四臂FRONTEND_COMPLETE；后端WAITING_RESOURCE；独立已知结果开发窗数量机制实验。
- Git commit and branch: source合同 d1c793a8d56b3f8efe2ed3b3d770b706e692dbdc，运行中发布2297bb8；exp/additive-budget-v1-20260907。精确运行模块哈希见source_and_backend_lock.json。
- Dataset and sequence/window: A09 6000–6800；windows.csv原帧偏移1/every_n2，输入801图像，400输出时刻。
- Environment and exact configuration: Python aquafe_cuda；XFeat2048/.82、GFTT1024；seed60/pool800；adaptive_clahe；锁文件及输入相机哈希完整。
- Baseline: 原KLT最多350，已审计bag SHA6de8ffe9…884ff只读复用。
- Proposed modification: L6/L-all共享一次源流、C-all独立传统源；完整KLT只加不删，无50次/短时替换窗口。
- Commands and artifacts: scripts/run_additive_budget_v1.py --window a09_6000_6800；scripts/audit_additive_budget_capacity.py同窗；runtime `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1/frontend/a09_6000_6800/receipt.json`；公开 frontend_audit.csv/candidate_lifecycle.csv/capacity/a09_6000_6800.json。
- Metrics: 追加观测、并发、公开寿命、编码/主干一致性、容量上界；APE/RPE、初始化和后端运行成本 Not evaluated。
- Results: L6=2251次/253ID/最长96次，346帧触顶；L-all=42018次/2555ID/最长192次，337帧>6，最多262并发；C-all=22392次/1474ID/最长188次，最多152并发。
- Validity checks and common support: 三添加臂全部KLT序列化重建、非feature一致、L6源ID/时间子集通过；四臂公开ID无断续复用。连续11帧>=4次ID最多B377/L6384/L-all638/C-all522；不是实际后端使用量。共同支撑 Not evaluated。
- Interpretation: Confirmed fact: A09剂量对照充分。Hypothesis / Inference: 更多有效后端约束是否改善仍未知。
- Conclusion: 尚不能回答净收益，未晋升主方法。
- Follow-up: 其余五窗源流正在顺序执行；后端等待外部VINS任务释放资源，不终止其他任务。

## EXP-20260907-ADDITIVE-BUDGET-V1 — A09后端完成
- Date: 2026-09-07。Status/scientific role: A09 12/12新回放完成，固定development局部结果；整个矩阵未完成。
- Git/branch: 诊断后端2297bb8合同，源流d1c793a文件哈希；exp/additive-budget-v1-20260907。
- Dataset/window/environment/configuration: 同锁A09 6000–6800，B/L6/L-all/C-all，max_solver_time=.04/8iter，固定端口12671，后端CPU2,3,8,9；自身前端在不同物理核。
- Baseline/modification: 完整共享KLT；公开并发6/all和传统all。
- Commands/artifacts: run_additive_budget_backend.py四臂三重复；evaluate_additive_budget_v1.py；runtime backend/a09_6000_6800/*/repeat*/receipt.json；paper checkpoint_a09.md/common_support/a09_6000_6800/。
- Metrics/results: APE/RPE中位B1242.139997/150.846816、L61415.067546/171.484729、L-all1451.201568/175.767799、C-all1242.363832/150.846781 m。完整范围见共同支撑CSV。
- Validity/common support: 12个接收完整、388poses、覆盖96.75%；38共同poses/37秒/95%/37RPE对；evo通过。未触发1000容量保护；有轨迹与初始化日志不代表定位可靠。
- Interpretation/conclusion: 剂量对照充分但A09未获净收益；L-all vs L6双升而未达实用变化门，两学习添加臂对B实用退化。所有臂严重尺度漂移；不把尺度对齐诊断替代fixed-scale主结果。
- Follow-up: 保留负例，继续固定其余五窗；不扩窗、不调参。
