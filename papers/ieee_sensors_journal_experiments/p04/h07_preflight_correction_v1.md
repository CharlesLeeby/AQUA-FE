# P04 H07 preflight correction v1

Date: 2026-08-05
Status: `P04_H07_INTERFACE_DIAGNOSTIC_ONLY`
Supersedes machine interpretation: `P04_PREFLIGHT_PASS_H07_ONLY`
Outcome boundary: frontend records only; no VINS, APE, RPE, or trajectory
outcome was read.

## Correction

The H07 replay artifacts are deterministic interface diagnostics, but they do
not satisfy the formal P04 native-q common-producer contract.

The normalizer used for those artifacts,
`scripts/normalize_p03_master_stream_v4.py`, assigns `raw_quality` from the P03
`q_lower` field and falls back to `1.0`. The P03 field is a calibrated lower
bound, not independent raw frontend quality. The same normalizer also has no
independently cross-linked publication evidence for publication timestamps,
pixel coordinate space, published base IDs, or the P03 learned/classical pool
hashes.

The strict replacement adapter,
`scripts/p04_nativeq_master_adapter_v4.py`, fails closed unless every source
observation has explicit `RawQualityEvidence` and every event has a complete
`PublicationEvidence` envelope. Its repository regression test confirms that
the existing P03 JSONL cannot be silently upgraded into formal P04 v4 input.

## Artifact disposition

- Keep every file under `p04/h07_1660_1720/` and the original ledger event.
- Treat the byte-identical H07 normalized streams and replay bundles only as
  evidence that the pure P/C/B2 replay interface is deterministic.
- Do not count `contract_audit_v1.json` as a formal P04 probe PASS, a physical
  common-producer attempt, or evidence for G3.
- Do not use the H07 normalized stream as formal input to P07.

## Required replacement evidence

P04 remains `IN_PROGRESS`. A new versioned producer must emit, during fresh
development-only physical attempts, all of the following before P04 or G3 can
pass:

1. independent raw-quality evidence for every K0, learned, and classical
   observation;
2. a publication envelope cross-linked to the P03 master/classical pool hashes;
3. common frame, preprocessing, trigger, K0, base-only F/H, budget, admission,
   publication, and native-q contracts for P, C, and B2;
4. two deterministic attempts for A03 and NTNU, with zero-action supply retained
   rather than replaced;
5. no VINS, APE, RPE, or trajectory artifact in the P04 bundle.

## Verification

The strict adapter and arm replayer targeted suite contains 17 passing tests,
including explicit rejection of raw P03 JSONL without the missing evidence,
source-neutral native-q mapping, pool independence, active/total budget
enforcement, exact drop, and deterministic replay.

This correction does not change the frozen native-q candidate-v3 scientific
hash and does not alter any P03, P06, exporter, or H07 diagnostic artifact.
