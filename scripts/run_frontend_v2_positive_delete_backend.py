#!/usr/bin/env python3
"""Freeze and execute the six positive-window donor-delete replays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_v2_positive_delete_diagnostic"
V2_RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_v2_positive_delete_diagnostic"
)
CONTRACT = PAPER / "contract.json"
BUILD_RECEIPT = PAPER / "build_receipt.json"
PLAN = PAPER / "replay_plan.csv"
LOCK = PAPER / "execution_lock.json"
CELL_RUNNER = ROOT / "scripts/run_frontend_v2_positive_delete_backend_cell.sh"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def no_vins_running() -> bool:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text().strip() == "vins_node":
                return False
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return True


def prepare() -> None:
    if PLAN.exists() or LOCK.exists():
        raise RuntimeError("refusing to overwrite replay plan/lock")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    receipt = json.loads(BUILD_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("contract_sha256") != sha256(CONTRACT):
        raise RuntimeError("derived bag receipt/contract mismatch")
    audits = {item["run_slug"]: item for item in receipt["windows"]}
    rows: list[dict[str, object]] = []
    for window in contract["windows"]:
        slug = window["run_slug"]
        audit = audits[slug]
        bag = Path(audit["output_bag"])
        if audit["status"] != "PASS" or sha256(bag) != audit["output_bag_sha256"]:
            raise RuntimeError(f"derived bag identity failure: {slug}")
        for repeat in (1, 2, 3):
            rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": slug,
                    "repeat": repeat,
                    "feature_bag": str(bag),
                    "feature_bag_sha256": sha256(bag),
                    "canonical_config": window["canonical_config"],
                    "canonical_config_sha256": window["canonical_config_sha256"],
                    "camera_config": window["camera_config"],
                    "camera_config_sha256": window["camera_config_sha256"],
                    "vins_node_sha256": contract["vins_node_sha256"],
                    "vins_lib_sha256": contract["vins_lib_sha256"],
                    "status": "PENDING",
                }
            )
    write_csv(PLAN, rows)
    files = [
        CONTRACT,
        BUILD_RECEIPT,
        PLAN,
        CELL_RUNNER,
        ROOT / "scripts/run_frontend_v2_positive_delete_backend.py",
        ROOT / "scripts/analyze_frontend_v2_positive_delete_backend.py",
        ROOT / "scripts/evaluate_vins_common_support_dual_scale.py",
        ROOT / "papers/frontend_coverage_monotone_router_v2/backend_results_repeats.csv",
        ROOT / "papers/frontend_coverage_monotone_router_v2/accuracy_repeats.csv",
    ]
    files.extend(Path(row["feature_bag"]) for row in rows[::3])
    files.extend(Path(row["canonical_config"]) for row in rows[::3])
    files.extend(Path(row["camera_config"]) for row in rows[::3])
    lock = {
        "schema_version": "aqua-fe-v2-positive-delete-execution-lock-v1",
        "files": [{"path": str(path), "sha256": sha256(path)} for path in files],
        "vins_node": contract["vins_node"],
        "vins_node_sha256": contract["vins_node_sha256"],
        "vins_lib": contract["vins_lib"],
        "vins_lib_sha256": contract["vins_lib_sha256"],
        "replay_order": [f"{row['run_slug']}:repeat{row['repeat']}" for row in rows],
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"prepared {len(rows)} positive-window donor-delete replays")


def verify_lock() -> list[dict[str, str]]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for item in lock["files"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
    for role in ("vins_node", "vins_lib"):
        path = Path(lock[role])
        if not path.is_file() or sha256(path) != lock[f"{role}_sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
    with PLAN.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if lock["replay_order"] != [f"{row['run_slug']}:repeat{row['repeat']}" for row in rows]:
        raise RuntimeError("replay order drift")
    return rows


def execute(port: int) -> int:
    rows = verify_lock()
    if not no_vins_running():
        raise RuntimeError("refusing to overlap an existing vins_node")
    failures: list[str] = []
    for row in rows:
        run_dir = (
            RUNTIME / "backend_replays" / row["run_slug"]
            / "donor_delete_only" / f"repeat{row['repeat']}"
        )
        scratch = V2_RUNTIME / "backend_scratch" / row["run_slug"]
        command = [
            "bash", str(CELL_RUNNER), row["window_id"], row["run_slug"], row["repeat"],
            row["feature_bag"], row["canonical_config"], str(scratch), str(run_dir), str(port),
        ]
        print(f"start {row['run_slug']} donor-delete repeat{row['repeat']}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            failures.append(f"{row['run_slug']}:repeat{row['repeat']}:rc{result.returncode}")
            print(f"failure {failures[-1]}", flush=True)
    if failures:
        print(json.dumps({"failures": failures}, sort_keys=True))
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--port", type=int, default=28831)
    args = parser.parse_args()
    if args.prepare_only == args.execute:
        raise SystemExit("choose exactly one of --prepare-only or --execute")
    if args.prepare_only:
        prepare()
        return 0
    return execute(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
