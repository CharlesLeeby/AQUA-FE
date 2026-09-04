# P06 Global Window Quota Protocol V1

- Protocol identity: `isj-p06-global-quota-v1`
- Parent protocol: `isj-window-selection-v2`
- Status: `FROZEN_BEFORE_COMPLETED_SEQUENCE_SCORES`
- Outcome boundary: KLT/image-quality screening fields only

## Purpose

The parent protocol freezes per-frame scoring, sequence percentiles, history
exclusion, per-sequence ranking, and a maximum of two windows per stratum and
four total per sequence. This supplement freezes the deterministic reduction
from those sequence-capped candidates to exactly 10 low and 10 normal windows.
It does not change any score, threshold, stratum, or replacement rule.

## Candidate Order

After history-overlapping windows are removed and sequence percentiles are
computed, retain only rows selected by the parent per-sequence rule. Assign a
stable global rank within each stratum:

- low: descending score, then dataset family, sequence, and ascending start;
- normal: ascending score, then dataset family, sequence, and ascending start.

Unclassified and history-excluded windows never enter the quota pool.

## Feasible Stratum Variant

For each stratum, enumerate every six-sequence seed set whose best-ranked
window per sequence spans at least two data domains. Start the variant with
those six best windows, then fill to 10 from the stable global order while
keeping at most two windows per sequence. A variant is infeasible if it cannot
reach 10 windows.

For each exact domain set, retain the variant with the lexicographically best
objective:

1. minimum sum of global ranks;
2. minimum worst selected rank;
3. lexicographically smallest sorted rank tuple;
4. lexicographically smallest selected window-ID tuple.

## Joint Low/Normal Decision

Evaluate every retained low/normal variant pair whose union spans at least
three data domains. Select the pair with the same combined objective order:
minimum total rank sum, minimum worst rank, low rank tuple, normal rank tuple,
then the combined window-ID tuple.

The final matrix is `PASS` only when the selected pair has exactly 10 low and
10 normal windows, each stratum has at least six sequences and two domains,
the union has at least three domains, and every per-sequence cap is respected.
Otherwise the decision is `REVISE`; thresholds and strata are not changed.

## Replacement

If a selected window later fails a preregistered input/reference integrity
check, exclude that exact window and rerun this frozen quota reducer. The next
result follows the same global ranks and constraints. Learned/P/VINS outcomes
cannot trigger exclusion or replacement.
