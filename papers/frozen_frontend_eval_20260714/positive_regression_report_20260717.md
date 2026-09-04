# 冻结正例回归报告（2026-07-17）

## 结论

本轮验证了 7 月 14 日 frozen learned-active 队列在最新 causal-lineage 开发后是否
退化。清单中的 33 个 full/drop/KLT feature bag 全部存在，SHA-256 为 `33/33`
与冻结结果一致。冻结 7 个算法文件哈希也保持不变。

冻结 learned-active 队列共 11 个窗口，其中 10 个原本满足 full APE 不高于 drop
和 KLT，A09 `5000-5400` 原本就是 full 优于 drop、但输 KLT 的已知反例。统一
replay-only fresh 后：

- 10/10 个既有正例全部保留；
- 8/8 个主 learned-active 正例全部保留；
- 2/2 个 secondary 正例全部保留；
- A09 `5000-5400` 仍是已知反例，没有被误算为正例；
- 所有 33 路均有有效轨迹，没有 hard failure。

新开发的 A08 `6800-7200` causal-lineage 正例另有 5 次 full/KLT 回归，APE/RPE
仍为 `5/5` 胜，因此最新反例修复没有牺牲这个新增正例。

## 回归口径

- VINS：`/home/ma/SLAM/VINS-Fusion-origin`；
- `VINS_MULTIPLE_THREAD=0`；
- `PLAY_RATE=1.0`；
- `WAIT_FOR_VINS_SUBSCRIBERS=1`；
- whole-lineage drop；
- APE 时间匹配上限 `0.6 s`，RPE 间隔 `1 s`；
- full/drop/KLT 串行运行，不并发启动 VINS。

本轮不重新生成 frozen bag。原因是当前新增逻辑位于默认关闭的
`scripts/inject_feature_sidecar.py`，冻结 exporter/arbitration 未修改；33/33 bag 哈希
一致已经证明前端输入没有变化。本轮重新运行的是后端 replay 和严格评估。

## 逐窗口结果

| 窗口 | 类型 | full APE | drop APE | KLT APE | full vs KLT | full vs drop | 判定 |
|---|---|---:|---:|---:|---:|---:|---|
| A05 `3300-3700` | 主正例 | 0.358972 | 0.923639 | 0.373168 | +3.804% | +61.135% | 保留 |
| A07 `10800-11200` | 主正例 | 0.126667 | 163.811746 | 0.427872 | +70.396% | +99.923% | 保留；drop 坏分支 |
| A08 `4500-4660` | 主正例 | 0.149850 | 0.179432 | 0.200692 | +25.333% | +16.486% | 5 次中 4 次胜，中位保留 |
| A09 `6000-6200` | 主正例 | 0.111514 | 44.695044 | 4.702022 | +97.628% | +99.751% | 保留 |
| NTNU fjord_1 `s83,d10` | 主正例 | 0.072807 | 0.947025 | 0.186594 | +60.981% | +92.312% | 保留 |
| NTNU mclab_1 `s60,d15` | 主正例 | 0.440272 | 2.553927 | 0.500314 | +12.001% | +82.761% | 保留 |
| CIRS `s575,d30` | 主正例 | 1.092839 | 2.388024 | 2.410345 | +54.660% | +54.237% | 保留；solver risk |
| CIRS `s900,d30` | 主正例 | 0.876939 | 1.025768 | 0.926658 | +5.365% | +14.509% | 保留；solver risk |
| A02 `7600-8000` | secondary | 0.066754 | 0.067306 | 0.095784 | +30.308% | +0.820% | APE 正例保留 |
| NTNU mclab_2 `s110,d10` | secondary | 0.024429 | 0.024670 | 0.025279 | +3.362% | +0.977% | 弱正例保留 |
| A09 `5000-5400` | 已知反例 | 1.360407 | 1.377751 | 1.082635 | -25.657% | +1.259% | 仍输 KLT |

表中 A08 `4500-4660` 使用 5 次 replay 中位数。其逐次 APE 为：

- full：`0.192649, 0.149870, 0.149850, 0.149846, 0.149850`；
- drop：`0.179432, 0.179429, 0.179182, 0.179432, 0.179439`；
- KLT：`0.200414, 0.200686, 0.200692, 0.200693, 0.200693`。

首轮 full 进入较差初始化分支，但后四次均同时优于 drop/KLT，因此不能把单次失败
解释为正例消失。

## 稳定性限制

正例关系保留不等于 solver 风险解决：

- A07 full/drop/KLT solver failure 为 `2/26/32`；
- CIRS s575 为 `7/5/10`；
- CIRS s900 为 `17/0/4`；
- A02 `7600-8000` 为 `19/27/13`；
- mclab_2 为 `14/14/14`。

因此当前证据仍只支持精度改善或 no-harm 主张，不能声称 learned 前端普遍提高了
后端数值稳定性。

## 产物

- 33 bag 哈希审计：`positive_regression_hash_audit_20260717.csv`；
- 单次 11-case 结果：`positive_regression_results_20260717.csv`；
- 汇总表：`positive_regression_summary_20260717.csv`；
- A08 五次重复：`a08_4500_4660_repeat_results_20260717.csv`；
- replay 产物：
  `/mnt/data/AQUA-FE_WS/frozen_positive_replay_20260717/`；
- replay-only runner：`scripts/run_frozen_positive_replay_regression.sh`。

## 允许的结论

当前可以继续使用：“冻结正例在最新开发后全部保留；学习轨迹在预选低纹理窗口中
通常不弱于 KLT，并经常改善 APE。”仍不能使用“学习前端普遍优于 KLT”或“所有
低纹理窗口都能改善”，因为 A09 `5000-5400` 仍是明确 KLT 反例，且多个窗口存在
solver risk。
