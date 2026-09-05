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
