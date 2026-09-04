# A08 HFNet-vs-KLT-only common-support analysis v2

Status: **IMPLEMENTED; EXECUTION AUTHORITY EXISTS ONLY WHEN THE INDEPENDENT
STATIC DESIGN-FREEZE JSON EXISTS AND PASSES THE RUNNER'S LIVE READ-ONLY AUDIT;
NO BACKEND V2 RESULT, DYNAMIC ANALYSIS LOCK, OR APE/RPE MAY BE OPENED BEFORE
THAT FREEZE.**

This is an additive, development-only two-arm analysis.  It does not repair or
replace the failed three-arm campaign.  The original backend v1 and three-arm
analysis v1 are permanently gate-closed.  XFeat remains
`NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED` and is never supplied to
VINS-Fusion or to the numeric evaluator.

## 1. Evidence boundary and permitted claim

The A08 sequence/window was selected after historical frontend outcomes were
known.  Source frames `4500..4660` are the historical learned-plus-KLT positive
window; `4000..4660` is a support extension selected after HFNet runability was
known.  Results are outcome-selected, support-extended development diagnostics,
not held-out or confirmatory evidence.  They cannot establish cross-dataset
superiority or statistical significance.  Five technical backend repetitions
are not five independent samples.  The AQUALOC COLMAP/depth-scale trajectory is
an image-derived reference proxy, not independent ground truth.

The allowed numeric claim is only a same-window comparison between the sealed
external HFNet trajectory and vanilla VINS-Fusion driven by the independently
accepted KLT frontend export.  KLT is summarized over all valid planned repeats.
No XFeat or learned-injection contribution may be claimed from this campaign.

## 2. XFeat exclusion is evidence, not an arm

The exclusion authority is
`papers/a08_xfeat_attempt002_terminal_forensic_audit_v1.md`, 3,695 bytes,
SHA-256
`4087a9cded9617e20c4f8e383bc4280c1a1c1cafe5d9fd49fbaa9fb2005bbf5a`.
It binds the terminal failure receipt
`frontends_v1/xfeat_attempt002_export_failure_v1.json`, 4,017 bytes, SHA-256
`15eaad3e5b02f54b4f141db416e9b1db868bea15fcb66fe8bee11318765df22c`,
with status `FAILED_NO_AUTOMATIC_RETRY`, qualified status
`FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT`, and error
`FEATURE_POINT_COUNT_RANGE`.  It also establishes:

- the accepted XFeat receipt is absent;
- no VINS or accuracy process was executed by the failed frontend attempt;
- one probe message contained 352 points, violating the frozen maximum 350;
- the method-native final `klt_safe_fallback` bag, metrics, and camera YAML are
  byte-identical to the independently accepted KLT control;
- the fallback is not an accepted XFeat arm and cannot evidence learned-feature
  contribution.

All five original XFeat backend slots are retained in the ten-slot disposition
table as `NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED`, with
`backend_launched=false`, no trajectory, no replacement, and all metrics `NA`.
XFeat is absent from the joint mask, evo arm set, medians, and ranking.

## 3. Three result-visibility boundaries

The transitions are separate and no-replace:

1. Static design freeze.  Before the KLT-only backend execution lock or any of
   its five terminal receipts exists, `freeze-design` binds this protocol,
   runner, process-free tests, numeric evaluator/core, epoch adapter, shared
   helper library, KLT-only backend protocol/runner, evo executable identities
   and version, support inputs, accepted KLT frontend receipt, XFeat exclusion,
   exact grid, gates, population rules, and audit rules.  It neither loads a
   trajectory nor computes accuracy.
2. Dynamic analysis lock.  Only after all five KLT backend allowances have
   terminal receipts does `build-lock` call the backend v2 runner's own
   `resolve_frontend_bindings`, `verify_lock`, and `prior_receipt` deep helpers.
   It freezes terminal dispositions and accepted trajectory identities without
   interpolation, alignment, evo, APE, or RPE.
3. One-shot analysis.  `run` first publishes a durable external claim, then
   consumes one allowance with zero retry and zero replacement.

If a backend result appears before a valid static freeze, the design is late and
the campaign blocks.  A final dynamic lock cannot cure a late or drifting static
design.  The old ten-item backend v1 lock, old three-arm analysis lock, and old
three-arm result directory must remain absent.

Canonical KLT-only backend authority:

```text
root:     /mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_replays_v2
items:    KLT_R01, KLT_R02, KLT_R03, KLT_R04, KLT_R05
lock:     /home/ma/AQUA-FE_WS/papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_execution_lock.json
receipt:  each item/formal_run_receipt_v2.json
```

The analysis dynamically imports the frozen backend runner and fails closed if
its interface, paths, item order, v2 schemas, lock status, or live authority
drifts.  It never degrades to trusting a JSON self-digest.  Every terminal
receipt must pass the backend helper's current namespace, replay-only FD guard,
claim, command/environment, workspace, process-drain, artifact-audit, evidence
tree, and identity checks.

## 4. Backend population and failure semantics

KLT has `planned_count=5`.  Every R01--R05 disposition is reported.
`PASS_BACKEND_REPLAY_ACCEPTED` is the only disposition admitted to the joint
numeric evaluator.  Its identity-bound `vins_output/vio.csv` is used as
`world_T_body`.  A terminal `FAILED_BACKEND_REPLAY_NO_REPLACEMENT` with execution
integrity `PASS` is a scientific failure: the planned repeat remains `NA`, is
not replaced, and supplies no trajectory.  Inclusion is decided from terminal
disposition before accuracy is visible.

Any missing or changed receipt, claimed-but-unterminated allowance, backend lock
drift, execution-integrity failure, namespace/FD-guard failure, changed evidence
tree, changed workspace binding, or changed accepted trajectory is an integrity
failure and blocks dynamic lock construction or invalidates analysis.  It is not
converted to a numeric penalty.

`valid_count` is the number of accepted planned KLT repeats.  The KLT headline
is the coordinate-wise median of all six metrics over every valid planned
repeat on the one joint mask.  No best, minimum, maximum, cherry-picked repeat,
replacement, or outcome-dependent subset is permitted.  If `valid_count=0`,
the population gate closes and both formal HFNet and KLT metrics are `NA`.

## 5. Sealed support, grid, mask, and pose convention

The support receipt is
`/mnt/data/AQUA-FE_WS/experiments/a08_hfnet_history_matched_support_extension_v1/evaluation_inputs/support_preparation_receipt_v1.json`,
5,286 bytes, SHA-256
`2fa2150604e2b81ea93556b9c82f4a15ae394429cb7fc51c96d31977a37e37d3`.
It binds the 5,082-byte reference TUM (SHA-256
`25ccba084e5b5edd5651d24bec2bf753b119bc8de7174d36b870855680086682`),
the 70,021-byte HFNet `world_T_body` bridge (SHA-256
`be8a6bd278ad0222adeaf869a50c710d791c6eb5bee6db1afd57e1678ca9b04c`),
and the shared 415-byte full-precision `body_T_cam0` (SHA-256
`a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1`).

The exact timestamp authority is integer nanoseconds:

```text
start_ns = 1542885161111831216
end_ns   = 1542885194106222672
grid_ns  = start_ns + i * 1000000000, i = 0..32
```

There are exactly 33 grid points.  The last is
`1542885193111831216 ns`; the inclusive bound is 994,391,456 ns later and does
not create a 34th point.  A separate JSON artifact preserves all 33 integers.

Reference interpolation has maximum bracket 2.5 s; estimate interpolation has
maximum bracket 0.25 s.  Extrapolation and fitted time offsets are forbidden;
all offsets are zero.  The mask is constructed once as:

```text
reference valid
AND HFNet valid
AND every accepted KLT repeat valid
```

No pairwise, repeat-specific, arm-specific, or post-accuracy mask is allowed.
An accepted sparse repeat may reduce support and cannot be discarded after its
accuracy is seen.

Every trajectory uses the same full-precision transform
`world_T_cam0 = world_T_body * body_T_cam0`.  Each arm is independently aligned
to the reference with proper fixed-scale SE(3).  Reflection, Sim(3), scale
fitting, fitted time offsets, and identity substitution for the HFNet extrinsic
are forbidden.

## 6. Metrics, gates, evo, and NA invariant

The six required finite, nonnegative metrics for HFNet and every accepted KLT
repeat are translational APE RMSE/median/max and exact-one-second positional RPE
RMSE/median/max.  Matched pose and RPE-pair counts must equal the shared support
counts.  RPE is the translation error between one-second position increments in
the aligned global frame within a contiguous common-mask segment; it is not
full orientation-aware SE(3) RPE.

The denominator is always 33.  The common-support gate requires all of:

```text
joint matched poses >= 30
joint common span >= 10 s
joint matched / 33 >= 0.70
exact one-second RPE pairs >= 10
```

Ranking additionally requires `KLT valid_count >= 1`, complete six-metric rows,
and an evo cross-check for the exact same arm set and RPE pairs.  The runner
recomputes actual primary/evo RMSE differences; it does not trust reported diff
fields.  All values must be finite and nonnegative, segment pair counts must sum
to the primary count, pair-weighted segmented RPE is recomputed, and both RMSE
differences must be at most `1e-5 m`.

If any support, population, completeness, evo, or execution-integrity gate
fails, every formal HFNet/KLT per-run and aggregate metric is `NA`.  XFeat is
always `NA`.  Raw numeric files, when present, carry the explicit label
`DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING`; they cannot be quoted as a formal ranking.

## 7. Transactional terminalization and deep audit

The start claim is outside the result directory.  All later actions, including
claim identity capture and staging creation, are inside the terminalization
boundary.  Artifacts are assembled in a hidden same-filesystem directory and
the complete terminal directory is published with Linux
`renameat2(RENAME_NOREPLACE)`.  Individual JSON publication uses a hard-link
no-replace commit.  A competing owner is never overwritten.

Raw CSV writer failure, partial evo output, post-authority drift, claim drift,
or any other post-claim infrastructure fault creates an all-`NA` failure
terminal.  Partial numeric/evo trees remain explicitly uncommitted evidence;
they are never published as a normal self-inconsistent terminal.  A
claimed-without-terminal, output-without-lock, invalid-kind, or partial terminal
state is blocked in preflight and fails audit; it is never treated as a
successfully consumed allowance.

The read-only terminal audit reopens the dynamic lock through live backend deep
helpers; checks the claim, receipt, output allowlist and every identity; verifies
all 33 exact grid integers; reruns the primary evaluator from locked trajectories;
requires byte-equivalent canonical primary JSON; validates every grid CSV
timestamp/0-or-1 validity/common-mask/segment row; deterministically regenerates
the metrics and ten-slot CSVs; recomputes evo differences and segment semantics;
rebuilds medians and formal gates; and enforces the global `NA` invariant.

No command in this analysis runner launches ROS or VINS-Fusion.  This protocol
does not authorize `freeze-design`, `build-lock`, or `run` until their explicit
preconditions and authorization token are satisfied.
