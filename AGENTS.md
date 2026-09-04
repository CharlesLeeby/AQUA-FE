# AGENTS.md

## Scope and precedence

These instructions apply to the entire /home/ma/AQUA-FE_WS workspace. Read this file, CLAUDE.md, uw_frontend/README.md, and the nearest experiment protocol before making changes. More specific frozen protocols and preregistrations take precedence for the experiment they govern.

This workspace is a standalone Git repository on branch main with SSH origin git@github.com:CharlesLeeby/AQUA-FE.git (public page: https://github.com/CharlesLeeby/AQUA-FE). Always confirm that git rev-parse --show-toplevel returns /home/ma/AQUA-FE_WS; never interpret the host-root repository as project status. Do not commit, push, rewrite history, or change remotes unless the user explicitly requests it.

## Project context

This repository contains research code for underwater visual SLAM, specifically a quality-guided visual frontend and its experimental evidence. Typical research topics may include:

- underwater image degradation
- illumination variation
- color attenuation
- turbidity and backscatter
- feature detection and matching
- visual odometry
- bundle adjustment
- loop closure
- geometric estimation
- visual-inertial fusion
- sonar / DVL / IMU fusion
- trajectory evaluation
- robustness experiments
- ablation studies

The executable research package is uw_frontend/. Experiment runners and analysis utilities are in scripts/. Paper protocols, freezes, audits, negative results, and claim-evidence records are primarily in papers/. Run-scale artifacts are in experiments/, artifacts/, and the logs symlink. The datasets, logs, and external_tools paths are symlinks into /mnt/data/AQUA-FE_WS/.

This is a frontend-focused workspace. Closed-loop evaluation uses an external VINS-Fusion workspace, normally /home/ma/SLAM/VINS-Fusion-origin. Do not modify /home/ma/SLAM/VINS-Fusion_3-15-WS. Do not modify any external backend unless the user explicitly places it in scope.

This is research code: correctness, reproducibility, provenance, and traceability are more important than aggressive refactoring.

## Working principles

Before coding:

1. Understand the relevant modules and end-to-end data flow.
2. State the objective, assumptions, evidence boundary, and a short implementation plan.
3. Read the applicable configuration map, preregistration, frozen contract, and prior negative results.
4. Check for existing processes and incomplete runs before launching ROS, VINS, or long jobs.

During coding:

1. Make the smallest change needed for the stated objective.
2. Avoid unrelated refactors and unnecessary interface changes.
3. Preserve existing behavior unless the task explicitly requires changing it.
4. Preserve the protected KLT/GFTT backbone and two-profile interpretation unless the user authorizes a research-direction change:
   - proposed_safe: protected KLT mirror plus strictly gated learned/LoFTR sidecars.
   - contribution_sparse: deliberately weaker/sparser backbone used only to measure learned contribution.
5. Do not edit export gates merely to make a metric pass.
6. Do not overwrite frozen inputs, preregistrations, manifests, hashes, run receipts, or prior outputs.
7. Never delete old experiments, failed attempts, negative results, or historical records. Quarantine incomplete artifacts when a governing protocol requires it.
8. Mark uncertainty explicitly instead of guessing.

After coding:

1. Inspect the complete diff or, while Git metadata is unavailable, inspect exact changed files and produce a no-index/stat fallback.
2. Run the smallest relevant validation first. After changing a gate or profile, run an export-only probe before any long VINS replay.
3. State exactly what was verified and what remains Not evaluated.
4. Update the logs required below.

## Evidence and scientific integrity

Never:

- fabricate experiment results, dataset properties, citations, or paper conclusions;
- turn Hypothesis / Inference into a confirmed fact;
- claim effectiveness because code looks plausible;
- hide negative results, failed runs, invalid common support, initialization failures, or null action;
- treat repeated solver replays as independent scientific samples;
- compare APE/RPE when one arm has no valid trajectory or the common-support gate fails;
- claim learned contribution when accepted learned-born observations are zero;
- change the research direction or promote an ablation to the main method without explicit authorization.

Use these exact labels when applicable:

- Not evaluated.
- Unknown.
- Hypothesis / Inference.
- Confirmed fact.

Tie every quantitative statement to an inspectable artifact path, exact dataset/window, configuration/profile, metric definition, and validity boundary. Prefer fresh same-contract baselines over cached historical numbers. Keep frontend reliability q_i distinct from demonstrated backend trajectory influence.

## Research logging

Every completed task with meaningful project impact must append a new entry to docs/CODEX_WORKLOG.md. Do not rewrite or delete history. Each entry must include:

- Date
- Task objective
- Problem / motivation
- Files changed
- Implementation
- Technical decisions
- Experiments performed
- Quantitative results
- Qualitative observations
- Failed attempts
- Known issues
- Interpretation
- Next steps

Do not merely list edits. Record why the change was made, which hypothesis or contract was checked, what the evidence shows, and what it does not show. If no experiment ran, write Not evaluated.

## Experiment logging

Whenever a formal experiment, benchmark, ablation, parameter sweep, frontend evaluation, or trajectory evaluation is performed, append it to docs/EXPERIMENTS.md. Preserve failed and negative experiments.

Every entry must include:

- Experiment ID
- Date
- status and scientific role
- Git commit and branch, or Unknown when unavailable
- dataset and sequence/window
- environment and exact configuration
- baseline
- proposed modification
- commands and artifact/run paths
- metrics
- results
- validity checks and common-support status
- interpretation
- conclusion
- follow-up

For SLAM/VIO, preferentially record ATE/APE, RPE, initialization and tracking success, lost-tracking count, coverage, runtime/FPS, feature count, inlier ratio, and trajectory length. Do not invent unavailable metrics.

## Research reasoning

When a task introduces a research idea, method design, important algorithm decision, evidence interpretation, or changed conclusion, append a reasoning entry to docs/RESEARCH_LOG.md. It must capture:

- Research question
- Hypothesis
- Motivation
- Related baseline
- Proposed idea
- Why it might work
- Assumptions
- Potential failure cases
- Evidence
- Current conclusion
- Open questions
- Next experiment

This file is paper-oriented reasoning memory, not a code changelog. Clearly separate Confirmed facts from Codex inference.

## Project context maintenance

Update docs/PROJECT_CONTEXT.md only when project state changes materially, including:

- baseline or main method changes;
- a new dataset or evaluation contract;
- a new validated result or invalidated hypothesis;
- a major bug or evidence-integrity issue;
- a change in research direction, priorities, or next experiments.

Routine implementation details belong only in docs/CODEX_WORKLOG.md.

## Experiment execution defaults

- Run commands from /home/ma/AQUA-FE_WS because the package has no installed-project metadata.
- Use uw_frontend/configs/README_recommended.md to distinguish defaults from probes and rejected variants.
- Use papers/frontend_baseline_protocol.md and the experiment-specific preregistration for baseline/proposed/ablation roles.
- For low-texture contribution, compare KLT, learned without LoFTR, and learned with LoFTR when the protocol calls for those arms.
- For normal-texture no-harm, compare KLT and proposed_safe and report actual learned/LoFTR export counts.
- Record run directories and primary CSV/report artifacts, not only console summaries.
- Check and clean up only processes launched for the current authorized task; never kill unrelated ROS or research jobs.
