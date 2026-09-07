# Classical additive opportunity expansion — evidence checkpoint

Status: IN_PROGRESS; scientific decision: Unknown.

1. New prospective C-all physical windows replayed: 4; replay attempts: 24.
2. Activated roster: 12 sequence-held-out / 0 window-held-out relative to the six C-all development windows; broader project exposure retained.
3. Full activated denominator: {"PRACTICAL_LOSS": 2, "PRACTICAL_GAIN": 1, "NOT_EVALUABLE": 1, "PENDING": 8}.
4. ROBUST_PRACTICAL_GAIN: 1.
5. Practical positive sequences: ["A04"].
6. Severe regression windows: 2.
7. Candidate dose/lifetime/initialization comparison with old A02/Bus: pending final case interpretation; exact new fields in case_registry.csv and old tables remain frozen.
8. Batch B activated: False. Exact unactivated windows remain in the registry.
9. Decision: Unknown.
10. Case handoff: positive_cases.csv, neutral_cases.csv, negative_cases.csv, failure_cases.csv.
11. Next step: Complete the frozen active batch and registered decision; no tuning or substitutions.

| Window | Batch | Class | Tier | B APE min / median / max (m) | C APE min / median / max (m) | Severe | Reason |
|---|---|---|---|---|---|---|---|
| coe1_a01_00000_00900 | A | PRACTICAL_LOSS | NONE | 0.114753 / 0.155037 / 0.155037 | 0.510393 / 0.554981 / 0.658114 | True |  |
| coe1_a03_00000_00900 | A | PRACTICAL_LOSS | NONE | 0.854467 / 0.858028 / 0.861665 | 2781.32 / 2854.46 / 2867.04 | True |  |
| coe1_a04_00000_00900 | A | PRACTICAL_GAIN | ROBUST_PRACTICAL_GAIN | 743.154 / 743.154 / 837.552 | 0.113788 / 0.113799 / 0.113804 | False |  |
| coe1_a05_00000_00900 | A | NOT_EVALUABLE | NONE | Not evaluated. | Not evaluated. | False | INVALID_COMMON_SUPPORT |
| coe1_a06_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a07_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a10_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h01_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h02_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h03_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h04_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h05_00000_00900 | A | PENDING | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a01_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a03_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a04_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a05_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a06_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a07_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_a10_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h01_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h02_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h03_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h04_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |
| coe1_h05_00900_01800 | B | NOT_ACTIVATED | NONE | Not evaluated. | Not evaluated. | False |  |

COLMAP/proxy is not independent GT. C-all is a classical opportunity probe, not the final AQUA-FE innovation. Technical repeats and neighboring windows are not independent population samples.
Every valid comparison uses its own six-trajectory common support and the frozen additive criteria. Fitted scale is diagnostic. Missing/invalid comparisons are never replaced by per-arm unmatched APE.
Candidate-set positives/negatives are not per-feature utility labels. Actual residual blocks may reuse an observation across optimization calls.
Source and execution identities: source_and_backend_lock.json, backend_execution_lock_v2.json, evaluation_lock.json. Raw bags and full console logs remain under the isolated runtime root.
