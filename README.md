# AQUA-FE

AQUA-FE is a research workspace for a quality-guided underwater visual
SLAM/VO/VIO frontend. The system keeps GFTT/KLT as a protected temporal
backbone and admits classical or learned recovery only under explicit
image-quality, temporal, spatial-coverage, and geometric checks.

The learned hooks include XFeat, SuperPoint + LightGlue, and a deliberately
restricted LoFTR path for extreme low-texture or near-planar support. The
workspace exports frontend metrics, per-feature reliability, and ROS feature
bags for evaluation with external SLAM/VIO backends.

## Repository layout

- uw_frontend/ — executable Python frontend package.
- uw_frontend/configs/ — baseline, proposed, ablation, and experimental YAML
  profiles.
- scripts/ — dataset preparation, feature export, replay, audit, evaluation,
  and report utilities.
- tests/ — unittest-based contract and evaluator tests.
- papers/ — preregistrations, frozen protocols, evidence tables, reports, and
  preserved negative results.
- configs/ — configurations for external comparison backends.
- docs/ — project context, work log, experiment ledger, and research log.
- AGENTS.md — repository-wide rules for reproducible AI-assisted work.

Large datasets, model weights, ROS bags, build products, and run-scale outputs
are intentionally excluded. Published reports retain their artifact paths,
hashes, and validity boundaries.

## Quick start

Run commands from the repository root because the package is not installed as
a wheel:

    python3 -m uw_frontend.evaluation.run_frontend_eval \
      --input /path/to/images-or-archive \
      --config uw_frontend/configs/klt_frontend.yaml \
      --method klt \
      --output-csv /path/to/frontend_metrics.csv

See uw_frontend/README.md for dataset-specific examples, metrics, learned
matcher setup, reliability calibration, and VINS feature export.

## External dependencies

OpenCV-only KLT/ORB paths do not require learned matchers. XFeat,
SuperPoint + LightGlue, LoFTR, ROS Noetic, VINS-Fusion, datasets, and model
weights are external dependencies and are not vendored here. Historical local
paths in protocols describe the original execution environment and may need to
be remapped.

The usual fixed-backend experiments use a separate VINS-Fusion workspace.
This repository does not vendor or claim ownership of that backend.

## Scientific evidence boundary

The durable method interpretation is:

- proposed_safe — protected KLT mirror plus strictly gated learned/LoFTR
  sidecars;
- contribution_sparse — a deliberately sparse/degraded backbone used to
  measure learned contribution when KLT is weak.

No single result should be treated as a universal underwater-SLAM claim.
Before citing numbers, read docs/PROJECT_CONTEXT.md,
docs/RESEARCH_LOG.md, and the experiment-specific preregistration or report.
In particular, zero learned action supports fallback/no-harm for those inputs,
not learned contribution.

## Reproducibility and project memory

- docs/PROJECT_CONTEXT.md provides the short current-state handoff.
- docs/CODEX_WORKLOG.md records meaningful implementation tasks.
- docs/EXPERIMENTS.md is the append-only formal experiment index.
- docs/RESEARCH_LOG.md records research questions and evidence interpretation.
- papers/frontend_baseline_protocol.md defines baseline/proposed/ablation
  roles.
- uw_frontend/configs/README_recommended.md distinguishes recommended,
  experimental, and rejected profiles.

The repository currently has no declared open-source license. Contact the
repository owner before redistributing or reusing the code.
