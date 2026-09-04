# Recommended Frontend Configuration Map

Date: 2026-05-18

This file separates paper-safe defaults from experimental candidates.

## Temporal GFTT Admission Candidate

`experiments/low_texture_xfeat_temporal_gftt_frontend.yaml` combines two
cadence/admission correctness rules for ROS-bag use:

- `frontend_runtime.process_skipped_frames: true` updates tracker state on all
  camera frames while `every-n` controls publication only.  The exporter and
  frontend bag diagnostic honor this value; either explicit CLI cadence flag
  overrides it.
- `hybrid.enable_temporal_gftt_admission: true` keeps newly detected GFTT
  points private until the existing forward/backward KLT, NCC, and border
  checks confirm them on a later processed frame.  Only then is a public track
  ID allocated.

Both settings are backward-compatible and default to off when absent.  The
paired process-all control is
`experiments/low_texture_xfeat_seedchain_processall_frontend.yaml`; it differs
from the candidate only in temporal GFTT admission.  Neither profile changes
detector thresholds, confirmation thresholds, nor backend export gates.

Adoption status (2026-09-01): **not adopted / default remains off**.  The
frozen A09 6000--6800 no-harm gate failed because output-track p10 fell from
350 to 263 (75.1% retention; required 90%), although lifetime p75 improved
from 2 to 5 and coverage did not fall.  Per the frozen stop rule, Harbor07 and
pool replays were not run for this candidate.  See
`logs/gftt_admission_noharm/real_pool_gftt_admission_noharm_report.md`.

Follow-up status (2026-09-01): shadow-replacement v2 removed the refill gap and
passed every A09 gate (lifetime median 1 to 2; tracks p10 350 to 350), but it
failed Harbor07 coverage (median/p10 0.833/0.792 to 0.750/0.667).  A dual-pool
v3 probe improved Harbor07 coverage to 0.771/0.708 but still failed the frozen
one-cell loss limit.  Both switches remain default-off experimental code; no
profile is adopted and no pool/VINS continuation is authorized.  See
`logs/gftt_admission_noharm_v2/gftt_admission_followup_report.md`.

Coverage decomposition (2026-09-02): Harbor07's control advantage exists only
when age-1 births are counted.  For age>=2 tracks, off/v2/v3 coverage
median/p10 is 0.750/0.625, 0.750/0.667, and 0.771/0.708; for age>=3 both
candidates also exceed control.  This does not retroactively change the frozen
raw-coverage failure.  At this point adoption was blocked pending an explicit
decision on whether no-harm coverage should be re-registered as persistent coverage.
See `logs/gftt_admission_persistent_coverage/persistent_coverage_report.md`.

Admission-aware continuation (2026-09-03): after explicit authorization,
age>=2 persistent coverage was pre-registered as the primary no-harm support
metric and raw coverage retained as a secondary cost.  V2 passes revised
no-harm (A09 all original gates pass; Harbor07 persistent-coverage p10 improves
0.625 to 0.667), and full real-pool replay raises GFTT/KLT lifetime median from
1 to 2 on all three motion bags.  It nevertheless fails the frozen minimum
supply gate on 171342 and 172529: age>=2 track p10 is 123.4/167.0 and coverage
p10 is 0.500/0.542.  Only 171944 passes, at the exact coverage boundary 0.75.
Therefore v2 remains default-off and is not eligible for feature-bag/VINS
continuation.  See
`logs/real_pool_temporal_admission_v2/real_pool_temporal_admission_v2_report.md`.

## VINS-Facing Default

Use the KLT-preserving learned-sidecar export path when exporting features to
VINS-Fusion. The backend-visible backbone should remain KLT/GFTT; learned
features are admitted only as sparse, confirmed sidecars.

Rationale:

- KLT/GFTT remains the backend-visible temporal backbone.
- Learned sources act as quality-gated sidecar candidates, not replacements.
- H07 closed-loop VINS is the normal-texture no-harm control: learned export is
  gated out and APE/RPE stay KLT-like.
- A06 low-texture planar windows are the strongest positive backend evidence:
  sparse LoFTR sidecars reduce repeated-run APE from about `0.266 m` to
  `0.070 m` on 2210-2460 and from about `0.330 m` to `0.116 m` on 2210-2700.
- A08 4520-4680 is a non-A06 neutral/no-harm check: a few LoFTR sidecars enter
  VINS, but APE remains essentially tied with KLT.

Do not use broad learned replacement or LoFTR flooding as a default. A09
5920-6060 is a boundary case showing that one or a few unhelpful LoFTR points can
increase APE unless the export gate requires real grid-cell benefit.

Relevant evidence tables:

- `logs/backend_evidence_compact.md`
- `logs/crossv36_learned_sidecar_validation.md`
- `logs/crossv37_gate_patch_probe.md`

## Frontend Robustness Candidate

Use `experiments/three_layer_source_aware_frontend.yaml` for frontend-only
tables and low-texture robustness studies.

Rationale:

- SP+LG improves degraded AFRL long windows.
- On the newly staged UVVID Cannon bottom-most sequence, the 80-frame matrix
  shows lower dropout, higher homography inlier median, and lower epipolar
  median than KLT + adaptive CLAHE. The Tank short-test window remains an exact
  no-harm case with learned/LoFTR counters at zero.
- LoFTR improves A06 planar sparse low-texture windows.
- H07 VINS tests show lower RPE but worse APE, so it is not yet the default
  VINS export profile.

## LoFTR Planar Residual-Neutral Candidate

Use `experiments/a06_loftr_residual_neutral_quality.yaml` only as a stricter
A06-like planar LoFTR variant.

Rationale:

- Positive on A06 2210-2460 and 2210-2700, with smaller epipolar tradeoff than
  the looser full gate.
- Not uniformly better than the full gate on H07/AFRL, so it should not replace
  the global frontend candidate.

## LoFTR Extreme-Only Paper Profile

Use `experiments/loftr_extreme_only_frontend.yaml` when the paper needs the
cleanest claim that LoFTR is only an extreme planar low-texture sparse-cell
refiller.

Rationale:

- H07 normal/long, H06 low-contrast, and AFRL-FL degraded/long show zero LoFTR
  accepted tracks under the hard texture gate.
- Newly staged Tank and UVVID Cannon checks also show zero LoFTR accepted or
  promoted tracks, so any improvements on those windows should be attributed to
  conservative scheduling/SP+LG/classical recovery rather than to LoFTR.
- A06 planar windows still trigger LoFTR and gain grid coverage/track
  continuity with residual-neutral epipolar/homography medians.
- Sparse homography alone cannot activate LoFTR in this profile; the frame must
  also satisfy the extreme texture-quality gate.

## LoFTR Export Safety Notes

- Ordinary coverage-gain learned sidecars must open at least two new grid cells
  under formal export. This blocks the A09 single-LoFTR negative case while
  leaving true LoFTR support-rescue as a separate path.
- The repeated A06 positive uses sparse support-sidecar behavior: about ten
  LoFTR backend observations over the window. Exporting dozens of LoFTR points
  with a broad weak-cell rescue did not reproduce the trajectory gain.
- Treat LoFTR as an extreme low-texture planar support module, not as a generic
  pairwise matcher for every low-grid frame.

## Rejected As Defaults

- VINS-safe source reordering in `export_vins_features.py`: useful as a
  diagnostic switch, but not a default.
- Raw `q_i` backend weighting: active implementation path exists, but raw q can
  hurt trajectory accuracy.
- Learned/LoFTR flood into VINS during initialization: improves some frontend
  metrics and RPE, but can degrade APE.
