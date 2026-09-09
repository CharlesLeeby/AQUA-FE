# A02 initialization trace and bounded repair — diagnostic preregistration

Date: 2026-09-09 (Asia/Shanghai). ID: EXP-20260909-A02-INIT-TRACE.
Authority: user requested “查清楚并修复” after the completed degradation audit.
This is a new, outcome-known development diagnostic. EXP-20260906-012 remains
COMPLETE / NO_EXPANSION; no original protocol, input, result or gate is replaced.

## Stage 1: observe the numerical fork, before choosing a repair

Fixed window: A02 0–900. Fixed inputs: original fresh v2 KLT and original
eight-observation donor-delete-only bags, identified by their existing manifests.
No new donor, bag, source, window, geometry or backend algorithm is introduced.
Run order: KLT repeat 1, delete repeat 1, KLT repeat 2, delete repeat 2,
KLT repeat 3, delete repeat 3. Six diagnostic replays, not six windows.

Use the original VINS node/library and canonical YAML/camera byte-for-byte.
The only intentional execution difference is VINS_INITIAL_DIAGNOSTICS=1.
The existing compiled switch only prints linear/refined scale and gravity norm;
it does not change the algorithm, acceptance thresholds or bias rollback.
Do not turn on any other initialization option. No backend edit/recompile.
Original replay rate 1.0, three-second bag delay and eight-second drain remain.
Record input/config/binary/environment identity and preserve every failure.
New runtime: /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a02_init_trace_repair_v1.
No /mnt/data writes or overwrites of old results. Root >=2 GiB/runtime >=8 GiB.

Main diagnostic: every attempted linear scale, gravity norm, refined scale when
reached, and accept/reject condition under the unchanged source. Compare the
trace across all three repeats and with old rejection counts/first pose time.
Gravity tolerance remains 0.5 and negative scales are rejected as in the binary;
these are observed backend rules, not newly tuned gates. Printed precision is
six decimals, so values within rounding distance of a boundary are Unknown.
Logging can affect scheduling; disagreement with old runs must be reported.

If trajectory comparisons are made, reuse the existing proper fixed-scale SE(3)
APE/strict 1s RPE evaluator and independent evo check. Sim(3) and fitted scale are
explicit diagnostics. Require all repeats >=70% trajectory coverage and one
all-arm/repeat common support >=30 poses, >=10 s, >=70% coverage, >=10 strict
1s pairs. Never substitute fitted scale for the primary metric. COLMAP/proxy
is not independent GT. No scoring is needed to select which trace to report.

## Stage 2: one evidence-backed frontend repair, separately frozen before testing

First complete the six traces. Then record a separate repair contract with one
mechanism, exact scope, tests and stopping rule before any repair experiment.
No automatic second timing/budget/routing variant or parameter search. Do not
change the fixed external backend to cure a frontend comparison. A safety
fallback that equals KLT must be called a fallback, not a learned improvement.
Any gain sacrificed must be reported, including A09/Bus. A repair preserving
gain is Not evaluated until its full registered validation succeeds.
No new-window expansion is authorized by this diagnostic.
