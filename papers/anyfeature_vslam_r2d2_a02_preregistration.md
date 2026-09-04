# AnyFeature-VSLAM R2D2 A02 formal-track preregistration

Status: **FROZEN BEFORE SCIENTIFIC EXECUTION**. This document is the execution authority for this track. At the original freeze no local AnyFeature-VSLAM or R2D2 checkout, retained model/vocabulary download, build, learned-feature extraction, AnyFeature-VSLAM trajectory, or trajectory-accuracy result existed for this track. The contract was amended during identity-only provisioning, before any build, model inference, dataset export, SLAM execution, or trajectory result, to close keyframe-evaluation, zero-feature, runtime-cache, and paper-era input-format ambiguities found by independent review. After infrastructure-only provisioning and still before any model inference, real dataset export, SLAM execution, or trajectory result, the independently audited adapter required one reserved one-image sequence-view path to make step 5 executable; that path alone was added to the frozen command role and reserved-path list. Read-only source inspection, byte downloads, environment construction, and source-unmodified compilation are not experiment results.

Date: 2026-08-11 (Asia/Shanghai)

## Claim boundary

This track runs the author-released **AnyFeature-VSLAM** system from RSS 2024 (DOI `10.15607/RSS.2024.XX.084`) with R2D2 learned keypoints/descriptors, plus an `orb32` control in the same AnyFeature-VSLAM binary. It is a whole-system, monocular camera-only comparison. It does not consume IMU measurements and must appear only in a separate **camera-only / Sim(3)** table. Its APE/RPE must never be mixed with monocular-inertial metric-SE(3) results.

The A02 window is development-exposed and is an integration/comparison window, not fresh held-out evidence. The official system retains its own feature count, matching, mapping, loop closing, and optimization behavior. No AQUA-FE feature bag, tracker, matcher, backend, or feature-budget cap is injected.

## Frozen upstream identity

### AnyFeature-VSLAM paper snapshot

- Repository: `https://github.com/alejandrofontan/AnyFeature-VSLAM.git`
- Paper-era commit: `6aa014b724f7a61bcbff2f8f28f20836986a43dc` (2024-07-13; the final commit before RSS XX began on 2024-07-15).
- Git tree: `36b264e1da05c6fe9cd987965e9a75ba96930b63`.
- `Thirdparty/DBoW2` submodule: `https://github.com/alejandrofontan/DBoW2.git`, commit `f4d585b45237836dbde757c0c8ec8b098ad1164a`.
- License: GPL-3.0; `License-gpl.txt` SHA-256 `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`.
- The untagged 2025/2026 `main` revisions are excluded.

Frozen paper-snapshot files:

| File | SHA-256 |
|---|---|
| `build.sh` | `649008a68ce60505209f25cac417db9ac33096dcba210d114be4bbac4ae4e396` |
| `environment.yml` | `39ba3cbc54dee52ad1b408f359efc1c4d600153daa58502e8ab306fb29cb92a2` |
| `src/mono.cpp` | `6b7926aefa29d93285b80b2f35644cf1574aa6f8f76b707f3e0847cad60e0a82` |
| `src/Utils.cpp` | `8af8f97cfe31f5862263fba04f5074fc92eea019cee31dc8185cd6f7e59c2e28` |
| `src/Image.cpp` | `95d7f6f8493c7383c023967b8c7f8db4531002c0012a26ef58e1c87e5564dccd` |
| `src/Feature_r2d2_128.cpp` | `21e56aab8997ea8a9ed05a3534ea33ffc57f6ff5ce1f039d57bd76f84708b512` |
| `settings/r2d2_128_settings.yaml` | `375ae1bdcfe92068a665f16b9943b09fb0c830be471f675ddb85289442526878` |
| `settings/orb32_settings.yaml` | `38a19b5f45863f64ee81b3306b3c66b43c4f587712fdda8babaef9b5f04c9647` |

The feature strings are frozen to `r2d2_128` and `orb32`. Visualization is disabled (`Vis:0`) and image resizing is disabled (`FixRes:0`).

### R2D2 implementation choice

- Official repository: `https://github.com/naver/r2d2.git`.
- Commit: `0ff8f6afcbea91f19613d0cb7d93143a977830f5`.
- Git tree: `47719bdaca38c6d90c124128492249818a442b95`.
- License: CC BY-NC-SA 3.0, non-commercial use only; `LICENSE` SHA-256 `2891af7a316a5783cdbde291bb6122637f0934473997fd7a335f8b668e2dcd7f`.
- Checkpoint: `models/r2d2_WASF_N16.pt`, 1,950,677 bytes, SHA-256 `9ae90e02a9a133d100ca7aeaa32f4d4d7736a6dd222a530a25c8f7da5e508528`.
- Exact checkpoint URL: `https://raw.githubusercontent.com/naver/r2d2/0ff8f6afcbea91f19613d0cb7d93143a977830f5/models/r2d2_WASF_N16.pt`.
- Official extractor `extract.py` SHA-256 `1720d85eadbcca605eafd35d430b41be12cdc22cd39b478b4fc5ad2ce977ad80`.

AnyFeature-VSLAM's paper and repository name R2D2 but do not identify a checkpoint. `r2d2_WASF_N16.pt` is therefore disclosed as a frozen implementation choice, not claimed to be the authors' exact unpublished experimental checkpoint. It is selected before A02 inference or accuracy because the R2D2 authors identify it for visual-localization experiments and use it in their extraction example. No checkpoint comparison is allowed.

R2D2 extraction is CPU-only (`--gpu -1`) and uses the official defaults explicitly: `--top-k 5000`, `--scale-f 1.189207115002721`, `--min-size 256`, `--max-size 1024`, `--min-scale 0`, `--max-scale 1`, `--reliability-thr 0.7`, and `--repeatability-thr 0.7`. Proposal order from the official `.r2d2` archive is preserved. No threshold, scale, model, or proposal-count search is allowed.

### Paper-era vocabularies

Both vocabularies come only from the authors' Hugging Face dataset revision `b5fed77abd7662c11b6669caa104ff8db22bddfb`. The files were uploaded on 2024-07-08, before RSS XX.

| Arm | File | Bytes | SHA-256 (HF LFS object) |
|---|---|---:|---|
| R2D2 | `R2d2_DBoW2_voc.txt` | 1,393,396,568 | `b169095f0ef57eaf5e6556db68f9df4eddd56970c35f983c7d00f5d3fa8bce73` |
| ORB32 | `ORBvoc.txt` | 145,250,924 | `f8dd027f7a6cb88129821341194d7f2c75b77b3394257ddd0d2229863d1a3570` |

Exact URL prefix: `https://huggingface.co/datasets/fontan/anyfeature_vocabulary/resolve/b5fed77abd7662c11b6669caa104ff8db22bddfb/`. The dataset card declares no license metadata, so the vocabulary files are used internally from the official source and are not redistributed. Only these two files may be fetched; `build.sh` must not trigger the seven-vocabulary bulk download.

## Frozen input and dataset-only adaptation

- Window: AQUALOC archaeology `A02:0005`.
- Raw bag: `datasets/aqualoc/rosbags/archaeo02_4500_5400.bag`, 222,477,260 bytes, SHA-256 `8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8`.
- Image topic: `/camera/image_raw`; ground-truth topic for later evaluation: `/aqualoc/colmap_gt`.
- Formal prefix: raw camera indices **0 through 199 inclusive**, exactly 200 images. First/last header timestamps are `1542829016700435392` and `1542829026649564544` ns; span `9.949129152 s`.
- Full window, reachable only through the gates below: raw camera indices 0 through 900 inclusive, exactly 901 images.
- Images are losslessly serialized as PNG without resizing, enhancement, masking, frame dropping, or timestamp alteration. The paper-era loader input is the headerless, comment-free `rgb.txt`; each line is exactly `absolute_epoch_sec.nanosec rgb/<timestamp_ns>.png`, with nine fractional digits derived from the integer nanosecond timestamp without a floating-point formatting round trip.
- Camera calibration is the frozen AQUALOC radtan calibration: `fx=543.3327734182214`, `fy=542.3987729825660`, `cx=489.0253604224790`, `cy=305.3872771200281`, `k1=-0.1255945656257394`, `k2=0.053221287232781606`, `p1=0.0000994070021080493`, `p2=0.00009550660927242349`, `k3=0`, width `968`, height `608`, fps `20`. Source calibration SHA-256 is `e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2`.
- IMU is not exported or consumed. This modality difference is mandatory in every label and table caption.

The same PNG files, `rgb.txt`, calibration, paper commit, built binary, viewer setting, image-size setting, output parser, and trajectory gate are used by R2D2 and ORB32. Arm-specific differences are only the official `Feat` selection, its official settings YAML, its corresponding official vocabulary, and the R2D2 feature files required by the learned arm. At 968x608, the unchanged paper code uses the same target of 2,000 features during normal tracking and 4,000 during monocular initialization for both arms; startup must report both `Number of Features: 2000` and `Number of Features: 4000`. R2D2 `top-k=5000` is an offline candidate limit, not the SLAM feature budget.

## Sole permitted interface repair: float32 to little-endian float64

The official R2D2 extractor writes finite NumPy `float32` arrays. The frozen AnyFeature-VSLAM `loadBinFile` in `src/Utils.cpp` reads raw elements with `sizeof(double)`. Feeding float32 bytes directly is therefore an interface/type mismatch, not a scientific failure.

The only permitted repair is a project-side serialization adapter after official R2D2 inference and before AnyFeature-VSLAM input. It must not edit either upstream checkout. For every official `.r2d2` archive it must:

1. load `rgb/<timestamp_ns>.png.r2d2` with `allow_pickle=False`, require `imsize == [968,608]` in the official `[width,height]` order, and require `keypoints` shape `(N,3)`, `descriptors` shape `(N,128)`, and `scores` shape `(N,)`, with one common `N` and `0 <= N <= 5000`; for nonempty arrays all values must be finite, coordinates in bounds, and scales positive;
2. preserve all rows and their order; perform no filtering, sorting, renormalization, clipping, thresholding, or descriptor modification;
3. cast each float32 value exactly to IEEE-754 little-endian float64 (`<f8`) and write C-order raw files to `r2d2/keypoints/<stem>.bin`, `r2d2/descriptors/<stem>.bin`, and `r2d2/scores/<stem>.bin`;
4. require exact byte counts `N*3*8`, `N*128*8`, and `N*8`; decode each output as `<f8` and require exact equality to the source float32 values after float64 widening; a legitimate `N=0` frame produces three zero-byte files and is retained for the official SLAM system rather than screened out by the adapter;
5. record source archive and output hashes, dtype, shapes, byte order, image identity, and adapter hash in a no-clobber manifest.

Because every binary32 value has an exact binary64 representation, this changes representation only. Any change to coordinates, scores, descriptors, ordering, count, learned inference, matching, or AnyFeature-VSLAM's reader is a forbidden low-level algorithm/source modification. The adapter and synthetic tests must be independently reviewed and hash-frozen before the one-image smoke; their later hashes do not amend any scientific choice in this document.

## Same-system ORB32 control

`orb32` is the mandatory control, invoked by the same built `bin/mono` with `Feat:orb32`, paper `settings/orb32_settings.yaml`, and paper-era `ORBvoc.txt`. It is not an external ORB-SLAM2 result. It controls the AnyFeature-VSLAM build, monocular backend, calibration, image layout, timing, trajectory writer, and evaluation path while changing the selected official feature type.

There are no short-window SLAM screening arms. After the common image contract and the R2D2 data/bin plus one-image ingestion closure pass, ORB32 and R2D2 each receive exactly one complete 901-image run. The fixed order is ORB32 then R2D2, but ORB32's scientific outcome cannot suppress R2D2 (R2D2 may legitimately rescue an ORB failure), and R2D2's outcome cannot erase or trigger a repeat of ORB32. A learned-only closure failure prevents an uninterpretable R2D2 full run but does not suppress the already-prespecified ORB32 full control when the common image/build contract is valid.

## Fixed resource and integrity gates

Before any checkout or retained download, all gates must pass:

- free space at `/mnt/data` at least `18 GiB`; free space at `/` at least `8 GiB`;
- available RAM at least `12 GiB`;
- all checkout, environment, package cache, build, vocabulary, feature, and run paths reside under `/mnt/data`; the root filesystem receives no large artifact;
- CPU R2D2 extraction only; CUDA/TensorRT availability and APE values cannot affect provisioning;
- no existing reserved output path, and every later command is no-clobber;
- exact upstream identities, hashes, licenses, bag hash, and calibration source hash match this document.

All provisioning and inference cache variables are set explicitly before their first writer: `MAMBA_ROOT_PREFIX`, `CONDA_PKGS_DIRS`, `PIP_CACHE_DIR`, `HF_HOME`, `XDG_CACHE_HOME`, and `TMPDIR` must resolve below `/mnt/data/opt/anyfeature-paper-2024-r1/`. No solver, pip, Hugging Face, or temporary extraction cache may default to the root filesystem.

The conservative full-track peak budget is `<=16 GiB`: isolated conda environment/package cache/build `<=7 GiB`, the two final vocabularies `1.54 GB`, images about `0.21 GB`, float32 R2D2 archives `<=2.4 GB`, widened float64 bins `<=4.8 GB`, and manifests/logs/repositories below `0.5 GB`. After a successful build, dispensable package caches must be purged before real extraction. Immediately before any full-window materialization, `/mnt/data` must again have at least `9 GiB` free; otherwise the track stops without a full run.

The official unpinned `environment.yml` must be solved once. The explicit package URLs/build strings and environment manifest are frozen before build. No dependency version may be selected based on build/runtime accuracy. `build.sh` lacks `set -e`; therefore its return code is insufficient. A valid build additionally requires `bin/mono` to exist, a recorded SHA-256, `ldd` with no `not found`, and an independent `cmake --build build --config Release` return code of zero. The checkout must remain clean. A source or CMake edit is forbidden.

R2D2 inference uses a separate CPU-only execution environment under `/mnt/data/opt/anyfeature-paper-2024-r1/r2d2-pyenv`. Before inference, its Python executable, `pip freeze`, `sys.path`, CPU-only Torch status, and versions plus file hashes for Torch, torchvision, NumPy, Pillow, SciPy, tqdm, and matplotlib are sealed. No package or model may be swapped after the one-image result. Neural extraction wall time is recorded separately from `bin/mono` wall/internal tracking time. Because R2D2 is precomputed while ORB32 detects online, `bin/mono` timing alone is not an end-to-end learned-versus-classical runtime comparison.

The target vocabulary directory is created and populated with only the two verified files before `build.sh` is invoked, so its bulk-download branch is not entered.

## Sequential execution and STOP rules

No accuracy value is read until both full runs and their structural/trajectory audits have terminated. The 200-image prefix is a data/serialization contract only. **AnyFeature-VSLAM is never run on that 200-image prefix**, because a short monocular-keyframe run could artificially censor a valid slow initialization.

1. **Freeze/space gate.** Verify this document's SHA-256, absence of reserved paths, disk/RAM gates, and input hashes. Failure is terminal `STOP_RESOURCE_OR_INTEGRITY`; do not clone or download.
2. **Provision once.** Checkout both exact commits, initialize only the frozen DBoW2 submodule, fetch the exact checkpoint and two exact vocabularies, create the isolated official environment, save its explicit lock, and build the unchanged paper snapshot. Any identity, license, solve, compile, link, or clean-tree failure is `STOP_PROVISIONING`; retain logs and do not repair source.
3. **Structural prefix export.** Export exactly A02 indices 0..199 once and audit count, order, timestamps, PNG pixel identity, dimensions, calibration, and manifest. Failure is `STOP_INPUT_CONTRACT`; no model inference or SLAM run.
4. **R2D2 prefix data/bin contract.** Run the official R2D2 extractor once for indices 0..199 with the frozen CPU parameters, convert only their representation through the frozen adapter, and audit every archive/bin for identity, shape, finiteness, bounds, byte order, byte count, row order, and hash. No SLAM binary is invoked on this prefix. Failure is `STOP_R2D2_DATA_CONTRACT` and forbids the learned full run and any retry with another model/threshold.
5. **One-image R2D2/float64 ingestion smoke.** Using only the already-audited index-0 PNG and bins, materialize the reserved one-row sequence view `/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_frame000_smoke_view_r1` and invoke one non-scientific one-image R2D2 ingestion smoke with that exact path as `sequence_path`, the unchanged built system, and visualization off. Index 0 must be nonempty so that the reader is actually exercised. It may verify only that the official reader consumes the `<f8` interface without dtype/shape/load failure; an empty trajectory is expected/permitted and is not inspected for accuracy. Require binary RC 0, no crash, and no reader/trajectory/stdout interface NaN/Inf or out-of-bounds diagnostic. The known empty-map statistics path may compute `0/0` and is excluded from the smoke finite-value gate. Failure is `STOP_R2D2_CLOSURE`; no R2D2 full run and no retry. This smoke does not authorize or constitute a 200-image SLAM run.
6. **Full resource and input gate.** Recheck at least `9 GiB` free on `/mnt/data`, then export A02 indices 0..900 exactly once. The verified prefix PNGs and R2D2 products are reused byte-for-byte; indices 0..199 are not inferred again. Extract/convert only indices 200..900 and audit a single complete 901-frame manifest. A common image/calibration/timestamp failure stops both arms. An R2D2-only archive/bin failure stops only the learned arm; the full ORB32 control remains mandatory when the common input is valid.
7. **ORB32 full run.** Run the same-system ORB32 arm exactly once on all 901 images with visualization off. Seal stdout, stderr, `/usr/bin/time -v`, command, environment, binary/config/vocabulary/input hashes, return code, and all output hashes. Its scientific success or failure does not decide whether the already-prespecified R2D2 full run occurs.
8. **R2D2 full run.** If and only if the R2D2 data contract and one-image ingestion smoke passed, run the R2D2 arm exactly once on the same 901 images. Seal the same provenance/runtime artifacts. Do not rerun ORB32 or R2D2 for any initialization or accuracy outcome.
9. **Full validity audit.** Independently classify each full output. A syntactically usable trajectory requires RC 0, a present nonempty keyframe trajectory, finite numeric pose fields, and strictly increasing unique timestamps. Pose count, span, and common support are reported separately and do not retroactively relabel a syntactically valid but sparse output as a runtime failure. Any runtime or syntax failure is a retained whole-system usability result, not permission to change the window, checkpoint, configuration, or runtime.
10. **Accuracy evaluation.** Only after both mandated full attempts are sealed, evaluate once against the 46 fixed 1 Hz `/aqualoc/colmap_gt` poses, explicitly labeled the same-image COLMAP plus pressure-scale **reference proxy**, not independent ground truth. If learned-only closure failed before its mandated attempt, no pairwise accuracy evaluation is made. For each arm and reference timestamp, use an exact keyframe pose when present; otherwise require keyframes on both sides, forbid extrapolation, require their gap to be at most `2.0 s`, interpolate translation linearly, and interpolate orientation by shortest-arc normalized quaternion SLERP. Interpolation never creates a new reference timestamp. Take the intersection of reference timestamps valid for both arms as the single common mask. On that identical mask, fit a separate Umeyama Sim(3) from each arm's world-to-camera position series to the proxy positions, rotate orientations consistently, and compute translational APE plus translational RPE at the fixed `1 s` reference-grid delta. Numeric pairwise claims require common reference coverage at least `0.70`, at least `30` common APE poses spanning `10 s`, and at least `10` common RPE pairs. If support is invalid, report only each arm's initialization/usability and the support failure; direct nearest-neighbor matching, GT reuse, alternative interpolation, extrapolation, or a one-sided mask is forbidden.

Passing a gate depends only on integrity, structure, initialization, and finite trajectory validity, never on whether R2D2 has lower APE/RPE than ORB32 or AQUA-FE. No full-window choice, parameter change, rerun, alternative alignment, or additional sequence may be authorized from observed accuracy. Any future sequence is a new preregistration.

## Frozen command roles

The exact absolute paths and final binary hash are recorded after provisioning, before any real run. The semantic command fields are already frozen:

```text
bin/mono
  anyfeat:<paper-checkout-with-trailing-slash>
  Voc:<verified-vocabulary-directory>
  FeatSet:<paper settings/{orb32|r2d2_128}_settings.yaml>
  Vis:0
  sequence_path:</mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_frame000_smoke_view_r1 for the one-image smoke, or the frozen A02 full export for a full arm>
  exp_folder:<new arm-specific output directory>
  exp_id:0
  Feat:{orb32|r2d2_128}
  FixRes:0
```

No argument may be silently omitted or changed. The output directory must exist but the trajectory/statistics targets must not. Environment, stdout, stderr, return code, `/usr/bin/time -v` output, and every source/input/output hash are retained.

## Reserved paths

These paths must be absent before provisioning and are never overwritten or resumed:

```text
/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r1
/mnt/data/SLAM/r2d2-official-r1
/mnt/data/opt/anyfeature-paper-2024-r1
/mnt/data/opt/anyfeature-paper-2024-r1/r2d2-pyenv
/mnt/data/opt/anyfeature-paper-2024-r1/mamba-root
/mnt/data/opt/anyfeature-paper-2024-r1/pip-cache
/mnt/data/opt/anyfeature-paper-2024-r1/hf-cache
/mnt/data/opt/anyfeature-paper-2024-r1/xdg-cache
/mnt/data/opt/anyfeature-paper-2024-r1/tmp
/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_prefix200_r1
/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_full_r1
/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_frame000_smoke_view_r1
/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/model_smokes/a02_frame000_r1
/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/full_runs/a02_orb32_r1
/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/full_runs/a02_r2d2_r1
/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/evaluation/a02_orb32_vs_r2d2_r1
```

All failures, including partial provisioning and prefix data-contract failures, remain hashed evidence. A new attempt requires a new revision suffix and a new preregistration/addendum written before that attempt.
