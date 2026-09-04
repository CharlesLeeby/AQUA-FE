# A08 recovered-July history-matched backend replays v1

Status: **implemented, execution gate closed until both attempt002 frontend
receipts are accepted and a final execution lock is published**.

This protocol defines the ten VINS-Fusion replays that follow the A08
recovered-July KLT and XFeat export-only controls.  It does not authorize a
backend launch by itself.

## 1. Fixed population and order

There are exactly five predeclared repeats per arm.  The supervisor order is
fixed and interleaved:

```text
KLT_R01, XFEAT_R01, KLT_R02, XFEAT_R02, KLT_R03, XFEAT_R03,
KLT_R04, XFEAT_R04, KLT_R05, XFEAT_R05
```

Every item replays sequence 8 from source index 0 through 4660, with external
features at `every_n=2`.  KLT uses method `klt`; XFeat uses method
`hybrid_xfeat`.  The two arms differ only through their accepted feature-bag
lineage and the resulting method label.  Backend settings and replay history
are otherwise identical.

## 2. Late-bound frontend authority

The runner must not discover a bag by globbing a run directory or accept a
manual bag override.  It binds the two bags only from these receipts:

- `frontends_v1/klt_attempt002_export_receipt_v1.json`;
- `frontends_v1/xfeat_attempt002_export_receipt_v1.json`.

Both receipts must be regular, stable JSON files with schema
`aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1`, status
`PASS_FRONTEND_EXPORT_ACCEPTED`, the matching `stage`, one supervisor launch,
and zero automatic retries.  For KLT, the authority is
`artifact_audit.outputs`; for XFeat it is
`artifact_audit.final.outputs`.  The referenced `features.bag`,
`frontend_metrics.csv`, and `aqualoc_archaeo08_pinhole.yaml` must match their
recorded size and SHA-256 identities and remain inside the recovered-July
overlay's frontend run root.  The two camera files must have identical content.

The two receipts must also carry one identical `raw_contract`: 4,661 camera
messages, 46,631 IMU messages, 226 ground-truth messages, and the exact 2,330
strictly increasing every-second-camera feature timestamps.  Each accepted
feature bag must contain those 2,330 feature messages and byte-identical copied
IMU/GT stream digests.  Its first and last feature timestamps must equal the
raw contract.  Both receipts must bind the frozen raw bag, source archive, and
ground-truth identities, and the XFeat receipt must explicitly bind the exact
accepted KLT receipt identity used here.  These checks establish equal causal
history rather than merely equal filenames or camera calibration.

Until both receipts pass those checks, preflight returns `WAITING` or
`BLOCKED`, does not inspect a partly written bag, and does not create a lock.

## 3. Final lock boundary

The final lock is deliberately absent while either frontend receipt is
missing.  After both are accepted, the separately authorized `build-lock`
operation freezes:

- both receipt and output identities, including the two dynamic bag paths;
- the exact ten item contracts, environment maps, namespaces, and paths;
- the raw bag, source archive, ground truth, recovered overlay authorities,
  VINS binary, namespace entry, runner, protocol, safety supervisor source, and
  the transitive catkin `setup.sh`, `_setup_util.py`, marker, and profile-hook
  source set used by the frozen environment.

`preflight` and `audit` are read-only.  A launch additionally requires the
final lock, an item-specific authorization token, an unconsumed item, and all
earlier items to have a terminal receipt whose execution integrity is `PASS`.

## 4. Backend execution contract

Each item has one durable process-start claim and at most one supervisor
`Popen`.  The child command is:

```text
/usr/bin/unshare --user --map-root-user --net \
  /usr/bin/python3.8 scripts/enter_samehistory_backend_netns_v4.py \
  --output-dir ITEM_OUTPUT --formal-port 11981 \
  --host-network-namespace LOCKED_NETNS \
  --host-user-namespace LOCKED_USERNS -- \
  /usr/bin/bash WORKSPACE/scripts/run_a08_recovered_july_backend_replay_only_guard_v1.sh \
  aqualoc_archaeo 8 0 4660 METHOD 2
```

Thus every replay receives a fresh user namespace and fresh loopback-only
network namespace while retaining the same formal internal ROS port 11981.
The verified namespace entry must record its manifest before it execs the
backend.

The effective child environment is fully specified by the lock.  Required
values include:

```text
RUN_VINS=1
FORCE_RAW=0
FORCE_EXPORT=0
EXPORT_FEATURES=0
BACKEND_REPLAY_ONLY=0
VINS_MULTIPLE_THREAD=0
PLAY_RATE=1.0
WAIT_FOR_VINS_SUBSCRIBERS=1
ROSBAG_WAIT_FOR_SUBSCRIBERS=0
ROSBAG_PLAY_DELAY=3
POST_PLAY_SLEEP=8
AQUALOC_BODY_T_CAM0_MODE=imu_cam
VINS_TD=-0.053694112369382575
VINS_ESTIMATE_TD=0
VINS_MAX_SOLVER_TIME=0.04
VINS_MAX_NUM_ITERATIONS=8
PORT=11981
```

The legacy recovered-July shell's `BACKEND_REPLAY_ONLY=1` branch belongs to a
different P07 sealed-interpreter contract, so `0` is deliberate here.  It is
not the A08 replay-only authority: the separately hash-bound A08 guard below
opens and identity-checks every possible reconstruction/export input first,
keeps those descriptors alive, forces both export controls to zero, and gives
the delegated shell only the sealed data descriptors.  Hence neither legacy
fallback predicate can become true during the delegated call.

The replay-only guard opens and hashes the accepted feature bag, raw history
bag, source archive, ground truth, frontend metrics, and camera file before it
delegates.  It then replaces every data path visible to the recovered-July
shell with an inherited `/proc/self/fd/*` handle.  Therefore a source pathname
being removed or replaced after validation cannot trigger raw reconstruction
or feature export and cannot redirect playback to another inode.  The guard
copies only the small metrics file into the new item output and records both
the accepted bag identity and sealed descriptor in the replay manifest.  It
contains no exporter invocation and never writes an accepted frontend path.
After all six descriptors pass, it publishes
`replay_only_guard_manifest.json` with exclusive creation plus file and
directory `fsync`, before invoking the recovered-July shell.  A run is not an
ordinary backend failure unless both that manifest and the namespace manifest
exist and pass their semantic audits; failure before either boundary is an
irreversible execution-integrity fault.

Each item has unique `TAG`, `ROS_HOME`, `ROS_LOG_DIR`, canonical evidence
directory, and overlay-log symlink.  The arm's `FEATURE_BAG_OVERRIDE` is the
identity-bound bag from its accepted receipt.  The same bag is reused for all
five repeats of that arm.

## 5. Failure and continuation semantics

There is no retry, replacement repeat, outcome-dependent rerun, or renumbering.
Once a claim exists, the item's allowance is consumed even if the child never
starts.  A timeout, nonzero return code, missing trajectory, failed
initialization, or other scientific/artifact failure produces
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT`.  If cleanup, authority, claim, and
workspace integrity still pass, the next predeclared item remains launchable.

Backend acceptance is not inferred merely from child return code.  The
diagnostic output must report `init_success=1`, at least 30 matched and output
poses, at least 10 RPE pairs, at least 10 seconds of output, at least 70%
temporal coverage, no output gap above 0.50 seconds, and no solver-failure,
failure, or restart events.  These are replay-usability gates only; the joint
HFNet common-support evaluator below remains the accuracy authority.

A receipt with authority drift, a changed claim, a broken workspace binding,
an invalid namespace/port manifest, a replay-only lineage mismatch, a generated
configuration that violates the frozen VINS settings, an unexpected evidence
file or directory, a missing or changed supervisor child log, or an owned
process that could not be drained has execution integrity `FAIL`.  Every such
condition is accumulated in the irreversible fault latch before the terminal
receipt is published.
That is a campaign integrity failure and blocks every later item.  A claim
without a terminal receipt also blocks later launches.  The supervisor never
silently substitutes a sixth run for a failed one.

## 6. Evidence and later scoring

Each item records its claim, child log, namespace manifest, generated VINS and
camera configurations, VINS environment manifest, replay manifest, raw VINS
trajectory, VINS log, runner-produced APE text, copied frontend metrics, and a
terminal receipt.  The runner-produced `ape.txt` is diagnostic only and is not
the A08 HFNet comparison statistic.

After all ten allowances are terminal, valid raw VINS outputs are evaluated
jointly with the sealed HFNet trajectory on one exact common-support mask over
source indices 4000 through 4660.  All trajectories use `world_T_body`, the
same `body_T_cam0`, proper fixed-scale SE(3), no Sim(3), and no fitted time
offset.  Formal ranking remains unavailable unless the joint mask has at least
30 samples, at least 10 seconds of span, at least 70% reference coverage, and
at least 10 RPE pairs.  All five declared outcomes and the valid-count per arm
must be reported; the arm summary is the median over valid repeats, never a
best-run selection.

The exact inclusive support endpoints are
`1542885161111831216 ns` (source 4000) and `1542885194106222672 ns`
(source 4660).  The evaluation grid is 1 Hz, anchored at source 4000, yielding
33 possible reference timestamps.  Its sealed inputs are:

- reference TUM: `evaluation_inputs/a08_reference_source_4000_4660.tum`,
  5,082 bytes, SHA-256
  `25ccba084e5b5edd5651d24bec2bf753b119bc8de7174d36b870855680086682`;
- HFNet `world_T_body` CSV:
  `evaluation_inputs/hfnet_world_T_body_support_source_4000_4660.vio.csv`,
  70,021 bytes, SHA-256
  `be8a6bd278ad0222adeaf869a50c710d791c6eb5bee6db1afd57e1678ca9b04c`;
- shared transform configuration:
  `evaluation_inputs/hfnet_aqualoc_body_T_cam0.yaml`, 415 bytes, SHA-256
  `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1`.

These paths are relative to
`experiments/a08_hfnet_history_matched_support_extension_v1`.  The later
evaluator must use one joint mask for HFNet and every valid KLT/XFeat repeat,
then cross-check the fixed-scale result with evo.  A failed gate yields `NA`,
not a substituted alignment or selected repeat.
