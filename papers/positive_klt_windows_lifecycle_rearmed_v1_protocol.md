# Existing KLT-positive windows: lifecycle-rearmed natural-history frontend v1

Status: `FROZEN_BEFORE_A10_OR_A09_MODEL_EXECUTION`

Date: 2026-08-27 (Asia/Shanghai)

## Question and evidence family

This development-only experiment asks whether the additive method
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1` consumes at least one learned
lineage in the exact historical score interval of every previously used AQUALOC
KLT-positive window when each sequence is fed continuously from source frame 0.

The closed roster is A06, A10, and A09.  It is the three-window roster used by
the existing HFNet natural-history runability comparison; it is not the broader
ORB-SLAM3 mechanism/action-positive roster.  The windows were selected using
earlier development results, so neither this experiment nor any later aggregate
over these windows is confirmatory evidence.

A06 has already been executed and is immutable.  Its terminal frontend receipt
is 2644 bytes with SHA-256
`4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705` at
`/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1/terminal_probe_receipt_v1.json`.
The receipt reports `PASS_SCORE_ACTION_GATE_FRONTEND_ONLY`.  This protocol does
not rerun, copy, or modify A06.  The new runner executes only A10 and A09, in
that fixed order.  A later three-window summary must adopt the A06 receipt by
identity and combine it with the two new terminal receipts.

Historical cold-crop statistics and outcomes establish roster provenance only.
They are forbidden as runtime inputs: no historical stats CSV, cold-crop bag,
sidecar, learned feature, trigger row, or action row may be read by the runner.

## Frozen feeds and gates

| key | natural-history source feed | external-KLT odd-frame carrier | exact score gate | score carrier indices | carrier messages | `max_triggers` |
|---|---:|---:|---:|---:|---:|---:|
| A10 | `0..2800` | `1,3,...,2799` | `2400..2800` | `1200..1399` | 1400 | 117 |
| A09 | `0..4400` | `1,3,...,4399` | `4000..4400` | `2000..2199` | 2200 | 184 |

The trigger limit is fixed before either new run by the sequence-length-only
rule `ceil(carrier_messages / 12)`.  It exactly extends the already executed A06
choice `ceil(1230 / 12) = 103`; it is not chosen from A10/A09 action outcomes.
The score gate uses exact camera-header timestamps from each frozen raw bag.

## Frozen runtime inputs

| input | bytes | SHA-256 |
|---|---:|---|
| A10 raw `archaeo10_0000_2800.bag` | 765976943 | `49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e` |
| A10 external-KLT `features.bag` | 42576500 | `34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f` |
| A10 camera YAML | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| A09 raw `archaeo09_0000_4400.bag` | 1187038470 | `a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97` |
| A09 external-KLT `features.bag` | 66859585 | `cce64be73ddd545ad469e42adddf9cf8f9592f8316adda69399ec27d0b71494f` |
| A09 camera YAML | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| `xfeat_seed_sidecar_node.py` | 41561 | `9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7` |
| `causal_lineage_shadow_node.py` | 16891 | `8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727` |
| `low_texture_lineage_safe_dense_start_frontend.yaml` | 778 | `369120917878b55564d6d993670328738e5436beae92bee25e99dd86c3eb66a6` |
| stock `xfeat.pt` | 6247949 | `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b` |
| `prepare_causal_multilineage_bag.sh` | 2814 | `0b6d1d2d049732ce536ca478ae1a146f8ce78169a2a9fb1264307ffb3b0be549` |

The runner and this protocol are also hashed immediately before and after each
child process.  The A10 raw bag contains exactly 2801 camera, 28064 IMU, and 139
GT messages; its KLT carrier contains 1400 feature, 28064 IMU, and 139 GT
messages.  The A09 counts are 4401/44025/213 in raw and 2200/44025/213 in the
carrier.  Every A10/A09 KLT feature message has exactly 350 classical points.

## Frozen method

Candidate generation is the same two-stage construction already executed on
A06.  It uses half-scale images, adaptive CLAHE, trigger warmup 0, cooldown 12,
seed-loss rearm disabled, and the per-window nonbinding trigger bound above.
All remaining values are fixed at: degradation 0.18, flat region 0.10, grid
texture 0.90, base tracks 300, base grid 0.80, dropout 0.18, long-track ratio
0.45, 50 seeds per trigger, 72 active seeds, base/active spacing 8/10 px, 2
seeds per cell, LK FB 1.20, NCC 0.42, confirmation/rank 10/5, novelty 40 px,
motion ratio 0.6..1.5, homography residual 0.75 px, remap base 10000000, and
match tolerance 0.02 s.  Candidate generation uses `max_lineages=0`, so its
dummy merged output must be exactly the KLT input.

The selector is invoked through `prepare_causal_multilineage_bag.sh` with exact
positional arguments `1 40 0 10 10`: at most one concurrent learned lineage,
40 px novelty, zero-speed bases retained, ten observations required, and the
lineage slot released after ten absent carrier messages.  Rank remains five and
motion remains 0.6..1.5.  There is no periodic trigger, score-boundary trigger,
state reset, crop splice, or outcome-dependent parameter edit.

## One-shot order, retention, and structural audits

The output root is
`/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1`,
with additive `a10` and `a09` children.  The fixed order is A10 then A09.  Each
candidate and selector stage receives exactly one `Popen`; its claim is written
before the process starts.  Automatic retry is forbidden.  A zero-action result
and every structural failure are retained.  A completed terminal receipt may be
audited/adopted during safe process-level resumption but its model stage is never
started again.  A partial or failed stage without a valid terminal blocks that
window rather than authorizing a retry.

For every window, the audit must establish all of the following:

- raw/KLT counts and odd-frame timestamp binding match the frozen contract;
- candidate sidecar and CSV each contain one row per KLT carrier message;
- candidate-stage selector injection is zero and its dummy bag equals KLT
  message-for-message;
- the lifecycle full bag preserves every non-feature record and, after removing
  learned points, recovers every original KLT message byte-for-byte;
- learned points have `is_learned=1`, source code 20, and remapped IDs at or
  above 10000000;
- no merged feature message contains more than one learned observation; and
- CSV and bag injection vectors are identical, with full-history, pre-gate, and
  exact-score-gate totals reported separately.

Ambient desktop/ToDesk and unrelated user workloads are allowed by the user's
development waiver.  Runtime, throughput, latency, real-time, and exclusive-GPU
claims are therefore forbidden.

## Per-window and aggregate decision rules

The only per-window frontend action gate is
`score_gate_injected_observations > 0`.  A positive value yields
`PASS_SCORE_ACTION_GATE_FRONTEND_ONLY`; zero yields
`STOPPED_SCORE_ACTION_ZERO`.  Zero is a result, not a reason to retune or retry.
A separately frozen paired KLT/AQUA-FE backend may be prepared only for a window
whose action gate passes.  This runner never starts ROS, VINS-Fusion, HFNet, an
evaluator, or any trajectory-producing process.

The aggregate terminal receipt reports both windows regardless of sign.  It is
not a precision comparison and cannot support a system ranking, superiority,
generalization, checkpoint-adaptation, or final-online identity claim.
