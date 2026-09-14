# AQUA-FE：学习式水下回环基线交接

更新：2026-09-15T01:41:05+08:00。实验：`frontend_learned_loop_baseline_v1`。
实际分支：`exp/learned-loop-baseline-v1-20260914`，不是 main。
**PARTIAL_FULL_KLT_EXPORT_RUNNING；系统增量 Not evaluated。**

本任务已明确扩展到全局关联。旧加点/恢复/坐标精化停止结论全部保留，不重开。

- **重访依据**：已预注册完整 AFRL Bus Outside、Cemetery，共2条序列；均有历史开发曝光。
  提供方描述重访，不等于有逐查询真回环标签。
- **模型已真实加载**：官方DINOv2 ViT-S/14，配套32×384词典，175个张量等值检查通过。
  只做1张合成黑图推理；真实关键帧推理0。词典拟合图像清单 Unknown。
- **输入正在执行**：找回精确历史 KLT 源码，8帧探针均350个经典点、学习0；
  完整 Bus 前端已启动，尚无完整输入成功回执。没有重复启动或重跑旧v2后端。
- **相同像素/消息**：流式输入与原转换128条消息逐字节一致；仅减少中间文件存储。
  后端31个顶层项只改输出目录，其余30项不变。相机标定未改。
- **系统仍未评估**：局部VIO0/6、C/L图处理0/12、B/C/L完成0/18。
  当前没有WIN/TIE/LOSS、APE/RPE或新增合法回环可报告。
- **空间与并发**：初次根盘11.43GiB已通过模型阶段预算；每阶段继续必要预检。
  另一个工作区间歇运行VINS，不干预它，不与其并发本任务的定时求解器。

唯一后续任务：完成当前完整 Bus 输入，再依冻结顺序运行共享局部输出及C/L。
不换模型、阈值、序列，不把加载通过当学习增量。
原生适配器已编译，但真实档案/几何/系统联调仍未完成。
proxy不是独立GT；本包相机姿态方向说明待核实，未知字段不猜测。

## 直接可读的证据与接口

- [报告（最新状态及历史失败全部保留）](../papers/frontend_learned_loop_baseline_v1/report.md)
- [完整任务](../papers/frontend_learned_loop_baseline_v1/task_instructions.md) /
  [冻结协议](../papers/frontend_learned_loop_baseline_v1/protocol.md) /
  [两序列和有限检查清单](../papers/frontend_learned_loop_baseline_v1/sequence_manifest.csv)
- [18行计划结果账本，尚未评估](../papers/frontend_learned_loop_baseline_v1/system_results.csv) /
  [候选表（表头，尚未检索）](../papers/frontend_learned_loop_baseline_v1/loop_candidates.csv) /
  [决策及实际计数](../papers/frontend_learned_loop_baseline_v1/decision.json)
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
