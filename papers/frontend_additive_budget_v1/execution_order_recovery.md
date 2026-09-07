2026-09-08，Cemetery结构恢复后的排程。

A09、A02、Bus、A08按原顺序完成48次正式回放后，暂停本任务旧controller PID615331；该controller在等待Cemetery前端，不持有后端锁，没有停止正在运行的ROS/VINS。H07仍用原冻结源runner。先等待其前端/容量完成，单独用execute_additive_budget_matrix.py --start-window h07_0_1000完成H07的12次；Cemetery恢复源在独立前端核心推进。

待H07后端结束且Cemetery恢复读回/容量通过，再SIGCONT原controller，执行Cemetery12次；其后对已完成H07只做receipt哈希核对，不新增重复。最终物理顺序为A09/A02/Bus/A08/H07/Cemetery，由结构恢复依赖决定，不由精度胜负筛选。每窗臂/重复内部顺序、后端二进制、CPU亲和、solver和所有输入/评估合同不变。仅一个backend controller处于可启动状态，另一任务记录为本任务协调暂停。
