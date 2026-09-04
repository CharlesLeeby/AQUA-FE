#!/usr/bin/env python3
"""Build trigger explainability and qualitative example figures from existing logs."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_explainability_qualitative"
LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)

TRIGGER_DIR = ROOT / "logs" / "opt_eval" / "trigger_explainability"

INPUTS = {
    "trigger_modes": TRIGGER_DIR / "long_window_triggers_modes.csv",
    "trigger_causes": TRIGGER_DIR / "long_window_triggers_causes.csv",
    "geometry_modes": TRIGGER_DIR / "long_window_triggers_geometry_modes.csv",
    "top_reasons": TRIGGER_DIR / "long_window_triggers_top_reasons.csv",
    "h07_default": ROOT
    / "logs"
    / "paper_texture_breadth"
    / "aqualoc_h07_lowtex_extreme_1740_1820_full_sp_lg_loftr.csv",
    "h07_churn_gate": ROOT
    / "logs"
    / "paper_texture_churn_gate_v2"
    / "aqualoc_h07_lowtex_extreme_1740_1820_full_sp_lg_loftr.csv",
    "h07_tracks": ROOT
    / "logs"
    / "opt_eval"
    / "source_dropout"
    / "h07_full_tracks_1660_1710.csv",
    "h07_dropout_by_source": ROOT
    / "logs"
    / "opt_eval"
    / "source_dropout"
    / "h07_source_dropout_by_frame.csv",
    "h07_source_metrics": ROOT
    / "logs"
    / "opt_eval"
    / "source_dropout"
    / "h07_full_metrics_1660_1710.csv",
    "a06_klt_control": ROOT
    / "logs"
    / "paper_texture_breadth"
    / "aqualoc_a06_planar_extreme_2280_2360_klt_adaptive_clahe.csv",
    "a06_full_hybrid": ROOT
    / "logs"
    / "paper_texture_breadth"
    / "aqualoc_a06_planar_extreme_2280_2360_full_sp_lg_loftr.csv",
    "a06_loftr_postval": ROOT / "logs" / "postval_eval" / "a06_loftr_postval.csv",
    "a06_semidense_loftr": ROOT
    / "logs"
    / "semidense_eval"
    / "aqualoc_archaeo06_2210_2310_loftr_fallback.csv",
}

CONTINUITY_INPUTS = {
    "AQUALOC-H07": ROOT / "logs" / "opt_eval" / "long_window_v1" / "h07_continuity_1660_1950.csv",
    "AQUALOC-H06": ROOT / "logs" / "opt_eval" / "long_window_v1" / "h06_continuity_2280_2490.csv",
    "AQUALOC-A06": ROOT / "logs" / "opt_eval" / "long_window_v1" / "a06_continuity_2210_2460.csv",
    "AFRL-FL": ROOT / "logs" / "opt_eval" / "long_window_v1" / "afrl_fl_continuity_080_319.csv",
    "AFRL-FR": ROOT / "logs" / "opt_eval" / "long_window_v1" / "afrl_fr_continuity_005_410.csv",
}

AQUALOC_TARS = {
    "harbor_sequence_07": ROOT / "datasets" / "aqualoc" / "samples" / "harbor_sequence_07_raw_data.tar.gz",
    "archaeo_sequence_06": ROOT / "datasets" / "aqualoc" / "samples" / "archaeo_sequence_06_raw_data.tar.gz",
}

DATASET_ORDER = ["AQUALOC-H07", "AQUALOC-H06", "AQUALOC-A06", "AFRL-FL", "AFRL-FR"]

TRACKER_ORDER = [
    "klt",
    "classical_recovery",
    "learned_recovery",
    "learned_initialization",
    "trigger_no_recovery",
]

SCHEDULER_ORDER = [
    "klt",
    "planar_klt",
    "learned_rematch",
    "homography_guided_recovery",
    "loftr_fallback",
]

GEOMETRY_ORDER = ["normal", "degraded_texture", "planar_near_wall", "severe_low_texture"]

CAUSE_RATIO_COLS = [
    "low_track_count_ratio",
    "low_grid_coverage_ratio",
    "low_texture_or_flat_ratio",
    "underwater_visibility_ratio",
    "geometry_degraded_ratio",
    "dropout_ratio",
    "track_health_ratio",
]

CAUSE_LABELS = {
    "low_track_count_ratio": "low track count",
    "low_grid_coverage_ratio": "low grid coverage",
    "low_texture_or_flat_ratio": "low texture / flat",
    "underwater_visibility_ratio": "underwater visibility",
    "geometry_degraded_ratio": "geometry degraded",
    "dropout_ratio": "dropout",
    "track_health_ratio": "track health",
}

MODE_LABELS = {
    "klt": "KLT",
    "classical_recovery": "classical recovery",
    "learned_recovery": "learned recovery",
    "learned_initialization": "learned init",
    "trigger_no_recovery": "trigger/no recovery",
    "planar_klt": "planar KLT",
    "learned_rematch": "learned rematch",
    "homography_guided_recovery": "homography recovery",
    "loftr_fallback": "LoFTR fallback",
    "normal": "normal",
    "degraded_texture": "degraded texture",
    "planar_near_wall": "planar near-wall",
    "severe_low_texture": "severe low texture",
}

TRACKER_COLORS = {
    "klt": "#6b6b6b",
    "classical_recovery": "#8aa678",
    "learned_recovery": "#2f6fa3",
    "learned_initialization": "#c07a2d",
    "trigger_no_recovery": "#b75a5a",
}

SCHEDULER_COLORS = {
    "klt": "#6b6b6b",
    "planar_klt": "#9c9c9c",
    "learned_rematch": "#2f6fa3",
    "homography_guided_recovery": "#8aa678",
    "loftr_fallback": "#7c4d8a",
}

SOURCE_COLORS = {
    "klt": (42, 111, 163),
    "gftt": (110, 110, 110),
    "lk_recovery": (122, 158, 126),
    "xfeat_init": (192, 122, 45),
    "xfeat_recovery": (177, 90, 90),
    "orb_recovery": (130, 105, 170),
}


@dataclass(frozen=True)
class ExampleRecord:
    filename: str
    title: str
    evidence: str
    claim: str


def ensure_inputs() -> None:
    paths = list(INPUTS.values()) + list(CONTINUITY_INPUTS.values()) + list(AQUALOC_TARS.values())
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing input files:\n" + "\n".join(f"- {m}" for m in missing))


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(INPUTS[name])


def save_csv_md(
    df: pd.DataFrame,
    stem: str,
    title: str,
    note: str | None = None,
    md_columns: Iterable[str] | None = None,
) -> None:
    csv_path = OUT_DIR / f"{stem}.csv"
    md_path = OUT_DIR / f"{stem}.md"
    df.to_csv(csv_path, index=False)
    display = df.copy()
    if md_columns is not None:
        display = display[list(md_columns)]
    lines = [f"# {title}", ""]
    if note:
        lines.extend([note, ""])
    if display.empty:
        lines.append("_No rows._")
    else:
        cols = list(display.columns)
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, row in display.iterrows():
            lines.append("| " + " | ".join(format_value(row[col]) for col in cols) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        if abs(float(value)) >= 100:
            return f"{float(value):.1f}"
        if abs(float(value)) >= 10:
            return f"{float(value):.2f}"
        if abs(float(value)) >= 1:
            return f"{float(value):.3f}"
        return f"{float(value):.4f}"
    return str(value)


def pivot_ratios(df: pd.DataFrame, mode_col: str, order: list[str]) -> pd.DataFrame:
    pivot = (
        df.pivot_table(index="dataset", columns=mode_col, values="ratio", aggfunc="sum")
        .reindex(DATASET_ORDER)
        .fillna(0.0)
    )
    for col in order:
        if col not in pivot.columns:
            pivot[col] = 0.0
    return pivot[order]


def build_scheduler_modes() -> pd.DataFrame:
    records = []
    for dataset, path in CONTINUITY_INPUTS.items():
        df = pd.read_csv(path)
        total = len(df)
        counts = df["scheduler_mode"].value_counts(dropna=False)
        for mode, frames in counts.items():
            records.append(
                {
                    "dataset": dataset,
                    "scheduler_mode": str(mode),
                    "frames": int(frames),
                    "ratio": float(frames / total) if total else 0.0,
                    "source_csv": str(path.relative_to(ROOT)),
                }
            )
    return pd.DataFrame(records)


def build_trigger_policy_ratios(trigger_modes: pd.DataFrame, scheduler_modes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in trigger_modes.iterrows():
        rows.append(
            {
                "dataset": row["dataset"],
                "family": "tracker_mode",
                "mode": row["tracker_mode"],
                "mode_label": MODE_LABELS.get(row["tracker_mode"], row["tracker_mode"]),
                "frames": int(row["frames"]),
                "ratio": float(row["ratio"]),
                "source": "long_window_triggers_modes.csv",
            }
        )
    for _, row in scheduler_modes.iterrows():
        rows.append(
            {
                "dataset": row["dataset"],
                "family": "scheduler_mode",
                "mode": row["scheduler_mode"],
                "mode_label": MODE_LABELS.get(row["scheduler_mode"], row["scheduler_mode"]),
                "frames": int(row["frames"]),
                "ratio": float(row["ratio"]),
                "source": row["source_csv"],
            }
        )
    return pd.DataFrame(rows)


def plot_stacked_bar(
    ax: plt.Axes,
    pivot: pd.DataFrame,
    order: list[str],
    colors: dict[str, str],
    title: str,
    ylabel: str = "frame ratio",
) -> None:
    x = np.arange(len(pivot.index))
    bottom = np.zeros(len(pivot.index))
    for mode in order:
        values = pivot[mode].to_numpy(dtype=float)
        ax.bar(
            x,
            values,
            bottom=bottom,
            color=colors.get(mode, "#999999"),
            edgecolor="white",
            linewidth=0.6,
            label=MODE_LABELS.get(mode, mode),
        )
        bottom += values
    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index, rotation=25, ha="right")
    ax.set_ylim(0, 1.0)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def save_trigger_policy_figure(trigger_modes: pd.DataFrame, scheduler_modes: pd.DataFrame) -> None:
    tracker_pivot = pivot_ratios(trigger_modes, "tracker_mode", TRACKER_ORDER)
    scheduler_pivot = pivot_ratios(scheduler_modes, "scheduler_mode", SCHEDULER_ORDER)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.7), sharey=True)
    plot_stacked_bar(
        axes[0],
        tracker_pivot,
        TRACKER_ORDER,
        TRACKER_COLORS,
        "Tracker action selected by gate",
    )
    plot_stacked_bar(
        axes[1],
        scheduler_pivot,
        SCHEDULER_ORDER,
        SCHEDULER_COLORS,
        "Scheduler context / LoFTR fallback",
    )
    handles, labels = [], []
    for ax in axes:
        h, l = ax.get_legend_handles_labels()
        handles.extend(h)
        labels.extend(l)
    unique = dict(zip(labels, handles))
    fig.legend(
        unique.values(),
        unique.keys(),
        loc="upper center",
        bbox_to_anchor=(0.5, 1.11),
        ncol=4,
        frameon=False,
        fontsize=8,
    )
    fig.tight_layout(pad=0.8)
    fig.savefig(OUT_DIR / "fig_trigger_policy_ratios.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def save_cause_heatmap(causes: pd.DataFrame) -> pd.DataFrame:
    matrix = causes.set_index("dataset").reindex(DATASET_ORDER)[CAUSE_RATIO_COLS]
    fig, ax = plt.subplots(figsize=(8.4, 3.9))
    im = ax.imshow(matrix.to_numpy(dtype=float), cmap="YlGnBu", vmin=0, vmax=1.0, aspect="auto")
    ax.set_xticks(np.arange(len(CAUSE_RATIO_COLS)))
    ax.set_xticklabels([CAUSE_LABELS[c] for c in CAUSE_RATIO_COLS], rotation=25, ha="right")
    ax.set_yticks(np.arange(len(matrix.index)))
    ax.set_yticklabels(matrix.index)
    for ridx in range(matrix.shape[0]):
        for cidx in range(matrix.shape[1]):
            value = matrix.iloc[ridx, cidx]
            ax.text(
                cidx,
                ridx,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if value > 0.55 else "#333333",
            )
    ax.set_title("Trigger cause families by dataset", fontsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("ratio")
    fig.tight_layout(pad=0.7)
    fig.savefig(OUT_DIR / "fig_trigger_cause_families.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    long_rows = []
    for dataset, row in matrix.iterrows():
        for col in CAUSE_RATIO_COLS:
            long_rows.append(
                {
                    "dataset": dataset,
                    "cause": col.replace("_ratio", ""),
                    "cause_label": CAUSE_LABELS[col],
                    "ratio": row[col],
                }
            )
    return pd.DataFrame(long_rows)


def save_dataset_mode_difference_figure(trigger_modes: pd.DataFrame, geometry_modes: pd.DataFrame) -> None:
    tracker = pivot_ratios(trigger_modes, "tracker_mode", TRACKER_ORDER)
    geometry = pivot_ratios(geometry_modes, "geometry_mode", GEOMETRY_ORDER)
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.8), sharey=True)
    plot_matrix(
        axes[0],
        tracker,
        [MODE_LABELS[m] for m in TRACKER_ORDER],
        "Tracker modes",
    )
    plot_matrix(
        axes[1],
        geometry,
        [MODE_LABELS[m] for m in GEOMETRY_ORDER],
        "Geometry modes",
    )
    fig.tight_layout(pad=0.8)
    fig.savefig(OUT_DIR / "fig_dataset_trigger_mode_differences.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_matrix(ax: plt.Axes, matrix: pd.DataFrame, col_labels: list[str], title: str) -> None:
    values = matrix.to_numpy(dtype=float)
    ax.imshow(values, cmap="Blues", vmin=0, vmax=max(1e-9, values.max()), aspect="auto")
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=28, ha="right")
    ax.set_yticks(np.arange(len(matrix.index)))
    ax.set_yticklabels(matrix.index)
    ax.set_title(title, fontsize=10)
    for ridx in range(values.shape[0]):
        for cidx in range(values.shape[1]):
            value = values[ridx, cidx]
            ax.text(
                cidx,
                ridx,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if value > 0.45 else "#333333",
            )
    ax.set_xticks(np.arange(-0.5, len(col_labels), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(matrix.index), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.0)
    ax.tick_params(which="minor", bottom=False, left=False)
    for spine in ax.spines.values():
        spine.set_visible(False)


def build_h07_churn_diagnosis(default: pd.DataFrame, churn: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, df in [("default_gate", default), ("churn_gate_probe", churn)]:
        rows.append(
            {
                "variant": label,
                "frames": len(df),
                "klt_mode_ratio": float((df["tracker_mode"] == "klt").mean()),
                "track_identity_churn_reason_ratio": float(
                    (df["tracker_recovery_reason"] == "track_identity_churn").mean()
                ),
                "tracker_healthy_reason_ratio": float((df["tracker_recovery_reason"] == "healthy").mean()),
                "learned_initialization_ratio": float(
                    (df["tracker_mode"] == "learned_initialization").mean()
                ),
                "classical_recovery_ratio": float((df["tracker_mode"] == "classical_recovery").mean()),
                "trigger_no_recovery_ratio": float((df["tracker_mode"] == "trigger_no_recovery").mean()),
                "loftr_gate_rejected_ratio": float(
                    (df.get("semidense_acceptance", pd.Series(index=df.index, dtype=str)) == "loftr_gate_rejected_mode").mean()
                ),
                "median_track_age_median": float(df["median_track_age"].median()),
                "dropout_ratio_median": float(df["dropout_ratio"].median()),
                "grid_coverage_median": float(df["grid_coverage"].median()),
                "epi_error_median": float(df["median_epipolar_error"].median()),
                "runtime_ms_median": float(df["runtime_ms"].median()),
            }
        )
    return pd.DataFrame(rows)


def save_h07_churn_diagnosis_figure(default: pd.DataFrame, churn: pd.DataFrame, diagnosis: pd.DataFrame) -> None:
    frame_window = (1740, 1760)
    d = default[(default["frame_index"] >= frame_window[0]) & (default["frame_index"] <= frame_window[1])]
    c = churn[(churn["frame_index"] >= frame_window[0]) & (churn["frame_index"] <= frame_window[1])]

    fig, axes = plt.subplots(2, 2, figsize=(9.6, 5.4), sharex="col")
    axes[0, 0].plot(d["frame_index"], d["dropout_ratio"], color="#6b6b6b", label="default")
    axes[0, 0].plot(c["frame_index"], c["dropout_ratio"], color="#2f6fa3", label="churn probe")
    axes[0, 0].set_ylabel("dropout ratio")
    axes[0, 0].set_title("H07 low-texture churn window")
    axes[0, 0].legend(frameon=False, fontsize=8)

    axes[1, 0].plot(d["frame_index"], d["median_track_age"], color="#6b6b6b", label="default")
    axes[1, 0].plot(c["frame_index"], c["median_track_age"], color="#2f6fa3", label="churn probe")
    axes[1, 0].set_ylabel("median track age")
    axes[1, 0].set_xlabel("frame")

    categories = [
        "klt_mode_ratio",
        "track_identity_churn_reason_ratio",
        "learned_initialization_ratio",
        "loftr_gate_rejected_ratio",
    ]
    labels = ["KLT mode", "churn reason", "learned init", "LoFTR rejected"]
    x = np.arange(len(categories))
    width = 0.34
    axes[0, 1].bar(
        x - width / 2,
        diagnosis.iloc[0][categories],
        width,
        color="#6b6b6b",
        label="default",
    )
    axes[0, 1].bar(
        x + width / 2,
        diagnosis.iloc[1][categories],
        width,
        color="#2f6fa3",
        label="churn probe",
    )
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(labels, rotation=20, ha="right")
    axes[0, 1].set_ylim(0, 1)
    axes[0, 1].set_ylabel("frame ratio")
    axes[0, 1].set_title("Why the default gate stays conservative")
    axes[0, 1].legend(frameon=False, fontsize=8)

    metrics = ["epi_error_median", "runtime_ms_median"]
    mlabels = ["epi residual", "runtime ms"]
    x2 = np.arange(len(metrics))
    vals0 = diagnosis.iloc[0][metrics].to_numpy(dtype=float)
    vals1 = diagnosis.iloc[1][metrics].to_numpy(dtype=float)
    axes[1, 1].bar(x2 - width / 2, vals0, width, color="#6b6b6b", label="default")
    axes[1, 1].bar(x2 + width / 2, vals1, width, color="#2f6fa3", label="churn probe")
    axes[1, 1].set_xticks(x2)
    axes[1, 1].set_xticklabels(mlabels)
    axes[1, 1].set_title("Tradeoff after enabling churn trigger")
    axes[1, 1].set_yscale("log")

    for ax in axes.ravel():
        ax.grid(axis="y", color="#dddddd", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.8)
    fig.savefig(OUT_DIR / "fig_h07_default_gate_churn_diagnosis.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def image_from_member(frame_name: str) -> Image.Image:
    candidate = ROOT / frame_name
    if candidate.exists():
        return Image.open(candidate).convert("RGB")
    tar_key = None
    if "harbor_images_sequence_07" in frame_name:
        tar_key = "harbor_sequence_07"
    elif "images_sequence_6" in frame_name:
        tar_key = "archaeo_sequence_06"
    if tar_key is None:
        raise FileNotFoundError(f"No image source mapping for {frame_name}")
    tar_path = AQUALOC_TARS[tar_key]
    with tarfile.open(tar_path, "r:gz") as tar:
        member = tar.extractfile(frame_name)
        if member is None:
            raise FileNotFoundError(f"{frame_name} not found in {tar_path}")
        return Image.open(io.BytesIO(member.read())).convert("RGB")


def resize_to_width(image: Image.Image, width: int) -> Image.Image:
    scale = width / image.width
    height = max(1, int(round(image.height * scale)))
    return image.resize((width, height), LANCZOS)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 18, bold: bool = False) -> None:
    x, y = xy
    fnt = font(size, bold)
    if hasattr(draw, "multiline_textbbox"):
        bbox = draw.multiline_textbbox((x, y), text, font=fnt, spacing=3)
    else:
        lines = text.splitlines() or [text]
        widths = []
        heights = []
        for line in lines:
            line_size = draw.textsize(line, font=fnt)
            widths.append(line_size[0])
            heights.append(line_size[1])
        bbox = (x, y, x + max(widths), y + sum(heights) + 3 * max(0, len(lines) - 1))
    pad = 6
    draw.rectangle((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), fill=(255, 255, 255))
    draw.multiline_text((x, y), text, fill=(20, 20, 20), font=fnt, spacing=3)


def draw_grid(draw: ImageDraw.ImageDraw, size: tuple[int, int], cols: int = 6, rows: int = 4) -> None:
    width, height = size
    for c in range(1, cols):
        x = int(round(width * c / cols))
        draw.line((x, 0, x, height), fill=(255, 255, 255), width=1)
        draw.line((x + 1, 0, x + 1, height), fill=(0, 0, 0), width=1)
    for r in range(1, rows):
        y = int(round(height * r / rows))
        draw.line((0, y, width, y), fill=(255, 255, 255), width=1)
        draw.line((0, y + 1, width, y + 1), fill=(0, 0, 0), width=1)


def draw_track_overlay(
    image: Image.Image,
    tracks: pd.DataFrame,
    frame_index: int,
    max_tracks: int = 220,
) -> Image.Image:
    frame_tracks = tracks[tracks["frame_index"] == frame_index].copy()
    if len(frame_tracks) > max_tracks:
        frame_tracks = frame_tracks.sample(max_tracks, random_state=7)
    draw = ImageDraw.Draw(image, "RGBA")
    for _, row in frame_tracks.iterrows():
        source = str(row["source"])
        color = SOURCE_COLORS.get(source, (200, 200, 200))
        rgba = color + (180,)
        px, py, x, y = float(row["prev_x"]), float(row["prev_y"]), float(row["x"]), float(row["y"])
        draw.line((px, py, x, y), fill=rgba, width=2)
        draw.ellipse((x - 2.5, y - 2.5, x + 2.5, y + 2.5), fill=color + (220,))
    return image


def make_canvas(width: int, height: int, color: tuple[int, int, int] = (250, 250, 250)) -> Image.Image:
    return Image.new("RGB", (width, height), color)


def paste_panel(canvas: Image.Image, panel: Image.Image, xy: tuple[int, int]) -> None:
    canvas.paste(panel, xy)


def save_h07_track_break_panel(tracks: pd.DataFrame, dropout: pd.DataFrame, metrics: pd.DataFrame) -> ExampleRecord:
    frame_index = 1706
    frame_name = tracks[tracks["frame_index"] == frame_index]["frame_name"].iloc[0]
    image = image_from_member(frame_name)
    image = draw_track_overlay(image.convert("RGB"), tracks, frame_index)
    panel = resize_to_width(image, 560)
    draw = ImageDraw.Draw(panel, "RGBA")
    row = metrics[metrics["frame_index"] == frame_index].iloc[0]
    drops = dropout[dropout["frame_index"] == frame_index]
    drop_summary = ", ".join(f"{r.source}:{int(r.dropped)}" for r in drops.itertuples())
    draw_label(
        draw,
        (12, 12),
        "H07 KLT track break\n"
        f"frame {frame_index}: dropout={row.dropout_ratio:.2f}, age={row.median_track_age:.0f}\n"
        f"dropped by source: {drop_summary}",
        size=16,
        bold=True,
    )
    legend_x, legend_y = 12, panel.height - 115
    draw.rectangle((legend_x - 6, legend_y - 6, legend_x + 255, legend_y + 95), fill=(255, 255, 255, 230))
    y = legend_y
    for source in ["klt", "gftt", "lk_recovery", "xfeat_init", "xfeat_recovery"]:
        color = SOURCE_COLORS[source]
        draw.rectangle((legend_x, y + 4, legend_x + 18, y + 18), fill=color + (255,))
        draw.text((legend_x + 26, y), source, fill=(20, 20, 20), font=font(14))
        y += 18
    out = OUT_DIR / "qual_h07_klt_track_break.png"
    panel.save(out)
    return ExampleRecord(
        filename=out.name,
        title="H07 KLT track break / identity churn context",
        evidence=f"Frame {frame_index} overlay from h07_full_tracks_1660_1710.csv; dropout={row.dropout_ratio:.2f}.",
        claim="KLT-preserved tracks can still suffer abrupt dropout in the H07 low-texture region, motivating trigger-level diagnostics.",
    )


def save_a06_loftr_supplement_panel(klt: pd.DataFrame, hybrid: pd.DataFrame) -> ExampleRecord:
    frame_index = 2296
    krow = klt[klt["frame_index"] == frame_index].iloc[0]
    hrow = hybrid[hybrid["frame_index"] == frame_index].iloc[0]
    base = image_from_member(hrow["frame_name"])
    left = resize_to_width(base.copy(), 500)
    right = resize_to_width(base.copy(), 500)
    for panel, row, title in [
        (left, krow, "KLT + adaptive CLAHE"),
        (right, hrow, "full hybrid + LoFTR init"),
    ]:
        draw = ImageDraw.Draw(panel, "RGBA")
        draw_grid(draw, panel.size)
        extra = ""
        if int(row.get("loftr_init_tracks", 0)) > 0:
            extra = f"\nLoFTR init={int(row.loftr_init_tracks)}"
        draw_label(
            draw,
            (12, 12),
            f"{title}\n"
            f"features={int(row.num_features)}, grid={int(row.grid_occupied)}/24\n"
            f"coverage={row.grid_coverage:.2f}, epi={row.median_epipolar_error:.3f}{extra}",
            size=16,
            bold=True,
        )
    canvas = make_canvas(left.width + right.width + 30, max(left.height, right.height) + 45)
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 8), f"A06 planar supplement at frame {frame_index}", fill=(20, 20, 20), font=font(20, True))
    paste_panel(canvas, left, (0, 42))
    paste_panel(canvas, right, (left.width + 30, 42))
    out = OUT_DIR / "qual_a06_full_hybrid_loftr_supplement.png"
    canvas.save(out)
    return ExampleRecord(
        filename=out.name,
        title="A06 full hybrid / LoFTR planar supplement",
        evidence=(
            f"At frame {frame_index}, KLT control has {int(krow.grid_occupied)}/24 cells, "
            f"while full hybrid has {int(hrow.grid_occupied)}/24 cells with {int(hrow.loftr_init_tracks)} LoFTR init tracks."
        ),
        claim="LoFTR is used as a sparse planar supplement when KLT coverage is low, improving grid coverage in the A06 planar segment.",
    )


def save_loftr_scope_panel(postval: pd.DataFrame) -> tuple[ExampleRecord, pd.DataFrame]:
    accepted = postval[postval["semidense_acceptance"].astype(str).str.startswith("accepted_loftr_")].copy()
    selected = accepted.sort_values("loftr_init_tracks", ascending=False).head(3)
    if len(selected) < 3:
        selected = accepted.head(3)
    panels = []
    for _, row in selected.iterrows():
        img = resize_to_width(image_from_member(row["frame_name"]), 350)
        draw = ImageDraw.Draw(img, "RGBA")
        draw_grid(draw, img.size)
        draw_label(
            draw,
            (10, 10),
            f"frame {int(row.frame_index)}\n"
            f"{row.scheduler_mode}\n"
            f"{row.geometry_mode}\n"
            f"LoFTR init={int(row.loftr_init_tracks)}",
            size=14,
            bold=True,
        )
        panels.append(img)

    counts = postval["semidense_acceptance"].fillna("n/a").astype(str)
    scope_rows = []
    for label, mask in [
        ("accepted_loftr", counts.str.startswith("accepted_loftr_")),
        ("rejected_low_coverage_gain", counts.str.startswith("rejected_low_coverage_gain")),
        ("rejected_too_few_candidates", counts == "rejected_too_few_candidates"),
        ("rejected_geometry_degradation", counts == "rejected_geometry_degradation"),
        ("loftr_gate_rejected_mode", counts == "loftr_gate_rejected_mode"),
        ("not_triggered", counts == "not_triggered"),
    ]:
        scope_rows.append(
            {
                "category": label,
                "frames": int(mask.sum()),
                "ratio": float(mask.mean()),
            }
        )
    scope = pd.DataFrame(scope_rows)

    bar_w = 360
    bar_h = panels[0].height
    bar = make_canvas(bar_w, bar_h)
    fig, ax = plt.subplots(figsize=(3.5, 2.8))
    plot_scope = scope.sort_values("frames", ascending=True)
    ax.barh(plot_scope["category"], plot_scope["frames"], color="#c07a2d")
    ax.set_xlabel("frames")
    ax.set_title("A06 LoFTR gate outcomes", fontsize=9)
    ax.grid(axis="x", color="#dddddd", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    bar_img = Image.open(buf).convert("RGB")
    bar_img.thumbnail((bar_w, bar_h), LANCZOS)
    bar.paste(bar_img, ((bar_w - bar_img.width) // 2, (bar_h - bar_img.height) // 2))

    gap = 14
    title_h = 42
    canvas = make_canvas(sum(p.width for p in panels) + bar.width + gap * 3, max(p.height for p in panels) + title_h)
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 8), "LoFTR is a gated low-texture supplement, not the default tracker", fill=(20, 20, 20), font=font(18, True))
    x = 0
    for panel in panels:
        paste_panel(canvas, panel, (x, title_h))
        x += panel.width + gap
    paste_panel(canvas, bar, (x, title_h))
    out = OUT_DIR / "qual_loftr_planar_low_texture_gate.png"
    canvas.save(out)
    total_accepted = int(scope[scope["category"] == "accepted_loftr"]["frames"].iloc[0])
    return (
        ExampleRecord(
            filename=out.name,
            title="LoFTR only as planar low-texture supplement",
            evidence=f"postval A06 LoFTR fallback has {total_accepted} accepted-LoFTR frames; other frames are rejected or not triggered.",
            claim="The frontend treats LoFTR as a conditional supplement for planar/low-texture frames rather than a blanket replacement for KLT.",
        ),
        scope,
    )


def save_h07_churn_failure_panel(default: pd.DataFrame, churn: pd.DataFrame) -> ExampleRecord:
    frames = [1741, 1742, 1743]
    panels = []
    for frame_index in frames:
        drow = default[default["frame_index"] == frame_index].iloc[0]
        crow = churn[churn["frame_index"] == frame_index].iloc[0]
        img = resize_to_width(image_from_member(drow["frame_name"]), 360)
        draw = ImageDraw.Draw(img, "RGBA")
        text = (
            f"frame {frame_index}\n"
            f"default: {drow.tracker_mode}/{drow.tracker_recovery_reason}\n"
            f"drop={drow.dropout_ratio:.2f}, age={drow.median_track_age:.0f}\n"
            f"churn probe: {crow.tracker_mode}, rec={int(crow.tracker_recovered_count)}\n"
            f"epi {drow.median_epipolar_error:.3f}->{crow.median_epipolar_error:.3f}"
        )
        draw_label(draw, (10, 10), text, size=13, bold=True)
        panels.append(img)
    gap = 14
    title_h = 42
    canvas = make_canvas(sum(p.width for p in panels) + gap * (len(panels) - 1), max(p.height for p in panels) + title_h)
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 8), "H07 churn failure: default gate stays healthy, churn probe is a tradeoff", fill=(20, 20, 20), font=font(18, True))
    x = 0
    for panel in panels:
        paste_panel(canvas, panel, (x, title_h))
        x += panel.width + gap
    out = OUT_DIR / "qual_h07_churn_failure_case.png"
    canvas.save(out)
    return ExampleRecord(
        filename=out.name,
        title="H07 churn failure case",
        evidence="Frames 1741-1743: default gate labels tracker recovery healthy while dropout is about 0.66-0.69 and age remains 1.",
        claim="H07 extreme low-texture identity churn is a limitation of the default gate; adding a churn trigger helps activity but introduces geometry/runtime tradeoffs.",
    )


def build_loftr_gate_scope() -> pd.DataFrame:
    rows = []
    for label, path in {
        "H07 default breadth": INPUTS["h07_default"],
        "A06 breadth full hybrid": INPUTS["a06_full_hybrid"],
        "A06 postval LoFTR fallback": INPUTS["a06_loftr_postval"],
        "A06 semidense LoFTR fallback": INPUTS["a06_semidense_loftr"],
    }.items():
        df = pd.read_csv(path)
        sem = df.get("semidense_acceptance", pd.Series(index=df.index, dtype=object)).fillna("n/a").astype(str)
        loftr_init = df.get("loftr_init_tracks", pd.Series(0, index=df.index)).fillna(0)
        accepted_mask = sem.str.startswith("accepted_loftr_") | (loftr_init > 0)
        rows.append(
            {
                "case": label,
                "frames": len(df),
                "accepted_loftr_frames": int(accepted_mask.sum()),
                "loftr_gate_rejected_mode_frames": int((sem == "loftr_gate_rejected_mode").sum()),
                "rejected_geometry_degradation_frames": int((sem == "rejected_geometry_degradation").sum()),
                "not_triggered_frames": int((sem == "not_triggered").sum()),
                "accepted_loftr_tracks_total": int(loftr_init.sum()),
                "scheduler_loftr_fallback_ratio": float(
                    (df.get("scheduler_mode", pd.Series(index=df.index, dtype=object)).fillna("") == "loftr_fallback").mean()
                ),
                "source_csv": str(path.relative_to(ROOT)),
            }
        )
    return pd.DataFrame(rows)


def write_source_manifest() -> None:
    rows = []
    for name, path in {**INPUTS, **CONTINUITY_INPUTS, **AQUALOC_TARS}.items():
        rows.append({"name": name, "path": str(path.relative_to(ROOT)), "available": path.exists()})
    pd.DataFrame(rows).to_csv(OUT_DIR / "source_manifest.csv", index=False)


def write_report(
    examples: list[ExampleRecord],
    diagnosis: pd.DataFrame,
    loftr_scope: pd.DataFrame,
    trigger_modes: pd.DataFrame,
    scheduler_modes: pd.DataFrame,
) -> None:
    h07_tracker = trigger_modes[trigger_modes["dataset"] == "AQUALOC-H07"]
    h07_learned = float(h07_tracker[h07_tracker["tracker_mode"] == "learned_recovery"]["ratio"].sum())
    a06_sched = scheduler_modes[scheduler_modes["dataset"] == "AQUALOC-A06"]
    a06_loftr_ratio = float(a06_sched[a06_sched["scheduler_mode"] == "loftr_fallback"]["ratio"].sum())
    h07_default = diagnosis[diagnosis["variant"] == "default_gate"].iloc[0]
    h07_churn = diagnosis[diagnosis["variant"] == "churn_gate_probe"].iloc[0]
    accepted_a06 = int(
        loftr_scope[loftr_scope["case"] == "A06 breadth full hybrid"]["accepted_loftr_tracks_total"].iloc[0]
    )

    lines = [
        "# Explainability And Qualitative Figures",
        "",
        "This package reuses existing CSV logs and a few frames read from local AQUALOC sample tar files. No new experiment was run.",
        "",
        "## Main Explainability Figures",
        "",
        "- `fig_trigger_policy_ratios.png`: tracker action ratios and scheduler context ratios by dataset. It supports the claim that the frontend switches between KLT preservation, classical/learned recovery, and LoFTR fallback according to scene state instead of replacing KLT with one learned matcher.",
        "- `fig_trigger_cause_families.png`: trigger-cause family heatmap. It supports the claim that A06 is dominated by low-texture/underwater degradation, H06 by visibility/low contrast, and AFRL by low coverage plus visibility degradation.",
        "- `fig_dataset_trigger_mode_differences.png`: paired heatmaps for tracker modes and geometry modes. It supports dataset-specific scheduling: H06 stays mostly normal, A06 is severe low texture, and H07 mixes planar near-wall and severe low texture.",
        "- `fig_h07_default_gate_churn_diagnosis.png`: H07 default-vs-churn-probe diagnosis. It supports the limitation statement that the default gate does not fire on identity churn because the active recovery reason remains healthy while LoFTR is rejected by mode.",
        "",
        "## Qualitative Examples",
        "",
    ]
    for ex in examples:
        lines.append(f"- `{ex.filename}`: {ex.claim} Evidence: {ex.evidence}")
    lines.extend(
        [
            "",
            "## Data-Backed Reading Notes",
            "",
            f"- In `AQUALOC-H07`, learned recovery accounts for {h07_learned:.1%} of long-window tracker modes, but the default H07 extreme gate still reports `healthy` tracker recovery on {h07_default['tracker_healthy_reason_ratio']:.1%} of frames.",
            f"- In the long-window A06 continuity log, `loftr_fallback` is the scheduler context on {a06_loftr_ratio:.1%} of frames; this is a context/gate label, not a guarantee that LoFTR points were accepted on every frame.",
            f"- In the A06 breadth full-hybrid example, accepted LoFTR initialization contributes {accepted_a06} sparse points on the selected planar frame.",
            f"- The churn-gate probe detects `track_identity_churn` on {h07_churn['track_identity_churn_reason_ratio']:.1%} of H07 extreme frames, but its median epipolar residual is {h07_churn['epi_error_median']:.4f} versus {h07_default['epi_error_median']:.4f} for the default gate, so it should be presented as a limitation/probe rather than the main default claim.",
            "",
            "## CSV Outputs",
            "",
            "- `trigger_policy_ratios.csv/.md`: combined tracker and scheduler ratios.",
            "- `trigger_cause_family_values.csv/.md`: long-form cause-family heatmap values.",
            "- `h07_default_churn_gate_diagnosis.csv/.md`: default-vs-churn gate diagnosis values.",
            "- `loftr_gate_scope.csv/.md`: LoFTR acceptance/rejection scope across selected existing logs.",
            "- `qualitative_examples_manifest.csv/.md`: file-level claim/evidence map for qualitative figures.",
            "- `source_manifest.csv`: source file inventory.",
            "",
            "## Claim Boundaries",
            "",
            "- Treat `KLT + adaptive CLAHE` and related KLT rows as internal controls, not external baselines.",
            "- Treat `LoFTR fallback` as a gated supplement. Some logs record the scheduler context even when LoFTR points are later rejected by geometry or coverage-gain checks.",
            "- Do not claim the default H07 gate solves identity churn. The generated figures support the opposite: H07 churn remains a documented failure case.",
            "",
        ]
    )
    (OUT_DIR / "explainability_qualitative_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_inputs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    trigger_modes = read_csv("trigger_modes")
    trigger_causes = read_csv("trigger_causes")
    geometry_modes = read_csv("geometry_modes")
    scheduler_modes = build_scheduler_modes()
    policy_ratios = build_trigger_policy_ratios(trigger_modes, scheduler_modes)
    save_csv_md(
        policy_ratios,
        "trigger_policy_ratios",
        "Trigger Policy Ratios",
        "Tracker modes come from long_window_triggers_modes.csv; scheduler modes come from existing long_window_v1 continuity CSVs.",
        ["dataset", "family", "mode_label", "frames", "ratio", "source"],
    )
    save_trigger_policy_figure(trigger_modes, scheduler_modes)

    cause_long = save_cause_heatmap(trigger_causes)
    save_csv_md(
        cause_long,
        "trigger_cause_family_values",
        "Trigger Cause Family Values",
        "Long-form values used by fig_trigger_cause_families.png.",
        ["dataset", "cause_label", "ratio"],
    )

    save_dataset_mode_difference_figure(trigger_modes, geometry_modes)

    default = read_csv("h07_default")
    churn = read_csv("h07_churn_gate")
    diagnosis = build_h07_churn_diagnosis(default, churn)
    save_csv_md(
        diagnosis,
        "h07_default_churn_gate_diagnosis",
        "H07 Default Gate vs Churn-Gate Probe",
        "Churn gate is an experimental probe and is not the default paper method.",
    )
    save_h07_churn_diagnosis_figure(default, churn, diagnosis)

    loftr_scope = build_loftr_gate_scope()
    save_csv_md(
        loftr_scope,
        "loftr_gate_scope",
        "LoFTR Gate Scope",
        "Acceptance/rejection counts from selected existing logs; scheduler fallback context is separate from accepted LoFTR points.",
    )

    tracks = read_csv("h07_tracks")
    dropout = read_csv("h07_dropout_by_source")
    h07_metrics = read_csv("h07_source_metrics")
    a06_klt = read_csv("a06_klt_control")
    a06_hybrid = read_csv("a06_full_hybrid")
    a06_postval = read_csv("a06_loftr_postval")

    examples: list[ExampleRecord] = []
    examples.append(save_h07_track_break_panel(tracks, dropout, h07_metrics))
    examples.append(save_a06_loftr_supplement_panel(a06_klt, a06_hybrid))
    loftr_example, loftr_postval_scope = save_loftr_scope_panel(a06_postval)
    examples.append(loftr_example)
    examples.append(save_h07_churn_failure_panel(default, churn))

    manifest = pd.DataFrame([ex.__dict__ for ex in examples])
    save_csv_md(
        manifest,
        "qualitative_examples_manifest",
        "Qualitative Examples Manifest",
        "Each row maps a generated qualitative PNG to a conservative paper claim.",
    )
    save_csv_md(
        loftr_postval_scope,
        "a06_postval_loftr_acceptance_breakdown",
        "A06 Postval LoFTR Acceptance Breakdown",
        "Detailed breakdown used in qual_loftr_planar_low_texture_gate.png.",
    )

    write_source_manifest()
    write_report(examples, diagnosis, loftr_scope, trigger_modes, scheduler_modes)

    print(f"Wrote explainability/qualitative package to {OUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
