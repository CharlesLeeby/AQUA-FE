# 出生参考消融：DIAGNOSTIC_UNRESOLVED

基于 `cd615f039d7e7daa75ab5cc1b217283846d86dc8` 的事后开发诊断；原NO_TEMPORAL_REFINEMENT_GAIN及MIMIR SUPERVISION_UNAVAILABLE不变。更新/网络推理/VINS/下载：**0/0/0/0**。

**缺失边界**：`training/`只存P/T_best.pt、P/T_curve.csv、P/T_summary.json，没有验证逐观测预测；`evaluation/`三预测仅含测试序列。验证P/T及anchor均标MISSING_PREDICTIONS，不能用验证p95反推。

**唯一干预**：按完整B历史的(sequence,id,frame−age)确定出生，仅出生delta=0；非出生预测、真值、patch有效性及观测集合不变。三分割左截断均0。测试出生111,694条（84,061有效），非出生82,730有效；验证出生49,491条（19,282有效）。

测试endofworld/Easy/P000[0,600)，同一209,862观测/166,791有效标签；验证carwelding/Easy/P001[0,600)仅B可分解。完整数值见[comparison.csv](comparison.csv)。

| 测试臂 | EPE median/p90/p95 px | >1/>2 % | 非出生p95 | 完整时序p95 |
|---|---|---|---:|---:|
| B | 0.0000/0.9964/1.6136 | 9.953/3.670 | 2.6158 | 0.7225 |
| P | 0.2985/1.1647/1.6895 | 12.690/3.595 | 2.4363 | 0.7418 |
| T | 0.3039/1.1141/1.6312 | 11.898/3.438 | 2.4339 | 0.7326 |
| P-anchor | 0.0000/1.1214/1.6695 | 11.747/3.557 | 2.4363 | 0.8490 |
| T-anchor | 0.0000/1.0852/1.6237 | 11.279/3.420 | 2.4339 | 0.8292 |

**出生贡献**：P/T全部出生修正median/p95为0.1567/0.6930、0.1742/0.6563px；有效出生引入误差median/p95为0.1784/0.7205、0.1966/0.6729px，anchor归零。P/T总EPE和减少19.71%/20.01%，完全来自出生恢复；整体p95仅降0.0200/0.0075px。分位数不可加，不能称跟踪能力提升。
**非出生已有局部尾部收益，但非稳定净收益**：T/B p95降低6.95%，median却0.3960→0.5019、mean 0.9425→1.0005px，>1比例20.066%→22.739%；两端非出生时序也劣于B。T/P该时序p95仅降低1.55%，anchor完整时序T/P仅降低2.34%<5%。

| 时序变化p95 px | 对数 | B | P | T | P-anchor | T-anchor |
|---|---:|---:|---:|---:|---:|---:|
| 出生→相邻有效帧 | 20588 | 0.8971 | 0.8469 | 0.8491 | 1.2046 | 1.1417 |
| 两端非出生 | 62142 | 0.6711 | 0.7135 | 0.7024 | 0.7135 | 0.7024 |

| 原冻结测试门 | 原/anchor |
|---|---|
| ≥100有效轨迹、每块≥100查询 | PASS/PASS |
| T/B总体p95下降≥20% | FAIL/FAIL |
| T/B >2比例不增 | PASS/PASS |
| T/P完整时序p95下降≥5% | FAIL/FAIL |
| T/P坐标p95不增 | PASS/PASS |
| 各100帧块p95比≤1.05且>2增量≤.01 | FAIL/FAIL |

**六块全部保留**；[500,600) B/P/T/P-anchor/T-anchor p95=1.0449/1.3743/1.3236/1.3625/1.3173px，T-anchor仍退化26.07%。出生置零还增大出生→下一帧的误差变化；不是所有退化都由出生引起。
**唯一决定**：验证预测缺失，完整请求DIAGNOSTIC_UNRESOLVED；可计算的测试侧已表明出生修复仍不满足原门。结束此次计算，不自动补推理/重训/VINS，不产生水下或独立泛化结论。

**读取文件**：R=`/mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1`；`cache/{train,validation,test}.{npz,json}`的轨迹/标签列、`evaluation/evaluation.json`和`evaluation/{B,P,T}_observations.npz`。出生识别不读取GT；原B/P/T指标及六项门重算一致。复现：在此目录执行`python3 analyze.py --root R`（R替换为上述路径，输出拒绝覆盖）。
