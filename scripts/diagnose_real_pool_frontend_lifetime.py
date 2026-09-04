#!/usr/bin/env python3
"""Frontend-only lineage and KLT failure diagnostics for real-pool ROS bags.

The script never starts ROS nodes, runs VINS, or writes a feature bag.  It
streams ``sensor_msgs/Image`` messages directly from a ROS1 bag, executes the
same AQUA-FE tracker/configuration, decomposes every KLT rejection into an
exclusive cause, and writes compact CSV/JSON/overlay artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rosbag

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.evaluation.run_frontend_eval import (
    build_matcher,
    load_config,
    resolve_process_skipped_frames,
)
from uw_frontend.geometry.grid import grid_stats
from uw_frontend.quality.image_quality import (
    fuse_image_quality_for_gates,
    score_image_quality,
)
from uw_frontend.tracking.hybrid_tracker import HybridConfig, HybridKltOrbTracker
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker, _in_border, _patch_ncc


FIELDS = (
    "sequence",
    "profile",
    "method",
    "preprocess",
    "process_skipped_frames",
    "raw_frame_index",
    "processed_frame_index",
    "selected_frame_index",
    "selected_for_output",
    "header_stamp_s",
    "bag_stamp_s",
    "header_minus_bag_s",
    "frame_dt_s",
    "raw_mean_intensity",
    "raw_contrast",
    "raw_gradient_mean",
    "raw_laplacian_var",
    "raw_underexposed_ratio",
    "raw_overexposed_ratio",
    "raw_flat_region_ratio",
    "raw_grid_texture_score",
    "raw_blur_score",
    "raw_degradation_score",
    "processed_contrast",
    "processed_gradient_mean",
    "processed_laplacian_var",
    "processed_flat_region_ratio",
    "processed_grid_texture_score",
    "processed_blur_score",
    "processed_degradation_score",
    "interframe_mean_absdiff",
    "interframe_mean_intensity_delta",
    "klt_input_tracks",
    "klt_forward_status_ok",
    "klt_backward_status_ok",
    "klt_fb_pass",
    "klt_ncc_pass",
    "klt_border_pass",
    "klt_final_pass",
    "death_forward_fail",
    "death_backward_fail",
    "death_fb_fail",
    "death_ncc_fail",
    "death_border_fail",
    "gftt_detected_births",
    "gftt_pending_candidates",
    "gftt_confirm_input",
    "gftt_confirm_forward_pass",
    "gftt_confirm_backward_pass",
    "gftt_confirm_fb_pass",
    "gftt_confirm_ncc_pass",
    "gftt_confirm_border_pass",
    "gftt_confirm_distance_pass",
    "gftt_confirm_geometry_pass",
    "gftt_confirm_selected",
    "gftt_confirm_admitted",
    "tracker_births",
    "tracker_deaths",
    "selected_births",
    "selected_deaths",
    "output_tracks",
    "output_grid_coverage",
    "output_age_ge2_tracks",
    "output_age_ge2_grid_coverage",
    "output_age_ge3_tracks",
    "output_age_ge3_grid_coverage",
    "output_gftt_births",
    "output_klt_survivors",
    "output_xfeat_tracks",
    "output_other_learned_tracks",
    "median_track_age",
    "long_track_age_ge5_ratio",
    "median_fb_error",
    "median_ncc",
    "median_motion_px",
    "p90_motion_px",
    "max_motion_px",
    "dropout_ratio",
    "learned_mode",
    "xfeat_candidates",
    "xfeat_confirmed",
    "pending_xfeat",
    "recovery_reason",
    "source_histogram",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--image-topic", default="/cam0/image_raw")
    parser.add_argument("--config", required=True)
    parser.add_argument("--camera-config", required=True)
    parser.add_argument(
        "--method",
        choices=["klt", "hybrid_xfeat", "hybrid_no_learned"],
        default="klt",
    )
    parser.add_argument(
        "--preprocess",
        choices=["none", "equalize", "clahe", "adaptive_clahe"],
        default="none",
    )
    parser.add_argument("--every-n", type=int, default=2)
    parser.add_argument("--frame-offset", type=int, default=0)
    cadence_group = parser.add_mutually_exclusive_group()
    cadence_group.add_argument(
        "--process-skipped-frames",
        dest="process_skipped_frames",
        action="store_true",
        help="Override the profile and process non-output frames.",
    )
    cadence_group.add_argument(
        "--no-process-skipped-frames",
        dest="process_skipped_frames",
        action="store_false",
        help="Override the profile and skip non-output frames.",
    )
    parser.set_defaults(process_skipped_frames=None)
    parser.add_argument("--start-raw-index", type=int, default=0)
    parser.add_argument("--end-raw-index", type=int, default=None)
    parser.add_argument("--max-raw-frames", type=int, default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--save-viz-dir", default=None)
    parser.add_argument("--save-viz-every", type=int, default=300)
    parser.add_argument("--max-event-overlays", type=int, default=6)
    parser.add_argument("--event-dropout-threshold", type=float, default=0.65)
    return parser.parse_args()


def build_tracker(method: str, cfg: dict[str, Any]):
    if method == "klt":
        return KltTracker(KltConfig(**cfg.get("klt", {})))
    return HybridKltOrbTracker(
        KltConfig(**cfg.get("klt", {})),
        HybridConfig(**cfg.get("hybrid", {})),
        learned_matcher=(
            build_matcher("hybrid_xfeat", cfg)
            if method == "hybrid_xfeat"
            else None
        ),
    )


def preprocess(gray: np.ndarray, mode: str, quality=None) -> np.ndarray:
    if mode == "none":
        return gray
    if mode == "equalize":
        return cv2.equalizeHist(gray)
    if mode == "clahe":
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    quality = quality if quality is not None else score_image_quality(gray)
    enhance = (
        quality.contrast_score < 0.72
        or quality.grid_texture_score < 0.58
        or quality.illumination_nonuniformity > 0.18
        or quality.degradation_score > 0.42
    )
    return (
        cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        if enhance
        else gray
    )


def decode_mono8(message) -> np.ndarray:
    encoding = str(message.encoding).lower()
    height, width, step = int(message.height), int(message.width), int(message.step)
    data = np.frombuffer(message.data, dtype=np.uint8).reshape(height, step)
    if encoding in {"mono8", "8uc1"}:
        return data[:, :width].copy()
    if encoding in {"bgr8", "rgb8"}:
        color = data[:, : width * 3].reshape(height, width, 3)
        code = cv2.COLOR_BGR2GRAY if encoding == "bgr8" else cv2.COLOR_RGB2GRAY
        return cv2.cvtColor(color, code)
    raise ValueError(f"unsupported image encoding {message.encoding!r}")


def klt_backbone(tracker):
    return tracker.klt if hasattr(tracker, "klt") else tracker


def transition_diagnostics(klt: KltTracker, current: np.ndarray) -> tuple[dict[str, Any], dict[int, str]]:
    empty = {
        "klt_input_tracks": 0,
        "klt_forward_status_ok": 0,
        "klt_backward_status_ok": 0,
        "klt_fb_pass": 0,
        "klt_ncc_pass": 0,
        "klt_border_pass": 0,
        "klt_final_pass": 0,
        "death_forward_fail": 0,
        "death_backward_fail": 0,
        "death_fb_fail": 0,
        "death_ncc_fail": 0,
        "death_border_fail": 0,
        "median_motion_px": float("nan"),
        "p90_motion_px": float("nan"),
        "max_motion_px": float("nan"),
        "interframe_mean_absdiff": float("nan"),
        "interframe_mean_intensity_delta": float("nan"),
    }
    if klt.prev_image is None or len(klt.points) == 0:
        return empty, {}
    previous = klt.prev_image
    old_points = klt.points.reshape(-1, 2).astype(np.float32)
    old_ids = klt.ids.astype(np.int64)
    prev_pts = old_points.reshape(-1, 1, 2)
    params = {
        "winSize": (klt.config.lk_win_size, klt.config.lk_win_size),
        "maxLevel": klt.config.lk_max_level,
        "criteria": (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    }
    cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, prev_pts, None, **params)
    if cur_pts is None or status is None:
        reasons = {int(track_id): "forward_fail" for track_id in old_ids}
        empty.update(
            {
                "klt_input_tracks": len(old_ids),
                "death_forward_fail": len(old_ids),
                "interframe_mean_absdiff": float(
                    np.mean(cv2.absdiff(previous, current), dtype=np.float64)
                ),
                "interframe_mean_intensity_delta": float(
                    np.mean(current, dtype=np.float64) - np.mean(previous, dtype=np.float64)
                ),
            }
        )
        return empty, reasons
    back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(current, previous, cur_pts, None, **params)
    if back_pts is None or back_status is None:
        back_pts = prev_pts.copy()
        back_status = np.zeros_like(status)
    cur_flat = cur_pts.reshape(-1, 2)
    back_flat = back_pts.reshape(-1, 2)
    forward = status.reshape(-1) > 0
    backward = back_status.reshape(-1) > 0
    fb_errors = np.linalg.norm(old_points - back_flat, axis=1)
    ncc = _patch_ncc(previous, current, old_points, cur_flat, klt.config.patch_radius)
    border = _in_border(cur_flat, current.shape, klt.config.border)
    fb_threshold = float(klt.config.fb_threshold)
    ncc_threshold = float(klt.config.min_ncc)
    fwd_ok = forward
    back_ok = fwd_ok & backward
    fb_ok = back_ok & np.isfinite(fb_errors) & (fb_errors <= fb_threshold)
    ncc_ok = fb_ok & np.isfinite(ncc) & (ncc >= ncc_threshold)
    final = ncc_ok & border
    exclusive = {
        "forward_fail": ~fwd_ok,
        "backward_fail": fwd_ok & ~backward,
        "fb_fail": back_ok & ~(np.isfinite(fb_errors) & (fb_errors <= fb_threshold)),
        "ncc_fail": fb_ok & ~(np.isfinite(ncc) & (ncc >= ncc_threshold)),
        "border_fail": ncc_ok & ~border,
    }
    reasons: dict[int, str] = {}
    for reason, mask in exclusive.items():
        for track_id in old_ids[mask]:
            reasons[int(track_id)] = reason
    motion = np.linalg.norm(cur_flat[final] - old_points[final], axis=1)
    result = {
        "klt_input_tracks": len(old_ids),
        "klt_forward_status_ok": int(np.sum(fwd_ok)),
        "klt_backward_status_ok": int(np.sum(back_ok)),
        "klt_fb_pass": int(np.sum(fb_ok)),
        "klt_ncc_pass": int(np.sum(ncc_ok)),
        "klt_border_pass": int(np.sum(final)),
        "klt_final_pass": int(np.sum(final)),
        "death_forward_fail": int(np.sum(exclusive["forward_fail"])),
        "death_backward_fail": int(np.sum(exclusive["backward_fail"])),
        "death_fb_fail": int(np.sum(exclusive["fb_fail"])),
        "death_ncc_fail": int(np.sum(exclusive["ncc_fail"])),
        "death_border_fail": int(np.sum(exclusive["border_fail"])),
        "median_motion_px": float(np.median(motion)) if len(motion) else float("nan"),
        "p90_motion_px": float(np.percentile(motion, 90)) if len(motion) else float("nan"),
        "max_motion_px": float(np.max(motion)) if len(motion) else float("nan"),
        "interframe_mean_absdiff": float(
            np.mean(cv2.absdiff(previous, current), dtype=np.float64)
        ),
        "interframe_mean_intensity_delta": float(
            np.mean(current, dtype=np.float64) - np.mean(previous, dtype=np.float64)
        ),
    }
    return result, reasons


def source_family(label: str) -> str:
    lowered = str(label).lower()
    if "xfeat" in lowered:
        return "xfeat_seed"
    if "learned" in lowered or "lightglue" in lowered or "loftr" in lowered:
        return "other_learned"
    return "gftt_klt"


def source_histogram(sources: list[str]) -> str:
    counts = Counter(source_family(source) for source in sources)
    return ";".join(f"{key}:{counts[key]}" for key in sorted(counts))


def finite_median(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def finite_percentile(values: list[float] | np.ndarray, percentile: float) -> float:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    return float(np.percentile(array, percentile)) if len(array) else float("nan")


def write_overlay(
    path: Path,
    gray: np.ndarray,
    tracks,
    births: set[int],
    row: dict[str, Any],
) -> None:
    canvas = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for track_id, previous, current, age, source in zip(
        tracks.ids, tracks.prev_points, tracks.points, tracks.ages, tracks.sources
    ):
        family = source_family(source)
        if family == "xfeat_seed":
            color = (255, 0, 255)
        elif int(track_id) in births:
            color = (0, 255, 0)
        elif int(age) >= 5:
            color = (255, 220, 0)
        else:
            color = (0, 180, 255)
        p0 = tuple(int(round(v)) for v in previous)
        p1 = tuple(int(round(v)) for v in current)
        cv2.line(canvas, p0, p1, color, 1, cv2.LINE_AA)
        cv2.circle(canvas, p1, 2, color, -1, cv2.LINE_AA)
    text = [
        f"{row['sequence']} {row['profile']} raw={row['raw_frame_index']}",
        (
            f"tracks={row['output_tracks']} births={row['selected_births']} "
            f"deaths={row['selected_deaths']} dropout={row['dropout_ratio']:.3f}"
        ),
        (
            f"LK in/fwd/back/fb/ncc/final={row['klt_input_tracks']}/"
            f"{row['klt_forward_status_ok']}/{row['klt_backward_status_ok']}/"
            f"{row['klt_fb_pass']}/{row['klt_ncc_pass']}/{row['klt_final_pass']}"
        ),
        (
            f"death F/B/FB/NCC/edge={row['death_forward_fail']}/"
            f"{row['death_backward_fail']}/{row['death_fb_fail']}/"
            f"{row['death_ncc_fail']}/{row['death_border_fail']} "
            f"XFeat cand/conf={row['xfeat_candidates']}/{row['xfeat_confirmed']}"
        ),
    ]
    for index, line in enumerate(text):
        y = 26 + index * 24
        cv2.putText(canvas, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 82]):
        raise OSError(f"failed to write overlay {path}")


def camera_dimensions(path: Path) -> tuple[int, int]:
    width = height = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("image_width:"):
            width = int(stripped.split(":", 1)[1])
        elif stripped.startswith("image_height:"):
            height = int(stripped.split(":", 1)[1])
    if width is None or height is None:
        raise ValueError(f"camera dimensions missing in {path}")
    return width, height


def close_selected_tracks(
    active: dict[int, dict[str, Any]],
    histogram: dict[str, Counter[int]],
    censored: dict[str, Counter[int]],
    *,
    right_censored: bool,
) -> None:
    target = censored if right_censored else histogram
    for meta in active.values():
        target[meta["source"]][int(meta["observations"])] += 1
    active.clear()


def percentile_from_counter(counter: Counter[int], q: float) -> float:
    total = sum(counter.values())
    if total == 0:
        return float("nan")
    threshold = q * (total - 1)
    cumulative = 0
    for lifetime in sorted(counter):
        next_cumulative = cumulative + counter[lifetime]
        if threshold < next_cumulative:
            return float(lifetime)
        cumulative = next_cumulative
    return float(max(counter))


def main() -> int:
    args = parse_args()
    every_n = max(1, int(args.every_n))
    frame_offset = int(args.frame_offset) % every_n
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    viz_dir = Path(args.save_viz_dir) if args.save_viz_dir else None
    cfg = load_config(args.config)
    cadence_cli_value = args.process_skipped_frames
    args.process_skipped_frames = resolve_process_skipped_frames(
        args.process_skipped_frames,
        cfg,
    )
    tracker = build_tracker(args.method, cfg)
    quality_gate_source = str(
        cfg.get("quality", {}).get("gate_source", cfg.get("quality_gate_source", "preprocessed"))
    )
    expected_width, expected_height = camera_dimensions(Path(args.camera_config))
    config_sha = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
    camera_sha = hashlib.sha256(Path(args.camera_config).read_bytes()).hexdigest()

    per_frame_path = output_dir / "per_frame.csv"
    active_selected: dict[int, dict[str, Any]] = {}
    lifetime_histogram: dict[str, Counter[int]] = defaultdict(Counter)
    censored_histogram: dict[str, Counter[int]] = defaultdict(Counter)
    death_reason_by_id: dict[int, str] = {}
    cumulative_death_reasons: Counter[str] = Counter()
    previous_processed_ids: set[int] = set()
    previous_selected_ids: set[int] = set()
    processed_frame_index = 0
    selected_frame_index = 0
    raw_image_count = 0
    selected_count = 0
    first_header_stamp = None
    last_header_stamp = None
    previous_header_stamp = None
    event_overlays = 0
    last_event_selected = -10_000
    numeric_rows: list[dict[str, Any]] = []

    with per_frame_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        with rosbag.Bag(args.bag, "r") as bag:
            for _topic, message, bag_stamp in bag.read_messages(topics=[args.image_topic]):
                raw_index = raw_image_count
                raw_image_count += 1
                if raw_index < int(args.start_raw_index):
                    continue
                if args.end_raw_index is not None and raw_index >= int(args.end_raw_index):
                    break
                if args.max_raw_frames is not None and raw_index >= int(args.start_raw_index) + int(args.max_raw_frames):
                    break
                selected = raw_index % every_n == frame_offset
                if not selected and not args.process_skipped_frames:
                    continue

                raw_gray = decode_mono8(message)
                if raw_gray.shape != (expected_height, expected_width):
                    raise ValueError(
                        f"image/calibration size mismatch at raw frame {raw_index}: "
                        f"image={raw_gray.shape[::-1]} calibration={(expected_width, expected_height)}"
                    )
                raw_quality = score_image_quality(raw_gray)
                gray = preprocess(raw_gray, args.preprocess, raw_quality)
                processed_quality = (
                    raw_quality
                    if args.preprocess == "none"
                    else score_image_quality(gray)
                )
                gate_quality = fuse_image_quality_for_gates(
                    processed_quality, raw_quality, quality_gate_source
                )
                klt = klt_backbone(tracker)
                previous_tracking_image = klt.prev_image
                interframe_mean_absdiff = (
                    float(
                        np.mean(
                            cv2.absdiff(previous_tracking_image, gray),
                            dtype=np.float64,
                        )
                    )
                    if previous_tracking_image is not None
                    else float("nan")
                )
                interframe_mean_intensity_delta = (
                    float(
                        np.mean(gray, dtype=np.float64)
                        - np.mean(previous_tracking_image, dtype=np.float64)
                    )
                    if previous_tracking_image is not None
                    else float("nan")
                )
                tracks, diagnostics = tracker.process(gray, gate_quality)
                klt_diagnostics = getattr(tracker, "_last_klt_diagnostics", diagnostics)
                transition = dict(klt.last_transition_diagnostics)
                transition["interframe_mean_absdiff"] = interframe_mean_absdiff
                transition["interframe_mean_intensity_delta"] = (
                    interframe_mean_intensity_delta
                )
                death_reasons = dict(klt.last_death_reasons)
                death_reason_by_id.update(death_reasons)
                cumulative_death_reasons.update(death_reasons.values())

                ids = set(int(value) for value in tracks.ids)
                tracker_births = ids - previous_processed_ids
                tracker_deaths = previous_processed_ids - ids
                previous_processed_ids = ids
                sources = {
                    int(track_id): source_family(source)
                    for track_id, source in zip(tracks.ids, tracks.sources)
                }
                selected_births: set[int] = set()
                selected_deaths: set[int] = set()
                if selected:
                    selected_births = ids - previous_selected_ids
                    selected_deaths = previous_selected_ids - ids
                    for track_id in selected_deaths:
                        meta = active_selected.pop(track_id, None)
                        if meta is not None:
                            lifetime_histogram[meta["source"]][int(meta["observations"])] += 1
                    for track_id in ids:
                        if track_id not in active_selected:
                            active_selected[track_id] = {
                                "source": sources.get(track_id, "gftt_klt"),
                                "observations": 1,
                            }
                        else:
                            active_selected[track_id]["observations"] += 1
                            if sources.get(track_id) == "xfeat_seed":
                                active_selected[track_id]["source"] = "xfeat_seed"
                    previous_selected_ids = ids

                header_stamp = float(message.header.stamp.to_sec())
                bag_stamp_s = float(bag_stamp.to_sec())
                if first_header_stamp is None:
                    first_header_stamp = header_stamp
                last_header_stamp = header_stamp
                frame_dt = (
                    header_stamp - previous_header_stamp
                    if previous_header_stamp is not None
                    else float("nan")
                )
                previous_header_stamp = header_stamp
                counts = Counter(sources.values())
                output_grid = grid_stats(tracks.points, gray.shape, rows=4, cols=6)
                age_ge2_mask = tracks.ages >= 2
                age_ge3_mask = tracks.ages >= 3
                age_ge2_grid = grid_stats(
                    tracks.points[age_ge2_mask],
                    gray.shape,
                    rows=4,
                    cols=6,
                )
                age_ge3_grid = grid_stats(
                    tracks.points[age_ge3_mask],
                    gray.shape,
                    rows=4,
                    cols=6,
                )
                gftt_confirmation = getattr(
                    tracker,
                    "last_confirmation_diagnostics",
                    {},
                ).get("gftt_confirmation", {})
                dropout = (
                    float(klt_diagnostics.dropped_features)
                    / max(1, int(klt_diagnostics.tracked_before_filter))
                )
                ages = tracks.ages.astype(np.float64)
                row = {
                    "sequence": args.sequence,
                    "profile": args.profile,
                    "method": args.method,
                    "preprocess": args.preprocess,
                    "process_skipped_frames": int(args.process_skipped_frames),
                    "raw_frame_index": raw_index,
                    "processed_frame_index": processed_frame_index,
                    "selected_frame_index": selected_frame_index if selected else "",
                    "selected_for_output": int(selected),
                    "header_stamp_s": f"{header_stamp:.9f}",
                    "bag_stamp_s": f"{bag_stamp_s:.9f}",
                    "header_minus_bag_s": header_stamp - bag_stamp_s,
                    "frame_dt_s": frame_dt,
                    "raw_mean_intensity": raw_quality.mean_intensity,
                    "raw_contrast": raw_quality.contrast,
                    "raw_gradient_mean": raw_quality.gradient_mean,
                    "raw_laplacian_var": raw_quality.laplacian_var,
                    "raw_underexposed_ratio": raw_quality.underexposed_ratio,
                    "raw_overexposed_ratio": raw_quality.overexposed_ratio,
                    "raw_flat_region_ratio": raw_quality.flat_region_ratio,
                    "raw_grid_texture_score": raw_quality.grid_texture_score,
                    "raw_blur_score": raw_quality.blur_score,
                    "raw_degradation_score": raw_quality.degradation_score,
                    "processed_contrast": processed_quality.contrast,
                    "processed_gradient_mean": processed_quality.gradient_mean,
                    "processed_laplacian_var": processed_quality.laplacian_var,
                    "processed_flat_region_ratio": processed_quality.flat_region_ratio,
                    "processed_grid_texture_score": processed_quality.grid_texture_score,
                    "processed_blur_score": processed_quality.blur_score,
                    "processed_degradation_score": processed_quality.degradation_score,
                    **transition,
                    "gftt_detected_births": int(klt_diagnostics.added_features),
                    "gftt_pending_candidates": int(
                        getattr(tracker, "last_candidate_bank_count", 0)
                    ),
                    "gftt_confirm_input": int(gftt_confirmation.get("pending_input", 0)),
                    "gftt_confirm_forward_pass": int(gftt_confirmation.get("forward_pass", 0)),
                    "gftt_confirm_backward_pass": int(gftt_confirmation.get("backward_pass", 0)),
                    "gftt_confirm_fb_pass": int(gftt_confirmation.get("fb_pass", 0)),
                    "gftt_confirm_ncc_pass": int(gftt_confirmation.get("ncc_pass", 0)),
                    "gftt_confirm_border_pass": int(gftt_confirmation.get("border_pass", 0)),
                    "gftt_confirm_distance_pass": int(gftt_confirmation.get("distance_pass", 0)),
                    "gftt_confirm_geometry_pass": int(gftt_confirmation.get("geometry_pass", 0)),
                    "gftt_confirm_selected": int(gftt_confirmation.get("selected", 0)),
                    "gftt_confirm_admitted": int(gftt_confirmation.get("admitted", 0)),
                    "tracker_births": len(tracker_births),
                    "tracker_deaths": len(tracker_deaths),
                    "selected_births": len(selected_births) if selected else "",
                    "selected_deaths": len(selected_deaths) if selected else "",
                    "output_tracks": len(tracks),
                    "output_grid_coverage": float(output_grid.coverage),
                    "output_age_ge2_tracks": int(np.sum(age_ge2_mask)),
                    "output_age_ge2_grid_coverage": float(age_ge2_grid.coverage),
                    "output_age_ge3_tracks": int(np.sum(age_ge3_mask)),
                    "output_age_ge3_grid_coverage": float(age_ge3_grid.coverage),
                    "output_gftt_births": counts.get("gftt_klt", 0)
                    - int(np.sum([source_family(s) == "gftt_klt" and int(a) > 1 for s, a in zip(tracks.sources, tracks.ages)])),
                    "output_klt_survivors": int(np.sum(ages > 1)),
                    "output_xfeat_tracks": counts.get("xfeat_seed", 0),
                    "output_other_learned_tracks": counts.get("other_learned", 0),
                    "median_track_age": finite_median(ages),
                    "long_track_age_ge5_ratio": float(np.mean(ages >= 5)) if len(ages) else 0.0,
                    "median_fb_error": finite_median(tracks.fb_errors),
                    "median_ncc": finite_median(tracks.ncc_scores),
                    "dropout_ratio": dropout,
                    "learned_mode": str(getattr(tracker, "last_learned_mode", "n/a")),
                    "xfeat_candidates": int(getattr(tracker, "last_learned_candidate_count", 0)),
                    "xfeat_confirmed": int(getattr(tracker, "last_confirmed_xfeat_count", 0)),
                    "pending_xfeat": int(getattr(tracker, "last_pending_xfeat_count", 0)),
                    "recovery_reason": str(getattr(tracker, "last_recovery_reason", "n/a")),
                    "source_histogram": source_histogram(tracks.sources),
                }
                writer.writerow(row)
                numeric_rows.append(row)

                if selected and viz_dir is not None:
                    periodic = selected_frame_index % max(1, int(args.save_viz_every)) == 0
                    event = (
                        dropout >= float(args.event_dropout_threshold)
                        and event_overlays < max(0, int(args.max_event_overlays))
                        and selected_frame_index - last_event_selected >= 50
                    )
                    if periodic or event:
                        suffix = "event" if event and not periodic else "periodic"
                        path = viz_dir / f"frame_{raw_index:06d}_{suffix}.jpg"
                        write_overlay(path, raw_gray, tracks, selected_births, row)
                        if event:
                            event_overlays += 1
                            last_event_selected = selected_frame_index
                processed_frame_index += 1
                if selected:
                    selected_frame_index += 1
                    selected_count += 1

    close_selected_tracks(
        active_selected,
        lifetime_histogram,
        censored_histogram,
        right_censored=True,
    )
    histogram_path = output_dir / "lifetime_histogram.csv"
    with histogram_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("sequence", "profile", "lineage", "lifetime_selected_frames", "track_count", "right_censored_count"),
        )
        writer.writeheader()
        for lineage in sorted(set(lifetime_histogram) | set(censored_histogram)):
            values = sorted(set(lifetime_histogram[lineage]) | set(censored_histogram[lineage]))
            for lifetime in values:
                writer.writerow(
                    {
                        "sequence": args.sequence,
                        "profile": args.profile,
                        "lineage": lineage,
                        "lifetime_selected_frames": lifetime,
                        "track_count": lifetime_histogram[lineage][lifetime],
                        "right_censored_count": censored_histogram[lineage][lifetime],
                    }
                )

    selected_rows = [row for row in numeric_rows if int(row["selected_for_output"]) == 1]
    complete_all = Counter()
    for counts in lifetime_histogram.values():
        complete_all.update(counts)
    complete_klt = lifetime_histogram["gftt_klt"]
    complete_xfeat = lifetime_histogram["xfeat_seed"]
    total_deaths = sum(cumulative_death_reasons.values())
    summary = {
        "sequence": args.sequence,
        "profile": args.profile,
        "method": args.method,
        "preprocess": args.preprocess,
        "process_skipped_frames": bool(args.process_skipped_frames),
        "process_skipped_frames_source": (
            "cli" if cadence_cli_value is not None else "config_or_default"
        ),
        "temporal_gftt_admission": bool(
            cfg.get("hybrid", {}).get("enable_temporal_gftt_admission", False)
        ),
        "input_bag": str(Path(args.bag).resolve()),
        "input_bag_sha256_not_computed_large_file": True,
        "image_topic": args.image_topic,
        "raw_image_messages_seen": raw_image_count,
        "processed_frames": processed_frame_index,
        "selected_frames": selected_count,
        "selected_span_s": (
            float(last_header_stamp - first_header_stamp)
            if first_header_stamp is not None and last_header_stamp is not None
            else 0.0
        ),
        "config": str(Path(args.config).resolve()),
        "config_sha256": config_sha,
        "camera_config": str(Path(args.camera_config).resolve()),
        "camera_config_sha256": camera_sha,
        "camera_dimensions": [expected_width, expected_height],
        "tracking_uses_camera_intrinsics": False,
        "klt_config": asdict(klt_backbone(tracker).config),
        "selected_median_output_tracks": statistics.median(
            int(row["output_tracks"]) for row in selected_rows
        ),
        "selected_p10_output_tracks": finite_percentile(
            [int(row["output_tracks"]) for row in selected_rows], 10
        ),
        "selected_min_output_tracks": min(
            int(row["output_tracks"]) for row in selected_rows
        ),
        "selected_median_output_grid_coverage": statistics.median(
            float(row["output_grid_coverage"]) for row in selected_rows
        ),
        "selected_p10_output_grid_coverage": finite_percentile(
            [float(row["output_grid_coverage"]) for row in selected_rows], 10
        ),
        "selected_min_output_grid_coverage": min(
            float(row["output_grid_coverage"]) for row in selected_rows
        ),
        "selected_median_age_ge2_tracks": statistics.median(
            int(row["output_age_ge2_tracks"]) for row in selected_rows
        ),
        "selected_p10_age_ge2_tracks": finite_percentile(
            [int(row["output_age_ge2_tracks"]) for row in selected_rows], 10
        ),
        "selected_median_age_ge2_grid_coverage": statistics.median(
            float(row["output_age_ge2_grid_coverage"]) for row in selected_rows
        ),
        "selected_p10_age_ge2_grid_coverage": finite_percentile(
            [float(row["output_age_ge2_grid_coverage"]) for row in selected_rows], 10
        ),
        "selected_median_age_ge3_tracks": statistics.median(
            int(row["output_age_ge3_tracks"]) for row in selected_rows
        ),
        "selected_p10_age_ge3_tracks": finite_percentile(
            [int(row["output_age_ge3_tracks"]) for row in selected_rows], 10
        ),
        "selected_median_age_ge3_grid_coverage": statistics.median(
            float(row["output_age_ge3_grid_coverage"]) for row in selected_rows
        ),
        "selected_p10_age_ge3_grid_coverage": finite_percentile(
            [float(row["output_age_ge3_grid_coverage"]) for row in selected_rows], 10
        ),
        "selected_median_births": statistics.median(
            int(row["selected_births"]) for row in selected_rows
        ),
        "selected_median_deaths": statistics.median(
            int(row["selected_deaths"]) for row in selected_rows
        ),
        "selected_total_births": sum(
            int(row["selected_births"]) for row in selected_rows
        ),
        "selected_total_deaths": sum(
            int(row["selected_deaths"]) for row in selected_rows
        ),
        "selected_median_track_age": statistics.median(
            float(row["median_track_age"]) for row in selected_rows
        ),
        "selected_median_dropout_ratio": statistics.median(
            float(row["dropout_ratio"]) for row in selected_rows
        ),
        "selected_median_long_track_age_ge5_ratio": statistics.median(
            float(row["long_track_age_ge5_ratio"]) for row in selected_rows
        ),
        "selected_median_motion_px": statistics.median(
            float(row["median_motion_px"])
            for row in selected_rows
            if math.isfinite(float(row["median_motion_px"]))
        ),
        "selected_median_raw_contrast": statistics.median(
            float(row["raw_contrast"]) for row in selected_rows
        ),
        "selected_median_raw_laplacian_var": statistics.median(
            float(row["raw_laplacian_var"]) for row in selected_rows
        ),
        "selected_median_raw_flat_region_ratio": statistics.median(
            float(row["raw_flat_region_ratio"]) for row in selected_rows
        ),
        "selected_median_raw_degradation_score": statistics.median(
            float(row["raw_degradation_score"]) for row in selected_rows
        ),
        "all_complete_track_count": sum(complete_all.values()),
        "all_lifetime_median_selected_frames": percentile_from_counter(complete_all, 0.5),
        "all_lifetime_p75_selected_frames": percentile_from_counter(complete_all, 0.75),
        "all_lifetime_p90_selected_frames": percentile_from_counter(complete_all, 0.90),
        "gftt_klt_complete_track_count": sum(complete_klt.values()),
        "gftt_klt_lifetime_median_selected_frames": percentile_from_counter(complete_klt, 0.5),
        "gftt_klt_lifetime_p75_selected_frames": percentile_from_counter(complete_klt, 0.75),
        "gftt_klt_lifetime_p90_selected_frames": percentile_from_counter(complete_klt, 0.90),
        "xfeat_complete_track_count": sum(complete_xfeat.values()),
        "xfeat_lifetime_median_selected_frames": percentile_from_counter(complete_xfeat, 0.5),
        "xfeat_lifetime_p75_selected_frames": percentile_from_counter(complete_xfeat, 0.75),
        "xfeat_lifetime_p90_selected_frames": percentile_from_counter(complete_xfeat, 0.90),
        "xfeat_candidates_total": sum(int(row["xfeat_candidates"]) for row in numeric_rows),
        "xfeat_confirmed_total": sum(int(row["xfeat_confirmed"]) for row in numeric_rows),
        "klt_death_reason_counts": dict(sorted(cumulative_death_reasons.items())),
        "klt_death_reason_fractions": {
            key: value / total_deaths if total_deaths else 0.0
            for key, value in sorted(cumulative_death_reasons.items())
        },
        "right_censored_track_count": sum(
            sum(counter.values()) for counter in censored_histogram.values()
        ),
        "per_frame_csv": str(per_frame_path.resolve()),
        "lifetime_histogram_csv": str(histogram_path.resolve()),
        "visualization_dir": str(viz_dir.resolve()) if viz_dir else None,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FRONTEND_DIAGNOSTIC_COMPLETE sequence={args.sequence} profile={args.profile}")
    print(f"per_frame={per_frame_path}")
    print(f"histogram={histogram_path}")
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
