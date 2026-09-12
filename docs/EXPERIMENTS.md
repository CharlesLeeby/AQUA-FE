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


## additive_budget_v1_A02_complete — 2026-09-07
- Status and scientific role: COMPLETE，该开发窗24臂窗矩阵的一部分；非独立测试集。
- Git commit / branch: 冻结源实现d1c793a，执行锁2297bb8；当前报告基于d1ddd0f / exp/additive-budget-v1-20260907。
- Dataset/window: windows.csv中A02 0–900原输入与every_n/frame_offset。
- Environment/config: source_and_backend_lock.json、backend_execution_lock_v2.json；同一诊断二进制、容量1000、原solver预算、CPU2,3,8,9。
- Baseline/proposed: 完整共享B，额外L6/L-all/C-all；三技术重复。
- Commands/artifacts: scripts/execute_additive_budget_matrix.py --start-window a02_0_900；运行根frontend_additive_budget_v1/backend/a02_0_900；checkpoint_a02.md、backend_results.csv、comparisons.csv、common_support/a02_0_900/。
- Metrics/results: L-all/L6 APE0.9945315745/0.9446784214m，RPE0.09277713305/0.08783911084m，SMALL_OR_UNCERTAIN；L6/B、L-all/B实用退化；C-all/B实用改善；L-all/C-all实用退化。
- Validity/common support: 全12接收完整、初始化/覆盖通过；各对比6轨迹和四臂12轨迹支撑通过，evo通过。不同支撑数值不混用。
- Interpretation/conclusion: 发布和实际残差差异充分，当前学习数量收益未获支持；C-all结果不能外推等资源来源优越性。
- Follow-up: 仅继续原矩阵。ATE单独口径、lost tracking真实事件、精确solver停止原因Not evaluated./Unknown；详列字段不臆造。


## additive_budget_v1_Cemetery_source_attempt1 — 2026-09-08
- Status/scientific role: INVALID_SOURCE_ALIGNMENT；结构失败尝试，非精度证据。
- Git commit/branch: 冻结源d1c793a，当前21ddfa3 / exp/additive-budget-v1-20260907。
- Dataset/window/config: AFRL Cemetery s135 d45，原windows.csv every_n2/frame_offset0、同B与输入SHA，source_and_backend_lock.json。
- Baseline/modification: 原B；同冻结XFeat/GFTT私有流，尚未得到有效添加bag。
- Commands/artifacts: run_additive_budget_v1.py --window afrl_cemetery_s135_d045；原console保留；quarantine/afrl_cemetery_s135_d045_source_attempt1；cemetery_invalid_attempt.json。
- Metrics/results: 713raw图像、357B、358源记录、1重复时间戳对且像素不同；合并身份门拒绝；后端0次。
- Validity/common support: INVALID_SOURCE_ALIGNMENT；APE/RPE、初始化、覆盖、残差Not evaluated.；未进入任何精度分母筛选。
- Interpretation/conclusion: raw191非冻结输出帧，必须按既定帧索引关联；不是资源或算法效果失败。
- Follow-up: cemetery_recovery_lock.json锁定一行关联overlay；保留无效源并重新生成一次正式共同流，明确额外计算与一次生成规则偏差，不改方法参数。


## additive_budget_v1_frontend24_and_backend60 — 2026-09-08
- Status/scientific role: 前端24/24结构验收完成，五个开发窗60/72后端完成，非最终矩阵。
- Git/branch: 源d1c793a、诊断执行2297bb8、Cemetery恢复38e5881；exp/additive-budget-v1-20260907。
- Dataset/config: 原windows.csv六窗、source_and_backend_lock.json及backend_execution_lock_v2.json；Cemetery仅frame-index overlay。
- Baseline/modification: 同原B加L6/L-all/C-all；完整四臂×3。
- Commands/artifacts: audit_additive_budget_delivery.py、summarize_additive_budget_sources.py、analyze_additive_budget_v1.py；独立runtime；delivery_readback_audit.csv、source_generation_attempts.csv、各checkpoint/common_support/。
- Metrics/results: 全24原B/非feature/源坐标q/速度读回通过；六窗剂量门通过。A08 L-all/L6实用改善但L-all/B实用退化；H07五对比均不确定；Bus异常首重复保留。量化与逐次范围见CSV。
- Validity/common support: 五窗六类支撑各PASS并经evo核对；技术3不作独立样本。Cemetery后端Not evaluated.。
- Interpretation/conclusion: 量对照确实形成；当前局部相对L6改善不能解释为对B稳定净收益。
- Follow-up: 仅完成Cemetery原12次；不新增预算/窗口/补最好重复。


## additive_budget_v1_final_matrix — 2026-09-08
- Status/scientific role: COMPLETE；六个已知结果开发窗的固定添加式数量对照，非held-out结论。
- Git commit/branch: 源d1c793a8d56b3f8efe2ed3b3d770b706e692dbdc；后端/评估2297bb837dac69ff587ec052425539cdd01a17dc；Cemetery恢复38e58813f82495e2e8c60a173b55610d401b1c77；exp/additive-budget-v1-20260907。报告发布commit另见该条所属发布版本。
- Dataset/sequence/window: A09 6000–6800、A02 0–900、Bus s180 d45、A08 2700–3600、Cemetery s135 d45、H07 0–1000；准确输入/stride/校准/IMU见原windows.csv和source锁，不由名称换算时间。
- Environment/exact config: environment_audit.json/resource_execution_schedule.json/source_and_backend_lock.json/backend_execution_lock_v2.json/evaluation_lock.json；后端同一二进制，容量1000、原solver合同，正式播放rate1，CPU2,3,8,9。非排他宿主限制另列。
- Baseline/proposed: 同一原KLT B加L6/L-all/C-all；L6/L-all同一正式XFeat流；六窗四臂各3技术重复。
- Commands/artifacts: run_additive_budget_v1.py、Cemetery恢复overlay、execute_additive_budget_matrix.py、analyze_additive_budget_v1.py、audit_additive_budget_delivery.py、report_additive_budget_v1.py；运行根/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1；backend_receipts.json保存逐次命令、配置/输入/日志哈希；report.md、comparisons.csv、backend_results.csv为主结果。
- Metrics/results: fixed-scale proper SE3 APE RMSE、严格1s全局对齐位置增量RPE；72初始化事件均1、reset/failure检测代理0、72接收完整，coverage/轨迹长度/资格/残差/solver/RSS逐次列出。L-all/L6=1/0/5、L6/B=0/3/3、L-all/B=0/3/3、C-all/B=2/0/4、L-all/C-all=0/3/3（改善/退化/不确定）。最大资格834，发布倍率1.92778–48.6853，残差中位倍率1.44839–45.9306。
- Validity/common support: 24输入结构/身份、72运行/逐ID接收、36组共同支撑/evo、全部锁和30窗口输入配置哈希通过。每项两臂6轨迹支撑与主表四臂12轨迹支撑不混用。
- Interpretation: 更多剂量成立，只有A08数量比较有实用改善且仍差于B；Bus L-all异常23.252566m重复保留。C-all正例仅整体方案证据，来源q/数量/成本不等。
- Conclusion: 本六窗不支持L-all相对完整KLT有实用净收益；不宣称增加学习候选永远无用，也不推总体正例率。
- Failed/negative records: Cemetery首源无效保留并重建，共7源尝试、6正式共同流；0额外正式回放；WAITING_RESOURCE单列，不剔除负结果。
- Follow-up: 对保存日志做一次初始化/尺度失稳归因审计；不自动新扫窗、改预算或时机。独立ATE口径、精确lost-tracking事件、GPU峰值和初始化SfM耗时Not evaluated./Unknown。

## EXP-20260908-CLASSICAL-OPPORTUNITY-V1 — Batch A activated

- Date: 2026-09-08; status IN_PROGRESS; scientific role: frozen classical additive control opportunity expansion.
- Git: exp/classical-opportunity-expansion-v1-20260908; roster 881dad7; source/execution 8f323ba; base 49c0247.
- Dataset/window: A01/A03/A04/A05/A06/A07/A10/H01/H02/H03/H04/H05; each Batch A [0,900), Batch B [900,1800), actual times in frozen roster. Sequence-held-out only relative to six C-all development windows; broader historical exposure possible.
- Environment/configuration: ROS Noetic, aquafe_cuda Python, frozen B archived exporter and additive PrivatePool/ClassicalGfttMatcher/Publisher; old A02/H07 family camera/backend snapshots; guarded binary e231871e...68aadd, capacity1000, solver .04s/8, loop_closure0, multiple_thread0, ROS12691.
- Baseline: fresh complete KLT B. Modification: exact C-all adds candidates, removes no KLT; no learned arm or changed detector/gate/q/backend.
- Commands/artifacts: `scripts/run_classical_opportunity_expansion.py --window coe1_a01_00000_00900 --frontend`; `scripts/execute_classical_opportunity_batch.py --batch A`; runtime `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1`; paper tables in corresponding papers directory. Exact commands retained in receipts/controller logs.
- Metrics: fixed-scale proper SE(3) APE RMSE, strict 1s translational RPE guardrail, min/median/max of three technical repeats; initialization/coverage, fitted scale diagnostic, feature counts, lifetimes, actual per-ID receipt/residual/capacity/runtime, reset/lost proxies.
- Results: Not evaluated. Formal replay count at entry creation 0; planned Batch A72 and conditional Batch B72.
- Validity/common support: source/metric identities locked; per-message B reconstruction, raw-frame association, per-ID encoding/delivery and capacity audit required before replay; six-trajectory comparison support >=30 poses, >=10s, >=70% coverage, >=10 RPE pairs, evo check. New common support Not evaluated.
- Interpretation/conclusion: prospective fixed-C case pool only; no effectiveness/population positive-rate conclusion.
- Follow-up: resolve all Batch A windows, commit/push/readback checkpoint, then exact conditional Batch B. No replacement windows or repeated scientific attempts.

## EXP-20260908-CLASSICAL-SOURCE-EQUIVALENCE — COMPLETE / structural probe

- Date: 2026-09-08; branch exp/classical-opportunity-expansion-v1-20260908 at 964db5b; source base49c0247.
- Dataset/window: old development A02 input first40 raw frames, 20 output records; not counted as a new opportunity window.
- Environment/configuration: aquafe_cuda Python, ROS Noetic, OpenCV threads1, NumPy seed0, fixed CPU0,6, unchanged ClassicalGfttMatcher/PrivatePool, same camera and B messages.
- Baseline: saved additive-budget dual-source C JSONL, SHA256934a7cc7...ef888. Proposed modification: execute only its classical private pool; no candidate/gate/q changes.
- Commands/artifacts: exact bounded Python orchestration recorded in session; result/provenance papers/frontend_classical_opportunity_expansion_v1/classical_source_equivalence_probe.json; old input/source paths in receipt.
- Metrics/results: full JSON-record equality20/20, candidate observations822; observed wall26.726 s, not an isolated timing comparison.
- Validity/common support: exact dictionary equality; backend common support/APE/RPE Not evaluated. Backend replay count0.
- Interpretation/conclusion: bounded execution equivalence PASS, not effectiveness evidence or a new outcome sample.
- Follow-up: continue registered new-window source/receipt gates and Batch A backend matrix.

## EXP-20260908-CLASSICAL-OPPORTUNITY-V1 / A01 — COMPLETE window, Batch A IN_PROGRESS

- Date: 2026-09-08; role: new frozen classical-control case; git branch exp/classical-opportunity-expansion-v1-20260908, source49c0247/execution8f323ba/compatibilityd162b73.
- Dataset/window: AQUALOC archaeologyA01 CSV image[0,900), measured44.942442912s; updated COLMAP proxy. Exact timestamps/input hashes in frozen roster and runtime preparation receipt.
- Environment/configuration: frozen B/C pipeline, existing guarded binary e231871e...68aadd, old A02-family config/camera unchanged, ROS12691, .04s/8 solver, cap1000; frontendCPU0,6 and backend2,3,8,9; fresh B and six new repeats.
- Baseline/modification: full KLT B vs exact additive C-all; no removals or q/backend changes.
- Commands/artifacts: run_classical_opportunity_expansion.py --window coe1_a01_00000_00900 --arm B|C-all --repeat1|2|3; full argv in each receipt under runtime/backend/coe1_a01_00000_00900. Tables and own-six common-support artifacts in papers/frontend_classical_opportunity_expansion_v1.
- Metrics/results: B/C APE medians0.155036765/0.554980933m; RPE0.020657359/0.070126905m; APE+257.9673%,RPE+239.4766%, both exceed frozen severe/noise margins. Full ranges are in case_registry.csv. PRACTICAL_LOSS/SEVERE_REGRESSION.
- Validity/common support: all6 runabilityPASS and exact per-ID receipts; 36 common poses,35s,coverage81.818%,35strict1sRPE pairs; evoPASS; static C upperbound992 and actual maxeligibility610<1000. B reconstruction/nonfeature/source-q/velocity/float32 contractsPASS.
- Initialization/diagnostics: one initialization per run; B firstpose delay6.248s,C7.249s; visual–IMU misalignment rejects B2,C7; fittedscale medians B0.7467,C0.4508. No reset/failure-detection logs. New candidate residual blocks med374181; repeated use is not independent information.
- Interpretation/conclusion: severe negative new C case, not a structural delivery defect; initialization/scale differences remain association, not causal proof. Overall decisionUnknown.
- Follow-up: complete the other11 Batch A windows; no early substitution or threshold changes.


## coe1_A03_initial_window — 2026-09-08
- Experiment ID: classical_opportunity_expansion_v1/coe1_a03_00000_00900.
- Status and scientific role: COMPLETE per-window comparison; PRACTICAL_LOSS / SEVERE_REGRESSION; frozen classical additive control, not proposed method.
- Git commit and branch: runner source3f8396a85dd668cd8f4fbad720ba689d1da9e525; exp/classical-opportunity-expansion-v1-20260908; source identity locks inherited8f323ba and Python3.8 adapterd162b73.
- Dataset/sequence/window: AQUALOC archaeology03,900rawimages[0,900), exact sensor stamps in window_roster_frozen.csv; broader history exposure separately recorded.
- Environment/configuration: ROS Noetic/Python3.8, existing guarded capacity1000 backend, ROS12691, .04s/8iterations, serial CPU2,3,8,9, inherited sensor family calibration; exact hash locks unchanged.
- Baseline: fresh complete KLT B,350cap,every2offset1,adaptive_clahe,vins_safe.
- Proposed modification: none to method; C-all appends frozen GFTT/LK classical candidates, preserves every B observation/nonfeature message.
- Commands/artifacts: scripts/classical_opportunity_py38.py --batch A drives run_classical_opportunity_expansion.py --window coe1_a03_00000_00900 --arm B|C-all --repeat1|2|3; runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a03_00000_00900; reports papers/frontend_classical_opportunity_expansion_v1/common_support/coe1_a03_00000_00900/C-all_vs_B and backend_results.csv.
- Metrics/results: BAPE median0.85802846m(range0.85446650–0.86166514), CAPE2854.46348m(2781.31691–2867.04419); BRPE0.07895172m(0.07863311–0.07921606), CRPE277.286662m(270.935815–278.489161). Fixed-scale properSE3, strict1s global positional delta RPE; Sim3 diagnostic only.
- Validity/common support:6/6runabilityPASS, exact per-IDreceiptsPASS,42commonposes,41s,coverage95.4545%,41RPEpairs,evo<1e-6m; actual max473<1000. Firstpose1.2501735s and trajectorycoverage97.1582% botharms. No reset/misalignment log evidence establishes a causal explanation; losttracking truth Unknown.
- Interpretation: initialized output continuity and successful delivery do not imply accurate VIO. Extremely large C errors occur in all3technicalrepeats and remain in the registered denominator.
- Conclusion: second severe new negative in Batch A prevents Batch B admission; all remaining10A windows still required.
- Follow-up: complete frozen Batch A, then final set-level case handoff; no rerun, XFeat arm or parameter adjustment.


## coe1_A04_initial_window — 2026-09-08
- Experiment ID: classical_opportunity_expansion_v1/coe1_a04_00000_00900.
- Date/status/scientific role:2026-09-08,COMPLETE per-window comparison;PRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN;fixed classical control/probe.
- Git commit/branch:e59c4fdfac30640a1308dc8657d363ed8143a541 report checkpoint;execution started undera5eec9e7604f3b66af6ca27bed0a22448f365f66;exp/classical-opportunity-expansion-v1-20260908;method source locks unchanged.
- Dataset/window:AQUALOC archaeology04raw[0,900),exact timestamps in frozen roster.
- Environment/configuration:ROSNoetic/Python3.8,ROS12691,guarded1000capacity,.04s/8iterations,CPU2,3,8,9,identical sensor-family backend source except runtime paths.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all appending classical candidates;no source/q/gate/backend/evaluator change.
- Commands/artifacts:registered batch controller invokes run_classical_opportunity_expansion.py --window coe1_a04_00000_00900 --arm B|C-all --repeat 1|2|3. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a04_00000_00900;published common_support/coe1_a04_00000_00900/C-all_vs_B and case_registry/backend_results tables in expansion paper directory.
- Metrics/results:BAPE743.154136/743.154136/837.552376m,CAPE0.11378774/0.11379938/0.11380400m;BRPE90.424742/90.424742/102.934309m,CRPE0.13762984/0.13763328/0.13763494m(allmin/median/max). Fixed properSE3/strict1s positional-delta RPE. C57373observations,4843IDs,2971ge4,1745ge10,life6median/195maxobservations.
- Validity/common support:all6runability and exactper-IDreceiptsPASS,maxactualeligible564<1000;31commonposes,35s,coverage70.4545%,2segments,29RPEpairs,evo<1e-6m. Cfirstpose2.899775s later thanB;Ccoverage82.6143%,B89.2058%;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:robust range-separated improvement over a numerically diverged baseline;common support just exceeds frozen bound. This supports a specific rescue case, not unqualified routine accuracy gain.
- Conclusion:first new practical/robust positive,one positive sequence;2existingsevere regressions still prohibitBatchB.
- Follow-up:finish9remainingA windows;handoff baseline-anomaly case to utility/risk mechanisms without tuning C-all.


## coe1_A05_initial_window — 2026-09-08
- Experiment ID: classical_opportunity_expansion_v1/coe1_a05_00000_00900.
- Date/status/scientific role:2026-09-08;NOT_EVALUABLE/INVALID_COMMON_SUPPORT;fixed classical additive probe;all6planned technical replays completed.
- Git commit/branch:969d7fe32c54fe71fddb9bf648ad22c62333cc3b;exp/classical-opportunity-expansion-v1-20260908;frozen mathematical source unchanged.
- Dataset/window:AQUALOC archaeology05raw[0,900);900images,reference exists but covers a shorter segment;exact timestamps in frozen roster/preparation receipt.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialbackend CPU2,3,8,9,unchanged calibration/configuration/hash locks.
- Baseline:fresh complete KLT B,350cap,every2offset1,adaptive_clahe,vins_safe.
- Proposed modification:frozen C-all adds all eligible classical candidates,without removingB.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_a05_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a05_00000_00900;published common_support/coe1_a05_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:all6runability/exactper-IDreceiptsPASS;C4442publishedobservations/1195IDs;APE/RPE comparison Not evaluated.
- Validity/common support:matched_count27<30,span26s,common_grid_count27,coverage1.0,rpe_pairs26;ape_validFalse. Reference span26.996555s;100% means coverage of this shorter reference grid,not full raw-input coverage. Do not compare a standalone valid RPE when the registered joint comparison fails.
- Interpretation:structural availability of reference did not guarantee evaluation eligibility;the preselected window remains in the full denominator.
- Conclusion:NOT_EVALUABLE with exact minimum-pose violation;neither a C gain nor a C loss,not a backend failure.
- Follow-up:continue remaining8A windows;retain as reference-limited case,without substitution or threshold changes.


## coe1_A06_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_a06_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN;frozen classical control.
- Git commit/branch:fd4ec2b0619f2b56b3cf3b3e7b2543f983a2340e;exp/classical-opportunity-expansion-v1-20260908;frozen method/runner identities unchanged.
- Dataset/window:AQUALOC archaeology06raw[0,900),existing sample rawarchive,exact input/reference identity in preparation receipt and frozen roster.
- Environment/configuration:ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,inherited family calibration/hash locks.
- Baseline:fresh completeKLT B,350cap,every2offset1,adaptive_clahe,vins_safe.
- Proposed modification:frozen C-all classical addition retaining allBobservations/nonfeature messages.
- Commands/artifacts:registered controller invokes run_classical_opportunity_expansion.py --window coe1_a06_00000_00900 --arm B|C-all --repeat 1|2|3. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a06_00000_00900;published common_support/coe1_a06_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APE min/median/max B2.050386/151.785956/183.491589m,C0.948918/0.950726/0.970376m;RPE B0.342113/19.136619/22.941066m,C0.184863/0.187006/0.187112m. Maximum APE repeat range181.441203m exceeds150.835229m median reduction,so practicalgain not met. C6697observations/1275IDs,lifetime3median/55maxobservations.
- Validity/common support:all6runability/per-IDreceiptsPASS;37poses,36s,84.0909%coverage,36RPEpairs,evo<1e-6m. C/Bfirstposedelay6.449473/4.449896s;C/Bcoverage85.3404/89.8854%;Cresidual14772perrepeat,maxactualeligible487<1000;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:large directional improvement with unstablebaseline;do not relabel as practicalgain using a post-hoc criterion.
- Conclusion:SMALL_OR_UNCERTAIN;useful baseline-instability/initialization-context case,not a registered positive.
- Follow-up:continue remaining7A windows;no tuning,extra repeats or BatchB.


## coe1_A07_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_a07_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,PRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN;frozen classical additive probe.
- Git commit/branch:6135930c9726cb9d1a00160c8c99652d9525c18e;exp/classical-opportunity-expansion-v1-20260908;frozen source/config/backend identities unchanged.
- Dataset/window:AQUALOC archaeology07raw[0,900),exact timestamps in frozen roster;broader project exposure retained separately.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged sensorfamily configuration.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all append-only classical candidates;no change to algorithm,gates,q,backend or evaluation.
- Commands/artifacts:registered controller invokes run_classical_opportunity_expansion.py --window coe1_a07_00000_00900 --arm B|C-all --repeat 1|2|3. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a07_00000_00900;published common_support/coe1_a07_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB3.042555/3.044412/3.053754m,C0.17339477/0.17339578/0.17340055m;RPEB0.68196793/0.68220301/0.68298444m,C0.10670231/0.10670485/0.10670487m. C30732observations/4890IDs,life3median/121maxobservations,2197ge4/897ge10.
- Validity/common support:all6runability/per-IDreceiptsPASS;36poses,38s,80%coverage,2segments,34RPEpairs,evo<1e-6m;maxactualeligible521<1000;Cresidual131448perrepeat;Cfirstpose0.199943searlier;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:second stable positive on a different sequence,with baseline scale error still visible;no independent population inference or per-feature utility label.
- Conclusion:ROBUST_PRACTICAL_GAIN onA07. The2severe cases already observed still prohibitBatchB despite2cross-sequencepositives.
- Follow-up:finish remaining6A windows and handoff complete positive/negative/uncertain/reference-limited pool to utility/risk research.


## coe1_A10_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_a10_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN;fixed classical control.
- Git commit/branch:ae5afea8499992074823e86651aac045f09e881f;exp/classical-opportunity-expansion-v1-20260908;frozen runner/mathematical identities unchanged.
- Dataset/window:AQUALOC archaeology10raw[0,900),exact timestamps/reference/input identities in frozen roster and preparation receipt.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged family calibration/hash locks.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:unchanged C-all adds eligible classical candidates while preserving allB and nonfeature messages.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_a10_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_a10_00000_00900;published common_support/coe1_a10_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB0.05984241/0.06007548/0.06047836m,C0.05649002/0.05661839/0.05662045m;RPEB0.05223652/0.05224253/0.05225060m,C0.05367140/0.05369101/0.05369167m. APEreduction0.003457089m<0.01m;RPEincrease0.001448478m within guard. C8287observations/1460IDs,lifetime2median/72maxobservations.
- Validity/common support:6/6runability/per-IDreceiptsPASS;40poses,39s,93.0233%coverage,39RPEpairs,evo<1e-6m;maxactualeligible429<1000,Cresidual28898perrepeat;firstposedelay2.949710sbotharms;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:stable baseline and small mixed metric changes;relative improvement alone does not satisfy the practical definition.
- Conclusion:SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN,retained in neutral list.
- Follow-up:complete H01–H05,then final case handoff;no parameter search or BatchB.


## coe1_H01_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_h01_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,SMALL_OR_UNCERTAIN/NONE;fixed classical control.
- Git commit/branch:292fe54d3c9ca69ed25823f324ae1cc679cc0e18 reporting checkpoint;H01replays began underae5afea8499992074823e86651aac045f09e881f;exp/classical-opportunity-expansion-v1-20260908,unchanged source locks.
- Dataset/window:AQUALOC Harbor01raw[0,900),exact timestamps/input/reference hashes in frozen roster and preparation receipt.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged Harbor-family configuration.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all append-only classical candidates;allB/nonfeature messages preserved.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_h01_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_h01_00000_00900;published common_support/coe1_h01_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB0.07076470/0.07076473/0.07089799m,C0.07120079/0.07152362/0.07155176m;RPEB0.00997389/0.00997393/0.01007549m,C0.00993253/0.01010866/0.01014479m. C20127observations/2498IDs,life3median/159maxobservations,124110actualcandidate residualblocksperrepeat.
- Validity/common support:all6runability/per-IDreceiptsPASS;42poses,41s,93.3333%coverage,41RPEpairs,evo<1e-6m;maxactualeligible482<1000;firstpose2.449259sbotharms;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:small error increases with substantial confirmed intervention;neutral is not null action.
- Conclusion:SMALL_OR_UNCERTAIN,not a practicalpositive/loss or independent no-harm population claim.
- Follow-up:finish H02–H05 and retain this nonzero-action neutral case for utility/risk research.


## coe1_H02_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_h02_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,PRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN;fixed classical additive probe.
- Git commit/branch:49c9c3b612bb73f34857d7bec80362a7366a2109 reporting checkpoint;replays began under292fe54d3c9ca69ed25823f324ae1cc679cc0e18;exp/classical-opportunity-expansion-v1-20260908;frozen identities unchanged.
- Dataset/window:AQUALOC Harbor02raw[0,900),exact timestamps/input/reference identity in frozen roster/preparation;broader project overlap retained.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged Harbor calibration and source locks.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all append-only classical candidates;allB/nonfeature messages preserved.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_h02_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_h02_00000_00900;published common_support/coe1_h02_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB0.10341843/0.10939183/0.11028445m,C0.02935680/0.02941242/0.02941257m;RPEB0.03472649/0.03621206/0.03636493m,C0.00768505/0.00768786/0.00768837m. C35978observations/4319IDs,life4median/106maxobservations;256448actualresidualblocksperrepeat.
- Validity/common support:all6runability/per-IDreceiptsPASS;41poses,40s,91.1111%coverage,40RPEpairs,evo<1e-6m;maxactualeligible620<1000;Cfirstpose1.599425searlier;misalignment countsB12/C2;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:stable practical improvement over a moderate-error baseline,accompanied by earlier initialization-related timing;cause remains Unknown.
- Conclusion:third ROBUST_PRACTICAL_GAIN on third positive sequence;2severe cases still violate the BatchB/final acceptable-risk bound.
- Follow-up:finish H03–H05,then utility/risk case analysis only.


## coe1_H03_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_h03_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN;fixed classical control with absolute numerical anomalies.
- Git commit/branch:9c07f6935daddd278bb165eb431718bf11769cec reporting checkpoint;replays began under49c9c3b612bb73f34857d7bec80362a7366a2109;exp/classical-opportunity-expansion-v1-20260908;source/config/binary locks unchanged.
- Dataset/window:AQUALOC Harbor03raw[0,900),exact timestamps/input/reference identities in frozen roster/preparation.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged Harbor-family configuration.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all classical addition retaining allB/nonfeature messages.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_h03_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_h03_00000_00900;published common_support/coe1_h03_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB848.004116/848.216346/848.384525m,C0.07146680/837.927196/838.008913m;RPEB91.990762/92.019467/92.037611m,C0.04154727/90.965970/90.972569m. C29659observations/2696IDs,life4median/141maxobservations;actual residualblocks29806–199867acrossrepeats.
- Validity/common support:all6runability/per-IDreceiptsPASS;43poses,42s,95.5556%coverage,42RPEpairs,evo<1e-6m;maxactualeligible644<1000;firstposeC1.448549–1.748524s,B1.448549s;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:one accurate C repeat and two inaccurate C repeats;the frozen median/range outcome is uncertain. This is not acceptable absolute performance despite structural/runability validity.
- Conclusion:SMALL_OR_UNCERTAIN with numerical anomaly and unusual C repeat instability;no extra repeat or best-run selection.
- Follow-up:finish H04/H05,retain full ranges and initialization/receipt context for utility/risk research.


## coe1_H04_initial_window — 2026-09-08
- Experiment ID:classical_opportunity_expansion_v1/coe1_h04_00000_00900.
- Date/status/scientific role:2026-09-08;COMPLETE comparison,SMALL_OR_UNCERTAIN/NONE;fixed classical control.
- Git commit/branch:2e4cee7ae1baf4a1af70e255f449c213836b17f0 reporting checkpoint;replays began under9c07f6935daddd278bb165eb431718bf11769cec;exp/classical-opportunity-expansion-v1-20260908;frozen identities unchanged.
- Dataset/window:AQUALOC Harbor04raw[0,900),exact input/reference/timestamps in frozen roster and preparation.
- Environment/configuration:registered ROSNoetic/Python3.8,port12691,guarded1000capacity,.04s/8iterations,serialCPU2,3,8,9,unchanged Harbor-family calibration/hash locks.
- Baseline:fresh completeKLT B350cap/every2offset1/adaptive_clahe/vins_safe.
- Proposed modification:frozen C-all classical addition,allB/nonfeature messages preserved.
- Commands/artifacts:run_classical_opportunity_expansion.py --window coe1_h04_00000_00900 --arm B|C-all --repeat 1|2|3 via registered controller. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_h04_00000_00900;published common_support/coe1_h04_00000_00900/C-all_vs_B and case/backend tables.
- Metrics/results:APEmin/median/maxB0.16890296/0.16890639/0.16892903m,C0.17110440/0.17110605/0.17139934m;RPEB0.02454722/0.02455506/0.02458801m,C0.02463115/0.02463187/0.02478457m. C5714observations/1014IDs,life3median/94maxobservations,residual34968perrepeat.
- Validity/common support:all6runability/per-IDreceiptsPASS;43poses,42s,95.5556%coverage,42RPEpairs,evo<1e-6m;maxactualeligible434<1000;firstpose1.351892sbotharms;losttrackingtruthUnknown,logproxiesseparate.
- Interpretation:APE increase0.002199662m andRPE increase0.000076803m below frozen practicalloss conditions.
- Conclusion:SMALL_OR_UNCERTAIN,retained with nonzero action and small error increases.
- Follow-up:complete H05 and final full-denominator handoff;no BatchB/tuning.


## COE1-A-H05 — 2026-09-08
- Status and scientific role: COMPLETE; final preregistered opportunity-probe case in Batch A; SMALL_OR_UNCERTAIN/NONE.
- Git commit and branch: execution lock 8f323ba with Python 3.8 reporting adapter d162b73; branch exp/classical-opportunity-expansion-v1-20260908. Latest pre-completion checkpoint 2e4cee7ae1baf4a1af70e255f449c213836b17f0.
- Dataset and sequence/window: AQUALOC Harbor05, coe1_h05_00000_00900, raw [0,900), sequence-held-out only relative to the old six C-all development windows.
- Environment and exact configuration: registered aquafe_cuda Python 3.8, ROS Noetic master 12691; frozen Harbor configuration, same capacity-1000 diagnostic VINS binary, solver 0.04 s/8 iterations; full configuration and hashes in expansion locks and per-run receipts.
- Baseline: fresh full KLT B, three technical replays.
- Proposed modification: fixed additive classical C-all, complete B retained, three technical replays.
- Commands and artifact/run paths: scripts/classical_opportunity_py38.py --batch A --wait-first-pid 846846; runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1/backend/coe1_h05_00000_00900/{B,C-all}/repeat{1,2,3}; primary papers/frontend_classical_opportunity_expansion_v1/{backend_results.csv,case_registry.csv,common_support/coe1_h05_00000_00900/C-all_vs_B/}.
- Metrics and results: fixed-scale proper SE(3) APE B min/median/max 0.218331637/0.218333457/0.218334404 m, C 0.218611866/0.218612648/0.218617415 m; strict 1 s translational RPE B 0.024782784/0.024782804/0.024783122 m, C 0.024875999/0.024877202/0.024877742 m. Median deltas +0.000279191 m APE and +0.000094398 m RPE. C 8610 observations, 1529 IDs, 660 IDs >=4 and 253 IDs >=10 observations; lifetime median/max 3/74 observations. Per-arm trajectory coverage 97.6523%, first-pose delay 1.051083 s, all reset/failure/misalignment proxies zero. Backend wall time B 64.828–64.941 s, C 64.791–65.036 s; not algorithm FPS. Lost-tracking count Unknown.
- Validity checks and common support: own six-trajectory support 43 poses/42 s/95.5556%/42 RPE pairs; evo below 1e-6 m; all six runability and per-ID receipts PASS, max actual eligible 460 < 1000. COLMAP/proxy is not independent GT.
- Interpretation: nonzero classical dose with small stable accuracy increases below the frozen practical-loss conditions.
- Conclusion: complete Batch A denominator is 12 windows/72 replays; 3 gains, 2 losses, 6 small/uncertain, 0 FAIL, 1 NOT_EVALUABLE, 2 severe regressions.
- Follow-up: freeze/publish Batch A checkpoint and final integrity/report; no Batch B under the registered gate.


## COE1-A-FINAL — 2026-09-08
- Status and scientific role: COMPLETE; final registered fixed-C opportunity expansion and integrity/descriptive analysis. ADDITIVE_OPPORTUNITY_NOT_GENERALIZED; EXPANSION_STOPPED_AFTER_BATCH_A.
- Git commit and branch: base 49c02471716e8ac960e35dd9dd44ef6fbb1428c6; roster 881dad7, method/execution lock 8f323ba, Python 3.8 adapter d162b73, full Batch A checkpoint 853cdd6011f9d3a73cfbd84e580d121530cbecdb; exp/classical-opportunity-expansion-v1-20260908.
- Dataset and sequence/window: AQUALOC A01/A03/A04/A05/A06/A07/A10/H01/H02/H03/H04/H05, each raw [0,900), one physical window per sequence; all 12 retained. Relative to old six C-all developer windows: 12 sequence-held-out/0 window-held-out. Broader checked history overlap 7/12; not globally unseen-data confirmation. Frozen Batch B [900,1800) not activated.
- Environment and exact configuration: isolated worktree, aquafe_cuda Python 3.8/ROS Noetic, dedicated master 12691; frontend CPU 0/6, serial backend CPU 2/3/8/9, BLAS limits; old capacity-1000 diagnostic binary and sensor-family snapshots, solver .04 s/8 iterations/loop0/multiple_thread0. Exact source/config/binary hashes in expansion locks and run_receipts.
- Baseline: fresh complete KLT B per window, 3 technical replays.
- Proposed modification: unchanged full-B-plus-classical C-all, 3 technical replays; no learned arms, dose tuning or new backend.
- Commands and artifact/run paths: scripts/classical_opportunity_py38.py --batch A --wait-first-pid 846846; final audit scripts/audit_classical_opportunity_final.py, supplement scripts/complete_classical_opportunity_case_fields.py, descriptive bundle scripts/build_classical_opportunity_analysis_bundle.py. All invoked from isolated worktree with registered environment. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1; paper papers/frontend_classical_opportunity_expansion_v1/{report.md,case_registry.csv,backend_results.csv,analysis-output/,run_receipts/,final_integrity_audit.json}.
- Metrics: fixed-scale proper SE(3) APE RMSE primary; strict 1 s aligned-global translational RPE guard, full 3-repeat min/median/max, fitted scale diagnostic. Runtime, feature coverage (4x6 occupied-grid median), published/received/eligible/residual counts, lifespan counts/seconds, first-pose clocks, proxy reset/failure/misalignment, support coverage and pose/RPE counts retained.
- Results: 12 physical windows/72 formal replays; 3 PRACTICAL_GAIN (A04/A07/H02, all robust), 2 PRACTICAL_LOSS (A01/A03, both severe), 6 SMALL_OR_UNCERTAIN, 0 FAIL, 1 NOT_EVALUABLE (A05). Directional-only A06/A10/H03 remain small/uncertain. Total candidate published observations 304268 across 29382 window/public-ID chains. Full numerical accuracy tables in report.md and exact_numeric_summary.csv; no cross-window error pooling.
- Validity checks and common-support status: 11 own-six-trajectory comparisons pass >=30 poses/>=10s/>=70%/>=10 pairs and evo<=1e-6m; max observed evo difference 4.993701410160867e-7m. A05 27 poses/26s/100% of short reference grid/26 pairs, invalid for APE comparison; reference span26.996555264s versus raw44.942624512s. All72 runability and exact per-ID receipts PASS, max actual eligible644<1000. Final audit1656 hashes/no mismatch and unchanged source/config/eval/class labels. COLMAP/proxy not independent GT.
- Interpretation: cross-sequence local benefit exists, but 2 severe regressions violate the frozen <=1 risk bound. A04 abnormal baseline rescue, H02 moderate-baseline gain, A06/H03 repeat pathologies and A05 short reference must remain distinct. Runability PASS does not certify numerical accuracy.
- Conclusion: Batch B not executed; stop additive-observation primary-hypothesis expansion under this contract. C-all stays classical control/probe. Technical repeats do not estimate a population success rate; statistical significance and per-candidate utility Not evaluated.
- Follow-up: publish final report/cases and hand off only to separately designed observation-utility/risk research. These outcome-known cases are development material for any new mechanism using them; fresh independent confirmation required later. No automatic C-all tuning.


## 2026-09-09 — LEARNED_SAME_FRAME_KLT_RECOVERY_V1_FRONTEND
- Status / scientific role: COMPLETE; fixed development correctness and direct-increment test; NO_LEARNED_INCREMENT, secondary REAL_RECOVERY_NOT_ESTABLISHED.
- Git: freeze915716d5e4d56bc4663125db061c5acc35ddadf9; branch exp/learned-klt-recovery-v1-20260909.
- Dataset/windows: A02 raw[0,200), A08[2700,2900), H02[0,200); exact bags/cameras/nanosecond endpoints in papers/frontend_learned_klt_recovery_v1/input_manifest.json. 12 fixed base images ×4 known transformations =48pairs; not held-out or natural GT.
- Environment/config: GTX1650, Torch2.2.2+cu121, OpenCV4.2.0, Python3.8.10, ROSNoetic image reader, taskset0,6 and OMP/OpenBLAS/MKL/OpenCV/Torch1thread; adaptive CLAHE+unchanged quality. B original21/3 KLT; C31/4 retry; L frozen XFeat2048/.82 affine initial flow plus31/4. Final gates and350cap shared; no q/backend change.
- Commands/artifacts: source /opt/ros/noetic/setup.bash; PYTHONPATH=.:scripts:$PYTHONPATH; export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1; taskset -c0,6 /mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/run_learned_recovery_frontend.py --sequence <A02|A08|H02>, sequential, then same Python scripts/summarize_learned_recovery_frontend.py --samples. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_learned_klt_recovery_v1; report/CSV/decision in same named papers directory.
- Metrics/results: correct visible recovery<=2px; controlled L835/C2488 correct, L0/C14 wrong accepted, L0/C8 invisible false, shared visible B failures6532/all8371. Natural paired2857 events: C148/L8, no L-only; actual streams C171/L11 recoveries, C99/L3 have>=4 public observations. Full event reasons/coordinates/lifetimes retained. Latency and absolute error distributions in report/decision.
- Validity/common support: C/L same B failures, initial GFTT, ordinary-success invariance, increasing adjacent raw time,350cap, no public-gap ID revival pass. Independent actual-output recount matches event lifetimes. Natural identity Unknown; future only offline; no ROS serialization or VINS evaluation, trajectory common support Not evaluated. Zero execution failures or reruns.
- Interpretation/conclusion/follow-up: L localizes some synthetic original points accurately but yields much less than C and no unique natural recovery. Frozen frontend gate fails; stop version. No new/reused backend replays; no backend_results.csv, no wider search or automatic validation.


## 2026-09-10 — SEA_RAFT_MEASUREMENT_CAPABILITY_SCREENING_V1
- Status/scientific role: COMPLETE, development-only direct optical-flow capability screen; CONTROLLED_GAIN_ONLY.
- Git/environment: protocol/model lock2833851648e84cf0c1bf0cd1f10406455878331e, branch exp/searaft-screening-v1-20260910; officialSEA-RAFT9137517, HFMemorySlices/Tartan-C-T-TSKH-spring540x960-M@eb97ef34; Torch2.2.2+cu121, Python3.8.10, OpenCV4.2.0, GTX1650, singlethread/CPU0,6, FP32/iters4/scale−1/batch1. Exact weightsSHA/config/loading in model_lock.json; no fallback resolution.
- Dataset/window/config: A02raw[0,200),A08[2700,2900),H02[0,200);4fixedbaseoffsets×4fixed transforms perseq=48pairs. Exactbags/timestamps/cameras/seed in controlled_pair_source.json. B21/3KLT, C31/4/40LK, SdirectSEA-RAFT; B/CadaptiveCLAHE, Smono8copiedRGB. Sharedquery/coreB-failure cohorts; C/Scommon finite/FB≤1originalpx/border8; Cproductionoldgatesseparate.
- Commands/artifacts: ROSreader scripts/prepare_searaft_inputs.py; isolatedruntime/env/bin/python scripts/run_searaft_screening.py, releaseRUN afterfreeze; conditional natural extraction andscreen automatically; finalizer scripts/finalize_searaft_screening.py. Runtime=/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1, all requiredsmalltables/report in papers/frontend_searaft_screening_v1.
- Metrics/results: EPE distribution and≤1/2px onvisible queries, completefinite/missing/outsidecoverage; common-filtercorrect/wrong/invisible/precision, subgroupA/B gates. Sraw6532/6532visibleBfailures≤2px, p95.2303px. Scommon6525correct/309wrong vs Ccommon2672/66; S-only4114ofwhich3835correct. largepassA08/H02; illuminationpassA02/A08/H02; outside_occludedallfail. Natural528pairs,2857Bfailedqueries: S-only61,C-only25,both995,neither1776. S-only3steps0/0/20, so naturalcrossseqgatefails. ControlledS median277.4ms/pair; completecost, peakmemory and warmup in timing/model_lock.
- Validity/common support: originalinput/queries/unitsandcurrentendpointFBchecked; noLKrefinementofS; all48andall3naturalpiecesretained. Independentquery/mask/countchecks and5behavioraltestsPASS. Synthetictruthonly, naturalphysicalidentityanddriftUnknown. Trajectorycommonsupport/APE/RPE/init/coverageNot evaluated.; nofeaturebag/VINS.
- Failures/interpretation/conclusion/follow-up: initialHFstrictaliascompatibilityerrorpreserved; samecheckpointofficiallocal-loader conversion+472exactstateverification. One successfulinstance,1156forwardcalls, noformalretry/OOM. Correctmeasurementabilityexists underlimitedsyntheticconditions, withocclusionfailureandonlyH02persistentexclusiveopportunities. CONTROLLED_GAIN_ONLY; stop/archivenoautomaticintegrationormodel/threshold/windowsearch.

## 2026-09-10 — SEA_RAFT_CORRESPONDENCE_EVIDENCE_CHECK_V1
- Status/scientific role: COMPLETE, internal development evidence check; EVIDENCE_GATE_NOT_SUPPORTED. Input a2f3bedcc2e4f98bd18f99a3601d70433de42aa7, protocol freeze12310f47e31b86764bb67e2920bc9171e0c38391, branch exp/searaft-evidence-check-v1-20260910.
- Data/environment/config: original48 controlled pairs (A02[0,200), A08[2700,2900), H02[0,200)); offset0/50 calibration,100/150 check, all four transforms grouped by base. Old2857 natural events, same originalmono8. Python3.8.10, NumPy1.24.4, OpenCV4.2.0; CPU single-thread. 11×11 exact bilinear NCC≥.65, std>1 gray level, full/finite patch required.
- Baseline/modification: S0=old S_common, C0=old C_common; S1/C1 add the identical evidence check at unchanged endpoints. SU uses one95%-retention calibration-label cutoff for official mixture-Laplace scale, separate from NCC and never substituted as natural main rule. C_production excluded from paired denominators.
- Commands/artifacts: `PYTHONPATH=. /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/env/bin/python scripts/run_searaft_evidence_check.py --run`; after explicit visual review use --finalize without rescoring. Results in papers/frontend_searaft_evidence_check_v1; sparse scores/timing in /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_evidence_check_v1. Six fixed panels,26 unique reviewed events.
- Metrics/results: check S0 correct3321/wrong199→S1 correct3276/wrong18; correct retention98.64%, invisible18/940=1.91%, precision99.45%. S1−C0/C1 correct recovery+61.49/+61.82pp; large/illumination retain≥5pp in all3 sequences. Original S-only correct2035/2080 retained. SU check3095correct/25wrong, no main-rule substitution. Full S1 correct6450/wrong26. All groups and original denominators retained in evidence_results.csv.
- Natural results: original61 S-only→45 retained (A02/A08/H02=8/5/32); original three-step support0/0/20→0/0/7. H02 retained7 visual supported3/contradiction0/unresolved4; all20 original H02 events have C/S endpoint distance≤2px. Visual review labels and gate reasons in natural_event_review.csv. No independent pixel truth.
- Validity/checks: five numerical checks pass; frozen coordinates/FB/truth and existing three-step records unchanged; one check-part scoring pass; no new inference/training/VINS/LK recheck/model/window. Trajectory common support, APE/RPE/init/tracking Not evaluated. No formal failure or rerun; required cached images were available.
- Interpretation/conclusion/follow-up: NCC removes160 artificial-occlusion rectangle false accepts in check but leaves14 occlusion guard+4 border guard false accepts under unchanged labels. Error target≤1% fails despite retained advantage and H02 local clues. EVIDENCE_GATE_NOT_SUPPORTED; preserve evidence and end this version without tuning or integration.

## 2026-09-11 — SEA_RAFT_REAL_CORRESPONDENCE_V1
- Status/scientific role: INFERENCE_AND_MATERIALS_COMPLETE, REFERENCE_PENDING; fixed small real-image development check. Branch exp/searaft-real-correspondence-v1-20260911; queries, blank references and blind sheets frozen at 637322c3c1b3c4450610b16b669a4c6840a8e0c0. Model settings from a2f3bed and evidence function from 4d061b8 are unchanged.
- Dataset/config: A02 [0,200), A08 [2700,2900), H02 [0,200), offsets 40/120 paired with +1/+10, 12 pairs. Actual dt is in the manifest (t+1 .049020–.052353 s, t+10 .498739–.501856 s). Source-only 4×2 grid, 16 px border, 92 queries; the same source points across gaps; empty q1 cells in A02_s120/A08_s040 retained.
- Baseline/modification/environment: C0 is old strong LK 31/4/40 with common FB/finite/8 px border checks; S0 is official spring-M direct flow. C1/S1 add identical fixed 11×11 subpixel NCC≥.65, std>1 and full patch support. C uses old adaptive CLAHE; S uses mono8 copied to RGB. Existing isolated Python 3.8/Torch 2.2.2+cu121/GTX1650, FP32/iters4/scale−1/batch1, single thread, TF32 off, offline cached weights. One load, 12 bidirectional pairs, 24 forward calls; no training, VINS or new weights.
- Commands/artifacts: scripts/run_searaft_real_correspondence.py prepare then predict, using /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/env/bin/python; PYTHONPATH=.:scripts for prediction, TORCH_HOME set to that original runtime's torch_cache, HF_HUB_OFFLINE=1, OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1. New papers/frontend_searaft_real_correspondence_v1 contains manifest/predictions/reference/comparison/report/decision and separate blind/algorithm sheets. /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_real_correspondence_v1 keeps 12 sparse pair caches and timing; no dense flow upload.
- Metrics/results: all 92 queries preserved; independent reference confirmed 0, pending 92. Acceptance C1/S1=85/88 overall; t+1 both 46/46; A02/A08 t+10 each 15/15; H02 t+10=9/12 of 16, C-only 1/S-only 4 with one near-endpoint gate discrepancy. C1=C0 and S1=S0 on this batch. EPE median/p95, ≤2 px accuracy, correct/wrong/unique-correct and invisible false acceptance are Not evaluated.; comparison cells are blank with REFERENCE_PENDING.
- Validity/common support: paired queries share source points and physical images/times. The query manifest, blank reference and blind target images existed before prediction and remained unchanged. Old Assistant reviews, LK, FB, NCC, poses and geometry are not independent reference. Masks and cache counts checked; no formal failure/rerun. Source points were restored by one original KLT/GFTT step from the old odd-frame B cache, without target selection. Trajectory common support, APE/RPE are Not evaluated.
- Runtime/interpretation/conclusion/follow-up: full S bidirectional first pair 2932.6 ms (cold), remaining 11 median/p95=254.5/262.7 ms; C raw median 2.3 ms with 366.5 ms preprocessing separately, descriptive costs only. H02 long-gap acceptance differences require blind reference review to establish any accuracy gain. REFERENCE_PENDING; annotate 92 fixed rows and then compare cached predictions, with no additional models/windows/VINS.

## frontend_searaft_system_probe_v1 — 2026-09-11
- Status/scientific role: COMPLETE, UNSAFE_OR_UNRESOLVED; outcome-known offline development, not held-out or robot deployment.
- Git: branch exp/searaft-system-probe-v1-20260911; protocol/inference1d677b7; original velocity repair2eccaf5; cached-export/backend source02afc3a. Exact source IDs in execution_provenance.json; final publication is the commit containing this entry.
- Dataset/windows: H02 and A02 raw[0,900), adjacent raw20Hz approximately,450 published feature messages per arm. Frozen image/IMU/camera/time inputs in input_manifest.json.
- Environment/configuration: original SEA-RAFT spring-M4 iterations,scale−1,FP32,GPU0,batch1; exact weight loading receipt.31/4/40 LK; fixed finite/FB≤1px/border8/raw11×11 NCC≥.65/std>1 evidence.350 tracks, unchanged recovery q and original export mapping. Existing backend binary SHA e231871eaff26a757a5d396ef5df0ad4d488d55be1c8d0e8d0f1204d1068aadd, same mathematical YAML, isolated ROS12731,rate1.
- Baselines/modification: B=original KLT; C=B+strong LK same-frame recovery; R=C+SEA-RAFT for only remaining failed original IDs. Later GFTT allocation may change.
- Commands/artifacts: scripts/run_searaft_system_probe.py frontend; cache-only frontend --cached-export (no new inference, rejected initial export retained); scripts/run_searaft_system_backend.py; scripts/analyze_searaft_system_probe.py, under ROS noetic and existing screening env. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_system_probe_v1. Published results/metrics/receipts in papers/frontend_searaft_system_probe_v1.
- Run count:18 new formal replays,0 historical reuse,0 fourth repeats.1355 new flow pairs/2710 forward-direction calls,203 reused query pairs,354.66s prediction/sampling incl loading.
- Metrics/results: fixed-scale proper SE(3) APE and strict1s RPE. H02 APE median B0.111301,C1030.084500,R0.026602m; R RPE0.007467m. A02 APE B0.065202,C1.153630,R1.157391m; R RPE0.130773m. All repeats/ranges/failure diagnostics preserved in results.csv/backend_results.csv/comparison.csv; no best-repeat selection.
- Validity/common support: B serialization exactly matches old baseline for all450 public frames in each window.6/6 capacity checks pass;18/18 receive complete features and pass runability. H02 common41poses/40strict pairs/91.11%coverage, A02 40/39/88.89%; all evo agreement≤1e-6m. These gates do not guarantee correct localization.
- Negative results/interpretation: H02 C all three APE1017.991709–1030.084500m, cause Unknown; H02 R/B local gain but healthy-C comparison is unresolved. Both B arms and A02 C unstable under frozen repeat guard. A02 R all three severely worse than B and no practical gain over C. Initial velocity export mismatch fixed before replay using cached predictions only, with full rejected artifacts retained.
- Conclusion/follow-up: UNSAFE_OR_UNRESOLVED; stop this combination. No extension/tuning or new human-label prerequisite. Per-point correctness Unknown; initialization and COLMAP/proxy limitations remain; old screening/reference conclusions unchanged.

## frontend_searaft_direct_recovery_v1 — 2026-09-11
- Status/role: COMPLETE / UNSAFE_OR_UNRESOLVED; outcome-known offline development deletion ablation, not held-out/deployment.
- Git: exp/searaft-direct-recovery-v1-20260911; base1138fab635910d3e1c34d57f99dab84c6ff8e9f5; frozen protocol/front4b74161e178ef37e1c39d140b3240303921f984b; backend/analysis basec63f38a85766aaa2753605f8cc492219be264f10. Final publication is commit containing entry.
- Inputs/config: H02/A02 raw[0,900),every raw,public every2offset1; manifest/camera/IMU/stamps unchanged. Original21/3 KLT; D skips31/4 retry entirely, fixed spring-M FP32/iters4/scale−1,finite/FB≤1/border8/11x11/std>1/NCC≥.65,350cap,existing q/velocity contract. Same frozen backend e231871eaff26a757a5d396ef5df0ad4d488d55be1c8d0e8d0f1204d1068aadd, mathematical configs/dependencies; isolatedROS12741,threads1,rate1.
- Baseline/modification: fresh B vs direct D,3 technical repeats each/window; fixed H02 B1..3,D1..3 then A02;12runs,none reused/added. Old C/R12 trajectories read only for auxiliary re-evaluation.
- Commands/artifacts: run_searaft_direct_recovery.py freeze/frontend/backend; analyze_searaft_direct_recovery.py; exact environment/paths in execution_provenance.json. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_direct_recovery_v1; published direct_recovery_v1 results/comparison/recovery_summary/decision/report.
- Metrics/results: fixed-scale properSE3 APE and strict1s RPE. H02 D/B medianAPE0.350326/0.102702m,RPE0.066359/0.034624m; A02 APE0.506198/0.145545m,RPE0.046424/0.021491m. All min/median/max retained; sixD severe-repeat flags,H02Dunstable. H02 oldR0.026602m,A02oldR1.157391m on independently recomputed support. Recovery10360/71events; network1069newpairs/2138calls,660fullycached;frontend1093.51s,backend779.89s. Lost-tracking countUnknown; no failure/reset logs.
- Validity:450feature messages each, full B exact serialization, nonfeature equality,350cap,allnewreceive/runabilityPASS. Maximumeligible574<1000. H02/A02 support41/40poses,40/39strictpairs,coverage91.11/88.89%; all6 comparisons/support/evoPASS. Twelve new + twelve historical auxiliary runs produce36comparison-specific rows, not36replays. Technical repeats not independent scientific samples.
- Interpretation/conclusion/follow-up: removing strong LK loses H02 benefit and only reduces A02 harm relative to oldR; still severe loss to freshB in both windows. B variance does not explain the separated D/B ranges; oldC kilometer anomaly and cross-batch limitations retained. Physical truthUnknown; proxy,initialization,GFTT limits. UNSAFE_OR_UNRESOLVED; close current same-frame SEA-RAFT recovery combination line, no further sweep or annotation.


## TOR-V1-SUPERVISION-20260911
- Date: 2026-09-11.
- Status and scientific role: COMPLETE / SUPERVISION_UNAVAILABLE; prerequisite data diagnosis, not method effectiveness experiment.
- Git commit and branch: protocol790467d, basea743558; exp/temporal-observation-refinement-v1-20260911; implementation uncommitted when diagnosis ran, captured in closing commit.
- Dataset and sequence/window: MIMIR-UW cam0 OceanFloor/track0_dark and SandPipe/track0_dark, fixed[0,1200); depth probes raw indices0,1,10,11,100,101 each; OceanFloor three extra nonconstant-signature files for format diagnosis only. Validation SeaFloor/track0 and test SeaFloor_Algae/track0[0,600) Not evaluated.
- Environment and exact configuration: Python3.8, OpenCV4.2.0 EXR unchanged, ImageMagick independent constant cross-check; immutable data_split.json and protocol.md; same official Zenodo record10406384.
- Baseline: intended original KLT B, not exported because supervision precondition failed.
- Proposed modification: intended P/T same211554-parameter patch residual model, framewise vs +0.5 temporal-error loss. No optimizer update or learned intervention occurred.
- Commands and artifacts: PYTHONPATH=. python3 scripts/audit_mimir_temporal_supervision.py --artifacts /mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1 --split papers/frontend_temporal_observation_refinement_v1/data_split.json --output /mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1/supervision_audit.json. Raw members, metadata, ZIP directories and receipts retained there. Public small result: papers/frontend_temporal_observation_refinement_v1/decision.json.
- Metrics/results:15 EXR decoded;12 constant1.0;6 segmentation PNG retained. Both training candidates have1200 matching depth names;933 and1185 directory entries share constant-sample length+CRC (signature evidence only). Valid labels0; P/T updates0; backend replays0. Training/measurement tables explicitly Not evaluated. APE/ATE/RPE, coverage, initialization, tracking loss, FPS, feature/inlier count and trajectory length Not evaluated.
- Validity checks and common support: CRC/length checked on retrieved members; original source unchanged; native HALF Y EXR channel confirmed; independent reader agrees constant. Depth semantics and real geometric projection not verified. No valid truth common support; no trajectory common support evaluation.
- Interpretation: cannot equate finite depth arrays with verified3D labels. Public issue4 reports constant maps but has no author resolution; issue3 closure is not a geometry fix. No claim all sequences defective.
- Conclusion: SUPERVISION_UNAVAILABLE; measurement/backend gates not reached. Seven unit tests passed but are not scientific gain evidence.
- Follow-up: obtain verified depth encoding/geometry correction before any new fit; retain all old stops.


## TA-TOR-V1-GEOMETRY-20260912
- Date / status / scientific role: 2026-09-12; completed supervision verification and zero-model smoke, not a method-effectiveness experiment.
- Git commit / branch: ea5fbcb; exp/temporal-observation-refinement-tartanair-v1-20260912 (cache-overlap wait flag pending stage commit).
- Dataset / window: TartanAir V1 abandonedfactory/Easy/P000, amusement/Easy/P001, carwelding/Easy/P001, endofworld/Easy/P000; fixed pairs0→1,10→11,20→21; cache smoke frames0,1 each.
- Environment / exact configuration: system Python3.8, OpenCV4.2, Torch2.2.2+cpu; 640×480 K=(320,320,320,240), optical z meters, camera NED→world. Frozen new protocol and original KLT config.
- Baseline / proposed: unchanged original KLT B; zero-initialized original211554-parameter refiner, no optimizer step.
- Commands / artifacts: PYTHONPATH=. python3 scripts/check_tartanair_temporal_geometry.py --split papers/frontend_temporal_observation_refinement_tartanair_v1/data_split.json --output /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/geometry_check_corrected.json; actual results papers/frontend_temporal_observation_refinement_tartanair_v1/{geometry_check,cache_smoke}.json. Raw retained artifacts /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/{geometry_check.json,geometry_check_corrected.json,cache_smoke.json}; cache production command recorded in final report.
- Metrics / results: 12/12 corrected real checks pass; flow EPEp95 1.09e-7–1.05e-6px, depth consistency on eligible queries0.98024–1.0. Four smokes each zero model exactlyB, finite loss and nonzero head gradient; 11/11 unit tests pass separately.
- Validity / common support: all projection comparisons on same valid image/depth/mask pixels. Initial incorrect denominator report retained; no frozen label or measurement thresholds altered. This does not evaluate learned coordinates or trajectories; APE/RPE/coverage/runtime system metrics Not evaluated.
- Interpretation / conclusion: real geometric labels usable; MIMIR remains unavailable. No underwater or learned-effectiveness claim.
- Follow-up: one fixed P/T fit and same-observation held-out simulation measurement.


## TA-TOR-V1-BPT-20260912
- Date: 2026-09-12.
- Status / scientific role: COMPLETE; single frozen supervised P/T comparison and held-out simulation measurement; decision NO_TEMPORAL_REFINEMENT_GAIN.
- Git commit / branch: f06ab49d4cc1e9db7d0a6c2e3af88fade841dac4; exp/temporal-observation-refinement-tartanair-v1-20260912. Model inherited byte-for-byte from39d1662. Early cache generation began at ea5fbcb with only the subsequently committed download-wait flag.
- Dataset / sequence/window: official TartanAirV1, left camera, train abandonedfactory/Easy/P000[0,1200), amusement/Easy/P001[0,734); validation carwelding/Easy/P001[0,600); test endofworld/Easy/P000[0,600), stride1, four distinct scenes selected by names/completeness.
- Environment / exact configuration: GTX1650 4GB, Torch2.2.2+cu121, Python3.8; cached raw31×31 gray patches, original KltTracker and klt_frontend.yaml; 211554 parameters, shared three-patch encoder, original4D KLT history, zero-initialized head bounded±2px/axis. Seed20260911, Adam lr.001 betas(.9,.999) eps1e-8 wd0; batch128 consecutive pairs,5000 updates/arm, validationp95 every250 incl0 selects earliest minimum. InitSHA7ecc3dc20a03f0a8c99a01aea4fb5ebccb6f2d38c863bc14f49c3f4ab6d096c4; batchSHA bdf7fcd83844b280bb8aefc35e3620c8542e7298982969f99b0924b644e642ab.
- Baseline / proposed modification: B unmodified KLT, P framewise SmoothL1 only, T adds frozen0.5 temporal error-change SmoothL1; exactly same fixed B IDs/times/count/q/sigma and same labels. No depth/pose/future image in inference.
- Commands: from /home/ma/AQUA-FE_WS_temporal_refinement_tartanair_v1, PYTHONPATH=. /mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/train_temporal_refinement.py --train /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/cache/train.npz --validation /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/cache/validation.npz --split papers/frontend_temporal_observation_refinement_tartanair_v1/data_split.json --output /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/training --device cuda. Evaluation exact command and cache generation command in report.md.
- Artifact / run paths: /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1/{cache,training,evaluation}; primary tables papers/frontend_temporal_observation_refinement_tartanair_v1/{training_summary.csv,measurement_results.csv,learning_curves.csv}; exact checkpoint paths/SHA in training table; all5001 loss rows/arm local. Metadata and invalid causes in decision.json.
- Metrics / results: valid labels/train tracks279305/68302, validation81830/19282, test166791/84061;211003 training pairs. P/T updates5000/5000, beststeps4000/4500, valp95=8.784821463/8.844387293px versus B9.052715492. Test all600 frames209862 observations, EPE median B/P/T0/0.298511624/0.303928852, p90 .996391177/1.164718032/1.114067435, p95 1.613564968/1.689463496/1.631222367px. >2px ratios .036704618/.035949182/.034384349; temporal error-change p95 .722518861/.741827387/.732637417px on82730 pairs. T/P reduction1.2388%<5%; T/Bp95 increases1.0943% rather than≥20% reduction. Last fixed blockp95 ratio1.2667>1.05; otherfive blocks pass no-harm. All age/time-block stats in CSV.
- Runtime / unavailable metrics: training walls206.17s P/138.67s T include validation and concurrent workload; not an arm speed comparison. Cached-patch inference/peakGPUmemory in training table, excludes IO/KLT/patch extraction. Actual VINS0; ATE/APE/RPE, initialization, lost-tracking, physical-time coverage, backendFPS and trajectory length Not evaluated.
- Validity / common support: allsix blocks>100 valid queries and84061 valid IDs. Same209862 rows verified acrossB/P/T, finite bounded corrections;35598 unavailablepatch rows=16.9626% retain B with zero correction. Test invalid labels43071 retained with causes;84061 birth labels make baseline median0 by definition. Replays are not independent samples; none run. One testscene limits generalization; no underwater evidence.
- Interpretation / conclusion: NO_TEMPORAL_REFINEMENT_GAIN. P/T older-age p95 decreases are descriptive positives, while overallp95 and cross-block gate fail; temporal term fails required incremental gain. OldMIMIR SUPERVISION_UNAVAILABLE unchanged; no SIMULATION_GAIN_NO_REAL_SYSTEM_GAIN because simulationgate fails.
- Follow-up: stop/archive fixed version, no second fit or A02/H02 replay.


## TA-TOR-ANCHOR-CONSISTENCY-20260912
- Date / status / role: 2026-09-12; DIAGNOSTIC_UNRESOLVED (validation predictions absent); post-hoc development diagnostic, not independent confirmation.
- Git commit / branch: inputcd615f039d7e7daa75ab5cc1b217283846d86dc8; exp/temporal-observation-refinement-tartanair-v1-20260912.
- Dataset / window: unchanged TartanAirV1 testendofworld/Easy/P000[0,600), validationcarwelding/Easy/P001[0,600); train caches read only for birth-history consistency.
- Environment / configuration: systemPython3.8+NumPy; original frozen cache/GT/checkpoints/predictions; no model library imported. Actual updates/inference/VINS/download0/0/0/0.
- Baseline / modification: sameB/P/T plus P-anchor/T-anchor, only actualbirth delta0 regardless of label validity; all nonbirth deltas, IDs, frame, q/sigma, patchvalid and GT unchanged.
- Command / artifacts: python3 papers/frontend_temporal_observation_refinement_tartanair_v1/anchor_consistency_check/analyze.py --root /mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1. Outputs comparison.csv/report.md alongside the script; no overwritten old files. Reads cache/{train,validation,test}.{npz,json}, evaluation/evaluation.json and saved B/P/T_observations.npz.
- Metrics / results: all/birth/nonbirth EPE median/p90/p95,>1/2 ratios; birth correction magnitudes; adjacent birth→next, nonbirth→nonbirth, full temporal error-change; all six100-frame blocks. Testp95B/P/T/P-anchor/T-anchor1.6136/1.6895/1.6312/1.6695/1.6237px. P/T EPEsum decreases19.71%/20.01% only by restoringbirths. NonbirthTp95 improves6.95% versusB butmedian.3960→.5019px andmean.9425→1.0005px worsen. Nonbirth temporalp95 B/P/T=.6711/.7135/.7024px; T/P gain1.55%. Anchor full temporalT/P gain2.34%<5%, lastblockT-anchor/Bp95 ratio1.2607>1.05. Original20% overallgate,5% temporalgate and crossblockgate all fail again.
- Validity / common support: test166791 labels/84061 validtracks, same209862 rows; all sixblocks remain; no left truncation in train/val/test. Birth based on full tracker history, never first valid label. Originaltest metrics/gates exactly reproduced, nonbirth outputs exact. Validation B computed; four learned-arm decompositions have missing status with known denominators, no fabricated metrics. Validation trajectories absent from all saved prediction files.
- Interpretation / conclusion: full-request DIAGNOSTIC_UNRESOLVED from missing validation arrays; test-only birth fix still insufficient under original criteria. Mixed nonbirth gains do not establish stable net benefit. Original stop unchanged; APE/RPE/real-system effects Not evaluated.
- Follow-up: end fixed diagnostic; no automatic new inference, training, download or VINS.
