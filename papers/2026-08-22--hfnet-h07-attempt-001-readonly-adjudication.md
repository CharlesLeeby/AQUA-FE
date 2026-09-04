# HFNet-SLAM AQUALOC H07 attempt_001 read-only adjudication

Date: 2026-08-22  
Status: **NON-AUTHORITY human evidence note**  
Scope: additive, read-only interpretation of the already terminal and sealed `attempt_001`.

This note does not alter, supersede, unlock, or authorize changes to the attempt, runner, execution lock, input, model, trajectory, or terminal result. It authorizes neither another HFNet start nor a retry, `attempt_002`, ground-truth evaluation, accuracy claim, cross-system ranking, or winner claim.

## Sealed evidence pins

Attempt root:

`/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_harbor_h07_0001_1720/attempt_001`

| Artifact | Size (bytes) | SHA256 |
|---|---:|---|
| `run_result.json` | 163359 | `fb3d5fdd9e29b55e08d58622d02fdac8992bca0132472ccae943533d87c8179a` |
| `process_start_claim.json` | 2934 | `94e733c2d1671232a761f383f29da6e531365fca6d875f1ecf69c1d3c26e7a12` |
| `headless.stdout.log` | 4506 | `bcfa369e19b128f76bbd9dfba24229e3a4e307e17c45c4431d054ec24bdde24b` |
| `headless.stderr.log` | 5604 | `77e500a4b90c9f7e2c6916daf372a5608d00dd0cc0a1523f48639395c6e421d2` |
| `result/trajectory.txt` | 188311 | `d924c4c2e2f3ff8f692a0aa6f258e8998a8d0a8c05cd12ce4150bc5a54e4f4f6` |
| `result/trajectory_keyframe.txt` | 40585 | `0e22671e1d3c34ef9f7af77692bd6da3779517ae4971e5979ba5d3a1b32c9ecc` |

Execution lock:

`/home/ma/AQUA-FE_WS/papers/hfnet_v6_h07_0001_1720_exact_window_execution_lock_v1.json`  
Size: 10629 bytes  
SHA256: `878387627cbf99b754c8d050f39b718f13ff14bd2814151f9d351ff32c057114`

The independently regenerated post-run input audit was byte-identical to the sealed preparation audit: size 4388 bytes, SHA256 `fd54bf547b4487d17fc440b525111d8b97a7cc125b2959b297f118a69ebcf1ec`, terminal `PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT`. The 13 materializer/runner unit tests also passed after the run.

## Narrow result supported by the sealed evidence

The controller terminal is `PASS_EXPLORATORY_UNDERWATER_USABILITY`, with raw return code 0, no timeout, synchronous reap, exactly one recorded Popen/start, and no retry. Runtime was 310.824853 seconds. All controller gates passed, including exact full pre/post dependency profile, exact input-tree identity, unchanged shared cache, parseable trajectories, full score-window trajectory continuity, and score-window keyframe support.

The honest feed contains 1720 camera images mapped from source frames 1 through 1720 inclusive. The frame trajectory contains 1643 uniquely associated poses, relative indices 77 through 1719, hence source frames 78 through 1720. This is one continuous run with no gaps. Its first pose appears 3.851068896 seconds after the feed's first camera timestamp.

Inside the frozen score window, relative indices 1659 through 1719 map exactly to source frames 1660 through 1720. The trajectory contains 61 of 61 poses as one continuous run with no gaps. The keyframe output contains 19 score-window keyframes, from relative indices 1660 through 1718 (source frames 1661 through 1719), and 355 keyframes overall.

One controller duration description requires human correction without changing the sealed machine evidence. The score window has 61 samples but 60 nominal 20 Hz intervals, so its nominal span is **3.00 s**, not the stored `3.05 s`. Its exact camera-timestamp span is **2.999640896 s** (`1523387629157970944` to `1523387632157611840` ns). Likewise, the preroll's relative indices 0 through 1658 span 1658 nominal intervals, or **82.90 s**, rather than the stored `82.95 s`.

## Synchronization boundary fixed before execution

Raw source frame 0 was excluded before the result existed. After applying the calibrated `td = -0.0403806549886 s` convention, source camera frame 0 at `1523387546122930336` ns has no preceding shifted IMU sample; the earliest shifted IMU sample is `1523387546153594095` ns. In the pinned author entry, its `first_imu--` logic would therefore reach `-1` and later access out of bounds for a feed beginning at frame 0.

The run consequently began at source frame 1, whose reader bracket is valid. No synthetic, duplicated, extrapolated, or fabricated IMU sample was introduced. The selector, execution lock, preparation audit, start/result metadata, and source-index mapping all recorded this decision before execution; it is not a post-result window repair.

## Runtime warnings and interpretation boundary

The stdout scan records 24 `Fail to track local map!` matches, one `60 Frames set to lost` event, and 12 reset-pattern matches, including insufficient-motion initialization and bad-IMU-map reset messages. It also records successful loading of four HFNet TensorRT model shapes. The final score window nevertheless has complete trajectory coverage; that coverage does not erase the earlier tracking failures and resets.

The stderr scan records 28 warning lines, including ONNX INT64-to-INT32 conversion, TensorRT linked against cuDNN 8.6.0 while loading cuDNN 8.4.1, and FP16 subnormal/underflow conversion warnings. It records no matched `error`, `failed`, `lost`, `reset`, `cuda`, `segfault`, or `terminate` line. The run-local TensorRT cache changed as expected during this isolated invocation, while the pinned shared cache and the ONNX/config inputs remained exact.

These facts support only execution/usability and trajectory availability. They do not establish clean tracking, metric accuracy, statistical advantage, or superiority over AQUA-FE, KLT, VINS-Fusion, or another learned system.

## Accuracy boundary and retained limitations

- No ground-truth evaluator was started. No APE or RPE follows from this attempt.
- The available H07 score-window COLMAP reference contains only 13 native poses. It is image-derived and falls below the frozen minimum of 30 native poses for a formal accuracy ranking. Interpolation cannot create independent reference support.
- H07 is development-exposed because the same source window already informed local AQUA-FE/KLT work. It may be used as exploratory multi-window evidence, not as an untouched confirmatory test.
- The `/mnt/data` volume is `fuseblk` and presents the H03, A06, and H07 attempt files uniformly as mode `0755`, despite the runner's requested post-write `0444` mode. Integrity therefore rests on exclusive creation, exact hashes, input/dependency pre/post identity, and the one-start claim rather than POSIX permission bits on that mount.

## Lifecycle closure

`attempt_001` is consumed and terminal. A post-run process audit found no live HFNet headless, VINS, MIMIR, or H07 runner process. This note is not execution authority, retry authority, evaluation authority, or unlock token. Any future computation must be independently additive, freshly frozen, and explicitly authorized.
