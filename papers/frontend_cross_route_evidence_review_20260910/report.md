# 跨分支证据核对：停止重复试错，先解决归因边界

更新时间：2026-09-10T00:21:00+08:00。状态：COMPLETE / READ_ONLY_REVIEW。
本轮新增前端运行 **0**、后端回放 **0**、方法版本 **0**、验证窗口 **0**。
这是对六个已提交证据包的核对，不是新实验或跨合同合并统计。

## 当前能下的结论

**Confirmed fact.** 主线 A02 的八个注册观测联合删除足以致害；此前已记录初始化尺度符号拒绝路径变化。
独立 guard 阻止该删除，但六开发窗的12个学习臂输入全部退回KLT，A09/Bus收益一起消失。
因此“危险操作已被防护”成立，“兼顾收益的算法修复完成”不成立。
原续传结果仍为2 WIN /8 TIE /2 LOSS /0 FAIL，不能用回退后的12 TIE替换历史。

**Confirmed fact.** 其他独立分支已经测试“增加剂量”“来源中性质量映射”“学习引导KLT恢复”；
各冻结实现均未通过其净收益/增量门。不能把这些再当作尚未验证的简单修复建议。
这不是对所有学习前端的普遍否定，也不是与SP+LG的新增有效排名。

## 已有结果，严格分开合同

| 证据包 | 既有执行量与完整分母 | 原协议结论 | 不能外推为 |
|---|---|---|---|
| [主线安全防护][guard] | 6个A02数值诊断replay；六开发窗×两学习臂的12个既有输入流检查 | 0学习发布；0 WIN /12 TIE /0 LOSS /0 FAIL；18条旧KLT回放映射36个位置，不是新增36次 | 保留收益的no-harm学习方法 |
| [添加式剂量][additive] | 六开发窗×四臂×三重复=72次正式replay | L-all/KLT：0实用收益、3实用损失、3小变化或不确定；C-all/KLT：2/0/4 | “学习点越多越好”或学习来源必需 |
| [质量映射][quality] | A02/A08×三臂×三重复=18次 | 中性q相对原q，2窗均无实用改善；A02中性q相对KLT仍严重退化 | 已修复来源权重问题或验证安全 |
| [原点KLT恢复][recovery] | 48个受控图像对；A02/A08/H02各200 raw帧三臂流；后端0 | 合成真值下L正确恢复835，传统重试C为2488；自然同B失败事件L-only为0；前端增量门未过 | 后端已验证失败，或已验证定位收益 |
| [传统补点扩展][classical] | Batch A：12物理窗、72次replay | 3实用收益 /2实用损失 /6小变化或不确定 /1不可评估；严重回归2，触发停止 | AQUA-FE学习正例率25%，或天然无害 |
| [观测效用审计][utility] | 原六窗只读分析；另6次工程A/A验证，正式诊断0/27 | 3对A/A全部未过原容差；具体数值异常根因仍Unknown | 日志增加无影响，或初始化内部诊断已经有效 |

表中计数来自各自协议及提交内结果，不是本轮新跑。重复回放不是独立窗口。
添加式、质量映射、传统扩展使用容量1000的独立只读诊断后端，允许总观测数超过350；
它们**不能混入主线350预算、原固定二进制的同后端隔离表**。
即使几项指标同为fixed-scale APE/RPE，其共同支撑、输入合同和胜负门也不同，不能拼接绝对误差作排名。

传统扩展的3个实用正例是A04/A07/H02，2个严重负例是A01/A03。
A05为参考共同位姿27<30，非后端未运行；仍保留在12窗分母。
另一批12窗已预列但NOT_ACTIVATED，不计成已跑；清单共24行不能误写24个验证窗。
这批只相对原C-all六窗作序列留出；其中7/12与更早项目窗口有重叠。
它不是本项目全新未见数据，也不是完整数据集自然正例率。[完整清单][classical-csv]

## 对“恶化原因”的收敛解释

1. **主线已确认的危险操作：删改基线观测。**
   年轻点也可能是后续多帧初始化轨迹的出生观测。donor377只缺一次，随后同ID返回；
   不是删掉104帧。A02八点联合删除充分，不证明某一个donor独立致因。
2. **保留全部KLT，也不自动保证后端无害。**
   添加式分支不删除KLT，仍有学习臂严重退化；传统扩展也有2个严重负例。
   这支持否定“只要保留基线观测就天然安全”的普遍推论，不把不同实验的负例归为同一原因。
3. **剂量、发布长链和进入残差，不等于有用。**
   添加式六窗剂量对照均充分，已记录实际残差使用；L-all相对L6仅A08有实用改善，
   但相对KLT无实用收益。几何/寿命代理能帮助定位问题，不能代替后端效果。
4. **数值稳定性仍是下一项归因风险。**
   观测效用A/A中A08的冻结版B最大位置范数约283235.52m，诊断版约3.67m；
   这不是APE，且两版二进制不同，不能将差异直接归因日志。
   质量映射实验的另三次A08 B APE为0.560903/0.060390/0.061873m，
   显示基线技术波动必须保留，不能选较好重放代替历史。
   上述A/A新增内部状态被原门禁用；本轮没有解禁。[A/A记录][aa-csv]、[位置范数工程表][engineering-csv]

**Hypothesis / Inference.** 优先核查同一冻结B输入与二进制的回放差异，比再增加候选或调q更能缩小归因不确定性。
solver时间预算、主机负载、依赖/构建身份和数值路径是待区分因素；本轮未确认其中任何一个为根因。
原A09/Bus的delete-only没有复现收益，候选加入有作用，但matched GFTT也有效；
现有证据仍不足以建立统一的“学习持久锚点决定收敛”因果解释。

## 唯一后续决策

维持主线SAFE_FALLBACK_ONLY / NO_EXPANSION；不合并其他方法代码，不重开已停止的参数/剂量/替换路线。
下一项建议限定为 **A08冻结B的回放身份与稳定性诊断**，先只读既有receipt、依赖、输入时序及solver日志。
如现有记录不能区分原因，再另行冻结一个有限工程对照；不恢复原已停止的27次矩阵，
不改VINS数学/solver预算，不改历史门，不把工程异常重放当成新正例。
本轮该进一步归因及保留正例的修复均为 **Not evaluated.**，不是已启动的后台任务。

主线新窗口扩展仍为0个已完成/12个建议名额，尚未形成并执行新清单；
其他分支的12个C-all窗口不能替主线填这个分母。没有新学习正例、没有方法晋升。
所有VIO参考为COLMAP/proxy而非独立GT，fixed-scale proper SE(3)是主口径，
Sim(3)仅显式诊断；实际loop_closure=0，不作回环检测改善声明。

## 复查与公开身份

[source_inventory.csv](source_inventory.csv)列出6个证据包各4份文件：
报告、decision、协议、紧凑CSV，共24份；记录精确commit、SHA-256和公开URL。
2026-09-10T00:18:26+08:00从GitHub raw端逐字节读回，**24/24与本地提交对象一致**。
这只验证公开内容一致，不等于本轮重新验证原始bag/全部环境/所有实验。
本轮只复核提交中的分类计数，不重新拟合轨迹，不复制/覆盖其他工作区产物。
引用的commit是各包证据快照，**不一概等于实验源码commit**；实验运行源码与配置/补丁身份仍见各包原协议、manifest和receipt。
本次索引发布commit由最终push回执提供，避免自引用。原始数据、bag、权重与完整日志不上传。

[guard]: https://github.com/CharlesLeeby/AQUA-FE/blob/4a23a49e73969b90cfa3d0a8bae173330147a16b/papers/frontend_a02_init_trace_repair_v1/report.md
[additive]: https://github.com/CharlesLeeby/AQUA-FE/blob/49c02471716e8ac960e35dd9dd44ef6fbb1428c6/papers/frontend_additive_budget_v1/report.md
[quality]: https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/papers/frontend_source_neutral_quality_v1/report.md
[recovery]: https://github.com/CharlesLeeby/AQUA-FE/blob/3bd6cc62a81edf2bb12e377a201499ebc8e62c11/papers/frontend_learned_klt_recovery_v1/report.md
[classical]: https://github.com/CharlesLeeby/AQUA-FE/blob/9c1c8c2363708e3d95a6850fc9591356e0f1f30e/papers/frontend_classical_opportunity_expansion_v1/report.md
[classical-csv]: https://github.com/CharlesLeeby/AQUA-FE/blob/9c1c8c2363708e3d95a6850fc9591356e0f1f30e/papers/frontend_classical_opportunity_expansion_v1/window_outcomes.csv
[utility]: https://github.com/CharlesLeeby/AQUA-FE/blob/90646d6a12f0cdde257ff5b7efa3166daa32dc12/papers/frontend_observation_utility_audit_v1/report.md
[aa-csv]: https://github.com/CharlesLeeby/AQUA-FE/blob/90646d6a12f0cdde257ff5b7efa3166daa32dc12/papers/frontend_observation_utility_audit_v1/diagnostic_aa.csv
[engineering-csv]: https://github.com/CharlesLeeby/AQUA-FE/blob/90646d6a12f0cdde257ff5b7efa3166daa32dc12/papers/frontend_observation_utility_audit_v1/diagnostic_engineering_results.csv
