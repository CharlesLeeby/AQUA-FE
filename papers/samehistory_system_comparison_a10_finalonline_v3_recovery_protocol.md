# A10 same-history final-online system comparison v3 recovery

Status: `FROZEN_BEFORE_SCORED_RUNS`

Date: 2026-08-24 (Asia/Shanghai)

## Question

Does the previously selected AQUALOC archaeology A10 development-positive
window remain runnable when the project controls and the exact learned-active
project method receive boundary-matched continuous camera history corresponding
to the sealed HFNet-SLAM warm-start run?

This protocol is separate from the sealed A06/H07 same-history v1 experiment.
It must not modify or reuse the A06/H07 lock or hard-coded analyzer.

## Recovery scope and immutable failed attempts

This is a pipeline-debug/secondary-sensitivity recovery, not a retrospective
repair of either earlier attempt and not yet primary paper evidence.

- A10 v1 is permanently retained as an infrastructure failure: its only child
  stopped before reading an image because `ROS_MASTER_URI` was absent under
  catkin's `set -u` hook. It produced none of the three KLT artifacts.
- A10 v2 is permanently retained as `EXECUTION_INTEGRITY_FAILED`. Its KLT child
  exited naturally with raw return code 0 and its complete artifact contract
  passed, but an unrelated ROS/VINS/rosbag workflow began at 20:26:48 while the
  final approximately 176 seconds of KLT artifact generation were still in
  progress. The immutable v2 receipt therefore correctly failed with
  `POSTFLIGHT_PROCESS_PRESENT`.

v3 recovery has exactly one eligible KLT input: the three v2 files fixed by
SHA-256 before any downstream trajectory exists. A short
`klt_input_adoption` item copies those files byte for byte—never by symlink or
hardlink—into a new v3 output tree and reruns the complete bag, PointCloud,
IMU/GT stream, 141-column CSV, and camera-YAML contract. Its sealed adoption
manifest records v2 terminal RC0, artifact PASS, execution FAIL, and expressly
forbids describing v2 as a successful attempt. v3 cannot switch to a regenerated
KLT candidate after seeing any downstream result.

The static adoption manifest, the copied `adoption_manifest.json`, and the v3
execution lock must bind the exact identities of the v2 process-start claim,
terminal receipt, supervisor log, v2 execution lock, and all three adopted KLT
files. The analyzer must independently reread these sources and establish all
of the following at once: v2 terminal status `TERMINAL_PROCESS_RC0` with raw
return code 0, artifact contract `PASS`, execution integrity `FAIL`, postflight
status `FAIL`, supervisor error `POSTFLIGHT_PROCESS_PRESENT`, and overall
disposition `EXECUTION_INTEGRITY_FAILED`. A missing, changed, contradictory, or
unbound source blocks recovery provenance; artifact `PASS` alone can never be
reported as v2 attempt success.

This adoption is acceptable only for continuing pipeline debugging and a
clearly labelled secondary sensitivity analysis. A later machine-exclusive
regeneration is still required before treating the project arms as primary
paper evidence. No v2 backend receipt or trajectory existed when the sole
adopted input was frozen, so downstream APE/RPE could not influence selection.

The launch-environment corrections introduced after v1 and already present in
v2 remain frozen here: initial
`ROS_MASTER_URI=http://localhost:11311`, with each backend replacing it by its
frozen item-specific URI, and experiment-specific `ROS_HOME/ROS_LOG_DIR` under
the v3 `/mnt/data` root. Data ranges, algorithms, checkpoint, feature budgets,
VINS parameters, score gates, and analysis rules are unchanged.

## Frozen systems

1. `vanilla_origin_native_image_context`: the pinned VINS-origin native-image
   path in the project's local quality-capable checkout. This is a native-image
   context control, not a byte-identical pristine/upstream VINS-Fusion build.
2. `external_klt_finalonline_backbone`: the exact 350-observation
   classical-mirror KLT/GFTT feature payload contract used by the earlier A10
   final-online development-positive experiment.
3. `aquafe_finalonline_xfeat_lineage`: the same KLT payload plus the frozen
   causal XFeat seed-to-KLT lineage state machine, using the stock XFeat
   checkpoint (not an underwater-adapted checkpoint): half-scale XFeat, zero
   trigger warmup/cooldown, at most three triggers, 50 seeds per trigger, 72
   active seeds, 10-frame causal survival before publication, five-observation
   ranking/geometry support, novelty at least 40 px, motion ratio in
   `[0.6, 1.5]`, homography residual at most 0.75 px, and at most one selected
   lineage.
4. `hfnet_slam_warmstart`: the already sealed external learned whole-system
   attempt. It is analysis-only here and is never rerun.

The project learned arm is deliberately named `finalonline_xfeat_lineage`.
It is not the v33 SuperPoint/LightGlue+LoFTR `proposed_safe` arm used in the
older A06/H07 same-history experiment.

## Frozen feed and score support

- Dataset: AQUALOC archaeology sequence A10.
- Continuous raw camera feed: source frames `0..2800`, inclusive (2801
  camera frames).
- Unscored history: source frames `0..2399`.
- Scored window: source frames `2400..2800`, inclusive (401 camera frames,
  19.996299264 s).
- Score timestamp interval:
  `[1542888916.043622160, 1542888936.039921424]` seconds.
- Native reference: `/aqualoc/colmap_gt` from the materialized raw bag.
- The score interval has 21 native COLMAP proxy poses.

The external project arms use `every2 + frame_offset1` together with
`--process-skipped-frames`: the KLT exporter updates its visual state on all
source images `0..2800` at 20 Hz, but publishes only source `1,3,...,2799`
(1400 feature messages), with score-native grid `2401,2403,...,2799` (200
messages). The XFeat sidecar is synchronized to this published odd-frame grid;
it does not independently consume all 20 Hz images. The vanilla native tracker
and HFNet see the 20 Hz camera stream. Vanilla's VINS configuration has
`freq: 10`, so its nominal estimator input rate is approximately 10 Hz.
Method-native rate differences are part of the frozen systems and must be
disclosed.

Camera history is boundary matched. The project raw converter retains a real
raw-IMU API margin around the camera range, while the sealed HFNet adapter uses
its shifted reader bracket. No IMU is synthetic or extrapolated, but IMU API
support is not byte-identical. Cross-system accuracy therefore remains
descriptive.

The sealed HFNet score crop contains exactly one pose for each source frame
`2400..2800` in source order. Its stored epoch-nanosecond spellings came through
a float64 timestamp path: relative to the corresponding raw camera-header
timestamps, the 401 signed differences are limited to
`{-112,-80,-48,-16,16,48,80,112}` ns, with counts
`{44,60,45,60,46,52,38,56}` in that order. Both endpoints differ by `-16` ns.
The immutable sealed crop and its delimiter/quaternion-order bridge remain
unchanged. For usability support and the common-support evaluator only, a
separate analysis input replaces each stored timestamp with the exact raw
camera-header timestamp at the preregistered same-row source index
`2400+i`. This canonicalization is permitted only if there are exactly 401
strictly ordered rows, every pose field is byte-for-byte unchanged, and every
absolute timestamp-spelling difference is at most 128 ns. It performs no
fitted offset, time synchronization, interpolation, resampling, pose change,
or result-informed tuning. The original bridge identity, canonical input
identity, source mapping, and complete signed-difference histogram must all be
recorded in the evaluator input manifest.

## Short-window identity preflight

Before the long-history attempts, the generation contracts were checked on the
distinct short A10 `2400..2800` authority:

- regenerated KLT `features.bag` SHA-256:
  `24be6d35764e8929b06bc8d31c10639a4cf9f7d3dd294f05cbb6fabc466af5d6`,
  byte-identical to the earlier KLT input;
- regenerated final-online `full_merged.bag` SHA-256:
  `b92bdb50fa90bbd10376e5460d66d97be33bdfba5c59ef30dc9aff92781f2022`,
  byte-identical to the earlier learned-active input;
- regenerated `sidecar.bag` SHA-256:
  `0c8807605ac98ef459090380f7e0e42fb70023a7977ad0ec15606ec610100089`;
  and
- semantic statistics reproduce selected source ID `1000002`, 97 injected
  observations, and zero row differences over the 27 non-timing fields common
  to both statistics versions. The two newly exposed state columns
  (`selector_retired_ids` and `selector_active_ids`) are not part of that older
  comparison.

Only the payload identities and semantic audit establish method equivalence;
probe runtime is not evidence. These short-window hashes are not the adopted
long-history v2 KLT hashes and do not upgrade v3 recovery to primary evidence.

## Long-history execution contract

- Large artifacts live under
  `/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery`.
- The already audited immutable raw bag remains at
  `/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/archaeo10_0000_2800.bag`;
  v3 reuses it by exact path, size, and SHA-256 and does not rematerialize it.
- Workspace run paths are symlinks to that root; large artifacts must not be
  written to the nearly full root filesystem.
- Raw materialization is completed and audited before the execution lock is
  sealed.
- `klt_input_adoption` is a byte-preserving import, not a new KLT generation.
  Both project external backends replay immutable feature bags derived from
  that single adopted payload.
- The XFeat sidecar starts at the beginning of its method-native odd-frame
  feed: its first synchronized sidecar/output message is source 1. A lineage
  selected in the prefix consumes the global single-lineage budget. It is
  forbidden to reset the sidecar at source frame 2400 or splice the old
  short-window learned bag onto the prefix.
- `VINS_MULTIPLE_THREAD=1`, `WAIT_FOR_VINS_SUBSCRIBERS=1`,
  `AQUALOC_BODY_T_CAM0_MODE=imu_cam`,
  `VINS_TD=-0.053694112369382575`, `VINS_ESTIMATE_TD=0`, and
  `PLAY_RATE=1.0` are fixed.
- Every scored backend launches the lock-pinned absolute executable
  `/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node`; executable
  discovery through `rosrun` is not used by these attempts. Each generated
  VINS YAML and camera YAML must match its preregistered byte identity, so a
  later duplicate or overriding configuration key is forbidden.
- ROS/VINS backends run serially on distinct ports. No concurrent HFNet,
  external ROS master, rosbag replay, or VINS process is allowed at launch.
  A pre-existing `rosout` may be classified separately only when its pinned
  executable/process/environment identity is stable across both prelaunch
  checks, its `ROS_MASTER_URI` resolves exclusively to loopback on a
  non-formal port, that master is unreachable, it has no active/SYN ROS
  connection or formal-port socket, and none of its paths enters the A10
  output tree. The immutable claim and receipt must record this exemption;
  any new, changed, reconnected, or leaked `rosout` remains a launch/postflight
  failure.
- Every item still requires strict global ROS quiescence both before its durable
  claim and immediately before `Popen`. The three backend items additionally
  require strict global quiescence at postflight. The two non-ROS offline items
  (`klt_input_adoption` and `aquafe_build`) use the preregistered
  `offline_artifact_only` postflight policy: an unrelated ROS/VINS/rosbag
  workflow that starts later is recorded as ambient evidence rather than
  invalidating their byte/semantic artifacts, but only if none of its argv
  paths enters the AQUA-FE workspace or v3 experiment, it uses no formal v3
  port, it is not HFNet/another learned-GPU process, and the supervised item has
  no surviving process-group member or descendant. Any violation remains a
  failure. This recovery-only policy does not reclassify v2 and does not apply
  to trajectory-producing backends.
- The sealed-input adoption, learned-sidecar generation, and each scored
  backend arm each have one process-launch allowance and zero result-informed
  retry. A run failure is retained as a failure; it is not converted to zero
  error or replaced by another input candidate.
- The one-shot supervisor accepts only an empty per-item output tree before its
  durable launch claim. Its immutable receipt records three independent
  outcomes: the raw child-process terminal state, the artifact/semantic
  contract, and score-window usability. In particular, an unusable score
  window does not rewrite a real exit code 0 into a process failure. The
  analyzer must preserve receipt validity, raw terminal-process outcome,
  artifact contract, execution integrity, and score usability as separate
  fields. It must also publish a separate recovery-provenance audit, explicitly
  state that v2 was unsuccessful, and withhold the common-support evaluator if
  the source/adoption bindings above do not pass. A valid fail-closed receipt
  created after a durable claim but before
  `Popen` is also a terminal attempt and must not be rejected merely because no
  child started. Only the declared data dependencies (`adopted KLT -> XFeat`,
  `adopted KLT -> external KLT backend`, and `XFeat -> AQUA-FE backend`) gate later launches;
  an independent backend failure cannot suppress another independent backend
  attempt, and already terminal arms remain individually visible while other
  arms are pending.
- `/home/ma/SLAM/VINS-Fusion_3-15-WS` is out of scope and must not be modified.

## Learned-action audit

Learned observations and affected feature frames are counted separately over:

1. the full method-native feed;
2. the unscored prefix; and
3. the score window.

Zero learned observations establish only absence of learned-action evidence.
Byte-identical learned and KLT feature payloads establish only input-level
no-action equivalence. Trajectory-level no-harm is a separate conclusion and
requires the preregistered usability and descriptive trajectory gates below.
The KLT metric artifact is accepted only if all 141 declared columns satisfy
their frozen numeric, nullable, enum, reason, and histogram grammars; the
learned statistics artifact likewise governs all 31 columns. For every one of
the 1400 method-native frames, the statistics `(frame_index, stamp,
selector_injected_observations)` sequence must match the exact per-message
suffix added by `full_merged.bag` relative to the immutable KLT base bag.
Agreement of totals alone is insufficient.
If learned action occurs only in the prefix, any score-window change is a
history effect and not direct learned action in the score frames. The
natural-history arm is not required to reproduce the cold-start window's 97
observations.

## Evaluation and interpretation gates

System usability is evaluated first. VINS-family trajectories must satisfy the
frozen strict 11-column output contract; the immutable HFNet pose bridge must
satisfy its strict 8-column contract. For every arm, the trajectory must be
finite with strictly increasing integer-nanosecond timestamps and the estimator
must initialize. Within score timestamps
`[1542888916043622160, 1542888936039921424]`, its output must cover at least
70% of the 19.996299264 s temporal span and have no adjacent output gap larger
than 0.50 s. The nominal backend output rate is 10 Hz. The score interval must
contain zero solver-failure, fatal tracking-failure, restart, or active-map
reset events. Prefix failures/resets are retained and disclosed but do not by
themselves fail score usability; the sealed HFNet arm is known to have zero
score reset. HFNet score membership and temporal support use only the fixed
source-row timestamp canonicalization above; its original timestamp spellings
remain separately audited and disclosed.

All systems are evaluated on one common 1 Hz uniform grid prepared from the
native reference after the HFNet pose-convention bridge and the explicit
source-row timestamp canonicalization above. The 19.996299264 s interval
produces 20 anchored uniform-grid samples; those samples are the numerator of
the common-support count. The frozen denominator remains the conservative
count of 21 native reference poses and must not be described as though the
numerator itself consisted of native reference rows. The common-support
evaluator is frozen to:

- evaluation rate 1 Hz;
- maximum reference bracket 2.5 s;
- maximum estimate bracket 0.25 s;
- 1 s translation RPE;
- minimum formal APE support 30 poses and 10 s;
- minimum common support requires all three equivalent/conservative checks:
  at least 15 four-system jointly supported samples, ordinary uniform-grid
  coverage `matched/20 >= 0.70`, and the conservative fixed-denominator index
  `matched/21 >= 0.70`; and
- minimum descriptive RPE support 10 pairs.

Because the score interval contains only 21 native reference poses, the formal
APE gate is closed by construction. RPE may be reported descriptively only if
the four-system common 1 Hz grid contains at least 10 valid pairs. No overall
winner, significance test, cross-window mean, or failure-as-zero ranking is
permitted. Any common-support summary must satisfy the frozen schema, integer
and range invariants, per-arm/common-count consistency, and finite-metric
contracts before descriptive values may be released.
The bundle and report must publish the names `uniform_grid_count=20`,
`uniform_common_matched_count`, `uniform_common_coverage=matched/20`, and
`conservative_fixed_denominator_index=matched/21`. The last quantity is an
index against a conservative native-reference-count denominator, not a claim
that the numerator consists of supported native-reference rows.

Even if all receipts, usability checks, and descriptive common-support checks
pass, every v3 number remains labelled
`PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY`. It may not support a primary
paper claim, winner, ranking, or significance statement. Primary use requires
a later machine-exclusive regeneration of the long-history KLT input and a new
prospectively frozen execution; it cannot be obtained by relabelling this v3
adoption.

The sealed HFNet run had 22 active-map resets in the prefix and initialized its
surviving map at source frame 2355. Its TensorRT/cuDNN warnings and online-final
map semantics remain deployment and trajectory-semantic confounds and must be
reported beside any descriptive comparison.
