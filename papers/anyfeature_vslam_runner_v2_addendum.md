# AnyFeature-VSLAM runner-v2 infrastructure addendum

Status: **FROZEN BEFORE RUNNER-V2 PREFLIGHT OR ANY OFFICIAL BINARY START**.

This addendum does not alter the scientific choices, input window, feature methods, checkpoint, thresholds, feature budget, official binary, feature settings, vocabulary, output paths, validity gates, or evaluation procedure frozen in `anyfeature_vslam_r2d2_a02_preregistration.md` (SHA-256 `74eb99a57aee660270561850a0b72f288951a80082b9c7a6200ecfed60a3c680`). It authorizes one project-side execution-harness correction before any AnyFeature-VSLAM process has started.

## Preserved invalid v1 call

The first call to the frozen v1 runner returned RC 2 during its project-side `ldd` preflight. The official executable did not start, the reserved experiment folder remained absent, and no upstream stdout, stderr, statistics, trajectory, or accuracy output existed. The failure is preserved without rerunning v1 in `anyfeature_vslam_r2d2_smoke_preflight_failure_r1.json` (SHA-256 `7571e76a55b69eeb6c12d999c05ceb74e06c26f921429a4bfd81549587619af2`).

The observed ELF graph was closed: `ldd` returned zero, reported no `not found`, and resolved `libopencv_core.so.409` inside the frozen r3 environment. The v1 checker nevertheless called `Path.resolve()` on that SONAME symlink, obtained `libopencv_core.so.4.9.0`, and required the real-target spelling to occur literally in normal `ldd` output, which reports the SONAME spelling. This is a deterministic wrapper false negative, not an R2D2 reader, AnyFeature-VSLAM runtime, initialization, trajectory, or accuracy result.

## Sole permitted harness correction

- Frozen v1 runner: `scripts/run_anyfeature_vslam_official_v1.py`, SHA-256 `0c60fa8126dbc9dfb309b995c15bb324eea29899b07145afc69c10324538707f`.
- New v2 runner: `scripts/run_anyfeature_vslam_official_v2.py`, SHA-256 `93f0342903e4e5ab9e2a3618ca77d08a7598ff19d67af42f0719a63b42dc5db3`.
- New v2 tests: `scripts/tests/test_run_anyfeature_vslam_official_v2.py`, SHA-256 `b9fd44e24d982445d3f6776d41ec4eaa291e081b28226cae21d517a656110847`.
- Unchanged v1 tests: `scripts/tests/test_run_anyfeature_vslam_official_v1.py`, SHA-256 `952777adbfb0add775cce5ad1df2e62aed2c023fc81d813188e99b5b982ac3af`.

V2 hard-binds and reuses the frozen v1 contract. Its only semantic change is the OpenCV-core `ldd` identity test: the left-hand SONAME must remain exactly `libopencv_core.so.409`; the right-hand `.409` symlink spelling or `.4.9.0` real-target spelling must resolve strictly to the same file under the frozen r3 `env/lib`. `not found`, a wrong SONAME, an environment-external OpenCV path, a missing target, or a different target remains a hard failure. V2 does not edit or wrap the official binary, source tree, input files, configuration, or outputs.

The v2 implementation avoids writing v1 module globals and binds the unchanged v1 executor bytecode to call-local globals. Synthetic verification passed v2 9/9 and unchanged v1 7/7 tests, including a real temporary `.409 -> .4.9.0` symlink, normal `.409` `ldd` text, target-spelling acceptance, wrong-SONAME/outside-env/`not found` rejection, no-clobber behavior, all three frozen profiles, and overlapped two-thread execution. An independent byte-level review returned GO with P0=0 and P1=0 before this addendum was frozen.

## One-way execution rule

1. Run v2 **preflight only** for the already materialized one-image R2D2 smoke view and write the unique no-clobber report `/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/adapter_reports/a02_r2d2_smoke_preflight_v2_r1.json`.
2. If that preflight is not RC 0 with `PREFLIGHT_READY`, stop the R2D2 arm permanently. No v3, alternative path spelling, second smoke frame, or additional harness repair is permitted in this track.
3. If it passes, invoke the unchanged official binary exactly once through v2 with the same `r2d2-smoke` profile, one-row sequence view, and reserved experiment folder. The original preregistration's binary RC, reader, finite-value, crash, and no-retry rules then apply without exception.
4. A successful official smoke permits the frozen full continuation. All subsequent AnyFeature runner calls in this track use the same v2 bytes. ORB32 remains the mandatory first full arm; R2D2 remains the second full arm. No accuracy value is read before both full attempts are sealed.

The invalid v1 call cannot be erased, described as a successful smoke, or counted as an upstream attempt. Conversely, the authorized v2 call cannot be used to tune the model or choose a result: no official process, feature outcome, initialization state, trajectory, or accuracy value existed when this addendum was frozen.

## Unchanged frozen identities

- Official AnyFeature-VSLAM paper commit: `6aa014b724f7a61bcbff2f8f28f20836986a43dc`.
- Official binary SHA-256: `9adb623fc8d83ce35297be7a7d810d269cd65273bd0f4fb1bddebbec0b8bdd59`.
- Official core-library SHA-256: `eea4a5a6c5dccb5825a8e6a1a3249c6b808881a22c7fe301d0a2a90efaa99954`.
- Official DBoW2-library SHA-256: `7215c8425e3620834ef24ea17f26fd0635b15d9d85b0093b00220e553a40c8c5`.
- R2D2 smoke-view manifest SHA-256: `68ac4ec0fc1217c9e4950a20cd97e46d1f96c47ec68ee0bc2e42bc5db7f87ac8`.
- A02 full-camera conversion manifest SHA-256: `2f08cc97e71d44e56d90720fbdd5bf925c1c7e5892096743f67265fc2df34afe`.
- A02 full-camera sequence identity: `d43ee7b00bf759ca3c5c2c60e532e453a797300d34a830d7777999931d5fb6e3`.

