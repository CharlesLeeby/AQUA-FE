# AQUA-FE：学习式水下回环基线交接

更新：2026-09-14T14:47:59+08:00。
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
- 候选层适配器及 8/8 合成测试完成；模型 encoder 与 native verifier 桥接未完成。
  原 VINS 已有 keyframe pose/3D-point 发布接口，TUM 不能冒充完整地图测量。
- **局部 VIO 0/6，位姿图 0/12，18 个计划 B/C/L 行全部未执行**。
  没有 WIN/LOSS、APE/RPE、合法新增回环或学习增量可报告；不能把未运行说成负结果。

## 为什么没有启动系统矩阵

继续请求后的必要复核：根盘只剩 **300.66 MiB**（315,260,928 字节），
`/mnt/data` **549.73 MiB**（576,438,272 字节），
`/media/ma/Data` **217.43 MiB**（227,987,456 字节）。
空间比首次报告更少；首次检查数值保留在原报告，不改写历史。
不满足沿用的保守运行储备（根盘 ≥2 GiB、任务输出盘 ≥8 GiB）；这是运行安全约束，
不是测得“模型需要 8 GiB”。没有删除/搬迁数据或修改原工作区、后端、CUDA/ROS。
还有配置/build 身份锁和真实 encoder/数据保存/验证桥接要完成，不把它们写成已完成。
本次仅复核仓库、协议、进程和空间：新增训练/模型加载/推理/VINS/位姿图/测试均 0，
没有需要恢复的本任务运行进程。原 8/8 测试没有重跑，系统账本未产生新结果。

**唯一后续任务**：提供安全的任务输出容量并恢复根盘储备，然后继续同一固定协议，
不是换模型或另找有利序列。当前没有后台实验在等候自动执行。

## 可直接阅读的资产

- [完整原任务](../papers/frontend_learned_loop_baseline_v1/task_instructions.md)
- [报告：证据、接口、资源与身份](../papers/frontend_learned_loop_baseline_v1/report.md)
- [盲于新结果的协议](../papers/frontend_learned_loop_baseline_v1/protocol.md)
- [完整有限清单及固定两序列](../papers/frontend_learned_loop_baseline_v1/sequence_manifest.csv)
- [系统结果账本：18 行 NOT_RUN_RESOURCE](../papers/frontend_learned_loop_baseline_v1/system_results.csv)
- [候选表：尚未检索，只有表头](../papers/frontend_learned_loop_baseline_v1/loop_candidates.csv)
- [决策与实际计算计数](../papers/frontend_learned_loop_baseline_v1/decision.json)
- [候选适配器](../scripts/learned_loop_candidates_v1.py) / [小型测试](../scripts/tests/test_learned_loop_candidates_v1.py)

基础源码：`8f5d91681c28460a2e4579bc71995ebefbe3abe4`。本次新代码/报告发布 SHA
由推送回执提供；没有本轮模型或 VINS 运行源码 commit 可冒认。数据引用与已检查
小型资产 SHA 在报告中；模型、bag、大缓存没有上传。报告内 LOCAL_ONLY_PENDING_PUSH
描述文档落盘时状态，远端发布是否成功以实际 push/读回回执为准。
