# HFNet-v6 same-history positive-roster prestart parser supersession v2

Status: **FROZEN PRESTART CORRECTION; V1 NEVER STARTED**  
Frozen at: 2026-08-29T01:55:56+08:00

This amendment supersedes only the execution authority and HFNet trajectory
timestamp parser of
`hfnet_v6_samehistory_old_positive_roster_protocol_v1.md`.  The ten-case
historical-positive roster, exact-window cold-start inputs, no-retry rule,
resource gate, runability thresholds, and separate accuracy boundary are
unchanged.

## Why v1 is retired

The official HFNet-SLAM EuRoC writer sets `fixed` and writes
`setprecision(6) << 1e9 * timestamp` (`System.cc:705`).  Thus an integral
nanosecond epoch is serialized as, for example,
`1542885085174933504.000000`.  The frozen v1 runner instead called
`int(fields[0])` in `parse_trajectory()`.  This rejects the official token
before the 256 ns source-header association is attempted.

The incompatibility was reproduced outcome-blind on an older development-only
HFNet file, not on any case in this roster:

- trajectory: 245,860 bytes, SHA-256
  `ee1c860011890ebaeb07eba1fb064868bff0239a761356d1ead7b9d96e2a67ce`;
- source camera headers: 93,220 bytes, SHA-256
  `0ce637bc6e9e74a300dee7b40eb18e84962106fb7fc867d5d0eae83bf47f7662`;
- frozen v1 parser: 0 / 2,180 poses, 2,180 `ROW_n_PARSE` errors;
- v2 parser: 2,180 / 2,180 rows parsed and uniquely associated, zero errors.

This is a parser-format defect, not an HFNet failure.  Consuming the one-shot
roster under v1 would therefore create ten false terminal failures.

At this adjudication boundary the v1 roster remained exactly:

- ten `PREPARED_NOT_STARTED` manifests;
- zero permanent start reservations;
- zero process-start claims;
- zero `run_result.json` files;
- zero roster HFNet logs or trajectories;
- zero accuracy-analysis roots or outputs.

The v1 pointer, hidden bundle, runner, and prepared attempts remain immutable
for audit.  They are **RETIRED_PRESTART_PARSER_INCOMPATIBLE**, are not attempts,
and must never be run, edited, deleted, relabeled as failures, or used as
accuracy inputs.

## V2 correction boundary

The v2 runner pins the complete v1 runner byte-for-byte and changes only:

1. the pointer/runtime and prepared/claim/result namespaces to v2;
2. the case/roster authorization schemas and per-case tokens to v2; and
3. the output timestamp bridge.

The bridge parses the printed token with exact decimal arithmetic, requires a
finite integral nanosecond value, requires serialized rows to be strictly
increasing, and maps each row to exactly one source camera header within the
closed `+-256 ns` interval.  Ambiguous mapping, missing mapping, source-header
reuse, or a non-increasing canonical header closes the output audit.  Binary
floating point, fitted offsets, nearest-choice tie breaking, timestamp
snapping after the bridge, and a caller-adjustable tolerance are forbidden.

Canonical v2 authorities are:

- runner `scripts/run_hfnet_v6_samehistory_positive_roster_v2.py`, 7,639
  bytes, SHA-256
  `ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb`;
- pinned v1 runner, 80,696 bytes, SHA-256
  `9dc28f08b44c240b4623f519e6ee90dd02bbdbe177c9cacc5096aab638021ad3`;
- v2 roster builder
  `scripts/build_hfnet_v6_samehistory_positive_roster_lock_v2.py`, 2,703
  bytes, SHA-256
  `ef053fc613552a005e69b5276cfe294fa85553de0a5f5e2d209a1cb12c15079e`;
- pinned v1 roster builder, 19,892 bytes, SHA-256
  `4a8fc2f2ae1228735b1dee5f0f0f4bda7708b95d37fb42e98b14e2ef6151dd23`;
- v2 regression tests, 5,772 bytes, SHA-256
  `615afb072e0a1e36d639434a66ab6b64adb185ebb9eba0695de2716494a6348d`.

The v2-specific suite passes 9 / 9 tests.  The v2-rebound inherited governance
suite passes 26 / 26 applicable tests; the sole excluded v1 synthetic parser
test placed camera headers only 50 ns apart and is intentionally invalid under
the frozen unique-within-256-ns rule.  Its realistic-spacing replacement is in
the v2 suite.  The old development trajectory reality check also passes.

Canonical publication/runtime paths are:

- `/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_roster_execution_lock_v2.json`;
- `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/samehistory_old_positive_roster_v2`.

V2 must be built once with no-clobber publication, then all ten v2 attempts
must be prepared and audited as `PREPARED_NOT_STARTED` before the outcome-blind
accuracy prestart seal is published.  No v2 start is authorized before that
seal.  Once v2 is published, all later documents and controllers must bind the
v2 pointer, roster lock, runner, this amendment, and the new prepared manifests;
any v1 execution identity is a hard error.
