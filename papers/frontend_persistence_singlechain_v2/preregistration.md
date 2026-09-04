# Persistence single-chain v2 preregistration

Locked before generating any `persistence_singlechain_v2` feature bag.

## Motivation fixed from v1 evidence

The v1 failure is associated with an online-observable structural discontinuity, not a post-hoc accuracy threshold:

- positive `a09_6000_6800` replaced 1/96, 1/102 and 1/106 GFTT births and published one XFeat ID for three selected frames;
- positive `a06_s045_d045` replaced at most 6/69 births and contained one three-frame core XFeat chain;
- failed `a06_s000_d045` replaced 5/5, 15/15 and 7/7 GFTT births, leaving zero GFTT births on all active frames, while publishing 16 XFeat IDs, nine of them for one selected frame only;
- late-event `h07_s000_d050` must remain exact KLT input.

Hypothesis H2: the a06 failure is caused by a dense, identity-churning startup burst and complete classical-birth starvation. A learned contribution intended as a seed chain must be identity-persistent and perturbation-bounded.

## Frozen v2 rule

Profile: `lineage_early_seed_singlechain_v2`.

The complete v1 contract remains unchanged except for one additional structural restriction:

1. At most one XFeat export ID may be committed during selected feature frames 0–4.
2. The first sidecar that passes the existing confirmed-XFeat, GFTT-target and raw-age-advantage rule is selected by the existing deterministic age/quality/NCC/FB order.
3. Once committed, only that exact sidecar ID may replace one GFTT on later eligible frames. No replacement ID switch is allowed inside the startup horizon.
4. If the committed sidecar is absent or no eligible GFTT exists, publish the independent KLT mirror unchanged for that frame.
5. Maximum displacement is one GFTT per selected frame; `source=klt` remains ineligible. Therefore at least four of five GFTT births survive even in the v1 worst frame, and all but one survive when more births are available.
6. The 350 cap, horizon 0–4, minimum raw-age advantage 2, all upstream candidate gates, quality mapping, preprocessing, timestamps and backend remain frozen.

This is a structural cap, not a threshold sweep. No alternative max-chain count, ratio, horizon or score threshold will be tried after seeing v2 results.

## Locked development/regression windows

- positive retention: `a09_6000_6800`, `a06_s045_d045`;
- failure repair: `a06_s000_d045`;
- late-event exact-input anchor: `h07_s000_d050`.

These are known-outcome development windows. They cannot establish unseen-window generalization.

## Frontend gates

- expected feature messages: 400/450/450/500;
- timestamps exactly equal to frozen KLT;
- maximum 350 observations;
- no learned output after selected frame 4;
- no more than one learned ID in the whole startup burst and no more than one learned observation per frame;
- every victim is `source=gftt`; no `source=klt` deletion;
- a09 must retain its three-frame XFeat pixel chain;
- h07 must be byte-identical to KLT.

All four windows are reported; a zero learned output is valid and is not silently removed.

## Fixed backend and decisions

Use the same VINS-Fusion-origin binaries as v1, no recompilation, and the same per-window normalized YAML. Three replays per distinct bag; exact KLT input may reuse the frozen KLT repeats.

Runability and accuracy contracts remain: 30 poses / 10 s / 70% coverage, all-arm common support, independent fixed-scale proper SE(3), 1 Hz common grid, 1 s translation RPE, explicit diagnostic Sim(3), and evo cross-check. COLMAP is a proxy, not independent GT.

Development decision:

- `REPAIR_PASS`: a06_s000 has 3/3 runability, no scale-diverged repeat, and both fixed-scale APE/RPE medians lie within the frozen KLT repeat envelope. Before backend execution, “scale-diverged” is operationalized as fixed-scale APE greater than 10 times the frozen KLT median or fitted Sim(3) scale below 0.1; the KLT repeat envelope means the closed observed min–max interval reported by the frozen three KLT replays;
- `POSITIVE_RETAINED`: each positive window retains 3/3 runability and both fixed-scale medians below KLT;
- `NO_HARM_INPUT`: h07 bag is byte-identical to KLT;
- otherwise `FAIL` with the complete repeat range reported.

No current v1 artifact or historical result is overwritten.

## Pre-implementation hashes and storage check

- exporter: `1eba04642284edb77df7b39aa036207d3c53fa7725dd90ea46a76d93c7fc0e08`
- profile environment: `d3ac80307cc49c99b85b3c2b4e78d957e18bc8fbcc99381910953b6f019a11ba`
- AQUALOC archaeology runner: `15deafffa75416b7ce69faf5af3d03da6c08bf3a4721c18402da4dcc3d43036d`
- AQUALOC harbor runner: `8431467e1bdc7dc056e49c063602f0b34aad9ad704ee5f878e7b9e6919c1e73c`
- frontend contract tests: `4e11edf6612cc9167d889567df67859eade877accfdc1cf4d0042b017764a1a2`
- frozen frontend YAML: `6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3`
- VINS node: `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278`
- libvins: `373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8`
- root disk free before implementation: approximately 4.5 GiB; projected new output below 0.25 GiB.
- `/mnt/data` remained 100% full and is read-only evidence/input for this experiment.
