# A02 4500--6300 v2.5 post-incident wrong-tree adoption and two-arm analysis

Status: **FROZEN ONLY AFTER THE CANONICAL JSON PASSES TWO INDEPENDENT AUDITS.**
Nothing in this addendum authorizes execution before that GO.  The authoritative
working directory is `/home/ma/AQUA-FE_WS`.

## 1. Governance boundary

The v2.4 protocol completed and remains immutably sealed as
`TERMINAL_XFEAT_VINS_UNUSABLE_NO_COMPARISON_HFNET_EXCLUDED` in
`papers/a02_4500_6300_xfeat_vins_terminal_v2_4_post_incident.json`, size 81783,
SHA256 `2e7814cf6d8a2d01c022a3f7fb516b93825c651ac2643d7eae17b5a90f499e81`.
v2.5 does not resume, repair, or relabel that terminal.

v2.5 is an additive **post-incident, result-informed, exploratory** protocol.
The runner-native single-arm `ape.txt` was already visible when adoption was
decided.  Therefore this is not preregistered or confirmatory.  It permits one
descriptive two-component common-support proxy contrast only.  It forbids
statistical-significance, superiority, ranking, three-arm, and whole-system
claims.

HFNet remains the immutable v2.4 unusable carry-forward and is excluded.  It is
not rerun.  B1/XFeat producers, audits, VINS processes, bridge, and all earlier
commands are also not rerun.

## 2. Read-only adoption fact

The frozen v2.4 command invoked
`run_aqualoc_archaeo_vins_eval.sh external 2 4500 6300 klt 2`.  The frozen runner
derives its output directory as
`${MODE}_${METHOD}_every${EVERY_N}_${TAG}`.  Consequently the healthy output was
written under `external_klt_every2_...`, while the v2.4 receipt and verifier
expected `external_xfeat_lk_every2_...`.

These remain two distinct trees:

- expected receipt-only tree:
  `/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1`;
- observed deterministic output tree:
  `/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1`.

The expected-tree receipt is size 958, SHA256
`b15e360d966e6488d1134437863688196550665c5a5f311947c0b5efcfbab571`, and
declares one authorized wrapper start with RC0.  It does not prove the actual
output path.  The actual tree was not a v2.4 reserved-absent namespace, so v2.5
does not retroactively claim v2.4 no-clobber protection for it.  The process was
observed as a singleton by the orchestrator, but no persistent process-telemetry
artifact cryptographically proves a unique VINS child.

The actual tree is adopted read-only, without move, copy, link, cleanup, or
rerun.  Its exact closure is 2 directories, 8 regular files, 188048 bytes,
inventory SHA256
`4124f09c96f42ea956238880b9339e190d06fac5c329d26c7db87c38a2cb0afd`.
The scientific trajectory is size 91884, SHA256
`d6d8742753e96d7fa6243b469337c2bebaa28aac1ba9f47bcaa43971e8e88b00`.
It has 872 finite, raw-order strictly increasing poses over 87.08553216 s;
450 poses lie in the score window.  `vins.log` is size 90373, SHA256
`dcccdfe164b332ea7ae3d9cff16526bed8cb0191a9c7461ccca9566533b96ec3`:
initialization occurs exactly once, all 11 solver-failure markers precede that
initialization, and every post-initialization failure/reboot/restart count is
zero.

Replay/config provenance is revalidated live: port 11532, the canonical XFeat
bag SHA256 `13d0daf45e81560506cc44927318d91821ffc40564ded4529ce1466ed70700c0`,
camera SHA256 `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5`,
and normalized VINS configuration SHA256
`45eb12852b8eff6b14dbfdb8f366fa64eebf7ca5dbf838d791f011dd84a4d084`.
The immutable B1 trajectory is independently revalidated as PASS, size 93578,
SHA256 `59c505704e9e82c050abe2c3e2edb83517b7044828beb694780646ff7a2bea92`.

The canonical incident is
`papers/a02_4500_6300_v2_4_wrong_output_tree_adoption_incident_v1.json`, size
19193, SHA256
`b90469c8bf7796f85e81c75263cfeaafd33d53c8fbce03681ba349770b51790a`.

## 3. Frozen two-arm protocol

The trajectories already include the v2.3/v2.4 4500--5399 preroll.  Only
camera frames 5400--6300 define the score interval; frame 5400 was fed once in
the original runs and is not replayed here.

Arms are exactly `B1_CONSTQ` and `XFEATBIRTH_RAWLK`.  Both use the same config
`configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml`, size 415,
SHA256 `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1`.
The proxy reference is the 46-row
`/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1/shared/reference_proxy.tum`,
size 7488, SHA256
`b1ae03e073ea1c2bcf12891ae0cca0eab462e044e73a1045ad4f11aa8b108d2c`.
It is a projected proxy derived from the same source and is **not independent
ground truth**.

The frozen score window is
`1542829061.692686528..1542829106.687510592`.  Evaluation/reference/estimate
nominal rates are 1/1/10 Hz; reference and estimate maximum gaps are 2.5/0.25 s;
RPE delta is 1 s.  The common uniform grid must contain 45 points.  APE requires
at least 30 poses, 10 s span, and 0.70 common coverage; RPE requires at least 10
pairs.  Both `ape_valid` and `rpe_valid` must be true.  Every reported APE/RPE
value must be finite.

Primary metrics are recomputed byte-for-byte from the two sealed VIO inputs by
`scripts/evaluate_vins_common_support.py`, size 27933, SHA256
`ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110`,
using `scripts/trajectory_eval_core.py`, size 27945, SHA256
`aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635`.
`evo_ape/evo_rpe` is a bound diagnostic cross-check only, never the ranking or
primary result.

## 4. Fixed execution and no-retry contract

The exact command strings are machine-authoritative in
`papers/a02_4500_6300_two_arm_adoption_analysis_freeze_v2_5.json` and are
generated by `expected_commands()` in the frozen verifier.  They must be run as
three independent shells, in this exact order, from the authoritative working
directory:

1. `42R5`: exact builder rebuild plus continuation-start/static/adoption-input
   gate.  Any failure exits 42 before creating evidence or evaluation output.
2. `43C5`: O_EXCL-style seal and exact recheck of
   `papers/a02_4500_6300_two_arm_pre_eval_adoption_v2_5.json`.
3. `44C5`: recheck static/adoption evidence; atomically claim the exact new eval
   directory with non-`-p` `/usr/bin/mkdir`; make exactly one two-arm evaluator
   attempt; seal its actual RC once; seal and recheck the terminal post record.
   An exact but scientifically failed terminal check returns RC3; evidence or
   identity corruption returns RC2.  Neither authorizes retry.

All Python/evaluator actions use the same frozen environment, interpreter,
NumPy/evo closure, empty pycache prefix, and single-thread BLAS settings inherited
from v1.  No command relies on ambient Python or cross-shell variables.

New reserved paths, all required absent at freeze:

- `papers/a02_4500_6300_two_arm_pre_eval_adoption_v2_5.json`;
- `papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_adopted_v2_5_r1`;
- `papers/a02_4500_6300_two_arm_proxy_contrast_post_eval_v2_5.json`.

The evaluator directory is claimed in the same shell immediately before the
single evaluator invocation.  Any pre-existing exact directory exits 73 and
the evaluator is not called.  The actual evaluator RC is sealed once.  Failure
is terminal evidence, not permission to retry.

## 5. Interpretation

If all strict gates pass, the result may be described only as a
post-incident, result-informed, exploratory two-component common-support proxy
contrast.  It cannot establish statistical significance, method superiority,
independent-ground-truth accuracy, a three-arm ranking, or a whole-system
comparison.  The official HFNet whole-system result remains unusable and
excluded, so component-vs-whole-system attribution is prohibited.

## 6. Frozen implementation identities

- verifier `scripts/verify_a02_two_arm_adoption_analysis_v2_5.py`, size 48415,
  SHA256 `325b6bd076870bcd18858bf74baf5ee628750731ad28a78c374d79bbe8a974b7`;
- builder `scripts/build_a02_two_arm_adoption_analysis_freeze_v2_5.py`, size
  5601, SHA256
  `be0bebc64b80059a1cb66887793cf5fb02d9a821efe5657c38009ea4f4bc0835`;
- tests `scripts/tests/test_verify_a02_two_arm_adoption_analysis_v2_5.py`, size
  15209, SHA256
  `49b2f809cc8edb43dcd54b7fdb0fc0e626012761a2a0149dcfb19a7b18e3ac66`;
- incident identity as specified in Section 2.

The canonical JSON freeze is the sole machine authority for the complete
static identity closure and exact commands.  The builder never executes
42R5--44C5.
