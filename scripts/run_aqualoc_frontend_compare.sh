#!/usr/bin/env bash
set -euo pipefail

MAX_FRAMES="${MAX_FRAMES:-120}"

METHOD=klt MAX_FRAMES="${MAX_FRAMES}" bash scripts/run_aqualoc_frontend_smoke.sh
METHOD=orb MAX_FRAMES="${MAX_FRAMES}" bash scripts/run_aqualoc_frontend_smoke.sh
METHOD=hybrid MAX_FRAMES="${MAX_FRAMES}" bash scripts/run_aqualoc_frontend_smoke.sh

python3 -m uw_frontend.evaluation.summarize_results \
  logs/aqualoc_harbor07_klt_frontend_smoke.csv \
  logs/aqualoc_harbor07_orb_frontend_smoke.csv \
  logs/aqualoc_harbor07_hybrid_frontend_smoke.csv \
  --output-csv logs/aqualoc_harbor07_frontend_compare_summary.csv \
  --output-md logs/aqualoc_harbor07_frontend_compare_summary.md
