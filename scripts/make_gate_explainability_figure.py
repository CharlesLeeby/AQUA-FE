#!/usr/bin/env python3
"""Create paper-oriented trigger/gate explainability figures.

This script is intentionally read-only with respect to experiment outputs: it
summarizes existing frontend_metrics.csv files and writes compact CSV/figures.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np


@dataclass(frozen=True)
class RunSpec:
    key: str
    label: str
    path: Path
    module: str


RUNS = [
    RunSpec(
        key="a06_loftr_long",
        label="AQUALOC A06\nLoFTR rescue",
        path=Path(
            "logs/aqualoc_archaeo_vins/"
            "external_hybrid_superpoint_lightglue_every2_"
            "jun01_a06_2210_2700_lowparallax_fullblock_vins_loftr/"
            "frontend_metrics.csv"
        ),
        module="LoFTR",
    ),
    RunSpec(
        key="h07_noharm",
        label="AQUALOC H07\nnormal/no-harm",
        path=Path(
            "logs/aqualoc_real_vins/"
            "external_hybrid_superpoint_lightglue_every2_"
            "jun01_h07_formal_v31_lowparallax_fullblock_noharm_loftr/"
            "frontend_metrics.csv"
        ),
        module="SP-LG/LoFTR",
    ),
    RunSpec(
        key="tank_noharm",
        label="Tank wall\nno-harm",
        path=Path(
            "logs/tank_vins/"
            "external_hybrid_superpoint_lightglue_every2_"
            "jun01_tank_lowparallax_fullblock_noharm_loftr/"
            "frontend_metrics.csv"
        ),
        module="SP-LG/LoFTR",
    ),
    RunSpec(
        key="afrl_fr70_xfeat",
        label="AFRL FR70-100\nXFeat sidecar",
        path=Path(
            "logs/afrl_cave_v31/"
            "external_hybrid_xfeat_every2_"
            "jun01_xfeat_covseed_formal_v2_fr70_100_export/"
            "frontend_metrics.csv"
        ),
        module="XFeat",
    ),
    RunSpec(
        key="uvvid_bottom_probe",
        label="UVVID bottom\nfrontend probe",
        path=Path("logs/prepared_new_frontend_probe/uvvid_cannon_bottom_096_175_hybrid_xfeat_loftr.csv"),
        module="LoFTR probe",
    ),
]


def _float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(row: dict[str, str], key: str) -> str:
    return str(row.get(key, "") or "")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _is_degraded(row: dict[str, str]) -> bool:
    if _float(row, "learned_export_gate_degraded") > 0:
        return True
    reason = _str(row, "learned_export_gate_reason")
    if reason and reason not in {"classical_healthy", "not_degraded", "disabled"}:
        return True
    recovery = _str(row, "recovery_reason") or _str(row, "tracker_recovery_reason")
    if recovery and recovery != "healthy":
        return True
    state = _str(row, "frontend_state_reason")
    return bool(state and state != "healthy")


def _has_candidate(row: dict[str, str]) -> bool:
    return (
        _float(row, "learned_candidate_count") > 0
        or _float(row, "semidense_raw_candidates") > 0
        or _float(row, "pre_gate_sidecar_total") > 0
    )


def _has_confirmed_or_accepted(row: dict[str, str]) -> bool:
    acceptance = _str(row, "semidense_acceptance")
    return (
        _float(row, "learned_confirmed_count") > 0
        or _float(row, "semidense_accepted_candidates") > 0
        or acceptance.startswith("accepted")
    )


def _exported(row: dict[str, str]) -> float:
    learned = _float(row, "exported_learned_features")
    by_source = _float(row, "exported_xfeat_features") + _float(row, "exported_loftr_features")
    return learned if learned > 0 else by_source


def _reason_bucket(reason: str) -> str:
    if not reason:
        return "none"
    if "accepted_loftr_support_rescue" in reason:
        return "LoFTR support\naccepted"
    if "accepted_coverage_gain" in reason:
        return "coverage gain\naccepted"
    if "accepted_weak_cell" in reason:
        return "weak-cell\naccepted"
    if "sidecar_observation_budget" in reason:
        return "sidecar\nbudget"
    if "adaptive_mirror_fallback" in reason:
        return "KLT mirror\nfallback"
    if "no_sidecar" in reason:
        return "no sidecar"
    if "requires_new_cells" in reason:
        return "needs new cells"
    if "min_export_count" in reason:
        return "min export\nsupport"
    return reason[:24]


def _semidense_bucket(reason: str) -> str:
    if not reason:
        return "none"
    if reason == "disabled":
        return "disabled"
    if reason == "not_triggered":
        return "not triggered"
    if reason.startswith("accepted"):
        return "accepted"
    if "not_extreme_texture" in reason:
        return "rejected:\nnot extreme"
    if "low_coverage_gain" in reason:
        return "rejected:\nlow gain"
    if "mode" in reason:
        return "rejected:\nmode"
    return "rejected:\nother"


def _top_counter(counter: Counter[str], max_items: int = 5) -> dict[str, int]:
    items = counter.most_common(max_items)
    rest = sum(counter.values()) - sum(v for _, v in items)
    out = dict(items)
    if rest > 0:
        out["other"] = rest
    return out


def summarize_runs(runs: Iterable[RunSpec]) -> tuple[list[dict[str, object]], dict[str, Counter[str]], dict[str, Counter[str]]]:
    summary: list[dict[str, object]] = []
    benefit: dict[str, Counter[str]] = {}
    semidense: dict[str, Counter[str]] = {}
    for spec in runs:
        rows = _read_csv(spec.path)
        benefit_counter: Counter[str] = Counter()
        semidense_counter: Counter[str] = Counter()
        for row in rows:
            benefit_counter[_reason_bucket(_str(row, "learned_export_benefit_reason"))] += 1
            semidense_counter[_semidense_bucket(_str(row, "semidense_acceptance"))] += 1
        exported_total = sum(_exported(row) for row in rows)
        summary.append(
            {
                "key": spec.key,
                "label": spec.label.replace("\n", " "),
                "module": spec.module,
                "frames": len(rows),
                "degraded_frames": sum(1 for row in rows if _is_degraded(row)),
                "candidate_frames": sum(1 for row in rows if _has_candidate(row)),
                "confirmed_or_accepted_frames": sum(1 for row in rows if _has_confirmed_or_accepted(row)),
                "exported_frames": sum(1 for row in rows if _exported(row) > 0),
                "exported_observations": int(exported_total),
                "exported_xfeat_observations": int(sum(_float(row, "exported_xfeat_features") for row in rows)),
                "exported_loftr_observations": int(sum(_float(row, "exported_loftr_features") for row in rows)),
                "learned_candidate_sum": int(sum(_float(row, "learned_candidate_count") for row in rows)),
                "learned_confirmed_sum": int(sum(_float(row, "learned_confirmed_count") for row in rows)),
                "semidense_raw_sum": int(sum(_float(row, "semidense_raw_candidates") for row in rows)),
                "semidense_accepted_sum": int(sum(_float(row, "semidense_accepted_candidates") for row in rows)),
            }
        )
        benefit[spec.key] = _top_counter(benefit_counter)
        semidense[spec.key] = _top_counter(semidense_counter)
    return summary, benefit, semidense


def write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _style_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)


def _stacked_reason_bars(ax, counters: dict[str, Counter[str]], run_keys: list[str], labels: list[str], title: str) -> None:
    all_reasons: list[str] = []
    for key in run_keys:
        for reason in counters[key]:
            if reason not in all_reasons:
                all_reasons.append(reason)
    preferred = [
        "KLT mirror\nfallback",
        "LoFTR support\naccepted",
        "coverage gain\naccepted",
        "weak-cell\naccepted",
        "sidecar\nbudget",
        "rejected:\nnot extreme",
        "accepted",
        "not triggered",
        "disabled",
        "other",
    ]
    all_reasons = [r for r in preferred if r in all_reasons] + [r for r in all_reasons if r not in preferred]
    palette = [
        "#999999",
        "#0072B2",
        "#009E73",
        "#56B4E9",
        "#E69F00",
        "#D55E00",
        "#CC79A7",
        "#BBBBBB",
        "#666666",
        "#F0E442",
    ]
    x = np.arange(len(run_keys))
    bottom = np.zeros(len(run_keys))
    for i, reason in enumerate(all_reasons):
        vals = np.array([counters[key].get(reason, 0) for key in run_keys], dtype=float)
        if np.all(vals == 0):
            continue
        ax.bar(x, vals, bottom=bottom, label=reason, color=palette[i % len(palette)], width=0.72)
        bottom += vals
    ax.set_title(title, fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("Frames")
    _style_axes(ax)
    ax.legend(frameon=False, fontsize=6, ncol=2, loc="upper left", bbox_to_anchor=(0, 1.03))


def make_figure(out_prefix: Path, rows: list[dict[str, object]], benefit: dict[str, Counter[str]], semidense: dict[str, Counter[str]]) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    keys = [str(r["key"]) for r in rows]
    labels = [str(r["label"]) for r in rows]
    short_labels = [label.replace(" ", "\n", 1) for label in labels]

    fig = plt.figure(figsize=(10.5, 7.2), constrained_layout=True)
    gs = fig.add_gridspec(2, 2)
    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])

    x = np.arange(len(rows))
    width = 0.18
    funnel_cols = [
        ("degraded_frames", "degraded", "#D55E00"),
        ("candidate_frames", "candidate", "#E69F00"),
        ("confirmed_or_accepted_frames", "confirmed/accepted", "#56B4E9"),
        ("exported_frames", "exported to VINS", "#009E73"),
    ]
    for i, (col, name, color) in enumerate(funnel_cols):
        vals = [float(r[col]) for r in rows]
        ax0.bar(x + (i - 1.5) * width, vals, width=width, label=name, color=color)
    ax0.set_title("A. Quality-guided sidecar funnel")
    ax0.set_xticks(x)
    ax0.set_xticklabels(short_labels, rotation=25, ha="right")
    ax0.set_ylabel("Frames")
    ax0.legend(frameon=False, fontsize=7)
    _style_axes(ax0)

    xfeat = np.array([float(r["exported_xfeat_observations"]) for r in rows])
    loftr = np.array([float(r["exported_loftr_observations"]) for r in rows])
    other = np.array([float(r["exported_observations"]) for r in rows]) - xfeat - loftr
    ax1.bar(x, xfeat, label="XFeat", color="#009E73")
    ax1.bar(x, loftr, bottom=xfeat, label="LoFTR", color="#0072B2")
    ax1.bar(x, other, bottom=xfeat + loftr, label="other learned", color="#CC79A7")
    for i, total in enumerate(xfeat + loftr + other):
        ax1.text(i, total + max(1.0, total * 0.04), f"{int(total)}", ha="center", va="bottom", fontsize=7)
    ax1.set_title("B. Learned observations actually exported")
    ax1.set_xticks(x)
    ax1.set_xticklabels(short_labels, rotation=25, ha="right")
    ax1.set_ylabel("Observations")
    ax1.legend(frameon=False)
    _style_axes(ax1)

    selected_semidense_keys = [k for k in keys if k in {"a06_loftr_long", "h07_noharm", "tank_noharm", "uvvid_bottom_probe"}]
    selected_semidense_labels = [labels[keys.index(k)] for k in selected_semidense_keys]
    _stacked_reason_bars(
        ax2,
        semidense,
        selected_semidense_keys,
        selected_semidense_labels,
        "C. LoFTR is gated before export",
    )

    selected_benefit_keys = [k for k in keys if k in {"a06_loftr_long", "afrl_fr70_xfeat", "h07_noharm"}]
    selected_benefit_labels = [labels[keys.index(k)] for k in selected_benefit_keys]
    _stacked_reason_bars(
        ax3,
        benefit,
        selected_benefit_keys,
        selected_benefit_labels,
        "D. Export requires measurable frontend benefit",
    )

    for letter, ax in zip("ABCD", [ax0, ax1, ax2, ax3]):
        ax.text(-0.12, 1.07, letter, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top")

    fig.suptitle("Trigger and acceptance behavior of the quality-guided learned sidecar frontend", fontsize=11)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_prefix.with_suffix(".png"), dpi=300)
    fig.savefig(out_prefix.with_suffix(".pdf"))
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("logs/paper_figures_jun01"))
    args = parser.parse_args()

    missing = [str(spec.path) for spec in RUNS if not spec.path.exists()]
    if missing:
        raise FileNotFoundError("Missing required metrics files:\n" + "\n".join(missing))

    rows, benefit, semidense = summarize_runs(RUNS)
    out_csv = args.out_dir / "jun01_gate_explainability_summary.csv"
    write_summary_csv(out_csv, rows)
    make_figure(args.out_dir / "jun01_gate_explainability", rows, benefit, semidense)

    print(f"wrote {out_csv}")
    print(f"wrote {args.out_dir / 'jun01_gate_explainability.png'}")
    print(f"wrote {args.out_dir / 'jun01_gate_explainability.pdf'}")
    for row in rows:
        print(
            f"{row['key']}: frames={row['frames']} degraded={row['degraded_frames']} "
            f"candidates={row['candidate_frames']} accepted={row['confirmed_or_accepted_frames']} "
            f"export_frames={row['exported_frames']} export_obs={row['exported_observations']}"
        )


if __name__ == "__main__":
    main()
