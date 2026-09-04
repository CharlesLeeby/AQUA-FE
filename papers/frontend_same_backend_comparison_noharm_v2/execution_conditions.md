# noharm-v2 execution conditions

## Infrastructure pre-attempt

The first launch of `a03_5000_5900 / klt / r1` exited with code 2 before reading images or starting VINS. The common exporter CLI rejected the conceptual KLT seed target `none`; its accepted enum does not include `none`, even though `method=klt` never executes a learned branch.

The runner was corrected to pass the historical inert placeholder `xfeat` for `method=klt`. No exporter, model, threshold, gate, feature budget, backend binary, backend YAML, window, arm, or evaluation rule changed. The failed console, receipt, command, and exit code are retained under that run directory's `infrastructure_attempt_001/`. The successful rerun of the same preregistered cell is the formal repeat.

The runner also now resumes only exit-code-zero receipts and stops immediately after any future nonzero cell, preventing an incomplete r1 export from being mistaken for a completed repeat.

## Timing

Cells are executed serially. Wall-clock efficiency is outside this comparison; no timing claim is made.
