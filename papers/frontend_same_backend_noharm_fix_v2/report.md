# XFeat seed-chain no-harm repair v2

## Outcome

The observed XFeat regressions were not caused by a different VINS backend or by evo alignment. They came from an unsafe publication policy in the frontend:

1. the online seed gate ran after the ordinary learned degradation gate and admitted compact XFeat bursts even though `learned_export_gate_reason=disabled` on every frame of the four formal windows;
2. the final mirror exporter allocated the 350-point budget to learned sidecars first and then reduced the independent KLT mirror to the remaining capacity;
3. therefore each accepted XFeat observation evicted one KLT observation. This happened at initialization in `a06_s000_d045` (12/29/9 observations on frames 3/5/7) and late in the healthy Harbor07 anchor (50 observations on frames 883-893).

The failure was a contract gap: the previous implementation guaranteed exact KLT rollback only when zero sidecars reached the finalizer. Once a sidecar was accepted, trajectory non-inferiority was merely an empirical assumption. [root_cause.csv](root_cause.csv) records every old common-support window, including the window where the same replacement happened to help.

## Repair

A new frontend epoch, `lineage_early_seed_noharm_v4`, was added and made the default for the generic non-CIRS seed-chain entry point. It retains all frozen v3 seed-chain thresholds but changes the final publication invariant:

- an independent KLT mirror is explicitly enabled across all dataset runners;
- the KLT mirror receives the feature budget first;
- learned sidecars can use only vacant capacity below `EXPORT_MAX_FEATURES=350`;
- a sidecar may never evict an independent KLT observation;
- if all sidecars are rejected for lack of capacity, the complete KLT mirror is restored verbatim, including ids, order, points, ages, frontend qualities, and the published PointCloud bytes.

The legacy `lineage_early_seed_scan` behavior and all frozen supplement artifacts remain unchanged and remain available only when named explicitly. This repair is a new frontend version and must not be used to relabel the old results.

## Frontend validation

The failure was first reproduced on a 3 s A06 export-only probe and then checked on two complete old counterexamples.

| probe | candidates / confirmed | sidecars reaching finalizer | kept | KLT evicted | result |
|---|---:|---:|---:|---:|---|
| A06 3 s | 54 / 30 | 50 | 0 | 0 | XFeat bag byte-identical to KLT |
| A06 45 s | 397 / 130 | 50 | 0 | 0 | XFeat bag byte-identical to frozen KLT |
| Harbor07 50 s | 45 / 9 | 50 | 0 | 0 | XFeat bag byte-identical to frozen KLT |
| AFRL FL 3 s | 47 / 16 | 7 | 0 | 0 | XFeat bag byte-identical to KLT after runner propagation fix |

The full A06 and H07 runs reproduced the exact old trigger frames and sidecar counts. Thus equality is not caused by disabling XFeat inference: candidates and confirmed tracks still exist, but the unsafe budget replacement is blocked. See [frontend_validation.csv](frontend_validation.csv).

One first AFRL probe is explicitly invalid: the preserve flag reached the runner, but the runner did not activate the independent mirror because the older profile had relied on two indirect AQUALOC-only switches. The profile now freezes mirror activation directly, and the same sealed AFRL short bag passed on rerun. The invalid probe is retained in the CSV.

No real validation frame in this batch had vacant independent-mirror capacity at a sidecar trigger, so the safe profile made no learned contribution in these probes. A unit test verifies that sidecars are retained when genuine capacity exists. Real low-texture benefit remains a separate pre-registered empirical question; it is not claimed here.

## Closed-loop replay

The repaired full A06 feature bag has SHA-256 `500c4f...ab97`, exactly equal to the frozen KLT bag. It was replayed three times through the unchanged backend. All repeats initialized, produced 406 poses over 40.495 s, and reached 90.0% coverage.

On the joint 40-pose / 39-pair common support:

| arm | fixed-scale SE(3) APE RMSE median [range] m | 1 s RPE RMSE median [range] m |
|---|---:|---:|
| frozen KLT repeats | 2.643 [2.520, 3.025] | 0.339 [0.319, 0.351] |
| XFeat no-harm v4 repeats | 2.543 [2.183, 2.728] | 0.351 [0.297, 0.354] |

The median changes are -3.76% APE and +3.72% RPE. Because both arms consume the exact same feature bag, these differences are backend replay variability and cannot be attributed to XFeat. The correct no-harm statement is therefore input-contract equivalence on full-budget frames, not a claim that a stochastic VINS replay must return numerically identical trajectories. The independent evo cross-check differs by at most `4.37e-7 m`. Full fixed-scale and explicitly labeled Sim(3) diagnostics are in [accuracy.csv](accuracy.csv) and [common_support](common_support/a06_s000_d045/).

The reference is COLMAP/dataset proxy. APE/RPE measure agreement with that proxy, not independent-GT absolute error.

## Backend audit and claim boundary

`vins_node` and `libvins_lib.so` retain the frozen hashes `4e91d8ac...f4278` and `373a598c...71e8`. The three new YAML files are byte-identical to each other. Against the frozen A06 KLT YAML, all 37 material lines are identical; only the non-algorithmic `output_path` differs. See [backend_config_audit.csv](backend_config_audit.csv).

Supported conclusion:

> The old XFeat regressions on A06/H07 were caused by accepted online-seed bursts evicting an equal number of KLT mirror tracks under the 350-feature cap. `lineage_early_seed_noharm_v4` removes that path: on the two complete counterexamples it preserves active XFeat candidate generation while producing a byte-identical KLT backend input, and it passes three fixed-backend A06 replays.

Not supported:

- universal trajectory non-inferiority whenever learned sidecars genuinely occupy vacant slots;
- a learned-feature accuracy improvement from the safe profile in this batch, because no real trigger frame had vacant mirror capacity;
- centimetre-level or independent-GT accuracy;
- pooling this new frontend epoch with the frozen v3 supplement.

For paper experiments, use `lineage_early_seed_noharm_v4` as the conservative `proposed_safe` profile. Keep any replacement-capable `contribution_sparse` profile separately labeled and do not call it no-harm.
