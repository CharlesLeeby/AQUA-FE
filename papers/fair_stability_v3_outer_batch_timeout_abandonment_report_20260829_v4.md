# Fair-stability v3 outer-batch timeout abandonment report

Status: **PERMANENTLY ABANDONED FOR INFERENCE; RETAINED READ-ONLY FOR FORENSICS**  
Date: 2026-08-29  
Successor authority: `fair_stability_control_supersession_v4.md`

## Decision

The formal v3 experiment at
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v3`
is permanently abandoned.  It must not be resumed, repaired, relabelled, or
used as a partial formal result.  Its first six terminal results and interrupted
seventh attempt are forensic pilot evidence only and are not imported into v4.

The outer multi-ordinal batch invocation reached its external timeout while
ordinal 7 was running.  The detached HFNet estimator survived loss of its
Python/controller ancestors and was subsequently terminated by the operator.
The operator action is contemporaneous incident information; v3 contains no
independent cleanup receipt that proves the signal or actor.  The filesystem
does independently prove that the estimator was launched and that the formal
supervision/result chain was never completed.

## Frozen v3 identities

| Artifact | Size (bytes) | SHA-256 |
|---|---:|---|
| `experiment_manifest.json` | 113639 | `17d508a53f25990243cedf8d1d17f8bcc5388f2416dd89f64c86eb0f9b6233ce` |
| `planned_schedule.json` | 12957 | `8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8` |
| `vins_dev_nativeq_schedfix_runtimeexcl_v3/backend_freeze.json` | 188896 | `0b6162654e16adec88e235cb05b404d438880b055e5d48a472355f9448b3a7e9` |
| `attempt_matrix_freeze_v3.json` | 88655 | `119519b75a64369237dd8fbeed349115fecbb59727c7cbd83ae43deec3e2f3d1` |
| `fair_stability_progress_summary_v3.json` | 53872 | `d04a0a347f7e8f6b803c6a171b2d162897bbe4e64d9c42d101010208bbc5cfc0` |

The six terminal ordinal-receipt hashes are, in ordinal order:

1. `5263e847ea6a847941aa6cf8c548f99d2131c193351a8281cb367625cbbd3f4e`
2. `6bb67fc1a05b9e06ef00351eea68d7f0539da98f371c1d96ea6ed882d68c5b33`
3. `7c20e8a3b2e9566d8f88be8c0b1368ae7d347f5591ef349b0d7d606322fa2163`
4. `aa42dc6a56d8a50b5e82e7f9235c5e1042a0f2459eef49a871d71f06a47853cb`
5. `501c61f9812aa8386551b693bcac08decc8762189892adee9965b572ea92f961`
6. `1d0cc6f0821486ceebcd806117127af4dc63b90f62bb832af97fec7569492f73`

They are explicitly excluded from every v4 denominator and summary.

## Interrupted ordinal 7

Coordinate: `a07_10800_11200 / hfnet_openloop_350 / repeat 1 /
attempt 1`.  The v3 state machine reports `STARTED_WITHOUT_RESULT`.

| Artifact | Size (bytes) | SHA-256 |
|---|---:|---|
| `attempt_manifest.json` | 5226 | `0a8e3e8ffd68ea847d138cdf2909a0808b0ccf3e09f8e14b27c37a1c516b02a1` |
| `ordinal_dispatch_claim.json` | 1624 | `8418b71d2b41e3e75978c8fbb91cfb1d7e03d597da3220176e230db92e3c310f` |
| `start_claim.json` | 4800 | `678329c2112e41cc3a41be30a8bafb50848f579eb63e8bf8372672a0df088708` |
| `launch_receipt.json` | 1907 | `90c4e2b62ad22f82029ced95bcff8a7933194eb4ce8e87a68a5ed016a8f36522` |
| `headless.stdout.log` | 2810 | `bea0013cb1787bb5680a5b0016950b10b5be01039ad5359b2916f51e96ff3cea` |
| `headless.stderr.log` | 6026 | `3518a0b7b5a8e0f878e2eccd9951088d7d38642d2ad056b3b8e5ab0f9916070d` |
| attempt-local `HF-Net.cache` | 853319 | `3ecdb89c1f4f7023315487775fe55d1b8a93818c9c48cdac6b648e4566b2b295` |

The launch receipt records PID=PGID `3222964`, Linux start ticks `60891161`,
and the exact expected executable/argv.  A post-clean audit found
`/proc/3222964` absent and no remaining VINS/HFNet/ROS/rosbag estimator process.

The following mandatory artifacts are absent:

- `controller_dispatch_execution_001.json`;
- `controller_dispatch_001.stdout.log` and `.stderr.log`;
- `runtime_resource_monitor.json`;
- `run_result.json`;
- `pipeline_invalid_receipt.json`; and
- every trajectory file under `result/`.

The stdout tail contains `Shutdown`, `Saving trajectory ...`, and
`Map 0 has 0 KFs`.  This corroborates shutdown after the supervisor chain was
lost, but it is not a valid trajectory result and cannot be converted into an
algorithm failure receipt after the fact.

## v4 non-import boundary

V4 may reuse only original source images, source bags, configurations, model
seed, estimator binaries, and source trees after fresh identity verification.
It must regenerate its input freeze, runtime namespace, attempt manifests,
cache copies, matrix, dispatches, starts, results, receipts, and summaries.
The same precommitted 120-coordinate order is retained; no order or parameter
may depend on the six observed v3 outcomes.

