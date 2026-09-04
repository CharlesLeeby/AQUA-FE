# 固定后端前端对比：长窗口 supplemental v1

## 定位与不可合并边界

本表仍是**固定 VINS-Fusion 后端的前端隔离对比**，对应 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 使用关键帧与局部 BA 后端，属于不同设计空间，仅可单列为 reference；这里不作整系统对 HFNet 的精度声明。

本批次在结果产生前预注册了 8 个新的 30–50 s 窗口，用来修正主批次短窗无法达到 30 common poses 的协议问题。三前端仍为 KLT、SP+LG、XFeat-seed；名义预算配置、采样相位、门控、质量映射、三重复和评估口径保持一致。事后实际 PointCloud 审计发现少数 learned 激活帧超过配置的 350 上限，相关窗口已从严格归因分母剔除，见下文。

主批次的 `libvins_lib.so` 哈希为 `373a598c...810f71e8`，但扩窗前该文件已被另一个本机构建替换，旧字节副本不可恢复。本批次因此冻结为独立 backend epoch `supplement_v1_libvins_82ec1fcd`（库哈希 `82ec1fcd...b049045e`）。本批次内部 72/72 份归一化后端配置通过一致性审计；前端归因还需同时通过有效输入与实际预算审计。不得把主批次与本批次伪装成同一 exact-build 精度分母。

## 执行与 runability

正式规模为 8 窗口 × 3 前端 × 3 replay = 72。初始化 72/72；重复级 runability PASS 72/72。窗口级通过数：KLT 8/8，SP+LG 8/8，XFeat-seed 8/8。

| Window | KLT | SP+LG | XFeat-seed |
| --- | --- | --- | --- |
| a03_5000_5900 | PASS 3/3; poses 403 [378–403]; cov 0.893 [0.838–0.893] | PASS 3/3; poses 403 [403–403]; cov 0.893 [0.893–0.893] | PASS 3/3; poses 403 [403–403]; cov 0.893 [0.893–0.893] |
| a01_16200_17100 | PASS 3/3; poses 439 [439–439]; cov 0.973 [0.973–0.973] | PASS 3/3; poses 439 [439–439]; cov 0.973 [0.973–0.973] | PASS 3/3; poses 439 [439–439]; cov 0.973 [0.973–0.973] |
| a07_900_1800 | PASS 3/3; poses 392 [392–407]; cov 0.871 [0.871–0.904] | PASS 3/3; poses 420 [420–433]; cov 0.932 [0.932–0.961] | PASS 3/3; poses 420 [420–420]; cov 0.932 [0.932–0.932] |
| a07_1800_2700 | PASS 3/3; poses 417 [417–417]; cov 0.923 [0.923–0.923] | PASS 3/3; poses 417 [417–417]; cov 0.923 [0.923–0.923] | PASS 3/3; poses 417 [417–417]; cov 0.923 [0.923–0.923] |
| h07_0_1000 | PASS 3/3; poses 489 [489–489]; cov 0.976 [0.976–0.976] | PASS 3/3; poses 489 [489–489]; cov 0.976 [0.976–0.976] | PASS 3/3; poses 489 [489–489]; cov 0.976 [0.976–0.976] |
| h01_0_900 | PASS 3/3; poses 426 [426–426]; cov 0.944 [0.944–0.944] | PASS 3/3; poses 426 [426–426]; cov 0.944 [0.944–0.944] | PASS 3/3; poses 426 [426–426]; cov 0.944 [0.944–0.944] |
| fjord5_s60_d30 | PASS 3/3; poses 290 [290–290]; cov 0.964 [0.964–0.964] | PASS 3/3; poses 290 [290–290]; cov 0.964 [0.964–0.964] | PASS 3/3; poses 290 [290–290]; cov 0.964 [0.964–0.964] |
| fjord6_s45_d45 | PASS 3/3; poses 440 [440–440]; cov 0.976 [0.976–0.976] | PASS 3/3; poses 440 [440–440]; cov 0.976 [0.976–0.976] | PASS 3/3; poses 440 [440–440]; cov 0.976 [0.976–0.976] |

`PASS` 要求 3/3 次均初始化且每次覆盖率 ≥0.70。位姿与覆盖率为中位 [完整范围]，失败不从分母移除。

上表是执行层 runability；是否满足“实际后端输入每帧 ≤350”另由下方预算审计决定。预算 FAIL 的窗口不进入严格前端贡献分母。

## 有效前端输入审计

| 窗口 | KLT feature topic | SP+LG feature topic | XFeat feature topic | 语义关系 | 归因状态 | IMU 等同 |
| --- | --- | --- | --- | --- | --- | --- |
| a03_5000_5900 | ed40a0c55d | ed40a0c55d | ed40a0c55d | KLT=SP+LG=XFeat-seed | NO_FRONTEND_ATTRIBUTION_IDENTICAL_BACKEND_INPUT | PASS |
| a01_16200_17100 | 9186b73141 | 0cbec392d1 | 9186b73141 | KLT=XFeat-seed;SP+LG_distinct | XFEAT_VS_KLT_NOT_ATTRIBUTABLE | PASS |
| a07_900_1800 | f7c64d94d4 | cbc3d8f91f | 12e75414fb | all_distinct | EFFECTIVE_INPUTS_DISTINCT | PASS |
| a07_1800_2700 | 574bab0400 | a1f9b5dde2 | 651833f84d | all_distinct | EFFECTIVE_INPUTS_DISTINCT | PASS |
| h07_0_1000 | 157037ff5d | 9c60bda397 | 7aecbca759 | all_distinct | EFFECTIVE_INPUTS_DISTINCT | PASS |
| h01_0_900 | e123ce3c8d | e123ce3c8d | e123ce3c8d | KLT=SP+LG=XFeat-seed | NO_FRONTEND_ATTRIBUTION_IDENTICAL_BACKEND_INPUT | PASS |
| fjord5_s60_d30 | 6a418d8aeb | 6a418d8aeb | bb8804c3f8 | KLT=SP+LG;XFeat-seed_distinct | KLT_VS_SPLG_NOT_ATTRIBUTABLE | PASS |
| fjord6_s45_d45 | ea95b28c4c | 19db1eb828 | 25c2f8466e | all_distinct | EFFECTIVE_INPUTS_DISTINCT | PASS |

feature-topic 消息流语义哈希相同的 pair 不用于前端贡献归因。下面的完整精度表保留所有 common-support 窗口以便审计；真正的前端贡献结论进一步按具体 contrast 排除相同输入。

冻结 seed-chain 是条件触发的；名义 learned method 可能产生候选但最终不向后端注入 learned observation。激活统计如下（同一 learned track 在多个帧出现会重复计 observation）：

| 窗口 | SP+LG learned obs | SP active frames | XFeat learned obs | XFeat active frames |
| --- | --- | --- | --- | --- |
| a03_5000_5900 | 0 | 0 | 0 | 0 |
| a01_16200_17100 | 50 | 5 | 0 | 0 |
| a07_900_1800 | 50 | 5 | 50 | 5 |
| a07_1800_2700 | 50 | 5 | 18 | 3 |
| h07_0_1000 | 0 | 0 | 50 | 6 |
| h01_0_900 | 0 | 0 | 0 | 0 |
| fjord5_s60_d30 | 0 | 0 | 0 | 0 |
| fjord6_s45_d45 | 50 | 5 | 9 | 3 |

## 实际 feature budget 审计

配置虽为 `EXPORT_MAX_FEATURES=350`，但在线 seed 注入发生在一次 cap 之后；少数激活帧实际送入 VINS 的 PointCloud 超过 350。严格合同按后端实际收到的点数审计：

| 窗口 | KLT | SP+LG | XFeat-seed |
| --- | --- | --- | --- |
| a03_5000_5900 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| a01_16200_17100 | PASS; max 350; >350 0 frame(s) | FAIL; max 359; >350 1 frame(s) | PASS; max 350; >350 0 frame(s) |
| a07_900_1800 | PASS; max 350; >350 0 frame(s) | FAIL; max 361; >350 1 frame(s) | FAIL; max 361; >350 1 frame(s) |
| a07_1800_2700 | PASS; max 350; >350 0 frame(s) | FAIL; max 359; >350 2 frame(s) | FAIL; max 354; >350 1 frame(s) |
| h07_0_1000 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| h01_0_900 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| fjord5_s60_d30 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| fjord6_s45_d45 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | FAIL; max 353; >350 1 frame(s) |

因此 `a01_16200_17100`、`a07_900_1800`、`a07_1800_2700`、`fjord6_s45_d45` 至少一个 learned arm 违反实际 350 上限。其完整 runability/精度仍保留，但不用于严格前端贡献结论；尤其 `a07_900_1800` 上 XFeat 的明显稳定性优势目前只能算探索性现象，不能当作公平预算证据。

## Common-support 资格

| 窗口 | 精度资格 | 原因 | 共同支撑 / 预注册门 |
| --- | --- | --- | --- |
| a03_5000_5900 | PASS | NONE | poses 32/30; coverage 0.711/0.700; span 31.0/10.0 s; RPE pairs 31/10 |
| a01_16200_17100 | PASS | NONE | poses 43/30; coverage 0.956/0.700; span 42.0/10.0 s; RPE pairs 42/10 |
| a07_900_1800 | PASS | NONE | poses 38/30; coverage 0.826/0.700; span 39.0/10.0 s; RPE pairs 36/10 |
| a07_1800_2700 | PASS | NONE | poses 40/30; coverage 0.909/0.700; span 39.0/10.0 s; RPE pairs 39/10 |
| h07_0_1000 | PASS | NONE | poses 94/30; coverage 0.931/0.700; span 48.0/10.0 s; RPE pairs 90/10 |
| h01_0_900 | PASS | NONE | poses 85/30; coverage 0.934/0.700; span 42.0/10.0 s; RPE pairs 83/10 |
| fjord5_s60_d30 | PASS | NONE | poses 289/30; coverage 0.967/0.700; span 28.8/10.0 s; RPE pairs 279/10 |
| fjord6_s45_d45 | PASS | NONE | poses 439/30; coverage 0.978/0.700; span 43.8/10.0 s; RPE pairs 429/10 |

共同门为 ≥30 poses、≥10 s、≥70% 覆盖和 ≥10 个严格 1 s RPE 对，且使用九条轨迹的同一交集。

评测审计中发现 NTNU 的 `start` 是相对 raw bag 首时刻，而初版分析误按 baseline 首时刻加 offset，导致共同网格错位。最终结果改用已冻结 `frontend_metrics.csv` 中实际选定图像的首末 timestamp；没有重跑前端/VINS，也没有改变任何门槛或轨迹。修正后 fjord5/fjord6 分别获得 289/439 个共同位姿。

## 精度

APE/RPE 为与 COLMAP 或数据集 baseline proxy 的一致程度，不是独立 GT 绝对误差。每条轨迹独立 fixed-scale proper SE(3) 对齐；禁止 Sim(3) 与尺度拟合。

| Window | KLT APE/RPE | SP+LG APE/RPE | XFeat APE/RPE | Common poses | 1 s pairs |
| --- | --- | --- | --- | --- | --- |
| a03_5000_5900 | 254.0998 [0.853661–254.109377] / 36.0104 [0.098418–36.012757] | 254.0998 [254.099753–254.238510] / 36.0104 [36.010374–36.030959] | 254.0998 [0.657827–254.183505] / 36.0104 [0.075886–36.023328] | 32 | 31 |
| a01_16200_17100 | 1.2354 [1.076271–1.398591] / 0.1006 [0.088104–0.113533] | 1.0703 [1.052710–1.227635] / 0.0877 [0.086322–0.100021] | 1.1337 [1.133304–1.133783] / 0.0926 [0.092548–0.092587] | 43 | 42 |
| a07_900_1800 | 1.2884 [1.288329–1928.105461] / 0.1309 [0.130883–206.938069] | 112.5498 [108.644594–2606.330808] / 13.4607 [12.828020–295.091660] | 0.8892 [0.888313–0.889216] / 0.0959 [0.095656–0.095879] | 38 | 36 |
| a07_1800_2700 | 0.6162 [0.613203–0.616862] / 0.1243 [0.124248–0.124370] | 0.6055 [0.536404–0.606622] / 0.1239 [0.121143–0.123909] | 0.6169 [0.549117–0.617406] / 0.1245 [0.121789–0.124538] | 40 | 39 |
| h07_0_1000 | 1.3066 [1.262906–1.404769] / 0.2044 [0.199777–0.229323] | 1.2801 [1.195699–1.315807] / 0.2144 [0.212582–0.226945] | 1.3728 [1.270438–1.411451] / 0.2407 [0.196109–0.259814] | 94 | 90 |
| h01_0_900 | 0.0716 [0.071507–0.071762] / 0.0116 [0.011540–0.011634] | 0.0717 [0.071648–0.071759] / 0.0114 [0.011376–0.011653] | 0.0716 [0.071591–0.071690] / 0.0114 [0.011403–0.011668] | 85 | 83 |
| fjord5_s60_d30 | 0.1310 [0.130975–0.130977] / 0.0406 [0.040598–0.040598] | 0.1310 [0.130974–0.130977] / 0.0406 [0.040598–0.040601] | 0.1317 [0.131720–0.131720] / 0.0410 [0.041016–0.041016] | 289 | 279 |
| fjord6_s45_d45 | 0.1354 [0.135416–0.135426] / 0.0397 [0.039701–0.039703] | 0.1355 [0.135500–0.135510] / 0.0397 [0.039734–0.039736] | 0.1353 [0.135265–0.135279] / 0.0396 [0.039615–0.039618] | 439 | 429 |

| 窗口 | 前端 | proxy 首末位移 (m) | SE(3) 后估计首末位移：中位 [范围] (m) |
| --- | --- | --- | --- |
| a01_16200_17100 | KLT | 5.265 | 1.158 [0.620–1.681] |
| a01_16200_17100 | SP+LG | 5.265 | 1.702 [1.184–1.759] |
| a01_16200_17100 | XFeat-seed | 5.265 | 1.492 [1.492–1.494] |
| a03_5000_5900 | KLT | 4.800 | 851.717 [2.026–851.759] |
| a03_5000_5900 | SP+LG | 4.800 | 851.717 [851.717–852.197] |
| a03_5000_5900 | XFeat-seed | 4.800 | 851.717 [2.636–852.012] |
| a07_1800_2700 | KLT | 7.018 | 4.910 [4.908–4.920] |
| a07_1800_2700 | SP+LG | 7.018 | 4.940 [4.937–5.172] |
| a07_1800_2700 | XFeat-seed | 7.018 | 4.900 [4.899–5.128] |
| a07_900_1800 | KLT | 6.434 | 1.996 [1.996–6076.649] |
| a07_900_1800 | SP+LG | 6.434 | 375.485 [360.592–7876.363] |
| a07_900_1800 | XFeat-seed | 6.434 | 3.357 [3.357–3.360] |
| fjord5_s60_d30 | KLT | 9.632 | 9.185 [9.185–9.185] |
| fjord5_s60_d30 | SP+LG | 9.632 | 9.185 [9.185–9.185] |
| fjord5_s60_d30 | XFeat-seed | 9.632 | 9.174 [9.174–9.174] |
| fjord6_s45_d45 | KLT | 1.945 | 1.798 [1.798–1.798] |
| fjord6_s45_d45 | SP+LG | 1.945 | 1.800 [1.799–1.800] |
| fjord6_s45_d45 | XFeat-seed | 1.945 | 1.801 [1.800–1.801] |
| h01_0_900 | KLT | 4.459 | 4.240 [4.239–4.241] |
| h01_0_900 | SP+LG | 4.459 | 4.239 [4.238–4.240] |
| h01_0_900 | XFeat-seed | 4.459 | 4.240 [4.239–4.240] |
| h07_0_1000 | KLT | 7.167 | 9.706 [9.317–10.293] |
| h07_0_1000 | SP+LG | 7.167 | 9.490 [8.109–9.687] |
| h07_0_1000 | XFeat-seed | 7.167 | 10.012 [9.537–10.948] |

## Pairwise 可归因结论

在 2 个同时满足 common support、pairwise 输入不同与实际 350 上限的窗口上，XFeat-seed 相对 KLT 的窗口中位 APE/RPE 变化为 +2.81%/+9.39%；胜/平/负为 APE 0/0/2、RPE 0/0/2。 在 2 个同时满足 common support、pairwise 输入不同与实际 350 上限的窗口上，XFeat-seed 相对 SP+LG 的窗口中位 APE/RPE 变化为 +3.90%/+6.62%；胜/平/负为 APE 0/0/2、RPE 0/0/2。

窗口才是独立科学单位；重复仅刻画 replay 变化。`a03_5000_5900` 与 `h01_0_900` 三臂 feature-topic 输入相同，因此其数值差异只反映后端 replay 敏感性。最终每个 contrast 仅剩 2 个同时满足 common support、输入不同和实际 ≤350 的窗口，不作普遍胜出声明。

| Contrast | Metric | n | median Δ (m) | range Δ (m) | median Δ (%) | wins/ties/losses |
| --- | --- | --- | --- | --- | --- | --- |
| XFeat-seed − KLT | APE | 2 | 0.033440 | 0.000744–0.066136 | 2.81 | 0/0/2 |
| XFeat-seed − KLT | RPE | 2 | 0.018355 | 0.000418–0.036293 | 9.39 | 0/0/2 |
| XFeat-seed − SP+LG | APE | 2 | 0.046708 | 0.000743–0.092672 | 3.90 | 0/0/2 |
| XFeat-seed − SP+LG | RPE | 2 | 0.013312 | 0.000418–0.026207 | 6.62 | 0/0/2 |

## 产物

- [windows.csv](windows.csv)、[contract.json](contract.json)、[preregistration.md](preregistration.md)
- [runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv)
- [accuracy.csv](accuracy.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)
- [common_support_status.csv](common_support_status.csv)
- [backend_config_audit.csv](backend_config_audit.csv)、[effective_frontend_input_audit.csv](effective_frontend_input_audit.csv)、[frontend_activation.csv](frontend_activation.csv)
- [backend_feature_budget_audit.csv](backend_feature_budget_audit.csv)
- [pairwise_attribution_windows.csv](pairwise_attribution_windows.csv)、[pairwise_attributable_effects.csv](pairwise_attributable_effects.csv)
- [artifacts.sha256](artifacts.sha256)

运行目录通过工作区 `logs/.../external_*_fsbcs1_*` 路径访问，物理文件位于 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_supplemental_v1`。wall-clock 效率不进入本报告。
