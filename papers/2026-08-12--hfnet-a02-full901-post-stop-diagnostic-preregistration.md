# HFNet-SLAM A02 prefix200 失败诊断与 full901 post-STOP 预注册（r2）

日期：2026-08-12

## 结论

prefix200 跑不起来的最强解释不是 HF-Net 模型未加载、IMU 未进入系统、外参/时移符号错误，也不是最后的 SIGSEGV 本身；它是 **9.949 s 短前缀落在官方单目惯性初始化的反复“建图—IMU 初始化—早期运动保护 reset”周期内**。两次视觉地图分别已建立 101/139 个 map points，日志两次打印 `Imu initialized`，随后才打印 `Not enough motion for initializing. Reseting...`。因此部署闭包和视觉两视图初始化均已越过，失败点在官方 early inertial motion/scale conditioning。

full901（901 图，44.992 s）值得另立一次诊断轨道：后半段含比前 10 s 更强的图像非单应运动和 IMU 激励，允许一次初始化尝试跨过官方 10 s 保护区。它的成功先验明显高于 prefix200，但不能在运行前保证；若 reset 在安静区反复重启，full 仍可能失败。该轨道是用户要求的 **post-STOP usability diagnostic**，不会覆盖或回填 r1 的正式 `STOP`。

## 1. 官方触发链

冻结源码为 author official build-repair commit `c354c72588a97bb6f6a9c7c8317530795956ec80`、tree `6619814aed4cd0e4baa2501341a48f753f8ba196`：

- `src/LocalMapping.cc:1364-1397`：单目惯性 `InitializeIMU` 至少需要 10 个 keyframes 和 2.0 s；
- `src/Tracking.cc:2390-2400`：IMU 初始化前，单目惯性每隔至少 0.25 s 可强制插入 keyframe；初始化后 `src/Tracking.cc:2491-2505` 的时间条件为至少 0.5 s；
- `src/LocalMapping.cc:199-220`：初始化前相邻 keyframe camera-center 位移 `<0.03` 会 reset；
- `src/LocalMapping.cc:141-165`：IMU 标记已初始化、BA2 尚未完成时，若 `mTinit<10 s` 且最近两段位移的低通量 `distFiltered<0.02`，即打印本次日志中的 motion failure 并 reset。只有 `dist>0.05` 才累计 `mTinit`。

这些距离位于系统当前重建尺度，不能把物理 proxy 的米数直接代入阈值；但源代码和日志共同准确定位了触发分支。

## 2. 两次失败时间线

冻结 stdout SHA-256 为 `3dd3f060bfcb52adb80e2c657594f775665fd0c2f44b43582cad2e564460a7c0`：

1. 第一尝试：init frame 4，101 map points，`Imu initialized`，motion reset；之后报告 49 frames lost，下一地图从约 frame 63 后重新尝试。
2. 第二尝试：init frame 110，139 map points，`Imu initialized`，同一 motion reset；报告 97 frames lost。由 `mnFirstFrameId=121`、`mnInitialFrameId=63` 和 lost count 推断，第二 reset 约在 frame 160 附近完成，200-frame 前缀只余约 2 s，已不足以重新经历完整初始化与 10 s 保护。
3. shutdown 后 atlas 只剩 `Map 0 has 0 KFs`。这说明保存时没有可输出地图，不是模型加载失败。

离线、非算法性的 LK/F-matrix 图像运动审计进一步显示第二次视觉初始化的支持明显更弱：frame 4→14（0.501 s）有 3,069 条 FB-valid tracks、median displacement 18.14 px、3,006 个 F inliers；frame 110→121（0.551 s）有 1,721 条 tracks、median 5.49 px、1,718 个 F inliers。位移不是三角化角度，但能说明第二尝试在更弱的图像运动条件下开始。

## 3. 为什么 full901 有价值但不保证

对冻结 full 图像的 1 s LK displacement median 分段为：0–10 s `27.08 px`、10–20 s `24.22 px`、20–30 s `49.92 px`、30–40 s `23.25 px`、40–45 s `44.76 px`。对应 homography inlier-ratio median 为 `0.904/0.951/0.835/0.971/0.617`；20–30 s 和 40–45 s 更不符合单一平面/纯旋转解释。

same-image COLMAP+pressure-scale reference proxy（只用于运动形状诊断，不作独立真值）在 camera index `0,20,...,900` 的 1 Hz 样本上给出：

| 区间 | path length | 1 s step median | IMU accel-norm std | gyro RMS |
|---|---:|---:|---:|---:|
| 0–10 s | 0.9322 m | 0.0936 m | 0.3504 m/s² | 0.0596 rad/s |
| 10–20 s | 0.5243 m | 0.0580 m | — | — |
| 20–30 s | 1.2801 m | 0.1386 m | 0.4982 m/s² | 0.0887 rad/s |
| 30–40 s | 0.6184 m | 0.0680 m | — | — |
| 40–45 s | 0.7180 m | 约 0.184 m | 0.493 m/s² | 0.0827 rad/s |

全 45 s path/net displacement 为 `4.492/3.856 m`。这些结果支持“后段提供新的、更强初始化机会”，但不证明官方系统必然保住尺度或 keyframes，所以只允许一次预注册 diagnostic run。

## 4. 数据适配排除项

- HFNet YAML 的 `IMU.T_b_c1` 数值逐项等于 AQUALOC Kalibr 的 `T_imu_cam`，并与项目成功使用的 VINS `body_T_cam0` 方向一致；不做逆置或低层补偿。
- Kalibr `timeshift_cam_imu=-0.053694112369382575 s`。VINS 的读取语义为 `curTime=feature.first+td`；adapter 将 raw IMU stamp 加 `53,694,112 ns` 后让无 `td` 字段的 HFNet reader 截止在 camera time，二者等价于 `t_raw<=t_cam-0.053694112 s`，符号正确。
- `NoiseGyro=0.003`、`NoiseAcc=0.05`、`GyroWalk=0.0001`、`AccWalk=0.0015`、`Frequency=200` 与 AQUALOC 配置一致。
- prefix 日志已显示图像/IMU 均 loaded、四个 TensorRT models 成功加载、视觉地图两次形成、IMU optimizer 两次进入，因此不存在“模型或 IMU 完全没接上”的证据。

综合判断：短前缀/运动在官方保护周期中的分布是主要原因；数据适配问题概率低；官方保存 bug 是次生退出问题。

## 5. SIGSEGV 边界

`src/System.cc:615-641` 将 `pBiggerMap` 留作未初始化指针；当所有 maps 都是 0 KFs 时，`numMaxKFs` 从不增加，代码在打开 trajectory 文件之前于 line 629 解引用该指针。它解释 shutdown 后 RC 139，但不能解释更早已经发生的两次 motion reset。

新 runner 不修该源码。它只让官方 binary 作为一个子进程运行，并封存 raw return code/signal。只有 stdout 同时出现 `Saving trajectory` 且所有 `Map ... has 0 KFs` 时，才标记 `EMPTY_MAP_SAVE_EXIT_BUG_AFTER_ALGORITHM_FAILURE`；仍然是不可评测、wrapper RC 1、零重试。这样避免证据 writer 随父进程一起崩溃，同时不改变算法结果。

## 6. 新轨道与冻结顺序

实现文件及当前 SHA-256：

- `scripts/export_aqualoc_to_hfnet_euroc_full_v2.py`: `b13f56b69fd88799d4885c044c75bd41aa4331e688c22edaa2301c523ef42013`；
- `scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py`: `165589aae498225d825b7a2e43586607475704fdbf98cba484a16346ffb245c4`；
- exporter tests: `69987405386075e0a0d504c9ddc3c4025c58cf1e025484726ce2df17255f5a3c`；
- runner tests: `2da3135644bc3cf1ce7d7890e79eec90bcabe6e34fec3eddd61cbaa19ece6255`。

严格顺序如下，任何一步失败均停止：

```bash
python3 scripts/export_aqualoc_to_hfnet_euroc_full_v2.py --action preflight
python3 scripts/export_aqualoc_to_hfnet_euroc_full_v2.py --action export \
  --output-sequence-root logs/hfnet_slam_adapter/aqualoc_a02_0005_full901_euroc_diag_r2
python3 scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py --action profile
python3 scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py --action freeze
python3 scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py --action run
```

exporter 锁 camera `0..900`、IMU `38..9031`、lossless PNG、raw image timestamps、IMU `+53,694,112 ns`、完整 payload tree，无覆盖写。runner 的 freeze 重新逐文件哈希，锁 official HEAD/tree/tracked-clean、binary/config/ONNX/cache、四个关键源码、旧 r1 STOP、输入 payload、GPU/linkage、exact argv 与新输出目录；run 必须重建出字节等价合同才允许唯一一次启动。

当前 cache `a687454...` 必须同时等于 r1 prefix result 的 `cache_after_sha256`；`40f8e09...` 是 prefix 合同记录的运行前 cache。新合同明确沿用前缀官方运行生成的 TensorRT runtime timing cache，它不是 ONNX weights 或 detector/backend 阈值变化。ONNX、完整 config hash 与 `HFNetRT / 675 / 4 / 1.2 / 0.01` 均 fail-closed 不变。

成功门为 official child RC 0、`trajectory.txt` 至少 30 个严格递增/有限 8-field poses、时间跨度至少 3 s、非空且语法正确的 keyframe trajectory。空轨迹、timeout、崩溃、非有限、非单调或 immutable drift 均保留为失败。

机器可读预注册为 `papers/hfnet_slam_a02_full901_diagnostic_track_preregistration_r2.json`。实际 run contract `papers/hfnet_slam_a02_full901_diagnostic_run_contract_r2.json` **故意尚不存在**：只有真实 full export 完成且 profile ready 后，freeze 才能把实际 901 PNG/IMU payload hashes 写入；提前伪造合同会破坏结果盲边界。

## 7. 当前状态与测试

- full exporter v2：5/5 PASS；旧 exporter v1 regression：11/11 PASS；
- runner v2：9/9 PASS，包括 input tree tamper、contract drift 零启动、no-clobber、一次启动、严格 trajectory gate、cache continuity、空地图 SIGSEGV 分类与零重试；
- 真实只读 runtime profile：binary linkage、GTX 1650、CUDA/TensorRT/cuDNN/Pangolin、DISPLAY 和三个输出 reservation 全部 ready；唯一 blocker 是 full901 input 尚未导出；
- 截至本文冻结，**未执行真实 full export、未冻结 run contract、未启动 HFNet full901、未生成新 trajectory**。
