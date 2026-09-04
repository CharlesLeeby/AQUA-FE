---
type: results-report
date: 2026-08-03
experiment_line: aqua-fe
round: 3
purpose: orb-v23-h07-search-addendum
status: complete
source_artifacts:
  - orb_v23_h07_followup_20260803/analysis-output/analysis-report.md
  - orb_v23_h07_followup_20260803/analysis-output/new_h07_formal_summary.csv
  - orb_v23_h07_followup_20260803/analysis-output/window_roster.csv
  - orb_v23_h07_followup_20260803/analysis-output/provenance.csv
  - ../logs/orb_v23_h07_action_search_20260803.md
  - ../logs/orb_v23_postinit_search_20260803_final.md
---

# AQUA-FE Round 03: ORB-v23 H07 search addendum

The raw final-online follow-up found three new independent frozen-v23 H07
action-positive windows: `1000-1160`, `1320-1480`, and `1480-1640`.
The first two are metric-mixed. H07 `1480-1640` is project strict against
native/drop and unbounded on reconstructed and online APE/RPE, with a
bridge-off reconstructed caveat.

The deduplicated roster is now 8 mechanism/action-positive windows, 4 project
strict windows, and 2 all-control repeatwise strict windows. Operational
degraded/low-grid windows are 3/8; sparse base-KLT windows remain 0/8.

No ORB source, v23 threshold, binary, library, or runner was changed. A new
H07 camera configuration and a reconstructed `1000-1160` raw segment were
created from the retained official calibration and full H07 rosbag; their
hashes are recorded in the provenance table.
