---
type: results-report
date: 2026-08-04
experiment_line: aqua-fe
round: 4
purpose: orb-v23-a06-search-addendum
status: complete
source_artifacts:
  - orb_v23_a06_followup_20260804/analysis-output/analysis-report.md
  - orb_v23_a06_followup_20260804/analysis-output/a06_formal_summary.csv
  - orb_v23_a06_followup_20260804/analysis-output/screening_summary.csv
  - orb_v23_a06_followup_20260804/analysis-output/window_roster.csv
  - orb_v23_a06_followup_20260804/analysis-output/provenance.csv
  - ../logs/orb_v23_a06_action_search_20260804.md
  - ../logs/orb_v23_postinit_search_20260804_final.md
---

# AQUA-FE Round 04: ORB-v23 A06 search addendum

The raw/final-online continuation found one new independent frozen-v23
action-positive window: AQUALOC A06 `2210-2460`.

A06 has 183/183 post-init accepted observations, three MapPoint lineages,
143 assisted matches, 22 assisted outliers, and 20/20 pre-KF purges. Its
trajectory result is metric-mixed: reconstructed APE/RPE worsen while online
APE/RPE improve. It is operational degraded/low-grid but not sparse base-KLT.

The deduplicated roster is now 9 mechanism/action-positive windows, 4 project
strict windows, and 2 all-control repeatwise strict windows. Operational
degraded/low-grid windows are 4/9; sparse base-KLT windows remain 0/9.

UVVID `s250,d20` and AFRL Cave `s150,d20` were excluded as pre-init/no-map
cases. AFRL Cemetery FR `s80,d30` reached one post-init MapPoint but had no
pre-KF purge action.

No ORB source, v23 threshold, binary, library, or runner was changed.
