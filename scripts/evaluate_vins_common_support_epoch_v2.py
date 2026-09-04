#!/usr/bin/env python3
"""Additive ROS epoch-ns adapter for the frozen common-support evaluator.

The formally bound v1 evaluator is imported unchanged.  This entrypoint only
replaces its ROS-bag reference loader so a ``secs``/``nsecs`` pair reaches
``numpy.longdouble`` without a ``Time.to_sec()`` float64 round trip.  All CLI,
metric, support, alignment, failure, and output behavior remains in v1.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

SEALED_BASE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_BASE"
SEALED_CORE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_CORE"
ROS_NOETIC_PYTHON_DIST_PACKAGES = "/opt/ros/noetic/lib/python3/dist-packages"

# Formal execution uses ``python -I`` so inherited PYTHONPATH, user-site, and
# sitecustomize cannot run before this hash-bound wrapper.  ROS bag support is
# a root-owned system dependency and is admitted through one frozen literal.
if ROS_NOETIC_PYTHON_DIST_PACKAGES not in sys.path:
    sys.path.insert(0, ROS_NOETIC_PYTHON_DIST_PACKAGES)


def _module_from_sealed_source(name: str, path: str) -> Any:
    if not path.startswith("/proc/self/fd/"):
        raise RuntimeError(f"{name} sealed source must be a procfd")
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise RuntimeError(f"cannot construct sealed module spec for {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _load_base() -> Any:
    base_path = os.environ.get(SEALED_BASE_ENV)
    core_path = os.environ.get(SEALED_CORE_ENV)
    if (base_path is None) != (core_path is None):
        raise RuntimeError("sealed evaluator base/core must be supplied together")
    if base_path is not None and core_path is not None:
        core = _module_from_sealed_source("trajectory_eval_core", core_path)
        sys.modules["scripts.trajectory_eval_core"] = core
        loaded = _module_from_sealed_source(
            "evaluate_vins_common_support", base_path
        )
        sys.modules["scripts.evaluate_vins_common_support"] = loaded
        return loaded
    try:
        from scripts import evaluate_vins_common_support as canonical_base
    except ModuleNotFoundError:
        import evaluate_vins_common_support as canonical_base  # type: ignore
    return canonical_base


base = _load_base()


NANOSECONDS_PER_SECOND = 1_000_000_000


def ros_stamp_to_longdouble(stamp: Any) -> np.longdouble:
    """Convert one ROS1 stamp from exact integer fields to seconds."""

    secs = getattr(stamp, "secs", None)
    nsecs = getattr(stamp, "nsecs", None)
    if type(secs) is not int or type(nsecs) is not int:
        raise ValueError("ROS stamp secs/nsecs must be exact integers")
    if secs < 0 or not 0 <= nsecs < NANOSECONDS_PER_SECOND:
        raise ValueError("ROS stamp secs/nsecs are outside canonical ROS1 range")
    return np.longdouble(secs) + (
        np.longdouble(nsecs) / np.longdouble(NANOSECONDS_PER_SECOND)
    )


def load_ros_reference(path: Path, topic: str) -> base.PoseSeries:
    """Load ROS pose messages while preserving epoch-scale nanoseconds."""

    import rosbag

    stamps: list[np.longdouble] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    orientation_available = True
    with rosbag.Bag(str(path)) as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            pose = None
            if hasattr(message, "pose") and hasattr(message.pose, "pose"):
                pose = message.pose.pose
            elif hasattr(message, "pose"):
                pose = message.pose
            if pose is not None:
                position = pose.position
                orientation = getattr(pose, "orientation", None)
            elif hasattr(message, "transform"):
                position = message.transform.translation
                orientation = getattr(message.transform, "rotation", None)
            else:
                continue
            stamps.append(ros_stamp_to_longdouble(message.header.stamp))
            positions.append(
                [float(position.x), float(position.y), float(position.z)]
            )
            if orientation is None:
                orientation_available = False
                quaternions.append([base.math.nan] * 4)
            else:
                quaternions.append(
                    [
                        float(orientation.x),
                        float(orientation.y),
                        float(orientation.z),
                        float(orientation.w),
                    ]
                )
    return base.PoseSeries(
        stamps=np.asarray(stamps, dtype=np.longdouble),
        positions=np.asarray(positions, dtype=float).reshape((-1, 3)),
        quaternions_xyzw=(
            np.asarray(quaternions, dtype=float).reshape((-1, 4))
            if orientation_available
            else None
        ),
    )


def main() -> int:
    """Run v1 with the exact ROS timestamp adapter installed transiently."""

    original = base.load_ros_reference
    base.load_ros_reference = load_ros_reference
    try:
        return base.main()
    finally:
        base.load_ros_reference = original


if __name__ == "__main__":
    raise SystemExit(main())
