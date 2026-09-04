# A09 same-history warm-start v1 frontend protocol

Status: frozen before frontend execution; development-only evidence.

## Purpose and boundary

This protocol builds two method-native feature streams from the already frozen
AQUALOC archaeological sequence 09 raw history `0..4400`:

1. a KLT/GFTT mirror backbone published every two source frames; and
2. the frozen causal XFeat lineage sidecar applied from the first KLT feature
   message, without resetting at the `4000..4400` score window.

This stage does not start VINS, HFNet, or any other SLAM backend. It produces no
trajectory or accuracy result and is not formal paper evidence. The user has
explicitly allowed ToDesk and ordinary desktop processes to remain active for
this development diagnostic; consequently no runtime or throughput claim is
permitted.

## Frozen raw authority

Downstream code must use the committed path, not the stale staging spelling in
the original raw receipt:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/raw/archaeo09_0000_4400.bag`

- size: 1,187,038,470 bytes;
- SHA-256: `a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97`;
- camera / IMU / proxy-GT: `4401 / 44025 / 213`;
- raw receipt SHA-256: `b6f0ec00f04d5c62514b96b3ce591bc561221227ea05163793fc68d8c4d3cf91`;
- canonicalization addendum SHA-256: `86e82d58dbd85f39907144aa1098352b97282c143fef5259cacd2974c4ca0956`;
- raw freeze SHA-256: `d72dcef75052194a8e48a8e14da5233412345b66a60b7c53e93e4650779cfa57`.

The raw receipt, addendum, and freeze remain immutable. The frontend runner
rehashes all pinned inputs before each stage and again before accepting output.

## KLT stage

The frozen science child is:

```text
/usr/bin/bash scripts/run_paper_sidecar_profiles.sh \
  aqualoc_archaeo_loftr_mirror_klt 9 0 4400
```

The environment fixes `RUN_VINS=0`, `FORCE_RAW=0`, `FORCE_EXPORT=1`,
`FRAME_OFFSET=1`, `PROCESS_SKIPPED_FRAMES=1`, `MEASUREMENT_SELECTION=0`,
`EXPORT_MAX_FEATURES=350`, source-aware backend quality with alpha `0.85` and
floor `0.80`, and two BLAS/OpenMP threads. The learned fallback is disabled.

Accepted output directory:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/frontends/klt_export`

Required scientific outputs are `features.bag`, `frontend_metrics.csv`, and
`aqualoc_archaeo09_pinhole.yaml`. The feature stream must contain 2,200
PointCloud messages bound exactly to raw source frames `1,3,...,4399`; the first
and last feature timestamps are
`1542888746121190768 / 1542888965985217392` ns. The score subset contains 200
messages for source frames `4001..4399`, with first timestamp
`1542888946088258928` ns. The copied IMU and GT streams must be serialized-byte
equivalent to raw.

Every feature message must contain exactly 350 finite classical observations,
the frozen 13-channel schema, unique IDs below 10,000,000, source code 1 or 2,
`is_learned=0`, quality in `[0.8,1]`, and the frozen sigma transform. The metrics
CSV must contain 2,200 rows, 141 columns, header SHA-256
`7afdc87e9515a88a83e4c7560042b3013f9dce303f77da2f40e6c6fcab846e83`,
and exact row-to-feature timestamp binding. Learned export columns must remain
zero.

## Causal AQUA-FE stage

The frozen producer is
`/usr/bin/python3.8 -m uw_frontend.ros.xfeat_seed_sidecar_node bag` with
`low_texture_lineage_safe_dense_start_frontend.yaml` and the complete parameter
vector embedded in the frozen runner. It consumes the accepted KLT bag and raw
image bag from their first messages. The selector requires 10 observations,
ranks at 5, permits at most one causal lineage, and uses remapped IDs beginning
at 10,000,000. No outcome-dependent retry is allowed.

Accepted output directory:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/frontends/aquafe_finalonline`

Required outputs are `full_merged.bag`, `sidecar.bag`, and `stats.csv`.
`full_merged.bag` must retain 2,200 feature messages plus the exact 44,025 IMU
and 213 GT messages. Each merged feature must preserve all 350 KLT points and
channel values exactly, then append zero or one observation with source 20,
`is_learned=1`, and a remapped ID. The whole run may use at most one remapped
lineage. `sidecar.bag` must contain 2,200 timestamp-aligned candidate messages.
`stats.csv` must contain 2,200 rows, 31 columns, header SHA-256
`f9ea50d9fb582d076bd22278d02111d021f73b1ebe346c5aadaaeaed2ca9fb36`,
and exact selector/frame binding.

Final learned action is authoritative only when three sources agree per frame:
the stats injection flag, the merged-minus-base suffix length, and suffix source
20 / learned flag 1. Full, prefix (`0..1999` method rows), and score
(`2000..2199`) counts are reported separately. Zero score-window action is a
valid frozen outcome and must not trigger a rerun.

## One-shot and failure semantics

Both stages share one `/mnt` flock. Canonical outputs, staging paths, failure
paths, and the KLT workspace link must be absent before their respective stage.
The runner writes an exclusive process-start claim before one `Popen`, starts a
new process session, enforces timeouts of 9,000 s for KLT and 3,600 s for XFeat,
waits for terminal return code, performs full artifact audit, and only then
atomically publishes the real output directory. A failed stage is retained
under a distinct failure directory and is never retried automatically.

To keep child argv paths canonical while retaining atomic publication, the
canonical directory name is temporarily a symlink to the unpublished staging
directory. It is removed and replaced by the audited real directory at commit.

## Frozen implementation identities

- runner: `scripts/run_a09_samehistory_warmstart_v1_frontends.py`, 37,468 bytes,
  SHA-256 `e9be49b75747f2421c5d4016fbbf88c22cef0892e544034535b4b71307e4c5a1`;
- KLT profile: SHA-256 `266e3c6f0c57eaae0555e1918298d450d9452794569de83de83700f8bae87130`;
- AQUALOC runner: SHA-256 `9da109074d559875434bc82e43febd7acf1e60c027f11bae31023e6d08198a9b`;
- exporter: SHA-256 `567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d`;
- causal XFeat producer: SHA-256 `9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7`;
- lineage selector: SHA-256 `8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727`;
- stock XFeat checkpoint: 6,247,949 bytes, SHA-256
  `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b`.
