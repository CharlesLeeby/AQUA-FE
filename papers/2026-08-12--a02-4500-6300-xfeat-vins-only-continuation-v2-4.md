# A02 4500..6300 XFeat-VINS-only post-incident continuation v2.4

Status: **frozen but not executed**. This is a fourth, additive,
post-incident development/exploratory protocol. It does not resume or retry
v1, v2.1, v2.2, or v2.3.

## Boundary and diagnosis

v2.3 completed its fixed order and sealed
`TERMINAL_COMPONENT_ARM_FAILURE_NO_RANKING_HFNET_UNUSABLE`. Its B1 VINS arm
was usable, its single HFNet run remained unusable, and its XFeat VINS process
was never started: the dependency gate rejected an otherwise byte-exact XFeat
bag/manifest/audit chain.

The false negative has exactly three predicates:

1. the frozen v1 validator compared detector calls with 900 published feature
   frames, while the actual carrier invokes XFeat on every raw frame needing a
   refill;
2. the actual detector call count is **1562**, independently equal to the
   runtime counter, profiler count, timing count, `tracked_after < 350` raw
   diagnostic count, and positive-candidate raw diagnostic count;
3. four official XFeat closure paths and the LICENSE path use the lexical
   `/home/ma/AQUA-FE_WS/external_tools/...` alias, whereas the old validator
   expected the resolved `/mnt/data/AQUA-FE_WS/external_tools/...` path. Each
   alias resolves to the same frozen regular file with the same size and SHA.

v2.4 accepts only manifest SHA
`49ab1814a84222167a173f9e01a9ff9a70b33df9974a131d4b32e026f436da99`
and uses a six-leaf in-memory compatibility projection solely while invoking
the old validator. The projection is never written. All evidence and outcome
records retain the observed detector-call count 1562; 900 is only the feature
publication count, never an asserted detector-call fact.

## Immutable carry-forward

The machine freeze binds the full v2.3 terminal, full B1 run tree, B1 RC0
receipt/log/VIO, full XFeat export tree, exact XFeat bag/manifest/audit, and the
old v2.3 XFeat dependency-skip receipt. That receipt has RC125,
`algorithm_started=false`, `actual_process_start_count=0`, and
`attempt_count=0`; it is not an algorithm attempt.

No v2.4 command may rerun or modify the B1 arm, const-q rewrite/audit, XFeat
producer/auditor, HFNet, bridge, or common-support evaluator. The generic VINS
runner's inherent single-arm descriptive `ape.txt` generation remains enabled;
it is not a common-support comparison or ranking.

## Frozen action and terminal meaning

Exactly one new algorithm process may start: XFeat VINS at ROS port 11532,
using the manifest-resolved `/mnt/data/.../features.bag`, in the new reserved
run directory ending `post_incident_v2_4_r1`. The run directory is atomically
reserved before the runner starts. Its process receipt is exclusive,
one-attempt, and no-retry. A nonzero process return code is a terminal
scientific failure, not authority to rerun.

The four machine-authoritative commands are labels `38R4` through `41C4` in
the canonical freeze JSON and must be executed individually, in order, from
`/home/ma/AQUA-FE_WS`. The first two are global identity/input gates. The third
is the only XFeat VINS attempt. The fourth always seals and checks terminal
evidence.

If B1 and XFeat VINS are both usable, the terminal may set
`descriptive_two_component_comparison_eligible=true`. This is eligibility for
a future separately frozen v2.5 two-arm common-support analysis, not a result.
v2.4 performs no common-support evaluation, no ranking, no superiority test,
and no three-arm comparison. HFNet stays excluded as immutable unusable
carry-forward. The proxy reference is not independent ground truth.

## Reserved outputs

- `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1`
- `/home/ma/AQUA-FE_WS/papers/a02_4500_6300_xfeat_vins_terminal_v2_4_post_incident.json`

Both must be absent at the start gate. Appearance consumes the one-shot path;
there is no cleanup/retry provision.

## Authority

The canonical JSON freeze is machine-authoritative for commands, identities,
paths, and policy. The additive verifier, builder, incident, tests, and this
addendum are all themselves frozen by exact path/size/SHA identities. Builders
and tests do not execute commands `38R4`--`41C4`.
