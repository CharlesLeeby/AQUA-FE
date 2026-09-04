# HFNet 三窗口自然历史运行性汇总（development-only）

本表仅描述 HFNet-SLAM 在三个既有 KLT 正例窗口、从自然序列帧 0 携带历史进入评分窗口时的运行性。精度均为 NA；不做精度排名、显著性检验或正式论文优越性声明。

| 窗口 | Feed | Score | 终态 | Score poses | Score KFs | Full poses/KFs | 初始化 IDs | Score 内 init/reset | 边界连续 | 精度 |
|---|---:|---:|---|---:|---:|---:|---|---:|---|---|
| A06 | 0–2460 | 2210–2460 | PASS_EXPLORATORY_UNDERWATER_USABILITY | 251/251 | 27 | 2457/268 | 0 | 0/0 | 是 | NA |
| A10 | 0–2800 | 2400–2800 | PASS_DEVELOPMENT_RUNABILITY_RESCUE | 401/401 | 30 | 444/34 | 0,105,243,419,497,560,717,882,1122,1231,1405,1471,1537,1705,1774,1854,1927,2032,2092,2152,2172,2230,2355 | 0/0 | 是 | NA |
| A09 | 0–4400 | 4000–4400 | PASS_DEVELOPMENT_RUNABILITY_RESCUE | 401/401 | 33 | 1154/62 | 0,124,351,492,694,757,867,933,961,1105,1268,1606,1771,1882,1944,2097,2199,2358,2506,2557,2625,2699,2853,2905,3175,3240 | 0/0 | 是 | NA |

## 冷启动历史敏感性诊断

冷启动结果不属于上表，也不进入其计数。三项均未形成轨迹/关键帧，因此精度是 NA，而不是 0。它们只说明这些短窗口对输入历史敏感。

| 窗口 | 冷启动终态 | Trajectory poses | KFs | 精度 |
|---|---|---:|---:|---|
| A06 | FAIL_EXPLORATORY_COLDSTART_USABILITY | 0 | 0 | NA |
| A10 | FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES | 0 | 0 | NA |
| A09 | FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES | 0 | 0 | NA |

## 解释边界

三个评分窗口是既有开发结果条件化的 KLT 正例窗口；结果只支持“外部 learned whole-system 能否在自然历史条件下跑通”的描述，不构成公平 head-to-head、精度结论或泛化结论。
