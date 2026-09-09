# AQUA-FE 固定交接入口

更新时间：2026-09-10T00:23:00+08:00
发布分支：`codex/aqua-fe-evidence-20260905`（不是 main）

## 9月10日续办：跨分支证据已接入

本轮仅核对已完成证据，**新增前端/后端/版本/窗口均为0**。下文6次A02诊断及防护验证是9月9日已完成结果，未重跑。
[紧凑跨分支报告](../papers/frontend_cross_route_evidence_review_20260910/report.md)与
[24份源文件身份/公开URL](../papers/frontend_cross_route_evidence_review_20260910/source_inventory.csv)
已接入；源文件24/24经GitHub逐字节读回一致。

- 独立添加式学习剂量实验：六窗L-all/KLT为0实用收益、3损失、3小变化或不确定。
- 来源中性q（18次既有replay）及学习引导KLT恢复也未过各自收益/增量门；不再作为“未试的简单修复”。
- 传统补点扩展：12窗3实用收益、2严重损失、6小变化或不确定、1不可评估，已触发停止。
  它不是学习正例率；容量1000的独立诊断合同不能混入主线350预算表。
- 主线仍是安全回退，收益保留修复未完成。下一项唯一建议：先核查既有A08固定B的身份与重放稳定性；
  此进一步诊断未启动，不自动重开替换/调参或已停止的回放矩阵。

## 当前结论

**EXP-20260909-A02-INIT-TRACE：COMPLETE / SAFE_FALLBACK_ONLY / NO_EXPANSION。**

A02 的初始化数值分叉已定位；独立安全防护已实现并验证。
**兼顾“不伤害 A02、保留 A09/Bus 收益”的算法修复尚未完成。**
不能宣称 AQUA-FE 整体优于 KLT/SP+LG。后端算法/YAML/门均未改变，旧负结果未覆盖。
参考为 COLMAP/proxy，不是独立 GT；fixed-scale proper SE(3) 为主，Sim(3) 明确单列。
实际 `loop_closure=0`，这是前端到 VINS 的端到端影响，不是回环检测收益。

## 9月9日已完成实验与机制

- 原 A02 KLT / 八观测 delete-only 各三次：**6/6 新日志诊断回放完成**。
  只开启二进制已有 `VINS_INITIAL_DIAGNOSTICS=1`，没有改源码/重编译。
- 三重复均：KLT 第八次对齐通过，删点组第四次通过；失败原因是线性 scale <0，
  不是重力模长越过 0.5 原门。两组接受后的 refined scale 为 0.033247 / 0.034290。
  不同视觉重建的内部 scale 不能混同最终 proxy 拟合尺度。
- 原八观测联合删除足以致害；之前确认首次 SFM 输入少了三条多帧轨迹的出生观测。
  “只动新点就安全”的解释不成立。不是某一个/三个 donor 的独立充分性证明。
  donor 377 只缺一个观测，之后同 ID 返回，不是删除了104帧。
- 新 guard 保护所有 KLT 的 ID/camera/坐标/通道/顺序，删改或超350就当帧回退，
  本 run 后续保持回退。只用当前/过去信息，不按窗口结果或离线初始化时间做选择。
- **9/9 测试；六开发窗×两学习臂=12/12 既有输入流验证完成**；没有重跑前端网络/跟踪器。
  所有 guarded bag 与 KLT 整文件一致，学习发布0。18条旧KLT回放身份有效，
  映射到36个臂—重复位置，**不是36次新增replay**。修复验证新增后端0次。

## 完整分母与收益代价

| 开发窗口 | 未防护 XFeat / SP+LG | 防护后 XFeat / SP+LG |
|---|---|---|
| A09 6000–6800 | WIN / TIE | TIE / TIE，原救回收益消失 |
| A02 0–900 | LOSS / LOSS | TIE / TIE，阻断原恶化操作 |
| Bus s180 d45 | WIN / TIE | TIE / TIE，原收益消失 |
| A08 2700–3600 | TIE / TIE | TIE / TIE |
| Cemetery s135 d45 | TIE / TIE | TIE / TIE |
| H07 0–1000 | TIE / TIE | TIE / TIE |

原续传开发版：24次新增后端+18次KLT复用；**2 WIN /8 TIE /2 LOSS /0 FAIL**。
guard 后：**0 WIN /12 TIE /0 LOSS /0 FAIL**，动作物理窗口0/6。
这只是安全回退，不是学习改进；KLT在A09发散，回退也会发散。
原研究入口保留不变，不会自动受新guard保护；不要把旧替换臂称安全版。

9月9日A02日志诊断（3次中位数；fixed APE /1s RPE，m）：
KLT **0.140174 /0.022646**；仅删点 **1.104454 /0.104535**。
APE范围分别0.102585–0.161920、1.082646–1.115142，不能声称日志回放精确复刻旧轨迹。
6/6初始化/覆盖通过，覆盖93.34%/95.33%；新6条+旧6条共同支撑42poses/41s/41RPE对，
evo差<4.88e-7m。原KLT/delete同网格中位APE为0.141317/1.073158。
原续传XFeat固定APE：A09 0.641290、A02 0.979235、Bus 0.042794；
对应KLT 1242.140/0.141317/0.060109，guard后按身份映射回KLT。

## Unknown、未完成与唯一决策

Unknown：逐ID真实残差使用、单donor/三观测子集充分性、偏置失败回滚的独立影响，
完整SFM/PNP状态如何演变。记录的尺度符号拒绝已不再Unknown。
原A09/Bus只删点不能复现收益；加点有作用，但matched GFTT也能改善，
因此不能证明learned必需。

**未完成：保留正例的无害增强方法；新窗口验证0/12；没有新增物理正例。**
六窗都是开发数据，不能据此估计整个数据集自然正例率。
唯一决策：安全使用独立防护/不删点基线，停止把此启动期替换路线作为已验证增强；
不扩大窗口、不自动试第二个变体。

## 可直接读取的完整证据与身份

- [本轮报告](../papers/frontend_a02_init_trace_repair_v1/report.md)、
  [每次初始化数值](../papers/frontend_a02_init_trace_repair_v1/initialization_attempts.csv)、
  [逐次运行/覆盖](../papers/frontend_a02_init_trace_repair_v1/replay_results.csv)、
  [误差及范围](../papers/frontend_a02_init_trace_repair_v1/accuracy.csv)。
- [诊断协议](../papers/frontend_a02_init_trace_repair_v1/preregistration.md)、
  [原输入回放清单](../papers/frontend_a02_init_trace_repair_v1/replay_manifest.json)、
  [修复合同](../papers/frontend_a02_init_trace_repair_v1/repair_contract.md)、
  [方法/输入锁](../papers/frontend_a02_init_trace_repair_v1/repair_lock.json)、
  [12项防护结果](../papers/frontend_a02_init_trace_repair_v1/guard_results.csv)、
  [决策](../papers/frontend_a02_init_trace_repair_v1/decision.json)、
  [SHA清单](../papers/frontend_a02_init_trace_repair_v1/artifacts.sha256)。
- [此前续传完整报告](../papers/frontend_admission_continuation_v1/report.md)、
  [此前恶化定位](../papers/frontend_admission_continuation_v1/a02_degradation_mechanism.md)、
  [原v2后端报告](../papers/frontend_coverage_monotone_router_v2/backend_completion_report.md)、
  [A02删除充分性](../papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/report.md)、
  [A09/Bus删除对照](../papers/frontend_v2_positive_delete_diagnostic/report.md)。

实验源码基底：`main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加 manifest/repair lock
内精确文件SHA；报告发布commit另由推送回执给出，不冒充运行身份。
原始bag、模型、完整日志/环境留本地，公开的是实际报告/CSV/必要代码及数据引用，
不是只有哈希；未写锁定/mnt/data或其他研究工作区。
