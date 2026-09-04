# A06 external-KLT infrastructure corrective replay

Status: `FROZEN_BEFORE_CORRECTIVE_REPLAY`

Date: 2026-08-23 (Asia/Shanghai)

The original `a06_external_klt` wrapper invocation started once at 15:16:58, completed its entire frozen 1230-frame feature export, and then entered VINS replay. The outer execution tool's 1800 s budget incorrectly covered both the long offline export and replay. It expired at approximately 15:46:58, after only 326 partial VINS poses and before the frozen score window began. The terminal receipt is:

`/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/external_klt/formal_run_receipt_v1.json`

This is `INFRASTRUCTURE_CENSORED`, not an algorithm failure. The original namespace and partial trajectory remain immutable and are never scored.

One additive backend-only corrective replay is authorized because no score-window result existed and the complete frontend payload was already frozen before the timeout. It is not a same-tag retry and cannot rewrite the terminal attempt.

## Frozen corrective inputs

- feature bag: `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/external_klt/features.bag`
  - size: 37403698 bytes
  - SHA-256: `0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6`
- frontend metrics SHA-256: `aab2266ace8f565ff39faf475889e6f8face3345b40385fb894d435eafdfd25e`
- source VINS config SHA-256: `e3b0ef0badfbe4392b3c29f59b1dd0a4d6c5260b528bf7380dc0b17ac4de19d0`
- camera config SHA-256: `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5`
- replay runner SHA-256: `2233e2be8bf9f9db3eb691392218b59bd7f9fbbe741bf51b6bea40316d509f8e`
- VINS binary SHA-256: `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278`

## One-shot contract

- fresh output: `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/external_klt_corrective_replay`
- ROS port: 11864
- `multiple_thread: 1` is preserved byte-for-byte from the frozen source config; only `output_path` changes.
- feature, IMU, and proxy-GT messages are replayed from the exact complete feature bag.
- one process start, zero retry, tool timeout 600 s.
- no other VINS/ROS replay may be active at launch.
- result adoption requires RC0, completed replay, finite strictly increasing trajectory, and frozen A06 native score support. Otherwise this corrective namespace is terminal and no further replay is authorized.

The corrective output may replace the censored partial trajectory only in the analysis arm mapping. It does not erase, repair, or relabel the original terminal attempt.
