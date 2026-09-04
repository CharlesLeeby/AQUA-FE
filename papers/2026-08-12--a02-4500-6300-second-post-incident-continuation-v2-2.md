# A02 4500–6300 second post-incident continuation v2.2

Date: 2026-08-12 (Asia/Shanghai)

Evidence class: **second revised post-incident development/exploratory**, not
confirmatory.

Machine authority:
`papers/a02_4500_6300_post_incident_continuation_freeze_v2_2.json`.

## 1. Two terminated protocols are preserved

The v1 protocol remains terminated at old command 9 with RC42. Commands 0–8
and the B1 native attempt were consumed exactly once; commands 10–27 were not
executed. Its incident receipt is immutable at SHA256
`5b19c46b06563250b4e54799608893e509269b85748de2213feb531df3694b07`.

The first post-incident continuation (v2.1) is also terminated. Its single
`9R` command produced these transcript-observed stages:

1. freeze builder: `PASS_EXACT_REBUILD` for freeze SHA256
   `b86da0e0015076960a9aeb9cf3766b50d6d2342438769866b7b84b4a5d55a355`,
   size 920,795 bytes;
2. continuation start: `PASS_POST_INCIDENT_CONTINUATION_START`, with all
   13 remaining outputs absent and the frozen shared/B1 inventories intact;
3. B1 decision gate:
   `VERIFICATION_BLOCKED:STATIC_COMMAND_PROTOCOL_EXACT_MISMATCH_AT_25`;
4. whole `9R` return code: 42.

No persistent raw stdout/stderr file was created. The exact command, exact
persisted builder line, parsed start evidence, exact decision stderr line,
orchestrator-transcript provenance, and no-raw-stream fact are sealed in
`papers/a02_4500_6300_v2_1_9r_infrastructure_false_negative_incident_v1.json`
(SHA256 `ed71ba881409786292b1c741a8d925bf0fd13574745e7806d23d29ef48b42aea`).

v2.1 `9R` is consumed and must not be rerun. No v2.1 scientific command, no
producer, and no B1 retry ran. v2.2 is not a resume or retry of v1 or v2.1.

Immutable governance identities include:

- v1 freeze:
  `dfcae748385766f5585e1799603f737abe9223cb30d1a9bcc43fe84476abf9be`;
- v1 verifier:
  `d5316e505d6d4337e3743a38c300d963fbede9702c037eaccd501813a0683cef`;
- v2.1 freeze:
  `b86da0e0015076960a9aeb9cf3766b50d6d2342438769866b7b84b4a5d55a355`;
- v2.1 verifier:
  `842574d8abc1a0041bee0aaa0085029d63157db480ef1fac4a13656dc51dc560`;
- v2.1 builder:
  `c7efd86e1a95464f99915f890d1fa1529651e4604fd2d696a90155896e846d56`.

## 2. v2.1 failure cause and the only v2.2 delegate fix

v2.1 temporarily changed `v1.DEFAULT_OUTPUT` and
`v1.DEFAULT_POST_EVAL_OUTPUT` before calling `v1.main`. The B1 decision gate
then called v1's static freeze audit. Its `authoritative_commands()` observed
the temporary v2.1 evidence paths, so old command indices 25 and 27 no longer
matched the immutable v1 freeze; the audit stopped at index 25 before the B1
decision semantics were evaluated.

v2.2 keeps both v1 default globals byte-for-byte and object-value unchanged.
It rejects any caller-supplied `--evidence` or `--post-eval-evidence` option,
then injects exactly one explicit v2.2 value for each option into the argv
delegated to `v1.main`. Immediately before delegation it requires
`v1.authoritative_commands()` to remain exactly equal to the 28 old frozen
commands. Only the loader and pre/post record-builder functions are patched
temporarily; all are restored in `finally`.

The original two-label shared-manifest correction is unchanged:
`SHARED_MANIFEST_SOURCE_CHAIN` and `SHARED_MANIFEST` alone require exact
`shared_exporter.canonical_json_bytes`; every other label retains the v1
pretty-canonical byte gate.

## 3. v2.2 evidence envelope

The new evidence paths are:

- pre-evaluation:
  `papers/a02_4500_6300_three_arm_pre_eval_verification_v2_2_post_incident.json`;
- post-evaluation:
  `strict_gate_receipt_v2_2_post_incident.json` within the frozen evaluation
  directory.

Their schemas are, respectively:

- `aqua-fe-a02-long-three-arm-pre-eval-verification-v2-2-post-incident-continuation`;
- `aqua-fe-a02-long-three-arm-post-eval-verification-v2-2-post-incident-continuation`.

Both require a recomputed `post_incident_continuation` envelope binding:

- the active v2.2 freeze and verifier identities;
- the two-label loader correction;
- both terminated protocol histories, each with its freeze, incident receipt,
  RC42, and no-resume status;
- the explicit-argv/no-default-mutation delegate contract;
- the second revised exploratory role.

Seal/check and post-seal/post-check recompute the envelope; any omission or
identity drift is a byte mismatch.

Frozen v2.2 implementation identities before machine-freeze creation:

- verifier:
  `9cf81c5e88d1423b599dda48f66142fc188ed1f483b5062f7ad5c24769a69cd8`;
- tests:
  `f20dd6fb460dedbc7b56d3ff467df93ebdc827040ea0c564dbeace811e859896`;
- read-only freeze builder:
  `7adb0bd85d3a78e007f02fcfd0dc1de66b405495c36b77b6fd393d799f6199f8`.

## 4. Carry-forward and three-generation absence

v2.2 copies the complete v2.1 carry-forward inventory exactly and revalidates
it through the immutable v2.1 start gate:

- shared root: 9 directories, 3,609 regular files, 878,580,060 bytes, full
  inventory SHA256
  `f135192579f68e6792dcf1d36f5dc66ea63e62a8433b46d307a2f010fe6afbd5`;
- 1,801 real shared/HFNet camera hard-link pairs;
- singleton B1 decision tree inventory SHA256
  `681507ddb004761d994e25984549f494c69eb90c5bcb8039150cdc9488b627f8`;
- full B1 native tree inventory SHA256
  `3902497f72d11c77a9d9979f1a858e085d838cd592727690ae03ad022c3e2e44`;
- canonical raw bag and manifest identities remain those frozen by v2.1.

The v2.2 start gate requires all three 13-path generations absent: legacy v1,
redirected v2.1, and active v2.2. Eleven scientific/output paths are shared;
the three generations have distinct pre/post evidence names. The old v1 and
v2.1 evidence paths must remain absent throughout. The empty frozen pycache
prefix remains required.

## 5. New command boundary

The new protocol has 19 commands: `9R2`, then `10C2` through `27C2`. Exact
shell strings are the machine freeze's ordered `commands` array and execute
individually from `/home/ma/AQUA-FE_WS` under single-writer/no-retry rules.

`9R2` performs only:

1. exact read-only rebuild of the v2.2 freeze;
2. v2.2 start validation, including both incidents, all three governance
   generations, full carry-forward inventory, and three-generation absence;
3. the corrected read-only B1 decision verification.

Any failure maps to governance RC42. `9R2` contains no materializer, shared
exporter, B1 runner, or v2.1 `9R` call. `10C2`–`27C2` derive only from old
commands 10–27 and use v2.2 verifier/evidence paths. All old scientific-arm,
mandatory-HFNet, dependency-local skip, zero-retry, no-clobber, and strict
common-support semantics remain unchanged.

No v2.2 formal command was executed while creating this addendum/freeze.
Synthetic tests, source parsing, and read-only inventory hashing are not
scientific runs.

## 6. Scientific interpretation remains unchanged

Any future comparison remains post-incident development/exploratory. B1
const-q and XFeat-birth/raw-LK are component arms sharing VINS; official HFNet
is a whole system, so whole-system differences cannot be attributed solely to
a learned frontend. The 46-row proxy provides 45 scoring grid points plus one
interpolation-support row and is not independent ground truth. Nothing in
v2.2 retroactively turns v1 or v2.1 into a completed preregistered protocol.
