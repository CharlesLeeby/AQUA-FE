# A08 固定基线重放：最早可见分叉已定位到求解工作量

更新时间：2026-09-10T01:08:00+08:00。
**COMPLETE / READ_ONLY_RETROSPECTIVE_ENGINEERING；新增回放0，前端/后端改动0。**

结论：同一输入和冻结二进制下，保存的基线轨迹确实会不同；异常记录最早的可见分叉
与初始化之后第7次优化的迭代条目数差异同帧出现。**求解工作量不同是Confirmed fact；
时间预算/主机负载造成最终发散仍是Hypothesis / Inference，尚未完成因果隔离。**
本轮没有修复算法，没有新增正例，也不能用本诊断抹去A02原有删点充分性或其他负结果。

## 范围和身份

按[审计范围](audit_scope.md)检查三个已知结果证据包中A08 [2700,3600) 的全部B记录：
additive三重复、utility frozen一次、quality三重复，共7条同版基线；
另单列utility diagnostic一次，不混成同二进制重复。它们来自容量1000的独立诊断合同，
不是主线350预算原二进制的新结果，三个实验的原精度表都不重算。

- 8/8原receipt的97个登记产物哈希通过；1471项锁条目核对通过，共享文件去重读取。
- 同版7条的节点、VINS库、完整feature bag、相机文件和除运行路径外的YAML一致。
  端口依原实验分别为12671/12681/12691，不声称完整进程环境逐字一致。
- 全部8条记录均收到450帧、157500个feature观测；接收日志的时刻/ID/次数/顺序逐字节一致。
  这不等于已记录每个IMU消息的实际到达/消费顺序，也不补造逐坐标接收证据。
- 全部8条均有440个位姿，完整输出头时间向量相同；第一头为
  `1542885097172932864`，最后头见[身份表](identity.csv)。
  solver的浮点秒打印与VIO的整数头按原double序列化关系核对，3520条全部一一对应；
  没用近邻时间配对。
- 当时每次进程完整环境、实际加载映射、连续主机负载、实际IMU消费边界：**Unknown.**
  现存库与锁一致，不冒充历史逐进程加载证明。quality公开的first-live快照对应另一个窗口，
  不能替本窗七次运行填“已确认”。
- runner把receipt的`started_at`写在运行结束后，因此它是receipt发出时间，不是实际启动时刻。
  本轮纠正字段解释，不改历史receipt；双时钟ROS日志也不能当作精确传感器初始化边界。

核心身份：feature bag `17305db38262a2ed4c7fa05b6269c9ea50592de07387517dfec798cf086ceae9`；
冻结node `e231871eaff26a757a5d396ef5df0ad4d488d55be1c8d0e8d0f1204d1068aadd`；
冻结lib `86c1f97712b3ead53f0693d7c408dcb4dec78a386f72f56c5cb5c5671d04ccd9`。
配置/相机/receipt身份及精确运行路径见[identity.csv](identity.csv)。

## 不是换了输入；同样配置下实际做的优化次数不同

锚点预先固定为最早additive B r1，不是按准确率挑出的最好重复。
下表是直接、未对齐的工程差异，不是APE、定位真值误差或方法胜负。
“位姿n”按保存输出的1起始编号，不是raw图像编号。

| 既有B记录 | 相对锚点首次位置差异：位姿n | 首次迭代条目数不同：位姿n，锚点/本次 | 最大直接位置差 m | 原始位置范数最大值 m |
|---|---:|---|---:|---:|
| additive r1 锚点 | — | — | 0 | 3.666900 |
| additive r2 | 3 | 3，9/8 | 0.356952 | 3.310171 |
| additive r3 | 3 | 3，9/8 | 0.336773 | 3.330318 |
| utility frozen r1 异常 | 7 | 7，7/6 | 283237.349446 | 283235.520028 |
| quality B r1 | 1 | 1，9/5 | 1.874848 | 1.792070 |
| quality B r2 | 5 | 5，6/5 | 0.010071 | 3.676948 |
| quality B r3 | 21 | 9，8/9 | 0.003438 | 3.670330 |

同版7条的全部21对都越过原A/A的1e-5m/rad严格一致容差；
这是**重放不严格相等**，不是21个新失败窗口，也不撤销原runability PASS。
不同诊断二进制的第8条单列在[audit_receipt.json](audit_receipt.json)；
其原始位置范数最大3.667543m，不能把它较小的值当成日志补丁改善算法的证明。
[21对完整表](pairwise_direct_differences.csv)。

### 异常运行最早分叉的逐帧证据

锚点与utility frozen异常记录，前6个位姿CSV的保存值一致；日志前6次六位小数姿态打印也一致。
两边都只有一次Initialization finish，记录的初始陀螺校准增量均为
(-0.000552984, 0.00909836, -0.0607808)。
但这仅是现有打印精度下的一致，**不证明完整内部初始化状态按位相同**。

| 事件 | 位姿n / 相对首输出秒 | 保存位置差 | 已有日志能确认什么 |
|---|---|---:|---|
| 首次迭代条目数/位置分叉 | 7 / 0.599826176s | 0.000042426m | 同一40ms预算；锚点7条/46.989671ms，异常6条/41.455725ms；两边termination均1 |
| 首次记录的资格/残差集合差异 | 201 / 19.996969472s | 0.033674m | 差异晚于第一次位置分叉；此前日志中的ID/观测数/残差块计数一致 |
| 首次实际预算分支不同 | 206 / 20.498659328s | 0.120146m | 锚点40ms，异常32ms；不是最早分叉时已经使用不同YAML |

第7次事件两边均在backend_use.csv第11043行，传感器头
`1542885097772759040`。精确时间、来源行号、每次耗时/条目数在
[first_fork_events.json](first_fork_events.json)。

“记录的集合一致”只指eligible/residual ID、观测数、块数和顺序，
不包括内部深度、参数、Jacobian或数值残差。201/206的后续差异不能倒推为第7次分叉的原因。
最大位置范数约283公里明显异常，但本轮没有拿这个值代替proxy APE。

## 源码和记录支持到哪里

只读检查与原build receipt哈希一致的快照：estimator.cpp SHA
`263d37db04d51e6571394fb517c9755bdc1a7cc61e1643e58f21f46b38dca9ff`，
1194–1222行设置max_num_iterations=8，并按边缘化分支设置0.032或0.04秒上限，
调用ceres::Solve后保存summary.iterations.size()/termination_type，再把当前解写回状态。
因此配置“最多8次”不是保证每次完成8个迭代步骤。

Ceres本机1.14头文件说明termination=1为NO_CONVERGENCE，可由时间或迭代上限触发；
它并不表示程序崩溃。迭代summary包含第0次条目，9条不能读成执行了9个成功更新。
冻结审计没有保存summary.message、每步接受状态、pre-solve全状态，
因此“少于上限的非收敛返回与耗时边界相邻”是强线索，不冒充已取得精确终止原因。
所有8条的solver整数termination中都没有2/FAILURE；这也不代表轨迹物理正确。

初始SfM另有0.2秒求解上限（initial_sfm.cpp快照SHA
`d3ec26d2e91325f69a93197c10ec17e44e1b8ed54915a27fbb92936fd32f6d9b`），
未在这些冻结记录中提供完整summary；同一首次位姿时刻不能排除亚打印精度的初始化差异。
[原诊断构建/源快照身份][build]、[原runner][runner]。未重编译或改外部VINS。

**Confirmed fact.** 文件身份一致、记录的视觉接收相同，但实际迭代工作量及输出不同；
异常记录最早可见分叉发生在第7次常规优化。
**Hypothesis / Inference.** 有限墙钟预算引入的求解工作量变化可能介导后续放大。
主机负载是候选上游因素，不是已确诊原因；该差异也不单独证明最终发散由第7次少一条迭代记录充分造成。
所有A02/学习臂负结果不能因此统统归咎于运行环境。

## 本轮实现、复核和边界

仅新增[只读分析脚本](../../scripts/audit_a08_existing_replays.py)及
[5项最小测试](../../tests/test_a08_replay_audit.py)，没有修复前端/后端算法。
初次分析把原utility锁中的相对脚本路径按主工作区解析，误报两处MISSING；
已用原工作区路径与提交对象的同一SHA核实，修正分析器并加测试。
初次四份派生结果保留在本地attempts/relative_lock_path_probe；数值表修正前后逐字节相同。
这不是历史环境漂移或需要重跑实验的证据。

最终5/5测试、97个receipt产物、1471个锁条目、全部输出/solver头对应通过。
本轮新APE/RPE、evo验证、初始化内部全状态、候选作用、算法修复、新窗口：**Not evaluated.**
原A/A失败及27次正式诊断未启动的决定不变。原guard输入身份映射也不能被解释为未来每次求解都确定相等。

## 唯一下一步

建议另行冻结**3次同一A08 B bag/二进制/YAML的有限工程重复**：
保持原CPU亲和、线程、32/40ms及迭代上限，只在无其他研究回放时运行，并记录每次实际加载库、
环境及主机负载；全部结果保留，不挑好重复替换旧数据。
用途是检查原预算下可获得的重放稳定性，不是宣称三次相似就证明确定性或时间预算因果。
本轮没有启动这3次，也不自动恢复已停止的27次矩阵或前端版本搜索。

决策：[decision.json](decision.json)。主线仍NO_EXPANSION，无新方法晋升或正例。
该一次只读阶段源码基底为main@f6f8fee加本脚本/范围精确SHA；发布commit由推送回执另记。
复现：在AQUA-FE根执行 `python3 -B scripts/audit_a08_existing_replays.py --output <新的空输出目录>`，
既有输出拒绝覆盖；原始bag/日志留本地，只发布紧凑证据和必要代码。
[派生与源码哈希](artifacts.sha256)，证据来自下列既有提交，不是本轮新运行：

- [additive完整结果][additive]：49c02471716e8ac960e35dd9dd44ef6fbb1428c6。
- [utility原失败门][utility]：90646d6a12f0cdde257ff5b7efa3166daa32dc12。
- [quality完整结果][quality]：6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f。

[build]: https://github.com/CharlesLeeby/AQUA-FE/blob/49c02471716e8ac960e35dd9dd44ef6fbb1428c6/papers/frontend_additive_budget_v1/backend_build_receipt.json
[runner]: https://github.com/CharlesLeeby/AQUA-FE/blob/49c02471716e8ac960e35dd9dd44ef6fbb1428c6/scripts/run_additive_budget_backend.py
[additive]: https://github.com/CharlesLeeby/AQUA-FE/blob/49c02471716e8ac960e35dd9dd44ef6fbb1428c6/papers/frontend_additive_budget_v1/report.md
[utility]: https://github.com/CharlesLeeby/AQUA-FE/blob/90646d6a12f0cdde257ff5b7efa3166daa32dc12/papers/frontend_observation_utility_audit_v1/diagnostic_gate_report.md
[quality]: https://github.com/CharlesLeeby/AQUA-FE/blob/6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f/papers/frontend_source_neutral_quality_v1/report.md
