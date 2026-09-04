#!/usr/bin/env python3
"""Create real-data diagnostic figures for persistence churn-guard v3."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_churn_guard_v3"
FIGURES = PAPER / "analysis-output/figures"
LABELS = {
    "a06_s000_d045": "A06 start",
    "a09_6000_6800": "A09",
    "a06_s045_d045": "A06 +45 s",
    "h07_s000_d050": "H07",
}
COLORS = {
    "a06_s000_d045": "#D55E00",
    "a09_6000_6800": "#0072B2",
    "a06_s045_d045": "#009E73",
    "h07_s000_d050": "#777777",
}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def save(fig: plt.Figure, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(FIGURES / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def outcome_figure() -> None:
    rows = read(PAPER / "accuracy.csv")
    windows = list(LABELS)
    x = np.arange(len(windows), dtype=float)
    width = 0.34
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.7), constrained_layout=True)
    for ax, field, title in (
        (axes[0], "fixed_se3_ape_rmse_median_m", "Fixed-scale APE RMSE"),
        (axes[1], "fixed_se3_rpe_rmse_median_m", "1 s RPE RMSE"),
    ):
        klt = [
            float(next(r[field] for r in rows if r["window"] == w and r["arm"] == "klt"))
            for w in windows
        ]
        guarded = [
            float(next(r[field] for r in rows if r["window"] == w and r["arm"] == "churn_guard_v3"))
            for w in windows
        ]
        ax.bar(x - width / 2, klt, width, label="KLT", color="#999999")
        ax.bar(x + width / 2, guarded, width, label="Churn-guard v3", color="#0072B2")
        ax.set_yscale("log")
        ax.set_xticks(x, [LABELS[w] for w in windows], rotation=20, ha="right")
        ax.set_ylabel("metres (log scale)")
        ax.set_title(title)
        ax.grid(axis="y", which="both", alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Frozen-backend outcomes on exact input support", fontsize=11)
    save(fig, "figure01_fixed_se3_outcomes")


def mechanism_figure() -> None:
    rows = read(PAPER / "birth_lifetime_evidence.csv")
    windows = ["a06_s000_d045", "a09_6000_6800", "a06_s045_d045"]
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.6), constrained_layout=True)
    for window in windows:
        group = [r for r in rows if r["window"] == window]
        frame = [int(r["selected_feature_index"]) for r in group]
        ratio = [float(r["gftt_birth_reserve_ratio"]) for r in group]
        mature = [float(r["all_gftt_lifetime_ge10_fraction"]) for r in group]
        axes[0].plot(frame, ratio, marker="o", color=COLORS[window], label=LABELS[window])
        axes[1].plot(frame, mature, marker="o", color=COLORS[window], label=LABELS[window])
    axes[0].axhline(0.10, color="black", linestyle="--", linewidth=1, label="v3 threshold")
    axes[0].set_title("Online birth reserve")
    axes[0].set_ylabel("GFTT births / 350")
    axes[0].set_xlabel("selected frame")
    axes[0].set_ylim(0, 0.34)
    axes[0].grid(alpha=0.25)
    axes[0].legend(frameon=False, fontsize=7)
    axes[1].set_title("Post-hoc mature-birth fraction")
    axes[1].set_ylabel("fraction with lifetime ≥10")
    axes[1].set_xlabel("selected frame")
    axes[1].set_ylim(0, 0.78)
    axes[1].grid(alpha=0.25)

    xpos = np.arange(len(rows))
    victim = [float(r["v2_victim_lifetime_frames"]) for r in rows]
    xfeat = [float(r["v2_xfeat_lifetime_frames"]) for r in rows]
    axes[2].bar(xpos - 0.18, victim, 0.36, color="#D55E00", label="deleted GFTT")
    axes[2].bar(xpos + 0.18, xfeat, 0.36, color="#0072B2", label="v2 XFeat")
    axes[2].set_xticks(
        xpos,
        [f"{LABELS[r['window']]}\nf{r['selected_feature_index']}" for r in rows],
        rotation=55,
        ha="right",
        fontsize=6.5,
    )
    axes[2].set_ylabel("observed lifetime (frames)")
    axes[2].set_title("v2 replacement outcome")
    axes[2].grid(axis="y", alpha=0.25)
    axes[2].legend(frameon=False, fontsize=7)
    save(fig, "figure02_churn_guard_mechanism")


def main() -> int:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
        }
    )
    outcome_figure()
    mechanism_figure()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
