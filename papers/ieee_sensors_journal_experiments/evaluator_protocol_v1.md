# Evaluator Protocol V1

- Protocol identity: `isj-evaluator-v1`
- Date: `2026-07-31`
- Primary implementation: `scripts/evaluate_vins_common_support.py`
- Core implementation: `scripts/trajectory_eval_core.py`
- Legacy implementations: `scripts/evaluate_vins_sim_ape.py`, `scripts/evaluate_vins_tum.py`
- Primary metric frame: camera trajectory in the reference world frame
- Status: `TECHNICAL_PASS`

## Input Contract

1. Reference poses are sorted and finite poses are retained. Identical duplicate timestamps collapse to one pose; conflicting duplicates are an evaluator error. The audit records raw, finite, duplicate, and unique counts.
2. Estimate poses retain input order. Non-finite poses, duplicate timestamps, and non-monotonic timestamps are algorithm hard failures.
3. VINS `vio.csv` is parsed as timestamp nanoseconds, body position, and body quaternion `qw,qx,qy,qz`.
4. Each estimate is converted from `world_T_body` to `world_T_camera` using the frozen run config's `body_T_cam0` before interpolation and alignment.
5. Reference and arm timestamp offsets are explicit protocol inputs. Current G0 probes use `0 s`; future non-zero values are recorded in the output protocol object.

## Grid Contract

The evaluation rate is the largest member of `{1,2,5,10}` Hz that is no greater than the nominal reference rate. The grid is anchored at the preregistered window start:

```text
t_k = window_start + k / evaluation_rate_hz
```

Translation uses linear interpolation and orientation uses shortest-path quaternion SLERP. Exact samples are valid. Interpolated samples are valid when both brackets exist and the bracket gap is within the frozen limit. Rejection reasons are `NO_SAMPLES`, `OUT_OF_RANGE`, and `GAP_EXCEEDED`.

Default gap limits are `2.5 / nominal_rate_hz`. Dataset/runner values used by G0 are:

| Dataset/profile | Reference | Nominal reference | Evaluation | Max reference gap | Nominal estimate | Max estimate gap | Transform |
|---|---|---:|---:|---:|---:|---:|---|
| AQUALOC archaeology | `/aqualoc/colmap_gt` camera pose | 1 Hz | 1 Hz | 2.5 s | 10 Hz | 0.25 s | run `body_T_cam0` |
| AQUALOC H07 | `/aqualoc/colmap_gt` camera pose | 4 Hz | 2 Hz | 0.625 s | 10 Hz | 0.25 s | run `body_T_cam0` |
| NTNU fjord4 probe | `fjord_4_baseline.tum` camera pose | 50 Hz | 10 Hz | 0.05 s | 6.6666667 Hz | 0.375 s | run `body_T_cam0` |

The exact window start/end, rate, gaps, offsets, reference identity, and transform application flag are embedded in each `common_support_summary.json`.

## P02 Candidate Dataset Profiles

The following rows freeze the evaluator defaults for every trajectory-bearing P02 candidate. Per-sequence paths, measured coverage, observed gaps, calibration status, and SHA-256 identities are in `reference_audit.csv` and `p02/input_reference_checksums.csv`. These are multi-sequence candidates, not independent external ground truth.

| Dataset/profile | Candidate sequences | Reference provenance and frame | Nominal reference | Evaluation | Max reference gap | Nominal estimate | Max estimate gap | Timestamp offset | Estimate transform |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| AQUALOC archaeology | A01-A10 | Updated offline COLMAP, image-derived `world_T_camera`; scale corrected with depth metadata | 1 Hz | 1 Hz | 2.5 s | 10 Hz | 0.25 s | 0 s | Apply frozen run `body_T_cam0` to `world_T_body` |
| AQUALOC harbor | H01-H07 | Updated offline COLMAP, image-derived `world_T_camera`; scale corrected with depth metadata | 4 Hz | 2 Hz | 0.625 s | 10 Hz | 0.25 s | 0 s | Apply frozen run `body_T_cam0` to `world_T_body` |
| NTNU fjord/mclab | fjord_1-fjord_6, mclab_1-mclab_2 | Dataset ReAqROVIO four-camera+IMU baseline, `world_T_cam0`; pseudo-GT rather than external sensor truth | 50 Hz | 10 Hz | 0.05 s | 6.6666667 Hz | 0.375 s | 0 s | Apply Kalibr-derived frozen run `body_T_cam0` |
| AFRL stereo VI | cave_gennie, bus_outside, cemetery | Offline COLMAP, image-derived approximate `world_T_camera`; metric scale corrected from stereo baseline | 5 Hz | 5 Hz | 0.5 s | 7.5 Hz | 0.333333333 s | 0 s | Apply frozen camera-IMU `body_T_cam0` for the registered camera |

The maximum gaps above are evaluator acceptance limits (`2.5 / nominal_rate`), not measured dataset gaps. AQUALOC/AFRL reference construction reuses dataset imagery, and the NTNU baseline reuses four cameras plus the IMU; all three therefore retain the reference caveats in trajectory claims. P06 records the exact registered camera for AFRL cemetery before freezing its final window manifest.

## Common Support

Each preregistered contrast uses one grid and one mask:

```text
valid_common = valid_reference AND all(valid_arm)
```

An invalid grid point or a timestamp gap beyond the frozen segment limit splits the support into segments. APE requires at least 30 common grid poses, at least 10 s span, and at least 70% window coverage. Positional RPE requires at least 10 exact 1 s pairs within segments.

For confirmatory selection, window duration also satisfies:

```text
duration >= max(20 s, (ceil(30 / 0.70) - 1) / evaluation_rate_hz)
```

This gives a 42 s minimum for 1 Hz references.

## Metric Contract

- APE: each arm is independently aligned to the reference positions on the same common mask using fixed-scale SE(3) rigid alignment; report translation RMSE, median, and maximum.
- RPE: after the same global alignment, compare global-frame positional deltas at exactly 1 s within the same valid segment; report translation RMSE, median, and maximum.
- Coverage: report reference/arm valid-grid counts, common count, common span, common coverage, segment count, and bracket-gap P50/P95/max.
- Legacy diagnostic: report old independent-nearest reference reuse and a global one-to-one minimum timestamp-error assignment. Legacy values do not enter primary metrics.

## Evo Cross-Check

TUM files use 17 significant digits. APE uses common-grid position TUM files. RPE writes each valid segment separately with aligned positions and identity quaternions, then runs:

```text
evo_rpe tum REF EST -r trans_part -d EVALUATION_RATE_HZ -u f \
  --all_pairs --pairs_from_reference
```

Segment RMSE values are combined by pair-count-weighted SSE. The installed reference implementation is evo `v1.31.1`. Primary/evo RMSE absolute difference must be below:

```text
max(1e-6 m, 1e-6 * primary_rmse)
```

The G0 cross-check contains 13 arm rows across A10, A09, A06, NTNU, and H07; all APE and RPE rows pass.

## G0 Interpretation

- A10/A09 corrected descriptive directions remain positive, but each has only 15 common 1 Hz poses and is formally `INSUFFICIENT_COMMON_SUPPORT` for APE.
- A06 has 10 common poses and 9 RPE pairs and is also below formal support.
- NTNU and H07 long probes satisfy formal common support and retain their full negative results.
- G0 technical evaluator status is `PASS`.
- Historical resource decision is `HISTORICAL_SIGNAL_REVIEW`.

Machine artifacts are under `papers/ieee_sensors_journal_experiments/g0/` and are rebuilt by `scripts/run_g0_evaluator_validation.sh`.
