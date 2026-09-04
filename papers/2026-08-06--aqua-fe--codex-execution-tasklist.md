---
type: execution-tasklist
date: 2026-08-06
project: AQUA-FE
executor: codex
target_venue: IEEE Sensors Journal
related:
  - papers/2026-08-03--aqua-fe--honest-incremental-experiment-plan.md
  - papers/frozen_frontend_eval_20260714/analysis-output/results_long.csv
---

# AQUA-FE codex 执行任务表

冻结方法 = `jul14frozen3way` 契约。权威 run 集:`papers/frozen_frontend_eval_20260714/positive_regression_hash_audit_20260717.csv`(33 bag SHA)+ `manifest.csv`(20 簇)。

## 任务表

| ID | 优先级 | 任务 |
|---|---|---|
| T1 | P0 | held-out 资源盘点 |
| T2 | P0 | E3 双指标 + sequence 聚合(现有数据) |
| T3 | P0 | E4 held-out 盲选 + 首跑 VINS |
| T4 | P0 | E1 modern baseline M(SP-LG/XFeat 同后端) |
| T5 | P1 | E5 多 replay 稳定性 |
| T6 | P1 | E2 classical control(C-QG)补齐 |
| T7 | P1 | E6 churn/持久性诊断(GT-free) |
| T8 | P2 | E8 normal no-harm 补强 |

## 执行检查点（2026-08-07T00:28:40+08:00）

| ID | 状态 | 证据 / 边界 |
|---|---|---|
| T1 | COMPLETE_NEGATIVE | `heldout_inventory.csv`:四个指定外部候选均不满足“本地独立 GT + 完整标定/同步 + 未跑 VINS”;当前 external-held-out=0。 |
| T2 | COMPLETE_DEVELOPMENT | 21 簇/63 arm 已用 G0 common-support 零 replay 复算；20 fresh 与 21 all 双口径见 `e3_dualmetric_summary.csv`、`e3_sequence_aggregate.md`。该矩阵是历史 development evidence。 |
| T3 | IN_PROGRESS | P06 选择/方法/队列已冻结；split audit 纠正为 exact-history-excluded,非 external-held-out。P07 frontend 队列按 append-only/no-clobber 协议执行中，trajectory outcome 仍封存。 |
| T4 | IN_PROGRESS | P05 XFeat same-backend integration/fairness PASS；P07 M 全 20 窗 trajectory comparison 未完成，实时状态见 `modern_baseline_M_results.csv`。 |
| T5 | PARTIAL_DEVELOPMENT | 14 个现有三 replay window-arm 组已汇总；P07 全矩阵 `3 replay/arm` 尚未开始。 |
| T6 | COMPLETE_DEVELOPMENT_ATTRIBUTION | `cqg_classical_control.csv` 保留 learned-positive A06/NTNU、classical-positive A03、A08 invalid-support、Cave proxy 与 NTNU online zero-supply。不得声称 learned/source-universal。 |
| T7 | COMPLETE | AQUALOC/NTNU/CIRS ID-lineage 重算与 PDF/600 dpi 图已生成；KLT 中位均为 1 帧，anchor 寿命跨域异质。 |
| T8 | PARTIAL_DEVELOPMENT | 9 个历史 zero-action exact fallback、H07 known-normal exact fallback、1 个 active-normal development case 已汇总；P06 十个 normal confirmatory trajectory 尚未读取。 |

投稿判定与实时 registry 计数由 `scripts/build_claim_evidence_audit.py` 生成到 `claim_evidence_audit.md`。在 60 个 frontend、20 个 D 和 `240+3k` backend replay 全部终态前，判定保持 `REVISE_EXPERIMENTS_INCOMPLETE`。

---

## T1 [P0] held-out 资源盘点
- **目标**:找"有独立 GT + 开发期未跑过 VINS"的窗,区分 sequence-held-out 与 external-held-out。
- **输入**:FLSea-VI `datasets/flsea_vi/`;UVVID `/mnt/data/AQUA-FE_WS/datasets/full_downloads/uvvid/files/visual-inertial/Orientkaj/`;UMA-VI `/mnt/data/AQUA-FE_WS/datasets/full_downloads/uma_vi/`;CIRS caves `/mnt/data/AQUA-FE_WS/datasets/full_downloads/cirs_caves/`。
- **步骤**:每候选域核 (a) 独立 GT/reference,(b) camera+IMU 标定,(c) 时间同步,(d) 该窗是否已在 `logs/*/` 出现过。
- **产物**:`papers/heldout_inventory.csv`:`domain,sequence,has_gt,calib_ok,sync_ok,ever_run_vins,heldout_class,notes`。每域可切 ≥3 个 45–60s 窗。

## T2 [P0] E3 双指标 + sequence 聚合(现有数据,零重跑)
- **目标**:用 G0 评测器对已有轨迹算 APE+RPE 双指标 + sequence 聚合。
- **输入**:`papers/frozen_frontend_eval_20260714/analysis-output/results_long.csv` + 已有 NTNU/CIRS `vio.csv` + GT。
- **步骤**:
  1. 每 `窗×arm` 用 `scripts/evaluate_vins_common_support.py` 算 APE+RPE+`ape_valid/rpe_valid`。
  2. 失败编码:APE>3m 或 RPE>1m=发散;双臂发散=平局排除;单臂发散=胜负。
  3. sequence 级配对聚合:win-rate + 改善中位 + 固定 seed 10000× bootstrap 95% CI + exact sign test。
- **产物**:`papers/e3_dualmetric_summary.csv` + `papers/e3_sequence_aggregate.md`(预选 20 簇主表 + 全体窗附录表双口径)。
- **锚点**:官方 20 簇 = 0 伤害、7 改善、10 no-harm、1 轻微差、发散救回 1/3(A09_6000: 4.70→0.11m)。

## T3 [P0] E4 held-out 盲选 + 首跑 VINS
- **依赖**:T1。
- **步骤**:
  1. 冻结方法/阈值并 hash;冻结窗选择规则(KLT grid coverage/dropout/flat-region/degradation,45–60s 窗)。
  2. held-out 域跑冻结 KLT-only frontend,只输出 KLT/image-quality 指标 → 按规则盲选 low-texture + normal 窗(不看 learned/VINS 结果)。
  3. 冻结方法首次 proposed 运行(full/drop/klt)+ VINS(`run_*_vins_eval.sh`)。
  4. G0 双指标评测。
- **产物**:`papers/heldout_selection_protocol.md`(规则+hash)、`papers/heldout_results.csv`。每域 ≥3 序列。

## T4 [P0] E1 modern baseline M(同后端)
- **输入**:`uw_frontend/matchers/lightglue_adapter.py`(SP-LG,available)或 XFeat direct;SuperVINS 作 reference(适用子集)。
- **步骤**:M 在全部 confirmatory 窗跑,匹配图像尺度/feature budget/VINS config/常数 backend q/IMU-GT/G0 评测/硬件。本地实现命名 `SP-LG same-backend reproduction`。报告运行时/资源。
- **产物**:`papers/modern_baseline_M_results.csv`。

## T5 [P1] E5 多 replay 稳定性
- **步骤**:每 `窗×arm` 冻结 feature bag 串行 replay VINS 3 次,取中位;报告 replay 方差 + solver-risk 率。frontend 确定则 export 一次 hash。
- **产物**:`papers/replay_stability.csv`。

## T6 [P1] E2 classical control(C-QG)补齐
- **输入**:`uw_frontend/matchers/classical_gftt.py`(drop-in BaseMatcher)。已完成 A06/Cave/A03。
- **步骤**:classical GFTT 种子过同一 pipeline(同 trigger/LK/gate/admission/budget/export,仅 candidate pool 换经典)+ VINS,≥3 窗。用 `export_vins_features.py` 全 pipeline(非简化 sidecar runner)。NTNU 用 retrospective same-ID/slot/dose 替换(`scripts/build_gftt_matched_lineage_control.py`)。
- **产物**:`papers/cqg_classical_control.csv`(并入 `build_learned_specificity_analysis.py`)。

## T7 [P1] E6 churn/持久性诊断(GT-free)
- **步骤**:跨 AQUALOC/NTNU/CIRS 报告 KLT track-age/churn 分布 vs 锚点寿命(KLT 中位 1-2 帧 vs 锚点 30-97 帧)。
- **产物**:`papers/persistence_churn_diagnostic.csv` + 图。

## T8 [P2] E8 normal no-harm 补强
- **步骤**:多个正常纹理长窗 + 零动作 byte-identical fallback + active-normal 案例。
- **产物**:`papers/normal_noharm.csv`。

---

## 执行顺序

```
T1 ──> T3(依赖 T1)
T2(并行) ──┐
T4 ────────┼──> T5 + T6 + T7 ──> claim_evidence_audit
           └──> 投稿判定
T8 并行
```

## 交付物

```
papers/heldout_inventory.csv
papers/heldout_selection_protocol.md
papers/heldout_results.csv
papers/e3_dualmetric_summary.csv
papers/e3_sequence_aggregate.md
papers/modern_baseline_M_results.csv
papers/replay_stability.csv
papers/cqg_classical_control.csv
papers/persistence_churn_diagnostic.csv
papers/normal_noharm.csv
papers/claim_evidence_audit.md
```
