# Published learned-SLAM/VIO baseline selection

Date: 2026-08-11  
Status: method class corrected; official-system artifacts audited; HFNet-SLAM and AirSLAM execution tracks preregistered before any official-system trajectory; isolated runtimes are still being provisioned; no official-system trajectory result exists

## Eligibility rule

The main comparison table accepts a baseline only when all of the following hold:

1. The method is described in a formally published, peer-reviewed paper rather than only a preprint.
2. The authors provide an official repository that actually contains the learned SLAM/VIO implementation reported by the paper.
3. The published implementation supports the sensor modality used in the comparison, or the modality difference is reported in a separate system-level table.
4. Dataset adaptation is limited to topics, calibration, input layout, launch/configuration, and trajectory conversion. The network, learned matcher, temporal association, estimator, and optimization code are not replaced or edited.
5. The exact paper-era commit, weights, runtime, configuration, input, and output are frozen before reading trajectory accuracy.

This rule moves the locally assembled Direct SP-LG, temporal-MAGSAC, SuperPoint-birth+KLT, and XFeat-birth+KLT arms out of the external baseline table. They remain project diagnostics/ablations because none is an author-released end-to-end SLAM/VIO implementation.

## Scientific priority and artifact status

| Order | Published system | Learned frontend and modality | Official implementation freeze | Role and current state |
|---:|---|---|---|---|
| 1 | **SuperVINS**, IEEE Sensors Journal 2025, DOI `10.1109/JSEN.2025.3556257` | SuperPoint extraction/description, adjacent-frame LightGlue matching, VINS-Fusion-based monocular-inertial estimator | `luohongk/SuperVINS`, commit `91e85d72a3828844538715cc4b1cd4b86a2620db` (`supervins1.0`) | Primary scientific match, but the stock artifact is runtime-blocked by two zero-byte CUDA arena limits in addition to missing host dependencies. No run is permitted under the no-source-repair rule. |
| 2 | **Rover-SLAM**, IEEE Transactions on Instrumentation and Measurement 2025, DOI `10.1109/TIM.2025.3527618` | SuperPoint+LightGlue, including monocular-inertial operation | `zzzzxxxx111/Rover-SLAM`, commit `452a37a6d4950762c13c5a9472bb3708302fb3a1` | Official code is present, but its invoked extractor/matcher paths hard-code CUDA and repeat the same zero-memory-limit assignment. Official examples/vocabulary and the GPU runtime are also missing. |
| 3 | **HFNet-SLAM**, Sensors 2023, DOI `10.3390/s23042113` | HF-Net local/global learned features in an ORB-SLAM3 monocular-inertial system | `LiuLimingCode/HFNet_SLAM`; strict paper-era `ecb8018f443e66aacf910bc9aaf17e308bc55570`, executed only through the authors' algorithm-equivalent build-repair commit `c354c72588a97bb6f6a9c7c8317530795956ec80` | First legal A02 whole-system track: the sensor modality matches, while the backend, frame rate, feature budget, and loop machinery remain official-system differences and are reported as such. |
| 4 | **AirSLAM**, IEEE Transactions on Robotics 2025, DOI `10.1109/TRO.2025.3539171` | learned point-line frontend with LightGlue; stereo visual and visual-inertial modes in the paper-era implementation | `sair-lab/AirSLAM`, paper-era commit `2b825166b05b351fc708c70cee3fc8b5a5b380e9` | A02 is ineligible because it has no independent right camera. The legal track is the true-stereo NTNU `fjord_6:0001` window and is reported in a separate different-input whole-system table. |

Under the strict no-source-repair rule, HFNet-SLAM and AirSLAM are the two remaining execution tracks. HFNet-SLAM's strict paper commit is not buildable as checked in because required time-utility sources were omitted and the inference backends were placed across an invalid namespace boundary. The authors' later commit `c354c725...` restores those files and namespace boundaries without changing the tracker, extractor mathematics, thresholds, optimizer, or entry-point control flow; it is therefore classified explicitly as an **official author build repair**, not silently treated as the paper commit. AirSLAM is not currently executable on this host: the paper-era build requires CUDA 12.1 and TensorRT 8.6.1.6, while the recommended official Docker path also requires Docker/NVIDIA Container Runtime; none is installed and the host has insufficient space for the 18.36 GB compressed image plus expansion/build artifacts. No full run is started until the corresponding isolated runtime passes a separate preflight.

SuperVINS is first because it is the closest scientific match: it is monocular-inertial, derives from VINS-Fusion, and replaces the classical frontend with an author-released learned frontend. The repository's later 2026 SuperVINS 2.0 changes are excluded. Commit `91e85d7` is the explicit `supervins1.0` state; its parent `8444f1e` contains the bulk code/weight import. The later 2025-03-07 documentation commits do not define a different algorithm release.

This remains a whole-system comparison, not a feature-budget-controlled ablation. In the 1.0 learned tracker, the YAML `max_cnt` value is read but is not applied to the learned tracking path: the code retains LightGlue matches and assigns new IDs to unmatched SuperPoint detections outside the `min_dist` mask. The official-as-is feature count may therefore differ from AQUA-FE's fixed 350-observation stream. We will report observed feature counts and runtime instead of silently modifying the official tracker to equalize the budget.

## Published methods not admitted to the executable main table

| Method | Publication | Decision |
|---|---|---|
| Mix-VIO | Sensors 2024, DOI `10.3390/s24165218` | Excluded from executable comparison. The official repository has two commits, but its complete tree contains no SuperPoint, LightGlue, ONNX, TensorRT, learned weights, or learned tracker implementation; the checked-in tracker is classical GFTT+PyrLK. Reimplementing the missing paper method locally would violate the official-implementation rule. |
| Practical Deep Feature-Based Visual-Inertial Odometry | ICPRAM 2024, DOI `10.5220/0012320200003654` | Excluded from execution because the authors' linked `LightGlue-VINS-Mono` repository is empty. The earlier local paper-style arm is retained only as a diagnostic. |
| SupSLAM | NICS 2021, DOI `10.1109/NICS54270.2021.9701527` | Literature precedent for learned keypoints with KLT, but no verified author-released complete implementation was found. |
| DL-VINS-Factory | arXiv 2026 | Excluded from the published-method table because it is presently a preprint. Local component-aligned experiments remain ablations only. |
| D2SLAM | IEEE T-RO 2024 | Official system exists, but its distributed/swarm backend and CUDA-only deployment make it substantially less comparable and currently infeasible on this host. |

Purely visual systems such as LF2SLAM, AnyFeature-VSLAM, DROID-SLAM, DPVO/DPV-SLAM, GO-SLAM, and MASt3R-SLAM must be placed in a separate camera-only table using their appropriate alignment. Their Sim(3) results must not be mixed with monocular-inertial metric SE(3) results.

## Frozen execution pivot (before official-system trajectories)

No official-system trajectory existed when this section was frozen. The two executable tracks and their stopping rules are:

### HFNet-SLAM on AQUALOC A02:0005

- Source tree: clean detached checkout `/home/ma/SLAM/HFNet-SLAM-paper-2023-r1`, commit `c354c72588a97bb6f6a9c7c8317530795956ec80`, tree `6619814aed4cd0e4baa2501341a48f753f8ba196`.
- Artifact classification: author-provided post-publication build repair, algorithm-equivalent for the default TensorRT path relative to strict paper-era commit `ecb8018f443e66aacf910bc9aaf17e308bc55570`; this is disclosed in every result label.
- Official model archive: `hfnet-rt.tar.xz`, 121,971,956 bytes, SHA-256 `137ac22e866e4b87e35affe9a8e908d8d38a5ea247e7811e72c9486e21c7c1a3`. Its `HF-Net.onnx` is 132,238,602 bytes with SHA-256 `354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5`.
- The archive's `HF-Net.cache` is not reused for execution because its originating GPU is not proven. A separate writable runtime model directory starts from the verified ONNX only; TensorRT must build a GTX-1650-local cache/engine.
- Input: `datasets/aqualoc/rosbags/archaeo02_4500_5400.bag`, SHA-256 `8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8`, image `/camera/image_raw`, IMU `/rtimulib_node/imu`.
- Dataset changes are limited to EuRoC/ASL directory layout, lossless PNG serialization, the frozen camera/IMU calibration, and conversion of IMU timestamps into the camera clock using the calibrated Kalibr time shift. Images, axes, measurements, learned model, feature thresholds, tracker, optimizer, and loop machinery are not changed.
- The fixed structural prefix is camera indices 0 through 199 (200 images, 9.949129152 s). It is only an input-contract gate and cannot produce an accuracy claim.
- Execution is mandatory and sequential after the runtime is ready: structural prefix audit -> official HF-Net TensorRT model construction and one-image inference -> one prefix mono-inertial run -> one full-window run -> strict common-support evaluation. A failure at any stage stops the track. There is no accuracy-dependent retry or parameter tuning.
- The full result is a whole-system comparison. HFNet-SLAM consumes the official image rate and feature budget; it is not presented as a fixed-350-feature one-variable frontend ablation.

The isolated runtime is rooted at `/home/ma/opt/hfnet_cuda116_trt851_r1`. Its package cache and source-model downloads are kept outside the clean checkout. The intended versions are CUDA compiler/runtime 11.6.2, cuDNN 8.4.1.50, and TensorRT 8.5.1; every NVIDIA package is SHA-verified before extraction. Runtime provisioning is infrastructure work, not an algorithm modification.

### AirSLAM on NTNU fjord_6:0001

- Source tree: clean paper-era AirSLAM commit `2b825166b05b351fc708c70cee3fc8b5a5b380e9`.
- AQUALOC A02 is permanently excluded for this baseline: its bag contains one camera, while the official paper-era AirSLAM loader and initializer require independent timestamp-paired left/right images and valid stereo triangulation. Copying the left image or inventing a baseline is forbidden.
- The legal input is the frozen 45 s NTNU `fjord_6:0001` window, which has 900 real cam0/cam1 pairs with equal header timestamps, distinct payloads, and IMU. Because this gives AirSLAM stereo information unavailable to the monocular B1 arm, it is reported only in a separate whole-system/different-input table.
- A unique three-pair smoke input has already passed the converter contract at `logs/airslam_adapter/ntnu_fjord6_0001_prefix3_asl_v1`; it is explicitly `SMOKE_PREFIX_NOT_EVALUABLE`, did not start AirSLAM, and cannot be cited as a trajectory result.
- Full conversion, model construction, and trajectory execution remain stopped until a stock CUDA 12.1/TensorRT 8.6.1.6 runtime passes on the GTX 1650. If that smoke fails or runs out of memory, the official AirSLAM result is reported as runtime-incompatible rather than repaired at the source level.
- The available NTNU reference is a ReAqROVIO four-camera-plus-IMU trajectory proxy rather than independent ground truth. Any eventual result must carry that caveat and use a separate strict common-support SE(3) table.

## SuperVINS 1.0 execution contract

Only high-level dataset adaptation is allowed:

- official repository and commit remain clean;
- official SuperPoint and LightGlue ONNX models are used;
- official temporal matching and VINS estimator code remain unchanged;
- AQUALOC image and IMU topic names, camera calibration, camera-IMU extrinsics, noise values, time offset, output path, and loop-closure switch are supplied through a new dataset YAML;
- the raw image+IMU bag is replayed directly; no project feature bag or project tracker is injected;
- loop closure is disabled for the VIO comparison;
- the official trajectory is converted only after the run, without changing poses;
- B1 and SuperVINS are evaluated on one strict common temporal support, while being identified as different complete systems rather than a one-variable frontend ablation.

The first data target is the already characterized AQUALOC A02:0005 window. It is an integration/compatibility window, not held-out evidence. Execution order is fixed:

1. fail-closed repository/runtime/input preflight;
2. official model/session construction smoke;
3. one fixed short raw-bag replay;
4. if and only if initialization and a finite nonempty trajectory succeed, one full A02 replay;
5. one strict common-support G0 evaluation;
6. only after the full endpoint is valid, preregister fresh cross-dataset windows before expansion.

No accuracy-dependent parameter tuning or repeat-until-success is allowed. Infrastructure failures may be corrected only when the method, weights, estimator, dataset window, and scientific thresholds remain unchanged and the failed attempt is retained.

## Current infrastructure boundary

The machine has Ubuntu 20.04, ROS Noetic, an NVIDIA GTX 1650 4 GB GPU, and a compatible NVIDIA driver. It does not currently have `nvcc`, CUDA runtime libraries, ONNX Runtime GPU, Docker, or TensorRT. SuperVINS 1.0 unconditionally registers the ONNX Runtime CUDA execution provider; its `*_cpu.onnx` filename does not make the unmodified binary CPU-capable.

There is also a stock-code blocker independent of the host installation. Both the extractor and matcher explicitly set `OrtCUDAProviderOptions::gpu_mem_limit = 0`. ONNX Runtime 1.16.3 defines the default/unlimited value as `SIZE_MAX`; its CUDA allocator forwards this field into a BFC arena whose available bytes are derived from the supplied total limit. A zero limit therefore rejects every positive allocation. Correcting the field to `SIZE_MAX` would be a small non-algorithmic artifact repair, but it is still a source edit and is not silently allowed under the present no-low-level-modification rule. The current state is **runtime-blocked, not scientifically failed**.

The runtime must be provisioned in an isolated location and verified before any AQUALOC replay. Replacing the CUDA provider with CPU code, replacing LightGlue, exporting project feature messages, or feeding the fixed local VINS binary would cease to be the official SuperVINS baseline and is forbidden on this track.

The paper-era sparse checkout is now present at `/home/ma/SLAM/SuperVINS-paper-1.0-r1`, clean at commit `91e85d72a3828844538715cc4b1cd4b86a2620db` with Git tree `036391d321d4ea9a914739a454c20976f01f7bd7`. Two earlier checkout attempts are retained as infrastructure-incomplete directories and are excluded from execution. The five official ONNX artifacts in the valid checkout are:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `disk.onnx` | 4,418,235 | `f02f18e254bd52d978981c715a4e7961f15afaa23290379b9b357f6745df12c4` |
| `disk_lightglue_fused.onnx` | 45,765,432 | `eff867103123a64720a1209218ff4bfa351a2d9b21a04b667265d794e9462cc9` |
| `superpoint.onnx` | 5,272,808 | `234d12c9f523292efb34e0ca513b011050b0c052700da9c01787b9356a1138d2` |
| `superpoint_lightglue_fused.onnx` | 45,632,517 | `8463182c165254b8cf182def813160691a5f3a455d95b4346e1b3ebf8a7709cf` |
| `superpoint_lightglue_fused_cpu.onnx` | 45,634,561 | `4f44f440bc08f71afc2ba619d33154d395284001c1387b14a3b58a3224f9490e` |

The fail-closed preflight is `scripts/preflight_published_supervins_v1.py`, SHA-256 `0e7abffd9c1d21954f378c6e600429e3e53c9b8f1fd9735083c30dcb6753b11c`; its test has SHA-256 `ff8c659fae398e4c0061c72779f4d9b7b2b820d752573bd1c030784e2907b1c8`. Twelve isolated tests pass. It also freezes the playable A02 raw window `datasets/aqualoc/rosbags/archaeo02_4500_5400.bag` (222,477,260 bytes, SHA-256 `8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8`) and the official-run camera input `datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_calibration_files/archaeo_camera_calib.yaml` (337 bytes, SHA-256 `e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2`). The runtime gate requires ONNX Runtime version 1.16.3 and successful dynamic loading of its core, shared-provider, and CUDA-provider libraries; `nvcc` is recorded only as build-environment information. A `READY` result still requires the separately prescribed official-model `OrtSession` construction smoke before any replay. The real stock checkout returns RC 1 / `RUNTIME_BLOCKED`, with no integrity error and blockers including `UPSTREAM_CUDA_MEMORY_LIMIT_ZERO` and the absent ONNX Runtime GPU installation. Editing away the upstream line without reclassifying the method instead returns RC 2 / `INTEGRITY_ERROR`.

## Evidence sources queried

- Crossref REST API (`https://api.crossref.org/works`) for title, DOI, publication type, and year.
- Publisher/DOI records for the formally published versions.
- Author repositories and their complete Git histories/trees for implementation and release-state verification.
- Local read-only environment inspection for ROS, GPU, CUDA, ONNX Runtime, disk, and existing checkouts.

The relevant Crossref record fields are: `SuperVINS -> DOI 10.1109/jsen.2025.3556257, type journal-article`; `Rover-SLAM -> DOI 10.1109/tim.2025.3527618, type journal-article`; `AirSLAM -> DOI 10.1109/tro.2025.3539171, type journal-article`; `Mix-VIO -> DOI 10.3390/s24165218, type journal-article`.
