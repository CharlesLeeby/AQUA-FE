# A02 4500–6300 additive component-only continuation v2.3

Date: 2026-08-12 (Asia/Shanghai)  
Role: third revised post-incident development/exploratory evidence; not
confirmatory evidence and not a completion of v1, v2.1, or v2.2.

## 1. Governance boundary

The v1 protocol terminated at command 9 with RC42. The v2.1 continuation
terminated at `9R` with RC42. The additive v2.2 protocol then executed its
complete fixed order and reached a scientific FAIL/no-ranking terminal state.
None of those protocols is resumed or retried here.

The canonical third incident is:

`papers/a02_4500_6300_v2_2_terminal_incident_v1.json`

It records the following immutable v2.2 observations:

- `10C2`: the const-q rewrite actually ran once and returned 0;
- `11C2`: the audit script returned 1, while its enclosing shell returned 0
  after printing the captured internal RC;
- `12C2`: the const-q contract gate had internal RC1;
- the XFeat producer and independent XFeat audit did not start and reported
  dependency-skip RC125;
- the old B1 and XFeat VINS receipts contain legacy `attempt_count=1`, but
  tree contents plus fixed-order dependency gates establish actual algorithm
  start count 0; they are immutable skip receipts, not consumed VINS attempts;
- HFNet had exactly one actual start: raw process RC0, wrapper RC1,
  `evaluable=false`, 22 score poses spanning 1.051619328 seconds;
- no HFNet bridge or evaluator ran;
- v2.2 preseal status was `FAIL_ONE_OR_MORE_SCIENTIFIC_ARMS`, SHA256
  `1cff9e454466673902f26f09811ad46a60122b1fe0b174b3b2b2c71af906cd7e`.

v2.2 is therefore complete but scientifically unusable for the preregistered
three-arm ranking. Its FAIL evidence remains immutable and byte-recomputable.

## 2. Only authorized correction

The const-q rewrite changed all 315,000 feature observations. The feature-bag
partition is 310,704 observations with `source_code=1` and 4,296 observations
with `source_code=2`. The v2.2 audit selected only source 1, so it correctly
detected changes outside its declared partition but did so under an incorrect
partition declaration.

The only semantic correction is:

```text
quality audit source_codes: [1] -> [1, 2]
```

The corrected read-only audit must report exactly:

- `source_codes=[1,2]`;
- 900 feature frames;
- `selected_observations=315000`;
- `changed_observations=315000`;
- `untouched_observations=0`;
- 19,075 total records and 18,175 byte-equal non-feature records;
- quality 1 and sigma 1;
- native bag SHA256
  `dbe85f68c91e523f56c7f7488accd216a6b56ffc3949eb9e6a09745fa2e5d6cb`;
- const-q bag SHA256
  `a91b159c46c51c0d3d7232e86901e86862b4f58fbf9bef58a224f9f8444db523`.

No feature bag, source code, quality value, frontend algorithm, backend
parameter, or camera configuration may be changed. The native exporter,
const-q rewrite, HFNet preflight/freeze/run, HFNet bridge, and common-support
evaluator are all forbidden.

## 3. Immutable carry-forward

The machine freeze binds the complete v2.2 carry-forward plus the full current
terminal inventories:

- const-q directory: one directory, two regular files, inventory SHA256
  `47af24f4...`; its bag and stats CSV remain byte-exact;
- old B1 RC125 skip directory: singleton receipt tree, inventory SHA256
  `8058a76a...`;
- old XFeat RC125 skip directory: singleton receipt tree, inventory SHA256
  `90d63d4a...`;
- HFNet contract and complete driver/run trees, including result SHA256
  `b7c911ca364a9d9233fa9b7cf0c6f245b83e89b129882628075fd8e759c6cb73`;
- v2.2 FAIL preseal cited above;
- all previously absent v1/v2.1/v2.2 output paths remain absent.

Full, untruncated identities and sorted tree entries are authoritative in the
canonical v2.3 freeze and third incident. Ellipses in this human summary are
not machine claims.

## 4. New reserved paths

Exactly five new paths must be absent at v2.3 start:

1. `/home/ma/AQUA-FE_WS/papers/a02_4500_6300_constq_quality_partition_audit_v2_3_post_incident.json`
2. `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_post_incident_v2_3_r1`
3. `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_post_incident_v2_3_r1`
4. `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_3_r1`
5. `/home/ma/AQUA-FE_WS/papers/a02_4500_6300_component_outcomes_terminal_v2_3_post_incident.json`

The old missing audit, XFeat, bridge, evaluation, and evidence paths must not
be populated. The two old RC125 run directories must not be reused.

## 5. Component attempts and fixed parameters

After the read-only start gate, v2.3 may perform only:

1. one corrected audit write with both `--source-code 1` and
   `--source-code 2`;
2. one first actual XFeat export into its new directory;
3. one independent XFeat audit;
4. one first actual B1 const-q VINS replay into its new directory;
5. one first actual XFeat-birth/raw-LK-carrier VINS replay into its new
   directory;
6. one terminal component-usability seal/check.

The XFeat exporter, official closure, 350-observation-per-frame contract,
CPU runtime, VINS binary, VINS shared libraries, body-to-camera transform,
time delay, solver budget, and all replay environment values remain those
frozen by v1. Ports 11531 and 11532 are reused because the v1 provenance
validator binds those exact values; the old processes are complete and new
paths/tags distinguish the new attempts.

Each v2.3 VINS receipt explicitly records `algorithm_started` and
`actual_process_start_count`. RC125 with start count 0 means dependency skip;
started nonzero means a terminal scientific failure; only started RC0 is a
usable replay.

## 6. Failure and execution semantics

The canonical freeze contains ten exact commands labeled `28R3` through
`37C3`. The JSON freeze is the machine authority for their bytes and order.
All commands run from `/home/ma/AQUA-FE_WS` in separate clean shells.

- Failure of builder/start/static identity gates is global governance STOP.
- Corrected-audit, XFeat, or either VINS scientific/dependency failure does
  not suppress later fixed-order commands.
- Every scientific command propagates its internal RC; the orchestrator must
  record it and continue to later mandatory commands.
- No command may be retried.
- `37C3` returns success when terminal evidence is sealed and byte-rechecked;
  scientific PASS versus FAIL is encoded in the evidence JSON and is not
  inferred from the evidence-sealing RC.

## 7. Terminal evidence and claim boundary

The terminal schema is:

`aqua-fe-a02-long-component-outcomes-terminal-v2-3-post-incident-continuation`

If both component arms are usable, status is
`TERMINAL_COMPONENT_ARMS_USABLE_NO_THREE_ARM_RANKING_HFNET_UNUSABLE`.
Otherwise status is `TERMINAL_COMPONENT_ARM_FAILURE_NO_RANKING_HFNET_UNUSABLE`.

In both cases:

- HFNet remains immutable and unusable;
- no bridge or evaluator is run;
- no component or three-arm ranking is produced;
- the 46-row proxy reference remains non-independent ground truth;
- the result supports only component-arm usability, not accuracy superiority;
- the evidence is post-STOP development/exploratory and not confirmatory.

## 8. Frozen implementation identities

The canonical freeze binds exact identities for all three prior incidents and
governance generations, the v2.2 preseal, quality auditor, and v2.3 files.
The final implementation identities are:

- verifier: `f90b1d552b621202f99c471c94cc6b6a9a6c4750668df05163ffda605a8bfef0`
- tests: `8d9178106803de3b50aaa7506544348722116df69723e6b346c335a96bc2aa1d`
- builder: `b04ba2f3969acefb133554dc3c36ef85cceedbff1a8a5bd57dde17ea906a3dc7`
- third incident: `0de6c739ab40d27ff07bf509ff7002d45b533aeb4b8c6174a96ee941f55305b8`

No v2.3 formal command was executed while creating this preregistration,
incident, verifier, tests, builder, or freeze.
