# AQUA-FE 添加式配额实验独立交接

2026-09-08；状态：COMPLETE。本轮已结束，没有新增窗口、预算档位或时机变体。

取消6条并发配额确实增加了实际剂量，但仅A08相对L6达到实用改善；六窗L-all相对完整B均无实用改善，其中A09/A02/A08三窗实用退化。

| 对比 | 实用改善 | 实用退化 | 小幅或不确定 |
|---|---:|---:|---:|
| L-all/L6 | 1 | 0 | 5 |
| L6/B | 0 | 3 | 3 |
| L-all/B | 0 | 3 | 3 |
| C-all/B | 2 | 0 | 4 |
| L-all/C-all | 0 | 3 | 3 |

C-all的改善窗口为A02、Bus。Bus L-all首重复在数量对比支撑上APE23.252566m，另两次约.043m，异常全部保留；不把中位数下降解释为无风险。A08数量APE改善21.2079%，但L-all仍差于B。

## 完整性与证据边界

- 六物理窗、24前端输出、72次新正式回放；未用旧后端结果替代重复。恢复controller对已完成H07的REUSE_RECEIPT只是哈希核查，未新增或复用为额外样本。
- 全24输入逐消息重建原B、非feature消息一致；L6/L-all共享源ID/精确时间戳/坐标/q，公开速度及重新准入身份读回通过。全72后端逐ID接收量与输入一致。
- 72次最终运行有效性、36组共同支撑和evo交叉核验通过；初始化事件各1次，reset/failure-detection日志代理均0。以上不代表尺度或定位正确。
- 最大实际优化资格834，原1000容量未扩展，未静默裁剪。solver诊断仅覆盖常规非线性优化；初始化SfM用时及确切停止原因Unknown。
- 六窗均达到预注册剂量差门；L-all/L6发布倍率1.92778–48.6853，实际候选残差中位倍率1.44839–45.9306。残差块可跨优化重复，不是独立新增信息。
- all仅对冻结top_k2048、每调用最多60种子、800私有池；A08 XFeat池实际触顶，10672个种子申请因池限制被拒。源原生分数不跨源比较；C/XFeat后端q映射及剂量/成本不同，不能声称等资源来源优越性。
- 开发窗已知历史结果，COLMAP/proxy不是独立GT；技术重复不作独立统计样本；新增观测可改变初始化，不是共享初始化后的纯跟踪因果试验。

## Cemetery结构失败与恢复

原输入raw190/191同stamp但像素不同；原B精确对应冻结every_n2/frame_offset0。首生成误按stamp输出两次，358记录对357个B，身份门拒绝，0次后端使用。无效源和部分bag保存在独立quarantine。

修复在Cemetery后端结果前另行冻结：仅给原runner的输出关联增加已有generate帧索引条件，原冻结runner、门、权重、源池及后端不改。不能简单删源行，因错误记录已影响previous_output；故Cemetery明确有两次源生成尝试，第二份为唯一正式共享流。其余五窗一次，共7尝试，失败额外精确墙钟Unknown而非0。详[恢复合同](../papers/frontend_additive_budget_v1/cemetery_recovery_addendum.md)、[失败哈希](../papers/frontend_additive_budget_v1/cemetery_invalid_attempt.json)。

实际后端窗顺序A09/A02/Bus/A08/H07/Cemetery，用于等待结构恢复；内窗四臂/重复顺序及合同不变。外部任务导致的WAITING_RESOURCE保留，没有停止其他工作区任务。宿主非排他，严格无干扰性能排名Not evaluated.。

## 身份与复现入口

- 任务分支：`exp/additive-budget-v1-20260907`。
- Worktree：`/home/ma/AQUA-FE_WS_additive_budget_v1`；运行根：`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1`。
- 原项目根已核对为`/home/ma/AQUA-FE_WS`；origin为`git@github.com:CharlesLeeby/AQUA-FE.git`。基准已发布证据`b6f11ca`，未合并主分支/证据分支。
- 原源实现：`d1c793a8d56b3f8efe2ed3b3d770b706e692dbdc`及逐文件锁。
- 后端诊断/执行/评估冻结：`2297bb837dac69ff587ec052425539cdd01a17dc`；四臂同一二进制SHA256 `e231871eaff26a757a5d396ef5df0ad4d488d55be1c8d0e8d0f1204d1068aadd`。
- Cemetery恢复overlay：`38e58813f82495e2e8c60a173b55610d401b1c77`及独立恢复锁。
- 报告发布版本为本交接文件所属Git commit，和实验源身份分开。frontend receipt.source_commit是完成时HEAD，源身份以锁哈希为准。

主报告首先包含完整24臂窗表：[report.md](../papers/frontend_additive_budget_v1/report.md)。核心结果：[30项对比](../papers/frontend_additive_budget_v1/comparisons.csv)、[72次结果](../papers/frontend_additive_budget_v1/backend_results.csv)、[三重复范围](../papers/frontend_additive_budget_v1/backend_arm_summary.csv)、[决策](../papers/frontend_additive_budget_v1/decision.json)。

审计：[24输入](../papers/frontend_additive_budget_v1/frontend_audit.csv)、[9756逐帧数量](../papers/frontend_additive_budget_v1/frontend_frame_counts.csv)、[独立读回](../papers/frontend_additive_budget_v1/delivery_readback_audit.csv)、[源供给](../papers/frontend_additive_budget_v1/source_supply.csv)、[完整锁复核](../papers/frontend_additive_budget_v1/frozen_contract_final_verification.json)、[前端receipts](../papers/frontend_additive_budget_v1/frontend_receipts.json)、[后端receipts](../papers/frontend_additive_budget_v1/backend_receipts.json)。

[分析包与两幅图](../papers/frontend_additive_budget_v1/analysis-output/analysis-report.md)、[统计附录](../papers/frontend_additive_budget_v1/analysis-output/stats-appendix.md)、[实现限制](../papers/frontend_additive_budget_v1/implementation_audit_notes.md)给出完整口径。所有bag、模型、缓存、大日志保留本地，未上传。没有遗留本任务待执行队列。

复核脚本从本worktree、ROS Noetic环境及`/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python`运行；`scripts/analyze_additive_budget_v1.py`、`scripts/audit_additive_budget_delivery.py`和`scripts/report_additive_budget_v1.py`只读原运行结果并重建汇总。不要删除正式receipt或重新跑原矩阵来选择更好结果。

## 唯一下一步

用已保存的逐ID、初始化和尺度日志做一次失稳归因审计，重点检查Bus异常重复及A02/A08学习添加退化；不自动扩数量或新增时机变体。
