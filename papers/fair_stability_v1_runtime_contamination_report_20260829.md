# Fair-stability v1 runtime-contamination report

Date: 2026-08-29 (Asia/Shanghai).  Parent protocol:
`fair_stability_positive_roster_protocol_v1.md`.

## Decision

The partial experiment in
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v1`
is retained as an immutable diagnostic record but is superseded for formal
stability comparison.  No v1 outcome may be used for an algorithm-stability
ranking.  A fresh v2 namespace must restart at ordinal 1.

## Proven overlap

Ordinal 6 was `a07_10800_11200 / hfnet_openloop_675 / repeat 1`.

- The frozen HFNet runner claimed and launched the attempt at
  `2026-08-29T06:35:49+00:00`.
- The supervised HFNet process ended at `2026-08-29T06:36:38+00:00` after
  49.4308 s, with raw return code `-6`, no successful initialization, and no
  valid trajectory.
- External PID 3173728 had Linux start ticks 59913603, corresponding to
  `2026-08-29T06:35:55.04+00:00`.  It was an independent
  `uw_frontend.ros.export_vins_features` process in the
  `mimir_rate1_fairsched_v2` chain.  Its command-line SHA-256 was
  `7357bc5ec82bb42abdefbfe5736cb8e6dd46291b5840f5fab54fe25ad1a7d8f9`.
- The external exporter was therefore alive during at least the final 43 s of
  the HFNet attempt.  A post-attempt `nvidia-smi` observation reported that PID
  as a compute application using 1622 MiB.
- HFNet stderr ended with a pthread priority assertion.  That observation does
  not identify whether the abort was intrinsic or contention-triggered; the
  proven overlap is sufficient to make causal attribution invalid.

Persistent artifacts in
`logs/mimir_uw_vins/mimir_rate1_fairsched_v2_oceanfloor_track0_dark_s45_d45_ours_export`
provide an independent timeline cross-check.  `vins_output` was created at
`2026-08-29 14:35:54.891993700 +0800`; `mimir_cam0_pinhole.yaml` was written at
14:35:55.029572500 and has SHA-256
`26893f9d567f50e0a6b8401e4a42c234c1f396c9ee6343e31c1d1cb2c130c3b2`;
`vins_mimir_external.yaml` has SHA-256
`655fdcab8daf0e677c7b07c33e5f11777ede5f565bebe54034e4caad04c133e7`;
and its manifest has SHA-256
`2c8262c001577a6784c38ddd17754770e686a150ffa2a0c5ce2ee0de305737e8`.
These are corroborating timeline records, not evidence that contention caused
the abort.

Evidence identities:

| Artifact | SHA-256 |
|---|---|
| ordinal-6 attempt manifest | `4c87931b27868bccf9278fc2f34c20c12bb4ef5c054efb1e72de2aadf697d642` |
| start claim | `767c9d7f50a02c3db9b7b8174fe1aab23e4a86ea7e212483a092b25db52e96f7` |
| launch receipt | `3448a42d92663cf196d4b1f09770d8a7c3f5844ff64abdec4c2487fb67fcf6db` |
| run result | `9015f3937e248e8a36729798eac88643aafdc8eb4b11e48748518ed65799b0bc` |
| terminal receipt | `2b9ef89b8421771bd279799943ecbc68990379be1f48cf8de2ec52163125448f` |
| HFNet stderr | `e02e6c231bba5471df90a1d1220501c964aba63115b5cb83e6b152e89d165472` |

## Scope of invalidation

The v1 pre-start resource gate worked correctly, but the runner did not sample
resource ownership throughout estimator execution.  Ordinals 1--5 have no
known conflicting process and remain useful diagnostics, but absence of a
mid-run intrusion was not positively recorded.  They are not imported into v2.
Ordinal 6 is positively contaminated.  Ordinal 7 was blocked before start and
has no dispatch, start claim, or result.

The correction is prospective: v1 files are not deleted or rewritten.  v2 adds
continuous runtime intrusion evidence and starts all 120 planned cells again.
