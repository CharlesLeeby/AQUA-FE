# Window Selection Protocol V2

- Protocol identity: `isj-window-selection-v2`
- Split route: `MULTI_SEQUENCE_CANDIDATE`
- Status: `FROZEN_FOR_P06_SCREENING`
- Screening boundary: KLT and image-quality metrics only
- Final manifest owner: P06, after the method hash is frozen
- V1 disposition: preserved unchanged; superseded for new P06 screening only

V2 exists because the direct runner and ROS exporter hashes drifted after the
P02 v1 freeze. It retains the complete v1 scientific selection contract but
registers the current code identities and a fresh development calibration.

## Outcome-Blind Boundary

Window selection may read only `grid_coverage`, `dropout_ratio`, `flat_region_ratio`, `degradation_score`, frame identity, and input timing. Learned-feature counts must be zero, and learned/P/VINS output, APE, RPE, initialization, solver state, trajectory coverage, or paper outcome labels must not enter scoring, ranking, replacement, or tie-breaking.

Exact windows in `history_exclusion_manifest.csv` are development-only and are removed before confirmatory selection. AQUALOC/AFRL/NTNU are sequence-held-out candidates because their domains have prior development use. FLSea-VI is metadata-only and is not external-ready. This protocol therefore does not support an external cross-domain claim.

## Frozen B1 Candidate

The strong classical screening frontend is KLT with `adaptive_clahe`, every input frame, and `uw_frontend/configs/klt_frontend.yaml`. The development command is:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input INPUT \
  --image-prefix OPTIONAL_ARCHIVE_PREFIX \
  --output-csv METRICS.csv \
  --method klt \
  --config uw_frontend/configs/klt_frontend.yaml \
  --preprocess adaptive_clahe \
  --every-n 1 \
  --start-index 0
```

Primary frozen identities are:

| Role | Path | SHA-256 |
|---|---|---|
| Config | `uw_frontend/configs/klt_frontend.yaml` | `73fd335a18ed77c821d8bc19b653f26b544acfa90fbb75a53d65d285888fd653` |
| Direct runner | `uw_frontend/evaluation/run_frontend_eval.py` | `c299038feb926e37bada04d0f150e57d45bed2f4d91bad8fb6a0c4ab2b22e6d2` |
| KLT source | `uw_frontend/tracking/klt_tracker.py` | `e60957bc0b45a11ef24824fa95ef9093dbbd7ba5998bc82bb91641c831f1fb5b` |
| Score core | `scripts/p02_window_selection.py` | `252dcd56be0f41b86934f18b6915f1bdc1d03cfcd240800ca860cc615395af59` |
| V2 selector entry | `scripts/p06_window_selection_v2.py` | `c50f7e93855e21214ac46a50e38a23e35224826a71cc56f0ed95178874c77c2b` |
| ROS exporter | `uw_frontend/ros/export_vins_features.py` | `7ed31890e3a55a528430e912df885830176b3c3432c420860a39d714bceae7cf` |

The complete runner/source hash set is
`p06/b1_screening_code_hashes_v2.sha256`. Any later change to a path in that
manifest creates a new protocol version and requires development recalibration
before further P06 screening.

## Frozen Score

Every required metric must be finite and in `[0,1]`; missing values are not imputed. No sequence-fitted min-max transform is permitted. For frame `t`:

```text
s_t = ((1 - grid_coverage_t)
       + dropout_ratio_t
       + flat_region_ratio_t
       + degradation_score_t) / 4
```

The direction-corrected grid deficit and the other three identity-scaled components are clipped only to their physical `[0,1]` support. The window score is the Hyndman-Fan type-7 median:

```text
S_W = Q_type7(0.50, {s_t : t in W})
```

Type-7 quantiles also define each sequence's `Q20` and `Q80`. The absolute thresholds and joint rules are:

```text
tau_low = 0.17
tau_normal = 0.10

low:          S_W >= tau_low    and S_W >= sequence_Q80
normal:       S_W <= tau_normal and S_W <= sequence_Q20
unclassified: every other valid window
```

The strict middle band is deliberate. It prevents the relative percentile rule from forcing an ambiguous sequence into either stratum.

## Window Construction

- Anchor fixed windows at candidate sequence time zero.
- Use half-open, non-overlapping intervals `[45k, 45(k+1))` seconds.
- Require at least 200 input image frames in every retained interval.
- Require 45 seconds of input/reference support. This exceeds the primary evaluator minimum `max(20 s, (ceil(30/0.70)-1)/evaluation_rate_hz)`, including the 42-second floor at 1 Hz.
- Remove any interval overlapping an exact historical development window before percentile calculation and selection.
- Reject intervals crossing a declared corrupt-data, timestamp-discontinuity, calibration, image/IMU synchronization, or reference-support failure.
- Keep unclassified intervals in the audit but never promote them into low or normal to fill a quota.

Within each sequence, rank low windows by descending `S_W` then ascending start time. Rank normal windows by ascending `S_W` then ascending start time. Select at most two per stratum and at most four total per sequence. Integer window index and start time provide the final stable tie-break.

## Development Calibration

Fresh v2 outputs produced by
`scripts/run_p06_development_calibration_v2.sh` are stored under
`p06/development_calibration_v2/` and summarized in
`p06/development_score_audit_v2.csv`. The machine decision is recorded in
`p06/development_calibration_v2.json`. Old AFRL-FR 189-row and UVVID 42-row
timeout partials remain excluded; v2 recomputed the complete 406- and 180-row
fixtures.

The unified B1 outputs separated the preregistered examples as follows:

- Low: A06 `2210-2460` (`0.177161287`), AFRL cemetery FR (`0.249415113`), and AFRL cemetery FL (`0.191931796`).
- Normal: H06 `2280-2490` (`0.076382044`) and Tank sensitivity (`0.030627338`).
- Unclassified guard-band check: H07 `1660-1720` (`0.156381629`).
- UVVID sensitivity: low by the absolute rule (`0.311139587`) but below the final 200-frame contract and not used as a primary calibration row.

The earlier `0.40/0.25` candidate thresholds were rejected before freeze because they came from configuration-heterogeneous historical CSVs and classified every fresh primary B1 fixture as normal. They do not define this protocol.

All seven v2 fixtures match their registered v1 inputs exactly on every frame
for all four required metrics. Recomputed type-7 scores have zero delta and all
seven classifications are unchanged. The threshold decision is therefore
`RETAIN_V1_THRESHOLDS`, not a post-hoc refit.

The required A06 direct/ROS development equivalence probe paired 251 frames.
After subtracting the constant frame-index offset, every index matched and the
maximum absolute difference for each required metric was `0.0`. Evidence is
in `p06/development_equivalence/aqualoc_a06_2210_2460/` and summarized by
`p06/window_selection_v2_calibration_report.md`.

## P06 Execution

For AQUALOC archives, run the frozen direct command over the complete sequence with `--every-n 1`, using `images_sequence_N` for archaeology and `harbor_images_sequence_NN` for harbor. Then execute:

```bash
python3 scripts/p06_window_selection_v2.py \
  --metrics-csv METRICS.csv \
  --output-csv WINDOW_AUDIT.csv \
  --dataset-family DATASET_FAMILY \
  --sequence SEQUENCE \
  --input-rate-hz 20
```

For NTNU ROS1 bags, use the frozen export-only adapter without backend replay or measurement selection:

```bash
RUN_DIR=RUN_DIR \
RUN_VINS=0 FORCE_EXPORT=1 MEASUREMENT_SELECTION=0 \
FORMAL_THREE_LAYER_EXPORT=0 VINS_SAFE_SOURCE_SELECTION=0 \
FRONTEND_CONFIG=uw_frontend/configs/klt_frontend.yaml \
PREPROCESS=adaptive_clahe \
bash scripts/run_ntnu_vins_eval.sh external SEQUENCE 0 DURATION_S klt 1

python3 scripts/p06_window_selection_v2.py \
  --metrics-csv RUN_DIR/frontend_metrics.csv \
  --output-csv WINDOW_AUDIT.csv \
  --dataset-family ntnu \
  --sequence SEQUENCE \
  --input-rate-hz 13.3333333
```

For AFRL, set the registered raw bag, reference, camchain, camera key, and source topic. Cave and bus use `cam0` with `/slave1/image_raw/compressed`; cemetery registers either `cam0` with `/cam_fl/image_raw/compressed` or `cam1` with `/cam_fr/image_raw/compressed` before screening and keeps that identity fixed through evaluation.

```bash
RAW_BAG=RAW_BAG GT_TXT=GT_TXT CAMCHAIN=CAMCHAIN \
CAMERA_KEY=CAMERA_KEY SRC_IMAGE_TOPIC=SRC_IMAGE_TOPIC \
RUN_DIR=RUN_DIR RUN_VINS=0 FORCE_RAW=1 FORCE_EXPORT=1 \
MEASUREMENT_SELECTION=0 FORMAL_THREE_LAYER_EXPORT=0 \
VINS_SAFE_SOURCE_SELECTION=0 IMAGE_SCALE=1.0 \
FRONTEND_CONFIG=uw_frontend/configs/klt_frontend.yaml \
PREPROCESS=adaptive_clahe \
bash scripts/run_afrl_cave_vins_eval.sh external klt 0 DURATION_S 1

python3 scripts/p06_window_selection_v2.py \
  --metrics-csv RUN_DIR/frontend_metrics.csv \
  --output-csv WINDOW_AUDIT.csv \
  --dataset-family afrl \
  --sequence SEQUENCE \
  --input-rate-hz 15
```

The required development equivalence probe is PASS under this v2 identity.
Any future mismatch creates a later protocol version; held-out results are
never repaired by rescaling.

## Replacement And Matrix Decision

If a selected interval fails a preregistered integrity/support check, mark it rejected with the reason and promote the next ranked interval from the same sequence and stratum. If that pool is exhausted, use the next stable-ranked eligible sequence in the same stratum while preserving the per-sequence cap and the two-domain minimum. Never change thresholds, percentiles, window length, or stratum after reading learned or trajectory outcomes.

P06 passes the final matrix only with at least 20 non-overlapping windows, exactly 10 low and 10 normal, at least six sequences and two domains per stratum, at least three domains overall, and no more than four windows per sequence. If the frozen eligible pool cannot meet those conditions, the decision is `REVISE`; unclassified windows are not quota replacements.
