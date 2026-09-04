# P02 Candidate Capacity Decision

- `split_route`: `MULTI_SEQUENCE_CANDIDATE`
- `external_held_out_ready`: `false`
- `eligible_reference_sequences`: `28`
- `eligible_data_domains`: `4` (`AFRL stereo VI, AQUALOC archaeology, AQUALOC harbor, NTNU underwater VI`)
- `available_nonoverlap_45s_candidates_after_history_exclusion`: `89`
- `available_slots_after_per_sequence_cap`: `53`
- `capacity_sequences`: `18`
- `capacity_domains`: `4` (`AFRL stereo VI, AQUALOC archaeology, AQUALOC harbor, NTNU underwater VI`)
- `target_matrix_capacity`: `PASS at metadata/time level; final low/normal counts are deferred to P06 KLT-only screening`
- `APE_reference_caveat`: AQUALOC/AFRL references are offline image-derived COLMAP; NTNU references are ReAqROVIO pseudo-GT, not independent sensor truth.
- `external_boundary`: FLSea-VI has metadata only; no external image decode, frontend run, or learned/VINS result was performed in P02.
- `history_boundary`: exact windows present in `history_exclusion_manifest.csv` remain development-only; P06 must exclude overlaps before selecting candidates.

The capacity result is not a claim that 10 low and 10 normal windows exist. It proves only that the frozen P06 selector has enough eligible sequence/time slots to attempt the preregistered matrix without reusing exact historical windows.
