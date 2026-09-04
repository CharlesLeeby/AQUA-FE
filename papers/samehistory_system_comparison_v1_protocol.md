# AQUALOC same-history system comparison v1

Status: `FROZEN_BEFORE_FORMAL_RUNS`

Date: 2026-08-23 (Asia/Shanghai)

## Question

Run the closest system-level controls and AQUA-FE with the same raw feed history as the completed official HFNet-SLAM windows. The frozen arms are:

1. `vanilla_origin`: the pinned VINS-origin native-image control and the same local VINS backend checkout used by this project. It is reviewer-facing context, but the checkout is quality-capable and must not be described as a byte-identical pristine/upstream Vanilla VINS-Fusion.
2. `external_klt`: the same external-feature path as AQUA-FE, with only its classical KLT/GFTT mirror backbone. This is the clean frontend ablation.
3. `aquafe_proposed_safe`: the frozen v33 mirror profile, preserving the same KLT/GFTT backbone and permitting only gated learned sidecar observations (SP+LG and/or LoFTR). Source-specific action is audited from the exported metrics rather than inferred from the task name.

`external_noloftr_mirror` remains an optional secondary mechanism ablation. It is not required for this first same-history run and must not substitute for either primary control. Dedicated single-arm KLT and proposed wrapper tasks are used so that this optional arm does not add an unnecessary long export.

HFNet-SLAM is not rerun. Its sealed attempt outputs remain the external learned-system comparison.

## Frozen windows

| window | feed source indices | score source indices | HFNet | VINS-origin control | external KLT / AQUA-FE |
|---|---:|---:|---:|---:|---:|
| A06 | 0..2460 | 2210..2460 | 20 Hz camera/backend | 20 Hz native tracker, MT1 every-second backend | 20 Hz tracker state, 10 Hz export/backend |
| H07 | 1..1720 | 1660..1720 | 20 Hz camera/backend | 20 Hz native tracker, MT1 every-second backend | 20 Hz tracker state, 10 Hz export/backend |

H07 source 0 remains excluded because it has no shifted-IMU predecessor. No synthetic or extrapolated IMU is permitted. A06 retains its already sealed source-0 contract.

The frozen external exporter uses `every2 + frame_offset1`: A06 publishes source `1,3,...,2459` (1230 feed frames; 125 in score), while H07 publishes source `2,4,...,1720` (860 feed frames; 31 in score). Usability coverage must use each method's native expected grid and also disclose its fraction of the 20 Hz camera grid; a 10 Hz arm must not be failed merely for lacking the other phase's camera timestamps.

Camera history is exactly boundary-matched. The current ROS bag converter exposes a 0.25 s raw-IMU API margin, whereas the sealed HFNet adapters retain only the reader bracket after applying the calibrated shift (A06 raw IMU indices 8..24588; H07 4..17192). These extra VINS prefix/suffix IMU messages are not synthetic, but the API-level IMU support is not byte-identical, and the prefix may affect VINS initialization. This must be disclosed as `camera-history matched / IMU API support differs`; it is another reason the cross-system accuracy gate stays closed.

## Execution contract

- Formal arms use fresh `systemfair_v1_*` tags, one launch per arm and zero result-informed retry.
- ROS/VINS runs are serial. No concurrent HFNet, MIMIR, ROS master, or VINS process is allowed at launch.
- `/home/ma/SLAM/VINS-Fusion_3-15-WS` is out of scope and must not be modified.
- Large raw and feature bags live under `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1`; workspace run paths may be symlinks to that storage.
- The existing v33 profile and VINS runner are used without threshold or model changes.
- `VINS_MULTIPLE_THREAD=1` is fixed for all formal VINS arms. On the native-image path the tracker sees every 20 Hz image, while this pinned estimator queues every second feature frame to its backend; this is distinct from the external arms, whose exporter itself emits the 10 Hz phase.
- `WAIT_FOR_VINS_SUBSCRIBERS=1` is enabled for formal runs.

## Predeclared interpretation gates

System usability is evaluated first: process completion, finite strictly increasing trajectory, initialization, score-window coverage, and failure/reset evidence. Accuracy is evaluated only on one common native reference grid after pose-convention bridging.

The learned-action gate is also predeclared: count learned/LoFTR observations and affected frames separately over the full feed, pre-roll, and score window. If the proposed arm exports zero learned observations, or its feature payload is equivalent to KLT, it is only a no-action/no-harm result and cannot support a learned-frontend improvement claim. If learned observations occur only in pre-roll, the result may show a system-history effect but not direct learned contribution inside the score frames.

Both A06 and H07 score windows contain only 13 native same-image COLMAP proxy rows. Therefore the formal accuracy gate (`native/common >= 30`, common span `>= 10 s`, and valid 1 s RPE pairs `>= 10`) is expected to remain closed even after history is matched. Results may support same-history usability and descriptive proxy-error statements, not a formal HFNet-versus-AQUA-FE accuracy winner, significance claim, or cross-window mean ranking.

The 10 Hz versus 20 Hz method-native input-rate difference and online VINS output versus HFNet final-map trajectory semantics must be disclosed beside every cross-system comparison.
