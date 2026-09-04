#!/usr/bin/env python3
"""Run the preregistered long-window same-backend frontend supplement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path("/home/ma/AQUA-FE_WS")
RESULT_ROOT = ROOT / "papers/frontend_same_backend_comparison_supplemental_v1"
STORAGE_ROOT = Path(os.environ.get(
    "FSBC_SUPPLEMENT_STORAGE_ROOT",
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_supplemental_v1",
))
TASK_TMP = STORAGE_ROOT / "tmp"
CUDA_ENV_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")
PORT_BASE = int(os.environ.get("PORT_BASE", "27700"))
RUN_ONLY_WINDOW = os.environ.get("RUN_ONLY_WINDOW", "")
RUN_ONLY_ARM = os.environ.get("RUN_ONLY_ARM", "")

WINDOWS = {
    "a03_5000_5900": ("aqualoc_archaeo", "3", "5000", "5900", 1),
    "a01_16200_17100": ("aqualoc_archaeo", "1", "16200", "17100", 2),
    "a07_900_1800": ("aqualoc_archaeo", "7", "900", "1800", 3),
    "a07_1800_2700": ("aqualoc_archaeo", "7", "1800", "2700", 4),
    "h07_0_1000": ("aqualoc_real", "h07", "0", "1000", 5),
    "h01_0_900": ("aqualoc_real", "h01", "0", "900", 6),
    "fjord5_s60_d30": ("ntnu", "fjord_5", "60", "30", 7),
    "fjord6_s45_d45": ("ntnu", "fjord_6", "45", "45", 8),
}

ARMS = {
    "klt": ("klt", "xfeat", 1),
    "splg": ("hybrid_superpoint_lightglue", "all_learned", 2),
    "xfeat_seed": ("hybrid_xfeat", "xfeat", 3),
}

FROZEN_HASHES = {
    ROOT / "uw_frontend/ros/export_vins_features.py": "68453b035037d04087dbad3e512c602b4ef6967b2a8cf6d14e34a14750f2312d",
    ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml": "6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3",
    ROOT / "scripts/run_learned_seedchain_eval.sh": "8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106",
    ROOT / "scripts/learned_seedchain_env.sh": "f4407a4dfe808f6d9f5c7b23ad1ad66cd06d58e87257fb9d6b355153c71a2df3",
    ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh": "9da109074d559875434bc82e43febd7acf1e60c027f11bae31023e6d08198a9b",
    ROOT / "scripts/run_aqualoc_real_vins_eval.sh": "a8cf19217dcdd358e73a6ec1293319868142d301a63db9f2a67208f01d7a6e48",
    ROOT / "scripts/run_ntnu_vins_eval.sh": "d393cd133adaf43c9633a984ba073bcab3bb0494fe2473746abcb5f73327297a",
    Path("/home/ma/.cache/torch/hub/checkpoints/superpoint_v1.pth"): "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e",
    Path("/home/ma/.cache/torch/hub/checkpoints/superpoint_lightglue_v0-1_arxiv.pth"): "6ff7040d0a497fc6639337946d7538dae07428c18f77a067a0b5a960e7cc551a",
    ROOT / "external_tools/accelerated_features/weights/xfeat.pt": "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b",
    ROOT / "uw_frontend/matchers/lightglue_adapter.py": "9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a",
    ROOT / "external_tools/LightGlue/lightglue/lightglue.py": "dcb75b9cad1985c5e7a537c512d4318d47fbcc99df75b39a513de60e027c039f",
    ROOT / "external_tools/LightGlue/lightglue/superpoint.py": "23e8a26137b44f37e9a319313822c5b38d9c55796e756202eb46d64f1979d2b0",
    ROOT / "uw_frontend/matchers/xfeat_adapter.py": "8090ad7246b7acba62183577d108f62b41c87fe04f52c66f5d897315481e91ee",
    ROOT / "external_tools/accelerated_features/modules/xfeat.py": "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7",
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"): "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"): "82ec1fcdc6728b827dee39d74a267db4709e62ed69cddca3b8c43190b049045e",
}

PREREGISTERED_HASHES = {
    RESULT_ROOT / "windows.csv": "305f681766bde3de97fb2ed6a3092a791c50864314067863c18f2679edf7840f",
    RESULT_ROOT / "arms.csv": "cd25847aecf86e1c86121aadb7dc8c3bc1d068b34fe0c34561e295a67f1c3633",
    RESULT_ROOT / "contract.json": "9999af832eeabd262dc32859c3218a04b2f8596c04184cda2e3c0cb80b9845df",
    RESULT_ROOT / "preregistration.md": "4a2e5633b7977900e63de7ee45ac736f938e2bdf592f6fccf2fe4e3710c5b9e1",
    RESULT_ROOT / "runtime_weight_lock.json": "0906ea554ed331977c627ca6975a890d63e38141c57ea3620246e02a2488204e",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_frozen_inputs() -> None:
    for path, expected in {**FROZEN_HASHES, **PREREGISTERED_HASHES}.items():
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            raise RuntimeError(
                f"frozen input hash mismatch: {path} expected={expected} actual={actual}"
            )


def run_root(family: str) -> Path:
    return {
        "aqualoc_archaeo": ROOT / "logs/aqualoc_archaeo_vins",
        "aqualoc_real": ROOT / "logs/aqualoc_real_vins",
        "ntnu": ROOT / "logs/ntnu_vins",
    }[family]


def run_dir(window_id: str, arm_id: str, repeat: int) -> Path:
    family, _, _, _, _ = WINDOWS[window_id]
    method, _, _ = ARMS[arm_id]
    tag = f"fsbcs1_{window_id}_{arm_id}_r{repeat}"
    return run_root(family) / f"external_{method}_every2_{tag}"


def prepare_offloaded_run_dir(expected: Path, family: str) -> Path:
    actual = STORAGE_ROOT / "runs" / family / expected.name
    actual.mkdir(parents=True, exist_ok=True)
    expected.parent.mkdir(parents=True, exist_ok=True)
    if expected.is_symlink():
        if expected.resolve() != actual.resolve():
            raise RuntimeError(f"unexpected run-dir symlink target: {expected}")
    elif expected.exists():
        raise RuntimeError(f"refusing existing non-symlink run directory: {expected}")
    else:
        expected.symlink_to(actual, target_is_directory=True)
    return actual


def other_exporters() -> str:
    result = subprocess.run(
        ["ps", "-eo", "pid=,comm=,args="], text=True, stdout=subprocess.PIPE, check=True
    ).stdout
    return "\n".join(
        line for line in result.splitlines()
        if "uw_frontend.ros.export_vins_features" in line and "fsbcs1_" not in line
    )


def file_identity(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def write_receipt(
    expected: Path,
    window_id: str,
    arm_id: str,
    repeat: int,
    method: str,
    seed_target: str,
    feature_bag: Path,
    return_code: int,
) -> None:
    payload = {
        "schema_version": "aqua-fe-fsbcs-cell-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "backend_epoch": "supplement_v1_libvins_82ec1fcd",
        "window_id": window_id,
        "arm_id": arm_id,
        "repeat": repeat,
        "method": method,
        "seed_target": seed_target,
        "exit_code": return_code,
        "feature_bag": file_identity(feature_bag),
        "vio_csv": file_identity(expected / "vins_output/vio.csv"),
        "vins_log": file_identity(expected / "vins.log"),
        "frontend_metrics": file_identity(expected / "frontend_metrics.csv"),
        "status": "ATTEMPT_COMPLETE",
    }
    (expected / "fsbc_cell_complete.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def clean_environment(tag: str, port: int, seed_target: str) -> dict[str, str]:
    current_path = os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    return {
        "HOME": os.environ.get("HOME", "/home/ma"),
        "USER": os.environ.get("USER", "ma"),
        "LOGNAME": os.environ.get("LOGNAME", "ma"),
        "SHELL": "/bin/bash",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": os.environ.get("TERM", "dumb"),
        "ROOT": str(ROOT),
        "PATH": f"{CUDA_ENV_BIN}:{current_path}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TORCH_HOME": "/home/ma/.cache/torch",
        "TMPDIR": str(TASK_TMP),
        "CUDA_VISIBLE_DEVICES": "0",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "ROS_DISTRO": "noetic",
        "ROS_VERSION": "1",
        "ROS_PYTHON_VERSION": "3",
        "ROS_ROOT": "/opt/ros/noetic/share/ros",
        "ROS_ETC_DIR": "/opt/ros/noetic/etc",
        "ROS_MASTER_URI": f"http://localhost:{port}",
        "ROS_HOSTNAME": "localhost",
        "ROS_PACKAGE_PATH": "/opt/ros/noetic/share",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TAG": tag,
        "PORT": str(port),
        "RUN_VINS": "1",
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
        "PLAY_RATE": "1.0",
        "POST_PLAY_SLEEP": "8",
        "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
        "LEARNED_EXPORT_ONLINE_SEED_SOURCES": seed_target,
    }


def run_cell(window_id: str, arm_id: str, repeat: int) -> None:
    family, p1, p2, p3, window_order = WINDOWS[window_id]
    method, seed_target, arm_order = ARMS[arm_id]
    tag = f"fsbcs1_{window_id}_{arm_id}_r{repeat}"
    port = PORT_BASE + window_order * 20 + arm_order * 4 + repeat
    expected = run_dir(window_id, arm_id, repeat)
    prepare_offloaded_run_dir(expected, family)
    feature_bag = run_dir(window_id, arm_id, 1) / "features.bag"
    receipt = expected / "fsbc_cell_complete.json"
    if receipt.is_file():
        print(f"resume completed cell: {window_id} {arm_id} r{repeat}", flush=True)
        return

    check_frozen_inputs()
    contamination = other_exporters()
    if contamination and os.environ.get("ALLOW_UNRELATED_EXPORTERS") != "1":
        raise RuntimeError(f"unrelated frontend exporters are active:\n{contamination}")

    args = [family, p1, p2, p3, method, "2"]
    env = clean_environment(tag, port, seed_target)
    if repeat == 1:
        env.update({"FORCE_EXPORT": "1", "EXPORT_FEATURES": "1", "FORCE_RAW": "0"})
    else:
        if not feature_bag.is_file() or feature_bag.stat().st_size == 0:
            raise RuntimeError(f"missing immutable r1 feature bag: {feature_bag}")
        env.update({
            "FORCE_EXPORT": "0",
            "EXPORT_FEATURES": "0",
            "FORCE_RAW": "0",
            "FEATURE_BAG_OVERRIDE": str(feature_bag),
        })

    TASK_TMP.mkdir(parents=True, exist_ok=True)
    command = ["/usr/bin/bash", str(ROOT / "scripts/run_learned_seedchain_eval.sh"), *args]
    (expected / "fsbc_command.txt").write_text(
        f"window_id={window_id}\narm_id={arm_id}\nrepeat={repeat}\n"
        f"method={method}\nseed_target={seed_target}\nport={port}\n"
        f"command={shlex.join(command)}\n",
        encoding="utf-8",
    )
    print(f"start cell: {window_id} {arm_id} r{repeat} method={method} port={port}", flush=True)
    with (expected / "fsbc_console.log").open("w", encoding="utf-8") as console:
        process = subprocess.run(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT, check=False)
    (expected / "fsbc_exit_code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    write_receipt(expected, window_id, arm_id, repeat, method, seed_target, feature_bag, process.returncode)
    print(f"finish cell: {window_id} {arm_id} r{repeat} rc={process.returncode}", flush=True)


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    check_frozen_inputs()
    for window_id in WINDOWS:
        if RUN_ONLY_WINDOW and RUN_ONLY_WINDOW != window_id:
            continue
        for arm_id in ARMS:
            if RUN_ONLY_ARM and RUN_ONLY_ARM != arm_id:
                continue
            for repeat in range(1, 4):
                run_cell(window_id, arm_id, repeat)
    print("all selected supplemental cells attempted", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
