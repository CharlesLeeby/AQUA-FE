#!/usr/bin/env python3
"""Render the decision-oriented report and figures for the fixed-backend comparison."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison"
FIG = OUT / "analysis-output/figures"
WINDOWS = ["a02_4500_6300", "a09_4000_4400", "a09_6000_6800", "a10_2400_2800", "a10_4800_5200", "h07_1660_1720", "mclab1_s60_d15"]
ARMS = ["klt", "splg", "xfeat_seed"]
DISPLAY = {"klt": "KLT", "splg": "SP+LG", "xfeat_seed": "XFeat-seed"}
COLORS = {"klt": "#4C78A8", "splg": "#F58518", "xfeat_seed": "#54A24B"}


def rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: str | float, digits: int = 4) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "NA"
    return f"{x:.{digits}f}" if math.isfinite(x) else "NA"


def table(headers: list[str], body: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in body)
    return "\n".join(lines)


def runability_table(data: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in data}
    body = []
    for window in WINDOWS:
        line: list[object] = [window]
        for arm in ARMS:
            row = lookup[(window, arm)]
            line.append(f"{row['status']} {row['pass_repeats']}/3; poses {number(row['poses_median'], 0)} [{row['poses_range']}]; cov {number(row['coverage_median'], 3)} [{row['coverage_range']}]")
        body.append(line)
    return table(["Window", "KLT", "SP+LG", "XFeat-seed"], body)


def accuracy_table(data: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in data}
    common = [window for window in WINDOWS if all((window, arm) in lookup for arm in ARMS)]
    body = []
    for window in common:
        line: list[object] = [window]
        for arm in ARMS:
            row = lookup[(window, arm)]
            line.append(f"{number(row['ape_rmse_median_m'])} [{row['ape_rmse_range_m']}] / {number(row['rpe_rmse_median_m'])} [{row['rpe_rmse_range_m']}]")
        line.extend([lookup[(window, "klt")]["common_poses"], lookup[(window, "klt")]["rpe_pairs"]])
        body.append(line)
    if not body:
        return "No preregistered window passed the all-arm, all-repeat common-support gate; accuracy denominator is zero."
    return table(["Window", "KLT APE/RPE", "SP+LG APE/RPE", "XFeat APE/RPE", "Common poses", "1 s pairs"], body)


def support_decision_table(data: list[dict[str, str]]) -> str:
    body: list[list[object]] = []
    for row in data:
        window = row["window"]
        summary_path = OUT / "common_support" / window / "common_support_summary.json"
        if summary_path.is_file():
            import json

            support = json.loads(summary_path.read_text(encoding="utf-8"))["support"]
            support_text = (
                f"poses {support['matched_count']}/30; "
                f"coverage {support['common_coverage']:.3f}/0.700; "
                f"span {support['common_span_s']:.1f}/10.0 s; "
                f"RPE pairs {support['rpe_pairs']}/10"
            )
        else:
            support_text = "未评估（未通过 all-arm runability）"
        body.append([window, row["status"], row["reason"], support_text])
    return table(["窗口", "精度资格", "原因", "共同支撑 / 预注册门"], body)


def effective_input_table(data: list[dict[str, str]]) -> str:
    body = []
    for row in data:
        short = lambda value: value[:10] if value else "missing"
        body.append([
            row["window"],
            short(row["klt_feature_bag_sha256"]),
            short(row["splg_feature_bag_sha256"]),
            short(row["xfeat_seed_feature_bag_sha256"]),
            row["equality_relation"],
            row["attribution_status"],
        ])
    return table(["窗口", "KLT bag", "SP+LG bag", "XFeat bag", "字节关系", "归因状态"], body)


def budget_table(data: list[dict[str, str]]) -> str:
    lookup = {(row["window"], row["arm"]): row for row in data}
    body = []
    for window in WINDOWS:
        cells = []
        for arm in ARMS:
            row = lookup[(window, arm)]
            cells.append(
                f"{row['budget_contract_status']}; max {row['points_max']}; "
                f">350 {row['messages_over_budget']} frame(s)"
            )
        body.append([window, *cells])
    return table(["窗口", "KLT", "SP+LG", "XFeat-seed"], body)


def write_trajectory_span_audit(accuracy: list[dict[str, str]]) -> list[dict[str, object]]:
    """Expose the fixed-scale displacement mismatch behind extreme APE values."""

    common = sorted({row["window"] for row in accuracy})
    output: list[dict[str, object]] = []
    for window in common:
        evo_dir = OUT / "common_support" / window / "evo_crosscheck"
        reference_path = evo_dir / "reference_common.tum"
        if not reference_path.is_file():
            continue
        reference = np.loadtxt(reference_path, ndmin=2)[:, 1:4]
        reference_displacement = float(np.linalg.norm(reference[-1] - reference[0]))
        for arm in ARMS:
            for repeat in range(1, 4):
                path = evo_dir / f"{arm}_r{repeat}_common_aligned.tum"
                if not path.is_file():
                    continue
                estimate = np.loadtxt(path, ndmin=2)[:, 1:4]
                output.append({
                    "window": window,
                    "arm": arm,
                    "arm_display": DISPLAY[arm],
                    "repeat": repeat,
                    "proxy_end_to_end_displacement_m": reference_displacement,
                    "aligned_estimate_end_to_end_displacement_m": float(np.linalg.norm(estimate[-1] - estimate[0])),
                    "scale_fit_applied": 0,
                })
    if output:
        fields = list(output[0])
        with (OUT / "trajectory_scale_audit.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(output)
    return output


def trajectory_span_table(data: list[dict[str, object]]) -> str:
    body: list[list[object]] = []
    for window in sorted({str(row["window"]) for row in data}):
        proxy = float(next(row for row in data if row["window"] == window)["proxy_end_to_end_displacement_m"])
        for arm in ARMS:
            values = [float(row["aligned_estimate_end_to_end_displacement_m"]) for row in data if row["window"] == window and row["arm"] == arm]
            body.append([window, DISPLAY[arm], number(proxy, 3), f"{median(values):.3f} [{min(values):.3f}–{max(values):.3f}]"])
    return table(["窗口", "前端", "proxy 首末位移 (m)", "SE(3) 后估计首末位移：中位 [范围] (m)"], body) if body else "无可用尺度审计。"


def paired_effects(data: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[str]]:
    lookup = {(row["window"], row["arm"]): row for row in data}
    effects: list[dict[str, object]] = []
    notes: list[str] = []
    for comparator in ("klt", "splg"):
        for metric in ("ape_rmse_median_m", "rpe_rmse_median_m"):
            pairs = []
            for window in WINDOWS:
                if (window, "xfeat_seed") in lookup and (window, comparator) in lookup:
                    x = float(lookup[(window, "xfeat_seed")][metric])
                    b = float(lookup[(window, comparator)][metric])
                    pairs.append((window, x, b, x - b, 100.0 * (x - b) / b if b else math.nan))
            if not pairs:
                continue
            deltas = [item[3] for item in pairs]
            percents = [item[4] for item in pairs if math.isfinite(item[4])]
            effects.append({
                "contrast": f"XFeat-seed − {DISPLAY[comparator]}",
                "metric": "APE" if metric.startswith("ape") else "RPE",
                "n_windows": len(pairs),
                "median_delta_m": float(median(deltas)),
                "range_delta_m": f"{min(deltas):.6f}–{max(deltas):.6f}",
                "median_delta_pct": float(median(percents)) if percents else math.nan,
                "xfeat_wins": sum(item[3] < 0 for item in pairs),
                "ties": sum(item[3] == 0 for item in pairs),
                "comparator_wins": sum(item[3] > 0 for item in pairs),
            })
    if not effects:
        notes.append("No common-support windows were available; no paired effect was computed.")
    elif min(int(row["n_windows"]) for row in effects) < 5:
        notes.append("Fewer than five independent windows were available; inference is descriptive only and no p-value is reported.")
    else:
        try:
            from scipy.stats import wilcoxon

            raw_p = []
            for effect in effects:
                comparator = "klt" if effect["contrast"].endswith("KLT") else "splg"
                metric = "ape_rmse_median_m" if effect["metric"] == "APE" else "rpe_rmse_median_m"
                delta = [float(lookup[(w, "xfeat_seed")][metric]) - float(lookup[(w, comparator)][metric]) for w in WINDOWS if (w, "xfeat_seed") in lookup and (w, comparator) in lookup]
                p = float(wilcoxon(delta, zero_method="wilcox", alternative="two-sided", method="auto").pvalue)
                raw_p.append(p)
                effect["wilcoxon_p_raw"] = p
            order = np.argsort(raw_p)
            adjusted = [math.nan] * len(raw_p)
            running = 0.0
            m = len(raw_p)
            for rank, index in enumerate(order):
                running = max(running, (m - rank) * raw_p[index])
                adjusted[index] = min(1.0, running)
            for effect, p in zip(effects, adjusted):
                effect["holm_p"] = p
            notes.append("Two-sided paired Wilcoxon tests use windows as units; four planned tests are Holm-adjusted.")
        except Exception as exc:
            notes.append(f"Inferential test unavailable: {type(exc).__name__}; descriptive effects remain primary.")
    return effects, notes


def make_figures(run_data: list[dict[str, str]], accuracy: list[dict[str, str]]) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    lookup = {(row["window"], row["arm"]): row for row in run_data}
    matrix = np.array([[1 if lookup[(window, arm)]["status"] == "PASS" else 0 for arm in ARMS] for window in WINDOWS])
    fig, ax = plt.subplots(figsize=(6.8, 5.3))
    ax.imshow(matrix, cmap=matplotlib.colors.ListedColormap(["#D95F5F", "#59A14F"]), vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(3), [DISPLAY[arm] for arm in ARMS])
    ax.set_yticks(range(len(WINDOWS)), WINDOWS)
    for i, window in enumerate(WINDOWS):
        for j, arm in enumerate(ARMS):
            row = lookup[(window, arm)]
            ax.text(j, i, f"{row['status']}\n{row['pass_repeats']}/3", ha="center", va="center", color="white", fontsize=8, fontweight="bold")
    ax.set_title("Runability gate (3/3 repeats and coverage ≥ 0.70)")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"figure-01-runability.{ext}", dpi=220, bbox_inches="tight")
    plt.close(fig)

    lookup_a = {(row["window"], row["arm"]): row for row in accuracy}
    common = [window for window in WINDOWS if all((window, arm) in lookup_a for arm in ARMS)]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    if common:
        x = np.arange(len(common))
        for arm in ARMS:
            ape = [float(lookup_a[(window, arm)]["ape_rmse_median_m"]) for window in common]
            rpe = [float(lookup_a[(window, arm)]["rpe_rmse_median_m"]) for window in common]
            axes[0].plot(x, ape, marker="o", label=DISPLAY[arm], color=COLORS[arm])
            axes[1].plot(x, rpe, marker="o", label=DISPLAY[arm], color=COLORS[arm])
        for ax, title in zip(axes, ("APE RMSE", "1 s RPE RMSE")):
            ax.set_xticks(x, common, rotation=35, ha="right")
            ax.set_yscale("log")
            ax.set_ylabel("Agreement with proxy (m, log scale)")
            ax.set_title(title)
            ax.grid(alpha=0.25)
        axes[1].legend(frameon=False)
    else:
        for ax in axes:
            ax.axis("off")
        axes[0].text(0.5, 0.5, "No all-arm common-support window", ha="center", va="center", transform=axes[0].transAxes)
    fig.suptitle("Accuracy on preregistered common support (fixed-scale SE(3), no Sim(3))")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"figure-02-common-support-accuracy.{ext}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    run_data = rows(OUT / "runability.csv")
    accuracy = rows(OUT / "accuracy.csv")
    support = rows(OUT / "common_support_status.csv")
    effective_inputs = rows(OUT / "effective_frontend_input_audit.csv")
    budget = rows(OUT / "backend_feature_budget_audit.csv")
    if not run_data:
        raise SystemExit("missing runability.csv")
    effects, stat_notes = paired_effects(accuracy)
    make_figures(run_data, accuracy)
    span_audit = write_trajectory_span_audit(accuracy)

    arm_passes = {arm: sum(row["status"] == "PASS" for row in run_data if row["arm"] == arm) for arm in ARMS}
    common = [row["window"] for row in support if row["status"] == "PASS"]
    failed_reasons = sorted({reason for row in run_data for reason in row["failure_reasons"].split(";") if reason != "NONE"})

    effect_table = table(
        ["Contrast", "Metric", "n", "median Δ (m)", "range Δ (m)", "median Δ (%)", "wins/ties/losses"],
        [[row["contrast"], row["metric"], row["n_windows"], number(row["median_delta_m"], 6), row["range_delta_m"], number(row["median_delta_pct"], 2), f"{row['xfeat_wins']}/{row['ties']}/{row['comparator_wins']}"] for row in effects],
    ) if effects else "No paired effects available."

    conclusion = []
    by_key = {(str(row["contrast"]), str(row["metric"])): row for row in effects}
    for comparator in ("KLT", "SP+LG"):
        a = by_key.get((f"XFeat-seed − {comparator}", "APE"))
        r = by_key.get((f"XFeat-seed − {comparator}", "RPE"))
        if a and r:
            conclusion.append(f"Against {comparator} on {a['n_windows']} common-support windows, XFeat-seed changed median APE by {a['median_delta_pct']:+.2f}% and median 1 s RPE by {r['median_delta_pct']:+.2f}% (negative favors XFeat).")
    if not conclusion:
        conclusion.append("The all-arm common-support denominator is empty, so no APE/RPE superiority claim is made.")

    report = f"""# 固定 VINS-Fusion 后端的前端隔离对比

## 定位与结论边界

本表是**前端隔离对比**：KLT、SP+LG 与 XFeat-seed 均送入同一冻结的 `VINS-Fusion-origin` 后端，只改变前端 `method/config`，对标 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 采用关键帧与局部 BA 后端，属于不同设计空间，只能单列为 reference；本文不做整系统对 HFNet 的精度声明。

Runability 是第一指标。预注册 7 个窗口、3 个前端、每格 3 次 VINS replay，共 63 次；63/63 均完成初始化，但 18/63 因覆盖率低于 70% 判为失败。窗口级原始通过数为 KLT {arm_passes['klt']}/7、SP+LG {arm_passes['splg']}/7、XFeat-seed {arm_passes['xfeat_seed']}/7。原先观察到的 `a09_4000_4400` / `a10_2400_2800` 胜负涉及 learned 臂实际超过 350，不能作为严格公平 runability 归因；在输入确实不同且三臂均满足实际 350 的 `a09_6000_6800`、`a10_4800_5200` 上，三臂均通过，因此没有 runability 优越性结论。

只有 `a09_6000_6800` 通过 all-arm、all-repeat 共同支撑门。该单一窗口上，XFeat-seed 相对 KLT 的 APE/RPE 中位变化为 -99.94%/-99.95%，相对 SP+LG 为 -99.97%/-99.97%。这只是 (n=1) 窗口的描述性结果；不能据此宣称跨窗口普遍胜出，也不报告显著性检验。

## 扩窗补充批次

另预注册并完成了 8 个 30–50 s 新窗口 × 3 前端 × 3 重复。由于运行前本机 `libvins_lib.so` 已被其他构建替换，扩窗批次属于独立 backend epoch，不能与本表的 exact-build 精度分母合并。扩窗原始 runability 为三臂均 8/8，8/8 窗通过 common-support；但实际预算审计发现 4 窗至少一个 learned 臂有 1–2 帧超过 350，最终每个 XFeat contrast 仅剩 2 个严格可归因窗口，XFeat 在两窗均未胜出。详见[扩窗补充报告](../frontend_same_backend_comparison_supplemental_v1/report.md)。

## Runability 表

{runability_table(run_data)}

`PASS` 要求 3/3 次均初始化且每次覆盖率 ≥ 0.70。表中位姿数与覆盖率为 3 次的中位 [完整范围]。所有失败保留在分母中，未补跑后挑窗；本轮失败类别只有 `COVERAGE_FAIL`，没有配置错误、激励不足或冷启动未初始化。

## 有效前端输入审计

名义 method 不等于后端实际收到的输入；只有 feature bag 不同，才可把后端差异归因于前端。SHA-256 审计如下：

{effective_input_table(effective_inputs)}

`a02_4500_6300` 三臂 bag 字节完全相同，因此该窗 KLT FAIL、两学习臂 PASS 是同一后端输入下的初始化/求解路径随机性，**不能**作为前端贡献证据。`h07_1660_1720` 的 KLT 与 SP+LG bag 相同，二者也不可作前端归因。唯一进入精度表的 `a09_6000_6800` 三臂 bag 均不同。

## 实际 feature budget 审计

配置为 `EXPORT_MAX_FEATURES=350`，但在线 seed 注入在少数帧发生于 cap 之后。以下为 VINS 实际收到的 PointCloud 点数：

{budget_table(budget)}

唯一进入精度表的 `a09_6000_6800` 三臂均严格不超过 350，因此其 n=1 精度结果仍满足预算合同；预算 FAIL 窗口不用于严格 runability 归因。

## 精度资格与 common support

精度仅在所有 9 条轨迹均通过 runability 后评估，并取同一共同位姿交集与同一 1 s RPE 网格。额外预注册门为 ≥30 个共同位姿、共同跨度 ≥10 s、共同覆盖 ≥70%、≥10 个 RPE 对。

{support_decision_table(support)}

`a10_4800_5200` 虽三臂 runability 均通过，但只有 16 个共同位姿，低于 30；`mclab1_s60_d15` 的共同覆盖为 0.662 且跨度 9.9 s，均未达到门槛。两窗均不进入精度分母，未使用其事后可见的 APE/RPE。

## Common-support 精度

数值为 APE RMSE / 1 s 平移 RPE RMSE，单位 m，报告 3 次中位 [完整范围]。每条轨迹独立做 fixed-scale proper SE(3) 对齐；禁止 Sim(3) 和尺度拟合。这些数值表示**与 COLMAP/数据集 baseline proxy 的一致程度**，不是独立 GT 的绝对误差。

{accuracy_table(accuracy)}

内部实现与 evo 1.31.1 的最大绝对差分别小于 4.9e-7 m（APE）和 5.0e-7 m（RPE）。极大的 KLT/SP+LG 数值不是尺度拟合造成的：固定尺度对齐后，首末位移审计为：

{trajectory_span_table(span_audit)}

proxy 的首末位移约 7.16 m，而 KLT/SP+LG 仍为公里级，说明这一窗口发生尺度发散；XFeat-seed 约 9.45 m。因此本窗结果支持“XFeat-seed 与 proxy 更一致”，但证据分母仍只有一个窗口。

## 配对效应（描述性）

符号为 XFeat-seed 减去对照，负值有利于 XFeat-seed。重复只刻画 replay 变化，不作为独立样本。

{effect_table}

## 冻结合同与来源谱系

所有臂共用 exporter SHA-256 `68453b035037d04087dbad3e512c602b4ef6967b2a8cf6d14e34a14750f2312d`、feature budget 350、`every_n=2`、`frame_offset=1`、`MEASUREMENT_SELECTION=0`、`VINS_SAFE_SOURCE_SELECTION=0`、相同质量映射、VINS 参数与后端二进制。[backend_config_audit.csv](backend_config_audit.csv) 显示每个窗口 9 份归一化 VINS YAML 均为同一哈希，7/7 窗口通过后端一致性审计。

XFeat 配置哈希 `6f89d861...00bf3` 与 `P_legacy_nativeq_xfeat_seedchain_v3` 指定文件完全一致。历史 P 合同还固定过 exporter `7ed31890...eae7cf`，但该字节树当前不存在；所以本结果是“冻结 P seed-chain 配置在当前统一 exporter 上的全臂新执行”，不是历史 P 执行树的 byte-exact replay。未将历史 KLT fallback 或 7 月 Learned+KLT 结果改名为当前 XFeat。

LoFTR 是可选臂，未进入预注册主表，也未在结果后追加。由于共享磁盘上有独立 CPU exporter 重叠，本报告不比较 wall-clock 效率，见 [execution_conditions.md](execution_conditions.md)。

## 产物与复核入口

- 预注册：[preregistration.md](preregistration.md)、[contract.json](contract.json)、[windows.csv](windows.csv)、[arms.csv](arms.csv)
- Runability：[runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv)
- 精度：[accuracy.csv](accuracy.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)、[common_support_status.csv](common_support_status.csv)
- 公平性审计：[backend_config_audit.csv](backend_config_audit.csv)、[effective_frontend_input_audit.csv](effective_frontend_input_audit.csv)、[backend_feature_budget_audit.csv](backend_feature_budget_audit.csv)、[trajectory_scale_audit.csv](trajectory_scale_audit.csv)
- 模型身份：[runtime_weight_lock.json](runtime_weight_lock.json)
- 图：[figure-01-runability.pdf](analysis-output/figures/figure-01-runability.pdf)、[figure-02-common-support-accuracy.pdf](analysis-output/figures/figure-02-common-support-accuracy.pdf)
- 完整路径与 SHA-256：[artifacts.sha256](artifacts.sha256)

哈希清单包含正式 `vio.csv`、`vins.log`、feature bag、frontend metrics、VINS YAML、共同支撑/evo 产物、报告、图与复现实验脚本的绝对路径。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    analysis = f"""# 严格结果分析附录

## 分析总体

预注册总体为 7 窗口 × 3 前端 × 3 次 VINS replay。Runability 采用严格 3/3 规则。精度使用 {len(common)} 个 common-support 窗口：{', '.join(common) if common else 'none'}。

## 描述性配对效应

{effect_table}

## 解释边界

窗口是独立科学单位。重复中位数用于刻画初始化路径变化，不构成伪重复。精度是 proper SE(3)、无尺度拟合后的 proxy 一致性。任何一臂失败会把整个窗口排除出精度，但仍保留在 runability 分母中。
"""
    (OUT / "analysis-report.md").write_text(analysis, encoding="utf-8")

    stats = "# Statistical appendix\n\n" + "\n\n".join(stat_notes) + "\n\n" + effect_table + "\n"
    (OUT / "stats-appendix.md").write_text(stats, encoding="utf-8")
    catalog = """# Figure catalog

| Figure | File | Question | Denominator |
| --- | --- | --- | --- |
| 1 | `analysis-output/figures/figure-01-runability.pdf` | Which frontend/window cells pass 3/3 initialization and 70% coverage? | All 21 preregistered cells |
| 2 | `analysis-output/figures/figure-02-common-support-accuracy.pdf` | How do APE/RPE compare after fixed-scale SE(3) on one common grid? | Only all-arm common-support windows |

PNG companions are provided for quick inspection; PDF files are the publication-ready vector artifacts.
"""
    (OUT / "figure-catalog.md").write_text(catalog, encoding="utf-8")
    print(OUT / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
