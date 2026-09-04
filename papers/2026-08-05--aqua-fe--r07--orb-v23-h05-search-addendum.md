---
type: results-report
date: 2026-08-05
experiment_line: aqua-fe
round: 7
purpose: orb-v23-h05-clean-search-addendum
status: complete
source_artifacts:
  - orb_v23_h05_followup_20260805/analysis-output/analysis-report.md
  - orb_v23_h05_followup_20260805/analysis-output/h05_formal_summary.csv
  - orb_v23_h05_followup_20260805/analysis-output/screening_summary.csv
  - orb_v23_h05_followup_20260805/analysis-output/window_roster.csv
  - orb_v23_h05_followup_20260805/analysis-output/provenance.csv
  - orb_v23_h05_followup_20260805/analysis-output/validation_summary.json
  - ../logs/orb_v23_h05_action_search_20260805.md
  - ../logs/orb_v23_postinit_search_20260804_final.md
---

# AQUA-FE Round 07: ORB-v23 H05 clean search addendum

The continuation found one new independent frozen-v23 action-positive window:
AQUALOC H05 `900-1240`.

The clean `n3,d14,min8,ignore0,no-rearm` selector produced three lineages and
89 seed observations. All attempts occurred post-initialization; 87 were
accepted and two were rejected at the extractor border. In every formal
repeat, `full` produced 11 distinct MapPoints, 59 consumed assisted matches,
6 assisted outliers, and 4/4 pre-KF purges.

All 20 formal runs are deterministic and audit-clean. Reconstructed, online,
and keyframe hashes are constant per role. The role-aware provenance audit
passes all `576/576` listed entries, and repeat 4 preserves the action after
swapping `full` and `full_unbounded`.

The trajectory result is not strict. Relative to native/drop, all four primary
metrics worsen: reconstructed APE/RPE by `0.043% / 0.403%` and online APE/RPE
by `16.548% / 12.220%`. Relative to unbounded, only reconstructed APE improves.
H05 is therefore action-positive and metric-mixed with a native-negative
primary result.

The clean frontend is normal/mixed: base KLT min/mean/max is
`254/347.153/350`, grid min/mean/max is
`0.694444/0.848203/0.944444`, and only `14/170` frames are at grid `<= 0.80`.
It is not operational low-grid and not sparse base-KLT.

The current deduplicated roster is 12 mechanism/action-positive windows, 4
project-strict windows, and 2 all-control repeatwise-strict windows. Six of 12
positives are operational degraded/low-grid; sparse base-KLT positives remain
0/12.

H07 `720-900` remains a clean selector action-null screen. UVVID OrientKaj
`s160,d20` remains a post-init no-MapPoint screen. Neither enters the positive
denominator.

No ORB source, binary, library, runner, seed row, selector threshold, quality
gate, projection gate, descriptor gate, or dose was changed.
