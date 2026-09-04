# AnyFeature-VSLAM provisioning addendum r3

Date: 2026-08-11 (Asia/Shanghai)  
Status: **FROZEN BEFORE R3 SOLVE, BUILD, MODEL INFERENCE, DATA EXPORT, OR SLAM**

This addendum authorizes one final infrastructure-only successor to the retained r2 provisioning failure in `anyfeature_vslam_provisioning_r2_result.json` (SHA-256 `b1bf61acd4f08e1a2f8a05063bc59d0ecafdef976acf52865542c909255e2f43`). It explicitly supersedes only the sentence in the r2 addendum that prohibited an r3 dependency attempt. It does not amend the scientific arms, source commit, checkpoint, vocabularies, A02 window, adapter semantics, run order, stopping rules, or evaluation contract in `anyfeature_vslam_r2d2_a02_preregistration.md` (SHA-256 at this freeze: `0d6c5d59651371821e0993985b59db1e299c56fdead5ae14938c79fc26bbc37b`).

## Why this final attempt is permitted

R2 did not fail by source compilation, model behavior, feature behavior, tracking, trajectory, timing, or accuracy. The unchanged paper snapshot built successfully, including independent DBoW2 and AnyFeature builds. Its runtime closure failed before any scientific input was produced because the official `fontan` BRISK and AKAZE package binaries have ELF `DT_NEEDED` entries for OpenCV 4.9 SONAMEs:

- BRISK requires `libopencv_features2d.so.409` and `libopencv_core.so.409`.
- AKAZE requires `libopencv_imgcodecs.so.409`, `libopencv_calib3d.so.409`, `libopencv_imgproc.so.409`, and `libopencv_core.so.409`.

R2 contained OpenCV 4.10 and therefore only `.410` libraries. The r3 correction is mechanically determined by these immutable official binary dependencies; it is not a version search or a result-dependent tuning decision.

R3 changes exactly one r2 constraint:

- `opencv=4.9.*` instead of `opencv=4.10.*`

The other r2 constraints remain byte-for-byte in intent:

- `python=3.10.*`
- `eigen=3.4.*`
- `cmake=3.29.*`

Every other package is selected by the unchanged official `environment.yml`. No source, CMake, header, algorithm, feature parameter, vocabulary, model, dataset, or evaluator may be changed. If this exact environment does not solve, build, or close under `ldd`, r3 is terminal `STOP_PROVISIONING`; there is no r4 or further dependency search.

## Isolation and evidence retention

- New clean checkout: `/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r3`, fixed to commit `6aa014b724f7a61bcbff2f8f28f20836986a43dc`, tree `36b264e1da05c6fe9cd987965e9a75ba96930b63`, and DBoW2 gitlink `f4d585b45237836dbde757c0c8ec8b098ad1164a`.
- New runtime root: `/mnt/data/opt/anyfeature-paper-2024-r3`.
- The r1 and r2 result JSON files, solve plans, explicit locks, build logs, RC files, `ldd` evidence, and hashes remain retained. Failed r2 environment/package-cache bytes may be removed only after sealing r2 and only to restore the preregistered free-space margin.
- The exact already-verified ORB32/R2D2 vocabulary bytes may be reused read-only. They are scientific assets with fixed identities, not build outputs.
- `MAMBA_ROOT_PREFIX`, `CONDA_PKGS_DIRS`, `PIP_CACHE_DIR`, `HF_HOME`, `XDG_CACHE_HOME`, and `TMPDIR` must all resolve under the new r3 runtime root. No large package or build artifact may be written to `/`.
- The source checkout remains tracked/staged clean. Generated build paths are classified separately and never treated as source modifications.

## R3 gates

1. Before creation, the r3 checkout and runtime paths are absent. After documented r2 cleanup, `/mnt/data` must have at least 18 GiB free, `/` at least 8 GiB, and available RAM at least 12 GiB.
2. Resolve exactly once using the unchanged official YAML plus the four fixed constraints above. Seal the JSON solve plan before installation; require installed `(name, version, build)` identities to match it exactly.
3. Run unchanged `build.sh -v`. Independently require DBoW2 and AnyFeature builds to return zero, `bin/mono` to exist, and `ldd` on the executable and project libraries to contain no `not found`.
4. Require runtime OpenCV identity `4.9.*` and require all official BRISK/AKAZE OpenCV `.409` dependencies to resolve inside the isolated r3 environment. Symlink shims, copied libraries, compatibility headers, source patches, and system-library fallbacks are forbidden.
5. Require fixed HEAD/tree/submodule and zero tracked or staged diff after build.
6. Only after all gates pass may the independently audited A02 adapter, R2D2 inference, one-image ingestion smoke, and the two unique full official runs proceed under the main preregistration.

At this freeze, both r3 paths were absent; no r3 process, solve, build, model inference, A02 conversion, SLAM execution, or trajectory existed.
