# A02 matched detector-birth probe16 audit incident (r2)

## Status

The ext4 `r2` namespace is permanently retired and must not be deleted, modified, completed, or reused. Its outcome-blind freeze and pre-run start check passed. The XFeat and GFTT prefix producers each started exactly once and ended naturally with return code 0. The sole post-run failure was an auditor false negative:

`XFEAT_BIRTH_RAWLK_MATCHED_V1 legacy formal eligibility reason mismatch`

Both the matched and legacy prefix manifests correctly record `status=PREFIX_NONFORMAL`, `formal_eligible=false`, and `formal_eligibility_reason=explicit_prefix_is_nonformal`. The frozen auditor nevertheless unconditionally required the two full-export reasons in its legacy cross-binding function. That predicate is correct for `formal900` but not for `probe16`.

## Scientific boundary

This incident does not establish a passed pair audit and the r2 outputs are not adopted as formal evidence. It also does not authorize any detector, carrier, preprocessing, input, schedule, cap, threshold, backend, or evaluator change. The continuation changes only the mode-aware audit mapping and additive incident/namespace governance. The next prefix run must use a fresh ext4 `r3` namespace and the same frozen scientific settings.

No VINS process, evaluator, formal900 producer, or scientific retry was started from r2. The dedicated Python bytecode prefix remained absent.

The observed post-audit return code (`2`) comes from the orchestrator transcript, because r2 had no independent post-audit launcher/RC receipt. The error predicate itself is independently preserved by the mode-0444 error seal. The frozen auditor source identity is recorded by the r2 freeze. Its retained CPython 3.8 bytecode has been copied once into the independent mode-0444 evidence file `a02_4500_6300_matched_birth_auditor_at_failure.cpython-38.pyc`; the machine-readable incident pins that copy for mechanical inspection of the historical branch. The root-cause statement is therefore a mechanically checked bytecode inference, not a claim that the missing source bytes were reconstructed.

## Retention policy

- Preserve the complete r2 tree byte-for-byte, including the error seal.
- Never rerun an r2 launcher or audit command.
- Validate the complete r2 tree before building, checking, or auditing r3.
- Treat the error seal as a terminal audit-infrastructure record, not as a scientific PASS or FAIL.
- Keep the earlier fuseblk r1 incident and orphan unchanged.
