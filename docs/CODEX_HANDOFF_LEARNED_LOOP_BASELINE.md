# AQUA-FE：学习式水下回环基线交接

更新：2026-09-14T16:14:36+08:00。
实验：`frontend_learned_loop_baseline_v1`。
分支：`exp/learned-loop-baseline-v1-20260914`，不是 main。
状态：**PARTIAL_BLOCKED_RESOURCE；系统增量 Not evaluated**。

新任务明确扩展到全局回环/重定位，不继续旧加点、SEA-RAFT 或 temporal refinement。
原 `NO_TEMPORAL_REFINEMENT_GAIN` 与出生诊断 `DIAGNOSTIC_UNRESOLVED` 保留；
后者不妨碍旧原型停止，本轮也没有补其验证预测。

## 现在能说什么

- **真实重访有依据**：数据提供方明确描述完整 AFRL Bus 环绕巴士、Cemetery 重复经过。
  已锁定这两条完整序列，不用旧短窗，不按学习结果换序列。两序列有历史开发曝光。
- 已检查 6 条物理序列 / 7 个 bag，验证两条选中序列的图像、IMU、标定、proxy 和
  时间格式；**未取得穷尽的逐查询真回环标签**。
- 匹配的 ViT-S/14 K32 词典确实可读：32×384、49,160 字节、固定哈希通过。
  配套 ONNX 远端存在，但模型加载/推理 **0**；词典具体拟合图像清单 **Unknown**。
- 候选层 8/8、关键帧档案 9/9 合成测试通过；原生回环适配器已在隔离副本编译成功。
  原生 PnP 与图优化算法未改，局部估计器未重编译。
  **真实档案联调、模型 encoder、几何与系统验证尚未完成**；编译通过不代表回环有效。
- **局部 VIO 0/6，位姿图 0/12，18 个计划 B/C/L 行全部未执行**。
  没有 WIN/LOSS、APE/RPE、合法新增回环或学习增量可报告；不能把未运行说成负结果。

## 本次进展及仍未启动的原因

新增共享档案接口：精确时间戳关联原生 body pose、3D 点、像素观测和原图，拒绝缺失，
不使用参考轨迹；可只读检查 receipt/文件身份。新增 C/L 候选读取、原生验证日志和
局部/全局输出接口，保留同一 PnP/4DoF 求解。首次准备的锚点错误已修复且失败目录
保留；目前编译成功，17 个合成测试通过，未执行真实回环。

根盘已恢复到 **7.78 GiB（8,352,247,808 字节）**；`/mnt/data` 575,979,520 字节，
`/media/ma/Data` 227,987,456 字节。独立根盘 2 GiB 储备已通过，所以推进了小型构建；
但仍无输出盘达到已冻结的 **8 GiB 运行储备＋有界产物空间**，没有启动模型或 VIO。
单全部原始 mono 图像像素就约 7.26 GB，不能将“接近 8 GiB 空闲”当作矩阵容量已够。
没有删/搬数据、升级环境或修改旧后端。实际本次训练/模型加载/推理/VINS/位姿图/大文件下载均 0。

局部身份也还未锁完：现有 VINS 二进制、两序列 canonical YAML 与旧锁一致；检查到的
历史 shadow exporter 当前哈希却与旧 method lock 不同，不能按目录名冒认冻结版本。
该差异的 KLT 行为影响 **Unknown**，未运行这份文件，亦未改写旧结果。

**唯一后续任务**：提供满足储备与产物预算的输出位置后，完成同一协议的 KLT 输入
身份与真实模型/接口检查，继续固定两序列矩阵；不换模型、阈值或序列。
当前没有后台实验在等候自动执行。

## 可直接阅读的资产

- [完整原任务](../papers/frontend_learned_loop_baseline_v1/task_instructions.md)
- [报告：证据、接口、资源与身份](../papers/frontend_learned_loop_baseline_v1/report.md)
- [盲于新结果的协议](../papers/frontend_learned_loop_baseline_v1/protocol.md)
- [完整有限清单及固定两序列](../papers/frontend_learned_loop_baseline_v1/sequence_manifest.csv)
- [系统结果账本：18 行 NOT_RUN_RESOURCE](../papers/frontend_learned_loop_baseline_v1/system_results.csv)
- [候选表：尚未检索，只有表头](../papers/frontend_learned_loop_baseline_v1/loop_candidates.csv)
- [决策与实际计算计数](../papers/frontend_learned_loop_baseline_v1/decision.json)
- [候选适配器](../scripts/learned_loop_candidates_v1.py) / [小型测试](../scripts/tests/test_learned_loop_candidates_v1.py)
- [共享关键帧档案与只读校验](../scripts/archive_loop_keyframes_v1.py) / [档案测试](../scripts/tests/test_archive_loop_keyframes_v1.py)
- [隔离构建器](../scripts/build_native_loop_baseline_v1.py) / [原生回环输入接口](../scripts/native_loop_baseline_v1/native_loop_replay.cpp)

基础源码：`8f5d91681c28460a2e4579bc71995ebefbe3abe4`。本次新代码/报告发布 SHA
由推送回执提供；没有本轮模型或 VINS 运行源码 commit 可冒认。构建时适配器内容
与二进制 SHA 在 decision 中，完整快照身份留本地 attempt2。数据引用与已检查
小型资产 SHA 在报告中；模型、bag、大缓存没有上传。报告内 LOCAL_ONLY_PENDING_PUSH
描述文档落盘时状态，远端发布是否成功以实际 push/读回回执为准。
