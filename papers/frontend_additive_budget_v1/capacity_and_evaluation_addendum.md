# 容量与评价执行补充，后端结果出现前冻结

2026-09-07。不改变候选、公开配额、质量、几何、窗口、指标或实用幅度。
原 source lock 与 backend_execution_lock.json 保留；实际执行采用
backend_execution_lock_v2.json，修正预检分类，未产生任何本任务后端结果。

NUM_OF_F=1000 未扩容。对无断续复用的公开 ID，滑窗删帧仍保持每条观测在
保留帧中的连续性。11 个保留帧中，任何长度>=4的连续区间都与索引3或7相交，
因此优化资格数 <=2×单帧最大点数。先审计原B和每个添加bag的ID连续性。
这一上界<=1000时为静态容量 PASS；大于1000仅为保守上界不能证明足够，
不等于实际容量不足，标 GUARDED_CAPACITY_PROBE_REQUIRED。

在后一情形，首个完整合同 replay 是容量探针。隔离副本在任何 para_Feature 写入前
检查真实资格数，超过1000则抛出 CAPACITY_UNSUPPORTED，绝不越界或截断；
外部消息通道长度也先检查。探针保持正式起点、完整输入、统一数学算法、
同一二进制/solver设置、完整receipt，因此成功或失败都计入固定三重复，
不挑选最好一次。所有后续重复继续保留保护，记录每次最大真实资格和使用量。
其他存储在已读源码中为 STL 动态容器，固定滑窗/位姿数组仍按原窗口大小索引。
任一真实上限触发保留失败/受限臂窗，不把工程阻塞当精度失败；不自动扩容追逐结果。

评价入口 evaluate_additive_budget_v1.py 只组合现有 dual-scale evaluator
与 epoch_v2 的精确ROS时间读取；proper fixed-scale SE(3)为主，Sim(3)仅诊断。
RPE沿用已验证的 aligned-global-frame positional-delta 1s 定义及同网格evo核对，
不是悄然更换成完整姿态相对变换RPE。主/护栏、共同支撑与三重复规则不变。
原始引用的 evaluator/core 连同此组合入口均需在新效果出现前哈希封存。
