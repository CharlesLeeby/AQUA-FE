# AQUA-FE 固定交接入口

更新时间：`2026-09-06T02:32:20+08:00`

发布分支：`codex/aqua-fe-evidence-20260905`

## 当前阶段和结论

当前最新实验是 `EXP-20260905-008`：在六个已经用于开发的窗口上，只把 v2
的 newborn exchange 从 selected feature frames 0–4 延后到 32–36；前 32 帧
与 fresh KLT 逐字节一致。该实验已完成并冻结为 **`NO_EXPANSION`**。

- 前端 18/18 PASS，matched-GFTT 7/7 PASS。
- 后端 42/42 新 replay PASS；另有 12 次 KLT replay 通过 bag、YAML、相机、
  VINS 二进制和 receipt 身份复用，不算独立重跑。
- 7/7 个 all-nine common supports PASS；固定尺度 SE(3) 为主，Sim(3) 只作尺度诊断。
- 七个 active 学习臂方向标签为 `6 WIN / 1 MIXED / 0 LOSS / 0 FAIL`；完整
  12 个学习臂—窗口分母另有 5 个零动作 exact TIE。这里的 WIN 包含低至
  0.003% 的微小方向变化，不能表述为六个有实际意义的正例。
- A02 的 v2 灾难回归消失；但 A09 的历史尺度救援也完全消失，Bus 没有任一臂
  达到预注册的 APE/RPE 同时改善至少 10%。因此不进入 12 个新窗口验证。

参考轨迹是 COLMAP/proxy，只表示与 proxy 的一致程度，不是独立 GT 绝对误差。
所有窗口均为 outcome-known 开发数据，不是 held-out。

## 完整窗口 × 方法结果

| 物理窗口 | delayed XFeat | delayed SP+LG | 说明 |
|---|---:|---:|---|
| A09 6000–6800 | WIN（微小、仍发散） | WIN（微小、仍发散） | 未保留 v2 尺度救援 |
| A02 0–900 | WIN | WIN | 均回到 KLT 附近，严重风险消失 |
| AFRL Bus s180 d45 | MIXED | WIN | XFeat APE 变差；SP+LG 改善不足 10% |
| A08 2700–3600 | exact TIE | exact TIE | 零动作、bag 与 KLT 相同 |
| AFRL Cemetery s135 d45 | WIN | exact TIE | XFeat 改善约 1.7%；SP+LG 零动作 |
| Harbor H07 0–1000 | exact TIE | exact TIE | 零动作、bag 与 KLT 相同 |

物理窗口数为 6，学习臂—窗口数为 12，active 臂—窗口数为 7；三次 solver
replay 只衡量技术稳定性，不是独立科学样本。

## 主要绝对结果

以下为三次技术重复中位数，APE/RPE 单位为米。18 个后端 cell 均为
`3/3 init`，54 个计划行的轨迹覆盖为 93.34%–96.75%；共同支撑为 38–43 poses、37–42 秒、
93.33%–95.56% coverage 和 37–42 个严格 1 秒 RPE pairs。

| 窗口 / 臂 | fixed-SE(3) APE | fixed-SE(3) RPE | Sim(3) scale |
|---|---:|---:|---:|
| A09 / KLT | 1242.140002 | 150.846817 | 0.001474 |
| A09 / delayed XFeat | 1242.106809 | 150.838407 | 0.001474 |
| A09 / delayed SP+LG | 1242.098781 | 150.838783 | 0.001474 |
| A02 / KLT | 0.141317 | 0.022697 | 0.898634 |
| A02 / delayed XFeat | 0.139741 | 0.022620 | 0.899927 |
| A02 / delayed SP+LG | 0.140679 | 0.022667 | 0.899152 |
| Bus / KLT | 0.060109 | 0.037218 | 0.956106 |
| Bus / delayed XFeat | 0.063018 | 0.035154 | 0.949511 |
| Bus / delayed SP+LG | 0.054487 | 0.036274 | 0.967653 |
| Cemetery / KLT | 0.533576 | 0.065177 | 1.252467 |
| Cemetery / delayed XFeat | 0.524416 | 0.064020 | 1.247086 |

evo 独立交叉验证最大差为 `4.997e-7 m`。完整中位数、范围、Sim(3) 和逐重复
结果见链接表格。

## 已查清的正例机制

`EXP-20260905-007` 的两个 donor-delete-only 对照均完成 3 次 replay：

- A09：KLT 与 delete-only 都在约 1242 m 的同一发散量级；加入 XFeat 或
  matched GFTT 才分别收敛到 0.732 m 和 1.082 m。
- Bus：delete-only 三次中两次发散，中位 APE 53.052 m；加入 XFeat 或
  matched GFTT 后分别为 0.0423 m 和 0.0442 m。

因此两个历史正例都不是“只删点即赢”，候选加入相对 delete-only 是必要的；
但 matched GFTT 同样能救援，所以 **learned 来源的必要性仍未证明**。当前最强结论是
“少量观测替换能双向改变初始化/收敛分支”，不是“学习持久锚点普遍增强”。

A02 的 `DELETE_SUFFICIENT` 边界保持不变：只删除预注册的八个启动期 donor
观测、不加候选，足以复现该窗口的严重尺度/精度退化。这不证明候选零影响，
不证明任一 donor 单独致因，也不能外推到总体窗口比例。

## Lineage 和 Unknown

v2 的 14 条 learned lineage 共 21 个发布观测：10 条长度 1、1 条长度 2、
3 条长度 3，没有一条达到锁定后端的 4 观测非线性残差资格计数。预算审计确认：

- v2 没有独立的新准入预算和已准入 ID 续传表；startup horizon 同时截断两者；
- 50 次 sequence counter 在最终仲裁前消费，A02 每臂有 50 个 pre-final
  sidecar，但只发布 8 个；
- 3 个 singleton 紧邻 aggregate budget 耗尽；另 5 个同 ID 停止原因仍
  **Unknown**；另外 2 个下一输出帧 tracker learned count 为 0。

候选逐 ID 内部存活、后端逐 ID 收到/实际进入残差、counter 原设计语义均仍是
**Unknown**，不得写成“已确认预算 bug”。A02 donor ID 377 实际只缺一个发布观测，
下一帧以同 ID 恢复；不能写成删除了未来 104 帧。

## 完成、未完成和唯一下一步

已完成：v2 42 次后端、A02 delete-only、A09/Bus delete-only、lineage/预算审计、
delayed-v3 的前端、matched controls、42 次新后端、共同支撑和冻结判定。

未完成且 **Not evaluated**：12 个新窗口验证、在线初始化状态保护、共享初始化状态
下的候选价值、数据集总体正例率。因为 v3 没过扩展门，这些项目没有启动，不能通过
继续换 horizon 或挑窗口来补正例。

唯一下一步：遵守 `NO_EXPANSION`，停止本协议的方法扩展并把“初始化干预高度敏感、
learned 必要性未证实”作为论文证据边界。若以后继续算法开发，必须为共享初始化状态
或在线可观测判据另写新协议，不能作为 EXP-20260905-008 的第二个参数尝试。

## 仓库内可读证据

- [delayed-v3 完整报告](../papers/frontend_delayed_newborn_slot_v3/report.md)
- [预注册协议](../papers/frontend_delayed_newborn_slot_v3/preregistration.md)、
  [冻结决策](../papers/frontend_delayed_newborn_slot_v3/backend_decision.json)
- [完整 12 臂结果](../papers/frontend_delayed_newborn_slot_v3/development_outcomes.csv)、
  [主精度表](../papers/frontend_delayed_newborn_slot_v3/accuracy.csv)、
  [逐重复精度](../papers/frontend_delayed_newborn_slot_v3/accuracy_repeats.csv)
- [逐 replay runability](../papers/frontend_delayed_newborn_slot_v3/backend_results_repeats.csv)、
  [臂级 runability](../papers/frontend_delayed_newborn_slot_v3/runability.csv)
- [前端动作审计](../papers/frontend_delayed_newborn_slot_v3/action_audit.csv)、
  [matched control 审计](../papers/frontend_delayed_newborn_slot_v3/matched_control_audit.csv)、
  [共同支撑审计](../papers/frontend_delayed_newborn_slot_v3/common_support_status.csv)
- [后端配置审计](../papers/frontend_delayed_newborn_slot_v3/backend_config_audit.csv)、
  [完整哈希清单](../papers/frontend_delayed_newborn_slot_v3/artifacts.sha256)、
  [公开副本来源身份](research_sync/EXP-20260905-008_delayed_v3/source_identity.csv)
- [A09/Bus 正例删除归因报告](../papers/frontend_v2_positive_delete_diagnostic/report.md)、
  [四臂比较](../papers/frontend_v2_positive_delete_diagnostic/comparisons.csv)
- [A02 DELETE_SUFFICIENT 报告](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/report.md)
- [v2 完整后端报告](../papers/frontend_coverage_monotone_router_v2/backend_completion_report.md)、
  [lineage 预算审计](../papers/frontend_coverage_monotone_router_v2/lineage_budget_audit.md)

## 源码、配置和数据身份

实验运行时基线为 `main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加冻结工作树
文件；报告发布 commit 是后来的证据身份，不能冒充运行时源码 commit。

- exporter：`bb4e50d8...714d1d`（v3 未修改 exporter）；
- v3 environment/profile lock：`scripts/learned_seedchain_env.sh`
  `4372ad94...aa02a`，method lock `9a6655a4...e8e54`；
- VINS node/library：`4e91d8ac...f4278` / `373a598c...71e8`；
- 后端原 lock：`26146d69...2473`；只修输出收集路径的 wrapper amendment：
  `f4d68efa...e89a`；所有四个 active 物理窗口三臂 YAML 哈希各自唯一且审计 PASS。

原始 bag、数据集、模型、缓存、完整控制台日志未上传。`artifacts.sha256` 用
`repo:`、`v3_runtime:`、`v2_runtime:` 表示真实本地根，并给出 feature bag、
`vio.csv`、`vins.log`、receipt 和紧凑报告的 SHA-256；GitHub 只发布小型报告、表格、
协议、必要脚本和路径脱敏身份清单。
