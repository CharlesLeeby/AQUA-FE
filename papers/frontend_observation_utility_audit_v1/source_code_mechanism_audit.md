# 冻结源码的机制路径（静态事实，不代替状态测量）

检查对象为additive锁中的外部后端source_snapshot；本轮只复制、添加日志，未修改外部原件。

1. `feature_manager.cpp::addFeatureCheckParallax`基于新生/延续/长轨数量和平均视差决定关键帧。完整保留B不等于关键帧路径保持B；添加会改变集合统计。
2. `Estimator::relativePose`按窗口顺序寻找correspondence>20且平均归一化视差×460>30的帧对，再调用relative RT；候选能改变帧对均值/几何与接受路径。
3. `initialStructure`把feature manager里的轨迹送入SfM；`initial_sfm.cpp`为state=true的各条观测建立ReprojectionError3D，鲁棒核为NULL，未读取visual_quality。SfM默认0.2s时间预算；环境未开启改预算开关。
4. `VisualIMUAlignment`由SfM姿态估计gyro bias，再构造scale/gravity线性系统；线性重力模长偏差>0.5或负scale拒绝，再细化重力及scale。失败尝试默认不回滚bias的现有行为保留。其独立贡献Unknown，不诊断为已确认bug。
5. `setQualityWeight(min(first,current))`在后续常规优化和边缘化投影因子中生效。q是后端权重混杂，但当前源码的初始relativePose/SfM/linear alignment没有直接读取q；不能把这些前优化路径的改变单独归咎于q映射。首个输出前还有优化，因此最终输出差异仍可受q影响。

以上只能说明干预路径可能存在；每点是否静态、是否有因果效用、真实尺度如何变化必须靠有效动态证据。诊断A/A失败时，新增内部状态禁止用于机制结论。
