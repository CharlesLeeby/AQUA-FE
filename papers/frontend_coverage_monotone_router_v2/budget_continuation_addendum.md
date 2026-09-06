# v2 预算与续传：冻结源码行为及归因补充

更新时间：2026-09-06T22:59:42+08:00。审计 ID：`EXP-20260906-011`。
状态：`COMPLETE_READ_ONLY`。这是结果已知后的诊断，不是新方法实验。

## 结论先行

**不能把 10 条单帧 lineage 统一归因为预算耗尽，也不能认为只修预算就能得到
持久的后端约束。** v2 混用了首次准入和已有 ID 的续传规则；但后续两份冻结
开发协议已明确保留这些语义。扩大续传属于新的策略实验，不是可直接覆盖冻结
版本的无行为变化修复。本次没有修改前端或后端。

**相对已有产物的实际增量：** 9 月 5 日已发布的
[lineage_budget_audit.md](lineage_budget_audit.md) 和
[逐 ID 表](lineage_budget_audit.csv) 已谨慎区分其中五条部分预算案例；它们当时仅在
发布 worktree，不在主工作目录。本次将原文件原样补回主工作目录，不把该区别
包装成新发现。新增的是五个冻结源码复现测试、带原始下一帧行的可重建审计，
以及固定首次发布/截止时刻下的观测数上界。

当前 `NO_EXPANSION` 不变。没有新增 frontend export / backend replay；新增窗口
仍为 0，12 窗验证没有启动，不能据此计算数据集总体正例率。

## 逐窗、逐 ID 的证据

[紧凑 CSV](budget_continuation_audit_20260906.csv) 包含全部四个 active 臂的
selected output frames 0–7（32 行），以及全部 14 条 lineage 的下一输出帧
诊断（14 行）。先按原前端动作清单确定范围，没有按后端正负结果删行。
原 [lineage_diagnostic.csv 的已发布副本](../../docs/research_sync/EXP-20260905-005_v2_backend/lineage_diagnostic.csv)
不覆盖；该副本与本地原件的变换/哈希见
[source_identity.csv](../../docs/research_sync/EXP-20260905-005_v2_backend/source_identity.csv)。

| 窗口 / v2 臂 | 最终仲裁前累计候选观测 / 实际发布 | 已发布 ID 数 | 停止附近能确认什么 |
|---|---:|---:|---|
| A09 6000–6800 / XFeat | 3 / 3 | 1 | 第 5 输出帧被 microburst-no-extend 拦截；并非 50 名额耗尽 |
| A02 0–900 / XFeat | 50 / 8 | 3 | 两条发布到帧 4，下一帧已有 15 个候选被最终 horizon 拦截；另一条帧 3 后停止的逐 ID 原因 Unknown |
| A02 0–900 / SP+LG | 50 / 8 | 8 | 5 条在帧 2 发布后停止，帧 3 仍通过 23 个候选；另 3 条在帧 3 发布，帧 4 的预算层不再通过候选 |
| AFRL Bus s180 d45 / XFeat | 2 / 2 | 2 | 帧 2 发布后，帧 3 无 learned tracker 输出 / pre-gate sidecar；不能确定具体 FB/NCC/身份终止原因 |

**Confirmed fact:** 10 条单帧轨迹的下一输出帧证据应拆为 **5 条部分预算截流、
3 条预算标记且无 pre-final 候选、2 条无 pre-gate 候选**。旧报告“8 条之后预算
耗尽”过于宽泛：`online_seed_budget` 同时用于部分放行和全部拒绝。前者不能当作
该 ID 被预算删除的证据。CSV 的所有标签都描述聚合状态，不声称逐 ID 因果。

**Unknown:** 已发布 ID 对应的内部候选出生、最后存活、最终消失的具体原因；
实际后端逐 ID 接收/残差使用仍无 receipt。含这些观测的 bag 已完成三重复 replay，
不等于记录了每个 ID 实际进入残差。没有隐藏池逐 ID 记录，无法事后补造。

## 四类预算不能混称

| 层级 | v2 实际含义 |
|---|---|
| 候选生成 | matcher / tracker 生成与确认的候选池，不是公开给 VINS 的观测 |
| 新公开 lineage 准入 | 没有独立的累计“首次 ID”记账；同一 ID 再次发布仍走相同规则 |
| 每帧容量 | 总量不超过 350，最终每帧最多 6 个 sidecar；这是观测容量，不是总 lineage 数 |
| 最终发布观测 | 实际从输出 bag 统计。上游 50 计数在最终仲裁前扣除，最终拒绝不退还；不是“已经向 VINS 发布 50 次” |

A02 两臂各 50 个 pre-final 输入只有 8 个发布，差额各 42。并非所有差额都是
同一原因：例如 XFeat 帧 3/4 的最终容量/准入筛选及帧 5/6 的 horizon 拒绝都在其中。
这里只对最终仲裁前计数作直接核对，不虚构额外的运行期逐 ID 计数日志。

## 五个冻结源码最小测试

[测试文件](../../tests/test_v2_budget_continuation_characterization.py) 从 Git 对象
读取**运行时 v2 exporter 的精确字节**，验证 SHA 后加载。5/5 PASS：

1. 剩余 23 名额面对 36 个合格候选，放行 23 个也输出 `online_seed_budget`。
2. 最终完全拒绝仍保留上游已扣的 50 名额；后续候选被预算阻断。
3. 同一个已准入 ID 满容量续传时重新需要 donor；没有 donor 就不发布。
4. 同一个有效 ID，即使还有合格 donor，帧 5 也被最终帧 4 horizon 截断。
5. 三帧 microburst 可在仅扣 3 个名额、剩余 47 个时关闭。

这些是合成 TrackSet 的函数行为测试，不是重新运行真实前端。为隔离行为，测试
夹具关闭无关门；任何真实实验配置和阈值均未变化。首次执行有 3 项因测试夹具
遗漏 GateInfo 必需参数而报错，修正夹具后全部通过；不是后端失败或新方法收益。

一个额外的确定性边界：这 14 条 lineage 实际首次发布都在帧 2 或 3。
**如果保持这些首次发布时刻及帧 4 截止不变**，且不倒填观测，每条最多获得
3 或 2 个单目输出观测。即使仅退还未发布预算，也不能让这些相同起点的轨迹达到
锁定后端 nonlinear visual residual 路径的四观测条件。该边界不预测预算修改是否
会改变其他候选的首次准入；初始化 SFM 与 nonlinear residual 的使用也不能混同。

## 决策与证据边界

Confirmed fact：存在提前扣预算、再次找 donor、microburst 和 horizon 四种不同
限制。Hypothesis / Inference：它们可能损失可持续候选，但缺乏逐 ID 内部状态，
不能确认“多数候选实际仍存活”。不能把策略限制包装成已经确认的跟踪 bug。

本轮只实现**已有诊断分类的可复现测试**：部分截流与全部阻断分开，精确 ID 原因保留 Unknown。
没有实施预算退还、延长 horizon、改变候选来源或 donor 顺序。修订后的
[分析脚本](../../scripts/audit_frontend_v2_budget_continuation.py) 新建独立补充 CSV，
拒绝覆盖已有文件。

唯一下一步决策：结束这轮被冻结停止规则约束的替换/准入实验，不扩展 12 窗。
如果另行重启研究，需单独授权并冻结“准入/续传分离”实验，明确新生 GFTT 的机会
成本；不能以“记账修复”名义同时解除多个门，也不能预称后端 no-harm。
该新策略的效果为 **Not evaluated.**

原后端结论未变化：v2 42/42 replay 完成，12 学习臂—窗为 2 WIN / 8 TIE /
2 LOSS / 0 FAIL；protected-prefill 为 1 WIN / 9 TIE / 2 LOSS / 0 FAIL。
A02 donor 377 仍是只少一个观测，不是删除 104 帧。参见
[v2 完整结果](backend_completion_report.md)、
[正例删除对照](../frontend_v2_positive_delete_diagnostic/report.md)、
[protected-prefill 结果](../frontend_protected_prefill_slot_v1/report.md)。
所有 APE/RPE 仍是与 COLMAP/proxy 的一致程度，不是独立 GT 绝对误差。

## 身份与复现

- 实验运行基底：`f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加
  [method_lock_recovery1.json](../../docs/research_sync/EXP-20260905-005_v2_backend/method_lock_recovery1.json)
  的脏源码身份。
- 后来归档的 v2 源码 Git 对象：`3c50b742d6e0c69796a69813e42823e9895ed684`；
  **不是实验运行当时的源码 commit**。
- 归档 exporter SHA-256：`bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d`。
- 四个 frontend_metrics.csv 均匹配原 receipt 的 SHA；具体值随每行写入补充 CSV。
  大型 bags 没有重写、重复哈希或上传。
- 原 lineage CSV SHA-256 保持 `aa8ecc58b8837d720c4e66df2c3b60268fc850e2628da883a05cf79e518c60ee`。
- 本审计 CSV SHA-256（统一 LF 换行）：`483ce249386cf9f05005fc5a41b2b89c3f6bb33803937ccc66d5ad4722c202b5`。

复现（在仓库根目录；输出选择一个尚不存在的文件）：

```bash
python3 scripts/audit_frontend_v2_budget_continuation.py --paper papers/frontend_coverage_monotone_router_v2 --output /tmp/aqua_v2_budget_audit_new.csv
source /opt/ros/noetic/setup.bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p test_v2_budget_continuation_characterization.py -v
```

重建真实数据审计需本地原 metrics/receipt；网页已公开紧凑实际行而非只有哈希。
函数测试只需仓库历史和现有 ROS/Python 依赖，不读取原始数据集。
