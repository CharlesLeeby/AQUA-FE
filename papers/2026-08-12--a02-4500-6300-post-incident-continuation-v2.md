# A02 4500–6300 post-incident continuation v2

Date: 2026-08-12 (Asia/Shanghai)

Evidence class: **revised post-incident development/exploratory**, not confirmatory.

Machine authority: `papers/a02_4500_6300_post_incident_continuation_freeze_v2.json`.

## 1. The v1 protocol stopped

The original v1 preregistration is preserved verbatim. Commands 0–8 were
consumed once. Command 9 returned process code 42 with the single observed
line:

```text
VERIFICATION_BLOCKED:SHARED_MANIFEST_SOURCE_CHAIN_NOT_CANONICAL_OBJECT
```

That event terminated v1. Commands 10–27 were not executed. This document
does not call the new work a resume, does not claim that the original 28-step
protocol was fulfilled, and does not erase the v1 STOP/RC42 result. The exact
old command, observed return code, transcript provenance, and absence of a
persistent raw stream file are sealed in
`papers/a02_4500_6300_command9_infrastructure_false_negative_incident_v1.json`
(SHA256 `5b19c46b06563250b4e54799608893e509269b85748de2213feb531df3694b07`).

The B1 native attempt is an immutable, already-consumed carry-forward
artifact. It is neither retried nor presented as a proposed-method result.
Commands 0–8, including materialization, shared export, and the guarded B1
native export, are forbidden in this continuation.

## 2. Confirmed infrastructure false negative

The shared producer wrote
`conversion_manifest.json` with its frozen
`shared_exporter.canonical_json_bytes` codec:

- actual size: 682,952 bytes;
- actual/producer-compact SHA256:
  `f2931e451e9542a3801209e88fd47519b881d6713ac829c9871a1f9366bc9d93`;
- v1 pretty re-encoding SHA256:
  `239b810e7e0120cada9914b3f715b9d8aad358cfb268daf554f10dc9539ce475`;
- actual bytes equal producer compact canonical bytes: true;
- actual bytes equal v1 pretty canonical bytes: false.

The failure was therefore a verifier/producer byte-codec mismatch, not a
scientific-arm failure and not evidence that the shared manifest semantics or
payload were invalid.

## 3. The only verifier change

`scripts/verify_a02_long_three_arm_eval_inputs_v2.py` is additive and leaves
the v1 file unchanged. It changes exactly two v1 loader call-site labels:

1. `SHARED_MANIFEST_SOURCE_CHAIN`
2. `SHARED_MANIFEST`

For those labels only, bytes must equal
`shared_exporter.canonical_json_bytes(parsed_dict)` exactly. Pretty JSON,
extra whitespace, reordered non-canonical keys, non-object JSON, and invalid
JSON remain failures. Every other label delegates to the original v1
pretty-canonical exact-byte loader. There is no dual-format or semantic-only
acceptance. All provenance, schema, status, reference, bridge, arm-health,
common-support, and post-evaluation checks remain v1 checks.

The wrapper also makes the result evidence explicitly v2. Pre-evaluation and
post-evaluation records use, respectively,
`aqua-fe-a02-long-three-arm-pre-eval-verification-v2-post-incident-continuation`
and
`aqua-fe-a02-long-three-arm-post-eval-verification-v2-post-incident-continuation`.
Both contain a mandatory `post_incident_continuation` object binding the
incident receipt, continuation freeze, old freeze, unchanged v1 verifier,
executing v2 verifier, the exact two-label codec correction, RC42 termination,
the not-resumed/not-fulfilled boundary, and the revised exploratory role.
`seal`, `check`, `seal-evaluation`, and `check-evaluation` independently
recompute that object; missing or changed provenance is a byte mismatch.

Frozen implementation identities before creation of the machine freeze:

- v2 verifier: `842574d8abc1a0041bee0aaa0085029d63157db480ef1fac4a13656dc51dc560`;
- v2 tests: `8def7cb72c5c7d4e95c5bc9f484def0363783e295ce19498d6aaf078eb700e04`;
- continuation-freeze builder:
  `c7efd86e1a95464f99915f890d1fa1529651e4604fd2d696a90155896e846d56`;
- unchanged v1 verifier:
  `d5316e505d6d4337e3743a38c300d963fbede9702c037eaccd501813a0683cef`;
- unchanged shared exporter:
  `c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f`;
- unchanged old freeze:
  `dfcae748385766f5585e1799603f737abe9223cb30d1a9bcc43fe84476abf9be`.

The machine freeze additionally binds sizes and canonical paths.

## 4. Adopted state, sealed in full

Old reserved paths 0–4 are present and adopted; old reserved paths 5–17 are
required absent at continuation freeze and again at the first continuation
gate.

The adopted shared root is bound by every sorted entry
(`relative_path`, `type`, and for regular files `size_bytes`, `sha256`):

- 9 directories;
- 3,609 regular files;
- 0 symlinks or special entries;
- 878,580,060 regular-file bytes;
- full-inventory SHA256
  `f135192579f68e6792dcf1d36f5dc66ea63e62a8433b46d307a2f010fe6afbd5`;
- 1,801 camera files required to be real hard-link pairs between
  `shared/cam0/data` and `hfnet/mav0/cam0/data`.

The guarded B1 decision directory is a singleton: one directory entry and
one regular file named `b1_current_exporter_v3_decision.json`, inventory hash
`681507ddb004761d994e25984549f494c69eb90c5bcb8039150cdc9488b627f8`.
The entire B1 native run tree is also bound: two directories, three regular
files, 27,983,213 bytes, inventory hash
`3902497f72d11c77a9d9979f1a858e085d838cd592727690ae03ad022c3e2e44`.

The canonical raw bag and adjacent manifest remain fixed at:

- bag: 449,056,538 bytes,
  `eebd45439e76c461e58a2a1d6321f3fcb82dbcf57ea4093929548c9620e63a83`;
- manifest: 4,502 bytes,
  `41667ae9fd00dc6baf261cb2c519642b0ff9c2123ba154421780bc41bcf4de8e`.

The 13 old still-reserved paths remain required absent exactly as old indices
5–17, in old order:

1. B1 const-q feature run directory;
2. B1 const-q quality-audit JSON;
3. XFeat-birth carrier export directory;
4. B1 const-q VINS run directory;
5. XFeat-birth VINS run directory;
6. HFNet v4 contract;
7. HFNet v4 run directory;
8. HFNet v4 driver directory;
9. HFNet bridge CSV;
10. HFNet bridge manifest;
11. three-arm pre-evaluation receipt;
12. common-support evaluation directory;
13. strict post-evaluation receipt.

The canonical JSON stores their full absolute paths. Any adopted identity
drift, shared-tree entry drift, broken hard-link pair, non-singleton decision,
missing consumed path, or prematurely present remaining path blocks the new
protocol. The frozen Python cache prefix
`/tmp/aqua-fe-a02-long-eval-empty-pycache-v1` must also remain absent, with
bytecode writes disabled as in v1.

For the continuation's own 13-output set, the two legacy evidence names are
redirected while the other 11 paths are unchanged:

- pre-evaluation evidence becomes
  `papers/a02_4500_6300_three_arm_pre_eval_verification_v2_post_incident.json`;
- post-evaluation evidence becomes
  `strict_gate_receipt_v2_post_incident.json` inside the frozen evaluation
  directory.

Both old v1 evidence paths must remain absent. The start gate checks absence
of both the old 13-path set and the redirected 13-path set.

## 5. New command boundary

This is a new 19-command continuation, labeled `9R`, then `10C` through
`27C`. The exact shell strings are the machine freeze's ordered `commands`
array. They must run individually from `/home/ma/AQUA-FE_WS` under the same
single-writer and no-retry assumptions as v1.

`9R` first requires an exact rebuild of the continuation freeze with the
frozen read-only builder. It then runs the new `check-continuation-start` gate,
which rehashes the old freeze, incident receipt, all new static identities,
the complete shared inventory, the hard-link relation, the complete B1 native
tree, the singleton B1 decision, all machine-authority fields, and the 5/13
reserved-path partition. It finally reruns only the failed read-only B1
decision verification through v2. Any failure maps to global governance code
42. It does not invoke B1 or any producer.

`10C`–`27C` are old commands 10–27 with only the verifier executable changed
from v1 to v2 and the continuation freeze made explicit. Their scientific-arm
failure, dependency-local skip, mandatory HFNet attempt, zero-retry,
three-valid-trajectory ranking gate, strict common-support, proxy caveat, and
no-clobber behavior are inherited without relaxation.

No command in this new sequence was executed while preparing this document or
its freeze. Static/synthetic tests and read-only inventory hashing are not
scientific runs.

## 6. Interpretation boundary

Any future table remains a comparison between component-level carrier arms
(B1 const-q and current XFeat-birth/raw-LK carrier, each replayed through the
same VINS backend) and official HFNet as a whole system. Differences cannot be
attributed solely to a learned frontend. The 46-row reference proxy supplies
45 uniform score grid points plus the 46th interpolation-support row; it is
not independent ground truth. Results under this continuation must be labeled
post-incident development/exploratory and cannot retroactively become a v1
preregistered result.
