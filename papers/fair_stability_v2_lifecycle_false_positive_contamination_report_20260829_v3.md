# Fair-stability v2 lifecycle false-positive contamination report

Date: 2026-08-29 (Asia/Shanghai).  This is a v3 provenance document about the
v2 namespace; it does not rewrite any v2 artifact.

## Decision

The prepared and partially started experiment at
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v2`
is retained as an immutable diagnostic record but is control-invalid for a
formal stability comparison.  No v2 outcome may enter an algorithm-stability
denominator.  A prospective v3 namespace must restart at planned ordinal 1;
no v2 attempt, receipt, cache, or summary may be imported.

No v3 backend/control freeze, attempt preparation, or estimator execution had
been performed when this report was written.

## Observed v2 outcome

Only planned ordinal 1 was started:
`a05_3300_3700 / learned_klt_vins / repeat 1 / attempt 1`.
It ran from `2026-08-29T07:15:23+00:00` to
`2026-08-29T07:16:08+00:00`.  The result was labelled `PIPELINE_INVALID` with
the sole pipeline code `SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN` and no algorithm
failure code.

The underlying evidence does not support a real residual-process failure:

- rosbag returned 0 and was reaped;
- VINS was alive with exact identity at bag end, produced a nonempty
  trajectory, received SIGTERM, returned 143, and was reaped without SIGKILL;
- roscore passed its identity check and was reaped without SIGKILL;
- the Python supervisor independently recorded an empty supervised process
  group after wait;
- the continuous resource monitor was proven, reported no intrusion and no
  monitor error; and
- the diagnostic trajectory had 190 poses and 0.95 coverage.

Nevertheless, `child_lifecycle.txt` recorded four residuals:
`3189777:S,3189778:R,3189779:S,3189780:S`.

## Root cause

The frozen v2 child wrapper implemented `group_residuals` as a
`ps | awk | paste` pipeline and invoked it through command substitution.  Bash
therefore created a command-substitution process plus the three pipeline
processes in the wrapper's own process group.  The scan observed those four
short-lived observer processes while they were still alive and reported them
as residual descendants.  This is a deterministic observer-induced false
positive, not evidence that VINS, roscore, or rosbag survived reap.

The v2 ordinal controller had a second unsafe consequence: it allowed
`SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN` to be automatically adjudicated as an
external pipeline fault and could then prepare unbounded same-cell
replenishments up to its generic attempt-index limit.  No v2
`pipeline_invalid_receipt.json` or replacement attempt was created before the
namespace was stopped.  V3 must instead halt on lifecycle/control/identity/
configuration/model drift, allow automatic replacement only for explicitly
external transient faults, cap each planned cell at two replacement attempts,
and halt immediately if an allowed pipeline code repeats.

## Evidence identities

| Artifact | SHA-256 |
|---|---|
| v2 child wrapper | `3a7d8c4caefc055f55c2ed5f1b665333ed7768c6884aa30925aba7e39ca090a8` |
| v2 ordinal controller | `6e9b29e202ef600b8f94697955509a8253d0cec8a641c64484867eb7080c0d22` |
| v2 ordinal common | `ce0c058cde8a90d13d26e35b4a4e271c4ed137a2f3b0db25fe7a77b9eca692d1` |
| v2 attempt-matrix freeze | `5a44aca0abe2826c445dc55ac6b5cc6fb57f990cc5b3aee923c63014afbdb579` |
| ordinal-1 lifecycle receipt | `62151e2accfb77b0a9b6e8e7fbd475549388ad197e15b82df1a8ccc42fa31b63` |
| ordinal-1 run result | `7c85bdaa344780ecb9fa1a2f2a9cac71e5b1bf9c1d600ba297993e69f6a703aa` |
| ordinal-1 runtime monitor | `4a2af66ce2594a30c95d67f541c66f05a42a75b313cc293e8454891bf57d30dc` |

## V3 correction boundary

The v3 child residual scan must use Bash builtins and `/proc` file reads in the
current shell, directly updating `DESCENDANT_RESIDUALS` and
`DESCENDANT_RESIDUAL_COUNT`.  It must not start `ps`, `awk`, `paste`, or a
command-substitution scanner.  The v3 freeze must bind this report and
`fair_stability_v1_runtime_contamination_report_20260829.md` by absolute path,
byte size, and SHA-256.
