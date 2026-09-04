#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import pandas as pd


ROOT = Path("/home/ma/AQUA-FE_WS")
UVVID_ROOT = ROOT / "datasets/full_downloads/uvvid/files"
PREP_ROOT = ROOT / "datasets/prepared_new/uvvid_window_scan_may24"
OUT_ROOT = ROOT / "logs/may24_uvvid_window_scan"

KLT_CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"
LOFTR_GATE_CONFIG = ROOT / "uw_frontend/configs/experiments/quality_coverage_loftr_gate_frontend.yaml"


@dataclass(frozen=True)
class VideoSpec:
    key: str
    path: Path
    starts: tuple[int, ...]


DEFAULT_VIDEOS = (
    VideoSpec(
        "uvvid_grafton_bottom",
        UVVID_ROOT / "Multicam Datasets Videos/Grafton Shipwreck Oostende/63346408_video_bottom_most.mp4",
        (0, 240, 720, 1200, 1680),
    ),
    VideoSpec(
        "uvvid_greenish_bottom",
        UVVID_ROOT / "Multicam Datasets Videos/Skovshoved Havn, Greenish water, Copenhagen/63346351_video_bottom_most.mp4",
        (0, 180, 420, 720),
    ),
    VideoSpec(
        "uvvid_rocky_bottom",
        UVVID_ROOT / "Multicam Datasets Videos/Skovshoved Havn, Rocky Bottom Copenhagen/63346369_video_bottom_most.mp4",
        (0, 180, 360),
    ),
    VideoSpec(
        "uvvid_sandy_bottom",
        UVVID_ROOT / "Multicam Datasets Videos/Skovshoved Havn Sandy Seaweed, Copenhagen/63346366_bottom_most.mp4",
        (0, 180, 420),
    ),
    VideoSpec(
        "uvvid_underwater_caves",
        UVVID_ROOT / "visual-inertial/UnderwaterCaves/50977041_export_camera_image_raw_sparus_camera.mp4",
        (0, 300, 900, 1800, 3000, 4800, 6600, 8200),
    ),
    VideoSpec(
        "uvvid_orientkaj_left",
        UVVID_ROOT / "visual-inertial/Orientkaj/Run_1/50977008_video_oak_d_lite_left_image_mono_h265_oak_2024-06-13-00-07-06_0.mp4",
        (0, 600, 1500, 3000, 5200, 7000),
    ),
    VideoSpec(
        "uvvid_saltholm_run7",
        UVVID_ROOT / "visual-inertial/Saltholm/Run_7/50977065_trimmed.mp4",
        (0, 1200, 3600, 7200, 12000, 18000, 23000),
    ),
    VideoSpec(
        "uvvid_pipeline_clip",
        UVVID_ROOT / "Nose cam/short clips/62468659_Long pipeline with mast at the end.mp4",
        (0, 300, 780, 1200),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--every-n", type=int, default=2)
    parser.add_argument(
        "--include",
        default="",
        help="Optional regex over the built-in video key; useful for small resumed scans.",
    )
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument(
        "--resize-width",
        type=int,
        default=0,
        help="Resize extracted frames to this width for quick screening; 0 keeps native resolution.",
    )
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--force-run", action="store_true")
    parser.add_argument("--klt-only", action="store_true")
    args = parser.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    PREP_ROOT.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    include_re = re.compile(args.include) if args.include else None
    scanned = 0
    for video in DEFAULT_VIDEOS:
        if include_re is not None and not include_re.search(video.key):
            continue
        frame_count = get_frame_count(video.path)
        if frame_count <= 0:
            continue
        for start in video.starts:
            if args.max_windows and scanned >= args.max_windows:
                break
            if start >= frame_count - 5:
                continue
            end = min(frame_count - 1, start + args.frames * args.every_n - 1)
            resize_tag = f"_w{args.resize_width}" if args.resize_width > 0 else ""
            seq_dir = PREP_ROOT / f"{video.key}_{start:06d}_{end:06d}_e{args.every_n}{resize_tag}"
            extract_window(
                video.path,
                seq_dir,
                start,
                end,
                args.every_n,
                args.force_extract,
                args.resize_width,
            )
            if not any(seq_dir.glob("*.jpg")):
                continue
            klt_csv = OUT_ROOT / f"{video.key}_{start:06d}_{end:06d}{resize_tag}_klt.csv"
            gate_csv = OUT_ROOT / f"{video.key}_{start:06d}_{end:06d}{resize_tag}_loftr_gate_v3.csv"
            run_frontend(seq_dir, klt_csv, "klt", KLT_CONFIG, "none", args.force_run)
            if not args.klt_only:
                run_frontend(
                    seq_dir,
                    gate_csv,
                    "hybrid_superpoint_lightglue",
                    LOFTR_GATE_CONFIG,
                    "loftr",
                    args.force_run,
                )
            rows.append(summarize_pair(video.key, video.path, start, end, seq_dir, klt_csv, gate_csv))
            scanned += 1
        if args.max_windows and scanned >= args.max_windows:
            break

    table = pd.DataFrame(rows)
    if table.empty:
        raise SystemExit("No windows were scanned.")
    table = table.sort_values(
        ["candidate_score", "accepted_loftr", "klt_grid_med"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    out_csv = OUT_ROOT / "summary.csv"
    out_md = OUT_ROOT / "summary.md"
    table.to_csv(out_csv, index=False)
    out_md.write_text(markdown_report(table), encoding="utf-8")
    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    print(table[compact_cols()].head(30).to_string(index=False))
    return 0


def get_frame_count(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return count


def extract_window(
    video_path: Path,
    out_dir: Path,
    start: int,
    end: int,
    every_n: int,
    force: bool,
    resize_width: int,
) -> None:
    if out_dir.exists() and not force and any(out_dir.glob("*.jpg")):
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for old in out_dir.glob("*.jpg"):
            old.unlink()
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    index = start
    written = 0
    while index <= end:
        ok, frame = cap.read()
        if not ok:
            break
        if (index - start) % every_n == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if resize_width > 0 and gray.shape[1] > resize_width:
                scale = resize_width / float(gray.shape[1])
                new_size = (resize_width, max(1, int(round(gray.shape[0] * scale))))
                gray = cv2.resize(gray, new_size, interpolation=cv2.INTER_AREA)
            out_path = out_dir / f"frame_{index:06d}.jpg"
            cv2.imwrite(str(out_path), gray)
            written += 1
        index += 1
    cap.release()
    if written == 0:
        raise RuntimeError(f"failed to extract {video_path} {start}-{end}")


def run_frontend(
    seq_dir: Path,
    out_csv: Path,
    method: str,
    config: Path,
    semidense: str,
    force: bool,
) -> None:
    if out_csv.exists() and not force:
        return
    cmd = [
        "python3",
        "-m",
        "uw_frontend.evaluation.run_frontend_eval",
        "--input",
        str(seq_dir),
        "--output-csv",
        str(out_csv),
        "--method",
        method,
        "--config",
        str(config),
        "--preprocess",
        "adaptive_clahe",
    ]
    if semidense != "none":
        cmd.extend(["--semidense-fallback-method", semidense])
    log_path = out_csv.with_suffix(".log")
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )


def summarize_pair(
    key: str,
    video_path: Path,
    start: int,
    end: int,
    seq_dir: Path,
    klt_csv: Path,
    gate_csv: Path,
) -> dict[str, object]:
    klt = pd.read_csv(klt_csv)
    gate = pd.read_csv(gate_csv) if gate_csv.exists() else pd.DataFrame()
    row: dict[str, object] = {
        "dataset": key,
        "video": str(video_path),
        "start": start,
        "end": end,
        "frames": len(klt),
        "prepared_dir": str(seq_dir),
        "klt_csv": str(klt_csv),
        "gate_csv": str(gate_csv) if gate_csv.exists() else "",
        "klt_grid_med": med(klt, "grid_coverage"),
        "klt_track_age_med": med(klt, "median_track_age"),
        "klt_epi_med": med(klt, "median_epipolar_error"),
        "klt_hom_med": med(klt, "median_homography_error"),
        "klt_f_inlier_med": med(klt, "fundamental_inlier_ratio"),
        "klt_h_inlier_med": med(klt, "homography_inlier_ratio"),
        "klt_degradation_med": med(klt, "degradation_score"),
        "klt_flat_med": med(klt, "flat_region_ratio"),
        "klt_grid_texture_med": med(klt, "grid_texture_score"),
        "accepted_loftr": 0,
        "accepted_frames": 0,
        "raw_loftr": 0,
        "post_loftr": 0,
        "gate_grid_med": math.nan,
        "gate_track_age_med": math.nan,
        "gate_epi_med": math.nan,
        "gate_hom_med": math.nan,
        "gate_f_inlier_med": math.nan,
        "gate_h_inlier_med": math.nan,
        "acceptance_top": "",
        "mode_top": "",
        "recovery_top": "",
    }
    if not gate.empty:
        row.update(
            {
                "accepted_loftr": total(gate, "semidense_accepted_candidates"),
                "accepted_frames": int((numeric(gate, "semidense_accepted_candidates") > 0).sum()),
                "raw_loftr": total(gate, "semidense_raw_candidates"),
                "post_loftr": total(gate, "semidense_post_validate_candidates"),
                "gate_grid_med": med(gate, "grid_coverage"),
                "gate_track_age_med": med(gate, "median_track_age"),
                "gate_epi_med": med(gate, "median_epipolar_error"),
                "gate_hom_med": med(gate, "median_homography_error"),
                "gate_f_inlier_med": med(gate, "fundamental_inlier_ratio"),
                "gate_h_inlier_med": med(gate, "homography_inlier_ratio"),
                "acceptance_top": counts(gate, "semidense_acceptance"),
                "mode_top": counts(gate, "learned_mode_after_sparse_homography"),
                "recovery_top": counts(gate, "tracker_recovery_reason"),
            }
        )
    row["grid_delta"] = as_float(row["gate_grid_med"]) - as_float(row["klt_grid_med"])
    row["epi_delta"] = as_float(row["gate_epi_med"]) - as_float(row["klt_epi_med"])
    row["hom_delta"] = as_float(row["gate_hom_med"]) - as_float(row["klt_hom_med"])
    row["candidate_score"] = candidate_score(row)
    row["decision"] = decision(row)
    return row


def med(df: pd.DataFrame, col: str) -> float:
    if col not in df or df.empty:
        return math.nan
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(values.median()) if not values.empty else math.nan


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def total(df: pd.DataFrame, col: str) -> int:
    return int(numeric(df, col).sum())


def counts(df: pd.DataFrame, col: str, limit: int = 3) -> str:
    if col not in df:
        return ""
    items = df[col].fillna("n/a").astype(str).value_counts().head(limit).items()
    return ";".join(f"{key}:{value}" for key, value in items)


def as_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def candidate_score(row: dict[str, object]) -> float:
    score = 0.0
    grid = as_float(row["klt_grid_med"])
    age = as_float(row["klt_track_age_med"])
    degr = as_float(row["klt_degradation_med"])
    tex = as_float(row["klt_grid_texture_med"])
    accepted = as_float(row["accepted_loftr"])
    if not math.isnan(grid):
        score += max(0.0, 0.86 - grid) * 3.0
    if not math.isnan(age):
        score += max(0.0, 8.0 - age) * 0.08
    if not math.isnan(degr):
        score += max(0.0, degr - 0.28)
    if not math.isnan(tex):
        score += max(0.0, 0.80 - tex)
    if accepted > 0:
        score += 1.0 + min(1.0, accepted / 50.0)
    epi_delta = as_float(row["epi_delta"])
    hom_delta = as_float(row["hom_delta"])
    if not math.isnan(epi_delta) and epi_delta <= 0.03:
        score += 0.3
    if not math.isnan(hom_delta) and hom_delta <= 0.08:
        score += 0.3
    return score


def decision(row: dict[str, object]) -> str:
    accepted = int(as_float(row["accepted_loftr"]))
    grid_delta = as_float(row["grid_delta"])
    epi_delta = as_float(row["epi_delta"])
    hom_delta = as_float(row["hom_delta"])
    grid = as_float(row["klt_grid_med"])
    age = as_float(row["klt_track_age_med"])
    if accepted > 0 and (math.isnan(epi_delta) or epi_delta <= 0.04) and (math.isnan(hom_delta) or hom_delta <= 0.10):
        return "LoFTR_frontend_positive_candidate"
    if accepted == 0 and grid >= 0.90 and age >= 8:
        return "normal_no_trigger_control"
    if accepted == 0 and (grid < 0.80 or age < 5):
        return "low_texture_but_gate_rejected"
    if not math.isnan(grid_delta) and grid_delta > 0 and accepted > 0:
        return "coverage_gain_caution_geometry"
    return "neutral_or_boundary"


def compact_cols() -> list[str]:
    return [
        "dataset",
        "start",
        "end",
        "decision",
        "candidate_score",
        "klt_grid_med",
        "gate_grid_med",
        "klt_track_age_med",
        "accepted_loftr",
        "accepted_frames",
        "raw_loftr",
        "klt_epi_med",
        "gate_epi_med",
        "klt_hom_med",
        "gate_hom_med",
    ]


def markdown_report(table: pd.DataFrame) -> str:
    lines = ["# May24 UVVID Window Scan", ""]
    compact = table[compact_cols()].copy()
    lines.append(to_markdown(compact.head(40)))
    lines.append("")
    lines.append("## Positive/Useful Windows")
    useful = table[table["decision"].isin(["LoFTR_frontend_positive_candidate", "low_texture_but_gate_rejected"])]
    if useful.empty:
        lines.append("No useful low-texture windows found in this scan.")
    else:
        for _, row in useful.head(20).iterrows():
            lines.append(
                f"- `{row['dataset']}` {int(row['start'])}-{int(row['end'])}: "
                f"{row['decision']}; accepted={int(row['accepted_loftr'])}, "
                f"KLT grid={as_float(row['klt_grid_med']):.3f}, "
                f"age={as_float(row['klt_track_age_med']):.2f}, "
                f"epi {as_float(row['klt_epi_med']):.3f}->{as_float(row['gate_epi_med']):.3f}, "
                f"H {as_float(row['klt_hom_med']):.3f}->{as_float(row['gate_hom_med']):.3f}; "
                f"csv `{row['gate_csv']}`"
            )
    lines.append("")
    lines.append("## Normal No-Trigger Controls")
    controls = table[table["decision"].eq("normal_no_trigger_control")]
    if controls.empty:
        lines.append("No normal no-trigger controls found in this scan.")
    else:
        for _, row in controls.head(12).iterrows():
            lines.append(
                f"- `{row['dataset']}` {int(row['start'])}-{int(row['end'])}: "
                f"KLT grid={as_float(row['klt_grid_med']):.3f}, "
                f"age={as_float(row['klt_track_age_med']):.2f}, LoFTR accepted=0."
            )
    return "\n".join(lines) + "\n"


def to_markdown(df: pd.DataFrame) -> str:
    headers = [str(c) for c in df.columns]
    rows = [[fmt(v) for v in row] for row in df.itertuples(index=False, name=None)]
    widths = [max([len(headers[i])] + [len(r[i]) for r in rows]) for i in range(len(headers))]
    out = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    out.extend("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(headers))) + " |" for r in rows)
    return "\n".join(out)


def fmt(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return f"{value:.4f}"
    return str(value)


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()


if __name__ == "__main__":
    raise SystemExit(main())
