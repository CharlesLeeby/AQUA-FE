# HFNet-SLAM 多窗口严格比较协议 v1

状态：`SUPERSEDED_BY_HFNET_MULTIWINDOW_COMPARISON_PROTOCOL_V2`

> 本 v1 及其 companion schema/CSV 已由 v2 整体取代。原因是随后冻结的执行协议确认 H07 与新 A02 必须因 shifted-IMU predecessor 边界从 source frame 1 开始，且新 A02 是 `feed 1..6300 / score 4500..6300` 的 additive full-history protocol。不得再用 v1 指导执行或分析。

日期：2026-08-22（Asia/Shanghai）

本文件只冻结分析问题、窗口、指标和有效性门。它不授权启动、重试、覆盖、移动或删除任何实验，也不修改任何既有 sealed artifact。P07 的 240-replay STOP 继续有效。

## 1. 要回答的问题

第一问题是外部 learned whole-system `HFNet-SLAM` 在多个已用 AQUALOC 窗口上的系统可用性，而不是谁的 APE 最小：

1. 系统是否只启动一次并正常退出；
2. 是否在预冻结评分窗内及时产生连续、有限、严格递增的轨迹；
3. 评分窗覆盖、首输出延迟、最长连续段和关键帧支持如何；
4. 只有历史、评分支持、参考和评估器全部一致时，是否允许打开描述性 accuracy 门。

分析单元是 `window`，不是 pose、frame、grid point、RPE pair 或 keyframe。当前候选只有 3 个开发暴露窗口，且两个来自 AQUALOC archaeology；因此禁止显著性检验、置信区间式总体外推、平均值赢家、跨窗 superiority 和逐 pose 伪重复。

## 2. 预冻结窗口集

| window_id | feed | pre-roll | score | score frames | native proxy rows | 当前 HFNet 状态 | accuracy 状态 |
|---|---:|---:|---:|---:|---:|---|---|
| `A06_2210_2460` | `0..2460` | `0..2209` | `2210..2460` | 251 | 13 (`2220..2460`, step 20) | `PASS_EXPLORATORY_UNDERWATER_USABILITY`；251/251 score poses，27 score KFs | `BLOCKED`: 旧 AQUA-FE/KLT 为 2210 冷启动，历史不一致；native proxy <30 |
| `H07_1660_1720` | 建议固定 `760..1720` | `760..1659`（900 frames） | `1660..1720` | 61 | 13 (`1660..1720`, step 5) | `PENDING_NOT_STARTED` | `BLOCKED`: 旧 AQUA-FE/KLT 为 1660 冷启动；score 约 3 s、native proxy <30 |
| `A02_5400_6300` | `4500..6300` | `4500..5399`（900 frames） | `5400..6300` | 901 | 46 (`5400..6300`, step 20) | 既有 terminal `HEADLESS_RUN_FAILED_OR_UNUSABLE` | `BLOCKED_UNUSABLE`: HFNet 只有 22 score poses/1.052 s，禁止同窗重试 |

H07 的 `760..1720` 是本协议建议的可落地 feed：它保留与 A02/H03 相同的 900-frame（约 45 s）pre-roll，并让 `1660..1720` 评分窗只出现一次。若执行方采用其他历史起点，必须另立版本；不得仍标作本协议的 H07 行。

## 3. Primary usability metrics

按以下固定顺序报告每个 `window × method × attempt`：

1. `usability_status`: `PASS | FAIL | PENDING | NOT_RUN`；
2. `score_coverage_fraction = score_pose_count / score_frame_count_expected`；
3. `score_first_output_delay_s`，相对 score start；无输出时为空并给 censor reason；
4. `score_longest_contiguous_fraction` 与 `score_gap_count`；
5. `score_pose_count`、`keyframe_score_count` 和 `score_trajectory_span_s`；
6. `process_start_count`、`retry_count`、`raw_returncode`、`timed_out` 和 wall time；
7. `failure_code`，用于区分算法不可用、基础设施失败和未执行。

`PASS` 的最低门为：一次启动、零重试、无 timeout、raw RC=0；轨迹存在且全部有限、严格递增、唯一关联；评分覆盖至少 0.70，最长连续比例至少 0.70，评分窗至少一个关键帧。基础设施失败不得伪装为算法失败；算法失败不得因为 RC=0 被改成 PASS。

当前只有 3 个开发窗口。可汇报 `usable k/3` 和逐窗原始值，不做显著性、总体成功率 CI 或 method winner。

## 4. A02 冷启动负结果的固定呈现

A02 必须显示为真实、非零但不足的输出：

- official child `raw_returncode=0`，一次启动、无 timeout、无重试；
- frame trajectory 22 poses，全部落在 score 内，score coverage `22/901 = 0.0244173140954495`；
- frame trajectory span `1.051619328 s`；
- keyframe trajectory 6 poses，span `2.000256768 s`；
- terminal status `HEADLESS_RUN_FAILED_OR_UNUSABLE`；
- fixed failure code `LATE_INITIALIZATION_INSUFFICIENT_SCORE_SUPPORT`；
- `accuracy_state=BLOCKED_UNUSABLE`，APE/RPE 必须为 JSON `null` / CSV 空字段。

禁止把缺失 APE/RPE 填成 `0`、`Inf`、最大惩罚值或排在数值榜末。也禁止把 RC=0 写成系统成功。该结果进入 usability matrix 和 timeline，但不进入 accuracy bar chart。既有 exact A02 attempt 是 terminal、zero-retry；多窗口工作不得再跑同一 feed/score/attempt。

## 5. Accuracy 开门条件

一项 accuracy 对比只有在同一窗口的所有待比 arms 同时满足以下条件时才可计算：

1. `usability_status=PASS`；
2. raw history 起止、pre-roll、score 起止及边界包含语义相同；
3. score 内相机输入相同，时间戳/时移、pose convention、body-camera 外参和尺度语义已锁定；
4. 使用同一 reference payload 与同一 evaluator identity；
5. native reference rows ≥30、common grid ≥30、common span ≥10 s、common coverage ≥0.70；
6. APE 有效且有限；1 s RPE 至少 10 pairs 且有效、有限；
7. 固定尺度 `SE(3)` 评估，不用 `Sim(3)` 隐藏尺度错误；
8. 方法输入频率不同可保留 method-native，但必须并列报告 input frames/rate，且共同评分网格相同。

任一条件失败时：`accuracy_state=BLOCKED`，填写穷尽式 `accuracy_block_codes`，APE/RPE 留空。不得只挑共同支持较好的方法，也不得缩窗、移动窗或改变阈值来救结果。

三个现有窗口均不能形成 HFNet-vs-AQUA-FE accuracy 排名：

- A06：HFNet 有 `0..2209` 历史，旧 KLT/AQUA-FE 从 2210 冷启动；且 native proxy 只有 13 行；
- H07：建议 HFNet 有 900-frame pre-roll，旧 KLT/AQUA-FE 从 1660 冷启动；总 score 约 3 s、native proxy 13 行；
- A02：历史和 45-point grid 对 B1/XFeat 已一致，但 HFNet unusable，故三臂 accuracy 门关闭。

A02 的现有 B1-vs-XFeat 结果可作为单独的、post-incident/result-informed component contrast：B1 APE/RPE `0.2213452229/0.0270780274 m`，XFeat-birth/raw-LK `0.1549902960/0.0179516822 m`，45 common grid、44 RPE pairs。它使用 same-image COLMAP+depth proxy，不是独立 ground truth；HFNet 被排除，因此不能升级成 whole-system 三臂排名或 superiority。

## 6. Legacy AQUA-FE 数值的边界

A06 旧结果（KLT `0.268486/0.113326 m`，proposed mirror-inject `0.058071/0.048803 m`）和 H07 旧结果（两臂约 `0.050207/0.113417 m`）可以作为窗口已被本项目运行过的 provenance。它们不得与新 HFNet 行在同一 accuracy 排名表中，因为历史不一致；H07 还只有 16 matched estimates、1.503 s output 和 6 RPE pairs。

若以后需要真正的 head-to-head accuracy，应先让 KLT 与 AQUA-FE 使用与外部系统完全相同的 feed/history，再以新命名空间通过本文件第 5 节；旧数值不得回填。

## 7. 表和图的固定设计

允许的主表：每行一个 `window × method × attempt`，先列 usability，再列 accuracy gate；所有 accuracy-blocked 行保持空值并显示 block code。

允许的图：

1. `usability_matrix`: window × method tile，颜色只表示 PASS/FAIL/PENDING，格内标 score coverage；
2. `score_support`: 每窗 expected vs produced score poses，标 coverage 和最长连续比例；
3. `initialization_timeline`: pre-roll、score、first output、continuous trajectory span；A02 必须直观看出 late initialization；
4. `accuracy_panel`: 只有 gate-open arms 才生成。当前不得生成 HFNet 三窗 accuracy 图；A02 B1-vs-XFeat component-only 图必须独立放置并标 proxy/non-independent。

禁止的图：跨窗平均 APE 排名、把 FAIL 当数值惩罚的 bar、逐 pose error 当独立样本的 violin/显著性图、只有成功窗的 cherry-picked winner 图。

## 8. 绑定证据

- A06 HFNet result: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_archaeology_a06_0000_2460/attempt_001/run_result.json`
- A02 HFNet terminal result: `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json`
- A02 two-arm common support: `/home/ma/AQUA-FE_WS/papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_adopted_v2_5_r1/common_support_summary.json`
- A06 legacy summary: `/home/ma/AQUA-FE_WS/logs/may22_sparse_vs_mirror_learning_contribution.csv`
- H07 legacy KLT: `/home/ma/AQUA-FE_WS/logs/aqualoc_real_vins/external_klt_every2_may22_mirrorinject_h07_1660_1720_klt/ape.txt`
- H07 legacy proposed: `/home/ma/AQUA-FE_WS/logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_h07_1660_1720_loftr/ape.txt`
- STOP authority: `/home/ma/AQUA-FE_WS/papers/2026-08-08--codex-STOP-and-redirect.md`

机器字段由 `papers/hfnet_multiwindow_result_schema_v1.json` 定义；CSV 入口模板为 `papers/hfnet_multiwindow_results_template_v1.csv`。
