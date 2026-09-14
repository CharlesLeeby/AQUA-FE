# AQUA-FE：学习式水下回环基线交接

更新：2026-09-15T04:13:54+08:00。实验：`frontend_learned_loop_baseline_v1`。
实际分支：`exp/learned-loop-baseline-v1-20260914`，不是 main。
**PARTIAL_BUS_COMPLETE_CEMETERY_RESOURCE_BLOCKED；Bus三次B/C/L完成，无后台任务在运行。**

本任务已明确扩展到全局关联。旧加点/恢复/坐标精化停止结论全部保留，不重开。

- **重访依据**：已预注册完整 AFRL Bus Outside、Cemetery，共2条序列；均有历史开发曝光。
  提供方描述重访，不等于有逐查询真回环标签。
- **模型已真实执行**：官方DINOv2 ViT-S/14，配套32×384词典，175个张量等值检查通过。
  三次共2501张唯一图像实际编码，另4809次身份有效缓存命中；总编码+VLAD526.06s。
  首轮每张中位211ms，C/L原生处理每轮约21/22s；独立优化耗时Unknown。
  累计官方模型加载4次（含一次合成探针）、训练0。词典拟合图像清单Unknown。
- **完整输入齐全**：Bus7338张原图/58487条IMU；Cemetery7781张原图/43400条IMU。
  原始KLT冻结代码未改，没有重跑旧v2；Cemetery导出结束，不是暂停状态。
- **相同像素/消息**：流式输入与原转换128条消息逐字节一致；仅减少中间文件存储。
  后端31个顶层项只改输出目录，其余30项不变。相机标定未改。
- **当前系统结果**：局部VIO3/6、C/L图处理6/12、B/C/L输出9/18完成；只有1条物理序列完成。
  三次均初始化2.228s、局部3654姿态；全部C输出与B字节一致，全部L输出改变。
  全部18行保留，9行Cemetery为NOT_RUN_RESOURCE，不是FAIL或0回环。
- **检索归因边界**：10次L通过查询的C最高分都未过冻结0.05门；其中1对正是C第一名。
  因此支持的是固定检索配置（排名+门限）的几何通过增量，不是表征本身已胜出。
  没有调任何阈值做反事实。10次通过对应7对唯一图像，并非10个独立回环场景。
- **正确性**：已查看全部7对的12张唯一图像，轮胎/车头结构支持重访；审阅并非严格盲审，
  正式独立正确/错误标签仍Unknown，不能将没有确认错误写成没有误闭环。
- **不能声称精度收益**：参考具体位姿约定未独立确认，APE/RPE/尺度及真Recall@4均Not evaluated。
  几何成立不自动证明正确回环，更不等于比传统方法精度好；当前无WIN/TIE/LOSS结论。
- **资源阻塞**：04:10:54根盘可用9.49GiB；Cemetery首次运行需10.25GiB（含8GiB储备），
  启动检查失败，未创建输出目录、未启动VINS、未消耗重复。其他两数据盘也不足。
  不是磁盘已满；缺的是既定储备加产物预算。建议另增2–3GiB或提供足够空间的任务路径。

| Bus技术重复 | 关键帧 | C通过/选择 | L通过/选择 | common poses/覆盖 |
|---|---:|---:|---:|---:|
| r1 | 2430 | 0/443 | 3/2198 | 497/92.04% |
| r2 | 2441 | 0/443 | 2/2209 | 501/92.78% |
| r3 | 2439 | 0/445 | 5/2206 | 496/91.85% |

L几何通过数中位3、范围2–5；C中位0、范围0–0，不能代替APE/RPE。
唯一后续任务：满足原资源门后完成剩余Cemetery三次共享局部输出及C/L，不重跑Bus。
不换模型、阈值、序列，不把加载通过当学习增量。
原生适配器已完成Bus三次真实档案/几何/图优化联调，其余矩阵尚未完成。
proxy不是独立GT；本包相机姿态方向说明待核实，未知字段不猜测。

## 直接可读的证据与接口

- [报告（最新状态及历史失败全部保留）](../papers/frontend_learned_loop_baseline_v1/report.md)
- [完整任务](../papers/frontend_learned_loop_baseline_v1/task_instructions.md) /
  [冻结协议](../papers/frontend_learned_loop_baseline_v1/protocol.md) /
  [两序列和有限检查清单](../papers/frontend_learned_loop_baseline_v1/sequence_manifest.csv)
- [18行结果账本，含未运行行](../papers/frontend_learned_loop_baseline_v1/system_results.csv) /
  [完整已执行候选表](../papers/frontend_learned_loop_baseline_v1/loop_candidates.csv) /
  [决策及实际计数](../papers/frontend_learned_loop_baseline_v1/decision.json)
- [实际运行小回执、命令及身份](../papers/frontend_learned_loop_baseline_v1/runtime_receipts.json) /
  [参考约定独立检查](../papers/frontend_learned_loop_baseline_v1/reference_checks.json)
- [模型/输入实测小回执](../papers/frontend_learned_loop_baseline_v1/prerequisite_checks.json) /
  [执行身份锁](../papers/frontend_learned_loop_baseline_v1/execution_lock.json) /
  [流式输入附录](../papers/frontend_learned_loop_baseline_v1/streaming_input_addendum.md)
- [固定encoder](../scripts/learned_loop_encoder_v1.py) /
  [原KLT流式导出](../scripts/run_loop_klt_export_v1.py) /
  [被动局部复放](../scripts/run_loop_vio_v1.py) /
  [关键帧档案](../scripts/archive_loop_keyframes_v1.py) /
  [原生图处理](../scripts/run_loop_graph_v1.py)
- [候选层](../scripts/learned_loop_candidates_v1.py) /
  [候选测试](../scripts/tests/test_learned_loop_candidates_v1.py) /
  [档案测试](../scripts/tests/test_archive_loop_keyframes_v1.py) /
  [原生构建器](../scripts/build_native_loop_baseline_v1.py) /
  [C++接口](../scripts/native_loop_baseline_v1/native_loop_replay.cpp)

历史KLT运行源码commit：`3c50b742d6e0c69796a69813e42823e9895ed684`；
DINO源commit：`7764ea0f912e53c92e82eb78a2a1631e92725fc8`。
后端、模型、词典和构建二进制SHA见decision/检查回执。
本轮前端启动时HEAD为4bdef735，使用新增未提交的IO适配器，其字节身份在运行中检查点记录（不冒称启动前receipt）；
不得把之后报告发布commit写成当时源码身份。报告发布SHA以实际push及远端读回回执为准。
大数据、权重、缓存未提交；没有删除或搬迁历史产物。
Bus r1局部运行源码提交7c08909；档案/C调用4ee416e；L调用902a886。
Bus r2局部902a886、其档案/C/L为bf9efeff；r3局部与档案/C/L均bf9efeff。
这些是任务适配器运行身份，外部VINS二进制始终为同一4e91d8ac…，不等于文档发布SHA。
