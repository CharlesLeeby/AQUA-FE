# 用户完整新任务：SEA-RAFT DIRECT RECOVERY ABLATION

2026-09-11。用户优先尽快回答系统设计问题，不重复审计、不增加模块、不靠小参数延长研究。

唯一问题：去掉强LK重试中间步骤，只让原KLT失败轨迹直接接受SEA-RAFT恢复，能否保留H02收益并避免A02严重退化？仓库 https://github.com/CharlesLeeby/AQUA-FE 。固定证据1138fab635910d3e1c34d57f99dab84c6ff8e9f5。定向读取其system_probe_v1 report、protocol、input_manifest、recovery_summary、run_searaft_system_probe.py和searaft_system_recovery.py，其余只读直接依赖。旧UNSAFE_OR_UNRESOLVED、18次运行和筛选结论冻结；这是删除组件消融，不重判旧版本成功。

授权隔离分支/结果目录、实现D、复用缓存及补充必要推理、最多12次新后端、正常commit/push小型必要文件。不得修改旧工作区正在运行代码或覆盖旧结果；不训练、不换模型、不调q/NCC/FB/帧间隔、不做标注/router、不重编译后端。

旧R=普通KLT→31/4强LK→剩余失败点SEA-RAFT；新D=普通KLT→失败点直接SEA-RAFT。D用原21/3普通KLT和原检查，本帧成功观测不改；失败旧轨迹直接调用既有SEA-RAFT接口，完全不执行31/4重试，不使用其结果或通过/失败作为调用条件。模型、预处理、FP32、iters4、scale−1沿1138fab及模型锁。恢复检查固定有限值、原像素FB≤1、8px端点边界、完整11×11 patch、std>1、NCC≥.65。不LK精化、不改预测坐标。同帧正式丢弃前恢复原ID，不跨公开断链复活、不倒填；后续普通KLT跟踪，再失败仍执行D。先留有效旧轨迹，再GFTT，总上限350。q/sigma/速度/公开频率/时间运算完全沿已修正实现。不顺便改预算、时机、质量/几何门。

D必须运行自己的因果前端状态；会改变后续轨迹/GFTT，不能剪贴旧R bag删除C观测伪造。

固定H02和A02 raw[0,900)，精确bag/相机/IMU/时间/索引/公开频率读取冻结input_manifest；每raw处理，每2帧offset1公开，不t+10、不换起点。这是已知开发数据，不held-out。

缓存优先已有模型，不下载；匹配图像身份、前后时间戳、预处理、模型配置、原查询坐标和预测坐标系。D的新轨迹可缺查询，允许补推理。同图像对所有查询共享正反一次；每窗每相邻对最多新增一次，两窗最多1798对；不逐点推理、不拼其他ID近邻预测。序列化修复只用新缓存，不再次推理。分别报告复用、新增、模型加载、CPU导出成本，不要求新增必须0、不隐瞒代价。

正式主比较B原KLT与D直接恢复，每窗各3次，最多12次新回放。B也全新跑，不挑历史最好B；旧C/R仅辅助，不重跑。同一冻结二进制/依赖/数学配置，无新诊断版、无完整A/A。结果前固定运行顺序，不按胜负调整。检查关闭恢复B与原B逐字段/序列化一致；D普通成功点不改；恢复ID/时间/坐标/速度/容量合法；非feature一致；后端无静默裁剪或接收缺失。D/B完整输入配置相同则映射跳过D，结论无学习介入。输入错误、非有限或基线数量级发散保留并限制结论，不挑选重跑；普通重复波动不能直接叫实现失败，runability不能掩盖精度。

结果前冻结评价：沿1138fab fixed-scale proper SE(3) APE、严格1秒RPE、共同支撑、实用幅度、单次严重异常门。3次技术重复全部min/median/max；COLMAP/proxy非独立GT。主结论D/B净收益；辅助D/旧R与D/旧C必须重新计算对应共同支撑，不拼旧标量，注明批次/环境/波动限制。不能因为胜发散C就成功，必须胜本轮B。记录恢复事件、不同ID、公开次数/后续长度、日志接收/残差可确认层、GFTT变化、推理和总开销；事件非独立点，同ID残差不全归功一次恢复，不新建诊断平台。

一次后停止。DIRECT_RECOVERY_PROMISING：至少一窗D/B实用净收益，另一窗无不可接受严重退化，无中位掩盖的D严重异常，仅开发支持。REMOVING_CLASSICAL_RETRY_HELPS_BUT_NO_GAIN：删除C缓解旧问题但D未超过B，不算正例。NO_DIRECT_LEARNED_INCREMENT：真实恢复但无D/B实用增量。UNSAFE_OR_UNRESOLVED：严重退化/重复异常/运行条件阻止可靠结论。NO_LEARNED_INTERVENTION：D/B无实际输入差异。任一结论不触发新窗口、阈值、模型或人工标注。D不支持则结束当前SEA-RAFT当帧恢复组合线，不再改顺序、追加第四门、找易赢窗口。

最少交付task_instructions.md、protocol.md、results.csv、recovery_summary.csv、decision.json、report.md，加必要组件开关、runner修改、关键测试，不复制框架。交接docs/CODEX_HANDOFF_SEARAFT_DIRECT_RECOVERY.md。报告开头回答H02收益保留否、A02严重退化消除否、是否胜KLT、对旧R变化、新推理/后端次数、值否继续。协议落盘和结束时正常commit/push小文件；不force、不无关文件、不bag/权重/大缓存，远端读回报告与结果。现在执行，不回到筛选、标注或初始化大审计。
