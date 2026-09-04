# A08 recovered-July joint common-support analysis v1

Status: **PERMANENTLY GATE-CLOSED; XFEAT FAILED ITS FROZEN FRONTEND
STRUCTURAL GATE; BACKEND V1 AND THREE-ARM ANALYSIS V1 MUST NEVER BE
LAUNCHED; FORMAL THREE-ARM RESULT IS
`NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED`.**

This document preserves the preplanned three-arm design and its audit lessons,
but no longer authorizes any accuracy comparison.  The sole XFeat attempt002
failed the frozen point-count contract; no accepted XFeat frontend receipt
exists.  Therefore the original ten-item backend campaign cannot build its
lock, none of its ten replays may launch, and this three-arm analysis may
neither build a dynamic lock nor run.  It does not authorize a replay, retry,
new frontend export, replacement arm, or analysis attempt.

The read-only forensic authority is
`papers/a08_xfeat_attempt002_terminal_forensic_audit_v1.md` (3,695 bytes,
SHA-256
`4087a9cded9617e20c4f8e383bc4280c1a1c1cafe5d9fd49fbaa9fb2005bbf5a`).
It binds the terminal XFeat failure receipt and documents that the selected
final `klt_safe_fallback` backend inputs are byte-identical to the accepted KLT
inputs.  They cannot be relabeled as XFeat or used to claim a learned-feature
contribution.

## 1. Evidence boundary

The sequence and score support were selected after historical outcomes were
known.  Source frames `4500..4660` are the historical XFeat-plus-KLT positive
window; source frames `4000..4660` are a support extension selected after
HFNet runability was known.  The comparison is therefore an outcome-selected,
support-extended development diagnostic.  It is not held-out or confirmatory
evidence, does not establish cross-dataset superiority or statistical
significance, and does not turn five technical repeats into five independent
data samples.  The AQUALOC COLMAP/depth-scale trajectory is an image-derived
reference proxy, not independent ground truth.

The earlier v1 design freeze is retained only as a superseded pre-result review
artifact.  No replacement v1 freeze or dynamic v1 analysis lock may be built.
The runner's `preflight` and `audit` commands report the permanent closure;
both `build-lock` and `run` fail closed before reading numeric inputs.

Any later HFNet-vs-KLT-only work is an additive v2 campaign with independently
named protocol, runner, static design freeze, dynamic lock, backend authority,
output root, and receipts.  It must bind the XFeat structural failure solely as
excluded evidence and keep its result `NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED`.

Sections 2--7 below preserve the abandoned preplanned three-arm contract for
forensic review only.  Their words "must", "may", and "runner" describe that
counterfactual design; they confer no execution authority after this permanent
closure.

## 2. Sealed support inputs

The support authority is
`/mnt/data/AQUA-FE_WS/experiments/a08_hfnet_history_matched_support_extension_v1/evaluation_inputs/support_preparation_receipt_v1.json`,
schema `aqua-fe-a08-hfnet-history-matched-support-extension-preparation-v1`,
status `PASS_SUPPORT_ONLY_PREPARATION_NO_ACCURACY`, 5,286 bytes, SHA-256
`2fa2150604e2b81ea93556b9c82f4a15ae394429cb7fc51c96d31977a37e37d3`.
It binds:

- reference TUM, 5,082 bytes, SHA-256
  `25ccba084e5b5edd5651d24bec2bf753b119bc8de7174d36b870855680086682`;
- HFNet `world_T_body` bridge CSV, 70,021 bytes, SHA-256
  `be8a6bd278ad0222adeaf869a50c710d791c6eb5bee6db1afd57e1678ca9b04c`;
- shared `body_T_cam0`, 415 bytes, SHA-256
  `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1`.

The bridge repairs only the at-most-112 ns float serialization displacement by
one-to-one association with frozen camera timestamps.  There is no fitted
time offset.  HFNet remains `world_T_body`; it is not assigned an identity
extrinsic.

## 3. Backend population and failure semantics

The analysis lock must bind the final backend execution lock and all ten
terminal receipts in this exact order:

```text
KLT_R01, XFEAT_R01, KLT_R02, XFEAT_R02, KLT_R03, XFEAT_R03,
KLT_R04, XFEAT_R04, KLT_R05, XFEAT_R05
```

Every terminal receipt must have execution integrity `PASS`, a clear
irreversible fault latch, zero retries, no replacement, and the exact backend
lock identity.  Any missing receipt, claimed-but-unterminated allowance,
execution-integrity failure, changed receipt, changed accepted trajectory, or
backend-lock drift blocks lock construction or invalidates the formal
analysis.  It is not converted to a numeric penalty.  The analysis authority
must reuse the backend supervisor's own `verify_lock` and `prior_receipt`
deep audits; merely checking the backend lock's self-digest or a subset of
receipt fields is insufficient.  The deep audit revalidates frontend/static
authority, namespace and replay-only FD-guard manifests, generated settings,
evidence-tree closure, workspace binding, process cleanup, and current artifact
identities for all ten planned items.

`PASS_BACKEND_REPLAY_ACCEPTED` is the only disposition admitted to the joint
numeric evaluator.  Its identity-bound `vins_output/vio.csv` is used exactly
once and remains `world_T_body`.  A terminal
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT` whose execution integrity is `PASS` is
a retained scientific failure: that planned repeat is reported as `NA`, is
not replaced, and is not used as a trajectory.  Inclusion is decided solely
from the terminal disposition before accuracy is visible, never from APE/RPE.

KLT and XFeat each have `planned_count=5`.  All R01--R05 dispositions are
reported.  `valid_count` is the count of accepted planned repeats.  Arm-level
APE/RPE summaries are coordinate-wise medians over all accepted planned
repeats on the one joint mask.  No minimum/maximum/best repeat is selected as
the headline result.

The analysis lock also reads the identity-bound XFeat frontend receipt and
freezes its method-native arbitration profile.  If the profile is
`klt_safe_fallback`, the arm label is **XFeat arbitration system, method-native
KLT safe fallback**.  In that case `learning_contribution_claim_permitted` is
false; no trajectory outcome may be attributed to learned-feature injection.

## 4. Exact grid and one joint mask

The score bounds are exact integers:

```text
start_ns = 1542885161111831216
end_ns   = 1542885194106222672
```

The formal grid is `start_ns + i * 1,000,000,000 ns` for integer
`i=0..32`, exactly 33 points.  The last grid point is
`1542885193111831216 ns`; the inclusive window upper bound lies
`994391456 ns` later and does not create a 34th point.  The runner writes the
33 integer timestamps as separate evidence.  Float-formatted JSON, CSV, or evo
TUM timestamps are not the sole timestamp authority.

Before alignment, the reference, HFNet, and every accepted KLT/XFeat repeat
are resampled to this grid.  Reference interpolation has a frozen maximum
bracket of `2.5 s`; estimate interpolation has `0.25 s`.  Extrapolation and
time-offset fitting are forbidden, and all configured offsets equal zero.
The mask is constructed once as:

```text
reference valid
AND HFNet valid
AND every accepted KLT repeat valid
AND every accepted XFeat repeat valid
```

No repeat-specific, pairwise, or arm-specific mask may be substituted.  A
sparsely supported accepted repeat is allowed to reduce the common mask; it
cannot be discarded after accuracy is visible.

## 5. Pose convention and metrics

Every arm is transformed with the same full-precision sealed matrix:

```text
world_T_cam0 = world_T_body * body_T_cam0
```

Generated per-replay camera files are provenance artifacts only and are not
used as separate numeric transforms.  On the joint mask, each trajectory is
independently aligned to the reference with a proper fixed-scale SE(3)
rotation and translation.  Reflection, Sim(3), scale fitting, and fitted time
offsets are forbidden.

APE is translational APE.  RPE is the translation error between exact
one-second position increments in the aligned global frame, with both grid
points valid and in the same contiguous joint-mask segment.  It is not a full
orientation-aware SE(3) RPE.

The primary numeric implementation is the frozen combination of
`scripts/evaluate_vins_common_support.py` and
`scripts/trajectory_eval_core.py`.  The exact grid is supplied from integer
nanoseconds rather than regenerated from float64.  The analysis lock binds
both sources, the additive epoch adapter, this runner and protocol, and the
resolved `evo_ape`/`evo_rpe` entrypoints plus the installed evo version.

## 6. Gates and NA policy

The fixed denominator is 33.  The common-support gate requires all of:

```text
joint matched poses >= 30
joint common span >= 10 s
joint matched / 33 >= 0.70
exact one-second RPE pairs >= 10
```

A three-arm ranking additionally requires at least one accepted planned repeat
for KLT and at least one for XFeat, and a passing evo cross-check.  The evo arm
set and RPE pair count must exactly equal the primary evaluator's; its APE and
segmented-RPE RMSE must differ from the primary result by at most `1e-5 m` for
every admitted arm.  evo is an implementation cross-check, not a second mask
or a tuning opportunity.
The runner recomputes both absolute differences from the primary and evo RMSE
values rather than trusting evo-summary difference fields.  All involved
metrics must be finite and nonnegative; the reported differences must equal
the recomputed differences; segment pair counts must sum to the primary exact
one-second pair count; and the pair-weighted segmented RPE RMSE is recomputed.

If any common-support condition, population condition, or evo condition
fails, every formal HFNet/KLT/XFeat ranking metric is `NA`.  Raw primary
diagnostics may be retained under an explicitly non-ranking key, but cannot be
quoted as the formal comparison.  An analysis execution error likewise
consumes the one allowance and closes formal ranking; it does not authorize a
retry.

## 7. Required outputs and claims

Before accuracy is computed, the runner publishes a durable start claim at a
path outside the result directory.  All numeric and textual artifacts are
then assembled in a same-filesystem hidden staging directory.  A complete
terminal receipt and an all-`NA` integrity fallback can be prepared there;
the terminal directory is made visible only by Linux `renameat2` with
`RENAME_NOREPLACE`.  A competing destination is never overwritten.  A
post-claim infrastructure exception triggers a separately staged terminal
failure receipt and all-`NA` formal summary; any partial numeric staging tree
is retained only as explicitly uncommitted diagnostic evidence.
Every post-claim action, including claim identity capture and creation of the
primary staging directory, is inside this terminalization boundary.  A
claimed-without-terminal or otherwise malformed consumed state is `BLOCKED` in
preflight and `FAIL` in audit, never a successful already-consumed state.

The terminal receipt binds the analysis lock, external start claim, exact integer-ns
grid, raw common-support summary and grid audit, per-repeat disposition table,
formal gate/median summary, evo audit and artifacts when invoked, and the
complete regular-file output tree.  It records pre/post authority identity and
keeps execution integrity separate from scientific/ranking availability.
The formal summary is not interpretable without its matching terminal receipt.
Raw primary JSON/grid/metrics artifacts carry an explicit sidecar boundary
`DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING`; only the receipt-bound formal summary is
the ranking authority.  A partial grid/metrics writer failure is not committed
as a normal all-`NA` terminal: it goes through the failure staging path and the
partial tree remains explicitly uncommitted.

The read-only audit revalidates the claim, lock, output allowlist and identities,
integer grid, joint arm set, pose/time policy, planned-repeat binding, metric
completeness, evo cross-check, medians, and the all-`NA` invariant.
It reruns the primary evaluator from the identity-locked reference, shared
extrinsic, HFNet trajectory, and accepted repeat trajectories, and requires the
stored primary JSON to equal that recomputation.  It then checks every grid CSV
row against the recomputed timestamp/validity/common-mask/segment values and
requires both numeric CSVs to equal deterministic regenerations from the
recomputed result.

Allowed conclusions remain limited to whether the external HFNet system and
history-matched controls were run and compared on this frozen development
support.  In particular, a method-native `klt_safe_fallback` result is evidence
about that arbitration system's fallback behavior, not evidence that XFeat
observations improved VINS-Fusion.
