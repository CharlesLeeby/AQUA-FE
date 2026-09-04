# Published learned-SLAM baseline runability diagnosis

Date: 2026-08-12

Status: diagnostic closure in progress.  This note preserves the original
attempts and separates upstream algorithm behavior, release-artifact defects,
project-side supervision defects, and scientifically admissible high-level
repairs.  It does not replace any preregistered STOP result and does not report
a new confirmatory accuracy comparison.

## Outcome

The two deployed published systems did not fail for one common reason.

- **HFNet-SLAM** did execute learned feature extraction, visual map creation,
  IMU initialization, tracking, and trajectory serialization.  Its first
  200-frame run was too short for the upstream early inertial-motion guard.
  On the 901-frame run, the system repeatedly reset for insufficient motion,
  retained initialization only at frame 796, and then produced 97 consecutive
  poses and 18 keyframes over about 4.8--5.0 s.  This proves runability but is
  only 10.77% image coverage and is not a full-window accuracy endpoint.
- **AnyFeature-VSLAM/R2D2** was initially blocked by an author-shipped YAML
  token, `FeatureMatcher.matchingTh: 0.38f`, which OpenCV FileStorage rejects.
  A project-side copy with the numerically identical YAML value `0.38` passed
  a one-image ingestion closure without changing the official repository,
  model, vocabulary, feature data, binary, matcher value, or SLAM algorithm.
  The same A02 window still cannot initialize a map because of the upstream
  two-view geometry decision, not because the learned bins are unreadable.
- **AnyFeature-VSLAM/ORB32** processed all 901 frames but created zero
  keyframes.  An exact harness linked to the frozen official library found
  adequate feature counts and hundreds of viable match sets.  Every viable
  attempt selected the homography branch and every homography reconstruction
  failed the unique-solution ambiguity gate; the implementation has no
  fallback to the fundamental branch.  Changing that decision is a low-level
  algorithm modification and is therefore prohibited for the official
  baseline.

## HFNet-SLAM: first failure cause and exit defect

The sealed full-window stdout records eight visual initialization attempts at
frames `4, 78, 141, 268, 285, 479, 526, 796`.  The first seven are followed by
the upstream `Not enough motion for initializing. Reseting...` path.  The last
attempt creates 274 map points, prints `Imu initialized`, remains active, and
writes:

- 97 finite, strictly increasing frame poses, span `4.799582208 s`;
- 18 finite, strictly increasing keyframe poses, span `5.000203776 s`.

The camera/IMU time conversion, body-camera transform, IMU noise values,
camera model, ONNX weight, feature count (`675`), pyramid (`4`, `1.2`), and
detector threshold (`0.01`) were independently checked.  The prefix failure is
therefore attributed to the upstream early inertial-motion protection on this
low-motion interval, not to a missing model, malformed image stream, reversed
time shift, or absent IMU data.

The raw full-run process nevertheless returns `SIGSEGV` after both trajectory
files and the tracking-time summary have been written.  The kernel record is:

```text
mono_inertial_e[1263182]: segfault at a38 ... in libOpenGL.so.0.0.0
```

The official entrypoint hard-codes `System(..., bUseViewer=true)`.  Shutdown
requests and waits for the viewer to finish but does not explicitly destroy
the Pangolin window/context.  Pangolin's global context destruction later
deletes OpenGL resources.  The stdout ordering and the kernel fault together
locate this as a post-output Pangolin/OpenGL teardown defect, not a tracking or
trajectory-save failure.  There is no core backtrace, so the exact destructor
frame is not claimed.

The project runner also incorrectly treated `HF-Net.cache` as immutable.
Official `HFNetRTModel` loads, combines, serializes, and rewrites this TensorRT
timing cache during model construction.  The full run changed its SHA-256 from
`a687...` to `6798...` while keeping its size at 853,319 bytes.  The binary,
configuration, ONNX weight, source commit/tree, and all input files remained
unchanged.  Future supervision must treat a run-local timing-cache copy as an
expected-mutable runtime derivative and record both hashes; it must not
mistake this for a learned-weight or algorithm change.

Sealed evidence:

- result: `logs/published_hfnet_slam_v2/post_stop_full901/drivers/aqualoc_a02_0005_full901_diag_r2/run_result.json`, SHA-256
  `0997198915365346dcdd0a0a7ffd5ebaa24a9d86395852ed688ad84dc07ed782`;
- trajectory SHA-256
  `ba3dc9d08ddacca1d13e3fb1b19754c4ae996785db19e452c14f6f6bacdb1321`;
- keyframe trajectory SHA-256
  `a207ecd7f72b8c8d99f4b76222748637a94e8e5d71a8c3ca8991f32626ea9d6a`.

## AnyFeature-VSLAM: release artifact and geometric initialization

The author-shipped R2D2 settings file has contained `0.38f` since its first
paper-era addition and still contains it upstream.  OpenCV 4.2 and 4.9 both
reject the suffix; replacing only that token with `0.38` yields the same real
value read into the same float matcher threshold.  The official tree remains
clean.  The artifact-repaired one-image run enters the image loop, reads 5,000
R2D2 features, echoes the 2,000/4,000 normal/initial feature budgets, completes
tracking and output serialization, and only then hits the separately known
thread teardown abort.  Its manifest is:

- `run_manifest.json` SHA-256
  `df66ba91b54c026e8f7053f324af059d5337da19b79bb2cffaee79a8490e67ca`.

This establishes ingestion compatibility only.  It is not a trajectory or
accuracy result.

The exact ORB32 state-machine audit found 596 match sets with at least 100
matches.  All had the official homography ratio `RH > 0.4`, all selected the H
branch, and all failed its ambiguity condition because the second/best good
solution ratio was `0.8385--1.0` whereas the implementation requires `<0.75`.
There is no H-failure-to-F fallback.  The exact R2D2 prefix audit similarly
found 199/199 frames with at least 100 matches but zero official
initializations.  This rules out feature starvation and binary-layout failure
as the first cause on A02.  Adding a fallback, changing the ratio, or relaxing
the reconstruction gates would change the official algorithm and is not an
admissible baseline repair.

Detailed ORB evidence is preserved in
`papers/anyfeature_orb_init_audit_r1/`; R2D2 prefix evidence is preserved in
`papers/anyfeature_r2d2_init_audit_prefix200_r1/`.

## Why the current trajectories cannot yet be compared

HFNet's 97 poses correspond exactly to camera indices `804--900`.  On the
frozen A02 1 Hz grid, HFNet, B1, and XFeat-birth/raw-KLT share only four poses,
three seconds, and three 1 s RPE pairs (`4/45 = 8.89%` reference coverage).
This fails the existing common-support gates of 30 poses, 10 s, 70% coverage,
and 10 RPE pairs.  APE and RPE are therefore invalid, even though four-point
descriptive calculations are mathematically possible.  The reference is also
the same-image COLMAP plus pressure-scale proxy, not independent ground truth.

## Admissible route to a usable comparison

No low-level network, matcher, initializer, or backend modification is
authorized.  The minimal high-level route is:

1. Build a project-side entrypoint linked to the frozen official HFNet-SLAM
   library whose only behavioral difference from the official EuRoC entrypoint
   is `bUseViewer=false`.  This removes the non-scientific OpenGL teardown path
   while leaving the learned frontend and SLAM algorithm untouched.
2. Copy the frozen ONNX and timing-cache seed into a unique run-local model
   directory.  Keep ONNX immutable, allow only the local timing cache to
   change, and record pre/post identities without writing back to the shared
   model directory.
3. Use one common continuous input for all methods: A02 camera indices
   `4500--6300`, with `4500--5400` declared a non-scored common preroll and
   `5400--6300` the only scored interval.  The boundary frame is consumed once.
   This gives every system identical history and allows HFNet to cross its
   upstream initialization guard naturally; it does not warm-start the
   baseline with a privileged pose or map.
4. Evaluate HFNet-SLAM, the strong B1 control, and the current AQUA-FE method
   only on the fixed suffix and their identical 1 Hz common mask.  Use metric
   SE(3), transform each `world_T_body` estimate with the same `T_body_camera`,
   preserve all coverage/pose/span/RPE gates, and report the COLMAP+pressure
   reference caveat.
5. Label this first extension as post-STOP/development diagnostic because its
   preroll length was motivated by the observed failure.  A paper-level
   confirmatory claim requires applying the now-fixed preroll/scoring protocol
   to a prespecified multi-sequence roster without outcome-dependent window
   selection.

AnyFeature-VSLAM remains a valid negative runability endpoint on A02.  It can
only re-enter an accuracy table on a separately prespecified scene whose
official unmodified initializer naturally produces a map; an A02-specific
geometry fallback is not permitted.
