#!/usr/bin/env python3
"""Stage-2 preparation and frontend export for the long-window supplement."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER_ROOT = ROOT / "papers/frontend_same_backend_comparison_supplement"
RUNTIME_ROOT = ROOT / "artifacts/frontend_same_backend_comparison_supplement"
SHADOW_ROOT = RUNTIME_ROOT / "shadow_root"
PREPARED_ROOT = RUNTIME_ROOT / "prepared"
CUDA_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")

PREREG_HASHES = {
    PAPER_ROOT / "preregistration.md": "3537a88663dffe316e2c518d9151b581b5351f46abd7d1ac1b62f785ec37bf0e",
    PAPER_ROOT / "candidate_windows.csv": "a5386d54923becf643dd88151cad615d65551fa87a5356b023c457cc4a627066",
}
FROZEN_HASHES = {
    ROOT / "uw_frontend/ros/export_vins_features.py": "fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04",
    ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml": "6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3",
    ROOT / "scripts/run_learned_seedchain_eval.sh": "8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106",
    ROOT / "scripts/learned_seedchain_env.sh": "f4407a4dfe808f6d9f5c7b23ad1ad66cd06d58e87257fb9d6b355153c71a2df3",
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"): "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"): "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8",
}
ARMS = {
    "klt": ("klt", "xfeat"),
    "splg": ("hybrid_superpoint_lightglue", "all_learned"),
    "xfeat_seed": ("hybrid_xfeat", "xfeat"),
}
A06_INPUTS = [
    ROOT / f"datasets/aqualoc/rosbags/archaeo06_{lo}_{hi}.bag"
    for lo, hi in ((0, 400), (400, 800), (800, 1200), (1200, 1600), (1600, 2000))
]
A06_ORIGIN_NS = 1_542_883_311_780_022_336
AFRL_BAG = Path("/media/ma/Data/AQUA-FE_WS/datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag")
AFRL_GT = Path("/media/ma/Data/AQUA-FE_WS/datasets/full_downloads/afrl_hf/colmap_groundtruth/cemetery.txt")
AFRL_CAMCHAIN = Path("/media/ma/Data/AQUA-FE_WS/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_cemetery.yaml")
AFRL_IMU = Path("/media/ma/Data/AQUA-FE_WS/datasets/full_downloads/afrl_hf/camera_imu_parameters/imu.yaml")
AFRL_FIRST_FL_STAMP_S = 1_535_224_862.0919013
AFRL_BAG_START_S = 1_535_224_862.0381794
AFRL_RUNNER_PHASE_S = AFRL_FIRST_FL_STAMP_S - AFRL_BAG_START_S


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen() -> None:
    usage = shutil.disk_usage(ROOT)
    if usage.free < 8 * 1024**3:
        raise RuntimeError(f"workspace free space below 8 GiB: {usage.free}")
    for path, expected in {**PREREG_HASHES, **FROZEN_HASHES}.items():
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            raise RuntimeError(f"frozen hash mismatch: {path}: {actual} != {expected}")


def load_windows() -> list[dict[str, str]]:
    with (PAPER_ROOT / "candidate_windows.csv").open(newline="", encoding="utf-8") as stream:
        return [row for row in csv.DictReader(stream) if row["eligibility"] == "ELIGIBLE"]


def symlink(path: Path, target: Path) -> None:
    if path.is_symlink():
        if path.resolve() != target.resolve():
            raise RuntimeError(f"wrong symlink target: {path}")
        return
    if path.exists():
        raise RuntimeError(f"refusing existing shadow path: {path}")
    path.symlink_to(target, target_is_directory=target.is_dir())


def prepare_shadow_root() -> None:
    SHADOW_ROOT.mkdir(parents=True, exist_ok=True)
    (SHADOW_ROOT / "logs").mkdir(exist_ok=True)
    for name in ("uw_frontend", "external_tools", "datasets"):
        symlink(SHADOW_ROOT / name, ROOT / name)
    scripts = SHADOW_ROOT / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in (
        "run_learned_seedchain_eval.sh",
        "learned_seedchain_env.sh",
        "run_aqualoc_archaeo_vins_eval.sh",
        "run_afrl_cave_vins_eval.sh",
        "record_vins_env.sh",
        "wait_for_ros_subscribers.py",
    ):
        symlink(scripts / name, ROOT / "scripts" / name)

    source = ROOT / "scripts/run_aqualoc_real_vins_eval.sh"
    target = scripts / "run_aqualoc_real_vins_eval.sh"
    adapted = source.read_text(encoding="utf-8").replace(
        'ROOT="/home/ma/AQUA-FE_WS"', 'ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"', 1
    )
    if adapted == source.read_text(encoding="utf-8"):
        raise RuntimeError("Harbor output-root adaptation did not apply")
    if target.exists() and target.read_text(encoding="utf-8") != adapted:
        raise RuntimeError(f"refusing changed generated runner: {target}")
    if not target.exists():
        target.write_text(adapted, encoding="utf-8")
        target.chmod(0o755)


def prepared_bag(row: dict[str, str]) -> Path:
    if row["window_id"] == "h07_s000_d050":
        return ROOT / "datasets/aqualoc/rosbags/harbor07_0_1000.bag"
    return PREPARED_ROOT / row["window_id"] / "input.bag"


def prepare_a06(row: dict[str, str]) -> None:
    output = prepared_bag(row)
    if output.is_file():
        return
    audit = output.parent / "materialization_audit.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/materialize_aqualoc_long_window_supplement.py"),
    ]
    for source in A06_INPUTS:
        command += ["--input-bag", str(source)]
    command += [
        "--output-bag", str(output),
        "--origin-ns", str(A06_ORIGIN_NS),
        "--start-s", row["start_s"],
        "--duration-s", row["duration_s"],
        "--audit-json", str(audit),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def prepare_afrl(row: dict[str, str]) -> None:
    output = prepared_bag(row)
    receipt = output.parent / "materialization_audit.json"
    if output.is_file() and receipt.is_file():
        return
    if output.exists():
        raise RuntimeError(f"unreceipted AFRL prepared bag requires quarantine: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cam0 = row["camera"] == "FL_cam0"
    absolute_start = AFRL_FIRST_FL_STAMP_S + float(row["start_s"])
    command = [
        sys.executable,
        "-m",
        "uw_frontend.datasets.afrl_cave_to_rosbag",
        "--input-bag", str(AFRL_BAG),
        "--gt-txt", str(AFRL_GT),
        "--output-bag", str(output),
        "--start", f"{absolute_start:.9f}",
        "--duration", row["duration_s"],
        "--image-topic-in", "/cam_fl/image_raw/compressed" if cam0 else "/cam_fr/image_raw/compressed",
        "--imu-topic-in", "/imu/imu",
        "--image-topic", "/camera/image_raw",
        "--imu-topic", "/imu/imu",
        "--gt-topic", "/afrl/colmap_gt",
        "--gt-timestamp-mode", "auto",
        "--grayscale",
        "--image-scale", "1.0",
    ]
    console = output.parent / "materialization_console.log"
    with console.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f"AFRL materialization failed: {row['window_id']}")
    payload = {
        "schema_version": "aqua-fe-afrl-long-window-materialization-v1",
        "window_id": row["window_id"],
        "camera": row["camera"],
        "absolute_start_s": absolute_start,
        "duration_s": float(row["duration_s"]),
        "runner_phase_from_bag_start_s": AFRL_RUNNER_PHASE_S,
        "output": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": sha256(output),
        "command": command,
    }
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"prepared AFRL {row['window_id']} size={output.stat().st_size}", flush=True)


def common_env(row: dict[str, str], arm: str) -> dict[str, str]:
    method, seed_source = ARMS[arm]
    env = os.environ.copy()
    env.update(
        {
            "ROOT": str(SHADOW_ROOT),
            "PATH": f"{CUDA_BIN}:{env.get('PATH', '')}",
            "PYTHONPATH": f"{ROOT}:{env.get('PYTHONPATH', '')}",
            "TMPDIR": str(RUNTIME_ROOT / "tmp"),
            "CUDA_VISIBLE_DEVICES": "0",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "RUN_VINS": "0",
            "FORCE_EXPORT": "1",
            "EXPORT_FEATURES": "1",
            "AQUAFE_SEEDCHAIN_PROFILE": "lineage_early_seed_scan",
            "FRONTEND_CONFIG": str(ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
            "MEASUREMENT_SELECTION": "0",
            "EXPORT_MAX_FEATURES": "350",
            "VINS_SAFE_SOURCE_SELECTION": "0",
            "FRAME_OFFSET": "1",
            "PROCESS_SKIPPED_FRAMES": "1",
            "PREPROCESS": "adaptive_clahe",
            "SEMIDENSE_FALLBACK_METHOD": "none",
            "FORMAL_THREE_LAYER_EXPORT": "0",
            "BACKEND_QUALITY_MODE": "vins_safe",
            "BACKEND_QUALITY_ALPHA": "0.65",
            "BACKEND_QUALITY_FLOOR": "0.80",
            "VINS_MULTIPLE_THREAD": "0",
            "VINS_ESTIMATE_TD": "0",
            "LEARNED_EXPORT_ONLINE_SEED_SOURCES": seed_source,
            "TAG": f"fsbcsupp_{row['window_id']}_{arm}_frontend",
        }
    )
    (RUNTIME_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    return env


def command_for(row: dict[str, str], arm: str) -> tuple[list[str], dict[str, str], Path]:
    method, _ = ARMS[arm]
    env = common_env(row, arm)
    script = SHADOW_ROOT / "scripts/run_learned_seedchain_eval.sh"
    tag = env["TAG"]
    if row["family"] == "aqualoc_archaeo":
        env.update(
            {
                "RAW_BAG": str(prepared_bag(row)),
                "RAW_TAR": str(ROOT / "datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz"),
                "GT_TXT": str(ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_06.txt"),
                "FORCE_RAW": "0",
            }
        )
        command = ["bash", str(script), "aqualoc_archaeo", "6", "0", "900", method, "2"]
        run_dir = SHADOW_ROOT / "logs/aqualoc_archaeo_vins" / f"external_{method}_every2_{tag}"
    elif row["family"] == "aqualoc_harbor":
        env.update(
            {
                "RAW_BAG": str(prepared_bag(row)),
                "RAW_TAR": str(ROOT / "datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz"),
                "GT_TXT": str(ROOT / "datasets/aqualoc/metadata/Harbor_sites_sequences/harbor_groundtruth_files/new_harbor_colmap_traj_sequence_07.txt"),
            }
        )
        command = ["bash", str(script), "aqualoc_real", "h07", "0", "1000", method, "2"]
        run_dir = SHADOW_ROOT / "logs/aqualoc_real_vins" / f"external_{method}_every2_{tag}"
    elif row["family"] == "afrl":
        cam0 = row["camera"] == "FL_cam0"
        env.update(
            {
                "RAW_BAG": str(AFRL_BAG),
                "GT_TXT": str(AFRL_GT),
                "CAMCHAIN": str(AFRL_CAMCHAIN),
                "IMU_YAML": str(AFRL_IMU),
                "CAMERA_KEY": "cam0" if cam0 else "cam1",
                "SRC_IMAGE_TOPIC": "/cam_fl/image_raw/compressed" if cam0 else "/cam_fr/image_raw/compressed",
                "SHORT_BAG": str(prepared_bag(row)),
                "PREPARE_BAG": "1",
                "FORCE_RAW": "0",
                "GT_TIMESTAMP_MODE": "auto",
                "GRAYSCALE": "1",
                "IMAGE_SCALE": "1.0",
            }
        )
        runner_start = float(row["start_s"]) + AFRL_RUNNER_PHASE_S
        command = ["bash", str(script), "afrl", f"{runner_start:.9f}", row["duration_s"], method, "2"]
        run_dir = SHADOW_ROOT / "logs/afrl_cave_v31" / f"external_{method}_every2_{tag}"
    else:
        raise RuntimeError(f"unsupported family: {row['family']}")
    return command, env, run_dir


def run_frontend(row: dict[str, str], arm: str) -> None:
    verify_frozen()
    if row["family"] == "aqualoc_archaeo":
        prepare_a06(row)
    command, env, run_dir = command_for(row, arm)
    feature_bag = run_dir / "features.bag"
    receipt = run_dir / "supplement_frontend_receipt.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".frontend.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if receipt.is_file() and feature_bag.is_file():
            print(f"resume frontend {row['window_id']} {arm}", flush=True)
            return
        console = run_dir / "frontend_console.log"
        print(f"start frontend {row['window_id']} {arm}", flush=True)
        with console.open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        payload = {
            "schema_version": "aqua-fe-fsbcsupp-frontend-cell-v1",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "window_id": row["window_id"],
            "arm": arm,
            "method": ARMS[arm][0],
            "return_code": result.returncode,
            "prepared_bag": str(prepared_bag(row).resolve()),
            "feature_bag": str(feature_bag.resolve()) if feature_bag.exists() else None,
            "feature_bag_sha256": sha256(feature_bag) if feature_bag.is_file() else None,
            "command": command,
        }
        receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"finish frontend {row['window_id']} {arm} rc={result.returncode}", flush=True)
        if result.returncode != 0 or not feature_bag.is_file():
            raise RuntimeError(f"frontend failed: {row['window_id']} {arm}")


def reclaim_afrl_prepared_input(row: dict[str, str]) -> None:
    if row["family"] != "afrl":
        return
    complete = True
    for arm in ARMS:
        _, _, run_dir = command_for(row, arm)
        complete = complete and (run_dir / "supplement_frontend_receipt.json").is_file()
        complete = complete and (run_dir / "features.bag").is_file()
    source = prepared_bag(row)
    if not complete or not source.is_file():
        return
    receipt = source.parent / "reclaimed_prepared_input.json"
    payload = {
        "schema_version": "aqua-fe-fsbcsupp-reclaimed-prepared-input-v1",
        "window_id": row["window_id"],
        "reason": "all_three_feature_bags_complete; retain hash receipt and reclaim derived uncompressed image bag",
        "path_before_reclaim": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": sha256(source),
        "reclaimed_at": datetime.now(timezone.utc).isoformat(),
        "recoverability": "deterministically regenerated from frozen raw bag, window, camera topic, and converter",
    }
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source.unlink()
    print(f"reclaimed prepared input {row['window_id']} size={payload['size_bytes']}", flush=True)


def adopt_completed_frontend(row: dict[str, str], arm: str) -> None:
    """Receipt a completed artifact after the supervising terminal disconnected.

    Adoption is intentionally conservative: it is allowed only when the normal
    receipt is absent, the final bag exists, no process still has that exact bag
    path in its command line, and the runner's terminal RUN_VINS=0 marker is in
    the captured console.  Bag contents still undergo the normal Stage-2 audit.
    """

    command, _, run_dir = command_for(row, arm)
    feature_bag = run_dir / "features.bag"
    receipt = run_dir / "supplement_frontend_receipt.json"
    if receipt.is_file():
        print(f"receipt already present {row['window_id']} {arm}", flush=True)
        return
    if not feature_bag.is_file():
        raise RuntimeError(f"cannot adopt missing feature bag: {feature_bag}")
    process_scan = subprocess.run(
        ["pgrep", "-af", str(feature_bag)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    active = [line for line in process_scan.stdout.splitlines() if "pgrep -af" not in line]
    if active:
        raise RuntimeError(f"cannot adopt active feature bag writer: {active}")
    console = run_dir / "frontend_console.log"
    console_text = console.read_text(encoding="utf-8", errors="ignore") if console.is_file() else ""
    scheduled = int(row["image_count_input"]) // 2
    terminal_frontend_manifest = (
        f"wrote {scheduled} feature frames to {feature_bag}" in console_text
        and f"feature_bag={feature_bag}" in console_text
        and "vins_config=" in console_text
    )
    if "RUN_VINS=0, skipping VINS" not in console_text and not terminal_frontend_manifest:
        raise RuntimeError(f"cannot adopt without terminal runner marker: {console}")
    payload = {
        "schema_version": "aqua-fe-fsbcsupp-frontend-cell-v1-recovered-supervisor-disconnect",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "window_id": row["window_id"],
        "arm": arm,
        "method": ARMS[arm][0],
        "return_code": 0,
        "return_code_basis": "terminal_frontend_manifest_and_no_active_writer",
        "recovery_reason": "supervising unified terminal session disconnected while child runner remained active",
        "prepared_bag": str(prepared_bag(row).resolve()),
        "feature_bag": str(feature_bag.resolve()),
        "feature_bag_sha256": sha256(feature_bag),
        "command": command,
    }
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"adopted frontend {row['window_id']} {arm}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="")
    parser.add_argument("--arm", choices=["", *ARMS], default="")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--parallel-arms", action="store_true")
    parser.add_argument("--adopt-completed", action="store_true")
    args = parser.parse_args()
    verify_frozen()
    prepare_shadow_root()
    windows = load_windows()
    for row in windows:
        if args.window and row["window_id"] != args.window:
            continue
        if row["family"] == "aqualoc_archaeo":
            prepare_a06(row)
        elif row["family"] == "afrl":
            prepare_afrl(row)
        if args.prepare_only:
            continue
        selected_arms = [arm for arm in ARMS if not args.arm or arm == args.arm]
        if args.adopt_completed:
            for arm in selected_arms:
                adopt_completed_frontend(row, arm)
            if not args.arm:
                reclaim_afrl_prepared_input(row)
            continue
        if args.parallel_arms and not args.arm and len(selected_arms) > 1:
            with ThreadPoolExecutor(max_workers=len(selected_arms)) as executor:
                futures = [executor.submit(run_frontend, row, arm) for arm in selected_arms]
                for future in futures:
                    future.result()
        else:
            for arm in selected_arms:
                run_frontend(row, arm)
        if not args.arm:
            reclaim_afrl_prepared_input(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
