# 固定 VINS-Fusion 后端的前端隔离对比

## 定位与结论边界

本表是**前端隔离对比**：KLT、SP+LG 与 XFeat-seed 均送入同一冻结的 `VINS-Fusion-origin` 后端，只改变前端 `method/config`，对标 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 采用关键帧与局部 BA 后端，属于不同设计空间，只能单列为 reference；本文不做整系统对 HFNet 的精度声明。

Runability 是第一指标。预注册 7 个窗口、3 个前端、每格 3 次 VINS replay，共 63 次；63/63 均完成初始化，但 18/63 因覆盖率低于 70% 判为失败。窗口级原始通过数为 KLT 4/7、SP+LG 5/7、XFeat-seed 5/7。原先观察到的 `a09_4000_4400` / `a10_2400_2800` 胜负涉及 learned 臂实际超过 350，不能作为严格公平 runability 归因；在输入确实不同且三臂均满足实际 350 的 `a09_6000_6800`、`a10_4800_5200` 上，三臂均通过，因此没有 runability 优越性结论。

只有 `a09_6000_6800` 通过 all-arm、all-repeat 共同支撑门。该单一窗口上，XFeat-seed 相对 KLT 的 APE/RPE 中位变化为 -99.94%/-99.95%，相对 SP+LG 为 -99.97%/-99.97%。这只是 (n=1) 窗口的描述性结果；不能据此宣称跨窗口普遍胜出，也不报告显著性检验。

## 扩窗补充批次

另预注册并完成了 8 个 30–50 s 新窗口 × 3 前端 × 3 重复。由于运行前本机 `libvins_lib.so` 已被其他构建替换，扩窗批次属于独立 backend epoch，不能与本表的 exact-build 精度分母合并。扩窗原始 runability 为三臂均 8/8，8/8 窗通过 common-support；但实际预算审计发现 4 窗至少一个 learned 臂有 1–2 帧超过 350，最终每个 XFeat contrast 仅剩 2 个严格可归因窗口，XFeat 在两窗均未胜出。详见[扩窗补充报告](../frontend_same_backend_comparison_supplemental_v1/report.md)。

## Runability 表

| Window | KLT | SP+LG | XFeat-seed |
| --- | --- | --- | --- |
| a02_4500_6300 | FAIL 0/3; poses 423 [207–436]; cov 0.450 [0.210–0.468] | PASS 3/3; poses 811 [809–888]; cov 0.900 [0.898–0.986] | PASS 3/3; poses 888 [888–888]; cov 0.986 [0.986–0.986] |
| a09_4000_4400 | FAIL 2/3; poses 161 [143–180]; cov 0.800 [0.620–0.895] | PASS 3/3; poses 180 [170–180]; cov 0.895 [0.845–0.895] | PASS 3/3; poses 170 [170–170]; cov 0.845 [0.845–0.845] |
| a09_6000_6800 | PASS 3/3; poses 388 [388–388]; cov 0.967 [0.967–0.967] | PASS 3/3; poses 388 [388–388]; cov 0.967 [0.967–0.967] | PASS 3/3; poses 388 [388–388]; cov 0.967 [0.967–0.967] |
| a10_2400_2800 | PASS 3/3; poses 157 [157–159]; cov 0.780 [0.745–0.780] | FAIL 1/3; poses 99 [99–157]; cov 0.490 [0.490–0.780] | FAIL 0/3; poses 136 [136–136]; cov 0.675 [0.675–0.675] |
| a10_4800_5200 | PASS 3/3; poses 190 [190–190]; cov 0.945 [0.945–0.945] | PASS 3/3; poses 190 [166–190]; cov 0.945 [0.825–0.945] | PASS 3/3; poses 190 [190–190]; cov 0.945 [0.945–0.945] |
| h07_1660_1720 | FAIL 0/3; poses 16 [16–18]; cov 0.501 [0.501–0.568] | FAIL 0/3; poses 16 [16–16]; cov 0.501 [0.501–0.501] | FAIL 0/3; poses 17 [17–17]; cov 0.535 [0.535–0.535] |
| mclab1_s60_d15 | PASS 3/3; poses 140 [140–140]; cov 0.928 [0.928–0.928] | PASS 3/3; poses 140 [132–140]; cov 0.928 [0.874–0.928] | PASS 3/3; poses 140 [140–140]; cov 0.928 [0.928–0.928] |

`PASS` 要求 3/3 次均初始化且每次覆盖率 ≥ 0.70。表中位姿数与覆盖率为 3 次的中位 [完整范围]。所有失败保留在分母中，未补跑后挑窗；本轮失败类别只有 `COVERAGE_FAIL`，没有配置错误、激励不足或冷启动未初始化。

## 有效前端输入审计

名义 method 不等于后端实际收到的输入；只有 feature bag 不同，才可把后端差异归因于前端。SHA-256 审计如下：

| 窗口 | KLT bag | SP+LG bag | XFeat bag | 字节关系 | 归因状态 |
| --- | --- | --- | --- | --- | --- |
| a02_4500_6300 | a0d07a4266 | a0d07a4266 | a0d07a4266 | KLT=SP+LG=XFeat-seed | NO_FRONTEND_ATTRIBUTION_IDENTICAL_BACKEND_INPUT |
| a09_4000_4400 | 7621059903 | d654c26e17 | f7f2fac8ca | all_distinct | EFFECTIVE_INPUTS_DISTINCT |
| a09_6000_6800 | 6de8ffe922 | dcb29e971d | 76452b8cbb | all_distinct | EFFECTIVE_INPUTS_DISTINCT |
| a10_2400_2800 | ad94e3ffe7 | 134b86745e | cb15be6f95 | all_distinct | EFFECTIVE_INPUTS_DISTINCT |
| a10_4800_5200 | 5068c4bb35 | 9b5a8b1fb4 | 75d6895350 | all_distinct | EFFECTIVE_INPUTS_DISTINCT |
| h07_1660_1720 | d286bedd22 | d286bedd22 | 3df2775b1d | KLT=SP+LG;XFeat-seed_distinct | KLT_VS_SPLG_NOT_ATTRIBUTABLE |
| mclab1_s60_d15 | 0f2b59a046 | 9f6be4027b | e2fd02249f | all_distinct | EFFECTIVE_INPUTS_DISTINCT |

`a02_4500_6300` 三臂 bag 字节完全相同，因此该窗 KLT FAIL、两学习臂 PASS 是同一后端输入下的初始化/求解路径随机性，**不能**作为前端贡献证据。`h07_1660_1720` 的 KLT 与 SP+LG bag 相同，二者也不可作前端归因。唯一进入精度表的 `a09_6000_6800` 三臂 bag 均不同。

## 实际 feature budget 审计

配置为 `EXPORT_MAX_FEATURES=350`，但在线 seed 注入在少数帧发生于 cap 之后。以下为 VINS 实际收到的 PointCloud 点数：

| 窗口 | KLT | SP+LG | XFeat-seed |
| --- | --- | --- | --- |
| a02_4500_6300 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| a09_4000_4400 | PASS; max 350; >350 0 frame(s) | FAIL; max 360; >350 1 frame(s) | FAIL; max 355; >350 1 frame(s) |
| a09_6000_6800 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| a10_2400_2800 | PASS; max 350; >350 0 frame(s) | FAIL; max 365; >350 2 frame(s) | FAIL; max 362; >350 2 frame(s) |
| a10_4800_5200 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) |
| h07_1660_1720 | PASS; max 350; >350 0 frame(s) | PASS; max 350; >350 0 frame(s) | FAIL; max 353; >350 1 frame(s) |
| mclab1_s60_d15 | PASS; max 350; >350 0 frame(s) | FAIL; max 353; >350 2 frame(s) | FAIL; max 352; >350 2 frame(s) |

唯一进入精度表的 `a09_6000_6800` 三臂均严格不超过 350，因此其 n=1 精度结果仍满足预算合同；预算 FAIL 窗口不用于严格 runability 归因。

## 精度资格与 common support

精度仅在所有 9 条轨迹均通过 runability 后评估，并取同一共同位姿交集与同一 1 s RPE 网格。额外预注册门为 ≥30 个共同位姿、共同跨度 ≥10 s、共同覆盖 ≥70%、≥10 个 RPE 对。

| 窗口 | 精度资格 | 原因 | 共同支撑 / 预注册门 |
| --- | --- | --- | --- |
| a02_4500_6300 | EXCLUDED | RUNABILITY | 未评估（未通过 all-arm runability） |
| a09_4000_4400 | EXCLUDED | RUNABILITY | 未评估（未通过 all-arm runability） |
| a09_6000_6800 | PASS | NONE | poses 38/30; coverage 0.950/0.700; span 37.0/10.0 s; RPE pairs 37/10 |
| a10_2400_2800 | EXCLUDED | RUNABILITY | 未评估（未通过 all-arm runability） |
| a10_4800_5200 | EXCLUDED | COMMON_SUPPORT_GATE | poses 16/30; coverage 0.800/0.700; span 15.0/10.0 s; RPE pairs 15/10 |
| h07_1660_1720 | EXCLUDED | RUNABILITY | 未评估（未通过 all-arm runability） |
| mclab1_s60_d15 | EXCLUDED | COMMON_SUPPORT_GATE | poses 100/30; coverage 0.662/0.700; span 9.9/10.0 s; RPE pairs 90/10 |

`a10_4800_5200` 虽三臂 runability 均通过，但只有 16 个共同位姿，低于 30；`mclab1_s60_d15` 的共同覆盖为 0.662 且跨度 9.9 s，均未达到门槛。两窗均不进入精度分母，未使用其事后可见的 APE/RPE。

## Common-support 精度

数值为 APE RMSE / 1 s 平移 RPE RMSE，单位 m，报告 3 次中位 [完整范围]。每条轨迹独立做 fixed-scale proper SE(3) 对齐；禁止 Sim(3) 和尺度拟合。这些数值表示**与 COLMAP/数据集 baseline proxy 的一致程度**，不是独立 GT 的绝对误差。

| Window | KLT APE/RPE | SP+LG APE/RPE | XFeat APE/RPE | Common poses | 1 s pairs |
| --- | --- | --- | --- | --- | --- |
| a09_6000_6800 | 1234.1316 [1230.939397–1296.253955] / 150.0565 [149.678915–156.964956] | 2173.4682 [1659.870162–2240.869764] / 248.9995 [198.168622–259.044957] | 0.7149 [0.714522–0.714905] / 0.0708 [0.070811–0.070818] | 38 | 37 |

内部实现与 evo 1.31.1 的最大绝对差分别小于 4.9e-7 m（APE）和 5.0e-7 m（RPE）。极大的 KLT/SP+LG 数值不是尺度拟合造成的：固定尺度对齐后，首末位移审计为：

| 窗口 | 前端 | proxy 首末位移 (m) | SE(3) 后估计首末位移：中位 [范围] (m) |
| --- | --- | --- | --- |
| a09_6000_6800 | KLT | 7.159 | 4076.737 [4066.728–4274.824] |
| a09_6000_6800 | SP+LG | 7.159 | 6883.241 [5430.518–7151.031] |
| a09_6000_6800 | XFeat-seed | 7.159 | 9.447 [9.447–9.447] |

proxy 的首末位移约 7.16 m，而 KLT/SP+LG 仍为公里级，说明这一窗口发生尺度发散；XFeat-seed 约 9.45 m。因此本窗结果支持“XFeat-seed 与 proxy 更一致”，但证据分母仍只有一个窗口。

## 配对效应（描述性）

符号为 XFeat-seed 减去对照，负值有利于 XFeat-seed。重复只刻画 replay 变化，不作为独立样本。

| Contrast | Metric | n | median Δ (m) | range Δ (m) | median Δ (%) | wins/ties/losses |
| --- | --- | --- | --- | --- | --- | --- |
| XFeat-seed − KLT | APE | 1 | -1233.416686 | -1233.416686–-1233.416686 | -99.94 | 1/0/0 |
| XFeat-seed − KLT | RPE | 1 | -149.985679 | -149.985679–-149.985679 | -99.95 | 1/0/0 |
| XFeat-seed − SP+LG | APE | 1 | -2172.753341 | -2172.753341–-2172.753341 | -99.97 | 1/0/0 |
| XFeat-seed − SP+LG | RPE | 1 | -248.928715 | -248.928715–-248.928715 | -99.97 | 1/0/0 |

## 冻结合同与来源谱系

所有臂共用 exporter SHA-256 `68453b035037d04087dbad3e512c602b4ef6967b2a8cf6d14e34a14750f2312d`、feature budget 350、`every_n=2`、`frame_offset=1`、`MEASUREMENT_SELECTION=0`、`VINS_SAFE_SOURCE_SELECTION=0`、相同质量映射、VINS 参数与后端二进制。[backend_config_audit.csv](backend_config_audit.csv) 显示每个窗口 9 份归一化 VINS YAML 均为同一哈希，7/7 窗口通过后端一致性审计。

XFeat 配置哈希 `6f89d861...00bf3` 与 `P_legacy_nativeq_xfeat_seedchain_v3` 指定文件完全一致。历史 P 合同还固定过 exporter `7ed31890...eae7cf`，但该字节树当前不存在；所以本结果是“冻结 P seed-chain 配置在当前统一 exporter 上的全臂新执行”，不是历史 P 执行树的 byte-exact replay。未将历史 KLT fallback 或 7 月 Learned+KLT 结果改名为当前 XFeat。

LoFTR 是可选臂，未进入预注册主表，也未在结果后追加。由于共享磁盘上有独立 CPU exporter 重叠，本报告不比较 wall-clock 效率，见 [execution_conditions.md](execution_conditions.md)。

## 产物与复核入口

- 预注册：[preregistration.md](preregistration.md)、[contract.json](contract.json)、[windows.csv](windows.csv)、[arms.csv](arms.csv)
- Runability：[runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv)
- 精度：[accuracy.csv](accuracy.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)、[common_support_status.csv](common_support_status.csv)
- 公平性审计：[backend_config_audit.csv](backend_config_audit.csv)、[effective_frontend_input_audit.csv](effective_frontend_input_audit.csv)、[backend_feature_budget_audit.csv](backend_feature_budget_audit.csv)、[trajectory_scale_audit.csv](trajectory_scale_audit.csv)
- 模型身份：[runtime_weight_lock.json](runtime_weight_lock.json)
- 图：[figure-01-runability.pdf](analysis-output/figures/figure-01-runability.pdf)、[figure-02-common-support-accuracy.pdf](analysis-output/figures/figure-02-common-support-accuracy.pdf)
- 完整路径与 SHA-256：[artifacts.sha256](artifacts.sha256)

哈希清单包含正式 `vio.csv`、`vins.log`、feature bag、frontend metrics、VINS YAML、共同支撑/evo 产物、报告、图与复现实验脚本的绝对路径。
