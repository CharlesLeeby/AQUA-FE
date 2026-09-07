# Observation-utility / risk 案例交接 — COMPLETE

2026-09-08。固定 C-all 扩展已结束，12 新窗口 / 72 正式 replay。3 PRACTICAL_GAIN（均 ROBUST）、2 PRACTICAL_LOSS（均 severe）、6 SMALL_OR_UNCERTAIN、0 FAIL、1 NOT_EVALUABLE。最终 `ADDITIVE_OPPORTUNITY_NOT_GENERALIZED`，`EXPANSION_STOPPED_AFTER_BATCH_A`；冻结 Batch B 的 12 窗为 NOT_ACTIVATED，不再启动。

本交接只提供集合级案例。正例不是逐 candidate 正标签，负例不是逐 candidate 负标签。本轮新窗口只相对旧六个 C-all 开发窗 held-out；7 个 A 窗与已检查的更广项目旧区间重叠。现在全部已 outcome-known，任何利用这些结果设计的新机制须将其作为开发案例，另行冻结独立确认材料。

| 角色 | 案例 | 研究价值及证据边界 |
|---|---|---|
| 稳定实用正例 | A04 / A07 / H02 | A04 为异常基线被改善；A07 较高误差基线改善；H02 中等误差基线稳定获益。三者初始化延迟差方向并不相同。 |
| 严重负例 | A01 / A03 | A01 较长寿命仍退化；A03 三次 C 数值均严重异常，单一首姿态延迟或 misalignment 计数不能排除风险。 |
| 稳定小变化 | A10 / H01 / H04 / H05 | 非零发布及后端接收，不应归因为零作用量；A10 APE/RPE 方向存在折衷。 |
| 技术重复与基线异常 | A06 / H03 | A06 中位数改善不足以超过 B range；H03 两个 C 异常、一个良好，同一 bag 下残差使用分化。 |
| 参考边界 | A05 | common poses 27<30，精度 Not evaluated.；仍保留全部前后端观测和时序。 |

数值主表为 [case_registry.csv](case_registry.csv)，逐窗文字解释为 [case_interpretation.csv](case_interpretation.csv)，结果列表为 [positive](positive_cases.csv)、[neutral](neutral_cases.csv)、[negative](negative_cases.csv)、[failure/reference-limited](failure_cases.csv)。每窗 ID 为 `coe1_<sequence>_00000_00900`，raw 索引 `[0,900)`，均 B×3/C-all×3、固定尺度 SE(3) APE 和 strict 1 s RPE、自身六轨支撑；完整 min/median/max 及尺度诊断在主表。

使用数据时遵循这些字段定义：

- `candidate_lifecycle.csv` 是公开 ID 的紧凑观测链，联合键 **window_id + public_id**；ID 每窗重新开始，不能只按 public_id 跨窗连接。`public_observations` 与 `observed_span_s` 分别为观测计数及时间跨度，受窗口与准入截断；private termination 原因 Unknown。
- 原始事件和源观测在本地 `frontend/<slug>/candidate_lifecycle.csv`、`classical_gftt_source.jsonl`，后端逐 ID 收据与残差记录在 `backend/<slug>/{B,C-all}/repeat{1,2,3}/`；根为 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1`。
- `received_candidate`、unique IDs、eligible IDs、residual blocks 区分发布、接收、可用和求解使用；残差块会在优化调用间重复，不能当独立观测量。全部实际后端逐 ID 接收通过，最大 actual eligible 644<1000。
- `B_feature_coverage_median` / `C_feature_coverage_median` 是逐输出消息 **4×6 网格占用比例**的中位数；不是轨迹 coverage，也不是像素纹理分数。该网格只用于描述，不是 C 选择规则。
- `*_first_pose_delay_from_raw_start_s` 是传感器首姿态相对 raw 起点；`*_first_pose_delay_from_reference_start_s` 以参考起点计。`*_initialization_ROS_clock_delay_from_raw_start_s` 来源于初始化日志的 ROS clock，与传感器姿态时间分开解释。A05 参考晚起使 reference-relative 值为负，raw-relative 约 1.351 s。
- `reference_span_s` 与 `raw_image_span_s` 分开使用；继承字段 `raw_reference_span_s` 实际含 roster image span，已在主表显式注释。`support_*` 是自身六轨交集的评价支撑。A05 100% 只覆盖短参考网格。
- `reset_count_proxy` / `failure_detection_count` 是日志代理，均为零不能排除数值发散；真实 lost-tracking 计数 Unknown。单 C 重复相对 B 中位数的 severe-margin 标志是冻结描述，不改窗口分类。

[完整中文报告](report.md)与[严格分析包](analysis-output/analysis-report.md)先于机制解释。`final_integrity_audit.json` PASS，1,656 个哈希无不一致，72 次回放身份/接收及有效评价一致。COLMAP/proxy 不是独立 GT；跨总体有效性和个体 candidate utility 均 Not evaluated.。

唯一研究后继是 observation-utility / risk mechanism research：检查现有正负案例中的观测效用、危险初始化和后端数值风险，再为新机制另行设计验证。停止把 additive observation 作为主要研究假设继续扩展；无自动 C-all 调参、补充 learned 臂或替换窗口授权。旧 continuation NO_EXPANSION、additive-budget 结论和受保护 KLT/两-profile 解释保持原样。
