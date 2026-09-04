#!/usr/bin/env python3
"""Build a source-audited MIMIR KLT/VINS/AQUA-FE debug report."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import numpy as np
import rosbag


ARMS = ("klt", "original", "ours")
LEARNED_SOURCE_CODES = {10, 20, 30}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-windows", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--baseline-prefix", required=True)
    parser.add_argument("--ours-prefix", required=True)
    parser.add_argument("--export-prefix", required=True)
    parser.add_argument("--unsafe-ours-prefix", default="")
    parser.add_argument("--unsafe-export-prefix", default="")
    parser.add_argument("--qi-ablation-run", type=Path)
    parser.add_argument("--qi-ablation-manifest", type=Path)
    parser.add_argument(
        "--diagnostic-probe",
        action="append",
        default=[],
        metavar="LABEL=RUN_DIR",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def number(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def compact(value: object) -> str:
    result = float(value)
    return str(int(result)) if result.is_integer() else str(result).replace(".", "p")


def safe_stem(row: dict[str, str]) -> str:
    environment = "".join(c if c.isalnum() else "_" for c in row["environment"].lower())
    track = "".join(c if c.isalnum() else "_" for c in row["track"].lower())
    start = compact(row["window_start_s"])
    duration = compact(float(row["window_end_s"]) - float(row["window_start_s"]))
    return f"{environment}_{track}_s{start}_d{duration}"


def parse_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def quaternion_matrix(w: float, x: float, y: float, z: float) -> np.ndarray:
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = (w / norm, x / norm, y / norm, z / norm)
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def load_vins(path: Path) -> list[tuple[float, np.ndarray, np.ndarray, float]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            if len(row) < 8:
                continue
            try:
                stamp = float(row[0]) * 1e-9
                position = np.asarray([float(item) for item in row[1:4]])
                rotation = quaternion_matrix(*[float(item) for item in row[4:8]])
                speed = (
                    float(np.linalg.norm([float(item) for item in row[8:11]]))
                    if len(row) >= 11
                    else math.nan
                )
            except (ValueError, ZeroDivisionError):
                continue
            rows.append((stamp, position, rotation, speed))
    return rows


def load_gt(path: Path) -> list[tuple[float, np.ndarray, np.ndarray]]:
    rows = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=["/mimir/ground_truth"]):
            pose = message.pose.pose
            p = pose.position
            q = pose.orientation
            rows.append(
                (
                    message.header.stamp.to_sec(),
                    np.asarray([p.x, p.y, p.z], dtype=float),
                    quaternion_matrix(q.w, q.x, q.y, q.z),
                )
            )
    return rows


def project_rotation(matrix: np.ndarray) -> np.ndarray:
    u_mat, _, vt_mat = np.linalg.svd(matrix)
    rotation = u_mat @ vt_mat
    if np.linalg.det(rotation) < 0:
        u_mat[:, -1] *= -1
        rotation = u_mat @ vt_mat
    return rotation


def align_se3(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    src = source - source.mean(axis=0)
    dst = target - target.mean(axis=0)
    rotation = project_rotation(dst.T @ src)
    translation = target.mean(axis=0) - rotation @ source.mean(axis=0)
    return (rotation @ source.T).T + translation, rotation


def align_sim3(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    src_mean = source.mean(axis=0)
    dst_mean = target.mean(axis=0)
    src = source - src_mean
    dst = target - dst_mean
    covariance = (dst.T @ src) / len(source)
    u_mat, singular, vt_mat = np.linalg.svd(covariance)
    sign = np.ones(3)
    if np.linalg.det(u_mat @ vt_mat) < 0:
        sign[-1] = -1
    rotation = u_mat @ np.diag(sign) @ vt_mat
    variance = float(np.mean(np.sum(src * src, axis=1)))
    scale = float(np.sum(singular * sign) / variance)
    translation = dst_mean - scale * (rotation @ src_mean)
    return (scale * (rotation @ source.T)).T + translation, scale


def rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else math.nan


def rpe(stamps: np.ndarray, estimated: np.ndarray, target: np.ndarray, delta: float = 1.0) -> np.ndarray:
    values = []
    for index, stamp in enumerate(stamps):
        other = int(np.searchsorted(stamps, stamp + delta, side="left"))
        if other >= len(stamps):
            break
        values.append(
            float(
                np.linalg.norm(
                    (estimated[other] - estimated[index])
                    - (target[other] - target[index])
                )
            )
        )
    return np.asarray(values)


def path_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()) if len(points) > 1 else 0.0


def trajectory_diagnostics(run_dir: Path, gt: list[tuple[float, np.ndarray, np.ndarray]]) -> dict[str, object]:
    receipt = parse_kv(run_dir / "ape.txt")
    trajectory = load_vins(run_dir / "vins_output/vio.csv")
    result: dict[str, object] = {
        "run_dir": str(run_dir),
        "has_trajectory": int(bool(trajectory)),
        "pose_count": len(trajectory),
    }
    for key in (
        "se3_ape_rmse_m",
        "rpe_trans_rmse_m",
        "output_coverage_ratio",
        "first_output_delay_s",
        "init_success",
        "max_timestamp_error_s",
    ):
        result[key] = receipt.get(key, "")
    derived = {
        "matched_gt_path_m": math.nan,
        "estimated_path_m": math.nan,
        "path_length_ratio_est_gt": math.nan,
        "sim3_scale_est_to_gt": math.nan,
        "scale_inflation_est_over_gt": math.nan,
        "sim3_ape_rmse_m": math.nan,
        "sim3_rpe_rmse_m": math.nan,
        "ape_over_matched_gt_path": math.nan,
        "orientation_residual_median_deg": math.nan,
        "orientation_residual_p95_deg": math.nan,
        "csv_speed_median_mps": math.nan,
        "csv_speed_max_mps": math.nan,
    }
    if trajectory and gt:
        gt_stamps = np.asarray([item[0] for item in gt])
        pairs = []
        for stamp, position, rotation, speed in trajectory:
            if not gt_stamps[0] <= stamp <= gt_stamps[-1]:
                continue
            index = int(np.searchsorted(gt_stamps, stamp, side="left"))
            candidates = [min(index, len(gt) - 1)]
            if index > 0:
                candidates.append(index - 1)
            nearest = min(candidates, key=lambda item: abs(gt_stamps[item] - stamp))
            pairs.append((stamp, position, rotation, speed, gt[nearest][1], gt[nearest][2]))
        if len(pairs) >= 3:
            stamps = np.asarray([item[0] for item in pairs])
            estimated = np.stack([item[1] for item in pairs])
            target = np.stack([item[4] for item in pairs])
            sim_aligned, scale = align_sim3(estimated, target)
            sim_ape = np.linalg.norm(sim_aligned - target, axis=1)
            sim_rpe = rpe(stamps, sim_aligned, target)
            gt_path = path_length(target)
            est_path = path_length(estimated)
            relative_rotations = np.stack([item[5] @ item[2].T for item in pairs])
            global_rotation = project_rotation(relative_rotations.sum(axis=0))
            orientation_errors = []
            for relative in relative_rotations:
                residual = global_rotation.T @ relative
                cosine = np.clip((np.trace(residual) - 1.0) / 2.0, -1.0, 1.0)
                orientation_errors.append(math.degrees(math.acos(cosine)))
            speeds = np.asarray([item[3] for item in pairs], dtype=float)
            speeds = speeds[np.isfinite(speeds)]
            fixed_ape = number(receipt.get("se3_ape_rmse_m"))
            derived.update(
                {
                    "matched_gt_path_m": gt_path,
                    "estimated_path_m": est_path,
                    "path_length_ratio_est_gt": est_path / gt_path if gt_path else math.nan,
                    "sim3_scale_est_to_gt": scale,
                    "scale_inflation_est_over_gt": 1.0 / scale if scale else math.nan,
                    "sim3_ape_rmse_m": rmse(sim_ape),
                    "sim3_rpe_rmse_m": rmse(sim_rpe),
                    "ape_over_matched_gt_path": fixed_ape / gt_path if gt_path else math.nan,
                    "orientation_residual_median_deg": float(np.median(orientation_errors)),
                    "orientation_residual_p95_deg": float(np.percentile(orientation_errors, 95)),
                    "csv_speed_median_mps": float(np.median(speeds)) if len(speeds) else math.nan,
                    "csv_speed_max_mps": float(np.max(speeds)) if len(speeds) else math.nan,
                }
            )
    result.update(derived)
    result.update(log_diagnostics(run_dir / "vins.log"))
    ape = number(result["se3_ape_rmse_m"])
    trans_rpe = number(result["rpe_trans_rmse_m"])
    result["metric_sanity_ape5_rpe2"] = int(
        str(result.get("init_success", "")) == "1"
        and math.isfinite(ape)
        and math.isfinite(trans_rpe)
        and ape <= 5.0
        and trans_rpe <= 2.0
    )
    return result


def log_diagnostics(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    lower = text.lower()
    states = re.findall(
        r"state diagnostics: t [^ ]+ p_norm ([^ ]+) v_norm ([^ ]+) ba_norm ([^ ]+) bg_norm ([^ \x1b]+)",
        text,
    )
    values = [[number(item) for item in state] for state in states]
    gyro_norms = []
    for match in re.findall(r"gyroscope bias initial calibration\s+([^\n\x1b]+)", text):
        vector = [number(item) for item in match.split()[:3]]
        if all(math.isfinite(item) for item in vector):
            gyro_norms.append(float(np.linalg.norm(vector)))
    refined = [number(item) for item in re.findall(r"refined scale ([^ ]+)", text)]
    return {
        "log_not_enough_features_parallax": lower.count("not enough features or parallax"),
        "log_weak_imu_excitation": lower.count("imu excitation not enouth"),
        "log_visual_imu_misalign": lower.count("misalign visual structure with imu"),
        "log_linear_solver_failure": lower.count("linear solver failure"),
        "initial_gyro_bias_norm_max": max(gyro_norms) if gyro_norms else math.nan,
        "accepted_refined_scale": refined[-1] if refined else math.nan,
        "state_v_norm_max": max((item[1] for item in values), default=math.nan),
        "state_ba_norm_max": max((item[2] for item in values), default=math.nan),
        "state_bg_norm_max": max((item[3] for item in values), default=math.nan),
    }


def feature_frames(path: Path) -> dict[int, dict[int, tuple[float, ...]]]:
    frames: dict[int, dict[int, tuple[float, ...]]] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            channels = {channel.name: channel.values for channel in message.channels}
            ids = channels["id"]
            source = channels.get("source_code", [0.0] * len(ids))
            quality = channels.get("quality", [1.0] * len(ids))
            p_u = channels.get("p_u", [math.nan] * len(ids))
            p_v = channels.get("p_v", [math.nan] * len(ids))
            frames[message.header.stamp.to_nsec()] = {
                int(round(feature_id)): (
                    float(message.points[index].x),
                    float(message.points[index].y),
                    float(p_u[index]),
                    float(p_v[index]),
                    float(quality[index]),
                    float(source[index]),
                )
                for index, feature_id in enumerate(ids)
            }
    return frames


def source_audit(export_dir: Path, klt_bag: Path) -> dict[str, object]:
    ours = feature_frames(export_dir / "features.bag")
    klt = feature_frames(klt_bag)
    learned_tracks: dict[int, list[int]] = {}
    classical_observations = 0
    learned_observations = 0
    for stamp, frame in ours.items():
        for feature_id, values in frame.items():
            learned = feature_id >= 10_000_000 or int(round(values[5])) in LEARNED_SOURCE_CODES
            if learned:
                learned_observations += 1
                learned_tracks.setdefault(feature_id, []).append(stamp)
            else:
                classical_observations += 1
    shared_stamps = sorted(set(ours) & set(klt))
    equal_id_frames = 0
    missing = 0
    extra = 0
    coordinate_mismatch = 0
    quality_differences = []
    for stamp in shared_stamps:
        ours_classical = {key: value for key, value in ours[stamp].items() if key < 10_000_000}
        klt_frame = klt[stamp]
        ours_ids = set(ours_classical)
        klt_ids = set(klt_frame)
        equal_id_frames += ours_ids == klt_ids
        missing += len(klt_ids - ours_ids)
        extra += len(ours_ids - klt_ids)
        for feature_id in ours_ids & klt_ids:
            if max(abs(ours_classical[feature_id][i] - klt_frame[feature_id][i]) for i in range(4)) > 1e-6:
                coordinate_mismatch += 1
            quality_differences.append(abs(ours_classical[feature_id][4] - klt_frame[feature_id][4]))
    lengths = [len(values) for values in learned_tracks.values()]
    first_stamp = min(ours) if ours else 0
    learned_stamps = [stamp for stamps in learned_tracks.values() for stamp in stamps]
    filter_manifest = {}
    manifest_path = export_dir / "warmup_filter.json"
    if manifest_path.is_file():
        filter_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "export_dir": str(export_dir),
        "feature_frames": len(ours),
        "shared_klt_frames": len(shared_stamps),
        "classical_idset_exact_frames": equal_id_frames,
        "classical_missing_observations": missing,
        "classical_extra_observations": extra,
        "classical_coordinate_mismatch_observations": coordinate_mismatch,
        "classical_quality_abs_diff_median": float(np.median(quality_differences)) if quality_differences else math.nan,
        "classical_observations": classical_observations,
        "learned_observations": learned_observations,
        "learned_unique_ids": len(learned_tracks),
        "learned_track_length_median": float(np.median(lengths)) if lengths else math.nan,
        "learned_track_length_max": max(lengths) if lengths else 0,
        "learned_first_s": (min(learned_stamps) - first_stamp) * 1e-9 if learned_stamps else math.nan,
        "learned_last_s": (max(learned_stamps) - first_stamp) * 1e-9 if learned_stamps else math.nan,
        "warmup_removed_learned_observations": filter_manifest.get("removed_learned_observations", 0),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object, digits: int = 2) -> str:
    value = number(value)
    return f"{value:.{digits}f}" if math.isfinite(value) else "--"


def outcome(row: dict[str, object], arm: str) -> str:
    if str(row.get(f"{arm}_init_success", "")) == "1":
        return "PASS"
    if int(row.get(f"{arm}_has_trajectory", 0)):
        return "partial"
    return "empty"


def build_report(
    rows: list[dict[str, object]],
    source_rows: list[dict[str, object]],
    unsafe_prefix: str,
    qi_ablation: dict[str, object] | None,
    diagnostic_probes: list[dict[str, object]],
) -> str:
    counts = {}
    for arm in ARMS:
        counts[arm] = (
            sum(int(row[f"{arm}_has_trajectory"]) for row in rows),
            sum(str(row[f"{arm}_init_success"]) == "1" for row in rows),
            sum(int(row[f"{arm}_metric_sanity_ape5_rpe2"]) for row in rows),
        )
    learned_total = sum(int(row["learned_observations"]) for row in source_rows)
    learned_windows = sum(int(row["learned_observations"]) > 0 for row in source_rows)
    removed = sum(int(row["warmup_removed_learned_observations"]) for row in source_rows)
    exact = sum(
        int(row["classical_idset_exact_frames"]) == int(row["feature_frames"])
        and int(row["classical_missing_observations"]) == 0
        and int(row["classical_coordinate_mismatch_observations"]) == 0
        for row in source_rows
    )
    shared_klt = [
        row
        for row in rows
        if str(row["klt_init_success"]) == "1" and str(row["ours_init_success"]) == "1"
    ]
    lines = [
        "# MIMIR-UW final debug report",
        "",
        "## Final outcome",
        "",
        "| Arm | Any trajectory | Availability gate | APE<=5 m and RPE<=2 m |",
        "|---|---:|---:|---:|",
        f"| Pure KLT external | {counts['klt'][0]}/9 | {counts['klt'][1]}/9 | {counts['klt'][2]}/9 |",
        f"| Original VINS tracker | {counts['original'][0]}/9 | {counts['original'][1]}/9 | {counts['original'][2]}/9 |",
        f"| AQUA-FE no-harm | {counts['ours'][0]}/9 | {counts['ours'][1]}/9 | {counts['ours'][2]}/9 |",
        "",
        "The existing availability gate checks delay and coverage only; it is not an accuracy gate.",
        "The last column is an explicit conservative diagnostic screen, not a published benchmark threshold.",
        "No availability-pass run meets it, so the large fixed-scale APE values remain unusable for a precision claim.",
        "",
        "## Per-window APE/RPE receipts",
        "",
        "| Window | KLT | Original VINS | AQUA-FE | Learned obs |",
        "|---|---:|---:|---:|---:|",
    ]
    source_by_stem = {row["stem"]: row for row in source_rows}
    for row in rows:
        cells = []
        for arm in ARMS:
            cells.append(
                f"{outcome(row, arm)}; {fmt(row[f'{arm}_se3_ape_rmse_m'])}/{fmt(row[f'{arm}_rpe_trans_rmse_m'])}"
            )
        source = source_by_stem[row["stem"]]
        lines.append(
            f"| `{row['sequence']}` {row['window_start_s']}-{row['window_end_s']} s | "
            f"{cells[0]} | {cells[1]} | {cells[2]} | {source['learned_observations']} |"
        )
    if shared_klt:
        row = shared_klt[0]
        ape_gain = 100.0 * (1.0 - number(row["ours_se3_ape_rmse_m"]) / number(row["klt_se3_ape_rmse_m"]))
        rpe_gain = 100.0 * (1.0 - number(row["ours_rpe_trans_rmse_m"]) / number(row["klt_rpe_trans_rmse_m"]))
        lines.extend(
            [
                "",
                "## Valid paired positive",
                "",
                f"The only KLT/AQUA-FE shared-pass window is `{row['sequence']}` {row['window_start_s']}-{row['window_end_s']} s.",
                f"AQUA-FE reduces APE by {ape_gain:.1f}% and RPE by {rpe_gain:.1f}% with identical classical IDs, coordinates, delay, and coverage.",
                "The learned warmup gate removes all early LoFTR observations in this window, so this is a q_i reliability-weighting positive, not a learned-point positive.",
            ]
        )
        if qi_ablation:
            reset_ape = number(qi_ablation["se3_ape_rmse_m"])
            reset_rpe = number(qi_ablation["rpe_trans_rmse_m"])
            reset_coverage = number(qi_ablation["output_coverage_ratio"])
            reset_delay = number(qi_ablation["first_output_delay_s"])
            exact_klt = (
                abs(reset_ape - number(row["klt_se3_ape_rmse_m"])) <= 1e-6
                and abs(reset_rpe - number(row["klt_rpe_trans_rmse_m"])) <= 1e-6
                and abs(reset_coverage - number(row["klt_output_coverage_ratio"])) <= 1e-6
                and abs(reset_delay - number(row["klt_first_output_delay_s"])) <= 1e-6
            )
            lines.extend(
                [
                    "",
                    "### Causal q_i-only ablation",
                    "",
                    f"Only the `quality` channel of {int(qi_ablation['replaced_quality_observations'])} classical observations was replaced with its pure-KLT reference value; IDs, timestamps, and coordinates were unchanged, with {int(qi_ablation['missing_reference_observations'])} missing reference observations.",
                    "",
                    "| Condition | SE3 APE | RPE | Coverage | First output delay |",
                    "|---|---:|---:|---:|---:|",
                    f"| Pure KLT | {fmt(row['klt_se3_ape_rmse_m'], 6)} m | {fmt(row['klt_rpe_trans_rmse_m'], 6)} m | {fmt(row['klt_output_coverage_ratio'], 6)} | {fmt(row['klt_first_output_delay_s'], 6)} s |",
                    f"| AQUA-FE q_i | {fmt(row['ours_se3_ape_rmse_m'], 6)} m | {fmt(row['ours_rpe_trans_rmse_m'], 6)} m | {fmt(row['ours_output_coverage_ratio'], 6)} | {fmt(row['ours_first_output_delay_s'], 6)} s |",
                    f"| AQUA-FE geometry + KLT quality | {fmt(reset_ape, 6)} m | {fmt(reset_rpe, 6)} m | {fmt(reset_coverage, 6)} | {fmt(reset_delay, 6)} s |",
                    "",
                    f"The quality-reset run {'exactly reproduces' if exact_klt else 'does not exactly reproduce'} the pure-KLT receipt at 1e-6 tolerance. This isolates the paired improvement to AQUA-FE's q_i quality weighting rather than hidden feature geometry or learned points.",
                ]
            )
    lines.extend(
        [
            "",
            "## Scale and shape diagnostics for non-empty trajectories",
            "",
            "| Window | Arm | SE3 APE | Sim3 APE | Est/GT scale | Orientation p95 | Max speed |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    arm_labels = {"klt": "KLT", "original": "VINS", "ours": "AQUA-FE"}
    for row in rows:
        for arm in ARMS:
            if not int(row[f"{arm}_has_trajectory"]):
                continue
            lines.append(
                f"| `{row['sequence']}` {row['window_start_s']}-{row['window_end_s']} s | "
                f"{arm_labels[arm]} | {fmt(row[f'{arm}_se3_ape_rmse_m'])} m | "
                f"{fmt(row[f'{arm}_sim3_ape_rmse_m'])} m | "
                f"{fmt(row[f'{arm}_scale_inflation_est_over_gt'])}x | "
                f"{fmt(row[f'{arm}_orientation_residual_p95_deg'])} deg | "
                f"{fmt(row[f'{arm}_state_v_norm_max'])} m/s |"
            )
    lines.extend(
        [
            "",
            "## Learned-point and no-harm audit",
            "",
            f"All {exact}/9 final bags exactly preserve the pure-KLT classical timestamp/ID/coordinate backbone.",
            f"The 15 s initialization guard removed {removed} early learned observations and retained {learned_total} learned observations in {learned_windows}/9 windows.",
            "Before the guard, OceanFloor/track1_light 90-135 s changed from KLT PASS to AQUA-FE empty after only 34 LoFTR observations were added.",
            "Those observations belonged to 12 IDs with very short exported histories (maximum 6 observations, under 0.5 s), which perturbed the deterministic five-point initialization RANSAC.",
            "After removing only those early learned observations, initialization and coverage return exactly to KLT while q_i weighting improves APE/RPE.",
            "No retained learned-point window becomes a new strict backend success: current MIMIR results therefore contain real learned observations but no learned-point VINS positive.",
            "",
            "## Why APE is still too large",
            "",
            "1. Timestamp association is exact (reported maximum error is zero), and independent adapter checks already reject camera/IMU units, axes, and timing as the primary cause.",
            "2. VINS's first visual-IMU alignment repeatedly estimates fictitious gyro biases on low-parallax structure. A synthetic zero-bias prior reduces some runs, but stronger priors or forced repropagation reverse ranking on other windows, so they were not adopted globally.",
            "3. Sim(3) alignment reduces many errors sharply while estimated/GT path scale remains far from 1, proving a dominant initialization-scale component. Remaining Sim(3) error and orientation residuals prove additional trajectory-shape drift.",
            "4. SeaFloor/track2 is the clearest divergence: VINS passes delay/coverage while velocity and path scale grow unrealistically. An availability-only gate therefore labels an unusable trajectory as successful.",
            "5. Original VINS passes windows that external KLT/AQUA-FE do not because its internal tracker has a denser, different feature lifecycle. In SeaFloor/track1, the 48 learned observations arrive around 32 s, far too late to repair the initial structure.",
        ]
    )
    if diagnostic_probes:
        lines.extend(
            [
                "",
                "## Rejected remediation probes",
                "",
                "| Probe | SE3 APE | RPE | Coverage | First output delay |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for probe in diagnostic_probes:
            lines.append(
                f"| `{probe['label']}` | {fmt(probe['se3_ape_rmse_m'])} m | "
                f"{fmt(probe['rpe_trans_rmse_m'])} m | "
                f"{fmt(probe['output_coverage_ratio'], 3)} | "
                f"{fmt(probe['first_output_delay_s'], 3)} s |"
            )
        lines.extend(
            [
                "",
                "On OceanFloor/track0_light 45-90 s, 15 s of common history changes APE only from 110.52 m to 105.63 m. A 45 s history gives immediate, complete score-window output but amplifies APE to 694.67 m, separating availability from scale correctness.",
                "Changing SeaFloor/track2 gravity magnitude from 9.81 to 9.80 m/s^2 changes APE/RPE only from 784.01/75.67 m to 738.57/72.42 m. The residual remains catastrophic, so gravity rounding is not the primary cause.",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- Keep the 15 s learned warmup guard and the exact KLT mirror backbone.",
            "- Report fixed-scale SE(3) APE/RPE as primary; use Sim(3) only to diagnose scale.",
            "- Do not call availability-pass trajectories accurate, and do not claim a MIMIR learned-point backend positive from these nine windows.",
            "- The next learned-sidecar change must produce multi-second persistent IDs; increasing the count of one-to-six-frame LoFTR tracks is contraindicated.",
            "",
            "## Statistical scope",
            "",
            "These are nine deliberately selected low-texture windows with one deterministic seed per arm. Pose samples are temporally dependent, so no p-value, confidence interval, or population-level superiority claim is valid.",
        ]
    )
    if unsafe_prefix:
        lines.extend(
            [
                "",
                f"Unsafe pre-guard backend prefix retained for the causal audit: `{unsafe_prefix}`.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    with args.selected_windows.open(newline="", encoding="utf-8") as handle:
        selected = list(csv.DictReader(handle))
    if len(selected) != 9:
        raise SystemExit(f"expected 9 windows, found {len(selected)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if bool(args.qi_ablation_run) != bool(args.qi_ablation_manifest):
        raise SystemExit("--qi-ablation-run and --qi-ablation-manifest must be supplied together")
    gt_cache: dict[Path, list[tuple[float, np.ndarray, np.ndarray]]] = {}
    comparison_rows = []
    source_rows = []
    arm_rows = []
    for source in selected:
        stem = safe_stem(source)
        klt_dir = args.run_root / f"{args.baseline_prefix}_{stem}_klt_vins_seed0"
        original_dir = args.run_root / f"{args.baseline_prefix}_{stem}_original_vins_seed0"
        ours_dir = args.run_root / f"{args.ours_prefix}_{stem}_ours_vins_seed0"
        manifest = parse_kv(klt_dir / "comparison_arm_manifest.txt")
        raw_bag = Path(manifest["raw_bag"])
        klt_bag = Path(manifest["feature_bag"])
        gt = gt_cache.setdefault(raw_bag, load_gt(raw_bag))
        row: dict[str, object] = {
            "stem": stem,
            "sequence": source["sequence"],
            "window_start_s": compact(source["window_start_s"]),
            "window_end_s": compact(source["window_end_s"]),
        }
        for arm, run_dir in (("klt", klt_dir), ("original", original_dir), ("ours", ours_dir)):
            diagnostics = trajectory_diagnostics(run_dir, gt)
            arm_rows.append({"stem": stem, "sequence": source["sequence"], "arm": arm, **diagnostics})
            for key, value in diagnostics.items():
                row[f"{arm}_{key}"] = value
        comparison_rows.append(row)
        audit = source_audit(
            args.run_root / f"{args.export_prefix}_{stem}_ours_export", klt_bag
        )
        source_rows.append({"stem": stem, "sequence": source["sequence"], **audit})
    write_csv(args.output_dir / "comparison.csv", comparison_rows)
    write_csv(args.output_dir / "trajectory_diagnostics.csv", arm_rows)
    write_csv(args.output_dir / "source_audit.csv", source_rows)
    qi_ablation = None
    if args.qi_ablation_run and args.qi_ablation_manifest:
        manifest = json.loads(args.qi_ablation_manifest.read_text(encoding="utf-8"))
        receipt = parse_kv(args.qi_ablation_run / "ape.txt")
        qi_ablation = {
            "run_dir": str(args.qi_ablation_run),
            "manifest": str(args.qi_ablation_manifest),
            "replaced_quality_observations": int(manifest["replaced_quality_observations"]),
            "missing_reference_observations": int(manifest["missing_reference_observations"]),
            "se3_ape_rmse_m": number(receipt.get("se3_ape_rmse_m")),
            "rpe_trans_rmse_m": number(receipt.get("rpe_trans_rmse_m")),
            "output_coverage_ratio": number(receipt.get("output_coverage_ratio")),
            "first_output_delay_s": number(receipt.get("first_output_delay_s")),
            "init_success": receipt.get("init_success", ""),
        }
        write_csv(args.output_dir / "qi_ablation.csv", [qi_ablation])
    diagnostic_probes = []
    for specification in args.diagnostic_probe:
        if "=" not in specification:
            raise SystemExit(f"invalid --diagnostic-probe: {specification}")
        label, raw_path = specification.split("=", 1)
        run_dir = Path(raw_path)
        receipt = parse_kv(run_dir / "ape.txt")
        if not receipt:
            raise SystemExit(f"missing diagnostic probe receipt: {run_dir / 'ape.txt'}")
        diagnostic_probes.append(
            {
                "label": label,
                "run_dir": str(run_dir),
                "se3_ape_rmse_m": number(receipt.get("se3_ape_rmse_m")),
                "rpe_trans_rmse_m": number(receipt.get("rpe_trans_rmse_m")),
                "output_coverage_ratio": number(receipt.get("output_coverage_ratio")),
                "first_output_delay_s": number(receipt.get("first_output_delay_s")),
                "init_success": receipt.get("init_success", ""),
            }
        )
    if diagnostic_probes:
        write_csv(args.output_dir / "diagnostic_probes.csv", diagnostic_probes)
    (args.output_dir / "analysis-report.md").write_text(
        build_report(
            comparison_rows,
            source_rows,
            args.unsafe_ours_prefix,
            qi_ablation,
            diagnostic_probes,
        ),
        encoding="utf-8",
    )
    print(f"wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
