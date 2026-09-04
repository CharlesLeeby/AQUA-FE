#!/usr/bin/env python3
"""Derive a deterministic gravity-aligned MSCKF initial state from IMU data."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rosbag
import yaml
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", required=True)
    parser.add_argument("--imu-topic", default="/rtimulib_node/imu")
    parser.add_argument("--gt-topic", default="/aqualoc/colmap_gt")
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument(
        "--mode",
        choices=("imu_only", "gt_calibrated"),
        default="imu_only",
    )
    parser.add_argument("--prior-yaml")
    parser.add_argument("--gt-imu-window-s", type=float, default=0.05)
    parser.add_argument("--gt-velocity-samples", type=int, default=3)
    parser.add_argument(
        "--bias-json",
        help="Optional independent calibration report providing accelerometer and gyroscope bias.",
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-yaml", required=True)
    return parser.parse_args()


def gravity_aligned_jpl_quaternion(acceleration: np.ndarray) -> np.ndarray:
    """Return JPL xyzw whose rotation maps global gravity into IMU axes."""
    acceleration = np.asarray(acceleration, dtype=float)
    if acceleration.shape != (3,) or not np.all(np.isfinite(acceleration)):
        raise ValueError("acceleration must be a finite 3-vector")
    norm = float(np.linalg.norm(acceleration))
    if norm < 1e-6:
        raise ValueError("acceleration norm is too small for gravity alignment")

    z_in_imu = acceleration / norm
    reference = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(reference, z_in_imu))) > 0.95:
        reference = np.array([0.0, 1.0, 0.0])
    x_in_imu = reference - z_in_imu * float(np.dot(reference, z_in_imu))
    x_in_imu /= np.linalg.norm(x_in_imu)
    y_in_imu = np.cross(z_in_imu, x_in_imu)
    y_in_imu /= np.linalg.norm(y_in_imu)

    rotation_global_to_imu = np.column_stack(
        [x_in_imu, y_in_imu, z_in_imu]
    )
    if np.linalg.det(rotation_global_to_imu) < 0.999999:
        raise ValueError("failed to construct a proper gravity-aligned rotation")

    # MSCKF-DVIO stores a JPL G->I quaternion. Its numeric xyzw values equal
    # the Hamilton quaternion of the inverse I->G rotation.
    quaternion = Rotation.from_matrix(rotation_global_to_imu.T).as_quat()
    if quaternion[3] < 0.0:
        quaternion *= -1.0
    return quaternion


def rotation_between_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    if source.shape != (3,) or target.shape != (3,):
        raise ValueError("rotation vectors must be 3-vectors")
    source_norm = np.linalg.norm(source)
    target_norm = np.linalg.norm(target)
    if source_norm < 1e-12 or target_norm < 1e-12:
        raise ValueError("rotation vectors must be nonzero")
    source = source / source_norm
    target = target / target_norm
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if sine < 1e-12:
        if cosine > 0.0:
            return np.eye(3)
        reference = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(reference, source))) > 0.9:
            reference = np.array([0.0, 1.0, 0.0])
        axis = np.cross(source, reference)
        axis /= np.linalg.norm(axis)
        return Rotation.from_rotvec(math.pi * axis).as_matrix()
    axis = cross / sine
    angle = math.atan2(sine, cosine)
    return Rotation.from_rotvec(angle * axis).as_matrix()


def _read_prior(path: Path) -> tuple[np.ndarray, float, float]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        transform = np.asarray(data["CAM0"]["T_C_I"], dtype=float)
        gravity = float(data["IMU"]["gravity"])
        time_offset = float(data["CAM0"].get("timeoffset_C_I", 0.0))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid MSCKF prior YAML: {path}") from error
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise ValueError("CAM0/T_C_I must be a finite 4x4 matrix")
    if gravity <= 0.0 or not math.isfinite(time_offset):
        raise ValueError("invalid gravity or camera/IMU time offset")
    return transform, gravity, time_offset


def _read_imu_and_gt(
    bag_path: Path, imu_topic: str, gt_topic: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[float, np.ndarray, np.ndarray]]]:
    imu_times: list[float] = []
    accelerations: list[list[float]] = []
    angular_velocities: list[list[float]] = []
    groundtruth: list[tuple[float, np.ndarray, np.ndarray]] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, msg, record_stamp in bag.read_messages(
            topics=[imu_topic, gt_topic]
        ):
            stamp = (
                msg.header.stamp.to_sec()
                if msg.header.stamp.to_sec() > 0.0
                else record_stamp.to_sec()
            )
            if topic == imu_topic:
                imu_times.append(stamp)
                accelerations.append(
                    [
                        msg.linear_acceleration.x,
                        msg.linear_acceleration.y,
                        msg.linear_acceleration.z,
                    ]
                )
                angular_velocities.append(
                    [
                        msg.angular_velocity.x,
                        msg.angular_velocity.y,
                        msg.angular_velocity.z,
                    ]
                )
            else:
                position = msg.pose.pose.position
                orientation = msg.pose.pose.orientation
                groundtruth.append(
                    (
                        stamp,
                        np.array([position.x, position.y, position.z], dtype=float),
                        np.array(
                            [
                                orientation.x,
                                orientation.y,
                                orientation.z,
                                orientation.w,
                            ],
                            dtype=float,
                        ),
                    )
                )
    times = np.asarray(imu_times, dtype=float)
    acceleration_array = np.asarray(accelerations, dtype=float)
    angular_velocity_array = np.asarray(angular_velocities, dtype=float)
    if len(times) < 2 or len(groundtruth) < 3:
        raise ValueError("GT-calibrated initialization needs IMU and at least 3 GT poses")
    if not (
        np.all(np.isfinite(times))
        and np.all(np.isfinite(acceleration_array))
        and np.all(np.isfinite(angular_velocity_array))
    ):
        raise ValueError("IMU data contains non-finite values")
    return times, acceleration_array, angular_velocity_array, groundtruth


def _window_mean(
    times: np.ndarray, values: np.ndarray, center: float, half_width: float
) -> np.ndarray:
    selected = np.abs(times - center) <= half_width
    if not np.any(selected):
        index = int(np.argmin(np.abs(times - center)))
        return values[index].copy()
    return values[selected].mean(axis=0)


def derive_gt_calibrated_state(
    bag_path: Path,
    *,
    imu_topic: str,
    gt_topic: str,
    prior_yaml: Path,
    imu_window_s: float,
    velocity_samples: int,
    bias_json: Path | None = None,
) -> tuple[list[float], float, dict[str, object]]:
    if imu_window_s <= 0.0:
        raise ValueError("GT/IMU averaging window must be positive")
    transform_camera_imu, gravity, time_offset = _read_prior(prior_yaml)
    imu_times, accelerations, gyros, gt = _read_imu_and_gt(
        bag_path, imu_topic, gt_topic
    )
    rotation_camera_imu = transform_camera_imu[:3, :3]
    translation_camera_imu = transform_camera_imu[:3, 3]

    aligned: list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for stamp, camera_position, camera_quaternion in gt:
        rotation_map_camera = Rotation.from_quat(camera_quaternion).as_matrix()
        rotation_map_imu = rotation_map_camera @ rotation_camera_imu
        imu_position_map = (
            camera_position + rotation_map_camera @ translation_camera_imu
        )
        imu_stamp = stamp + time_offset
        mean_acceleration = _window_mean(
            imu_times, accelerations, imu_stamp, imu_window_s
        )
        mean_gyro = _window_mean(imu_times, gyros, imu_stamp, imu_window_s)
        aligned.append(
            (
                imu_stamp,
                rotation_map_imu,
                imu_position_map,
                mean_acceleration,
                mean_gyro,
            )
        )

    bias_source = "target_window_joint_gt_fit"
    if bias_json is not None:
        bias_report = json.loads(bias_json.read_text(encoding="ascii"))
        try:
            acceleration_bias = np.asarray(
                bias_report["accelerometer_bias"], dtype=float
            )
            gyro_bias = np.asarray(bias_report["gyroscope_bias"], dtype=float)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid bias calibration JSON: {bias_json}") from error
        if (
            acceleration_bias.shape != (3,)
            or gyro_bias.shape != (3,)
            or not np.all(np.isfinite(acceleration_bias))
            or not np.all(np.isfinite(gyro_bias))
        ):
            raise ValueError(f"invalid bias vectors in {bias_json}")
        gravity_rows = np.stack(
            [
                rotation_map_imu @ (mean_acceleration - acceleration_bias)
                for _, rotation_map_imu, _, mean_acceleration, _ in aligned
            ]
        )
        gravity_map = gravity_rows.mean(axis=0)
        gravity_map *= gravity / np.linalg.norm(gravity_map)
        bias_source = str(bias_json)
    else:
        linear_matrix = []
        linear_target = []
        for _, rotation_map_imu, _, mean_acceleration, _ in aligned:
            linear_matrix.append(
                np.column_stack([rotation_map_imu.T, np.eye(3)])
            )
            linear_target.append(mean_acceleration)
        matrix = np.vstack(linear_matrix)
        target = np.concatenate(linear_target)
        initial = np.linalg.lstsq(matrix, target, rcond=None)[0]

        def fit_residual(parameters: np.ndarray) -> np.ndarray:
            gravity_candidate = parameters[:3]
            bias_candidate = parameters[3:]
            observation_residuals = [
                rotation_map_imu.T @ gravity_candidate
                + bias_candidate
                - mean_acceleration
                for _, rotation_map_imu, _, mean_acceleration, _ in aligned
            ]
            norm_residual = 100.0 * (
                np.linalg.norm(gravity_candidate) - gravity
            )
            return np.concatenate([*observation_residuals, [norm_residual]])

        fit = least_squares(fit_residual, initial)
        if not fit.success:
            raise ValueError(
                f"gravity/accelerometer-bias fit failed: {fit.message}"
            )
        gravity_map = fit.x[:3]
        acceleration_bias = fit.x[3:]
        if abs(float(np.linalg.norm(gravity_map)) - gravity) > 1e-3:
            raise ValueError("gravity fit did not satisfy the configured norm")

    gyro_bias_rows = []
    for current, following in zip(aligned[:-1], aligned[1:]):
        time_current, rotation_current = current[0], current[1]
        time_following, rotation_following = following[0], following[1]
        delta_time = time_following - time_current
        if delta_time <= 0.0:
            continue
        relative = rotation_current.T @ rotation_following
        visual_gyro = Rotation.from_matrix(relative).as_rotvec() / delta_time
        selected = (imu_times >= time_current) & (imu_times < time_following)
        if not np.any(selected):
            continue
        gyro_bias_rows.append(gyros[selected].mean(axis=0) - visual_gyro)
    if not gyro_bias_rows:
        raise ValueError("unable to estimate gyroscope bias from GT intervals")
    gyro_bias_array = np.asarray(gyro_bias_rows)
    if bias_json is None:
        gyro_bias = np.median(gyro_bias_array, axis=0)

    rotation_global_map = rotation_between_vectors(
        gravity_map, np.array([0.0, 0.0, gravity])
    )
    initial_rotation_global_imu = rotation_global_map @ aligned[0][1]
    quaternion = Rotation.from_matrix(initial_rotation_global_imu).as_quat()
    if quaternion[3] < 0.0:
        quaternion *= -1.0

    position_count = min(max(velocity_samples, 2), len(aligned))
    velocity_times = np.asarray(
        [row[0] - aligned[0][0] for row in aligned[:position_count]]
    )
    velocity_positions = np.stack([row[2] for row in aligned[:position_count]])
    velocity_map = np.array(
        [
            np.polyfit(velocity_times, velocity_positions[:, axis], 1)[0]
            for axis in range(3)
        ]
    )
    velocity_global = rotation_global_map @ velocity_map

    state = [
        *quaternion.tolist(),
        0.0,
        0.0,
        0.0,
        *velocity_global.tolist(),
        *gyro_bias.tolist(),
        *acceleration_bias.tolist(),
    ]
    observation_residual = np.stack(
        [
            rotation_map_imu.T @ gravity_map
            + acceleration_bias
            - mean_acceleration
            for _, rotation_map_imu, _, mean_acceleration, _ in aligned
        ]
    )
    gravity_observations = np.stack(
        [
            rotation_map_imu @ (mean_acceleration - acceleration_bias)
            for _, rotation_map_imu, _, mean_acceleration, _ in aligned
        ]
    )
    gravity_angles = np.degrees(
        np.arccos(
            np.clip(
                gravity_observations @ gravity_map
                / (
                    np.linalg.norm(gravity_observations, axis=1)
                    * np.linalg.norm(gravity_map)
                ),
                -1.0,
                1.0,
            )
        )
    )
    report = {
        "initialization": "gt_calibrated_segment_state_common_to_all_frontends",
        "gt_topic": gt_topic,
        "prior_yaml": str(prior_yaml),
        "gt_pose_count": len(aligned),
        "camera_imu_time_offset_s": time_offset,
        "gravity_in_map": gravity_map.tolist(),
        "gravity_norm": float(np.linalg.norm(gravity_map)),
        "gravity_direction_mean_error_deg": float(np.mean(gravity_angles)),
        "gravity_direction_max_error_deg": float(np.max(gravity_angles)),
        "accelerometer_bias": acceleration_bias.tolist(),
        "bias_source": bias_source,
        "accelerometer_fit_rmse": float(
            np.sqrt(np.mean(observation_residual**2))
        ),
        "gyroscope_bias": gyro_bias.tolist(),
        "gyroscope_bias_interval_std": gyro_bias_array.std(axis=0).tolist(),
        "initial_velocity_global": velocity_global.tolist(),
        "velocity_fit_gt_samples": position_count,
    }
    return state, aligned[0][0], report


def read_initial_imu(
    bag_path: Path, imu_topic: str, samples: int
) -> tuple[float, np.ndarray, np.ndarray, int]:
    if samples < 1:
        raise ValueError("sample count must be positive")
    accelerations: list[list[float]] = []
    angular_velocities: list[list[float]] = []
    first_stamp: float | None = None
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, msg, record_stamp in bag.read_messages(topics=[imu_topic]):
            stamp = (
                msg.header.stamp.to_sec()
                if msg.header.stamp.to_sec() > 0.0
                else record_stamp.to_sec()
            )
            if first_stamp is None:
                first_stamp = stamp
            accelerations.append(
                [
                    msg.linear_acceleration.x,
                    msg.linear_acceleration.y,
                    msg.linear_acceleration.z,
                ]
            )
            angular_velocities.append(
                [
                    msg.angular_velocity.x,
                    msg.angular_velocity.y,
                    msg.angular_velocity.z,
                ]
            )
            if len(accelerations) >= samples:
                break
    if first_stamp is None:
        raise ValueError(f"no IMU messages found on {imu_topic}")
    acceleration_array = np.asarray(accelerations, dtype=float)
    angular_velocity_array = np.asarray(angular_velocities, dtype=float)
    if not np.all(np.isfinite(acceleration_array)) or not np.all(
        np.isfinite(angular_velocity_array)
    ):
        raise ValueError("initial IMU window contains non-finite values")
    return (
        first_stamp,
        acceleration_array.mean(axis=0),
        angular_velocity_array.mean(axis=0),
        len(accelerations),
    )


def main() -> int:
    args = parse_args()
    bag_path = Path(args.bag).resolve()
    if not bag_path.is_file():
        raise SystemExit(f"missing bag: {bag_path}")
    output_json = Path(args.output_json).resolve()
    output_yaml = Path(args.output_yaml).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.parent.mkdir(parents=True, exist_ok=True)

    try:
        if args.mode == "gt_calibrated":
            if not args.prior_yaml:
                raise ValueError("--prior-yaml is required in gt_calibrated mode")
            prior_yaml = Path(args.prior_yaml).resolve()
            if not prior_yaml.is_file():
                raise ValueError(f"missing prior YAML: {prior_yaml}")
            state, timestamp, mode_report = derive_gt_calibrated_state(
                bag_path,
                imu_topic=args.imu_topic,
                gt_topic=args.gt_topic,
                prior_yaml=prior_yaml,
                imu_window_s=args.gt_imu_window_s,
                velocity_samples=args.gt_velocity_samples,
                bias_json=Path(args.bias_json).resolve() if args.bias_json else None,
            )
            sample_count = 0
            mean_acceleration = np.zeros(3)
            mean_gyro = np.zeros(3)
        else:
            timestamp, mean_acceleration, mean_gyro, sample_count = read_initial_imu(
                bag_path, args.imu_topic, args.samples
            )
            quaternion = gravity_aligned_jpl_quaternion(mean_acceleration)
            state = [
                *quaternion.tolist(),
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ]
            mode_report = {
                "initialization": "imu_gravity_alignment_zero_yaw_position_velocity_bias",
                "requested_samples": args.samples,
                "used_samples": sample_count,
                "mean_acceleration": mean_acceleration.tolist(),
                "mean_acceleration_norm": float(
                    np.linalg.norm(mean_acceleration)
                ),
                "mean_angular_velocity": mean_gyro.tolist(),
            }
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if len(state) != 16 or not all(math.isfinite(value) for value in state):
        raise SystemExit("derived MSCKF state is invalid")

    report = {
        "bag": str(bag_path),
        "imu_topic": args.imu_topic,
        "mode": args.mode,
        "initial_timestamp": timestamp,
        "state_xyzw_p_v_bg_ba": state,
        **mode_report,
    }
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )

    state_text = ", ".join(f"{value:.16g}" for value in state)
    output_yaml.write_text(
        "INIT_MODE: INIT_SETTING\n"
        "INIT_SETTING:\n"
        "  IMU:\n"
        f"    time: {timestamp:.9f}\n"
        f"    state: [{state_text}]\n",
        encoding="ascii",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
