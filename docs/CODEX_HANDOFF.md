# AQUA-FE 固定交接入口

更新时间：`2026-09-06T22:59:42+08:00`
发布分支：`codex/aqua-fe-evidence-20260905`

## 当前阶段与结论

最新检查点是 `EXP-20260906-011`（只读预算/续传诊断）：4/4 原 metrics 身份
核验通过，14 条 lineage 全部复核，5/5 冻结源码函数测试通过。10 条单帧发布不能
统一归因于预算耗尽：5 条停止后的下一帧仍通过 23 个候选，3 条之后无 pre-final
候选，另 2 条之后没有 learned tracker 输出。A09 只用了 3/50 名额就被 microburst
关闭。这个分类区别此前已在发布区审计中说明，本次补回主目录，并新增五个精确
冻结源码的复现测试和固定发布起点下的长度上界。逐 ID 内部存活和精确终止原因
仍为 Unknown。**没有修改
前端算法、重跑后端或新增正例**。仅修记账不能解除同一 ID 的 donor/horizon 续传
限制；另开续传策略需要独立授权与冻结，不绕过现有 `NO_EXPANSION`。

此前检查点 `EXP-20260906-010`（VINS initialization-state interface
audit）：后端没有显式 `initialized` topic/service，但第一条私有
`/vins_estimator/odometry` 只会在内部进入 `NON_LINEAR` 后发布，因此是可在线
观察的单向 post-init 边沿。当前前端先离线生成 feature bag，不能消费这个反馈；
该事件无法回溯改变初始化输入。后端随后仍继续优化，因此“以后也无法修正尺度”
超出了当前证据；详见下方结论边界补充。

此前实验 `EXP-20260906-009`（protected pre-refill slot v1）在六个
outcome-known 开发窗口上测试一个最小机制：保留所有已经存活的 KLT/GFTT
观测，只让学习候选与“本帧即将新生的 GFTT”竞争 350 预算。

冻结结论是 **`NO_EXPANSION`**：保护成熟/延续轨迹仍不足以保证 no-harm。
A09/XFeat 保留了强收敛正例，但 A02 两个学习臂仍进入错误尺度分支，Bus 的旧正例
变为精确 TIE。不能据此声称 AQUA-FE 总体优于 KLT 或同后端现代学习前端，也没有
启动 12 个新窗口验证。

- 前端：18/18 PASS，9/9 结构检查 PASS。
- 动作：4/12 学习臂—窗口有动作；14 条 lineage、21 个学习观测；只省略 21 个
  age-1 GFTT，carried 观测逐字段损失为 0。
- 零动作：8/12 学习臂整 bag 与 fresh KLT 字节一致，仅映射为 TIE。
- matched control：4/4 同 ID/同帧/同剂量 GFTT/LK 控制 PASS。
- 后端：24/24 新 replay PASS；18/18 KLT replay 经精确身份复用，不算独立运行。
- common support：4/4 PASS；fixed-scale proper SE(3) 为主，Sim(3) 仅诊断尺度。
- active 分母：`1 WIN / 1 TIE / 2 LOSS / 0 FAIL`；完整 12 臂分母：
  `1 WIN / 9 TIE / 2 LOSS / 0 FAIL`。

参考轨迹是 COLMAP/proxy，只表示与 proxy 的一致程度，不是独立 GT 绝对误差。
三次 solver replay 是技术重复，不是独立科学样本。

## 六窗口 × 两学习臂

| 物理窗口 | protected XFeat | protected SP+LG | 说明 |
|---|---:|---:|---|
| A09 6000–6800 | WIN | exact TIE | XFeat 3 个连续观测恢复尺度收敛 |
| A02 0–900 | LOSS | LOSS | 各改 8 个 newborn，均进入错误尺度分支 |
| AFRL Bus s180 d45 | active exact TIE | exact TIE | XFeat 两个单帧观测对轨迹无影响 |
| A08 2700–3600 | exact TIE | exact TIE | 零动作、bag 等于 KLT |
| AFRL Cemetery s135 d45 | exact TIE | exact TIE | 零动作、bag 等于 KLT |
| Harbor H07 0–1000 | exact TIE | exact TIE | 零动作、bag 等于 KLT |

## 主要绝对结果

下表为三次技术重复中位数，APE/RPE 单位为米；每行 K/L/C 分别是 KLT、
learned、matched classical。

| active 窗口 / 臂 | fixed APE K / L / C | fixed RPE K / L / C | Sim(3) scale K / L / C |
|---|---:|---:|---:|
| A09 / XFeat | 1242.140 / 0.733 / 1.082 | 150.847 / 0.0736 / 0.1169 | 0.00147 / 0.753 / 0.673 |
| A02 / XFeat | 0.141 / 1.094 / 1.094 | 0.0227 / 0.1046 / 0.1046 | 0.899 / 0.509 / 0.509 |
| A02 / SP+LG | 0.141 / 1.130 / 1.134 | 0.0227 / 0.1043 / 0.1048 | 0.899 / 0.501 / 0.500 |
| Bus / XFeat | 0.0601 / 0.0601 / 0.0601 | 0.0372 / 0.0372 / 0.0372 | 0.956 / 0.956 / 0.956 |

共同支撑为 38–42 poses、37–41 秒、93.3%–95.0% coverage、37–41 个严格
1 秒 RPE pairs；evo 独立交叉验证最大差小于 `5e-7 m`。

## 为什么得到这个结论

1. A02 中所有 carried 观测都和 KLT 一样，只改变了 8 个 newborn；结果仍从
   KLT 的 Sim(3) 拟合 scale≈0.899 变为 learned/matched≈0.50，并出现固定尺度
   误差大幅增长。这支持启动期新生观测干预会影响尺度一致性；拟合 scale 并非
   直接读取的后端初始化变量，具体内部收敛分支仍含推断。
2. A02 的 learned 与 matched GFTT 几乎相同（差小于 0.5%），说明这里主要是
   新生观测调度效应，不是 XFeat/SP+LG 内容本身。
3. A09 的 XFeat 不仅击败发散的 KLT，还比同剂量 matched GFTT 的 fixed APE/RPE
   低 32.31%/37.10%。这支持“这个窗口中 XFeat 内容有额外作用”，但样本只有一个
   开发窗口，不能外推为总体优势。
4. Bus 两个单帧 XFeat 观测和 matched control 都产生与 KLT 完全相同的后端轨迹，
   因而旧 v2 Bus 收益依赖原 donor/newborn 干预组合，不是这两个孤立观测本身。

## 完成、未完成与 Unknown

已完成：前端矩阵、matched controls、后端三重复、runability、all-nine common
support、fixed/Sim(3) 与 evo、配置/二进制身份审计、178 项哈希清单。

未完成且 **Not evaluated**：12 个新窗口、sequence-held-out 结果、数据集总体正例率、
实时初始化反馈下的学习候选价值、实时 ROS 传输延迟、运行时/FPS。
delayed-v3 已测试固定初始化保护前缀，但实时反馈版本尚未测试。

仍为 **Unknown**：后端逐 ID 是否实际进入残差；独立 GT 下的绝对误差。

本阶段唯一决策：保持 `NO_EXPANSION` 和 `DO_NOT_IMPLEMENT_POST_INIT_VARIANT`。
测试过的 delayed-v3 未保留 A09 收敛正例，protected-prefill 仍有两项严重回归；
按冻结停止规则，本轮不再运行 slot、顺序或时机变体。这不构成“所有初始化后方法
均不可能有效”的证明，后续尺度恢复能力仍需独立证据。

## 仓库内可读证据

- [预算/续传诊断补充](../papers/frontend_coverage_monotone_router_v2/budget_continuation_addendum.md)、
  [46 行逐帧/逐 ID 紧凑证据](../papers/frontend_coverage_monotone_router_v2/budget_continuation_audit_20260906.csv)、
  [可复查分析脚本](../scripts/audit_frontend_v2_budget_continuation.py)、
  [冻结源码行为测试](../tests/test_v2_budget_continuation_characterization.py)
- [结论边界补充](../papers/frontend_init_state_interface_audit/claim_boundary_addendum.md)
- [初始化状态接口审计](../papers/frontend_init_state_interface_audit/report.md)、
  [接口表](../papers/frontend_init_state_interface_audit/interface_audit.csv)、
  [决策](../papers/frontend_init_state_interface_audit/decision.json)
- [本轮完整报告](../papers/frontend_protected_prefill_slot_v1/report.md)
- [预注册协议](../papers/frontend_protected_prefill_slot_v1/preregistration.md)、
  [前端决策](../papers/frontend_protected_prefill_slot_v1/decision.json)、
  [冻结后端决策](../papers/frontend_protected_prefill_slot_v1/backend_decision.json)
- [完整 12 臂结果](../papers/frontend_protected_prefill_slot_v1/development_outcomes.csv)、
  [主精度表](../papers/frontend_protected_prefill_slot_v1/accuracy.csv)、
  [逐重复精度](../papers/frontend_protected_prefill_slot_v1/accuracy_repeats.csv)
- [前端动作审计](../papers/frontend_protected_prefill_slot_v1/action_audit.csv)、
  [matched control 审计](../papers/frontend_protected_prefill_slot_v1/matched_control_audit.csv)、
  [common support 审计](../papers/frontend_protected_prefill_slot_v1/common_support_status.csv)
- [逐 replay runability](../papers/frontend_protected_prefill_slot_v1/backend_results_repeats.csv)、
  [臂级 runability](../papers/frontend_protected_prefill_slot_v1/runability.csv)、
  [后端配置审计](../papers/frontend_protected_prefill_slot_v1/backend_config_audit.csv)
- [v2 与本机制对照](../papers/frontend_protected_prefill_slot_v1/v2_vs_prefill_mechanism.csv)、
  [完整哈希清单](../papers/frontend_protected_prefill_slot_v1/artifacts.sha256)
- [此前 delayed-v3 报告](../papers/frontend_delayed_newborn_slot_v3/report.md)、
  [v2 后端报告](../papers/frontend_coverage_monotone_router_v2/backend_completion_report.md)、
  [A09/Bus 删除归因](../papers/frontend_v2_positive_delete_diagnostic/report.md)

## 源码、配置与数据身份

实验运行时基线为 `main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加冻结
工作树文件；后来的报告发布 commit 不能冒充运行时源码 commit。

- exporter SHA-256：`e20bc39f...9e17`
- profile/env SHA-256：`665c96a4...1e615`
- method lock SHA-256：`a66e67b7...e8a7`
- backend plan SHA-256：`f1a40ee0...3612`
- VINS node/library：`4e91d8ac...f4278` / `373a598c...71e8`

原始 bag、数据集、模型、缓存和完整控制台日志未上传。`artifacts.sha256` 使用
`repo:`、`prefill_runtime:`、`v2_runtime:` 逻辑根记录本地输入、feature bag、
`vio.csv`、`vins.log` 和 receipts 的身份；GitHub 只包含小型报告、表格、协议、
必要脚本和 compact common-support/matched-control 证据。
