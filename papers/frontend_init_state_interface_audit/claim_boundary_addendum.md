# EXP-20260906-010 结论边界补充

更新时间：2026-09-06T17:16:31+08:00

本补充保留原始报告、decision、协议、结果与哈希，校正其推论范围。
适用于 [初始化接口审计](report.md)、
[delayed-v3](../frontend_delayed_newborn_slot_v3/report.md) 和
[protected-prefill](../frontend_protected_prefill_slot_v1/report.md)。

## 已确认的内容

- **Confirmed fact.** 所检查源码中，发布 odometry 时要求
  `solver_flag == NON_LINEAR`。这表明估计器已经进入非线性阶段，
  不等于尺度正确、后端无害或初始化质量合格。
- **Confirmed fact.** 当前离线生成 feature bag 的执行路径没有消费这个
  ROS 反馈。接入实时反馈需要额外工程工作。
- **Confirmed fact.** delayed-v3 在既定六窗、frames 32–36、原候选及预算下，
  没有恢复 A09 的显著收敛收益，未通过冻结扩展条件。
- **Confirmed fact.** protected-prefill 的完整 12 个学习臂—窗口结果仍是
  1 WIN / 9 TIE / 2 LOSS / 0 FAIL；六个物理窗口，三次运行是技术重复。

## 校正上一版的两处推论

**“不能回溯改变初始化输入”不等于“以后永远无法改善尺度”。**
初始化后，所检查源码的 `processImage()` 仍调用
`triangulate()` 和 `optimization()`（estimator.cpp:540–548）；
优化器加入位姿与速度/偏置参数、IMU 和视觉残差
（1040–1185），调用 `ceres::Solve()` 并回写状态（1204–1209）。
因此仅凭进入 `NON_LINEAR`，不能断言后续状态或尺度已经永久锁死。

**Hypothesis / Inference.** 后续有效视觉与惯性约束可能影响当前状态和尺度
误差，但这段代码不能证明某种候选一定能恢复已经发散的轨迹。
本项目尚未验证基于实时反馈的方案，标记为 **Not evaluated.**
delayed-v3 的失败只适用于其冻结干预，不能否定所有初始化后介入方法。

另外，此前表格中的约 0.50、0.899 等 scale 是轨迹对 proxy 的
**Sim(3) 对齐拟合尺度**。它们提示整体尺度不一致，不能直接当作读出了
估计器初始化变量 `s`。关于确切内部初始化分支的解释仍含推断；
fixed-scale APE/RPE 和全部失败记录维持原口径。

## 接口的时序限制

odometry 提供已经进入非线性阶段的证据，但没有显式“质量合格”状态。
也未实测它是否总早于 `imu_propagate` 抵达订阅者：IMU 与图像处理可能
在不同线程运行。原报告中“imu_propagate 必然更晚”的描述应收窄为
两个输出都受 `NON_LINEAR` 条件约束，实际到达次序 **Unknown.**

## 本阶段决定

保持 `NO_EXPANSION` 和本阶段 `DO_NOT_IMPLEMENT_POST_INIT_VARIANT`：
现有开发实验没有通过收益/回归标准，所以本轮不再运行参数或时机变体。
这是基于已有证据和停止规则的研发决定，不是对整类方法不可能有效的证明。

本次只校正解释，没有新增实验或胜例；12 新窗口验证仍为 0/12、尚未启动。
原实验使用的 proxy 不构成独立 GT，结果不支持整体优于 KLT 或现代学习前端。

所检查 estimator.cpp SHA-256：
`ea75d3f074f6c8780fff3353dc1628e94d265e63be13672caed4bdd64dd3572e`。
源码身份与原接口审计相同，外部后端没有修改。
