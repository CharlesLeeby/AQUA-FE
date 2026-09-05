# AQUA-FE 固定交接入口

更新时间：`2026-09-05T23:15:18+08:00`

## 当前阶段与结论

当前权威实验为 `EXP-20260905-005`（coverage-monotone router v2 固定后端闭环）、
`EXP-20260905-006`（A02 donor-delete-only route-D 诊断）和 `EXP-20260905-007`
（A09/Bus 正例 donor-delete-only 诊断）。这些窗口均为已知结果的开发证据；
参考轨迹是 COLMAP/proxy，不是独立真值。主指标使用逐轨迹 proper fixed-scale SE(3) 对齐，
Sim(3) 只作尺度诊断。

- v2 冻结后端完成 `42/42` 次 replay，`42/42` 初始化并通过覆盖门；14 个独立 replay cell
  全部 PASS，4 个 active 三臂共同支撑全部 PASS。
- active 学习臂相对 KLT 为 `2 WIN / 0 TIE / 2 LOSS / 0 FAIL`。加入 8 个零动作、bag 与 KLT
  逐字节一致的映射后，完整 12 个学习臂—窗口分母为 `2 WIN / 8 exact TIE / 2 LOSS / 0 FAIL`；
  这些 TIE 不是额外 replay 或独立样本。
- A09 与 AFRL Bus 改善，但 matched GFTT 也呈同方向改善；A02 的 XFeat、SP+LG 和对应
  matched GFTT 均严重退化。因此 v2 被判定为 `COMPLETE_REJECT_NOHARM`，不能支持 AQUA-FE
  普遍优于 KLT 或现代学习前端。
- A02 route-D 从 fresh KLT 只删除预注册的 8 个启动期 donor 观测、完全不加候选。
  3/3 replay PASS，并复现尺度/精度崩坏，判定 `DELETE_SUFFICIENT`。准确边界是：这 8 个
  注册删除足以产生该 A02 结果；它不证明新增候选完全无影响、不证明任何单个 donor 独立致因，
  也不能外推自然正例率。
- 正例删除对照新增 replay `6/6` PASS，两个窗口的 12-arm 联合共同支撑均 PASS。A09 的
  delete-only 与 KLT 同样数量级发散，只有加入 learned 或 matched GFTT 后才收敛；Bus 的
  delete-only 中位数严重退化，加入任一候选才稳定并优于 KLT。因此两个正例都不是“删点即赢”。
  但 matched GFTT 同样有效，现有正例主要支持观测/初始化干预，尚不支持 learned 必要性。

## 完整分母

| 物理窗口 | XFeat v2 vs KLT | SP+LG v2 vs KLT | 备注 |
|---|---:|---:|---|
| A09 6000–6800 | WIN | exact TIE | SP+LG 零动作、映射 KLT |
| A02 0–900 | LOSS | LOSS | 两臂均为重复严重回归 |
| AFRL Bus s180 d45 | WIN | exact TIE | SP+LG 零动作、映射 KLT |
| A08 2700–3600 | exact TIE | exact TIE | 两臂零动作 |
| AFRL Cemetery s135 d45 | exact TIE | exact TIE | 两臂零动作 |
| Harbor H07 0–1000 | exact TIE | exact TIE | 两臂零动作 |

这里的物理窗口数为 6，学习臂—窗口数为 12；三次 solver replay 只衡量技术稳定性，
不作为独立科学样本。

## 主要绝对结果

数值为三次 replay 的中位数；APE/RPE 单位为米。共同支撑有 38–42 个 pose、37–41 秒、
93.33%–95.00% coverage 和 37–41 个严格 1 秒 RPE pair。

| 窗口 / 臂 | fixed-SE(3) APE | fixed-SE(3) RPE | Sim(3) scale |
|---|---:|---:|---:|
| A09 / KLT | 1242.140002 | 150.846817 | 0.001474 |
| A09 / XFeat | 0.732414 | 0.073563 | 0.753181 |
| A09 / matched GFTT | 1.082355 | 0.116941 | 0.673421 |
| A02 / KLT | 0.141317 | 0.022697 | 0.898634 |
| A02 / XFeat | 1.091754 | 0.104297 | 0.509214 |
| A02 / SP+LG | 1.113829 | 0.104368 | 0.504201 |
| A02 / donor-delete-only | 1.073158 | 0.102008 | 0.513513 |
| AFRL Bus / KLT | 0.060109 | 0.037218 | 0.956106 |
| AFRL Bus / XFeat | 0.042794 | 0.026725 | 0.972868 |
| AFRL Bus / matched GFTT | 0.044833 | 0.027888 | 0.962457 |

A02 donor-delete-only 相对 KLT 的 APE/RPE 为 `+659.4% / +349.4%`；其接受的初始化事件
中位数提前 0.785 秒，与 learned/matched 的约 0.795 秒提前接近。该证据支持“启动期删点
改变初始化路径并足以造成 A02 尺度失败”，但具体后端因果链仍是 Hypothesis / Inference。

正例删除对照在重新计算的 12-arm 共同支撑上得到：

| 窗口 / 臂 | fixed-SE(3) APE | fixed-SE(3) RPE | Sim(3) scale |
|---|---:|---:|---:|
| A09 / B fresh KLT | 1242.140002 | 150.846817 | 0.001474 |
| A09 / B-D delete only | 1242.135147 | 150.843919 | 0.001474 |
| A09 / B-D+L XFeat | 0.732414 | 0.073563 | 0.753181 |
| A09 / B-D+C matched GFTT | 1.082355 | 0.116941 | 0.673421 |
| Bus / B fresh KLT | 0.060301 | 0.037071 | 0.950924 |
| Bus / B-D delete only | 53.052375 | 6.980129 | 0.013964 |
| Bus / B-D+L XFeat | 0.042258 | 0.026681 | 0.969382 |
| Bus / B-D+C matched GFTT | 0.044229 | 0.026862 | 0.961621 |

A09 `B-D` 对 `B` 的微小中位数差（APE `-0.00039%`、RPE `-0.00192%`）只是同一发散量级，
不复现正例；Bus `B-D` 三次中有两次发散。结论边界是“候选加入对这两个正例必要”，并非
“learned 来源必要”；删除和加入仍是一个联合干预，不能据此断言某一单独候选的因果效应。

## Lineage 与审计边界

14 条 learned lineage 共发布 21 个观测：10 条长度 1、1 条长度 2、3 条长度 3；没有一条
达到锁定后端的 4 观测非线性残差资格计数。实现审计确认 v2 没有分离首次准入与已准入续传，
startup horizon 对两者一并关闭，并且 50 次 sequence 计数在最终仲裁之前消费：A02 两臂各有
50 个 pre-final sidecar、实际只发布 8 个。10 条 singleton 中，3 条下一帧已被 aggregate budget
挡住，5 条仍有 aggregate sidecar 但同 ID 原因 Unknown，另 2 条下一输出帧 tracker learned
count 为 0。精确同 ID 的内部候选出生、隐藏存活、
后端逐 ID 接收以及实际进入残差，当前均为 **Unknown**。A02 donor ID 377 实际只少了替换帧
的 1 个观测，下一帧以同 ID 连续恢复；“基线以后还有 104 帧”不是“v2 删除了 104 帧”。

## 已完成、未完成与唯一下一项

已完成：v2 前端/动作/matched control/lineage 审计、42 次冻结后端、全重复共同支撑评估、
A02 donor-delete-only 三次诊断、A09/Bus donor-delete-only 六次诊断，以及本证据快照的
路径脱敏镜像。

尚未完成：基于删除归因选择的唯一最小新版本；12 个新窗口验证。它们当前均为
**Not evaluated**，不能写成已完成或已同步结果。

唯一下一项实验是：在原六窗开发集冻结一个 delayed newborn-slot 版本，只把 v2 的固定
5-selected-frame 介入窗延后到全局固定启动保护之后；候选来源、阈值、donor 排序、每帧及
总预算均不变。保护期内输入保持 fresh KLT；之后仍只置换 age-1 GFTT，不删成熟轨迹。
它不是在线“已初始化”保证，也不等于保留全部将来新生 GFTT。该版本先验证 A02 风险是否
消失以及 A09/Bus 收益能否保留；通过预注册开发门后才允许锁定 12 个新窗口。

## 可读证据与身份

- [v2 完整后端报告](../papers/frontend_coverage_monotone_router_v2/backend_completion_report.md)
- [v2 主精度表](../papers/frontend_coverage_monotone_router_v2/accuracy.csv)、
  [逐重复精度](../papers/frontend_coverage_monotone_router_v2/accuracy_repeats.csv)、
  [比较表](../papers/frontend_coverage_monotone_router_v2/backend_comparisons.csv)、
  [runability](../papers/frontend_coverage_monotone_router_v2/runability.csv)
- [v2 动作审计](research_sync/EXP-20260905-005_v2_backend/action_audit.csv)、
  [matched control 审计](research_sync/EXP-20260905-005_v2_backend/matched_control_audit.csv)、
  [lineage 审计](research_sync/EXP-20260905-005_v2_backend/lineage_diagnostic.csv)、
  [42 次紧凑 replay 表](research_sync/EXP-20260905-005_v2_backend/backend_results_repeats_compact.csv)、
  [来源 SHA-256](research_sync/EXP-20260905-005_v2_backend/source_identity.csv)
- [lineage 预算/续传审计](../papers/frontend_coverage_monotone_router_v2/lineage_budget_audit.md)、
  [逐 ID 紧凑表](../papers/frontend_coverage_monotone_router_v2/lineage_budget_audit.csv)
- [v2 冻结协议](../papers/frontend_coverage_monotone_router_v2/preregistration.md)、
  [最终决策](../papers/frontend_coverage_monotone_router_v2/decision_backend_complete.json)；
  `decision_historical_blocked_disk.json` 仅是已被完成结果取代的历史检查点。
- [A02 donor-delete 报告](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/report.md)、
  [主精度表](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/accuracy.csv)、
  [逐重复精度](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/accuracy_repeats.csv)、
  [删除清单](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/deleted_observations.csv)、
  [协议](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/preregistration.md)、
  [决策](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/decision.json)、
  [来源 SHA-256](research_sync/EXP-20260905-006_a02_donor_delete/source_identity.csv)
- [A09/Bus 正例 donor-delete 报告](../papers/frontend_v2_positive_delete_diagnostic/report.md)、
  [主精度表](../papers/frontend_v2_positive_delete_diagnostic/accuracy.csv)、
  [逐重复精度](../papers/frontend_v2_positive_delete_diagnostic/accuracy_repeats.csv)、
  [四臂比较](../papers/frontend_v2_positive_delete_diagnostic/comparisons.csv)、
  [runability](../papers/frontend_v2_positive_delete_diagnostic/runability.csv)、
  [删除清单](../papers/frontend_v2_positive_delete_diagnostic/deleted_observations.csv)、
  [预注册协议](../papers/frontend_v2_positive_delete_diagnostic/preregistration.md)、
  [决策](../papers/frontend_v2_positive_delete_diagnostic/decision.json)、
  [来源 SHA-256](research_sync/EXP-20260905-007_positive_delete/source_identity.csv)

实验运行时源码身份是 `main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加锁定的工作区文件：
exporter SHA-256 `bb4e50d8...714d1d`，v2 runner `a5c171d8...ec3fe4`，后端 node
`4e91d8ac...f4278`，后端 library `373a598c...71e8`。逐文件、逐窗口配置和输入 bag 的完整
哈希见公开的 execution/method lock 与紧凑 replay 表；原始 bag、数据、模型、缓存和完整日志
没有上传。后续“报告发布 commit”仅表示证据发布身份，不冒充上述实验运行时源码 commit。
