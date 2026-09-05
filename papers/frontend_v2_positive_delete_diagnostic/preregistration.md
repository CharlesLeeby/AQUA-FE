# V2 positive-window donor-delete-only diagnostic: preregistration

Frozen at: `2026-09-05T22:31:00+08:00`

Status at freeze: **outcome-known development windows; donor-delete-only backend outcomes not observed**

Experiment ID: `EXP-20260905-007`

## Question and scope

The completed v2 matrix contains two XFeat wins relative to fresh KLT: AQUALOC A09
6000–6800 and AFRL Bus s180 d45. In both cells, learned replacement and its matched-GFTT
control delete the same registered donor observations and add a replacement. This diagnostic
asks whether deletion alone is sufficient for the positive direction, or whether adding the
candidate is required.

This is a mechanism diagnostic on already used development windows, not held-out evidence.
COLMAP/proxy is not independent ground truth. No frontend gate, threshold, feature budget,
backend source, backend YAML, time axis, proxy, evaluation rate, or common-support gate may
change.

## Frozen windows and deletion sets

Only the XFeat action cells are included:

| order | window | run slug | timestamp ns | donor IDs | added XFeat IDs in v2 |
|---:|---|---|---:|---|---|
| 1 | AQUALOC Archaeology A09 6000–6800 | `a09_6000_6800` | 1542889046271565680 | 944 | 10000000 |
| 1 | AQUALOC Archaeology A09 6000–6800 | `a09_6000_6800` | 1542889046371444368 | 1086 | 10000000 |
| 1 | AQUALOC Archaeology A09 6000–6800 | `a09_6000_6800` | 1542889046471564144 | 1320 | 10000000 |
| 2 | AFRL Bus s180 d45 | `afrl_bus_s180_d045` | 1494876660116016699 | 487, 500 | 10000000, 10000001 |

Each control starts from the frozen fresh-KLT bag. It removes exactly these timestamp/ID
pairs and inserts nothing. All retained observations, per-feature values, message order,
timestamps, topics, IMU, proxy, and other messages must remain unchanged. A derived bag is
invalid unless a serialization-level structural audit confirms the registered deletion set,
unchanged non-target content, unchanged message counts/timestamps, and zero learned features.

No donor, frame, window, arm, or tolerance may be added after any donor-delete backend result
is seen.

## Frozen arms, order, and reuse

For each window, compare on one exact common support:

1. `B`: fresh KLT, three existing frozen v2 replays;
2. `B-D`: donor-delete-only, three new replays;
3. `B-D+L`: v2 XFeat replacement, three existing frozen v2 replays;
4. `B-D+C`: same-ID/frame/dose matched GFTT, three existing frozen v2 replays.

Existing trajectories may be reused only if their receipt, feature-bag, backend-config, VINS
node, VINS library, and trajectory hashes satisfy the frozen identities. Reuse is not counted
as a new replay. New replay order is fixed as:

`A09 r1, A09 r2, A09 r3, Bus r1, Bus r2, Bus r3`.

The stop condition is exactly six new replay attempts. Failures remain in the denominator.

## Frozen validity and metrics

Each repeat requires `Initialization finish!`, a nonempty trajectory, and at least 70%
trajectory-span coverage relative to its proxy. Accuracy is evaluated only if all 12
trajectories for that window are runable and their exact common support has at least 30 poses,
10 s span, 70% coverage, and 10 strict 1 s RPE pairs.

Primary: translation APE RMSE after each trajectory's own proper fixed-scale SE(3) alignment.
Secondary: translation RPE RMSE on the same strict 1 s common grid. Sim(3) APE/RPE and fitted
scale are reported only as diagnostics. Run the independent evo cross-check. Report all three
repeats, their median, and full range; repeats measure technical stability and are not
independent scientific samples.

## Frozen attribution rule

For each window:

- `DELETE_REPRODUCES_MAIN_WIN`: `B-D` has lower median fixed-scale APE and RPE than `B`, and
  for both metrics `B-D` is closer in absolute error to `B-D+L` than to `B`. This means the
  registered deletion set is sufficient for the win direction and accounts for more than
  half of the observed absolute KLT-to-learned gap under this four-arm intervention; it does
  not prove insertion has zero effect or any donor is individually causal.
- `DELETE_DIRECTION_ONLY`: `B-D` improves both primary metrics versus `B` but fails the
  closeness condition for at least one metric.
- `INSERTION_REQUIRED_FOR_WIN`: `B-D` does not improve both metrics versus `B`, while
  `B-D+L` does.
- `MIXED_OR_INCONCLUSIVE`: common support fails or none of the above patterns applies.

Always report the conditional insertion deltas `(B-D+L) - (B-D)` and `(B-D+C) - (B-D)`.
The two windows may receive different mechanism classifications; no pooled label may hide
that difference. `DELETE_REPRODUCES_MAIN_WIN` establishes sufficiency only for the tested
registered deletion set. It is not a learned-feature claim and does not establish necessity,
population prevalence, or general superiority.

## Post-diagnostic decision boundary

This diagnostic alone cannot authorize v2 expansion. It will be combined with the already
frozen A02 `DELETE_SUFFICIENT` result and the read-only lineage budget audit to select exactly
one minimal development version. No second mechanism, new network, matcher, enhancement,
geometry threshold, or per-window tuning is permitted in that version.
