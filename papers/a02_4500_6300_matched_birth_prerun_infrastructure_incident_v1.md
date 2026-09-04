# Matched-birth pre-run infrastructure incident (r1 terminated)

The original `r1` pre-run namespace is permanently terminated before any
matched XFeat or GFTT producer process started. Three outcome-blind builder
invocations returned code 2:

1. The then runtime contract did not model the duplicate canonical workspace
   entry produced by the frozen `python -m` launch boundary. No governed file
   was written.
2. Trusted ROS-bag reconstruction appended scoped `/tmp/genpy_*` import paths
   before the runtime was rechecked. No governed file was written.
3. The first XFeat command-contract publication was attempted on `fuseblk`.
   Although `fchmod(0444)` was requested, `fstat`/`lstat` exposed mode `0755`,
   so the builder stopped with
   `FREEZE_BUILD_ERROR:FreezeBuildError:O_EXCL artifact descriptor contract failed`.

The third failure left exactly one non-authoritative zero-byte orphan:
`/mnt/data/AQUA-FE_WS/logs/matched_birth_control_probes/a02_4500_6300_prefix16/xfeat_r1/command_contract.json`.
It is retained immutably; deletion, repair, reuse, or reinterpretation as a
freeze-authorized command is forbidden. The GFTT `r1` directory remains empty,
the freeze and audit receipts are absent, and producer process start count is
zero.

The orphan is a non-symlink regular file with requested mode 0444 and
observed mode 0755; its nanosecond timestamp is encoded as a decimal string
in the canonical receipt to avoid JSON-number precision loss. The receipt also
binds the exact 58-token builder argv, cwd, frozen environment, three identical
invocations, and all 21 paths that remained absent.

Any continuation must be additive under
`/home/ma/AQUA-FE_WS/experiments/matched_birth_a02_4500_6300_r2`, must bind the
canonical JSON incident, and must verify an ext4/same-device artifact
filesystem contract before its first `O_EXCL` publication. This is an
infrastructure continuation, not a retry or fulfilment of the terminated `r1`
protocol.
