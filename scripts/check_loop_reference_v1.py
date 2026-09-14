#!/usr/bin/env python3
"""Read-only reference orientation check against calibrated raw IMU, no VIO fit.

This compares two explicit pose-direction interpretations, not learned outputs.
It does not certify a pose convention or choose one automatically.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import rosbag
from scipy.spatial.transform import Rotation

from evaluate_loop_system_v1 import reference
from learned_loop_encoder_v1 import sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sequence", choices=("bus_outside", "cemetery"), required=True)
    p.add_argument("--bag", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("Existing diagnostic is retained")
    t, _, q = reference(a.reference, "afrl_digits" if a.sequence == "cemetery" else "raw")
    if not np.all(np.diff(t) > 0) or not np.allclose(np.linalg.norm(q, axis=1), 1., atol=1e-6):
        raise ValueError("Reference time/quaternion fields invalid")
    calibration = cv2.FileStorage(str(a.config), cv2.FILE_STORAGE_READ)
    rbc = calibration.getNode("body_T_cam0").mat()[:3, :3]
    td = calibration.getNode("td").real()
    calibration.release()
    it, gyro = [], []
    with rosbag.Bag(str(a.bag)) as b:
        for _, m, record in b.read_messages(topics=["/imu/imu"]):
            ns = m.header.stamp.to_nsec() or record.to_nsec()
            it.append(np.longdouble(ns) / 10**9)
            gyro.append([m.angular_velocity.x, m.angular_velocity.y, m.angular_velocity.z])
    it, gyro = np.asarray(it), np.asarray(gyro)
    order = np.argsort(it, kind="stable")
    it, gyro = it[order], gyro[order]
    if not np.all(np.diff(it) > 0):
        raise ValueError("Ambiguous IMU header times")
    dt = np.asarray(np.diff(t), float)
    # Integrate provided gyro without bias, rotation, scale or offset fitting.
    cumulative = np.vstack((np.zeros(3), np.cumsum((gyro[1:] + gyro[:-1]) / 2 * np.asarray(np.diff(it), float)[:, None], axis=0)))
    query = np.asarray(t + td - it[0], float)
    imu_times = np.asarray(it - it[0], float)
    sampled = np.column_stack([np.interp(query, imu_times, cumulative[:, k]) for k in range(3)])
    mean_body = np.diff(sampled, axis=0) / dt[:, None]
    mean_camera = mean_body @ rbc
    valid = (dt > 0) & (dt <= 1.) & (query[:-1] >= 0) & (query[1:] <= imu_times[-1])
    r = Rotation.from_quat(q).as_matrix()
    interpretations = {"as_world_T_cam0": np.transpose(r[:-1], (0, 2, 1)) @ r[1:],
        "inverse_direction": r[:-1] @ np.transpose(r[1:], (0, 2, 1))}
    result = dict(sequence=a.sequence, reference_sha256=sha(a.reference), config_sha256=sha(a.config),
        intervals_total=len(dt), valid_intervals=int(valid.sum()), imu_samples=len(it),
        fixed_camera_imu_td_s=td, no_estimator_or_learned_outputs_used=True,
        fitting="none: no bias/offset/scale/rotation fit", validity="positive dt<=1s and enclosed IMU support",
        convention_validated=False, pose_convention="Unknown", interpretations={})
    for name, relative in interpretations.items():
        observed = Rotation.from_matrix(relative).as_rotvec() / dt[:, None]
        error = np.linalg.norm(observed[valid] - mean_camera[valid], axis=1)
        result["interpretations"][name] = dict(gyro_difference_rmse_rad_s=float(np.sqrt(np.mean(error**2))),
            median_rad_s=float(np.median(error)), p95_rad_s=float(np.percentile(error, 95)),
            per_axis_correlation=[float(np.corrcoef(observed[valid, k], mean_camera[valid, k])[0, 1]) for k in range(3)])
    result["limitation"] = "Finite-interval gyro consistency is supporting evidence, not independent proof of camera origin/world pose convention; no automatic relabeling or trajectory score."
    with a.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
