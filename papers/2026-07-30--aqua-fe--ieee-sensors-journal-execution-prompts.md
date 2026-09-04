---
type: experiment-execution-prompts
date: 2026-07-31
project: AQUA-FE
target_venue: IEEE Sensors Journal
publication_model: traditional
paper_scope: underwater-vins-learned-seed-frontend
status: ready-for-selector-prototype
version: v3
companion_plan: papers/2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md
---

# AQUA-FE IEEE Sensors Journal 实验执行提示词

## Material Passport

- Origin skills: `underwater-slam-frontend-research`, `academic-research-suite/experiment-agent`
- Origin mode: staged experiment execution
- Origin date: 2026-07-31
- Verification status: `METHOD-UPGRADE-CONTRACT-AUDITED`; selector prototype and experiment outcomes pending
- Version label: `isj_execution_prompts_v3`
- Workspace: `/home/ma/AQUA-FE_WS`
- Canonical VINS workspace: `/home/ma/SLAM/VINS-Fusion-origin`
- Historical reference VINS workspace: `/home/ma/SLAM/VINS-Fusion_3-15-WS`

## 1. 使用方式

按 P00-P11 顺序执行，其中 P03A/P03B 是 P03 的 selector shadow 与 canonical migration 子阶段。每次向实验代理提供一条阶段提示词，当前阶段验收完成后进入下一阶段。P00 建立状态表，后续代理从第一个待完成阶段继续。

这些提示词服务于冻结后的 VINS 主论文：学习模块提出候选种子，KLT 负责多帧验证，经 survival、motion 和 F/H correctness eligibility 后，按 source-neutral conservative conformalized reliability 与相对 KLT base + active accepted lineage 的 marginal geometric-support gain 限量导出给 VINS-Fusion。`lineage` 承担 provenance、accepted-track persistence、whole-lineage drop 和 matched-control 审计。`PROMOTE` profile 主要贡献聚焦 reliability-calibrated marginal geometric-support selection；`BASELINE_ROUTE` 则改为 selective learned-seeded KLT system 主线，QG/C2/P-H/HU 仅作 development。

建议先复制“公共固定前缀”，再接上相应阶段正文。每阶段重新附上前缀，以便在上下文压缩后延续同一实验合同。

## 2. 公共固定前缀

```text
你正在执行 AQUA-FE 的 IEEE Sensors Journal 投稿实验。工作目录固定为：
/home/ma/AQUA-FE_WS

开始前完整阅读：
1. /home/ma/AQUA-FE_WS/CLAUDE.md
2. /home/ma/AQUA-FE_WS/papers/2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md
3. /home/ma/AQUA-FE_WS/papers/2026-07-30--aqua-fe--ieee-sensors-journal-execution-prompts.md
4. /home/ma/AQUA-FE_WS/papers/2026-07-30--aqua-fe--r00--project-progress-review.md
5. 与本阶段直接相关的 runner、config、README 和已有报告。

科学范围：
- 论文聚焦 VINS 主线：quality/health trigger -> learned seed proposal -> KLT multi-frame probation -> correctness eligibility -> calibrated reliability -> marginal support selection -> bounded export -> VINS-Fusion。
- learned feature 定位为 seed proposal；lineage 定位为 provenance/消融机制；标题贡献聚焦增量测量选择方法。
- promoted 路线工作标题为 Reliability-Calibrated Marginal Measurement Selection for Degradation-Triggered Underwater VINS；legacy 路线不使用 marginal-selection 标题。
- 3x3 目标是 image-plane support surrogate，不写成 FIM、6DoF observability 或 backend covariance optimization。
- MSCKF、ORB v23、连续风险后验、LoFTR 历史优化和 raw q_i trajectory weighting 作为后续扩展。
- 后端使用完全一致的 constant `q=1`；`q_i^-` 是前端选择使用的 conservative conformalized score，不称为 conditional-probability confidence bound。
- 历史窗口统一标记为 development。

执行合同：
- 所有 backend build/run/write 操作使用 /home/ma/SLAM/VINS-Fusion-origin；/home/ma/SLAM/VINS-Fusion_3-15-WS 仅作为历史路径信息。CLAUDE.md 中相关描述按本实验 task-specific 配置解释。
- 以实际脚本的 --help、usage 和源码确定参数。
- 既有 run 保持原样；每个新 run 使用唯一目录。
- 版本与文件更新采用非破坏性操作；该工作区的 git root 位于 `/`。
- crash、timeout、empty trajectory、solver failure、异常回放和负结果完整归档。
- held-out 结果沿用冻结阈值与窗口；方法更新进入新的 protocol version。
- 基础设施故障保留原 run，并在 append-only ledger 中记录故障证据和 replacement reason，再创建 replacement run。
- backend replay 用于稳定性汇总；sequence 是主统计单位。
- 每个 applicable `window x arm` 有 3 个 algorithmic replay slots；>=2/3 可评估才取数值 median，否则为 `WINDOW_ARM_HARD_FAILURE`；solver-risk 按 any-of-3 归并。
- 每个数字追溯到 exact run directory 和机器可读产物，汇总表由脚本生成。
- 计划与真实代码/数据出现差异时记录证据，将受影响阶段标记为 REVISE，并更新科学合同版本。

每次开始时：
1. 报告当前阶段、前置状态、计划读取/修改/运行的文件；
2. 检查 roscore、rosbag、vins_node 或 sidecar 进程，按本实验 PID/command 身份管理进程；
3. 更新 papers/ieee_sensors_journal_experiments/experiment_status.md，将当前阶段标为 IN_PROGRESS；
4. 在 papers/ieee_sensors_journal_experiments/execution_ledger.jsonl 追加开始记录。

每次结束时输出：
- 阶段结论：PASS / REVISE / WAITING；
- 实际执行命令和运行目录；
- 新增或修改文件；
- 关键机器可读产物路径；
- failure、异常、替换和未决问题；
- 下一阶段入口。
同时更新 experiment_status.md 和 execution_ledger.jsonl；PASS 状态对应可核验产物。
```

## 3. P00：建立实验注册表与状态面板

```text
阶段：P00 bootstrap experiment registry/status

目标：建立 append-only 实验治理骨架；本阶段工作范围为注册表与状态文件。

输入：
- 两份 2026-07-30 IEEE Sensors Journal 文档；
- 当前 logs/、papers/、scripts/、uw_frontend/ 和 datasets/ 目录结构；
- 已有 run 命名和报告格式。

任务：
1. 创建或复用 papers/ieee_sensors_journal_experiments/，保留已有内容。
2. 创建 experiment_status.md，列出 G0-G6、P00-P11、P03A/P03B、状态、负责人/代理、开始时间、结束时间、PASS 证据、阻塞原因。
3. 创建 run_registry.csv，字段至少包括：run_id, protocol_version, method_profile, stage, dataset_family, sequence, window_start, window_end, texture_stratum, split_role, arm, arm_version, arm_applicability, applicability_rule, frontend_seed, backend_replay, accepted_lineage_count, active, selection_active, candidate_pool_hash, frame_chain_hash, selection_hash, status, replay_evaluable, replay_hard_failure, window_arm_hard_failure, any_repeat_hard_failure, init_failure, full_coverage, solver_risk, window_arm_solver_risk, queue_drop_rate, sustained_queue_drop, infrastructure_failure, replacement_for, run_dir, command_file, input_hash_manifest, output_hash_manifest, notes。历史启发式使用 `H_legacy`，确认性启发式使用 `H_confirmatory`。
4. 创建 arm_applicability.csv 空 schema，字段至少包括：protocol_version, method_profile, dataset_family, sequence, window_start, window_end, proposed_arm, accepted_lineage_count, applicability_rule, resolution_time, drop_arm, classical_arm, resolution, evidence_path, resolver_hash。状态允许 `PENDING_APPLICABILITY/APPLICABLE/NOT_APPLICABLE`，P06/P07 按冻结顺序 append/解析。
5. 创建 execution_ledger.jsonl，并追加 bootstrap 记录；每行采用合法 JSON，历史行保持 append-only。
6. 创建 failures_and_replacements.md 模板。
7. 创建 README.md，说明 append-only 原则、目录身份、状态值和 run_id 规则。
8. 检查 CSV/JSONL schema 可被标准解析器读取。

阶段转向条件：
- 目标目录已有不同 schema 时，先完成 schema migration 方案；
- 既有产物需要迁移时，先创建备份与映射表；
- 路径与工作区结构存在差异时，先更新路径清单。

完成标准：
- 所有治理文件存在且可解析；
- P00=PASS，G0=NOT_STARTED；
- 本阶段运行记录仅包含治理初始化；
- 给出下一阶段 P01 的明确入口。
```

## 4. P01：修复评估器并重评冻结 development bags

```text
阶段：P01 repair evaluator and re-evaluate frozen development bags

目标：实现 unique reference-grid 评测，建立 common-support 与 evo 双实现合同。G0 PASS 后启动 confirmatory export/VINS。

必读实现：
- scripts/evaluate_vins_sim_ape.py
- scripts/evaluate_vins_tum.py
- scripts/summarize_run_evidence.py
- 历史 A10、A09、A06 和至少一个 NTNU/UVVID、一个正常窗口的现有 trajectory/GT/config。

任务：
1. 先用测试或诊断脚本复现“同一 GT pose 被多个 estimate pose 使用”的问题，保存 before 证据。
2. 实现唯一 primary association：reference timestamps 去重排序；从 `{1,2,5,10}` 选低于或等于 metadata nominal reference rate 的最大 evaluation rate，以 frozen window start 生成 uniform grid；reference 和每个 estimate 的 translation 线性插值、orientation 用 SLERP 插值到有效 bracket 内。nominal reference rate >=1 Hz 的数据进入 primary table；legacy one-to-one nearest 用于诊断。
3. 在 evaluator_protocol_v1.md 为每个 dataset 依据 nominal sensor/reference rate 预注册 evaluation rate、reference/estimate max gap、timestamp offset、坐标变换和 tie-break；默认 gap 上限为 nominal period 的 2.5 倍。
4. 输出 raw/unique reference count、grid count、各 arm valid count、bracket gap P50/P95/max、rejection reason、support segments 和 coverage。
5. 实现 profile-configured contrast common grid/mask：promoted 为 P-B1、P-H、P-C-QG、P-D、P-M、P-B0 和描述性 B1-B2-H-P core mask；legacy 为 P_legacy-B1、P_legacy-C_legacy、P_legacy-D_legacy、P_legacy-M、P_legacy-B0 和 B1-B2-P_legacy core mask。APE 有效标准为 >=30 unique grid poses、span >=10 s、window coverage >=70%；1 s RPE 有效标准为 10 个同 segment pairs。内部 gap 分段处理；其余情况标记 INSUFFICIENT_COMMON_SUPPORT 并保留分母。
6. 锁定 primary/evo 等价语义：translation APE、每 arm 固定尺度 SE(3) align；RPE 为对齐后 global-frame positional delta error，配对同 segment 中相隔 evaluation_rate_hz 个 grid steps 的 poses。common TUM timestamps 以 17 significant digits 序列化；每个 segment 分别写 aligned-position + identity-quaternion TUM，并执行 `evo_rpe ... -r trans_part -d evaluation_rate_hz -u f` 后汇总全部 error samples。记录 evo v1.31.1、完整命令和 config；现有 10-frame RPE 标记为 legacy metric。
7. 增加最小单元/回归测试：reference 去重、GT unique use、translation/SLERP 边界、bracket range、max gap、内部 dropout/common mask、segment/RPE、最小 support、坐标/时间 offset、已知 toy trajectory。
8. 对现有冻结 bags 重评 A10、A09、A06、至少一个 NTNU/UVVID 和一个 normal 窗口，沿用原 export 与 gate。
9. 生成 legacy_vs_corrected.csv 和 g0_evaluator_validation.md，解释方向是否保持、增益是否来自 support 差异。

预期产物：
- 修正后的 evaluator 代码及测试；
- papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md；
- papers/ieee_sensors_journal_experiments/g0/legacy_vs_corrected.csv；
- papers/ieee_sensors_journal_experiments/g0/evo_crosscheck.csv；
- papers/ieee_sensors_journal_experiments/g0/g0_evaluator_validation.md。

阶段转向条件：
- primary/evo RMSE 差异超过 protocol tolerance 时，转入公式与序列化排查；
- reference 时间戳/坐标系待确认时，转入 reference audit。

完成标准：
- 所有 evaluator 测试通过；
- 五类 development case 交叉验证完成；
- G0 技术状态按 evaluator 测试/交叉验证判定；另按 companion plan 第 4.4 节输出 HISTORICAL_SIGNAL_PRESERVED/REVIEW/REDIRECT。REDIRECT 状态进入方法复核。
```

## 5. P02：历史排除、数据资格与选窗协议

```text
阶段：P02 history exclusion, data eligibility, and window-selection protocol

目标：机器化区分 development、sequence-held-out 和 external-held-out，并在 development 上冻结选窗规则；external 候选在本阶段完成 metadata/reference audit，最终 window manifest 由 P06 生成。

输入：
- logs/、papers/、正反例窗口整理/、runner 默认参数、bag/run 文件名；
- datasets/ 与 datasets/full_downloads/；
- P01 已通过的 evaluator protocol。

任务：
1. 全盘检索数据集、sequence、start/end、窗口别名及 prior learned/VINS 产物；保留检索命令。
2. 生成 history_exclusion_manifest.csv，字段至少符合实验闭环方案第 5.2 节。
3. 对每个候选数据检查 reference 独立性、nominal rate/时间覆盖、坐标系/尺度、许可、校准、IMU 与图像同步、原始文件 hash；依据 metadata/provenance 补全 evaluator_protocol_v1.md 的 dataset rate/gap/transform rows。
4. UMA-VI sample 归入 frontend/runtime 数据；带独立 GT 的完整序列进入 APE 候选表。
5. 在 development 数据上定义并验证 KLT/image-quality score、feature scaling、绝对 tau_low/tau_normal、序列内 percentile、固定窗口长度、非重叠、tie-break 和替换规则；low/normal 同时满足绝对 threshold 与相对 percentile，中间区归入 unclassified pool。screening 输入为 KLT/image-quality 指标。
6. external 候选在本阶段完成许可、文件完整性、reference provenance、标定/同步元数据和 checksum 审计；图像 screening 与 learned/P/VINS evaluation 分别在 P06 和 P07 执行。
7. 预注册目标：至少 3 域、20 个非重叠窗口；10 low-texture 和 10 normal；每窗 >=200 input frames，且 `duration>=max(20 s,(ceil(30/0.70)-1)/evaluation_rate_hz)`，1 Hz reference 至少 42 秒；H1 与 H4a/H4b 各覆盖至少 6 sequences（可重叠），每个 stratum >=2 domains；每 sequence 最多 4 窗；真正 external-held-out 域有独立 reference，并为 cross-domain claim 各贡献至少一个 low/normal 窗口。
8. 生成 data_eligibility_manifest.csv、window_selection_protocol.md、reference_audit.csv 和 input/reference checksum；window_selection_protocol 记录用于制定 score 的 B1 candidate source/config/runner hash。最终 dataset_manifest.csv/window_selection_audit.csv 由 P06 生成。
9. hash freeze 选窗规则和 eligibility manifest，并在 execution ledger 记录时间；P06 沿用该版本的 scaling、score、`tau_low`、`tau_normal`、percentile、tie-break 和替换规则。

阶段转向条件：
- external-held-out 数据就绪时进入 cross-domain 路线，其余情况进入 multi-sequence 路线；
- 候选窗口身份待确认时转入 history audit；
- GT/IMU/时间同步待确认时转入 reference audit；
- 选窗规则在 development 上完成后进入 hash freeze。

完成标准：
- history exclusion 决策逐项有 evidence_paths；
- eligibility manifest 和 window-selection protocol 已 hash freeze；
- eligible sequences 足以在 P06 构造目标矩阵；external-ready 对应 cross-domain candidate，其余对应 multi-sequence candidate；
- external 候选完成 metadata/reference audit。
```

## 6. P03：冻结主方法与环境候选版本

```text
阶段：P03 core method/config/environment candidate freeze

目标：冻结 B0/B1/B2/H 的上游方法和环境候选版本，并冻结 P 将继承的 trigger、proposal、KLT probation、correctness eligibility 与 budget contract。P03A 完成 selector shadow 后确定 P 的最终 ranker；P03B 迁移 canonical P；全部 arms 的最终哈希在 P06 合同探针通过后正式封存。

输入：
- G0/P01 PASS；
- P02 的 frozen history/eligibility manifest 与 window-selection protocol；
- uw_frontend/configs/README_recommended.md、canonical runners、模型权重；
- /home/ma/SLAM/VINS-Fusion-origin 的实际构建和配置。

任务：
1. 明确 B0 native VINS、B1 strong KLT、B2 ungated learned seed、H distance/grid heuristic 的唯一配置和执行入口；为 P、D、C-QG 与 M 预留显式 registry identity。同时在 development 上冻结 GFTT 或 FAST 中唯一 classical proposer identity、参数和 adapter，生成 calibration-only classical track rows；P04 不得换 detector。
2. 冻结 quality/health trigger、learned seed、KLT probation、survival、motion、F/H correctness eligibility、`K_t^0`、selector-independent master candidate stream、`B_active`、total feature cap 和 export contract；H/P 共享这些字段，admission/export 不得反馈改变后续 master pool。使用 external-feature interface 的 B1/B2/H/P/D/C-QG/M 后端 q 固定为 `1`，B0 保持 native 行为。核对 B1 hash 与 window_selection_protocol 一致；B1 更新时同步更新 P02 protocol version。
3. 定义单一 pooled `temporal_reliability_calibrator`：`Y_(i,t)^h=1` 表示未来冻结 h 帧内持续 KLT-valid 且 geometry-correct，每个 `track-lineage x decision time` 是一个 calibration row，同 lineage rows 不跨 train/calibration split，split 同时 sequence-disjoint。基础模型输出 `p_hat`，calibration 上以 `s=|Y-p_hat|` 得到 `Q_(1-alpha)`，selector 使用 `q_lower=clip(p_hat-Q,0,1)`。KLT base、learned-seeded 和已冻结 classical-seeded tracks 使用同一模型；feature schema 仅包含 age、NCC、FB、survival 与 `<=t-1` residual history，禁止 `base_quality`、detector confidence、source one-hot/model/blend/bucket 和当前 residual。冻结 h、alpha、split、overall/source/geometry subgroup coverage 与 base-model ECE gates；selector 不使用 backend `min_quality` floor。P03A 生成 provisional score，三类 calibration rows 齐备后 P03B 才能冻结模型。
4. 只用排序固定的 base-KLT correspondences 估计冻结 F/H model set，候选加入后不重估；固定 RANSAC seed/order/arbitration 和 mode-specific threshold `T_m`，使用 `e_i=min_m clip(r_m(i)/T_m,0,e_max)` 的无量纲残差。`NO_VALID_BASE_MODEL` 默认不准入新 lineage。冻结 `lambda_A>0`、`tau_e>0`、`min_gain>=0` 的所有权和 inner-development 决策规则；`tau_e` 与选窗 `tau_low/tau_normal` 无关。
5. 创建 protocol_v1_candidate.md，写明唯一窗口选择、association、common support、replay reducer、失败、重跑、统计、all-low HU P-H contrast 和成功标准；P06 将通过探针的候选版本封存为 selected `protocol_v1.md` 或 `protocol_v1_legacy.md`。
6. 创建 method_lock_candidate.json，记录已有上游 arms 的源码、runner、config、evaluator、VINS source tree、构建产物、模型和 calibration 的 SHA-256；Git commit 不适用时记录 canonical snapshot hash。P03B/P04/P05 新增 selector、控制和 baseline 文件并保持上游 candidate hash。
7. 创建 environment_manifest.txt：OS、ROS、Python、包版本、CUDA、PyTorch、OpenCV、evo、CPU/GPU、线程和资源设置。
8. 按 companion plan 第 6.5 节建立 pair-specific fairness：P-H 共享 selector-independent master stream/gates/maximum caps，P-C-QG 共享 selector/export function 但 candidate pool 独立，P-D 共享 P bag，P-B1 验证 fallback/no-harm；M、B0 与 official baseline 保留各自方法合同。
9. 依据 companion plan 第 9.5 节和 development logs 创建 failure_taxonomy_v1.yaml，冻结 replay-level valid/init/coverage/hard-failure/solver-risk/queue-drop/infrastructure signatures，以及 >=2/3 可评估的 window-arm reducer、any-repeat failure 和 any-of-3 solver-risk；运行分类器测试、已有测试和必要 smoke test，记录完整输出。

阶段转向条件：
- arm 依赖待确认时先完成 dependency audit；
- 受控 arms 的共享合同待统一时先完成 fairness mapping；
- 权重/配置/源码 hash 待补齐时先完成 release snapshot；
- canonical runner 的动态参数映射为显式 frozen config。

完成标准：
- protocol_v1_candidate.md、method_lock_candidate.json、environment_manifest.txt 均生成；
- H/P 共享的 selector-independent master-stream contract 已锁定，classical proposer/calibration rows 可用，P03A 具备 shadow 入口；
- G2 的主方法/环境部分 PASS，下一阶段为 P03A shadow selector；
- P06 正式封存后，方法更新创建新 protocol version，各版本结果分别归档。
```

## 7. P03A：实现 shadow selector 与路线晋级

```text
阶段：P03A marginal-support shadow prototype

目标：在既有 candidate stream 上实现 3x3 marginal geometric-support selector，完成合成验证与 6 个 development 窗口的排序审计，生成 `PROMOTE/BASELINE_ROUTE/REVISE` 决策。

输入：
- P03 冻结的 trigger/proposal/KLT probation/correctness/budget contract；
- `uw_frontend/ros/causal_lineage_shadow_node.py`、`uw_frontend/evaluation/measurement_selection.py`、`uw_frontend/quality/conformal_calibrator.py`；
- A10 `2400-2800`、A09 `4000-4400`、A10 `400-800`、A08 `7200-7600`、H07 `1660-1720` 与 Tank `short_test 0-15 s / 300 frames`。

任务：
1. 新增 `uw_frontend/geometry/marginal_support.py` 纯函数：输入 ID 互斥的 `K_t^0`、arm-specific `L_t`、从未准入的 `E_t`、image shape、冻结 base-model residuals 和 config，输出 selected IDs、`q_lower`、normalized residual、marginal gain、rank、rejection reason 和 deterministic frame-chain hash。
2. 实现正则化 3x3 image-plane support matrix：`z=[1,2u/W-1,2v/H-1]^T`，`w=q_lower*exp(-e/tau_e)`，`A0=lambda_A*I+sum_(K0 union L)(wzz^T)`，按最大 `log1p(w*z^T*solve(A,z))` 贪心选择至 `b_t=max(0,B_active-|L_t|)` 或 `min_gain`。使用 float64 Cholesky/solve 与 rank-one update，不显式求逆。
3. 使用 P03 定义的 provisional pooled calibrator 与 `q_lower=clip(p_hat-Q,0,1)`；强制 selector-specific schema，当前 normalized F/H residual 只进入 `exp(-e/tau_e)` 一次。记录 h/alpha/split/model hash、overall/source/geometry-stratum conformal coverage 和 base-model ECE；任一预注册 subgroup gate 失败则 calibration audit 失败。
4. 为冗余候选、新区域候选、低可靠性候选、F/H 归一化、无有效 base model、K0/L/E 去重、active cap、termination/不重准入、分辨率缩放和 stable tie-break 编写合成测试；记录 golden-vector hash。
5. 在 causal lineage shadow mode 同时记录完整 ranking：R 为 seed `20260730` 的 grid-balanced stable pseudorandom；H 为冻结 distance/grid；Q 按 `(-q_lower,canonical_id)` 且不用几何增益；G 对 K0/L/E 全部令 `q_lower=1` 后用 residual-weighted gain；QG 使用完整权重。既有 export 路径持续生成 H bag，shadow 结果单列保存。
6. 对 6 个固定 development 窗口执行 export-only probe，输出 master candidate-pool hash、model-fit hash/seed、`q_lower/e/gain/rank/reason`、actual admission count、exported-observation dose、H-QG overlap 和 frame-chain hash；分别报告 calibration、kernel、combined 的 invoked-frame P50/P95 和 all-frame amortized latency。
7. 以完整 QG policy 在每个共同 decision event 的 `n_t=|S_QG,t|` 为准，R/H/Q/G 各取完整 ranking 前 `n_t` 个构造 per-event admission-count-matched bags；后续 lifetime/observations 作为结果，不强制相等。每窗 R/Q/G 各总计 1 次 replay，H/QG 各总计 3 次（首次同时作 diagnostic，不是 `1+3`）。使用修正 evaluator 生成 APE、learned observations 和 visual-factor cost。
8. 生成 `shadow_rank_comparison.csv`、`selector_development_results.csv`、`selector_synthetic_test_report.md`、`selector_runtime_probe.csv`、`selector_shadow_manifest.csv` 和 `selector_decision.md`。

路线判定：
- rank percentile 归一化到 `[0,1]`，0 为最高优先级。对 `n_t>0` 的共同 events 定义 `o_t=|S_H,t intersect S_QG,t|/n_t`，`n_t=0` 不进入 overlap median。对 H policy 在正/反例原本会准入的 lineage，在首个 eligibility event 计算 H/QG rank percentile；`m=median(r_negative)-median(r_positive)`，`Delta_m=m_QG-m_H`。positive selected-dose retention 的分子为正例中同时被 QG 准入的 H-lineage 实际 observations，分母为全部 H-lineage observations；negative rank increment 是反例 H-lineage 的 `median(r_QG-r_H)`。
- admission-count-matched QG 对 X=Q、G 分别通过单因素门槛：4 个 low/boundary 窗口的 median APE 改善 >=2%，或 APE degradation <=2% 且 learned observations/visual-factor cost 降低 >=20%；同时至少 3/4 窗口 APE degradation <=2%。完整 H/QG policy 在两个 normal 窗口的 QG degradation 均 <=5%。
- `PROMOTE`：合成与 calibration 合同通过；QG 同时通过 Q/G 门槛；positive selected-dose retention >=90%；negative rank percentile 相对 H 增加 >=0.10；并满足 `o<0.90` 或 `Delta_m>=0.10`。
- `BASELINE_ROUTE`：合成合同和 calibration audit 均通过，且 `o>=0.90`、negative rank percentile 增量 `<0.10`。生成 `protocol_v1_legacy_candidate.md`：`P_legacy=H_confirmatory`，使用 B0/B1/B2/P_legacy/D_legacy/C_legacy/M 的 7-arm profile，移除 HU/P-H confirmatory contrast。
- `REVISE`：其余组合。调整 selector/calibration 后创建新的 P03A candidate version。

完成标准：
- 纯函数、合成测试、shadow logging、6 窗 export-only probe 和 route-decision VINS diagnostics 完成；
- `selector_decision.md` 记录完整证据、路线与下一阶段；
- `PROMOTE` 进入 P03B；`BASELINE_ROUTE` 跳过 P03B，但仍必须完成 P04 legacy control 和 P05 M integration；`REVISE` 保持在 P03A。
```

## 8. P03B：迁移 canonical P 与冻结可靠性选择器

```text
阶段：P03B promote and freeze canonical marginal-support selector

目标：将经 P03A 晋级的 QG selector 迁移到唯一 canonical hybrid/export implementation，训练并冻结 pooled reliability calibration，使 H/P 对照使用可审计的统一选择合同，并为 P04 提供 source-neutral selector API。

输入：
- P03A=`PROMOTE` 与完整 shadow artifacts；
- `uw_frontend/tracking/hybrid_tracker.py`、`uw_frontend/ros/export_vins_features.py`、`uw_frontend/quality/conformal_calibrator.py`；
- P03 frozen upstream contract、development calibration split 和 C-QG matching plan。

任务：
1. 将 `marginal_support.py` 接入 `hybrid_tracker.py` 的 confirmed learned candidate selection，再接入 `export_vins_features.py` 的 canonical online export path。accepted ID 不重排、不驱逐、不重准入，仅按 H/P 共用的 LK failure/出界/持续正确性 termination contract 结束。
2. 只有在 KLT base、learned-seeded 和 P03 冻结 classical proposer 的 calibration rows 均存在时，才训练并冻结单一 pooled `temporal_reliability_calibrator`；三类 track 使用同一 selector-specific schema、h/alpha/split/model。生成 `reliability_calibration_protocol.md` 和 `reliability_calibration.csv`，记录 model/config/data hash、overall/source/geometry coverage 和 base-model ECE。
3. H/P 消费逐帧相同的 selector-independent master stream，共享 KLT base、correctness gates、`B_active`、total feature cap、exporter、constant backend `q=1` 和 stable tie-break；arm-specific admission 只影响 `L_t` 和 export。selector API 接受 source-neutral temporal track evidence，P04 用该 API 构造完整 C-QG。若 master-stream hash 在首个选择分歧后不一致，P-H selector-only contract 失败。
4. 冻结 `lambda_A`、`tau_e`、`B_active`、total feature cap、`min_gain`、pooled model/config hash 和 reason vocabulary。frame-chain hash 包含规范排序后的 K0/L/E IDs、z/q/e、image shape、model-fit hash/seed、active slots、ordered decisions/gains/reasons 及 selector/model/config hash，浮点使用冻结 IEEE bytes 或 17-digit serialization；更新 protocol_v1_candidate.md 与 method_lock_candidate.json。
5. 在两个 positive、两个 negative、两个 normal development 窗口完成 H/P export-only contract probe、最小 VINS smoke和 classical candidate adapter 接口测试；报告 master-stream equality、selection-active rate、calibration/kernel/combined latency、observations 和 visual-factor count，并确认冻结模型下仍满足 P03A 的 `PROMOTE` 判据。完整 C-QG control 在 P04 实现与验证。
6. 为 canonical path 增加单元/合同测试，验证 K0/L/E 互斥、selected IDs、reject reasons、constant backend q、active cap、termination/不重准入和 repeatable golden/frame-chain hash。

完成标准：
- canonical P、pooled reliability calibration、H/P paired contract 和 C-QG selector API 完成；
- `method_lock_candidate.json`、`selector_config.yaml`、`reliability_calibration_protocol.md` 与测试报告已更新；
- selector-invoked frames 的 combined calibration+selection P95 <=1 ms/frame，并分开报告 calibration、kernel 与 all-frame amortized latency；
- 进入 P04/P05 的 controls and baseline integration。
```

## 9. P04：实现 matched classical seed control

```text
阶段：P04 implement and test matched classical seed control

目标：依据 method profile 构造 trajectory-outcome-blind offline matched-dose classical attribution control。promoted profile 使用 C-QG 与 pooled calibrator/QG selector；legacy profile 使用 C_legacy 与 P_legacy 的 frozen heuristic admission。两种 profile 都比较 learned seed 与同剂量 classical 长轨迹的贡献；它们不称为随机化或无条件 causal control，匹配在完整 frontend track log 生成后、读取任何 VINS trajectory metric 前完成。

输入：
- promoted `protocol_v1_candidate.md` 或 `protocol_v1_legacy_candidate.md` 的 seed/admission/export contract；
- causal lineage logs 与 whole-lineage drop 工具；
- development active-positive、active-negative、normal zero-action 窗口。

任务：
1. 验证并复用 P03 已冻结的唯一 GFTT/FAST proposer identity、参数、adapter 和 calibration rows；P04 不得重新选 detector。
2. 在与 selected proposed arm 相同的 trigger frame 产生独立 classical master candidate log，随后使用同一 KLT propagation、survival、motion、F/H correctness eligibility 和 backend export contract。
3. promoted only：classical pool 先独立执行完整 pooled reliability + QG selector。matching 只能对已准入 C-QG lineages 配对或子采样，不得提升、重排或挽回被 QG 拒绝的候选。确认 C-QG 除 proposal source 和预注册 matching 外，与 P 共用 carrier/QG selector/export function。
4. promoted only：对每条 accepted learned lineage 匹配 birth/trigger frame、activation frame、grid cell/位置、lifetime、export observation count、`q_lower`、marginal gain、maximum caps 和 backend q。
5. 冻结 matching objective、caliper、tie-break 和 unmatched 规则，并用 development candidate pool 冻结 standardized-difference scale。字段使用 profile-neutral 名称 `lifetime_control/lifetime_proposed`、`obs_control/obs_proposed`。hard gates：trigger exact；activation diff <=1 frame；same grid cell 或 image distance <=0.10 diagonal；`abs(lifetime_control-lifetime_proposed)<=max(2 frames,0.10*lifetime_proposed)`；`abs(obs_control-obs_proposed)<=max(2 obs,0.10*obs_proposed)`；window total dose/peak budget diff <=5%；continuous covariate absolute SMD <=0.10；unmatched lineages <=20% 且 unmatched observation dose <=10%。
6. 固定 detector、stable sort、tie-break 和 deterministic settings；输出 per-lineage balance、标准化/绝对差、lineage/observation unmatched 比例、dose、peak budget 和 selector-score 审计。promoted 的 selector score 是 `q_lower/marginal_gain`，legacy 是 frozen heuristic score。所有 learned lineages 均进入 balance 分母。
7. D/D_legacy 覆盖完整 learned-born lineage，包括后续由 KLT 延续的 observations。
8. 在 development 的 active positive、active negative、zero-action 上做 export-only 测试，再做最小 VINS smoke；matching 标准沿用冻结 protocol。
9. 增加单元/合同测试，确认 matching 不读取 trajectory metric、不挽回 selector rejection，drop 是 exact whole-lineage，重复 export/control hash 一致。
10. legacy only：P_legacy/C_legacy 共享 trigger、KLT carrier、correctness gates、frozen heuristic admission、maximum caps、exporter 和 backend `q=1`；不计算 `q_lower/marginal_gain`，用 frozen heuristic score 做 balance audit。输出 `legacy_control_contract.md`，HU/P-H 字段记 `NOT_APPLICABLE`。

预期产物：
- matched classical control 实现、配置与测试；
- matched_control_protocol.md；
- development_control_balance.csv；
- exact_drop_audit.csv；
- implementation_decision_log.md。

阶段转向条件：
- C-QG 需要新的 P contract 时，创建新的 method candidate version；
- C-QG/P 的 KLT、QG selector 或 backend budget 存在差异时，先完成合同统一；
- D whole-lineage audit 存在差异时，先修正派生逻辑。

完成标准：
- 开发集合同测试全部通过；
- P04=PASS 表示 selected profile 的 classical/drop control 实现与 development 审计完成；另写 `H2_CONTROL_CONTRACT=PASS/REVISE`。confirmatory `H2_ELIGIBLE` 必须在 P07/P09 按每窗 balance、determinism 和 common support 重新解析，不由 development PASS 代替；
- exact whole-lineage drop 得到逐 observation 审计；
- control 使用冻结 matching protocol。
```

## 10. P05：现代 learned VINS baseline 与公平性审计

```text
阶段：P05 modern baseline integration and fairness audit

目标：形成覆盖全部 confirmatory 窗口的 controlled same-backend modern baseline（M）；官方端到端 baseline 作为兼容子集的附加 system reference。

输入：
- P03/P03B promoted candidate 或 P03A legacy candidate 的 method/environment hashes 与公平性合同；
- 项目已有 SP-LG、XFeat/LK 实现、模型权重和 development smoke windows；
- P02 eligible data formats/calibration metadata。

优先级：
1. 核心：本项目真实实现的 SP-LG same-backend、direct/periodic XFeat+LK same-backend 或等价现代 learned frontend，能在全部主矩阵窗口运行，并具有独立于 B2/H/P 或 P_legacy 的方法身份；
2. 可选强化：官方 SuperVINS，在其官方支持的数据/配置子集可靠复现。

任务：
1. 先检查许可证、官方代码/权重、输入支持、校准合同和可复现性；记录版本/hash。
2. 官方实现使用官方名称；本地实现使用准确名称，如 SP-LG same-backend reproduction。
3. 在 development 上冻结 baseline 配置。
4. same-backend reproduction 匹配 raw image/IMU/GT、window、图像尺度、feature budget、VINS config、constant backend q、common support、硬件和失败判据。
5. official end-to-end baseline 匹配 raw input、window、标定、硬件、失败和评测合同，并报告其原生 backend、preprocessing、budget 和线程配置。预注册 compatible subset 和分母，official baseline 与 M 分表呈现。
6. 在 development smoke window 完成输入/输出/时间/预算/坐标系审计。
7. 生成 learned_baseline_fairness.md 和 machine-readable fairness_audit.csv。

阶段转向条件：
- M 数据格式覆盖待补齐时，先完成 adapter 与 smoke test；
- official baseline 的输入合同与主矩阵不同時，采用 compatible subset；
- baseline/P 配置在 development 上完成冻结后进入 P06。

完成标准：
- M 通过 smoke 和公平性审计，并具备全矩阵执行入口；
- 命名、代码来源和限制准确；
- baseline identity 与 counterbalancing rule 纳入 candidate registry/protocol；实际 arm_order.csv 由 P06 在 final windows 生成后封存；
- M 全矩阵执行入口完成后 P05=PASS；其余状态标记 REVISE。
```

## 11. P06：export-only 合同探针

```text
阶段：P06 export-only contract probes

目标：先用 development/auxiliary data 验证每个 arm 的合同并冻结 method hashes；随后把 P02 的冻结 KLT-only 规则应用到 eligible confirmatory sequences，生成最终 dataset/window manifest。confirmatory learned/P/VINS 从 P07 开始。

输入：
- P02 frozen eligibility/window-selection protocol；
- P03/P03B promoted candidate 或 P03A legacy candidate 的 method/environment/failure taxonomy；
- P04 selected-profile classical/drop implementation and balance protocol；
- P05 M implementation/fairness audit；
- development/auxiliary probe cases。

选择固定探针：
- known active positive；
- known active negative；
- normal zero-action：Tank `short_test 0-15 s / 300 frames`；
- normal nonzero-action：在 development inventory 中仅用冻结 image/KLT stratum 和 selected proposed `accepted_lineage_count>0` 选出 degradation score 最低的窗，必须先将 exact dataset/sequence/start/end registry key 写入 probe manifest。若无符合项，记 `NO_ELIGIBLE_NORMAL_NONZERO_ACTION`，仅用冻结 boundary-active case 做 integration smoke，不得充当 normal no-harm 证据；
- cross-format auxiliary integration smoke window；该 domain 明确标记为 development，并与 external-held-out domain 分离。

任务：
1. 使用 canonical runner 的 RUN_VINS=0 或真实等效选项，并核对脚本参数。
2. 审计 topic、channel schema、feature ID、timestamp、frame count、image/IMU support、feature cap 和 backend q。
3. promoted profile 比较 B1/B2/H/P/D 的 selector-independent master stream、KLT carrier、eligibility、`q_lower/e/gain`、maximum caps 和时间支持；C-QG 的 classical candidate pool 独立，只审计共用 reliability/QG/export function 与 matching balance。legacy profile 比较 B1/B2/P_legacy/D_legacy 的 master stream/legacy admission/caps/time support，C_legacy 使用独立 classical pool 和同一 heuristic admission；M、B0 与 official baseline 按各自合同审计。
4. 检查 selected profile 的 drop arm 删除完整 learned-born lineage，classical control 的 dose/lifetime/activation/selector-score balance 成立。
5. zero-action 时 selected proposed arm 与 B1 feature stream 达到 byte-identical 或逐点语义等价；promoted P 的 master candidate-pool 和 frame-chain hash 可回溯。
6. frontend deterministic 时重复 export、selector decision 和 hash；其余实现锁定 seed 并量化差异来源。
7. 用 development positive/negative logs 验证 failure_taxonomy_v1.yaml 的分类结果，输出 contract_probe_results.csv、bag_hashes.csv、schema_audit.json、failure_taxonomy_validation.csv 和 probe_report.md。
8. 探针全部通过后，将 selected profile 的 P03B（promoted only）、P04/P05 hash 合并到 method_lock.json，并记录最终 method freeze 时间。方法本体更新时创建新的 candidate version；integration data 保持 development 身份。
9. method hash 冻结后，使用 window_selection_protocol.md 中的固定 KLT/image-only 命令筛选 eligible sequences，沿用 frozen scaling、score、`tau_low`、`tau_normal`、percentile、tie-break 和替换规则。
10. 生成 dataset_manifest.csv、window_selection_audit.csv、dataset_checksum_manifest.txt 和 arm_order.csv；检查至少 3 域、20 窗、10 low/10 normal、每个 stratum >=6 sequences/>=2 domains、每 sequence <=4 窗及 external 身份。promoted profile 每窗登记 B0/B1/B2/H_confirmatory/P/M，legacy profile 每窗登记 B0/B1/B2/P_legacy/M。D/C-QG 或 D_legacy/C_legacy 在每窗预注册为 `CONDITIONAL_ON_PROPOSED_ACTIVE` 的 3-replay slots，applicability rule 冻结为 `accepted_lineage_count>0`；P06 不解析 active，不写 `NOT_APPLICABLE`。
11. 将 method profile、method lock、dataset manifest、evaluator、failure taxonomy、environment 和 arm order hash 写入最终 protocol_v1.md 或 protocol_v1_legacy.md；所有 confirmatory run 使用该冻结版本。

阶段转向条件：
- zero-action fallback 差异进入 stream audit；
- selected profile 的 drop/classical-control 合同差异进入 control audit；
- arm 的 budget、q、timestamp 或 preprocessing 差异进入 fairness audit；
- run directory 或 ROS 进程状态待整理时先完成环境清理；
- frozen selector 形成的矩阵规模不足时，记录实际规模并进入 REVISE。

完成标准：
- 所有 required arms 通过 contract probe；
- selected `protocol_v1.md` 或 `protocol_v1_legacy.md`、method_lock.json、dataset_manifest.csv、window_selection_audit.csv、failure_taxonomy_v1.yaml、environment_manifest.txt 和 arm_order.csv 已最终 hash freeze；
- promoted profile 为 G2/G2A/G2B/G3=PASS；legacy profile 为 G2/G2A/G3=PASS 且 G2B=NOT_APPLICABLE；
- probe 使用冻结 threshold；
- 明确 P07 入口状态。
```

## 12. P07：执行确认性 VINS 主矩阵

```text
阶段：P07 run confirmatory VINS matrix with monitoring

目标：完整执行 frozen manifest，逐项登记结果、replacement 与失败状态。

前置条件：
- G0-G3 全部 PASS；P03A 已完成路线确认；promoted profile 的 P03B=PASS，legacy profile 的 P03B=NOT_APPLICABLE；
- dataset_manifest、selected protocol、method_lock、failure_taxonomy_v1、environment_manifest、arm_order 和 run_registry 均已冻结并 hash；
- P04 selected-profile control audit 已完成并记录 `H2_CONTROL_CONTRACT=PASS`；P05 M 已通过合同审计。confirmatory H2 eligibility 由本阶段的逐窗 balance/determinism/common-support 解析，不从 development 直接继承。

任务：
1. 从 frozen dataset_manifest 和 arm_order 生成 frontend-export queue 与 backend-replay queue；conditional control slots 保持 `PENDING_APPLICABILITY`。
2. 先构造 promoted 的 B1/B2/H_confirmatory/P/M 或 legacy 的 B1/B2/P_legacy/M，B0 使用 native path。selected proposed export 完成后、读取任何 trajectory metric 前，仅按 `accepted_lineage_count>0` 生成 append-only `arm_applicability.csv`：active 窗将 D/C-QG 或 D_legacy/C_legacy 解析为 `APPLICABLE`，zero-action 解析为 `NOT_APPLICABLE`；两者都保留在 no-harm 分母，且不修改 arm_order counterbalancing hash。
3. D/D_legacy 从 selected proposed bag 执行 exact whole-lineage drop；C-QG/C_legacy 不从 learned measurements 派生，而是在 proposed identity/dose 冻结后从独立 frozen classical candidate log 构造并匹配。frontend 确定时每 arm 导出一次并记录 master candidate-pool/frame-chain/export hash；随后对 B0 及所有 applicable frozen bags 按 arm_order.csv counterbalance 串行 VINS replay 3 次。bag dependency 与 backend replay order 分开记录。
4. 同一时刻运行一个 VINS/roscore/rosbag 实例；监控进程、CPU/GPU、磁盘、ROS master 和输出增长。
5. 每次 replay 前后检查进程，并按本实验 PID/command 身份完成清理。
6. 按冻结 failure_taxonomy_v1.yaml 对每个 replay 的 crash、timeout、empty/nonfinite trajectory、init、coverage、solver-risk、queue drop 和 infrastructure failure 分类并写入 registry/ledger；日志与 signature version 一并保存。每个 window-arm 在 >=2/3 可评估时对数值取 median，否则记 `WINDOW_ARM_HARD_FAILURE`；另存 `any_repeat_hard_failure`，solver-risk 按 any-of-3 归并。
7. 基础设施故障创建 replacement run_id；原 run 状态保留，并关联 replacement_for/reason。有证据的 infrastructure run 不占用 3 个 algorithmic slots，replacement 必须填回原槽位。
8. 每完成一个窗口立即运行修正 evaluator，生成 full-support 与预注册 contrast-specific common-support 机器结果；后续方法和窗口沿用 frozen protocol。
9. 定期生成 progress summary：planned/completed/failed/waiting/not_applicable，全量报告各状态。
10. 全矩阵完成后检查 registry 是否有遗漏、重复、孤立目录或 hash 漂移。promoted profile 每窗必须有 B0/B1/B2/H_confirmatory/P/M 状态，legacy profile 每窗必须有 B0/B1/B2/P_legacy/M 状态；每个 conditional control slot 必须在 `arm_applicability.csv` 中解析为 3 个 algorithmic replay 状态或 `NOT_APPLICABLE`，不得留在 `PENDING`。
11. `active` 和 promoted `selection-active` 必须在读取 trajectory metric 前解析。HU 的 effect/failure denominator 始终是全部 10 个 low windows；>=6/10 selection-active、>=3 sequences/2 domains 仅是 adequacy gate。在 export/drop/control audit 和 common-support mask 生成后、计算 APE effect 前，逐窗解析 `H2_ELIGIBLE = active + classical balance PASS + deterministic PASS + P*-C* common support PASS` 与 `H3_ELIGIBLE = active + exact-drop PASS + P*-D* common support PASS`；两者各需 >=6/10 low windows、>=3 sequences/2 domains。H4a 始终在全部 10 个 normal windows 上判定；>=3/10 active 且覆盖 >=2 sequences 时额外判定 H4b，否则 H4b=`INCONCLUSIVE_ACTIVITY`。

阶段转向条件：
- method/input/evaluator hash 与冻结值存在差异时转入 version audit；
- arms 的输入、budget、q 或 support 合同存在差异时转入 fairness audit；
- 同类基础设施故障连续发生三次时转入 environment audit；
- 磁盘/硬件状态异常时转入资源维护；
- 方法更新需求进入新 protocol version。

完成标准：
- frozen manifest 的每个 required arm/replay 都有 COMPLETED/FAILED/BLOCKED/NOT_APPLICABLE 状态，arm-count 与 3-replay completeness audit 通过；
- 每个 run 具备 exact command、输入输出 hash、frontend/VINS log、trajectory、评测和 failure summary；
- replacement 均有原 run、证据和 reason；
- G4=PASS 表示矩阵完整，假设结论由 P09 判定。
```

## 13. P08：运行时与资源测量

```text
阶段：P08 runtime profiling

目标：用固定硬件和冻结方法给出可复现的计算代价，并确定 `real-time`、`selective` 或 `offline-capable` 表述。

输入：
- frozen protocol/method/environment/hardware manifest；
- P07 完成的代表性 low/normal runs 与输入频率；cross-domain 版本包含 external-held-out，multi-sequence 版本使用预注册第三域或 sequence-held-out run；
- 可记录 stage latency、message count、queue 和 CPU/GPU memory 的 profiling hooks。

任务：
1. 固定 CPU/GPU、频率/电源模式、线程、图像尺度、输入频率、warm-up、测量时长和后台负载说明。
2. 分阶段测量 preprocessing、KLT、learned inference/matching、eligibility、reliability calibration、marginal-support selector、export、VINS backend 和 end-to-end。
3. 报告 per-frame 与按触发频率摊销后的 P50/P95、throughput、CPU/GPU memory、GPU utilization、queue depth/drop。
4. 至少覆盖一个 low-texture active、一个 normal zero-action 和已在 P06 probe manifest 冻结的 normal nonzero-action；若 P06 已记 `NO_ELIGIBLE_NORMAL_NONZERO_ACTION`，用冻结 boundary-active integration case 补 runtime coverage 并明确标记，不伪称 normal。cross-domain 版本覆盖一个 external-held-out 窗口，multi-sequence 版本覆盖预注册第三域或 sequence-held-out 窗口，并采用相应 runtime 表述。
5. online runtime 主表在同一硬件合同下比较 promoted B1/H/P/M 或 legacy B1/P_legacy/M。C-QG/C_legacy 的 offline candidate construction/matching cost 单列，不进入 online throughput/H5；official baseline 的硬件/实现采用独立表格。
6. end-to-end latency 从输入接收计时到 backend output，并与 matcher inference 分项同时报告。
7. 生成 runtime_long.csv、runtime_summary.csv、resource_summary.csv、selector_runtime.csv 和 runtime_report.md；同时报告 learned observations、visual factor count、calibration/kernel/combined selector overhead、invoked-frame P50/P95 和 all-frame amortized cost。

阶段转向条件：
- arms 间硬件功耗/频率/线程配置存在差异时，先统一 profiling environment；
- instrumentation 改变调度时，先完成 overhead calibration；
- queue drop 记录待补齐时，先完成 message accounting；
- 汇总表同时包含均值、分位数和样本量。

完成标准：
- 所有阶段耗时与资源可追溯；
- amortized throughput >= input rate 且 sustained queue drop=0 时记 `PROFILED_REAL_TIME` 并允许 real-time；
- 其余结果记 `PROFILED_SELECTIVE` 或 `PROFILED_OFFLINE`，使用 selective、asynchronous 或 offline-capable；低 throughput 不单独导致科学结论 FAIL，但禁止 real-time claim；
- G5 的 runtime 部分完成。
```

## 14. P09：统计汇总与敏感性分析

```text
阶段：P09 statistical aggregation

目标：从 append-only registry 和 run 产物生成唯一结果源。promoted profile 以 sequence 为主推断单位验证 HU/H1/H2/H3/H4a/H4b 并给出 H5 profiling status；legacy profile 验证 H1/H2/H3/H4a/H4b、给出 H5 profiling status，并将 HU 标为 NOT_APPLICABLE。

输入：
- frozen dataset/protocol/evaluator/failure taxonomy hashes；
- 完整 run_registry、全部 run directories、P08 runtime tables；
- H/P master-stream/selection audits、arm_applicability.csv、reliability calibration、classical balance、exact-drop 和 activity audits。

任务：
1. 验证 registry 完整性、hash、protocol version、失败、replacement 和 NOT_APPLICABLE 逻辑；每个 conditional control slot 必须在 arm_applicability.csv 中解析为 3 个 algorithmic replay 或 NOT_APPLICABLE，且解析时间早于任何 trajectory metric read。
2. 生成 results_long.csv：一行对应 window x arm x replay，保留 full-support、coverage、init、replay/window-arm failure、any-repeat failure、any-of-3 solver-risk、runtime、learned observations、visual factor count、calibration/kernel/combined selector overhead 和前端指标。
3. 生成 contrast_results_long.csv：promoted profile 预注册 P-B1、P-H、P-C-QG、P-D、P-M、P-B0 和 B1-B2-H-P core support；legacy profile 预注册 P_legacy-B1、P_legacy-C_legacy、P_legacy-D_legacy、P_legacy-M、P_legacy-B0 和 B1-B2-P_legacy core support。
4. 按冻结 reducer：对每个 window x contrast x arm，>=2/3 可评估时对可评估 replay 取中位数，<2/3 记 WINDOW_ARM_HARD_FAILURE；replay variance 与 any-repeat failure 单独报告，主检验 `n` 为 sequence 数。
5. 生成 case_summary.csv：一行对应 window x contrast x arm；定义 `P*=P` (promoted) 或 `P_legacy` (legacy)，`r_w=log(APE_(P*)/APE_comparator)`，再生成 sequence_summary.csv，以 sequence 内 median `r_w` 得到一个 `r_s`，总体 improvement=`100*(1-exp(median_s(r_s)))`，每条 sequence 贡献一个等权 effect。
6. 唯一 primary 均为 low-texture proposed vs B1。promoted profile 的关键方法 contrast 为 P vs H，mechanistic secondary 为 P vs D、P vs C-QG；legacy profile 的 mechanistic secondary 为 P_legacy vs D_legacy/C_legacy；normal proposed vs B1 是 operational no-harm gate。
7. H1 作为唯一 primary contrast；95% CI 使用 seed=20260730、10,000 次 percentile hierarchical bootstrap（先抽 sequence，再抽其 windows），小样本 p 值用 `r_s` 的 exact two-sided sign test。promoted Holm family 固定为 `{HU,H2,H3}`，legacy 为 `{H2,H3}`，family-wise alpha=0.05。adjusted p/CI 作支持性报告，HU/H2/H3 PASS 由 practical-effect + adequacy/safety gates 决定；adjusted p 未通过时不得写 statistically significant。domain 作分层描述，报告 window/sequence win count、sequence-equal median/IQR/95% CI 和 sequence-level rank-biserial effect。
8. 按 companion plan 第 9.5 节先机器分类 replay-level valid pose、init failure、coverage、hard failure、solver-risk、queue drop 和 infrastructure failure；再生成 window-arm reducer、any-repeat hard failure、any-of-3 solver-risk 与 contrast insufficient support。分类器及 log signatures 在 development 上冻结。
9. 所有预注册窗口进入 failure denominator：proposed-only window-arm fail=automatic loss，B1-only fail=proposed failure-win，双 fail=failure-tie，support 不足=INCONCLUSIVE_PAIR；数值 APE 使用双方可评估 pairs，failure table 覆盖完整分母。
10. 在计算 effect 前生成 contrast eligibility：`H2_ELIGIBLE = active + control balance PASS + deterministic PASS + P*-C* common support PASS`；`H3_ELIGIBLE = active + exact-drop PASS + P*-D* common support PASS`。两者分别需 >=6/10 low windows、>=3 sequences/2 domains；全部 active/unmatched/ineligible 项仍进入 activity/balance table。
11. 分开判定 H4a/H4b：H4a 的分母始终是全部 10 normal windows 和全部预注册 normal sequences；>=9/10 windows 必须可评估且 degradation <=5%，>=80% sequences（最少 5 条）必须有可评估 pair、`r_s<=log(1.05)`、coverage sequence-median loss <=2 pp 且无 proposed-only failure，solver-risk event rate 不增加。insufficient/no-pair 窗或序列不记 success。H4b 在 >=3 active normal windows 跨 >=2 sequences 时额外判定，要求全部 active windows 可评估、degradation <=5%、coverage loss <=2 pp、proposed-only fail=0、solver-risk 增量=0；activity 不足时 H4b=`INCONCLUSIVE_ACTIVITY`，H4a 仍独立判定。
12. promoted profile 判定 HU：APE/failure estimand 使用全部 10 low windows，selection-active >=6/10、>=3 sequences/2 domains 仅是 adequacy gate。成功路径为 sequence-equal median APE improvement >=3%；或 APE degradation <=2% 且 learned observations 或 visual-factor cost reduction >=30%。成本在同一 all-low set 上先按 sequence 求和再计算 `1-cost_P/cost_H`，最后 sequence 等权 median；`0/0` 为 neutral 且不能单独满足成本路径，`cost_H=0,cost_P>0` 为恶化。同时检查 master-stream equality、maximum caps、within-arm frame-chain hash 与 invoked-frame combined calibration+selection P95 <=1 ms。legacy profile 将 HU=NOT_APPLICABLE。
13. 汇总 admission-count-matched development R/H/Q/G/QG，以及独立 classical pool 的 C-QG。按 P03A 固定门槛判定 QG 对 Q、G，并报告 overall/source/geometry conformal coverage、base-model ECE、H-QG overlap 与正负例 rank margin。
14. 进行预注册敏感性：contrast-common-mask vs full-support、H/P master-stream equality、reliability calibration、D-vs-B1 stream equivalence/gap、classical matching balance、hierarchical resampling choices，并完整呈现各分析。
15. 所有预注册窗口、solver-risk、unmatched classical lineages 和缺失值进入报告。
16. promoted 验证并保留 P03B 生成的 reliability_calibration.csv，不覆写其 frozen rows；legacy 将其标为 NOT_APPLICABLE 并保留 P03A provisional calibration audit。输出 selector_decisions.csv、matched_control_balance.csv、sequence_summary.csv、selector_ablation.csv、selector_pareto.csv、statistics.json、statistics_report.md、failure_table.csv、failure_sensitivity.csv 和 hypothesis_decisions.csv。

阶段转向条件：
- 表格与机器源存在差异时，先修正生成脚本；
- 统计单位检查确认主检验 `n=sequence`；
- protocol version 分别汇总；
- failure denominator 与 frozen manifest 对齐；
- 统计脚本通过固定 bundle 的 clean reproduction。

完成标准：
- 单一 pipeline 可从 registry/results_long/contrast_results_long 重建全部统计；
- promoted profile 对 HU/H1/H2/H3/H4a/H4b、legacy profile 对 H1/H2/H3/H4a/H4b 给出 PASS/FAIL/INCONCLUSIVE、effect、CI、failure context；H5 给出 `PROFILED_REAL_TIME/PROFILED_SELECTIVE/PROFILED_OFFLINE`；
- hypothesis status 对应 READY、CONDITIONAL 或 REVISE 表述；
- G5 的统计部分完成。
```

## 15. P10：论文图表与 claim-evidence 审计

```text
阶段：P10 figures/tables and claim audit

目标：生成 IEEE Sensors Journal 稿件所需的机器化表图，并使每个陈述对应明确证据。

输入：
- P09 的 results_long、contrast_results_long、case/sequence summary、failure/statistics tables；
- P08 runtime/resource tables；
- companion plan 的 claim boundaries 和 project-progress-review。

任务：
1. 从 results_long.csv、contrast_results_long.csv、case_summary.csv、sequence_summary.csv、selector_ablation.csv、selector_pareto.csv、failure_table.csv、runtime_summary.csv 自动生成 Table I-IV 和 Figure 1-5 的数据/图。
2. Figure 2 显示全部 per-window `P*`/B1 APE ratio、texture stratum、sequence/domain 和 5% no-harm line。
3. 使用 route-specific Table III/Figure 4：promoted 报告 confirmatory P-H、C-QG、D 和 development Q/G/QG，并标注 HU 两条成功路径；legacy 主表报告 P_legacy-D_legacy/C_legacy，QG/P-H/HU 仅放 development/Discussion，不得伪装成 confirmatory。
4. 表中同时报告 common-support accuracy、full coverage、init、failures 与全部 run 状态。
5. 生成 claim_evidence_matrix.md：每条 claim、支持数据、统计单位、适用范围、论文措辞、对应表图。
6. 做术语全局映射：
   - promoted 方法使用 reliability-calibrated marginal geometric-support selection；legacy 改用 selective learned-seeded KLT system；
   - learned feature 使用 learned seed proposal；
   - lineage 定位为 provenance/ablation；
   - 本地 baseline 使用 SP-LG/XFeat same-backend reproduction 等准确名称；
   - external-ready 版本使用 cross-domain evaluation，其他版本使用 multi-sequence evaluation；
   - `q_i^-` 使用 conservative conformalized reliability score，不写 conditional probability lower confidence bound；
   - 3x3 support 是 image-plane surrogate，不写 FIM、6DoF observability 或 backend covariance optimization；
   - Related Work 显式对照 Good Features to Track、Learned Good Features to Track、CHAMELEON-SLAM 和 CF2-SLAM，区分点是 selector-independent KLT master stream 上的多帧 learned-lineage marginal admission；正式引文必须另行验证；
   - runtime 按 H5 的 `PROFILED_REAL_TIME/PROFILED_SELECTIVE/PROFILED_OFFLINE` 使用 real-time、selective 或 offline-capable；
   - no-harm 表述为 operational no-harm。
7. 对照 project-progress-review，将 `H_legacy`、A06 LoFTR、跨后端和 raw q_i 结果放入其对应的 development/Discussion 位置；promoted P 的 confirmatory 数字从冻结 P03B method hash 产生，legacy 数字使用 `P_legacy` identity。
8. 生成 tables/、figures/、figure_data/、table_data/ 和 paper_result_inventory.md。

阶段转向条件：
- 图表与机器表存在差异时，先修正生成 pipeline；
- 主图包含全部预注册窗口与完整分母；
- development 与 confirmatory 证据分栏呈现；
- promoted 的 HU/H1/H3/H4a/evaluator 或 legacy 的 H1/H3/H4a/evaluator 状态为 REVISE 时，稿件同步进入 REVISE。

完成标准：
- 所有数字能反查到 case/run；
- claim-evidence matrix 中每条 claim 均有对应证据；
- 图表同时呈现效果与适用范围；
- G5=PASS，允许进入 P11 投稿审计。
```

## 16. P11：最终投稿就绪审计

```text
阶段：P11 final submission readiness audit

目标：依据实验、复现和 claim-evidence 合同决定 READY / CONDITIONAL / REVISE，并形成最终投稿版本。

输入：
- P00-P10 的全部 frozen manifests、machine tables、reports、figures 和 ledger；
- canonical release snapshot 与 clean output directory；
- 当前论文 claims/table inventory。

任务：
1. 逐项核验实验闭环方案第 13 节的完整投稿版本；external-ready 对应 cross-domain READY，其他版本单独评估 multi-sequence CONDITIONAL。
2. promoted profile 审计 HU/H1/H2/H3/H4a/H4b、H5 profiling status、G2A/G2B promotion、P-H、Q/G/QG、pooled calibration、M/official baseline、C-QG、normal no-harm、runtime 和 clean-room reproduction；legacy profile 审计 H1/H2/H3/H4a/H4b、H5 profiling status、P_legacy/D_legacy/C_legacy/M 与系统证据。
3. 从 canonical release snapshot 在干净输出目录重现至少一个代表性窗口，包括 export、3 次 backend replay、评测、汇总和图表数据行。
4. 检查 source/config/model/dataset/environment hash、数据许可、命令、随机 seed、失败 ledger 和负结果完整性。
5. 做 evidence coverage audit：数据选择、GT association、common support、H/P master-stream equality、maximum-cap/realized-dose fairness、calibration、frame-chain hash、conditional-arm applicability timing、replay reducer、统计单位、HU all-low 分母、H4a 完整 normal 分母、runtime wording、baseline naming 和 lineage positioning。
6. 生成 submission_readiness_audit.md，按 Critical/Major/Minor 列问题、证据和对应处理状态。
7. 给出决策：
   - READY：`method_profile=promoted`，G0-G6、HU/H1/H2/H3/H4a/H4b、H5 profiling 与 external-held-out 支撑主要 claim；
   - CONDITIONAL：`method_profile=promoted`，HU/H1/H3/H4a 成立，H2、H4b activity 或 external evidence 处于 INCONCLUSIVE；稿件聚焦 reliability-calibrated selective measurement system；
   - CONDITIONAL：`method_profile=legacy`，H1/H2/H3/H4a 成立、H5 profiling 完整，H4b 成立或按冻结 rule 为 `INCONCLUSIVE_ACTIVITY`；稿件聚焦 selective learned-seeded KLT system，QG/P-H/HU 只作 development；
   - REVISE：核心 evaluator、promoted HU、H1、H3、H4a 或复现合同待完善。H5 吞吐较低不单独触发 REVISE，但必须使用 selective/offline-capable 表述。
8. REVISE 状态对应新的 protocol version、补充数据或目标范围调整。

阶段转向条件：
- clean-room reproduction 待完成时保持 REVISE；
- 主表数字追溯待补齐时更新 analysis bundle；
- external identity 对应选择 cross-domain 或 multi-sequence 表述；
- claim-evidence 尚未对齐时更新稿件措辞；
- 主表保持完整 failure/window 分母。

完成标准：
- submission_readiness_audit.md、reproduction_report.md、final_claim_evidence_matrix.md 完成；
- G6 状态和 READY/CONDITIONAL/REVISE 决策明确；
- 所有 remaining items 在稿件中有对应适用范围；
- 核心实验清单与投稿版本一致。
```

## 17. 长任务监控续跑提示词

当 P07/P08 因会话中断但进程仍在运行时，使用以下提示词，按 frozen protocol 监控和续接。

```text
你正在续接 AQUA-FE 的长实验。先读取公共固定前缀、experiment_status.md、run_registry.csv、execution_ledger.jsonl、当前 run 的 command/log/pid 证据和 frozen hashes。

先判断：
1. 原进程是否仍存在且属于本实验；
2. 输出是否持续增长；
3. ROS master、rosbag、vins_node/sidecar 的关系是否正常；
4. run directory 和 registry 状态是否一致；
5. frozen method/input/evaluator hash 是否仍一致。

原进程健康时监控到自然结束并完成评测/登记。进程已结束或失败时保留原状态；基础设施故障创建新的 replacement run_id，并在 failures_and_replacements.md 与 ledger 中关联原 run、证据、原因和批准依据。

最终报告当前 run 状态、健康证据、产物路径、是否创建 replacement、队列中下一项，以及是否仍满足 frozen protocol。
```

## 18. 最短执行路线

若目标是尽快形成可投稿证据，按以下顺序执行：

1. P00-P01：先修 evaluator，决定旧方向是否还成立；
2. P02：完成 external metadata/reference 资格审计，并在 development 上冻结选窗规则；
3. P03：冻结 H/P 共用的 trigger、proposal、KLT probation、correctness gates、selector-independent master stream、active/total caps 和 classical proposer/calibration adapter；
4. P03A：用 3 天完成 6 窗 shadow、合成测试和 `PROMOTE/BASELINE_ROUTE/REVISE`；
5. `PROMOTE` 进入 P03B-P05，迁移 canonical P、冻结 pooled calibration、补 C-QG/M；`BASELINE_ROUTE` 跳过 P03B，以 P_legacy/C_legacy/M 继续；`REVISE` 保持在 P03A；
6. P06：完成 selected-profile proposed/drop/classical-control 与 M/B0 合同探针；method hash 完成后运行 external KLT-only screening，封存 manifest 与 conditional control slots；
7. P07：promoted profile 最多 8 arms/480 replays；legacy profile 最多 7 arms/420 replays；
8. P08-P11：selector/runtime、统计、Pareto 图表和投稿审计。

最快路线先完成 P01、P02、P03A；第 3 天依据 shadow 证据决定是否投入 P03B 的 canonical 实现。历史搜索窗口统一登记为 development，新 P 的投稿数字来自冻结后的 confirmatory matrix。
