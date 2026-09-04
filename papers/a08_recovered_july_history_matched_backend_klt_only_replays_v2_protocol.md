# A08 recovered-July history-matched KLT-only backend replays v2

Status: **frozen protocol only; execution lock absent; no backend item started**.

This is a separate five-repeat diversion made necessary by the terminal XFeat
frontend failure.  It does not amend or unlock the original interleaved 5+5
backend campaign, does not accept the XFeat fallback, and does not make a
learned-feature accuracy claim.

## 1. Immutable frontend authority and exclusion

The sole accepted backend input is the accepted KLT attempt002 receipt:

- `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/frontends_v1/klt_attempt002_export_receipt_v1.json`
- 363,673 bytes; SHA-256
  `69a857307f088e58ea18abbb6c25cd2069b7b15783fc2d17548e1fb001c4d2b8`
- `status=PASS_FRONTEND_EXPORT_ACCEPTED`, `stage=klt`.

The runner must independently reopen and validate that receipt and its three
accepted output identities before a lock can be built or verified.

XFeat is excluded, not accepted.  Its terminal authority is:

- failure receipt: 4,017 bytes, SHA-256
  `15eaad3e5b02f54b4f141db416e9b1db868bea15fcb66fe8bee11318765df22c`,
  with `FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT`,
  `FEATURE_POINT_COUNT_RANGE`, and `vins_or_accuracy_executed=false`;
- process-start claim: 149,433 bytes, SHA-256
  `a8d0828f9117c077b0bcef80b60d945478f6f2856d1dbe66bab43311d2698707`;
- supervisor log: 11,417 bytes, SHA-256
  `23fc5398f991e04d6050005be4ed8c909e7ee6b98609abfc09c8cb4b522decb0`;
- independent forensic note:
  `papers/a08_xfeat_attempt002_terminal_forensic_audit_v1.md`, 3,695 bytes,
  SHA-256 `4087a9cded9617e20c4f8e383bc4280c1a1c1cafe5d9fd49fbaa9fb2005bbf5a`.

The method-native probe's `frontend_metrics.csv` is frozen bytewise and must
show exactly one `exported_features>350` row: zero-based row 3 / source frame
7, `num_features=356`, `exported_features=352`, two exported learned XFeat
points, and `export_source_histogram=gftt:11;klt:339;xfeat_confirmed:2`.
The probe bag, metrics, and camera configuration are all identity-bound.

The selected `klt_safe_fallback` bag, metrics, and camera configuration are
also identity-bound, and each content identity must equal the corresponding
independently accepted KLT artifact.  This equality is exclusion evidence:
the fallback is **not** an accepted XFeat frontend, is **not** an input to this
campaign, and provides **no** learned-feature contribution.

Every resolved authority and execution lock must expose the exact boundary:

```text
excluded_xfeat.disposition=NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED
excluded_xfeat.accepted_receipt_present=false
excluded_xfeat.backend_launched_count=0
excluded_xfeat.learning_contribution_claim_permitted=false
```

XFeat system accuracy is therefore `NA`.  This campaign measures only KLT
backend repeat stability; by itself it cannot support an XFeat/learned-frontend
contribution claim or a KLT/XFeat/HFNet three-arm ranking.  Its sealed KLT
results may later serve as the control in a separately frozen two-arm
HFNet-versus-KLT evaluator.

## 2. Separation from the original 5+5 campaign

The original lock
`papers/a08_recovered_july_history_matched_backend_replays_v1_execution_lock.json`
must remain absent.  All original `KLT_R01/XFEAT_R01/.../KLT_R05/XFEAT_R05`
output, workspace, and runtime paths must remain absent.  The v2 lock binds
this fail-closed diversion gate and becomes invalid if that old campaign is
touched.

The independent v2 authorities are:

- protocol: this file;
- runner:
  `scripts/run_a08_recovered_july_history_matched_backend_klt_only_replays_v2.py`;
- KLT-only guard:
  `scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v2.sh`;
- lock:
  `papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_execution_lock.json`;
- output root:
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_replays_v2`;
- runtime root:
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/runtime/backend_klt_only_replays_v2`.

The v2 supervisor reuses the reviewed v1 one-shot backend engine and FD guard
only after exact bootstrap identity checks.  The inherited runner is 84,455
bytes with SHA-256
`4ca198cd678ba5df2e2b82a0468cbca3c23fbc5608302019d6540775ca58d3a0`;
the inherited FD guard is 8,704 bytes with SHA-256
`8740c0e4166e51050af287a05c67821f94a932a11f91d14c7e90059310244bcb`.
Their v1 protocol is also identity-bound.  These inherited files remain
unchanged and gain no v2 output authority outside the separately frozen lock.

No path, token, or receipt in this protocol authorizes or modifies the
original campaign or any frozen frontend artifact.

## 3. Fixed five-item schedule

The only order is:

```text
KLT_R01, KLT_R02, KLT_R03, KLT_R04, KLT_R05
```

Each item has a fresh output directory, ROS home/log directory, tag, workspace
symlink, fresh user namespace, and fresh loopback-only network namespace on
internal port 11981.  `VINS_MULTIPLE_THREAD=0`; BLAS/OpenMP thread counts are
one.  The method argument is always exactly `klt`.

The delegated backend is strict replay-only: the accepted KLT bag is opened
and hash-checked by the inherited FD guard, raw reconstruction and frontend
export switches remain disabled, and the delegated shell receives inherited
`/proc/self/fd` paths.  The v2 wrapper rejects every XFeat, probe, fallback,
or non-KLT input/path before delegation.

## 4. One-shot control and integrity latch

The v2 execution lock is created only with
`A08_BUILD_KLT_ONLY_BACKEND_REPLAYS_V2_LOCK_AFTER_TERMINAL_XFEAT_FAILURE`.
Item tokens are
`A08_KLT_ONLY_BACKEND_REPLAYS_V2_RUN_KLT_R01_EXACTLY_ONCE` through
`..._R05_EXACTLY_ONCE`.

For each item, an exclusive process-start claim consumes its allowance before
the single supervisor `Popen`.  Automatic retries and replacement repeats are
forbidden.  A scientific/backend failure publishes
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT`; later predeclared KLT items may
continue only if execution integrity passes.  Authority drift, unstable
claim/workspace, missing boundary manifests, evidence-tree mutation, or
incomplete owned-process cleanup irreversibly latches integrity failure and
blocks later items.

Each terminal file is named `formal_run_receipt_v2.json` and uses schema
`aqua-fe-a08-recovered-july-backend-klt-only-replay-receipt-v2`.

## 5. Current non-execution state

Creating this protocol, guard, runner, and process-free tests does not build
the v2 lock and does not launch ROS, VINS-Fusion, an exporter, or HFNet.  A
future operator must first pass read-only preflight, separately authorize the
lock, then authorize each item in the fixed order.
