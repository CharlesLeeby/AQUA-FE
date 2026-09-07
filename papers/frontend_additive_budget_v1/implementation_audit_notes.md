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

5. 2026-09-08资源审计补充：每次正式启动前检查其他VINS/rosbag replay，本任务使用固定物理核2/3，自身源生成固定物理核0。但宿主不是排他的计算节点；Bus部分回放期间只读进程快照观察到另一窗口的单任务C++编译（采样所在逻辑核11/5），未修改其进程。没有连续保存全程调度轨迹，不能保证系统负载完全恒定。运行耗时和技术极差只能按实测描述，不能作无干扰的严格性能排名；没有据此删掉或挑选重跑。

6. H07 B repeat1的receipt墙钟区间近似为2026-09-07 16:21:17–16:22:27 UTC（精确启动时刻仍Unknown）。临近该阶段的进程快照出现另一窗口VINS，后续叶runner记录WAITING_RESOURCE并等待其结束。启动前检查不能阻止外部任务在本任务期间新启动；未保存全程调度/跨项目互斥锁，因此完整宿主独占为Unknown，存在回放时间重叠的可能。保留全部技术重复及原运行有效性判据，不基于此选择重跑；运行成本和预算敏感性需带非排他宿主限制解释。

7. solver诊断范围为estimator.optimization中的常规非线性ceres::Solve；初始化SfM内部的求解时间、触限与停止原因没有单独日志，Unknown。Bus异常重复的“达到预算0次”仅指已记录的常规优化，不能据此排除初始化求解预算或时序影响。初始化视觉/IMU结构不一致的日志尝试数另列，不能与最终初始化失败、reset次数混用。

8. frontend receipt.source_commit读取的是该次完成时worktree的HEAD；运行期间可提交本任务文档，因此它不是单独的源实现版本标识。原始源实现以d1c793a及source_and_backend_lock.json的逐文件哈希为准；Cemetery另加38e5881中的恢复overlay与cemetery_recovery_lock.json。报告发布commit另列，不能混作实验源身份。
