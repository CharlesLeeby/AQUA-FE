# Confirmatory-v3 execution notes

## Recoverable batch interruption

The first interactive frontend batch was interrupted while materializing
`a10_10800_11700/klt`.  It had produced neither frontend metrics nor a cell
receipt.  The stale batch status, 92 MB partial input bag, and empty run log
were moved without deletion to:

`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_confirmatory_v3/quarantine/recovery_20260904T_current`

The interrupted input is not used by any formal cell.  Its SHA-256 is
`5258a0489a12fc22b0cb29256b2b867432a9f3d9530d137c0ac29a7ccdf97e6a`.

## A04 archive-layout correction

All three initial A04 invocations failed before frontend execution because
the generic archaeology adapter requested
`raw_data/img_sequence_4.csv`.  The locked source archive instead stores
`img_sequence_4.csv`, `imu_sequence_4.csv`, and `images_sequence_4/` at archive
root.  This layout and the empty `--raw-root` correction were already recorded
by the earlier P07 A04 replacement lock; no method outcome was consulted.

The correction materialized the same preregistered `5400:6300` interval once
with `scripts/materialize_frontend_same_backend_confirmatory_v3_a04.py`
(SHA-256
`9df59ed1ad7b82809f442c7f5e5a6feb909cd9f6373cc48914c1afda70e143e1`).
The resulting common input contains 901 images, 9091 IMU messages, and 42
proxy poses over 44.993 s.  Its SHA-256 is
`0d2d504302e677f17715174b87ad7d1f7c85838f7393fb5cc46a63ab870f8b3b`;
the materialization receipt SHA-256 is
`15c9fb9df766c909b8870634433906b200e4e86adbf2a996b94444a1f2305a5b`.
Only the data member path changed.  Frontend profiles, feature budget,
selection/quality gates, timestamps, backend, and evaluation gates remain
unchanged.

The failed pre-frontend A04 directories are retained under the runtime
`quarantine/` tree and are excluded from the formal ledger after successful
replacement cells receive complete receipts.

## Persistent service environment

An ordinary `nohup` child was reaped by the execution environment.  A first
transient user-service attempt then failed before batch execution because ROS
Python modules were absent; a second failed while sourcing ROS with Bash
`nounset`.  Both logs and stale status files are preserved in the recovery
directory above.

The active recovery uses
`scripts/run_frontend_same_backend_confirmatory_v3_service.sh` (SHA-256
`69cbad30f4eeb72b9f6f3d1b5be08d749321a52231ae12df003ebe0150a91b72`),
which only loads ROS Noetic before executing the unchanged batch runner.  It
changes no scientific setting.  The systemd user unit is
`aquafe-confirmatory-v3-frontend.service`.
