#!/usr/bin/env python3
"""Render the repaired no-harm same-backend comparison report."""

from __future__ import annotations

from pathlib import Path

import analyze_frontend_same_backend_noharm_v2 as analysis
import report_frontend_same_backend_comparison_v1 as common
import report_frontend_same_backend_supplement_v1 as supplement


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison_noharm_v2"
WINDOWS = [window.window_id for window in analysis.WINDOWS]
ARMS = ["klt", "splg", "xfeat_seed"]
DISPLAY = {"klt": "KLT", "splg": "SP+LG", "xfeat_seed": "XFeat-seed"}


def final_mirror_table(rows: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in rows}
    body = []
    for window in WINDOWS:
        values = []
        for arm in ARMS:
            row = lookup[(window, arm)]
            values.append(
                f"{row['zero_sidecar_rollback_status']}; "
                f"zero {row['zero_sidecar_restore_frames']}; "
                f"active {row['active_sidecar_frames']}; "
                f"mismatch {row['zero_sidecar_message_mismatches']}"
            )
        body.append([window, *values])
    return common.table(["窗口", "KLT", "SP+LG", "XFeat-seed"], body)


def configure_helpers() -> None:
    common.OUT = OUT
    common.FIG = OUT / "analysis-output/figures"
    common.WINDOWS = WINDOWS
    supplement.OUT = OUT
    supplement.WINDOWS = WINDOWS


def main() -> int:
    configure_helpers()
    runability = supplement.rows(OUT / "runability.csv")
    repeats = supplement.rows(OUT / "runability_repeats.csv")
    accuracy = supplement.rows(OUT / "accuracy.csv")
    support = supplement.rows(OUT / "common_support_status.csv")
    effective = supplement.rows(OUT / "effective_frontend_input_audit.csv")
    activation = supplement.rows(OUT / "frontend_activation.csv")
    budget = supplement.rows(OUT / "backend_feature_budget_audit.csv")
    backend = supplement.rows(OUT / "backend_config_audit.csv")
    noharm = supplement.rows(OUT / "final_mirror_noharm_audit.csv")
    if not runability or not noharm:
        raise SystemExit("missing analyzed noharm-v2 CSV artifacts")

    decisions, effects = supplement.pairwise_attribution_analysis(accuracy, effective, budget)
    common.make_figures(runability, accuracy)
    span = common.write_trajectory_span_audit(accuracy)

    arm_passes = {
        arm: sum(row["status"] == "PASS" for row in runability if row["arm"] == arm)
        for arm in ARMS
    }
    repeat_passes = sum(row["status"] == "PASS" for row in repeats)
    common_windows = [row["window"] for row in support if row["status"] == "PASS"]
    backend_windows_ok = sum(
        all(
            row["window_same_backend_config"] == "PASS"
            for row in backend if row["window"] == window
        )
        for window in WINDOWS
    )
    budget_cells_ok = sum(row["budget_contract_status"] == "PASS" for row in budget)
    rollback_mismatches = sum(int(row["zero_sidecar_message_mismatches"]) for row in noharm)
    rollback_frames = sum(int(row["zero_sidecar_restore_frames"]) for row in noharm)

    effect_table = common.table(
        ["Contrast", "Metric", "n", "windows", "median Δ (m)", "range Δ (m)", "median Δ (%)", "wins/ties/losses"],
        [[
            row["contrast"], row["metric"], row["n_windows"], row["windows"],
            common.number(row["median_delta_m"], 6), row["range_delta_m"],
            common.number(row["median_delta_pct"], 2),
            f"{row['xfeat_wins']}/{row['ties']}/{row['comparator_wins']}",
        ] for row in effects],
    ) if effects else "没有满足严格归因门的窗口。"

    conclusions = []
    for comparator in ("KLT", "SP+LG"):
        ape = next((row for row in effects if row["contrast"] == f"XFeat-seed − {comparator}" and row["metric"] == "APE"), None)
        rpe = next((row for row in effects if row["contrast"] == f"XFeat-seed − {comparator}" and row["metric"] == "RPE"), None)
        if ape and rpe and int(ape["n_windows"]) > 0:
            conclusions.append(
                f"在 {ape['n_windows']} 个严格可归因窗口上，XFeat-seed 相对 {comparator} 的窗口中位 "
                f"APE/RPE 变化为 {float(ape['median_delta_pct']):+.2f}%/"
                f"{float(rpe['median_delta_pct']):+.2f}%；胜负为 "
                f"{ape['xfeat_wins']}/{ape['ties']}/{ape['comparator_wins']}（APE）和 "
                f"{rpe['xfeat_wins']}/{rpe['ties']}/{rpe['comparator_wins']}（RPE）。"
            )
    if not conclusions:
        conclusions.append("严格可归因的 common-support 分母为空，因此不作 XFeat 相对 KLT 或 SP+LG 的精度声明。")

    report = f"""# 修复 no-harm 后的固定 VINS-Fusion 后端前端隔离对比

## 定位与结论边界

本表是**前端隔离对比**：KLT、SP+LG 与当前 XFeat seed-chain 使用同一冻结 `VINS-Fusion-origin` 后端，只改变 `method/frontend source config`，对应 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 使用关键帧与局部 BA 后端，属于不同设计空间，仅作为 reference；本表不作整系统对 HFNet 的精度声明。

这是 exporter SHA-256 `fdb624f2...0c04` 的新前端 epoch，后端 `libvins_lib.so` SHA-256 为 `373a598c...810f71e8`。旧实验不被重命名或并入本结果。

## 主要结果

正式规模为 8 窗 × 3 前端 × 3 次 replay = 72。重复级 runability PASS {repeat_passes}/72；窗口级通过数为 KLT {arm_passes['klt']}/8、SP+LG {arm_passes['splg']}/8、XFeat-seed {arm_passes['xfeat_seed']}/8。{len(common_windows)}/8 个窗口通过 all-arm common-support 门。

实际 backend feature budget 审计通过 {budget_cells_ok}/24 个窗口-前端单元；归一化 VINS 配置在 {backend_windows_ok}/8 个窗口内保持九条轨迹一致。最终回滚审计覆盖 {rollback_frames} 个 zero-sidecar 帧，发现 {rollback_mismatches} 个与独立 KLT 消息不一致。

{' '.join(conclusions)} 窗口是独立科学单位，三个 replay 只用于报告中位与完整范围。

## Runability

{common.runability_table(runability)}

`PASS` 要求 3/3 次均初始化且每次覆盖率 ≥0.70。失败继续保留在 runability 分母；配置/基础设施、冷启动、激励不足和覆盖失败分开标注。

## 最终 no-harm 与 350 点合同

{final_mirror_table(noharm)}

`zero` 是最终没有 sidecar 后恢复 KLT mirror 的帧数；`active` 是实际保留 learned sidecar 的帧数。零-sidecar 比较针对后端实际收到的完整 feature 消息，而非名义 method。sidecar 激活时不预设轨迹无害，只检查等量替换、唯一 ID 和硬预算，轨迹影响由下方 APE/RPE 决定。

{supplement.budget_table(budget)}

## 有效前端输入与激活

{supplement.effective_input_table(effective)}

名义 learned 方法在某些窗口可能被完整门控为 KLT；feature-topic 语义相同的 pair 不用于前端贡献归因。

{supplement.activation_table(activation)}

## Common-support 资格

{common.support_decision_table(support)}

精度只在所有九条轨迹都通过 runability 后计算，并使用同一共同位姿交集和同一严格 1 s RPE 网格。门为 ≥30 poses、≥10 s、≥70% 共同覆盖、≥10 个 RPE 对。

## 精度：fixed-scale proper SE(3)

数值为 APE RMSE / 1 s 平移 RPE RMSE，单位 m，报告三次中位 [完整范围]。每条轨迹独立做 proper SE(3) 对齐；禁止 Sim(3) 和尺度拟合。参考为 COLMAP 或数据集 baseline proxy，所以这里只表示**与 proxy 的一致程度**，不是独立 GT 绝对误差。

{common.accuracy_table(accuracy)}

{common.trajectory_span_table(span)}

## 严格可归因的配对效应

只有同时满足 common support、pairwise feature-topic 输入不同、两臂实际每帧 ≤350 的窗口才进入对应 contrast。

{effect_table}

不以三个 replay 作为独立统计样本；若严格窗口数不足 5，仅给描述性结果，不报告显著性结论。

## 冻结合同与产物

- 预注册：[preregistration.md](preregistration.md)、[contract.json](contract.json)、[windows.csv](windows.csv)、[arms.csv](arms.csv)
- Runability：[runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv)
- 精度：[accuracy.csv](accuracy.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)、[common_support_status.csv](common_support_status.csv)
- 公平性：[backend_config_audit.csv](backend_config_audit.csv)、[effective_frontend_input_audit.csv](effective_frontend_input_audit.csv)、[backend_feature_budget_audit.csv](backend_feature_budget_audit.csv)
- no-harm：[final_mirror_noharm_audit.csv](final_mirror_noharm_audit.csv)、[frontend_activation.csv](frontend_activation.csv)
- 配对归因：[pairwise_attribution_windows.csv](pairwise_attribution_windows.csv)、[pairwise_attributable_effects.csv](pairwise_attributable_effects.csv)
- 完整绝对路径与 SHA-256：[artifacts.sha256](artifacts.sha256)

运行目录通过工作区 `logs/.../external_*_fsbcnh2_*` 访问，物理文件位于 `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_noharm_v2`。wall-clock 效率不进入本报告。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    (OUT / "analysis-report.md").write_text(
        "# noharm-v2 strict analysis\n\n"
        f"Independent unit: window. Registered population: 8 windows × 3 arms × 3 repeats. "
        f"Strict common-support population: {len(common_windows)} window(s): "
        f"{', '.join(common_windows) if common_windows else 'none'}.\n\n{effect_table}\n",
        encoding="utf-8",
    )
    (OUT / "stats-appendix.md").write_text(
        "# Statistical appendix\n\nWindows are the scientific units; replay repeats are not independent samples. "
        "No inferential claim is made with fewer than five attributable windows.\n\n" + effect_table + "\n",
        encoding="utf-8",
    )
    (OUT / "figure-catalog.md").write_text(
        "# Figure catalog\n\n| Figure | File | Denominator |\n| --- | --- | --- |\n"
        "| 1 | `analysis-output/figures/figure-01-runability.pdf` | all 24 window-arm cells |\n"
        "| 2 | `analysis-output/figures/figure-02-common-support-accuracy.pdf` | all-arm common-support windows |\n",
        encoding="utf-8",
    )
    analysis.configure()
    analysis.artifact_manifest()
    print(OUT / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
