#!/usr/bin/env python3
"""Identity-map unchanged v2 KLT frontend artifacts into the v3 matrix."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
V2 = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
V3 = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_delayed_newborn_slot_v3"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def family_dir(family: str) -> str:
    return {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[family]


def directory(root: Path, row: dict[str, str], label: str) -> Path:
    return root / "shadow_root" / "logs" / family_dir(row["family"]) / (
        f"external_klt_every{row['every_n']}_{label}_{row['run_slug']}_klt"
    )


def main() -> int:
    rows = read_csv(PAPER / "development_windows.csv")
    output: list[dict[str, object]] = []
    for row in rows:
        if row["run_slug"] == "a09_6000_6800":
            continue
        source = directory(V2, row, "gmrv2")
        target = directory(V3, row, "dnr3")
        source_receipt_path = source / "frontend_receipt.json"
        source_receipt = json.loads(source_receipt_path.read_text(encoding="utf-8"))
        source_bag = source / "features.bag"
        source_metrics = source / "frontend_metrics.csv"
        checks = {
            "source_return_code_zero": source_receipt.get("return_code") == 0,
            "source_input_hash_matches_roster": (
                source_receipt.get("input_bag_sha256") == row["input_bag_sha256"]
            ),
            "source_bag_hash_matches_receipt": (
                sha256(source_bag) == source_receipt.get("feature_bag_sha256")
            ),
            "source_metrics_hash_matches_receipt": (
                sha256(source_metrics) == source_receipt.get("frontend_metrics_sha256")
            ),
            "source_method_is_klt": source_receipt.get("method") == "klt",
            "source_integrity_pass": bool(source_receipt.get("integrity_pass")),
        }
        if not all(checks.values()):
            raise RuntimeError(f"invalid v2 KLT reuse source {row['run_slug']}: {checks}")
        if target.exists():
            raise RuntimeError(f"refusing to overwrite existing v3 KLT cell: {target}")
        target.mkdir(parents=True)
        os.link(source_bag, target / "features.bag")
        os.link(source_metrics, target / "frontend_metrics.csv")
        for path in source.glob("*.yaml"):
            shutil.copy2(path, target / path.name)
        receipt = {
            "schema_version": "aqua-fe-delayed-newborn-slot-v3-cell-v1",
            "window_id": row["window_id"],
            "run_slug": row["run_slug"],
            "arm": "klt",
            "method": "klt",
            "profile": "lineage_delayed_newborn_slot_v3",
            "execution": "REUSED_FROZEN_V2_KLT_FRONTEND",
            "independent_execution": False,
            "reuse_reason": (
                "KLT has no learned sidecars; the v3-only warmup/horizon change "
                "cannot alter this arm. Input and source receipt hashes pass."
            ),
            "source_receipt": str(source_receipt_path),
            "source_receipt_sha256": sha256(source_receipt_path),
            "return_code": 0,
            "run_dir": str(target),
            "input_bag": row["input_bag"],
            "input_bag_sha256": row["input_bag_sha256"],
            "input_image_messages": source_receipt["input_image_messages"],
            "expected_feature_messages": source_receipt["expected_feature_messages"],
            "feature_messages": source_receipt["feature_messages"],
            "frontend_coverage": source_receipt["frontend_coverage"],
            "max_features": source_receipt["max_features"],
            "integrity_pass": True,
            "feature_bag": str(target / "features.bag"),
            "feature_bag_sha256": sha256(target / "features.bag"),
            "frontend_metrics": str(target / "frontend_metrics.csv"),
            "frontend_metrics_sha256": sha256(target / "frontend_metrics.csv"),
            "method_lock_sha256": sha256(PAPER / "method_lock.json"),
            "exporter_sha256": source_receipt["exporter_sha256"],
            "identity_checks": checks,
        }
        receipt_path = target / "frontend_receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        output.append(
            {
                "run_slug": row["run_slug"],
                "status": "PASS",
                "execution": receipt["execution"],
                "input_bag_sha256": row["input_bag_sha256"],
                "feature_bag_sha256": receipt["feature_bag_sha256"],
                "source_receipt_sha256": receipt["source_receipt_sha256"],
                "hardlink_same_inode": (
                    source_bag.stat().st_ino == (target / "features.bag").stat().st_ino
                ),
            }
        )
        print(f"REUSE {row['run_slug']} klt", flush=True)
    audit = PAPER / "klt_reuse_audit.csv"
    with audit.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
