# A02 初始化路径：既有日志只读补充

更新时间：2026-09-07T22:52:50+08:00。归属 `EXP-20260906-012` 的事后机制审计，
不是新的算法实验或预注册检验。状态：`COMPLETE / NO_EXPANSION` 不变。

## 新确认了什么

**Confirmed fact：A02 的有害输入改变了被接受的初始化路径；这一变化也出现在原 v2 的只删点对照。**
不是“只有 learned 匹配差”，也不是“删掉 donor 后续 104 帧”。
但“提前初始化导致全部误差”“某一个 donor 单独致因”仍未被证明。

只读检查三个已有 manifest 中 A02 的全部记录，按实际 replay 目录去重：
10 个版本—臂组合 × 3 重复 = **30 份既有回放、1 个物理开发窗口、0 次新增 replay**。
其中 KLT 3、旧 v2 学习/matched 12、本版学习/matched 12、原 donor-delete-only 3。
30/30 receipt 的臂/重复/输入/配置/二进制身份与 manifest 一致，实际 `vio.csv` 哈希与 receipt 一致。
没有重算或拼接不同 common support 的 APE/RPE，没有改变胜负和停止标准。

下表中的次数是**每次回放日志内**的次数，每组全部重复一致；不是独立窗口样本量。
时间为首个位姿的传感器时间减去首个 feature 时间，不是 ROS 日志时钟或运行耗时。

| 已有输入组 | 既有回放数 | 特征/视差不足拒绝 | 视觉—IMU 对齐拒绝 | 陀螺偏置校准日志 | 首个位姿延迟（s） |
|---|---:|---:|---:|---:|---:|
| fresh KLT | 3 | 5 | 7 | 8 | 2.897861216 |
| 旧 v2 XFeat/SP+LG 及各自 matched | 12 | 5 | 3 | 4 | 1.999418464 |
| 续传 v1 XFeat/SP+LG 及各自新 matched | 12 | 5 | 3 | 4 | 1.999418464 |
| 原 v2 八观测 donor-delete-only | 3 | 5 | 3 | 4 | 1.999418464 |

干预组首个输出对应的传感器时刻比 KLT 提前 **0.898442752 s**。
30/30 均仅有一次 `Initialization finish!`，未记录 `system reboot!`；
没有 reboot 日志不等于已测量所有 lost-tracking 事件。
逐次值、日志行号、实际路径、receipt/log/vio/environment 哈希见
[a02_initialization_log_audit.csv](a02_initialization_log_audit.csv)。

例如 KLT repeat1 的对齐失败位于 `vins.log` 行 44、46、48、50、52、54、57，
成功标记行 59；本版 XFeat repeat1 对齐失败位于行 40、42、44，成功标记行 46。
WARN 与 INFO 的文本行可能因 stdout/stderr 缓冲而乱序，审计按日志的 wall-clock
时间排序后统计成功之前的事件；CSV 同时保留原文件行号。不能把文件行序当时间序。

## 源码让日志可以解释到哪一层

只读当前同身份外部后端，未修改或重编译：

- `estimator.cpp:637–648`：特征/视差不足信息对应 `relativePose()` 失败；SFM 失败另用 DEBUG。
- `estimator.cpp:720–739`：`misalign visual structure with IMU` 对应视觉—IMU 初始化对齐失败，
  不是通用“候选跟丢”信息。成功后先优化、更新状态，再切到 `NON_LINEAR`。
- `estimator.cpp:608–613`：低 IMU 激励只打印提示，紧随的 `return false` 已注释。
  KLT 14 次、各干预 9 次提示，**不能把这些提示另算成初始化拒绝次数**。
- `initial_aligment.cpp:190–225`：对齐过程涉及重力模长检查和尺度符号/细化检查；
  当时的数值没有写入现有日志。额外初始化尺度/偏置限制与诊断选项在 30 份环境记录中均为空。
  因此具体失败条件、初始化尺度值、重力误差和完整 SFM/PNP 尝试序列仍是 **Unknown**。

源码还有失败尝试前的偏置更新与可选回滚逻辑；本审计没有测量其对结果的独立贡献，
不将其诊断为已确认后端 bug，不开环境开关“修正”冻结后端。
本轮源码读取的身份：`estimator.cpp` SHA-256
`ea75d3f074f6c8780fff3353dc1628e94d265e63be13672caed4bdd64dd3572e`
（与之前接口审计一致）；`initial_aligment.cpp` SHA-256
`b17af48453b31f213ef7b48fa99cd3c894a99b6b5f77d5c69ae6ea945af82047`。
当前 node/lib 哈希也与冻结 manifest 一致。源码逐行解释不替代未记录的内部状态。

## 结论边界与决策

结合原 [A02 删除对照](../frontend_coverage_monotone_router_v2_donor_delete_diagnostic/report.md)，
**注册八个观测的联合删除足以复现严重退化和较早接受的初始化路径**。
本版延长发布链后仍落在相同首个输出时刻，但不是状态数值完全相同的证明；
原删除集合的因果结论也不能自动转移到本版新删除集合。

**Hypothesis / Inference：** A02 的主要风险与启动期观测扰动改变视觉—IMU初始化过程一致，
不是单纯缺少后续持久约束；延长候选链不能保证纠正已改变的初始化结果。
较早初始化与更差 fixed-scale proxy 误差的关联，不证明提前 0.898 秒本身就是根因。
最终 Sim(3) 拟合尺度也不是初始化时内部求出的尺度，二者不得混称。

本补充不更新旧精度表：本版六窗仍为 **2 WIN / 8 TIE / 2 LOSS / 0 FAIL**，
A02 风险未消除，新正例窗口 0，新窗口验证 0。参考为 COLMAP/proxy，非独立 GT。

**唯一决策：停止此启动期准入/续传版本，维持 NO_EXPANSION；不自动再试第二个变体。**
现有 INFO 日志的细化归因已到证据边界。任何进一步干预实验需独立问题、明确授权和新协议；
不修改外部后端，也不把已失败的延迟/保护方案重新当成未试过的下一步。

## 复核入口

- [只读脚本](../../scripts/audit_a02_initialization_logs.py)：在仓库根运行
  `python3 -B scripts/audit_a02_initialization_logs.py`，CSV 仅输出到 stdout，不写输入或运行后端。
- 来源：[原 v2 manifest](../frontend_coverage_monotone_router_v2/backend_smoke_plan.csv)、
  [本版 manifest](backend_replay_plan.csv)、
  [原删点 manifest](../frontend_coverage_monotone_router_v2_donor_delete_diagnostic/replay_plan.csv)。
  历史 manifest 的 PENDING 是冻结时状态，完成性以其实际 receipt/完成报告为准。
- [完整开发结果](report.md)、[冻结决策](backend_decision.json)、
  [既有初始化接口审计](../frontend_init_state_interface_audit/report.md)保留原文。
- 验证：两项解析检查（ANSI/乱序、无双时钟行）；30/30 receipt 身份；重运行脚本与 CSV 逐字节一致。
  原始 bag/完整日志不上传，公开本表与行号/哈希供核查；读回时间口径用 Decimal，
  与旧 float 时刻表可能有亚微秒舍入差异，不代表输入时轴改变。
