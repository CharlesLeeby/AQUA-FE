# AnyFeature-VSLAM ORB32 在 A02 上零地图的只读根因审计

日期：2026-08-12  
状态：`PASS_ROOT_CAUSE_LOCALIZED`  
范围：冻结的 AQUALOC A02 `4500–5400`（适配后索引 `0–900`），AnyFeature-VSLAM RSS 2024 官方论文提交 `6aa014b724f7a61bcbff2f8f28f20836986a43dc`。

## 结论

ORB32 的首要故障不是“没有特征”、没有读到图像、时间戳单位错误或标定文件没有生效，而是官方单目初始化器在该水下序列上的**模型选择与唯一解门失配**：

1. 901 帧全部具有足够的 ORB 特征，748 帧进入与当前初始化参考帧的匹配。
2. 其中 596 帧达到官方 `nmatches >= 100` 门槛并实际进入几何初始化。
3. 596 次的官方得分比 `RH=SH/(SH+SF)` 全部大于 `0.4`，因此全部只执行 `ReconstructH`。
4. 596 次 Homography 重建全部被拒绝；直接且一致的拒绝项是唯一解门：`secondBestGood / bestGood` 实测为 `0.8385–1.0`，而源码要求 `<0.75`。
5. 官方实现对已选择但失败的 Homography **没有 Fundamental fallback**，故状态从未转为 `OK`，`CreateInitialMapMonocular()` 从未执行，最终自然得到 0 keyframes / 0 map points / 空轨迹。

首因置信度为高。场景层解释为近平面/低基线或旋转占优条件下 Homography 分解的多个运动假设无法唯一化；这一物理解释置信度为中等，而“被唯一解门拒绝且无 fallback”的程序级因果链由官方函数逐帧重放直接确认。

## 定量证据

| 项目 | 结果 |
|---|---:|
| 输入帧 | 901 |
| `set_reference` | 153 |
| 实际匹配尝试 | 748 |
| `<100` matches 后 reset | 152 |
| `>=100` matches、进入几何初始化 | 596 |
| 官方初始化成功 | 0 |
| ORB 总特征 min / median / max | 578 / 1404 / 2659 |
| octave-0 特征 min / median / max | 50 / 170 / 390 |
| 官方初始化匹配 min / median / max | 35 / 113 / 277 |
| 匹配位移中位数的 min / median / max | 0.650 / 14.184 / 128.939 px |
| `RH` min / median / max | 0.4497 / 0.4826 / 0.4912 |
| Homography 被选择 | 596 / 596 |
| H：SVD 门通过 | 596 / 596 |
| H：`bestGood > 50` 通过 | 596 / 596 |
| H：`bestGood > 0.9 N` 通过 | 596 / 596 |
| H：视差 `>=1°` 通过 | 372 / 596 |
| H：唯一解门通过 | 0 / 596 |
| H：最终重建成功 | 0 / 596 |

因此不能把失败概括为“全序列低视差”。即使有 372 个候选通过官方 `1°` 视差门，仍然全部因多个 Homography 解过于接近而失败。

## 源码因果链

- `Tracking::GrabImageMonocular()` 在未初始化时使用 4000 特征的初始化 extractor；尺寸不变时没有额外 resize：`src/Tracking.cc:135–146`。
- `Tracking::Track()` 在状态不是 `OK` 时每帧返回，不会进入正常跟踪：`src/Tracking.cc:151–173`。
- 单目初始化要求 `>100` keypoints 和 `>=100` matches；匹配不足时销毁当前 initializer：`src/Tracking.cc:436–484`，常量位于 `include/Tracking.h:265–271`。
- `Initializer::Initialize()` 同时计算 H/F 得分，但用 `RH>0.4` 二选一；选中分支失败后直接返回，不尝试另一分支：`src/Initializer.cc:93–112`，阈值位于 `include/Initializer.h:110–123`。
- H 重建要求第二好解少于最好解的 75%，并同时满足视差和 good-point 门：`src/Initializer.cc:665–703`。
- 统计字段 `numTrackedFrames` 在声明处初始化为 2，因此结果文件中的值 2 不是“成功跟踪了两帧”：`include/Tracking.h:122`。

## 反事实 Fundamental 诊断的边界

审计 harness 在不改变状态机输出的情况下，额外对同一批官方匹配调用了未被状态机选择的 `ReconstructF`。本次冻结进程中有 15 个候选按原始 F 阈值可以重建。这证明至少存在被 H-only 选择路径挡住的可用几何机会，但它**不是一次合法 SLAM 运行，也不是可报告的轨迹结果**。

该计数不能视为跨进程确定值：官方 `RandomIntegerGenerator` 在 `src/Utils.cpp:8–9` 使用 `random_device` 初始化 `mt19937`；另一次诊断实现曾得到 17。冻结 CSV 中的 15 只描述本次带哈希的 RANSAC realization。稳定主结论是 596/596 选择 H、596/596 H 唯一解门失败，而不是 F 反事实的精确数量。

## 已排除或降级的候选原因

- **没有读到全部输入：排除。** 官方 stdout 报告 901 张；只读状态机审计也逐一构造了 901 个官方 `Frame`。
- **ORB 特征不足：排除为首因。** 每帧总特征至少 578，596 次通过 100-match 门。
- **时间戳/时间单位/节流：排除为首因。** 901 个时间戳严格递增，跨度 44.992 s，帧间隔中位数 0.050018 s；单目初始化几何本身不使用时间间隔。
- **图像格式或尺寸：排除。** 输入为 `mono8`、`968×608`，`FixRes=0`，适配 manifest 已验证 PNG 像素身份。
- **标定顺序/方向错误：未发现证据。** AQUALOC 原始 `pinhole+radtan` 的 `[fx,fy,cx,cy]` 和 `[k1,k2,p1,p2]` 被按 OpenCV 顺序传入；官方回显与源文件一致，`Frame::UndistortKeyPoints()` 用同一 K/D 执行 `cv::undistortPoints`。标定误差不能从本审计中绝对排除，但它不是观测到的直接程序阻断项。
- **退出时 `terminate called without an active exception`：独立次生缺陷。** 它发生在轨迹和统计写出之后；0-map 已在此前形成，不能解释初始化为何 596 次均失败。

## 不修改算法时的最小可运行路径

允许且建议的路径是：预先声明一个**双方共同的、连续的初始化 preroll**，从 A02 原始序列更早的帧启动 AnyFeature 与 AQUA-FE，并只在共同的目标区间计算指标。preroll 必须在读取任何 SLAM 结果前用图像身份、时间戳和资源条件冻结；筛选条件只能是数据/几何可观测性，不得依据轨迹精度择优。自然启动必须产生 `RH<=0.4`，或产生能通过唯一解门的 H。若没有这样的共同 preroll，则应更换为另一条双方都能按官方入口自然初始化的公开序列，或更换正式发表的官方基线。

以下操作会改变低层算法，在当前对比规则下禁止：

- 增加 H 失败后的 F fallback；
- 强制 Fundamental 或修改 `RH=0.4`；
- 放宽 H 的 `secondBest/best < 0.75`、视差或三角化门；
- 修改 ORB/匹配阈值、特征预算或预处理；
- 为基线单独选择有利 warm start，而 AQUA-FE 不使用相同输入和评估协议。

## 可复现产物

- `scripts/diagnostics/anyfeature_orb_init_audit_v1.cpp`：直接链接冻结官方库，机械重放官方初始化参考生命周期、特征、匹配和 H/F 初始化器；不构造 `System`，不会启动 SLAM 线程。
- `scripts/diagnostics/summarize_anyfeature_orb_init_audit_v1.py`：对 CSV 执行 fail-closed 汇总和身份冻结。
- `exact_state_machine.csv`：901 行逐帧证据。
- `summary.json`：机器可读结论、输入/源码/库哈希和 F 反事实边界。

主要 SHA-256：

- 官方 `libAnyFeature-VSLAM.so`：`eea4a5a6c5dccb5825a8e6a1a3249c6b808881a22c7fe301d0a2a90efaa99954`
- 官方 `orb32_settings.yaml`：`38a19b5f45863f64ee81b3306b3c66b43c4f587712fdda8babaef9b5f04c9647`
- harness：`e172e22e5119cab09b81f1b0febd1eb079a70dc5faabf8ee5a560639a639567c`
- CSV：`5e0dbb9b93dd661c54d375ff3fa296e49e0fbf7b17e74b9dcc5015c4bb3ae36a`
- `summary.json`：`9eee9c67826f435e225d1844452c775bc4cc32f63f1bea82803062e333ca2359`

编译必须保留官方构建使用的 `-march=native`，否则 Eigen 固定矩阵在外部诊断程序与冻结共享库之间可能出现类布局 ABI 不一致。正式审计的 compile RC、runtime RC 均为 0；汇总器单元测试 3/3 通过，重复汇总与冻结 JSON 字节一致。
