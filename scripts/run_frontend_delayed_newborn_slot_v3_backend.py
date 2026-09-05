#!/usr/bin/env python3
"""Execute only the new rows in the frozen delayed-newborn-slot v3 plan."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_delayed_newborn_slot_v3"
)
PLAN = PAPER / "backend_replay_plan.csv"
LOCK = PAPER / "backend_execution_lock.json"
LOCK_AMENDMENT = PAPER / "backend_execution_lock_amendment.json"
CELL_RUNNER = ROOT / "scripts/run_frontend_delayed_newborn_slot_v3_backend_cell.sh"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def parse_receipt(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return dict(line.split("=", 1) for line in path.read_text(errors="ignore").splitlines() if "=" in line)


def verify_lock() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    amendment = json.loads(LOCK_AMENDMENT.read_text(encoding="utf-8"))
    if amendment["original_lock_sha256"] != sha256(LOCK):
        raise RuntimeError("backend execution lock amendment targets a different lock")
    replacements = amendment["wrapper_file_replacements"]
    for item in lock["files"]:
        path = Path(item["path"])
        actual = sha256(path) if path.is_file() else ""
        replacement = replacements.get(str(path))
        replacement_ok = bool(
            replacement
            and replacement["old_sha256"] == item["sha256"]
            and replacement["new_sha256"] == actual
        )
        if actual != item["sha256"] and not replacement_ok:
            raise RuntimeError(f"backend execution lock drift: {path}")
    if sha256(VINS_NODE) != lock["vins_node_sha256"] or sha256(VINS_LIB) != lock["vins_lib_sha256"]:
        raise RuntimeError("VINS binary identity drift")


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


def validate_reused(row: dict[str, str]) -> None:
    replay = Path(row["replay_dir"])
    receipt = parse_receipt(replay / "replay_receipt.txt")
    vio = replay / "vins_output/vio.csv"
    expected = {
        "window_id": row["window_id"], "run_slug": row["run_slug"],
        "cell_id": row["cell_id"], "repeat": row["repeat"],
        "feature_bag_sha256": row["feature_bag_sha256"],
        "canonical_config_sha256": row["canonical_config_sha256"],
        "vins_node_sha256": row["vins_node_sha256"],
        "vins_lib_sha256": row["vins_lib_sha256"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise RuntimeError(f"reused receipt drift: {row['run_slug']}/r{row['repeat']}")
    if not vio.is_file() or receipt.get("vio_csv_sha256") != sha256(vio):
        raise RuntimeError(f"reused trajectory drift: {row['run_slug']}/r{row['repeat']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=28731)
    args = parser.parse_args()
    verify_lock()
    rows = read_csv(PLAN)
    if len(rows) != 54:
        raise RuntimeError(f"expected 54 plan rows, got {len(rows)}")
    if not no_vins_running():
        raise RuntimeError("refusing to overlap an existing vins_node")
    failures: list[str] = []
    reused = 0
    for row in rows:
        for key in ("feature_bag", "canonical_config", "camera_config"):
            if sha256(Path(row[key])) != row[f"{key}_sha256"]:
                raise RuntimeError(f"input identity drift: {row['run_slug']}:{row['cell_id']}:{key}")
        if row["execution"] == "REUSED_FROZEN_V2_REPLAY":
            validate_reused(row)
            reused += 1
            continue
        replay = Path(row["replay_dir"])
        command = [
            "bash", str(CELL_RUNNER), row["window_id"], row["run_slug"],
            row["cell_id"], row["repeat"], row["feature_bag"],
            row["canonical_config"], str(RUNTIME / "backend_scratch" / row["run_slug"]),
            str(replay), str(args.port),
        ]
        print(f"start backend {row['run_slug']} {row['cell_id']} repeat{row['repeat']}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            failure = f"{row['run_slug']}:{row['cell_id']}:repeat{row['repeat']}:rc{result.returncode}"
            failures.append(failure)
            print(f"backend failure {failure}", flush=True)
            if result.returncode == 73:
                break
    print(json.dumps({"reused_validated": reused, "failures": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
