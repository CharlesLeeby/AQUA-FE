# A02 formal900 r4 auditor mode false-negative adoption

## Status

The `r4` detector-birth namespace is consumed and immutable. Both frozen arm
commands were committed before either result existed. XFeat and GFTT each
started exactly once, ended naturally with return code 0, and published their
complete 900-published-frame / 1800-raw-frame artifact sets. The decision to
run GFTT was therefore precommitted by the freeze and pre-run absence receipt;
it was not made after inspecting either arm.

The frozen post-run auditor wrote an `ERROR` seal before scientific result
validation. Its active-tree snapshot applied mode `0444` uniformly to every
governed regular file. That is correct for freeze, command, attempt, launcher,
and seal records, but not for producer result roles. The frozen producer core
published feature bags, diagnostics, matched manifests, and legacy manifests
as mode `0664`. The immutable r3 probe PASS inventory records the same `0664`
mode for all eight corresponding result-role files. The r4 tree preserves this
same role split: governance/receipt files are `0444`, result files are `0664`.
The old `ERROR` is consequently an audit-infrastructure false negative, not a
scientific pair PASS or FAIL.

## Authorized continuation

This record may authorize exactly one invocation of
`scripts.audit_matched_birth_rawlk_pair_formal_r4_modefix_v1.py`, using the
machine permit's exact argv, environment, working directory, old ERROR seal,
and fresh write-once continuation seal at
`papers/a02_4500_6300_matched_birth_formal900_r4_modefix_continuation_seal_v1.json`.
The sole allowed predicate correction is the role-specific mapping `0444` for
governance/receipt files and `0664` for producer result files. Every frozen
scientific input, command, schedule, detector, threshold, audit gate, and
result byte remains unchanged.

No detector or producer rerun, retry, deletion, replacement, or chmod is
authorized. The old ERROR seal remains terminal and immutable. No VINS replay
is authorized unless the corrected auditor publishes a fresh strict PASS. A
corrected ERROR or FAIL does not authorize VINS.

## Outcome boundary

The machine builder reads result artifacts only to verify their held inode,
bytes, cross-bindings, one-shot process status, and full schedule. Its permit
exposes only exact inventory, governance facts, the mode correction, and the
single corrected-audit authorization. It contains no detector outcome values,
relative arm comparison, winner, trajectory metric, or whole-SLAM claim.
