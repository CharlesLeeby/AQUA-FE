#!/usr/bin/env python3
"""Run the preregistered geometry-maturity router v1 frontend matrix."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_geometry_maturity_router_v1"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_geometry_maturity_router_v1"
)
SHADOW = RUNTIME / "shadow_root"
RUN_LABEL = "gmrv1"
CELL_SCHEMA = "aqua-fe-geometry-maturity-router-v1-cell-v1"
METHOD_LOCK_FILENAME = "method_lock.json"
CUDA_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")

REGISTRATION = {
    PAPER / "preregistration.md": "bcf689fc960c20795f08e62b2d464771586d654e2b4d0da3aa78c7eb30cfb95b",
    PAPER / "development_windows.csv": "8fb87b023f525da6610ced4fa591916399b4750c01f1d96177ca47e04cde9915",
    PAPER / "arms.csv": "5daa58db38c14551fae9fe8f1f8b7dfae2d9a80b5ff5558cd2f1d350164188d6",
}

PROFILE_ENV_PREFIXES = (
    "AQUAFE_", "LEARNED_EXPORT_", "FINAL_MIRROR_", "FORMAL_EXPORT_",
    "VINS_SAFE_", "BACKEND_", "MEASUREMENT_SELECTION",
)
PROFILE_ENV_NAMES = {
    "EXPORT_CLASSICAL_MIRROR_BACKBONE", "EXPORT_MAX_FEATURES",
    "EXPORT_MIN_AGE", "EXPORT_MIN_LEARNED_AGE", "FEATURE_BAG",
    "FEATURE_BAG_OVERRIDE", "FORCE_EXPORT", "FORCE_RAW", "FRONTEND_CONFIG",
    "GT_TXT", "PREPARE_BAG", "RAW_BAG", "RAW_TAR", "RUN_DIR", "RUN_VINS",
    "SHORT_BAG", "TAG", "TAG_BASE",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def verify_registration_and_method() -> dict:
    for path, expected in REGISTRATION.items():
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            raise RuntimeError(f"registration hash mismatch: {path}: {actual}")
    lock_path = PAPER / METHOD_LOCK_FILENAME
    if not lock_path.is_file():
        raise FileNotFoundError(
            f"{METHOD_LOCK_FILENAME} must be created before execution"
        )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for item in lock["files"]:
        path = ROOT / item["path"]
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != item["sha256"]:
            raise RuntimeError(f"method hash mismatch: {path}: {actual}")
    for row in read_csv(PAPER / "development_windows.csv"):
        path = Path(row["input_bag"])
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != row["input_bag_sha256"]:
            raise RuntimeError(f"input hash mismatch: {path}: {actual}")
    root_free = shutil.disk_usage(ROOT).free
    runtime_free = shutil.disk_usage(RUNTIME.parent).free
    if root_free < 2 * 1024**3:
        raise RuntimeError(f"root free space below 2 GiB: {root_free}")
    if runtime_free < 8 * 1024**3:
        raise RuntimeError(f"runtime free space below 8 GiB: {runtime_free}")
    return lock


def prepare_shadow() -> None:
    SHADOW.mkdir(parents=True, exist_ok=True)
    (SHADOW / "logs").mkdir(exist_ok=True)
    for name in ("datasets", "external_tools", "papers", "scripts", "uw_frontend"):
        link = SHADOW / name
        target = ROOT / name
        if link.is_symlink():
            if link.resolve() != target.resolve():
                raise RuntimeError(f"wrong shadow link: {link}")
        elif link.exists():
            raise RuntimeError(f"shadow entry is not a symlink: {link}")
        else:
            link.symlink_to(target, target_is_directory=True)
    for path in (RUNTIME / "tmp", RUNTIME / "ros_home", RUNTIME / "ros_logs"):
        path.mkdir(parents=True, exist_ok=True)


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key in PROFILE_ENV_NAMES or key.startswith(PROFILE_ENV_PREFIXES):
            env.pop(key, None)
    return env


def data_manifest(sequence: str, family: str) -> dict[str, str]:
    rows = [
        row for row in read_csv(
            ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
        )
        if row["sequence"] == sequence and row["dataset_family"] == family
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected one data-manifest row for {family}/{sequence}")
    return rows[0]


def camera_topic(camchain: Path) -> str:
    import yaml

    payload = yaml.safe_load(camchain.read_text(encoding="utf-8"))
    return str(payload["cam0"]["rostopic"])


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"{RUN_LABEL}_{window['run_slug']}_{arm['arm']}"
    )


def command_and_env(
    window: dict[str, str], arm: dict[str, str]
) -> tuple[list[str], dict[str, str], Path]:
    output = run_dir(window, arm)
    manifest = data_manifest(window["sequence"], window["family"])
    reference = ROOT / manifest["reference_path"]
    input_bag = Path(window["input_bag"])
    env = clean_environment()
    env.update(
        {
            "ROOT": str(SHADOW),
            "VINS_WS": str(VINS_WS),
            "PATH": f"{CUDA_BIN}:{env.get('PATH', '')}",
            "PYTHONPATH": f"{ROOT}:{env.get('PYTHONPATH', '')}",
            "TMPDIR": str(RUNTIME / "tmp"),
            "ROS_HOME": str(RUNTIME / "ros_home"),
            "ROS_LOG_DIR": str(RUNTIME / "ros_logs"),
            "CUDA_VISIBLE_DEVICES": "0",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "RUN_VINS": "0",
            "FORCE_EXPORT": "1",
            "EXPORT_FEATURES": "1",
            "FORCE_RAW": "0",
            "AQUAFE_SEEDCHAIN_PROFILE": arm["profile"],
            "FRONTEND_CONFIG": str(
                ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
            ),
            "RAW_BAG": str(input_bag),
            "GT_TXT": str(reference),
            "RUN_DIR": str(output),
            "FEATURE_BAG": str(output / "features.bag"),
            "MEASUREMENT_SELECTION": "0",
            "EXPORT_MAX_FEATURES": "350",
            "VINS_MAX_CNT": "350",
            "VINS_SAFE_SOURCE_SELECTION": "0",
            "FORMAL_THREE_LAYER_EXPORT": "0",
            "PROCESS_SKIPPED_FRAMES": "1",
            "PREPROCESS": "adaptive_clahe",
            "SEMIDENSE_FALLBACK_METHOD": "none",
            "BACKEND_QUALITY_MODE": "vins_safe",
            "BACKEND_QUALITY_ALPHA": "0.65",
            "BACKEND_QUALITY_FLOOR": "0.80",
            "BACKEND_LEARNED_QUALITY_SCALE": "1.0",
            "BACKEND_SP_LG_QUALITY_SCALE": "1.0",
            "BACKEND_XFEAT_QUALITY_SCALE": "1.0",
            "BACKEND_LOFTR_QUALITY_SCALE": "1.0",
            "RAW_QUALITY_TO_BACKEND": "0",
            "CONSTANT_QUALITY_TO_BACKEND": "0",
            "VINS_MULTIPLE_THREAD": "0",
            "VINS_ESTIMATE_TD": "0",
            "FRAME_OFFSET": window["frame_offset"],
            "LEARNED_EXPORT_ONLINE_SEED_SOURCES": arm["seed_source"],
            "TAG": f"{RUN_LABEL}_{window['run_slug']}_{arm['arm']}",
        }
    )
    script = SHADOW / "scripts/run_learned_seedchain_eval.sh"
    if window["family"] == "aqualoc_archaeology":
        sequence_number = str(int(window["sequence"][1:]))
        command = [
            "bash", str(script), "aqualoc_archaeo", sequence_number,
            window["start_arg"], window["end_or_duration_arg"],
            arm["method"], window["every_n"],
        ]
    elif window["family"] == "aqualoc_harbor":
        command = [
            "bash", str(script), "aqualoc_real", window["sequence"],
            window["start_arg"], window["end_or_duration_arg"],
            arm["method"], window["every_n"],
        ]
    elif window["family"] == "afrl":
        afrl = ROOT / "datasets/full_downloads/afrl_hf"
        camchain = afrl / f"camera_imu_parameters/camchain_{window['sequence']}.yaml"
        env.update(
            {
                "SHORT_BAG": str(input_bag),
                "PREPARE_BAG": "0",
                "CAMCHAIN": str(camchain),
                "IMU_YAML": str(afrl / "camera_imu_parameters/imu.yaml"),
                "CAMERA_KEY": "cam0",
                "SRC_IMAGE_TOPIC": camera_topic(camchain),
                "GRAYSCALE": "1",
                "IMAGE_SCALE": "0.5",
            }
        )
        command = [
            "bash", str(script), "afrl", window["start_arg"],
            window["end_or_duration_arg"], arm["method"], window["every_n"],
        ]
    else:
        raise RuntimeError(f"unsupported family: {window['family']}")
    return command, env, output


def bag_counts(path: Path) -> dict[str, int]:
    import rosbag

    result = {"images": 0, "features": 0, "max_features": 0}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _stamp in bag.read_messages():
            if topic == "/camera/image_raw":
                result["images"] += 1
            elif topic == "/feature_tracker/feature":
                result["features"] += 1
                result["max_features"] = max(result["max_features"], len(message.points))
    return result


def cell_complete(window: dict[str, str], arm: dict[str, str]) -> bool:
    output = run_dir(window, arm)
    receipt = output / "frontend_receipt.json"
    bag = output / "features.bag"
    metrics = output / "frontend_metrics.csv"
    if not (receipt.is_file() and bag.is_file() and metrics.is_file()):
        return False
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    return (
        payload.get("return_code") == 0
        and payload.get("feature_bag_sha256") == sha256(bag)
        and payload.get("frontend_metrics_sha256") == sha256(metrics)
    )


def run_cell(window: dict[str, str], arm: dict[str, str], method_lock: dict) -> None:
    if cell_complete(window, arm):
        print(f"SKIP {window['run_slug']} {arm['arm']}", flush=True)
        return
    command, env, output = command_and_env(window, arm)
    if output.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine = RUNTIME / "quarantine" / f"partial_{window['run_slug']}_{arm['arm']}_{stamp}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(output), str(quarantine))
    output.mkdir(parents=True, exist_ok=True)
    console_path = output / "frontend_console.log"
    started = datetime.now(timezone.utc).isoformat()
    print(f"START {window['run_slug']} {arm['arm']}", flush=True)
    with console_path.open("w", encoding="utf-8") as console:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            console.write(line)
            console.flush()
            print(line, end="", flush=True)
        return_code = process.wait()
    feature_bag = output / "features.bag"
    metrics = output / "frontend_metrics.csv"
    input_counts = bag_counts(Path(window["input_bag"]))
    output_counts = bag_counts(feature_bag) if feature_bag.is_file() else {}
    expected = (input_counts["images"] + int(window["every_n"]) - 1) // int(window["every_n"])
    coverage = (
        output_counts.get("features", 0) / expected if expected else 0.0
    )
    receipt = {
        "schema_version": CELL_SCHEMA,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "window_id": window["window_id"],
        "run_slug": window["run_slug"],
        "arm": arm["arm"],
        "method": arm["method"],
        "profile": arm["profile"],
        "command": command,
        "return_code": return_code,
        "run_dir": str(output),
        "input_bag": window["input_bag"],
        "input_bag_sha256": window["input_bag_sha256"],
        "input_image_messages": input_counts["images"],
        "expected_feature_messages": expected,
        "feature_messages": output_counts.get("features", 0),
        "frontend_coverage": coverage,
        "max_features": output_counts.get("max_features", 0),
        "integrity_pass": bool(
            return_code == 0
            and output_counts.get("features", 0) > 0
            and coverage >= 0.70
            and output_counts.get("max_features", 0) <= 350
        ),
        "feature_bag": str(feature_bag),
        "feature_bag_sha256": sha256(feature_bag) if feature_bag.is_file() else None,
        "frontend_metrics": str(metrics),
        "frontend_metrics_sha256": sha256(metrics) if metrics.is_file() else None,
        "method_lock_sha256": sha256(PAPER / METHOD_LOCK_FILENAME),
        "exporter_sha256": method_lock["exporter_sha256"],
    }
    atomic_json(output / "frontend_receipt.json", receipt)
    print(
        f"DONE {window['run_slug']} {arm['arm']} rc={return_code} "
        f"coverage={coverage:.3f} max={output_counts.get('max_features', 0)}",
        flush=True,
    )
    if not receipt["integrity_pass"]:
        raise RuntimeError(f"frontend integrity failed: {window['run_slug']} {arm['arm']}")


def main() -> int:
    method_lock = verify_registration_and_method()
    prepare_shadow()
    windows = read_csv(PAPER / "development_windows.csv")
    arms = read_csv(PAPER / "arms.csv")
    for window in windows:
        for arm in arms:
            run_cell(window, arm, method_lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
