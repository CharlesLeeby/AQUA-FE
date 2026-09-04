#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="papers/ieee_sensors_journal_experiments/g0"
mkdir -p "$OUT"

python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v \
  >"$OUT/unit_tests.log" 2>&1

python3 scripts/evaluate_vins_common_support.py \
  --reference-bag datasets/aqualoc/rosbags/archaeo10_2400_2800.bag \
  --reference-topic /aqualoc/colmap_gt \
  --arm full=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_full_r1/vins_output/vio.csv \
  --arm drop=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_drop_r1/vins_output/vio.csv \
  --arm klt=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_klt_r1/vins_output/vio.csv \
  --arm-config full=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_full_r1/vins_aqualoc_archaeo_external.yaml \
  --arm-config drop=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_drop_r1/vins_aqualoc_archaeo_external.yaml \
  --arm-config klt=logs/aqualoc_archaeo_vins/external_klt_every2_jul21_online_positive_a10_2400_2800_klt_r1/vins_aqualoc_archaeo_external.yaml \
  --nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 \
  --contrast-name a10_2400_2800_full_drop_klt_r1 \
  --output-dir "$OUT/a10_2400_2800_probe" --run-evo

python3 scripts/evaluate_vins_common_support.py \
  --reference-bag /mnt/data/AQUA-FE_WS/online_positive_search_20260721/a09_4000_4400_fresh2/full_merged.bag \
  --reference-topic /aqualoc/colmap_gt \
  --arm full=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_full_r2/vins_output/vio.csv \
  --arm drop=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_drop_r2/vins_output/vio.csv \
  --arm klt=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_klt_r2/vins_output/vio.csv \
  --arm-config full=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_full_r2/vins_replay_external.yaml \
  --arm-config drop=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_drop_r2/vins_replay_external.yaml \
  --arm-config klt=logs/aqualoc_archaeo_vins/external_klt_every2_jul22_finalonline_a09_4000_klt_r2/vins_replay_external.yaml \
  --nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 \
  --contrast-name a09_4000_4400_full_drop_klt_r2 \
  --output-dir "$OUT/a09_4000_4400_probe" --run-evo

python3 scripts/evaluate_vins_common_support.py \
  --reference-bag logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460/features.bag \
  --reference-topic /aqualoc/colmap_gt \
  --arm full=logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460/vins_output/vio.csv \
  --arm klt=logs/aqualoc_archaeo_vins/external_klt_every2_slamgate_v31_a06_2210_2460_klt_sorted/vins_output/vio.csv \
  --arm-config full=logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460/vins_aqualoc_archaeo_external.yaml \
  --arm-config klt=logs/aqualoc_archaeo_vins/external_klt_every2_slamgate_v31_a06_2210_2460_klt_sorted/vins_aqualoc_archaeo_external.yaml \
  --nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 \
  --contrast-name a06_2210_2460_mirrorinject_vs_klt \
  --output-dir "$OUT/a06_2210_2460_probe" --run-evo

python3 scripts/evaluate_vins_common_support.py \
  --reference-tum datasets/full_downloads/ntnu_hf/subset-fjord/fjord_4/fjord_4_baseline.tum \
  --arm full=logs/ntnu_vins/external_hybrid_xfeat_every3_may20k_ntnu_fjord4_s0_d30_xfeat_formal_proposed/vins_output/vio.csv \
  --arm protected=logs/ntnu_vins/external_hybrid_xfeat_every3_may20k_ntnu_fjord4_s0_d30_xfeat_formal_protected/vins_output/vio.csv \
  --arm klt=logs/ntnu_vins/external_klt_every3_may20k_ntnu_fjord4_s0_d30_klt_full350/vins_output/vio.csv \
  --arm-config full=logs/ntnu_vins/external_hybrid_xfeat_every3_may20k_ntnu_fjord4_s0_d30_xfeat_formal_proposed/vins_ntnu_external.yaml \
  --arm-config protected=logs/ntnu_vins/external_hybrid_xfeat_every3_may20k_ntnu_fjord4_s0_d30_xfeat_formal_protected/vins_ntnu_external.yaml \
  --arm-config klt=logs/ntnu_vins/external_klt_every3_may20k_ntnu_fjord4_s0_d30_klt_full350/vins_ntnu_external.yaml \
  --nominal-reference-rate-hz 50 --nominal-estimate-rate-hz 6.6666666667 \
  --window-start-s 1700605840.195402 --window-end-s 1700605870.186740 \
  --contrast-name ntnu_fjord4_s0_d30_xfeat_protected_klt \
  --output-dir "$OUT/ntnu_fjord4_s0_d30_probe" --run-evo

python3 scripts/evaluate_vins_common_support.py \
  --reference-bag logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_dir3_mirror_gate_h07_0_1000/features.bag \
  --reference-topic /aqualoc/colmap_gt \
  --arm full=logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_dir3_mirror_gate_h07_0_1000/vins_output/vio.csv \
  --arm klt=logs/aqualoc_real_vins/external_klt_every2_trial_real_h07_0_1000_klt_adaptive_clahe/vins_output/vio.csv \
  --arm-config full=logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_dir3_mirror_gate_h07_0_1000/vins_aqualoc_external.yaml \
  --arm-config klt=logs/aqualoc_real_vins/external_klt_every2_trial_real_h07_0_1000_klt_adaptive_clahe/vins_aqualoc_external.yaml \
  --nominal-reference-rate-hz 4 --nominal-estimate-rate-hz 10 \
  --contrast-name h07_0_1000_normal_full_vs_klt \
  --output-dir "$OUT/h07_0_1000_probe" --run-evo

python3 scripts/summarize_g0_common_support.py \
  --probe A10_2400_2800="$OUT/a10_2400_2800_probe/common_support_summary.json" \
  --probe A09_4000_4400="$OUT/a09_4000_4400_probe/common_support_summary.json" \
  --probe A06_2210_2460="$OUT/a06_2210_2460_probe/common_support_summary.json" \
  --probe NTNU_FJORD4_S0_D30="$OUT/ntnu_fjord4_s0_d30_probe/common_support_summary.json" \
  --probe H07_0_1000="$OUT/h07_0_1000_probe/common_support_summary.json" \
  --proposed-arm full --comparator-arm drop --comparator-arm klt \
  --output-csv "$OUT/legacy_vs_corrected.csv" \
  --output-evo-csv "$OUT/evo_crosscheck.csv" \
  --output-report "$OUT/g0_evaluator_validation.md"

sha256sum \
  scripts/trajectory_eval_core.py \
  scripts/evaluate_vins_common_support.py \
  scripts/summarize_g0_common_support.py \
  papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md \
  >"$OUT/evaluator_hashes.sha256"

echo "G0_EVALUATOR_VALIDATION_COMPLETE"
