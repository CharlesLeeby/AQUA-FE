#!/usr/bin/python3
"""Prepare and run the open-loop HFNet arms of fair-stability-positive-roster-v1.

The formal one-shot HFNet namespaces are read-only.  This controller creates a
new development namespace, verifies the exact VINS camera phase against both
historical feature bags, generates loop-off configs, gives every replicate an
independent timing-cache seed, and retains every terminal outcome.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from fair_stability_ordinal_common_v1 import (
    authorize as authorize_ordinal,
    verify_dispatch_claim,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
PROTOCOL = ROOT / "papers/fair_stability_positive_roster_protocol_v1.md"
ROSTER = ROOT / "papers/fair_stability_positive_roster_v1.csv"
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v1"
)
ORDINAL_COMMON = ROOT / "scripts/fair_stability_ordinal_common_v1.py"

EXPECTED_PROTOCOL_SHA256 = (
    "ab057022d47e4e90e81c639c84a5444000c67cca3aab10316a554b3e3beecd09"
)
EXPECTED_ROSTER_SHA256 = (
    "63715003fde3374a96fd045917e1e718a8b3473723ba1afc50e2d48693d87e3c"
)

BINARY = (
    ROOT
    / "build/published_baselines/hfnet_slam_headless_entry_v3"
    / "mono_inertial_euroc_headless_v3"
)
OFFICIAL_LIBRARY = Path(
    "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so"
)
SHARED_ONNX = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx"
)
SHARED_CACHE = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache"
)

EXPECTED_STACK = {
    "binary": (118_280, "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb"),
    "official_library": (4_807_712, "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717"),
    "onnx": (132_238_602, "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5"),
    "cache": (853_319, "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7"),
}
EXPECTED_CONFIGS = {
    "aqualoc_archaeology": "d0cbe8e575c2b8234d1d617baabc27560118625398fd588ec83c3e93b4ce6177",
    "ntnu": "5b8b8d7ed6c010f25d4cf8d80ca24692b06de4cd17f4d19ae2a0cb9cc91a54dd",
    "cirs": "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204",
}

CASE_ORDER = [
    "a05_3300_3700",
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
]
BUDGETS = (675, 350)
REPEATS = (1, 2, 3)
ASSOCIATION_TOLERANCE_NS = 256
MIN_SUCCESS_COVERAGE = 0.70
MIN_PARTIAL_COVERAGE = 0.50
MAX_INIT_LATENCY_S = 10.0
TIMEOUT_SECONDS = 1800
MIN_MNT_FREE_BYTES = 5 * 1024**3
MIN_ROOT_FREE_BYTES = 512 * 1024**2


class ContractError(RuntimeError):
    """A frozen input or execution boundary was violated."""


class SupervisorInterrupted(RuntimeError):
    pass


def raise_supervisor_interrupt(signum: int, _frame: object) -> None:
    raise SupervisorInterrupted(f"received signal {signum}")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"MISSING_OR_SYMLINK_FILE:{path}")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def require_identity(path: Path, size: int, digest: str, label: str) -> dict[str, object]:
    actual = identity(path)
    if actual["size_bytes"] != size or actual["sha256"] != digest:
        raise ContractError(f"IDENTITY_MISMATCH:{label}:{path}")
    return actual


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_copy(source: Path, target: Path, mode: int) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.copy-", dir=str(target.parent)
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as src, os.fdopen(descriptor, "wb") as dst:
            descriptor = -1
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temporary, mode)
        os.link(temporary, target, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return identity(target)


def load_roster() -> dict[str, dict[str, str]]:
    require_identity(PROTOCOL, PROTOCOL.stat().st_size, EXPECTED_PROTOCOL_SHA256, "protocol")
    require_identity(ROSTER, ROSTER.stat().st_size, EXPECTED_ROSTER_SHA256, "roster")
    with ROSTER.open(newline="", encoding="utf-8") as stream:
        rows = {row["case_id"]: row for row in csv.DictReader(stream)}
    if list(rows) != CASE_ORDER or len(rows) != 10:
        raise ContractError("ROSTER_ORDER_OR_SIZE_MISMATCH")
    return rows


def read_ns_lines(path: Path) -> list[int]:
    values = [int(line.strip()) for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    if not values or any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"TIMESTAMP_LIST_INVALID:{path}")
    return values


def selected_source_stamps(row: Mapping[str, str]) -> tuple[list[int], list[int]]:
    source = read_ns_lines(Path(row["input_root"]) / "cam0_times.txt")
    if len(source) != int(row["source_camera_count"]):
        raise ContractError(f"SOURCE_CAMERA_COUNT_MISMATCH:{row['case_id']}")
    indices = list(range(len(source))) if row["selection"] == "every1" else list(range(1, len(source), 2))
    selected = [source[index] for index in indices]
    if len(selected) != int(row["selected_camera_count"]):
        raise ContractError(f"SELECTED_CAMERA_COUNT_MISMATCH:{row['case_id']}")
    return indices, selected


def bag_feature_stamps(path: Path) -> list[int]:
    try:
        import rosbag  # type: ignore
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED_USE_USR_BIN_PYTHON3") from error
    stamps: list[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            stamps.append(int(message.header.stamp.to_nsec()))
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError(f"FEATURE_TIMESTAMPS_INVALID:{path}")
    return stamps


def list_digest(values: Iterable[int]) -> str:
    payload = "".join(f"{value}\n" for value in values).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_mapping(selected: Sequence[int], feature: Sequence[int], label: str) -> dict[str, object]:
    if len(selected) != len(feature):
        raise ContractError(f"FEATURE_COUNT_MISMATCH:{label}")
    deltas = [abs(left - right) for left, right in zip(selected, feature)]
    if max(deltas, default=0) > ASSOCIATION_TOLERANCE_NS:
        raise ContractError(f"FEATURE_TIMESTAMP_PHASE_MISMATCH:{label}")
    return {
        "feature_count": len(feature),
        "feature_timestamp_sha256": list_digest(feature),
        "max_absolute_header_delta_ns": max(deltas, default=0),
        "bijection_within_256ns": True,
    }


def parse_imu_stamps(path: Path) -> list[int]:
    stamps: list[int] = []
    with path.open(newline="", encoding="ascii") as stream:
        for row in csv.reader(stream):
            if not row or row[0].startswith("#"):
                continue
            stamps.append(int(row[0]))
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError(f"IMU_TIMESTAMPS_INVALID:{path}")
    return stamps


def imu_bracket(stamps: Sequence[int], selected: Sequence[int], label: str) -> dict[str, int]:
    first_right = bisect.bisect_right(stamps, selected[0])
    last_right = bisect.bisect_right(stamps, selected[-1])
    if first_right == 0 or first_right >= len(stamps) or last_right == 0 or last_right >= len(stamps):
        raise ContractError(f"IMU_BRACKET_INVALID:{label}")
    return {
        "first_camera_ns": selected[0],
        "first_predecessor_imu_ns": stamps[first_right - 1],
        "first_successor_imu_ns": stamps[first_right],
        "last_camera_ns": selected[-1],
        "last_predecessor_imu_ns": stamps[last_right - 1],
        "last_successor_imu_ns": stamps[last_right],
    }


def image_inventory(input_root: Path, selected: Sequence[int]) -> dict[str, object]:
    digest = hashlib.sha256()
    total = 0
    for stamp in selected:
        image_path = input_root / "mav0/cam0/data" / f"{stamp}.png"
        item = identity(image_path)
        total += int(item["size_bytes"])
        digest.update(f"{stamp}\0{item['size_bytes']}\0{item['sha256']}\n".encode("ascii"))
    return {
        "image_count": len(selected),
        "total_bytes": total,
        "ordered_image_inventory_sha256": digest.hexdigest(),
    }


def frozen_schedule() -> list[dict[str, object]]:
    arms = ["learned_klt_vins", "pure_klt_vins", "hfnet_openloop_675", "hfnet_openloop_350"]
    schedule: list[dict[str, object]] = []
    ordinal = 0
    for repeat in REPEATS:
        case_rotation = (repeat - 1) * 3
        cases = CASE_ORDER[case_rotation:] + CASE_ORDER[:case_rotation]
        for case_position, case_id in enumerate(cases):
            arm_rotation = (case_position + repeat - 1) % len(arms)
            ordered_arms = arms[arm_rotation:] + arms[:arm_rotation]
            for arm in ordered_arms:
                ordinal += 1
                schedule.append(
                    {"ordinal": ordinal, "case_id": case_id, "arm": arm, "repeat": repeat}
                )
    return schedule


def freeze_inputs() -> dict[str, object]:
    if EXPERIMENT_ROOT.exists() or EXPERIMENT_ROOT.is_symlink():
        raise ContractError(f"EXPERIMENT_NAMESPACE_EXISTS:{EXPERIMENT_ROOT}")
    rows = load_roster()
    stack = {
        "binary": require_identity(BINARY, *EXPECTED_STACK["binary"], "binary"),
        "official_library": require_identity(
            OFFICIAL_LIBRARY, *EXPECTED_STACK["official_library"], "official_library"
        ),
        "shared_onnx": require_identity(SHARED_ONNX, *EXPECTED_STACK["onnx"], "onnx"),
        "shared_cache_seed": require_identity(SHARED_CACHE, *EXPECTED_STACK["cache"], "cache"),
    }
    cases: dict[str, dict[str, object]] = {}
    selected_by_case: dict[str, list[int]] = {}
    for case_id in CASE_ORDER:
        row = rows[case_id]
        input_root = Path(row["input_root"])
        if input_root.is_symlink() or not input_root.is_dir():
            raise ContractError(f"INPUT_ROOT_INVALID:{case_id}")
        config_path = Path(row["base_config"])
        config = identity(config_path)
        if config["sha256"] != EXPECTED_CONFIGS[row["dataset"]]:
            raise ContractError(f"BASE_CONFIG_IDENTITY_MISMATCH:{case_id}")
        indices, selected = selected_source_stamps(row)
        selected_by_case[case_id] = selected
        learned_path = Path(row["learned_klt_bag"])
        klt_path = Path(row["klt_bag"])
        learned_identity = identity(learned_path)
        klt_identity = identity(klt_path)
        if learned_identity["sha256"] != row["learned_klt_sha256"]:
            raise ContractError(f"LEARNED_BAG_IDENTITY_MISMATCH:{case_id}")
        if klt_identity["sha256"] != row["klt_sha256"]:
            raise ContractError(f"KLT_BAG_IDENTITY_MISMATCH:{case_id}")
        learned_mapping = validate_mapping(selected, bag_feature_stamps(learned_path), f"{case_id}:learned")
        klt_mapping = validate_mapping(selected, bag_feature_stamps(klt_path), f"{case_id}:klt")
        imu_path = input_root / "mav0/imu0/data.csv"
        materialization = input_root / "materialization_manifest.json"
        cases[case_id] = {
            "case_id": case_id,
            "dataset": row["dataset"],
            "input_root": str(input_root),
            "source_camera_count": int(row["source_camera_count"]),
            "selected_camera_count": len(selected),
            "selected_source_indices": indices,
            "selected_header_ns_inclusive": [selected[0], selected[-1]],
            "selected_timestamp_sha256": list_digest(selected),
            "selection": row["selection"],
            "nominal_fps": int(row["nominal_fps"]),
            "base_config": config,
            "source_times": identity(input_root / "cam0_times.txt"),
            "source_materialization_manifest": identity(materialization),
            "imu": identity(imu_path),
            "imu_bracket": imu_bracket(parse_imu_stamps(imu_path), selected, case_id),
            "images": image_inventory(input_root, selected),
            "learned_klt_bag": learned_identity,
            "pure_klt_bag": klt_identity,
            "learned_mapping": learned_mapping,
            "klt_mapping": klt_mapping,
        }

    staging = EXPERIMENT_ROOT.parent / f".{EXPERIMENT_ROOT.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        seed_root = staging / "runtime_seed/HFNet-RT"
        seed_root.mkdir(parents=True)
        seed_onnx = atomic_copy(SHARED_ONNX, seed_root / "HF-Net.onnx", 0o444)
        seed_cache = atomic_copy(SHARED_CACHE, seed_root / "HF-Net.cache", 0o444)
        seed_onnx["path"] = str(EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx")
        seed_cache["path"] = str(EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache")
        for case_id, selected in selected_by_case.items():
            case_root = staging / "input_freeze" / case_id
            times_payload = "".join(f"{stamp}\n" for stamp in selected).encode("ascii")
            write_exclusive(case_root / "cam0_times_vins_matched.txt", times_payload)
            cases[case_id]["selected_times_file"] = identity(
                case_root / "cam0_times_vins_matched.txt"
            )
            cases[case_id]["selected_times_file"]["path"] = str(
                EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt"
            )
            write_exclusive(case_root / "case_manifest.json", canonical_json(cases[case_id]))
        schedule = frozen_schedule()
        write_exclusive(staging / "planned_schedule.json", canonical_json(schedule))
        schedule_identity = identity(staging / "planned_schedule.json")
        schedule_identity["path"] = str(EXPERIMENT_ROOT / "planned_schedule.json")
        manifest = {
            "schema_version": "aqua-fe-fair-stability-hfnet-input-freeze-v1",
            "status": "FROZEN_INPUTS_NO_ESTIMATOR_STARTED",
            "created_at_utc": now_utc(),
            "protocol": identity(PROTOCOL),
            "roster": identity(ROSTER),
            "runner": identity(RUNNER),
            "stack": stack,
            "runtime_seed": {"onnx": seed_onnx, "cache": seed_cache},
            "cases": cases,
            "planned_schedule": schedule_identity,
            "claims": {
                "same_camera_timestamps_verified": True,
                "loop_closing_disabled_at_runtime_config_generation": True,
                "outcome_selected_roster": True,
                "system_ranking_supported": False,
                "estimator_started": False,
            },
        }
        write_exclusive(staging / "experiment_manifest.json", canonical_json(manifest))
        os.rename(staging, EXPERIMENT_ROOT)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def load_experiment() -> dict[str, Any]:
    load_roster()
    manifest_path = EXPERIMENT_ROOT / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "aqua-fe-fair-stability-hfnet-input-freeze-v1":
        raise ContractError("EXPERIMENT_MANIFEST_SCHEMA_MISMATCH")
    if manifest["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ContractError("EXPERIMENT_PROTOCOL_PIN_MISMATCH")
    if manifest["roster"]["sha256"] != EXPECTED_ROSTER_SHA256:
        raise ContractError("EXPERIMENT_ROSTER_PIN_MISMATCH")
    for label, path, expected in (
        ("binary", BINARY, EXPECTED_STACK["binary"]),
        ("official_library", OFFICIAL_LIBRARY, EXPECTED_STACK["official_library"]),
        ("shared_onnx", SHARED_ONNX, EXPECTED_STACK["onnx"]),
        ("shared_cache", SHARED_CACHE, EXPECTED_STACK["cache"]),
    ):
        require_identity(path, *expected, label)
    return manifest


def attempt_root(case_id: str, budget: int, repeat: int, attempt_index: int = 1) -> Path:
    base = EXPERIMENT_ROOT / f"hfnet_openloop_{budget}" / case_id / f"repeat_{repeat:03d}"
    if attempt_index < 1:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    return base if attempt_index == 1 else base.with_name(
        f"{base.name}__replenishment_{attempt_index:03d}"
    )


def patch_config(base: Path, local_model_dir: Path, fps: int, budget: int) -> tuple[bytes, list[dict[str, object]]]:
    source = base.read_text(encoding="utf-8")
    substitutions = [
        (
            r'^Extractor\.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"$',
            f'Extractor.modelPath: "{local_model_dir}/"',
            "model_path",
        ),
        (r"^Camera\.fps: (?:20|5\.0)$", f"Camera.fps: {fps}", "camera_fps"),
        (r"^Extractor\.nFeatures: 675$", f"Extractor.nFeatures: {budget}", "feature_budget"),
        (r"^loopClosing: 1$", "loopClosing: 0", "loop_closing"),
    ]
    receipts: list[dict[str, object]] = []
    for pattern, replacement, label in substitutions:
        source, count = re.subn(pattern, replacement, source, flags=re.MULTILINE)
        if count != 1:
            raise ContractError(f"CONFIG_SUBSTITUTION_COUNT:{label}:{count}")
        receipts.append({"label": label, "pattern": pattern, "replacement": replacement, "count": count})
    return source.encode("utf-8"), receipts


def validate_generated_config(path: Path, fps: int, budget: int, model_dir: Path) -> dict[str, object]:
    try:
        import cv2  # type: ignore
    except ImportError as error:
        raise ContractError("OPENCV_IMPORT_FAILED") from error
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ContractError(f"OPENCV_CONFIG_OPEN_FAILED:{path}")
    try:
        observed = {
            "Camera.fps": int(storage.getNode("Camera.fps").real()),
            "Extractor.nFeatures": int(storage.getNode("Extractor.nFeatures").real()),
            "loopClosing": int(storage.getNode("loopClosing").real()),
            "Extractor.modelPath": storage.getNode("Extractor.modelPath").string(),
        }
    finally:
        storage.release()
    expected = {
        "Camera.fps": fps,
        "Extractor.nFeatures": budget,
        "loopClosing": 0,
        "Extractor.modelPath": f"{model_dir}/",
    }
    if observed != expected:
        raise ContractError(f"GENERATED_CONFIG_VALUE_MISMATCH:{observed}:{expected}")
    return observed


def prepare_attempt(case_id: str, budget: int, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    manifest = load_experiment()
    if case_id not in manifest["cases"] or budget not in BUDGETS or repeat not in REPEATS:
        raise ContractError("ATTEMPT_COORDINATE_INVALID")
    case = manifest["cases"][case_id]
    if attempt_index < 1:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    if attempt_index > 1:
        previous = attempt_root(case_id, budget, repeat, attempt_index - 1) / "run_result.json"
        if not previous.is_file() or json.loads(previous.read_text(encoding="utf-8")).get("status") != "PIPELINE_INVALID":
            raise ContractError("REPLENISHMENT_REQUIRES_PREVIOUS_PIPELINE_INVALID")
    root = attempt_root(case_id, budget, repeat, attempt_index)
    root.mkdir(parents=True, exist_ok=False)
    try:
        result_dir = root / "result"
        model_dir = root / "run_local_model/HFNet-RT"
        result_dir.mkdir(parents=True)
        model_dir.mkdir(parents=True)
        seed_onnx = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx"
        seed_cache = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache"
        local_onnx = model_dir / "HF-Net.onnx"
        local_cache = model_dir / "HF-Net.cache"
        os.link(seed_onnx, local_onnx, follow_symlinks=False)
        os.chmod(local_onnx, 0o444)
        cache_pre = atomic_copy(seed_cache, local_cache, 0o644)
        selected_source = EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt"
        selected_local = root / "cam0_times_vins_matched.txt"
        os.link(selected_source, selected_local, follow_symlinks=False)
        config_payload, patch_receipt = patch_config(
            Path(case["base_config"]["path"]),
            model_dir,
            int(case["nominal_fps"]),
            budget,
        )
        config_path = root / "runtime_config_openloop.yaml"
        write_exclusive(config_path, config_payload)
        config_values = validate_generated_config(
            config_path, int(case["nominal_fps"]), budget, model_dir
        )
        attempt = {
            "schema_version": "aqua-fe-fair-stability-hfnet-attempt-v1",
            "status": "PREPARED_NOT_STARTED",
            "prepared_at_utc": now_utc(),
            "case_id": case_id,
            "budget": budget,
            "arm": f"hfnet_openloop_{budget}",
            "repeat": repeat,
            "planned_repeat": repeat,
            "attempt_index": attempt_index,
            "replenishes_invalid_attempt": attempt_index - 1 if attempt_index > 1 else None,
            "attempt_root": str(root),
            "case_manifest": identity(
                EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
            ),
            "selected_times": identity(selected_local),
            "base_config": case["base_config"],
            "runtime_config": identity(config_path),
            "config_patch_receipt": patch_receipt,
            "config_values": config_values,
            "local_onnx_pre": identity(local_onnx),
            "local_cache_seed_pre": cache_pre,
            "launch": {
                "argv": [
                    str(BINARY),
                    str(config_path),
                    f"{result_dir}/",
                    str(case["input_root"]),
                    str(selected_local),
                ],
                "cwd": str(root),
                "timeout_seconds": TIMEOUT_SECONDS,
            },
            "claims": {
                "cold_start": True,
                "loop_closing": False,
                "same_camera_timestamp_phase": True,
                "independent_cache_seed": True,
                "repeat_is_not_retry": True,
                "pipeline_invalid_replenishment_is_not_a_replicate": attempt_index > 1,
            },
        }
        write_exclusive(root / "attempt_manifest.json", canonical_json(attempt))
        return attempt
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def prepare_all() -> list[dict[str, object]]:
    prepared: list[dict[str, object]] = []
    schedule = json.loads((EXPERIMENT_ROOT / "planned_schedule.json").read_text(encoding="utf-8"))
    for cell in schedule:
        arm = str(cell["arm"])
        if not arm.startswith("hfnet_openloop_"):
            continue
        budget = int(arm.rsplit("_", 1)[1])
        root = attempt_root(str(cell["case_id"]), budget, int(cell["repeat"]))
        if root.exists():
            continue
        prepared.append(prepare_attempt(str(cell["case_id"]), budget, int(cell["repeat"])))
    return prepared


def process_record(pid: int) -> dict[str, object]:
    root = Path("/proc") / str(pid)
    try:
        executable = os.readlink(root / "exe")
    except OSError:
        executable = ""
    try:
        comm = (root / "comm").read_text(errors="replace").strip()
    except OSError:
        comm = ""
    try:
        tokens = [part.decode(errors="replace") for part in (root / "cmdline").read_bytes().split(b"\0") if part]
    except OSError:
        tokens = []
    return {"pid": pid, "executable": executable, "comm": comm, "tokens": tokens, "command": " ".join(tokens)}


def resource_gate() -> dict[str, object]:
    errors: list[str] = []
    conflicts: list[dict[str, object]] = []
    forbidden_names = {
        "mono_inertial_euroc_headless_v3", "mono_inertial_euroc", "vins_node",
        "roscore", "rosmaster", "roslaunch", "rosbag", "cc1plus", "cmake",
        "make", "ninja",
    }
    forbidden_fragments = (
        "uw_frontend.ros.export_vins_features",
        "catkin build",
        "catkin_make",
    )
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        record = process_record(int(entry.name))
        names = {Path(str(record["executable"])).name.lower(), str(record["comm"]).lower()}
        names.update(Path(str(value)).name.lower() for value in record["tokens"])
        command = str(record["command"])
        if names & forbidden_names or any(fragment in command for fragment in forbidden_fragments):
            conflicts.append(record)
    if conflicts:
        errors.append("CONFLICTING_ESTIMATOR_EXPORTER_ROS_OR_COMPILER_PROCESS")
    query = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,uuid,driver_version,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    gpu_row = query.stdout.strip()
    if query.returncode != 0 or not gpu_row:
        errors.append("GPU_QUERY_FAILED")
    compute = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    competing_compute: list[str] = []
    for line in compute.stdout.splitlines():
        lower = line.lower()
        if line.strip() and "todesk" not in lower:
            fields = [item.strip() for item in line.split(",")]
            if fields and fields[0].isdigit() and int(fields[0]) != os.getpid():
                competing_compute.append(line.strip())
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_QUERY_FAILED")
    elif competing_compute:
        errors.append("COMPETING_GPU_COMPUTE_APPLICATION")
    disk_probe = EXPERIMENT_ROOT if EXPERIMENT_ROOT.exists() else EXPERIMENT_ROOT.parent
    free_bytes = shutil.disk_usage(disk_probe).free
    if free_bytes < MIN_MNT_FREE_BYTES:
        errors.append("MNT_FREE_SPACE_BELOW_5_GIB")
    root_free_bytes = shutil.disk_usage(ROOT).free
    if root_free_bytes < MIN_ROOT_FREE_BYTES:
        errors.append("ROOT_FREE_SPACE_BELOW_512_MIB")
    return {
        "checked_at_utc": now_utc(),
        "ready": not errors,
        "errors": errors,
        "conflicting_processes": conflicts,
        "gpu": gpu_row,
        "compute_applications": [line for line in compute.stdout.splitlines() if line.strip()],
        "competing_compute_applications": competing_compute,
        "mnt_free_bytes": free_bytes,
        "root_free_bytes": root_free_bytes,
        "todesk_may_be_present": True,
        "runtime_claim_allowed": False,
    }


def verify_attempt(
    case_id: str,
    budget: int,
    repeat: int,
    require_unstarted: bool,
    attempt_index: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    experiment = load_experiment()
    root = attempt_root(case_id, budget, repeat, attempt_index)
    attempt = json.loads((root / "attempt_manifest.json").read_text(encoding="utf-8"))
    if (
        attempt.get("case_id") != case_id
        or attempt.get("budget") != budget
        or attempt.get("repeat") != repeat
        or int(attempt.get("attempt_index", 1)) != attempt_index
    ):
        raise ContractError("ATTEMPT_COORDINATE_MISMATCH")
    case = experiment["cases"][case_id]
    checks = [
        (root / "runtime_config_openloop.yaml", attempt["runtime_config"]),
        (root / "cam0_times_vins_matched.txt", attempt["selected_times"]),
        (root / "run_local_model/HFNet-RT/HF-Net.onnx", attempt["local_onnx_pre"]),
    ]
    for path, expected in checks:
        actual = identity(path)
        if actual["size_bytes"] != expected["size_bytes"] or actual["sha256"] != expected["sha256"]:
            raise ContractError(f"ATTEMPT_INPUT_DRIFT:{path}")
    case_manifest_path = EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
    case_manifest_identity = identity(case_manifest_path)
    expected_case_manifest = attempt["case_manifest"]
    if (
        case_manifest_identity["size_bytes"], case_manifest_identity["sha256"]
    ) != (expected_case_manifest["size_bytes"], expected_case_manifest["sha256"]):
        raise ContractError("CASE_MANIFEST_DRIFT")
    case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
    selected = read_ns_lines(root / "cam0_times_vins_matched.txt")
    for key in ("source_times", "source_materialization_manifest", "imu"):
        expected = case_manifest[key]
        observed = identity(Path(expected["path"]))
        if (observed["size_bytes"], observed["sha256"]) != (
            expected["size_bytes"], expected["sha256"]
        ):
            raise ContractError(f"FROZEN_SOURCE_INPUT_DRIFT:{key}")
    observed_images = image_inventory(Path(case_manifest["input_root"]), selected)
    if observed_images != case_manifest["images"]:
        raise ContractError("FROZEN_IMAGE_INVENTORY_DRIFT")
    observed_bracket = imu_bracket(
        parse_imu_stamps(Path(case_manifest["imu"]["path"])), selected, case_id
    )
    if observed_bracket != case_manifest["imu_bracket"]:
        raise ContractError("FROZEN_IMU_BRACKET_DRIFT")
    cache = identity(root / "run_local_model/HFNet-RT/HF-Net.cache")
    if require_unstarted and cache != attempt["local_cache_seed_pre"]:
        raise ContractError("CACHE_SEED_PRESTART_DRIFT")
    validate_generated_config(
        root / "runtime_config_openloop.yaml",
        int(case["nominal_fps"]),
        budget,
        root / "run_local_model/HFNet-RT",
    )
    if require_unstarted and any((root / name).exists() for name in ("start_claim.json", "run_result.json")):
        raise ContractError("ATTEMPT_ALREADY_STARTED_OR_TERMINAL")
    return experiment, attempt


def integral_epoch_ns(token: str, row: int) -> int:
    try:
        value = Decimal(token)
    except InvalidOperation as error:
        raise ValueError(f"ROW_{row}_TIMESTAMP_DECIMAL") from error
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError(f"ROW_{row}_TIMESTAMP_NOT_INTEGRAL")
    return int(value)


def parse_trajectory(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    result: dict[str, Any] = {"exists": path.is_file(), "valid": False, "pose_count": 0, "errors": []}
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    associated: list[int] = []
    used: set[int] = set()
    previous_serialized: int | None = None
    previous_index: int | None = None
    for line_number, raw in enumerate((line for line in path.read_text(encoding="ascii").splitlines() if line.strip()), 1):
        fields = raw.split()
        if len(fields) != 8:
            result["errors"].append(f"ROW_{line_number}_FIELD_COUNT")
            continue
        try:
            stamp = integral_epoch_ns(fields[0], line_number)
            pose = [float(value) for value in fields[1:]]
        except ValueError:
            result["errors"].append(f"ROW_{line_number}_PARSE")
            continue
        if not all(math.isfinite(value) for value in pose):
            result["errors"].append(f"ROW_{line_number}_NONFINITE")
            continue
        if abs(math.sqrt(sum(value * value for value in pose[3:7])) - 1.0) > 1e-3:
            result["errors"].append(f"ROW_{line_number}_QUATERNION_NORM")
            continue
        if previous_serialized is not None and stamp <= previous_serialized:
            result["errors"].append(f"ROW_{line_number}_TIMESTAMP_NOT_STRICT")
            continue
        previous_serialized = stamp
        lower = bisect.bisect_left(stamps, stamp - ASSOCIATION_TOLERANCE_NS)
        upper = bisect.bisect_right(stamps, stamp + ASSOCIATION_TOLERANCE_NS)
        if upper - lower != 1 or lower in used or (previous_index is not None and lower <= previous_index):
            result["errors"].append(f"ROW_{line_number}_ASSOCIATION_NOT_UNIQUE_OR_STRICT")
            continue
        used.add(lower)
        associated.append(lower)
        previous_index = lower
    longest = current = 0
    longest_start = longest_end = current_start = previous = None
    for index in associated:
        if previous is not None and index == previous + 1:
            current += 1
        else:
            current = 1
            current_start = index
        if current > longest:
            longest, longest_start, longest_end = current, current_start, index
        previous = index
    result.update(
        {
            "valid": bool(associated) and not result["errors"],
            "pose_count": len(associated),
            "first_relative_index": associated[0] if associated else None,
            "last_relative_index": associated[-1] if associated else None,
            "coverage_fraction": len(associated) / len(stamps),
            "longest_contiguous_count": longest,
            "longest_contiguous_fraction": longest / len(stamps),
            "longest_contiguous_relative_indices_inclusive": [longest_start, longest_end] if longest_start is not None else None,
            "identity": identity(path),
        }
    )
    return result


def parse_log(stdout_path: Path, stderr_path: Path, admitted_count: int) -> dict[str, Any]:
    if not stdout_path.is_file() or not stderr_path.is_file():
        return {
            "valid": False, "errors": ["STDOUT_OR_STDERR_MISSING"],
            "init_frame_ids": [], "reset_events": [], "solver_risk_events": [],
        }
    lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    stderr_lines = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
    errors: list[str] = []
    init_ids: list[int] = []
    reset_events: list[dict[str, object]] = []
    risk_events: list[dict[str, object]] = []
    last_init: int | None = None
    pending: list[dict[str, object]] = []
    risk_pattern = re.compile(
        r"Cholesky failure|FAIL LOCAL-INERTIAL BA|Fail to track local map|"
        r"Sophus.*ensure|(?<![A-Za-z])(?:[-+]?nan|[-+]?inf(?:inity)?)(?![A-Za-z])",
        re.IGNORECASE,
    )
    reset_pattern = re.compile(
        r"SYSTEM-> Reseting active map|LM: Reseting Atlas|Timestamp jump detected",
        re.IGNORECASE,
    )
    for line_number, line in enumerate(lines, 1):
        match = re.search(r"Init frame id:\s*(\d+)", line)
        if match:
            frame_id = int(match.group(1))
            for event in pending:
                event["next_init_frame_id"] = frame_id
            pending.clear()
            last_init = frame_id
            init_ids.append(frame_id)
        if reset_pattern.search(line):
            event = {
                "stream": "stdout", "line_number": line_number,
                "preceding_init_frame_id": last_init, "next_init_frame_id": None,
                "line_sha256": hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(),
            }
            reset_events.append(event)
            pending.append(event)
        if risk_pattern.search(line):
            event = {
                "stream": "stdout", "line_number": line_number,
                "preceding_init_frame_id": last_init, "next_init_frame_id": None,
                "line_sha256": hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(),
            }
            risk_events.append(event)
            pending.append(event)
    for line_number, line in enumerate(stderr_lines, 1):
        if risk_pattern.search(line):
            risk_events.append(
                {
                    "stream": "stderr", "line_number": line_number,
                    "preceding_init_frame_id": None, "next_init_frame_id": None,
                    "line_sha256": hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(),
                }
            )
    if any(frame_id < 0 or frame_id >= admitted_count for frame_id in init_ids):
        errors.append("INITIALIZATION_FRAME_ID_OUT_OF_RANGE")
    if any(right <= left for left, right in zip(init_ids, init_ids[1:])):
        errors.append("INITIALIZATION_FRAME_IDS_NOT_STRICT")
    saving = max((index for index, line in enumerate(lines) if line.startswith("Saving trajectory to ")), default=-1)
    tail = lines[saving + 1 :] if saving >= 0 else []
    atlas_count = None
    atlas_position = -1
    for index, line in enumerate(tail):
        match = re.search(r"There are (\d+) maps in (?:the )?atlas", line)
        if match:
            atlas_count, atlas_position = int(match.group(1)), index
    end_position = next((index for index, line in enumerate(tail[atlas_position + 1 :], start=atlas_position + 1) if line.startswith("End of saving trajectory to ")), -1) if atlas_position >= 0 else -1
    map_rows: list[tuple[int, int]] = []
    if atlas_position >= 0 and end_position >= 0:
        for line in tail[atlas_position + 1 : end_position]:
            match = re.fullmatch(r"\s*Map (\d+) has (\d+) KFs\s*", line)
            if match:
                map_rows.append((int(match.group(1)), int(match.group(2))))
    exact = bool(atlas_count is not None and end_position >= 0 and len(map_rows) == atlas_count and {row[0] for row in map_rows} == set(range(atlas_count)))
    environment_failure_pattern = re.compile(
        r"CUDA driver version is insufficient|no CUDA-capable device|"
        r"cannot open shared object file|cudaErrorInsufficientDriver|"
        r"failed to (?:load|deserialize).*(?:model|engine|cache|onnx)",
        re.IGNORECASE,
    )
    environment_failures = [
        {"stream": stream, "line_number": index + 1}
        for stream, stream_lines in (("stdout", lines), ("stderr", stderr_lines))
        for index, line in enumerate(stream_lines)
        if environment_failure_pattern.search(line)
    ]
    return {
        "valid": exact and not errors,
        "errors": errors,
        "init_frame_ids": init_ids,
        "initialization_count": len(init_ids),
        "reinitialization_count": max(0, len(init_ids) - 1),
        "reset_events": reset_events,
        "active_map_reset_count": len(reset_events),
        "solver_risk_events": risk_events,
        "solver_risk_count": len(risk_events),
        "atlas_map_count": atlas_count,
        "map_keyframes": [row[1] for row in map_rows],
        "final_atlas_nonempty": bool(exact and any(row[1] > 0 for row in map_rows)),
        "trajectory_save_completed": end_position >= 0,
        "loop_event_text_count": sum(bool(re.search(r"loop detected|loop fusion|global bundle adjustment", line, re.IGNORECASE)) for line in lines),
        "environment_failure_events": environment_failures,
        "stdout_identity": identity(stdout_path),
        "stderr_identity": identity(stderr_path),
    }


def accepted_events(log: Mapping[str, Any], trajectory: Mapping[str, Any]) -> dict[str, object]:
    accepted = trajectory.get("longest_contiguous_relative_indices_inclusive")
    if not isinstance(accepted, list) or len(accepted) != 2 or not all(isinstance(value, int) for value in accepted):
        return {
            "proven_early_resets": [],
            "unresolved_resets": list(log.get("reset_events", [])),
            "proven_early_solver_risks": [],
            "unresolved_solver_risks": list(log.get("solver_risk_events", [])),
            "support_reinitializations": list(log.get("init_frame_ids", [])[1:]),
        }
    start, end = accepted
    resets = list(log.get("reset_events", []))
    early = [event for event in resets if event.get("next_init_frame_id") is not None and int(event["next_init_frame_id"]) <= start]
    unresolved = [event for event in resets if event not in early]
    risks = list(log.get("solver_risk_events", []))
    early_risks = [
        event for event in risks
        if event.get("next_init_frame_id") is not None
        and int(event["next_init_frame_id"]) <= start
    ]
    unresolved_risks = [event for event in risks if event not in early_risks]
    reinits = [
        int(value) for value in list(log.get("init_frame_ids", []))[1:]
        if start < int(value) <= end
    ]
    return {
        "proven_early_resets": early,
        "unresolved_resets": unresolved,
        "proven_early_solver_risks": early_risks,
        "unresolved_solver_risks": unresolved_risks,
        "support_reinitializations": reinits,
    }


def runtime_environment(tmp_root: Path) -> dict[str, str]:
    tmp_root.mkdir(parents=True, exist_ok=True)
    return {
        "CUDA_VISIBLE_DEVICES": "0",
        "HOME": "/home/ma",
        "USER": "ma",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(tmp_root / "tmp"),
        "XDG_CACHE_HOME": str(tmp_root / "xdg_cache"),
        "CUDA_CACHE_PATH": str(tmp_root / "cuda_cache"),
        "LD_LIBRARY_PATH": ":".join(
            [
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib",
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Thirdparty/g2o/lib",
                "/home/ma/SLAM/aqua_deps/install/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/lib/x86_64-linux-gnu",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.6/targets/x86_64-linux/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.8/targets/x86_64-linux/lib",
            ]
        ),
    }


def terminate(process: subprocess.Popen[bytes]) -> tuple[int | None, bool]:
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
        try:
            return process.wait(timeout=10), True
        except subprocess.TimeoutExpired:
            continue
    return process.poll(), process.poll() is not None


def process_start_receipt(process: subprocess.Popen[bytes], attempt: Mapping[str, Any]) -> dict[str, object]:
    proc = Path("/proc") / str(process.pid)
    errors: list[str] = []
    try:
        start_ticks = int((proc / "stat").read_text().split()[21])
    except (OSError, ValueError, IndexError):
        start_ticks = None
        errors.append("START_TICKS_UNREADABLE")
    try:
        executable = os.readlink(proc / "exe")
    except OSError:
        executable = ""
        errors.append("EXECUTABLE_UNREADABLE")
    try:
        argv = [
            token.decode("utf-8", errors="replace")
            for token in (proc / "cmdline").read_bytes().split(b"\0") if token
        ]
    except OSError:
        argv = []
        errors.append("ARGV_UNREADABLE")
    try:
        pgid = os.getpgid(process.pid)
    except OSError:
        pgid = None
        errors.append("PGID_UNREADABLE")
    expected_argv = [str(value) for value in attempt["launch"]["argv"]]
    if executable != str(BINARY):
        errors.append("EXECUTABLE_MISMATCH")
    if argv != expected_argv:
        errors.append("ARGV_MISMATCH")
    if pgid != process.pid:
        errors.append("PROCESS_GROUP_MISMATCH")
    return {
        "schema_version": "aqua-fe-fair-stability-hfnet-launch-receipt-v1",
        "valid": not errors,
        "errors": errors,
        "pid": process.pid,
        "start_ticks": start_ticks,
        "pgid": pgid,
        "executable": executable,
        "argv": argv,
        "expected_executable": str(BINARY),
        "expected_argv": expected_argv,
    }


def reap_process_group(pgid: int) -> bool:
    for _ in range(10):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.2)
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, signal_value)
        except ProcessLookupError:
            return False
        time.sleep(1.0)
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
    return False


def residual_attempt_processes(attempt: Mapping[str, Any], pgid: int | None) -> list[dict[str, object]]:
    needles = [str(attempt["attempt_root"])] + [str(value) for value in attempt["launch"]["argv"][1:]]
    residuals: list[dict[str, object]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        pid = int(entry.name)
        record = process_record(pid)
        try:
            observed_pgid = os.getpgid(pid)
        except OSError:
            observed_pgid = None
        command = str(record["command"])
        if (pgid is not None and observed_pgid == pgid) or any(
            needle in command for needle in needles
        ):
            record["pgid"] = observed_pgid
            residuals.append(record)
    return residuals


def run_attempt(case_id: str, budget: int, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    experiment, attempt = verify_attempt(case_id, budget, repeat, True, attempt_index)
    root = attempt_root(case_id, budget, repeat, attempt_index)
    lock_path = EXPERIMENT_ROOT / ".gpu_serial.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        ordinal_state = authorize_ordinal(
            EXPERIMENT_ROOT,
            case_id,
            f"hfnet_openloop_{budget}",
            repeat,
            attempt_index,
        )
        dispatch = verify_dispatch_claim(
            EXPERIMENT_ROOT,
            root,
            case_id,
            f"hfnet_openloop_{budget}",
            repeat,
            attempt_index,
        )
        gate = resource_gate()
        if gate["ready"] is not True:
            raise ContractError(f"RESOURCE_GATE_BLOCKED:{gate['errors']}")
        verify_attempt(case_id, budget, repeat, True, attempt_index)
        claim = {
            "schema_version": "aqua-fe-fair-stability-hfnet-start-claim-v1",
            "claimed_at_utc": now_utc(),
            "case_id": case_id,
            "budget": budget,
            "repeat": repeat,
            "attempt_index": attempt_index,
            "planned_ordinal": int(ordinal_state["cell"]["ordinal"]),
            "ordinal_state_before_start": ordinal_state,
            "ordinal_dispatch": dispatch,
            "resource_gate": gate,
            "attempt_manifest": identity(root / "attempt_manifest.json"),
            "runner": identity(RUNNER),
        }
        write_exclusive(root / "start_claim.json", canonical_json(claim))
        stdout_path = root / "headless.stdout.log"
        stderr_path = root / "headless.stderr.log"
        started = now_utc()
        start_monotonic = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        returncode: int | None = None
        reaped = False
        timed_out = False
        supervisor_error: str | None = None
        launch_receipt: dict[str, object] | None = None
        deferred_postprocess_signals: list[int] = []

        def defer_postprocess_signal(signum: int, _frame: object) -> None:
            deferred_postprocess_signals.append(signum)

        previous_handlers = {
            value: signal.getsignal(value) for value in (signal.SIGTERM, signal.SIGINT)
        }
        for value in previous_handlers:
            signal.signal(value, raise_supervisor_interrupt)
        try:
            environment = runtime_environment(root / "runtime_temp")
            for key in ("TMPDIR", "XDG_CACHE_HOME", "CUDA_CACHE_PATH"):
                Path(environment[key]).mkdir(parents=True, exist_ok=True)
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = subprocess.Popen(
                    attempt["launch"]["argv"],
                    cwd=attempt["launch"]["cwd"],
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                launch_receipt = process_start_receipt(process, attempt)
                write_exclusive(
                    root / "launch_receipt.json", canonical_json(launch_receipt)
                )
                try:
                    returncode = process.wait(timeout=TIMEOUT_SECONDS)
                    reaped = True
                except subprocess.TimeoutExpired:
                    timed_out = True
                    returncode, reaped = terminate(process)
        except BaseException as error:
            supervisor_error = f"{type(error).__name__}:{error}"
            if process is not None and not reaped:
                returncode, reaped = terminate(process)
        finally:
            for value in previous_handlers:
                signal.signal(value, defer_postprocess_signal)
        execution = {
            "started_at_utc": started,
            "ended_at_utc": now_utc(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "raw_returncode": returncode,
            "timed_out": timed_out,
            "child_reaped": reaped,
            "supervisor_error": supervisor_error,
            "popen_invocations": 1 if process is not None else 0,
            "postprocess_signals_deferred": deferred_postprocess_signals,
        }
        process_group_clean = True if process is None else reap_process_group(process.pid)
        residuals = residual_attempt_processes(attempt, process.pid if process is not None else None)
        execution["supervised_process_group_empty_after_wait"] = process_group_clean
        execution["residual_attempt_processes"] = residuals
        stamps = read_ns_lines(root / "cam0_times_vins_matched.txt")
        trajectory = parse_trajectory(root / "result/trajectory.txt", stamps)
        keyframes = parse_trajectory(root / "result/trajectory_keyframe.txt", stamps)
        log = parse_log(stdout_path, stderr_path, len(stamps))
        events = accepted_events(log, trajectory)
        init_ids = [
            int(value) for value in log.get("init_frame_ids", [])
            if 0 <= int(value) < len(stamps)
        ]
        init_latency = (
            (stamps[int(init_ids[0])] - stamps[0]) / 1e9 if init_ids else None
        )
        pipeline_failures: list[str] = []
        algorithm_failures: list[str] = []
        if process is None or supervisor_error is not None or not reaped:
            pipeline_failures.append("SUPERVISOR_LAUNCH_OR_REAP_FAILED")
        if launch_receipt is None or launch_receipt.get("valid") is not True:
            pipeline_failures.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        if not process_group_clean or residuals:
            algorithm_failures.append("SUPERVISED_DESCENDANT_RESIDUAL")
        if timed_out:
            algorithm_failures.append("ESTIMATOR_TIMEOUT")
        if returncode not in (None, 0) and not timed_out:
            if log.get("environment_failure_events"):
                pipeline_failures.append("GPU_DRIVER_OR_RUNTIME_LOAD_FAILURE")
            else:
                algorithm_failures.append("ESTIMATOR_NONZERO_EXIT")
        if trajectory.get("valid") is not True:
            algorithm_failures.append("TRAJECTORY_INVALID")
        coverage = float(trajectory.get("coverage_fraction", 0.0))
        contiguous = float(trajectory.get("longest_contiguous_fraction", 0.0))
        if coverage < MIN_PARTIAL_COVERAGE or contiguous < MIN_PARTIAL_COVERAGE:
            algorithm_failures.append("TRAJECTORY_COVERAGE_BELOW_50_PERCENT")
        elif coverage < MIN_SUCCESS_COVERAGE or contiguous < MIN_SUCCESS_COVERAGE:
            algorithm_failures.append("PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
        if keyframes.get("valid") is not True or int(keyframes.get("pose_count", 0)) < 1:
            algorithm_failures.append("NO_VALID_KEYFRAME_TRAJECTORY")
        if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
            algorithm_failures.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
        if init_latency is None:
            algorithm_failures.append("NO_SUCCESSFUL_INITIALIZATION")
        elif init_latency > MAX_INIT_LATENCY_S:
            algorithm_failures.append("INITIALIZATION_AFTER_10_SECONDS")
        if events["unresolved_resets"]:
            algorithm_failures.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
        if events["unresolved_solver_risks"]:
            algorithm_failures.append("SOLVER_OR_TRACKING_RISK_BOUNDARY_UNRESOLVED")
        if events["support_reinitializations"]:
            algorithm_failures.append("REINITIALIZATION_WITHIN_ACCEPTED_SUPPORT")
        if int(log.get("loop_event_text_count", 0)):
            algorithm_failures.append("LOOP_EVENT_OBSERVED_DESPITE_OPEN_LOOP_CONFIG")

        integrity: dict[str, object] = {}
        for label, path in (
            ("local_onnx_post", root / "run_local_model/HFNet-RT/HF-Net.onnx"),
            ("local_cache_post", root / "run_local_model/HFNet-RT/HF-Net.cache"),
            ("runtime_config", root / "runtime_config_openloop.yaml"),
            ("selected_times", root / "cam0_times_vins_matched.txt"),
        ):
            try:
                integrity[label] = identity(path)
            except BaseException as error:
                integrity[label] = {"error": f"{type(error).__name__}:{error}"}
                pipeline_failures.append(f"POSTRUN_IDENTITY_UNREADABLE:{label}")
        local_onnx_post = integrity["local_onnx_post"]
        if isinstance(local_onnx_post, Mapping) and local_onnx_post.get("sha256") != EXPECTED_STACK["onnx"][1]:
            pipeline_failures.append("ONNX_MODEL_DRIFT")
        runtime_config_post = integrity["runtime_config"]
        if isinstance(runtime_config_post, Mapping) and runtime_config_post.get("sha256") != attempt["runtime_config"]["sha256"]:
            pipeline_failures.append("RUNTIME_CONFIG_DRIFT")
        selected_times_post = integrity["selected_times"]
        if isinstance(selected_times_post, Mapping) and selected_times_post.get("sha256") != attempt["selected_times"]["sha256"]:
            pipeline_failures.append("SELECTED_TIMESTAMPS_DRIFT")
        try:
            verify_attempt(case_id, budget, repeat, False, attempt_index)
            integrity["full_frozen_input_and_stack_reverification"] = "PASS"
        except BaseException as error:
            integrity["full_frozen_input_and_stack_reverification"] = (
                f"FAIL:{type(error).__name__}:{error}"
            )
            pipeline_failures.append("POSTRUN_FROZEN_INPUT_OR_STACK_REVERIFICATION_FAILED")
        integrity["local_cache_seed_pre"] = attempt["local_cache_seed_pre"]
        local_cache_post = integrity["local_cache_post"]
        integrity["cache_mutation_expected"] = True
        integrity["cache_changed"] = bool(
            isinstance(local_cache_post, Mapping)
            and local_cache_post.get("sha256") != attempt["local_cache_seed_pre"]["sha256"]
        )

        pipeline_failures = list(dict.fromkeys(pipeline_failures))
        algorithm_failures = list(dict.fromkeys(algorithm_failures))
        if pipeline_failures:
            status = "PIPELINE_INVALID"
        elif not algorithm_failures:
            status = "SUCCESS"
        elif algorithm_failures == ["PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT"]:
            status = "PARTIAL_NON_SUCCESS"
        else:
            status = "ALGORITHM_FAILURE"
        failures = pipeline_failures + algorithm_failures
        clean_success = (
            status == "SUCCESS"
            and int(log.get("active_map_reset_count", 0)) == 0
            and int(log.get("solver_risk_count", 0)) == 0
            and int(log.get("reinitialization_count", 0)) == 0
            and len(init_ids) == 1
        )
        result = {
            "schema_version": "aqua-fe-fair-stability-hfnet-result-v1",
            "status": status,
            "clean_success": clean_success,
            "case_id": case_id,
            "arm": f"hfnet_openloop_{budget}",
            "repeat": repeat,
            "attempt_index": attempt_index,
            "failure_codes": failures,
            "pipeline_failure_codes": pipeline_failures,
            "algorithm_failure_codes": algorithm_failures,
            "execution": execution,
            "launch_receipt": launch_receipt,
            "support": {"trajectory": trajectory, "keyframes": keyframes, "log": log, "events": events},
            "initialization_latency_seconds": init_latency,
            "integrity": integrity,
            "claim_boundary": {
                "outcome_selected_roster": True,
                "loop_closing_disabled": True,
                "system_ranking_supported": False,
                "runtime_claim_allowed": False,
                "failed_accuracy_is_na": True,
            },
        }
        write_exclusive(root / "run_result.json", canonical_json(result))
        for value, handler in previous_handlers.items():
            signal.signal(value, handler)
        return result


def summary() -> dict[str, object]:
    load_experiment()
    rows: list[dict[str, object]] = []
    for budget in BUDGETS:
        for case_id in CASE_ORDER:
            for repeat in REPEATS:
                result_path = attempt_root(case_id, budget, repeat) / "run_result.json"
                if result_path.is_file():
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    rows.append(
                        {
                            "case_id": case_id,
                            "arm": f"hfnet_openloop_{budget}",
                            "repeat": repeat,
                            "status": result["status"],
                            "clean_success": result["clean_success"],
                            "failure_codes": result["failure_codes"],
                            "coverage": result["support"]["trajectory"].get("coverage_fraction"),
                            "contiguous_coverage": result["support"]["trajectory"].get("longest_contiguous_fraction"),
                            "initialization_latency_seconds": result.get("initialization_latency_seconds"),
                        }
                    )
    aggregate: dict[str, object] = {}
    for budget in BUDGETS:
        arm = f"hfnet_openloop_{budget}"
        arm_rows = [row for row in rows if row["arm"] == arm]
        aggregate[arm] = {
            "completed": len(arm_rows),
            "successes": sum(row["status"] == "SUCCESS" for row in arm_rows),
            "clean_successes": sum(bool(row["clean_success"]) for row in arm_rows),
            "planned": len(CASE_ORDER) * len(REPEATS),
        }
    report = {
        "schema_version": "aqua-fe-fair-stability-hfnet-summary-v1",
        "generated_at_utc": now_utc(),
        "rows": rows,
        "aggregate": aggregate,
        "claim_boundary": "DEVELOPMENT_OUTCOME_SELECTED_ROSTER_NO_SYSTEM_RANKING",
    }
    output = EXPERIMENT_ROOT / "hfnet_progress_summary.json"
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_json(report))
    os.replace(temporary, output)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("freeze-inputs")
    subparsers.add_parser("prepare-all")
    for name in ("prepare", "check", "run"):
        child = subparsers.add_parser(name)
        child.add_argument("--case", required=True, choices=CASE_ORDER)
        child.add_argument("--budget", required=True, type=int, choices=BUDGETS)
        child.add_argument("--repeat", required=True, type=int, choices=REPEATS)
        child.add_argument("--attempt-index", type=int, default=1)
    subparsers.add_parser("resource-check")
    subparsers.add_parser("summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "freeze-inputs":
            result = freeze_inputs()
        elif args.command == "prepare-all":
            result = {"prepared_count": len(prepare_all())}
        elif args.command == "prepare":
            result = prepare_attempt(args.case, args.budget, args.repeat, args.attempt_index)
        elif args.command == "check":
            _, attempt = verify_attempt(
                args.case, args.budget, args.repeat, True, args.attempt_index
            )
            gate = resource_gate()
            result = {"attempt": attempt, "resource_gate": gate, "ready": gate["ready"]}
        elif args.command == "run":
            result = run_attempt(args.case, args.budget, args.repeat, args.attempt_index)
        elif args.command == "resource-check":
            result = resource_gate()
        elif args.command == "summary":
            result = summary()
        else:  # pragma: no cover
            raise ContractError("UNKNOWN_COMMAND")
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        if args.command in ("check", "resource-check") and result.get("ready") is not True:
            return 2
        if args.command == "run" and result.get("status") != "SUCCESS":
            return 3
        return 0
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
