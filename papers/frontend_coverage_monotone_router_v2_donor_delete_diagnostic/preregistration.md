# V2 donor-delete-only diagnostic: preregistration

Date frozen: 2026-09-05 (Asia/Shanghai)
Status at freeze: **outcome-known development diagnostic; new donor-delete-only
backend outcome not observed**
Scientific role: route D, chosen after the complete frozen v2 backend result.
This is not a held-out experiment and is not a new proposed method.

## Question and evidence boundary

The frozen v2 result has a repeatable A02 regression for both the XFeat
replacement and its matched-GFTT replacement. Both interventions delete the
same KLT/GFTT donor observations and insert a replacement, so donor deletion
and replacement insertion remain confounded. This diagnostic asks whether
**deleting the donor observations alone is sufficient to cause the A02
regression**.

Only the already observed A02/XFeat intervention is tested. No thresholds,
gates, frontend implementation, feature budget, backend source, backend YAML,
window, proxy, time axis, or evaluation gate may change. The COLMAP trajectory
is a proxy reference, not independent ground truth.

## Frozen window and exact intervention

- Window: `aqualoc_archaeology:A02:0000`, run slug `a02_0_900`.
- Source bag: the fresh v2 KLT bag identified in `contract.json`.
- Feature topic: `/feature_tracker/feature`.
- Counterfactual operation: remove exactly the following eight feature
  observations, keyed by message timestamp and feature ID, and insert nothing:

| timestamp ns | removed IDs |
|---:|---|
| 1542828791986278080 | 362, 363, 365 |
| 1542828792085880800 | 371, 372, 373 |
| 1542828792185715008 | 376, 377 |

All message timestamps, topics, feature order for retained observations,
per-feature channel values, IMU messages, proxy messages, and other messages
must remain unchanged. The three edited frames contain 347, 347, and 348
features after deletion; the 350 cap is never exceeded. No future information
is used to create the bag: the deleted timestamp/ID pairs are exactly the
donors already recorded by the frozen online v2 action audit.

The derived bag is invalid unless an export-only structural audit confirms:

1. exactly eight and only the registered observations are absent;
2. every target exists exactly once in the source bag;
3. all retained feature data are byte-for-byte equal after serialization;
4. all non-feature messages are byte-for-byte equal after serialization;
5. topic/message counts and timestamps are unchanged; and
6. no learned-source feature is introduced.

## Frozen arms and replay roster

Four arms are compared on one exact common support:

1. fresh KLT (existing three frozen v2 replays);
2. v2 XFeat replacement (existing three frozen v2 replays);
3. matched-GFTT replacement for XFeat (existing three frozen v2 replays);
4. donor-delete-only (three new replays).

Only arm 4 is newly replayed. Existing outputs may be reused only when their
receipts, feature-bag hash, canonical-config hash, VINS node hash, and VINS
library hash pass the frozen identities in `contract.json`. Repeated backend
replays measure technical stability; they are not independent scientific
windows.

Run order is donor-delete-only repeats 1, 2, 3. Stop after these three runs;
do not add windows, arms, or parameters in this diagnostic.

## Frozen runability and common-support gates

Each repeat must contain the VINS `Initialization finish!` marker, a nonempty
trajectory, and at least 70% trajectory-span coverage relative to the proxy
span. Failures and empty trajectories remain in the denominator.

Accuracy is evaluated only if all 12 trajectories (four arms times three
repeats) pass runability and the exact common support has:

- at least 30 common poses;
- at least 10 s common span;
- at least 70% common coverage; and
- at least 10 strict 1 s RPE pairs.

The primary metric is translational APE RMSE after each trajectory's own proper
fixed-scale SE(3) alignment. The secondary metric is translational RPE RMSE on
the same strict 1 s grid. Sim(3) APE/RPE and fitted scale are reported only as
scale diagnostics; Sim(3) is never silently substituted for the primary
metric. Results are the median and full range of the three replays. The
repository evaluator is run with its independent `evo` cross-check.

## Frozen decision rule

The normal-texture no-harm boundary from `papers/frontend_baseline_protocol.md`
is retained: APE/RPE may not be worse by more than 5%; on a short window, an
absolute APE difference below 0.01 m is tolerated; initialization must be
equal. No new numerical threshold is introduced.

- `DELETE_SUFFICIENT`: donor-delete-only initializes equally but fails the
  existing no-harm boundary versus KLT in both APE and RPE, in the same harmful
  direction as the learned and matched replacements. This establishes that
  deletion alone is sufficient for material harm, not that insertion has zero
  effect.
- `INSERTION_DOMINANT`: donor-delete-only passes the existing no-harm boundary
  versus KLT while both already observed replacement arms fail it. This
  implicates insertion/replacement content rather than donor deletion as the
  dominant tested cause.
- `MIXED_OR_INCONCLUSIVE`: any other valid pattern, or failure of the four-arm
  common-support gate.

Regardless of outcome, this diagnostic cannot establish general superiority,
natural positive-window rate, or a deployable no-harm policy. New-window
expansion remains blocked unless a unified method first passes the existing
development no-harm standard.
