# Frozen frontend evaluation protocol

## Frozen algorithm

No frontend, exporter, arbitration threshold, or VINS source change is permitted after this
protocol starts. The runner checks these SHA-256 values before every case:

```text
82bd47f019a423fc3e8f92bf533c06556dd1eb9b2d20c49ba8ff09e435744fb0  scripts/run_xfeat_seedchain_arbitrated_eval.sh
8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106  scripts/run_learned_seedchain_eval.sh
de78c8258f32bcea4c04d4d4fffa9fa8ac82abffbf896a1c73ba28b694702f67  uw_frontend/ros/export_vins_features.py
4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce  uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml
745d8c5c07cbc8fb65e307221f744e5c4b44b3f93618c4ca68754a7060430e0d  scripts/filter_feature_bag_by_channel.py
ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33  scripts/evaluate_vins_sim_ape.py
b994676b9e845c68427d01c8d80b1a4492ed2dedd25a770918cff61b0fea4ff4  scripts/evaluate_vins_tum.py
```

The VINS implementation is fixed to `/home/ma/SLAM/VINS-Fusion-origin`. The forbidden
`VINS-Fusion_3-15-WS` workspace is not used.

## Three-way comparison

For every fresh-capable case:

1. `full`: fresh current arbitration export from the raw/short bag, then VINS replay.
2. `drop`: remove every observation whose feature ID was ever learned, including later KLT
   propagation, from the fresh final full bag; replay the resulting bag.
3. `KLT`: independently fresh-export the same raw window with method `klt`, then replay it.

All three use `multiple_thread=0`. AQUALOC A07 uses the already frozen
`degraded_mature_dense` recovery timing for all three arms, not only for full.

## Metric contract

- Primary metric: SE(3)-aligned APE RMSE, lower is better.
- Secondary metric: 1-second translational RPE RMSE, lower is better.
- Timestamp association: nearest match with `max_match_dt=0.6 s` for every dataset.
- Main win: full has valid output and APE is no worse than both drop and KLT.
- Dual-metric win: full is no worse than both controls on both APE and RPE.
- No-harm: full APE degradation relative to KLT is at most 5%.
- Hard failure: no valid trajectory, `init_success=0`, or output coverage below 0.5.
- Solver risk is reported separately from hard failure.

The repeated-measure unit is the independent temporal cluster in `manifest.csv`. Overlapping
extensions are excluded from the denominator. AFRL `FR70-100` is explicitly marked as an
existing-bag replay because its raw bag is unavailable.

## Completion record

The matrix completed with 20 fresh independent clusters (60 arms) plus one AFRL
existing-feature-bag cluster (3 arms). Final machine-readable results are in
`analysis-output/results_long.csv` and `analysis-output/case_summary.csv`.

Three replay artifacts were replaced after detecting unrelated concurrent VINS processes or
same-input replay instability. Their original paths remain in the corresponding status files:

- `h02_2400_2800`: contaminated full replaced by idle exact-config `full_idle_r2`.
- `a08_4480_4680`: contaminated full/drop replaced by idle exact-config `*_idle_r1`.
- `a02_8600_9000`: unstable same-bag three-way replay replaced by idle exact-config `*_idle_r1`.

These replacements replayed the already frozen feature bags. No frontend export, arbitration,
or algorithm file was changed. AFRL used the historical full/drop/KLT feature bags and a common
single-thread VINS configuration; it is excluded from all fresh-export denominators.
