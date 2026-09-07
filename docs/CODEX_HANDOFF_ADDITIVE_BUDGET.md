# AQUA-FE 添加式数量对照独立交接

分支：`exp/additive-budget-v1-20260907`；基准 `b6f11ca`。
原窗口、原交接及旧实验保持不变。

协议与源码哈希已冻结，后端执行锁等待容量与只读诊断检查。
[报告](../papers/frontend_additive_budget_v1/report.md) / [比较](../papers/frontend_additive_budget_v1/comparisons.csv) / [决策](../papers/frontend_additive_budget_v1/decision.json)。

恢复：从独立 worktree 加载 `/opt/ros/noetic/setup.bash`，设置 `PYTHONPATH=.:$PYTHONPATH`，用 `/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/run_additive_budget_v1.py --window a09_6000_6800`。仅在无已完成 receipt 时运行；不可覆盖未完成目录。

后端已完成诊断构建，实际执行锁为 `backend_execution_lock_v2.json`；原锁保留审计。数学算法/1000容量不变。容量证据、评价时间适配及探针规则见 capacity_and_evaluation_addendum.md。所有正式结果仍 Not evaluated。

A09前端四臂完成；L6=2251、L-all=42018、C-all=22392次追加观测，KLT逐字段保持。backend B/repeat1预启动遇到WAITING_RESOURCE，尚无正式replay。剩余五窗源流在本轮终端会话顺序执行；不要重复启动，先查进程/receipt。准确状态见report和decision。

A09正式12/12完成且共同支撑/evo通过：更多剂量未改善净收益，两学习添加臂对B实用退化。A02前端4臂完成，后端控制器等待/顺序执行；AFRL Bus源流运行中。见checkpoint_a09.md。恢复前检查 execute_additive_budget_matrix.py 与 frontend进程，不重复启动。
