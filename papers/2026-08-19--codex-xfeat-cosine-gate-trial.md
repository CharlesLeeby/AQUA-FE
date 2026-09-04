---
type: execution-task
date: 2026-08-19
project: AQUA-FE
executor: codex
goal: 验证"XFeat 描述子 cosine 置信度作为运行时注入/保留门控"是否是一个有效、有差异化的编排组件
scope: 纯组合/编排,不训练任何网络。复用现有 xfeat-birth+rawLK 基础设施。
---

# 试验:XFeat-cosine 门控编排(最小验证)

## 0. 背景与假设(为什么做这个)

A02 4500–6300 已有正向结果:`XFeat-birth + raw LK`(learned 只提议新生点,LK 承载持久轨迹)相对 B1(纯 KLT)在统一 VINS 后端上 **APE −30%、RPE −34%**(单序列、探索性、proxy GT)。

现在测一个**差异化旋钮**:XFeat adapter 已实现 `confidence_mode='cosine'`(描述子余弦相似度作为每个匹配的置信度)。假设:**用 XFeat cosine 置信度做新生点的注入/保留门控**,相对"无 cosine 门控"的 xfeat-birth,能进一步改善或更稳。

这一步的目的**不是**再证明 learned 有用(A02 已证),而是回答:**"learned 置信度门控"是不是一个值得写进论文的、属于我们自己的编排组件**(相对 Mix-VIO / XFeat+LK 的纯几何/光流门控多一层 learned-informed 门控)。

## 1. 实验设计(单序列,3 臂,对照 cosine 门控开/关)

同一序列(先 A02 4500–6300,与已有 −30% 结果同窗)、同一 VINS 后端、同一 raw-LK 承载、同一 G0 common-support 评测。**唯一变量 = 新生点的置信度门控**:

| 臂 | 配置 | 说明 |
|---|---|---|
| **B1** | 纯 KLT(const-q) | baseline,复用已有 |
| **birth-noconf** | XFeat-birth + raw LK,`confidence_mode='ones'`(无 cosine 门控) | 已有的 −30% 臂 |
| **birth-cosine** | XFeat-birth + raw LK,`confidence_mode='cosine'`,新生点按 cosine 阈值门控 | **本次新增,唯一变量** |

- **cosine 门控逻辑**:XFeat 提议新生点时,只接纳 cosine 置信度 ≥ 阈值 τ 的点(τ 先扫 {0.82(默认 min_cossim), 0.88, 0.92} 三档)。其余 pipeline(raw LK 承载、多帧 probation、export、VINS)与 birth-noconf **完全一致**。
- 复用脚本:`scripts/export_matched_xfeat_birth_rawlk_v1.py` + `scripts/matched_birth_rawlk_core_v1.py`;config 继承 `uw_frontend/configs/experiments/isj_p05_xfeat_persistent_v2.yaml`,只改 `xfeat.confidence_mode` 和门控阈值。

## 2. 执行原则(避免上几轮的坑)

1. **纯组合,不训练**。只调 adapter 参数和门控阈值,不碰权重、不改网络。
2. **直接跑,不做 probe/preflight/dry-run/治理锁基建**。同名输出写到带时间戳的新目录,失败看报错再改。
3. **先跑 1 个窗(A02)出三臂结果给我看**,不要一次性铺多窗。
4. 单个 bug 最多修一次;30 分钟没产出数据就停下报告卡点。
5. **诚实边界照旧**:A02 proxy GT 非独立真值,结果是单序列探索性,不 claim 统计显著。

## 3. 判据(这次试验成功=什么)

- **birth-cosine 相对 birth-noconf**:APE/RPE 在某个 τ 下**更好或相当且更稳**(注入更少坏点)→ cosine 门控是有效差异化组件,值得写进论文;
- **若 birth-cosine ≈ birth-noconf(无差别)**→ cosine 门控在这个窗没加值,诚实记录,回退到"birth+LK 已足够"的叙事;
- **若 birth-cosine 更差**→ cosine 门控有害,记录并放弃这个旋钮。

三种结果都写进 claim-evidence,都是有用信息。

## 4. 产物

```
papers/xfeat_cosine_gate_a02_results.csv    # B1 / birth-noconf / birth-cosine(3档τ) 的 APE+RPE(G0 双指标)
papers/xfeat_cosine_gate_trial_report.md    # 三臂对比 + 每臂注入的新生点数/被cosine门控滤掉的数 + 结论
```

## 5. 一句话

复用 A02 已成功的 xfeat-birth+rawLK,只加一个变量——XFeat cosine 置信度门控新生点——跑 B1/birth-noconf/birth-cosine 三臂,一个窗看方向。回答:learned 置信度门控是不是我们能写进论文的差异化编排组件。不训练、不铺全套、不造治理基建。
