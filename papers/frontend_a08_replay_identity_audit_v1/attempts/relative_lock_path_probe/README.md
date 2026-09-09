# Preserved first audit attempt

2026-09-10. The first read-only analyzer resolved two occurrences of the
utility runner's relative lock path against the main workspace, producing
MISSING. Both refer to the same scripts/run_observation_utility_diagnostics.py
in its original execution worktree, not a changed backend artifact. The
owner-resolved current file and committed source have the registered SHA-256.
Corrected this independent analyzer and added a regression test. These four
first-attempt derived files are retained here, not overwritten or scored.
Original eight run receipts/logs/bags/configs and audit scope are unchanged.
This is an analyzer-path error, not evidence of historical environment drift.
