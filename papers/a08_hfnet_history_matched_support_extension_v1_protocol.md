# A08 HFNet history-matched support extension v1 protocol

Status: **FROZEN BEFORE CONTROL EXPORT, CONTROL REPLAY, OR ACCURACY EVALUATION.**

## Purpose and evidence boundary

The historical A08 learned-plus-KLT positive window is source frame
`4500..4660`.  It spans only about eight seconds and contains only nine native
1 Hz COLMAP anchors (eight are present because source frame 4640 is absent).
It therefore cannot satisfy the already frozen accuracy
gate of at least 30 common 1 Hz poses and at least 10 seconds of common span.
That exact window remains the authoritative HFNet runability subwindow and is
not redefined.

For a development-only accuracy diagnostic, this protocol freezes the support
extension `4000..4660`.  It contains the complete historical positive window,
uses only earlier causal history, and is selected from support length and the
already sealed reset log before any HFNet APE/RPE or any history-matched control
trajectory is computed.  It is not confirmatory or held-out evidence and must
be reported as an outcome-selected, support-extended diagnostic.

## Immutable HFNet source

- terminal freeze:
  `papers/hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_terminal_outcome_freeze_v1.json`;
  SHA-256 `e9d93aff74f5614c380be46710f7857a7ac6198477cb052cc1f0faffae73a527`;
- full HFNet `world_T_body` trajectory: 2,180 poses, source frames
  `2481..4660`, SHA-256
  `ee1c860011890ebaeb07eba1fb064868bff0239a761356d1ead7b9d96e2a67ce`;
- frozen camera-time list: 4,661 source timestamps for `0..4660`;
- frozen AQUALOC HFNet body-to-camera extrinsic:
  `configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml`,
  415 bytes, SHA-256
  `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1`;
- AQUALOC A08 COLMAP file:
  `datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_08.txt`,
  54,593 bytes, SHA-256
  `519d27750efd7e53c27a2bc3ff35bc9cf5c9fd2b888184eefea284bcfe8f2b6c`.

The sealed HFNet trajectory is never edited.  Its printed epoch-nanosecond
timestamps passed through float64 and differ from the frozen source camera
timestamps by at most 112 ns.  The bridge maps every row to its unique nearest
frozen camera timestamp, requires strictly increasing one-to-one source indices,
and restores the exact integer timestamp.  This is a serialization repair, not
a fitted time offset.

## Frozen support

- extended score source frames: `4000..4660` inclusive;
- exact timestamps:
  `1542885161111831216..1542885194106222672` ns;
- expected HFNet poses: `661/661`, contiguous;
- native GT anchors: the nominal `4000,4020,...,4660` grid except missing
  source frames 4400 and 4640, 32 anchors total; the frozen evaluator may
  interpolate across those approximately two-second brackets under its
  unchanged 2.5 s reference-gap limit;
- exact historical positive subwindow retained: `4500..4660`;
- frozen 1 Hz grid: 33 points, anchored at the source-4000 timestamp;
- no HFNet initialization or map reset is allowed within the extension.  The
  pinned `run_result.json` places the last parsed reset initialization at
  source frame 2413 (next first frame 2423) and the final successful
  initialization at source frame 2473, all before the extension.

## History-matched controls

Both controls must consume AQUALOC A08 raw source frames `0..4660` continuously
without a frontend or VINS reset at frame 4000 or 4500:

1. reconstructed-contract pure KLT/GFTT, every two source frames;
2. reconstructed-contract July-14 XFeat-plus-KLT arbitration/profile,
   including its method-native outcome when run from source frame zero.

The exact July-14 exporter identity registered by the historical experiment is
`de78c8258f32bcea4c04d4d4fffa9fa8ac82abffbf896a1c73ba28b694702f67`.
It is recovered byte-exactly as a member of
`/mnt/data/AQUA-FE_WS/backups/frozen_frontend_source_20260716_before_adaptive_dev.tar.gz`,
89,815 bytes, archive SHA-256
`7e13b845a2d7b88dc3b20c9ad2df89c2506e80ebaf89bb25772bdd13ae4af21c`.
The archive contains all seven files registered by the historical freeze and
must be extracted only into a new isolated execution overlay; it must not
replace the current workspace files.

The historical seven-file freeze did not register the complete transitive
closure (including the AQUALOC runner, seed-chain environment/config ancestry,
raw converter, XFeat implementation and checkpoint).  Those remaining
dependencies must therefore be newly pinned before execution.  Consequently,
neither fresh control may be labelled a complete July-14 environment
reproduction or a reproduction of the old cold-crop positive.  The label is
"recovered seven-file July core plus newly frozen transitive closure."  The two
controls remain internally matched because they use the same reconstructed
closure, raw history, timestamps, VINS binary, calibration, and replay
settings.

The historical learned action occurred near the start of the `4500..4660`
cold crop.  In the source-zero run the same admission gate acts near the true
sequence start and is not rearmed at source frame 4500.  Zero learned action in
the extended score support, or an arbitration fallback to KLT, is an accepted
method-native result.  Grafting the old learned observations or old feature bag
into the long-history stream is prohibited.

The source archive, GT, converter, exporters, XFeat checkpoint, VINS-Fusion
workspace, complete environment, commands, and generated artifacts must be
hashed in additive receipts.  Run an export-only probe before each VINS replay.
No failed arm is assigned zero accuracy, and no outcome-dependent retry is
allowed.

After both export-only arms pass their structural audits, execute exactly five
predeclared single-thread VINS replays per accepted feature bag.  Reuse the same
feature bag within an arm; vary no setting between repetitions.  A failed
replay remains failed and is not replaced.  Report all five outcomes and the
median over valid planned repetitions, with the valid count; do not select the
best run.

## Common-support evaluation

The evaluator must use one reference grid and one joint mask across HFNet, KLT,
and XFeat-plus-KLT:

- evaluation rate: 1 Hz, anchored at the exact source-4000 timestamp;
- window: the exact source-4000 and source-4660 timestamps above;
- at least 30 joint common poses;
- at least 10 seconds joint common span;
- at least 70% fixed-denominator score coverage;
- at least 10 exact one-second RPE pairs;
- fixed-scale proper SE(3), no Sim(3), no fitted time offset;
- every arm is supplied as `world_T_body` and transformed to camera by the
  same frozen AQUALOC `body_T_cam0`; HFNet is not assigned an identity
  extrinsic;
- evo APE/RPE cross-check required.

If any gate fails, all three-arm ranking metrics are `NA`.  The exact
`4500..4660` subwindow may be disclosed only as runability or a separately
labelled gate-closed diagnostic; it cannot replace the extended common-support
endpoint.

## Claim boundary

Even when all gates pass, the result is a development-only comparison on a
historically outcome-selected sequence and a support extension chosen after
HFNet runability was known.  It may establish that an external learned-feature
system was run and compared under matched causal history.  It does not establish
cross-dataset superiority, statistical significance, real-time performance, or
confirmatory generalization.  The AQUALOC COLMAP trajectory is an
image-derived, depth-scaled reference proxy rather than independent ground
truth, and the reconstructed current-contract controls cannot be used to
retroactively validate the exact July-14 cold-crop method.
