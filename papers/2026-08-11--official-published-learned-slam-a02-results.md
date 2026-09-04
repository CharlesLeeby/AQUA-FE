# A02 官方已发表学习型 SLAM 基线实验结果（r1）

日期：2026-08-11

## 结论先行

本轮严格执行了两套**正式发表、作者官方实现**的 learned-SLAM/VIO 基线，而不是把本项目的 SuperPoint/XFeat 高层适配器冒充论文系统：

1. **HFNet-SLAM**，Sensors 2023，DOI `10.3390/s23042113`；
2. **AnyFeature-VSLAM**，RSS 2024，DOI `10.15607/RSS.2024.XX.084`，其中 learned arm 为作者支持的 `r2d2_128`，same-system control 为 `orb32`。

两套官方系统都完成了真实构建或启动，但在冻结的 AQUALOC Archaeology A02 输入上都没有产生可评测轨迹。因此本轮得到的是**正式的 whole-system usability negative results**，不是 APE/RPE 胜负：

| 已发表官方系统 | 输入/范围 | 官方执行结果 | 可用轨迹 | 精度结论 |
|---|---:|---|---:|---|
| HFNet-SLAM, HF-Net + ORB-SLAM3 mono-inertial | A02 前 200 图 + 1,990 IMU，9.949 s | 两次视觉-惯性初始化均因运动不足 reset；最终 0 KFs；空地图保存路径随后 SIGSEGV，raw RC 139 | 0 poses | 不可评测；按预注册 STOP，不扩 full |
| AnyFeature-VSLAM `r2d2_128` | index-0 official ingestion smoke | 官方配置 `r2d2_128_settings.yaml:11` 的 `0.38f` 被 OpenCV 4.9 FileStorage 判为非法浮点，SIGABRT，raw RC 134；尚未进入图像/R2D2-bin 读取循环 | 无 | learned full 永久 STOP；不得修官方配置或重跑 |
| AnyFeature-VSLAM `orb32` same-system control | A02 全 901 图，44.992 s | 901/901 图进入官方处理循环；0 KFs、0 map points、0 observations、无一次成功 tracking 增量；空轨迹落盘后官方 joinable thread 析构触发 `std::terminate`，raw RC 134 | 0 poses | whole-system unusable；不可作单边 Sim(3) 精度 |

这意味着当前不能诚实给出“官方 learned paper baseline 的 APE/RPE 比较表”。任何将 AQUA-FE component-aligned XFeat/SP-LK 数值与上述空轨迹系统混排为官方论文复现的做法，都会越过证据边界。

## 1. 共同约束

- 不修改官方网络、特征阈值、SLAM tracker/backend、初始化、线程或轨迹保存逻辑。
- 仅允许数据布局、时间戳、标定、模型路径和项目侧 fail-closed 运行封装。
- 每个正式运行只有一次；初始化失败、崩溃、空轨迹或精度差均不允许换窗、换阈值或重跑。
- A02 `/aqualoc/colmap_gt` 是 same-image COLMAP + pressure-scale reference proxy，不是独立 ground truth。
- 只有两条 full trajectory 都封存且通过语法/共同支撑门时，才允许一次 Sim(3) 评价。本轮该条件不成立，reference exporter 与 evaluator 均未运行。

## 2. HFNet-SLAM 正式结果

### 2.1 身份与运行边界

- 论文：HFNet-SLAM, Sensors 2023, DOI `10.3390/s23042113`。
- 官方作者 build-repair commit：`c354c72588a97bb6f6a9c7c8317530795956ec80`。该 commit 仅修复作者仓库的构建/命名空间问题；论文期算法路径不变，且晚于论文，已明确披露。
- 官方 binary SHA-256：`4029c6ba8ecdc76c98f2c190c1a1151493ed2553da087c1a4f077fc036e143a3`。
- 官方 HF-Net ONNX SHA-256：`354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5`。
- A02 config SHA-256：`7e6482653e55b2fcf86a9e5418fd87747677a88eb9c06443d505cda311b80569`。
- 输入 manifest SHA-256：`9905ba2249e062f02f9be4743acb56d51ada514f97e2f62b766e5e218fca3158`。

真实单图 model smoke 已先通过：四个 TensorRT models 初始化成功，HFextractor 返回 405 个 keypoints；这只证明部署闭包，不是轨迹结果。随后唯一 prefix200 运行读取 200 图、200 timestamps 和 1,990 条 IMU：

- 第一次初始化：init frame 4，建立 101 map points；IMU initialization marker 出现后因 `Not enough motion for initializing` reset，49 frames set lost；
- 第二次初始化：init frame 110，建立 139 map points；同样 reset，97 frames set lost；
- 最终 0 keyframes、0 trajectory poses；
- 之后 `SaveTrajectoryEuRoC` 在空地图上解引用未初始化 `pBiggerMap`，导致 SIGSEGV/RC 139。该保存崩溃发生在初始化失败之后，不是初始化首因。

冻结结果：`papers/hfnet_slam_a02_prefix200_result_r1.json`，SHA-256 `9e42c9e1f9b2848b45ff90d1a1bc581ba42752a91dcf07a0ac5bdecfa8d3a4c4`。决策为 `STOP / ALGORITHM_INITIALIZATION_FAILED`，不允许 full-window 补救。

## 3. AnyFeature-VSLAM 正式结果

### 3.1 官方身份与输入

- 论文：AnyFeature-VSLAM, RSS 2024, DOI `10.15607/RSS.2024.XX.084`。
- 官方 paper snapshot：`6aa014b724f7a61bcbff2f8f28f20836986a43dc`；tree `36b264e1da05c6fe9cd987965e9a75ba96930b63`。
- 官方 binary SHA-256：`9adb623fc8d83ce35297be7a7d810d269cd65273bd0f4fb1bddebbec0b8bdd59`。
- 官方 core-library SHA-256：`eea4a5a6c5dccb5825a8e6a1a3249c6b808881a22c7fe301d0a2a90efaa99954`。
- DBoW2 submodule/library：commit `f4d585b45237836dbde757c0c8ec8b098ad1164a`；library SHA-256 `7215c8425e3620834ef24ea17f26fd0635b15d9d85b0093b00220e553a40c8c5`。
- A02 full camera manifest SHA-256：`2f08cc97e71d44e56d90720fbdd5bf925c1c7e5892096743f67265fc2df34afe`。
- `rgb.txt` SHA-256：`abb30058d0ec330a3860ca45674bf99930548e71c68c2b8f19eeac416020908f`。
- sequence identity：`d43ee7b00bf759ca3c5c2c60e532e453a797300d34a830d7777999931d5fb6e3`。

独立输入审计确认：901/901 PNG 与原 bag 像素一致，header/record stamps 相等且严格递增；前 200 PNG 与 prefix 字节完全相同，后 701 PNG 与冻结无损编码器重算逐字节相同。

### 3.2 R2D2 producer 与接口闭包

官方 NAVER R2D2 CPU producer 对 200 帧唯一运行完成：RC 0，200/200 archives，elapsed `2264.3675 s`，每帧恰 5,000 proposals；全部 `(N,3)` keypoints、`(N,128)` descriptors、`(N,)` scores 为 `<f4`、finite、坐标/尺度合法。

项目侧 adapter 只做表示层转换：官方 float32 数值逐值精确扩宽为 AnyFeature paper loader 实际读取的 little-endian float64；200 帧三类 bins 全部 roundtrip exact。它不改变数值、顺序、数量、网络或 SLAM reader。

- producer manifest SHA-256：`38acc02c00593c136dc98a591158636232d7d68ece962b6a72d1a4587d695365`；
- materialization manifest SHA-256：`914f5697fa5d3b8744ee622855ee60124a0db8a72bf540e04055958b50caa5f5`；
- validate-output report SHA-256：`0a4d7a101a5c2040af059a1b8d2c5e5f3284a33c04e3a418eef2e61994374751`。

### 3.3 runner-v1 无效预检与 runner-v2 治理

首次 v1 harness 调用因项目侧 `ldd` symlink/realpath 文本比较错误而在官方进程启动前 RC 2。它没有创建 experiment folder，也没有任何官方输出，因此透明封存为 infrastructure-invalid，不冒充 official smoke：

- failure seal SHA-256：`7571e76a55b69eeb6c12d999c05ceb74e06c26f921429a4bfd81549587619af2`；
- v1 runner 保持原 SHA-256 `0c60fa8126dbc9dfb309b995c15bb324eea29899b07145afc69c10324538707f`；
- runner-v2 仅修复 `.409` SONAME 与 `.4.9.0` target 的严格同文件等价判断，SHA-256 `93f0342903e4e5ab9e2a3618ca77d08a7598ff19d67af42f0719a63b42dc5db3`；
- addendum SHA-256：`eb1ab675c6734c5d6522b5b858942176ce4d861b2a7dd4ba73ac5c54f99491ea`；
- execution freeze-r2 SHA-256：`c67d4b1af25ae57eefdb7dfc18fe942a26e12bc4b5a14b633ceb36e56aa219ea`；
- v1/v2 tests 共 16/16 PASS，独立审计 P0=0/P1=0。

V2 预检随后 RC 0 / `PREFLIGHT_READY`，才允许唯一 official smoke start。此处没有改官方源码、配置或二进制。

### 3.4 `r2d2_128` learned arm：官方配置兼容性失败

唯一 official smoke 真实启动后：

- raw RC 134 / SIGABRT；runner status `SMOKE_R2D2_INGESTION_CLOSURE_FAILED`；
- elapsed `38.288 s`，MaxRSS `711856 KiB`；
- 官方完成 R2D2 vocabulary 加载，并在 settings 解析阶段失败，尚未进入图像主循环；
- stderr：OpenCV 4.9 `processSpecialDouble` 报 `r2d2_128_settings.yaml(11): Bad format of floating-point constant`；
- 官方 Git blob 与工作树都写 `FeatureMatcher.matchingTh: 0.38f`，settings SHA-256 `375ae1bdcfe92068a665f16b9943b09fb0c830be471f675ddb85289442526878`；
- 无 trajectory/statistics、无 NaN/Inf、无残留进程，官方树 clean。

Run manifest SHA-256：`cb9909491c9ca6248d21b5217c99dfcf31b4916b7e5a564bede1cda1e72068aa`。按冻结规则，不将 `0.38f` 改成 `0.38`，不改 OpenCV，不换配置，不重跑；R2D2 full 永久 STOP。

### 3.5 `orb32` same-system control：全窗未初始化

`orb32` 使用合法官方 YAML 数字 `75.0`，preflight RC 0 / `PREFLIGHT_READY`。唯一 full run 的参数回显全部正确：901 images、`Feature=orb32`、`Vis=0`、`FixRes=0`，normal/init feature budgets 分别 2,000/4,000。

执行结果：

- 901/901 images 进入无 break 的官方 processing loop；
- median tracking compute time `0.0289681 s`，mean `0.0331571 s`；这些是官方内部 tracking compute 统计，不含输入节流或 R2D2 离线推理；
- 0 keyframes、0 map points、0 observations，空 keyframe trajectory（0 B）；
- statistics 中 `numTrackedFrames=2` 是源码初始常量且从未因 `bOK` 增加，不能误写为“只处理了两帧”；
- 轨迹/统计已落盘后，官方 local-mapping/loop-closing `std::thread` 未 join/detach，main 返回析构时触发 `terminate called without an active exception`；raw RC 134；
- runner status `FULL_RUN_UNUSABLE_RETAINED`，无残留进程，官方树 clean。

Run manifest SHA-256：`a40b89c21296ee89833b1709420bcfe3aee33f6e39de0aaeaadee6ace9b99640`；artifact tree SHA-256：`e0ac967fce7abac0ba9289d8dccde8ff86f6b198318eac53ad433bc85ef85967`。

## 4. 科学解释边界

本轮支持以下结论：

- 在“不改官方低层算法/源码”的约束下，HFNet-SLAM 与 AnyFeature-VSLAM 的论文官方实现均未在冻结 A02 轨道上产生可用轨迹；
- HFNet-SLAM 失败于该短前缀的运动/初始化条件，随后暴露空地图保存缺陷；
- AnyFeature learned R2D2 arm 失败于作者配置与冻结 OpenCV 运行栈的语法兼容性，尚未形成 learned tracking 结果；
- AnyFeature ORB32 control 完成全窗输入处理但未建图，随后暴露官方 teardown thread 缺陷；
- 这些都是部署/适用性与 whole-system usability 证据，不是“本项目方法在 APE/RPE 上优于论文方法”的证据。

本轮不支持以下表述：

- “R2D2 精度比 ORB32 差”——R2D2 未进入图像读取，ORB32 无轨迹；
- “AQUA-FE 显著优于 HFNet-SLAM/AnyFeature-VSLAM”——没有共同有效轨迹支撑数值比较；
- “官方代码无法运行”——HFNet model runtime 与 AnyFeature ORB processing loop 都真实运行过；更准确的是它们未在冻结合同下产生可评测轨迹；
- 将 XFeat-birth/KLT、SuperPoint-birth/KLT 或 SP-LG high-level adapters 称为上述官方论文系统复现。

## 5. 后续决策

本轮 A02 official-baseline 轨道到此停止，不修改 `0.38f`、线程析构、初始化参数或窗口来“救”结果。若论文需要正向数值 official baseline，只能另立**结果盲的新预注册轨道**，选择传感器模态和官方输入假设匹配的数据集，并在开始前明确：

- 是否允许作者仓库的非算法 artifact repair；
- official-as-is whole-system 表与固定预算 component-aligned 表分开；
- camera-only Sim(3) 与 mono-inertial SE(3) 不混排；
- 失败系统进入 usability/compatibility 表，不用调参后成功轨迹替换。
