# 冻结系统新增正例续扫报告（2026-07-15 至 2026-07-16）

## 结论

截至 2026-07-16，本探索队列累计完成 `146` 个 fresh current-exporter 前端 probe：
AQUALOC `77` 个、CIRS `27` 个、NTNU `42` 个。仍没有找到可加入当前冻结系统的
新增正例。所有新增窗口均未满足冻结系统的通用 learned-active 签名，因此按协议没有
绕过 `klt_safe_fallback` 启动 VINS 三路，避免把 probe bag 当成 full。

这个结果不改变已完成的 20 个 fresh 窗口簇结论，也不表示原有正例消失。冻结源码
哈希保持不变，既有 learned-active fresh 结果仍为 APE 胜 `10/11`、双指标胜
`9/11`、no-harm `10/11`；learned-inactive fresh no-harm 为 `9/9`。

## 2026-07-16 续扫

本次续扫新增 `36` 个 direct probe，并额外对 A05 `1600-2000` 运行完整 arbitration。
A05 probe 在 frame `3-5` 发布 9 条 XFeat，但 frame 5 的 3 条观测构成 late tail，
违反 `max_late_total=0`，final 自动选择 `klt_safe_fallback`。

NTNU `fjord_2` 完整 HF bag 已验证可用。先按全 598 秒时轴每 10 秒聚合图像质量，
随后完成全部 `27` 个中位 `texture_score < 0.65` 的自然 10 秒窗 fresh probe。没有
窗口命中 current arbitration：

| 窗口 | fresh 形态 | 拒绝依据 |
|---|---|---|
| fjord2 `s490,d10` | 13 条，frame 6-8 | 首 age `3 < 4`、support 12、全 degraded |
| fjord2 `s570,d10` | 9 条，frame 8-10 | 低于 mature-lineage 最少 12 条，support 3 |
| fjord2 `s430,d10` | 16 条，frame 8-10 | 首 age 3、support 10、全 degraded |
| fjord2 `s530,d10` | 50 条，frame 3-5，max/frame 25 | early 过注入 |
| fjord2 `s340,d10` | 50 条，frame 1-5，max/frame 16 | early 过注入且 grid 0.792 |
| fjord2 `s510/s470/s460/s140` | 0 条导出 | classical/GFTT 仍饱和，mirror-only 拒绝 |

A10 另按每 400 帧自然网格做质量排序，并 fresh 扫描 7 个未覆盖窗口：

| 窗口 | fresh 形态 | 拒绝依据 |
|---|---|---|
| A10 `4400-4800`、`5200-5600` | candidate/confirmed/export 均为 0 | no-trigger |
| A10 `9600-10000` | 9 条，frame 94-96 | 出现过晚 |
| A10 `0-400` | 18 条，frame 2-4，max/frame 6 | 总量超过 14，grid 0.792 > 0.75 |
| A10 `400-800` | 50 条，frame 2-5，max/frame 18 | early 过注入 |
| A10 `1200-1600` | 150 candidates、80 confirmed、0 export | classical 满载 350，mirror-only 拒绝 |
| A10 `2400-2800` | 50 条，frame 10-12，max/frame 22 | 剂量和单帧上限均不安全 |

随后补扫 A06/A01 六个与主正例簇不重叠的新自然窗：

| 窗口 | fresh 形态 | 拒绝依据 |
|---|---|---|
| A06 `0-400` | 50 条，frame 1-3，max/frame 29 | early 过注入 |
| A06 `2800-3200` | 50 条，frame 135-139 | 出现过晚 |
| A01 `12800-13200` | 180 candidates、39 confirmed、0 export | classical 满载 350 |
| A01 `4400-4800` | 50 条，frame 145-152 | 出现过晚 |
| A01 `4800-5200` | 50 条，frame 148-151 | 出现过晚 |
| A01 `13200-13600` | 50 条，frame 24-30 | 超出 mature-lineage 首帧范围 |

这些结果把失败机制收敛为四类：learned 不触发、传统前端仍饱和、learned 发生过晚、
以及 early 过注入。它们是筛选/no-harm 边界，不进入 VINS 胜率分母。

## 完整仲裁候选

以下历史候选均用当前源码 fresh 导出，且 final 都回退 KLT：

| 数据集/窗口 | fresh probe | 当前决定 | 主要原因 |
|---|---:|---|---|
| AQUALOC A08 `7200-7600` | 50 XFeat，frame 5-10 | `klt_safe_fallback` | 出现过晚、总量/单帧剂量过高、KLT 网格不弱 |
| AQUALOC A02 `3920-4200` | 0 XFeat | `klt_safe_fallback` | 新 exporter 下没有可发布 learned 观测 |
| NTNU mclab1 `s40,d10` | 0 XFeat | `klt_safe_fallback` | 历史 14 点签名未在当前系统复现 |
| NTNU fjord3 `s90,d10` | 0 XFeat | `klt_safe_fallback` | 历史微正例未在当前系统复现 |
| NTNU fjord5 `s69.85,d10` | 0 XFeat | `klt_safe_fallback` | 历史 early-seed 签名未在当前系统复现 |

## 第二批 AQUALOC 自然窗口

第二批继续扫描 6 个与既有正例簇不重叠的自然 400 帧窗口。所有窗口都完成 fresh
raw-to-bag 和 current-exporter probe；没有窗口满足冻结系统的任一通用放行签名，
因此没有启动完整 arbitration 或 VINS 三路。

| 窗口 | XFeat 形态 | 决定依据 |
|---|---|---|
| A02 `2000-2400` | 1 条，frame 38 | 出现过晚且剂量不足 |
| A03 `3600-4000` | 11 条，frame 19-21，planar | 超出 mature-lineage 的 first-frame 5-12；burst 时 grid `0.792-0.833` |
| A03 `5200-5600` | 2 条，frame 55 | 出现过晚且剂量不足 |
| A05 `1200-1600` | 9 条，frame 33-35 | 出现过晚；burst 时 grid `0.833-0.875` |
| A05 `2400-2800` | 13 条，frame 17-19 | 首帧超出 mature-lineage 范围；candidate/confirmed `30/12`，不满足 rejected-rich |
| A08 `8000-8400` | 0 条，candidate/confirmed `0/0` | 当前 XFeat 没有形成可确认轨迹 |

这 6 个窗口合计发布 36 条 XFeat，但没有 learned-active final profile。它们补充的是
no-trigger/边界覆盖，不计作反例，也不加入 VINS 胜率分母。

## 最接近门槛的窗口

| 数据集/窗口 | fresh 形态 | 拒绝依据 |
|---|---|---|
| AQUALOC A05 `2000-2400` | 12 条，frame 2-4，max/frame 6 | KLT grid `0.792 > 0.75`，不是弱覆盖初始化 |
| AQUALOC A08 `6800-7200` | 11 条，frame 2-4 | KLT grid `0.833`，传统前端覆盖健康 |
| NTNU fjord4 `s20,d10` | 9 条，frame 5-7，normal | 低于 mature-lineage 最少 12 条 |
| AQUALOC A03 `3200-3600` | 50 条，frame 5-10 | grid `0.792` 且剂量高；对应历史污染类型 |
| AQUALOC A03 `5600-6000` | 50 条，frame 6-10，max/frame 12 | 帧数、单帧剂量和 grid 均不满足 dense 分支 |
| AQUALOC A08 `4700-4860` | 50 条，frame 2-7，max/frame 12 | 高剂量长 burst，不满足 early-dense age/span 合同 |
| CIRS `s120,d30` | 13 条，frame 10-12 | 少于 CIRS oldcontract 的 20 条，grid 为 1.0 |
| CIRS `s690,d30` | 34 条，frame 106-113 | learned 出现过晚，不能支持初始化 |

## CIRS 时轴覆盖

本轮按 30 秒自然网格扫描了 `s0` 至 `s1020` 的可用非冻结时段，并排除了与冻结
`s450/s575/s900/s960` 重叠的窗口。没有新窗口出现 early `dense_start_cap` 或满足
CIRS oldcontract。多个窗口有候选/confirmed 点，但最终可发布点太少或发生太晚；
这些窗口应作为 no-trigger 覆盖，而不是强行进入后端。

## 证据边界

- 不能继续把 7 月 13 日 exporter 更新之前的 NTNU/CIRS 微正例直接计入当前系统。
- 不能用 probe bag 绕过 `klt_safe_fallback` 跑 full；那会评估一个最终系统不会输出的配置。
- 不能通过平移 1-2 帧起点让 burst 落入初始化期后再把重叠窗口算成独立正例。
- 本轮结果支持维持原主张：冻结系统在 learned-active 条件下经常改善，并在大多数
  不适合 learned 的窗口安全回退；不支持扩大为“所有低纹理窗口都能新增 learned 正例”。

## 后续优先级

继续在同一冻结门控下盲扫的边际收益已经很低，`fjord_2` 低纹理层和 A10 关键缺口
均已闭合。下一步若仍要求增加独立正例，应先
定义一个新的训练/方法开发阶段，而不是继续窗口筛选：重点解决 A05 `2000`、A08
`6800` 这类“early learned 足够但 KLT grid 健康”的几何增益判别，并在独立开发集上
确定规则后重新冻结，再用保留集统一复验。当前 20 簇冻结评测应保留为旧版本证据，
不能被新规则覆盖。

## 主要文件

- 逐窗紧凑统计：`papers/frozen_frontend_exploration_20260715/screening_summary_jul15_late_and_jul16.csv`
- 标准 run-level 汇总：`papers/frozen_frontend_exploration_20260715/run_evidence_jul15_late_and_jul16.csv`
- A10 自然窗质量扫描：`papers/frozen_frontend_exploration_20260715/a10_natural400_quality_scan.csv`
- A01/A06 自然窗质量扫描：`papers/frozen_frontend_exploration_20260715/a01_natural400_quality_scan.csv`、
  `papers/frozen_frontend_exploration_20260715/a06_natural400_quality_scan.csv`
- 探索协议：`papers/frozen_frontend_exploration_20260715/protocol.md`
