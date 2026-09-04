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
        description="Evaluate per-feature q_i against geometric consistency from track logs."
    )
    parser.add_argument(
        "--track-log",
        action="append",
        type=_parse_spec,
        required=True,
        help="Spec in label:path.csv format. CSV must come from run_frontend_eval --track-log-csv.",
    )
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--min-frame-tracks", type=int, default=12)
    parser.add_argument("--f-threshold", type=float, default=1.0)
    parser.add_argument("--h-threshold", type=float, default=3.0)
    args = parser.parse_args()

    per_method = []
    per_bin = []
    for spec in args.track_log:
        df = pd.read_csv(spec.csv_path)
        method_frame, method_points = _evaluate_one(
            spec.label,
            df,
            bins=args.bins,
            min_frame_tracks=args.min_frame_tracks,
            f_threshold=args.f_threshold,
            h_threshold=args.h_threshold,
        )
        per_method.append(method_frame)
        per_bin.append(method_points)

    method_table = pd.DataFrame(per_method)
    bin_table = pd.concat(per_bin, ignore_index=True) if per_bin else pd.DataFrame()

    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    method_csv = output_prefix.with_name(output_prefix.name + "_method.csv")
    bin_csv = output_prefix.with_name(output_prefix.name + "_bins.csv")
    report_md = output_prefix.with_name(output_prefix.name + "_report.md")
    method_table.to_csv(method_csv, index=False)
    bin_table.to_csv(bin_csv, index=False)
    report_md.write_text(_make_report(method_table, bin_table), encoding="utf-8")

    print(method_table.to_string(index=False))
    print(f"wrote {method_csv}")
    print(f"wrote {bin_csv}")
    print(f"wrote {report_md}")
    return 0


def _parse_spec(raw: str) -> TrackLogSpec:
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("track log spec must be label:path.csv")
    return TrackLogSpec(parts[0], Path(parts[1]))


def _evaluate_one(
    label: str,
    df: pd.DataFrame,
    bins: int,
    min_frame_tracks: int,
    f_threshold: float,
    h_threshold: float,
) -> tuple[dict, pd.DataFrame]:
    rows = []
    all_points = []
    required = {"frame_index", "prev_x", "prev_y", "x", "y", "quality", "visual_sigma"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"track log is missing columns: {sorted(missing)}")

    for frame_index, group in df.groupby("frame_index"):
        if len(group) < min_frame_tracks:
            continue
        pts0 = group[["prev_x", "prev_y"]].to_numpy(dtype=np.float32)
        pts1 = group[["x", "y"]].to_numpy(dtype=np.float32)
        geom = _frame_geometry(pts0, pts1, f_threshold=f_threshold, h_threshold=h_threshold)
        if geom is None:
            continue
        f_inlier = geom["f_inlier"]
        h_inlier = geom["h_inlier"]
        epi = geom["epipolar_error"]
        hom = geom["homography_error"]
        q = np.clip(group["quality"].to_numpy(dtype=np.float32), 0.0, 1.0)
        sigma = group["visual_sigma"].to_numpy(dtype=np.float32)
        point_df = pd.DataFrame(
            {
                "method": label,
                "frame_index": int(frame_index),
                "quality": q,
                "visual_sigma": sigma,
                "f_inlier": f_inlier.astype(np.float32),
                "h_inlier": h_inlier.astype(np.float32),
                "epipolar_error": epi,
                "homography_error": hom,
            }
        )
        if "source" in group:
            point_df["source"] = group["source"].astype(str).to_numpy()
        all_points.append(point_df)
        rows.append(
            {
                "method": label,
                "frame_index": int(frame_index),
                "num_tracks": int(len(group)),
                "mean_quality": float(np.mean(q)),
                "median_quality": float(np.median(q)),
                "median_sigma": float(np.median(sigma)),
                "f_inlier_ratio": float(np.mean(f_inlier)),
                "h_inlier_ratio": float(np.mean(h_inlier)),
                "median_epipolar_error": float(np.nanmedian(epi)),
                "median_homography_error": float(np.nanmedian(hom)),
                "weighted_epipolar_error": _weighted_mean(epi, q),
                "weighted_homography_error": _weighted_mean(hom, q),
            }
        )

    frame_table = pd.DataFrame(rows)
    if all_points:
        point_table = pd.concat(all_points, ignore_index=True)
    else:
        point_table = pd.DataFrame(
            columns=[
                "method",
                "quality",
                "visual_sigma",
                "f_inlier",
                "h_inlier",
                "epipolar_error",
                "homography_error",
            ]
        )
    bin_table = _bin_points(label, point_table, bins)
    method_row = _summarize_method(label, frame_table, point_table, bin_table)
    return method_row, bin_table


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
        ransacReprojThreshold=f_threshold,
        confidence=0.99,
    )
    h_mat, h_mask = cv2.findHomography(pts0, pts1, cv2.RANSAC, h_threshold)
    if f_mat is None or np.asarray(f_mat).shape != (3, 3):
        f_inlier = np.zeros((len(pts0),), dtype=bool)
        epi = np.full((len(pts0),), np.nan, dtype=np.float32)
    else:
        f_inlier = f_mask.reshape(-1).astype(bool) if f_mask is not None else np.zeros((len(pts0),), dtype=bool)
        epi = _epipolar_errors(f_mat, pts0, pts1)
    if h_mat is None or np.asarray(h_mat).shape != (3, 3):
        h_inlier = np.zeros((len(pts0),), dtype=bool)
        hom = np.full((len(pts0),), np.nan, dtype=np.float32)
    else:
        h_inlier = h_mask.reshape(-1).astype(bool) if h_mask is not None else np.zeros((len(pts0),), dtype=bool)
        hom = _homography_errors(h_mat, pts0, pts1)
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


def _bin_points(label: str, point_table: pd.DataFrame, bins: int) -> pd.DataFrame:
    if point_table.empty:
        return pd.DataFrame()
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (point_table["quality"] >= lo) & (
            point_table["quality"] < hi if hi < 1.0 else point_table["quality"] <= hi
        )
        group = point_table[mask]
        if group.empty:
            continue
        rows.append(
            {
                "method": label,
                "bin": f"{lo:.1f}-{hi:.1f}",
                "count": int(len(group)),
                "q_mean": float(group["quality"].mean()),
                "sigma_median": float(group["visual_sigma"].median()),
                "f_inlier_rate": float(group["f_inlier"].mean()),
                "h_inlier_rate": float(group["h_inlier"].mean()),
                "epipolar_median": float(group["epipolar_error"].median()),
                "homography_median": float(group["homography_error"].median()),
            }
        )
    return pd.DataFrame(rows)


def _summarize_method(
    label: str,
    frame_table: pd.DataFrame,
    point_table: pd.DataFrame,
    bin_table: pd.DataFrame,
) -> dict:
    if frame_table.empty:
        return {"method": label, "frames": 0, "points": int(len(point_table))}
    corr_f = _corr(point_table["quality"], point_table["f_inlier"])
    corr_h = _corr(point_table["quality"], point_table["h_inlier"])
    return {
        "method": label,
        "frames": int(len(frame_table)),
        "points": int(len(point_table)),
        "tracks_mean": float(frame_table["num_tracks"].mean()),
        "quality_median": float(point_table["quality"].median()) if not point_table.empty else float("nan"),
        "sigma_median": float(point_table["visual_sigma"].median()) if not point_table.empty else float("nan"),
        "f_inlier_mean": float(frame_table["f_inlier_ratio"].mean()),
        "h_inlier_mean": float(frame_table["h_inlier_ratio"].mean()),
        "epipolar_median": float(frame_table["median_epipolar_error"].median()),
        "homography_median": float(frame_table["median_homography_error"].median()),
        "q_f_inlier_corr": corr_f,
        "q_h_inlier_corr": corr_h,
        "f_inlier_ece": _geometry_ece(bin_table, "f_inlier_rate"),
        "h_inlier_ece": _geometry_ece(bin_table, "h_inlier_rate"),
    }


def _geometry_ece(bin_table: pd.DataFrame, col: str) -> float:
    if bin_table.empty or col not in bin_table:
        return float("nan")
    total = float(bin_table["count"].sum())
    if total <= 0.0:
        return float("nan")
    return float(np.sum(bin_table["count"] / total * np.abs(bin_table["q_mean"] - bin_table[col])))


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    mask = np.isfinite(values)
    if not np.any(mask):
        return float("nan")
    w = np.clip(weights[mask], 1e-3, 1.0)
    return float(np.sum(values[mask] * w) / np.sum(w))


def _corr(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    arr_a = a.to_numpy(dtype=np.float32)
    arr_b = b.to_numpy(dtype=np.float32)
    if float(np.std(arr_a)) < 1e-6 or float(np.std(arr_b)) < 1e-6:
        return float("nan")
    return float(np.corrcoef(arr_a, arr_b)[0, 1])


def _make_report(method_table: pd.DataFrame, bin_table: pd.DataFrame) -> str:
    lines = ["# Track Geometry Reliability", ""]
    lines.append("## Method Summary")
    lines.append(_to_markdown(method_table))
    if not bin_table.empty:
        lines.append("")
        lines.append("## Quality Bins")
        lines.append(_to_markdown(bin_table))
    return "\n".join(lines) + "\n"


def _to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    headers = [str(col) for col in df.columns]
    rows = [[_fmt(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    header = "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
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
