# A09 same-history warm-start AQUA-FE v2 protocol

Status: **FROZEN FOR AQUA-FE V2 EXECUTION.**

The accepted KLT identities, the post-hoc KLT execution-strength addendum and
its auditor, and the identities of this runner, builder, and protocol are
frozen by `a09_samehistory_warmstart_v2_aquafe_execution_lock.json` before
launch.

## Scope and evidence boundary

This protocol runs only the learned AQUA-FE frontend on the already accepted
A09 KLT full-history export. It does not run VINS-Fusion or any SLAM backend.
Its accepted result is therefore a frontend artifact and learned-sidecar
contract result, not trajectory, APE/RPE, accuracy, speed, or paper evidence.
The user has explicitly allowed an ambient desktop/ToDesk process for this
development run; no runtime or throughput claim may be made from it.

## Immutable authority

The execution lock must pin every file in the runner's `STATIC_EXPECTED`
authority table, all six accepted KLT files, the immutable post-hoc KLT
execution-strength addendum, its auditor script, and the runner, builder, and
this protocol. It also freezes the exact child argv and the complete
allowlisted environment. Ambient `os.environ` is not inherited.

The v1 KLT receipt is not accepted as stronger evidence than it actually
contains. It waited for the session leader but did not continuously prove that
the process group and owned descendants were empty at leader exit; its
environment field recorded overrides rather than the complete effective
environment; and its claim was a plain write rather than durable exclusive
publication. Consequently it does not establish exactly-once execution,
durable claim publication, complete effective environment, or descendant
emptiness at the historical exit instant. A post-hoc addendum may record an
empty later process snapshot and external post-commit rehash, but cannot
retroactively create those missing guarantees.

The addendum must use schema
`aqua-fe-a09-samehistory-warmstart-klt-execution-strength-addendum-v1` and
status `PASS_POSTHOC_KLT_EXECUTION_STRENGTH_AUDIT`. It binds all six KLT files
by public identity, binds its auditor, records the canonical directory and
workspace-symlink inode relationship, and carries structured limitations. The
AQUA runner revalidates those bindings and limitations; it never treats the old
receipt's `process_group_waited_to_terminal` field as strong process-tree proof.

The runner independently resolves the full eight-file YAML `extends` chain,
recomputes the merged configuration digest, and requires the effective stock
XFeat configuration to be exactly:

```json
{"min_cossim":0.82,"repo_path":"external_tools/accelerated_features","semi_dense":false,"top_k":2048}
```

The merged-config SHA-256 is
`9ecd1329953d4b95ab38297e173cfed880616050469b81d547ab1094efc8aa69`;
the effective-XFeat-object SHA-256 is
`7ddbc0d1e640f92433d9f080343ab8987f1f3a7fbbfb12283ab969c700b8e107`.
The workspace `external_tools` path must remain the exact symlink to
`/mnt/data/AQUA-FE_WS/external_tools`, and the stock module and weight files are
pinned separately.

The safety implementation reused from the pinned A10 v3 supervisor is limited
to its fsync/atomic-publication, signal masking, subreaper, child identity, and
owned-process draining helpers. The AQUA-specific audits are implemented in the
new v2 runner and are not delegated to an unpinned wrapper.

## Freeze sequence (only after KLT acceptance)

1. The KLT addendum and its auditor have passed independent review, and this
   protocol is frozen with the exact status required by the lock builder.
2. Run the builder's `static-selftest`; it does not inspect A09 KLT artifacts.
3. Run `print-candidate`. This performs the receipt/addendum bindings and complete KLT
   artifact audit but does not write a lock.
4. Inspect the candidate. Then explicitly publish the canonical lock once:

```bash
/usr/bin/python3.8 scripts/build_a09_samehistory_warmstart_v2_aquafe_lock.py \
  write-lock \
  --output /home/ma/AQUA-FE_WS/papers/a09_samehistory_warmstart_v2_aquafe_execution_lock.json
```

The builder refuses an existing lock and refuses any noncanonical output path.
After publication it invokes the runner's full lock verifier.

## Preflight and lawful positive fixture

`preflight` rehashes every locked input, binds the KLT receipt to its four
recorded outputs, audits the complete raw/KLT history, and rejects any existing
AQUA canonical, stage, or failure directory. By default it also audits the
accepted A10 v3 output as a known-lawful positive fixture using the same strict
AQUA artifact validator. That fixture validates the validator; it is not an A09
outcome oracle and does not waive any A09 check.

The fixture must be a real directory (not a symlink) and must match the pinned
A10 receipt plus all three science outputs recorded by that receipt
(`stats.csv`, `sidecar.bag`, and `full_merged.bag`). The accepted base bag,
camera YAML, and raw image bag are pinned separately for independent replay of
the artifact audit.
The validator requires the A10 counts and timeline passed explicitly by
`selftest_a10_fixture`; success is reported only as
`PASS_KNOWN_LAWFUL_A10_FIXTURE`.

## One-shot execution and publication invariant

The runner obtains the shared frontend flock, repeats preflight, creates a new
private stage directory, and creates the canonical AQUA path as an absolute
symlink to that exact stage inode. It prepares only the allowlisted runtime
directories. Before the sole `Popen`, it durably publishes a read-only claim
with argv, environment, lock, input identities, and symlink/inode binding.
Publication of the claim consumes the only launch allowance; automatic retry
is forbidden.

The child starts in a new process session. The supervisor enables subreaping,
tracks direct-child identities, and requires the leader to be reaped, its
process group to be empty, and every owned descendant to be drained. A zero
leader return code is insufficient by itself.

Only four child/science/log artifacts plus the durable claim (five regular
files total) are allowed before the formal receipt: `full_merged.bag`,
`sidecar.bag`, `stats.csv`, `supervisor_process.log`, and
`process_start_claim_v2.json`. Empty runtime
directories are removed; any unexpected remaining file or directory fails
closed. After the science audit, all four files are made read-only and fsynced.
The canonical symlink is then removed and the same stage inode is renamed to
the canonical real directory. Every science artifact is re-opened and rehashed
after this directory commit, followed by a durable formal receipt and a final
rehash.

## Strict learned-output acceptance

The audit checks all 2,200 feature timestamps against the accepted KLT base and
requires exact IMU and ground-truth serialization equality. It validates the
complete `sensor_msgs/PointCloud` contract: type/MD5/header/record timestamp,
the exact 13-channel order and lengths, finite values, pixel bounds, normalized
coordinates, sigma-from-quality, source classes, ID namespaces, classical
prefix preservation, and the learned merged suffix/sidecar equality.

The CSV header and every row are checked. Timestamp spelling must equal the
producer expression `str(float(base.header.stamp.to_sec()))`, not merely a
numerically equivalent timestamp. Integer and float fields use canonical
grammars. Trigger reasons use the full ordered token grammar and are recomputed
from the thresholds and trigger budget. Selector sets use sorted, unique,
semicolon-separated canonical IDs; discovered/evaluated/activated/retired/
active/selected transitions are reconstructed across all rows. Each injected
observation must bind the selected ID, sidecar point, merged learned suffix,
remapped ID, and selector action. Summary counts and lineage-action constraints
must agree with the full-history evidence.

## Failure handling

Any post-claim failure is terminal for this attempt. The supervisor drains its
owned process tree, records a durable failure receipt where possible, verifies
the same stage/canonical inode invariant, and transitions the private stage or
committed directory to `aquafe_finalonline_failed_v2`. It never removes or
retargets a foreign canonical path and never retries automatically.

## Frozen commands

```bash
/usr/bin/python3.8 scripts/run_a09_samehistory_warmstart_v2_aquafe.py preflight
/usr/bin/python3.8 scripts/run_a09_samehistory_warmstart_v2_aquafe.py run
```

The first command is non-launching and does not modify experiment or KLT
artifacts; it may create/open and lock the supervisor flock if that coordination
file is absent. The runner disables Python bytecode writes. The second command
is authorized only after the lock is frozen, inspected, and accepted. No
command here authorizes deletion or modification of the accepted KLT
canonical path.
