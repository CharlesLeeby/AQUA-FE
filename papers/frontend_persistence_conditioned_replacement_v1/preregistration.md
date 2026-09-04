# Persistence-conditioned replacement v1 preregistration

Locked before the first `persistence_replace_v1` feature bag is generated.

## Status and purpose

This is an explicitly experimental contribution branch, not the default no-harm profile and not a rewrite of any historical result. Its purpose is to test whether an online, conservative birth-for-birth replacement can retain the old XFeat initialization benefit without reintroducing the v3 failure mode that evicted tracked KLT observations.

The four attribution windows are a development/regression set whose outcomes are already known. Results on them can establish mechanism preservation and regression removal, but not unseen-window generalization.

## Frozen frontend rule

Base profile: `lineage_early_seed_noharm_v4`, including the independent KLT mirror and all existing seed-chain candidate, confirmation, NCC, FB, microburst, quality mapping and 350-feature-cap settings.

New profile name: `lineage_early_seed_persistence_replace_v1`.

At the final mirror publication boundary:

1. Vacant capacity below 350 remains available to an already accepted sidecar without displacement.
2. At full capacity, replacement is permitted only for `xfeat_confirmed` sidecars during selected feature frames 0–4 inclusive. This horizon is the frozen three-frame early-seed microburst plus its observed startup allowance; it is fixed before execution and is not moved for a window.
3. A replacement sidecar must have raw tracker age at least two frames greater than its target.
4. The target must have source `gftt`. In the independent KLT mirror this denotes a same-frame birth; a source `klt` observation is never eligible, irrespective of its current score.
5. Eligible sidecars are ordered by age, frontend quality, NCC, FB and stable ID. Eligible GFTT targets are ordered from weakest frontend persistence score to strongest. Replacement is deterministic and one-for-one.
6. If any condition fails, the sidecar is dropped and the corresponding mirror observation is preserved exactly. The final cap remains 350 and duplicate IDs are forbidden.

No learned threshold, backend setting, measurement selection, quality mapping, camera/IMU timing, window boundary or evo setting may be changed after seeing results.

## Locked windows and comparisons

| window | role | known historical behavior |
|---|---|---|
| `a09_6000_6800` | positive mechanism regression | old shared-tracker seed converged; KLT diverged |
| `a06_s045_d045` | positive mechanism regression | old final-mirror replacement improved APE/RPE |
| `a06_s000_d045` | safety regression | old replacement worsened APE while slightly improving RPE |
| `h07_s000_d050` | late-event safety anchor | old late replacement worsened APE/RPE |

Frozen comparison inputs/results: pure KLT, historical v3 replacement, and no-harm v4. Historical bags and results are read-only.

## Phase A: implementation and unit contracts

- Legacy mode behavior must remain byte-for-byte unchanged under its existing tests.
- `preserve_classical_budget` v4 must remain unchanged and must still restore a full mirror at capacity.
- New mode must replace only `gftt`, never `klt`; enforce the age advantage and early horizon; use vacant capacity without deletion; restore mirror exactly when no replacement is eligible.
- All existing frontend unit tests plus new rule-specific tests must pass.

## Phase B: frontend-only experiment

Run all four windows once with the new profile, export-only, using the same raw/prepared input, `every_n=2`, frame phase, budget 350, `MEASUREMENT_SELECTION=0`, `VINS_SAFE_SOURCE_SELECTION=0`, preprocessing and `vins_safe` quality mapping as the frozen comparisons.

Frontend validity gates:

- 400/450/450/500 feature messages as applicable and the same timestamps as the frozen KLT arm;
- maximum feature count 350;
- every dropped classical observation is source `gftt` and age 1 at that frame;
- no learned publication after selected frame 4;
- h07 must be byte-identical to KLT because its only historical seed burst is late;
- all candidates and all pruning outcomes are reported; zero replacement is a valid negative result.

No failed frontend window is silently removed. Only windows passing these integrity gates may enter backend replay.

## Phase C: fixed-backend replay

For each distinct valid feature bag, run the same frozen VINS-Fusion-origin backend three times without recompiling or editing YAML. If a new bag is byte-identical to a frozen KLT bag, reuse the existing KLT three-repeat result as an exact-input counterfactual rather than rerunning it.

Runability remains primary. Accuracy uses the existing common-support construction, independent fixed-scale proper SE(3) alignment and 1 s RPE grid. Sim(3) is diagnostic and explicitly labeled. Reference trajectories are COLMAP/proxy, not independent GT.

Development-set decision labels:

- `WIN`: all repeats pass runability and both fixed-scale APE and RPE medians are below frozen KLT on the same common support.
- `MIXED`: runability passes and APE/RPE directions disagree.
- `NO_HARM_INPUT`: feature bag is byte-identical to KLT.
- `REGRESSION`: runability decreases, or both APE and RPE worsen outside the frozen KLT repeat range.

These labels do not establish generalization. A later unseen-window preregistration is required before a paper-level no-harm or superiority claim.

## Pre-execution hashes

- exporter before implementation: `14d4d657e04f305a9d649c326910c137ba4dfda184d8db84c04840bb4643361c`
- seed profile environment before implementation: `559ded41df50f8854f128f05b3cf0c9dc38bd7006bca54072010a66f19fa1ea7`
- frontend YAML: `6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3`

