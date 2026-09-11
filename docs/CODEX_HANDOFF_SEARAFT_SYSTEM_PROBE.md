# SEA-RAFT system probe v1

Status: COMPLETE — UNSAFE_OR_UNRESOLVED.
Branch: exp/searaft-system-probe-v1-20260911.

[Report](../papers/frontend_searaft_system_probe_v1/report.md) · [Results](../papers/frontend_searaft_system_probe_v1/results.csv) · [Comparison](../papers/frontend_searaft_system_probe_v1/comparison.csv) · [Decision](../papers/frontend_searaft_system_probe_v1/decision.json).

H02/A02 raw[0,900), B/C/R×3:18 new backend replays,0 historical reuse,0 additional repeats. H02 R APE median0.026602m versus B0.111301m; C1017.991709–1030.084500m is an unexplained control anomaly. A02 R1.157391m versus B0.065202m and C1.153630m: severe regression versus B, no practical increment over C. B repeat instability in both windows and C instability in A02 limit inference.

1355 new image-pair inferences (2710 direction calls),203 exact query-cache reuses,354.66s prediction/sampling including loading. Learned recovery events1135/33 for H02/A02;1055/15 reach public observations. All18 runs receive complete feature input; common support and evo checks pass. Physical correspondence correctness remains Unknown.

Before backend, fixed original ROS epoch-float velocity arithmetic by cache-only re-export: zero new inference, unchanged recovery/public tracks, full B serialization exact in both windows. Rejected initial export is preserved under runtime/pre_velocity_fix. Source/input/model/backend identities are in the experiment directory. Runtime: /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_system_probe_v1.

Stop this combination. No new inference, backend replay, parameter tuning, expansion, annotation work or deployment is authorized by completion. Any next research task requires a new user instruction. Old CONTROLLED_GAIN_ONLY, EVIDENCE_GATE_NOT_SUPPORTED, REFERENCE_PENDING and all old artifacts remain unchanged. Resume context from the task_instructions.md file, not older experiment receipts.
