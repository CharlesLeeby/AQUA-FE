# Delayed newborn-slot router v3: development preregistration

Date: 2026-09-05  
Status: `FROZEN_BEFORE_V3_IMPLEMENTATION_AND_EXPORT`  
Experiment ID: `EXP-20260905-008`  
Scientific role: outcome-known six-window development test; not held-out evidence.

## Question and evidence boundary

Can the same coverage-monotone newborn exchange used by v2 avoid its A02
startup failure when the entire intervention interval is moved after a single
global startup-protection horizon, while retaining at least one registered
A09/Bus benefit?

The positive-delete diagnostic showed that A09 and Bus require candidate
insertion relative to delete-only, but matched GFTT also succeeds. A02 showed
that its registered startup deletions are sufficient for severe failure. This
version therefore tests intervention timing, not learned-source necessity.

All six windows are the already-used v2 development windows in
`development_windows.csv`. Their outcomes, baseline initialization times, and
candidate summaries were inspected before this freeze. No result here is
sequence-held-out or window-held-out.

## Sole mechanism difference from v2

The only algorithmic change is the globally fixed selected-feature-frame
intervention interval:

- v2: online-seed warmup `0`, final newborn-exchange frames `0--4`;
- v3: online-seed warmup `32`, final newborn-exchange frames `32--36`.

Frames `0--31` reject sidecars before sequence-budget accounting and must
publish the fresh KLT mirror exactly. Frames `32--36` use the unchanged v2
candidate source, confirmation, quality, microburst, dose, donor ordering,
age advantage, source filter, and 4-by-6 coverage-monotone rule. Frames after
36 again reject sidecars at final arbitration. The inherited 50-observation
counter remains a pre-final reservation counter; this version does not repair
or reinterpret it. Admission and continuation remain unseparated.

The horizon was selected once from the maximum fresh-KLT initialization point
in the six development windows: all 18 baseline replays initialize before the
feature message at selected index 31; v3 begins at index 32. This is an offline,
outcome-known development choice. It is not an online initialization signal and
does not guarantee initialization on a new window.

At full capacity, v3 still substitutes an age-1 GFTT observation. It preserves
tracked KLT and older GFTT observations but does not preserve every potential
newborn GFTT; it is not intrinsically no-risk and is not called a natural-empty-
slot method.

## Frozen common contract

- Same `VINS-Fusion-origin` binaries, per-window YAML/camera, proxy, time axis,
  IMU bounds, feature-message index, and evaluator as v2.
- `MEASUREMENT_SELECTION=0`, `EXPORT_MAX_FEATURES=350`, `VINS_MAX_CNT=350`,
  `VINS_SAFE_SOURCE_SELECTION=0`, `FORMAL_THREE_LAYER_EXPORT=0`.
- `PROCESS_SKIPPED_FRAMES=1`, `PREPROCESS=adaptive_clahe`, every-n `2`,
  `FORCE_EXPORT=1`; frontend stage uses `RUN_VINS=0`.
- XFeat and SP+LG remain separate learned-source arms; LoFTR is ineligible.
- Three serial backend repeats; repeats measure technical stability, not
  independent scientific sample size.
- Proper fixed-scale SE(3) APE and strict 1 s RPE are primary. Sim(3) and fitted
  scale are diagnostics only. Proxy agreement is not independent GT error.

## Frozen roster and methods

All six rows of `development_windows.csv` remain in the denominator:

1. A09 6000--6800;
2. A02 0--900;
3. AFRL Bus s180 d45;
4. A08 2700--3600;
5. AFRL Cemetery s135 d45;
6. Harbor H07 0--1000.

Methods are fresh KLT, delayed-router XFeat, and delayed-router SP+LG. Every
action-positive learned arm receives a newly generated same-ID/frame/dose
matched-GFTT control. Old v2 matched controls may not be reused for a changed
action schedule. Zero-action learned bags may map to KLT only after byte-level
identity is confirmed; such mappings are ties, not independent replays.

## Frontend validity and stopping rule

All 18 cells must cover at least 70% of expected feature messages and never
exceed 350 observations. For every learned arm:

1. feature messages at selected indices 0--31 are byte-identical to KLT;
2. all actions occur only at selected indices 32--36;
3. no tracked KLT or GFTT older than age 1 is removed;
4. raw age advantage is at least 2;
5. no donor cell becomes empty and occupied grid-cell count never decreases;
6. no frame admits more than six sidecars;
7. every zero-action full bag is byte-identical to KLT.

Any violation is `REJECT_FRONTEND`. If all learned arms have zero action, the
version is `SAFE_NULL` and stops without backend replay. No persistent-cell,
minimum-ID, or geometry-spectrum gain is an additional gate.

## Backend comparison and frozen development decision

For every action-positive learned cell, evaluate KLT, learned, and its new
matched-GFTT control on one all-nine common support. A support must have at
least 30 common poses, at least 10 seconds, at least 70% coverage for every arm,
and the same strict 1 s RPE grid. Failures and invalid supports remain in the
full denominator.

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
3. at least one of A09 or Bus retains a joint APE/RPE improvement of at least
   10% with actual action;
4. the number of active joint `WIN` cells exceeds active `LOSS` plus `MIXED`
   cells;
5. all applicable matched controls pass structural and common-support audits.

Otherwise the decision is `NO_EXPANSION`; no second v3 parameter or horizon is
tried. If authorized, one unified configuration is frozen before enumerating
the 12 new windows.
