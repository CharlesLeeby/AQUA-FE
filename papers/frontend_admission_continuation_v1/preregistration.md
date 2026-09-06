# Admission/continuation separation v1 — development preregistration

Date: 2026-09-06. Experiment ID: EXP-20260906-012.
Status: FROZEN_BEFORE_IMPLEMENTATION_AND_EXPORT.

## Authority and sole research question

The user explicitly authorized this separate experiment after the completed
v2 accounting audit. This reopens only admission/continuation separation;
earlier NO_EXPANSION decisions and frozen results are not changed.

Can a truly published learned ID continue on currently valid observations
without repeatedly satisfying first-admission microburst/horizon/reservation
rules, and thereby yield net backend benefit? All six windows are development
data, not held out. No new network, preprocessing, geometry score, backend
algorithm, source, or first-admission timing is introduced.

## One mechanism: published-ID lifecycle

The source for first admission is the exact v2 exporter archived in Git object
3c50b742d6e0c69796a69813e42823e9895ed684, SHA-256
bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d.
An independent entrypoint wraps its online-seed and final-publication calls;
the frozen exporter and external backend remain unedited.

1. First admissions retain v2 candidate generation, confirmation, quality,
   FB/NCC/geometry rules, online-seed gate, microburst, frames 0–4,
   coverage-monotone newborn-donor ranking, and age advantage >=2. No future
   trajectory, future lifetime, or per-window initialization time is used.
2. Only a raw ID published on the immediately preceding output can continue.
   Its current observation must still exist immediately before online-seed
   gating and pass the same confirmed non-LoFTR source and basic age/quality/
   FB/NCC checks. Missing or invalid observations terminate the public chain;
   no interpolation, backfill, or revival of a closed raw ID is allowed.
   Absence at this stage does not establish the tracker's exact failure cause.
3. These existing IDs do not re-enter first-admission microburst, startup
   horizon, or the upstream reservation cap. Continuation has priority over
   new admissions, ordered by original public admission then public ID.
4. Every independently tracked carried KLT/GFTT observation is preserved.
   Continuing IDs reserve capacity before same-frame age-1 GFTT refill;
   if necessary omit those newborns from the end of the mirror's original
   order. This is explicit opportunity cost, not free or intrinsically safe.
   Insufficient newborn/vacant capacity terminates excess continuations;
   mature classical observations are never removed.
5. New admissions use the unchanged v2 donor rule on the remaining mirror
   with continued tracks protected. They may use only the remaining part of
   the existing six-sidecar per-frame capacity. Their realized schedule can
   therefore differ because continuation occupies slots; source and donor
   ranking are not retuned.
6. The 350 total and six sidecars/frame limits remain. The original upstream
   50-reservation counter is preserved, not silently refunded/reinterpreted.
   A separate ledger caps ALL actually published learned observations at 50
   per run, including first admission and continuation; final rejections never
   debit this publication ledger. Exhaustion terminates remaining lineages.
   This lifecycle policy, not a separate budget optimization, is the only new
   development version. No alternative cap will be tried.
7. Public IDs remain stable throughout consecutive publication. A new entry is
   recorded only after final successful publication. Per-ID events record
   continuation, termination reason, raw age/source/FB/NCC/quality, and the
   final cumulative publication count. Backend per-ID residual use remains
   Unknown without an existing receipt; do not modify VINS to instrument it.

Reset-recovered-ID / separate identity-remapping modes are outside this minimal
entrypoint and must fail explicitly if requested; the frozen six-window profile
does not enable them. No hidden offline baseline initialization prefix is used.

## Fixed roster, arms and execution

Use the exact six inputs, bounds, phase and order copied from protected-prefill
development_windows.csv into this directory: A09 6000–6800, A02 0–900,
AFRL Bus s180 d45, A08 2700–3600, AFRL Cemetery s135 d45, H07 0–1000.
Run KLT, lifecycle-XFeat, lifecycle-SP+LG in that order within each window,
18 frontend cells. LoFTR is excluded as in the governing v2 experiment.
The first completed A09 KLT/XFeat pair is the export-only probe and counts
toward the matrix; do not repeat valid receipts.

All action-positive learned cells receive a NEW same-ID/frame/dose matched
GFTT control from the existing frozen builder. Old controls cannot be reused
for a changed schedule. All unmatched chains and failures remain in the ledger.
No matched-control failure may silently remove an active cell.

Use the same per-window VINS-Fusion-origin YAML/camera/binaries and evaluation
as v2; no recompile. Freeze the backend manifest before seeing new trajectories.
Three serial repeats for every action-positive learned and matched cell.
Identity-valid KLT trajectories may be reused only with matching fresh input,
configuration, binary/environment and original receipts; reuse is not replay.
Zero-action learned bags map to KLT only after actual byte identity checks.
Retain all active failures, empty trajectories and invalid common supports.

MEASUREMENT_SELECTION=0, EXPORT_MAX_FEATURES=VINS_MAX_CNT=350,
VINS_SAFE_SOURCE_SELECTION=0, FORMAL_THREE_LAYER_EXPORT=0,
PROCESS_SKIPPED_FRAMES=1, PREPROCESS=adaptive_clahe, every_n=2,
FORCE_EXPORT=1. Source quality scales remain 1.0, vins_safe floor .80/alpha .65.
Root outputs/shadow runtime only; no writes to locked /mnt/data evidence.
Resource floors remain root 2 GiB and runtime 8 GiB. No migration or deletion.

## Validity, comparison and stopping

Frontend validity: >=70% feature-message coverage; cap <=350; <=6 learned/frame;
<=50 final learned observations; no carried classical deletion; confirmed valid
source; first admissions only at 0–4; same-ID continuation has a preceding
published observation and a current valid observation; no duplicate/resurrected
IDs; exact KLT fallback when no action. Any structural violation stops before
backend as REJECT_FRONTEND, preserving all evidence. If all cells have zero
action, SAFE_NULL stops. Length/cell/geometry gains are diagnostics, not gates.

For each active source cell, KLT/learned/new matched control use one all-nine
common support: >=30 common poses, >=10 seconds, >=70% coverage for every
arm/repeat, identical strict 1 s RPE grid. Proper fixed-scale SE(3) APE/RPE are
primary, with evo cross-check. Sim(3) and fitted scale are explicit diagnostics,
never silent scale fitting. Reference is COLMAP/proxy, not independent GT.

Per cell on three-repeat medians: WIN if both errors lower; LOSS if both higher;
MIXED if signs differ; TIE for exact equality; FAIL for a failed repeat or invalid
support. Show absolute APE/RPE, ranges, initialization time and coverage, and
learned versus matched. Compare also with original v2 on a re-associated common
support, not metrics stitched from different time intervals. Repeats are not
independent windows. Keep all 12 learned arm-windows in the outcome denominator.

Expansion requires all inherited conditions: no active FAIL; no active median
APE or RPE regression >10% versus KLT; >=10% joint improvement in at least one
action-positive A09/Bus cell; active WIN count greater than LOSS+MIXED; all
matched structural/support checks pass. Otherwise NO_EXPANSION. No second
lifecycle variant or parameter search under this experiment. If passing, freeze
one global source/config before a separately preregistered 12-window extension;
never select sources post hoc per window. No target number of wins is a stop goal.

Budget: 18 frontend cells, <=24 matched/learned active bags (<=72 new replays),
at most 18 fresh KLT replays only if identity reuse fails, three repeats each.
No other dataset/window or algorithm experiment is authorized by this freeze.
