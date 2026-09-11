# SEA-RAFT system probe v1

Branch: exp/searaft-system-probe-v1-20260911

Status: PROTOCOL_FROZEN; frontend and backend Not evaluated.

Task/protocol: papers/frontend_searaft_system_probe_v1/task_instructions.md and protocol.md. H02/A02 raw[0,900), B/C/R, three backend repetitions, at most18. Runtime: /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_system_probe_v1.

Initial validation: same-frame recovery priority unit test passed; first public B frame serialized exactly matches the frozen baseline for both windows. Initial quality-channel mismatch was resolved by restoring baseline raw_degradation quality fusion before formal inference.

Old CONTROLLED_GAIN_ONLY, EVIDENCE_GATE_NOT_SUPPORTED, REFERENCE_PENDING remain unchanged. Annotation is not a prerequisite. Resume from task_instructions.md; do not restart completed inference or replay.
