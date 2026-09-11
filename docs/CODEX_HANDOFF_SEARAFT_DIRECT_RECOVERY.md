# SEA-RAFT direct recovery v1

Status: PROTOCOL_FROZEN / execution Not evaluated.
Branch: exp/searaft-direct-recovery-v1-20260911; base1138fab635910d3e1c34d57f99dab84c6ff8e9f5.
Task and frozen one-page protocol: papers/frontend_searaft_direct_recovery_v1/.

D removes strong LK entirely; own causal KLT→SEA-RAFT state, unchanged gates and corrected export. Two focused tests passed (including hard failure on any D strong-LK call). Fixed order H02 B1..3,D1..3 then A02 B1..3,D1..3, at most12 new backends. Fresh B; old C/R only auxiliary common-support re-evaluation.

Runner: scripts/run_searaft_direct_recovery.py freeze/frontend/backend. Runtime /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_direct_recovery_v1. Missing exact queries may require one shared forward/backward inference per pair, at most1798 pairs. Do not restart a completed pair; preserve old inputs and results.

Old UNSAFE_OR_UNRESOLVED and screening/reference conclusions unchanged. Stop after this ablation; no automatic tuning, expansion or annotation.
