# XFeat persistent-ID repair (M2) — 2026-08-08

## Outcome

The original pure pairwise XFeat arm `M` remains unchanged as a valid failure
observation: all 20 P07 windows produced empty VINS trajectories.  The failure
was not repaired by relaxing VINS thresholds.  Instead, an additive arm,
`M2_XFeatPersistent_v2`, repairs the frontend-to-backend identity contract.

Two fixed 10-second probes now both initialize VINS and produce non-empty
trajectories under the same backend settings used by their corresponding P07
comparisons:

| probe | export frames | warm long-4 min / median / max | lag-10 pose-gate pairs | VINS initialization | output poses | short-window APE / RPE (m) |
|---|---:|---:|---:|---|---:|---:|
| AQUALOC archaeology `A02:0005` | 98 | 200 / 242 / 282 | 21 | PASS | 82 | 7.734678 / 4.700785 |
| NTNU `fjord_6:0001` | 100 | 99 / 151 / 197 | 10 | PASS | 80 | 19.477723 / 11.585075 |

The short-window APE/RPE values are diagnostics only.  They are not formal
accuracy endpoints and are not used to replace the original M results.

The same fixed implementation was then evaluated on the complete 45-second
windows.  Both trajectories initialized and both strict common-support G0
evaluations were valid, but M2 accuracy was orders of magnitude worse than B1:

| full window | export/checker | M2 initialization / poses | common support | B1 APE / RPE RMSE (m) | M2 APE / RPE RMSE (m) |
|---|---|---:|---:|---:|---:|
| AQUALOC archaeology `A02:0005` | 450 frames / PASS | PASS / 393 | 39/45, 86.67% | 0.441820 / 0.044751 | 138.588486 / 13.968817 |
| NTNU `fjord_6:0001` | 450 frames / PASS | PASS / 430 | 429/451, 95.12% | 0.133959 / 0.039282 | 492.846198 / 67.439196 |

For both rows, `ape_valid=true` and `rpe_valid=true`; the large M2 errors are
therefore not empty-trajectory placeholders or invalid-support artifacts.  The
supported repair claim is deliberately narrow: on these two prespecified full
windows, persistent IDs removed the observed no-initialization failure, but this
M2 association rule did **not** recover usable localization accuracy.  It must
not replace M or be expanded to the full 20-window endpoint as currently
implemented.

For each comparison, B1 and M2 used numerically identical backend settings and
the same camera calibration; their generated VINS YAML differs only in
`output_path` and, for NTNU, equivalent numeric spellings such as `1` versus
`1.0`.  The replayed IMU streams are identical, as is the embedded A02 GT
stream.  The large error difference is therefore not attributable to a changed
backend configuration or reference input.

## Root cause

The original M bags contained many feature observations but almost no persistent
landmark identities:

- across the 20 P07 windows, adjacent-frame ID retention had a median of about
  7.6% for M versus about 95.0% for B1;
- no M identity survived 11 published frames;
- the median number of tracks with at least four consecutive observations was
  zero;
- all 20 M logs repeatedly reported insufficient features/parallax and none
  reached initialization.

The XFeat adapter assigned confidence 1 to every pairwise match.  The pairwise
tracker then truncated the arbitrarily ordered match list before attempting ID
continuation and used an 8-pixel greedy association.  Re-detection therefore
replaced most IDs at every frame even when there were hundreds of valid matches.

Schema, normalized coordinates, timestamps, IMU/GT payloads, camera calibration,
VINS configuration, and VINS binary were checked pairwise and did not explain
the failure.

## Additive repair

- `uw_frontend/tracking/pairwise_matcher_tracker.py`
  - keeps legacy behavior as the default;
  - adds `continuity_first_v2`;
  - performs global one-to-one continuation over all NCC-valid candidates before
    applying the 350-feature cap;
  - ranks continued/older tracks before births, with native confidence and NCC
    as deterministic tie-breakers.
- `uw_frontend/matchers/xfeat_adapter.py`
  - keeps the legacy all-ones confidence mode as the default;
  - adds native descriptor cosine confidence;
  - caches the shared middle-frame sparse XFeat result without changing emitted
    measurements.
- `uw_frontend/configs/experiments/isj_p05_xfeat_persistent_v2.yaml`
  - selects the two additive behaviors while inheriting the original M config.
- `scripts/check_xfeat_persistent_v2.py`
  - is a read-only export gate;
  - requires unique IDs, at least 40 long-4 tracks after warmup, and at least one
    lag-10 pair satisfying the VINS correspondence, parallax, and pose-inlier
    conditions;
  - returns 0 for PASS, 1 for scientific FAIL, and 2 for input/runtime ERROR.

No B1 coordinates or trajectories are copied, no per-window threshold is tuned,
and no VINS initialization threshold is relaxed.

## Evidence paths

### A02 post-optimization probe

- export:
  `logs/aqualoc_archaeo_vins/external_xfeat_every2_repairdiag_p07_m2_a02_0005_s10_postopt_r1`
- VINS replay:
  `logs/aqualoc_archaeo_vins/external_xfeat_every2_repairdiag_p07_m2_a02_0005_s10_postopt_vins_r2`
- feature-bag SHA-256:
  `e6a3919b265659fcb9a9754f54a4438ce081d53e6fcd821a56cca42742680517`

The post-optimization export and the prior M2 cache probe have identical
timestamps, points, pixels, normalized coordinates, velocities, and identity
partition.  Their 5,042 IDs are related by a conflict-free global bijection;
only three newly allocated numeric labels differ.  Maximum absolute differences
are `5.96e-08` for quality and `1.19e-07` for sigma.

The comparison artifact is
`logs/aqualoc_archaeo_vins/external_xfeat_every2_repairprobe_p07_a02_m2_persistent_v2_cache_r1/features.bag`,
with SHA-256
`2349d7343551271a8b9c15f4a2a5a885b8d54e563083b33b275bbf1e9c5a6180`.

The excluded `...postopt_vins_r1` directory is an orchestration-only failed
probe: rosbag waited on a GT topic with no subscriber, no messages were replayed,
and its trajectory stayed empty.  The corrected `r2` replay disabled that wait
and reused exactly the already-passed feature bag.

### A02 full-window result

- final export:
  `logs/aqualoc_archaeo_vins/external_xfeat_every2_p07_m2_full_aqualoc_archaeology_a02_0005_export_r2`
- VINS replay:
  `logs/aqualoc_archaeo_vins/external_xfeat_every2_p07_m2_full_aqualoc_archaeology_a02_0005_vins_r2`
- G0 common-support result:
  `papers/p07_b1_vs_m2_common_support/aqualoc_archaeology_A02_0005_r2/common_support_summary.json`
- feature-bag SHA-256:
  `70e36a7c0c39946a6764f09c4e8fbdd1025e300f86d43c2564a31e4b1971bdba`
- G0 summary SHA-256:
  `e0b225bf6d6a806b5c93fd4b958eba19f41b05cf456f4ac918a1e2173e5419f5`
- evo cross-check SHA-256:
  `0af764490457f390b23a65e11bae3c6b513397c1ba6b6524f9f9b1790dd76924`

The export contains exactly 450 feature frames and 157,500 observations.  Its
feature header and record stamps match the original P07 B1 and M bags exactly.
The checker passed with long-4 min/median/max `157/222.5/283` and 134 qualifying
lag-10 pose pairs.  VINS initialized and wrote 393 poses, but recorded 25 linear
solver failures.  The strict G0 mask contains 39 matched samples over 38 seconds
(`common_coverage=0.866667`, 38 RPE pairs).  B1 and M2 are both valid on that
same mask; their APE/RPE RMSE values are respectively
`0.4418201083/0.0447510538 m` and `138.5884861351/13.9688173573 m`.

The earlier `...export_r1` is retained only as a boundary-truncated diagnostic
(448 frames) and is excluded from the full-window result.

### NTNU cross-dataset probe

- export:
  `logs/ntnu_vins/external_xfeat_every2_repairdiag_p07_m2_ntnu_fjord_6_0001_s45_d10_export_r1`
- VINS replay:
  `logs/ntnu_vins/external_xfeat_every2_repairdiag_p07_m2_ntnu_fjord_6_0001_s45_d10_vins_r1`
- feature-bag SHA-256:
  `64cb9d60255c40da1fc3002c8140996fb659c24ec558884288ecede80d0d9a9e`

### NTNU full-window result

- final export:
  `logs/ntnu_vins/external_xfeat_every2_p07_m2_full_ntnu_fjord_6_0001_export_r1`
- VINS replay:
  `logs/ntnu_vins/external_xfeat_every2_p07_m2_full_ntnu_fjord_6_0001_vins_r1`
- G0 common-support result:
  `papers/p07_b1_vs_m2_common_support/ntnu_fjord_6_0001_r1/common_support_summary.json`
- feature-bag SHA-256:
  `3ade0435425d156aba458e993a103d44c15e17fd3ff90ae4510300ec5f943004`
- G0 summary SHA-256:
  `ab5aaf6108d87e8d626ae47f3064e1fcbf3a03b09e2ad235e09f94c417c0f892`
- evo cross-check SHA-256:
  `06a4caa82c5263723adbc053b19bd13dd336fbaf78dc47a33a5a4a55b876e506`

The export contains exactly 450 feature frames and 157,500 observations.  Its
header and record stamps match the original P07 B1 and M bags item-for-item.
The checker passed with long-4 min/median/max `62/156/263` and 90 qualifying
lag-10 pose pairs.  VINS initialized once and wrote 430 poses without a solver
failure or restart.  The strict G0 mask contains 429 matched samples over 42.8
seconds (`common_coverage=0.951220`, 419 RPE pairs).  B1 and M2 are both valid on
that same mask; their APE/RPE RMSE values are respectively
`0.1339587813/0.0392820087 m` and `492.8461977016/67.4391955592 m`.  The evo
cross-checks for both datasets agree with the primary evaluator to within
`4.41e-7 m`.

## Verification

The combined regression suite passes 17/17 tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.tests.test_xfeat_persistent_v2 \
  scripts.tests.test_check_xfeat_persistent_v2
```

The tests include the original cap-before-association failure, exact-endpoint
association, low-NCC ID stealing, rejection/backfill and `next_id`, NCC cap
tie-breaking, native confidence, shared-endpoint cache reuse, and checker PASS/
FAIL/ERROR behavior.

Frozen source hashes for these probes:

| file | SHA-256 |
|---|---|
| `pairwise_matcher_tracker.py` | `74ed8ebafbe97ead3b1e0c61a5e5d50a731825803352e1073f2ebe676fe94857` |
| `xfeat_adapter.py` | `919b6b365548f2439b13eb01a24bd3e476de543dfcfa28b77baa09a7692fe345` |
| `isj_p05_xfeat_persistent_v2.yaml` | `a9db0639904f02b30cf901bf1a9d5d5f9ce74c1df5b2fb7fe85414b1c22cb075` |
| `check_xfeat_persistent_v2.py` | `9ecdbac16e34e9b8d59fc43b6e258bf63a696bd04f846a7aa1b592b0df4c184a` |

## Decision after full-window validation

Do not run this M2 across all 20 P07 windows.  The two prespecified
cross-dataset full-window checks agree on the important boundary:

1. on the two prespecified full windows, persistent identity was sufficient to
   remove the observed no-initialization failure;
2. it is not sufficient to make the pairwise matches geometrically trustworthy;
3. the resulting trajectories can be valid under the support protocol yet be
   orders of magnitude less accurate than B1.

The original M 20/20 empty-trajectory rows remain the primary result for the
original arm.  M2 is retained as a diagnostic sensitivity result.  Any next
repair must target geometric association/outlier consistency, pass the same
export-only persistence and pose gates without per-window tuning, and then
repeat these two representative full-window comparisons before broader
execution.
