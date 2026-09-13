# Learned underwater loop baseline v1 — outcome-blind protocol

Registered: 2026-09-14T01:14:00+08:00. Status: `DESIGN_FROZEN_EXECUTION_NOT_READY`.
Scope authority: [complete user task](task_instructions.md). This is a new,
explicitly authorized global-association baseline, not a continuation of the
stopped local-frontend experiments. No learned descriptors or new trajectories
have been computed before registration.

## Question, sequence selection, and denominator

Does L add verifiably correct, geometrically usable loops beyond C on identical
KLT local outputs, with useful global trajectory improvement? B has no loops.
This is mature-component integration, not an original algorithm claim.

The finite availability check covers six physical sequences / seven bags in
[sequence_manifest.csv](sequence_manifest.csv). Select exactly **AFRL Bus Outside
and Cemetery**, whole supplied ROS1 bags, in that order. The provider README
explicitly describes repeated traversal of these scenes, and both have images,
IMU, camera–IMU calibration and COLMAP proxy. Selection does not use learned
retrieval, VIO performance, or a predicted winner. Other inspected sequences
are not substitutions if these fail. These sequences have historical local
frontend development exposure; neither is sequence-held-out.

The manifest bag times are **record-time metadata**, not a new crop. Consume all
camera/IMU messages with original header times; retain both sides of revisits.
Use cam0/left and `/imu/imu`. Camera intrinsics/extrinsics and IMU noise come
from each supplied camchain and shared imu.yaml. Do not feed references online.
Bus proxy timestamps are seconds. Cemetery uses the existing `afrl_digits`
parser (first ten digits as integer seconds, remaining digits as fraction).
No optimized offset, rescaling of positions, or rewriting of the source file.
Only reference associations outside actual input support are omitted from
metrics; input messages are never cropped to improve evaluation.

## Local identity and execution order

Use the existing frozen KLT-only external-observation route (no learned seeds,
recovery, or coordinate correction), `method=klt`, `every_n=2`,
`PROCESS_SKIPPED_FRAMES=1`, grayscale half-resolution AFRL camera conversion,
350 feature cap, measurement/source selection disabled. Preserve the existing
KLT preprocessing and frozen VINS local settings; do not substitute a native
tracker or tune initialization. The existing KLT profile and generated YAML
must be resolved and hashed before execution, not inferred from a TUM file.
All numerical YAML values are identical across B/C/L within a local repeat;
different calibrated cameras necessarily have different calibration files.
Execution remains **not ready** until this identity lock is complete.

Serial order: Bus r1,r2,r3; Cemetery r1,r2,r3. At most six new local VIO runs.
For each successful saved local output derive B, then C, then L; at most twelve
pose-graph runs. A failed local run remains a failed three-arm block, without
an extra replacement repeat. Valid complete archive reuse requires matching
input/configuration/build/runtime identity and is labeled reused, not fresh.
No valid reusable full keyframe archive has yet been confirmed by this check.

Capture once per local repeat: raw local body poses, keyframe images and header
times, body poses and extrinsics, solved world 3D points, normalized/pixel
observations and IDs, original odometry edges. The existing `keyframe_pose` and
`keyframe_point` publishers can supply the necessary pose/point data without
changing initialization or estimation. Timestamp joins must be exact; never
silently pick a nearby image. Preserve the native keyframe selection (initial
ten-keyframe skip; subsequent native skip/distance policy), freeze one resulting
keyframe roster, and feed precisely that roster to all three arms.

Native saved pose-graph/TUM files alone lack the required current-frame 3D
observations. Do not synthesize them. No feedback from C/L may change local VIO.
Store original and global poses separately. Reuse a descriptor only when image
content, preprocessing, model and dictionary identity match, including across
technical repeats. Never assume identical keyframes across independent VIO
repeats; the same image is encoded once, a different image is not a cache hit.

## One fixed learned configuration

Implementation reference:
[DL-VINS config](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/blob/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6/DL-VINS/src/loop_fusion/config/loop_fusion_euroc.yaml),
[pinned exporter](https://github.com/limshoonkit/AnyLoc/blob/e8bb9e0a19dc20db32470ea34e2d7f8e5184b31c/vpr/dino_vpr_export.py),
[VLAD implementation](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/blob/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6/DL-VINS/src/loop_fusion/src/vlad.cpp).

- DINOv2 ViT-S/14, **final `x_norm_patchtokens`**, 384 channels, not a ViT-L/G
  vocabulary or an intermediate value-token configuration.
- Official pretrained weights must actually load, without random initialization.
  The reference exporter calls `facebookresearch/dinov2`, `dinov2_vits14`.
  This source-level finding is not a completed runtime weight validation.
- 280 high × 448 wide, aspect-preserving linear resize, integer floor dimensions,
  centered black letterbox; grayscale repeated to RGB or BGR converted to RGB;
  /255 then ImageNet mean [0.485,0.456,0.406], std [0.229,0.224,0.225].
- Exactly 640 patch tokens; nearest-center residual VLAD, intra-cluster L2,
  signed square root, global L2; epsilon 1e-12; final 12,288 dimensions.
- Provided `vlad_vocab_dino_vits14_k32.bin`, K=32,D=384, 49,160 bytes;
  SHA-256 `695985ec145406609d5c8d122092198886c4d89463c316e6a3b1606aee34143d`.
  Source is the pinned DL repository's `loop_fusion/support_files`.
  **Exact vocabulary fitting image manifest: Unknown.** Exporter example paths
  are not proof of actual training data. No test-data fitting/adaptation here;
  historical vocabulary exposure to these scenes cannot be excluded yet.
- The matching 88,315,627-byte ONNX is available in the same pinned directory.
  Its weight tensors/loading and Python-runtime equivalence are Not evaluated.
  Prefer an isolated Python encoder, no TensorRT/ROS2 installation or migration.
- One minimal loading/finite-output/peak-memory check must precede keyframe
  encoding. No second model, new vocabulary, training or threshold search.

## Shared retrieval pool, verification, and graph

Keyframe indices are contiguous zero-based archive indices. For query q use
only past IDs **j < q - 50**, i.e. separation strictly greater than 50 keyframes;
q≤50 has no eligible history. Same rule for both arms, applied **before** top-K.
This is an index exclusion; report its actual time span rather than calling it
50 seconds. Fixed top-K=4, ties use increasing candidate index.

The local DBoW `queryL1` source includes a last-entry exception even when a
maximum ID is supplied. The isolated candidate interface must remove this
exception for C and enforce the same explicit allowed-history set for L.
Filtering after a truncated top-4 list is insufficient: it would consume C's
budget with excluded neighbors. Do not modify the old VINS workspace.

C: existing BRIEF vocabulary and DBoW score; native gate best score >0.05 and
at least one other top-4 score >0.015. Among qualifying candidates choose the
earliest index with score >0.015. L: cosine score with the reference default
threshold ≥0.60; choose the earliest qualifying top-4 candidate. **At most one
geometric verification per query** in both arms, preserving native VINS's
single-candidate policy. Record all ranked candidates, gate failures and the
selected candidate. Recall@4 concerns ranking before these score gates.

Both arms invoke the **same original BRIEF correspondences and 3D–2D PnP**,
same camera model/extrinsics, same rejection and graph-edge treatment. Do not
import the reference ROS2 project's LightGlue verifier. Native code uses
MIN_LOOP_NUM=25 with strict > comparisons, yaw difference <30 degrees and
relative translation <20 m; preserve the source's OpenCV-dependent PnP settings
and all existing geometric checks, not just these summary numbers. No edge from
image similarity, F/H alone, or unit essential-matrix translation.

Same 4-DoF graph implementation, edge weights/robust kernel, raw odometry edges,
and optimization schedule in C/L. A candidate is never an edge until verification
passes. No generic scale-repair claim from a 4-DoF graph. Unstable local scale is
reported as a baseline limitation, not evidence for/against retrieval ability.
An actual archive-to-native-verifier bridge is still to be implemented/validated;
the Python candidate adapter alone is **not** a complete loop-closure system.

## Evaluation, labels and fixed decision rules

Report every sequence and repeat, including failed initialization, empty output,
invalid support and missing labels. Technical repeats are not independent
sequences. Planned denominator: 2 sequences, 6 shared-local blocks, 18 arm rows;
0 completed rows must not be presented as 0 successful loops.

1. Retrieval: Recall@4 only where an outcome-independent revisit label set is
   available for the query and shared eligible history. Sequence-level revisit
   descriptions do not provide exhaustive query labels. Do not infer true
   Recall@4 from labels assigned only to retrieved candidates. Spatial-neighbor
   proxy recall, if reported, is separately named and not true loop recall.
2. Count ranked/selected/verified/rejected candidates; distinguish correct,
   incorrect and Unknown. Inspect the union of C/L accepted pairs with arm
   identity hidden, using the image pair and independent reference/scene
   evidence. Provider overlap labels can be used only with verified image-ID
   mapping. Geometry acceptance alone is not independent correctness. Separate
   repetitive appearance, nearby non-overlapping views and excluded temporal
   neighbors. No dense pixel annotation is required.
3. Global position APE RMSE and translation/rotation RPE at a fixed 1 s grid;
   compare B/C/L on exactly the same camera-frame reference associations.
   Convert body poses with fixed extrinsics. Grid uses integer epoch seconds
   inside joint trajectory/reference support; interpolate only between enclosing
   reference/trajectory poses with a gap ≤1 s, never extrapolate. Primary APE
   uses independent fixed-scale proper SE(3) alignments, checked with evo.
   Diagnostic Sim(3) scale/APE is explicitly separate, never the primary metric.
4. Valid common support requires ≥30 common poses, ≥10 s span and ≥70% of
   reference-evaluable grid samples over the full input interval. Report input,
   reference and trajectory coverage separately, and preserve failed rows.
   Both position and full-pose RPE require their actual reference fields to be
   valid. Reference conventions not validated means Not evaluated, not guessed.
5. Report medians and min–max across all three technical repeats with valid
   counts and all failures. Include original local trajectory, per-repeat
   initialization time, scale diagnostic, and errors in both pre/post-loop
   intervals. Shared boundary is the earliest union-of-C/L verified loop time;
   retain whole-sequence metrics and the boundary rule, not a favorable crop.
6. Record model cold load, per-keyframe inference, cache hit counts, retrieval,
   verification and optimization wall time and peak memory. Cached/reused
   execution is not independent timing evidence.

Primary incremental success requires additional independently confirmed correct
L loops in ≥2/3 paired repeats of a sequence, median fixed-scale APE improvement
≥10% over C, median 1 s translational RPE no worse by >5%, no newly confirmed
incorrect accepted L edge, and no new failure/coverage loss. These are practical
development decision tolerances, not significance tests or a search target.
No other evaluated sequence may have a new failure, confirmed incorrect L edge,
or >10% median APE regression for a positive whole-matrix designation.
Unresolved candidate correctness prevents a confirmed positive designation.

After the entire available matrix: `PROMISING_GLOBAL_ASSOCIATION_BASELINE` only
when that incremental condition holds; `RETRIEVAL_GAIN_ONLY` when valid labels
show retrieval gain but legal constraints/system gain do not follow;
`NO_LEARNED_LOOP_INCREMENT` when evaluated evidence shows no practical increment.
L>B without L>C only supports loop closure, not learned-specific value.
Missing data/assets/interfaces/resource capacity yield an explicit partial or
blocked state, **not** an evaluated negative. Do not replace sequences/configs.

## Resource and release boundary

Use only the isolated task worktree and a task-specific writable runtime path.
Do not alter the primary workspace, old backend, datasets or old results.
Retain the existing project's conservative replay reserve: ≥2 GiB free on root
and ≥8 GiB on the chosen runtime filesystem, plus a bounded storage estimate
for retained archives before launching. These are operational safety reserves,
not a measured assertion that this matrix intrinsically needs exactly 8 GiB.
Current free space fails this check; no bulk download, replay or model load is
launched while below it. A different suitably provisioned output path is allowed
without changing scientific settings. No automatic deletion or data migration.

Record unresolved execution identities before running; never retroactively call
an unvalidated configuration frozen. Publish only task documents, compact CSVs,
adapter/tests and required project logs on
`exp/learned-loop-baseline-v1-20260914`; never weights, bags or large caches.
