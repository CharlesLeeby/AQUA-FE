# A06 same-history harmonized common-support diagnostic v1 protocol

Status: frozen before execution; analysis-only, development-only.

## Question

On the preselected AQUALOC archaeology A06 KLT-positive window, source camera
indices `2210..2460`, what descriptive fixed-scale trajectory errors are
obtained when the existing same-history Vanilla, External KLT, AQUA-FE and
HFNet-SLAM trajectories are evaluated on one common temporal support?

This diagnostic harmonizes A06 with the A10 epoch-nanosecond and `evo 1.31.1`
protocol. It does not run or alter any SLAM system.

## Frozen systems and order

The display and manifest order is fixed before metric calculation:

1. `VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT`
2. `EXTERNAL_KLT_CORRECTIVE_REPLAY`
3. `AQUAFE_PROPOSED_SAFE_NO_LEARNED_ACTION`
4. `HFNET_SLAM_NATURAL_HISTORY`

The order must not be changed according to the resulting values.

## Frozen inputs

- Reference bag:
  `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/raw/archaeo06_0000_2460.bag`,
  573,420,704 bytes, SHA-256
  `22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a`.
- Vanilla trajectory:
  `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/vanilla_origin/vins_output/vio.csv`,
  127,225 bytes, SHA-256
  `932025ff3a818fcad2880e88c8385022019b4f3d11df8fff8fc0bb7289a9a35a`.
- External KLT corrective trajectory:
  `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/external_klt_corrective_replay/vins_output/vio.csv`,
  124,824 bytes, SHA-256
  `c4bb08ab3cea8fd509539beb40b36f9c6764f788fcc195c70020dd2c253fc93b`.
- AQUA-FE trajectory:
  `/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/aquafe_proposed_safe/vins_output/vio.csv`,
  124,964 bytes, SHA-256
  `9535c953fe543201cfd01dc1cd631daa50687fa9e89905b609642fefc1d5d6c0`.
- HFNet bridge:
  `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_archaeology_a06_0000_2460/attempt_001/bridges/hfnet_world_T_body_vins_csv_v1.csv`,
  259,978 bytes, SHA-256
  `e460b4d51c40f6bb04068a81dcf74cb050a4192e586fa2def334e76ee9b2227d`.

All three VINS configurations and the dedicated HFNet `body_T_cam0`
configuration are pinned by the runner. The three VINS matrices are numerically
identical. The HFNet configuration expresses the same calibration; its maximum
OpenCV-loaded element difference is `3.38812256e-8`, caused by YAML float
storage rather than a different physical extrinsic.

## Receipt boundary

- Vanilla receipt remains `TERMINAL_PROCESS_RC0`, one start, RC 0.
- The original External KLT run remains censored. The selected trajectory is
  the additive infrastructure corrective replay, status
  `TERMINAL_PROCESS_RC0_ADDITIVE_INFRASTRUCTURE_CORRECTIVE`, one start, RC 0.
  Its front end was not recomputed and its original namespace was not changed.
- AQUA-FE receipt remains `TERMINAL_PROCESS_RC0`, one start, RC 0.
- No earlier receipt or analysis may be edited or relabelled.

The External KLT and AQUA-FE `features.bag` files are each 37,403,698 bytes and
have the identical SHA-256
`0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6`.
The frozen AQUA-FE receipt records zero learned observations in the complete
history and in the score window. Therefore this window is no-learned-action,
no-harm evidence only; no difference may be attributed to a learned frontend.

## Timestamp canonicalization

The HFNet bridge has 2,457 rows and maps uniquely and monotonically to source
camera indices `4..2460`. The score region `2210..2460` is complete (`251/251`).
Only the timestamp text is replaced by the exact source
`/camera/image_raw.header.stamp`; pose fields must remain byte-for-byte equal.

- Maximum permitted timestamp spelling correction: 128 ns.
- No fitted offset, synchronization model, pose transform or scale operation is
  permitted during canonicalization.
- Frozen canonical payload: 259,978 bytes, SHA-256
  `a76d3670dec7434494e94dc9a823520e2a9fb3d3d61d578d62909572b67b77fd`.

## Frozen evaluation protocol

- Reference: `/aqualoc/colmap_gt` from the full `0..2460` bag.
- Score start: `1542883422.269233600` seconds, exact nanoseconds
  `1542883422269233600`.
- Score end: `1542883434.765650624` seconds, exact nanoseconds
  `1542883434765650624`.
- Input trajectories retain their complete natural history; the evaluator alone
  applies the score bounds.
- Uniform evaluation rate: 1 Hz.
- Maximum reference interpolation bracket: 2.5 s.
- Maximum estimate interpolation bracket: 0.25 s.
- Support: one intersection mask shared by all four systems and the reference.
- Alignment: per-system rigid fixed-scale SE(3), with `body_T_cam0` applied.
- Sim(3), scale correction, fitted time shift and nearest-reference reuse are
  prohibited.
- RPE: exact 1 s positional delta within a continuous common-support segment.
- Primary evaluator:
  `scripts/evaluate_vins_common_support_epoch_v2.py`, 5,447 bytes, SHA-256
  `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91`.
- Independent numeric cross-check: `evo 1.31.1`; APE and RPE RMSE must each
  agree within `1e-5` m.

Frozen gates:

- minimum APE poses: 30;
- minimum APE span: 10 s;
- minimum common coverage: 0.70;
- minimum exact-1 s RPE pairs: 10.

The score window contains only 13 native COLMAP proxy rows. The formal APE gate
is known to be closed before execution. Descriptive RPE is allowed only if the
common support and 10-pair gate pass.

## Statistical and claim boundary

There is one preselected window and one existing trajectory per method. Time
samples are correlated and are not independent replicates. No confidence
interval, significance test, effect-size inference, multiple-comparison test,
ranking, winner or superiority claim is permitted.

The reference is a same-image COLMAP trajectory with depth-scale correction,
not independent ground truth. Values must be called descriptive COLMAP/depth-
scale proxy errors. They are not authorized as primary-paper system accuracy
evidence.

## Output and runner

All generated artifacts must be new and exclusive under:

`/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1`

The output must be atomically committed and include the canonical HFNet CSV and
audit, input manifest, evaluator receipt, common-support files, `evo`
cross-check, analysis bundle, text report and final result manifest.

The only runner is
`scripts/run_a06_samehistory_harmonized_common_support_diagnostic_v1.py`,
25,466 bytes, SHA-256
`e692cf8c09a9c8f3fb01bce03984161d0adf70ab4bb1625225a761ac9d344267`.
