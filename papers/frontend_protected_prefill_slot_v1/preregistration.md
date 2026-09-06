# Protected pre-refill slot admission v1: development preregistration

Date: 2026-09-06  
Status: `FROZEN_BEFORE_IMPLEMENTATION_AND_EXPORT`  
Experiment ID: `EXP-20260906-009`  
Scientific role: outcome-known six-window mechanism-development test; not held-out evidence.

## Question and evidence boundary

Can confirmed learned candidates retain a useful A09/Bus intervention while
avoiding the A02 failure if every carried KLT track is protected and candidates
compete only for capacity that would otherwise be filled by same-frame newborn
GFTT detections?

The v2 experiment showed that deleting registered startup GFTT observations is
sufficient for the A02 failure, while the A09 and Bus donor-delete controls
showed that insertion is required relative to deletion-only. Delayed v3 removed
the A02 failure but also removed the meaningful A09 rescue. This experiment
therefore tests *where candidate admission occurs in the KLT replenish cycle*;
it does not test a second delay horizon or learned-source necessity.

All six windows have already been used for development and their outcomes are
known. Results from this experiment cannot be called sequence-held-out or
window-held-out.

## Sole mechanism difference from v2

The v2 candidate source, confirmation, online-seed gates, startup timing,
quality thresholds, microburst behavior, feature cap, and upstream 50-count
reservation counter remain unchanged. The final admission mechanism changes:

1. the independent KLT mirror is split into carried observations and this-frame
   GFTT births;
2. every carried observation is retained exactly;
3. an eligible confirmed non-LoFTR candidate may occupy at most six of the
   `350 - carried_count` pre-refill slots on selected frames 0--4;
4. the remaining slots are filled by the mirror's same-frame GFTT births in
   their original deterministic order;
5. no carried KLT/GFTT observation is selected as a donor and no occupied-track
   deletion is allowed.

For this experiment, a carried observation is any mirror observation not
labelled as a same-frame age-1 `gftt` birth. An eligible candidate must be a
confirmed XFeat or confirmed SP+LG/non-LoFTR learned observation with raw age at
least 3, retaining v2's two-frame advantage over an age-1 birth. LoFTR is not
eligible.

The six-slot limit is inherited from v2 rather than tuned on an intermediate
result. The upstream 50-observation counter retains its known pre-final
reservation semantics; admission and continuation remain unseparated. No
candidate source, threshold, trigger, continuation rule, backend setting, or
timing window changes in this version.

This is not free capacity relative to the counterfactual KLT baseline: when a
candidate is admitted, one potential same-frame GFTT birth is not published.
The method protects already carried tracks, but it does not preserve every GFTT
that the baseline would have created. It is therefore not described as
intrinsically no-harm.

## Frozen common contract

- Same `VINS-Fusion-origin` binaries, per-window YAML/camera, proxy, time axis,
  IMU bounds, feature-message index, and evaluator as v2/v3.
- `MEASUREMENT_SELECTION=0`, `EXPORT_MAX_FEATURES=350`, `VINS_MAX_CNT=350`,
  `VINS_SAFE_SOURCE_SELECTION=0`, `FORMAL_THREE_LAYER_EXPORT=0`.
- `PROCESS_SKIPPED_FRAMES=1`, `PREPROCESS=adaptive_clahe`, every-n `2`,
  `FORCE_EXPORT=1`; frontend stage uses `RUN_VINS=0`.
- XFeat and SP+LG remain separate learned-source arms; LoFTR is ineligible.
- Three serial backend repeats. Repeats measure technical variability, not
  independent scientific sample size.
- Proper fixed-scale SE(3) APE and strict 1 s RPE are primary. Sim(3) and fitted
  scale are diagnostics only. Proxy agreement is not independent GT error.

## Frozen roster and methods

All six rows in `development_windows.csv` remain in the denominator:

1. A09 6000--6800;
2. A02 0--900;
3. AFRL Bus s180 d45;
4. A08 2700--3600;
5. AFRL Cemetery s135 d45;
6. Harbor H07 0--1000.

Methods are fresh KLT, protected-slot XFeat, and protected-slot SP+LG. Every
action-positive learned arm receives a newly generated same-ID/frame/dose
matched-GFTT control. Older matched controls cannot be reused because the
intervention schedule and omitted-newborn set may differ. A zero-action learned
bag may map to KLT only after byte-level identity is confirmed; that mapping is
an exact tie, not an independent replay.

## Frontend validity and stopping rule

All 18 cells must cover at least 70% of expected feature messages and never
exceed 350 observations. For every learned arm:

1. all carried mirror observations are retained byte-for-byte in every feature
   message;
2. every action occurs only on selected feature frames 0--4;
3. no action publishes LoFTR or an unconfirmed learned source;
4. every admitted candidate has raw age at least 3;
5. no frame admits more than six candidates;
6. every omitted mirror observation is an age-1 `gftt` birth; the omitted count
   is exactly `max(0, baseline_count + admitted_count - 350)` (a truly underfull
   baseline may admit a candidate without omitting a birth);
7. every zero-action full bag is byte-identical to fresh KLT.

Any violation is `REJECT_FRONTEND`. If all learned arms have zero action, the
version is `SAFE_NULL` and stops without backend replay. Persistent-cell gain,
minimum distinct IDs, and geometry-spectrum improvement are explanatory
metrics, not added gates.

## Backend comparison and frozen development decision

For every action-positive learned cell, evaluate KLT, learned, and its new
matched-GFTT control on one all-nine common support. A support must have at
least 30 common poses, at least 10 seconds, at least 70% coverage for every arm,
and the same strict 1 s RPE grid. All failures and invalid supports remain in
the full denominator.

Per active learned arm-window:

- `WIN`: learned median APE and RPE are both below KLT;
- `LOSS`: both are above KLT;
- `MIXED`: signs differ;
- `FAIL`: any repeat fails initialization/coverage or common support is invalid;
- zero-action byte identity is `exact TIE`.

Expansion is authorized only if all conditions hold:

1. no active `FAIL`;
2. no active learned arm has either median APE or median RPE more than 10%
   above KLT;
3. at least one of A09 or Bus has a joint APE/RPE improvement of at least 10%
   with actual action;
4. active joint `WIN` cells outnumber active `LOSS` plus `MIXED` cells;
5. all applicable matched controls pass structural and common-support audits.

Otherwise the decision is `NO_EXPANSION`. No second slot budget, alternate
newborn ordering, or timing variant will be tried under this experiment. If
authorized, one unified configuration must be frozen before enumerating 12 new
windows.
