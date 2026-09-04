#!/usr/bin/env python3
"""Generate the frozen frontend analysis reports and figures."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


COLORS = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "red": "#D55E00",
    "sky": "#56B4E9",
    "black": "#000000",
    "gray": "#777777",
}


def f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def i(row: dict[str, str], key: str) -> int:
    return int(row[key])


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = successes / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def exact_sign_p(positive: int, negative: int) -> float:
    n = positive + negative
    if n == 0:
        return math.nan
    tail = min(positive, negative)
    one_tail = sum(math.comb(n, k) for k in range(tail + 1)) / (2**n)
    return min(1.0, 2.0 * one_tail)


def holm(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    adjusted = [math.nan] * len(values)
    running = 0.0
    m = len(values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, values[index] * (m - rank)))
        adjusted[index] = running
    return adjusted


def rank_biserial(differences: list[float]) -> float:
    nonzero = [value for value in differences if value != 0.0]
    if not nonzero:
        return 0.0
    order = sorted(range(len(nonzero)), key=lambda idx: abs(nonzero[idx]))
    ranks = [0.0] * len(nonzero)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and abs(nonzero[order[end]]) == abs(nonzero[order[start]]):
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for pos in range(start, end):
            ranks[order[pos]] = average_rank
        start = end
    positive = sum(rank for rank, value in zip(ranks, nonzero) if value > 0.0)
    negative = sum(rank for rank, value in zip(ranks, nonzero) if value < 0.0)
    return (positive - negative) / (positive + negative)


def bootstrap_median(values: list[float], seed: int = 20260714, draws: int = 20000) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(array, size=(draws, len(array)), replace=True)
    medians = np.median(samples, axis=1)
    low, high = np.quantile(medians, [0.025, 0.975])
    return float(low), float(high)


def pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def rate(successes: int, n: int) -> str:
    low, high = wilson(successes, n)
    return f"{successes}/{n} ({100.0 * successes / n:.1f}%, 95% CI {100.0 * low:.1f}-{100.0 * high:.1f}%)"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def configure_fonts() -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            font_manager.fontManager.addfont(candidate)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=candidate).get_name()
            break
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, figures: Path, stem: str) -> None:
    fig.savefig(figures / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(figures / f"{stem}.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_case_ratios(fresh: list[dict[str, str]], figures: Path) -> None:
    labels = [row["case_id"] for row in fresh]
    ratios = [f(row, "full_ape_rmse_m") / f(row, "klt_ape_rmse_m") for row in fresh]
    active = [i(row, "learned_active") == 1 for row in fresh]
    y = np.arange(len(fresh))
    fig, ax = plt.subplots(figsize=(7.0, 6.2))
    for is_active, color, marker, label in [
        (True, COLORS["orange"], "o", "learned lineage active"),
        (False, COLORS["blue"], "s", "fallback / no learned lineage"),
    ]:
        idx = [pos for pos, value in enumerate(active) if value == is_active]
        ax.scatter([ratios[pos] for pos in idx], y[idx], color=color, marker=marker, s=35, label=label, zorder=3)
    ax.axvline(1.0, color=COLORS["black"], linewidth=1.1, label="KLT parity")
    ax.axvline(1.05, color=COLORS["red"], linewidth=1.0, linestyle="--", label="5% no-harm boundary")
    ax.set_xscale("log")
    ax.set_xlabel("APE ratio: full / KLT (lower is better)")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    save_figure(fig, figures, "figure-01-casewise-ape-ratio")


def figure_rates(rows: list[dict[str, str]], figures: Path) -> None:
    groups = [
        ("Main", [row for row in rows if row["cohort"] == "main"]),
        ("Secondary", [row for row in rows if row["cohort"] == "secondary"]),
        ("Fresh stress", [row for row in rows if row["cohort"] == "stress" and row["fresh_export"] == "1"]),
        ("All fresh", [row for row in rows if row["fresh_export"] == "1"]),
    ]
    metrics = [
        ("APE win", "ape_win", COLORS["blue"]),
        ("Dual-metric win", "dual_metric_win", COLORS["orange"]),
        ("No-harm", "no_harm_vs_klt", COLORS["green"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), gridspec_kw={"width_ratios": [1.5, 1.0]})
    x = np.arange(len(groups))
    width = 0.24
    for offset, (label, key, color) in enumerate(metrics):
        values = []
        low_errors = []
        high_errors = []
        for _, group in groups:
            successes = sum(i(row, key) for row in group)
            n = len(group)
            value = successes / n
            low, high = wilson(successes, n)
            values.append(value)
            low_errors.append(value - low)
            high_errors.append(high - value)
        pos = x + (offset - 1) * width
        axes[0].bar(pos, values, width, color=color, label=label)
        axes[0].errorbar(pos, values, yerr=[low_errors, high_errors], fmt="none", ecolor="black", capsize=2, linewidth=0.8)
    axes[0].set_xticks(x, [label for label, _ in groups], rotation=15, ha="right")
    axes[0].set_ylim(0.0, 1.08)
    axes[0].set_ylabel("Rate across independent clusters")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3)

    fresh = [row for row in rows if row["fresh_export"] == "1"]
    risk_metrics = [
        ("Hard failure", "hard_failure", COLORS["red"]),
        ("Solver risk", "solver_risk", COLORS["sky"]),
    ]
    arms = ["full", "drop", "klt"]
    width = 0.34
    for offset, (label, suffix, color) in enumerate(risk_metrics):
        values = [sum(i(row, f"{arm}_{suffix}") for row in fresh) / len(fresh) for arm in arms]
        axes[1].bar(np.arange(3) + (offset - 0.5) * width, values, width, color=color, label=label)
    axes[1].set_xticks(np.arange(3), ["full", "drop", "KLT"])
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_ylabel("Rate over all fresh clusters")
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].legend(frameon=False)
    fig.tight_layout()
    save_figure(fig, figures, "figure-02-outcome-and-risk-rates")


def figure_active_improvements(active: list[dict[str, str]], figures: Path) -> None:
    ordered = sorted(active, key=lambda row: f(row, "full_vs_klt_relative_improvement"))
    labels = [row["case_id"] for row in ordered]
    klt = [100.0 * f(row, "full_vs_klt_relative_improvement") for row in ordered]
    drop = [100.0 * f(row, "full_vs_drop_relative_improvement") for row in ordered]
    y = np.arange(len(ordered))
    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    ax.barh(y - 0.18, klt, height=0.34, color=COLORS["blue"], label="full vs KLT")
    ax.barh(y + 0.18, drop, height=0.34, color=COLORS["orange"], label="full vs whole-lineage drop")
    ax.axvline(0.0, color=COLORS["black"], linewidth=1.0)
    ax.set_yticks(y, labels)
    ax.set_xlabel("Relative APE improvement (%)")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    save_figure(fig, figures, "figure-03-learned-active-improvements")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-summary", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out = Path(args.output_dir)
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    with Path(args.case_summary).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    fresh = [row for row in rows if row["fresh_export"] == "1"]
    main_rows = [row for row in fresh if row["cohort"] == "main"]
    secondary = [row for row in fresh if row["cohort"] == "secondary"]
    stress = [row for row in fresh if row["cohort"] == "stress"]
    active = [row for row in fresh if i(row, "learned_active") == 1]
    inactive = [row for row in fresh if i(row, "learned_active") == 0]
    afrl = next(row for row in rows if row["case_id"] == "afrl_fr70_100")

    klt_improvements = [f(row, "full_vs_klt_relative_improvement") for row in active]
    drop_improvements = [f(row, "full_vs_drop_relative_improvement") for row in active]
    klt_differences = [f(row, "klt_ape_rmse_m") - f(row, "full_ape_rmse_m") for row in active]
    drop_differences = [f(row, "drop_ape_rmse_m") - f(row, "full_ape_rmse_m") for row in active]
    p_klt = exact_sign_p(sum(value > 0 for value in klt_differences), sum(value < 0 for value in klt_differences))
    p_drop = exact_sign_p(sum(value > 0 for value in drop_differences), sum(value < 0 for value in drop_differences))
    p_klt_holm, p_drop_holm = holm([p_klt, p_drop])
    klt_ci = bootstrap_median(klt_improvements)
    drop_ci = bootstrap_median(drop_improvements, seed=20260715)

    configure_fonts()
    figure_case_ratios(fresh, figures)
    figure_rates(rows, figures)
    figure_active_improvements(active, figures)

    cohort_specs = [
        ("主队列", main_rows),
        ("Secondary", secondary),
        ("Fresh stress", stress),
        ("全部 fresh", fresh),
        ("Learned-active fresh", active),
        ("Learned-inactive fresh", inactive),
    ]
    cohort_table = []
    for label, group in cohort_specs:
        cohort_table.append(
            [
                label,
                str(len(group)),
                f"{sum(i(row, 'ape_win') for row in group)}/{len(group)}",
                f"{sum(i(row, 'dual_metric_win') for row in group)}/{len(group)}",
                f"{sum(i(row, 'no_harm_vs_klt') for row in group)}/{len(group)}",
                f"{sum(i(row, 'full_hard_failure') for row in group)}/{len(group)}",
                f"{sum(i(row, 'full_solver_risk') for row in group)}/{len(group)}",
            ]
        )

    active_table = []
    for row in active:
        active_table.append(
            [
                row["case_id"],
                row["dataset_family"],
                row["learned_track_ids"],
                f"{f(row, 'full_ape_rmse_m'):.6f}",
                f"{f(row, 'drop_ape_rmse_m'):.6f}",
                f"{f(row, 'klt_ape_rmse_m'):.6f}",
                pct(f(row, "full_vs_klt_relative_improvement")),
                "是" if i(row, "dual_metric_win") else "否",
                "是" if i(row, "full_solver_risk") else "否",
            ]
        )

    stress_table = []
    for row in stress:
        stress_table.append(
            [
                row["case_id"],
                row["selected_profile"],
                row["learned_track_ids"],
                f"{f(row, 'full_ape_rmse_m'):.6f}",
                f"{f(row, 'klt_ape_rmse_m'):.6f}",
                "是" if i(row, "no_harm_vs_klt") else "否",
                f"{i(row, 'full_solver_failure_count')}/{i(row, 'drop_solver_failure_count')}/{i(row, 'klt_solver_failure_count')}",
            ]
        )

    report = f"""# 冻结前端统一三路评测分析

## 分析问题与口径

- 比较：fresh full、从同一 full bag 删除 whole learned lineage 的 drop、独立 fresh KLT。
- 主要指标：SE(3) 对齐 APE RMSE；次要指标：1 s 平移 RPE RMSE；时间匹配上限 0.6 s。
- 独立单位：manifest 中不重叠的时间窗口簇。fresh 队列共 {len(fresh)} 簇；AFRL FR70-100 仅作 existing-bag replay。
- 主胜定义：full 有效且 APE 不差于 drop 和 KLT；no-harm 定义：full 相对 KLT 的 APE 退化不超过 5%。

## 关键结果

1. 预选主队列为 {rate(sum(i(row, 'ape_win') for row in main_rows), len(main_rows))} APE 胜，双指标胜 {sum(i(row, 'dual_metric_win') for row in main_rows)}/{len(main_rows)}。其中 A02_2800-3200 未触发 learned lineage，是 no-harm tie；其余 8/8 learned-active 主窗口均严格优于 KLT 与 drop。
2. 所有 learned-active fresh 窗口中，full 相对 KLT 的 APE 胜率为 {rate(sum(i(row, 'ape_win') for row in active), len(active))}，双指标胜率为 {sum(i(row, 'dual_metric_win') for row in active)}/{len(active)}。APE 相对改善中位数为 {pct(statistics.median(klt_improvements))}，簇 bootstrap 95% CI 为 {pct(klt_ci[0])} 至 {pct(klt_ci[1])}。
3. full 相对 whole-lineage drop 在 learned-active fresh 窗口上为 {sum(f(row, 'full_ape_rmse_m') < f(row, 'drop_ape_rmse_m') for row in active)}/{len(active)} APE 改善；中位改善 {pct(statistics.median(drop_improvements))}，bootstrap 95% CI {pct(drop_ci[0])} 至 {pct(drop_ci[1])}。
4. 唯一超过 5% 的 fresh 反例是 A09_5000-5400：full/KLT APE 为 1.360408/1.082993 m，full 退化 25.6%。因此证据支持“不弱于 KLT，且经常改善”，不支持“普遍优于 KLT”。
5. learned-inactive fresh 窗口 no-harm 为 {sum(i(row, 'no_harm_vs_klt') for row in inactive)}/{len(inactive)}。A02_8600-9000、A08_4480-4680 和 H02_2400-2800 的并发/时序异常 run 已保留审计，并由空闲、同配置 replay 替换；最终三路结果收敛。
6. 全部 fresh arm 的 hard failure 为 full/drop/KLT = {sum(i(row, 'full_hard_failure') for row in fresh)}/{len(fresh)}、{sum(i(row, 'drop_hard_failure') for row in fresh)}/{len(fresh)}、{sum(i(row, 'klt_hard_failure') for row in fresh)}/{len(fresh)}。但 solver-risk 窗口率分别为 {sum(i(row, 'full_solver_risk') for row in fresh)}/{len(fresh)}、{sum(i(row, 'drop_solver_risk') for row in fresh)}/{len(fresh)}、{sum(i(row, 'klt_solver_risk') for row in fresh)}/{len(fresh)}，不能宣称系统已普遍稳定。
7. AFRL existing-bag full/drop/KLT APE 为 {f(afrl, 'full_ape_rmse_m'):.6f}/{f(afrl, 'drop_ape_rmse_m'):.6f}/{f(afrl, 'klt_ape_rmse_m'):.6f} m，无 solver failure；差异仅 0.016%，作为 no-harm 控制，不作为 fresh 学习正例。

## 队列汇总

{markdown_table(['队列', 'n', 'APE 胜', '双指标胜', 'no-harm', 'full hard failure', 'full solver risk'], cohort_table)}

## Learned-active 逐簇结果

{markdown_table(['窗口', '数据族', 'learned IDs', 'full APE', 'drop APE', 'KLT APE', 'full vs KLT', '双指标胜', 'full solver risk'], active_table)}

## Fresh stress / no-harm

{markdown_table(['窗口', '实际 profile', 'learned IDs', 'full APE', 'KLT APE', 'no-harm', 'solver failures F/D/K'], stress_table)}

## Claim Candidates

- Claim:
  - Source evidence: learned-active fresh 10/11 APE 胜；覆盖 AQUALOC、NTNU、CIRS 三个数据族。
  - Allowed wording: “在预先选定的低纹理水下窗口中，learned-seeded KLT 前端通常不弱于 KLT，并经常降低 VINS APE。”
  - Forbidden stronger wording: “learned features broadly/universally improve VINS”或“所有低纹理场景都优于 KLT”。
  - Uncertainty: 主队列经过历史筛选，且每簇只有一次有效 replay；A09_5000-5400 为真实反例。
  - Next check: 在未参与 profile 设计的新数据或整段序列上盲测。
  - Decision: keep with weakened wording

- Claim:
  - Source evidence: learned-active fresh 11/11 的 full APE 低于 whole-lineage drop。
  - Allowed wording: “在本评测矩阵的 learned-active 窗口中，保留 learned lineage 比删除完整 lineage 获得更低 APE。”
  - Forbidden stronger wording: “任意 learned 点都会改善后端”。
  - Uncertainty: drop 会删除后续 KLT 传播的整条 lineage，表示轨迹级贡献，不是单点质量因果。
  - Next check: 增加等数量随机 KLT lineage 删除对照。
  - Decision: keep

- Claim:
  - Source evidence: learned-inactive fresh 9/9 满足 5% no-harm。
  - Allowed wording: “冻结 arbitration 在未接受 learned lineage 的控制窗口中保持 KLT 级表现。”
  - Forbidden stronger wording: “所有普通场景绝对无害”。
  - Uncertainty: solver-risk 仍存在，且 no-harm 是窗口级 APE 定义。
  - Next check: 增加长序列和跨运行重复。
  - Decision: keep
"""
    (out / "analysis-report.md").write_text(report, encoding="utf-8")

    hard_rows = []
    for arm in ["full", "drop", "klt"]:
        hard = sum(i(row, f"{arm}_hard_failure") for row in fresh)
        solver = sum(i(row, f"{arm}_solver_risk") for row in fresh)
        hard_rows.append([arm, rate(hard, len(fresh)), rate(solver, len(fresh))])

    stats = f"""# 统计附录

## 设计与独立性

- 独立单位为 20 个 fresh 非重叠窗口簇，而不是 feature frame、轨迹点或重叠扩窗。
- 主队列 n=9 是历史预选正例，secondary n=3 是弱候选，stress n=8 是预注册压力/no-harm 窗口。AFRL n=1 因 raw 缺失单列。
- 每个窗口只有一次最终有效 replay；不存在可用于估计训练 seed 方差的重复实验。A02_8600-9000、A08_4480-4680、H02_2400-2800 的额外 replay 仅用于排除并发/配置异常。

## 描述统计

- learned-active fresh n={len(active)}：APE 胜 {rate(sum(i(row, 'ape_win') for row in active), len(active))}；双指标胜 {rate(sum(i(row, 'dual_metric_win') for row in active), len(active))}；no-harm {rate(sum(i(row, 'no_harm_vs_klt') for row in active), len(active))}。
- learned-inactive fresh n={len(inactive)}：no-harm {rate(sum(i(row, 'no_harm_vs_klt') for row in inactive), len(inactive))}。
- 全部 fresh n={len(fresh)}：APE 胜 {rate(sum(i(row, 'ape_win') for row in fresh), len(fresh))}；双指标胜 {rate(sum(i(row, 'dual_metric_win') for row in fresh), len(fresh))}；no-harm {rate(sum(i(row, 'no_harm_vs_klt') for row in fresh), len(fresh))}。
- learned-active full vs KLT 相对改善：中位数 {pct(statistics.median(klt_improvements))}，IQR {pct(float(np.quantile(klt_improvements, 0.25)))} 至 {pct(float(np.quantile(klt_improvements, 0.75)))}，cluster bootstrap 95% CI {pct(klt_ci[0])} 至 {pct(klt_ci[1])}。
- learned-active full vs drop 相对改善：中位数 {pct(statistics.median(drop_improvements))}，IQR {pct(float(np.quantile(drop_improvements, 0.25)))} 至 {pct(float(np.quantile(drop_improvements, 0.75)))}，cluster bootstrap 95% CI {pct(drop_ci[0])} 至 {pct(drop_ci[1])}。

## 探索性配对检验

样本量小且 APE 差值强偏态，因此不采用配对 t 检验；使用不依赖正态性的双侧精确符号检验。两个主要 contrast 采用 Holm 校正。

- full vs KLT：正/负差值 = {sum(value > 0 for value in klt_differences)}/{sum(value < 0 for value in klt_differences)}；exact sign p={p_klt:.6f}，Holm-adjusted p={p_klt_holm:.6f}；paired rank-biserial effect={rank_biserial(klt_differences):.3f}。
- full vs drop：正/负差值 = {sum(value > 0 for value in drop_differences)}/{sum(value < 0 for value in drop_differences)}；exact sign p={p_drop:.6f}，Holm-adjusted p={p_drop_holm:.6f}；paired rank-biserial effect={rank_biserial(drop_differences):.3f}。

这些 p 值仅描述当前窗口矩阵，不可外推为随机抽样总体显著性，因为主窗口有选择偏差且没有独立数据级重复。

## 失败与风险

{markdown_table(['arm', 'hard failure rate', 'solver-risk rate'], hard_rows)}

- hard failure：空轨迹、init_success=0 或 coverage<0.5。
- solver risk：VINS log 中至少一次 linear solver failure；与 hard failure 分开统计。
- 所有最终 fresh arm 均无 hard failure，但 solver-risk 仍高，尤其 learned-active secondary 3/3 均有 solver risk。

## Replay 审计

- H02 原 full 在外部 VINS 并发时得到 38.069371 m；空闲且配置完全一致的 r2 为 0.225773 m，与 KLT 相同。原 run 路径保留在状态文件的 `full_run_contaminated`。
- A02_8600-9000 原三路同 bag 却得到 0.168223/0.086341/0.089505 m；空闲 r1 三路均为 0.089505 m，solver failure 均为 11。旧路径保留为 `*_run_unstable`。
- A08_4480-4680 的 full/drop 与外部任务重叠；空闲复放 strict APE 均为 0.298231 m，clean KLT 为 0.298233 m。
- 这些替换只重放冻结 feature bag，没有重新 export 或修改 arbitration。

## 局限

1. 主队列是预选窗口，不能据此估计未经筛选数据流上的总体胜率。
2. 单窗口单 replay 无法给出后端运行方差；solver-risk 窗口需要重复 replay 或更确定性的消息调度。
3. whole-lineage drop 同时删除 learned seed 及其后续 KLT 传播，衡量的是 lineage 级贡献。
4. AFRL 只有 existing-bag replay，不能进入 fresh-export 统计。
5. APE 使用 SE(3) 对齐，不能替代初始化成功率、覆盖率和 solver stability。
"""
    (out / "stats-appendix.md").write_text(stats, encoding="utf-8")

    catalog = """# 图表目录

## figure-01-casewise-ape-ratio

- 文件：`figures/figure-01-casewise-ape-ratio.pdf` 与 `.png`
- 目的：展示每个 fresh 独立窗口的 full/KLT APE 比值，并区分 learned-active 与 fallback。
- 数据源：`case_summary.csv` 中 20 个 fresh 簇。
- Caption 要求：说明横轴为对数尺度，1.0 为 KLT 持平，1.05 为 no-harm 边界。
- 关键观察：唯一超过 1.05 的点是 A09_5000-5400；多个 learned-active 主窗口显著低于 1.0。
- 解读边界：主窗口是预选正例，不可把点的密度解释成自然数据分布。

## figure-02-outcome-and-risk-rates

- 文件：`figures/figure-02-outcome-and-risk-rates.pdf` 与 `.png`
- 目的：左图比较各队列 APE 胜、双指标胜和 no-harm；右图分开显示 hard failure 与 solver risk。
- 数据源：`case_summary.csv`；误差线是窗口簇二项率的 Wilson 95% CI。
- 关键观察：主队列胜率高但区间仍宽；hard failure 为零，solver risk 明显非零。
- 解读边界：Wilson CI 反映有限窗口数量，不代表随机抽样总体置信区间。

## figure-03-learned-active-improvements

- 文件：`figures/figure-03-learned-active-improvements.pdf` 与 `.png`
- 目的：逐个 learned-active 窗口展示 full 相对 KLT 和 whole-lineage drop 的 APE 改善。
- 数据源：11 个 learned-active fresh 簇。
- 关键观察：full 相对 drop 全部改善；相对 KLT 仅 A09_5000-5400 为负。
- 解读边界：极大百分比来自控制 APE 很大，必须与绝对 APE 表一起阅读。
"""
    (out / "figure-catalog.md").write_text(catalog, encoding="utf-8")
    print(f"fresh_clusters={len(fresh)}")
    print(f"learned_active_clusters={len(active)}")
    print(f"output_dir={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
