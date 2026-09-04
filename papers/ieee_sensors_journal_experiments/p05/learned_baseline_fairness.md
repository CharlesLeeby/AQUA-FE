---
type: experiment-audit
date: 2026-08-04
experiment_line: isj-p05-modern-xfeat-baseline
round: 1
purpose: learned-baseline-fairness
status: PASS
source_artifacts:
  - fairness_audit.csv
  - fairness_audit.json
  - ../data_eligibility_manifest.csv
  - ../evaluator_protocol_v1.md
---

# P05 Modern XFeat Baseline / Fairness Audit / 2026-08-04

## Decision

P05 passes its export-only integration and fairness contract for a controlled
same-backend modern learned baseline, `M_xfeat_pairwise_nativeq_v1`. The baseline
is the official Apache-2.0 XFeat sparse matcher wrapped by the repository's
frame-to-frame pairwise persistent-ID adapter. It is methodologically separate
from the proposed KLT seed-chain/arbitration path: it does not use KLT
probation, learned-seed admission, the proposed microburst selector, or QG.

This is an adapter and export contract PASS, not a trajectory winner claim.
P07 must still run M and the frozen proposed/KLT arms on the outcome-blind P06
window manifest under the same VINS evaluator and replay reducer.

## Frozen Contract

- Input: the P02 eligibility manifest and its registered raw/reference paths.
- Image preprocessing: `adaptive_clahe`.
- Feature publication: every second selected frame (`every_n=2`); AQUALOC and
  NTNU use frame offset 1, AFRL uses offset 0 to match its existing wrapper.
- Maximum feature budget: 350 per published frame. Realized counts are not
  forced to match; the contract is equal maximum budget with complete count
  reporting.
- Backend quality: native `vins_safe`, floor `0.80`, alpha `0.65`; no global
  constant-q replacement is used in the main matrix.
- Measurement selection and semidense fallback: disabled.
- Sensor copy: the exporter carries the source IMU and available reference
  topics into the feature bag. Reference topics are audit metadata, not an
  input to the XFeat tracker.
- P07 replay: serial single-threaded VINS-Fusion-origin, three technical
  replays per window and arm, median reducer; replay is not an independent
  scientific sample.

## Probe Evidence

| Probe | Feature frames | Observations | Per-frame count (min/median/max) | q range | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| NTNU `fjord_1`, s83,d10, r1 | 100 | 25,013 | 221 / 251 / 278 | 0.827865-0.900440 | PASS |
| NTNU `fjord_1`, s83,d10, r2 | 100 | 25,013 | 221 / 251 / 278 | 0.827865-0.900440 | PASS |
| AQUALOC A06 `2210-2280` | 35 | 9,087 | 235 / 261 / 284 | 0.826630-0.899754 | PASS |
| AQUALOC H07 `1660-1720` | 30 | 7,554 | 192 / 258 / 296 | 0.827853-0.907188 | PASS |
| AFRL cemetery `0-10 s` | 75 | 24,715 | 0 / 334 / 342 | 0.832316-0.920000 | PASS |

The AFRL first published frame is intentionally zero-action because a pairwise
matcher has no previous image on its first frame. The audit requires every
subsequent frame to be nonzero; it does not hide this cold-start row.

All probes have source code `20` only, `is_learned=1`, camera id `0`, finite
point/channel values, positive sigma, no within-frame duplicate IDs, monotonic
feature timestamps, matching metrics row counts, and at least one copied sensor
topic. The maximum realized count is 342, below the frozen cap of 350.

The two NTNU exports are byte-identical at both bag and `frontend_metrics.csv`
level:

- bag SHA-256: `210ad894b16de75b10ce374f129f946d41ae5a04ab1f986442fc4d64be2f13de`
- metrics SHA-256: `13e04fef7565327bb3af26fc25189c8705414a578c58019a4c193f05a78715ea`

## Input and License Audit

The XFeat source is the local checkout of
`https://github.com/verlab/accelerated_features`, commit
`e92685f57f8318b18725c5c8c0bd28c7fe188d9a`, with the upstream Apache-2.0
license retained. The local weight file is recorded by SHA-256 in the method
lock. The AFRL adapter resolves the sequence-specific camera chain and image
topic (`cemetery`: `/cam_fl/image_raw/compressed`) and uses the documented 0.5
image scale. AQUALOC H06/H07 and A06 use the exact sample archives registered
by P02; the damaged H07 full-download placeholder is not silently substituted.

## Fairness Limits

The baseline is a local same-backend reproduction, not an official end-to-end
XFeat-VIO system. Its approximate IDs come from nearest-neighbor association
between consecutive pairwise matches; it has no KLT persistence probation. The
realized observation count is therefore naturally different from the proposed
seed-chain count even though the maximum budget, input window, backend, and
export schema are shared. This is why P07 must report realized dose and failure
denominators rather than claim equal-count matching.

No learned or VINS outcome was read from the P06 candidate pool during these
probes. All listed windows are history-excluded development smoke cases.

## Artifact Index

- Machine audit: [fairness_audit.csv](fairness_audit.csv) and
  [fairness_audit.json](fairness_audit.json).
- Baseline config: [isj_p05_xfeat_pairwise_nativeq.yaml](../../../uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml).
- Baseline runner: [run_p05_modern_xfeat_baseline.sh](../../../scripts/run_p05_modern_xfeat_baseline.sh).
- Audit implementation: [audit_p05_modern_xfeat.py](../../../scripts/audit_p05_modern_xfeat.py).
- Proposed candidate entry: [run_isj_nativeq_legacy_candidate.sh](../../../scripts/run_isj_nativeq_legacy_candidate.sh).

## Next Gate

P05 is complete for development integration. The next gate is P06: run the
frozen KLT/image-only selector, construct the held-out manifest and arm order,
then hand the manifest to P07 for first proposed/KLT/M trajectory evaluation.
The old QG candidate remains archived and is not promoted by this PASS.
