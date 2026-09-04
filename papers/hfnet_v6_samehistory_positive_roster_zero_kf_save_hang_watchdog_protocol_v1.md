# HFNet-v6 same-history roster prospective zero-KF save-hang watchdog protocol v1

Frozen: 2026-08-29 (Asia/Shanghai)

## Scope and non-retroactivity

This protocol adds an external liveness supervisor only for the nine v2
attempts that were still pristine after `a05_3300_3700` had been consumed:

1. `a07_10800_11200`
2. `a08_4500_4660`
3. `a09_6000_6200`
4. `fjord1_s83_d10`
5. `mclab1_s60_d15`
6. `cirs_s575_d30`
7. `cirs_s900_d30`
8. `a02_7600_8000`
9. `mclab2_s110_d10`

It is not retrospective.  No watchdog receipt is fabricated for
`a05_3300_3700`, and that case is not rerun.  Its existing v2 runner result
remains the sole canonical runability adjudication for that consumed attempt.

The supervisor does not edit or replace the frozen runner, HFNet binary, case
specifications, prepared manifests, accuracy seal, cache adjudication, logs,
trajectories, or runner results.  It launches exactly one invocation of the
existing v2 runner.  The original runner retains the only HFNet `Popen`, the
resource gate, the global GPU lock, the start-once claim, timeout behavior,
post-audit, and terminal result publication.

## Prospective authority

- v2 runner: `scripts/run_hfnet_v6_samehistory_positive_roster_v2.py`, 7,639
  bytes, SHA-256
  `ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb`;
- watchdog:
  `scripts/run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py`,
  35,087 bytes, SHA-256
  `a85c6620fb16bb3c2525e654342aa22ab816684030d41bc598ead752fc399b71`;
- synthetic tests:
  `scripts/tests/test_run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py`,
  23,476 bytes, SHA-256
  `6921b6834c53cb6f056bfb4bcbf221fc78bfcac5b7dc81ac3cae48656ca7c276`;
- frozen v2 roster pointer: 5,296 bytes, SHA-256
  `f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1`;
- frozen accuracy prefreeze seal: 98,877 bytes, SHA-256
  `67f2ae286d0e0e3f19a7b490711318e9f7b059c12949e3efe297bbbe5151c6b5`.

The watchdog validates the pointer, seal, selected case specification,
prepared manifest, v2 runner, and HFNet binary before starting the runner.  It
rejects `a05_3300_3700`, any case outside the fixed nine, aliases, drift, or an
existing watchdog receipt before any process start.

The one-shot authorization token is read from a non-echoing terminal prompt
or standard input.  It is delivered to an in-memory `runpy` invocation over an
anonymous pipe.  The raw token is never placed in an OS command line,
environment variable, watchdog receipt, or watchdog log.  Child discovery
does not search for or depend on the token.  The Python wrapper/bootstrap
process names are not among the frozen runner's forbidden SLAM/ROS process
names, so the wrapper does not alter the resource-gate decision.

## The only signal-authorizing condition

The fixed grace is exactly 30 seconds and is not a command-line option.  Every
condition below must remain continuously true for the complete grace:

1. an exact `Shutdown` line precedes the applicable `Saving trajectory to
   <canonical result/trajectory.txt>` line;
2. the subsequent atlas declaration reports `N >= 1` maps;
3. exactly the complete map-ID set `0..N-1` is reported, with no missing or
   duplicate row;
4. every reported row says `Map i has 0 KFs`;
5. the canonical `result/trajectory.txt` is absent as both file and symlink;
6. no `End of saving trajectory to ...` line has appeared.

If any condition becomes false, the grace resets.  A clean save, a trajectory
appearing during the grace, any nonzero keyframe count, an incomplete or
ambiguous atlas report, a different hang, or ordinary runner exit never
authorizes a watchdog signal.

The prospective target must be the unique direct child of the one runner
process and must match the prepared launch in all of: PPid, Linux process
start-time ticks, resolved executable, and complete argv.  Discovery opens a
Linux pidfd and then repeats the identity check.  Immediately before signaling
the same four fields are checked again.  The only permitted action is one
`SIGTERM` delivered through that pidfd.  There is no process-group signal,
`SIGKILL`, second signal, retry, or signal to another process.  Immediately
after delivery the PID state is audited as either the same exact child still
visible, the exact child gone, or an identity change; no further action is
taken.  The supervisor then waits for and explicitly reaps the runner.

## Receipt and scientific meaning

Each invocation publishes exactly one no-clobber roster-level receipt outside
all attempt directories:

`/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/samehistory_old_positive_roster_v2/_zero_kf_save_hang_watchdog_v1/<case_id>.json`

The schema is
`aqua-fe-hfnet-v6-zero-kf-save-hang-watchdog-receipt-v1`.  Publication uses a
same-filesystem temporary file, file `fsync`, hard-link no-replace, and parent
directory `fsync`.

Normal receipt statuses are:

- `SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_SAVE_HANG`; or
- `PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL`.

Any monitor, anonymous-pipe, or runner-reap error produces
`WATCHDOG_SUPERVISION_ERROR_FAIL_CLOSED` and a nonzero supervisor exit.  A
downstream adjudicator may accept a normal watchdog receipt only when
`execution.runner_reaped` is true and `observations.monitoring_errors` is the
empty list, in addition to checking the exact receipt and authority identities.

The receipt is operational evidence, not a replacement runability result.  A
confirmed zero-KF save hang remains a scientific runability **FAIL**, accuracy
is **NA**, and it cannot authorize ranking.  The frozen v2 runner's terminal
`run_result.json` remains canonical.  A passive receipt likewise does not
assert scientific PASS; it only proves that this watchdog sent no signal.

The watchdog never retries.  Once its receipt exists, a second watchdog launch
for that case is rejected before runner start.  The runner's permanent
start-once boundary independently continues to prohibit a second HFNet attempt.
