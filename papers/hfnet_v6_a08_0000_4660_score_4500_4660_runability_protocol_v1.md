# HFNet-v6 A08 natural-history runability protocol v1

Status: frozen before A08 input materialization and before any governed HFNet child process starts.

## Question

Can the unchanged external HFNet-SLAM system consume AQUALOC archaeology A08 continuously through the previously selected learned-plus-KLT positive score window `4500..4660` and produce usable score-window trajectory support?

This is a development-only whole-system runability experiment. The A08 window was selected because an older XFeat-plus-KLT frontend beat pure KLT in four of five short-crop replays, with the reported five-replay median APE/RPE `0.149850/0.115440` versus KLT `0.200692/0.147971`. It is therefore outcome-selected, not held out. The historical hybrid/KLT runs cold-started at source frame 4500, whereas this HFNet run receives natural history. Those old accuracy values are provenance only and must not be placed in a head-to-head accuracy table with the new HFNet trajectory.

## Frozen feed

- Dataset: AQUALOC archaeology sequence A08.
- Canonical raw archive: `/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz`.
- Continuous HFNet feed: source camera frames `0..4660`, inclusive, 4661 cameras.
- History-only interval: `0..4499`.
- Sole score interval: `4500..4660`, inclusive, 161 cameras.
- After the frozen `+53,694,112 ns` IMU clock shift, source camera 0 has both a shifted IMU predecessor and successor and is a legal feed frame.
- No synthetic or extrapolated IMU sample, estimator state, pose, map, or image is permitted.

The selection identity and old-positive provenance are frozen in `papers/hfnet_v6_a08_0000_4660_score_4500_4660_selector_freeze_v1.json`.

## External system

- System: HFNet-SLAM, author repository build-repair commit `c354c72588a97bb6f6a9c7c8317530795956ec80` corresponding to the paper-era algorithm.
- Learned extractor, official ONNX model, HFNet thresholds, feature budget, matching/tracking, inertial estimator, optimizer, and loop behavior remain unchanged.
- Dataset adaptation is limited to the existing AQUALOC archaeology calibration, EuRoC/ASL input layout, the frozen camera/IMU time conversion, a headless entry point, run-local model/cache paths, and output inspection.
- The shared ONNX is copied to an attempt-local directory and remains immutable. The TensorRT timing cache is attempt-local and its pre/post identities are recorded.

## One-shot execution contract

1. Materialize the canonical input atomically under `/mnt/data`; do not write large artifacts to the root filesystem.
2. Independently validate source archive identity, selected camera/IMU endpoints, every camera's reader brackets, generated CSVs, all 4661 PNG byte identities, exact input-tree closure, and the materialization manifest.
3. Freeze the exact materialized input, runner, tests, binary, libraries, configuration, ONNX, cache seed, command, timeout, and output namespace before the child starts.
4. Create the process-start claim with `O_EXCL` before one `Popen`.
5. Permit one HFNet child and zero retry. A failure, timeout, reset, or empty trajectory is retained as the terminal result.
6. Run A08 alone. Ambient ToDesk and unrelated work are allowed by the user's development waiver; runtime, throughput, latency, real-time, and exclusive-GPU claims are forbidden.
7. Preserve A09 as an unstarted independent later window regardless of the A08 sign.

## Runability adjudication

The score-window runability state is `PASS` only if all of the following hold:

- every input/code/model authority passes its pre- and post-run identity audit;
- the child is synchronously reaped and the terminal receipt is sealed;
- a finite, strictly increasing trajectory is associated to the frozen camera timestamps;
- all 161 score cameras have one contiguous trajectory pose;
- at least one keyframe lies in the score interval;
- the active map was initialized before source frame 4500;
- there is no initialization, active-map reset, or unresolved reset boundary in `4500..4660`.

Any failed condition produces a retained `FAIL` with accuracy left `NA`. A failure is not a numeric error penalty and does not authorize changing the score window, adding warm-up beyond the frozen feed, retuning HFNet, or retrying.

## Accuracy boundary

This run alone cannot rank HFNet against the historical learned-plus-KLT or pure-KLT trajectories because their estimator histories differ. Accuracy evaluation is authorized only after history-matched comparator trajectories exist and a separately frozen evaluator establishes:

- identical score timestamps and one common mask;
- at least 30 common 1 Hz poses, at least 10 seconds of common span, and at least 70% score coverage for APE;
- at least 10 exact 1-second RPE pairs;
- fixed-scale proper SE(3), no reference reuse, no fitted time offset, and an evo cross-check;
- the AQUALOC same-image COLMAP/depth-scale trajectory is disclosed as a non-independent proxy.

Until then the allowed conclusion is limited to HFNet runability and score support on a previously selected positive window.
