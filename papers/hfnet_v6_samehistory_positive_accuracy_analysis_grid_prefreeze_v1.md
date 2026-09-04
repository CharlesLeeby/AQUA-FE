# HFNet-v6 same-history positive-roster accuracy analysis-grid prefreeze v1

Status: **FROZEN DESIGN BOUNDARY BEFORE ANY HFNET PROCESS START OR TRAJECTORY IN THIS TEN-CASE ROSTER**  
Frozen at: 2026-08-29T02:02:00+08:00

This document resolves the analysis-grid ambiguity in
`hfnet_v6_samehistory_old_positive_roster_protocol_v1.md`, as amended by
`hfnet_v6_samehistory_positive_roster_prestart_parser_supersession_v2.md`,
before any HFNet outcome exists for this ten-case roster.  It does not
authorize an accuracy calculation.  A separate
execution lock must still identity-pin every admitted HFNet run result,
historical trajectory, reference, frame transform, evaluator, and evo binary.

## Authority and outcome blindness

- Controlling v2 whole-roster pointer:
  `/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_roster_execution_lock_v2.json`,
  5,296 bytes, SHA-256
  `f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1`.
- Controlling v2 bundle root:
  `/mnt/data/AQUA-FE_WS/locks/.hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-a1df6b5e08cc9230`.
- Controlling v2 roster lock: 3,132 bytes, SHA-256
  `a1df6b5e08cc923087e563caddf017eac344d111ddc3b2db801949a620245289`.
- Controlling v2 build receipt: 5,379 bytes, SHA-256
  `946f272063bfc55dc11296fcdbc09197419bd506818959bced8a836140fe8017`.
- Prepared v2 runner: 7,639 bytes, SHA-256
  `ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb`.
- Prestart parser-supersession amendment: 4,653 bytes, SHA-256
  `cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7`.
- Parent protocol SHA-256:
  `a5f9db42e9b35e470fe1fa680e1d2682dd59e52a064fe805da95de829e4ef541`.
- Historical-positive report SHA-256:
  `4ddb11404c64f44537b9d142f97a4d13d744b0db3f18e1f8b857787503024ade`.
- The original v1 execution pointer, roster lock, runner, and ten prepared
  attempt directories are `RETIRED_PRESTART_PARSER_INCOMPATIBLE`.  They were
  retired before any process-start reservation or HFNet child existed, must
  never be executed or accepted by an evaluator, and count as neither attempts
  nor failures.
- At this renewed freeze boundary all ten controlling v2 attempts were
  `PREPARED_NOT_STARTED` and independently returned `READY=True`; there were
  exactly zero per-case start-once reservations, process claims, terminal
  results, HFNet logs, HFNet trajectories, or accuracy outputs.

The July learned-plus-KLT and KLT APE values select the roster only.  They use
the old nearest-reference `dt <= 0.6 s` convention and are not the future
head-to-head values.

## Meaning of common timestamp support

For every AQUALOC case, the observed raw-set intersection
`reference AND learned_plus_KLT AND KLT` is empty.  Adding a future HFNet set
cannot make the literal four-way raw intersection nonempty.  Therefore
"one intersection of timestamps" means the intersection of valid support on
one prospectively fixed integer-nanosecond analysis grid, not equality of raw
serialized timestamps:

```text
M(g) = valid_reference(g)
     AND valid_HFNet(g)
     AND valid_learned_plus_KLT(g)
     AND valid_KLT(g)
```

The only nonzero timestamp tolerance in the entire pipeline is a
pre-evaluation serialization bridge for stock HFNet output.  Each printed
epoch-double timestamp may be mapped within 256 ns to exactly one frozen
source camera header only when the mapping is bijective, strictly monotonic,
and uses no source header twice.  The mapped source header replaces the
printed value.  All later support, grid, and metric operations use integer
nanoseconds with exactly 0 ns tolerance.  This bridge is not timestamp
snapping for analysis and may not repair a missing or ambiguous pose.  The
`256 ns` limit is an exact non-overridable constant; no public or internal
metric path may accept a caller-supplied larger value.

For every case,
`g_k = first_score_camera_header_ns + k * 100000000 ns`, with
`g_k <= last_score_camera_header_ns`.  A source is valid at `g` only for an
exact sample or a frozen, two-sided bracket.  Translation uses linear
interpolation and rotation uses shortest-arc SLERP.  Nearest-only association,
timestamp snapping, sample reuse as a substitute for a missing bracket,
extrapolation, and any fitted or searched time offset are forbidden.  All
offsets are exactly zero.

| Dataset | Grid | Reference max two-sided gap | Each estimate max two-sided gap |
|---|---:|---:|---:|
| AQUALOC archaeology | 10 Hz | 2.50 s | 0.25 s |
| NTNU | 10 Hz | 0.05 s | 0.25 s |
| CIRS | 10 Hz | 0.25 s | 0.50 s |

These values combine existing project contracts prospectively: NTNU and CIRS
reuse the E3/G0 profiles; AQUALOC prospectively adopts the audited 10 Hz roster
grid with the frozen A06/A09 2.5 s reference-gap rule.  No case may receive a
different grid or gap after its HFNet outcome is known.

The coverage denominator is the complete score grid.  Reference-valid count
is also reported separately.  An invalid grid point breaks a contiguous
segment.  RPE never crosses a break, and a one-second pair must satisfy the
integer identity `g_j - g_i = 1000000000 ns` (ten grid steps).

## Gate and structural eligibility

Metrics are authorized only after all of the following pass on the same joint
mask: at least 30 grid poses, common span at least 10.0 s, coverage at least
0.70, at least ten exact one-second RPE pairs, and a runability-PASS HFNet
receipt.  Each system is aligned independently with proper fixed-scale SE(3):
scale is exactly one, `det(R)` is positive and approximately one, and no Sim(3)
result is primary.  The alignment defines translation APE.  Translation RPE is
the standard full-pose SE(3) relative error at exactly one second:
`E_ij = (T_ref_i^-1 T_ref_j)^-1 (T_est_i^-1 T_est_j)`, reported as
`norm(translation(E_ij))`.  It uses the resampled, common-target positions and
orientations and is invariant to any global left-frame alignment.  The older
aligned-global positional-delta-vector RPE is not used.  Failure produces
accuracy `NA` and no hidden APE/RPE number.

The historical two-arm-plus-reference mask is an upper bound because adding
HFNet can only remove support:

| Case | Upper-bound poses / grid | Span | Coverage | 1 s pairs | Accuracy status before HFNet |
|---|---:|---:|---:|---:|---|
| A05 3300--3700 | 189 / 200 | 18.8 s | 0.9450 | 179 | conditional |
| A07 10800--11200 | 150 / 200 | 14.9 s | 0.7500 | 140 | conditional |
| A08 4500--4660 | 67 / 80 | 6.6 s | 0.8375 | 57 | structural `NA`: span |
| A09 6000--6200 | 87 / 100 | 8.6 s | 0.8700 | 77 | structural `NA`: span |
| NTNU fjord1 s83 d10 | 85 / 100 | 8.4 s | 0.8500 | 75 | structural `NA`: span |
| NTNU mclab1 s60 d15 | 139 / 150 | 13.8 s | 0.9267 | 129 | conditional |
| CIRS s575 d30 | 252 / 299 | 25.1 s | 0.8428 | 242 | conditional |
| CIRS s900 d30 | 258 / 299 | 25.7 s | 0.8629 | 248 | conditional |
| A02 7600--8000 | 150 / 200 | 14.9 s | 0.7500 | 140 | conditional |
| NTNU mclab2 s110 d10 | 67 / 100 | 6.8 s | 0.6700 | 47 | structural `NA`: span and coverage |

Thus all ten cases remain required runability attempts, but at most six can
enter accuracy under this frozen gate: A05, A07, A02, NTNU mclab1, and the two
CIRS windows.

## AQUALOC native-reference disclosure

A05, A07, and A02 each contain only 21 native approximately 1 Hz COLMAP
reference anchors.  The 30-pose gate above counts preregistered common-grid
poses, not independent native reference observations.  The 10 Hz residuals
are serially correlated interpolation samples and must never be presented as
independent replicates, used to inflate significance, or described as 150--189
independent ground-truth observations.  Every AQUALOC table must report both
native-anchor count and common-grid count.  A mandatory native-anchor-only
sensitivity is descriptive, may run only after the primary common-support gate
has passed, and does not retroactively change the primary grid contract.  A
gate-closed case remains `NA` and must not leak metrics through the sensitivity
path.

All AQUALOC COLMAP, NTNU ReAqROVIO, and CIRS odometry references are
non-independent proxy references, not external ground truth.

## Required implementation boundary

The roster evaluator must be a new case-table-driven controller.  It may reuse
the pinned numerical implementations below but not an old case-specific
wrapper unchanged:

- `trajectory_eval_core.py`:
  `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635`;
- `evaluate_vins_common_support.py`:
  `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110`;
- `evaluate_vins_common_support_epoch_v2.py`:
  `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91`;
- control-flow reference `run_a09_samehistory_fourarm_common_support_v1.py`:
  `05ff0bad4ec449c7545628f71498ce23ca8a09e1331f4e8d79b67854983e3df0`.

Only audited pure helpers may be imported from the old evaluators.  Their
existing end-to-end paths are forbidden because they can compute alignment
and metrics after a support gate has closed.

Support must be computed before coordinates are aligned.  A closed gate may
write mask and rejection evidence only; it may not calculate or retain an APE
or RPE value.  The HFNet epoch timestamp is canonicalized to the unique source
camera header (the stock double serialization may differ by at most 256 ns),
with no fitted offset.  Quaternion order is converted losslessly.

## Frozen pose, frame, and interpolation adjudication

The serialized HFNet and VINS poses are local `world_T_IMU/body` trajectories.
HFNet uses quaternion order `qx,qy,qz,qw`; the historical VINS CSV uses
`qw,qx,qy,qz`.  Order conversion is a lossless permutation only.  For every
source, the mandatory operation order is:

1. parse the native `world_T_source` pose;
2. resample that source trajectory at the common integer-nanosecond grid with
   position-linear interpolation and shortest normalized quaternion SLERP;
3. right-compose the frozen `source_T_target` static transform;
4. fit and apply that arm's proper fixed-scale left SE(3) alignment in the
   common target frame; and
5. calculate error only on the already accepted joint population.

Composing the lever arm before linear translation interpolation is forbidden:
translation interpolation does not commute with a rotating lever arm.  A
metric entry point must first validate the case's identity-pinned execution
lock and must reject transforms that do not equal the dataset contract below;
merely checking that four caller-supplied target-frame strings agree is not
sufficient.

- **AQUALOC archaeology:** the COLMAP proxy reference is direct
  `world_T_camera`; every estimate remains `world_T_IMU` until resampling and
  then right-composes the one published `IMU_T_camera` below.  The inverse is
  forbidden as the estimate bridge.  Matrix comparison tolerance is at most
  `1e-12` elementwise.

  ```text
  IMU_T_camera =
  [-0.999372214240385 -0.034374888513960 -0.008575805730306 -0.019289625059918]
  [ 0.009015607185122 -0.012659747009765 -0.999879217522163 -0.175142540090067]
  [ 0.034262169098800 -0.999328823683828  0.012961709892746 -0.026795196070038]
  [ 0                  0                  0                  1                ]
  ```

  The calibration authority is
  `/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_calibration_files/archaeo_imu_camera_calib.yaml`
  (938 bytes, SHA-256
  `e3aad241432b6619395564224fc39cb64931f17ac9446129c47a1ddf6c7a3ebc`).

- **NTNU:** the ReAqROVIO proxy reference and all three estimates are direct
  `world_T_IMU/body`; the common frame is that IMU/body frame and every static
  bridge is identity.  This adjudication explicitly supersedes the NTNU rows
  that incorrectly say `world_T_cam0` or require `body_T_cam0` in
  `reference_audit.csv` (SHA-256
  `3f4ba3963542e8b8b735ca315b7b6883b9c3ec6d6fe310584fbddc9d56f53a20`),
  `data_eligibility_manifest.csv` (SHA-256
  `510c276c33217706eef11ea53e58de4b37318828f8a6dc793dea9262f0a0a0f5`),
  and `evaluator_protocol_v1.md` (SHA-256
  `d3ae583ca799ef423054a5b9ece8b53e0000a8d3bbb1ea8c50121f7a60a40816`).
  Those older files are not authorities for this roster.

- **CIRS:** the odometry proxy reference is direct `world_T_vehicle`; the
  common frame is the published vehicle/DVL body.  Each estimate is
  `world_T_MTi-IMU` and, after resampling, right-composes the published
  `IMU_T_vehicle` below.  Matrix comparison tolerance is at most `1e-15`
  elementwise.

  ```text
  IMU_T_vehicle =
  [ 2.220446049250313e-16 -1                       0                      -2.220446049250313e-17]
  [-1                     -2.220446049250313e-16  1.224646799147353e-16  0.10000000000000002]
  [-1.224646799147353e-16 -2.465190328815662e-32 -1                     -0.16]
  [ 0                      0                       0                       1]
  ```

  It must be verified as the two-sided inverse of the sealed published
  `vehicle_T_IMU`.  The historical CIRS VINS setting `estimate_extrinsic: 1`
  estimates a camera extrinsic and does not change the serialized IMU/body
  pose.  That online camera extrinsic is ignored for the body bridge; using it,
  or any `IMU_T_camera`, as `IMU_T_vehicle` is forbidden.

Before metrics, the execution lock must identity-pin and test all of these
pose conventions, matrices, directions, and operation ordering.

Independent evo verification is frozen to evo `v1.31.1` using the absolute
executables below:

- `/home/ma/.local/bin/evo_ape`, 213 bytes,
  SHA-256 `6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15`;
- `/home/ma/.local/bin/evo_rpe`, 213 bytes,
  SHA-256 `9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1`.

Those 213-byte files are console entrypoints, not the implementation.  The
prestart seal and later execution lock must additionally bind
`/usr/bin/python3.8` (5,490,456 bytes, SHA-256
`298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06`),
evo `RECORD` (SHA-256
`a720ae5d78b1cf5d0c5b3ed81b8deb2adc41cb686ccffd773a42a1553823cbde`),
NumPy 1.24.4 `RECORD` (SHA-256
`6c7ce7bb7cd520b75be0d504637fe57020dd50aef3503d9941b2cbc20473676a`),
and SciPy 1.10.1 `RECORD` (SHA-256
`ff024ed0ab4a9407c96c290ad8db1453153fa4cdddcdb99e6a637a2c6916d004`).
The evo implementation tree identity is reproducibly defined under
`/home/ma/.local/lib/python3.8/site-packages`: include every regular,
non-symlink file below `evo/` and `evo-1.31.1.dist-info/`, exclude every path
containing `__pycache__`, and sort by site-relative POSIX path.  For each file,
feed SHA-256 the ASCII record
`relative_path + NUL + decimal_size + NUL + file_sha256_hex + LF`.  The frozen
result is 45 files, 473,395 total bytes, tree SHA-256
`adab14dc969a68572af4c4e1966010df89b3f7dfb50f7dad441221075f410a4d`.

The evo adapter starts from the raw resampled common-target full poses and
uses relative-zero timestamps derived from authoritative integer nanoseconds;
it must never replace real orientations with identity quaternions.  APE uses
one all-common-pose TUM pair and exact arguments equivalent to
`evo_ape tum REF EST -a -r trans_part --t_max_diff 1e-9 --t_offset 0`, with no
`-s`.  RPE is run separately for every contiguous accepted segment using raw
full poses and exact arguments equivalent to
`evo_rpe tum REF_SEG EST_SEG -r trans_part -d 10 -u f --all_pairs
--pairs_from_reference --t_max_diff 1e-9 --t_offset 0`; neither `-a` nor `-s`
is used because a full-pose relative transform is invariant to global left
alignment.  Segment squared errors are combined by their exact pair counts,
never by an unweighted mean of segment RMSE values.

Primary and evo must consume the same common-pose and exact-one-second-pair
populations, verified by count and ordered integer-nanosecond list digests.
The adapter must freeze the exact argv, return status, stdout/stderr identities,
generated TUM identities, segment membership, and parsed pair counts; accepting
caller-supplied scalar RMSE values or population dictionaries is forbidden.
Primary and evo APE/RPE RMSE must agree within `1e-5 m`; a larger difference
closes the case without a ranking.  Primary numbers remain
`EVO_CROSSCHECK_PENDING` and are not accuracy- or ranking-authorized until the
cross-check passes.

The formal controller must verify the running evaluator and controller against
their sealed identities, verify every receipt/trajectory/frame/bridge/evo
identity before opening it and again before publication, and bind the numeric
path to the validated matching execution lock.  It must use an atomic
exactly-once claim, canonicalize all destination paths before checking
distinctness, publish on FUSE with temp `O_EXCL` + file fsync + hard-link
no-replace + directory fsync, and always publish a terminal receipt.  A mere
identity-field shape check or sequential `lstat` dry-run is not execution
authorization.
