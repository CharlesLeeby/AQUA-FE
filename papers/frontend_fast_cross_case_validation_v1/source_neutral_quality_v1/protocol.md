# 快速跨案例验证：候选入口检查

状态：**CANDIDATE_NOT_READY**；本次入口检查已结束，执行协议未激活。2026-09-08。

候选只能来自另一窗口的正式发布。本次检查固定发布 `6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f`（分支 `exp/source-neutral-quality-v1-20260908`），源码 `94e59f5598580eb72f7588d776fdce12d529130f`；[交接](https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/docs/CODEX_HANDOFF_FAST_LEARNED_TEST.md)、[候选协议](https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/papers/frontend_source_neutral_quality_v1/protocol.md)、[转换脚本](https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/scripts/convert_source_neutral_quality_v1.py)、[配置与运行计划](https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/papers/frontend_source_neutral_quality_v1/run_plan.json)。唯一改动是同一 XFeat L-all 的候选 quality 及派生 sigma 使用已冻结的通用映射，坐标、ID、时刻、数量、生命周期及 KLT 不变。后端为原 additive capacity-1000 诊断 binary，只读复用，具体身份由上述 run_plan 提供；本窗口未重新核验二进制或执行转换。

进入条件是初步结果存在超过 KLT 的实用净收益，且候选值得扩展。该发布的 decision 为 SOURCE_MAPPING_NOT_MAIN_EXPLANATION，A02/A08 零实用净收益、A02 neutral/B 严重退化，故入口条件不满足。不以仅缓解原学习方案退化作为启动理由。

用户固定后续案例：H02 raw [0,900)（coe1_h02_00000_00900）、A01 raw [0,900)（coe1_a01_00000_00900）。均为 outcome-known 开发回归检查，不是 held-out。输入身份依据 classical expansion 发布 9c1c8c2 的冻结清单和 receipts；本次未进入输入适配/B 复用核验，不转用旧精度作为新三臂结果。

只有合格的正式候选才能激活 B/L-original/L-candidate 三臂、各三技术重复：同窗只生成一次 XFeat 源，唯一差异限于候选冻结字段；B 严格合法复用时新增12次，否则全新18次，绝不超过18次、不加第四次。具体候选/输入/配置/复用身份须在激活前冻结，不能依据聊天重造 q。指标、护栏、实用/严重门槛及后端数学继承候选，不对 H02/A01 调参；原始 KLT 完整、学习两臂坐标/ID/时间/发布量相同，接收和共同支撑有效。数量级异常原样保留，不择优重跑。

若以后完成验证，必须同时比较 candidate/original 与 candidate/B，按用户的 PARTIAL_RECOVERY_NO_NET_GAIN、CANDIDATE_NOT_SUPPORTED 或 PROMISING_CROSS_CASE_DEVELOPMENT 条件结束，不能自动扩大矩阵。本次三者均 **Not evaluated.**，不把未运行窗口记 TIE 或安全。

Classical expansion 的 ADDITIVE_OPPORTUNITY_NOT_GENERALIZED、EXPANSION_STOPPED_AFTER_BATCH_A、完整旧分母均封存。无 Batch B、C-all 重跑/调参、另一套 GFTT/slot/horizon/数量研究或重复 observation-utility/risk 审计。本窗口仅验证已发布候选，不开发候选、不轮询或寻找替代任务。
