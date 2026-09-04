# SuperVINS 1.0 development-only runtime repair protocol r1

Date: 2026-08-16

Status: **development/runtime qualification only**.  This protocol does not
authorize a trajectory run, APE/RPE computation, a formal baseline row, or a
claim about SuperVINS accuracy.

## Objective

Reach a compile-complete and fail-closed preflight checkpoint for the author
SuperVINS 1.0 artifact while preserving the clean official checkout.  The
checkpoint ends before `Ort::Session` construction and before any ROS image or
IMU message is consumed.

## Frozen official identity

- Repository: `https://github.com/luohongk/SuperVINS.git`
- Clean checkout: `/home/ma/SLAM/SuperVINS-paper-1.0-r1`
- Commit: `91e85d72a3828844538715cc4b1cd4b86a2620db`
- Git tree: `036391d321d4ea9a914739a454c20976f01f7bd7`
- Stock CUDA source SHA-256:
  `dfae6b3fdcb0a588d26d527ef0043c1a77f089305523f02f9bcc0b16ba88428f`
- Stock estimator CMake SHA-256:
  `253eb7247b84fe9735c4be200ba7f431f3dab0e37bb1efccd97a7543ad9a132a`

The official checkout must remain byte-clean.  All source work is confined to
the fresh private worktree below.

## Fresh namespaces

- Evidence:
  `/home/ma/AQUA-FE_WS/experiments/published_supervins_v1_devrepair_20260816_r1`
- Private catkin workspace:
  `/home/ma/SLAM/SuperVINS-v1-devrepair-ws-20260816-r1`
- Private SuperVINS worktree:
  `/home/ma/SLAM/SuperVINS-v1-devrepair-ws-20260816-r1/src/SuperVINS`
- Isolated dependencies:
  `/home/ma/opt/supervins_v1_devrepair_20260816_r1`

All four paths were absent before this protocol was created.  A failed or
partial attempt consumes the `r1` namespace; it must not be silently retried
under the same name.

## Strict source-repair allowlist

Only these changes are authorized:

1. In `supervins_estimator/src/featureTracker/extractor_matcher_dpl.cpp`,
   replace both and only both occurrences of
   `cuda_options.gpu_mem_limit = 0;` with
   `cuda_options.gpu_mem_limit = SIZE_MAX;`.
2. In `supervins_estimator/CMakeLists.txt`, replace the author-machine-only
   `ONNXRUNTIME_ROOTDIR` assignment with one CMake cache-path assignment so
   the official ONNX Runtime root can be supplied at configure time.

No network, weight, feature budget, threshold, image preprocessing, matcher,
tracker, initializer, estimator, or output-trajectory logic may change.  Ceres
and ONNX Runtime paths may be passed through CMake without editing any other
SuperVINS source.

The resulting method label is
`SuperVINS 1.0 + disclosed runtime-artifact repair`; it is not `official
as-is`.

## Dependency identity

- ONNX Runtime GPU:
  `onnxruntime-linux-x64-gpu-1.16.3.tgz`, official GitHub release asset,
  expected HTTP/GitHub asset size `136722770` bytes.  A locally computed
  SHA-256, extracted version, library identities, and `ldd` closure must be
  recorded before configuration.
- Ceres Solver: official tag `2.1.0`, peeled commit
  `f68321e7de8929fbcdb95dd42877531e64f72f66`.  The source checkout must be
  clean and the isolated installation must report version `2.1.0`.
- Existing CUDA/cuDNN assets may be referenced in place from
  `/home/ma/opt/hfnet_cuda116_trt851_r1`; they must not be copied into the new
  namespace.

## Actual official model pins

The official EuRoC configuration loads this exact pair:

- `superpoint.onnx`: `5272808` bytes, SHA-256
  `234d12c9f523292efb34e0ca513b011050b0c052700da9c01787b9356a1138d2`
- `superpoint_lightglue_fused_cpu.onnx`: `45634561` bytes, SHA-256
  `4f44f440bc08f71afc2ba619d33154d395284001c1387b14a3b58a3224f9490e`

The `_cpu` filename does not authorize switching execution provider or
substituting `superpoint_lightglue_fused.onnx`; the stock source still
registers the CUDA execution provider.

## Authorized checkpoint

The development checkpoint passes only if all of the following hold:

1. The official checkout is still clean at the frozen commit/tree.
2. The private worktree has the same HEAD and exactly the allowlisted diff.
3. All five author ONNX files, especially the actual EuRoC matcher above,
   retain their frozen identities.
4. ONNX Runtime reports version `1.16.3`; its core, shared-provider, and CUDA
   provider libraries exist, and static/dynamic dependency inspection has no
   unresolved library under the prescribed isolated environment.
5. Ceres `2.1.0` is installed in the isolated prefix.
6. `camera_models` and `supervins` compile and link; the resulting node has no
   unresolved dynamic library.
7. No `supervins_node`, `roscore`, `rosbag play`, model inference, or
   `Ort::Session` construction occurred.

Session construction and inference are a later, separately authorized stage.

