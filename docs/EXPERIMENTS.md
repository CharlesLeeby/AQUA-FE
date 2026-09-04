# Experiment Log

This is the append-only index for formal experiments, benchmarks, ablations, parameter sweeps, frontend evaluations, and trajectory evaluations. Existing run-scale artifacts under logs/, experiments/, artifacts/, and papers/ remain authoritative; new entries here point to those artifacts rather than replacing them.

Rules:

- Never delete failed or negative experiments.
- Record measured values only. Use Not evaluated or Unknown for missing values.
- Record exact paths, configurations, commands, hashes, and validity gates whenever available.
- Treat a dataset sequence/window as the scientific unit unless a preregistration states otherwise. Technical replay repeats are not independent samples.
- Keep fixed-scale SE(3), Sim(3), proxy-reference, and ground-truth results explicitly distinguished.

## Entry template

## EXP-YYYYMMDD-001 — Experiment Name

### Objective

### Hypothesis

### Status and Scientific Role

Status:

Role: exploratory / development / confirmatory / ablation / diagnostic / negative result

### Code Version

Commit:

Branch:

Project Git status:

### Dataset

Dataset:

Sequence / window:

Input paths:

Reference / ground truth:

Sensors:

Environment:

### Configuration

Config files:

Overrides:

Random seeds:

Backend and binary/config hashes:

### Baseline

### Modification

### Commands and Artifacts

Command:

Run directory:

Primary metrics artifact:

Logs / receipts / manifests:

### Metrics

| Metric | Baseline | Proposed | Difference |
| ------ | -------: | -------: | ---------: |
| ATE / APE | Not evaluated | Not evaluated | Not evaluated |
| RPE | Not evaluated | Not evaluated | Not evaluated |
| Initialization / tracking success | Not evaluated | Not evaluated | Not evaluated |
| Lost tracking count | Not evaluated | Not evaluated | Not evaluated |
| Output coverage | Not evaluated | Not evaluated | Not evaluated |
| Runtime / FPS | Not evaluated | Not evaluated | Not evaluated |
| Feature count | Not evaluated | Not evaluated | Not evaluated |
| Inlier ratio | Not evaluated | Not evaluated | Not evaluated |
| Trajectory length | Not evaluated | Not evaluated | Not evaluated |

### Validity Checks

Input identity:

Run integrity:

Common support:

Metric validity:

### Results

### Observations

### Failed Attempts

### Interpretation

State what the evidence supports and what it does not support.

### Conclusion

### Follow-up
