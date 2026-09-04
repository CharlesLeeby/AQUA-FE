#!/usr/bin/env python3
"""Plot the current submission evidence ledger.

The figure intentionally separates two claims:
1. learned sidecars can help in degraded windows;
2. the scheduler does not harm normal/no-target windows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("logs/jun01_submission_evidence_ledger.csv")
DEFAULT_OUT_DIR = Path("logs/paper_figures_jun01")

COLORS = {
    "LoFTR": "#2F6FA3",
    "XFeat": "#C47A35",
    "no_harm": "#5A8F69",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--stem", default="jun01_submission_evidence_overview")
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fig = make_figure(df)
    png = args.out_dir / f"{args.stem}.png"
    pdf = args.out_dir / f"{args.stem}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)

    summary_csv = args.out_dir / f"{args.stem}_summary.csv"
    make_summary(df).to_csv(summary_csv, index=False)
    print(f"wrote {png}")
    print(f"wrote {pdf}")
    print(f"wrote {summary_csv}")
    return 0


def make_figure(df: pd.DataFrame) -> plt.Figure:
    positive = df[df["evidence_type"] == "positive"].copy()
    no_harm = df[df["evidence_type"] == "no_harm"].copy()

    positive = positive[~positive["module"].str.contains("constant backend quality", na=False)]
    positive["plot_label"] = positive.apply(_positive_label, axis=1)
    positive["module_family"] = positive["module"].map(_module_family)
    positive = positive.sort_values(
        ["module_family", "ape_gain_pct", "window"], ascending=[True, True, True]
    )

    no_harm["plot_label"] = no_harm.apply(_no_harm_label, axis=1)
    no_harm = no_harm.sort_values("ape_gain_pct")

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(12.8, 5.8),
        gridspec_kw={"width_ratios": [1.45, 1.0]},
    )
    fig.patch.set_facecolor("white")
    _plot_positive(axes[0], positive)
    _plot_no_harm(axes[1], no_harm)
    fig.suptitle(
        "Quality-guided learned sidecars: positive degraded-window gains and no-harm controls",
        fontsize=14,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def _plot_positive(ax: plt.Axes, df: pd.DataFrame) -> None:
    y = np.arange(len(df))
    colors = [COLORS.get(family, "#777777") for family in df["module_family"]]
    ax.barh(y, df["ape_gain_pct"], color=colors, edgecolor="white", linewidth=1.0)
    ax.set_yticks(y)
    ax.set_yticklabels(df["plot_label"], fontsize=9)
    ax.set_xlabel("APE reduction vs matched control (%)")
    ax.set_title("Degraded-window positive evidence", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(80, float(df["ape_gain_pct"].max()) * 1.12))
    for ypos, value, module in zip(y, df["ape_gain_pct"], df["module_family"]):
        ax.text(
            float(value) + 1.0,
            ypos,
            f"{value:.1f}% {module}",
            va="center",
            fontsize=8.5,
            color="#333333",
        )
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)


def _plot_no_harm(ax: plt.Axes, df: pd.DataFrame) -> None:
    y = np.arange(len(df))
    ax.axvspan(-1.0, 1.0, color="#EAF4EC", zorder=0)
    colors = [COLORS["no_harm"] if value >= 0 else "#7C7C7C" for value in df["ape_gain_pct"]]
    ax.barh(y, df["ape_gain_pct"], color=colors, edgecolor="white", linewidth=1.0)
    ax.axvline(0.0, color="#333333", linewidth=0.8)
    ax.axvline(-1.0, color="#8BBF9A", linewidth=0.8, linestyle="--")
    ax.axvline(1.0, color="#8BBF9A", linewidth=0.8, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels(df["plot_label"], fontsize=9)
    ax.set_xlabel("APE reduction vs KLT/control (%)")
    ax.set_title("Normal/no-target no-harm controls", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)
    limit = max(1.2, float(np.nanmax(np.abs(df["ape_gain_pct"]))) * 1.4)
    ax.set_xlim(-limit, limit)
    for ypos, value in zip(y, df["ape_gain_pct"]):
        align = "left" if value >= 0 else "right"
        offset = 0.04 * limit if value >= 0 else -0.04 * limit
        ax.text(
            float(value) + offset,
            ypos,
            f"{value:+.2f}%",
            va="center",
            ha=align,
            fontsize=8.5,
            color="#333333",
        )
    ax.text(
        0.5,
        -0.16,
        "green band: +/-1% replay-scale no-harm region",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=8.5,
        color="#555555",
    )
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)


def make_summary(df: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "evidence_type",
        "dataset",
        "window",
        "module",
        "comparison",
        "baseline_ape",
        "method_ape",
        "ape_gain_pct",
        "backend_learned_or_loftr",
        "artifact",
    ]
    return df[keep].copy()


def _module_family(module: str) -> str:
    text = str(module)
    if "XFeat" in text:
        return "XFeat"
    if "LoFTR" in text:
        return "LoFTR"
    return "Other"


def _positive_label(row: pd.Series) -> str:
    dataset = str(row["dataset"])
    window = str(row["window"])
    if dataset == "AQUALOC":
        return window.replace("Archaeology06 ", "A06 ")
    if dataset == "AFRL":
        return window.replace("cemetery ", "AFRL ")
    return f"{dataset} {window}"


def _no_harm_label(row: pd.Series) -> str:
    dataset = str(row["dataset"])
    window = str(row["window"])
    if dataset == "AQUALOC":
        return window.replace("Harbor07 ", "H07 ").replace("Archaeology08 ", "A08 ")
    return f"{dataset} {window}".replace("short_test normal sequence", "short_test")


if __name__ == "__main__":
    raise SystemExit(main())
