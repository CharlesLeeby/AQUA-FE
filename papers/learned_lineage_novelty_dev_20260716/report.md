# KLT 空间新颖性 learned-lineage 开发报告（2026-07-16）

## 结论

本轮在不修改冻结 7 文件、不改变既有 learned-active 分支的前提下，验证了一条新的
开发路径：保留完整 KLT bag，只把活过 5 帧、相对 KLT 空间覆盖足够新颖的 XFeat
seed lineage 重映射到独立高 ID 后追加。初始化期最多选择 1 条 lineage。

AQUALOC A08 `6800-7200` 得到一个稳定开发正例。自动规则选择原 ID `378`，重映射为
`10000000`，注入 27 帧。5 次独立 VINS 复放中，full 的 APE/RPE 均为 `5/5` 胜：

- KLT 中位数：`0.163099 / 0.225271`；
- full 中位数：`0.157140 / 0.224854`；
- 中位改善：APE `3.654%`，RPE `0.185%`；
- full APE/RPE 标准差均约 `1e-6`，coverage 为 `1.0`，无 solver failure。

该结果是默认关闭的开发证据，尚未回填冻结 20 簇分母，也尚未成为在线 final profile。

## 冻结边界

冻结 7 文件 SHA-256 保持不变：

```text
82bd47f0... scripts/run_xfeat_seedchain_arbitrated_eval.sh
8b2db28e... scripts/run_learned_seedchain_eval.sh
de78c825... uw_frontend/ros/export_vins_features.py
4500894e... paper_vins_safe_learned_sidecar.yaml
745d8c5c... filter_feature_bag_by_channel.py
ef68c19a... evaluate_vins_sim_ape.py
b994676b... evaluate_vins_tum.py
```

源码快照：
`/mnt/data/AQUA-FE_WS/backups/frozen_frontend_source_20260716_before_adaptive_dev.tar.gz`，
SHA-256 为 `7e13b845a2d7b88dc3b20c9ad2df89c2506e80ebaf89bb25772bdd13ae4af21c`。

本轮只修改了非冻结工具 `scripts/inject_feature_sidecar.py`，新增选项默认关闭：

- `--include-learned-track-lineage`；
- `--max-track-lineages`；
- `--lineage-rank-observations`；
- `--lineage-min-median-base-distance-px`。

默认旧参数在修改前后生成的 200 个 feature frames 逐点、逐 channel 完全一致。

## 根因诊断

### post-quality cap 会留下 KLT 名额空洞

A10 `400-800` 的 cap=2 probe 通过 frozen old-contract，但原 final 使用非 mirror
classical backbone，full/drop 均明显输给 fresh KLT。切到 mirror 后发现，learned
候选先占据配额，再被 post-quality cap 删除，frame 2-5 分别少了 `8/6/4/2` 个 KLT
点。仅看 feature 数、grid 和 age 的中位数无法发现这个问题。

### mirror learned ID 与 KLT ID 冲突

mirror learned 使用低 ID 空间，首个 learned 帧的 ID `466/467` 与 fresh KLT ID
重合，不能直接把缺失 KLT 补回。将 learned ID 重映射到 `10000000` 以上后，可构造
完整 KLT 加独立 sidecar；whole-lineage drop 后与 KLT `200/200` 帧完全一致。

### 轨迹长不等于有效

A08 的两条候选 lineage 分别为 27 帧和 78 帧。两条同时注入时 full 有 `3/5` 次进入
APE `0.5555` 的坏分支。逐条消融后：

- 27 帧轨迹：APE/RPE `5/5` 胜；
- 78 帧轨迹：APE/RPE 仅 `3/5` 胜，存在双峰波动。

两者的 q、运动量和寿命都不能正确排序。真正有区分度的是相对 KLT 的空间新颖性：

- 27 帧好轨迹前 5 次观测的最近 KLT 距离中位数：`171.703 px`；
- 78 帧不稳定轨迹：`15.747 px`。

## 开发规则

本轮统一使用以下规则，不增加窗口专用签名：

1. learned seed 必须形成至少 5 帧的 KLT lineage；
2. 只用前 5 次观测计算与同帧 base KLT 最近点的像素距离中位数；
3. 距离低于 `40 px` 的 lineage 拒绝；
4. 初始化阶段最多选择 1 条 lineage，按上述距离降序；
5. learned ID 重映射到独立高 ID，完整 350 点 KLT backbone 不被替换。

该规则自动得到：

| 窗口 | 自动选择 | 结果 |
|---|---:|---|
| A08 `6800-7200` | ID 378，`171.703 px`，27 帧 | 稳定开发正例 |
| A05 `2000-2400` | 0 条；最高 `27.761 px` | 输出与 KLT `200/200` 帧相同 |
| A10 `0-400` | 0 条；最高 `18.580 px` | 输出与 KLT `200/200` 帧相同 |
| A10 `400-800` | 0 条；最高 `22.779 px` | 输出与 KLT `200/200` 帧相同 |
| A03 `4000-4400` | ID 386，`103.393 px`，62 帧 | 中位打平，但有一次 14-16% 退化 |

A03 表明空间新颖性是必要但仍非充分条件，后续还需加入初始化几何一致性或在线残差。

## 重复实验

统一使用 `/home/ma/SLAM/VINS-Fusion-origin`、`VINS_MULTIPLE_THREAD=0`、
`PLAY_RATE=1.0`、`WAIT_FOR_VINS_SUBSCRIBERS=1`、APE `max_match_dt=0.6s` 和 1 秒 RPE。

详细表：`papers/learned_lineage_novelty_dev_20260716/repeat_summary.csv`。

146 个 fresh probe 的逐 lineage 扫描表：
`papers/learned_lineage_novelty_dev_20260716/lineage_novelty_screening.csv`。表内共
265 条活过 5 帧的 lineage，其中 44 条通过 40 px 前端筛选；这 44 条只是待补 fresh
KLT/VINS 的候选，不等于 44 个正例。

主要 artifact：

- A08 自动 full bag：`/mnt/data/AQUA-FE_WS/adaptive_dev_20260716/a08/klt_plus_auto_novel_lineage.bag`；
- A08 5 次单 lineage 日志：`/mnt/data/AQUA-FE_WS/adaptive_dev_20260716/a08/single_lineage_repeats/`；
- A05/A10 no-harm bag：`/mnt/data/AQUA-FE_WS/adaptive_dev_20260716/`；
- A03 压力窗口：`/mnt/data/AQUA-FE_WS/adaptive_dev_20260716/a03_4000_4400/`。

## 下一步边界

当前证据支持继续实现在线版本，但不支持现在切换默认系统。在线化时必须：

1. 仅在 frozen arbitration 已决定 `klt_safe_fallback` 后尝试 novelty rescue；
2. 保持完整 mirror KLT，不让 learned 候选预占后又留下空配额；
3. 使用独立 learned ID 命名空间；
4. 活过 5 帧后再按因果的前 5 帧新颖性选择 1 条 lineage；
5. 对 11 个 learned-active 正例做 fresh 回归，通过后才允许进入默认配置。
