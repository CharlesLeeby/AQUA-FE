# A09 same-history four-arm common-support analysis v1

Status: `FROZEN_AWAITING_EXECUTION_LOCK_PUBLICATION`.

Date: 2026-08-26 (Asia/Shanghai)

## Question and scope

On the fixed AQUALOC archaeology A09 feed `0..4400` and score window
`4000..4400`, what descriptive fixed-scale SE(3) APE and exact 1 s translation
RPE are obtained on one joint 1 Hz common-support mask by, in this fixed order:

1. `VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT`;
2. `EXTERNAL_KLT_FINALONLINE_BACKBONE`;
3. `AQUAFE_FINALONLINE_XFEAT_LINEAGE`; and
4. `HFNET_SLAM_WARMSTART`?

This is analysis of four already-published trajectories. The runner must not
start ROS, rosbag replay, VINS, either frontend, or HFNet. It may call only the
frozen common-support evaluator, exactly once and without retry. One selected
window and one trajectory per arm do not support a confidence interval,
significance test, ranking, winner, superiority claim, or isolated causal claim
about direct learned action in score frames.

## Frozen direct inputs

The future execution lock must bind the final runner and this protocol plus
every direct input below by exact absolute path, byte count, and SHA-256.

| Input | Bytes | SHA-256 |
|---|---:|---|
| Raw A09 bag | 1,187,038,470 | `a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97` |
| Vanilla accepted receipt | 41,435 | `18bd02c2a268306a9154e60dffbac326b9320fc55084e62be01bdc0fa500474d` |
| KLT accepted receipt | 44,131 | `8c12b5701309bd79652aa723951fa6f8c866135f744c813c3092ec658c1775fb` |
| AQUA-FE accepted receipt | 44,279 | `34833858bddf210de373a8b3fc9c36be78b02168fbeda2274070382d82a89302` |
| Vanilla trajectory | 227,239 | `e7f8e06536bd788edc60dd13add6c0d371a41d0351eaa29a7f5c3d1cde9afc2d` |
| KLT trajectory | 228,066 | `edb75ed45449761c0a79cc72ad2084eb8e45f0508be9aa90641e84361e549b43` |
| AQUA-FE trajectory | 228,064 | `92089ada8e065dbb86940f8a5cc96f1850e8a76c4ac42a10b8a45b9a7d8053dd` |
| HFNet source-stamp-canonical trajectory | 42,105 | `2b5bd98de228b13c33a79e40b0462d51db57e3280449230d3e1f33f369072d5d` |
| Vanilla config | 990 | `eafd7e6f22e573c4e0d7b5e36f2550938029456fc75ad55bd741c1d000016ff7` |
| KLT config | 986 | `b928b31af629bddd9ff677953c185778a2172a0f946fce71bfa1e08b5d879178` |
| AQUA-FE config | 1,015 | `4b58c2e422fcce4dfecfc6ffbb227fe979e641923a378bbaa227f0baa22894ed` |
| HFNet `body_T_cam0` config | 415 | `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1` |
| HFNet lossless-bridge receipt | 5,037 | `d03e5cd87ec8e936b2160f1bef43fe8ae3a79f4b53540e9baf24b0e809371483` |
| HFNet canonical receipt | 5,632 | `dff07d76e1d363846e31a693017df58e580a4482a076507dd1036372c1ce22b4` |
| Epoch-ns evaluator wrapper | 5,447 | `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91` |
| Common-support evaluator | 27,933 | `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` |
| Evaluator core | 27,945 | `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635` |
| evo 1.31.1 `evo_ape` entrypoint | 213 | `6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15` |
| evo 1.31.1 `evo_rpe` entrypoint | 213 | `9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1` |

Each of the three backend receipts is checked separately. It must remain
`TERMINAL_PROCESS_RC0` and `ACCEPTED`, with one Popen, RC 0, no timeout,
reaped/empty owned process state, artifact PASS, execution-integrity PASS,
score-usability PASS, sealed-in-place PASS, and exact binding of its trajectory
and evaluation config. The score endpoints in every receipt must be exactly
`1542888946038630384` and `1542888966034698672` ns.

The runner reads the already-published canonical HFNet CSV directly, together
with both bridge receipts. The canonical receipt must bind the actual canonical
CSV, actual stage-1 receipt, and stage-1 output identity. Both receipts must
bind the same tool and authorities; their shared seven-pose-token stream hash
must be `3f93d76ed106b8dc2b0edb5fee1cdecc79a0fbb15d7fc8219669a9f59dd7847d`.
The canonical CSV must contain 401 strictly increasing finite eight-column
rows with the exact score endpoints above. This analysis performs no further
timestamp rewriting or pose transformation.

## Analysis execution lock

The only lock path is:

`papers/a09_samehistory_fourarm_common_support_v1_execution_lock.json`

It is created only after the runner and protocol are final. It must be
canonical JSON with schema
`aqua-fe-a09-samehistory-fourarm-common-support-execution-lock-v1`, status
`LOCKED_BEFORE_ANALYSIS`, and exact `runner`, `protocol`, `inputs`, and
`protocol_constants` fields expected by the runner. `check` rehashes every
input and verifies that the lock binds the current runner, protocol, and full
input identity map. `run` repeats this before the evaluator and after it
returns. Editing either file or any input after locking is a hard failure.

This frozen protocol does not itself create the lock or authorize evaluator
execution. Lock publication and execution require a separate action.

## Fixed evaluator protocol

- Exact inclusive score interval:
  `[1542888946038630384, 1542888966034698672]` ns, passed as
  `1542888946.038630384` and `1542888966.034698672` seconds.
- Reference: raw bag topic `/aqualoc/colmap_gt`; reference time offset is 0.
- Nominal reference/estimate rates are 1/10 Hz; all four arm time offsets are 0.
- Uniform evaluation grid: 1 Hz, exactly 20 anchored points.
- Fixed method order: the four arms listed above; never metric-sorted.
- One logical joint mask: the intersection of reference validity and all four
  arm-validity masks. Each arm must report the same matched and RPE-pair count.
- Maximum reference interpolation bracket: 2.5 s.
- Maximum estimate interpolation bracket: 0.25 s.
- Per-arm alignment: one independent proper rigid SE(3), scale fixed to 1.
  Sim(3), fitted scale, fitted time offset, snapping, and result-informed
  alignment choices are forbidden.
- APE: translation RMSE, median, and max. The frozen formal gate requires 30
  poses and 10 s, so `ape_valid` must remain false on the 20-point grid.
- RPE: aligned-global-frame positional delta at exactly 1 s, with RMSE,
  median, and max; at least 10 joint pairs are required.
- Common-support gate: at least 15/20, `matched/20 >= 0.70`, and conservative
  `matched/21 >= 0.70`.
- evo version 1.31.1 independently cross-checks each arm on the fixed joint
  mask. Per-arm APE and RPE RMSE disagreement must be at most `1e-5 m`.

APE values may be retained only as explicitly gate-closed diagnostics. Passing
RPE support authorizes only a development-only descriptive result.

## Exactly-once execution and output

The fixed final output root is:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_fourarm_common_support_v1`

The runner also reserves these fixed siblings under the same experiments root:

- claim: `a09_samehistory_fourarm_common_support_v1.process_start_claim.json`;
- terminal receipt: `a09_samehistory_fourarm_common_support_v1.terminal_receipt.json`.

`check` is read-only and requires exactly the output root, claim, and terminal
receipt to be absent. Before any subprocess call, `run` first publishes the
claim with `O_CREAT|O_EXCL`, fsyncs the file and parent directory, and thereby
permanently consumes the one evaluator allowance. It then makes one atomic
`os.mkdir(OUTPUT)` call to reserve the final output namespace. An existing
file, symlink, empty directory, or nonempty directory is a hard failure and is
never adopted or modified. The successful reservation's device and inode are
recorded and rechecked before and after critical writes. Only after reservation
does the runner call `subprocess.run` exactly once, with no retry branch. The
evaluator's internal pinned evo cross-checks belong to that one invocation.

There is no staging directory, directory rename, cleanup, resume, or retry.
The evaluator and analysis writer generate evidence directly inside the unique
reserved output directory. A failure retains that directory and appends a
no-replace `failure.json` when the reservation identity still matches; it never
deletes partial scientific evidence. On success, `result_manifest.json` is
written, every regular file and directory in the complete output tree is
fsynced, and the exact tree is hashed again including `result_manifest.json`.
The external terminal receipt is then published with `O_CREAT|O_EXCL`; only a
terminal receipt with status `COMPLETE` is the completion commit marker. It
binds the durable claim, execution lock, output reservation identity, sole
evaluator call/RC, and the exact complete tree. Failure receipts are terminal
but are not completion markers. This sealed-in-place reservation protocol is
used because the `/mnt/data` fuseblk filesystem does not provide the required
`RENAME_NOREPLACE` semantics; projected permission bits are not an integrity
basis.

## Commands in the current state

Static inspection only:

```bash
/usr/bin/python3.8 scripts/run_a09_samehistory_fourarm_common_support_v1.py --help
```

After a separately reviewed lock exists, the read-only check is:

```bash
/usr/bin/python3.8 scripts/run_a09_samehistory_fourarm_common_support_v1.py check
```

The `run` command is not executed during this scaffold-and-static-test step.
