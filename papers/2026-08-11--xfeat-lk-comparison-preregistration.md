# XFeat-birth + frozen raw-frame KLT comparison preregistration

Status: frozen before any real XFeat model load, image inference, feature-bag export, VINS replay, or G0 evaluation for this arm.

Date: 2026-08-11 (Asia/Shanghai)

## Method identity and claim boundary

The comparison arm is **AQUA-FE XFeat-birth + frozen raw-frame KLT carrier v1 (DL-VINS-Factory component-aligned)**. XFeat proposes births; the frozen AQUA-FE raw-frame KLT carrier exclusively propagates persistent IDs. This is an independent detector/configuration comparator within the learned-keypoint-plus-LK family. It is not an official or code-exact DL-VINS-Factory reproduction, an XFeat-paper baseline, a pure-XFeat temporal frontend, a descriptor-head-free implementation, or a TensorRT/runtime reproduction.

The local wrapper calls the pinned VerLab `XFeat.detectAndCompute(..., top_k=2048)` API and consumes only keypoints and scores. That API still computes 64-D descriptors internally; they are discarded and no descriptor matcher, XFeat-star, LighterGlue, MAGSAC frontend filter, pairwise occurrence-ID adapter, or GFTT fallback is used.

Frozen method values:

- XFeat threshold `0.05`, NMS kernel `5`, proposal budget `2048`.
- `adaptive_clahe` preprocessing; detector runs only when the carrier needs replenishment.
- Raw frame 0 initializes state; every raw frame is tracked; raw indices `1,3,...,899` are published.
- Total cap `350`, birth spacing `18 px`, border `8 px`.
- LK window `21x21`, pyramid level `3`, iterations `30`, epsilon `0.01`, minimum eigenvalue `1e-4`.
- Forward/backward error `<=1 px`; NCC `>=0.65`, radius `5`.
- Survivors sort by age descending then ID ascending; dead IDs are never reused or revived.
- `quality=1`, `sigma=1`, `source_code=20`, `is_learned=1`; velocity uses the true interval between published header stamps.

The frozen algorithm-config SHA-256 is `98a8e674f19bfdc2e965a8ea5f27254d837da7f7f4d1254fcbeaa01665c7c1a8`.

## Implementation and model lock

Independent review found no remaining P0/P1; 51/51 synthetic tests and 8/8 `py_compile` checks passed under pre/post hash fuse. No real model, image, or bag was used to obtain those results.

| Artifact | SHA-256 |
|---|---|
| `scripts/export_superpoint_lk_carrier_v1.py` | `2419fddc561c3a5bb2742aa033c62aa24d7361806a975c09c7e25ecf5995a34c` |
| `scripts/tests/test_export_superpoint_lk_carrier_v1.py` | `01fd79d9be3b061ef67814dbdc0dbaec7dc617e5ff909a51bfef10222096bc78` |
| `scripts/export_xfeat_lk_carrier_v1.py` | `d7b6a698b784e0cee1c432308eb6f7546251503f0b47f4eeed9651b8fe401aba` |
| `scripts/tests/test_export_xfeat_lk_carrier_v1.py` | `ba4a84c368e934582c44b93c10a9daa89617250be4af08d46ee005c6690657eb` |
| `scripts/audit_superpoint_lk_carrier_v1.py` | `f8a6abecb6c2253d8721befaccf1e49eb6e68013b6d1376cff8dbd71f579f1d1` |
| `scripts/tests/test_audit_superpoint_lk_carrier_v1.py` | `7b2afabcc87f80af582dfe5c9a8c4d19cda1389f3ce8019042b7e965efc659af` |
| `scripts/audit_xfeat_lk_carrier_v1.py` | `89998cacb929b00de08eb93cc21e36e7b64434a59acb3fc1b332f16822608935` |
| `scripts/tests/test_audit_xfeat_lk_carrier_v1.py` | `1d2c73e058ac8637e00dd17dae9b83909b9f416bf4d51d90b4b8e0aedc8671d7` |

Pinned upstream XFeat checkout: commit `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`; the checkout's 39 dirty paths have been proven byte-identical to the index and differ only in executable mode bits.

| XFeat closure artifact | Size | SHA-256 |
|---|---:|---|
| `weights/xfeat.pt` | 6,247,949 B | `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b` |
| `modules/xfeat.py` | 13,472 B | `385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7` |
| `modules/model.py` | 4,542 B | `d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964` |
| `modules/interpolator.py` | 1,175 B | `d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da` |
| `LICENSE` | 11,357 B | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |

Executed/frozen local carrier dependencies are `uw_frontend/quality/image_quality.py` (13,301 B, SHA-256 `e0b4a885cb8ecd2909b8abefc0fbc17098c9596df44091d5a3398df56583b89e`) and the KLT reference implementation `uw_frontend/tracking/klt_tracker.py` (12,306 B, SHA-256 `e60957bc0b45a11ef24824fa95ef9093dbbd7ba5998bc82bb91641c831f1fb5b`). The first executes the adaptive-CLAHE decision; the second is recorded as the frozen reference for the carrier implementation.

Only a full export invoked through the frozen production CLI factory may set `formal_eligible=true`. Prefixes and all Python-injected detector paths are nonformal. XFeat audits use the method-specific schema `aqua-fe-xfeat-lk-carrier-audit-v1`, method ID `xfeat_detector_raw_frame_lk_carrier_v1`, and fixed source code 20; none is CLI-overridable.

## Frozen inputs

| Window | Artifact | Path | Size | SHA-256 / counts |
|---|---|---|---:|---|
| A02:0005 | raw | `datasets/aqualoc/rosbags/archaeo02_4500_5400.bag` | 222,477,260 B | `8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8`; 901 image, 9,091 IMU, 46 GT |
| A02:0005 | B1-constq schedule/control | `logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_0005_full_b1_constq_r2/features.bag` | 13,728,676 B | `683e9dcf9f2ef470d2e68fd746b84b5d509bbb10650c62206417c258597fcf38`; 450x350 |
| A02:0005 | camera | `logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_0005_full_b1_constq_vins_r2/aqualoc_archaeo02_pinhole.yaml` | 357 B | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| A07:0001 | raw | `datasets/aqualoc/rosbags/archaeo07_900_1800.bag` | 250,669,586 B | `4097aed3759d22e130c1fc418422d14c6dba8517fa5433e4f6b65ccab7413d9d`; 901 image, 8,968 IMU, 46 GT |
| A07:0001 | B1-constq schedule/control | `logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a07_0001_full_b1_constq_r1/features.bag` | 13,681,750 B | `2d2a0573497f710ce090c2b040b6bee3d1b858848d0a95bda0057bbdfaac40c4`; 450x350 |
| A07:0001 | camera | `logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a07_0001_b1_attempt01/aqualoc_archaeo07_pinhole.yaml` | 357 B | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |

The 100-frame prefixes are raw indices `1,3,...,199`. A02 spans feature headers `1542829016.751271248` through `1542829026.649564505`; A07 spans `1542883756.512375355` through `1542883766.411674738`.

Both producer and auditor topics are frozen to raw image `/camera/image_raw` and feature `/feature_tracker/feature`. The G0 reference topic is `/aqualoc/colmap_gt`.

## Frozen audit gates

Every gate must pass; there is no compensating score and no post-result threshold adjustment.

| Gate | Required value |
|---|---:|
| Structural contract | 350 observations/frame; exact schedule/schema/nonfeature prefix; `q=sigma=1`, `source=20`, `is_learned=1`, `z=1` |
| Pixel-to-normalized consistency | maximum error `<=1e-6` |
| Published velocity consistency | maximum error `<=1e-5` |
| Birth rate | median `<=0.05`, p90 `<=0.10` |
| Episode lifetime | median `>=10` frames |
| Episodes of length <=2 | fraction `<=0.45` |
| Lag-10 common IDs | median `>=250`, p10 `>=220` |
| Deterministic 20 px thinning | median `>=250`, p10 `>=220` |
| Occupied 8x6 cells | median `>=30`, p10 `>=26` |
| Pixel second difference | median `<0.3 px` |
| Essential USAC_MAGSAC at 0.3 px | median inlier ratio `>0.90`, p10 `>0.85` |

The audit must run through `/tmp/aqua-fe-opencv-usac-v1/bin/python scripts/audit_xfeat_lk_carrier_v1.py`; the system OpenCV 4.2 lacks the required real `USAC_MAGSAC` capability. Prefix audit alone uses `--allow-candidate-prefix`. Source code, method ID, and audit schema are not command-line options.

## Sequential execution and stopping rule

1. Run exactly one non-scientific single-image loading/inference smoke on A02 raw image index 0 from `/camera/image_raw`, after the frozen adaptive-CLAHE preprocessing. It may only verify frozen closure loading, `0 < N <= 2048` finite/in-bounds proposals, absence of matcher calls, and runtime/device recording. Failure terminates this revision before any feature-bag export; any corrected environment requires a new revision and preregistration. It cannot change any method value.
2. Export exactly one A02 100-published-frame prefix and run exactly one method-specific audit.
3. If any A02 prefix gate fails, seal the artifacts and stop the entire XFeat arm: no A02 full/VINS/G0 and no A07.
4. If and only if the A02 prefix passes, export one A02 full window and run one full audit. Any failure stops before VINS.
5. If and only if the A02 full audit passes, replay it through the fixed single-thread VINS backend once on port 11461. Initialization failure, empty/unparseable/nonfinite trajectory, or infrastructure-clean scientific failure is a terminal result and is not retried.
6. If and only if VINS produces a valid trajectory, run strict G0 once against the existing B1-constq control. Continue based on both `ape_valid=true` and `rpe_valid=true`, not on whether XFeat is numerically better.
7. Only after an A02 usable G0 endpoint, run exactly one A07 100-frame prefix with the unchanged code/model/gates. A07 prefix failure stops without full/VINS/G0.
8. An A07 prefix pass mandates, rather than optionally permits, one A07 full export and audit. A full-audit failure stops before replay.
9. An A07 full-audit pass mandates one replay of the already frozen B1-constq bag and one replay of the XFeat bag, both single-threaded and without re-export, followed by one strict G0 comparison. There is no result-dependent choice to omit or add these runs.

A02 G0 is fixed at 1 Hz, reference gap 2.5 s, estimate gap 0.25 s, RPE delta 1 s, window `[1542829016.7004354, 1542829061.6926866]`, at least 30 APE poses, 10 s APE span, 0.70 common coverage, and 10 RPE pairs. Arm labels are `B1_CONSTQ` and `XFEATBIRTH_RAWLK`.

A07 G0 uses the same rates, gaps, RPE delta, validity minima, and arm labels, with window `[1542883756.4635663, 1542883802.2091215]`. Its B1-constq replay must be generated once from the frozen A07 const-q bag before the XFeat replay; both outputs are then evaluated on the same common support.

The frozen A02 control trajectory is `logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_0005_full_b1_constq_vins_r2/vins_output/vio.csv` (46,576 B, SHA-256 `c85bce4238d12e7b1edb754828f1746ffc07656d5ef295e352d03b352d93dd61`). Its VINS config is the same run's `vins_aqualoc_archaeo_external.yaml` (955 B, SHA-256 `7e1286a9375dc26478e5592c3d16b956b197f792b25af33040c7d6daed6a92cb`). Candidate configs must be identical to their window's frozen B1 config after removing only `output_path`; for A07 the reference config is `logs/aqualoc_archaeo_vins/external_klt_every2_p07_b1m_normal_aqualoc_archaeology_a07_0001_b1_r1/vins_aqualoc_archaeo_external.yaml` (966 B, SHA-256 `888efd54389fa3616c43ecf5953771e99a8fcb8785009766ef9d7ad2d9f3b9ec`).

VINS replays use `scripts/run_aqualoc_archaeo_vins_eval.sh` SHA-256 `c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc`, with the exact candidate `FEATURE_BAG_OVERRIDE`, `RUN_VINS=1`, `FORCE_EXPORT=0`, `EXPORT_FEATURES=0`, `VINS_MULTIPLE_THREAD=0`, and `ROSBAG_WAIT_FOR_SUBSCRIBERS=0`. A02 uses port 11461. If reached, A07 B1-constq and XFeat use ports 11462 and 11463 sequentially. G0 uses `scripts/evaluate_vins_common_support.py` SHA-256 `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` with `--run-evo`.

Every replay must use `/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node`, 13,104,360 B, SHA-256 `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278` (MD5 `7739ae5fe158681765cea3983b8e55bb`). A mismatch before any replay is an infrastructure stop; substituting or rebuilding the backend requires a new revision and preregistration.

Infrastructure errors are distinguished from scientific failure only when they occur before a complete scientific artifact and return the documented error status. A correction may not modify XFeat, the carrier, or any gate; it must use a new revision path and retain the failed attempt. No half-written artifact is resumed.

## Reserved paths

These paths were absent at preregistration time and may not be silently reused:

```text
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_0005_s10_xfeatbirth_rawlkcarrier_v1_r1
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_0005_full_xfeatbirth_rawlkcarrier_v1_r1
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_0005_full_xfeatbirth_rawlkcarrier_v1_vins_r1
papers/litcmp_a02_0005_common_support/b1_constq_vs_xfeatbirth_rawlkcarrier_v1_r1
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a07_0001_s10_xfeatbirth_rawlkcarrier_v1_r1
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a07_0001_full_xfeatbirth_rawlkcarrier_v1_r1
logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a07_0001_full_b1_constq_vins_r1
logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a07_0001_full_xfeatbirth_rawlkcarrier_v1_vins_r1
papers/litcmp_a07_0001_common_support/b1_constq_vs_xfeatbirth_rawlkcarrier_v1_r1
```

A02 and A07 are development-exposed windows. Neither may be described as fresh held-out evidence, and an A07 result may only be described as a prespecified current-method compatibility validation.
