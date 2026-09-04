#!/usr/bin/env python3
"""Prepare or validate the frozen VINS config used by P07 replay-only runs.

The dataset preparation runners are invoked with ``RUN_VINS=0`` before this
helper.  NTNU and AFRL already produce their VINS configs in that mode, so this
helper only validates them.  The two AQUALOC runners stop before writing the
VINS config; for those families this helper writes the exact frozen config with
exclusive-create semantics.  It never opens a bag or a trajectory artifact.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


FAMILIES = {
    "ntnu",
    "aqualoc_archaeology",
    "aqualoc_harbor",
    "afrl",
}
MODES = {"external", "origin"}


class ConfigError(RuntimeError):
    """A replay config is absent, unsafe, or inconsistent with the lock."""


def _absolute_plain_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ConfigError(f"{label} must be absolute: {path}")
    if path.is_symlink() or not path.is_dir():
        raise ConfigError(f"{label} must be an existing non-symlink directory: {path}")
    return path


def _plain_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ConfigError(f"{label} must be an existing non-symlink file: {path}")
    return path


def _paths(family: str, mode: str, run_dir: Path) -> tuple[Path, Path, Path]:
    names = {
        "ntnu": ("ntnu_cam0_kannala_brandt.yaml", f"vins_ntnu_{mode}.yaml"),
        "aqualoc_archaeology": (
            "aqualoc_archaeo_pinhole.yaml",
            f"vins_aqualoc_archaeo_{mode}.yaml",
        ),
        "aqualoc_harbor": (
            "aqualoc_harbor07_kannala.yaml",
            f"vins_aqualoc_{mode}.yaml",
        ),
        "afrl": ("afrl_cave_cam0_pinhole.yaml", f"vins_afrl_cave_{mode}.yaml"),
    }
    camera_name, vins_name = names[family]
    if family == "aqualoc_archaeology":
        matches = sorted(run_dir.glob("aqualoc_archaeo*_pinhole.yaml"))
        if len(matches) != 1:
            raise ConfigError(
                "AQUALOC archaeology prep must leave exactly one camera config"
            )
        camera = matches[0]
    else:
        camera = run_dir / camera_name
    return camera, run_dir / vins_name, run_dir / "vins_output"


def _body_block(family: str) -> str:
    if family == "aqualoc_archaeology":
        return """body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]"""
    return """body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99978035,  0.0169654,   0.01230552, -0.01719238,
            0.01210101, -0.01210461,  0.99985351,  0.14944769,
            0.01711187,  0.9997828,   0.01189665, -0.01915984,
            0.0,         0.0,         0.0,         1.0 ]"""


def _aqualoc_text(
    family: str,
    mode: str,
    camera_config: Path,
    vins_output: Path,
) -> str:
    archaeology = family == "aqualoc_archaeology"
    width, height = (968, 608) if archaeology else (640, 512)
    image_topic = "/unused/image" if mode == "external" else "/camera/image_raw"
    max_cnt = 150
    acc_n = "0.05" if archaeology else "0.02"
    gyr_n = "0.003" if archaeology else "0.001"
    acc_w = "0.0015" if archaeology else "0.001"
    gyr_w = "0.0001" if archaeology else "0.00005"
    td = "-0.053694112369382575" if archaeology else "-0.0403806549886"
    return f"""%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 0

imu_topic: "/rtimulib_node/imu"
image0_topic: "{image_topic}"
image1_topic: ""
output_path: "{vins_output}"

image_width: {width}
image_height: {height}
cam0_calib: "{camera_config.name}"

estimate_extrinsic: 0
{_body_block(family)}

max_cnt: {max_cnt}
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: {acc_n}
gyr_n: {gyr_n}
acc_w: {acc_w}
gyr_w: {gyr_w}
g_norm: 9.8100

loop_closure: 0
td: {td}
estimate_td: 0
rolling_shutter: 0
"""


def _required_fragments(
    family: str,
    mode: str,
    camera_config: Path,
    vins_output: Path,
) -> tuple[str, ...]:
    image_topics = {
        "ntnu": "/alphasense_driver_ros/cam0",
        "aqualoc_archaeology": "/camera/image_raw",
        "aqualoc_harbor": "/camera/image_raw",
        "afrl": "/camera/image_raw",
    }
    imu_topics = {
        "ntnu": "/alphasense_driver_ros/imu",
        "aqualoc_archaeology": "/rtimulib_node/imu",
        "aqualoc_harbor": "/rtimulib_node/imu",
        "afrl": "/imu/imu",
    }
    image_topic = "/unused/image" if mode == "external" else image_topics[family]
    return (
        "imu: 1",
        "num_of_cam: 1",
        "multiple_thread: 0",
        f'imu_topic: "{imu_topics[family]}"',
        f'image0_topic: "{image_topic}"',
        f'output_path: "{vins_output}"',
        f'cam0_calib: "{camera_config.name}"',
        "loop_closure: 0",
    )


def validate_config(
    family: str,
    mode: str,
    camera_config: Path,
    vins_config: Path,
    vins_output: Path,
) -> None:
    _plain_file(camera_config, "camera config")
    _plain_file(vins_config, "VINS config")
    _absolute_plain_directory(vins_output, "VINS output directory")
    text = vins_config.read_text(encoding="utf-8")
    validate_config_text(
        family,
        mode,
        text,
        camera_config_name=camera_config.name,
        vins_output=vins_output,
    )


def validate_config_text(
    family: str,
    mode: str,
    text: str,
    *,
    camera_config_name: str,
    vins_output: Path,
) -> None:
    """Validate already-snapshotted config bytes without reopening a path."""

    if family not in FAMILIES or mode not in MODES:
        raise ConfigError("unsupported frozen config family/mode")
    if not isinstance(text, str) or not text:
        raise ConfigError("VINS config text is empty")
    camera_config = Path(camera_config_name)
    if camera_config.is_absolute() or camera_config.name != camera_config_name:
        raise ConfigError("camera config name is not a plain basename")
    missing = [
        item
        for item in _required_fragments(
            family, mode, camera_config, vins_output
        )
        if item not in text
    ]
    if missing:
        raise ConfigError(f"VINS config violates frozen replay contract: {missing}")


def prepare(family: str, mode: str, run_dir: Path) -> dict[str, str]:
    if family not in FAMILIES:
        raise ConfigError(f"unsupported family: {family}")
    if mode not in MODES:
        raise ConfigError(f"unsupported mode: {mode}")
    run_dir = _absolute_plain_directory(run_dir, "run directory")
    camera_config, vins_config, vins_output = _paths(family, mode, run_dir)
    _plain_file(camera_config, "camera config")
    _absolute_plain_directory(vins_output, "VINS output directory")

    action = "VALIDATED_EXISTING"
    if family.startswith("aqualoc_"):
        payload = _aqualoc_text(family, mode, camera_config, vins_output)
        try:
            fd = os.open(
                vins_config,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o444,
            )
        except FileExistsError as error:
            raise ConfigError(f"refusing to overwrite VINS config: {vins_config}") from error
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # Do not unlink a partial file: immutable evidence must remain visible.
            raise
        action = "CREATED_EXCLUSIVE"

    validate_config(family, mode, camera_config, vins_config, vins_output)
    return {
        "family": family,
        "mode": mode,
        "action": action,
        "camera_config": os.fspath(camera_config),
        "vins_config": os.fspath(vins_config),
        "vins_output": os.fspath(vins_output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=sorted(FAMILIES))
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.family, args.mode, args.run_dir)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
