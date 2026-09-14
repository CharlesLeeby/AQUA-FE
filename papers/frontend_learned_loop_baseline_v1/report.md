# 水下学习回环基线 v1：有真实重访，系统比较尚未执行

## 最新增量：2026-09-14T16:14:36+08:00

**状态仍为 PARTIAL_BLOCKED_RESOURCE，系统增量 Not evaluated。** 已从候选层代码
推进到隔离的原生回环适配器编译成功，但没有运行真实关键帧、PnP 或位姿图。

| 第一屏问题 | 最新证据 |
|---|---|
| 有无真实重访？ | 仍为已锁定的完整 Bus/Cemetery，提供方描述重访；逐查询标签 Unknown。 |
| 学习相对传统多带来什么？ | Not evaluated：模型加载/推理、C/L 检索均 0。 |
| 几何是否成立？ | 已实现通往原生 BRIEF/PnP 的输入接口；真实几何验证 0，不能报合法新增回环。 |
| 全局轨迹是否改善？ | 局部 VIO 0/6，位姿图 0/12，18 个 B/C/L 计划行仍全部 NOT_RUN_RESOURCE。 |
| 本次计算？ | 原生适配器编译成功；9 个档案测试、8 个候选测试通过。训练/模型推理/VINS/位姿图/大文件下载均 0。 |
| 是否值得继续？ | 固定基线仍值得完成检验；尚无支持或否定学习增量的系统结果。 |

### 已实现与尚未验证的边界

- [档案脚本](../../scripts/archive_loop_keyframes_v1.py)：从已有原生 pose/point 发布
  被动保存一次局部输出，使用精确 header 时间戳关联原图；保留 native first10 skip、
  零距离过滤、body pose、world XYZ、normalized xy、pixel uv、ID。缺失时失败，
  不拿邻近图或 TUM 补造测量。`--verify-only ARCHIVE` 只读检查 receipt、逐文件哈希、
  时间/ID/位姿/点结构；**不证明几何正确**。目前只接受与 KLT 相同的 800×600 mono8
  转换图像，尚未生成真实档案。
- [构建脚本](../../scripts/build_native_loop_baseline_v1.py)只复制 loop_fusion 源码到
  本任务 `experiments/` 下构建；原外部工作区不动。隔离补丁限于 C/L 候选接口、
  已注册的历史集合限制、验证日志和优化完成通知。`keyframe.cpp` 逐字节未变，
  4DoF/6DoF 求解函数除只读完成通知之外未变；未重编译局部 VINS。
- [原生适配器](../../scripts/native_loop_baseline_v1/native_loop_replay.cpp)读取同一
  关键帧档案，调用原生 `findConnection()`，保留原图优化；记录候选、通过/拒绝、
  原生相对约束、四前驱原始里程计边目录、局部/全局位姿及处理耗时。
  四前驱目录不是声明所有边都进入每次优化的 active segment。
- 首次准备在补丁锚点不唯一处失败，目录 `native_adapter_build` 保留。收窄到
  `addKeyFrame` 后 `native_adapter_build_attempt2` 编译通过。随后修复 CSV CRLF
  兼容与非法 pose 拒绝并增量重编译。没有把失败的准备计成 VIO 技术重复。
- 17/17 合成测试的具体入口是已有候选测试和新增
  [9 项档案测试](../../scripts/tests/test_archive_loop_keyframes_v1.py)。它们不是
  真实数据几何/时序一致性验证。模型 encoder、真实档案联调、独立回环标签和
  完整系统评价仍未完成；不能将这次编译称为系统 baseline 已交付。

构建命令与运行尺度资产（不上传）：

```bash
python3 -B scripts/build_native_loop_baseline_v1.py --build-dir experiments/learned_loop_baseline_v1/native_adapter_build_attempt2
cmake --build experiments/learned_loop_baseline_v1/native_adapter_build_attempt2/build --parallel 1
python3 -B -m unittest discover -s scripts/tests -p test_archive_loop_keyframes_v1.py -v
python3 -B -m unittest discover -s scripts/tests -p test_learned_loop_candidates_v1.py -v
```

构建器会拒绝覆盖已有目录；上面第一条是本次执行记录，不是让接手人重复执行。
源码快照及逐文件原身份位于该 attempt2 的 `snapshot_identity.json`，二进制在
`build/aqua_native_loop_replay`，SHA-256
`e87f60c8d9b13f4c8db90a960b7a95610fb83ff609928db9ecc00f064cf6b027`。
适配器源码/配置和二进制身份摘要在 [decision.json](decision.json)，没有模型/VIO
运行源码提交可冒认。本次使用既有 GCC9.4、OpenCV4.2、Ceres1.14、Eigen3.3.7、ROS1；
所检查 Python 为 torch2.2.2+cpu，未加载模型，也未安装或升级环境。

### 资源与局部身份仍未完全就绪

新实测根盘 **8,352,247,808 字节（7.78 GiB）**，比先前约 300 MiB 明显恢复；
`/mnt/data` 575,979,520 字节，`/media/ma/Data` 227,987,456 字节。
根盘 ≥2 GiB 的独立储备已通过，允许这次小型适配器构建；但任何现有输出盘仍不满足
冻结的 **≥8 GiB 运行储备再加保留产物预算**，因此没有模型加载、下载或 replay。
没有清理/迁移用户数据。需提供满足储备与产物预算的任务输出路径；只差几百 MiB
达到 8 GiB 并不代表已有足够空间保存完整矩阵。若保留全部转换 mono 图，单两序列
图像像素就有 15,119×800×600=7,257,120,000 字节，未含消息开销；必须先有有界
产物预算，不能在近满盘下盲目生成。此为容量上界检查，不是实测磁盘占用或新方法。

定向核对确认现有 `vins_node` / `libvins_lib.so` 与历史冻结身份一致，Bus/Cemetery
旧 canonical YAML 和 frontend YAML 可读且哈希一致（具体值见 decision）。但检查到
旧 v2 shadow 目录的 exporter 当前 SHA 为 `e20bc39f...`，不同于旧锁的 `bb4e50d8...`；
基础 Git f6f8feec 中该文件也不是该旧锁内容。因此**不能把目录名当成源码身份**。
尚未据此归因 KLT 行为改变或否定历史结果，亦未运行这份不同身份的 exporter。
完整 KLT 源码/新输入锁仍待完成，磁盘恢复不自动等于所有执行前提就绪。

本次按照项目研究 skill 的证据分层保留 `Not evaluated`，并按冻结资源合同暂停长运行；
旧停止结论和原始协议/CSV 不改。没有后台系统实验在等待自动执行。

## 初次检查快照（以下保留原始状态，不代表最新进度）

更新：2026-09-14T01:15:11+08:00。状态：`PARTIAL_BLOCKED_RESOURCE`。

| 第一屏问题 | 目前证据 |
|---|---|
| 有无真实重访？ | **有数据提供方明确描述的重访**：完整 AFRL Bus 绕沉船巴士，Cemetery 多次经过同一区域。尚不是逐关键帧真回环标签。 |
| 学习比传统多带来什么？ | **Not evaluated**：尚未计算学习描述子或传统检索。 |
| 几何成立吗？ | 找到原生关键帧 3D–2D/PnP 接口；没有执行几何验证，不能声称已有合法回环边。 |
| 全局轨迹改善吗？ | **Not evaluated**：局部 VIO 0/6，位姿图 0/12，三臂结果行 0/18 完成。 |
| 计算成本？ | 仅有限数据/源码检查、词典内存读取、8 个合成接口测试。训练、模型加载/推理、VINS、位姿图均 0；没有模型或数据集大文件下载。 |
| 值得继续吗？ | 已有适合检验的数据和匹配词典；系统价值仍 Unknown。不能宣称成功，也不能判为 `NO_LEARNED_LOOP_INCREMENT`。当前应先解除资源阻塞，而不是换模型/序列。 |

这是一项成熟组件的**全局数据关联**基线，不冒称 KLT 局部里程计改善、
原创算法或论文创新。旧 XFeat、SEA-RAFT、temporal refinement 停止结论不变。
本轮没有启动旧实验、修改旧后端、清理/搬迁数据或升级系统环境。

## 已锁定数据与分母

完整任务保存在 [task_instructions.md](task_instructions.md)；
[protocol.md](protocol.md) 在读取新学习结果前锁定研究设计。
执行身份尚未全部锁定，状态不是“已准备好立即运行”。

有限检查为 **6 条物理序列、7 个现有 ROS1 bag**：AQUALOC A02/H05，
AFRL Bus/Cemetery/Cave Gennie，CIRS Cala Viuda 的 camera+sensor 两个 bag。
全部列在 [sequence_manifest.csv](sequence_manifest.csv)，不代表扫过所有数据集。

选择依据：优先已明确描述重访、现成完整 bag、IMU、标定和 proxy 均可用的序列；
因此预先固定 Bus、Cemetery，**不是依据学习结果或历史输赢**。两序列都曾用于局部
前端开发，不能称为 sequence-held-out。输入保留完整路径，不裁成旧 45 秒窗口。

| 完整序列 | bag 时长（记录时间） | 左图像 | IMU | COLMAP proxy 位姿 |
|---|---:|---:|---:|---:|
| Bus Outside | 584.999 s | 7,338 | 58,487 | 3,388 |
| Cemetery | 433.997 s | 7,781 | 43,400 | 2,519 |

两份 proxy 均严格时间递增。Bus 原时间为 epoch 秒。Cemetery 的字符串例如
`153.522486209` 必须按现有 `afrl_digits` 规则读为 `1535224862.09`，不是 153 秒，
也不是通过轨迹误差拟合时间偏移。其 2,519 个 proxy 时间中 2,514 个位于 bag
**记录时间**范围；这不是已计算的传感器 header/common-support 覆盖率。
最终只在真实关联支持内评价，不能为此删除输入尾部。

A02 提供的重叠矩阵是 450×450，但检查的旧 proxy 只有 445 行，故不能直接按行号
生成回环标签（`ROW_MAPPING_UNRESOLVED`）。H05 重叠文件存在但未核对行身份；
Cave Gennie、CIRS 在此次有限检查中没有确认独立的重访标签。
CIRS 的 `/odometry` 不当作独立真值。未选序列不充当失败后的替补。

参考来自 COLMAP：所有未来 APE/RPE 都是**与 proxy 的一致程度**，不是独立 GT
绝对精度。数据说明能确认序列存在重访，不能凭此计算 Recall@4。
没有有效全查询标签时，真实检索召回率必须保留 Unknown。

## 模型、词典和实现边界

固定一个配置：DINOv2 ViT-S/14、最终 `x_norm_patchtokens`、384 维、K=32 VLAD，
280×448 RGB letterbox + ImageNet 归一化，输出 12,288 维。
出处是 [DL-VINS 固定配置](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/blob/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6/DL-VINS/src/loop_fusion/config/loop_fusion_euroc.yaml)
及 [其 AnyLoc 子模块导出器](https://github.com/limshoonkit/AnyLoc/blob/e8bb9e0a19dc20db32470ea34e2d7f8e5184b31c/vpr/dino_vpr_export.py)。
没有照搬 ROS2 工程、TensorRT 或其中 LightGlue 几何验证。

- 实际读回配套词典 49,160 字节，头部 `(32,384)`，固定哈希通过适配器检查；
  不是 ViT-L/G 的词典。词典仅在内存读取，未训练新词典。
- 同目录配套 ONNX 在远端存在，大小 88,315,627 字节；**没有下载、加载或推理该模型**。
  导出器调用官方 pretrained DINOv2，只证明源码意图，不证明本轮已加载官方权重。
- 词典来源仓库/提交/哈希明确，但实际拟合图像清单 **Unknown**。
  导出器示例目录不是训练出处证据，不能声称已排除历史测试场景曝光。
- 本机检查的 Python 中无 onnxruntime/onnx，存在 torch/cv2；本轮没有安装环境。
  仍需隔离 Python 中真实加载、有限输出和显存检查，不能随机初始化替代。

已新增小型 [候选适配器](../../scripts/learned_loop_candidates_v1.py)：
严格词典身份、参考预处理/VLAD、同历史集合、top-4、每查询至多一个待验证候选、
缓存身份检查。它不产生相对位姿，不把相似度转成回环边。
**真实模型 encoder 与 archive→原生 verifier 桥接尚未实现/验证**，不能把这份
候选代码称为已经交付的完整回环系统。CLI 只读真实描述子缓存，不会启动模型或 VINS。

8/8 [合成测试](../../scripts/tests/test_learned_loop_candidates_v1.py) 通过：
时间近邻/自身/未来排除、top-K 前过滤、边界与并列顺序、传统门与单候选预算、
非法词典/输入拒绝、预处理、VLAD 归一化。它们不是学习检索或系统有效性证据。
测试命令：

```bash
python3 -B -m unittest discover -s scripts/tests -p test_learned_loop_candidates_v1.py -v
```

## 同局部轨迹如何保证

只保存一次每个技术重复的 KLT local 输出，再派生 B/C/L。
现有 VINS `pubKeyframe()` 已发布 keyframe pose 和含 world 3D、normalized xy、pixel uv、
feature ID 的点消息。注意 pose 实际是 body/IMU 坐标，不凭注释误当 camera。
需要同时保存对应原图、精确时间、标定和原里程计边。
旧 `savePoseGraph()`/TUM 没有保存本任务所需的全部当前帧 3D 观测，不能伪造补齐。
此次有限查找没有确认可复用的完整档案，不等于穷尽证明所有本地历史都不存在。

本机 `TemplatedDatabase.h:679` 的 L1 分支包含 last-entry 例外；其文档中的 `<=`
也不同于实际 `< max_id`。协议明确 C/L 都使用 `candidate_id < query_id - 50`，
在 top-4 **之前**约束历史集合；不让最近帧例外消耗传统臂预算。
这个约束需在隔离候选接口落实，原工作区/后端未被修改。
两臂均只送一个候选到相同原生 BRIEF/PnP，沿用同一 4-DoF 图优化。
不把四自由度优化称为通用尺度修复。

## 当前阻塞、空表含义与剩余工作

2026-09-14T01:15:11+08:00 可用空间：

| 文件系统 | 可用字节 | 约数 |
|---|---:|---:|
| `/` | 1,541,496,832 | 1.44 GiB |
| `/mnt/data` | 1,850,081,280 | 1.72 GiB |
| `/media/ma/Data` | 227,987,456 | 217 MiB |

低于沿用的保守 replay 运行储备：根盘 2 GiB、任务 runtime 盘 8 GiB。
这不是断言完整实验“精确需要 8 GiB”；实际档案/构建量尚未测定，还需预算。
根盘增加约 0.57 GiB 可达到根盘储备；任务还需具备 ≥8 GiB 可用的输出位置。
不降低安全储备、删除旧实验或把输出偷偷写到其他工作区。小文件检查可以完成，
但本轮没有冒险下载模型、启动整段 VIO、构建隔离回环后端。

[system_results.csv](system_results.csv) 保留 **2×3×3=18 个计划行**，全部
`NOT_RUN_RESOURCE`，数值为空，不是 18 次失败或 0 个检出的回环。
[loop_candidates.csv](loop_candidates.csv) 只有表头，因为检索未执行。
初始化、覆盖、Recall@4、真实/错误回环、APE/RPE、尺度和运行成本均 Not evaluated。
没有完整矩阵，不触发正/负科学标签，也不伪造 L/C 增量。

资源恢复后只接着本协议：完成配置/build 身份锁、真实权重加载、必要的被动数据
保存与候选读取桥接，再按 Bus r1–r3、Cemetery r1–r3 执行同输入 B/C/L。
不换序列、模型或阈值，不重开加点、恢复或坐标精化。

## 溯源与公开资产

实验基础源码提交：`8f5d91681c28460a2e4579bc71995ebefbe3abe4`。
本轮新增代码在专用分支 `exp/learned-loop-baseline-v1-20260914`；报告发布 commit
由推送回执给出，不冒称运行时 VINS identity。原仓库 `/home/ma/AQUA-FE_WS`
保持不动；隔离目录 `/home/ma/AQUA-FE_WS_learned_loop_baseline_v1`。
数据根通过原仓库 `datasets` 只读解析；CSV 存该数据根下相对路径。
数据未上传，也没有以仅哈希代替这份可直接阅读的检查结果/协议。

| 已读小型资产 / 源码 | SHA-256 |
|---|---|
| AFRL `README.md` | `372450be8e61e4def5807c86e917096dd45f161c0127bd42252641f016bae48d` |
| Bus `colmap_groundtruth/bus_outside.txt` | `341770a61a2adae1135c4319bf858be32218ec406b446420d6a9a495b4a36bb7` |
| Cemetery `colmap_groundtruth/cemetery.txt` | `cd34aa974c4561d270fcde3efc9badfebfab9b85622ab0a15289ffbf0981860f` |
| Bus camchain | `61fe329f4d0938db73b697f2e03b7ac9ebbf76f4a84c0843573f5c0b4144cda1` |
| Cemetery camchain | `abf9aed6ff1b4ab81641c38b2149a5c37f2f194b7b465cc6fe924dd518235b03` |
| Shared imu.yaml | `07c9a4377133d6f9ba2d91c29dbcbfbb5d8b070c6005d47fb947ff70a1f236a5` |
| Fixed K32 vocabulary | `695985ec145406609d5c8d122092198886c4d89463c316e6a3b1606aee34143d` |
| Inspected local `loop_fusion_node` binary | `7a09865bd9a2c5174a729033d654dc5c5efa61fdb954527b6c385ecf6ddc4066` |
| Local `loop_fusion/src/pose_graph.cpp` | `24128be4ca6f2f2adb7d68eaf1478f48c68d356eba4d29fc0b3becfa497c9b26` |
| Local `loop_fusion/src/keyframe.cpp` | `fafcf63d4918e78aa6169735e2610aa0342efd9e6c1776e4f918335161bb2479` |
| Local `vins_estimator/src/utility/visualization.cpp` | `a1da39a9c7aba660d4aa7d5d10728e8c08d2699e50670b415e44ce052dd8039e` |

这些是本次定向检查身份，不是“已验证源/二进制一一对应”的构建证明。
原始大 bag 本次只读索引/元数据，尚未为新运行生成全输入 SHA 或 receipt。
没有重新哈希全库。

直接参考：
[VINS-Fusion 原生回环](https://github.com/HKUST-Aerial-Robotics/VINS-Fusion)，
[AnyLoc 官方实现](https://github.com/AnyLoc/AnyLoc/tree/a9fda68c55083f765b019df148a1b67614f90ee2)，
[DL-VINS 集成](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/tree/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6)，
[SEALOC 的几何与重访标签说明](https://github.com/sealoc/sealoc/tree/898cdee0fd78b55a160614ff1ba512bb74e94d45)。
SEALOC 仅核对说明，没有自动获取新数据。

有限失败记录：A02 overlap 初次按空格解析失败，改用逗号后发现行数不一致，
因此不输出伪标签；一次 GitHub tree 请求 HTTP 500 改用定向 contents API；
读取子模块父仓库路径返回 404 后按实际子模块提交解析。均无模型/VIO失败运行。
完整决策：[decision.json](decision.json)。
