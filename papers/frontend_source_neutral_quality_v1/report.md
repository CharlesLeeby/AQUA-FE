本轮实际完成 **0/18次正式replay**，其中B基线0/6次。DECISION：**NOT_EVALUATED**。

- 基线是否足够可靠：Not evaluated.；沿用有效轨迹、接收完整性和重复范围，未要求旧A/A的1e-5m一致。
- 唯一改动：同一L-all候选的quality与派生sigma；锁定源码的通用映射，原始质量/年龄/FB/NCC不变，真实XFeat标签不变。
- 相对L-original：见下表两窗的全部实用判定及误差变化；不以较低中位数替代重复范围门。
- 相对KLT净收益：0个窗口通过实用收益门（完整分母2；未评估槽位不能视为失败或成功）。
- 严重异常：0次，全部列入results.csv；内部原因Unknown。
- 新窗口：未启动，0/36；仅首轮PROMISING允许扩展。
- 唯一下一步：按冻结顺序完成本轮18次正式回放。

| 窗口 | 比较 | neutral APE(m) | 参考APE(m) | APE变化(m/%) | RPE变化(m) | 判定 |
|---|---|---:|---:|---|---:|---|
| a02_0_900 | L-neutral_vs_L-original | Unknown | Unknown | Unknown / Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-neutral_vs_B | Unknown | Unknown | Unknown / Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-neutral_vs_L-original | Unknown | Unknown | Unknown / Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-neutral_vs_B | Unknown | Unknown | Unknown / Unknown | Unknown | Not evaluated. |

| 窗口 | 臂 | 重复 | APE(m) | 严格1s RPE(m) | Sim3诊断尺度 | 状态 |
|---|---|---:|---:|---:|---:|---|
| a02_0_900 | B | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | B | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | B | 3 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-original | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-original | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-original | 3 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-neutral | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-neutral | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a02_0_900 | L-neutral | 3 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | B | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | B | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | B | 3 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-original | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-original | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-original | 3 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-neutral | 1 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-neutral | 2 | Unknown | Unknown | Unknown | Not evaluated. |
| a08_2700_3600 | L-neutral | 3 | Unknown | Unknown | Unknown | Not evaluated. |

逐次表采用三臂九轨迹共同支撑；两项主比较采用各自六轨迹共同支撑，精确min/max/极差与有效性见[comparison.csv](comparison.csv)。原始未对齐位移、初始化/接收/残差计数、覆盖与运行时间见[results.csv](results.csv)，全部运行receipts见[receipts/runs.json](receipts/runs.json)。

这是两个已知结果development窗上的实现混杂消融。三次技术重复不是独立科学样本；COLMAP/proxy非独立GT。q改变常规优化及边缘化，不能归因于初始SfM/视觉IMU对齐的直接q作用。没有C-all配对臂，不能宣称学习来源优于传统来源。旧A/A失败与旧72结果保持原样。

[冻结协议](protocol.md) · [输入/运行计划](run_plan.json) · [决策](decision.json)。大bag/日志只留本任务runtime；报告发布commit为本文件所属版本，实验源码见decision.json/source_commits。
