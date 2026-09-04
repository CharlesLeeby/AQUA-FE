---
type: results-report
date: 2026-07-31
experiment_line: aqua-fe
round: 1
purpose: project-progress-addendum
status: complete
source_artifacts:
  - 2026-07-30--aqua-fe--r00--project-progress-review.md
  - orb_v23_crossdataset_afrl_20260731/analysis-output/analysis-report.md
  - orb_v23_crossdataset_afrl_20260731/analysis-output/stats-appendix.md
  - orb_v23_crossdataset_afrl_20260731/analysis-output/figure-catalog.md
  - orb_v23_crossdataset_afrl_20260731/2026-07-31--orb-v23-crossdataset--r01--transfer-summary.md
linked_experiments:
  - orb_v23_crossdataset_ntnu_20260730/2026-07-30--orb-v23-crossdataset--r00--transfer-summary.md
linked_results:
  - 2026-07-30--aqua-fe--r00--project-progress-review.md
---

# AQUA-FE / Round 01 / project-progress-addendum / 2026-07-31

> 本文只记录 2026-07-30 全量进展报告之后新增的证据，不重复改写历史结论。当前仓库未绑定 Obsidian，未执行 write-back。

## 1. 新增完成项

- 构建 AFRL Cave Gennie `s0,d20` 原生 ORB 数据集：389 张 1600 x 1200 图像、60 个 COLMAP GT poses、完整相机配置；
- 从冻结 final-online 资产导出 1 条 lineage、54 个 post-init observations，图像时间误差 `0 ns`；
- 完成 `orb_only/drop/full` reachability smoke；
- 完成五臂四轮正式矩阵，共 20 runs；
- 完成 reconstructed/online APE 与 20-associated-pose RPE；
- 建立 fail-fast 分析脚本、三张科学图、统计附录、provenance 和 13 文件可重复 bundle；
- 完整 bundle 独立重建后逐字节一致。

## 2. 新增证据与结论

### 2.1 被闭合的问题

NTNU `s30,d10` 的主要缺口是 seed 发生在 ORB 初始化前，0 MapPoint、0 assisted match。AFRL 候选闭合了这一级：

- 54/54 observations 全部 post-init accepted；
- 1 条 lineage 成为 MapPoint；
- 42 observations 与 MapPoint 关联；
- bridge-on 消费 37 次 assisted matches；
- keyframe observations 从 bridge-off 的 23 增加到 27。

因此“final-online lineage 能否在另一数据域进入 ORB 持久状态”已经从未知推进为 supported。

### 2.2 没有闭合的问题

v23 每轮执行 214 次 scans，但 assisted outlier/purge 为 `0/0`。`full` 与 `full_unbounded` 的 reconstructed/online 轨迹四轮逐字节相同。

轨迹也是混合结果：

| Trajectory | v23 APE vs native | v23 RPE vs native |
| --- | ---: | ---: |
| Reconstructed | `-3.098%` | `+5.679%` |
| Online | `-0.599%` | `+4.730%` |

因此 AFRL 不是精度正例，不是 strict reconstructed no-harm，也不是 v23 action-positive。

### 2.3 新的 ORB 机制边界链

当前 ORB 证据可整理为：

1. **A10 `2400-2800`：** post-init reachability、assisted outlier、pre-KF purge、轨迹双指标改善全部成立，当前唯一完整机制正例；
2. **NTNU `s30,d10`：** seed accepted，但 0 MapPoint/assisted/action，属于 guard 上游 reachability null；
3. **AFRL Gennie `s0,d20`：** MapPoint 与 assisted consumption 成立，但 0 outlier/purge，属于 action-opportunity null；
4. **NTNU `s50,d20` normal：** 0 learned injection，12 arms reconstructed/online exact no-harm。

这条链比单独增加一个正例更有解释力：它把 `birth -> MapPoint -> assisted match -> outlier -> purge -> trajectory` 的每一级都对应到了真实证据或真实缺口。

## 3. 对 7 月 30 日项目判断的修订

### 强化

- “post-init persistent-state reachability 是 ORB 迁移必要条件”得到 AFRL 正向验证；
- “后端 observation contract 决定 learned lineage 的作用”进一步被 bridge-off/bridge-on 大差异支持；
- “机制计数必须与轨迹指标分开”再次被 full/unbounded 精确相同支持。

### 收窄

- 原 P0 “第二域 post-init MapPoint/action”只完成了 MapPoint 与 assisted consumption，action 仍未完成；
- 不能把 bridge rescue 写成 v23 purge rescue；
- 不能因 APE 略好忽略 RPE 恶化。

## 4. 当前最高优先级

1. 停止 AFRL Gennie 重复与调参；
2. 下一低纹理候选必须在 frozen smoke 中自然出现 `assisted_outliers > 0`，否则不进入正式四轮；
3. 保留 NTNU normal exact no-harm，不为补救 AFRL 结果重开正常纹理 profile；
4. 继续推进原总报告中的 MSCKF 跨域、ORB A09 完整窗和盲测任务；
5. 开始把 ORB 四级边界链整理进论文 Experiments/Discussion，而不是继续产生 v24+ 机制分支。

## 5. 新增资产

- AFRL transfer report：`orb_v23_crossdataset_afrl_20260731/2026-07-31--orb-v23-crossdataset--r01--transfer-summary.md`
- 严格分析：`orb_v23_crossdataset_afrl_20260731/analysis-output/analysis-report.md`
- 统计附录：`orb_v23_crossdataset_afrl_20260731/analysis-output/stats-appendix.md`
- 图目录：`orb_v23_crossdataset_afrl_20260731/analysis-output/figure-catalog.md`
- provenance：`orb_v23_crossdataset_afrl_20260731/analysis-output/provenance.json`
- 分析脚本：`../scripts/analyze_orbslam3_v23_afrl_gennie.py`

## 最终增量判断

**AQUA-FE 的 ORB 外部效度取得了真实进展，但不是通过新增精度正例，而是通过把跨域失败点从 pre-init reachability 推进到 assisted-outlier opportunity。项目现在应停止在已回答窗口上继续调 v23，转向一个自然 action-positive 候选，或接受“A10 完整机制正例 + NTNU/AFRL 分级边界 + normal exact no-harm”作为论文的诚实证据结构。**
