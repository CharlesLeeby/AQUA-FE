# Delayed newborn-slot router v3: frontend result

Date: 2026-09-05

Decision: `FRONTEND_GO`.

Outcome-known development controls only; backend is Not evaluated here.

- Complete cells: 18/18.
- Action-positive learned arm-windows: 7.
- Active cells: a09_6000_6800:router_xfeat, a09_6000_6800:router_splg, a02_0_900:router_xfeat, a02_0_900:router_splg, afrl_bus_s180_d045:router_xfeat, afrl_bus_s180_d045:router_splg, afrl_cemetery_s135_d045:router_xfeat.

## Frozen frontend checks

- `all_cells_integrity`: PASS
- `startup_frames_0_31_exact_klt`: PASS
- `actions_only_frames_32_36`: PASS
- `no_tracked_klt_or_old_gftt_removed`: PASS
- `age_advantage_at_least_2`: PASS
- `donor_cell_retained`: PASS
- `grid_occupancy_monotone`: PASS
- `per_frame_cap_6`: PASS
- `zero_action_exact_klt`: PASS

- `matched_control_complete`: True

No action count or proxy quantity is interpreted as backend success.
