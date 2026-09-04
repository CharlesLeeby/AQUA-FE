#!/usr/bin/env python3
"""Run the preregistered frontend stage for same-backend confirmatory v3.

Large outputs are kept off /mnt/data.  The runner is serial and resumable so a
single 4 GiB GPU cannot accidentally host overlapping learned frontends.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_same_backend_confirmatory_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_same_backend_confirmatory_v3"
)
SHADOW = RUNTIME / "shadow_root"
CUDA_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")

LOCKED = {
    PAPER / "preregistration.md": "0495399e399523303d550735109e97cb6aaa0f616fb73d0ad46888e5ccfa5a26",
    PAPER / "candidate_windows.csv": "bcb929f172f8597d0665fc8eed506d9539deced55b835a31b0b05c50c7069b4d",
    PAPER / "arms.csv": "f8a3b5ac61e230ebfc2235f5034d8a4b2818893050bc40c8058ca2ee76d7e1dd",
    PAPER / "current_history_audit.csv": "03f79f1966d996ec06a8e4e29af3a9a0d7ee492c8571c8532f4304a50fc4f61e",
    PAPER / "contract.json": "3ff8c1b2fa9e7a16ff01fe21fcbfe21a7a292e405381ae20dd059852f1c930c9",
    ROOT / "papers/ieee_sensors_journal_experiments/window_selection_audit_v4.csv": "e6da25ed6338deddb85b7b7d6b016668e0a220df8f88554beec52b5e18e226d6",
    ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv": "510c276c33217706eef11ea53e58de4b37318828f8a6dc793dea9262f0a0a0f5",
    ROOT / "uw_frontend/ros/export_vins_features.py": "f4bf20b254dbcc441f899c9b9b80b0d6043063798f7e90fe850aba63e7b9620d",
    ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml": "6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3",
    ROOT / "scripts/learned_seedchain_env.sh": "805f0c747d5da5167d1e9b3a147c799d141a499ab4516bb9c49d68c639dde19e",
    ROOT / "scripts/run_learned_seedchain_eval.sh": "5a18fa6a590ae6f64311a0329c2dd5c0ddf6c79dc19ceb13ad7587e39d42410e",
    VINS_WS / "devel/lib/vins/vins_node": "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    VINS_WS / "devel/lib/libvins_lib.so": "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8",
}

PROFILE_ENV_PREFIXES = (
    "AQUAFE_",
    "LEARNED_EXPORT_",
    "FINAL_MIRROR_",
    "FORMAL_EXPORT_",
    "VINS_SAFE_",
    "BACKEND_",
    "MEASUREMENT_SELECTION",
)
PROFILE_ENV_NAMES = {
    "EXPORT_CLASSICAL_MIRROR_BACKBONE",
    "EXPORT_MAX_FEATURES",
    "EXPORT_MIN_AGE",
    "EXPORT_MIN_LEARNED_AGE",
    "FEATURE_BAG",
    "FEATURE_BAG_OVERRIDE",
    "FORCE_EXPORT",
    "FORCE_RAW",
    "FRONTEND_CONFIG",
    "GT_TXT",
    "PREPARE_BAG",
    "RAW_BAG",
    "RAW_TAR",
    "RUN_DIR",
    "RUN_VINS",
    "SHORT_BAG",
    "TAG",
    "TAG_BASE",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def verify_lock() -> None:
    root_free = shutil.disk_usage(ROOT).free
    runtime_parent = RUNTIME.parent
    runtime_parent.mkdir(parents=True, exist_ok=True)
    runtime_free = shutil.disk_usage(runtime_parent).free
    if root_free < 2 * 1024**3:
        raise RuntimeError(f"root free space below 2 GiB: {root_free}")
    if runtime_free < 8 * 1024**3:
        raise RuntimeError(f"runtime free space below 8 GiB: {runtime_free}")
    for path, expected in LOCKED.items():
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            raise RuntimeError(f"frozen hash mismatch: {path}: {actual} != {expected}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_windows() -> list[dict[str, str]]:
    return read_csv(PAPER / "candidate_windows.csv")


def load_arms() -> dict[str, dict[str, str]]:
    return {row["arm"]: row for row in read_csv(PAPER / "arms.csv")}


def symlink_once(link: Path, target: Path) -> None:
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise RuntimeError(f"wrong symlink target: {link}")
        return
    if link.exists():
        raise RuntimeError(f"refusing non-symlink shadow entry: {link}")
    link.symlink_to(target, target_is_directory=target.is_dir())


def prepare_shadow() -> None:
    SHADOW.mkdir(parents=True, exist_ok=True)
    (SHADOW / "logs").mkdir(exist_ok=True)
    for name in ("datasets", "external_tools", "papers", "scripts", "uw_frontend"):
        symlink_once(SHADOW / name, ROOT / name)
    for path in (RUNTIME / "tmp", RUNTIME / "ros_home", RUNTIME / "ros_logs"):
        path.mkdir(parents=True, exist_ok=True)


def manifest_row(family: str, sequence: str) -> dict[str, str]:
    rows = [
        row
        for row in read_csv(
            ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
        )
        if row["dataset_family"] == family and row["sequence"] == sequence
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected one data manifest row: {family}/{sequence}")
    return rows[0]


def source_path(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"missing locked input: {path}")
    return path


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key in PROFILE_ENV_NAMES or key.startswith(PROFILE_ENV_PREFIXES):
            env.pop(key, None)
    return env


def common_env(window: dict[str, str], arm: dict[str, str]) -> dict[str, str]:
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
            "AQUAFE_SEEDCHAIN_PROFILE": arm["seedchain_profile"],
            "FRONTEND_CONFIG": str(
                ROOT
                / "uw_frontend/configs/experiments/"
                "low_texture_xfeat_seedchain_frontend.yaml"
            ),
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
            "TAG": f"fsbccv3_{window['run_slug']}_{arm['arm']}",
        }
    )
    return env


def camera_topic(camchain: Path) -> str:
    import yaml

    data = yaml.safe_load(camchain.read_text(encoding="utf-8"))
    return str(data["cam0"]["rostopic"])


def command_for(
    window: dict[str, str], arm: dict[str, str]
) -> tuple[list[str], dict[str, str], Path, Path]:
    env = common_env(window, arm)
    manifest = manifest_row(window["family"], window["sequence"])
    raw_input = source_path(manifest["raw_input_path"])
    reference = source_path(manifest["reference_path"])
    prepared = RUNTIME / "prepared" / window["run_slug"] / "input.bag"
    script = SHADOW / "scripts/run_learned_seedchain_eval.sh"
    method = arm["method"]
    every_n = window["every_n"]

    if window["family"] == "aqualoc_archaeology":
        sequence_number = str(int(window["sequence"][1:]))
        env.update(
            {
                "RAW_TAR": str(raw_input),
                "RAW_BAG": str(prepared),
                "GT_TXT": str(reference),
            }
        )
        command = [
            "bash",
            str(script),
            "aqualoc_archaeo",
            sequence_number,
            window["start_arg"],
            window["end_or_duration_arg"],
            method,
            every_n,
        ]
        family_log = "aqualoc_archaeo_vins"
    elif window["family"] == "aqualoc_harbor":
        env.update(
            {
                "RAW_TAR": str(raw_input),
                "RAW_BAG": str(prepared),
                "GT_TXT": str(reference),
            }
        )
        command = [
            "bash",
            str(script),
            "aqualoc_real",
            window["sequence"],
            window["start_arg"],
            window["end_or_duration_arg"],
            method,
            every_n,
        ]
        family_log = "aqualoc_real_vins"
    elif window["family"] == "afrl":
        afrl = ROOT / "datasets/full_downloads/afrl_hf"
        camchain = afrl / f"camera_imu_parameters/camchain_{window['sequence']}.yaml"
        imu = afrl / "camera_imu_parameters/imu.yaml"
        env.update(
            {
                "RAW_BAG": str(raw_input),
                "GT_TXT": str(reference),
                "CAMCHAIN": str(camchain),
                "IMU_YAML": str(imu),
                "CAMERA_KEY": "cam0",
                "SRC_IMAGE_TOPIC": camera_topic(camchain),
                "SHORT_BAG": str(prepared),
                "PREPARE_BAG": "1",
                "GT_TIMESTAMP_MODE": "auto",
                "GRAYSCALE": "1",
                "IMAGE_SCALE": "0.5",
            }
        )
        command = [
            "bash",
            str(script),
            "afrl",
            window["start_arg"],
            window["end_or_duration_arg"],
            method,
            every_n,
        ]
        family_log = "afrl_cave_v31"
    else:
        raise RuntimeError(f"unsupported family: {window['family']}")

    run_dir = (
        SHADOW
        / "logs"
        / family_log
        / f"external_{method}_every{every_n}_{env['TAG']}"
    )
    return command, env, run_dir, prepared


def bag_audit(path: Path) -> dict:
    import rosbag

    feature_messages = 0
    max_features = 0
    first_feature_ns = None
    last_feature_ns = None
    topic_counts: dict[str, int] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages():
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if topic != "/feature_tracker/feature":
                continue
            feature_messages += 1
            max_features = max(max_features, len(message.points))
            stamp_ns = int(stamp.to_nsec())
            first_feature_ns = stamp_ns if first_feature_ns is None else first_feature_ns
            last_feature_ns = stamp_ns
    return {
        "feature_messages": feature_messages,
        "max_features": max_features,
        "first_feature_ns": first_feature_ns,
        "last_feature_ns": last_feature_ns,
        "topic_counts": topic_counts,
    }


def metric_audit(path: Path) -> dict:
    rows = read_csv(path)

    def total(field: str) -> int:
        return int(sum(float(row.get(field) or 0) for row in rows))

    decisions = sorted(
        {
            int(float(row["final_mirror_persistence_churn_guard_decision"]))
            for row in rows
            if row.get("final_mirror_persistence_churn_guard_decision") not in (None, "")
        }
    )
    decision_rows = [
        row
        for row in rows
        if row.get("final_mirror_persistence_churn_guard_decision") in ("0", "1")
    ]
    decision = {}
    if decision_rows:
        row = decision_rows[0]
        decision = {
            "decision": int(float(row["final_mirror_persistence_churn_guard_decision"])),
            "frame": int(float(row["final_mirror_persistence_churn_guard_decision_frame"])),
            "gftt_births": int(float(row["final_mirror_persistence_churn_guard_gftt_births"])),
            "denominator": int(float(row["final_mirror_persistence_churn_guard_denominator"])),
            "ratio": float(row["final_mirror_persistence_churn_guard_ratio"]),
        }
    return {
        "rows": len(rows),
        "exported_xfeat_observations": total("exported_xfeat_features"),
        "exported_splg_observations": total("exported_sp_lg_features"),
        "classical_dropped_for_sidecars": total("final_mirror_classical_dropped_for_sidecars"),
        "churn_guard_decision_values": decisions,
        "churn_guard_decision": decision,
    }


def quarantine(path: Path, label: str) -> None:
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = RUNTIME / "quarantine" / f"{label}_{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))


def run_cell(window: dict[str, str], arm: dict[str, str]) -> None:
    verify_lock()
    prepare_shadow()
    command, env, run_dir, prepared = command_for(window, arm)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    lock = RUNTIME / "locks" / f"{window['run_slug']}__{arm['arm']}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        receipt = run_dir / "confirmatory_frontend_receipt.json"
        feature_bag = run_dir / "features.bag"
        metrics = run_dir / "frontend_metrics.csv"
        if receipt.is_file() and feature_bag.is_file() and metrics.is_file():
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if saved["feature_bag_sha256"] != sha256(feature_bag):
                raise RuntimeError(f"resume hash mismatch: {feature_bag}")
            print(f"resume {window['run_slug']} {arm['arm']}", flush=True)
            return
        if run_dir.exists():
            quarantine(run_dir, f"partial_{window['run_slug']}_{arm['arm']}")
        run_dir.mkdir(parents=True, exist_ok=True)
        prepared.parent.mkdir(parents=True, exist_ok=True)
        console = run_dir / "frontend_console.log"
        print(f"start {window['run_slug']} {arm['arm']}", flush=True)
        with console.open("w", encoding="utf-8") as output:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        if result.returncode != 0 or not feature_bag.is_file() or not metrics.is_file():
            atomic_json(
                run_dir / "failed_receipt.json",
                {
                    "window_id": window["window_id"],
                    "arm": arm["arm"],
                    "return_code": result.returncode,
                    "command": command,
                    "console": str(console),
                },
            )
            raise RuntimeError(
                f"frontend failed: {window['run_slug']} {arm['arm']} rc={result.returncode}"
            )
        bag = bag_audit(feature_bag)
        metric = metric_audit(metrics)
        expected = (int(window["input_frame_count"]) + int(window["every_n"]) - 1) // int(
            window["every_n"]
        )
        frontend_coverage = bag["feature_messages"] / expected if expected else 0.0
        integrity = (
            bag["feature_messages"] > 0
            and frontend_coverage >= 0.70
            and bag["max_features"] <= 350
        )
        payload = {
            "schema_version": "aqua-fe-confirmatory-v3-frontend-cell-v1",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "window_id": window["window_id"],
            "run_slug": window["run_slug"],
            "arm": arm["arm"],
            "method": arm["method"],
            "seedchain_profile": arm["seedchain_profile"],
            "return_code": result.returncode,
            "command": command,
            "run_dir": str(run_dir),
            "feature_bag": str(feature_bag),
            "feature_bag_size_bytes": feature_bag.stat().st_size,
            "feature_bag_sha256": sha256(feature_bag),
            "frontend_metrics": str(metrics),
            "frontend_metrics_sha256": sha256(metrics),
            "prepared_input": str(prepared),
            "prepared_input_sha256": sha256(prepared),
            "expected_feature_messages": expected,
            "frontend_coverage": frontend_coverage,
            "frontend_integrity_pass": integrity,
            "bag_audit": bag,
            "metric_audit": metric,
            "frozen_exporter_sha256": LOCKED[ROOT / "uw_frontend/ros/export_vins_features.py"],
        }
        atomic_json(receipt, payload)
        atomic_json(
            prepared.parent / "materialization_receipt.json",
            {
                "window_id": window["window_id"],
                "prepared_input": str(prepared),
                "size_bytes": prepared.stat().st_size,
                "sha256": payload["prepared_input_sha256"],
            },
        )
        print(
            f"done {window['run_slug']} {arm['arm']} "
            f"messages={bag['feature_messages']}/{expected} "
            f"max={bag['max_features']} integrity={integrity}",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", action="append", help="run_slug; repeatable")
    parser.add_argument("--arm", action="append", help="arm id; repeatable")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    verify_lock()
    prepare_shadow()
    if args.verify_only:
        print("confirmatory v3 lock PASS")
        return 0

    windows = load_windows()
    arms = load_arms()
    if args.window:
        selected = set(args.window)
        windows = [row for row in windows if row["run_slug"] in selected]
        missing = selected - {row["run_slug"] for row in windows}
        if missing:
            raise SystemExit(f"unknown windows: {sorted(missing)}")
    arm_ids = args.arm or list(arms)
    missing_arms = set(arm_ids) - set(arms)
    if missing_arms:
        raise SystemExit(f"unknown arms: {sorted(missing_arms)}")

    for window in windows:
        for arm_id in arm_ids:
            run_cell(window, arms[arm_id])
    return 0


if __name__ == "__main__":
    sys.exit(main())
