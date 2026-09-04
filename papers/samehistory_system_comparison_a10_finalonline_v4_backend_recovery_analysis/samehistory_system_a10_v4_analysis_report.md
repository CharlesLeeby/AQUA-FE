# A10 v4 backend-recovery analysis

Analysis state: `PREREQUISITES_FAILED_OR_INCOMPLETE`.

Evidence scope: `PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY`. Primary-paper evidence permitted: `false`.

Each backend ran in a fresh loopback-only network namespace. CPU, memory, I/O, and scheduler time were not machine exclusive.

## Prior-attempt provenance

The failed v3 Vanilla receipt remains `PROCESS_FAILED` and was not rerun. The v3 KLT/AQUA backend attempts remain unstarted; v4 uses only the accepted v3 KLT-adoption and AQUA-FE-build artifacts as frozen external inputs.

Source audit state: `PASS`.

## Backend acceptance and score usability

| System | Attempt | child RC | artifact | execution | score | score poses | span | max gap (s) |
|---|---|---:|---|---|---|---:|---:|---:|
| `vanilla_origin_native_image_context` | ACCEPTED | 0 | PASS | PASS | PASS | 200 | 0.995 | 0.104 |
| `klt_external_feature_context` | TERMINAL_FAILED | 0 | PASS | FAIL | PASS | 200 | 0.995 | 0.104 |
| `aquafe_external_feature_context` | ACCEPTED | 0 | PASS | PASS | PASS | 200 | 0.995 | 0.104 |

## Common support and descriptive accuracy

Common-support state: `WITHHELD_PREREQUISITES_NOT_PASS`.

Formal APE gate open: `False`; winner permitted: `False`.

Uniform grid: `20`; common matched: `None`; matched/20: `None`; matched/21 conservative index: `None`; exact 1 s RPE pairs: `None`.

Descriptive metrics are withheld because their preregistered prerequisites are not all satisfied.

## Mandatory disclosures

- v4 is a new backend attempt family; the failed v3 Vanilla attempt is retained and not rerun.
- The v3 KLT/AQUA backend launch allowances remain unconsumed; only accepted v3 frontend artifacts are inputs.
- Loopback-only network namespaces isolate ROS networking but do not provide machine-exclusive CPU scheduling.
- The formal APE gate is closed because 21 native reference poses and 20 uniform samples are below the frozen 30-pose minimum.
- Any released APE is a descriptive aligned proxy; any released RPE is descriptive only.
- No winner, rank, significance statement, or failure-as-zero comparison is permitted.
