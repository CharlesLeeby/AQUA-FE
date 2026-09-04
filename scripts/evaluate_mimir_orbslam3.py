#!/usr/bin/env python3
"""Evaluate ORB-SLAM3 MIMIR trajectories with fixed- and free-scale alignment."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gt-csv", required=True, type=Path)
    parser.add_argument("--cam-yaml", required=True, type=Path)
    parser.add_argument("--image-times", required=True, type=Path)
    parser.add_argument(
        "--trajectory",
        action="append",
        required=True,
        metavar="LABEL=PATH",
    )
    parser.add_argument("--max-time-diff", type=float, default=0.02)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def quaternion_matrix(w: float, x: float, y: float, z: float) -> np.ndarray:
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0:
        raise ValueError("zero quaternion")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


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


def align_sim3(
    source: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
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
    return (scale * (rotation @ source.T)).T + translation, rotation, scale


def rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else math.nan


def path_length(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def load_gt(path: Path, cam_yaml: Path) -> list[tuple[float, np.ndarray, np.ndarray]]:
    sensor = json.loads(cam_yaml.read_text(encoding="utf-8"))
    body_t_camera = np.asarray(sensor["T_BS"], dtype=float)
    rotation_body_camera = body_t_camera[:3, :3]
    translation_body_camera = body_t_camera[:3, 3]
    result = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            stamp = int(row["timestamp"]) * 1e-9
            position_world_body = np.asarray(
                [row["t_0_kf_X"], row["t_0_kf_Y"], row["t_0_kf_Z"]], dtype=float
            )
            rotation_world_body = quaternion_matrix(
                float(row["q_0_kf_w"]),
                float(row["q_0_kf_x"]),
                float(row["q_0_kf_y"]),
                float(row["q_0_kf_z"]),
            )
            position_world_camera = (
                position_world_body + rotation_world_body @ translation_body_camera
            )
            rotation_world_camera = rotation_world_body @ rotation_body_camera
            result.append((stamp, position_world_camera, rotation_world_camera))
    return result


def load_orb(path: Path) -> list[tuple[float, np.ndarray, np.ndarray]]:
    result = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) != 8:
            continue
        values = [float(field) for field in fields]
        stamp = values[0] * (1e-9 if values[0] > 1e12 else 1.0)
        position = np.asarray(values[1:4], dtype=float)
        rotation = quaternion_matrix(values[7], values[4], values[5], values[6])
        result.append((stamp, position, rotation))
    return result


def associate(
    estimated: list[tuple[float, np.ndarray, np.ndarray]],
    gt: list[tuple[float, np.ndarray, np.ndarray]],
    max_difference: float,
) -> list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]]:
    gt_stamps = np.asarray([row[0] for row in gt])
    pairs = []
    for stamp, position, rotation in estimated:
        index = int(np.searchsorted(gt_stamps, stamp, side="left"))
        candidates = []
        if index < len(gt):
            candidates.append(index)
        if index > 0:
            candidates.append(index - 1)
        if not candidates:
            continue
        nearest = min(candidates, key=lambda item: abs(gt_stamps[item] - stamp))
        difference = abs(float(gt_stamps[nearest] - stamp))
        if difference <= max_difference:
            pairs.append(
                (stamp, position, rotation, gt[nearest][1], gt[nearest][2], difference)
            )
    return pairs


def rotation_errors_deg(
    estimated: list[np.ndarray], target: list[np.ndarray], alignment: np.ndarray
) -> np.ndarray:
    errors = []
    for source_rotation, target_rotation in zip(estimated, target):
        residual = target_rotation.T @ alignment @ source_rotation
        cosine = float(np.clip((np.trace(residual) - 1.0) / 2.0, -1.0, 1.0))
        errors.append(math.degrees(math.acos(cosine)))
    return np.asarray(errors)


def translational_rpe(
    stamps: np.ndarray,
    estimated: np.ndarray,
    target: np.ndarray,
    delta: float,
) -> np.ndarray:
    values = []
    for index, stamp in enumerate(stamps):
        other = int(np.searchsorted(stamps, stamp + delta, side="left"))
        if other >= len(stamps):
            break
        values.append(
            np.linalg.norm(
                (estimated[other] - estimated[index]) - (target[other] - target[index])
            )
        )
    return np.asarray(values, dtype=float)


def evaluate(
    label: str,
    trajectory: Path,
    gt: list[tuple[float, np.ndarray, np.ndarray]],
    image_times: list[float],
    max_difference: float,
    rpe_delta: float,
) -> dict[str, object]:
    estimated_rows = load_orb(trajectory)
    pairs = associate(estimated_rows, gt, max_difference)
    row: dict[str, object] = {
        "method": label,
        "trajectory": str(trajectory.resolve()),
        "pose_count": len(estimated_rows),
        "matched_pose_count": len(pairs),
    }
    if len(pairs) < 3:
        row["status"] = "insufficient_matches"
        return row
    stamps = np.asarray([item[0] for item in pairs])
    estimated = np.stack([item[1] for item in pairs])
    estimated_rotations = [item[2] for item in pairs]
    target = np.stack([item[3] for item in pairs])
    target_rotations = [item[4] for item in pairs]
    differences = np.asarray([item[5] for item in pairs])
    se3_points, se3_rotation = align_se3(estimated, target)
    sim3_points, sim3_rotation, sim3_scale = align_sim3(estimated, target)
    se3_ape = np.linalg.norm(se3_points - target, axis=1)
    sim3_ape = np.linalg.norm(sim3_points - target, axis=1)
    se3_rpe = translational_rpe(stamps, se3_points, target, rpe_delta)
    sim3_rpe = translational_rpe(stamps, sim3_points, target, rpe_delta)
    # Fit orientation alignment independently. Position-only monocular methods can
    # have a noisy translational Horn alignment whose rotation is not the best
    # constant frame transform for attitude diagnostics.
    relative_rotations = np.stack(
        [target_rotation @ source_rotation.T for source_rotation, target_rotation in zip(
            estimated_rotations, target_rotations
        )]
    )
    orientation_alignment = project_rotation(relative_rotations.sum(axis=0))
    orientation_error = rotation_errors_deg(
        estimated_rotations, target_rotations, orientation_alignment
    )
    gt_path = path_length(target)
    estimated_path = path_length(estimated)
    first_image = image_times[0]
    last_image = image_times[-1]
    row.update(
        {
            "status": "ok",
            "max_timestamp_error_s": float(differences.max()),
            "output_coverage_ratio": len(pairs) / len(image_times),
            "first_output_delay_s": max(0.0, float(stamps[0] - first_image)),
            "last_output_early_s": max(0.0, float(last_image - stamps[-1])),
            "matched_gt_path_m": gt_path,
            "estimated_path_m": estimated_path,
            "path_length_ratio_est_gt": estimated_path / gt_path if gt_path else math.nan,
            "se3_ape_rmse_m": rmse(se3_ape),
            "se3_ape_median_m": float(np.median(se3_ape)),
            "se3_rpe_1s_rmse_m": rmse(se3_rpe),
            "sim3_scale_est_to_gt": sim3_scale,
            "scale_inflation_est_over_gt": 1.0 / sim3_scale if sim3_scale else math.nan,
            "sim3_ape_rmse_m": rmse(sim3_ape),
            "sim3_ape_median_m": float(np.median(sim3_ape)),
            "sim3_rpe_1s_rmse_m": rmse(sim3_rpe),
            "orientation_residual_median_deg": float(np.median(orientation_error)),
            "orientation_residual_p95_deg": float(np.percentile(orientation_error, 95)),
        }
    )
    return row


def main() -> int:
    args = parse_args()
    trajectories = []
    for value in args.trajectory:
        if "=" not in value:
            raise SystemExit(f"invalid --trajectory {value!r}; expected LABEL=PATH")
        label, raw_path = value.split("=", 1)
        path = Path(raw_path)
        if not label or not path.is_file():
            raise SystemExit(f"invalid or missing trajectory: {value}")
        trajectories.append((label, path))
    gt = load_gt(args.gt_csv, args.cam_yaml)
    image_times = [
        int(line) * 1e-9
        for line in args.image_times.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    rows = [
        evaluate(
            label,
            path,
            gt,
            image_times,
            args.max_time_diff,
            args.rpe_delta_s,
        )
        for label, path in trajectories
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with (args.output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
