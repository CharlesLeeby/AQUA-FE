# HFNet H03 descriptive proxy evaluation

## Outcome

The frozen HFNet Phase-F H03 trajectory has valid reference support on all 91 points of the frozen 2 Hz evaluation grid.  Primary fixed-scale SE(3) translation APE is **0.105163521 m RMSE** (median 0.080678091 m; max 0.363085108 m).  Exact-1 s translation RPE is **0.082618063 m RMSE** over 89 overlapping pairs (median 0.021491936 m; max 0.293478277 m).

The native score suffix covers 901/901 camera samples.  First usable trajectory output occurs 43.767672425 s after feed start and 1.250702588 s before score start; scored-output delay is 0 s.

## Alignment and reference boundary

- Primary: fixed-scale SE(3), after converting `world_T_body` to `world_T_camera` with the exact runtime `body_T_camera` calibration.
- Secondary diagnostic only: Sim(3), fitted scale 0.790231384; it must not replace the fixed-scale result.
- Reference: updated AQUALOC H03 offline COLMAP camera trajectory, scale corrected with depth metadata.  It is reconstructed from the same image sequence and is not sensor-independent ground truth.
- Unit of analysis: one frozen development-only trajectory.  The 901 native timestamps, 91 evaluation-grid poses, and 89 overlapping RPE pairs are temporally dependent, not independent experimental samples.

## Claim candidates

- Claim:
  - Source evidence: `evaluation_result.json`, `grid_metrics.csv`, `rpe_pairs.csv`.
  - Allowed wording: the frozen H03 run has the reported descriptive translation errors against the image-derived COLMAP proxy and full frozen score coverage.
  - Forbidden stronger wording: independent-GT accuracy, statistical significance, superiority to another system, general underwater robustness, or a formal paper claim.
  - Uncertainty: one development-only sequence/run and image-derived reference.
  - Next check: repeat the same preregistered evaluator on genuinely held-out sequences and independent reference where available.
  - Decision: keep with caveat.
