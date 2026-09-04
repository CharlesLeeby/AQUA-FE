# 图表目录

## figure-01-casewise-ape-ratio

- 文件：`figures/figure-01-casewise-ape-ratio.pdf` 与 `.png`
- 目的：展示每个 fresh 独立窗口的 full/KLT APE 比值，并区分 learned-active 与 fallback。
- 数据源：`case_summary.csv` 中 20 个 fresh 簇。
- Caption 要求：说明横轴为对数尺度，1.0 为 KLT 持平，1.05 为 no-harm 边界。
- 关键观察：唯一超过 1.05 的点是 A09_5000-5400；多个 learned-active 主窗口显著低于 1.0。
- 解读边界：主窗口是预选正例，不可把点的密度解释成自然数据分布。

## figure-02-outcome-and-risk-rates

- 文件：`figures/figure-02-outcome-and-risk-rates.pdf` 与 `.png`
- 目的：左图比较各队列 APE 胜、双指标胜和 no-harm；右图分开显示 hard failure 与 solver risk。
- 数据源：`case_summary.csv`；误差线是窗口簇二项率的 Wilson 95% CI。
- 关键观察：主队列胜率高但区间仍宽；hard failure 为零，solver risk 明显非零。
- 解读边界：Wilson CI 反映有限窗口数量，不代表随机抽样总体置信区间。

## figure-03-learned-active-improvements

- 文件：`figures/figure-03-learned-active-improvements.pdf` 与 `.png`
- 目的：逐个 learned-active 窗口展示 full 相对 KLT 和 whole-lineage drop 的 APE 改善。
- 数据源：11 个 learned-active fresh 簇。
- 关键观察：full 相对 drop 全部改善；相对 KLT 仅 A09_5000-5400 为负。
- 解读边界：极大百分比来自控制 APE 很大，必须与绝对 APE 表一起阅读。
