# Classical additive opportunity expansion 独立交接

2026-09-08；状态：**Batch A IN_PROGRESS，5/12 窗完成，30/72 次正式 replay 完成。**

首窗 `coe1_a01_00000_00900`：**PRACTICAL_LOSS / SEVERE_REGRESSION**。自身六轨迹共同支撑36 poses、35s、coverage81.818%、35对严格1s RPE；evo检查通过。B APE min/median/max=0.114753/0.155037/0.155037m；C=0.510393/0.554981/0.658114m。B RPE=0.015997/0.020657/0.020657m；C=0.064600/0.070127/0.083283m。全部6次runability和逐ID接收PASS，实际最大优化资格610<1000，未扩容/删KLT。

C追加50545次观测，1017公开ID，寿命中位26、最长435；首个位姿相对参考延迟由6.248s变为7.249s，视觉/IMU对齐拒绝日志次数2→7。两臂重复波动均保留。尺度/初始化变化是同时观察到的现象，不是已经证明的致因。这个新负例不能删除或用于调整C。

A03也已完成并出现严重退化：BAPE中位0.858028m，CAPE2854.46348m；自身42poses/41s/95.4545%/41RPEpairs，evo与6次逐ID/runability均PASS。A04已完成并获PRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN，但B数值异常：BAPE中位743.154m，C0.113799m；支撑31/44poses=70.4545%，evo/receiptsPASS，C首姿更晚约2.900s。A05六次运行/逐ID均PASS，但共同位姿27<30，归NOT_EVALUABLE，不比较APE/RPE。A06为SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN：CAPE中位0.950726m，B151.785956m，但B范围181.441203m超过中位改善150.835229m，不能升级practical。剩余Batch A7窗pending；A07前端正在执行。两次严重退化已使Batch B进入条件不成立，但必须继续完整A分母。必须完成全部12窗后再按冻结门决定Batch B，不可因首个严重退化提前换窗/停掉其余A窗。当前最终科学结论 **Unknown**。A/B合计24窗清单已在任何新C/后端结果前一次冻结，Batch B尚未激活。

独立 worktree `/home/ma/AQUA-FE_WS_classical_opportunity_expansion_v1`，分支 `exp/classical-opportunity-expansion-v1-20260908`，基准49c0247。清单冻结881dad7、执行冻结8f323ba、控制器964db5b、Python3.8兼容入口d162b73；均已推送并远端读回。旧主工作区/旧实验源码与结果不改。

实际运行入口（先source ROS Noetic、设置线程环境）：`/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/classical_opportunity_py38.py --batch A --wait-first-pid 846846`。当前控制器仍在运行，不要重复启动。运行根 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1`；活动日志 `batch_A_controller_attempt2.log`。原等待控制器在0次正式replay时为Python3.8描述表行构造兼容而停止，独立A01前端未停止/未重跑；原脚本、锁和日志保留。见execution_notes.md。

使用ROS12691；其他VINS存在则WAITING_RESOURCE，不算FAIL，不kill。只有本任务前端与串行后端可并行；宿主独占Unknown。每次回放前检查binary/config/输入哈希、容量、磁盘、进程、端口、锁。

12条序列×每批每序列1窗，共24个预注册C-all比较窗口；112候选含12不足900帧的尾窗。全部sequence-held-out仅相对六个C-all开发窗，**不是整个项目完全未见**；更广历史重叠另行只读核验，不改变冻结清单。

入口：[预注册](../papers/frontend_classical_opportunity_expansion_v1/preregistration.md)、[全清单](../papers/frontend_classical_opportunity_expansion_v1/window_roster_frozen.csv)、[实时报告](../papers/frontend_classical_opportunity_expansion_v1/report.md)、[逐次结果](../papers/frontend_classical_opportunity_expansion_v1/backend_results.csv)、[案例注册](../papers/frontend_classical_opportunity_expansion_v1/case_registry.csv)、[决策](../papers/frontend_classical_opportunity_expansion_v1/decision.json)。

C-all只作 classical additive opportunity probe。旧NO_EXPANSION不变。不得增加学习对照、调参、换窗口或第四次技术重复。最终案例只允许窗口候选集合层面的正负解释。唯一研究交付对象是observation-utility / risk机制分析。

更广历史只读核验：A、B各有7/12窗与两个已检查旧项目清单的已登记区间有内部重叠；其余窗仅表示这两个清单未发现内部重叠，不能证明全项目未见。见broader_history_exposure_audit.csv及其provenance。此核验不改变预先声明的six-window heldout范围、清单或判定。

新增机制交接说明见 [case_mechanism_handoff.md](../papers/frontend_classical_opportunity_expansion_v1/case_mechanism_handoff.md)，包含A01/A03负例和A04基线数值异常救援正例。最终运行后依finalization_notes.md执行审计、案例补充和图表；当前不要覆盖控制器实时表。
