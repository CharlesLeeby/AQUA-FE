# Coverage-monotone newborn-exchange router v2: development preregistration

Date: 2026-09-05
Status: `FROZEN_BEFORE_V2_IMPLEMENTATION_AND_EXPORT`
Scientific role: development-only mechanism test on outcome-known controls.

## Question and evidence boundary

Can a coverage-monotone age-1 GFTT donor exchange recover the early learned
opportunities suppressed by geometry-maturity router v1, without reopening its
successfully blocked late mature-track path?

The six windows in `development_windows.csv` are copied unchanged from v1.
Their historical outcomes and v1 gate failures are known, so no result on them
is confirmatory. V2 may be frozen for paper evaluation only after it passes this
development Go/No-Go and is then evaluated on a new non-overlapping,
outcome-blind roster.

## V2 structural contract

V2 changes only final frontend arbitration and remains default off.

1. The independently tracked KLT/GFTT mirror is authoritative.
2. Only KLT-confirmed non-LoFTR learned lineages are eligible. XFeat and SP+LG
   remain separate source arms.
3. A `source=klt` observation is never removed.
4. At a full 350-point budget, an admitted sidecar may replace only a
   `source=gftt`, raw-age-1 birth.
5. The learned sidecar raw age must exceed the victim age by at least 2.
6. Action remains restricted to selected feature frames 0--4 and at most six
   admitted sidecars per frame.
7. Geometry uses a fixed 6-column by 4-row image grid.
8. For each candidate, prefer an eligible victim in the same cell. If none
   exists, a cross-cell donor is allowed only when removing it leaves at least
   one published observation in the donor cell.
9. After each sequential exchange, the number of occupied grid cells must not
   decrease. Donor choice is deterministic: same-cell first, then greatest
   current donor-cell occupancy, then the pre-existing weakest-GFTT order.
10. The v1 global GFTT-birth ratio is disabled. Safety is enforced per actual
    victim and per exchange, rather than by requiring a window-wide abundance
    of newborns.
11. Sidecars failing source, confirmation, horizon, age, donor occupancy,
    grid-monotonicity, or cap checks are removed before publication.
12. If no sidecar survives, the feature message must be byte/field identical
    to fresh KLT. LoFTR remains ineligible even with vacant capacity.

No dataset-specific threshold, recovery-reason token, backend state, proxy
trajectory, or historical outcome enters this rule.

## Frozen common frontend contract

- `MEASUREMENT_SELECTION=0`
- `EXPORT_MAX_FEATURES=350`, `VINS_MAX_CNT=350`
- `VINS_SAFE_SOURCE_SELECTION=0`
- `FORMAL_THREE_LAYER_EXPORT=0`
- `PREPROCESS=adaptive_clahe`
- `PROCESS_SKIPPED_FRAMES=1`
- `SEMIDENSE_FALLBACK_METHOD=none`
- `FORCE_EXPORT=1`, `RUN_VINS=0`
- `every_n=2`
- AQUALOC `FRAME_OFFSET=1`; AFRL `FRAME_OFFSET=0`
- backend quality mode `vins_safe`, floor `0.80`, alpha `0.65`, all source
  scales `1.0`
- all upstream seed-chain gates and the 50-observation sequence budget remain
  unchanged from v1

## Frozen roster and arms

The six exact inputs and SHA-256 values are in `development_windows.csv`:

- opportunity: A09 6000--6800, A02 0--900, AFRL Bus s180 d45;
- safety: A08 2700--3600, AFRL Cemetery s135 d45, H07 0--1000.

The arms in `arms.csv` are fresh KLT, v2+XFeat, and v2+SP+LG. No row or arm may
be removed after v2 output is observed. Missing and failed cells remain in the
ledger.

## Export-only validity and Go/No-Go

Every cell must publish at least 70% of expected feature messages and never
exceed 350 points.

Safety passes only if all hold:

1. every removed observation is age-1 `gftt`; tracked KLT and older GFTT are
   never removed;
2. every replacement has raw age advantage at least 2;
3. every donor cell retains at least one output observation;
4. occupied 6-by-4 grid-cell count never decreases on an action frame;
5. no frame admits more than six learned sidecars;
6. every zero-action learned bag is byte-identical to fresh KLT;
7. A08, AFRL Cemetery, and H07 are zero-action for both learned arms.

Opportunity passes only if both hold:

8. at least two of A09, A02, and AFRL Bus are action-positive across the union
   of learned arms;
9. at least one admitted learned lineage appears on at least two output frames.

If any safety item fails, v2 is `REJECT_SAFETY` and stops. If safety passes but
opportunity fails, v2 is `SAFE_NULL` and stops. If both pass, a matched-GFTT
lineage control must be attempted for every active lineage before any backend
work. Unmatched lineages are reported, never silently dropped.

## Backend boundary if export-only and matched control pass

Only a smoke set is authorized: every action-positive opportunity cell, fresh
KLT, its learned arm, and its matched classical control, plus the three
zero-action safety controls. The same VINS-Fusion-origin build/YAML, three
serial repeats, common support, proper fixed-scale SE(3), diagnostic Sim(3),
and proxy wording from confirmatory-v3 must be used. Repeats measure technical
stability, not independent scientific samples.

## Frozen interpretation

Development success only licenses a new untouched confirmation roster. It
cannot establish superiority over KLT or SP+LG. If matched classical equals or
beats the learned arm, the result is track-management evidence rather than a
learned-source contribution.
