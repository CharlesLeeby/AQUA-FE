# AnyFeature-VSLAM adapter execution addendum r1

Date: 2026-08-11 (Asia/Shanghai)  
Status: **FROZEN BEFORE REAL A02 EXPORT, R2D2 INFERENCE, INGESTION SMOKE, OR SLAM**

This addendum closes the high-level representation adapter and its one-image sequence-view authority after infrastructure-only provisioning. It changes no scientific arm, model, upstream source, feature threshold, frame window, run order, or evaluation rule.

## Authority and retained infrastructure

- Main preregistration after the reserved-path-only amendment: `papers/anyfeature_vslam_r2d2_a02_preregistration.md`, SHA-256 `74eb99a57aee660270561850a0b72f288951a80082b9c7a6200ecfed60a3c680`.
- Independently reviewed adapter audit: `papers/anyfeature_vslam_adapter_audit_r1.json`, SHA-256 `3f32f4705fd99a430526224a650091240f54220909f7124729e28af3fb2437b7`.
- Source-unmodified r3 provisioning result: `papers/anyfeature_vslam_provisioning_r3_result.json`, SHA-256 `cd74fc9cf16ab89ab02429031901590e9ee347e1197756286a05cb7c9edc3442`.
- Frozen official binary: `/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r3/bin/mono`, SHA-256 `9adb623fc8d83ce35297be7a7d810d269cd65273bd0f4fb1bddebbec0b8bdd59`.
- Frozen r3 environment explicit lock: `/mnt/data/opt/anyfeature-paper-2024-r3/evidence/anyfeature_env_explicit.txt`, SHA-256 `12656125f716a449af782fbbde07e49d8a20139e529e3d55c0a6c436c1236d0b`.

## Frozen adapter implementation

| File | SHA-256 |
|---|---|
| `scripts/export_aqualoc_to_anyfeature_v1.py` | `2dccbe93f68df3ec18f4bbae20ee2fcf24bf3a5e4d857313d23bd2a77690f09e` |
| `scripts/tests/test_export_aqualoc_to_anyfeature_v1.py` | `abb0da317c1c3ed35cfbc87f895203057c4e4f406c688e46b0f2f66634595130` |
| `scripts/materialize_anyfeature_r2d2_bins_v1.py` | `4aa1bcfa9073fa667d47154de64fc0f20d0f3a9806a812514b5616e06702f8e7` |
| `scripts/tests/test_materialize_anyfeature_r2d2_bins_v1.py` | `ada29004e86c295e9ccb3c2437456410749fd66377732b078ef6d8cfae4162ab` |

`py_compile` and all `36/36` synthetic contract tests passed in both implementation and independent-review runs. Any hash drift is a hard integrity stop.

## One-image sequence view

The formal one-image R2D2 ingestion smoke uses exactly:

```text
sequence_path:/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_frame000_smoke_view_r1
exp_folder:/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/model_smokes/a02_frame000_r1
```

The sequence view is materialized only after prefix image/archive/bin audit. It contains exactly one `rgb.txt` row and the byte-identical index-0 PNG, calibration, and three nonempty R2D2 bins. It is not the 200-image prefix and cannot be used for accuracy. Both paths were absent at this freeze and are no-clobber.

## Remaining hard gate before inference

This addendum does not by itself authorize R2D2 execution. Before the first real inference, a separately tested producer runner must be frozen and must bind the exact Python executable, `sys.path`, CPU-only Torch state, package versions and module-file hashes, official extractor/checkpoint identities, canonical argv and working directory, image-list identity, stdout/stderr/RC/timing, and every `.png.r2d2` hash. The producer runner and official-system runner hashes must be recorded in a final run-closure artifact before they are invoked.

At this freeze, the prefix, full sequence, one-image sequence view, one-image experiment directory, both full-run directories, and evaluation directory were all absent. No real A02 image had been exported for this track, no R2D2 inference had run, and no AnyFeature trajectory existed.
