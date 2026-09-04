#!/usr/bin/env python3
"""Replay valid persistence-conditioned bags through the frozen VINS backend."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_conditioned_replacement_v1"
RUNTIME = ROOT / "artifacts/frontend_persistence_conditioned_replacement_v1"
CELL = ROOT / "scripts/run_persistence_conditioned_backend_v1_cell.sh"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
LIBVINS = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")
EXPECTED_NODE = "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"
EXPECTED_LIB = "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8"


CASES = {
    "a09_6000_6800": {
        "new_bag": RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a09_6000_6800/features.bag",
        "source_config": Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r1/vins_aqualoc_archaeo_external.yaml"),
    },
    "a06_s045_d045": {
        "new_bag": RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s045_d045/features.bag",
        "source_config": ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s045_d045/vins_same_backend.yaml",
    },
    "a06_s000_d045": {
        "new_bag": RUNTIME / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s000_d045/features.bag",
        "source_config": ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s000_d045/vins_same_backend.yaml",
    },
    "h07_s000_d050": {
        "new_bag": RUNTIME / "shadow_root/logs/aqualoc_real_vins/external_hybrid_xfeat_every2_pcrv1_h07_s000_d050/features.bag",
        "source_config": ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/h07_s000_d050/vins_same_backend.yaml",
    },
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


def prepare_config(window: str, source: Path) -> tuple[Path, str]:
    target_dir = RUNTIME / "backend_canonical" / window
    target_dir.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    normalized = re.sub(
        r'^output_path:\s*".*"$', 'output_path: "<NORMALIZED>"', text, flags=re.MULTILINE
    )
    scratch_output = RUNTIME / "scratch" / window / "vins_output"
    text, count = re.subn(
        r'^output_path:\s*".*"$', f'output_path: "{scratch_output}"', text, flags=re.MULTILINE
    )
    if count != 1:
        raise RuntimeError(f"unexpected output_path count for {source}: {count}")
    config = target_dir / "vins_same_backend.yaml"
    if config.exists() and config.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"canonical config changed: {config}")
    if not config.exists():
        config.write_text(text, encoding="utf-8")
    camera_match = re.search(r'^cam0_calib:\s*"([^"]+)"$', text, flags=re.MULTILINE)
    if not camera_match:
        raise RuntimeError(f"missing cam0_calib in {source}")
    source_camera = source.parent / camera_match.group(1)
    target_camera = target_dir / source_camera.name
    if not source_camera.is_file():
        raise FileNotFoundError(source_camera)
    if target_camera.exists() and sha256(target_camera) != sha256(source_camera):
        raise RuntimeError(f"camera config changed: {target_camera}")
    if not target_camera.exists():
        shutil.copyfile(source_camera, target_camera)
    return config, hashlib.sha256(normalized.encode()).hexdigest()


def main() -> int:
    if sha256(VINS_NODE) != EXPECTED_NODE or sha256(LIBVINS) != EXPECTED_LIB:
        raise RuntimeError("frozen VINS-Fusion-origin binary hash mismatch")
    if subprocess.run(["pgrep", "-x", "vins_node"], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("refusing to overlap a pre-existing vins_node")
    validations = {row["window"]: row for row in read_csv(PAPER / "frontend_validation.csv")}
    audit_rows: list[dict[str, object]] = []
    for order, (window, case) in enumerate(CASES.items(), start=1):
        validation = validations.get(window)
        if not validation or validation["status"] != "PASS":
            raise RuntimeError(f"frontend gate did not pass: {window}")
        feature_bag = Path(case["new_bag"])
        config, normalized_hash = prepare_config(window, Path(case["source_config"]))
        identical = validation["whole_bag_byte_identical_to_klt"].lower() == "true"
        for repeat in range(1, 4):
            run_dir = RUNTIME / "replays" / window / "persistence_replace" / f"repeat{repeat}"
            status = "REUSED_EXACT_KLT_INPUT" if identical else "PENDING"
            if not identical:
                command = [
                    "bash", str(CELL), window, str(repeat), str(feature_bag), str(config),
                    str(RUNTIME / "scratch" / window), str(run_dir), str(29100 + order),
                ]
                print(f"start backend {window} persistence_replace repeat{repeat}", flush=True)
                result = subprocess.run(command, cwd=ROOT, check=False)
                if result.returncode != 0:
                    raise RuntimeError(f"backend failed: {window} repeat{repeat} rc={result.returncode}")
                status = "COMPLETE"
            audit_rows.append(
                {
                    "window": window,
                    "arm": "persistence_replace",
                    "repeat": repeat,
                    "status": status,
                    "feature_bag": str(feature_bag),
                    "feature_bag_sha256": sha256(feature_bag),
                    "config": str(config),
                    "config_sha256": sha256(config),
                    "normalized_backend_config_sha256": normalized_hash,
                    "vins_node_sha256": sha256(VINS_NODE),
                    "libvins_sha256": sha256(LIBVINS),
                    "vio_csv": "EXACT_KLT_REUSE" if identical else str(run_dir / "vins_output/vio.csv"),
                }
            )
    PAPER.mkdir(parents=True, exist_ok=True)
    fields = list(audit_rows[0])
    with (PAPER / "backend_config_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audit_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
