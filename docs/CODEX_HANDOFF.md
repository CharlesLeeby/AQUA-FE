# AQUA-FE 固定交接入口

更新时间：2026-09-08T02:35:14+08:00
发布分支：`codex/aqua-fe-evidence-20260905`

## 当前实验与结论

**EXP-20260906-012：COMPLETE / NO_EXPANSION。**
只实现了一个“首次准入与同 ID 持续发布分离”开发版本：首次准入不变，
续传绕过首次准入期限/预算规则，保留镜像 carried KLT，只竞争新生 GFTT/空位。
这是独立策略改动，不是覆盖旧 v2 的记账修复。

结论：**A09 已知正例进一步改善，但 A02 风险未消除，没有新增正例窗口。**
新版本不能称 no-harm，不能说明 AQUA-FE 总体优于 KLT 或同后端现代学习系统。
固定后端前端隔离对比，不作与 HFNet-SLAM 的整系统精度声明。
实际配置 `loop_closure=0`；验证的是前端到 VINS 的端到端影响，不是回环检测收益。
参考为 COLMAP/proxy，非独立 GT；fixed-scale proper SE(3) 为主，Sim(3) 只作明确诊断。

- 六个已知结果的开发窗口，不是 held-out。前端 18/18 PASS，matched GFTT 4/4 PASS。
- 动作：4/12 学习臂—窗口、3/6 物理窗口；33 次发布、11 条 lineage。
  省略 33 个 age-1 GFTT，carried 观测变化为 0；8 个零动作学习臂整 bag 等于 KLT。
- **24/24 新后端回放完成 + 18/18 身份有效 KLT 复用**，不是 42 次新 replay。
  原 v2 的 42 次结果未重跑。solver 三重复不是独立科学样本。
- 全分母：**2 WIN / 8 TIE / 2 LOSS / 0 MIXED / 0 FAIL**；
  active 分母：2 WIN / 2 LOSS / 0 FAIL。没有丢弃 active 失败。
- 42/42 初始化和覆盖门通过；266–489 poses，轨迹覆盖 93.336%–97.604%。
  四组 all-nine common support 全 PASS：38–42 poses、37–41 秒、93.33%–95%。
  evo 最大差 < 5e-7 m；每窗后端/相机 YAML 和二进制一致，42 项环境身份审计 PASS。
- 新窗口完成 0；没有进入 12 窗验证，不能据此估计数据集自然正例率。

| 开发窗口 | XFeat | SP+LG |
|---|---|---|
| A09 6000–6800 | WIN | exact TIE / 零动作 |
| A02 0–900 | LOSS | LOSS |
| Bus s180 d45 | WIN，中位数；输入与旧 v2 相同 | exact TIE / 零动作 |
| A08 2700–3600 | exact TIE / 零动作 | exact TIE / 零动作 |
| Cemetery s135 d45 | exact TIE / 零动作 | exact TIE / 零动作 |
| H07 0–1000 | exact TIE / 零动作 | exact TIE / 零动作 |

## 主要绝对结果与机制边界

下表为三次中位数，fixed APE / 1s RPE，单位 m；完整范围、逐次值与 Sim(3) 在报告/CSV。

| active 窗口 / 臂 | KLT APE / RPE | learned APE / RPE | matched GFTT APE / RPE |
|---|---|---|---|
| A09 / XFeat | 1242.140 / 150.847 | 0.641290 / 0.061445 | 1.653014 / 0.166323 |
| A02 / XFeat | 0.141317 / 0.022697 | 0.979235 / 0.091623 | 1.109044 / 0.104795 |
| A02 / SP+LG | 0.141317 / 0.022697 | 0.996579 / 0.092403 | 0.999609 / 0.092963 |
| Bus / XFeat | 0.060109 / 0.037218 | 0.042794 / 0.026725 | 0.054469 / 0.027436 |

A09 同一 ID 从 3 次延长至 11 次（约 1 秒）；相对旧 v2 重新共同支撑后的 fixed
APE/RPE 降 12.44%/16.47%。但 Sim(3) APE/RPE 反增约 41.4%/3.4%，拟合 scale
0.753→0.778：不是所有几何口径都提升。相对本版 matched，fixed APE/RPE 低
61.20%/63.06%，支持这个开发窗候选内容有额外作用；matched 也优于 KLT，
因此 learned 仍非被证明必需。

A02 两臂相对旧 v2 改善约一成，仍较 KLT 有约 +593%/+605% APE 回归，未修复风险。
Bus 新输入与旧 v2 字节一致，中位数收益不算新机制收益；一次 APE 为 0.065287，
高于 KLT 0.060109，不能称三次都无害。

本版 11 条 lineage 的终止分类：8 条因镜像保护规则下无空位，1 条质量不合格，
2 条下一帧门前已无候选（精确 tracker 原因 Unknown）；4 条仍是单次发布。
原 v2 的 10 条单帧不能全部归因于预算耗尽，原审计结论未改写。
A02 镜像还保护了此前从未公开的点，限制了续传；放宽它将改变更多基线观测，
属于另一个未经测试、不能保证无害的策略，本轮没有实施。
donor 377：本版只缺输出帧 4 的一个观测，帧 5 同 ID 返回；不是删掉 104 帧。

原 A02 **DELETE_SUFFICIENT** 仅表示注册八个 donor 观测的联合删除足以复现危害，
不表示某一个 donor 单独致因、候选毫无影响，或本版新删除集合也完成了删除归因。
原 A09/Bus delete-only 不复现收益，支持原组合需要加点作用，但 matched classical
也能提供正向作用，不能改写成“学习持久锚点必需”。

## 已完成、Unknown 与唯一下一步

已完成：本版六窗前端、逐链诊断、新 matched 控制、完整后端三重复、双尺度/evo、
旧 v2 同网格比较、配置/环境/时刻审计与产物身份。之前的 v2、删除诊断及负例均保留。

Unknown：逐 ID 内部完整寿命、实际后端接收/残差使用、Bus 两条候选的精确 tracker 终止原因。
Not evaluated：新窗口/sequence-held-out、独立 GT 精度、实时初始化反馈方法、总体自然正例率。
初始化日志 ROS 时间和首个位姿传感器时间在运行审计中分开记录。

本轮只读补充（0 次新 replay）：A02 全部 30 份既有记录的身份核验通过。
KLT 各重复有 7 次视觉—IMU 对齐拒绝，旧/新替换、matched、原只删点组均为 3 次；
后者首个位姿传感器时刻提前 0.898443 s。原删点也改变了接受初始化的路径，
但具体尺度/重力拒绝值 Unknown，不能说“较早初始化本身已被证明是根因”。
详见 [初始化补充](../papers/frontend_admission_continuation_v1/a02_initialization_addendum.md)
与 [30 份逐次日志审计](../papers/frontend_admission_continuation_v1/a02_initialization_log_audit.csv)。

9 月 8 日新增 [恶化机制定位](../papers/frontend_admission_continuation_v1/a02_degradation_mechanism.md)：
直接调用冻结库做初始化前缀诊断（不是新 VIO replay），KLT/delete-only 首次相对位姿前的
窗口、323 对对应点及相对位姿完全相同；进入 SFM 的多帧观测 3834→3831，
对应 donor 363/372/377 各少一个出生观测，371 条多帧轨迹的数量和顺序不变。
这否定“只动 age-1 就保护了初始化约束”的推理；不是三点子集已被单独验证致因。
源码/日志还确认失败对齐前的偏置更新不自动回滚，但其独立致害作用 Unknown。
精确尺度/重力失败值仍需独立的仅日志诊断，尚未授权/执行；本轮未修方法或再开变体。

**唯一下一步：按冻结决定停止此续传版本，不扩展新窗、不自动再试第二个预算/顺序/保护范围变体。**
保留局部 A09 增益与 A02 严重负例；“扩大正例且没有严重回归”的目标未获支持。

## 可直接读取的证据

- [完整报告](../papers/frontend_admission_continuation_v1/report.md)、
  [12 项胜负](../papers/frontend_admission_continuation_v1/development_outcomes.csv)、
  [主精度与范围](../papers/frontend_admission_continuation_v1/accuracy.csv)、
  [逐次精度](../papers/frontend_admission_continuation_v1/accuracy_repeats.csv)
- [runability](../papers/frontend_admission_continuation_v1/runability.csv)、
  [逐次后端](../papers/frontend_admission_continuation_v1/backend_results_repeats.csv)、
  [共同支撑](../papers/frontend_admission_continuation_v1/common_support_status.csv)
- [逐链与 donor 诊断](../papers/frontend_admission_continuation_v1/lineage_diagnostic.csv)、
  [动作](../papers/frontend_admission_continuation_v1/action_audit.csv)、
  [matched 审计](../papers/frontend_admission_continuation_v1/matched_control_audit.csv)、
  [与旧 v2 的同网格比较](../papers/frontend_admission_continuation_v1/v2_common_comparison.csv)
- [预注册](../papers/frontend_admission_continuation_v1/preregistration.md)、
  [窗口](../papers/frontend_admission_continuation_v1/development_windows.csv)、
  [方法锁](../papers/frontend_admission_continuation_v1/method_lock.json)、
  [replay manifest](../papers/frontend_admission_continuation_v1/backend_replay_plan.csv)、
  [冻结决策](../papers/frontend_admission_continuation_v1/backend_decision.json)
- [后端配置审计](../papers/frontend_admission_continuation_v1/backend_config_audit.csv)、
  [实际 YAML 快照来源表](../papers/frontend_admission_continuation_v1/backend_config_snapshots/source_identity.csv)、
  [环境与初始化时刻](../papers/frontend_admission_continuation_v1/backend_environment_audit.csv)、
  [哈希清单](../papers/frontend_admission_continuation_v1/artifacts.sha256)
- [原 v2 完整后端](../papers/frontend_coverage_monotone_router_v2/backend_completion_report.md)、
  [A02 删除对照](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/report.md)、
  [A09/Bus 删除归因](../papers/frontend_v2_positive_delete_diagnostic/report.md)、
  [原预算审计](../papers/frontend_coverage_monotone_router_v2/budget_continuation_addendum.md)

运行源码身份：`main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加 method lock 的精确文件。
新入口 SHA-256 为 `52c793ee…be8e`；原 v2 exporter 从 `3c50b742…de684` Git 对象加载并校验
`bb4e50d8…d1d`。这是实验源码身份，不是之后的报告发布 commit。
数据/相机/窗口引用及完整 SHA 见协议、manifest、真实 YAML 快照。
bag、模型、原始数据和完整控制台日志留本地，不上传；这里公开实际报告和数值表，不只有哈希。
