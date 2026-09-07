# 实现审计边界（不修改冻结方法）

2026-09-07，已产生A09后端结果后的只读审计。

1. 冻结的 `_backend_reliability(..., mode="vins_safe", floor=.80, alpha=.65)`
内部对`xfeat_confirmed`有专门映射，`classical_gftt_confirmed`采用通用映射与.80地板。
同名函数/参数不等于两来源同一权重公式。原生XFeat/角点分数只作各自种子排序，
没有直接把二者作为可比质量；但后端来源先验仍是L-all/C-all比较中的另一混杂。
此映射已包含在原冻结源码哈希内，全部结果后不改权重，也不把C-all重标成XFeat。
L6和L-all使用同一XFeat源流、同一质量值，核心数量对照不受跨源映射差异影响。
已完成源流的实际q范围见source_weight_audit_checkpoint.csv，完整汇总在最终source_weight_audit.csv。
C-all的GFTT检测器为正常参数、没有按学习结果筛选或降低检测质量；来源间只报告整个方案差异。

2. 后端叶runner的原receipt字段`started_at`实际在回放收尾时写入，表示receipt生成时刻，
不是精确启动时刻。冻结receipt不重写；分析表将其标为receipt_emitted_at，
可用该时刻减wall_s给近似起点，精确墙钟启动时刻Unknown。
这不影响固定bag起点、传感器时间、初始化日志时刻或实际wall_s测量。

3. 私有tracker精确终止原因没有逐ID落盘。质量/几何/去重的逐帧汇总和
真实FB/NCC/border死亡累计存在；具体公开ID为什么在共同源流中消失，
不能由这些汇总唯一归因，逐链字段明确Unknown/source_missing_or_invalid。

4. 用户任务固定六窗三技术重复；这些已知结果开发窗不是随机样本。
不把技术重复当独立科学样本，不从三重复构造总体获益显著性或自然正例率。
