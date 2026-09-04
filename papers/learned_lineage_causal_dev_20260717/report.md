# Learned lineage 因果选择与运动一致性开发报告（2026-07-17）

## 结论

本轮把此前离线使用整段轨迹筛选 learned lineage 的做法收缩为因果选择：lineage
只有在第 5 次观测到达后才允许进入 VINS，前 4 次观测不回填。AQUALOC A08
`6800-7200` 的 XFeat lineage `378` 因此由 27 个观测变为 23 个观测，但 5 次
单线程 fresh 复放仍保持 APE/RPE `5/5` 胜。

同时发现 A03 `4000-4400` 的剩余退化与 learned 运动幅值偏离 KLT 主体运动有关。
在前 5 帧加入 learned 速度与同帧 KLT 中位速度的倍率 gate 后：

- A08 倍率为 `1.046`，低于 `1.5`，输出 bag 与已验证 causal 正例逐点相同；
- A03 倍率为 `1.697`，高于 `1.5`，自动拒绝并逐点恢复为 KLT；
- A05 `2000-2400`、A10 `0-400`、A10 `400-800` 仍为 exact no-harm。

这证明“存活确认 + 空间新颖性 + 相对 KLT 运动一致性”比仅看轨迹寿命或空间距离
更稳健，但目前仍是默认关闭的因果回放开发逻辑，不是已经接入在线 exporter 的最终系统。

## 实现边界

只修改非冻结工具 `scripts/inject_feature_sidecar.py`，新增默认关闭参数：

- `--causal-lineage-selection`：第 5 次观测确认后才发布，不回填历史观测；
- `--causal-lineage-max-motion-ratio`：以前 5 次 learned 速度相对同帧 KLT
  中位速度的倍率中位数做上限 gate。

冻结 7 文件未修改。旧参数兼容性使用 A10 `400-800` 的 8 个 XFeat 观测验证，
修改前后 200 个 feature frames 逐点、逐 channel 完全一致。

## A08 因果正例

统一口径为 `/home/ma/SLAM/VINS-Fusion-origin`、`VINS_MULTIPLE_THREAD=0`、
`PLAY_RATE=1.0`、`WAIT_FOR_VINS_SUBSCRIBERS=1`、APE 最大匹配误差 `0.6 s`、
RPE 间隔 `1 s`。

| 方法 | 重复次数 | APE 中位数 | RPE 中位数 | APE/RPE 胜次 | coverage | solver failure |
|---|---:|---:|---:|---:|---:|---:|
| KLT | 5 | 0.163098 | 0.225271 | - | 1.000000 | 0 |
| causal full，23 个观测 | 5 | 0.157138 | 0.224854 | 5/5，5/5 | 1.000000 | 0 |

相对中位 KLT，causal full 的 APE 改善 `3.654%`，RPE 改善 `0.185%`。运动倍率
gate 打开后生成的 A08 bag 与上述 causal full bag 200/200 帧完全相同，因此不会
牺牲这个正例。

## A03 压力反例

不加运动倍率 gate 时，lineage `386` 在第 5 次观测后发布 58 帧。5 次 fresh 结果为：

- full 对 KLT 的 APE/RPE 均为 `4/5` 胜；
- KLT/full APE 中位数为 `0.546949 / 0.546935`，基本打平；
- 唯一一次 paired 退化约为 APE `0.507%`、RPE `0.486%`；
- 此前非因果版本约 14%-16% 的大退化分支没有再次出现。

该 lineage 的前 5 帧运动倍率为 `1.697`。设置统一上限 `1.5` 后自动拒绝，输出
与 KLT 200/200 帧逐点相同。该 gate 没有使用窗口名称、帧号或 feature ID。

## 候选分布检查

对已有 44 条通过 `40 px` 空间新颖性筛选的 lineage 回看：

- 43 条可计算运动倍率，1 条 NTNU 候选因 velocity 信息不足无法计算；
- 倍率分布最小值/中位数/最大值为 `0.225 / 0.881 / 1.696`；
- `1.5` 上限仅拒绝 2/43 条可计算候选；
- A03 `386` 是最大值，另一个被拒绝候选来自 AQUALOC real H04 `800-1200`；
- 信息不足的候选按安全逻辑不放行。

因此 `1.5` 不是大面积清空 learned 候选的阈值，但当前有 VINS 重复证据的运动倍率
正例和反例仍各只有一个，不能据此宣称阈值已经跨数据集定型。

## 主要产物

- 逐次结果：`papers/learned_lineage_causal_dev_20260717/run_evidence.csv`；
- 重复汇总：`papers/learned_lineage_causal_dev_20260717/repeat_summary.csv`；
- 44 条候选运动倍率：
  `papers/learned_lineage_novelty_dev_20260716/lineage_motion_ratio_screening_20260717.csv`；
- A08 causal bag：
  `/mnt/data/AQUA-FE_WS/causal_dev_20260717/a08_6800_7200/klt_plus_causal_novel_lineage.bag`；
- A08 motion-gate bag：
  `/mnt/data/AQUA-FE_WS/causal_dev_20260717/a08_6800_7200/klt_plus_causal_novel_motiongate.bag`；
- A03 motion-gate no-harm bag：
  `/mnt/data/AQUA-FE_WS/causal_dev_20260717/a03_4000_4400/klt_plus_causal_novel_motiongate.bag`。

## 下一步边界

1. 先在 44 条候选中选择不与 A08 重叠、具有 fresh KLT bag 且可跑 GT 的窗口，
   用同一 `40 px + 1.5` 规则做跨数据集 VINS 验证。
2. 只有出现第二个跨数据集正例并补充多个 no-harm 后，才把逻辑以默认关闭方式接入
   在线 exporter 开发分支。
3. 在线集成必须只在既有 arbitration 已选择 `klt_safe_fallback` 后启动 rescue，不能
   替换 frozen learned-active 分支；集成后要回归 frozen manifest 中 11 个正例。
4. `1.5` 仍是开发阈值，不得写成已经充分验证的最终常数。
