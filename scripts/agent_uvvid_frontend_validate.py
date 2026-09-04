#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS/datasets/full_downloads/uvvid/files")
PREP_ROOT = Path("/mnt/data/AQUA-FE_WS/datasets/prepared_new")
OUT_DIR = ROOT / "logs" / "agent_uvvid_frontend"

KLT_CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"
NORMAL_SAFE_CONFIG = ROOT / "uw_frontend/configs/paper_normal_safe_frontend.yaml"
LOFTR_EXTREME_CONFIG = ROOT / "uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml"

FRAMES_PER_VIDEO = 300


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    rel_path: str
    size_bytes: int
    mtime: str
    readable: bool
    stable: bool
    status: str
    duration_s: float
    nb_frames: int
    fps: float
    width: int
    height: int
    priority: int
    reason: str


@dataclass(frozen=True)
class PreparedSequence:
    key: str
    video: VideoInfo
    frame_dir: Path
    start_frame: int
    step: int
    requested_frames: int
    written_frames: int


@dataclass(frozen=True)
class MethodSpec:
    key: str
    display: str
    method: str
    config: Path
    preprocess: str = "adaptive_clahe"
    semidense: str = "none"


METHODS = [
    MethodSpec(
        key="klt_adaptive_clahe",
        display="KLT baseline + adaptive CLAHE",
        method="klt",
        config=KLT_CONFIG,
    ),
    MethodSpec(
        key="paper_normal_safe_hybrid_superpoint_lightglue",
        display="paper_normal_safe hybrid SuperPoint+LightGlue",
        method="hybrid_superpoint_lightglue",
        config=NORMAL_SAFE_CONFIG,
    ),
    MethodSpec(
        key="loftr_extreme_only_sp_lg_loftr",
        display="LoFTR extreme-only three-layer SP+LG+LoFTR",
        method="hybrid_superpoint_lightglue",
        config=LOFTR_EXTREME_CONFIG,
        semidense="loftr",
    ),
]


SUMMARY_COLUMNS = [
    "sequence",
    "video",
    "method",
    "status",
    "frames",
    "num_features_mean",
    "num_features_median",
    "grid_coverage_mean",
    "grid_coverage_median",
    "median_track_age_median",
    "long_track_ratio_mean",
    "dropout_ratio_mean",
    "fundamental_inlier_ratio_median",
    "homography_inlier_ratio_median",
    "median_epipolar_error_median",
    "median_homography_error_median",
    "image_quality_median",
    "degradation_score_median",
    "flat_region_ratio_median",
    "grid_texture_score_median",
    "runtime_ms_median",
    "sp_lg_tracks_sum",
    "loftr_tracks_sum",
    "loftr_accepted_frames",
    "semidense_accepted_sum",
    "csv",
    "log",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare currently complete UVVID videos and run frontend-only validation."
    )
    parser.add_argument("--data-root", default=str(DATA_ROOT))
    parser.add_argument("--prepared-root", default=str(PREP_ROOT))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--frames", type=int, default=FRAMES_PER_VIDEO)
    parser.add_argument("--num-videos", type=int, default=2)
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--force-run", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    prepared_root = Path(args.prepared_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.frames < 300 or args.frames > 600:
        raise ValueError("--frames must stay within the requested 300-600 range.")

    videos = scan_videos(data_root)
    write_inventory(videos, output_dir / "mp4_inventory.csv")
    selected = select_videos(videos, args.num_videos)
    write_selection(selected, output_dir / "selected_videos.csv")

    sequences = [
        prepare_sequence(
            video=video,
            prepared_root=prepared_root,
            requested_frames=args.frames,
            force=args.force_extract,
        )
        for video in selected
    ]
    write_prepared_manifest(sequences, output_dir / "prepared_sequences.csv")

    run_records: list[dict[str, Any]] = []
    if not args.summary_only:
        for sequence in sequences:
            for method in METHODS:
                record = run_method(sequence, method, output_dir, force=args.force_run)
                run_records.append(record)
                if args.strict and record["status"] != "OK":
                    raise RuntimeError(f"{sequence.key}/{method.key} failed; see {record['log']}")

    summary = summarize_all(sequences, output_dir, run_records)
    summary_csv = output_dir / "uvvid_frontend_summary.csv"
    summary_md = output_dir / "uvvid_frontend_report.md"
    summary.to_csv(summary_csv, index=False)
    summary_md.write_text(build_report(videos, selected, sequences, summary), encoding="utf-8")
    print(f"inventory: {output_dir / 'mp4_inventory.csv'}")
    print(f"prepared:  {output_dir / 'prepared_sequences.csv'}")
    print(f"summary:   {summary_csv}")
    print(f"report:    {summary_md}")
    return 0


def scan_videos(data_root: Path) -> list[VideoInfo]:
    if not data_root.exists():
        raise FileNotFoundError(data_root)
    videos: list[VideoInfo] = []
    for path in sorted(data_root.rglob("*.mp4")):
        stable = is_size_stable(path)
        metadata, error = ffprobe(path)
        readable = metadata is not None
        rel_path = str(path.relative_to(data_root))
        status = "complete" if readable and stable else "pending_or_incomplete"
        if readable:
            stream = (metadata.get("streams") or [{}])[0]
            fmt = metadata.get("format") or {}
            duration = to_float(fmt.get("duration") or stream.get("duration"))
            nb_frames = to_int(stream.get("nb_frames"))
            fps = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
            width = to_int(stream.get("width"))
            height = to_int(stream.get("height"))
        else:
            duration = 0.0
            nb_frames = 0
            fps = 0.0
            width = 0
            height = 0
            if error:
                status = f"incomplete: {error[:120]}"
        stat = path.stat()
        priority, reason = score_video(rel_path, readable, stable, nb_frames)
        videos.append(
            VideoInfo(
                path=path,
                rel_path=rel_path,
                size_bytes=stat.st_size,
                mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                readable=readable,
                stable=stable,
                status=status,
                duration_s=duration,
                nb_frames=nb_frames,
                fps=fps,
                width=width,
                height=height,
                priority=priority,
                reason=reason,
            )
        )
    return videos


def is_size_stable(path: Path, wait_s: float = 1.5) -> bool:
    size0 = path.stat().st_size
    time.sleep(wait_s)
    size1 = path.stat().st_size
    return size0 == size1


def ffprobe(path: Path) -> tuple[dict[str, Any] | None, str]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_frames,r_frame_rate,avg_frame_rate,width,height,duration",
        "-show_entries",
        "format=duration,size,format_name",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return None, result.stderr.strip()
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as exc:
        return None, str(exc)


def score_video(rel_path: str, readable: bool, stable: bool, nb_frames: int) -> tuple[int, str]:
    rel = rel_path.lower()
    filename = Path(rel_path).name.lower()
    score = 0
    reasons: list[str] = []
    if readable and stable and nb_frames >= 300:
        score += 1000
        reasons.append("complete_readable")
    if "multicam datasets videos" in rel:
        score += 350
        reasons.append("real_multicam_scene")
    if "calibration" in rel:
        score -= 250
        reasons.append("calibration_only")
    if any(token in filename for token in ["bottom_most", "stereo_bottom", "_bottom", "bottom_"]):
        score += 220
        reasons.append("bottom_camera")
    if any(token in rel for token in ["shipwreck", "cannon", "copenhaguen", "amaliahavn"]):
        score += 120
        reasons.append("underwater_scene")
    if any(token in rel for token in ["cave", "wall", "near", "aqualoc", "saltholm", "rocky bottom"]):
        score += 80
        reasons.append("low_texture_candidate_name")
    return score, ",".join(reasons) if reasons else "not_prioritized"


def select_videos(videos: list[VideoInfo], num_videos: int) -> list[VideoInfo]:
    complete = [video for video in videos if video.readable and video.stable and video.nb_frames >= 300]
    ranked = sorted(complete, key=lambda item: (-item.priority, item.rel_path))
    if not ranked:
        raise RuntimeError("No complete readable mp4 with at least 300 frames was found.")
    return ranked[: max(1, num_videos)]


def prepare_sequence(
    video: VideoInfo,
    prepared_root: Path,
    requested_frames: int,
    force: bool,
) -> PreparedSequence:
    key = make_sequence_key(video)
    frame_dir = prepared_root / key
    expected = requested_frames
    existing = sorted(frame_dir.glob("frame_*.png")) if frame_dir.exists() else []
    if len(existing) == expected and not force:
        start_frame, step = read_extract_params(frame_dir, video.nb_frames, requested_frames)
        return PreparedSequence(key, video, frame_dir, start_frame, step, requested_frames, len(existing))

    frame_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for image in frame_dir.glob("frame_*.png"):
            image.unlink()

    start_frame = 0
    step = max(1, video.nb_frames // requested_frames)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video.path),
        "-vf",
        f"select='not(mod(n\\,{step}))',scale=960:-2",
        "-vsync",
        "vfr",
        "-frames:v",
        str(requested_frames),
        str(frame_dir / "frame_%06d.png"),
    ]
    subprocess.run(command, check=True)
    written = len(sorted(frame_dir.glob("frame_*.png")))
    manifest = frame_dir / "extract_manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_video",
                "source_frames",
                "requested_frames",
                "written_frames",
                "start_frame",
                "step",
                "scale",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "source_video": str(video.path),
                "source_frames": video.nb_frames,
                "requested_frames": requested_frames,
                "written_frames": written,
                "start_frame": start_frame,
                "step": step,
                "scale": "width=960,height=auto",
            }
        )
    return PreparedSequence(key, video, frame_dir, start_frame, step, requested_frames, written)


def read_extract_params(frame_dir: Path, nb_frames: int, requested_frames: int) -> tuple[int, int]:
    manifest = frame_dir / "extract_manifest.csv"
    if manifest.exists():
        with manifest.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            return to_int(rows[0].get("start_frame")), max(1, to_int(rows[0].get("step")))
    return 0, max(1, nb_frames // requested_frames)


def run_method(
    sequence: PreparedSequence,
    method: MethodSpec,
    output_dir: Path,
    force: bool,
) -> dict[str, Any]:
    csv_path = output_dir / f"{sequence.key}_{method.key}.csv"
    log_path = output_dir / f"{sequence.key}_{method.key}.log"
    if csv_path.exists() and csv_path.stat().st_size > 0 and not force:
        return {"sequence": sequence.key, "method": method.key, "status": "OK", "csv": csv_path, "log": log_path}
    command = [
        "python3",
        "-m",
        "uw_frontend.evaluation.run_frontend_eval",
        "--input",
        str(sequence.frame_dir),
        "--output-csv",
        str(csv_path),
        "--method",
        method.method,
        "--config",
        str(method.config),
        "--preprocess",
        method.preprocess,
    ]
    if method.semidense != "none":
        command += ["--semidense-fallback-method", method.semidense]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    status = "OK" if result.returncode == 0 and csv_path.exists() and csv_path.stat().st_size > 0 else f"FAILED_{result.returncode}"
    return {"sequence": sequence.key, "method": method.key, "status": status, "csv": csv_path, "log": log_path}


def summarize_all(
    sequences: list[PreparedSequence],
    output_dir: Path,
    run_records: list[dict[str, Any]],
) -> pd.DataFrame:
    status_map = {
        (record["sequence"], record["method"]): record["status"]
        for record in run_records
    }
    rows: list[dict[str, Any]] = []
    for sequence in sequences:
        for method in METHODS:
            csv_path = output_dir / f"{sequence.key}_{method.key}.csv"
            log_path = output_dir / f"{sequence.key}_{method.key}.log"
            status = status_map.get((sequence.key, method.key), "OK" if csv_path.exists() else "PENDING")
            if csv_path.exists() and csv_path.stat().st_size > 0:
                try:
                    row = summarize_csv(csv_path)
                except (EmptyDataError, pd.errors.ParserError):
                    row = empty_summary()
                    status = "FAILED_UNREADABLE_CSV"
            else:
                row = empty_summary()
            row.update(
                {
                    "sequence": sequence.key,
                    "video": sequence.video.rel_path,
                    "method": method.key,
                    "status": status,
                    "csv": str(csv_path),
                    "log": str(log_path) if log_path.exists() else "",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)[SUMMARY_COLUMNS]


def summarize_csv(csv_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(csv_path)
    if frame.empty:
        row = empty_summary()
        row["frames"] = 0
        return row
    row = {
        "frames": int(len(frame)),
        "num_features_mean": mean(frame, "num_features"),
        "num_features_median": median(frame, "num_features"),
        "grid_coverage_mean": mean(frame, "grid_coverage"),
        "grid_coverage_median": median(frame, "grid_coverage"),
        "median_track_age_median": median(frame, "median_track_age"),
        "long_track_ratio_mean": mean(frame, "long_track_ratio"),
        "dropout_ratio_mean": mean(frame, "dropout_ratio"),
        "fundamental_inlier_ratio_median": median(frame, "fundamental_inlier_ratio"),
        "homography_inlier_ratio_median": median(frame, "homography_inlier_ratio"),
        "median_epipolar_error_median": median(frame, "median_epipolar_error"),
        "median_homography_error_median": median(frame, "median_homography_error"),
        "image_quality_median": median(frame, "image_quality"),
        "degradation_score_median": median(frame, "degradation_score"),
        "flat_region_ratio_median": median(frame, "flat_region_ratio"),
        "grid_texture_score_median": median(frame, "grid_texture_score"),
        "runtime_ms_median": median(frame, "runtime_ms"),
        "sp_lg_tracks_sum": source_sum(
            frame,
            [
                "superpoint_lightglue_tracks",
                "superpoint_lightglue_recovery_tracks",
                "superpoint_lightglue_init_tracks",
                "superpoint_lightglue_confirmed_tracks",
            ],
        ),
        "loftr_tracks_sum": source_sum(
            frame,
            ["loftr_tracks", "loftr_recovery_tracks", "loftr_init_tracks", "loftr_confirmed_tracks"],
        ),
        "loftr_accepted_frames": accepted_frames(
            frame,
            ["loftr_tracks", "loftr_recovery_tracks", "loftr_init_tracks", "loftr_confirmed_tracks"],
        ),
        "semidense_accepted_sum": source_sum(frame, ["semidense_accepted_candidates", "loftr_confirmed_promoted"]),
    }
    return row


def empty_summary() -> dict[str, Any]:
    return {
        "frames": 0,
        "num_features_mean": math.nan,
        "num_features_median": math.nan,
        "grid_coverage_mean": math.nan,
        "grid_coverage_median": math.nan,
        "median_track_age_median": math.nan,
        "long_track_ratio_mean": math.nan,
        "dropout_ratio_mean": math.nan,
        "fundamental_inlier_ratio_median": math.nan,
        "homography_inlier_ratio_median": math.nan,
        "median_epipolar_error_median": math.nan,
        "median_homography_error_median": math.nan,
        "image_quality_median": math.nan,
        "degradation_score_median": math.nan,
        "flat_region_ratio_median": math.nan,
        "grid_texture_score_median": math.nan,
        "runtime_ms_median": math.nan,
        "sp_lg_tracks_sum": 0,
        "loftr_tracks_sum": 0,
        "loftr_accepted_frames": 0,
        "semidense_accepted_sum": 0,
    }


def build_report(
    videos: list[VideoInfo],
    selected: list[VideoInfo],
    sequences: list[PreparedSequence],
    summary: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# UVVID Frontend Validation Report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- Data root: `{DATA_ROOT}`")
    lines.append(f"- Output dir: `{OUT_DIR}`")
    lines.append("")
    lines.append("## Current MP4 Status")
    lines.append("")
    complete = [video for video in videos if video.readable and video.stable and video.nb_frames >= 300]
    pending = [video for video in videos if video not in complete]
    lines.append(f"- Complete/readable MP4 with >=300 frames: {len(complete)}")
    lines.append(f"- Pending/incomplete MP4: {len(pending)}")
    lines.append("")
    lines.append("| status | frames | duration_s | camera/scene | file |")
    lines.append("|---|---:|---:|---|---|")
    for video in sorted(videos, key=lambda item: (-item.priority, item.rel_path)):
        status = "complete" if video in complete else markdown_cell(video.status)
        lines.append(
            f"| {status} | {video.nb_frames} | {video.duration_s:.1f} | {markdown_cell(video.reason)} | `{markdown_cell(video.rel_path)}` |"
        )
    lines.append("")
    lines.append("## Selected Videos And Extraction")
    lines.append("")
    lines.append("| sequence | video | extracted frames | sampling | frame dir |")
    lines.append("|---|---|---:|---|---|")
    for sequence in sequences:
        lines.append(
            f"| `{sequence.key}` | `{sequence.video.rel_path}` | {sequence.written_frames} | "
            f"start {sequence.start_frame}, every {sequence.step} source frames, scaled width 960 | "
            f"`{sequence.frame_dir}` |"
        )
    lines.append("")
    lines.append("## Frontend Metrics")
    lines.append("")
    display_cols = [
        "sequence",
        "method",
        "frames",
        "num_features_mean",
        "grid_coverage_median",
        "median_track_age_median",
        "long_track_ratio_mean",
        "dropout_ratio_mean",
        "fundamental_inlier_ratio_median",
        "homography_inlier_ratio_median",
        "median_epipolar_error_median",
        "runtime_ms_median",
        "sp_lg_tracks_sum",
        "loftr_tracks_sum",
        "semidense_accepted_sum",
    ]
    lines.append(markdown_table(summary[display_cols]))
    lines.append("")
    lines.append("## Learned / LoFTR Positive Gain")
    lines.append("")
    for sequence in sequences:
        lines.extend(learned_assessment(sequence, summary))
    lines.append("")
    lines.append("## Missing UVVID Files For Stronger Low-Texture Testing")
    lines.append("")
    real_complete = [
        video
        for video in complete
        if video.rel_path.startswith("Multicam Datasets Videos/")
    ]
    real_folders = sorted({str(Path(video.rel_path).parent) for video in real_complete})
    bottom_like = [
        video.rel_path
        for video in real_complete
        if any(token in video.rel_path.lower() for token in ["bottom_most", "stereo_bottom", "bottom"])
    ]
    if real_folders:
        lines.append(
            "- Current complete real-scene folders: "
            + ", ".join(f"`{folder}`" for folder in real_folders)
            + "."
        )
    if bottom_like:
        preview = bottom_like[:8]
        suffix = "..." if len(bottom_like) > len(preview) else ""
        lines.append(
            "- Current complete bottom/stereo-bottom candidates include: "
            + ", ".join(f"`{item}`" for item in preview)
            + suffix
            + "."
        )
    pending_now = [video for video in videos if video not in complete]
    if pending_now:
        lines.append(
            "- Still pending/incomplete at scan time: "
            + ", ".join(f"`{video.rel_path}`" for video in pending_now)
            + "."
        )
    else:
        lines.append("- No incomplete MP4 was detected at scan time.")
    lines.append("- More targeted low-texture validation is still waiting for later UVVID downloads named in the task: `visual-inertial/AQUALOC`, `Saltholm`, and `UnderwaterCaves`.")
    lines.append("- For the next pass, prioritize bottom/stereo-bottom, rocky-bottom, cave, or near-wall camera streams from those folders over calibration videos.")
    lines.append("")
    lines.append("## Reproducibility")
    lines.append("")
    lines.append("- Inventory CSV: `logs/agent_uvvid_frontend/mp4_inventory.csv`")
    lines.append("- Prepared sequence manifest: `logs/agent_uvvid_frontend/prepared_sequences.csv`")
    lines.append("- Summary CSV: `logs/agent_uvvid_frontend/uvvid_frontend_summary.csv`")
    lines.append("- Per-run CSV/log files are stored under `logs/agent_uvvid_frontend/`.")
    return "\n".join(lines) + "\n"


def learned_assessment(sequence: PreparedSequence, summary: pd.DataFrame) -> list[str]:
    rows = summary[summary["sequence"] == sequence.key].set_index("method")
    lines = [f"### {sequence.key}", ""]
    baseline_key = "klt_adaptive_clahe"
    if baseline_key not in rows.index:
        lines.append("- Baseline row is missing; no gain assessment possible.")
        lines.append("")
        return lines
    baseline = rows.loc[baseline_key]
    for method_key in [
        "paper_normal_safe_hybrid_superpoint_lightglue",
        "loftr_extreme_only_sp_lg_loftr",
    ]:
        if method_key not in rows.index:
            lines.append(f"- `{method_key}` missing; no assessment.")
            continue
        candidate = rows.loc[method_key]
        if int(candidate.get("frames", 0)) == 0:
            lines.append(f"- `{method_key}` did not produce a usable CSV.")
            continue
        gains = []
        grid_delta = safe_delta(candidate, baseline, "grid_coverage_median")
        age_delta = safe_delta(candidate, baseline, "median_track_age_median")
        dropout_delta = safe_delta(candidate, baseline, "dropout_ratio_mean")
        epi_delta = safe_delta(candidate, baseline, "median_epipolar_error_median")
        if grid_delta >= 0.01:
            gains.append(f"grid +{grid_delta:.3f}")
        if age_delta >= 1.0:
            gains.append(f"age +{age_delta:.2f}")
        if dropout_delta <= -0.01:
            gains.append(f"dropout {dropout_delta:.3f}")
        geometry_cost = ""
        if not math.isnan(epi_delta) and epi_delta > 0.25:
            geometry_cost = f"; epipolar cost +{epi_delta:.3f}"
        learned_sum = int(candidate.get("sp_lg_tracks_sum", 0))
        loftr_sum = int(candidate.get("loftr_tracks_sum", 0))
        semidense_sum = int(candidate.get("semidense_accepted_sum", 0))
        if gains:
            verdict = "positive frontend gain"
        elif learned_sum > 0 or loftr_sum > 0 or semidense_sum > 0:
            verdict = "learned path active but no clear positive gain over KLT"
        else:
            verdict = "no learned/LoFTR contribution observed"
        lines.append(
            f"- `{method_key}`: {verdict}; "
            f"SP+LG sum={learned_sum}, LoFTR sum={loftr_sum}, semidense accepted/promoted={semidense_sum}; "
            f"{', '.join(gains) if gains else 'no core metric win'}{geometry_cost}."
        )
    lines.append("")
    return lines


def write_inventory(videos: list[VideoInfo], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(VideoInfo.__dataclass_fields__.keys()))
        writer.writeheader()
        for video in videos:
            row = {key: getattr(video, key) for key in VideoInfo.__dataclass_fields__}
            row["path"] = str(video.path)
            writer.writerow(row)


def write_selection(videos: list[VideoInfo], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "rel_path", "priority", "reason", "frames", "duration_s"])
        writer.writeheader()
        for rank, video in enumerate(videos, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "rel_path": video.rel_path,
                    "priority": video.priority,
                    "reason": video.reason,
                    "frames": video.nb_frames,
                    "duration_s": video.duration_s,
                }
            )


def write_prepared_manifest(sequences: list[PreparedSequence], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sequence",
                "source_video",
                "frame_dir",
                "source_frames",
                "requested_frames",
                "written_frames",
                "start_frame",
                "step",
            ],
        )
        writer.writeheader()
        for sequence in sequences:
            writer.writerow(
                {
                    "sequence": sequence.key,
                    "source_video": str(sequence.video.path),
                    "frame_dir": str(sequence.frame_dir),
                    "source_frames": sequence.video.nb_frames,
                    "requested_frames": sequence.requested_frames,
                    "written_frames": sequence.written_frames,
                    "start_frame": sequence.start_frame,
                    "step": sequence.step,
                }
            )


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    display = frame.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(format_float)
    headers = [str(column) for column in display.columns]
    rows = [
        ["" if pd.isna(value) else str(value) for value in row]
        for row in display.itertuples(index=False, name=None)
    ]
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in rows)) if rows else len(headers[idx])
        for idx in range(len(headers))
    ]

    def render_row(values: list[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([render_row(headers), separator] + [render_row(row) for row in rows])


def markdown_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).replace("|", "/").strip()


def make_sequence_key(video: VideoInfo) -> str:
    rel = video.rel_path.lower()
    stem = Path(rel).stem
    parent = Path(rel).parent.name
    raw = f"uvvid_{parent}_{stem}"
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw[:120]


def parse_rate(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value)
    if "/" in text:
        num, den = text.split("/", 1)
        denominator = to_float(den)
        if denominator == 0.0:
            return 0.0
        return to_float(num) / denominator
    return to_float(text)


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def mean(frame: pd.DataFrame, column: str) -> float:
    values = numeric_series(frame, column)
    return float(values.mean()) if len(values) else math.nan


def median(frame: pd.DataFrame, column: str) -> float:
    values = numeric_series(frame, column)
    return float(values.median()) if len(values) else math.nan


def source_sum(frame: pd.DataFrame, columns: list[str]) -> int:
    total = 0.0
    for column in columns:
        values = numeric_series(frame, column)
        if len(values):
            total += float(values.fillna(0.0).sum())
    return int(round(total))


def accepted_frames(frame: pd.DataFrame, columns: list[str]) -> int:
    present = [numeric_series(frame, column).fillna(0.0) for column in columns if column in frame]
    if not present:
        return 0
    stacked = pd.concat(present, axis=1)
    return int((stacked.sum(axis=1) > 0).sum())


def safe_delta(candidate: pd.Series, baseline: pd.Series, column: str) -> float:
    cand = to_float(candidate.get(column))
    base = to_float(baseline.get(column))
    if math.isnan(cand) or math.isnan(base):
        return math.nan
    return cand - base


def format_float(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return ""
    if abs(number) >= 1000:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.2f}"
    return f"{number:.3f}"


if __name__ == "__main__":
    sys.exit(main())
