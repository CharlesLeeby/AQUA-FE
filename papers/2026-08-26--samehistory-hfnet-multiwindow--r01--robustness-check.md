---
type: results-report
date: 2026-08-26
experiment_line: samehistory-hfnet-multiwindow
round: 1
purpose: robustness-check
status: complete-development-only
source_artifacts:
  - /mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/analysis_bundle.json
  - /mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/result_manifest.json
  - /mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/analysis-report.md
  - /mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/stats-appendix.md
  - /mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/figure-catalog.md
  - /mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/analysis_bundle.json
  - /mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/result_manifest.json
  - /mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/analysis-report.md
  - /mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/stats-appendix.md
  - /mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/figure-catalog.md
  - papers/hfnet_positive_natural_history_summary_v1.md
  - papers/hfnet_positive_natural_history_summary_v1.json
linked_experiments:
  - papers/a06_samehistory_harmonized_common_support_diagnostic_v1_protocol.md
  - papers/a10_samehistory_user_waived_common_support_diagnostic_v1_protocol.md
linked_results:
  - papers/a06_samehistory_harmonized_common_support_diagnostic_v1_freeze.json
  - papers/a10_samehistory_user_waived_common_support_diagnostic_v1_freeze.json
  - papers/hfnet_positive_natural_history_summary_publication_freeze_v1.json
---

# Same-History HFNet Multiwindow / Round 1 / Robustness Check / 2026-08-26

## 1. Executive Summary

本轮把外部 learned whole-system baseline HFNet-SLAM 放到三个既有 KLT 正例窗口的自然历史输入上，并在其中两个具备同历史、可作 development-only sensitivity analysis 的窗口上执行统一的 fixed-scale SE(3) 共同支持评测。

当前最高置信度结论有两个。第一，HFNet-SLAM 在这三个选择性 AQUALOC 自然历史评分窗中均形成完整评分轨迹，覆盖分别为 `251/251`、`401/401`、`401/401`；这只排除了“HFNet-SLAM 在这三个指定评分窗中无法形成完整评分轨迹”的窄担忧。第二，A06 与 A10 的数值关系方向不同：HFNet 相对 Vanilla 的误差关系在两个窗口间反转，说明两窗结果不支持一个跨窗口通用排名。

这改变了下一步决策：HFNet 应保留为外部 learned system baseline；但当前 A06/A10 只能作为开发性描述，不应用来宣称 AQUA-FE、KLT、Vanilla 或 HFNet 的总体优越性。下一项高价值工作是补齐 A09 的 `0..4400` Vanilla/KLT/AQUA-FE 同历史链，并寻找具有至少 30 个 proxy-GT 支持点且确有 learned action 的更长评分段。

## 2. Experiment Identity and Decision Context

本报告属于 `samehistory-hfnet-multiwindow` 实验线第 1 轮。此前的不确定性是：

- 外部 learned SLAM 是否能在 AQUALOC 水下序列上真正运行，而不只是前端 matcher 离线打分；
- 它与同历史 Vanilla/KLT/AQUA-FE 轨迹放在相同评分窗口和共同支持上后，数值处于什么范围；
- 当前证据能否归因于 AQUA-FE 的 learned frontend。

窗口不是随机抽样，而是既有开发结果条件化的 KLT 正例窗口。报告对象是运行性和描述性 robustness check，不是总体性能估计。

## 3. Setup and Evaluation Protocol

三个 HFNet 自然历史输入均从源帧 0 送入评分窗：A06 `0..2460 → 2210..2460`，A10 `0..2800 → 2400..2800`，A09 `0..4400 → 4000..4400`。A06 与 A10 具备可用于 development-only sensitivity analysis 的同历史四臂轨迹；A09 目前只具备 HFNet warm-history 轨迹，缺少三条 `0..4400` VINS 轨迹。

A06/A10 的统一评测协议为：

- 1 Hz uniform grid；
- reference interpolation gap 不超过 2.5 s；estimate gap 不超过 0.25 s；
- 四方法与 reference 的单一共同 intersection mask；
- 每臂独立进行 rigid fixed-scale SE(3) 对齐，应用 `body_T_cam0`；
- 禁止 Sim(3)、尺度修正、拟合时间偏移和旧式稀疏 GT 重复最近邻；
- exact 1 s positional RPE，只在连续共同 segment 内计算；
- `evo 1.31.1` 独立复核，容差 `1e-5 m`。

参考是同图像来源的 COLMAP/depth-scale proxy，不是独立外部真值。指标方向为数值越小表示对该 proxy 的描述性误差越小，但本轮不据此计算排名。

协议偏离与保留边界：A06 的 KLT 是未重算前端的 additive corrective replay，原 censored receipt 保留；A10 的 KLT 子进程 RC0、artifact/score PASS，但原回执因 postflight ambient process 保持 `EXECUTION_INTEGRITY_FAILED`，本轮仅按用户授权进入 development-only sensitivity analysis。

## 4. Main Findings

### 4.1 自然历史运行性

| 窗口 | HFNet feed → score | Score poses | Score keyframes | 前缀 reset | Score 内 init/reset | 运行性终态 |
|---|---|---:|---:|---:|---:|---|
| A06 | `0..2460 → 2210..2460` | 251/251 | 27 | 0 | 0/0 | `PASS_EXPLORATORY_UNDERWATER_USABILITY` |
| A10 | `0..2800 → 2400..2800` | 401/401 | 30 | 22 | 0/0 | `PASS_DEVELOPMENT_RUNABILITY_RESCUE` |
| A09 | `0..4400 → 4000..4400` | 401/401 | 33 | 25 | 0/0 | `PASS_DEVELOPMENT_RUNABILITY_RESCUE` |

这里的运行性 `PASS` 只表示评分窗轨迹覆盖完整，不表示从源帧 0 到评分窗之间存在不间断历史。A10 与 A09 的前缀分别发生 22 和 25 次 reset，因而完整评分轨迹不能被扩写为完整连续 warm-history。

三次 cold-start 诊断均未形成轨迹或关键帧。这些失败值是 `NA`，不是零误差；它们只说明在这三个指定短评分窗中，先前输入历史会影响 HFNet 能否形成完整评分轨迹，不能外推为 HFNet 的一般历史依赖结论，也不能把 cold-start 与自然历史结果混表。

### 4.2 两个同历史窗口的描述性误差

下表按预冻结的窗口和方法顺序展示 `APE RMSE / exact-1s RPE RMSE`，单位为米。没有按结果排序。

| 窗口与支持 | 方法 | APE RMSE | 1 s RPE RMSE | 证据角色 |
|---|---|---:|---:|---|
| A06, 13/13 grid, 12 RPE pairs | Vanilla | 0.163255 | 0.050010 | development-only |
| A06, 13/13 grid, 12 RPE pairs | External KLT corrective | 0.167771 | 0.050465 | development-only corrective |
| A06, 13/13 grid, 12 RPE pairs | AQUA-FE | 0.164408 | 0.049598 | no-learned-action/no-harm only |
| A06, 13/13 grid, 12 RPE pairs | HFNet-SLAM | 0.495422 | 0.145196 | external learned system diagnostic |
| A10, 20/20 grid, 19 RPE pairs | Vanilla | 1.581690 | 0.278818 | development-only |
| A10, 20/20 grid, 19 RPE pairs | External KLT | 0.599622 | 0.111452 | user-waived failed-receipt sensitivity |
| A10, 20/20 grid, 19 RPE pairs | AQUA-FE | 0.606411 | 0.112709 | prefix-history effect only |
| A10, 20/20 grid, 19 RPE pairs | HFNet-SLAM | 0.887128 | 0.156968 | external learned system diagnostic |

最重要的跨窗观察不是“谁赢”，而是数值关系不稳定：A06 中 HFNet 的 APE/RPE 数值高于 Vanilla，A10 中则低于 Vanilla。因此，仅凭这两个选择性窗口无法形成通用系统排序。

对 AQUA-FE 贡献的观察也有限。A06 的 AQUA-FE 与 KLT feature payload 字节相同，learned export 为 0；A10 的 61 个新增 observation 全部发生在评分窗前，评分窗内新增为 0，而且 A10 中 AQUA-FE 与 KLT 的 APE/RPE 仅相差约 1.13%。这两窗都不能证明 score-frame learned action 带来精度收益。

## 5. Statistical Validation

每个窗口每种方法只有一条既有轨迹，推断意义上的样本量是 `n=1`。13 或 20 个时间网格点是相关轨迹样本，不是独立重复。窗口本身又由既有 KLT 正例条件化，不能当作随机总体样本。

因此本轮没有计算置信区间、显著性检验、效应量推断、多重比较校正或跨窗平均。A06 和 A10 的正式 APE gate 均关闭：A06 有 13 条原生 proxy 行、13 个插值评估网格点；A10 有 21 条原生 proxy 行、20 个评估网格点；两者都低于冻结的 30-pose minimum。描述性 RPE gate 分别以 12 和 19 对通过。

数值实现通过双重验证：A06 的 `evo` 最大 APE/RPE 差为 `2.93e-7 / 3.23e-7 m`；A10 为 `4.89e-7 / 4.71e-7 m`，均远低于 `1e-5 m`。独立只读审计还逐文件验证了两个输出树各 30 个登记产物的尺寸和 SHA-256。

## 6. Figure-by-Figure Interpretation

本轮没有生成主图。两个严格分析 bundle 的 figure catalog 都说明：在没有重复运行和不确定性估计时，固定顺序的精确表比无 error bar 的柱状图更诚实、更易审计。上面的两张表分别承担运行性映射和同窗口数值映射；不应把它们重画成暗示总体排名的图。

## 7. Failure Cases / Negative Results / Limitations

- A09 尚无 `0..4400` raw ROS bag、KLT full-history feature bag、因果 AQUA-FE full-history bag和三条 VINS 轨迹，因此不能与 HFNet 做公平同历史精度比较；之后还需完成 epoch-canonical HFNet pose bridge 和冻结的四臂共同支持评测。A09 的评分窗仅有 21 条原生 proxy 行，因此即使补齐 VINS 轨迹，冻结的 30-pose 正式 APE gate 仍将关闭。
- A09 的现有 `4000..4400` cold-start VINS 输入不能拼接到 warm-history 前缀；feature ID、KLT 状态和 learned lineage 均依赖历史。
- A06 没有实际 learned observation 进入后端，不能作为学习增强收益证据。
- A10 的 learned additions 只在 prefix；其 KLT 回执仍是执行完整性失败，本轮数值不能升级为正式三臂结果。
- 两个评分窗均不足 30 个 proxy 支持点，且 reference 与被评估方法共享图像来源。
- HFNet 三次 cold-start 均不可用；在这三个指定短评分窗中，先前输入历史影响其能否形成完整评分轨迹，但不能外推为一般系统属性。
- 目前没有独立重复、独立真值或随机窗口抽样，无法支持显著性、泛化或总体 superiority。

## 8. What Changed Our Belief

本轮加强了一个受限判断：HFNet-SLAM 在这三个选择性 AQUALOC 自然历史评分窗中能够形成完整评分轨迹，因此值得继续验证其作为系统级 baseline 的可用性，而不是仅因 cold-start 失败就只放在 Related Work 中。

本轮削弱了两个过强假设。其一，“某一种系统在 KLT 正例窗口中稳定占优”没有得到支持，因为 HFNet 与 Vanilla 的数值关系在 A06/A10 反转。其二，“当前系统轨迹差异已经证明 AQUA-FE 的 learned frontend 有效”没有得到支持，因为 A06 无 learned action，A10 也没有 score-window direct action。

仍未解决的是：在真实 learned observation 进入后端、执行回执完整、评分段更长的条件下，AQUA-FE 相对 Vanilla、KLT 和外部 learned system 的稳定贡献有多大。

## 9. Next Actions

1. 继续：本地物化 A09 `0..4400` raw bag，顺序生成 KLT、因果 AQUA-FE 和三条 VINS warm-history 轨迹；工程估计新增 1.2–1.4 GB、耗时约 2–3 小时，不是测得的资源结果。
2. 补强：为 A10 运行一个执行完整性正式通过的 KLT 后端结果，保持现有失败回执不变。
3. 选择新窗口：优先至少 30 个原生 proxy 点的更长评分段，并要求 AQUA-FE 在评分段内确有非零 learned export。
4. 保留 HFNet：三窗口运行性可以作为外部系统 baseline 的开发证据；精度表只保留在内部/补充性诊断层级。
5. 停止：不再把 cold-start VINS 与 warm-history HFNet 混排，不再使用旧 `ape.txt` 稀疏最近邻结果做跨系统排名，不再从 A06/A10 推导 learned-benefit 或总体 superiority。
6. 稿件状态：当前受限运行性描述只保留为内部 development-only 记录；在正式协议、完整回执与稿件证据冻结前，不形成 manuscript-facing claim。系统精度 superiority 和 learned frontend contribution 均不进入主文结论。

## 10. Artifact and Reproducibility Index

- A06 protocol: `papers/a06_samehistory_harmonized_common_support_diagnostic_v1_protocol.md`
- A06 runner: `scripts/run_a06_samehistory_harmonized_common_support_diagnostic_v1.py`
- A06 freeze: `papers/a06_samehistory_harmonized_common_support_diagnostic_v1_freeze.json`, SHA-256 `1ce2d7ef2497c5b4a63b15ff632c6ecfffab2de893c2d60db8af6aafad4aa56b`
- A06 output: `/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1`
- A06 analysis bundle: `/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/analysis_bundle.json`
- A06 result manifest: `/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/result_manifest.json`, SHA-256 `9fb04609b378734df87c2590afd35db2a09a46cbd82a75f8214d22eee521e49b`
- A10 protocol: `papers/a10_samehistory_user_waived_common_support_diagnostic_v1_protocol.md`
- A10 runner: `scripts/run_a10_samehistory_user_waived_common_support_diagnostic_v1.py`
- A10 freeze: `papers/a10_samehistory_user_waived_common_support_diagnostic_v1_freeze.json`, SHA-256 `23a49d14e271f6e68b688e4c484e04f1f8eda97993051a09df50daf528eb2b04`
- A10 output: `/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1`
- A10 analysis bundle: `/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/analysis_bundle.json`
- A10 result manifest: `/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/result_manifest.json`, SHA-256 `33f8e790e79cf45348d53fe19138c4423a17f1907b23fb2e46c38adbea0a159a`
- HFNet three-window runability: `papers/hfnet_positive_natural_history_summary_v1.md`, SHA-256 `2afa3dfef2ecaf5704f9a76776ffe5ebdc9a2cfd89b43a9676bea734c5f2b673`
- HFNet machine-readable summary: `papers/hfnet_positive_natural_history_summary_v1.json`, SHA-256 `ec984c53af5622bc58ec3ddbf22a33173ed3df80a4ac8e7f54acda8b8691c17f`
- HFNet publication freeze: `papers/hfnet_positive_natural_history_summary_publication_freeze_v1.json`, SHA-256 `fda84e99719c7e1ec8738b4382607541cfeb255ec31b1ec58c5da5e01c99415e`
- Epoch evaluator: `scripts/evaluate_vins_common_support_epoch_v2.py`, SHA-256 `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91`
- Core evaluator: `scripts/trajectory_eval_core.py`, SHA-256 `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635`

This repository is not bound to an Obsidian project knowledge base; no Obsidian write-back was attempted.
