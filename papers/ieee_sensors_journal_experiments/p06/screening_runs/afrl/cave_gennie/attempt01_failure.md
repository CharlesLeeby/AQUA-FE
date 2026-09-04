# P06 AFRL cave_gennie Attempt 01 Failure

- Observed at: `2026-08-04T21:55:59+08:00`
- Stage: `P06` outcome-blind screening
- Status: `FAILED`
- Failure class: `INFRASTRUCTURE_DISK_CAPACITY_PREFLIGHT`
- Runner return code: `143` after an intentional `SIGTERM`
- Scientific result produced: `false`
- Learned or VINS trajectory outcome read: `false`

The frozen AFRL wrapper first materialized the compressed camera stream as an
uncompressed full-resolution ROS bag.  At the safety stop, the converter had
read approximately `3,402,264,820` bytes from the `8,435,218,703` byte source
bag while the temporary output had already reached `10,473,954,306` bytes.
The final closed partial bag was `11,992,547,328` bytes, while `/mnt/data` had
approximately 12 GB available.  Continuing the same adapter would therefore
have risked filling the filesystem before screening started.

Partial adapter artifact before deletion:

```text
cb19e23654579d16ce75df54203674bb966540f566aba23818f43fd08fef5924  /mnt/data/AQUA-FE_WS/p06_screening_work/afrl/cave_gennie/cave_gennie_short.bag
size_bytes=11992547328
```

The partial bag is not a scientific artifact and contains no screening metrics.
It may be deleted after this digest, the failed runner audit, command, and log
are archived.  The replacement must use a versioned direct compressed-image
adapter and pass a development equivalence audit before full-sequence use.
