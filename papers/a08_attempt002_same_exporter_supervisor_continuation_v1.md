# A08 KLT attempt002 same-exporter supervisor continuation v1

Status: **FROZEN AFTER PROCESS ANCHOR, BEFORE EXPORT TERMINAL AUDIT.**

## Scope

The formal KLT `attempt002` exporter was started exactly once by the frozen
attempt002 runner.  Its enclosing tool command had an inadvertently short
1,200 s wall-time limit.  At that limit the original Python supervisor and its
output summarizer were terminated, while the already independent exporter
session continued.  This note does not authorize an exporter restart, a third
KLT attempt, VINS, accuracy evaluation, or a change to any frontend parameter.

The only permitted continuation is to wait for the exact already-running
exporter session to end and then perform the frozen artifact audit.  Because
the original Python supervisor cannot observe the terminal return code after
it is terminated, any accepted receipt must store `return_code: null`, disclose
that loss, require the shell's ordered `set -euo pipefail` success sentinels,
and pass the complete frozen bag/metrics/environment/input audit.

## Existing exporter identity

The additive anchor was written at `2026-08-28T07:54:54+00:00`, before the
outer deadline.  It records boot ID, `/proc` start ticks, PPID, PGID, SID,
command line, executable, working directory, and standard-file targets for the
whole process chain.  In particular:

- original Python supervisor: PID `2478166`, start ticks `51639451`;
- export session leader: PID/PGID/SID `2478925`, start ticks `51651095`;
- inner dataset shell: PID `2478926`, start ticks `51651096`;
- exporter: PID `2478973`, start ticks `51651122`;
- the three export-session processes write to the original
  `klt_attempt002_supervisor_process.log`;
- the exporter command is the claimed pure-KLT command on the frozen A08 raw
  bag, with `--method klt`, `--every-n 2`, `--frame-offset 1`, and
  `--process-skipped-frames`;
- `additional_exporter_popen_count` is `0` and `exporter_restarted` is false.

Anchor identity:

- `klt_attempt002_same_exporter_continuation_anchor_v1.json`: 12,247 bytes,
  SHA-256 `5af0cac668adb9ac051dc0bfb68e93ded76ad043ea98cf358f77f253b2081bf8`.

The outer deadline occurred at approximately `2026-08-28T07:56:53+00:00`.
After it, a post-deadline read-only process snapshot recorded session leader
`2478925` reparented without changing its start ticks, PGID, or SID; exporter
`2478973` continued without changing identity.  The snapshot is
`papers/a08_attempt002_post_tool_deadline_process_snapshot_v1.json`, 2,646
bytes, SHA-256
`2feed6adc052adefa73415efdd5f1ae304ae2ad22e3441cf234e2d5b3761c11a`.
This is recorded continuation of the same exporter invocation, not an
algorithm retry.

## Continuation-monitor lineage

The first audit-only monitor launch exited before writing an anchor because
system Python rejected `Path.stat(follow_symlinks=False)`.  It did not call an
exporter, touch the running exporter, run VINS, or compute accuracy.  Its
terminal evidence is preserved:

- `klt_attempt002_same_exporter_continuation_crash_v1.json`: 397 bytes,
  SHA-256 `227535830c2b9b57b7637adc33cb0f7f5cf069ab4e117cf0fc8a227844daa242`;
- `klt_attempt002_same_exporter_continuation_watch_v1.log`: 790 bytes,
  SHA-256 `0c088daf7ab113a8965efddd22768578f9de383048f721c2872ff0555b6bfd84`;
- classification: pre-anchor audit-monitor Python compatibility failure;
- cumulative audit-monitor launch count including the failed and corrected
  launches: `2`;
- exporter invocation count throughout: `1`.

The documented compatibility correction replaced that unsupported monitor
call; no exporter command or frontend parameter was changed.  The active
continuation script is 17,110 bytes, SHA-256
`5b2f086dc3331d02c771be8497048918085a02e8fdd606bb0dbf7cca72cf5bd0`;
the anchor pins this exact identity.  The script cannot start an exporter.  It
must no-op if the original receipt appears, stop if an original failure
appears, and otherwise audit only after the original supervisor is gone and
the exact export session has naturally ended.

## Terminal rule

Acceptance requires all of the following:

1. the exact anchored exporter session ends without any replacement process;
2. the original shell log contains, in order, the exact `RUN_VINS=0` skip,
   `run_dir`, `raw_bag`, and `play_bag` success lines;
3. the frozen raw contract, feature-bag audit, metrics audit, copied IMU/GT
   streams, execution tree, runtime environment, and fixed inputs all pass;
4. the receipt explicitly labels the tool-supervisor interruption and does not
   claim an observed return code or benchmark runtime;
5. no VINS, HFNet, APE, or RPE computation occurs in this stage.

If an artifact audit fails, the KLT arm is terminal `NA`; no new exporter run
is allowed.  An audit-only continuation does not turn an exporter failure into
an accuracy value.
