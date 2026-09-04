#!/usr/bin/env python3
"""Generate descriptive figures for the paired MIMIR three-way comparison."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap


METHODS = ("Pure KLT", "Original VINS", "AQUA-FE")
PREFIXES = ("klt", "original", "ours")
COLORS = ("#E69F00", "#56B4E9", "#009E73")
HATCHES = ("///", "...", "xxx")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def save_all(fig: plt.Figure, base: Path) -> None:
    for suffix in ("pdf", "svg"):
        fig.savefig(base.with_suffix(f".{suffix}"), bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def configure() -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "axes.linewidth": 0.8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def plot_counts(rows: list[dict[str, str]], output_dir: Path) -> None:
    trajectories = [sum(int(row[f"{p}_has_trajectory"]) for row in rows) for p in PREFIXES]
    strict = [sum(row.get(f"{p}_init_success") == "1" for row in rows) for p in PREFIXES]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8), sharey=True, constrained_layout=True)
    for ax, values, label in zip(
        axes,
        (trajectories, strict),
        ("Any trajectory", "Strict initialization gate"),
    ):
        bars = ax.bar(
            np.arange(3),
            values,
            color=COLORS,
            edgecolor="black",
            linewidth=0.8,
            width=0.68,
        )
        for bar, hatch, value in zip(bars, HATCHES, values):
            bar.set_hatch(hatch)
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.16, f"{value}/9", ha="center")
        ax.set_xticks(np.arange(3), METHODS, rotation=18, ha="right")
        ax.set_xlabel(label)
        ax.set_ylim(0, 9.8)
        ax.set_yticks(range(0, 10))
        ax.grid(axis="y", alpha=0.25, linewidth=0.7)
    axes[0].set_ylabel("Selected windows (count)")
    save_all(fig, output_dir / "figure-01-main-comparison")


def short_window(row: dict[str, str]) -> str:
    abbreviations = {
        "OceanFloor": "OF",
        "SandPipe": "SP",
        "SeaFloor": "SF",
    }
    environment, track = row["sequence"].split("/", 1)
    track = track.replace("track", "t").replace("_light", "L").replace("_dark", "D")
    return f"{abbreviations.get(environment, environment)} {track} {row['window_start_s']}–{row['window_end_s']} s"


def plot_matrix(rows: list[dict[str, str]], output_dir: Path) -> None:
    # 0 empty, 1 late/partial trajectory, 2 strict pass.
    matrix = np.zeros((len(rows), 3), dtype=int)
    for i, row in enumerate(rows):
        for j, prefix in enumerate(PREFIXES):
            if row.get(f"{prefix}_init_success") == "1":
                matrix[i, j] = 2
            elif row.get(f"{prefix}_has_trajectory") == "1":
                matrix[i, j] = 1
    cmap = ListedColormap(("#D9D9D9", "#F0E442", "#0072B2"))
    fig, ax = plt.subplots(figsize=(5.4, 4.4), constrained_layout=True)
    ax.imshow(matrix, cmap=cmap, vmin=-0.5, vmax=2.5, aspect="auto")
    symbols = ("E", "P", "G")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            ax.text(j, i, symbols[value], ha="center", va="center", color="white" if value == 2 else "black", fontweight="bold")
    ax.set_xticks(np.arange(3), METHODS)
    ax.set_yticks(np.arange(len(rows)), [short_window(row) for row in rows])
    ax.set_xlabel("Frontend arm")
    ax.set_ylabel("Paired 45 s window")
    ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.text(
        0.0,
        -0.13,
        "E = empty, P = trajectory but strict gate failed, G = strict gate passed",
        transform=ax.transAxes,
        fontsize=8,
    )
    save_all(fig, output_dir / "figure-02-window-outcomes")


def plot_shared_ape(rows: list[dict[str, str]], output_dir: Path) -> None:
    shared = [
        row
        for row in rows
        if row.get("original_init_success") == "1" and row.get("ours_init_success") == "1"
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.1), constrained_layout=True)
    metric_pairs = (
        ("se3_ape_rmse_m", "SE(3) APE RMSE (m)"),
        ("rpe_trans_rmse_m", "Translational RPE RMSE (m)"),
    )
    markers = ("o", "s", "^")
    for ax, (metric, ylabel) in zip(axes, metric_pairs):
        for marker, row in zip(markers, shared):
            values = [as_float(row[f"original_{metric}"]), as_float(row[f"ours_{metric}"])]
            label = short_window(row)
            ax.plot([0, 1], values, color="#666666", linewidth=1.2, alpha=0.8)
            ax.scatter(
                [0, 1],
                values,
                c=(COLORS[1], COLORS[2]),
                edgecolor="black",
                linewidth=0.6,
                marker=marker,
                s=40,
                zorder=3,
                label=label,
            )
        ax.set_xticks((0, 1), ("Original VINS", "AQUA-FE"))
        ax.set_yscale("log")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", which="both", alpha=0.25, linewidth=0.7)
    handles, labels = axes[1].get_legend_handles_labels()
    # Each line contributes two identical legend entries; retain one per window.
    unique = {}
    for handle, label in zip(handles, labels):
        unique.setdefault(label, handle)
    fig.legend(
        unique.values(),
        unique.keys(),
        loc="lower center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=3,
        frameon=False,
    )
    save_all(fig, output_dir / "figure-03-shared-pass-errors")


def main() -> int:
    args = parse_args()
    with args.input_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 9:
        raise SystemExit(f"expected 9 rows, got {len(rows)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure()
    plot_counts(rows, args.output_dir)
    plot_matrix(rows, args.output_dir)
    plot_shared_ape(rows, args.output_dir)
    print(f"wrote figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
