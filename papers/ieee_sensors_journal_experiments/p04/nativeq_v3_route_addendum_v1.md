# Native-q v3 route addendum v1

Date: 2026-08-06  
Status: `FROZEN_FOR_P06_FINALIZATION`  
Machine contract: `p04/nativeq_v3_route_contract_v1.json`  
Contract hash: `b8d673057432b9b9f34f0d41d0a254375ac9d9d930b9ef5d2ee4efb077c5bfeb`  
Outcome boundary: `P04_FRONTEND_CONTRACT_ONLY_NO_VINS_APE_RPE_TRAJECTORY`

## Scope

This addendum narrows the July P04/P06/P07 arm contract for the retained
`isj-nativeq-legacy-candidate-v3` method. It does not change the frozen v3
frontend, the native-q mapping, the evaluator, or the outcome-blind P06 window
selection rule.

The strict common-K0 learned/classical control is not identifiable under v3.
Confirmed learned tracks enter the tracker's state before later KLT tracking,
replenishment masks, trigger opportunities, and ID allocation. A source swap
therefore cannot guarantee the same future carrier. This disposition is a
contract limitation, not a claim that every window must numerically diverge.

## Frozen arm matrix

Every confirmatory window has these required arms:

- `B0_native_vins_origin_v1`;
- `B1_klt_nativeq_v3`;
- `P_legacy_nativeq_xfeat_seedchain_v3`;
- `M_xfeat_pairwise_nativeq_v1`.

`D_legacy_exact_lineage_drop_v3` is the only conditional arm. No confirmatory
slot is created for `C_legacy` or `B2`.

- `C_legacy` is retired because v3 cannot provide the strict common-carrier H2
  contrast. Development classical-positive, mixed, and zero-supply results
  remain mandatory diagnostics without causal language.
- `B2` is retired as a scope decision. New pre-admission instrumentation could
  recover an admission ablation, but the current paper makes no clean
  admission-only claim.
- `H2_CONTROL_CONTRACT=NOT_APPLICABLE_CARRIER_FEEDBACK`; the paper reports H2
  as `INCONCLUSIVE_NOT_TESTED_UNDER_FROZEN_V3`, not PASS and not a missing row.

The external-feature arms share a maximum budget of 350. Equal maximum budget
does not imply equal realized observation count. No `min_gain`, dose matching,
or post-outcome balancing is introduced by this addendum.

## D applicability

Applicability is resolved after the frozen P export and before any trajectory,
APE, or RPE is read:

1. Count learned-born lineages accepted into the published P stream.
2. If the count is zero, append `D_legacy=NOT_APPLICABLE` and do not create a
   replay slot.
3. If the count is positive, append `D_legacy=APPLICABLE`, delete every
   observation of every learned-born ID, and run the frozen whole-lineage
   audit before backend replay.
4. An audit failure blocks D and marks the H3 contrast ineligible as a contract
   failure. It cannot be repaired after reading an outcome or replaced with a
   seed-only deletion.

D holds the learned-conditioned carrier fixed and estimates only the direct
backend exposure effect of the published learned-born lineages. It is not a
counterfactual removal of the complete learned frontend.

The development NTNU audit is an exact contract PASS: P and D contain 6300
aligned messages; all 6000 non-feature messages are byte-identical; learned
IDs 662, 663, and 664 contribute eight removed observations across three
frames; and every retained feature payload is unchanged. The report is
`p04/ntnu_fjord1_s83_d30_whole_lineage_exact_drop_audit_v1.json`.

## Execution guards

- P enters through `scripts/run_isj_nativeq_contract_guarded_v4.sh`.
- M enters through `scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh`.
- Reused M bags require a contract-, producer-, metrics-, and bag-SHA-bound
  P05 attestation.
- A P or M consumer mismatch cannot count as that arm. The independent KLT
  fallback receives no learned bag and is labelled as an operational fallback.

The A03 `5000-5900` actual-v3 export attempt is retained only as a zero-action
diagnostic. It produced 450 feature frames over 44.892 s, 282 learned
candidates and 126 confirmed track instances, but zero published XFeat
observations. Arbitration selected `klt_safe_fallback`, and the probe/final
feature bags are byte-identical with SHA-256
`d34d9730d7496b03ccff18c58cc6e6badce748ca11a61d0042797a3532a1c6be`.
It is not a learned-positive, H2, trajectory, or confirmatory result.

## P06/P07 amendment

After this contract is included in the next candidate method lock, the guarded
P06 builder may create the 10-low/10-normal outcome-blind manifest exactly
once. The subsequent `arm_order.csv` must include only B0, B1, P, and M in the
unconditional counterbalanced order, plus a separately identified conditional
D dependency. It must not allocate C or B2 replay rows.

P07 resolves D applicability from P's frontend artifacts before opening any
trajectory result. Each applicable frozen feature bag still receives three
serial backend replays; replay is a technical repeat and the scientific unit
remains the sequence. Primary inference remains sequence-equal 1 s translation
RPE on G0 common support. All failures and zero-action windows remain in their
predeclared denominators.

This addendum supersedes only conflicting C/B2/H2/D arm clauses in the July
execution documents. All other evaluator, held-out, no-harm, failure, replay,
and reporting contracts remain in force.
