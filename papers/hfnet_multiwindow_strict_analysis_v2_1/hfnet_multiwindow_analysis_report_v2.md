# HFNet-SLAM 多窗口严格分析 v2

状态：`TERMINAL_DESCRIPTIVE_ONLY`

呈现修订：`v2.1`（仅修正图 2 annotation 布局；机器结果与门控不变）。

三个 current 窗口均已终态；严格 usability 结果为 **2/3**。

分母固定为 3；legacy A02 cold-start 仅作终态上下文，不进入分母。

## 逐窗原始 usability

| role | window | strict status | producer terminal | raw/controller RC | score poses | coverage | longest contiguous | first output delay (s) | score KFs | failure code |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| current | `A06_SCORE_2210_2460` | PASS | `PASS_EXPLORATORY_UNDERWATER_USABILITY` | 0/0 | 251 / 251 | 1.000000 | 1.000000 | 0.000000 | 27 | `NONE` |
| current | `H07_SCORE_1660_1720` | PASS | `PASS_EXPLORATORY_UNDERWATER_USABILITY` | 0/0 | 61 / 61 | 1.000000 | 1.000000 | 0.000000 | 19 | `NONE` |
| current | `A02_FULLHISTORY_SCORE_4500_6300` | FAIL | `FAIL_EXPLORATORY_UNDERWATER_USABILITY` | 0/1 | 13 / 1801 | 0.007218 | 0.007218 | 89.383986 | 4 | `INSUFFICIENT_SCORE_COVERAGE` |
| legacy (excluded) | `A02_LEGACY_COLDSTART_SCORE_5400_6300` | FAIL | `HEADLESS_RUN_FAILED_OR_UNUSABLE` | 0/1 | 22 / 901 | 0.024417 | 0.024417 | 43.943205 | 6 | `LATE_INITIALIZATION_INSUFFICIENT_SCORE_SUPPORT` |

## 证据边界

- 统计单元是冻结窗口，current `n=3`；每窗只有一次冻结运行，且窗口异质、开发暴露。
- 不计算显著性检验、置信区间、跨窗 mean±std、逐 pose 推断或平均值 winner。
- accuracy gate 对四行全部关闭：history/support/evaluator 尚未统一；APE/RPE 保持 null。
- 失败行只保留实际观察到的支持；不填 0、Inf、惩罚值，也不进入 accuracy 排名。
- H07 与新 A02 的 source frame 0 裁剪是 shifted-IMU predecessor 安全边界；score 窗未移动，未使用 synthetic/extrapolated IMU。

## 图件

- `figure-01-usability-matrix-v2`: 逐门显示 PASS/FAIL，legacy 以分隔列呈现。
- `figure-02-score-support-v2`: 显示 produced/expected 支持，失败保留观测值。
- `figure-03-feed-score-timeline-v2`: 显示 feed、pre-roll、score、sync trim 与 first output。

## 当前允许结论

本 bundle 只回答外部 learned whole-system 在各冻结窗口是否达到 usability 门。它不支持 HFNet 与 AQUA-FE/KLT 的轨迹精度优劣结论。
