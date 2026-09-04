# Frozen frontend positive-window exploration protocol

## Scope

This exploration extends, but does not modify, the completed 20-cluster frozen
evaluation in `papers/frozen_frontend_eval_20260714`. New windows are screened as
an exploratory cohort and are not added to the frozen denominator.

## Frozen implementation

The frontend, arbitration, exporter, VINS implementation, drop rule, and metric
contract remain unchanged. The checked SHA-256 values are:

```text
82bd47f019a423fc3e8f92bf533c06556dd1eb9b2d20c49ba8ff09e435744fb0  scripts/run_xfeat_seedchain_arbitrated_eval.sh
8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106  scripts/run_learned_seedchain_eval.sh
de78c8258f32bcea4c04d4d4fffa9fa8ac82abffbf896a1c73ba28b694702f67  uw_frontend/ros/export_vins_features.py
4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce  uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml
745d8c5c07cbc8fb65e307221f744e5c4b44b3f93618c4ca68754a7060430e0d  scripts/filter_feature_bag_by_channel.py
ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33  scripts/evaluate_vins_sim_ape.py
b994676b9e845c68427d01c8d80b1a4492ed2dedd25a770918cff61b0fea4ff4  scripts/evaluate_vins_tum.py
```

VINS is fixed to `/home/ma/SLAM/VINS-Fusion-origin` with
`VINS_MULTIPLE_THREAD=0`. `/home/ma/SLAM/VINS-Fusion_3-15-WS` is not used.

## Screening rule

1. Use a fresh current-exporter probe from the raw dataset window.
2. Use natural, non-overlapping windows or previously documented candidates;
   do not tune a start by one or two frames after observing a burst.
3. Run full arbitration only when historical evidence is strong enough to
   justify the extra export. A final `klt_safe_fallback` is not learned-active.
4. Run full/drop/KLT VINS only after the frozen arbitration selects a
   learned-active final profile.
5. Use whole-lineage drop, SE(3) APE with `max_match_dt=0.6 s`, 1-second RPE,
   and the same valid-output checks as the frozen evaluation.

## Artifacts

- `screening_summary.csv`: compact per-window frontend screening statistics.
- `run_evidence.csv`: standard `summarize_run_evidence.py` output for all fresh
  probe runs.
- `report.md`: decisions, near misses, and the effect on the evidence claim.

