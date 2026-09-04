# ORB-SLAM3 v23 post-init follow-up: deduplicated cross-dataset analysis

## Analysis question

After the AQUALOC search, how many unique ORB-v23 mechanism-positive windows exist, how many
are operationally degraded/low-grid, and which windows satisfy the frozen repeatwise trajectory
criterion after adding the NTNU mclab1 and mclab2 formal matrices?

## Unit and rule

The independent unit is a fixed image interval. Selector variants (`n3`, `n6`) and rearm assets
from the same interval are robustness observations, not new windows. Four formal repeats are
deterministic reproducibility checks. The repeatwise strict rule is the existing AQUALOC rule:
in every repeat, reconstructed and online APE/RPE for `full` must be lower than native/drop and
the same-repeat `full_unbounded` shadow.

## Window-level result

The deduplicated mechanism-positive roster contains five windows: AQUALOC A10 `2400-2800`,
AQUALOC A02 `2800-3200`, AQUALOC A08 `4500-4660`, NTNU mclab2 `s110,d10`, and NTNU mclab1
`s60,d15`. The first three are inherited from the frozen AQUALOC search; the last two are
new NTNU follow-up matrices.

Under the project's promoted strict label, A10, A02, and mclab1 are trajectory positives. A10's
unbounded shadow has an alternate map branch in repeat 2, so a stricter all-control repeatwise
audit records `3/4` against that shadow and counts only A02 and mclab1. Both labels are retained
because the existing project evidence uses native/drop as the primary accuracy control and
unbounded as the causal shadow.

| Window | Level in this audit | Action | Texture |
|---|---|---|---|
| A10 `2400-2800` | project strict; 3/4 all-control repeatwise audit | 52 matches, 15 outliers, 13/13 purge | normal/non-low; KLT saturated at cap |
| A02 `2800-3200` | project strict and all-control repeatwise strict | 7, 3, 3/3 | operational degraded/planar/low-grid |
| A08 `4500-4660` | action-positive, metric-mixed | 32, 23, 10/10 | operational degraded/planar/low-grid |
| NTNU mclab2 `s110,d10` | action-positive, metric-mixed | 45, 16, 8/8 | normal; 341-350 classical features |
| NTNU mclab1 `s60,d15` | project strict and all-control repeatwise strict | 7, 2, 1/1 | normal/mixed; mean 346.93 features |

## Texture denominator

Among all five mechanism-positive windows, operational degraded/low-grid windows are A02 and
A08: `2/5 = 40%`. Among the project's promoted strict subset (A10, A02, mclab1), only A02 is
operationally degraded: `1/3 = 33.3%`. A stricter all-control repeatwise audit has two windows
(A02, mclab1), again with one degraded window (`1/2 = 50%`). Under a narrower definition requiring sparse base KLT below the
350-feature cap, none of the five qualify (`0/5`). A02/A08 are degraded/planar/low-grid windows
with near-saturated base KLT, not genuinely sparse-base windows.

## New NTNU evidence

### mclab1 n3

The formal five-arm x four-repeat matrix completed `20/20` with status `ok`, no overflow or
conservation failure, and `64/64` reconstructed/online directional checks. Full action was
stable at 7 assisted matches, 2 assisted outliers, and one pre-KF purge. Full means were
`0.018007/0.062446` reconstructed APE/RPE and `0.035048/0.062985` online, versus native/drop
`0.018122/0.062520` and `0.052752/0.063240`. This is a strict independent NTNU window.

The n6 selector on the same interval is retained as a robustness case only: it is action-positive
but online metric-mixed. It does not increase the window denominator.

### mclab2 n3

The formal matrix also completed `20/20` with stable action (`45/16/8` matches/outliers/purges),
but the trajectory is metric-mixed: reconstructed APE improves versus native while reconstructed
RPE worsens, and both online metrics worsen versus native. The n6 selector is the same window and
is likewise a robustness case. This is cross-dataset action reachability, not a strict accuracy
positive.

## Statistical validation

No inferential test is appropriate. Each window has `n=1` independent interval; repeat means and
sample SDs describe deterministic branch reproducibility only. The directional checks and action
counters are pre-specified mechanism checks. See `formal_summary.csv` and `texture_denominator.csv`.

## Limits and correction

The search queue is mechanism-selected and cannot estimate deployment success probability. The
operational low-texture label is not interchangeable with sparse KLT texture. The existing
`logs/orb_v23_postinit_search_20260802_final.md` promoted A10 as strict; the underlying A10 report
records `3/4` repeatwise dominance versus unbounded. This follow-up preserves the project label,
adds the stricter audit count, and makes the discrepancy explicit.

The mclab2 `seed_export_stats.json` records a maximum feature-to-image timestamp difference of
`49,999,500 ns`. The selected ORB `cam0_times` are exact; the nonzero maximum is retained as an
alignment caveat rather than silently treated as zero.

## Decision

Stop rerunning mclab1/mclab2 selector variants or rearm assets. Promote mclab1 as the new strict
NTNU ORB window, retain mclab2 as action-positive mixed evidence, retain A02 as the operationally
degraded strict window, and preserve A08/A10 plus fjord3/fjord4/AFRL/UVVID exclusions as boundary
evidence. Do not claim a genuine sparse-base low-texture ORB positive from this roster.
