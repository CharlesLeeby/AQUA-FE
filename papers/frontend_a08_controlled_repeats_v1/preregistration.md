# A08 原预算有限工程重复 v1

2026-09-12；EXP-20260912-A08-CONTROLLED-REPEATS。用户继续授权的工程诊断，
不是新方法或结果盲窗口验证。既有 A08 结果已知；本合同先于本次三个结果冻结。

## 唯一问题与固定范围

AQUALOC Archaeo08 [2700,3600)，同一现存 KLT feature bag、同一冻结容量1000诊断
node/library、同一数学 YAML/camera，按 B/r1、B/r2、B/r3 顺序新增且仅新增3次。
输入仍350点/帧，不重建前端或 bag，不改外部源码、时间预算、迭代数、门或窗口。
这是独立诊断后端合同，不混进原 v2 42 次主表，不恢复已停止的27次矩阵。
历史锚点固定为 additive/B/repeat1，不按结果选锚点；保留全部新旧负结果。

输入和原执行器源证据为 49c02471716e8ac960e35dd9dd44ef6fbb1428c6，
前阶段只读定位见 ../frontend_a08_replay_identity_audit_v1/report.md。
新 execution_lock.json 在运行前锁定原依赖、输入、相机、YAML、新包装脚本/协议/测试。
源码身份为 main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf 加精确文件SHA；
后来的文档发布提交不冒充运行时源码。

## 执行与有限观测

直接调用原只读 runner 的 run()，仅重定向本任务 PAPER/RUNTIME/ROOT/端口12701；
source metadata 仅保留该窗 B 的引用，不复制或修改 bag。ROOT 为主工作区，
wait_for_ros_subscribers.py 必须与原版同SHA。原 runner 的流程与数学 YAML 不变：
32/40ms、maxiterations8、CPU2,3,8,9、OMP/OPENBLAS/MKL线程1；rate1、delay3、drain8，
ROS启动等待3s、node等待4s。ROS_HOME/LOG/TMP/output 指向实验盘的本任务目录。
无其他 VINS/rosbag 回放才启动；不杀其他任务。

包装器只在进程外读取 /proc：启动时间、命令、exe、实际环境白名单、映射库；
约每5s记录负载、可用内存/磁盘、node RSS/线程/亲和，第一次约1s读取加载库。
库哈希在 replay 后核验，避免播放中哈希争抢；不记录凭据或完整环境原文。
负载观测不是控制负载的实验，也不保证系统完全空闲。
观察器失败标明身份不完整，不暗中重跑。实际 IMU 消费顺序、内部完整状态、
Ceres精确终止消息无现成日志仍 Unknown.，不修改估计器补日志。

继承原资源线：系统盘>=2GiB、运行盘>=8GiB、MemAvailable>=4GiB，node RSS<=8GiB，
单次<=300s、日志<=512MiB。启动前及观察时检查；触线只终止本任务进程并保留结果，
余项标 NOT_STARTED_RESOURCE，不调低门。资源/身份阻塞之外，结果差也完成剩余项。
每项最多一次实际启动；已有有效 receipt 仅核验/复用，不覆写或以重试替换。
无新网络、参数搜索、新窗口或第二变体。

## 预先度量与判定

每次报告状态、实际环境身份、feature接收帧数/观测数/摘要、位姿数、首末纳秒头、
初始化日志次数、输出头跨度/完整输入feature跨度覆盖、solver条目数/预算/耗时。
覆盖只作工程描述，不替代原proxy common-support门。
逐时间头比全部新重复的3对以及各新重复对固定历史锚点的3对；
只有完整头向量和solver序列一一相同才作直接未对齐位置/姿态差及首次分叉比较。
不匹配时保留 NOT_COMPARABLE，不按序号强拼、不丢失败。
沿用旧严格A/A容差1e-5m/rad，标 EXACT_AA_PASS/AA_VARIATION；它不是APE门。
另报告原始最大位置范数，非定位真值误差，不设事后灾难阈值。

主判定：3/3完成且身份可核对后，如任一新—新对越过旧容差，标
ORIGINAL_BUDGET_VARIATION_PERSISTS；若都不越过，标 LIMITED_REPEAT_AGREEMENT，
不声称确定性。缺结果标 PARTIAL，缺接收/输出支撑标 NOT_COMPARABLE。
本次不做新的 APE/RPE、evo、对齐或尺度拟合，不设前端 WIN/LOSS，不宣称学习收益。
时间预算/负载的因果充分性仍未隔离，三次稳定或不稳定都不是其独立证明。
完成三次后停止，只给一个后续决策；不自动修改后端或复开前端搜索。

## 产物

本目录：协议、execution_lock.json、replay_results.csv、pairwise.csv、events.json、
report.md、decision.json、artifacts.sha256。运行期 receipt、库环境/负载、vio.csv、
backend_use.csv、日志留 /media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a08_controlled_repeats_v1。
GitHub仅发布紧凑证据和必要脚本，更新 docs/CODEX_HANDOFF.md 并实际读回验证。
