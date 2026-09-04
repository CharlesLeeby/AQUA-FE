#!/usr/bin/env python3
"""Generate camera and external-feature VINS-Fusion configs for MIMIR-UW."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import List, Sequence


# Official MIMIR ORB-SLAM3 monocular-inertial configuration defaults.
# https://github.com/olayasturias/ORB_SLAM3/blob/bd34d378fab97754db5ee88e90f8ad7be5607600/Examples/Monocular-Inertial/MIMIR.yaml
OFFICIAL_IMU_DEFAULTS = {
    "gyr_n": 1.7e-4,
    "acc_n": 2.0e-3,
    "gyr_w": 1.9393e-5,
    "acc_w": 3.0e-3,
}

# MIMIR's camera T_BS uses the simulator sensor axes (forward, right, down),
# while VINS/camodocal normalized pinhole points use OpenCV optical axes
# (right, down, forward).  This rotation maps OpenCV camera vectors into the
# MIMIR camera-sensor frame before applying the published T_BS.
MIMIR_CAMERA_FROM_OPENCV = [
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-dir", required=True, type=Path)
    parser.add_argument("--camera-config", required=True, type=Path)
    parser.add_argument(
        "--camera1-config",
        type=Path,
        default=None,
        help="Optional cam1 calibration output; enables stereo configuration.",
    )
    parser.add_argument("--vins-config", required=True, type=Path)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument("--imu-topic", default="/imu0")
    parser.add_argument(
        "--image-topic",
        default="/unused/image",
        help="Raw image topic for VINS internal-tracker diagnostics; leave unused for external features.",
    )
    parser.add_argument("--image1-topic", default="")
    parser.add_argument("--camera-name", default="mimir_cam0")
    parser.add_argument("--camera1-name", default="mimir_cam1")
    parser.add_argument(
        "--camera-axis-mode",
        choices=("opencv-optical", "published-sensor"),
        default="opencv-optical",
        help=(
            "Compose the MIMIR sensor axes with OpenCV optical axes (default), "
            "or reproduce the published T_BS matrix literally for diagnostics."
        ),
    )
    parser.add_argument("--multiple-thread", type=int, default=0)
    parser.add_argument("--use-imu", type=int, choices=(0, 1), default=1)
    parser.add_argument("--max-cnt", type=int, default=150)
    parser.add_argument("--min-dist", type=int, default=20)
    parser.add_argument("--freq", type=int, default=10)
    parser.add_argument("--f-threshold", type=float, default=1.0)
    parser.add_argument("--equalize", type=int, default=1)
    parser.add_argument("--keyframe-parallax", type=float, default=10.0)
    parser.add_argument("--max-solver-time", type=float, default=0.04)
    parser.add_argument("--max-num-iterations", type=int, default=8)
    parser.add_argument("--g-norm", type=float, default=9.81)
    parser.add_argument(
        "--td",
        type=float,
        default=0.0,
        help="Fixed VINS camera-to-IMU time offset in seconds.",
    )
    for key, value in OFFICIAL_IMU_DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=float, default=value)
    return parser.parse_args()


def _finite_matrix(
    value: object, label: str, expected_rows: int, expected_cols: int
) -> List[List[float]]:
    if not isinstance(value, list) or len(value) != expected_rows:
        raise ValueError(f"{label} must be a {expected_rows}x{expected_cols} list")
    matrix: List[List[float]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != expected_cols:
            raise ValueError(f"{label} must be a {expected_rows}x{expected_cols} list")
        parsed = [float(item) for item in row]
        if not all(math.isfinite(item) for item in parsed):
            raise ValueError(f"{label} contains non-finite values")
        matrix.append(parsed)
    if expected_rows == 4 and expected_cols == 4 and matrix[3] != [0.0, 0.0, 0.0, 1.0]:
        raise ValueError(f"unexpected homogeneous row in {label}: {matrix[3]}")
    return matrix


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _opencv_matrix_data(matrix: Sequence[Sequence[float]]) -> str:
    return ",\n           ".join(
        ", ".join(f"{value:.17g}" for value in row) for row in matrix
    )


def _matmul4(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> List[List[float]]:
    return [
        [sum(float(left[i][k]) * float(right[k][j]) for k in range(4)) for j in range(4)]
        for i in range(4)
    ]


def main() -> int:
    args = parse_args()
    sequence_dir = args.sequence_dir.resolve()
    camera_sensor_path = sequence_dir / "auv0/rgb/cam0/sensor.yaml"
    camera1_sensor_path = sequence_dir / "auv0/rgb/cam1/sensor.yaml"
    imu_sensor_path = sequence_dir / "auv0/imu0/sensor.yaml"
    camera_sensor = json.loads(camera_sensor_path.read_text(encoding="utf-8"))
    stereo = args.camera1_config is not None
    if stereo != bool(args.image1_topic):
        raise SystemExit("--camera1-config and non-empty --image1-topic must be used together")
    camera1_sensor = (
        json.loads(camera1_sensor_path.read_text(encoding="utf-8")) if stereo else None
    )
    imu_sensor = json.loads(imu_sensor_path.read_text(encoding="utf-8"))
    if camera_sensor.get("camera_model") != "pinhole":
        raise SystemExit(f"unsupported MIMIR camera model: {camera_sensor.get('camera_model')}")
    if camera_sensor.get("distortion_model") != "radial-tangential":
        raise SystemExit(
            f"unsupported MIMIR distortion model: {camera_sensor.get('distortion_model')}"
        )
    if camera1_sensor is not None:
        if camera1_sensor.get("camera_model") != "pinhole":
            raise SystemExit(
                f"unsupported MIMIR cam1 model: {camera1_sensor.get('camera_model')}"
            )
        if camera1_sensor.get("distortion_model") != "radial-tangential":
            raise SystemExit(
                "unsupported MIMIR cam1 distortion model: "
                f"{camera1_sensor.get('distortion_model')}"
            )
    if imu_sensor.get("sensor_type") != "imu0":
        raise SystemExit(f"unexpected MIMIR IMU sensor type: {imu_sensor.get('sensor_type')}")

    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    intrinsics = _finite_matrix(camera_sensor["intrinsics"], "camera intrinsics", 3, 3)
    body_t_camera_sensor = _finite_matrix(
        camera_sensor["T_BS"], "camera T_BS", 4, 4
    )
    camera_axis_rotation = (
        MIMIR_CAMERA_FROM_OPENCV
        if args.camera_axis_mode == "opencv-optical"
        else identity
    )
    body_t_cam0 = _matmul4(body_t_camera_sensor, camera_axis_rotation)
    body_t_cam1: List[List[float]] | None = None
    if camera1_sensor is not None:
        body_t_camera1_sensor = _finite_matrix(
            camera1_sensor["T_BS"], "camera1 T_BS", 4, 4
        )
        body_t_cam1 = _matmul4(body_t_camera1_sensor, camera_axis_rotation)
    imu_t_body = _finite_matrix(imu_sensor["T_BS"], "IMU T_BS", 4, 4)
    if imu_t_body != identity:
        raise SystemExit("MIMIR adapter currently requires the published identity IMU T_BS")
    resolution = [int(value) for value in camera_sensor["resolution"]]
    if len(resolution) != 2:
        raise ValueError(f"invalid MIMIR resolution: {resolution}")
    width, height = resolution
    distortion = [float(value) for value in camera_sensor["distortion_coefficients"]]
    if len(distortion) < 4:
        raise ValueError("MIMIR distortion_coefficients must contain at least four values")
    fx, fy = intrinsics[0][0], intrinsics[1][1]
    cx, cy = intrinsics[0][2], intrinsics[1][2]
    k1, k2, p1, p2 = distortion[:4]
    if camera1_sensor is not None:
        resolution1 = [int(value) for value in camera1_sensor["resolution"]]
        if resolution1 != resolution:
            raise ValueError(
                f"MIMIR stereo resolution mismatch: cam0={resolution} cam1={resolution1}"
            )
        intrinsics1 = _finite_matrix(
            camera1_sensor["intrinsics"], "camera1 intrinsics", 3, 3
        )
        distortion1 = [
            float(value) for value in camera1_sensor["distortion_coefficients"]
        ]
        if len(distortion1) < 4:
            raise ValueError(
                "MIMIR cam1 distortion_coefficients must contain at least four values"
            )
        fx1, fy1 = intrinsics1[0][0], intrinsics1[1][1]
        cx1, cy1 = intrinsics1[0][2], intrinsics1[1][2]
        k11, k21, p11, p21 = distortion1[:4]

    camera_config = args.camera_config.resolve()
    camera1_config = args.camera1_config.resolve() if args.camera1_config else None
    vins_config = args.vins_config.resolve()
    output_path = args.output_path.resolve()
    camera_config.parent.mkdir(parents=True, exist_ok=True)
    if camera1_config is not None:
        camera1_config.parent.mkdir(parents=True, exist_ok=True)
    vins_config.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    camera_config.write_text(
        "%YAML:1.0\n"
        "---\n"
        "model_type: PINHOLE\n"
        f"camera_name: {args.camera_name}\n"
        f"image_width: {width}\n"
        f"image_height: {height}\n"
        "distortion_parameters:\n"
        f"   k1: {k1:.17g}\n"
        f"   k2: {k2:.17g}\n"
        f"   p1: {p1:.17g}\n"
        f"   p2: {p2:.17g}\n"
        "projection_parameters:\n"
        f"   fx: {fx:.17g}\n"
        f"   fy: {fy:.17g}\n"
        f"   cx: {cx:.17g}\n"
        f"   cy: {cy:.17g}\n",
        encoding="utf-8",
    )
    if camera1_config is not None:
        camera1_config.write_text(
            "%YAML:1.0\n"
            "---\n"
            "model_type: PINHOLE\n"
            f"camera_name: {args.camera1_name}\n"
            f"image_width: {width}\n"
            f"image_height: {height}\n"
            "distortion_parameters:\n"
            f"   k1: {k11:.17g}\n"
            f"   k2: {k21:.17g}\n"
            f"   p1: {p11:.17g}\n"
            f"   p2: {p21:.17g}\n"
            "projection_parameters:\n"
            f"   fx: {fx1:.17g}\n"
            f"   fy: {fy1:.17g}\n"
            f"   cx: {cx1:.17g}\n"
            f"   cy: {cy1:.17g}\n",
            encoding="utf-8",
        )
    matrix_data = _opencv_matrix_data(body_t_cam0)
    matrix1_data = _opencv_matrix_data(body_t_cam1) if body_t_cam1 is not None else ""
    cam1_calib_line = (
        f'cam1_calib: "{camera1_config.name}"\n' if camera1_config is not None else ""
    )
    body_t_cam1_block = (
        "body_T_cam1: !!opencv-matrix\n"
        "   rows: 4\n"
        "   cols: 4\n"
        "   dt: d\n"
        f"   data: [{matrix1_data}]\n\n"
        if body_t_cam1 is not None
        else ""
    )
    vins_config.write_text(
        "%YAML:1.0\n\n"
        f"imu: {int(args.use_imu)}\n"
        f"num_of_cam: {2 if stereo else 1}\n"
        f"multiple_thread: {int(args.multiple_thread)}\n\n"
        f"imu_topic: \"{args.imu_topic}\"\n"
        f"image0_topic: \"{args.image_topic}\"\n"
        f"image1_topic: \"{args.image1_topic}\"\n"
        f"output_path: \"{output_path}\"\n\n"
        f"image_width: {width}\n"
        f"image_height: {height}\n"
        f"cam0_calib: \"{camera_config.name}\"\n"
        f"{cam1_calib_line}\n"
        "estimate_extrinsic: 0\n"
        "body_T_cam0: !!opencv-matrix\n"
        "   rows: 4\n"
        "   cols: 4\n"
        "   dt: d\n"
        f"   data: [{matrix_data}]\n\n"
        f"{body_t_cam1_block}"
        f"max_cnt: {int(args.max_cnt)}\n"
        f"min_dist: {int(args.min_dist)}\n"
        f"freq: {int(args.freq)}\n"
        f"F_threshold: {float(args.f_threshold):.17g}\n"
        "show_track: 0\n"
        "flow_back: 1\n"
        f"equalize: {int(args.equalize)}\n\n"
        f"max_solver_time: {float(args.max_solver_time):.17g}\n"
        f"max_num_iterations: {int(args.max_num_iterations)}\n"
        f"keyframe_parallax: {float(args.keyframe_parallax):.17g}\n\n"
        f"acc_n: {float(args.acc_n):.17g}\n"
        f"gyr_n: {float(args.gyr_n):.17g}\n"
        f"acc_w: {float(args.acc_w):.17g}\n"
        f"gyr_w: {float(args.gyr_w):.17g}\n"
        f"g_norm: {float(args.g_norm):.17g}\n\n"
        "loop_closure: 0\n"
        f"td: {float(args.td):.17g}\n"
        "estimate_td: 0\n"
        "rolling_shutter: 0\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "aqua-fe-mimir-uw-vins-config-v1",
        "sequence_dir": str(sequence_dir),
        "source_sensors": {
            str(camera_sensor_path): _sha256(camera_sensor_path),
            str(imu_sensor_path): _sha256(imu_sensor_path),
            **(
                {str(camera1_sensor_path): _sha256(camera1_sensor_path)}
                if stereo
                else {}
            ),
        },
        "camera_config": str(camera_config),
        "camera1_config": str(camera1_config) if camera1_config is not None else None,
        "vins_config": str(vins_config),
        "output_path": str(output_path),
        "image_topic": args.image_topic,
        "image1_topic": args.image1_topic,
        "use_imu": int(args.use_imu),
        "td": args.td,
        "transform_convention": {
            "camera_axis_mode": args.camera_axis_mode,
            "body_T_cam0": (
                "MIMIR camera sensor.yaml T_BS composed with the fixed "
                "OpenCV-optical-to-MIMIR-camera-sensor axis rotation"
            ),
            "body_T_cam1": (
                "MIMIR camera1 sensor.yaml T_BS composed with the fixed "
                "OpenCV-optical-to-MIMIR-camera-sensor axis rotation"
                if stereo
                else None
            ),
            "mimir_camera_from_opencv": camera_axis_rotation,
            "reason": (
                "MIMIR T_BS uses forward/right/down simulator sensor axes; "
                "VINS pinhole bearings use right/down/forward optical axes"
            ),
        },
        "imu_noise": {
            "values": {
                "acc_n": args.acc_n,
                "gyr_n": args.gyr_n,
                "acc_w": args.acc_w,
                "gyr_w": args.gyr_w,
            },
            "authority": "official MIMIR ORB-SLAM3 monocular-inertial MIMIR.yaml",
        },
    }
    manifest_path = vins_config.with_suffix(vins_config.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"camera_config={camera_config}")
    print(f"vins_config={vins_config}")
    print(f"config_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
