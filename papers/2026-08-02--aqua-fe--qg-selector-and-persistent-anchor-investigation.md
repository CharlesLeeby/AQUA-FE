---
type: investigation-report
date: 2026-08-02
project: AQUA-FE
scope: QG marginal-support selector + persistent-anchor mechanism + C-QG classical control
status: decision-pending
supersedes_narrative: null
related:
  - papers/2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md
  - papers/frontend_baseline_protocol.md
  - memory: qg-selector-supply-bottleneck, positives-not-lowtexture-regime, a06-ape-not-evidence
---

# AQUA-FE 调查报告:QG 选择器、持久锚点机制与 C-QG 经典对照

## 0. 执行摘要(TL;DR)

本轮围绕 ISJ 方案的头条创新——**reliability-calibrated marginal geometric-support 选择器(QG)**——从零构建并逐层验证。结论是一连串**诚实的负向发现**,最终收敛到一个明确的战略判断:

1. **QG 选择器不 pay off。** 在饱和窗(A09/A10)和稀疏低纹理窗(AFRL Cave)两种 regime 下,QG 的测量集覆盖/可靠性均**不优于**启发式 H、甚至不优于随机 R。
2. **单窗 AQUALOC APE 作为主指标已死。** G0 修正评测器下,旗舰正例 A10/A09 的 APE 因共同 GT 位姿不足(15<30)判为无效;旧"5/5 APE 强正例"是 legacy 评测器 GT 复用 ×10 的产物。**RPE 幸存且正向**(A10 −33%、A09 −15%)。
3. **干净正例不来自"低纹理"regime。** A09/A10 的 KLT 每帧饱和在 350(MAX_CNT),是 **churny 高周转**(单 track 中位活 1 帧)但特征仍丰富的窗;真低纹理(Cave)所有机制失效。
4. **真机制是"持久锚点"而非覆盖/选择/协方差**:learned 锚点活 30–97 帧 vs KLT 中位 1 帧,drop 掉即 27m 发散。
5. **但"锚点必须 learned"被证伪**:在 A06 raw 图上,经典 Shi-Tomasi 在空隙里的种子 **81% 活 ≥10 帧**,learned XFeat 种子仅 **27%**。经典持久锚点又多又好。

**净判断:以 QG / learned 前端为头条的论文,数据不支持。** 剩下能站住的是一个更简单、更诚实、但新颖性中低的经典观察:*退化/churny 水下 VIO 里,补少量持久 gap-filling 锚点(无需 learned)即可提供缺失的长基线、抑制发散。*

---

## 1. 背景与目标

ISJ 投稿方案(`2026-07-30--...-experiment-closure-plan.md`)把论文头条定为 QG 选择器:退化触发 → learned 种子提议 → KLT 多帧验证 → 保守 conformal 可靠性 `q_i^-` × 相对已保留测量集的边际几何支撑,决定哪些 lineage 进入 VINS。

本轮任务(用户三步计划):
1. 用 G0 新评测器重算 A10/A09 强正例,确认 REVIEW 信号没把它们打没;
2. 造 QG 选择器,跑 Q/G/QG + C-QG development ablation(决定"组合是否真贡献 + learned 是否特有");
3. 两步 green 后再投入完整 confirmatory 矩阵。

结果:第 1、2 步均返回负向/证伪信号,第 3 步不应启动。

---

## 2. 构建的代码产物(均未改动主 export 路径)

| 文件 | 作用 | 验证 |
|---|---|---|
| `uw_frontend/geometry/marginal_support.py` | QG 选择器内核:log-det 次模贪心 + `q_i^-` 加权 + view-space 条件化;确定性帧哈希 | 13 合同(含并行升级后的 NO_VALID_BASE_MODEL、disjoint 校验、frame-chain hash) |
| `uw_frontend/geometry/shadow_rankings.py` | 五臂 R/H/Q/G/QG 排序对照,admission-count-matched overlap `o_t` | 8 合同 |
| `uw_frontend/geometry/_marginal_support_selftest.py` / `_shadow_rankings_selftest.py` | 合成合同测试 | 全过 |
| `scripts/selector_shadow_compare.py` | 真实 bag 上复现 eligibility,H-vs-QG 竞争/分道统计 | 运行 |
| `scripts/selector_qg_validate.py` | surplus 池上五臂覆盖/可靠性验证(GT-free) | 运行 |
| `scripts/cqg_classical_persistence.py` | C-QG 一级:raw 图上经典 Shi-Tomasi 种子持久性 vs learned | 运行 |

数学(方案 6.2):`z_i=[1, 2u/W−1, 2v/H−1]`;`w_i=q_i^-·exp(−e_i/τ_e)`;`A(S)=λ_A I+Σ w z zᵀ`;`Δ(c|S)=log(1+w_c z_cᵀ A(S)⁻¹ z_c)`;cardinality-bounded greedy(1−1/e 保证)。为**图像平面 view-space 支撑代理**,非 6DoF FIM。

---

## 3. 实验与发现(逐层)

### 3.1 G0 重算旗舰正例(第 1 步)

修正评测器:common-support + reference 重采样,APE 有效门槛 ≥30 共同 GT 位姿 / ≥10s / ≥70% 覆盖。

| 窗口 | 共同 GT 位姿 | APE 有效 | RPE(full vs KLT) | 描述性 APE gain |
|---|---:|---|---|---|
| A10 2400-2800 | 15 (<30) | ❌ 无效 | 0.159 vs 0.239(**−33%**) | +35.7% |
| A09 4000-4400 | 15 (<30) | ❌ 无效 | 0.200 vs 0.235(**−15%**) | +15.5% |
| NTNU s0_d30(密GT) | 245 | ✅ | — | **−5.4%(更差)** |
| H07 0-1000(密GT) | 94 | ✅ | — | **−9.4%(更差)** |

- 旧"5/5 APE 强正例"由 legacy 评测器 **GT 复用 ×10**(159 估计点匹配 16-17 个唯一 GT)算出——正是 G0 修的漏洞。
- **方向幸存(RPE 正向),但单窗 APE 头条死了。** 机器判据 `HISTORICAL_SIGNAL_REVIEW`。
- 唯二 APE 有效的窗(密 GT)方向为**负**,但都是 non-low-texture 窗,不打低纹理主张;H07 −9.4% 破 5% no-harm,是 C4 隐忧。

### 3.2 QG 机制在合成数据成立

- G 挑几何新颖、Q 挑可靠性、QG 融合(可分离,组合有意义的前提)。
- 冗余新颖场景:H 选冗余对(o=0.50),QG 条件化后分散到不同区域。

### 3.3 真实数据:候选供给瓶颈

`selector_shadow_compare` on A09/A10:

| 窗口 | distinct 成熟 lineage | 竞争 event(≥2争1) | QG-vs-H 分道 |
|---|---:|---:|---|
| A10 | 3 | 1 | 0/1 |
| A09 | 8 | 3 | 1/3(一次 o=0.0) |

诊断:生成器产 84/81 distinct 候选(每帧最多 67-71),~24 存活≥5帧,但**严格 novelty+motion 门只放 3-8 个成熟**。瓶颈在门,不在生成器;但机制在真实数据确实会 fire(A09 一次 o=0.0)。

### 3.4 QG 验证:两种 regime 均无优势

`selector_qg_validate`(surplus 池,GT-free,budget=8,8×8 网格):

| arm | A09 覆盖 | A10 覆盖 | Cave 覆盖(稀疏靶场) |
|---|---:|---:|---:|
| R 随机 | **7.44** | **6.25** | **7.00** |
| H | 4.22 | 6.19 | 6.25 |
| Q | 3.31 | 6.00 | 7.00 |
| G | 4.11 | 5.91 | 6.75 |
| **QG** | 4.19 | 5.81 | 6.50 |

- 随机覆盖最高,QG 不占优、A10/Cave 甚至最低。可靠性五臂近乎同质(0.43–0.86)→ Q 层无区分。
- **即使在 QG 的目标 regime(Cave 稀疏 base)也无优势**;且 Cave surplus 帧仅 4 个。

### 3.5 KLT 饱和 = MAX_CNT 假象

逐帧 base KLT 数:

| 窗口 | base KLT | 判定 |
|---|---|---|
| A09/A10 | 恒 350(min=median=max) | 饱和(=MAX_CNT),非低纹理 |
| AFRL Cave s150 | min=58 median=139(172/194帧<200) | 真稀疏靶场 |
| AFRL Gennie/cemfr | 350 | 饱和 |
| A06 | 183–194 | 中度稀疏 |

"350"是 tracker 每帧补满预算,不代表纹理丰富。

### 3.6 真机制:持久锚点 vs churny KLT

full_merged 逐 id 寿命:

| 窗口 | KLT track 中位/max | 准入 learned lineage 寿命 | 全体 learned ≥10帧 vs KLT |
|---|---|---|---|
| A10 | 1 / 171 | 97 帧 | 25% vs 10% |
| A09 | 1 / 154 | 30 帧 | 30% vs 18% |
| A09_6000(发散) | 1 / 100 | 16 帧 | — |
| **Cave(真低纹理)** | 2 / 67 | 11 帧 | **7% vs 18%(learned 更差)** |

- **KLT 极度 churny:单 track 中位活 1-2 帧**(200帧有 9000-13000 个不同 id)。"饱和 350"靠不停重检测。
- learned 锚点在 A09/A10 是稀有长基线(30-97帧),drop 掉即发散(A09_6000 full 0.11 vs drop/KLT 27m)。
- **但在真低纹理 Cave,learned 反而更短命** → 机制不泛化到低纹理。

### 3.7 matched-classical 持久性代理(混合)

KLT base = Shi-Tomasi 检测。比锚点 25px 邻域经典特征寿命:

| 窗口 | 锚点寿命 | 邻域经典最长寿命 | 判读 |
|---|---|---|---|
| A10 | 97 | **85(1.1×)** | 经典就够,否定 learned 必需 |
| A09_4000 | 30 | 25px 内无经典 | learned 填空白 |
| A09_6000(发散) | 16 | 7(2.3×) | learned 更持久 |

n=1×3,最强反例(A10)否定"learned 必需"。

### 3.8 C-QG 一级:证伪 learned 必需

`cqg_classical_persistence` on A06 raw(251帧):在空隙(≥8px 离KLT)用 Shi-Tomasi 检测经典种子 LK 追踪 vs learned XFeat(sidecar):

| 种子来源 | ≥10帧持久 | 中位 | max |
|---|---|---|---|
| **经典 Shi-Tomasi(空隙)** | **81%** (164/202) | 26 | 251 |
| learned XFeat | 27% (22/83) | 4 | 124 |

- **经典持久锚点又多又好** → "learned 找到经典给不了的持久点"证伪。Shi-Tomasi 为 LK 可追踪性设计,XFeat 为匹配设计。
- **Caveat**:自实现 cv2 LK(FB<1.0)≠ 真 pipeline 追踪器,27% 可能含 learned 自有严门控;确切数字软,但"经典持久锚点大量可得"方向硬。真定论需二级(经典种子过真 pipeline+VINS 比轨迹)。

### 3.9 Prior-art(lit-review)

- QG-邻近的"质量/不确定度→测量协方差加权"已很挤:**MAC-VO**(2024)、**D3VO**(CVPR'20)、DROID-SLAM、**Enhancing VINS with Smart Feature Grading**(ISPRS'25)、水下 **AWARE**、**Statistical Uncertainty Learning for VI**(2025)。
- conformal 产逐特征 σ 注入 VIO 后端:检索未见(仅用于在线外参标定),是少数还开着的缝——但很窄,且需正面打赢 MAC-VO。

---

## 4. Meta-发现(最重要)

1. **单窗 AQUALOC APE 不可当 load-bearing 证据**(稀疏 1Hz GT),推广自 [[a06-ape-not-evidence]] 到 A10/A09。主指标应转 RPE / 跨窗聚合。
2. **唯一干净、审计过的 VINS 正例(A09/A10)不来自论文声称的"低纹理"regime**——是 churny-but-feature-saturated 窗。
3. **每个机制(QG 覆盖、持久锚点、learned 特异性)都在 A09/A10 成立、在真低纹理(Cave/AFRL)失效。** 动摇的是核心 claim("低纹理改善")本身,不是某个 selector。
4. **learned 必需性证伪**:经典 Shi-Tomasi 锚点更持久。

---

## 5. 对论文的影响

| 原方案卖点 | 本轮结论 |
|---|---|
| QG 边际选择是核心贡献 | ❌ 跨 regime 不 pay off |
| learned sidecar 提供经典替代不了的测量 | ❌ 持久锚点经典做得更好 |
| 低纹理改善主张(protocol C1/C2) | ❌ 无干净低纹理正例;正例来自 churny 饱和窗 |
| q→σ 后端闭环 | ❌ prior-art 太挤 |
| 持久性 vs 计数脱节 + 持久锚点稳定 VIO | ✅ 真、诚实、可写(但无 learned,新颖性中低) |

---

## 6. 决策与三条路

1. **写经典版(建议默认)**:*"Gap-filling persistent anchors for churny/high-turnover underwater VIO"*——诊断(count 与 persistence 脱节)+ 轻量经典修复;指标用 track-age 分布(KLT 中位1帧 vs 锚点30-97帧)+ 发散预防(27m→0.11m)+ RPE;**不带 learned**。诚实、能发、新颖性中低。
2. **跑二级 C-QG 救 learned**:经典 GFTT proposer 过**真 pipeline + VINS**,比轨迹。一级已预警大概率经典也行甚至更好——上坡路。需构建经典 proposer 节点(仿 `xfeat_seed_sidecar_node.py`,换检测)+ `run_aqualoc_archaeo_vins_eval.sh`。
3. **退回三后端重估**:若经典版新颖性不足、learned 又撑不住,回 [[project-state-20260730]] 的 VINS/MSCKF/ORB 三后端找别的角度,或重新定题。

---

## 7. 未完成 / 待验证

- **二级 C-QG(真 pipeline + VINS)**:一级 caveat(自实现 tracker)的定论确认。基础设施:raw bag(`datasets/aqualoc/rosbags/*.bag`,`/camera/image_raw`)、VINS 脚本、cv2/cv_bridge 均就绪;缺经典 proposer 节点。
- **RPE 作为主指标 + 跨窗聚合**的完整低纹理矩阵(替代已死的单窗 APE)。
- QG 相关代码保留价值:即便不当头条,可作 ablation 组件(no-harm)或 measurement-set 质量分析工具。

---

## 8. 复现命令

```bash
cd /home/ma/AQUA-FE_WS && source /opt/ros/noetic/setup.bash
export PYTHONPATH=/home/ma/AQUA-FE_WS:$PYTHONPATH

# 合同测试
python3 -m uw_frontend.geometry._marginal_support_selftest
python3 -m uw_frontend.geometry._shadow_rankings_selftest

# QG 验证(surplus 池覆盖/可靠性)
D=/mnt/data/AQUA-FE_WS/online_positive_search_20260722/afrl_cave_s150_d20
python3 scripts/selector_qg_validate.py --full $D/full_merged.bag --sidecar $D/sidecar.bag --survival 5 --budget 8

# C-QG 一级(经典种子持久性)
python3 scripts/cqg_classical_persistence.py \
  --raw /mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo06_2210_2460.bag \
  --sidecar /mnt/data/AQUA-FE_WS/online_positive_search_20260721/a06_2210_2460/sidecar.bag

# G0 重算产物
cat papers/ieee_sensors_journal_experiments/g0/g0_evaluator_validation.md
```

数据身份:A09/A10/A06/Cave 均为 development 集(见 [[project-state-20260730]]);本报告所有数字为 development-grade 证据,非 confirmatory。
