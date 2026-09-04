# Selective improvement case studies

> 状态：2026-08-08 只读证据整理；未运行新前端、VINS 或 ORB-SLAM3 实验。

## 使用边界

本页只回答一个有限问题：历史开发实验中，是否存在 learned sidecar / lineage 机制在某些特定水下窗口改善轨迹的实例。答案是“存在”，但这些实例全部属于 `DEVELOPMENT_ONLY`，并在 confirmatory 窗口冻结前因既往搜索、参数使用或轨迹观察而被 history-excluded。它们只能作为 **case studies / existence proofs**，不能进入 P07 confirmatory 分母，也不能支持盲选成功率或总体效应估计。

允许的表述：

- “在若干开发期识别的退化窗口中，受门控的 learned 支持曾产生选择性救回；CIRS `s575,d30` 是具有有效 G0 APE/RPE 的 VINS 案例。”
- “A09 `6000-6200` 展示了显著但支持不足的探索性救回信号；A02 `2800-3200` 展示了另一个 ORB-v23 后端中的确定性、窗口特定正例。”

不允许的表述：

- 不 claim final P profile 能盲选这些窗口，或能复现这些历史 profile 的改善。
- 不 claim learned 必需、普遍优于 KLT、source-agnostic，或“低纹理普遍改善”。
- 不把 A02 的 ORB-v23 结果写成 VINS-Fusion 结果；不把技术重复当作独立样本。

history-exclusion 的机器可读依据是 `papers/ieee_sensors_journal_experiments/history_exclusion_manifest.csv`：A02 `2800-3200`、A09 `6000-6200`、CIRS `575-605 s` 分别记录为 `DEVELOPMENT_ONLY`，且 `prior_learned_seen=true`、`prior_vins_seen=true`、`prior_parameter_use=true`。因此下面没有任何 confirmatory/held-out 或 deployment-rate 含义。

## 已核实结果概览

| 案例 | 后端与开发 profile | 基线 APE/RPE RMSE (m) | 方法 APE/RPE RMSE (m) | 支持与有效性 | 本页定位 |
| --- | --- | ---: | ---: | --- | --- |
| CIRS `s575,d30` | VINS-Fusion；XFeat `mirror_densecap` | KLT `2.224181 / 0.304697` | full `1.091415 / 0.270008` | G0 `ape_valid=true`, `rpe_valid=true`; 252/310 common grid, 25.10 s, 242 RPE pairs | **强 VINS existence proof**；但有 solver-risk 日志 |
| A09 `6000-6200` | VINS-Fusion；XFeat `oldcontract_microburst` | KLT `4.702022 / 3.393186` | full `0.111514 / 0.078392` | 旧 `dt<=0.6 s` 评估有效；后续 G0 仅 8/10 common grid、7.0 s，`ape_valid=false`, `rpe_valid=false` | 探索性 headline case；不可作为有效 G0 endpoint |
| A02 `2800-3200` | ORB-SLAM3 lineage bridge；final-online v23 + enforced pre-KF purge | native online `0.066472 / 0.032750` | full online `0.022080 / 0.018213` | 20/21 GT poses；5-arm x 4-repeat；`4/4_vs_all`，重复为确定性复现 | ORB 后端特定 existence proof；不是 VINS 结果 |

### 1. CIRS `s575,d30`：当前最干净的 VINS 双指标案例

这是本页最适合作为论文 selective-improvement case study 的 VINS 证据，因为统一 G0 common-support 审计同时通过 APE 和 RPE 有效性门限。

- 数据与窗口：CIRS Cala Viuda，`575-605 s`。
- 冻结 profile：计划与实际选择均为 `mirror_densecap`；5 个 learned track IDs，whole-lineage drop 删除 27 条观测。
- G0 KLT：APE `2.2241813517 m`，RPE `0.3046973832 m`。
- G0 full：APE `1.0914152006 m`，RPE `0.2700076310 m`。
- 相对 KLT：APE 降低约 `50.93%`，RPE 降低约 `11.39%`；drop 为 `2.2044315836 / 0.3019872554 m`。
- 公共支持：310 个 10 Hz grid 点中 252 个三臂共同有效，coverage `0.812903`，common span `25.10 s`，RPE pairs `242`，单一连续 segment；`ape_valid=true`、`rpe_valid=true`。
- 限制：fresh regression 中 full/drop/KLT 分别记录 `7/5/10` 个 solver-failure mentions，三臂均 `init_success=1`、无 hard failure。它证明该窗口上的精度救回，不证明 learned 提高数值稳定性。

运行目录：

- full：`logs/cirs_caves_vins/external_hybrid_xfeat_every1_jul14frozen3way_cirs_s575_d30_full`
- whole-lineage drop：`logs/cirs_caves_vins/external_hybrid_xfeat_every1_jul14frozen3way_cirs_s575_d30_drop_lineage`
- KLT：`logs/cirs_caves_vins/external_klt_every1_jul14frozen3way_cirs_s575_d30_klt`
- frozen full feature profile：`logs/cirs_caves_vins/external_hybrid_xfeat_every1_jul14frozen3way_cirs_s575_d30_cirs_mirror_densecap`

已保存的 replay 入口为：

```bash
bash scripts/run_frozen_positive_replay_regression.sh cirs_s575_d30
```

runner 固定 `VINS_WS=/home/ma/SLAM/VINS-Fusion-origin`、`VINS_MULTIPLE_THREAD=0`、`PLAY_RATE=1.0`、`EVERY_N=1`，并对 frozen bag 做 SHA-256 校验。G0 的完整评估命令保存在 `papers/e3_g0_common_support/cirs_s575_d30/command.txt`。

关键证据：

- `papers/e3_g0_common_support/cirs_s575_d30/common_support_summary.json`
- `papers/e3_g0_common_support/cirs_s575_d30/common_support_metrics.csv`
- `papers/e3_g0_common_support/cirs_s575_d30/common_grid_audit.csv`
- `papers/e3_g0_common_support/cirs_s575_d30/command.log`（`ape_valid=1`, `rpe_valid=1`）
- `papers/e3_dualmetric_summary.csv`
- `papers/frozen_frontend_eval_20260714/analysis-output/case_summary.csv`
- `papers/frozen_frontend_eval_20260714/positive_regression_hash_audit_20260717.csv`（三臂 bag hash 均匹配）

### 2. A09 `6000-6200`：`4.70 -> 0.11 m` 的探索性救回

该窗口给出了最醒目的单窗结果，但必须连同后续 support 审计一起报告。

- 数据与窗口：AQUALOC archaeology A09，frames `6000-6200`。
- frozen profile：`oldcontract_microburst`；1 个 learned track ID，whole-lineage drop 删除 3 条观测。
- 2026-07-17 fresh replay（旧 `max-match-dt=0.6 s` 口径）：
  - KLT：APE `4.702022 m`，RPE `3.393186 m`；
  - full：APE `0.111514 m`，RPE `0.078392 m`；
  - drop：APE `44.695044 m`，RPE `18.655168 m`；
  - full 相对 KLT 的 APE 降低 `97.628%`；三臂均 88 poses、coverage `0.869980`、初始化成功、无 solver/failure mention。
- 保护性五次复跑的 full 中位数为 `0.572393 / 0.267525 m`，KLT/drop 为 `4.702022 / 3.393186 m`，说明“改善方向”并非只存在于一条 full 轨迹；证据在 `logs/jul21_final_online_master_status.csv`。
- 关键限制：后续统一 G0 common-support 重算只有 10 个 grid 点中的 8 个共同匹配、common span `7.0 s`、7 个 RPE pairs，明确给出 `ape_valid=false`、`rpe_valid=false`。G0 数值仍呈 full 优于 KLT，但不得把无效 endpoint 当作正式双指标结果。论文中若保留 `4.70 -> 0.11 m`，必须标注为 legacy-support exploratory case。

fresh replay 运行目录：

- full：`logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul17positive_replay_a09_6000_6200_full`
- whole-lineage drop：`logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul17positive_replay_a09_6000_6200_drop`
- KLT：`logs/aqualoc_archaeo_vins/external_klt_every2_jul17positive_replay_a09_6000_6200_klt`
- frozen full feature profile：`logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a09_6000_6200_oldcontract_microburst`

已保存的 replay 入口为：

```bash
bash scripts/run_frozen_positive_replay_regression.sh a09_6000_6200
```

每个 fresh run 的 `replay_manifest.txt` 绑定 raw bag、实际播放的 frozen feature bag 和输出轨迹；`vins_env_manifest.txt` 绑定 VINS-Fusion-origin binary。逐臂 `ape_strict_dt0p6.txt` 保存上述 APE/RPE、coverage 和 failure 计数。

关键证据：

- `papers/frozen_frontend_eval_20260714/positive_regression_results_20260717.csv`
- `papers/frozen_frontend_eval_20260714/positive_regression_summary_20260717.csv`
- `papers/frozen_frontend_eval_20260714/positive_regression_hash_audit_20260717.csv`
- `papers/frozen_frontend_eval_20260714/positive_regression_report_20260717.md`
- `papers/e3_g0_common_support/a09_6000_6200/common_support_summary.json`
- `papers/e3_g0_common_support/a09_6000_6200/common_support_metrics.csv`
- `papers/e3_g0_common_support/a09_6000_6200/command.txt`
- `papers/e3_g0_common_support/a09_6000_6200/command.log`（`ape_valid=0`, `rpe_valid=0`）

### 3. A02 `2800-3200`：ORB-v23 后端特定严格正例

A02 需要与 VINS 证据严格分开。旧 frozen VINS 三臂在该窗没有 learned lineage；G0 full/drop/KLT 均为 `35.556730 / 10.283631 m`，且 `ape_valid=false`、`rpe_valid=true`。因此 **A02 不是 VINS selective-rescue case**。

可核实的救回发生在另一个实验系统：ORB-SLAM3 external-lineage bridge 的 final-online v23。该 profile 固定 q `>=0.9`、projection error `<=4 px`、Hamming `<=100`，并在 full 臂强制 pre-KF assisted-outlier purge；CPU2、single CPU、双后台 barrier、deterministic gate、ASLR off。完整 5-arm x 4-repeat matrix 的结果为：

- reconstructed native/drop：APE `0.077687 m`，RPE `0.037684 m`；full：`0.023321 / 0.021781 m`，分别降低 `69.981% / 42.201%`。
- online native/drop：APE `0.066472 m`，RPE `0.032750 m`；full：`0.022080 / 0.018213 m`，分别降低 `66.783% / 44.388%`。
- 每个 full repeat 均接受 `106/106` observations，并稳定产生 7 assisted matches、3 assisted outliers、3/3 pre-KF purges；对 native、drop 和 unbounded 的方向检查为 `4/4_vs_all`。
- 支持：20/21 GT poses associated；四次结果用于确定性复现，不构成四个独立样本。窗口为 operational degraded/planar/low-grid，但 base KLT near-saturated，不能写成 sparse-KLT 普遍低纹理证据。

formal root：

`/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_action_search_20260731/a02_2800_3200/formal_finalonline_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

每个 role/repeat 目录内的 `run_manifest.txt` 是实际执行契约；例如 `full_r1/run_manifest.txt` 记录 binary/config/times/seed hash、阈值、调度和 enforcement 状态，`instrumentation/seed_summary.json` 记录 106/106 与 7/3/3 动作链，`ape_trans.txt`、`rpe_trans_1f.txt`、`online_ape_trans.txt`、`online_rpe_trans_1f.txt` 保存指标。没有找到独立保存的原始 shell `command.txt`，因此本页不反向拼接一个未经核实的命令。

关键证据：

- `papers/orb_v23_postinit_action_search_20260731/analysis-output/analysis-report.md`
- `papers/orb_v23_postinit_action_search_20260731/analysis-output/case_summary.csv`
- `papers/orb_v23_postinit_followup_20260802/analysis-output/formal_summary.csv`
- `papers/orb_v23_postinit_followup_20260802/analysis-output/window_roster.csv`
- `papers/orb_v23_postinit_followup_20260802/2026-08-02--orb-v23-postinit-followup--r02--transfer-summary.md`
- VINS 对照限制：`papers/e3_g0_common_support/a02_2800_3200/common_support_summary.json`

## 论文落点

主结果仍应是 P07 20/20 confirmatory 窗口的逐字节 no-harm。selective improvement 只放在单独的 case-study 小节：优先报告 G0-valid 的 CIRS `s575,d30`，将 A09 作为明确标注 legacy-support 的醒目探索性案例；若使用 A02，则放在“跨后端机制证据/补充材料”，不能与 VINS 主表合并。

最稳妥的一句话是：

> The confirmatory matrix establishes exact no-harm under zero action, while development-only, history-excluded case studies provide existence proofs of selective rescue; these cases do not estimate blind-selection success or population-level improvement.
