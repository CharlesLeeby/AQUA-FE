---
type: execution-closeout
date: 2026-08-24
experiment_line: hfnet-a10-warmstart
round: 0
purpose: runability-closeout
status: development-only-pass
primary_result: /mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/run_result.json
---

# HFNet A10 Warm-Start / Round 0 / Runability Closeout / 2026-08-24

## Executive outcome

The unchanged external HFNet-SLAM whole system genuinely ran on the previously
selected AQUALOC A10 KLT-positive score window. With source frames `0..2399`
fed as unscored history and frames `2400..2800` scored, the frozen gate returned
`PASS_DEVELOPMENT_RUNABILITY_RESCUE`:

- exactly `401/401` scored camera frames have one valid finite pose;
- the score crop is contiguous from source frame `2400` through `2800`;
- source frame `2399` immediately precedes frame `2400` in the same surviving
  trajectory;
- the score window contains `30` valid keyframes;
- no initialization or active-map reset occurs inside the score window;
- the final atlas contains one map with `34` keyframes; and
- one HFNet process was started, with return code `0`, no timeout, no watchdog,
  and no retry.

This closes only the external-system **runability** question. It does not yet
provide a fair HFNet-versus-KLT/AQUA-FE accuracy row.

## Frozen question and protocol

The score window is the previously identified development-positive A10 window,
not a newly selected or held-out window. The frozen feed and score bounds were:

| Item | Frozen value |
|---|---:|
| Continuous HFNet feed | source frames `0..2800` |
| Unscored prefix | source frames `0..2399` |
| Scored KLT-positive window | source frames `2400..2800` |
| Feed frames | `2801` |
| Score frames | `401` |
| Feed duration | `139.976942624 s` |
| Score duration | `19.996299264 s` |

The run reused the byte-identical HFNet binary, library, ONNX model, detector
threshold, feature budget, calibration, IMU clock transform, and published A06
configuration. No result-informed tuning or retry was allowed.

## Main runability comparison

| HFNet condition | Feed | Score | Process result | Score poses | Score KFs | Final map | Outcome |
|---|---|---|---|---:|---:|---|---|
| Exact-window cold start | `2400..2800` | `2400..2800` | watchdog SIGTERM after official zero-KF save hang | `0/401` | `0` | `0` KFs | `FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES` |
| Natural-sequence warm start | `0..2800` | `2400..2800` | return code `0` | `401/401` | `30` | one map, `34` KFs | `PASS_DEVELOPMENT_RUNABILITY_RESCUE` |

The cold-start attempt formed four visual maps but repeatedly failed inertial
initialization and ended with zero keyframes. The warm-start attempt ultimately
produced a contiguous `444`-pose trajectory covering source frames
`2357..2800`; its keyframe trajectory begins at frame `2355`.

## Important failure behavior before the score window

The warm-start run was not stable over the entire prefix. It recorded `22`
active-map resets before the final initialization at source frame `2355`.
Earlier initialization frame IDs were:

`0, 105, 243, 419, 497, 560, 717, 882, 1122, 1231, 1405, 1471, 1537, 1705,
1774, 1854, 1927, 2032, 2092, 2152, 2172, 2230`.

The final initialization at frame `2355` survived into the score window, which
starts only `45` camera frames later. There were no score-window resets or
reinitializations. Therefore the supported interpretation is narrow:

> Natural preceding history gave HFNet an initialization opportunity that
> survived through this score window; it did not make HFNet robust throughout
> the full 140-second feed.

## Relationship to the prior KLT-positive evidence

The score window was selected because the earlier development replay reported:

| Project arm | Legacy development APE / RPE RMSE (m) | Learned observations |
|---|---:|---:|
| KLT baseline | `1.042609 / 0.264110` | `0` |
| AQUA-FE learned-active | `0.639080 / 0.180777` | `97` |

The corrected common-support evaluator retained the same direction:

| Project arm | Corrected APE RMSE (m) | Corrected RPE RMSE (m) | Support |
|---|---:|---:|---:|
| KLT | `0.982468` | `0.238825` | `15` poses / `14` RPE pairs |
| AQUA-FE learned-active | `0.631472` | `0.158859` | `15` poses / `14` RPE pairs |

These numbers are selection context only. They must not be placed in one winner
table with the new HFNet run because the project arms cold-started at frame
`2400` and ran at the project frontend rate, whereas HFNet received frames
`0..2399` at its native 20 Hz rate. The native reference has only `21` rows and
the corrected common support has `15` poses, below the project's `30`-pose
formal APE gate.

## Integrity and deployment caveats

- Runner SHA-256: `83cd89015ac42d73982a61c0bcd95f627034ccecea01f700dfd5feaca147c30c`.
- Result SHA-256: `88c340849adcc60985711dedd499c74db36e36b3ac103768bc3aa0d615372a46`.
- Score crop SHA-256: `b5df265df24baa0d7035ee183de28ca105b2bf6429ebf819d90fd6f275154566`.
- Input, controller, runtime configuration, binary, library, shared model, and
  local ONNX identities were unchanged after the run.
- The isolated attempt-local TensorRT cache changed as expected; the shared
  cache seed remained pinned.
- TensorRT reported that it was linked against cuDNN `8.6.0` but loaded
  cuDNN `8.4.1`, plus INT64-to-INT32 and FP16 subnormal conversion warnings.
  These warnings are a deployment confound for later accuracy interpretation,
  although they did not prevent this runability PASS.

## What changed our belief

Before this run, the strong A10 positive window had only an external HFNet
cold-start failure. The new evidence changes the diagnosis from “HFNet may not
run on this underwater window” to “HFNet is history-sensitive: it fails when
cold-started inside the window but can carry a valid initialized map through
the complete window when fed natural preceding history.”

It does not change the paper-level accuracy ranking. No claim that AQUA-FE
beats HFNet, or that HFNet beats KLT, is authorized by this experiment.

## Next actions

1. Freeze an A10 same-history system comparison in which vanilla VINS/KLT and
   AQUA-FE also receive source frames `0..2800`, while all arms are scored only
   on `2400..2800`.
2. Bridge the frozen HFNet score crop from HFNet `world_T_body` convention into
   the validated project trajectory convention, then run one common-support
   descriptive evaluator. Keep formal APE closed because reference support is
   below `30` poses.
3. Treat cuDNN/TensorRT compatibility as a separate deployment-sensitivity
   experiment. Do not rerun or reinterpret this consumed attempt.
4. After the A10 same-history row is frozen, repeat the pre-registered
   warm-history diagnostic on the other strong positive A09 `4000..4400` if a
   second external-system window is still required.

## Artifact index

- Frozen protocol: `papers/hfnet_v6_a10_0000_2800_score_2400_2800_warmstart_runability_rescue_protocol_v1.md`
- Frozen selector: `papers/hfnet_v6_a10_0000_2800_score_2400_2800_warmstart_selector_freeze_v1.json`
- Canonical input manifest: `/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a10_0000_2800_score_2400_2800_warmstart/materialization_manifest.json`
- Independent input audit: `/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a10_0000_2800_score_2400_2800_warmstart.audit.json`
- Prepared manifest: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/prepared_manifest.json`
- One-shot process claim: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/process_start_claim.json`
- Terminal result: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/run_result.json`
- Exact score crop: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/result/trajectory_score_2400_2800.txt`
- Cold-start terminal result: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_2400_2800_coldstart/attempt_001/run_result.json`
- Corrected project common support: `papers/ieee_sensors_journal_experiments/g0/a10_2400_2800_probe/common_support_summary.json`

No Obsidian write-back was attempted; this repository was treated as an
unbound local workspace.
