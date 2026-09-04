# AnyFeature-VSLAM R2D2 artifact-repair and prefix-viability addendum r1

Status: **FROZEN BEFORE THE ARTIFACT-REPAIRED OFFICIAL SMOKE START**.  A
project-side preflight has passed, but the new official output folder remains
absent.  This is a new, explicitly authorized artifact-repair track.  It does
not erase or reinterpret the retained negative result in
`2026-08-11--official-published-learned-slam-a02-results.md` and it does not
retroactively alter the stopping rule of the original verbatim-artifact track.

## Root cause and author intent boundary

The direct crash cause is the author file
`settings/r2d2_128_settings.yaml:11`:

```yaml
FeatureMatcher.matchingTh: 0.38f
```

OpenCV `FileStorage` treats the trailing C/C++ literal suffix `f` as an illegal
character in a YAML floating-point scalar.  The retained official smoke reached
`System::setDescriptorDistanceThresholds()` only after successfully loading the
1.39 GB R2D2 vocabulary, then OpenCV 4.9 raised `processSpecialDouble: Bad
format of floating-point constant` and the process returned 134.  It had not
entered the image loop.

The history and current-upstream checks support classifying this as a release
artifact, not an environment-specific numerical choice:

- The file was introduced by author commit
  `43ea4f8e22302f50e4067b3edaeecbacdbb0fad2` on 2024-07-13 as Git blob
  `27023c0e31a1a6d8b401ebe4f4c1a9d7c18189ed` and has never had a later file
  commit.
- The paper snapshot `6aa014b724f7a61bcbff2f8f28f20836986a43dc`, current upstream `main`
  `0c3c3770a87c97b9ddfdb5a89a15a6de6ded6d11`, and current upstream
  `allfeat` `4b17add141a6630d7a05b2cf8d54e17583e7be5c` all resolve this file to that
  same blob and still contain `0.38f`.
- The current author raw file is
  [unchanged upstream](https://raw.githubusercontent.com/alejandrofontan/AnyFeature-VSLAM/main/settings/r2d2_128_settings.yaml).
- OpenCV 4.2 and the frozen OpenCV 4.9 both reject the author scalar and both
  parse an in-memory `0.38` replacement as a real with value `0.38`.
- All other eight files in the author `settings/` directory parse under both
  versions.  R2D2 is the only settings file containing a C/C++ numeric suffix.

The RSS 2024 paper ([official PDF](https://www.roboticsproceedings.org/rss20/p084.pdf),
locally verified SHA-256
`136ef2c74683a10108bb4977b8f437414d8b249bff3f650220d01b1dbe0a80f7`)
defines a descriptor matching threshold `d_th` in Section III-D, but it does
not publish the number `0.38`.  The released R2D2 code computes
`cv::NORM_L2SQR` and reads `FeatureMatcher.matchingTh` into `const float`, then
assigns that value unchanged to all four matcher thresholds.  The extractor
reader independently maps `numOctaves` to `int` and `scaleFactor` and
`detectionTh` to `float`.  The project repair deliberately preserves the
released squared-L2 implementation and the released numerical value `0.38`;
it changes neither distance semantics nor an algorithm parameter.  The author
README does not list R2D2 in its command-line feature options even though the
paper and source implement `r2d2_128`; this is a documentation gap, not a
second runtime blocker.

## Sole settings repair

- Author artifact: 207 bytes, SHA-256
  `375ae1bdcfe92068a665f16b9943b09fb0c830be471f675ddb85289442526878`.
- Project copy:
  `configs/published_baselines/anyfeature_vslam_r2d2_128_artifact_repaired_r1.yaml`,
  206 bytes, SHA-256
  `6c7cb75c4209d00198bc552472f4ff5bb36510df6490c4a4b17eea04bd0db753`.
- Exact transformation: delete the one trailing byte `f` from line 11.  A
  byte-for-byte assertion verifies that no other byte differs.
- Frozen OpenCV 4.9 preflight reads node types `int, real, real, real` and
  values `1, 2.0, 1.0, 0.38`.

No author source, Git tree, binary, shared library, vocabulary, checkpoint,
R2D2 archive, materialized bin, image, calibration, timestamp, feature budget,
matcher threshold value, or SLAM state-machine constant is edited.  Results
from this track must be labeled:

> author-official AnyFeature-VSLAM code/binary/model/vocabulary with a
> project-side representation-only artifact-repaired settings copy

They must not be abbreviated to an unqualified “verbatim official run.”

## Next-layer closure and exact prefix audit

After the representation repair, the frozen official loader and extractor have
no observed next blocker.  A direct official-library read of prefix index 0
loaded 5000 keypoint rows, 5000 score rows, and 5000 `128`-D descriptor rows;
the official extractor returned 1668 keypoints and a `1668 x 128 CV_32F`
descriptor matrix.  The stronger exact-state audit then exercised that same
official extractor, matcher, `Frame`, and `Initializer` implementation over all
200 already materialized prefix frames.

The complete audit is sealed in
`papers/anyfeature_r2d2_init_audit_prefix200_r1/summary.json` (SHA-256
`be7082d6a39db094e86925d42037db22fa69250e66f71c28712c1a538bb0b903`)
and `exact_state_machine_r2.csv` (SHA-256
`97cc1bbbcc9941e5cdb68e2d3f55a78c2ee5d2a9c0b17a2a1bb23c4b0c85b743`).
Its result is a negative full-inference gate:

- frame 0 set the reference; all 199 later frames reached a geometry attempt;
- all 199 had at least 100 matches; match count min/median/max was
  `874 / 1551 / 3034`, with exactly 4000 keypoints per frame;
- the exact official initializer succeeded `0 / 199` times;
- `RH` min/median/max was `0.253329 / 0.350273 / 0.465596`, selecting F 144
  times and H 55 times;
- H reconstruction succeeded `0 / 199`, including `0 / 199` with parallax and
  minimum-triangulation thresholds relaxed to zero; its ambiguity gate passed
  `0 / 199` while SVD, minimum-good, and good-fraction gates passed `199 / 199`;
- F had four exact reconstruction counterfactuals, but all four occurred at
  `RH > 0.4`, where the unchanged official state machine selected the failing
  H branch.  The 144 frames on which it actually selected F had zero exact F
  reconstruction.

The released utility seeds its RANSAC set generator from `random_device`, so
the H/F counterfactual counts above belong to this sealed diagnostic
realization; they are not asserted to be invariant across fresh processes.
Within this realization the audit reused the exact `mvSets` generated by the
official `Initialize()` call for every recorded H/F reconstruction check.

Thus the remaining A02 failure layer is the released monocular geometry model
selection/reconstruction state machine, not the R2D2 producer, paths, binary
layout, finite values, descriptor type, feature count, or match count.  On this
evidence, materializing frames 200--900 would consume roughly another two CPU
hours with a low probability of producing an evaluable trajectory.  This
addendum therefore **does not authorize the 701-frame continuation**.  A new
full learned-baseline inference should first use a results-blind,
parallax-suitable window under a separate preregistration.

## Runner-v3 smoke boundary

The new fail-closed runner is
`scripts/run_anyfeature_vslam_artifact_repaired_v3.py`, SHA-256
`2094ca9d827bdb3248f96107edb91f4747472e7953295e4fb57f85f0675d50b9`.
Its tests are
`scripts/tests/test_run_anyfeature_vslam_artifact_repaired_v3.py`, SHA-256
`705b959b52641bf2c7433aad899c0922dae74535ec6c4160fe517e691811c04a`.
Unchanged v1, v2, and v3 suites pass `24 / 24` tests.

V3 exposes exactly one profile and no full profile:

- sequence:
  `/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_frame000_smoke_view_r1`;
- new no-clobber output:
  `/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/model_smokes/a02_frame000_artifact_repaired_r1`;
- feature `r2d2_128`, 2000 normal features, 4000 initialization features,
  `Vis:0`, `FixRes:0`, and the unchanged author binary/vocabulary.

The project-side preflight report is
`/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/adapter_reports/a02_r2d2_artifact_repaired_smoke_preflight_v3_r1.json`,
SHA-256
`095214b6643bf1a721fcdde34f465fb99f7d132f6a52a24b180e450068f20ee1`.
It returned `PREFLIGHT_READY`; no official process was started and the new
output remained absent.

The runner separates a clean official exit from the known author teardown
defect.  RC 134 is accepted only as a one-image **ingestion closure**, never as
a clean process exit, when all of the following hold simultaneously:

1. stderr is exactly `terminate called without an active exception`;
2. all argument, feature-budget, repaired-settings, finite timing, image-loop,
   trajectory-save, and statistics-save anchors occur in order;
3. trajectory, statistics YAML, and statistics text artifacts all exist as
   regular files;
4. no OpenCV/YAML, vocabulary, image/bin reader, bounds/assertion/allocation,
   segmentation, nonfinite-output, or initialization/reset diagnostic occurs.

Any reader or initialization error overrides the teardown signature and makes
the smoke fail.  Tests cover exact-teardown acceptance, wrong RC, wrong stderr,
missing completion, reader error, OpenCV error, initialization/reset error,
synthetic manifest sealing, and no-clobber behavior.

## One-way next action

After an independent review returns GO, the only permitted official action is
one invocation of the v3 one-image smoke at the new path.  A clean exit or the
strictly recognized post-loop teardown may establish R2D2 ingestion closure.
Any other result stops this A02 R2D2 track without retry.  Neither outcome
authorizes full inference, trajectory accuracy evaluation, parameter tuning,
source repair, or a claim that AnyFeature-VSLAM has been quantitatively
compared on A02.
