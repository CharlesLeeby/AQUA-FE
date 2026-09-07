# Classical additive opportunity expansion — evidence checkpoint

Status: COMPLETE; scientific decision: ADDITIVE_OPPORTUNITY_NOT_GENERALIZED.

1. New prospective C-all physical windows replayed: 12; replay attempts: 72.
2. Activated roster: 12 sequence-held-out / 0 window-held-out relative to the six C-all development windows; broader project exposure retained.
3. Full activated denominator: {"PRACTICAL_LOSS": 2, "PRACTICAL_GAIN": 3, "NOT_EVALUABLE": 1, "SMALL_OR_UNCERTAIN": 6}.
4. ROBUST_PRACTICAL_GAIN: 3.
5. Practical positive sequences: ["A04", "A07", "H02"].
6. Severe regression windows: 2.
7. Candidate dose/lifetime/initialization comparison with old A02/Bus: pending final case interpretation; exact new fields in case_registry.csv and old tables remain frozen.
8. Batch B activated: False. Exact unactivated windows remain in the registry.
9. Decision: ADDITIVE_OPPORTUNITY_NOT_GENERALIZED.
10. Case handoff: positive_cases.csv, neutral_cases.csv, negative_cases.csv, failure_cases.csv.
11. Next step: Transfer the retained positive/negative/initialization cases to observation-utility / risk-mechanism research; no automatic C-all tuning.

| Window | Batch | Class | Tier | B APE min / median / max (m) | C APE min / median / max (m) | Severe | Reason |
|---|---|---|---|---|---|---|---|
| coe1_a01_00000_00900 | A | PRACTICAL_LOSS | NONE | 0.114753 / 0.155037 / 0.155037 | 0.510393 / 0.554981 / 0.658114 | True |  |
| coe1_a03_00000_00900 | A | PRACTICAL_LOSS | NONE | 0.854467 / 0.858028 / 0.861665 | 2781.32 / 2854.46 / 2867.04 | True |  |
| coe1_a04_00000_00900 | A | PRACTICAL_GAIN | ROBUST_PRACTICAL_GAIN | 743.154 / 743.154 / 837.552 | 0.113788 / 0.113799 / 0.113804 | False |  |
| coe1_a05_00000_00900 | A | NOT_EVALUABLE | NONE | Not evaluated. | Not evaluated. | False | INVALID_COMMON_SUPPORT |
| coe1_a06_00000_00900 | A | SMALL_OR_UNCERTAIN | DIRECTIONAL_GAIN | 2.05039 / 151.786 / 183.492 | 0.948918 / 0.950726 / 0.970376 | False |  |
| coe1_a07_00000_00900 | A | PRACTICAL_GAIN | ROBUST_PRACTICAL_GAIN | 3.04255 / 3.04441 / 3.05375 | 0.173395 / 0.173396 / 0.173401 | False |  |
| coe1_a10_00000_00900 | A | SMALL_OR_UNCERTAIN | DIRECTIONAL_GAIN | 0.0598424 / 0.0600755 / 0.0604784 | 0.05649 / 0.0566184 / 0.0566204 | False |  |
| coe1_h01_00000_00900 | A | SMALL_OR_UNCERTAIN | NONE | 0.0707647 / 0.0707647 / 0.070898 | 0.0712008 / 0.0715236 / 0.0715518 | False |  |
| coe1_h02_00000_00900 | A | PRACTICAL_GAIN | ROBUST_PRACTICAL_GAIN | 0.103418 / 0.109392 / 0.110284 | 0.0293568 / 0.0294124 / 0.0294126 | False |  |
| coe1_h03_00000_00900 | A | SMALL_OR_UNCERTAIN | DIRECTIONAL_GAIN | 848.004 / 848.216 / 848.385 | 0.0714668 / 837.927 / 838.009 | False |  |
| coe1_h04_00000_00900 | A | SMALL_OR_UNCERTAIN | NONE | 0.168903 / 0.168906 / 0.168929 | 0.171104 / 0.171106 / 0.171399 | False |  |
| coe1_h05_00000_00900 | A | SMALL_OR_UNCERTAIN | NONE | 0.218332 / 0.218333 / 0.218334 | 0.218612 / 0.218613 / 0.218617 | False |  |
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
