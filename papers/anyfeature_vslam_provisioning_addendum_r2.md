# AnyFeature-VSLAM provisioning addendum r2

Date: 2026-08-11 (Asia/Shanghai)  
Status: **FROZEN BEFORE R2 SOLVE, BUILD, MODEL INFERENCE, DATA EXPORT, OR SLAM**

This addendum authorizes one infrastructure-only successor to the retained r1 provisioning failure in `anyfeature_vslam_provisioning_r1_result.json` (SHA-256 `e7a168ec658140a1ee00cb335783f89311f4a122e4ad54b5a919d0d573aa6311`). It does not amend the scientific arms, checkpoint, vocabularies, A02 window, adapter semantics, run order, stopping rules, or evaluation contract in `anyfeature_vslam_r2d2_a02_preregistration.md` (SHA-256 at this freeze: `0d6c5d59651371821e0993985b59db1e299c56fdead5ae14938c79fc26bbc37b`).

## Why r2 is permitted

The official paper-era `environment.yml` names `opencv`, `eigen`, `cmake`, and Python without version bounds. The single r1 solve on 2026-08-11 selected OpenCV 5.0.0, Eigen 5.0.1, CMake 4.4.2, and Python 3.14.6. Frozen DBoW2 then failed before the AnyFeature binary existed because the 2024 `brisk/agast` package includes `opencv2/features2d/features2d.hpp`, a compatibility header removed from OpenCV 5. The upstream shell script nevertheless returned zero because it lacks fail-fast handling; the independent build returned one.

R2 is fixed before another solve and uses only publication-era ABI bounds. This is an environment repair, not a source or algorithm repair:

- `python=3.10.*`
- `opencv=4.10.*`
- `eigen=3.4.*`
- `cmake=3.29.*`

These four versions were available by the July 2024 paper snapshot and restore the dependency generation implied when the authors published the unbounded environment. Every other package remains selected by the unchanged official YAML. No version is chosen from trajectory, feature, timing, or accuracy behavior. If this exact overlay does not solve or build, r2 is terminal `STOP_PROVISIONING`; there is no r3 dependency search in this execution chain.

## Isolation and reuse

- New clean checkout: `/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r2`, same commit/tree/submodule as r1.
- New runtime root: `/mnt/data/opt/anyfeature-paper-2024-r2`.
- The exact r1 vocabulary bytes may be reused read-only through links after rechecking their fixed size/SHA-256; they are data assets, not build outputs.
- The r1 solve plan, explicit lock, logs, RC files, and result JSON remain retained. Its failed environment and package cache may be removed only to restore the preregistered free-space margin; their identities are fully sealed and reproducible from the explicit lock.
- All r2 cache and temporary variables resolve under the r2 runtime root. The root filesystem receives no large artifact.
- The AnyFeature and DBoW2 tracked sources remain byte-for-byte unchanged. Generated build directories and a temporary vocabulary link are allowed, enumerated, and removed or classified separately before the clean-tree audit.

## R2 gates

1. Before r2 creation, `/mnt/data` has at least 18 GiB free after the documented r1 runtime-cache cleanup; `/` has at least 8 GiB and available RAM at least 12 GiB.
2. Resolve once using the unchanged `environment.yml` plus exactly the four constraints above. Seal the JSON plan before installing and require the installed `(name, version, build)` set to match it exactly.
3. Run unchanged `build.sh -v`, but do not trust its return code alone. Independently require DBoW2 and AnyFeature `cmake --build ... --config Release` to return zero, `bin/mono` to exist, and `ldd` to contain no `not found`.
4. Require the frozen Git HEAD/tree/submodule and zero tracked or staged diff after build. No source/CMake edit, patch, include shim, copied header, or feature-code replacement is permitted.
5. Only after these gates pass may the adapter audit, data export, R2D2 inference, and official full runs proceed under the main preregistration.

No r2 directory, solve, build, model inference, A02 export, SLAM process, or trajectory existed when this addendum was written.
