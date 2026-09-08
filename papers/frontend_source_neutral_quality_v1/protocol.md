# Source-neutral quality v1 — 冻结开发协议

2026-09-08。原则：**结果优先、审计有上限、一个任务一个可检验问题**。
只检验来源专用后端可靠度映射是否部分造成XFeat添加方案的不良表现。
已知结果development窗A02 `[0,900)`、A08 `[2700,3600)`；原manifest的精确bag/时刻/标定/IMU配置不变。
源证据49c0247，机制边界90646d6；不修改或重跑旧矩阵，不使用新内部日志后端，不重编译。

## 唯一改动

B=原完整KLT；L-original=原L-all；L-neutral=同一L-all只改候选`quality`及派生`sigma=1/sqrt(q)`。
从锁定`export_vins_features.py::_backend_reliability`执行原公式；通用版本只使
`_backend_source_reliability`取源码现有末尾fallback、跳过`_vins_safe_backend_reliability`的来源专用循环。
即保留通用age/FB/NCC/raw-quality乘积、原clip和floor=.80；fallback=.90来自锁定源码，不另设权重。
仍传真实`xfeat_confirmed`，仍使用原raw_quality、age、FB、NCC；不改源标签、不重跑网络/筛点。
以source_id + 精确帧/时刻 + lifecycle的public_id核对，重算原q必须逐float32相等；缺少精确输入立即停止。
所有坐标/ID/时刻/顺序/数量/生命周期及原KLT所有字段必须一致；新bag磁盘读回只允许上述两通道的候选段变化。
后端rosNodeTest读取quality；常规优化/边缘化以min(first,current)设置q，残差及Jacobian乘sqrt(q)，sigma通道仅保持语义一致。
初始relativePose/SfM/alignment不直接读q，不能把终局改善解读为已修复所有初始化差异。

## 执行与工程停止

使用原additive的`backend_diagnostic_attempt2/bin/vins_node`及同目录lib；确切输入/二进制/动态库身份和运行顺序写入run_plan.json，在新回放前冻结。
原叶runner只读复用；独立端口12691、输出/tmp/ROS目录和任务锁，CPU2,3,8,9、线程1、rate1、drain8s；数学YAML仅重定向输出/相机路径。
每次启动前无其他正式replay，检查输入、实际动态依赖、配置/相机、空输出路径和资源；不终止其他任务。
次序：A02 B r1–3，A08 B r1–3；随后A02、A08各r1 original→neutral，r2 neutral→original，r3 original→neutral。总18次；前6次兼作基线可用性检查，不另开A/A。
不要求1e-5m数值一致，旧A/A FAIL保持原样。沿用300s/8GiB RSS/512MiB日志/可用内存4GiB、运行盘8GiB资源限制。
严重工程异常：非有限位姿、空/失败运行、逐ID接收不完整，或原始位置相对首位姿最大位移超过`10*max(1m,旧三次B最大位移)`；每窗确切上限在run_plan.json冻结。这是数量级报警，不是APE阈值。
B异常立即保留并只做一次直接输入/进程/依赖/配置检查；没有可复现工程原因则EVALUATION_BLOCKED，不继续精度优劣结论。只有查明工程原因才修复并另登记最多3次验证；不得择优重跑。
方法臂异常全部保留，不能以中位数掩盖，禁止据此进入新窗。内部原因Unknown无需追加无界诊断。

## 评价与一次性决策

沿用additive冻结evaluator：1Hz共同网格、reference gap<=2.5s、estimate gap<=.25s；>=30位姿、>=10s、覆盖>=70%、严格1s RPE>=10对。
主比较L-neutral/L-original、L-neutral/B分别用两臂三重复共同支撑；另给三臂九轨迹共同支撑的逐次结果。任一次无效则该对比不判精度胜负。
主指标fixed-scale proper SE(3) APE RMSE；严格1s平移RPE为护栏，Sim(3)仅诊断。
实用改善：APE下降同时>=5%、>=.01m，且超过两臂最大重复极差；RPE回归<=max(参考5%,.005m,两臂最大RPE极差)。实用退化反向同门。严重回归沿用>10%且>.01/.005m并超过极差，或新增失败。
全部18槽位及每次结果进入results.csv；comparison.csv给中位、min/max、极差和精确方向，技术重复不是独立样本。

按顺序决策：B不可用为EVALUATION_BLOCKED；至少一窗neutral/B实用净收益、另一窗无严重退化、没有严重异常为PROMISING_DEVELOPMENT_RESULT；否则若neutral/original有实用改善为SOURCE_MAPPING_MATTERS_BUT_NO_NET_GAIN；其余为SOURCE_MAPPING_NOT_MAIN_EXPLANATION（逐项报告不确定或变差，不把未改善解释为绝对无影响）。停止常数扫描。
仅PROMISING时授权在看新方法结果前冻结六个新、不重叠且尽量不同序列的固定时间窗，B/neutral各3次，共<=36次；不换窗/调参。其余不扩展。不与本轮缺席的C-all宣称学习来源优越。
结束输出五份主文件、必要代码/receipts与简短项目日志；协议冻结和阶段结束各同步一次，远端读回handoff/report/comparison。唯一后续动作由结果决定。
