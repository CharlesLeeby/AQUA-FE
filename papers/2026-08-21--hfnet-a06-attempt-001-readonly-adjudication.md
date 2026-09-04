# HFNet-SLAM AQUALOC A06 attempt_001 read-only adjudication

Date: 2026-08-21  
Status: **NON-AUTHORITY human evidence note**  
Scope: additive, read-only interpretation of the already terminal and sealed `attempt_001`.

This note does not alter, supersede, unlock, or authorize changes to the attempt, runner, execution lock, input, model, trajectory, or terminal result. It authorizes neither another HFNet start nor a retry, `attempt_002`, trajectory evaluation, accuracy claim, cross-system comparison, ranking, or winner claim.

## Sealed evidence pins

Attempt root:

`/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_archaeology_a06_0000_2460/attempt_001`

| Artifact | Size (bytes) | SHA256 |
|---|---:|---|
| `run_result.json` | 161265 | `2b9640fbc206f11db8e5a90d74f8c57214ae0912a3608263e9d3ddc23686441b` |
| `process_start_claim.json` | 2963 | `7fb2e0b0fa463b302d9e9d016a0e34ac6333269e862190c8e6d92f9a846c250c` |
| `headless.stdout.log` | 3360 | `1f03cf3e23c27e6263877af9cc3c85fed901c977b61374c06062b9db65f68969` |
| `headless.stderr.log` | 5918 | `617e42e7bc32c7fd50b3df371478242ebacf40cb48ab8df1a5d34340820c8545` |
| `result/trajectory.txt` | 277177 | `72cbd969ec645ea0b5f527c9b1a404fd4e4176a9475819a054b2dd553d027460` |
| `result/trajectory_keyframe.txt` | 30970 | `9bb7b96df11ca2cf354c5ca75ce25dd1d0631d320d6c44b7e0cbfaa9556b52db` |

Execution lock:

`/home/ma/AQUA-FE_WS/papers/hfnet_v6_a06_0000_2460_exact_window_execution_lock_v1.json`  
Size: 9331 bytes  
SHA256: `a0b78b50253e303dcb85b82eeeda90fac0281dd0aa61fb5b0670d10f14dbcbf4`

## Narrow result supported by the sealed evidence

The controller terminal is `PASS_EXPLORATORY_UNDERWATER_USABILITY`, with raw process return code 0, no timeout, synchronous reap, exactly one recorded Popen/start, and no retry. This PASS supports only the narrow statement that the pinned official HFNet-SLAM build completed the frozen development-exposed AQUALOC Archaeology A06 feed and produced parseable trajectories.

The input feed contains 2461 camera images, source indices 0 through 2460 inclusive. The frame trajectory contains 2457 uniquely associated poses, indices 4 through 2460. Inside the frozen score window, source indices 2210 through 2460 inclusive, it contains 251 of 251 poses as one contiguous run. The keyframe trajectory contains 27 score-window keyframes (268 keyframes overall).

Two controller descriptions require human correction without changing the sealed machine evidence:

1. The run processed **2461 images**, not the H03-engine residual text “sequential 1801-image loop.” The same terminal record's numeric `inferred_images_consumed` field correctly says 2461.
2. The score window has 251 samples but 250 nominal 20 Hz intervals, so its nominal span is **12.5 s**, not 12.55 s. Its exact source-camera timestamp span is **12.496417024 s** (`1542883422269233600` to `1542883434765650624` ns).

## Runtime warnings and interpretation boundary

The stderr log records optional-parameter absence notices and TensorRT warnings, including ONNX INT64-to-INT32 weight conversion, TensorRT linked against cuDNN 8.6.0 while loading cuDNN 8.4.1, and FP16 subnormal/underflow conversion warnings. The sealed warning scan reports no matches for `error`, `failed`, `lost`, `not_initialized`, `not_enough_acceleration`, `reset`, `segfault`, or `terminate`. These observations support completion/usability only; the conversion and version warnings remain relevant to any future numerical interpretation.

No ground-truth evaluator was started by this attempt. No APE, RPE, accuracy, statistical comparison, superiority, ranking, or winner result follows from this PASS. The A06 reference later available for evaluation is an offline image-derived COLMAP trajectory with a scale caveat, not sensor-independent ground truth, and any future comparison would require a separately frozen common-support protocol and separate authority.

## Evidence limitations retained rather than repaired

- The two A06 synthetic/non-model test files are identity-pinned and were observed to pass 14 tests in the preparation audit workflow, but there is no separately sealed historical test-execution receipt containing the exact command, stdout, stderr, return code, and runtime. This note does not manufacture such a receipt after the fact.
- The independent input auditor strongly binds the official archive, copied PNG bytes, generated CSV hashes, timestamps, and full-tree identity, but its manifest-semantic checks are incomplete and some transformation constants are frozen expectations rather than independently derived inside that auditor. Separate read-only reconstruction from the official raw CSV and calibration confirmed the current `0..2460`, score `2210..2460`, and IMU `raw_ns + 53694112` instance; this does not generalize the auditor into a complete future-data proof.
- Several selector/config/test files were mode `0664`, while files on the `/mnt/data` `fuseblk` volume present as mode `0755`. Integrity therefore rests on exact hashes, O_EXCL claims, full-tree checks, and pre/post identity equality rather than operating-system read-only permissions.

## Lifecycle closure

`attempt_001` is consumed and terminal. This note is not an execution authority, retry authority, adoption authority, evaluation authority, or unlock token. It does not permit another scientific start under the same or a new attempt name. Any future computation must be independently additive, freshly frozen, and explicitly authorized.
