# HFNet-SLAM 多窗口严格比较协议 v2

状态：`ANALYSIS_PROTOCOL_FROZEN_V2_NOT_EXECUTION_AUTHORITY`

日期：2026-08-22（Asia/Shanghai）

本 v2 取代整个 v1 bundle，但不删除或改写 v1 的历史内容。v2 绑定随后冻结的 H07 和 A02 selector；它只规定分析，不授权 HFNet 启动、重试、覆盖、移动或删除。P07 240-replay STOP 继续有效。

## 1. 四行结果表与三个当前分析单元

结果表固定四行，但当前多窗口统计单元仍只有三个：A06、H07、新 A02 full-history。旧 A02 cold-start 是同一 A02 的 legacy terminal context，不是第四个独立窗口，不得进入 `k/3` 分母或当重复试验。

| row role | window_id | feed | pre-roll | score | score frames | native proxy | 状态 |
|---|---|---:|---:|---:|---:|---:|---|
| current | `A06_SCORE_2210_2460` | `0..2460` | `0..2209` | `2210..2460` | 251 | 13 | existing PASS，251/251 score poses，27 score KFs |
| current | `H07_SCORE_1660_1720` | `1..1720` | `1..1659` | `1660..1720` | 61 | 13 | pending，new additive protocol |
| current | `A02_FULLHISTORY_SCORE_4500_6300` | `1..6300` | `1..4499` | `4500..6300` | 1801 | 91 | pending，new additive full-history protocol |
| legacy context | `A02_LEGACY_COLDSTART_SCORE_5400_6300` | `4500..6300` | `4500..5399` | `5400..6300` | 901 | 46 | terminal FAIL，22/901 score poses |

H07 精确绑定 `papers/hfnet_v6_h07_0001_1720_exact_window_selector_freeze_v1.json`。新 A02 精确绑定 `papers/hfnet_v6_a02_0001_6300_score_4500_6300_selector_freeze_v1.json`。任何 feed 或 score 边界变化必须另立协议版本，不能回填到本表。

## 2. 必须披露的同步裁剪

H07 与新 A02 都从 source camera 1 开始。校准时移施加后，source camera 0 没有 shifted-IMU predecessor；author official EuRoC entry 的读取逻辑会先递增 IMU index，再减一，因而可能得到 `-1` 并越界。source camera 1 是最早具有合法 predecessor/bracket 的帧。

固定披露：

- `sync_trim_applied=true`；
- `sync_trimmed_source_indices=0`；
- `camera0_has_shifted_imu_predecessor=false`；
- `first_fed_camera_has_shifted_imu_predecessor=true`；
- 禁止 synthetic/extrapolated IMU；
- score 窗不移动、不缩短；
- 这是输入同步安全裁剪，不是算法、阈值、初始化器或 learned model 调参。

A06 沿用已经成功的既有 `0..2460` 合同，不用 H07/A02 的同步事实反向改写。旧 A02 从 source 4500 才开始，本来就不包含 source frame 0；它不是此次 frame-0 trim。

## 3. 新 A02 不是旧 A02 重试

新协议 `feed 1..6300 / score 4500..6300` 与 legacy `feed 4500..6300 / score 5400..6300` 的历史和评分支持都不同，是 result-informed、development-only 的 additive full-history usability experiment。它有独立 selector、namespace 和单次启动权，不能称为旧 attempt retry，也不能覆盖旧 terminal。

旧 A02 保持 zero-retry terminal：official child RC0，但只有 22 个 score poses，coverage `22/901 = 0.0244173140954495`，首 frame-trajectory 输出比 score start 晚 `43.943204608 s`，trajectory span `1.051619328 s`，6 keyframes/span `2.000256768 s`。固定写作 `FAIL / LATE_INITIALIZATION_INSUFFICIENT_SCORE_SUPPORT`。APE/RPE 必须为空/null，不能填 0、Inf、惩罚值或进入 accuracy 排名。

## 4. Primary usability metrics 与 PASS 门

每行按固定顺序报告：

1. `usability_status` 和 `failure_code`；
2. `score_coverage_fraction`；
3. `score_first_output_delay_s`；
4. `score_longest_contiguous_fraction` 与 `score_gap_count`；
5. `score_pose_count`、`score_trajectory_span_s`、`keyframe_score_count`；
6. `process_start_count`、`retry_count`、raw RC、timeout、wall time；
7. sync-trim disclosure 与证据路径。

`PASS` 的最低门：一次启动、零重试、无 timeout、raw RC=0；轨迹存在、有限、严格递增且唯一关联；score coverage ≥0.70、最长连续比例 ≥0.70、score 内至少一个 keyframe。基础设施失败与算法不可用必须分开，RC0 不能单独决定 PASS。

当前窗口是开发暴露、异质且只有 n=3。可报告当前协议 `usable k/3` 与每窗原始值；不得做显著性、总体成功率 CI、mean±std、平均值 winner 或把 pose/grid/RPE pair 当独立样本。

## 5. Accuracy 门保持关闭

Accuracy 只有在所有待比较 arms 同时满足以下条件时才可打开：

1. usability PASS；
2. feed/history、pre-roll、score 边界和包含语义一致；
3. 相机输入、时间戳/时移、pose convention、body-camera 外参和 fixed-scale `SE(3)` 语义一致；
4. reference payload 与 evaluator identity 一致；
5. native reference rows ≥30、common grid ≥30、common span ≥10 s、coverage ≥0.70；
6. APE 有限有效，1 s RPE 至少 10 pairs 且有限有效；
7. method-native input rate 必须并列披露；
8. same-image COLMAP+depth reference 仍标 proxy/non-independent，只能做 descriptive accuracy，不能支撑正式 superiority。

当前四行均不能进入 HFNet-vs-AQUA-FE accuracy 排名：

- A06：旧 AQUA-FE/KLT 从 2210 冷启动，而 HFNet 有 `0..2209` 历史；native proxy 13；evaluator 未统一。
- H07：旧 AQUA-FE/KLT 从 1660 冷启动，而新 HFNet feed 从 1 开始；score 约 3 s、native proxy 13；evaluator 未统一。
- 新 A02：旧 B1/XFeat feed 是 `4500..6300` 且只 score `5400..6300`，与新 HFNet 的 `1..6300 / score 4500..6300` 同时 history/score mismatch；evaluator 未统一。
- legacy A02：HFNet unusable，三臂 accuracy 门关闭。

若要新 A02 head-to-head，必须另跑 KLT/AQUA-FE `feed 1..6300 / score 4500..6300`，不能复用现有 45-point B1/XFeat 数值。现有 A02 B1-vs-XFeat `0.221345/0.027078 m` vs `0.154990/0.017952 m` 仍只是 45-grid、post-incident、result-informed component-only proxy contrast。

## 6. 固定表图

允许：

1. 四行 usability table，并用 `row_role` 区分 current 与 legacy；
2. 三个 current windows 的 usability matrix，legacy A02 作为旁注/独立列而非第四样本；
3. expected-vs-produced score pose support 图；
4. feed/pre-roll/score/first-output timeline，突出 sync trim 与 legacy A02 late initialization；
5. 仅在 accuracy gate open 后生成 accuracy panel。

禁止：跨窗平均 APE、把 FAIL 数值插补后排名、只画成功窗、逐 pose 显著性、把新旧 A02 当两个独立窗口、当前四行 winner 图。

机器字段由 `papers/hfnet_multiwindow_result_schema_v2.json` 定义；四行 CSV 入口为 `papers/hfnet_multiwindow_results_template_v2.csv`。
