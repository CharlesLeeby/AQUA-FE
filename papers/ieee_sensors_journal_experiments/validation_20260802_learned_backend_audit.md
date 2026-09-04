# Learned Backend Validation Audit (2026-08-02)

## Decision

The current evidence does **not** support the claim that learned seeds have no
backend effect. It does support a narrower, conditional statement: in the
AQUALOC A06 frozen profile, a small learned/LoFTR insertion at the initialization
event changes the VINS trajectory relative to a same-frame classical KLT
replacement. The evidence is not sufficient to validate the current P03/QG
paper claim or a general learned-over-classical claim.

## Replay Contract

- Backend: `/home/ma/SLAM/VINS-Fusion-origin`, `multiple_thread=0`.
- Same feature-bag timestamp stream, IMU, GT, camera calibration, and VINS
  configuration within each A06 contrast.
- Serial ROS masters on ports 16346-16353; VINS subscribers were checked before
  playback. `rosbag --wait-for-subscribers` was not used because it waits for
  unconsumed GT/image topics in these bags.
- Metrics in `ape_strict_dt0p6.txt` use `evaluate_vins_sim_ape.py` with
  `--rpe-delta-s 1.0 --max-match-dt 0.6`.
- A06 has only 13 GT messages (10 common poses under the strict match for the
  short contrast), below the G0 APE support gate. APE is therefore descriptive;
  RPE and initialization/coverage are development evidence, not confirmatory
  sequence-level inference.

## Fresh A06 Results

| Window / arm | APE RMSE (m) | 1 s RPE RMSE (m) | Coverage | Init | Lost proxy |
|---|---:|---:|---:|---:|---:|
| A06 2210-2460 learned full | 0.068740 | 0.051935 | 0.909216 | 1 | 0 |
| A06 2210-2460 KLT | 0.266948 | 0.112836 | 0.900817 | 1 | 0 |
| A06 2210-2460 frame-6 classical replacement | 0.266819 | 0.112940 | 0.900817 | 1 | 0 |
| A06 2210-2700 learned full | 0.099047 | 0.047783 | 0.954174 | 1 | 0 |
| A06 2210-2700 KLT | 0.330420 | 0.085674 | 0.949973 | 1 | 0 |
| A06 2210-2700 frame-6 classical replacement | 0.331118 | 0.085833 | 0.949973 | 1 | 0 |
| A06 2210-2700 frame-29 learned removal | 0.099047 | 0.047782 | 0.954174 | 1 | 0 |

The frame-6 control replaces only the six learned observations in the frame
where they occur; all other feature frames remain from the learned bag. The
bag comparison reports exact frame counts, identical timestamps, median ID
Jaccard 1.0, and only one changed frame. Relative to this control, the learned
full arm reduces descriptive RPE by 54.0% (2210-2460) and 44.3% (2210-2700).
For the six exchanged observations, both source groups carry the same
`quality=0.8` and `sigma=1.118` values; the controlled variable is their image
location/feature identity, not a post-hoc covariance advantage.
Removing the four learned observations at frame 29 changes the result by less
than 0.01%, so the observed effect is localized to the initialization event.

The exported learned dose in both frozen bags is only 10 observations in two
events (six at the first event and four at the second); each high-ID learned
observation occurs in one feature frame. This is not evidence for a persistent
learned lineage.

## Stability and Sensitivity

Historical three-replay reducers for the same A06 profiles are numerically
stable: the 2460 learned full arm has APE/RPE mean `0.069894/0.051093` with
standard deviations `1e-6/1e-6`; the KLT arm has `0.266881/0.112872` with
standard deviations `0.001175/0.000206`. The 2700 learned full arm has
`0.116374/0.048412`, while its no-LoFTR control has `0.330748/0.085715`.
These repeats are replay-stability reducers, not independent windows, and the
two fresh A06 windows are nested, so no sequence-level p-value or universal
effect estimate is claimed.

The naive whole-lineage drop is not a valid learned-isolation control for these
bags: it removes the learned points without restoring the classical observations
that the learned exporter replaced. In the short A06 bag it therefore gives
`0.068788/0.051015`, almost identical to full despite the full-vs-KLT contrast.
The frame-level replacement control above fixes this attribution problem.

## Boundary Checks

- AFRL Cave classical proxy: `8.578092 m` APE / `2.600886 m` RPE.
- AFRL Cave full proxy with 12 learned observations: `10.893400 m` APE /
  `3.530406 m` RPE.
- AFRL Cave sparse learned full: no VINS trajectory; initialization repeatedly
  reported insufficient features/parallax.

These Cave bags are old development profiles. The `classical_proxy.bag` is a
learned-lineage-drop/zero-learned proxy, not an independent GFTT proposer, so it
cannot establish classical superiority or learned specificity. It does reject
the broad claim that learned sidecars automatically rescue the true sparse Cave
regime.

## Independent Dense-GT Development Check

As a separate, non-P03 development check, the old NTNU Fjord1 `s83,d10` frozen
bags were replayed through the same VINS backend with the external TUM evaluator:

| Arm | APE RMSE (m) | 1 s RPE RMSE (m) | Coverage | Solver failures |
|---|---:|---:|---:|---:|
| learned/XFeat full | 0.072807 | 0.080204 | 0.851748 | 0 |
| KLT | 0.186594 | 0.140598 | 0.851748 | 0 |

This is an independent dense-GT direction check (APE reduction 61.0%, RPE
reduction 42.9%), but the old full and KLT bags have low feature-set overlap
(median ID Jaccard about 0.18) and are not a same-master-stream counterfactual.
It therefore supports a reproducible learned-active signal, not a confirmatory
learned-specific attribution.

## P03/QG Status

The current P03 candidate remains non-canonical and has no confirmatory VINS
export. Current-code `selector_qg_validate.py` on A06 scores 53 frames but
selects zero candidates in every arm because the current total feature cap is
already consumed by the 350-point KLT base. `selector_shadow_compare.py` fails
the current K0/L/E disjoint-ID contract. The P03 bundle validator consequently
keeps `confirmatory_claim_authorized=false`; C-QG matched-dose implementation is
still pending.

## Allowed Paper Wording

Allowed now (development/conditional):

> A matched frame-level counterfactual on AQUALOC A06 shows that a small learned
> initialization insertion can alter VINS backend trajectory error relative to
> the corresponding KLT replacement; the effect is repeatable in this frozen
> profile but localized to an initialization event.

Not supported now:

- learned seeds generally outperform classical features;
- learned seeds provide persistent anchors in the tested bags;
- QG/conformal selection improves the backend;
- learned is superior to an independent classical matched-dose control;
- a confirmatory low-texture or cross-domain superiority claim.

## Required Before Submission

1. Freeze and export the canonical P03 profile through VINS, including explicit
   source IDs and the promoted calibration/selector hash.
2. Produce an independent GFTT/classical proposer bag with matched birth,
   lifetime, dose, and backend contract (C-QG), then run the same frame-level
   replacement/lineage audit.
3. Add disjoint held-out windows/sequences with dense enough GT or a registered
   RPE estimand; treat the two A06 windows as one development sequence family.
4. Re-run at least three serial backend replays per frozen bag and report
   window/sequence-level paired effects, not replay rows as independent samples.

## Machine Artifacts

- Fresh replay summary: `/mnt/data/AQUA-FE_WS/validation_20260802/summary.csv`.
- Strict A06 evaluator outputs: `/mnt/data/AQUA-FE_WS/validation_20260802/a06_*_v1/ape_strict_dt0p6.txt`.
- A06 bag alignment: `/mnt/data/AQUA-FE_WS/validation_20260802/a06_2460_alignment.md`
  and `a06_2700_alignment.md`.
- Frame-6 counterfactual construction:
  `/mnt/data/AQUA-FE_WS/validation_20260802/a06_2460_classical_replace_frame6.csv`
  and `a06_2700_classical_replace_frame6.csv`.
- Current P03 selector probes:
  `/mnt/data/AQUA-FE_WS/validation_20260802/a06_selector_qg_current.txt` and
  `a06_shadow_current.txt`.
- NTNU dense-GT fresh replays:
  `/mnt/data/AQUA-FE_WS/validation_20260802/ntnu_fjord1_s83_d10_learned_v1/ape.txt`
  and `ntnu_fjord1_s83_d10_klt_v1/ape.txt`.
