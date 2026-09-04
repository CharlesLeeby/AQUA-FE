# External-KLT 对 AQUA-FE 的借鉴意义：Codex 交接报告

日期：2026-09-04  
目标工作区：`/home/ma/AQUA-FE_WS`  
边界：本文档只讨论 AQUA-FE 前端研究，不属于 `/home/ma/SLAM/VINS-Fusion_3-15-WS` 后端系统的贡献或实验结论。

## 一、结论

External-KLT 对 AQUA-FE **有明确借鉴意义**，但应分级理解：

- 高价值：作为受保护的经典时序骨干、强基线和 no-harm 参照。
- 中等价值：密集候选池、退化触发、滞回退出、每帧限量补充等救援调度结构。
- 低可迁移性：水池 `cap8` 的 DVL 弱支持门控、300 s 离墙截断和具体阈值，它们依赖另一套后端及场景。
- 不构成证据：`cap8` 全部是经典 KLT 候选，不能证明 learned/LoFTR/XFeat 的贡献。

建议 AQUA-FE 保留现有“两种 profile”结构：`proposed_safe` 以 protected KLT mirror 为骨干，学习特征仅作严格门控的 sidecar；`contribution_sparse` 专门用于证明低纹理下的学习增量。不要把 External-KLT 当作新的学习方法，也不要让学习候选挤掉健康 KLT 轨迹。

## 二、External-KLT 实际做了什么

External-KLT 在 VINS 进程外生成 `/feature_tracker/feature`：角点初始化后使用金字塔 Lucas–Kanade 光流传播，通过 forward-backward error、NCC、边界和空间间距过滤并补充新角点。当前配置的主要数值是：最多 350 条轨迹、最小间距 18 px、LK 窗口 21、3 层金字塔、FB 阈值 1 px、NCC 下限 0.65，并使用 CLAHE。

它与原版 VINS 内部跟踪器属于同一经典 KLT 技术族。优势主要来自更密集、更长寿命且更可控的轨迹管理，以及能冻结成 bag 做同后端复放，而不是来自一种全新的视觉模型。

## 三、现有证据如何解读

### 3.1 支持借鉴的证据

1. AQUALOC Harbor 07 全段诊断中，固定 VINS 后端下，原生输入为 18.885 m APE / 1.452 m 1 s RPE，历史 External-KLT 输入为 2.328 / 0.320 m。数值差距很大，说明水下单目 VIO 可能被轨迹寿命、覆盖和特征管理主导；但该历史 KLT 行不是同轮新鲜复跑，只能作为方向性诊断。
2. AQUALOC A06 `2210–2460` 的当前证据中，KLT 基线为 0.268486 / 0.113326 m；稀疏 SP-LG+LoFTR 为 0.118616 / 0.062520 m；完整 mirror-inject 为 0.058071 / 0.048803 m，且只导出 10 个 LoFTR 观测。这支持“强 KLT 骨干上少量、几何安全的学习补充”。
3. H07 `1660–1720` 正常纹理 no-harm 中，KLT 与 `proposed_safe` 分别为 0.050207/0.113417 和 0.050207/0.113416 m，后者导出 0 个 LoFTR，说明健康 KLT 下保持静默是正确策略。

### 3.2 限制与反证

1. P07 的 20 个正式窗口中，AQUA-FE P 臂有效 learned-born lineage 为 0，最终都回退到 KLT；因此 P 与 External-KLT 几乎相同，不能用该矩阵声称学习前端优于 KLT。
2. 水池 `cap8` 迁移仅在 172529 的 6651 帧中触发 57 帧；raw 后端的冻结倾斜壁面 RMS、单步 RMS 和重访均值分别约改善 3.03%、4.76% 和 0.17%。严格回环后连续性改善，但重访 P90 变差。说明救援机制可控但收益是小幅、场景依赖的。
3. `cap8` 使用 DVL 弱支持作为触发条件，并与壁面有效时间绑定。AQUA-FE 的通用论文前端不能默认依赖这些后端信号，否则会改变方法问题定义。

## 四、AQUA-FE 应借鉴的设计

### 4.1 Protected KLT backbone

- KLT/GFTT 始终是主干和强基线。
- sidecar 只能填补空间/时间支持，不能驱逐健康 KLT。
- 未触发时，输出应与 KLT 基线逐消息或逐字段一致。

### 4.2 候选池和输出预算分离

- 内部可维护约 350 条或更多候选。
- VINS 输出预算单独冻结，确保比较只改变候选来源而不改变总特征数。
- 记录候选数、导出数、出生来源、轨迹年龄和退出原因。

### 4.3 因果退化门控与滞回

- 进入条件使用 KLT 自身可在线获得的证据：轨迹数、成熟轨数、网格覆盖、FB/NCC、dropout、图像质量和 `q_i`。
- 要求连续多帧退化后才进入；连续恢复多帧后才退出。
- 每帧限制新 sidecar 数，避免一次性替换造成估计器跳变。
- `cap4/6/8` 只能作为待校准候选，不应直接把水池的 `8` 固定成 AQUA-FE 默认值。

### 4.4 明确 learned-born lineage

- 每条学习轨迹必须有不可混淆的出生来源和完整 lineage。
- 正式 learned contribution 窗口必须满足 `accepted_learned_born_lineage_count > 0`。
- 如果学习输出为 0 且结果与 KLT 相同，应报告 zero-action/no-harm，不能报告学习提升。

## 五、不应搬用的内容

- 不搬用 DVL 弱覆盖门控，除非实验问题明确变成前后端联合调度。
- 不搬用三轮壁面、离墙时间截断或原版 VINS 回环结果。
- 不把 External-KLT 与 AQUA-FE proposed 当作两个完全不同的后端系统。
- 不用单个 AQUALOC 全段的大数值差距替代多窗口、重复运行和 common-support 检验。
- 不让 `proposed_safe` 的 KLT fallback 掩盖“学习分支没有动作”。

## 六、建议下一轮最小实验

先做小规模 action-positive 验证，不立即扩大全矩阵：

1. 从已有窗口中冻结 5 个 `accepted_learned_born_lineage_count > 0` 的低纹理窗口。
2. 每个窗口运行 4 臂：protected KLT、dense-KLT rescue only、learned no-LoFTR、learned+LoFTR。
3. 每臂 3 次固定 VINS 后端复放，共 `5×4×3=60` 次。
4. 再选 5 个正常纹理窗口，运行 protected KLT 与 `proposed_safe` 各 3 次，共 `5×2×3=30` 次。
5. 合计 90 次；先完成 export-only 探针，确认来源直方图和 lineage 后再启动 VINS。

主指标：exact-1-s translation RPE、APE、覆盖、首输出延迟、失败率；前端指标：learned/LoFTR 实际导出数、成熟轨、网格覆盖、FB/NCC、lineage 生存长度。科学单位是窗口所属序列，重复运行先取中位数，不能把同一序列的多个窗口当作完全独立样本。

Go 条件：至少 4/5 低纹理窗口有真实 learned-born 输入，且序列级 RPE 相对 dense-KLT 的方向一致；正常纹理 5/5 不超过 5% 伤害且覆盖不下降。否则保留 KLT backbone，把学习分支结论降级为尚未建立。

## 七、给下一位 Codex 的执行提示

- 只在 `/home/ma/AQUA-FE_WS` 工作，不修改 `/home/ma/SLAM/VINS-Fusion_3-15-WS`。
- 先读取项目 `experiment_status.md` 和 P07 冻结协议，再建立新的补充实验目录；不要覆盖既有 P07 历史产物。
- 优先解决“正式窗口 learned-born 为 0”这一事实问题，而不是继续扩充无动作重复运行。
- 使用当前 skill 规定的 `proposed_safe` / `contribution_sparse` 双 profile 和 no-harm 规则。

## 八、证据入口

- 当前证据说明：`/home/ma/.codex/skills/underwater-slam-frontend-research/references/current_evidence_state.md`
- KLT 配置：`/home/ma/AQUA-FE_WS/uw_frontend/configs/klt_frontend.yaml`
- cap8 三包诊断：`/mnt/data/AQUA-FE_WS/experiments/external_klt_pool_transfer_v1/threebag_cap8_20260904/REPORT.md`
- P07 严格分析：`/media/ma/Data/AQUA-FE_WS_storage_offload/p07_backend_completion_serial_v2/analysis-output/analysis-report.md`

