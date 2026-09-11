# 用户授权：SEA-RAFT 系统增量离线开发试验

2026-09-11。继续 AQUA-FE，优先总体系统成果，不再把92点人工标注作为前置条件。本轮是有限的“传统恢复之后，SEA-RAFT是否提供系统增量”实验，不是重判旧筛选通过，也不用于真实机器人部署。

现有点选工具、92点清单、预测和报告全部保留，不再扩展页面、要求现在标完或重做旧图像对研究。旧 CONTROLLED_GAIN_ONLY、EVIDENCE_GATE_NOT_SUPPORTED、REFERENCE_PENDING 不变。不能把 Unknown 伪装为正确观测。

仓库 https://github.com/CharlesLeeby/AQUA-FE 。复用现有 KLT、31/4强LK、a2f3bed模型设置、4d061b8固定patch检查、feature导出、固定VINS和评价流程。新隔离分支及 papers/frontend_searaft_system_probe_v1，不修改其他工作区。只做B原KLT、C原KLT+强LK、R在C之后仅恢复剩余当帧失败的原轨迹。不训练、不换权重、不调q、不增加新点来源，不扫描帧间隔/NCC/预算/时机。

普通KLT成功和强LK成功观测不改。SEA-RAFT直接预测原点，原有限值、FB≤1原px、边界、11×11 NCC≥.65及原低方差/patch有效性语义不降低；不以预测替代图像支撑。仅同一处理帧、正式丢弃前恢复同ID，不复活已公开断链ID、不倒填。之后正常跟踪，真实失效结束。先留有效旧轨迹再补GFTT，总上限350。恢复改变未来补点集合，必须报告，不称整段与纯KLT相同或天然无害。沿用恢复路径可靠度，不给学习额外高权重。同帧失败点共享一次正反网络；可复用合法旧缓存，完整窗口缺少的预测允许新增，不冒称旧12对覆盖完整窗口。

固定 H02 raw[0,900)、A02 raw[0,900)，准确输入/相机/IMU/时间从既有manifest取；原相邻raw帧，不用t+10。已知开发窗，不称held-out。先结构检查和前端导出，确认R/C新增恢复、公开持续、ID/坐标/时间/350容量及接收使用诊断边界。R/C整段feature及配置相同则映射，不重复replay、不称学习贡献。否则B/C/R每臂三次，最多18次正式后端；只有完整合同适配可复用基线，不混二进制或不同支撑。已有冻结后端不重编译、不做新A/A框架。

新后端结果前冻结一页协议的主指标、实用幅度、重复范围、失败和严重退化护栏。沿用fixed-scale SE(3) APE、严格1秒RPE、共同支撑和COLMAP/proxy限制。保留全部重复/失败/异常，不挑最佳。必须回答R/B净收益及R/C学习增量；恢复数、轨迹长度、像素分数只作解释。无需先有92点人工GT；轨迹变好不等于每个恢复点正确。包括初始化影响，不称纯运行期机制隔离。基线严重不可解释异常须保留并限制结论，不反复重跑。

一次固定小矩阵后停止：无R/C实际输入差异 NO_LEARNED_INTERVENTION；有干预无实用增量 NO_SYSTEM_INCREMENT；只比B好未超过C CLASSICAL_RECOVERY_EXPLAINS_GAIN；比B/C均实用增量且另一窗无不可接受回归 PROMISING_SYSTEM_COMPONENT（仅开发证据）；严重退化/不稳定 UNSAFE_OR_UNRESOLVED。不扩窗、不调第二版、不追加人工标注；即使有效也不称SEA-RAFT+NCC本身为论文创新。

必要产物 protocol.md、results.csv、recovery_summary.csv、decision.json、report.md；只必要集成，不建框架。报告首屏回答系统是否变好、相对强传统恢复的增量、网络调用/耗时、严重风险、是否值得继续。正常commit/push小文件并更新 docs/CODEX_HANDOFF_SEARAFT_SYSTEM_PROBE.md，保留旧结果，不force push、不提交无关修改、不上传bag/模型/大缓存；推送后读回报告与结果表。
