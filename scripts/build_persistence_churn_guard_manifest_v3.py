#!/usr/bin/env python3
"""Hash v3 outputs, code, frozen backend inputs, trajectories and logs."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_churn_guard_v3"
ARTIFACT = ROOT / "artifacts/frontend_persistence_churn_guard_v3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    paths: set[Path] = set()
    for base in (PAPER, ARTIFACT):
        paths.update(path for path in base.rglob("*") if path.is_file())
    paths.discard(PAPER / "artifacts.sha256")
    paths.discard(PAPER / "artifact_index.csv")
    for relative in (
        "uw_frontend/ros/export_vins_features.py",
        "scripts/learned_seedchain_env.sh",
        "scripts/run_aqualoc_archaeo_vins_eval.sh",
        "scripts/run_aqualoc_real_vins_eval.sh",
        "scripts/run_afrl_cave_vins_eval.sh",
        "scripts/run_ntnu_vins_eval.sh",
        "scripts/run_cirs_caves_vins_eval.sh",
        "scripts/run_persistence_singlechain_frontend_v2.py",
        "scripts/analyze_persistence_churn_guard_frontend_v3.py",
        "scripts/analyze_persistence_churn_guard_mechanism_v3.py",
        "scripts/build_persistence_churn_guard_backend_v3.py",
        "scripts/plot_persistence_churn_guard_v3.py",
        "scripts/build_persistence_churn_guard_manifest_v3.py",
        "tests/test_final_mirror_noharm_contract.py",
        "papers/frontend_persistence_conditioned_replacement_v1/accuracy.csv",
        "papers/frontend_persistence_conditioned_replacement_v1/accuracy_repeats.csv",
        "papers/frontend_persistence_conditioned_replacement_v1/backend_config_audit.csv",
        "papers/frontend_persistence_singlechain_v2/accuracy.csv",
        "papers/frontend_persistence_singlechain_v2/accuracy_repeats.csv",
        "papers/frontend_persistence_singlechain_v2/report.md",
    ):
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        paths.add(path)
    for path in (
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
        paths.add(path)

    with (PAPER / "backend_config_audit.csv").open(newline="", encoding="utf-8") as stream:
        audit = list(csv.DictReader(stream))
    for row in audit:
        for key in ("feature_bag", "config", "vio_csv"):
            path = Path(row[key])
            if not path.is_file():
                raise FileNotFoundError(path)
            paths.add(path)
        repeat_dir = Path(row["vio_csv"]).parent.parent
        log = repeat_dir / "vins.log"
        if log.is_file():
            paths.add(log)

    records = [
        {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "path": str(path),
        }
        for path in sorted(paths, key=lambda item: str(item))
    ]
    with (PAPER / "artifact_index.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sha256", "bytes", "path"])
        writer.writeheader()
        writer.writerows(records)
    with (PAPER / "artifacts.sha256").open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(f"{row['sha256']}  {row['path']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
