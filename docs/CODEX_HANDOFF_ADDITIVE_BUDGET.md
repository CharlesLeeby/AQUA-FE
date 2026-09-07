# AQUA-FE 添加式数量对照独立交接

分支：`exp/additive-budget-v1-20260907`；基准 `b6f11ca`。
原窗口、原交接及旧实验保持不变。

协议与源码哈希已冻结，后端执行锁等待容量与只读诊断检查。
[报告](../papers/frontend_additive_budget_v1/report.md) / [比较](../papers/frontend_additive_budget_v1/comparisons.csv) / [决策](../papers/frontend_additive_budget_v1/decision.json)。

恢复：从独立 worktree 加载 `/opt/ros/noetic/setup.bash`，设置 `PYTHONPATH=.:$PYTHONPATH`，用 `/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/run_additive_budget_v1.py --window a09_6000_6800`。仅在无已完成 receipt 时运行；不可覆盖未完成目录。
