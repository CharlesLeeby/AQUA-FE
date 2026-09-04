# Same-history system comparison v1: strict descriptive audit

State: `TERMINAL_DESCRIPTIVE_FORMAL_ACCURACY_BLOCKED`

Formal accuracy is blocked for both windows. Each has only 13 native same-image COLMAP proxy rows; no winner, significance test, failure penalty, or cross-window mean ranking is permitted.

## Usability and learned action

| Window | Method | State | Usability | Native score support | Learned full / preroll / score |
|---|---|---|---|---:|---:|
| A06 | vanilla_origin | TERMINAL | PASS | 125/125 (1.000) | n/a / n/a / n/a |
| A06 | external_klt | TERMINAL | PASS | 125/125 (1.000) | 0 / 0 / 0 |
| A06 | aquafe_proposed_safe | TERMINAL | PASS | 125/125 (1.000) | 0 / 0 / 0 |
| A06 | hfnet_slam | SEALED_TERMINAL | PASS | 251/251 (1.000) | n/a / n/a / n/a |
| H07 | vanilla_origin | TERMINAL | PASS | 31/31 (1.000) | n/a / n/a / n/a |
| H07 | external_klt | TERMINAL | PASS | 31/31 (1.000) | 0 / 0 / 0 |
| H07 | aquafe_proposed_safe | TERMINAL | PASS | 31/31 (1.000) | 0 / 0 / 0 |
| H07 | hfnet_slam | SEALED_TERMINAL | PASS | 61/61 (1.000) | n/a / n/a / n/a |

## Frontend payload identity gate

- A06 `external_klt` features.bag: size_bytes=`37403698`, SHA-256=`0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6`, exists=`True`.
- A06 `aquafe_proposed_safe` features.bag: size_bytes=`37403698`, SHA-256=`0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6`, exists=`True`.
- A06 payload_byte_identical: `True`; action: `NO_ACTION_BYTE_IDENTICAL_TO_KLT`; proposed exported learned full total: `0`.
- A06 learned pipeline activity (summed diagnostics only): observed=`True`, learned_candidate_count=`1021`, pre_gate_sidecar_total=`2921`, learned_export_gate_dropped=`2921`. These repeated per-frame counts are not independent samples and are not exported learned action.
- A06 backend_run_nondeterminism_observed: `True`; trajectory_difference_not_attributable_to_frontend: `True`; learning improvement attribution: `PROHIBITED_PAYLOAD_BYTE_IDENTICAL`.
- A06: the feature payload bytes are identical while selected VIO SHA-256 differs. This is backend-run nondeterminism evidence; the trajectory difference cannot be credited to the learned frontend.
- H07 `external_klt` features.bag: size_bytes=`26259535`, SHA-256=`45659eb766a29b6671e77108f181bad58a27d47f6487e2c770fd2f98b51c0630`, exists=`True`.
- H07 `aquafe_proposed_safe` features.bag: size_bytes=`26259535`, SHA-256=`45659eb766a29b6671e77108f181bad58a27d47f6487e2c770fd2f98b51c0630`, exists=`True`.
- H07 payload_byte_identical: `True`; action: `NO_ACTION_BYTE_IDENTICAL_TO_KLT`; proposed exported learned full total: `0`.
- H07 learned pipeline activity (summed diagnostics only): observed=`True`, learned_candidate_count=`650`, pre_gate_sidecar_total=`1954`, learned_export_gate_dropped=`1954`. These repeated per-frame counts are not independent samples and are not exported learned action.
- H07 backend_run_nondeterminism_observed: `True`; trajectory_difference_not_attributable_to_frontend: `True`; learning improvement attribution: `PROHIBITED_PAYLOAD_BYTE_IDENTICAL`.
- H07: the feature payload bytes are identical while selected VIO SHA-256 differs. This is backend-run nondeterminism evidence; the trajectory difference cannot be credited to the learned frontend.

## A06 external-KLT infrastructure incident

- The original wrapper invocation was infrastructure-censored by its outer 1800 s supervisor timeout after the frozen frontend export but before the score window.
- Original incident state: `VALID_INFRASTRUCTURE_CENSORED_INCIDENT`; algorithm failure: `False`; partial trajectory scored: `false`.
- Corrective adoption state: `ADOPTED_EXACT_BACKEND_ONLY_CORRECTIVE_REPLAY`; adopted: `True`.
- The corrective run is a backend-only replay of the exact frozen feature bag; it neither rewrites the original namespace nor counts as an independent method repeat.

## Accuracy gate

- A06: `BLOCKED_FORMAL` — COMMON_MATCHED_ROWS_LT_30, REFERENCE_NATIVE_ROWS_LT_30
- H07: `BLOCKED_FORMAL` — COMMON_MATCHED_ROWS_LT_30, COMMON_SPAN_LT_10S, REFERENCE_NATIVE_ROWS_LT_30, RPE_PAIRS_LT_10

## Mandatory disclosures

- A06 external_klt original replay was infrastructure-censored before score; only the exact frozen-feature backend corrective namespace may be adopted, and the immutable partial output is never scored
- vanilla_origin is the pinned native-image context control from the local quality-capable checkout, not a byte-identical pristine upstream Vanilla VINS-Fusion
- camera-history matched / IMU API support differs
- external AQUA-FE arms export at 10 Hz while HFNet camera/backend is 20 Hz
- origin sees 20 Hz images but MT1 queues every second tracker feature frame
- Candidate/pre-gate/gate-drop sums are repeated per-frame pipeline diagnostics, not independent samples or exported learned action
- Byte-identical external_klt and proposed feature bags prohibit attributing any VIO difference to the learned frontend
- VINS online outputs and HFNet final-map trajectory semantics differ
- reference is a same-image COLMAP depth-scale proxy, not sensor-independent GT

No figures were generated by this audit.
