# Classical additive opportunity expansion 独立交接

2026-09-08；状态：ROSTER_FROZEN_BEFORE_NEW_C_OR_BACKEND。

独立 worktree `/home/ma/AQUA-FE_WS_classical_opportunity_expansion_v1`，分支 `exp/classical-opportunity-expansion-v1-20260908`，基准 `49c02471716e8ac960e35dd9dd44ef6fbb1428c6`。原主工作区和旧实验未修改。

12 条 AQUALOC 序列完整结构枚举 112 个窗口（含 12 个不足 900 帧的尾窗），固定选择 24 窗：A/B 各 12 窗、每序列每批 1 窗。长度/stride=900 帧，半开区间；所有窗口相对六个 C-all 开发窗均为 sequence-held-out，但更广项目历史使用可能存在，不能称全部从未见过的数据。

前端 C-all 及新后端精度：Not evaluated.。先提交/推送并远端读回 roster；随后冻结执行适配器并开始 Batch A。B×3+C×3 每窗，Batch B 只按注册门启动。

入口：[预注册](../papers/frontend_classical_opportunity_expansion_v1/preregistration.md)、[全候选/排除](../papers/frontend_classical_opportunity_expansion_v1/window_roster_frozen.csv)、[两批计划](../papers/frontend_classical_opportunity_expansion_v1/batch_plan.json)。运行根 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1`。独立 ROS 12691；其他 replay 存在则 WAITING_RESOURCE，不能 kill。

C-all 只作 additive opportunity probe；不能重写旧 NO_EXPANSION，不能加学习臂、调参、换窗、挑重复。最终案例集只允许窗口集合层面正负解释。
