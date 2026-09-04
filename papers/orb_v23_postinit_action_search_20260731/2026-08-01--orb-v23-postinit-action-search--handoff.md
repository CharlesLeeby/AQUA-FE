# ORB-SLAM3 v23 post-init action-search handoff

## Status

The frozen AQUALOC post-init search is complete. The strict new positive is A02 `2800-3200`.
The analysis denominator contains five screened windows; A09 and A07 remain smoke-only, while
A08, A10 `400-800`, and A02 received formal five-arm x four-repeat evaluation.

## Bundle

- Manifest: `manifest.json`
- Strict analysis: `analysis-output/analysis-report.md`
- Statistics and limits: `analysis-output/stats-appendix.md`
- Figures: `analysis-output/figures/`
- Machine-readable screening: `analysis-output/screening_summary.csv`
- Machine-readable formal cases: `analysis-output/case_summary.csv`
- Provenance and hashes: `analysis-output/provenance.json`, `analysis-output/trajectory_hash_audit.json`
- Rebuild command:
  `python3 scripts/analyze_orbslam3_v23_postinit_action_search.py --manifest papers/orb_v23_postinit_action_search_20260731/manifest.json --output papers/orb_v23_postinit_action_search_20260731/analysis-output --replace`

## Strict positive

A02 smoke reached `106/106` post-init accepted observations, one external lineage with a MapPoint,
and formal full action of `7` assisted matches, `3` total/pre-KF assisted outliers, and `3/3`
pre-KF purges in all four repeats.

Full versus native/drop:

- Reconstructed APE/RPE: `0.023321/0.021781` vs `0.077687/0.037684`, improvements `69.98%/42.20%`.
- Online APE/RPE: `0.022080/0.018213` vs `0.066472/0.032750`, improvements `66.78%/44.39%`.

Full versus unbounded also improves all four metrics: reconstructed `74.30%/46.04%`, online
`71.31%/44.83%`. All 48 directional full-versus-control checks pass and full trajectory/action
hashes are stable across repeats.

## Screening outcomes

- A09 `4000-4400`: `30/30` post-init, `22` assisted matches, `0/0` outlier/purge; no formal matrix.
- A08 `4500-4660`: formal action `32/23/10/10` (matches/total outliers/pre-KF outliers/purges), but online APE worsens `49.03%`; action-positive, not strict positive.
- A07 `10800-11200`: six pre-init observations and one post-init border rejection; action exists, but pure post-init protocol fails.
- A10 `400-800`: formal action `28/1/1/1`, improves over unbounded but reconstructed full worsens native by `9.46%/9.23%`; guard-rescue boundary. Drop r4 remains a retained map-branch anomaly.

## Boundaries

RPE uses evaluator `delta=1` with `max_time_diff=0.06 s`; no significance test is reported because
repeats are deterministic replications of one window. A10 has one input seed below nominal q 0.9
(`q=0.890251338`); the extractor accepted it under the frozen interface and the caveat is recorded.

