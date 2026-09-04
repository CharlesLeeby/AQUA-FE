# A02 4500–6300 post-STOP long-window comparison preregistration

Status: **FROZEN; NO INPUT MATERIALIZATION, FEATURE EXPORT, VINS REPLAY, HFNET PROCESS, BRIDGE, OR EVALUATION HAS BEEN STARTED BY THIS PREREGISTRATION WORK**

Date: 2026-08-12 (Asia/Shanghai)

Canonical machine freeze: `papers/a02_4500_6300_post_stop_long_window_comparison_freeze_v1.json`.

The JSON is machine-authoritative. Its `commands` array is the only execution sequence, its `identities` map is the complete runtime identity set, and its `reserved_paths_absent_at_freeze` array is the exact start-state contract. Every command is executed as an independent `/bin/bash --noprofile --norc -c` command with working directory `/home/ma/AQUA-FE_WS`; no command relies on a variable from another command or on external `set -e`.

## Scientific role and attribution boundary

This is a development-exposed, result-informed, post-STOP exploratory comparison. The longer feed was selected after the earlier HFNet diagnostic exposed late initialization. It is not held out or confirmatory and cannot establish general superiority.

- `B1_CONSTQ` and `XFEATBIRTH_RAWLK` are frontend component arms sharing one frozen VINS-Fusion backend.
- `HFNET_WHOLE_SYSTEM` is an already-published learned whole SLAM system with its own frontend, map and optimization.
- Identical score support permits descriptive end-to-end trajectory comparison. It does not isolate a pure frontend causal effect between HFNet and either VINS arm.

## Window, pre-roll and score support

| Contract | Frozen value |
|---|---|
| camera feed | raw A02 indices `4500..6300` inclusive, 1,801 frames |
| pre-roll only | `4500..5399`, 900 frames |
| scored interval | `5400..6300`, 901 frames |
| frame 5400 | fed exactly once, as the first scored frame |
| score timestamps | `1542829061692686528..1542829106687510592 ns` |
| canonical raw-window IMU | 18,084 messages with closed ±0.25 s margin; `1542829016456083680..1542829106933121504 ns` |
| shared HFNet inner IMU | 17,987 messages; this is a downstream inner selection, not the raw-window bag count |

Input sampling is intentionally method-native: HFNet consumes all 1,801 images at approximately 20 Hz; the B1/XFeat carrier consumes raw frames but publishes 900 external-feature messages on `4501,4503,...,6299`, approximately 10 Hz. Image/feature counts must remain beside the result table.

## Reference and common-support rule

The reference is the same-image offline COLMAP trajectory scale-corrected with depth metadata. It is an image-derived proxy, **not independent ground truth**. The 46 rows correspond to `5400,5420,...,6300`; the frozen 1 Hz evaluation yields 45 uniform grid points, while row 46 supplies the final interpolation bracket.

All three arms use the same `a76c728b...` `body_T_cam0` config. G0 runs only when all three raw trajectories and their provenance chains seal as legal. The post gate requires, for every arm, `ape_valid=true`, `rpe_valid=true`, finite metrics and `grid_count=45`. Otherwise the artifact reports arm usability without a ranking.

Frozen evaluator parameters: reference 1 Hz, nominal estimate 10 Hz, evaluation 1 Hz, reference gap ≤2.5 s, estimate gap ≤0.25 s, score window `1542829061.692686528..1542829106.687510592`, RPE delta 1 s, minimum 30 APE poses, 10 s APE span, 0.70 common coverage and 10 RPE pairs. Evaluation and post-recomputation use the same sealed `/usr/bin/python3.8`, NumPy 1.24.4 numeric closure/SVD fingerprint, evo 1.31.1, and one BLAS/OMP/MKL thread.

## Execution/failure semantics

The fixed order is B1 native guard/export → const-q rewrite/audit → XFeat-birth/raw-KLT export/audit → B1 VINS → XFeat VINS → HFNet preflight/freeze/run → conditional lossless bridge → conditional three-arm G0.

Static/input/identity/infrastructure/guard-contract failure is a global STOP. In particular, the B1 v3 decision is revalidated after the project-side v4 environment repair and any mismatch exits 42. Once a scientific arm has started, its nonzero return code is sealed as that arm's terminal outcome and does not suppress later independent mandatory arms. The bridge is attempted only from a persisted exact HFNet-v4 PASS result. G0 is attempted only if all three arms have legal sealed trajectories. There is no retry, resume, overwrite, deletion, arm omission, window move or threshold change.

After the pre-evaluation seal and byte check pass, command 27 creates the non-reserved parent and then atomically claims the exact reserved evaluation directory with a non-`-p` `/usr/bin/mkdir`. If that claim fails, the evaluator is not invoked; the preceding command-26 absence check is only an early diagnostic, not the no-clobber authority.

Each VINS arm has a no-clobber process receipt and must have rc 0, a nonempty finite raw-order strictly monotonic `vio.csv`, exactly one `Initialization finish!`, and zero solver-failure/reboot/restart markers after initialization. Pre-initialization solver messages remain diagnostics. B1 uses port 11531 and XFeat uses 11532.

HFNet v4 records both raw trajectory and keyframe identities with their strict canonical `/mnt/data/...` paths after resolving the workspace `logs` symlink. The bridge consumes the same canonical trajectory path, and the pre/post verifier requires byte, size, hash and path equality across the v4 result, bridge and expected source.

All Python producers and verifiers require the dedicated `/tmp/aqua-fe-a02-long-eval-empty-pycache-v1` prefix to be absent, then run with `PYTHONDONTWRITEBYTECODE=1` and that prefix. This prevents unfrozen timestamp-based workspace `.pyc` files from substituting for the frozen sources. B1 runs under Noetic + `VINS-Fusion-origin` only. XFeat is frozen to CPU `torch 2.2.2+cpu` (`cuda_available=false`), so no short external timeout is permitted; the expected XFeat export duration is roughly 10–15 minutes on this host.

## Operational capacity estimate (not a scientific outcome)

Plan approximately 30–75 minutes wall time and 6–12 GiB of additional space for window/shared materialization, three feature-bag stages, two real-time replays, HFNet and evidence. This is a planning range, not a frozen measured result. The formal start remains blocked unless the preflight confirms adequate free space for every no-clobber output; no cleanup is authorized by this preregistration.

## Reserved paths required absent at command 0

The following exact 18 paths were absent at freeze and are checked by `check-start`. This is a controlled single-writer protocol, not a kernel-level atomicity claim.

```text
/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag
/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag.manifest.json
/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1
/home/ma/AQUA-FE_WS/logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_r1
/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1
/home/ma/AQUA-FE_WS/papers/hfnet_slam_a02_long1801_headless_run_contract_v4.json
/home/ma/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/runs/aqualoc_a02_4500_6300_headless_r1
/home/ma/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1
/home/ma/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv
/home/ma/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv.manifest.json
/home/ma/AQUA-FE_WS/papers/a02_4500_6300_three_arm_pre_eval_verification_v1.json
/home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1
/home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1/strict_gate_receipt.json
```

## Frozen identity set

This table is the complete rendering of the JSON identity map (131 entries); the sets and hashes are identical.

| Path | SHA-256 |
|---|---|
| `/home/ma/.evo/assets_version` | `4be46314bd7bb15822fda619849fea4d28b993d5bb6631352605819b9819a4e6` |
| `/home/ma/.evo/settings.json` | `62a54e1c4b15fdbae6d36ea2c875b99c1f1a70a8d874d6b905b282ae0bd4d3bd` |
| `/home/ma/.local/bin/evo_ape` | `6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15` |
| `/home/ma/.local/bin/evo_rpe` | `9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1` |
| `/home/ma/.local/lib/python3.8/site-packages/evo-1.31.1.dist-info/RECORD` | `a720ae5d78b1cf5d0c5b3ed81b8deb2adc41cb686ccffd773a42a1553823cbde` |
| `/home/ma/.local/lib/python3.8/site-packages/evo/__init__.py` | `ea1a753dbb2d53e58f5b3c7c1691fbcac02295cd22be8fe0831092fe7e009010` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libgfortran-040039e1.so.5.0.0` | `47ab3b68295b0a3ce8990a448de7fab11abddbc160f8895972ca9aa712cf86d0` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libopenblas64_p-r0-15028c96.3.21.so` | `554bde1d8a0c71d8dc21ae74de05c44da4fff5dbc6791a819f6acf5adfe90bd9` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libquadmath-96973f99.so.0.0.0` | `97cda85ddb5163e2da6e1edb4e1d6b557833a99a40eda079ae37e5039465b65d` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py` | `edd18feff93348beb02f392959e80b9fda1875a842d7f9760847f32386fdfd48` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/core/_multiarray_umath.cpython-38-x86_64-linux-gnu.so` | `190fed599b26cf689e22f198faf97d632f1d19b8aa75fdf5ca7fb96d37d97e37` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/lib/function_base.py` | `e2c03da3ca2ee0f918b8759df35a621db422f36dc6c017eef0f769188c8d452e` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/_umath_linalg.cpython-38-x86_64-linux-gnu.so` | `77d989daf30e91b14b657f0a125377d1c5bf49d7d950522baefdce9a7a93f927` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/lapack_lite.cpython-38-x86_64-linux-gnu.so` | `793234784255abc82b21e594a61906664219da405b0f73bf613da7b36e70c776` |
| `/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/linalg.py` | `304a00b1bbd5f933e3920264c93f7a21a46e4091a05fc714248492b54e78d1c9` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/_C.cpython-38-x86_64-linux-gnu.so` | `cbf6861cb2e89e098e1cc88c38fa3e565b70cdf471042b0bde14a351df26acf1` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/__init__.py` | `fe825c99bf91627cc438ab1967e413f4efef8599de835fb71af926c15b07a223` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libc10.so` | `4804bd9f2524b593a71eecaeb5b09d82594ca98408574a93fcf70e92d3f28966` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libgomp-a34b3233.so.1` | `570455c2902d6cc2a7f367703c06dac07495dd7f8a1ed2c8fc4cea628c881b13` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libshm.so` | `46e21dd56dc8093909ebe0d7c01c1609b7957ffc269a137590b4e78bb40a9d98` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch.so` | `d85f826501ff97723aa4671328929a43e456dcda589e0be33f7bab5e9b882b37` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch_cpu.so` | `ea615ec43ee633af935a073f6937f25555f4f68484935472ead52f80f6c801e2` |
| `/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch_python.so` | `ff832d1a405158eaae1241f17d4fef0ec143c42e3f129c9f7a934a617c773bdf` |
| `/home/ma/AQUA-FE_WS/build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3` | `4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb` |
| `/home/ma/AQUA-FE_WS/configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml` | `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1` |
| `/home/ma/AQUA-FE_WS/configs/published_baselines/hfnet_slam_aqualoc_a02_0005.yaml` | `7e6482653e55b2fcf86a9e5418fd87747677a88eb9c06443d505cda311b80569` |
| `/home/ma/AQUA-FE_WS/external_tools/accelerated_features/LICENSE` | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| `/home/ma/AQUA-FE_WS/external_tools/accelerated_features/modules/interpolator.py` | `d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da` |
| `/home/ma/AQUA-FE_WS/external_tools/accelerated_features/modules/model.py` | `d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964` |
| `/home/ma/AQUA-FE_WS/external_tools/accelerated_features/modules/xfeat.py` | `385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7` |
| `/home/ma/AQUA-FE_WS/external_tools/accelerated_features/weights/xfeat.pt` | `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b` |
| `/home/ma/AQUA-FE_WS/papers/ieee_sensors_journal_experiments/b1_klt_exporter_7ed_to_567_transition_proof_v2.json` | `9a149489e1defa790a9ff7a5ec107a75f9c15a506723fea081315c68eaf1dd2a` |
| `/home/ma/AQUA-FE_WS/papers/ieee_sensors_journal_experiments/backend_quality_contract_b1_current_exporter_v3.json` | `24995595906c0ea2e121ac91e7acbfd1f9d2e583a7011e6953073e9e1134f177` |
| `/home/ma/AQUA-FE_WS/papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json` | `14abab7ca7ad0f48af8856372b3cf97470d405c1e20081cdb4247f3c87b64957` |
| `/home/ma/AQUA-FE_WS/papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv` | `510c276c33217706eef11ea53e58de4b37318828f8a6dc793dea9262f0a0a0f5` |
| `/home/ma/AQUA-FE_WS/scripts/agent_qi_calibration_rewrite_bag.py` | `1cbf679994ad2897cdadd5e94cbf3653822ae980a7c1fabb47c7f2f400157f2d` |
| `/home/ma/AQUA-FE_WS/scripts/audit_quality_partition.py` | `9ba78f3fa3ae9ea87109bed10b58233afef85d003f5ae996404eabee0f765c0b` |
| `/home/ma/AQUA-FE_WS/scripts/audit_superpoint_lk_carrier_v1.py` | `f8a6abecb6c2253d8721befaccf1e49eb6e68013b6d1376cff8dbd71f579f1d1` |
| `/home/ma/AQUA-FE_WS/scripts/audit_xfeat_lk_carrier_v1.py` | `89998cacb929b00de08eb93cc21e36e7b64434a59acb3fc1b332f16822608935` |
| `/home/ma/AQUA-FE_WS/scripts/bridge_hfnet_world_body_to_vins_csv_v1.py` | `5b14003204da7724f5a750bd0f6538575517aae7e21202c9b468a2716a84d2a1` |
| `/home/ma/AQUA-FE_WS/scripts/build_b1_klt_nativeq_current_exporter_contract_v2.py` | `cabda6889b1bd4e82607b541104577aa05c42030b20224d36270876b8477be50` |
| `/home/ma/AQUA-FE_WS/scripts/build_b1_klt_nativeq_current_exporter_contract_v3.py` | `5701538678248de97711756264ff9cf5dfb64ff120cfe90f9b2c6376e354a50a` |
| `/home/ma/AQUA-FE_WS/scripts/build_nativeq_backend_contract.py` | `0c5bbdf3fd1f0948a94df346d29dc8b26ee66666c51287b933db5e7e79a0decc` |
| `/home/ma/AQUA-FE_WS/scripts/check_b1_klt_nativeq_contract_v1.py` | `8dafcb3e40278210e4fb545c5e19e347b69898cd45e5af3ec7736ceb682bad15` |
| `/home/ma/AQUA-FE_WS/scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py` | `aa7f0b53049b99ed9dcbc1c511a709f9cc0e492514ac4662c31ca803672f57b6` |
| `/home/ma/AQUA-FE_WS/scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py` | `32130de7016ad326281080825e74a9baab214cce1f98379f603e07b29c87d87e` |
| `/home/ma/AQUA-FE_WS/scripts/check_nativeq_backend_contract.py` | `37c61326e38d17e2a950fff66c9bd062bed8eab015385da36474c3bb558d3f4f` |
| `/home/ma/AQUA-FE_WS/scripts/evaluate_vins_common_support.py` | `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` |
| `/home/ma/AQUA-FE_WS/scripts/evaluate_vins_sim_ape.py` | `ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33` |
| `/home/ma/AQUA-FE_WS/scripts/export_aqualoc_a02_shared_4500_6300_v1.py` | `c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f` |
| `/home/ma/AQUA-FE_WS/scripts/export_aqualoc_to_hfnet_euroc_full_v2.py` | `b13f56b69fd88799d4885c044c75bd41aa4331e688c22edaa2301c523ef42013` |
| `/home/ma/AQUA-FE_WS/scripts/export_aqualoc_to_hfnet_euroc_v1.py` | `7bc4fcdae60172b00c630ae35fba1515b8969cf1a403a33a2cdbc2847cb1b9b0` |
| `/home/ma/AQUA-FE_WS/scripts/export_superpoint_lk_carrier_v1.py` | `2419fddc561c3a5bb2742aa033c62aa24d7361806a975c09c7e25ecf5995a34c` |
| `/home/ma/AQUA-FE_WS/scripts/export_xfeat_lk_carrier_v1.py` | `d7b6a698b784e0cee1c432308eb6f7546251503f0b47f4eeed9651b8fe401aba` |
| `/home/ma/AQUA-FE_WS/scripts/materialize_aqualoc_a02_4500_6300_window_v1.py` | `7d5ca32fea25945fcce454b948c55bc9d883b8dca3f5bf481611ced0395cd7a3` |
| `/home/ma/AQUA-FE_WS/scripts/prove_b1_klt_exporter_transition_v2.py` | `5541d9e211490c5eb0d0ec39c57e5233597514e30729a9cff1f285382118f50b` |
| `/home/ma/AQUA-FE_WS/scripts/record_vins_env.sh` | `577e17acb5e8df1a4a6d8d5b6ed531103adb984a5c7cb1cc8523f95d6e695ad3` |
| `/home/ma/AQUA-FE_WS/scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh` | `1525a5f4ff18e6c562ab75ca17539b5748f0d9617e9c331ca4720672cd651d7e` |
| `/home/ma/AQUA-FE_WS/scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh` | `0e2735985cc8041ddeb8b9a8cea4c9264844f3c49c5f7349929e6819eb54167f` |
| `/home/ma/AQUA-FE_WS/scripts/run_aqualoc_archaeo_vins_eval.sh` | `c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc` |
| `/home/ma/AQUA-FE_WS/scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py` | `165589aae498225d825b7a2e43586607475704fdbf98cba484a16346ffb245c4` |
| `/home/ma/AQUA-FE_WS/scripts/run_hfnet_slam_a02_full901_headless_v3.py` | `b5ad8731f7d50ed2dd5eb0e435f95ed2db9e854474c6d559ab6d21bcec4675a2` |
| `/home/ma/AQUA-FE_WS/scripts/run_hfnet_slam_a02_long1801_headless_v4.py` | `3cbf73588be58da7cd550b2deba42e0082968924bb9ed756684181720a38f41f` |
| `/home/ma/AQUA-FE_WS/scripts/run_isj_b1_klt_nativeq_guarded_v1.sh` | `6c112ebdb916becf615b0772c4474a119bf774a17b4f85391ceb88d46d0505d1` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_a02_b1_guarded_execution_repair_v4.py` | `7d1192518e8ee7dec0d96725bae44efb136729674eb7c82b848c659514dcea55` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_b1_klt_nativeq_current_exporter_contract_v3.py` | `c38740e508e687fa176b7f970e8f1c966ffb941c598f2c2cd1c0c0fd052a9af5` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_export_aqualoc_a02_shared_4500_6300_v1.py` | `736d085b6358e0b25356d9d76ba475a9f4904c334233ebae627e9d03c13a0f39` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_materialize_aqualoc_a02_4500_6300_window_v1.py` | `15d0355539079a744799d260ee29f1c64a993042b796d6d46cbf8a829dfb37ce` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_run_hfnet_slam_a02_long1801_headless_v4.py` | `7963f86ebb8e7cd80ea699391c7061be11317ad251dfbbf256332afcfd11d397` |
| `/home/ma/AQUA-FE_WS/scripts/tests/test_verify_a02_long_three_arm_eval_inputs_v1.py` | `fdc861837ce7196d0c2d36294625772f2b2919ec4150a6bba7e553fec9223a5d` |
| `/home/ma/AQUA-FE_WS/scripts/trajectory_eval_core.py` | `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635` |
| `/home/ma/AQUA-FE_WS/scripts/verify_a02_long_three_arm_eval_inputs_v1.py` | `d5316e505d6d4337e3743a38c300d963fbede9702c037eaccd501813a0683cef` |
| `/home/ma/AQUA-FE_WS/uw_frontend/__init__.py` | `44c8ccc9ab0cd7e8637b0dd005f183fb7b250a539c8b22ea6d26889a394f0934` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/backend_strict_frontend.yaml` | `908351d3d9547b98f917ffd059efdc7b279ee7f9199887688cda48e178a4855a` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml` | `d5927fb412de869cfe9dd6275dfb81a566fc33e4149160bafc0e8fa933b27eed` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml` | `2a61f1c57a77df4ed6bf2d85c080c7e6bd754a2ff47171e526e0643a3d617a25` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml` | `6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml` | `4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce` |
| `/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml` | `236e5173611731ffefd3acdd3b9f69429633dac16ae66429690d609fab0dd5d7` |
| `/home/ma/AQUA-FE_WS/uw_frontend/datasets/__init__.py` | `3e51607ce52c41b4cdba7cdc4b09e9cf3aff20c2e90b028971ab950cb8010477` |
| `/home/ma/AQUA-FE_WS/uw_frontend/datasets/aqualoc_raw_to_rosbag.py` | `b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec` |
| `/home/ma/AQUA-FE_WS/uw_frontend/datasets/image_sequence.py` | `2ba225a52a7caab9e92eb6b06c3ae7ff9a0030b96ea78e6f20f4228e97337384` |
| `/home/ma/AQUA-FE_WS/uw_frontend/evaluation/__init__.py` | `b95c4d2adf475a333bb42261ad54ee79656fe5aaecb351c4ecec31c18f5dea9b` |
| `/home/ma/AQUA-FE_WS/uw_frontend/evaluation/frontend_metrics.py` | `dae3258f04316c387bbbee5b0870132f7bac4fb3261b6069f690f06e07b9baf8` |
| `/home/ma/AQUA-FE_WS/uw_frontend/evaluation/measurement_selection.py` | `83230a42744be60e010ee4870011375fdd432a562843388c7adacd030dc298d3` |
| `/home/ma/AQUA-FE_WS/uw_frontend/evaluation/run_frontend_eval.py` | `c299038feb926e37bada04d0f150e57d45bed2f4d91bad8fb6a0c4ab2b22e6d2` |
| `/home/ma/AQUA-FE_WS/uw_frontend/geometry/__init__.py` | `f51eef8fcc512e338b3c5fd4f1e77f1dcb19dc09ab68eaab9289c968d56de882` |
| `/home/ma/AQUA-FE_WS/uw_frontend/geometry/dl_vins_magsac.py` | `d3c70b0c1f83f589380db82172b448ade485c101ed10102744f8a8d32487e128` |
| `/home/ma/AQUA-FE_WS/uw_frontend/geometry/grid.py` | `c1e6be4bfaee6cc1cac222c2dc5ba8f3e941702c60074f8473f663cf706de6eb` |
| `/home/ma/AQUA-FE_WS/uw_frontend/geometry/mode.py` | `402b5dc3eaecfb450a889502760cd591d02ff9c0e770edb522d1c777634c7a69` |
| `/home/ma/AQUA-FE_WS/uw_frontend/geometry/validation.py` | `4e2080bf786bf59b13af87ea7ee56b70b5f03892160ccd0a75aa9968d1781bb2` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/__init__.py` | `ad377bf38dfe58a58b8db275c70c1f5b9372ab6329d0591bc88ff5425f949c13` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/base.py` | `ad1baae7dc56188ae9d4a117de5efe0ae032a1b2749a4de38474c43d960876fa` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/classical_gftt.py` | `ec846d33ef8cc6ccb8e69fb30d87214c660807f94e9ca3b19aed6c944316604f` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/lightglue_adapter.py` | `9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/loftr_adapter.py` | `105cf63af51b6d4f8554a76939f88509d30fd85abc1b804ef18f2fd78edaebc2` |
| `/home/ma/AQUA-FE_WS/uw_frontend/matchers/xfeat_adapter.py` | `919b6b365548f2439b13eb01a24bd3e476de543dfcfa28b77baa09a7692fe345` |
| `/home/ma/AQUA-FE_WS/uw_frontend/quality/__init__.py` | `940c342bc9918992c9e53190993d1bff4f04970d3d0a9536d99f069a1b4a85fd` |
| `/home/ma/AQUA-FE_WS/uw_frontend/quality/feature_confidence.py` | `2ba770c1be212ec587c64ae0a35b3abc1dd58458f2e6eda572444859faf82864` |
| `/home/ma/AQUA-FE_WS/uw_frontend/quality/image_quality.py` | `e0b4a885cb8ecd2909b8abefc0fbc17098c9596df44091d5a3398df56583b89e` |
| `/home/ma/AQUA-FE_WS/uw_frontend/quality/reliability_features.py` | `f5f3d770af0655e7d68dbec9fdf043d6b772dd7b11b0f43ebc821515978cd8a4` |
| `/home/ma/AQUA-FE_WS/uw_frontend/ros/__init__.py` | `63e8c6c8109779dde006b8e6067ae7dabb9520342bd069a210615ba1a2c774d1` |
| `/home/ma/AQUA-FE_WS/uw_frontend/ros/export_vins_features.py` | `567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d` |
| `/home/ma/AQUA-FE_WS/uw_frontend/scheduler/__init__.py` | `c7ddade87b1a990451e559aa16a24892309a95cee6f5b976bc7e93e719279a90` |
| `/home/ma/AQUA-FE_WS/uw_frontend/scheduler/hybrid_scheduler.py` | `71e8ee6f95b47e6fbbfc8d25c96affea2abca217c91c47f75e0d13750ab3279b` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/__init__.py` | `74c60ba0b8a4cceec88519da9c269dce3b796812e900a0cdf10110488c2a696a` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/hybrid_tracker.py` | `7772772f1baf0966a4b1096ac1cd3122d71edbe18031756de409443e7c5ea2ae` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/klt_tracker.py` | `e60957bc0b45a11ef24824fa95ef9093dbbd7ba5998bc82bb91641c831f1fb5b` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/matcher_recovery.py` | `3d65f84f0d81a85ec7ce97daa44b9885ed8726f4df4c330b76fa390a9eb46e70` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/orb_tracker.py` | `c8490ab98348a6e57b2b250df7faf52cc527206449e9a90778001c84d7e363b2` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/pairwise_matcher_tracker.py` | `c2796382afdf79f4ab6c06615390749a6a91e5d8b7cf1f239209ea51e47500c6` |
| `/home/ma/AQUA-FE_WS/uw_frontend/tracking/track_state.py` | `c6a5f23209f830088a33cf2afd733c3520d7da88e14a0f10c01e8d54ce384802` |
| `/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so` | `a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717` |
| `/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache` | `6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7` |
| `/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx` | `354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5` |
| `/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so` | `6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d` |
| `/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so` | `c1080aefdfd0eb3f011d491041c773649917a77923b97e24503bd90136bab467` |
| `/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node` | `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278` |
| `/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/msg/__init__.py` | `d19edf818de477fe4555552190ee083ce4967320d3b0ce63a6e79b0eceff0cb2` |
| `/opt/ros/noetic/lib/python3/dist-packages/nav_msgs/msg/__init__.py` | `83cb4a545c959030c156611321bdadc8de74d09519beaf08b0c7e190191821cf` |
| `/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py` | `a65e884f18df0e88ff7403b53d77ad9ac59bd24734d880e301f7afe68fec4a81` |
| `/opt/ros/noetic/lib/python3/dist-packages/rospy/__init__.py` | `9e5c4e111abae5c45266c74c2ed83ff045d00b29d4c514d31c09b250460c9159` |
| `/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/__init__.py` | `c34aa9962d67d308caafc5cf61acf0515c9ba4826f6de2dbfee3b50ca8a9128f` |
| `/opt/ros/noetic/lib/python3/dist-packages/std_msgs/msg/__init__.py` | `d51bf5761f4b02c5d4ba24325c02eb9962d49cfafbaf98f60eaaffe12b52b9f2` |
| `/tmp/aqua-fe-opencv-usac-v1/lib/python3.8/site-packages/cv2/cv2.abi3.so` | `72c7fe9b389ecd9549b6e9cdca35ee11940de15d13d46722b8412865cafabc78` |
| `/usr/bin/ldd` | `d089c1054925b1f1dc9b574c2e7fabf3a495a1ce2ef946cd66d507daf09b7b8f` |
| `/usr/bin/python3.8` | `298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06` |
| `/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so` | `00f302d1efe76049187e2e2c7a05262e883394f82316490e2f28adb807ac1833` |
| `/usr/lib/python3/dist-packages/numpy/__init__.py` | `e9ba95ebf3add32b201e50e1d2685aa28c21a3ce5ce460b9384b7266b49c77d5` |
| `datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt` | `1122b753372545966026df10f1899e751cdaa3359a6938be251cd8e22b6e4379` |
| `datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz` | `8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69` |

## Exact authoritative command sequence

Exactly 28 independent commands follow. Run them only in order, only from `/home/ma/AQUA-FE_WS`, and only after explicit authorization to start the formal track.

### Command 0

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-start || exit $?
```

### Command 1

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/materialize_aqualoc_a02_4500_6300_window_v1.py --action preflight || exit $?
```

### Command 2

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/materialize_aqualoc_a02_4500_6300_window_v1.py --action export || exit $?
```

### Command 3

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/export_aqualoc_a02_shared_4500_6300_v1.py --action preflight || exit $?
```

### Command 4

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/export_aqualoc_a02_shared_4500_6300_v1.py --action export --output /mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1 || exit $?
```

### Command 5

```bash
test ! -e /mnt/data/AQUA-FE_WS/logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1 || exit 73
```

### Command 6

```bash
test ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1 || exit 73
```

### Command 7

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-static || exit $?
```

### Command 8

```bash
b1_native_rc=0; /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 AQUAFE_B1_V4_DECISION_DIR=/mnt/data/AQUA-FE_WS/logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1 RUN_VINS=0 FORCE_RAW=0 FORCE_EXPORT=0 TAG=litcmp_a02_4500_6300_preroll_b1_native_r1 /bin/bash --noprofile --norc scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh aqualoc_archaeology A02 4500 6300 2 || b1_native_rc=$?; printf 'B1_NATIVE_EXPORT_RC=%s\n' "$b1_native_rc"
```

### Command 9

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-b1-decision || exit 42
```

### Command 10

```bash
constq_rewrite_rc=125; if [ -f /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/features.bag ] && [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1 ]; then constq_rewrite_rc=0; /usr/bin/mkdir /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1 && test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/agent_qi_calibration_rewrite_bag.py --input-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/features.bag --output-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag --schedule constq --feature-topic /feature_tracker/feature --stats-csv /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/constq_stats.csv || constq_rewrite_rc=$?; fi; printf 'CONSTQ_REWRITE_RC=%s\n' "$constq_rewrite_rc"
```

### Command 11

```bash
constq_audit_rc=125; if [ -f /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/features.bag ] && [ -f /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag ] && [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json ]; then constq_audit_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/audit_quality_partition.py --input-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/features.bag --output-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag --audit-json /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json --feature-topic /feature_tracker/feature --source-code 1 --quality 1 --min-quality 0.05 || constq_audit_rc=$?; fi; printf 'CONSTQ_AUDIT_RC=%s\n' "$constq_audit_rc"
```

### Command 12

```bash
constq_gate_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B -c 'import json,pathlib; p=pathlib.Path("/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json"); d=json.loads(p.read_text()); ok=(d.get("schema_version")=="aqua-fe-quality-partition-audit-v1" and d.get("contract_pass") is True and d.get("feature_frames")==900 and d.get("selected_observations")==315000 and d.get("untouched_observations")==0 and d.get("quality")==1.0 and d.get("sigma")==1.0 and d.get("total_messages")==d.get("raw_equal_nonfeature_messages",-1)+d.get("feature_frames",-2)); raise SystemExit(0 if ok else 2)' || constq_gate_rc=$?; printf 'CONSTQ_CONTRACT_GATE_RC=%s\n' "$constq_gate_rc"
```

### Command 13

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-static || exit $?
```

### Command 14

```bash
xfeat_export_rc=125; if test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B -c 'import json,pathlib; p=pathlib.Path("/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json"); d=json.loads(p.read_text()); ok=(d.get("schema_version")=="aqua-fe-quality-partition-audit-v1" and d.get("contract_pass") is True and d.get("feature_frames")==900 and d.get("selected_observations")==315000 and d.get("untouched_observations")==0 and d.get("quality")==1.0 and d.get("sigma")==1.0 and d.get("total_messages")==d.get("raw_equal_nonfeature_messages",-1)+d.get("feature_frames",-2)); raise SystemExit(0 if ok else 2)'; then if [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1 ]; then xfeat_export_rc=0; /usr/bin/mkdir /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1 && test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 CUDA_VISIBLE_DEVICES=0 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 scripts/export_xfeat_lk_carrier_v1.py --source-feature-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag --raw-image-bag /home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag --camera-yaml /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/aqualoc_archaeo02_pinhole.yaml --output-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag --image-topic /camera/image_raw --feature-topic /feature_tracker/feature --manifest-json /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/export_manifest.json || xfeat_export_rc=$?; else xfeat_export_rc=73; fi; fi; printf 'XFEAT_EXPORT_RC=%s\n' "$xfeat_export_rc"
```

### Command 15

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-static || exit $?
```

### Command 16

```bash
xfeat_audit_rc=125; if [ -f /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag ] && [ -f /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/export_manifest.json ] && [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/audit.json ]; then xfeat_audit_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages /tmp/aqua-fe-opencv-usac-v1/bin/python scripts/audit_xfeat_lk_carrier_v1.py --reference-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag --candidate-bag /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag --camera-yaml /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/aqualoc_archaeo02_pinhole.yaml --feature-topic /feature_tracker/feature --output-json /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/audit.json || xfeat_audit_rc=$?; fi; printf 'XFEAT_AUDIT_RC=%s\n' "$xfeat_audit_rc"
```

### Command 17

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-static || exit $?
```

### Command 18

```bash
b1_vins_rc=125; if test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B -c 'import json,pathlib; p=pathlib.Path("/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/quality_partition_audit.json"); d=json.loads(p.read_text()); ok=(d.get("schema_version")=="aqua-fe-quality-partition-audit-v1" and d.get("contract_pass") is True and d.get("feature_frames")==900 and d.get("selected_observations")==315000 and d.get("untouched_observations")==0 and d.get("quality")==1.0 and d.get("sigma")==1.0 and d.get("total_messages")==d.get("raw_equal_nonfeature_messages",-1)+d.get("feature_frames",-2)); raise SystemExit(0 if ok else 2)'; then if [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_r1 ]; then b1_vins_rc=0; /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 ROS_DISTRO=noetic ROS_MASTER_URI=http://localhost:11531 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel CATKIN_SETUP_UTIL_ARGS='--local --extend' ROOT=/home/ma/AQUA-FE_WS VINS_WS=/home/ma/SLAM/VINS-Fusion-origin AQUALOC_ROOT=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences RAW_TAR=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz RAW_ROOT=raw_data GT_TXT=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt RAW_BAG=/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag FEATURE_BAG_OVERRIDE=/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag FRONTEND_CONFIG=/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml BACKEND_REPLAY_ONLY=0 RUN_VINS=1 FORCE_RAW=0 FORCE_EXPORT=0 EXPORT_FEATURES=0 VINS_MULTIPLE_THREAD=0 VINS_TD=-0.053694112369382575 VINS_ESTIMATE_TD=0 VINS_MAX_SOLVER_TIME=0.04 VINS_MAX_NUM_ITERATIONS=8 AQUALOC_BODY_T_CAM0_MODE=imu_cam PLAY_RATE=1.0 POST_PLAY_SLEEP=8 ROSBAG_PLAY_DELAY=3 ROSBAG_WAIT_FOR_SUBSCRIBERS=0 ROSBAG_PLAY_TOPICS= WAIT_FOR_VINS_SUBSCRIBERS=0 WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT=20 PORT=11531 TAG=litcmp_a02_4500_6300_preroll_b1_constq_vins_r1 /bin/bash --noprofile --norc /home/ma/AQUA-FE_WS/scripts/run_aqualoc_archaeo_vins_eval.sh external 2 4500 6300 klt 2 || b1_vins_rc=$?; else b1_vins_rc=73; fi; fi; b1_receipt_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action seal-arm-rc --arm B1_CONSTQ --return-code "$b1_vins_rc" || b1_receipt_rc=$?; printf 'B1_CONSTQ_VINS_RC=%s\n' "$b1_vins_rc"; printf 'B1_CONSTQ_RECEIPT_RC=%s\n' "$b1_receipt_rc"
```

### Command 19

```bash
xfeat_vins_rc=125; if test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B -c 'import json,pathlib; p=pathlib.Path("/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/audit.json"); d=json.loads(p.read_text()); i=d.get("input",{}); m=d.get("method",{}); ok=(d.get("schema_version")=="aqua-fe-xfeat-lk-carrier-audit-v1" and d.get("status")=="PASS" and d.get("pass") is True and i.get("candidate_bag")=="/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag" and m.get("method_id")=="xfeat_detector_raw_frame_lk_carrier_v1" and m.get("expected_source_code")==20 and m.get("expected_observations_per_frame")==350); raise SystemExit(0 if ok else 2)'; then if [ ! -e /home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1 ]; then xfeat_vins_rc=0; /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 ROS_DISTRO=noetic ROS_MASTER_URI=http://localhost:11532 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel CATKIN_SETUP_UTIL_ARGS='--local --extend' ROOT=/home/ma/AQUA-FE_WS VINS_WS=/home/ma/SLAM/VINS-Fusion-origin AQUALOC_ROOT=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences RAW_TAR=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz RAW_ROOT=raw_data GT_TXT=/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt RAW_BAG=/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag FEATURE_BAG_OVERRIDE=/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag FRONTEND_CONFIG=/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml BACKEND_REPLAY_ONLY=0 RUN_VINS=1 FORCE_RAW=0 FORCE_EXPORT=0 EXPORT_FEATURES=0 VINS_MULTIPLE_THREAD=0 VINS_TD=-0.053694112369382575 VINS_ESTIMATE_TD=0 VINS_MAX_SOLVER_TIME=0.04 VINS_MAX_NUM_ITERATIONS=8 AQUALOC_BODY_T_CAM0_MODE=imu_cam PLAY_RATE=1.0 POST_PLAY_SLEEP=8 ROSBAG_PLAY_DELAY=3 ROSBAG_WAIT_FOR_SUBSCRIBERS=0 ROSBAG_PLAY_TOPICS= WAIT_FOR_VINS_SUBSCRIBERS=0 WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT=20 PORT=11532 TAG=litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1 /bin/bash --noprofile --norc /home/ma/AQUA-FE_WS/scripts/run_aqualoc_archaeo_vins_eval.sh external 2 4500 6300 klt 2 || xfeat_vins_rc=$?; else xfeat_vins_rc=73; fi; fi; xfeat_receipt_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action seal-arm-rc --arm XFEATBIRTH_RAWLK --return-code "$xfeat_vins_rc" || xfeat_receipt_rc=$?; printf 'XFEATBIRTH_RAWLK_VINS_RC=%s\n' "$xfeat_vins_rc"; printf 'XFEATBIRTH_RAWLK_RECEIPT_RC=%s\n' "$xfeat_receipt_rc"
```

### Command 20

```bash
test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-static || exit $?
```

### Command 21

```bash
hfnet_preflight_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/run_hfnet_slam_a02_long1801_headless_v4.py --action preflight || hfnet_preflight_rc=$?; printf 'HFNET_PREFLIGHT_RC=%s\n' "$hfnet_preflight_rc"
```

### Command 22

```bash
hfnet_freeze_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/run_hfnet_slam_a02_long1801_headless_v4.py --action freeze || hfnet_freeze_rc=$?; printf 'HFNET_FREEZE_RC=%s\n' "$hfnet_freeze_rc"
```

### Command 23

```bash
hfnet_run_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/run_hfnet_slam_a02_long1801_headless_v4.py --action run || hfnet_run_rc=$?; printf 'HFNET_WHOLE_SYSTEM_RC=%s\n' "$hfnet_run_rc"
```

### Command 24

```bash
hfnet_bridge_rc=2; if test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B -c 'import json,pathlib; p=pathlib.Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json"); d=json.loads(p.read_text()); ok=(d.get("schema_version")=="aqua-fe-hfnet-slam-a02-long1801-headless-result-v4" and d.get("status")=="PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE" and d.get("return_code")==0 and d.get("evaluable") is True); raise SystemExit(0 if ok else 2)'; then hfnet_bridge_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/bridge_hfnet_world_body_to_vins_csv_v1.py --action convert --input /mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/runs/aqualoc_a02_4500_6300_headless_r1/trajectory.txt --output /mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv --run-result-json /mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json || hfnet_bridge_rc=$?; fi; printf 'HFNET_BRIDGE_RC=%s\n' "$hfnet_bridge_rc"
```

### Command 25

```bash
test ! -e /home/ma/AQUA-FE_WS/papers/a02_4500_6300_three_arm_pre_eval_verification_v1.json || exit 73
```

### Command 26

```bash
test ! -e /home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1 || exit 73
```

### Command 27

```bash
pre_seal_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action seal || pre_seal_rc=$?; pre_check_rc=2; if [ -e /home/ma/AQUA-FE_WS/papers/a02_4500_6300_three_arm_pre_eval_verification_v1.json ]; then pre_check_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check || pre_check_rc=$?; fi; if [ "$pre_seal_rc" -eq 0 ] && [ "$pre_check_rc" -eq 0 ]; then eval_dir_claim_rc=0; /usr/bin/mkdir -p /home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support && /usr/bin/mkdir /home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1 || eval_dir_claim_rc=$?; if [ "$eval_dir_claim_rc" -eq 0 ]; then eval_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/evaluate_vins_common_support.py --reference-tum /mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1/shared/reference_proxy.tum --arm B1_CONSTQ=/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_r1/vins_output/vio.csv --arm XFEATBIRTH_RAWLK=/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1/vins_output/vio.csv --arm HFNET_WHOLE_SYSTEM=/home/ma/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv --arm-config B1_CONSTQ=/home/ma/AQUA-FE_WS/configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml --arm-config XFEATBIRTH_RAWLK=/home/ma/AQUA-FE_WS/configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml --arm-config HFNET_WHOLE_SYSTEM=/home/ma/AQUA-FE_WS/configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml --nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 --evaluation-rate-hz 1 --max-reference-gap-s 2.5 --max-estimate-gap-s 0.25 --window-start-s 1542829061.692686528 --window-end-s 1542829106.687510592 --rpe-delta-s 1 --min-ape-poses 30 --min-ape-span-s 10 --min-common-coverage 0.70 --min-rpe-pairs 10 --contrast-name A02_4500_6300_POST_STOP_B1_XFEAT_HFNET --output-dir /home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1 --run-evo || eval_rc=$?; if [ "$eval_rc" -eq 0 ]; then post_seal_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action seal-evaluation || post_seal_rc=$?; post_check_rc=2; if [ -e /home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1/strict_gate_receipt.json ]; then post_check_rc=0; test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash PATH=/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 PYTHONPATH=/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages /usr/bin/python3.8 -B scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-evaluation || post_check_rc=$?; fi; if [ "$post_seal_rc" -eq 0 ] && [ "$post_check_rc" -eq 0 ]; then echo THREE_ARM_G0_STRICT_PASS; exit 0; else echo THREE_ARM_G0_POST_GATE_FAILED_NO_RANKING; exit 2; fi; else echo THREE_ARM_G0_EVALUATOR_FAILED_NO_RANKING; exit 2; fi; else echo THREE_ARM_G0_EVAL_DIR_CLAIM_FAILED_NO_EVALUATOR; exit 2; fi; else echo THREE_ARM_G0_SKIPPED_REPORT_USABILITY_WITHOUT_RANKING; exit 2; fi
```

## Reporting boundary

The final table must report, beside APE/RPE, initialization status, process return code, scored coverage, first scored output delay, output rows, failure markers, common poses/span/coverage, image/feature sampling counts and the proxy-GT caveat. It must label HFNet as a whole-system baseline, B1/XFeat as frontend-component arms on common VINS, and the entire comparison as post-STOP exploratory.
