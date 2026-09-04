#!/usr/bin/env python3
"""Build cross-domain GT-free lineage persistence and churn diagnostics."""

from __future__ import annotations

import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rosbag


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "papers/persistence_churn_diagnostic.csv"
OUTPUT_PNG = ROOT / "papers/persistence_churn_diagnostic.png"
OUTPUT_PDF = ROOT / "papers/persistence_churn_diagnostic.pdf"
FEATURE_TOPIC = "/feature_tracker/feature"
LEARNED_SOURCE_CODES = {10, 20, 30}

RUNS = (
    (
        "AQUALOC",
        "A07_10800_11200",
        ROOT
        / "logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a07_10800_11200_degraded_mature_dense_lineage/features.bag",
    ),
    (
        "NTNU",
        "fjord1_s83_d30",
        ROOT
        / "logs/ntnu_vins/external_hybrid_xfeat_every2_validation_20260804_ntnu_fjord1_s83_d30_xfeat_historical_profile_nativeq/features.bag",
    ),
    (
        "CIRS",
        "cala_viuda_s575_d30",
        ROOT
        / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jul14frozen3way_cirs_s575_d30_cirs_mirror_densecap/features.bag",
    ),
)


def channel_values(message, name: str, count: int, default: float) -> list[float]:
    matches = [list(channel.values) for channel in message.channels if channel.name == name]
    if len(matches) > 1:
        raise ValueError(f"duplicate {name} channel")
    if not matches:
        return [default] * count
    if len(matches[0]) != count:
        raise ValueError(f"{name} channel length mismatch")
    return matches[0]


def exact_id(value: float) -> int:
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or number < 0:
        raise ValueError(f"invalid feature ID {value}")
    return int(number)


def scan_bag(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    frames_by_id: dict[int, set[int]] = defaultdict(set)
    first_marker: dict[int, bool] = {}
    late_marker_ids: set[int] = set()
    active_counts: list[int] = []
    frame_count = 0
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, message, _stamp in bag.read_messages(topics=[FEATURE_TOPIC]):
            count = len(message.points)
            ids = [exact_id(value) for value in channel_values(message, "id", count, -1.0)]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate feature ID within a frame")
            sources = [
                int(round(float(value)))
                for value in channel_values(message, "source_code", count, 0.0)
            ]
            learned = [
                int(round(float(value)))
                for value in channel_values(message, "is_learned", count, 0.0)
            ]
            active_counts.append(count)
            for feature_id, source, marker in zip(ids, sources, learned):
                is_marker = bool(marker or source in LEARNED_SOURCE_CODES)
                if feature_id not in first_marker:
                    first_marker[feature_id] = is_marker
                elif is_marker and not first_marker[feature_id]:
                    late_marker_ids.add(feature_id)
                frames_by_id[feature_id].add(frame_count)
            frame_count += 1
    if frame_count == 0 or not frames_by_id:
        raise ValueError(f"no feature observations in {path}")

    births: Counter[int] = Counter()
    deaths: Counter[int] = Counter()
    for frames in frames_by_id.values():
        births[min(frames)] += 1
        deaths[max(frames)] += 1
    return {
        "frame_count": frame_count,
        "frames_by_id": frames_by_id,
        "first_marker": first_marker,
        "late_marker_ids": late_marker_ids,
        "active_counts": active_counts,
        "births": births,
        "deaths": deaths,
    }


def percentile(values: list[int], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q, method="linear"))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def summarize(
    domain: str, window: str, path: Path, scan: dict[str, object], category: str
) -> dict[str, object]:
    learned_category = category == "learned_born_anchor"
    frames_by_id = scan["frames_by_id"]
    first_marker = scan["first_marker"]
    selected = [
        feature_id
        for feature_id in frames_by_id
        if bool(first_marker[feature_id]) == learned_category
    ]
    lifetimes = [len(frames_by_id[feature_id]) for feature_id in selected]
    if not lifetimes:
        return {
            "domain": domain,
            "window": window,
            "lineage_class": category,
            "track_count": 0,
            "lifetime_median_frames": "",
            "lifetime_p25_frames": "",
            "lifetime_p75_frames": "",
            "lifetime_p90_frames": "",
            "lifetime_max_frames": "",
            "short_lived_le2_fraction": "",
            "births_per_frame": 0.0,
            "deaths_per_frame": 0.0,
            "mean_active_observations": statistics.mean(scan["active_counts"]),
            "normalized_churn_index": "",
            "late_marker_id_count": len(scan["late_marker_ids"]),
            "source_bag": display_path(path),
        }
    selected_set = set(selected)
    frames = int(scan["frame_count"])
    births = sum(
        1 for feature_id in selected_set if min(frames_by_id[feature_id]) > 0
    )
    deaths = sum(
        1 for feature_id in selected_set if max(frames_by_id[feature_id]) < frames - 1
    )
    mean_active = statistics.mean(scan["active_counts"])
    normalized_churn = (births + deaths) / (2.0 * frames * mean_active)
    return {
        "domain": domain,
        "window": window,
        "lineage_class": category,
        "track_count": len(lifetimes),
        "lifetime_median_frames": statistics.median(lifetimes),
        "lifetime_p25_frames": percentile(lifetimes, 25),
        "lifetime_p75_frames": percentile(lifetimes, 75),
        "lifetime_p90_frames": percentile(lifetimes, 90),
        "lifetime_max_frames": max(lifetimes),
        "short_lived_le2_fraction": sum(value <= 2 for value in lifetimes) / len(lifetimes),
        "births_per_frame": births / frames,
        "deaths_per_frame": deaths / frames,
        "mean_active_observations": mean_active,
        "normalized_churn_index": normalized_churn,
        "late_marker_id_count": len(scan["late_marker_ids"]),
        "source_bag": display_path(path),
    }


def write_summary(rows: list[dict[str, object]]) -> None:
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ecdf(values: list[int]) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(np.asarray(values, dtype=float))
    y = np.arange(1, len(x) + 1, dtype=float) / len(x)
    return x, y


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "axes.linewidth": 0.7,
            "lines.linewidth": 1.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def make_figure(scans: dict[str, dict[str, object]]) -> None:
    configure_style()
    colors = {"AQUALOC": "#0072B2", "NTNU": "#D55E00", "CIRS": "#009E73"}
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.8), constrained_layout=True)

    ax = axes[0]
    for domain, scan in scans.items():
        for category, linestyle in ((False, "-"), (True, "--")):
            values = [
                len(scan["frames_by_id"][feature_id])
                for feature_id in scan["frames_by_id"]
                if bool(scan["first_marker"][feature_id]) == category
            ]
            if not values:
                continue
            x, y = ecdf(values)
            label = f"{domain} {'anchor' if category else 'KLT'}"
            ax.step(x, y, where="post", color=colors[domain], linestyle=linestyle, label=label)
    ax.set_xscale("log")
    ax.set_xlabel("Observed lineage lifetime (feature frames)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.5)
    ax.legend(frameon=False, ncol=2, handlelength=2.5, columnspacing=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(-0.14, 1.04, "A", transform=ax.transAxes, fontweight="bold", fontsize=10)

    ax = axes[1]
    positions = np.arange(len(scans), dtype=float)
    rng = np.random.default_rng(20260806)
    for index, (domain, scan) in enumerate(scans.items()):
        for offset, learned, marker, face in (
            (-0.16, False, "o", "white"),
            (0.16, True, "s", colors[domain]),
        ):
            values = np.asarray(
                [
                    len(scan["frames_by_id"][feature_id])
                    for feature_id in scan["frames_by_id"]
                    if bool(scan["first_marker"][feature_id]) == learned
                ],
                dtype=float,
            )
            if values.size == 0:
                continue
            q25, median, q75 = np.percentile(values, [25, 50, 75])
            x = positions[index] + offset
            ax.vlines(x, q25, q75, color=colors[domain], linewidth=2.2, zorder=2)
            ax.scatter(
                [x],
                [median],
                marker=marker,
                s=28,
                facecolor=face,
                edgecolor=colors[domain],
                linewidth=1.0,
                zorder=3,
            )
            if learned:
                jitter = rng.uniform(-0.045, 0.045, size=values.size)
                ax.scatter(
                    x + jitter,
                    values,
                    marker="|",
                    s=24,
                    color="#222222",
                    linewidth=0.8,
                    zorder=4,
                )
    ax.set_yscale("log")
    ax.set_xticks(positions, list(scans))
    ax.set_ylabel("Lineage lifetime (feature frames)")
    ax.set_xlabel("Data domain")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.scatter([], [], marker="o", facecolor="white", edgecolor="#333333", label="KLT median [IQR]")
    ax.scatter([], [], marker="s", facecolor="#777777", edgecolor="#333333", label="Anchor median [IQR]")
    ax.scatter([], [], marker="|", color="#222222", label="Individual anchors")
    ax.legend(frameon=False, loc="upper right")
    ax.text(-0.14, 1.04, "B", transform=ax.transAxes, fontweight="bold", fontsize=10)

    fig.savefig(OUTPUT_PDF, bbox_inches="tight")
    fig.savefig(OUTPUT_PNG, dpi=600, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    rows: list[dict[str, object]] = []
    scans: dict[str, dict[str, object]] = {}
    for domain, window, path in RUNS:
        scan = scan_bag(path)
        scans[domain] = scan
        for category in ("klt_born", "learned_born_anchor"):
            rows.append(summarize(domain, window, path, scan, category))
    write_summary(rows)
    make_figure(scans)
    print(f"PERSISTENCE_CHURN_COMPLETE rows={len(rows)}")
    print(f"summary={OUTPUT_CSV.relative_to(ROOT)}")
    print(f"figure={OUTPUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
