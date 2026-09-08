# Classical opportunity expansion v1 独立交接

状态：**COMPLETE**，2026-09-08。本轮所有已授权实验、完整案例整理和最终报告已完成。最终科学决策 `ADDITIVE_OPPORTUNITY_NOT_GENERALIZED`，扩展状态 `EXPANSION_STOPPED_AFTER_BATCH_A`。

本轮基于 `49c02471716e8ac960e35dd9dd44ef6fbb1428c6`，独立工作树 `/home/ma/AQUA-FE_WS_classical_opportunity_expansion_v1`，分支 `exp/classical-opportunity-expansion-v1-20260908`。原主工作树、外部 VINS 源码/二进制以及旧论文实验目录均未修改。旧 continuation NO_EXPANSION、旧 additive C/B 2/0/4 和 L/B 0/3/3 结论保持不变。

**Confirmed fact.** Batch A 12 个新物理窗口、72 次正式回放全部完成。3 practical gain（A04/A07/H02，均 robust）、2 practical loss（A01/A03，均 severe）、6 small/uncertain、0 FAIL、1 NOT_EVALUABLE（A05 的 common poses=27<30）。正例跨三条序列，但严重退化超过冻结的 <=1 条件，故没有运行 Batch B；其另外 12 个冻结窗为 NOT_ACTIVATED / Not evaluated.。没有第四次重复、learned 扩展臂或结果驱动换窗。

全部 A 窗为相应序列 raw `[0,900)`，相对旧六个 C-all 开发窗为 12 sequence-held-out/0 window-held-out。更广历史有 7/12 与已检查旧区间重叠；未发现重叠不等于全局从未使用。全部现已 outcome-known，供未来机制设计时属于开发案例，不能充当该未来机制的独立确认集。

最终审计 PASS：1,656 个唯一产物哈希、72 次回放身份/配置/逐 ID 接收、全部有效窗口评价和分类均一致；最大 actual eligible 644<1000；最大 evo 差 4.9937014e-7 m<1e-6 m。运行 PASS 与零 reset/failure 代理不等于绝对数值可靠；A03、A04 基线、A06、H03 异常详见报告。

最先阅读：

- [完整报告](../papers/frontend_classical_opportunity_expansion_v1/report.md)：首屏回答全部 11 个问题，完整 min/median/max、A02/Bus 对照及解释边界。
- [案例表](../papers/frontend_classical_opportunity_expansion_v1/case_registry.csv)及[逐窗解释](../papers/frontend_classical_opportunity_expansion_v1/case_interpretation.csv)。
- [机制交接](../papers/frontend_classical_opportunity_expansion_v1/case_mechanism_handoff.md)：联合 ID 键、各字段语义、异常案例和下一步边界。
- [决策](../papers/frontend_classical_opportunity_expansion_v1/decision.json)、[冻结 Batch A 快照](../papers/frontend_classical_opportunity_expansion_v1/checkpoint_batch_A/)、[最终审计](../papers/frontend_classical_opportunity_expansion_v1/final_integrity_audit.json)。
- [分析包](../papers/frontend_classical_opportunity_expansion_v1/analysis-output/analysis-report.md)：2 张 PNG/SVG 图、精确数值表、统计附录、输入 provenance。

可复现入口与运行根：

- 方法执行锁、原始 roster 和 preregistration 位于 `papers/frontend_classical_opportunity_expansion_v1/`。窗口冻结 `881dad7`、方法锁 `8f323ba`、完整 Batch A 检查点 `853cdd6011f9d3a73cfbd84e580d121530cbecdb` 均正常推送并远端回读。最终发布另有 runtime 读回收据。
- 本地根 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1`；原始输入/输出 bag、源流和大日志留在本地。Git 只交付必要收据和适量派生 CSV/图表。
- 控制器已经正常退出；专用 ROS master 12691，任务节点随回放清理。不应重启 `classical_opportunity_py38.py --batch A` 或运行 Batch B。已完成最终化目录有防覆盖检查，不要反复执行脚本。
- Python 3.8 兼容适配、旧 wrapper 路径映射和有限前缀等价探针见 execution_notes；早期失败/初版图表均保留。脚本只做执行兼容与报告，没有改变 C-all、后端或评价合同。

唯一下一步为 observation-utility / risk mechanism research。停止把 additive observation 作为主要研究假设继续扩展；保留局部机会和严重负例，并为新机制另行预注册独立验证。不得把窗口集合级正负标签传播为每个 candidate 的 utility；COLMAP/proxy 不是独立 GT，总体自然正例率和因果机制 Not evaluated.。


## 2026-09-08 — 角色收缩：已有候选方法的快速跨案例验证

本段覆盖上文关于本窗口继续机制研究的后续安排。Classical expansion 以9c1c8c2封口，ADDITIVE_OPPORTUNITY_NOT_GENERALIZED / EXPANSION_STOPPED_AFTER_BATCH_A及全部旧分母不变；无Batch B、C-all调参或重复机制审计。

检查固定候选发布 `6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f`（source-neutral-quality-v1，源码 `94e59f5598580eb72f7588d776fdce12d529130f`）：上游结论 SOURCE_MAPPING_NOT_MAIN_EXPLANATION，A02/A08无超过KLT的实用净收益，A02有严重退化。故本次 **CANDIDATE_NOT_READY**，新回放0、复用0，固定H02/A01均Not evaluated.。不重造映射、不启动后端、不轮询。

本窗口保留 **READY_FOR_CANDIDATE** 角色，仅接收另一个窗口正式发布且满足净收益进入条件的候选；之后才按固定H02/A01、三个臂、最多18次上限冻结执行。当前执行到此结束，后续交回主规划窗口。独立分支 `exp/fast-cross-case-validation-v1-20260908`。

[简短报告](../papers/frontend_fast_cross_case_validation_v1/source_neutral_quality_v1/report.md) · [比较状态](../papers/frontend_fast_cross_case_validation_v1/source_neutral_quality_v1/comparison.csv) · [上游固定交接](https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/docs/CODEX_HANDOFF_FAST_LEARNED_TEST.md)。
