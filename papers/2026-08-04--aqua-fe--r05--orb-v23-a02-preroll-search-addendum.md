---
type: results-report
date: 2026-08-04
experiment_line: aqua-fe
round: 5
purpose: orb-v23-a02-phase-aligned-search-addendum
status: complete
source_artifacts:
  - orb_v23_a02_preroll_followup_20260804/analysis-output/analysis-report.md
  - orb_v23_a02_preroll_followup_20260804/analysis-output/a02_preroll_formal_summary.csv
  - orb_v23_a02_preroll_followup_20260804/analysis-output/screening_summary.csv
  - orb_v23_a02_preroll_followup_20260804/analysis-output/window_roster.csv
  - orb_v23_a02_preroll_followup_20260804/analysis-output/provenance.csv
  - orb_v23_a02_preroll_followup_20260804/analysis-output/validation_summary.json
  - ../logs/orb_v23_a02_preroll_action_search_20260804.md
  - ../logs/orb_v23_postinit_search_20260804_final.md
---

# AQUA-FE Round 05: ORB-v23 A02 phase-aligned search addendum

The continuation found one new fixed-interval frozen-v23 action-positive
window: AQUALOC A02 `8520-9000`.

The interval adds 40 unseeded native frames before the exact `8600-9000`
suffix. It does not alter the 375 seed rows, timestamps, IDs, qualities,
selector, ORB source, v23 thresholds, binary, library, or runner. The old
overlapping `8600-9000` mixed-phase precursor remains excluded; the time
cluster counts once.

A02 `8520-9000` has 375/375 post-init observations, two MapPoint lineages,
279 assisted matches, 22 assisted outliers, and 10/10 pre-KF purges. All 20
formal runs are deterministic and audit-clean.

The role-aware provenance audit passes in full: the four seedless `orb_only`
runs each contain 28 snapshot entries, the 16 seeded runs each contain 29,
and all `576/576` listed files match their recorded SHA-256. The 28 common
frozen paths are identical across all runs; only the expected seed input
distinguishes the native, empty-drop, and full-family snapshot groups.

Its result is metric-mixed. Reconstructed APE worsens by `3.586%` while
reconstructed RPE improves by `1.114%`; online APE/RPE improve by
`35.425% / 17.907%`. All four metrics improve relative to unbounded. It is
action-positive, not project strict.

The current deduplicated roster is 10 mechanism/action-positive windows, 4
project-strict windows, and 2 all-control repeatwise-strict windows. Five of
10 positives are operational degraded/low-grid; sparse base-KLT positives
remain 0/10.
