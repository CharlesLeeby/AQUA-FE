# Figure catalog

## Figure 1: `figures/figure-01-quality-partition-replays.pdf`

- Purpose: test whether classical quality partitions reproduce the q=1 divergence while learned geometry and XFeat q remain fixed.
- Data source: `/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/g0_all_replays_max350/common_support_summary.json`.
- Plotted variables: one-second translation RPE RMSE for every technical replay; horizontal bars are technical-replay medians; log y axis is explicit.
- Sample size: one scientific event, three technical repeats per arm.
- Caption requirements: state that dots are non-independent technical repeats and that no uncertainty bar is shown.
- Key observation: source-1-only remains stable, source-2 birth q=1 has a one-of-three severe error branch, and joint classical q=1 diverges in all three repeats.
- Interpretation: with learned-active geometry fixed, the negative result is a classical quality/backend interaction, not a learned-q-only failure.
- Caveat: a log axis is required to retain all branches without clipping; it must not be read as a population effect plot.

## Figure 2: `figures/figure-02-gftt-birth-lineage.pdf`

- Purpose: show why changing one source-2 observation per GFTT-born track can affect later factors.
- Data source: `/mnt/data/AQUA-FE_WS/logs/ntnu_vins/external_hybrid_xfeat_every2_validation_20260804_ntnu_fjord1_s83_d30_xfeat_historical_profile_nativeq/features.bag` plus the frozen VINS weighting implementation.
- Plotted variables: track-count funnel and positive changes in `sqrt(q)` for static full-bag lineage-pair opportunities.
- Sample size: 21,424 GFTT-born tracks; 34,565 diagnostic pair opportunities among full-bag tracks with at least four observations.
- Caption requirements: call these static lineage diagnostics, not runtime factor counts.
- Key observation: source 2 occurs exactly once at track birth and can cap later higher-q observations through `min(first_q,current_q)`.
- Interpretation: native birth reliability is an active part of this backend contract.
- Caveat: this mechanism localization comes from one development event and one VINS implementation.
