# A08 XFeat attempt002 terminal forensic audit v1

Status: **terminal method failure; no retry and no backend authority**.

This note records a read-only forensic examination performed after the sole
attempt002 XFeat supervisor had terminated.  It does not amend the frozen
frontend protocol, accept a failed artifact, authorize another frontend
attempt, or authorize VINS-Fusion.  Accuracy was not computed or inspected.

## Terminal authority

The authoritative failure receipt is
`/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/frontends_v1/xfeat_attempt002_export_failure_v1.json`:

- size: 4,017 bytes;
- SHA-256: `15eaad3e5b02f54b4f141db416e9b1db868bea15fcb66fe8bee11318765df22c`;
- status: `FAILED_NO_AUTOMATIC_RETRY`;
- qualified status: `FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT`;
- error: `FEATURE_POINT_COUNT_RANGE`;
- `vins_or_accuracy_executed=false`.

The process-start claim is 149,433 bytes with SHA-256
`a8d0828f9117c077b0bcef80b60d945478f6f2856d1dbe66bab43311d2698707`.
The supervisor log is 11,417 bytes with SHA-256
`23fc5398f991e04d6050005be4ed8c909e7ee6b98609abfc09c8cb4b522decb0`.

## Exact structural violation

The method-native probe bag contains 2,330 feature messages.  Exactly one
message exceeds the frozen maximum of 350 points:

- zero-based feature-message index: 3;
- source `frame_index`: 7;
- exact bag header and record timestamp: `1542884961494887216 ns`;
- point count: 352;
- source-code histogram: 339 code-1 KLT, 11 code-2 GFTT, and 2 code-20
  XFeat points;
- learned-flag histogram: 350 classical and 2 learned points.

Thus the violation is the addition of two learned XFeat observations beyond
the 350-point export capacity.  It is not a ROS bootstrap failure, ToDesk
interference, a partial bag, or a failure of the final fallback exporter.

Probe identities:

- `features.bag`: 70,140,496 bytes, SHA-256
  `fcaa39bebfe9ef9f9dbaa720386a5e05367818fba9085c9d2b81fed59d5a4541`;
- `frontend_metrics.csv`: 1,452,927 bytes, SHA-256
  `3a71e46077f31e8be18b4e2c6f47875ab55b81b6f69f50a05fb10836b438462d`;
- camera YAML: 357 bytes, SHA-256
  `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5`.

## Method-native final fallback

The frozen arbitration selected `klt_safe_fallback`.  Its final export
completed naturally with 2,330 feature messages, source frame 4659 last, and
350 points in every message.  Nevertheless it is not an accepted XFeat arm,
because the frozen method contract audits both the probe and the selected
final branch and the probe failed.

The final fallback is byte-for-byte identical to the independently accepted
KLT control for all three backend inputs:

| artifact | size (bytes) | shared SHA-256 |
|---|---:|---|
| `features.bag` | 70,811,242 | `0a33248739ec3f02df26b8f784b469afa37c6bbc172461d67b2a91a82b10843a` |
| `frontend_metrics.csv` | 1,259,980 | `7deda4bd28a0e22b0fa87be111239df2219d2e3a00d0c34b4ac47bf9ff4ff305` |
| camera YAML | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |

Consequently, replaying this fallback under an XFeat label would neither
repair the structural failure nor provide evidence of learned-feature
contribution.  The original ten-item backend campaign must remain locked:
its read-only preflight reports
`WAITING_FOR_BOTH_ACCEPTED_FRONTEND_RECEIPTS`, with the KLT receipt present,
the XFeat accepted receipt missing, the final execution lock absent, and all
ten items unstarted.

Any later KLT-only replay campaign must use a separately frozen protocol,
lock, output root, and authorization tokens.  It must bind this terminal
failure evidence, report the XFeat arm as `NA`, and must not reinterpret the
fallback as learned-system accuracy.
