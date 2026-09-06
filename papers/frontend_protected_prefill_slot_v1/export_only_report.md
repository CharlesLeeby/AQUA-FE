# Protected pre-refill slot v1: frontend result

Experiment: `EXP-20260906-009`

Decision: `PENDING_MATCHED_CONTROL`.

Outcome-known six-window development controls only; backend is Not evaluated here.

- Complete cells: 18/18.
- Action-positive learned arm-windows: 4/12.
- Active cells: a09_6000_6800:slot_xfeat, a02_0_900:slot_xfeat, a02_0_900:slot_splg, afrl_bus_s180_d045:slot_xfeat.

## Frozen frontend checks

- `all_18_cells_complete_and_integrity_pass`: PASS
- `all_carried_observations_exact`: PASS
- `only_age1_gftt_births_omitted`: PASS
- `no_extra_classical_observations`: PASS
- `actions_only_frames_0_4`: PASS
- `confirmed_non_loftr_sources_only`: PASS
- `candidate_age_at_least_3`: PASS
- `strict_count_contract_and_cap`: PASS
- `zero_action_exact_klt`: PASS

Candidates consume possible newborn-GFTT capacity; this is not a free or guaranteed no-harm intervention.
No frontend action count is interpreted as backend success.
