---
type: execution-redirect
date: 2026-08-08
project: AQUA-FE
priority: OVERRIDES papers/2026-08-06--aqua-fe--codex-execution-tasklist.md backend section
---

# STOP + 重定向指令(优先级高于既有任务表的 backend 部分)

## 0. 立即停止

**停止 backend 240-replay 主队列的一切准备与执行。** 停止所有治理/安全基建的继续迭代(no-clobber、TOCTOU、sealed memfd、path correction、incident/adoption、fjord_2 checksum、B0 v2、resolver 等)。**不要再修下一个"缺陷"。**

**理由(不可辩驳的科学事实)**:P07 前端 20/20 D 全部 `NOT_APPLICABLE`,即 P 在每个盲选窗零动作,P feature bag 与 B1 **逐字节相同**(SHA 已验)。因此:
- **P vs B1 的 240 个 replay 结果在数学上已确定 = 全平局(P 轨迹 ≡ B1 轨迹),D 全 N/A。**
- 跑完这 240 个 replay **不产生任何新科学信息**;它只会生成一张"P 处处等于 KLT"的表。
- 继续为这个注定 null 的队列构建证据链 = 为空结果造保险箱,**零价值**。

**保留但冻结**:已完成的 60/60 前端 export、20/20 D、所有 audit/manifest/hash——这些是有效证据,不动。240 条 PLANNED registry 行**保留但不执行**。

## 1. 只做这一件有信息量的事:B1-vs-M

唯一还有信息量的 backend 对比是 **B1(KLT baseline)vs M(modern learned baseline,SP-LG/XFeat 同后端)**,因为 M 的 feature bag **不是** byte-identical to B1。

- **范围**:只对 20 个 confirmatory 窗跑 **B1 和 M 两臂**的 VINS replay(不跑 P——P≡B1 已知)。若资源紧张,可先跑 10 个 low/degraded 窗。
- **产物**:每窗 B1、M 的 APE+RPE(G0 common-support 双指标 + `ape_valid`/`rpe_valid`)。
- **目的**:回答"现代 learned 前端(M)在这些窗相对纯 KLT(B1)有没有优势",作为论文对"我们为什么不用 heavy learned matcher"的对照。
- **不要**为这一步再新建两天的锁基建;用已有的 replay adapter,最小治理即可。

## 2. 把 P07 结果按真实论文目标整理(不需重跑)

论文目标(已确认,锁定):**大部分窗 no-harm + 小部分窗 selective improvement。**

按这个目标,把现有证据整理成 claim-evidence 表:

| Claim | 证据(现有,零重跑) | 定位 |
|---|---|---|
| **No-harm(主,最强形式)** | 20/20 盲选 confirmatory 窗 P 与 B1 **逐字节相同**(SHA 列表)+ 10 normal 窗零动作 | 主结果。逐字节相同 = 数学零差异,比"退化≤5%"更强 |
| **保守触发(机制)** | P 只在退化窗触发,否则精确回退 KLT(20/20 zero-action 证明回退可靠) | 机制说明 |
| **Selective improvement(次,案例)** | 开发期识别的退化窗救回:A09_6000(4.70→0.11m)、A02_2800 等 | **case studies / existence proofs**,诚实标注为"能在此类场景救回",**不 claim 可盲选/普遍性** |
| **B1-vs-M 对照** | 第 1 节产出 | 说明现代 learned 前端的取舍 |

**诚实边界(必须写进论文)**:
- confirmatory 盲选未能选中真退化窗(真退化窗都被 history-excluded),所以**低纹理 confirmatory 正例拿不到**;selective improvement 只作 case study,不作统计 claim。
- 不 claim "learned 必需""learned 普遍优越""source-agnostic""低纹理普遍改善"。

## 3. 产物清单(codex 交付)

```
papers/b1_vs_m_results.csv              # 第1节:20窗(或10 low窗) B1/M APE+RPE 双指标
papers/p07_noharm_byte_identity.csv     # 20/20 P≡B1 的 SHA 对照表(no-harm 主证据)
papers/selective_case_studies.md        # A09_6000 等救回案例,标注为 existence proof
papers/final_claim_evidence.md          # 上表 + 诚实边界,投稿判定
```

## 4. 投稿判定(基于真实目标,不是 P07 的 H1)

- **不再用 P07 的 H1**(要求低纹理窗普遍改善)作为判据——那个 claim 注定失败,且不是本论文的目标。
- 判据改为:**no-harm 成立(20/20 byte-identical)+ ≥1 个 selective case study + B1-vs-M 对照完成** → 可以 CONDITIONAL 定位为 "conservative gated frontend: provable no-harm + selective rescue case studies, VINS-primary" 投稿。

## 5. 一句话总结给 codex

前端已经把科学问题回答完了(方法保守、零动作、逐字节 no-harm)。**别再为注定平局的 P-vs-B1 队列造保险箱。** 只补 B1-vs-M 一个有信息量的对照,然后按 "no-harm + selective case study" 收敛论文。停止一切进一步的治理基建迭代。
