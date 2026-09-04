#!/usr/bin/env python3
"""Render the long-window same-backend supplemental report."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import median

import report_frontend_same_backend_comparison_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison_supplemental_v1"
WINDOWS = [
    "a03_5000_5900", "a01_16200_17100", "a07_900_1800", "a07_1800_2700",
    "h07_0_1000", "h01_0_900", "fjord5_s60_d30", "fjord6_s45_d45",
]
ARMS = ["klt", "splg", "xfeat_seed"]
DISPLAY = {"klt": "KLT", "splg": "SP+LG", "xfeat_seed": "XFeat-seed"}


def rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, data: list[dict[str, object]]) -> None:
    if not data:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def pairwise_attribution_analysis(
    accuracy: list[dict[str, str]],
    effective: list[dict[str, str]],
    budget: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Compute contrasts only for distinct inputs that honor the hard budget."""

    metric_lookup = {(row["window"], row["arm"]): row for row in accuracy}
    audit_lookup = {row["window"]: row for row in effective}
    budget_lookup = {(row["window"], row["arm"]): row for row in budget}
    decisions: list[dict[str, object]] = []
    effects: list[dict[str, object]] = []
    for comparator in ("klt", "splg"):
        contrast = f"XFeat-seed − {DISPLAY[comparator]}"
        eligible: list[dict[str, object]] = []
        for window in WINDOWS:
            audit = audit_lookup[window]
            common = (window, "xfeat_seed") in metric_lookup and (window, comparator) in metric_lookup
            flag = audit[f"xfeat_vs_{comparator}_attributable"] == "1"
            budget_ok = all(
                budget_lookup[(window, arm)]["budget_contract_status"] == "PASS"
                for arm in ("xfeat_seed", comparator)
            )
            if not common:
                reason = "COMMON_SUPPORT_GATE"
            elif not flag:
                reason = "IDENTICAL_FEATURE_TOPIC_INPUT"
            elif not budget_ok:
                reason = "FEATURE_BUDGET_CONTRACT_FAIL"
            else:
                reason = "NONE"
            decision: dict[str, object] = {
                "window": window,
                "contrast": contrast,
                "common_support": int(common),
                "pairwise_backend_input_distinct": int(flag),
                "pairwise_budget_contract_pass": int(budget_ok),
                "included_for_attribution": int(common and flag and budget_ok),
                "exclusion_reason": reason,
                "equality_relation": audit["equality_relation"],
                "xfeat_points_max": budget_lookup[(window, "xfeat_seed")]["points_max"],
                "comparator_points_max": budget_lookup[(window, comparator)]["points_max"],
            }
            if common:
                x = metric_lookup[(window, "xfeat_seed")]
                b = metric_lookup[(window, comparator)]
                for label, field in (("ape", "ape_rmse_median_m"), ("rpe", "rpe_rmse_median_m")):
                    xv, bv = float(x[field]), float(b[field])
                    decision[f"xfeat_{label}_m"] = xv
                    decision[f"comparator_{label}_m"] = bv
                    decision[f"delta_{label}_m"] = xv - bv
                    decision[f"delta_{label}_pct"] = 100.0 * (xv - bv) / bv if bv else math.nan
            decisions.append(decision)
            if common and flag and budget_ok:
                eligible.append(decision)
        for label in ("ape", "rpe"):
            delta = [float(row[f"delta_{label}_m"]) for row in eligible]
            percent = [float(row[f"delta_{label}_pct"]) for row in eligible]
            effects.append({
                "contrast": contrast,
                "metric": label.upper(),
                "n_windows": len(eligible),
                "windows": ";".join(str(row["window"]) for row in eligible),
                "median_delta_m": median(delta),
                "range_delta_m": f"{min(delta):.6f}–{max(delta):.6f}",
                "median_delta_pct": median(percent),
                "xfeat_wins": sum(value < 0 for value in delta),
                "ties": sum(value == 0 for value in delta),
                "comparator_wins": sum(value > 0 for value in delta),
            })
    write_csv(OUT / "pairwise_attribution_windows.csv", decisions)
    write_csv(OUT / "pairwise_attributable_effects.csv", effects)
    return decisions, effects


def activation_table(data: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in data}
    body = []
    for window in WINDOWS:
        sp = lookup[(window, "splg")]
        xf = lookup[(window, "xfeat_seed")]
        body.append([
            window,
            sp["exported_learned_features_total"],
            sp["frames_with_exported_learned_features"],
            xf["exported_learned_features_total"],
            xf["frames_with_exported_learned_features"],
        ])
    return base.table(
        ["窗口", "SP+LG learned obs", "SP active frames", "XFeat learned obs", "XFeat active frames"],
        body,
    )


def effective_input_table(data: list[dict[str, str]]) -> str:
    body = []
    for row in data:
        short = lambda value: value[:10] if value else "missing"
        body.append([
            row["window"],
            short(row["klt_feature_topic_sha256"]),
            short(row["splg_feature_topic_sha256"]),
            short(row["xfeat_seed_feature_topic_sha256"]),
            row["equality_relation"],
            row["attribution_status"],
            "PASS" if row["imu_semantic_equal_all_arms"] == "1" else "FAIL",
        ])
    return base.table(
        ["窗口", "KLT feature topic", "SP+LG feature topic", "XFeat feature topic", "语义关系", "归因状态", "IMU 等同"],
        body,
    )


def budget_table(data: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in data}
    body = []
    for window in WINDOWS:
        values = []
        for arm in ARMS:
            row = lookup[(window, arm)]
            values.append(
                f"{row['budget_contract_status']}; max {row['points_max']}; "
                f">350 {row['messages_over_budget']} frame(s)"
            )
        body.append([window, *values])
    return base.table(["窗口", "KLT", "SP+LG", "XFeat-seed"], body)


def main() -> int:
    base.OUT = OUT
    base.FIG = OUT / "analysis-output/figures"
    base.WINDOWS = WINDOWS

    run_data = rows(OUT / "runability.csv")
    accuracy = rows(OUT / "accuracy.csv")
    support = rows(OUT / "common_support_status.csv")
    effective = rows(OUT / "effective_frontend_input_audit.csv")
    activation = rows(OUT / "frontend_activation.csv")
    budget = rows(OUT / "backend_feature_budget_audit.csv")
    repeats = rows(OUT / "runability_repeats.csv")
    backend = rows(OUT / "backend_config_audit.csv")
    if not run_data:
        raise SystemExit("missing runability.csv")

    pairwise_decisions, effects = pairwise_attribution_analysis(accuracy, effective, budget)
    stat_notes = [
        "Pairwise effects are descriptive and use only common-support windows whose feature-topic semantic SHA-256 values differ and whose actual PointCloud counts never exceed 350.",
        "No p-value is used for the causal frontend claim; only two strict-contract attributable windows remain.",
    ]
    base.make_figures(run_data, accuracy)
    span_audit = base.write_trajectory_span_audit(accuracy)
    arm_passes = {
        arm: sum(row["status"] == "PASS" for row in run_data if row["arm"] == arm)
        for arm in ARMS
    }
    common = [row["window"] for row in support if row["status"] == "PASS"]
    init_count = sum(row.get("init") == "1" for row in repeats)
    repeat_passes = sum(row.get("status") == "PASS" for row in repeats)
    backend_pass = sum(row.get("window_same_backend_config") == "PASS" for row in backend)

    effect_table = base.table(
        ["Contrast", "Metric", "n", "median Δ (m)", "range Δ (m)", "median Δ (%)", "wins/ties/losses"],
        [[
            row["contrast"], row["metric"], row["n_windows"],
            base.number(row["median_delta_m"], 6), row["range_delta_m"],
            base.number(row["median_delta_pct"], 2),
            f"{row['xfeat_wins']}/{row['ties']}/{row['comparator_wins']}",
        ] for row in effects],
    ) if effects else "无通过 common-support 的配对窗口。"

    conclusions = []
    lookup = {(str(row["contrast"]), str(row["metric"])): row for row in effects}
    for comparator in ("KLT", "SP+LG"):
        ape = lookup.get((f"XFeat-seed − {comparator}", "APE"))
        rpe = lookup.get((f"XFeat-seed − {comparator}", "RPE"))
        if ape and rpe:
            conclusions.append(
                f"在 {ape['n_windows']} 个同时满足 common support、pairwise 输入不同与实际 350 上限的窗口上，XFeat-seed 相对 {comparator} "
                f"的窗口中位 APE/RPE 变化为 {ape['median_delta_pct']:+.2f}%/{rpe['median_delta_pct']:+.2f}%；"
                f"胜/平/负为 APE {ape['xfeat_wins']}/{ape['ties']}/{ape['comparator_wins']}、"
                f"RPE {rpe['xfeat_wins']}/{rpe['ties']}/{rpe['comparator_wins']}。"
            )
    if not conclusions:
        conclusions.append("没有窗口同时通过严格 common-support 门与 pairwise 输入差异审计，因此不做 APE/RPE 前端优劣声明。")

    report = f"""# 固定后端前端对比：长窗口 supplemental v1

## 定位与不可合并边界

本表仍是**固定 VINS-Fusion 后端的前端隔离对比**，对应 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 使用关键帧与局部 BA 后端，属于不同设计空间，仅可单列为 reference；这里不作整系统对 HFNet 的精度声明。

本批次在结果产生前预注册了 8 个新的 30–50 s 窗口，用来修正主批次短窗无法达到 30 common poses 的协议问题。三前端仍为 KLT、SP+LG、XFeat-seed；名义预算配置、采样相位、门控、质量映射、三重复和评估口径保持一致。事后实际 PointCloud 审计发现少数 learned 激活帧超过配置的 350 上限，相关窗口已从严格归因分母剔除，见下文。

主批次的 `libvins_lib.so` 哈希为 `373a598c...810f71e8`，但扩窗前该文件已被另一个本机构建替换，旧字节副本不可恢复。本批次因此冻结为独立 backend epoch `supplement_v1_libvins_82ec1fcd`（库哈希 `82ec1fcd...b049045e`）。本批次内部 {backend_pass}/{len(backend)} 份归一化后端配置通过一致性审计；前端归因还需同时通过有效输入与实际预算审计。不得把主批次与本批次伪装成同一 exact-build 精度分母。

## 执行与 runability

正式规模为 8 窗口 × 3 前端 × 3 replay = 72。初始化 {init_count}/72；重复级 runability PASS {repeat_passes}/72。窗口级通过数：KLT {arm_passes['klt']}/8，SP+LG {arm_passes['splg']}/8，XFeat-seed {arm_passes['xfeat_seed']}/8。

{base.runability_table(run_data)}

`PASS` 要求 3/3 次均初始化且每次覆盖率 ≥0.70。位姿与覆盖率为中位 [完整范围]，失败不从分母移除。

上表是执行层 runability；是否满足“实际后端输入每帧 ≤350”另由下方预算审计决定。预算 FAIL 的窗口不进入严格前端贡献分母。

## 有效前端输入审计

{effective_input_table(effective)}

feature-topic 消息流语义哈希相同的 pair 不用于前端贡献归因。下面的完整精度表保留所有 common-support 窗口以便审计；真正的前端贡献结论进一步按具体 contrast 排除相同输入。

冻结 seed-chain 是条件触发的；名义 learned method 可能产生候选但最终不向后端注入 learned observation。激活统计如下（同一 learned track 在多个帧出现会重复计 observation）：

{activation_table(activation)}

## 实际 feature budget 审计

配置虽为 `EXPORT_MAX_FEATURES=350`，但在线 seed 注入发生在一次 cap 之后；少数激活帧实际送入 VINS 的 PointCloud 超过 350。严格合同按后端实际收到的点数审计：

{budget_table(budget)}

因此 `a01_16200_17100`、`a07_900_1800`、`a07_1800_2700`、`fjord6_s45_d45` 至少一个 learned arm 违反实际 350 上限。其完整 runability/精度仍保留，但不用于严格前端贡献结论；尤其 `a07_900_1800` 上 XFeat 的明显稳定性优势目前只能算探索性现象，不能当作公平预算证据。

## Common-support 资格

{base.support_decision_table(support)}

共同门为 ≥30 poses、≥10 s、≥70% 覆盖和 ≥10 个严格 1 s RPE 对，且使用九条轨迹的同一交集。

评测审计中发现 NTNU 的 `start` 是相对 raw bag 首时刻，而初版分析误按 baseline 首时刻加 offset，导致共同网格错位。最终结果改用已冻结 `frontend_metrics.csv` 中实际选定图像的首末 timestamp；没有重跑前端/VINS，也没有改变任何门槛或轨迹。修正后 fjord5/fjord6 分别获得 289/439 个共同位姿。

## 精度

APE/RPE 为与 COLMAP 或数据集 baseline proxy 的一致程度，不是独立 GT 绝对误差。每条轨迹独立 fixed-scale proper SE(3) 对齐；禁止 Sim(3) 与尺度拟合。

{base.accuracy_table(accuracy)}

{base.trajectory_span_table(span_audit)}

## Pairwise 可归因结论

{' '.join(conclusions)}

窗口才是独立科学单位；重复仅刻画 replay 变化。`a03_5000_5900` 与 `h01_0_900` 三臂 feature-topic 输入相同，因此其数值差异只反映后端 replay 敏感性。最终每个 contrast 仅剩 2 个同时满足 common support、输入不同和实际 ≤350 的窗口，不作普遍胜出声明。

{effect_table}

## 产物

- [windows.csv](windows.csv)、[contract.json](contract.json)、[preregistration.md](preregistration.md)
- [runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv)
- [accuracy.csv](accuracy.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)
- [common_support_status.csv](common_support_status.csv)
- [backend_config_audit.csv](backend_config_audit.csv)、[effective_frontend_input_audit.csv](effective_frontend_input_audit.csv)、[frontend_activation.csv](frontend_activation.csv)
- [backend_feature_budget_audit.csv](backend_feature_budget_audit.csv)
- [pairwise_attribution_windows.csv](pairwise_attribution_windows.csv)、[pairwise_attributable_effects.csv](pairwise_attributable_effects.csv)
- [artifacts.sha256](artifacts.sha256)

运行目录通过工作区 `logs/.../external_*_fsbcs1_*` 路径访问，物理文件位于 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_supplemental_v1`。wall-clock 效率不进入本报告。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    analysis = f"""# Supplemental strict analysis

Independent unit: window. Registered population: 8 windows × 3 arms × 3 repeats. Strict common-support population: {len(common)} window(s): {', '.join(common) if common else 'none'}.

{effect_table}

Primary and supplemental backend epochs are not pooled as one exact-build population.
"""
    (OUT / "analysis-report.md").write_text(analysis, encoding="utf-8")
    (OUT / "stats-appendix.md").write_text(
        "# Statistical appendix\n\n" + "\n\n".join(stat_notes) + "\n\n" + effect_table + "\n",
        encoding="utf-8",
    )
    (OUT / "figure-catalog.md").write_text(
        "# Figure catalog\n\n"
        "| Figure | File | Denominator |\n| --- | --- | --- |\n"
        "| 1 | `analysis-output/figures/figure-01-runability.pdf` | all 24 window-arm cells |\n"
        "| 2 | `analysis-output/figures/figure-02-common-support-accuracy.pdf` | strict all-arm common-support windows |\n",
        encoding="utf-8",
    )
    print(OUT / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
