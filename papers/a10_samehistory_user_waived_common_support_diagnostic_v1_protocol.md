# A10 same-history user-waived common-support diagnostic v1

Status: `FROZEN_BEFORE_DIAGNOSTIC_EVALUATION`

Date: 2026-08-26 (Asia/Shanghai)

## Question and scope

On the fixed AQUALOC archaeology A10 feed `0..2800` and score window
`2400..2800`, what descriptive SE(3)-aligned COLMAP-proxy APE and 1 s
translation RPE are obtained on one common 1 Hz support grid by:

1. `VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT`;
2. `EXTERNAL_KLT_FINALONLINE_BACKBONE`;
3. `AQUAFE_FINALONLINE_XFEAT_LINEAGE`; and
4. `HFNET_SLAM_WARMSTART`?

This is an additive `DEVELOPMENT_ONLY_USER_WAIVED_DIAGNOSTIC`. It does not
modify or relabel the frozen A10 v4 analysis. It does not run or retry any
SLAM/VINS/HFNet process.

## Explicit local-policy waiver

The frozen v4 KLT attempt remains `EXECUTION_INTEGRITY_FAILED` because its
postflight observed unrelated host-side `rosout` processes. The child itself
started once, returned raw code 0, was reaped, and produced an artifact-contract
PASS, score-usability PASS trajectory inside a loopback-only network namespace.

Following the user's authorization to ignore a requirement when it is only a
project-local restriction, this diagnostic may read that real KLT trajectory.
The waiver applies only to the v4 host-postflight ambient-process gate. It does
not convert the v4 attempt to accepted, erase its receipt, authorize a retry,
or upgrade the resulting metrics to primary paper evidence.

## Frozen input identities

| Input | Bytes | SHA-256 |
|---|---:|---|
| Raw A10 bag | 765,976,943 | `49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e` |
| Vanilla VINS trajectory | 141,986 | `f3f07e846fae02bd33b44a295106e769b8288710204c05d7b1c65f1d124dbcca` |
| KLT VINS trajectory | 142,025 | `cd6af6015dfd85662edda8f35309b850d3b4c3f98f9554747a823ec153223fd3` |
| AQUA-FE VINS trajectory | 142,034 | `e303003668a6c3f1fbfe90720b34bd59b990a7d6d3ca15f0d514089b877da7bb` |
| Sealed HFNet score bridge | 42,749 | `a268350cda12c0e4b453420853c19e4dd7b4dc2e121d6616344ad247be032ec1` |
| Vanilla VINS config | 1,009 | `da4518da471bdcc282430ecef9f7d4f5b69b96148845a60dec012a65ebf656dc` |
| KLT VINS config | 1,005 | `46db57acf32b1a8f70cfbe67656b7f8544fd7c761e9f79e3c1832e1cce959370` |
| AQUA-FE VINS config | 1,034 | `4f45c72928f6437b134844954c038bbc5dd9cefdf52dea35dc2bfba11c33ff11` |
| HFNet `body_T_cam0` evaluation config | 415 | `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1` |
| Epoch-ns evaluator wrapper | 5,447 | `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91` |
| Common-support evaluator | 27,933 | `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` |
| Evaluator core | 27,945 | `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635` |
| evo 1.31.1 `evo_ape` entrypoint | 213 | `6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15` |
| evo 1.31.1 `evo_rpe` entrypoint | 213 | `9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1` |

The native reference is `/aqualoc/colmap_gt` in the raw bag. The score interval
contains 21 native reference poses. It is a same-image COLMAP/depth-scale proxy,
not an independent metrology-grade trajectory.

## HFNet timestamp canonicalization

The existing sealed HFNet score bridge has 401 ordered rows. For evaluation
only, row `i` receives the exact raw camera header timestamp for source frame
`2400+i`; all seven pose fields and their text remain unchanged. The signed
sealed-minus-raw delta histogram is frozen as:

`{-112:44, -80:60, -48:45, -16:60, 16:46, 48:52, 80:38, 112:56}` ns.

Maximum absolute change is 112 ns. The canonical 42,749-byte payload must have
SHA-256 `de0090a2c08d795ecdbe47f51c43e18cd624da14be9cfa64bfb3efd52ce2d99a`.
No pose transform, fitted offset, interpolation, resampling, or result-informed
tuning is permitted at this step.

## Fixed evaluator protocol

- Score timestamps: `[1542888916.043622160, 1542888936.039921424]` s.
- Evaluation grid: 1 Hz, 20 anchored samples.
- The additive `evaluate_vins_common_support_epoch_v2.py` wrapper must load
  ROS `secs/nsecs` as exact integer fields before conversion to
  `numpy.longdouble`; the otherwise frozen evaluator and evaluator core remain
  unchanged. The older `Time.to_sec()` float64 reference path is forbidden.
- Maximum reference interpolation bracket: 2.5 s.
- Maximum estimate interpolation bracket: 0.25 s.
- VINS body-to-camera composition is applied from each arm's frozen config;
  HFNet uses the separately pinned full-precision `body_T_cam0` evaluation
  config because its bridge is `world_T_body`.
- Alignment: one rigid SE(3) position alignment per arm, with no scale change.
- APE: translation RMSE, median, and max after that SE(3) alignment.
- RPE: aligned-global-frame positional delta at exactly 1 s; RMSE, median, max.
- evo 1.31.1 must independently cross-check APE and segmented 1 s RPE RMSE
  on the evaluator's already fixed common mask; absolute disagreement must not
  exceed `1e-5 m`.
- Minimum diagnostic common support: at least 15/20 samples, `matched/20 >= 0.70`,
  and the conservative index `matched/21 >= 0.70`.
- Minimum descriptive RPE support: 10 pairs.
- Formal APE minimum remains 30 poses and 10 s. With only 20 uniform samples
  and 21 native reference rows, the formal APE gate is closed by construction.

The method order above is fixed before evaluation and must not be sorted by a
metric.

## Interpretation boundary

- Unit of analysis: one selected development window, one existing trajectory
  per method (`n=1` window; no independent repeated-run inference).
- No mean across windows, confidence interval, p-value, significance test,
  winner, ranking, superiority claim, or failure-as-zero imputation.
- Numbers may be used only to decide whether a fresh formally accepted KLT
  backend run and extension to A06/A09 are worth performing.
- Native-image, external-feature, and HFNet ingestion/rate semantics differ and
  remain system-level confounds.
- The v4 KLT postflight failure and the HFNet prefix-reset history must be shown
  beside any numeric table.

## Output namespace

All generated artifacts must be new and exclusive under:

`/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1`

Existing v1-v4 files are read-only inputs and must not be changed.

## Frozen diagnostic runner

The only analysis runner is
`scripts/run_a10_samehistory_user_waived_common_support_diagnostic_v1.py`,
25,718 bytes, SHA-256
`9db50f45fcb00781caae03faef6d8b6857945888a1652cef1973e27860f4920b`.
