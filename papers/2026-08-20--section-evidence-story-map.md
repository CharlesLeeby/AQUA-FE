---
type: section-evidence-story-map
date: 2026-08-20
project: AQUA-FE
target_venue: IEEE Sensors Journal (fallback RA-L)
authority:
  - papers/final_claim_evidence.md
  - papers/2026-08-08--codex-STOP-and-redirect.md
memory_refs:
  - paper-framing-strategy
  - framing-playbook-peer-papers
  - competitive-landscape-defensive-citations
---

# 章节-证据-讲故事映射(论文骨架)

把已有证据按取景法排进各章:每个结果 = 落点(主表/motivation/limitations/附录) + 措辞基调 + 引哪篇挡枪。
**红线(见 [[counterexample-fix-not-report]]):取景/归因/范围收窄可以;选择性只报有利后端口径、删 divergence、把零动作粉饰成改善——不可。**

---

## §I Introduction —— claim 收窄到强项区

- **卖点定位(见 [[paper-framing-strategy]]):** 卖"面向水下低纹理/退化的保守门控前端:可证 no-harm + 选择性救回",**不卖** learned 普遍优越。
- **标题/claim 范围收窄(招2):** 写 "low-texture / degraded underwater",不写泛化 "underwater VIO"。范围越窄反例越少。
- **生态位护城河:** 水下低纹理 + 质量门控 + 可证 no-harm。**不**主打 "XFeat 接 VINS"(XfeatVINS/XFeat-VINS/SuperVINS 已占位,见 [[competitive-landscape-defensive-citations]])。

## §II Related Work —— 用同行给自己铺台阶

- learned 前端接 VINS:SuperVINS / XfeatVINS / Mix-VIO / DL-VINS-Factory。
- **DL-VINS-Factory 埋伏笔(招3+挡枪②):** 引其结论"learned 前端可行但非普遍优于经典跟踪"→ 为后文 no-harm 叙事和"learned 非普遍更优"铺共识台阶。
- 质量/不确定性 VIO:VINS-Mono 单位协方差等权 / ORB 仅尺度加权 / MAC-VO learned 协方差。**承认 MAC-VO 等前作**,把自己 q→σ 定位成"水下+conformal+KLT-carrier 组合",非首创(见 [[competitive-landscape-defensive-citations]] ③)。

## §III Method —— 只写系统真用到的组件

| 组件 | 写不写 | 依据 |
|---|---|---|
| KLT-carrier + learned-seed + 门控准入 | **写(核心)** | 系统真用 |
| XFeat 置信度降序取 top-N births | **写(方法节)** | 系统隐式真用;探针证跨数据集更持久 1.25-1.82×(见 [[xfeat-confidence-ordering-births]]) |
| q_i→σ_i 后端闭环 | **写(差异化)** | 已实现闭环;定位为组合+域,非首创 |
| 新增显式 τ 置信度门控 | **不写** | 是既有 top-N 的重述,写"新增"=夸大 |
| QG 边际选择器 | **不写/降级附录** | 跨 regime 实测不 pay off(见 [[qg-selector-supply-bottleneck]]) |

## §IV Experiments

### 主表(只放强项区,招1数据集选择)
| 进主表 | 证据文件 | 措辞 |
|---|---|---|
| **20/20 逐字节 no-harm(主结论)** | `p07_noharm_byte_identity.csv` | "在冻结 20 窗上门控零动作、feature bag 与 KLT 逐字节相同(SHA-256)——比'退化≤5%'更强的可证不伤害" |
| **B1-vs-M 初始化鲁棒性对照** | `b1_vs_m_results.csv` | "固定同后端配置下 B1 20/20 成功、当前 XFeat-M 20/20 初始化失败"——**scope-limited**,不泛化所有 learned |
| **CIRS s575,d30 选择性救回(最强 VINS 案例)** | `e3_g0_common_support/cirs_s575_d30/` | APE -50.9%/RPE -11.4%,G0 双 valid;标 development/history-excluded existence proof |

### Motivation 小节(招3:把负结果写成设计动机,不写成弱项)
| 素材 | 证据 | 措辞 |
|---|---|---|
| 逐帧 learned→VINS landmark 不可靠 | `b1_vs_m_results.csv`(M 20/20 init fail)+ M2 138/492m | "朴素 learned-to-landmark 在水下初始化不鲁棒/ID 持久性不足**→ 这正是我们 KLT-carrier 门控设计的动机**" |
| 独立佐证 | DL-VINS-Factory | 引其同结论,证明这是领域观察非我方失败(挡枪②) |

### Case studies(招6:单序列 exploratory 标注免责)
| 案例 | 落点 | 强制标注 |
|---|---|---|
| A09 6000 (4.70→0.11m) | 醒目案例 | 紧邻标 legacy-support + G0 ape_valid=false |
| A02 2800 (ORB-v23) | 跨后端机制证据/补充材料 | 标 backend-specific,不写成 VINS 结果、不写成 4 独立样本 |

## §V Evaluation Protocol —— 把评测选择包装成稳健性(挡枪①)

- **水下 GT 弱 = 领域公认(见 [[competitive-landscape-defensive-citations]] ①):** 引 AQUALOC/FLSea 原文承认 SfM 伪 GT 有瑕疵 → 把"proxy GT + 前端指标 + G0 common-support"从"退而求其次"包装成"针对水下伪 GT 不可靠这一公认问题的稳健评测选择"。消解"你 APE 证据弱"最大攻击面。
- G0 有效性门(≥30 poses/≥10s span/≥70% coverage):写成严谨性卖点,不是遮羞。

## §VI Limitations(招4:局部诚实增可信,归因场景不归因方法)
- confirmatory 盲选未选中真退化窗(真退化窗都 history-excluded)→ 低纹理 confirmatory 正例拿不到;selective 只作 case study 不作统计 claim。
- C-QG 经典 births 某些窗更持久 → **归因"该窗纹理均匀,learned 边际收益衰减"**,不归因"learned 没用"(见 [[positives-not-lowtexture-regime]])。
- 真低纹理所有机制失效:诚实列为边界,但主表本就不 claim 该 regime。
- **明确否定**(招:主动划界防 reviewer 外推):不 claim learned 必需/普遍优越/source-agnostic/低纹理普遍改善。

## §VII 投稿判定
- ISJ/RA-L 是天花板(见 [[competitive-landscape-defensive-citations]] ④);证据是单窗 exploratory + proxy GT + 不 claim 显著,够 ISJ,够不到 T-RO。别去补做不出来的多数据集统计。
- 现状 CONDITIONAL_READY(`final_claim_evidence.md`):no-harm 成立 + ≥1 selective case + B1-vs-M 完成 → 可投。

---

## 攻防速查(reviewer 攻击 → 挡枪)
| 攻击 | 挡枪 |
|---|---|
| "APE 证据弱/单窗" | 水下 GT 全域是 SfM 伪真值,引 AQUALOC/FLSea 原文;我方 G0 common-support 反而更稳健 |
| "learned 没到处超 KLT" | 引 DL-VINS-Factory 同结论=领域共识;我方 claim 本就是 no-harm 非普遍优越 |
| "q→σ 不新,MAC-VO 做过" | 我方定位=水下+conformal 校准+KLT-carrier 组合,非首创原语 |
| "只在有利数据集报" | 同赛道 SuperVINS 只报 EuRoC、XfeatVINS 只报室内热红外,范围收窄是领域惯例 |
| "C-QG 经典更好说明 learned 没用" | 归因场景(均匀纹理边际收益衰减),非方法失败;局部诚实 |
