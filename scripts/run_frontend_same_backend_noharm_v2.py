#!/usr/bin/env python3
"""Run the preregistered repaired no-harm same-backend comparison epoch."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess

import run_frontend_same_backend_supplement_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
RESULT_ROOT = ROOT / "papers/frontend_same_backend_comparison_noharm_v2"
STORAGE_ROOT = Path(os.environ.get(
    "FSBC_NOHARM_V2_STORAGE_ROOT",
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_noharm_v2",
))
TASK_TMP = STORAGE_ROOT / "tmp"
PORT_BASE = int(os.environ.get("PORT_BASE", "28100"))
RUN_ONLY_WINDOW = os.environ.get("RUN_ONLY_WINDOW", "")
RUN_ONLY_ARM = os.environ.get("RUN_ONLY_ARM", "")

WINDOWS = base.WINDOWS
ARMS = {
    # The shared exporter CLI requires one valid seed-source enum even when
    # method=klt; this placeholder is unreachable for the classical arm.
    "klt": ("klt", "xfeat", 1),
    "splg": ("hybrid_superpoint_lightglue", "all_learned", 2),
    "xfeat_seed": ("hybrid_xfeat", "xfeat", 3),
}

FROZEN_HASHES = {
    ROOT / "uw_frontend/ros/export_vins_features.py": "fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04",
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
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"): "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8",
}

PREREGISTERED_HASHES = {
    RESULT_ROOT / "windows.csv": "305f681766bde3de97fb2ed6a3092a791c50864314067863c18f2679edf7840f",
    RESULT_ROOT / "arms.csv": "8bf895a3c8a3b8e0cbc96f257fcbbe339ee818c84b58e6314ef82b4c1ee242c0",
    RESULT_ROOT / "contract.json": "b304e6e76be66dbe0fdbd3f3bedd7f03f96974706a06af41579c17784de2495e",
    RESULT_ROOT / "preregistration.md": "262ea36acd9aefde39ed7576ab637ff1d5caf040bf8fec10c3dabfb4dd7bfcf6",
    RESULT_ROOT / "runtime_weight_lock.json": "02ff3e0c07bc82f2c62c1c47074cd2cfb62ec809efd6f72b3789f344c0fa7afa",
}


def run_dir(window_id: str, arm_id: str, repeat: int) -> Path:
    family, _, _, _, _ = WINDOWS[window_id]
    method, _, _ = ARMS[arm_id]
    tag = f"fsbcnh2_{window_id}_{arm_id}_r{repeat}"
    return base.run_root(family) / f"external_{method}_every2_{tag}"


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
        "schema_version": "aqua-fe-fsbc-noharm-v2-cell-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "backend_epoch": "noharm_v2_libvins_373a598c_exporter_fdb624f2",
        "window_id": window_id,
        "arm_id": arm_id,
        "repeat": repeat,
        "method": method,
        "seed_target": seed_target,
        "exit_code": return_code,
        "feature_bag": base.file_identity(feature_bag),
        "vio_csv": base.file_identity(expected / "vins_output/vio.csv"),
        "vins_log": base.file_identity(expected / "vins.log"),
        "frontend_metrics": base.file_identity(expected / "frontend_metrics.csv"),
        "status": "ATTEMPT_COMPLETE",
    }
    (expected / "fsbc_cell_complete.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_cell(window_id: str, arm_id: str, repeat: int) -> None:
    family, p1, p2, p3, window_order = WINDOWS[window_id]
    method, seed_target, arm_order = ARMS[arm_id]
    tag = f"fsbcnh2_{window_id}_{arm_id}_r{repeat}"
    port = PORT_BASE + window_order * 20 + arm_order * 4 + repeat
    expected = run_dir(window_id, arm_id, repeat)
    base.prepare_offloaded_run_dir(expected, family)
    feature_bag = run_dir(window_id, arm_id, 1) / "features.bag"
    receipt = expected / "fsbc_cell_complete.json"
    if receipt.is_file():
        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
        if int(receipt_data.get("exit_code", -999)) == 0:
            print(f"resume completed cell: {window_id} {arm_id} r{repeat}", flush=True)
            return
        print(f"retry incomplete cell: {window_id} {arm_id} r{repeat}", flush=True)

    base.check_frozen_inputs()
    contamination = base.other_exporters()
    if contamination and os.environ.get("ALLOW_UNRELATED_EXPORTERS") != "1":
        raise RuntimeError(f"unrelated frontend exporters are active:\n{contamination}")

    args = [family, p1, p2, p3, method, "2"]
    env = base.clean_environment(tag, port, seed_target)
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
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=console,
            stderr=subprocess.STDOUT,
            check=False,
        )
    (expected / "fsbc_exit_code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    write_receipt(expected, window_id, arm_id, repeat, method, seed_target, feature_bag, process.returncode)
    print(f"finish cell: {window_id} {arm_id} r{repeat} rc={process.returncode}", flush=True)
    if process.returncode != 0:
        raise RuntimeError(
            f"cell failed before completion: {window_id} {arm_id} r{repeat} rc={process.returncode}"
        )


def configure_base() -> None:
    base.RESULT_ROOT = RESULT_ROOT
    base.STORAGE_ROOT = STORAGE_ROOT
    base.TASK_TMP = TASK_TMP
    base.PORT_BASE = PORT_BASE
    base.RUN_ONLY_WINDOW = RUN_ONLY_WINDOW
    base.RUN_ONLY_ARM = RUN_ONLY_ARM
    base.WINDOWS = WINDOWS
    base.ARMS = ARMS
    base.FROZEN_HASHES = FROZEN_HASHES
    base.PREREGISTERED_HASHES = PREREGISTERED_HASHES
    base.run_dir = run_dir
    base.write_receipt = write_receipt
    base.run_cell = run_cell


def main() -> int:
    configure_base()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
