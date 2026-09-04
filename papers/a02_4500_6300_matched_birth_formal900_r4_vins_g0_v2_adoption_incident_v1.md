# A02 formal900 r4 VINS G0 runtime-probe stderr incident and v2 adoption

Status: additive infrastructure incident/adoption authority. This record does
not contain, recompute, compare, or authorize access to VIO trajectory metric
values.

## Retained v1 fact pattern

The v1 runtime-probe launch intent exists as a single-link regular file at
`papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v1.json`.
Its fixed identity is SHA-256
`d433ce9e5be085efc8854d60b2e34279c9f8e5dc3953e400e89751b53fdcba0a`,
3626 bytes, mode `0644`. It records exactly one authorized process start and a
no-retry policy. The v1 freeze, probe failure receipt, result directory, post
seal, and publication staging/intent/closeout leaves are absent.

The missing failure receipt is itself part of the incident. It must not be
invented after the fact. The probe's stdout and stderr bytes were held only in
the terminated parent process and are no longer recoverable; this incident
does not claim their content, length, or hash. The terminal diagnostic
classification `runtime probe emitted stderr` is an operator-observed,
non-durable diagnostic, not a substitute for the missing stream bytes.

## Infrastructure false-negative

In the retained v1 governor, the representative child can exit RC 0 and its
captured receipt can return from `_capture_runtime_closure`. The empty-stderr
gate is evaluated later by `_validate_freeze_runtime_static`, during the
freeze transaction. The failure-receipt backfill in `_capture_runtime_closure`
therefore does not cover this later validation branch. A nonempty stderr stream
can consequently leave the durable launch intent while writing neither a
freeze nor a failure receipt. This is an evidence-retention/control-flow defect,
not evidence about either scientific arm.

## Narrow v2 authorization

The only permitted continuation is the separately pinned
`scripts/govern_matched_birth_r4_vins_g0_v2.py`. It may use only the exact v2
freeze, runtime-probe intent/failure, r2 result, post-seal, and job-hash-derived
r2 publication sibling namespace named by the machine record. It must adopt
the old intent as a terminal consumed v1 attempt, must not retry or modify the
v1 namespace, and must repair the stderr gate plus the fail-closed
intent/success-closeout state machine before its first process start.

Any visible v2 probe-intent leaf without its exact runtime-probe success
closeout consumes the namespace and forbids retry or continuation. Later v2
actions require the exact freeze, intent, and success closeout together. A
failure receipt is best-effort additive evidence only when the parent observes
the failure and its write/fsync succeeds; it is never the authority for retry.
No receipt is promised for `SIGKILL`, `SIGSTOP`, process crash, power loss,
kernel or storage failure, signal-API failure, or failure-receipt write/fsync
failure. In every such observable surviving-filesystem case, the intent leaf
alone still fails closed and forbids another process start.

No detector export, feature bag, VINS replay, old evaluator invocation, or old
formal namespace may be rerun. No scientific input, threshold, support rule,
alignment, metric, arm order, or interpretation is changed. Any v2 evidence is
additive post-incident exploratory evidence and cannot retroactively make v1 a
successful freeze.

## Publication

The machine incident is built only by
`scripts/build_a02_matched_birth_r4_vins_g0_probe_stderr_incident_v1.py`.
Its optional `write-once` action holds the old intent, the v1 code authorities,
this human record, the exact successor governor, and all required absences
through publication. The complete JSON is written to an anonymous held inode,
set to mode `0444`, file-fsync'd, linked under a fixed hidden name, and
directory-fsync'd. Only after all held authorities, absences, and publication
sibling sets pass their final checks is that exact inode atomically renamed to
the canonical name with `RENAME_NOREPLACE`; this rename is the adoption commit
point. A fixed hidden pending leaf consumes the builder namespace after an
interrupted pre-commit. As elsewhere in this workspace governance, an active
same-UID namespace adversary is outside the trust boundary.
