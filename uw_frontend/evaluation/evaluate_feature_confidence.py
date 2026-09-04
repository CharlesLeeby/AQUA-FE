from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TrackLogSpec:
    label: str
    csv_path: Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether per-feature q_i and sigma_i predict backend-useful "
            "track reliability: next-frame survival, geometric residual, and track length."
        )
    )
    parser.add_argument("--track-log", action="append", type=_parse_spec, required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--min-frame-tracks", type=int, default=12)
    parser.add_argument("--f-threshold", type=float, default=1.0)
    parser.add_argument("--h-threshold", type=float, default=3.0)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    summaries = []
    bins = []
    point_tables = []
    for spec in args.track_log:
        df = pd.read_csv(spec.csv_path)
        point_table = _make_point_table(
            spec.label,
            df,
            min_frame_tracks=args.min_frame_tracks,
            f_threshold=args.f_threshold,
            h_threshold=args.h_threshold,
        )
        point_tables.append(point_table)
        bin_table = _bin_points(spec.label, point_table, args.bins)
        bins.append(bin_table)
        summaries.append(_summarize(spec.label, point_table, bin_table))

    summary_df = pd.DataFrame(summaries)
    bin_df = pd.concat(bins, ignore_index=True) if bins else pd.DataFrame()
    point_df = pd.concat(point_tables, ignore_index=True) if point_tables else pd.DataFrame()

    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    summary_csv = output_prefix.with_name(output_prefix.name + "_summary.csv")
    bins_csv = output_prefix.with_name(output_prefix.name + "_bins.csv")
    points_csv = output_prefix.with_name(output_prefix.name + "_points.csv")
    report_md = output_prefix.with_name(output_prefix.name + "_report.md")
    summary_df.to_csv(summary_csv, index=False)
    bin_df.to_csv(bins_csv, index=False)
    point_df.to_csv(points_csv, index=False)
    report_md.write_text(_make_report(summary_df, bin_df), encoding="utf-8")
    if args.plot:
        _write_plot(bin_df, output_prefix.with_name(output_prefix.name + "_bins.png"))
    print(summary_df.to_string(index=False))
    print(f"wrote {summary_csv}")
    print(f"wrote {bins_csv}")
    print(f"wrote {points_csv}")
    print(f"wrote {report_md}")
    return 0


def _parse_spec(raw: str) -> TrackLogSpec:
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("track-log spec must be label:path.csv")
    return TrackLogSpec(parts[0], Path(parts[1]))


def _make_point_table(
    label: str,
    df: pd.DataFrame,
    min_frame_tracks: int,
    f_threshold: float,
    h_threshold: float,
) -> pd.DataFrame:
    required = {
        "frame_index",
        "track_id",
        "prev_x",
        "prev_y",
        "x",
        "y",
        "age",
        "quality",
        "visual_sigma",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"track log is missing columns: {sorted(missing)}")
    df = df.copy()
    df["method"] = label
    df = df.sort_values(["frame_index", "track_id"]).reset_index(drop=True)
    next_survived = _next_survival(df)
    track_lengths = df.groupby("track_id")["frame_index"].transform("count").astype(np.float32)
    final_age = df.groupby("track_id")["age"].transform("max").astype(np.float32)
    future_length = _future_observations(df)

    geom_rows = []
    for frame_index, group in df.groupby("frame_index", sort=True):
        if len(group) < min_frame_tracks:
            continue
        pts0 = group[["prev_x", "prev_y"]].to_numpy(dtype=np.float32)
        pts1 = group[["x", "y"]].to_numpy(dtype=np.float32)
        geom = _frame_geometry(pts0, pts1, f_threshold=f_threshold, h_threshold=h_threshold)
        if geom is None:
            continue
        frame_rows = pd.DataFrame(
            {
                "row_index": group.index.to_numpy(dtype=np.int64),
                "f_inlier": geom["f_inlier"].astype(np.float32),
                "h_inlier": geom["h_inlier"].astype(np.float32),
                "epipolar_error": geom["epipolar_error"].astype(np.float32),
                "homography_error": geom["homography_error"].astype(np.float32),
            }
        )
        geom_rows.append(frame_rows)
    if geom_rows:
        geom_df = pd.concat(geom_rows, ignore_index=True).set_index("row_index")
    else:
        geom_df = pd.DataFrame(
            columns=["f_inlier", "h_inlier", "epipolar_error", "homography_error"]
        )

    out = pd.DataFrame(
        {
            "method": label,
            "frame_index": df["frame_index"].astype(int),
            "track_id": df["track_id"].astype(int),
            "source": df["source"].astype(str) if "source" in df else "unknown",
            "quality": np.clip(df["quality"].to_numpy(dtype=np.float32), 0.0, 1.0),
            "visual_sigma": df["visual_sigma"].to_numpy(dtype=np.float32),
            "age": df["age"].to_numpy(dtype=np.float32),
            "next_survived": next_survived.astype(np.float32),
            "track_observations": track_lengths.to_numpy(dtype=np.float32),
            "final_track_age": final_age.to_numpy(dtype=np.float32),
            "future_observations": future_length.astype(np.float32),
        },
        index=df.index,
    )
    for col in ["f_inlier", "h_inlier", "epipolar_error", "homography_error"]:
        out[col] = geom_df[col] if col in geom_df else np.nan
    return out.reset_index(drop=True)


def _next_survival(df: pd.DataFrame) -> np.ndarray:
    frames = list(df["frame_index"].drop_duplicates())
    next_frame = {int(a): int(b) for a, b in zip(frames[:-1], frames[1:])}
    ids_by_frame = {
        int(frame): set(int(track_id) for track_id in group["track_id"])
        for frame, group in df.groupby("frame_index")
    }
    survived = []
    for frame, track_id in zip(df["frame_index"], df["track_id"]):
        nf = next_frame.get(int(frame))
        survived.append(1.0 if nf is not None and int(track_id) in ids_by_frame.get(nf, set()) else 0.0)
    return np.asarray(survived, dtype=np.float32)


def _future_observations(df: pd.DataFrame) -> np.ndarray:
    future = np.zeros((len(df),), dtype=np.float32)
    for _, group in df.groupby("track_id", sort=False):
        order = group.sort_values("frame_index").index.to_numpy()
        counts = np.arange(len(order), 0, -1, dtype=np.float32)
        future[order] = counts
    return future


def _frame_geometry(
    pts0: np.ndarray,
    pts1: np.ndarray,
    f_threshold: float,
    h_threshold: float,
) -> dict[str, np.ndarray] | None:
    if len(pts0) < 8 or len(pts1) < 8:
        return None
    f_mat, f_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        method=cv2.FM_RANSAC,
        ransacReprojThreshold=float(f_threshold),
        confidence=0.99,
    )
    h_mat, h_mask = cv2.findHomography(pts0, pts1, cv2.RANSAC, float(h_threshold))
    if _valid_matrix(f_mat):
        f_inlier = f_mask.reshape(-1).astype(bool) if f_mask is not None else np.zeros((len(pts0),), dtype=bool)
        epi = _epipolar_errors(f_mat, pts0, pts1)
    else:
        f_inlier = np.zeros((len(pts0),), dtype=bool)
        epi = np.full((len(pts0),), np.nan, dtype=np.float32)
    if _valid_matrix(h_mat):
        h_inlier = h_mask.reshape(-1).astype(bool) if h_mask is not None else np.zeros((len(pts0),), dtype=bool)
        hom = _homography_errors(h_mat, pts0, pts1)
    else:
        h_inlier = np.zeros((len(pts0),), dtype=bool)
        hom = np.full((len(pts0),), np.nan, dtype=np.float32)
    return {
        "f_inlier": f_inlier,
        "h_inlier": h_inlier,
        "epipolar_error": epi,
        "homography_error": hom,
    }


def _epipolar_errors(f_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    p0 = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    p1 = np.concatenate([pts1, np.ones((len(pts1), 1), dtype=np.float32)], axis=1)
    lines1 = (f_mat @ p0.T).T
    numer = np.abs(np.sum(p1 * lines1, axis=1))
    denom = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2) + 1e-6
    return (numer / denom).astype(np.float32)


def _homography_errors(h_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    pts0_h = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    warped = (h_mat @ pts0_h.T).T
    warped = warped[:, :2] / (warped[:, 2:3] + 1e-6)
    return np.linalg.norm(warped - pts1, axis=1).astype(np.float32)


def _valid_matrix(mat: np.ndarray | None) -> bool:
    return mat is not None and np.asarray(mat).shape == (3, 3)


def _bin_points(label: str, points: pd.DataFrame, bins: int) -> pd.DataFrame:
    rows = []
    if points.empty:
        return pd.DataFrame()
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (points["quality"] >= lo) & (
            points["quality"] < hi if hi < 1.0 else points["quality"] <= hi
        )
        group = points[mask]
        if group.empty:
            continue
        rows.append(
            {
                "method": label,
                "q_bin": f"{lo:.1f}-{hi:.1f}",
                "count": int(len(group)),
                "q_mean": float(group["quality"].mean()),
                "sigma_median": float(group["visual_sigma"].median()),
                "next_survival_rate": float(group["next_survived"].mean()),
                "future_observations_median": float(group["future_observations"].median()),
                "final_track_age_median": float(group["final_track_age"].median()),
                "f_inlier_rate": float(group["f_inlier"].mean()),
                "h_inlier_rate": float(group["h_inlier"].mean()),
                "epipolar_median": float(group["epipolar_error"].median()),
                "homography_median": float(group["homography_error"].median()),
            }
        )
    return pd.DataFrame(rows)


def _summarize(label: str, points: pd.DataFrame, bins: pd.DataFrame) -> dict:
    top = bins.sort_values("q_mean").tail(1)
    bottom = bins.sort_values("q_mean").head(1)
    return {
        "method": label,
        "points": int(len(points)),
        "tracks": int(points["track_id"].nunique()) if "track_id" in points else 0,
        "q_median": float(points["quality"].median()),
        "sigma_median": float(points["visual_sigma"].median()),
        "next_survival_mean": float(points["next_survived"].mean()),
        "future_observations_median": float(points["future_observations"].median()),
        "f_inlier_mean": float(points["f_inlier"].mean()),
        "h_inlier_mean": float(points["h_inlier"].mean()),
        "epipolar_median": float(points["epipolar_error"].median()),
        "q_vs_next_survival_spearman": _spearman(points["quality"], points["next_survived"]),
        "q_vs_future_observations_spearman": _spearman(points["quality"], points["future_observations"]),
        "q_vs_final_track_age_spearman": _spearman(points["quality"], points["final_track_age"]),
        "q_vs_epipolar_spearman": _spearman(points["quality"], points["epipolar_error"]),
        "sigma_vs_next_survival_spearman": _spearman(points["visual_sigma"], points["next_survived"]),
        "sigma_vs_epipolar_spearman": _spearman(points["visual_sigma"], points["epipolar_error"]),
        "top_minus_bottom_survival": _delta(top, bottom, "next_survival_rate"),
        "top_minus_bottom_future_obs": _delta(top, bottom, "future_observations_median"),
        "bottom_minus_top_epipolar": _delta(bottom, top, "epipolar_median"),
    }


def _spearman(a: pd.Series, b: pd.Series) -> float:
    df = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 3:
        return float("nan")
    if float(df["a"].std()) < 1e-9 or float(df["b"].std()) < 1e-9:
        return float("nan")
    return float(df["a"].corr(df["b"], method="spearman"))


def _delta(a: pd.DataFrame, b: pd.DataFrame, col: str) -> float:
    if a.empty or b.empty or col not in a or col not in b:
        return float("nan")
    return float(a.iloc[0][col] - b.iloc[0][col])


def _make_report(summary: pd.DataFrame, bins: pd.DataFrame) -> str:
    lines = ["# Feature Confidence Reliability", ""]
    lines.append(
        "A useful q_i should increase with next-frame survival and realized track length, "
        "while decreasing with epipolar residual. Since sigma_i = sigma_base / sqrt(q_i + eps), "
        "sigma_i should show the opposite trend."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append(_to_markdown(summary))
    lines.append("")
    lines.append("## Quality Bins")
    lines.append(_to_markdown(bins))
    return "\n".join(lines) + "\n"


def _write_plot(bins: pd.DataFrame, output_path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"skip plot: {exc}")
        return
    if bins.empty:
        return
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    for method, group in bins.groupby("method"):
        group = group.sort_values("q_mean")
        axes[0].plot(group["q_mean"], group["next_survival_rate"], marker="o", label=method)
        axes[1].plot(group["q_mean"], group["epipolar_median"], marker="o", label=method)
        axes[2].plot(group["q_mean"], group["future_observations_median"], marker="o", label=method)
    axes[0].set_title("q vs next survival")
    axes[1].set_title("q vs epipolar residual")
    axes[2].set_title("q vs future track length")
    for ax in axes:
        ax.set_xlabel("q_i bin mean")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("survival rate")
    axes[1].set_ylabel("median residual")
    axes[2].set_ylabel("median observations")
    axes[0].legend(fontsize=7)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    print(f"wrote {output_path}")


def _to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    headers = [str(col) for col in df.columns]
    rows = [[_fmt(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    header = "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers)) ) + " |"
    body = ["| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |" for row in rows]
    return "\n".join([header, sep] + body)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
