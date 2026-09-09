# A02 数值分叉已定位；安全防护完成，保留收益的算法修复未完成

更新时间：2026-09-09T16:59:17+08:00。实验 ID：EXP-20260909-A02-INIT-TRACE。
状态：COMPLETE / SAFE_FALLBACK_ONLY / NO_EXPANSION。
这是固定 VINS-Fusion 后端的前端机制诊断，不是新系统 benchmark，也不是回环检测实验。
COLMAP/proxy 是参考，不是独立 GT。六窗都已用于开发，不是 held-out。

## 本轮查清了什么

**Confirmed fact：原注册八个 donor 观测联合删除，足以使 A02 严重恶化；数值日志现已确认
两组初始化接受路径的分叉发生在尺度符号检查，而不是重力模长门。**
这不等于每一个 donor 单独致因，也不证明提前初始化本身独立导致全部误差。

本轮使用原 KLT、原 donor-delete-only bag 各三次，共 **6 次新增诊断回放**。
只开启冻结二进制已经存在的 `VINS_INITIAL_DIAGNOSTICS=1`，只打印数值；没有改源码、
重编译、改 YAML、改尺度/重力阈值、开启 bias rollback 或重跑原 v2 的 42 项 benchmark。
顺序为 KLT1/delete1/KLT2/delete2/KLT3/delete3，全六项完成，不按中途结果改变顺序。

| A02 输入 | 三重复各自的对齐尝试数 | 被拒次数 | 通过时线性 scale | 细化后 scale | 首个位姿延迟 |
|---|---:|---:|---:|---:|---:|
| KLT | 8 | 7 | 0.016609 | 0.033247 | 2.897861216 s |
| 仅删八观测 | 4 | 3 | 0.008543 | 0.034290 | 1.999418464 s |

每个已记录的失败都是 **线性尺度为负**；重力模长约 9.776–9.794，均在 9.81±0.5 的
原门内。第 4 次“各自的对齐尝试”中，KLT 为约 -0.00949，删点组为 +0.008543。
两组尝试序号不是已经证明的同一滑窗/同一图像时刻，不把这个差值当单一输入的导数。
全部六项的拒绝次数和首个位姿传感器时间与对应旧记录一致。
完整逐次值和原日志行号见 [initialization_attempts.csv](initialization_attempts.csv)。

结合之前的冻结库诊断：首次成功相对位姿之前，两组滑窗、323 对对应点及相对 R/T
完全相同；进入初始三维重建的 371 条多帧轨迹仍相同，但观测数 3834→3831。
donor 363/372/377 各少一个出生观测。**“只删 age-1、不删成熟点”并没有保住初始化约束。**
donor 377 后续同 ID 返回；原基线 105 次、本版 104 次，不能说删掉后续 104 帧。

**重要修正：内部接受 scale 约 0.033/0.034，并不是一边直接估成另一边两倍。**
不同初始视觉重建有各自尺度基准，内部 scale 与最后对 proxy 拟合的 scale 不可混称。
不能由最终误差倒推“初始化尺度恰好错两倍”。失败时偏置更新保留是代码事实，
但其独立致害作用、完整 SFM/PNP 状态及某三个/单个观测的充分性仍是 **Unknown**。

## 轨迹验证：负例仍稳定存在，日志回放不是旧轨迹的精确复刻

六项均初始化并通过覆盖门；新增六条与旧 KLT/delete 六条一起评估：
12 条共同支撑为 **42 poses / 41 s / 93.33% / 41 个严格 1s RPE 对**。
proper fixed-scale SE(3) 为主；Sim(3) 明确单列。evo 最大绝对差 4.88e-7 m。

下表为三重复中位数，括号为全范围；单位 m，参考为 proxy。

| 输入/运行 | fixed APE | fixed 1s RPE | Sim(3) APE | 拟合 scale 中位数 |
|---|---:|---:|---:|---:|
| 本轮日志 KLT | 0.140174 (0.102585–0.161920) | 0.022646 (0.020489–0.023853) | 0.060892 | 0.899579 |
| 本轮日志仅删点 | 1.104454 (1.082646–1.115142) | 0.104535 (0.102619–0.105733) | 0.046684 | 0.506317 |
| 旧 KLT，同网格复核 | 0.141317 (0.141052–0.142194) | 0.022697 (0.022691–0.022702) | 0.060774 | 0.898634 |
| 旧仅删点，同网格复核 | 1.073158 (1.071533–1.093353) | 0.102008 (0.101861–0.104176) | 0.045444 | 0.513513 |

新增 KLT 数值范围比旧记录宽，不能声称日志开关和当前调度完全不影响数值轨迹。
六次均复现初始化时刻/拒绝计数，且删点与 KLT 的 APE/RPE 范围仍完全分开。
保留所有值，不挑最好的一次；旧 benchmark 原表未改写。

## 实际修复：逐条保护完整 KLT 观测，而不是只保护成熟点

独立新增 [ClassicalObservationGuard](../../uw_frontend/ros/classical_observation_guard.py)：
对每一帧按 `(ID, camera)` 核对原 KLT 的全部观测，包括出生帧的坐标、quality 等所有通道，
以及保留顺序。删点、改写、换序、错误身份/非有限值或超过 350 都触发当帧 KLT 回退，
随后该 run 保持回退，避免不一致学习轨迹重新进入。决策只看当前/过去，不读取未来寿命、
proxy、序列名或离线初始化时刻；不改旧 exporter 和外部后端。

这是可调用的独立安全入口和实际 guarded bag 输出，不是把旧研究版本偷偷改名。
默认 noharm_v4 原本就要求不删除 KLT；本轮是针对已冻结替换输出增加不可绕过该入口的
逐观测检查，**不是声称发明了新的无害增强方法**。用户仍可显式运行保留的旧研究入口，
它们不因此自动受到本防护，也不能被叫作安全版本。

9 项单元测试通过。随后对原六窗、两学习臂的 **12 对已有完整输入流**执行防护，
没有重新运行网络/跟踪器。全部输出流重新读回核对，保留非特征消息、IMU、时间戳和顺序；
确认与 KLT 的每条消息一致后，最终 bag 保存为原 KLT 的整文件副本并核验 SHA-256。
最初的重写容器也保留供审计。

| 开发窗口 | 原 XFeat / SP+LG 对 KLT | 防护后 XFeat / SP+LG | 代价 |
|---|---|---|---|
| A09 6000–6800 | WIN / TIE | TIE / TIE | 丢失 XFeat 收敛收益，回到 KLT 发散轨迹 |
| A02 0–900 | LOSS / LOSS | TIE / TIE | 两个有害替换被阻断 |
| Bus s180 d45 | WIN / TIE | TIE / TIE | 原中位数收益消失 |
| A08 2700–3600 | TIE / TIE | TIE / TIE | 原零动作保持 |
| Cemetery s135 d45 | TIE / TIE | TIE / TIE | 原零动作保持 |
| H07 0–1000 | TIE / TIE | TIE / TIE | 原零动作保持 |

原四个动作臂均在输出帧 2 因 `baseline_observation_deleted` 触发防护。
防护后 **0 WIN / 12 TIE / 0 LOSS / 0 FAIL**，学习发布为 0，不能称作正例率提高。
18 条独立旧 KLT 轨迹经过输入、配置、相机、二进制、环境记录、receipt 和 VIO 哈希核验，
映射到 12 个臂—窗口的 36 个引用位置；**不是 36 次新回放**。修复验证新增后端回放 0。
全零动作不需要新 matched 控制；不能把旧控制当新干预结构的独立证明。

因此，**修复了这条路径的安全漏洞，但“同时消除 A02 回归且保留 A09/Bus 收益”没有完成。**
基线本身若发散，精确回退也会发散；禁止把它写成总体收敛性提高。
如果将来真实空位下有纯加点通过本 guard，也只说明经典观测未删除，不保证后端无害。

## 决策、边界与可复现入口

唯一决策：**SAFE_FALLBACK_ONLY / NO_EXPANSION**。安全使用该防护/既有不删点基线；
停止把启动期替换作为已验证的无害增强方法，不自动开第二个变体或扩大窗口。
兼顾收益的新机制必须另立问题、协议和授权，不能靠放宽本轮保护或事后选窗。
新窗口验证 0；本轮不新增物理正例，不估计自然正例率，不宣称优于同后端现代学习系统。

- [诊断协议](preregistration.md)、[六次 manifest](replay_manifest.json)、
  [逐次初始化/覆盖](replay_results.csv)、[误差中位数及范围](accuracy.csv)、
  [全部逐次精度](common_support/common_support_metrics.csv)、[共同支撑](common_support/common_support_summary.json)、
  [evo 核验](common_support/evo_crosscheck.json)。
- [独立修复合同](repair_contract.md)、[方法及输入锁](repair_lock.json)、
  [十二项防护结果](guard_results.csv)、[产物哈希](artifacts.sha256)。
- 命令（仓库根、已有 ROS Python 环境）：`python3 -B scripts/run_a02_initialization_trace.py`；
  `python3 -B scripts/analyze_a02_initialization_trace.py`；
  `python3 -B -m unittest discover -s tests -p test_classical_observation_guard.py -v`；
  `python3 -B scripts/validate_classical_observation_guard.py`。
  已完成分析/防护目录会拒绝覆盖，不能为了重现而删除旧产物。
- 源码身份：实验运行主树 `main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加新 manifest/repair lock
  内逐文件 SHA。冻结 node `4e91d8ac…f4278`、lib `373a598c…71e8`，A02 YAML `a0d5aad3…5af1`。
  报告发布 commit 是之后的文档/代码发布，不冒充实验运行时 commit。
- 运行数据根 `trace_runtime:` = `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a02_init_trace_repair_v1`；
  六次日志/VIO/receipt 和十二项 guarded bag 在 CSV/manifest 指向的位置。只公开紧凑证据，
  不上传 bag、模型、数据集、完整日志/环境或凭据；未写 `/mnt/data`、未改其他研究工作区。

失败尝试：防护验证启动前遇到 Python 项目搜索路径、覆盖 PYTHONPATH 后丢失 ROS 包、
以及 `__file__` 相对路径问题；已修正入口路径处理，均发生在方法锁和任何 guard 单元执行前。
不涉及科学结果筛选。逐 ID 真实残差使用、单 donor 充分性和偏置回滚的独立效果仍为 Unknown。
