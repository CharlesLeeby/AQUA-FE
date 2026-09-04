#!/usr/bin/env python3
"""Replay valid single-chain v2 bags with the frozen VINS backend."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_singlechain_v2"
RUNTIME = ROOT / "artifacts/frontend_persistence_singlechain_v2"
CELL = ROOT / "scripts/run_persistence_singlechain_backend_v2_cell.sh"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
LIBVINS = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")

CASES = {
    "a06_s000_d045": (
        RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pscv2_a06_s000_d045/features.bag",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s000_d045/vins_same_backend.yaml",
    ),
    "a09_6000_6800": (
        RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pscv2_a09_6000_6800/features.bag",
        Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r1/vins_aqualoc_archaeo_external.yaml"),
    ),
    "a06_s045_d045": (
        RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pscv2_a06_s045_d045/features.bag",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s045_d045/vins_same_backend.yaml",
    ),
    "h07_s000_d050": (
        RUNTIME / "shadow_root/logs/aqualoc_real_vins/external_hybrid_xfeat_every2_pscv2_h07_s000_d050/features.bag",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/h07_s000_d050/vins_same_backend.yaml",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_config(window: str, source: Path) -> Path:
    target_dir = RUNTIME / "backend_canonical" / window
    target_dir.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    output = RUNTIME / "scratch" / window / "vins_output"
    text, count = re.subn(r'^output_path:\s*".*"$', f'output_path: "{output}"', text, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"output_path count {count}: {source}")
    config = target_dir / "vins_same_backend.yaml"
    if config.exists() and config.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"changed canonical config: {config}")
    if not config.exists():
        config.write_text(text, encoding="utf-8")
    camera_name = re.search(r'^cam0_calib:\s*"([^"]+)"$', text, flags=re.MULTILINE)
    if not camera_name:
        raise RuntimeError(f"missing camera config: {source}")
    source_camera = source.parent / camera_name.group(1)
    target_camera = target_dir / source_camera.name
    if not target_camera.exists():
        shutil.copyfile(source_camera, target_camera)
    elif sha256(target_camera) != sha256(source_camera):
        raise RuntimeError(f"changed camera config: {target_camera}")
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="")
    args = parser.parse_args()
    if sha256(VINS_NODE) != "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278":
        raise RuntimeError("VINS node hash mismatch")
    if sha256(LIBVINS) != "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8":
        raise RuntimeError("libvins hash mismatch")
    if subprocess.run(["pgrep", "-x", "vins_node"], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("pre-existing vins_node")
    with (PAPER / "frontend_validation.csv").open(newline="", encoding="utf-8") as stream:
        valid = {row["window"]: row for row in csv.DictReader(stream)}
    selected = [window for window in CASES if not args.window or window == args.window]
    if not selected:
        raise SystemExit(f"unknown window: {args.window}")
    for order, window in enumerate(CASES, start=1):
        if window not in selected:
            continue
        if valid.get(window, {}).get("status") != "PASS":
            raise RuntimeError(f"frontend gate not passed: {window}")
        bag, source_config = CASES[window]
        if valid[window]["byte_identical_klt"].lower() == "true":
            print(f"reuse exact KLT input: {window}", flush=True)
            continue
        config = prepare_config(window, source_config)
        for repeat in range(1, 4):
            run = RUNTIME / "replays" / window / "singlechain" / f"repeat{repeat}"
            command = [
                "bash", str(CELL), window, str(repeat), str(bag), str(config),
                str(RUNTIME / "scratch" / window), str(run), str(29400 + order),
            ]
            print(f"start backend {window} singlechain repeat{repeat}", flush=True)
            result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode:
                raise RuntimeError(f"backend failed: {window} repeat{repeat} rc={result.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
