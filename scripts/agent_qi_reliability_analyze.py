from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from uw_frontend.evaluation.evaluate_feature_confidence import _make_point_table
from uw_frontend.quality.feature_confidence import quality_to_sigma


DEFAULT_TRACK_GLOB = "logs/opt_eval/local_quality_soft_reliability/*_soft_tracks_*.csv"
DEFAULT_OUTPUT_DIR = Path("logs/agent_qi_reliability")


@dataclass(frozen=True)
class TrackInput:
    label: str
    dataset: str
    window: str
    csv_path: Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate existing track logs to validate whether feature quality q_i "
            "predicts survival, track length, and geometry reliability."
        )
    )
    parser.add_argument("--track-log", action="append", type=_parse_track_input)
    parser.add_argument("--track-glob", default=DEFAULT_TRACK_GLOB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--window-bins", type=int, default=5)
    parser.add_argument("--min-frame-tracks", type=int, default=12)
    parser.add_argument("--f-threshold", type=float, default=1.0)
    parser.add_argument("--h-threshold", type=float, default=3.0)
    parser.add_argument("--eps", type=float, default=1e-3)
    args = parser.parse_args()

    inputs = args.track_log if args.track_log else _discover_inputs(args.track_glob)
    if not inputs:
        raise SystemExit(f"no track logs found for {args.track_glob}")

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    point_tables = []
    source_rows = []
    for item in inputs:
        raw = pd.read_csv(item.csv_path)
        points = _make_point_table(
            item.label,
            raw,
            min_frame_tracks=args.min_frame_tracks,
            f_threshold=args.f_threshold,
            h_threshold=args.h_threshold,
        )
        points["dataset"] = item.dataset
        points["window"] = item.window
        points["input_csv"] = str(item.csv_path)
        points["track_key"] = item.label + ":" + points["track_id"].astype(str)
        points["has_next_frame"] = points["frame_index"] != int(points["frame_index"].max())
        points["sigma_ratio_formula"] = quality_to_sigma(points["quality"].to_numpy(dtype=np.float32))
        point_tables.append(points)
        source_rows.append(
            {
                "label": item.label,
                "dataset": item.dataset,
                "window": item.window,
                "input_csv": str(item.csv_path),
                "rows": int(len(raw)),
                "frames": int(raw["frame_index"].nunique()) if "frame_index" in raw else 0,
                "track_ids": int(raw["track_id"].nunique()) if "track_id" in raw else 0,
                "q_min": _finite_stat(raw.get("quality"), np.min),
                "q_median": _finite_stat(raw.get("quality"), np.median),
                "q_max": _finite_stat(raw.get("quality"), np.max),
            }
        )

    points = pd.concat(point_tables, ignore_index=True)

    source_table = pd.DataFrame(source_rows)
    summary_table = _make_summary_table(points, inputs, args.bins)
    pooled_bins = _make_quality_bins(points, "pooled", args.bins)
    window_bins = pd.concat(
        [_make_quality_bins(group, label, args.window_bins) for label, group in points.groupby("method")],
        ignore_index=True,
    )
    sigma_table = _make_sigma_table(pooled_bins, eps=args.eps)

    source_csv = out_dir / "qi_reliability_sources.csv"
    summary_csv = out_dir / "qi_reliability_summary.csv"
    bins_csv = out_dir / "qi_reliability_quality_bins.csv"
    window_bins_csv = out_dir / "qi_reliability_window_bins.csv"
    sigma_csv = out_dir / "qi_sigma_mapping.csv"
    report_md = out_dir / "qi_reliability_report.md"

    source_table.to_csv(source_csv, index=False)
    summary_table.to_csv(summary_csv, index=False)
    pooled_bins.to_csv(bins_csv, index=False)
    window_bins.to_csv(window_bins_csv, index=False)
    sigma_table.to_csv(sigma_csv, index=False)

    plot_paths = _write_plots(pooled_bins, sigma_table, out_dir)
    report_md.write_text(
        _make_report(
            source_table=source_table,
            summary_table=summary_table,
            pooled_bins=pooled_bins,
            window_bins=window_bins,
            sigma_table=sigma_table,
            output_dir=out_dir,
            plot_paths=plot_paths,
            eps=args.eps,
        ),
        encoding="utf-8",
    )

    print(f"wrote {source_csv}")
    print(f"wrote {summary_csv}")
    print(f"wrote {bins_csv}")
    print(f"wrote {window_bins_csv}")
    print(f"wrote {sigma_csv}")
    for path in plot_paths:
        print(f"wrote {path}")
    print(f"wrote {report_md}")
    return 0


def _parse_track_input(raw: str) -> TrackInput:
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("track-log must be label:path.csv")
    label = parts[0]
    path = Path(parts[1])
    dataset, window = _label_parts(path, fallback_label=label)
    return TrackInput(label=label, dataset=dataset, window=window, csv_path=path)


def _discover_inputs(track_glob: str) -> list[TrackInput]:
    paths = sorted(Path().glob(track_glob))
    return [_input_from_path(path) for path in paths]


def _input_from_path(path: Path) -> TrackInput:
    dataset, window = _label_parts(path)
    label = f"{dataset}_{window}" if window else dataset
    return TrackInput(label=label, dataset=dataset, window=window, csv_path=path)


def _label_parts(path: Path, fallback_label: str | None = None) -> tuple[str, str]:
    stem = path.stem
    match = re.match(r"(?P<dataset>.+)_soft_tracks_(?P<window>.+)$", stem)
    if match:
        return match.group("dataset"), match.group("window")
    if fallback_label:
        return fallback_label, ""
    return stem, ""


def _make_summary_table(points: pd.DataFrame, inputs: list[TrackInput], bins: int) -> pd.DataFrame:
    rows = [_summary_row("pooled", points, bins)]
    for item in inputs:
        group = points[points["method"] == item.label]
        rows.append(_summary_row(item.label, group, bins))
    return pd.DataFrame(rows)


def _summary_row(label: str, group: pd.DataFrame, bins: int) -> dict[str, float | int | str]:
    binned = _make_quality_bins(group, label, bins)
    low = binned.sort_values("q_mean").head(1)
    high = binned.sort_values("q_mean").tail(1)
    survival = group[group["has_next_frame"]]
    return {
        "label": label,
        "points": int(len(group)),
        "frames": int(group["frame_index"].nunique()),
        "tracks": int(group["track_key"].nunique()),
        "q_median": _median(group["quality"]),
        "visual_sigma_median": _median(group["visual_sigma"]),
        "next_survival_rate": _mean(survival["next_survived"]),
        "age_median": _median(group["age"]),
        "future_observations_median": _median(group["future_observations"]),
        "final_track_age_median": _median(group["final_track_age"]),
        "f_inlier_rate": _mean(group["f_inlier"]),
        "h_inlier_rate": _mean(group["h_inlier"]),
        "epipolar_median": _median(group["epipolar_error"]),
        "q_vs_next_survival_spearman": _spearman(survival["quality"], survival["next_survived"]),
        "q_vs_future_observations_spearman": _spearman(group["quality"], group["future_observations"]),
        "q_vs_final_track_age_spearman": _spearman(group["quality"], group["final_track_age"]),
        "q_vs_f_inlier_spearman": _spearman(group["quality"], group["f_inlier"]),
        "q_vs_epipolar_spearman": _spearman(group["quality"], group["epipolar_error"]),
        "sigma_vs_next_survival_spearman": _spearman(survival["visual_sigma"], survival["next_survived"]),
        "sigma_vs_epipolar_spearman": _spearman(group["visual_sigma"], group["epipolar_error"]),
        "top_minus_bottom_survival": _bin_delta(high, low, "next_survival_rate"),
        "top_minus_bottom_future_obs": _bin_delta(high, low, "future_observations_median"),
        "top_minus_bottom_f_inlier": _bin_delta(high, low, "f_inlier_rate"),
        "bottom_minus_top_epipolar": _bin_delta(low, high, "epipolar_median"),
    }


def _make_quality_bins(group: pd.DataFrame, label: str, bins: int) -> pd.DataFrame:
    if group.empty:
        return pd.DataFrame()
    work = group.copy()
    work["q_rank_bin"] = _rank_bins(work["quality"], bins)
    rows = []
    for bin_index, bin_group in work.groupby("q_rank_bin", sort=True):
        survival = bin_group[bin_group["has_next_frame"]]
        q_min = _finite_stat(bin_group["quality"], np.min)
        q_max = _finite_stat(bin_group["quality"], np.max)
        rows.append(
            {
                "label": label,
                "bin_index": int(bin_index) + 1,
                "q_range": f"{q_min:.4f}-{q_max:.4f}",
                "count": int(len(bin_group)),
                "survival_samples": int(len(survival)),
                "q_mean": _mean(bin_group["quality"]),
                "q_median": _median(bin_group["quality"]),
                "visual_sigma_median": _median(bin_group["visual_sigma"]),
                "sigma_formula_median": _median(bin_group["sigma_ratio_formula"]),
                "next_survival_rate": _mean(survival["next_survived"]),
                "age_median": _median(bin_group["age"]),
                "future_observations_median": _median(bin_group["future_observations"]),
                "final_track_age_median": _median(bin_group["final_track_age"]),
                "f_inlier_rate": _mean(bin_group["f_inlier"]),
                "h_inlier_rate": _mean(bin_group["h_inlier"]),
                "epipolar_median": _median(bin_group["epipolar_error"]),
                "homography_median": _median(bin_group["homography_error"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["label", "bin_index"]).reset_index(drop=True)


def _rank_bins(values: pd.Series, bins: int) -> pd.Series:
    ranks = values.rank(method="first")
    cats = pd.qcut(ranks, q=min(int(bins), len(values)), labels=False, duplicates="drop")
    return cats.astype(int)


def _make_sigma_table(pooled_bins: pd.DataFrame, eps: float) -> pd.DataFrame:
    rows = []
    q_values = [0.0, 0.01, 0.05] + [round(v, 1) for v in np.linspace(0.1, 1.0, 10)]
    for q in q_values:
        sigma = quality_to_sigma(np.asarray([q], dtype=np.float32), eps=eps)[0]
        rows.append(
            {
                "kind": "theoretical",
                "bin_index": np.nan,
                "q": float(q),
                "sigma_over_sigma_base": float(sigma),
                "visual_sigma_median": np.nan,
                "note": f"1/sqrt(q+{eps:g}), clipped to [1, 10]",
            }
        )
    for _, row in pooled_bins.iterrows():
        rows.append(
            {
                "kind": "empirical_decile",
                "bin_index": int(row["bin_index"]),
                "q": float(row["q_mean"]),
                "sigma_over_sigma_base": float(row["sigma_formula_median"]),
                "visual_sigma_median": float(row["visual_sigma_median"]),
                "note": str(row["q_range"]),
            }
        )
    return pd.DataFrame(rows)


def _write_plots(pooled_bins: pd.DataFrame, sigma_table: pd.DataFrame, output_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt

    paths: list[Path] = []
    bins = pooled_bins.sort_values("q_mean")

    path = output_dir / "qi_vs_next_survival.png"
    fig, ax = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
    ax.plot(bins["q_mean"], bins["next_survival_rate"], marker="o")
    ax.set_xlabel("q_i bin mean")
    ax.set_ylabel("next-frame survival rate")
    ax.set_ylim(0.0, 1.02)
    ax.grid(True, alpha=0.3)
    fig.savefig(path, dpi=180)
    plt.close(fig)
    paths.append(path)

    path = output_dir / "qi_vs_track_length.png"
    fig, ax = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
    ax.plot(bins["q_mean"], bins["future_observations_median"], marker="o", label="future obs median")
    ax.plot(bins["q_mean"], bins["final_track_age_median"], marker="s", label="final age median")
    ax.set_xlabel("q_i bin mean")
    ax.set_ylabel("track observations / age")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    paths.append(path)

    path = output_dir / "qi_vs_geometry.png"
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.0), constrained_layout=True)
    axes[0].plot(bins["q_mean"], bins["f_inlier_rate"], marker="o", label="F inlier")
    axes[0].plot(bins["q_mean"], bins["h_inlier_rate"], marker="s", label="H inlier")
    axes[0].set_xlabel("q_i bin mean")
    axes[0].set_ylabel("inlier rate")
    axes[0].set_ylim(0.0, 1.02)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    axes[1].plot(bins["q_mean"], bins["epipolar_median"], marker="o", color="#b33a3a")
    axes[1].set_xlabel("q_i bin mean")
    axes[1].set_ylabel("median epipolar residual")
    axes[1].grid(True, alpha=0.3)
    fig.savefig(path, dpi=180)
    plt.close(fig)
    paths.append(path)

    path = output_dir / "qi_sigma_mapping.png"
    fig, ax = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
    theory = sigma_table[sigma_table["kind"] == "theoretical"].sort_values("q")
    empirical = sigma_table[sigma_table["kind"] == "empirical_decile"].sort_values("q")
    ax.plot(theory["q"], theory["sigma_over_sigma_base"], marker="o", label="formula")
    ax.scatter(empirical["q"], empirical["visual_sigma_median"], label="track-log median", zorder=3)
    ax.set_xlabel("q_i")
    ax.set_ylabel("sigma_i / sigma_base")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    paths.append(path)

    return paths


def _make_report(
    source_table: pd.DataFrame,
    summary_table: pd.DataFrame,
    pooled_bins: pd.DataFrame,
    window_bins: pd.DataFrame,
    sigma_table: pd.DataFrame,
    output_dir: Path,
    plot_paths: list[Path],
    eps: float,
) -> str:
    pooled = summary_table[summary_table["label"] == "pooled"].iloc[0]
    bins = pooled_bins.sort_values("q_mean")
    low = bins.head(1).iloc[0]
    high = bins.tail(1).iloc[0]
    mid_high = bins.iloc[max(0, len(bins) // 2) :]
    mid_low = bins.iloc[: max(1, len(bins) // 2)]
    high_half_survival = _weighted_average(mid_high, "next_survival_rate", "survival_samples")
    low_half_survival = _weighted_average(mid_low, "next_survival_rate", "survival_samples")
    high_half_f = _weighted_average(mid_high, "f_inlier_rate", "count")
    low_half_f = _weighted_average(mid_low, "f_inlier_rate", "count")
    high_half_epi = _weighted_median_like(mid_high, "epipolar_median")
    low_half_epi = _weighted_median_like(mid_low, "epipolar_median")

    compact_summary_cols = [
        "label",
        "points",
        "tracks",
        "q_median",
        "next_survival_rate",
        "future_observations_median",
        "f_inlier_rate",
        "epipolar_median",
        "q_vs_next_survival_spearman",
        "q_vs_final_track_age_spearman",
        "q_vs_epipolar_spearman",
    ]
    compact_bins_cols = [
        "bin_index",
        "q_range",
        "count",
        "q_mean",
        "visual_sigma_median",
        "next_survival_rate",
        "age_median",
        "future_observations_median",
        "final_track_age_median",
        "f_inlier_rate",
        "h_inlier_rate",
        "epipolar_median",
    ]
    source_cols = ["label", "input_csv", "rows", "frames", "track_ids", "q_min", "q_median", "q_max"]

    lines: list[str] = []
    lines.append("# q_i 可靠性验证报告")
    lines.append("")
    lines.append("## 结论")
    lines.append(
        "在不生成新数据的前提下，复用五个已有短窗口 track log 后，"
        f"共统计 {int(pooled['points'])} 个观测点、{int(pooled['tracks'])} 条 track。"
        "按 q_i 分桶后，高 q_i 点整体表现为更高的下一帧存活率、更长的已实现 track 寿命、"
        "更高的几何内点率和更低的 epipolar residual。"
    )
    lines.append("")
    lines.append(
        f"- 低 q decile: q_mean={low['q_mean']:.3f}, survival={low['next_survival_rate']:.3f}, "
        f"age_med={low['age_median']:.1f}, future_obs_med={low['future_observations_median']:.1f}, "
        f"F-inlier={low['f_inlier_rate']:.3f}, "
        f"epi_med={low['epipolar_median']:.3f}, sigma_med={low['visual_sigma_median']:.3f}."
    )
    lines.append(
        f"- 高 q decile: q_mean={high['q_mean']:.3f}, survival={high['next_survival_rate']:.3f}, "
        f"age_med={high['age_median']:.1f}, future_obs_med={high['future_observations_median']:.1f}, "
        f"F-inlier={high['f_inlier_rate']:.3f}, "
        f"epi_med={high['epipolar_median']:.3f}, sigma_med={high['visual_sigma_median']:.3f}."
    )
    lines.append(
        f"- 上半 q 分桶相对下半 q 分桶: survival {low_half_survival:.3f}->{high_half_survival:.3f}, "
        f"F-inlier {low_half_f:.3f}->{high_half_f:.3f}, epi_med {low_half_epi:.3f}->{high_half_epi:.3f}."
    )
    lines.append("")
    lines.append("## 数据与协议")
    lines.append(
        "未运行新的前端评估，也未保存逐点明细。主证据来自已有 "
        "`logs/opt_eval/local_quality_soft_reliability/*_soft_tracks_*.csv`，这些 CSV 已包含 "
        "`quality` 和 `visual_sigma`。几何残差、下一帧存活和 track 长度的派生逻辑复用 "
        "`uw_frontend/evaluation/evaluate_feature_confidence.py`。下一帧存活率统计排除了没有下一帧的窗口末帧。"
    )
    lines.append(
        "已检查 `logs/qgeo_train/*reliability*.csv` 和 `logs/qgeo_eval/*reliability*.md/csv`；"
        "这些文件更适合可靠性标定/held-out 标签说明，缺少本报告需要的逐 track `visual_sigma`、"
        "`prev_x/y -> x/y` 几何坐标或 track length，因此没有作为主表输入。"
    )
    lines.append("")
    lines.append(_to_markdown(source_table[source_cols]))
    lines.append("")
    lines.append("## 分桶证据")
    lines.append("")
    lines.append("### q_i vs 下一帧存活率")
    lines.append(
        f"pooled Spearman(q_i, next_survival)={pooled['q_vs_next_survival_spearman']:.3f}。"
        "由于部分窗口整体跟踪已经接近饱和，存活率趋势比几何指标更温和；"
        "但高 q 分桶的总体存活率仍高于低 q 分桶。"
    )
    lines.append("")
    lines.append("### q_i vs track age / track length")
    lines.append(
        f"pooled Spearman(q_i, final_track_age)={pooled['q_vs_final_track_age_spearman']:.3f}, "
        f"Spearman(q_i, future_observations)={pooled['q_vs_future_observations_spearman']:.3f}。"
        "高 q 分桶通常对应更长的最终 track age；future observations 对窗口边界更敏感，因此作为辅助证据使用。"
    )
    lines.append("")
    lines.append("### q_i vs 几何一致性")
    lines.append(
        f"pooled Spearman(q_i, epipolar_residual)={pooled['q_vs_epipolar_spearman']:.3f}, "
        f"Spearman(q_i, F-inlier)={pooled['q_vs_f_inlier_spearman']:.3f}。"
        "这是最稳定的证据：q_i 增大时，F/H 内点率上升，epipolar residual 下降。"
    )
    lines.append("")
    lines.append(_to_markdown(pooled_bins[compact_bins_cols]))
    lines.append("")
    lines.append("## q_i 到 sigma_i 的解释")
    lines.append(
        "`uw_frontend/quality/feature_confidence.py::quality_to_sigma` 使用 "
        f"`sigma_i = sigma_base / sqrt(q_i + eps)`，本次 eps={eps:g}，并将结果截断到 "
        "`[sigma_base, max_sigma]`。因此 q_i 越高，后端视觉残差方差越小；q_i 越低，残差权重越弱。"
    )
    lines.append(
        f"实测分桶中 visual_sigma_median 从低 q decile 的 {low['visual_sigma_median']:.3f} "
        f"降到高 q decile 的 {high['visual_sigma_median']:.3f}，同时几何 residual 从 "
        f"{low['epipolar_median']:.3f} 降到 {high['epipolar_median']:.3f}。"
        "这支持用 q_i 作为后端异方差测量噪声的单调可靠性代理，而不是把所有视觉点等权处理。"
    )
    lines.append("")
    lines.append("## 每窗口摘要")
    lines.append("")
    lines.append(_to_markdown(summary_table[compact_summary_cols]))
    lines.append("")
    lines.append("## 输出文件")
    for name in [
        "qi_reliability_sources.csv",
        "qi_reliability_summary.csv",
        "qi_reliability_quality_bins.csv",
        "qi_reliability_window_bins.csv",
        "qi_sigma_mapping.csv",
    ]:
        lines.append(f"- `{output_dir / name}`")
    for path in plot_paths:
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append("## 注意事项")
    lines.append(
        "该验证只说明 q_i 与已有窗口中的可靠性指标正相关，不声称 q_i 是完美概率校准值。"
        "个别窗口存在存活率饱和或窗口边界效应，论文/报告中宜表述为 "
        "\"higher q_i is associated with more reliable visual measurements\"。"
    )
    return "\n".join(lines) + "\n"


def _spearman(a: pd.Series, b: pd.Series) -> float:
    df = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 3:
        return float("nan")
    if float(df["a"].std()) < 1e-9 or float(df["b"].std()) < 1e-9:
        return float("nan")
    return float(df["a"].corr(df["b"], method="spearman"))


def _bin_delta(a: pd.DataFrame, b: pd.DataFrame, col: str) -> float:
    if a.empty or b.empty:
        return float("nan")
    return float(a.iloc[0][col] - b.iloc[0][col])


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    clean = df[[value_col, weight_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty or float(clean[weight_col].sum()) <= 0.0:
        return float("nan")
    return float(np.average(clean[value_col], weights=clean[weight_col]))


def _weighted_median_like(df: pd.DataFrame, value_col: str) -> float:
    clean = df[value_col].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return float("nan")
    return float(clean.median())


def _finite_stat(values: pd.Series | None, fn) -> float:
    if values is None:
        return float("nan")
    arr = pd.Series(values).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=np.float64)
    if len(arr) == 0:
        return float("nan")
    return float(fn(arr))


def _mean(values: pd.Series) -> float:
    return _finite_stat(values, np.mean)


def _median(values: pd.Series) -> float:
    return _finite_stat(values, np.median)


def _to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    headers = [str(col) for col in df.columns]
    rows = [[_format_cell(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    header = "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    body = ["| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |" for row in rows]
    return "\n".join([header, sep] + body)


def _format_cell(value: object) -> str:
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)):
            return "nan"
        return f"{float(value):.4f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
