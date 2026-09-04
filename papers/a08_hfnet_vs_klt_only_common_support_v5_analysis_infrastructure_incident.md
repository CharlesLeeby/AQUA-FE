# A08 HFNet-vs-KLT analysis-v5 infrastructure incident

Status: read-only sidecar incident record. This file is outside the canonical
analysis output and is not a terminal receipt, a recovery authorization, or a
formal accuracy result.

## Disposition

`NA_ANALYSIS_INFRASTRUCTURE_CLAIMED_WITHOUT_TERMINAL_FUSEBLK_RENAMEAT2_NOREPLACE_EINVAL_NO_RETRY`

The single analysis-v5 allowance was consumed. Recalculation, retry,
replacement analysis, post-hoc promotion of staged numbers, and best-repeat
selection are forbidden. No staged APE/RPE value is admissible as the formal
A08 HFNet-vs-KLT ranking.

## Accepted backend evidence

The backend-v5 control campaign itself completed successfully and remains
valid:

- `KLT_R04`: `PASS_BACKEND_REPLAY_ACCEPTED`, 2319 poses, artifact contract
  `PASS`, execution integrity `PASS`, one supervisor `Popen`, zero retries.
  Receipt: 16400 bytes,
  SHA-256 `3c4cad4861096627bbc7d0c3ac413e54d08f38c725789ee7ba229792cb438aaf`.
- `KLT_R05`: `PASS_BACKEND_REPLAY_ACCEPTED`, 2319 poses, artifact contract
  `PASS`, execution integrity `PASS`, one supervisor `Popen`, zero retries.
  Receipt: 16400 bytes,
  SHA-256 `09d6fa109bda249e76800c0bc287e852dbae1df457c80939406498a7ed2d68fb`.
- The original five-slot population remains fixed. `KLT_R01`, `KLT_R02`, and
  `KLT_R03` are permanent infrastructure NAs with no rerun or replacement;
  the valid KLT count is two of five.

Frozen authorities:

- analysis-v5 static design freeze: 35773 bytes,
  SHA-256 `579b5fda3c6e4e00e65395352efd4297c2e7ace03d8c774cd674e5e2a0ae8b14`;
- backend-v5 execution lock: 103900 bytes,
  SHA-256 `272d2091cf27b6c89cabb946ed24f7facf274174c14242e7803302f9ed8a421c`;
- analysis-v5 dynamic execution lock: 54536 bytes,
  SHA-256 `4331eb29632ce6c850e9b03a3431f0133d867b2c7a064883acab2e80b1eae49b`.

## Single analysis attempt

The canonical claim was published and is immutable:

- path:
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/hfnet_vs_klt_only_common_support_start_claim_v5.json`;
- identity: 795 bytes,
  SHA-256 `b31221720c8ed89c49e04a68aefd469be9d4994128364ac97dd2609c2bbb540c`;
- status: `CLAIMED_SINGLE_ANALYSIS_ALLOWANCE_CONSUMED_NO_RETRY`.

The primary evaluator generated its uncommitted staging tree. HFNet,
`KLT_R04`, and `KLT_R05` each generated one evo APE log and one evo RPE log.
All six commands completed successfully; no error, fatal, exception, or
traceback was present. Execution reached the directory commit after evo
validation, so the evo cross-check itself had passed. Independent identity
audit matched all five primary-staging files and all fourteen evo-work files
(19/19) to the preserved partial-evidence manifest.

No concrete staged accuracy value is reproduced in this memo.

## Failure chain

1. The frozen evaluator attempted to publish
   `.hfnet_vs_klt_only_common_support_v5.evo_work/evo_crosscheck` to
   `.hfnet_vs_klt_only_common_support_v5.staging/evo_crosscheck` using a helper
   that requires source and destination to have the same parent. They do not.
   The exact first failure was
   `EVO_EXECUTION_OR_VALIDATION:AnalysisProtocolError:TERMINAL_COMMIT_NOT_SAME_PARENT`.
2. The failure path created an all-NA candidate summary and candidate receipt
   under `.hfnet_vs_klt_only_common_support_v5.failure_staging`.
3. Publishing that directory to the canonical output invoked Linux
   `renameat2(..., RENAME_NOREPLACE)`. The experiment root is on
   `/dev/sda2` mounted as `fuseblk`; this call returned `EINVAL`.
4. The command therefore exited with
   `OSError:[Errno 22] Invalid argument` for the canonical output path.

The canonical output directory
`/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/hfnet_vs_klt_only_common_support_v5`
does not exist. The frozen state machine consequently reports
`CLAIMED_WITHOUT_TERMINAL_RECEIPT`.

## Preserved uncommitted evidence

The following identities are diagnostic only and are not canonical terminal
artifacts:

- candidate failure receipt: 3583 bytes,
  SHA-256 `ce053680e0103aecba6aa481ca3d34dbd5a6887883aebe52d44fb44c4f0436b8`;
- all-NA candidate formal summary: 13164 bytes,
  SHA-256 `7d1a9e175cdd5376468e4323bf5cfd52f0fe50c86af9943a32ee8c58c0d45632`;
- partial-evidence manifest: 6305 bytes,
  SHA-256 `a37220e3e53c117c5cae6d9a4552e36ccc7f1f8e6b7002d4622d1aaded76dae8`.

The candidate receipt contains a prewritten
`terminal_directory_committed_atomically_noreplace=true` field, but the absent
canonical output proves that commit did not occur. It must not be cited as a
formal terminal receipt.

## Preservation and future protocol rule

Do not move, rename, copy, delete, or edit the claim, locks, primary staging,
evo work, failure staging, or candidate receipt. Do not call the v5 analysis
`run` command again.

For future windows, test the exact directory-publication primitive on the
actual target mount before freezing the analysis protocol. Any fuseblk-safe
receipt-last publisher or same-parent evo staging layout must be declared,
tested, and frozen before accuracy is generated; it cannot be applied
retroactively to this v5 attempt.
