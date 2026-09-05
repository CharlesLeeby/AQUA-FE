#!/usr/bin/env python3
"""Prepare or execute the preregistered donor-delete-only backend replays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
)
FEATURE_BAG = RUNTIME / "a02_0_900/features_donor_delete_only.bag"
CONFIG = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2/backend_canonical/"
    "a02_0_900/vins_same_backend.yaml"
)
CAMERA = CONFIG.parent / "aqualoc_archaeo02_pinhole.yaml"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")
CELL_RUNNER = ROOT / "scripts/run_frontend_coverage_monotone_router_v2_donor_delete_backend_cell.sh"
THIS_RUNNER = ROOT / "scripts/run_frontend_coverage_monotone_router_v2_donor_delete_backend.py"
BUILDER = ROOT / "scripts/build_frontend_coverage_monotone_router_v2_donor_delete_control.py"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
CONTRACT = PAPER / "contract.json"
BAG_AUDIT = PAPER / "bag_structural_audit.json"
PLAN = PAPER / "replay_plan.csv"
ORIGINAL_LOCK = PAPER / "execution_lock.json"
LOCK = PAPER / "execution_lock_recovery1.json"
CONFIG_SCRATCH = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2/backend_scratch/a02_0_900"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def verify_preregistered_inputs() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for item in contract["inputs"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"preregistered input identity failure: {path}")
    audit = json.loads(BAG_AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("deleted_observations") != 8:
        raise RuntimeError("derived bag structural audit is not PASS/8")
    if sha256(FEATURE_BAG) != audit.get("output_bag_sha256"):
        raise RuntimeError("derived feature bag drift")


def prepare() -> None:
    verify_preregistered_inputs()
    rows = []
    for repeat in (1, 2, 3):
        rows.append(
            {
                "window_id": "aqualoc_archaeology:A02:0000",
                "run_slug": "a02_0_900",
                "cell_id": "donor_delete_only",
                "repeat": repeat,
                "feature_bag": str(FEATURE_BAG),
                "feature_bag_sha256": sha256(FEATURE_BAG),
                "canonical_config": str(CONFIG),
                "canonical_config_sha256": sha256(CONFIG),
                "camera_config": str(CAMERA),
                "camera_config_sha256": sha256(CAMERA),
                "vins_node_sha256": sha256(VINS_NODE),
                "vins_lib_sha256": sha256(VINS_LIB),
                "status": "PENDING",
            }
        )
    write_csv(PLAN, rows)
    files = [
        CONTRACT,
        BAG_AUDIT,
        PLAN,
        CELL_RUNNER,
        THIS_RUNNER,
        BUILDER,
        EVALUATOR,
        V2_PAPER / "backend_results_repeats.csv",
        V2_PAPER / "accuracy_repeats.csv",
        ORIGINAL_LOCK,
        FEATURE_BAG,
        CONFIG,
        CAMERA,
    ]
    lock = {
        "schema_version": "aqua-fe-v2-donor-delete-execution-lock-v1",
        "files": [
            {"path": str(path), "sha256": sha256(path)} for path in files
        ],
        "vins_node": str(VINS_NODE),
        "vins_node_sha256": sha256(VINS_NODE),
        "vins_lib": str(VINS_LIB),
        "vins_lib_sha256": sha256(VINS_LIB),
        "replay_order": [1, 2, 3],
        "recovery_note": (
            "The original runner looked for vio.csv under the diagnostic "
            "runtime although the frozen canonical YAML writes to the v2 "
            "canonical scratch. Recovery1 uses that exact configured path, "
            "preserves repeat1, and continues after a failed repeat."
        ),
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"prepared {len(rows)} donor-delete-only replays")


def verify_lock() -> list[dict[str, str]]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for item in lock["files"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
    if sha256(VINS_NODE) != lock["vins_node_sha256"]:
        raise RuntimeError("VINS node drift")
    if sha256(VINS_LIB) != lock["vins_lib_sha256"]:
        raise RuntimeError("VINS library drift")
    with PLAN.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


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


def make_receipt(run_dir: Path, repeat: str, vio: Path, recovery: bool) -> None:
    values = {
        "schema_version": "aqua-fe-v2-donor-delete-backend-cell-v1",
        "window_id": "aqualoc_archaeology:A02:0000",
        "run_slug": "a02_0_900",
        "cell_id": "donor_delete_only",
        "repeat": repeat,
        "feature_bag": str(FEATURE_BAG),
        "feature_bag_sha256": sha256(FEATURE_BAG),
        "canonical_config": str(CONFIG),
        "canonical_config_sha256": sha256(CONFIG),
        "vins_node": str(VINS_NODE),
        "vins_node_sha256": sha256(VINS_NODE),
        "vins_lib": str(VINS_LIB),
        "vins_lib_sha256": sha256(VINS_LIB),
        "vio_csv": str(vio),
        "vio_csv_sha256": sha256(vio),
    }
    if recovery:
        values["recovered_from"] = str(CONFIG_SCRATCH / "vins_output/vio.csv")
        values["recovery_reason"] = "runner_checked_wrong_scratch_path_after_successful_replay"
    text = "".join(f"{key}={value}\n" for key, value in values.items())
    (run_dir / "replay_receipt.txt").write_text(text, encoding="utf-8")


def recover_repeat1_if_complete() -> None:
    run_dir = RUNTIME / "backend_replays/a02_0_900/donor_delete_only/repeat1"
    receipt = run_dir / "replay_receipt.txt"
    if receipt.is_file():
        return
    if not run_dir.is_dir():
        return
    source_vio = CONFIG_SCRATCH / "vins_output/vio.csv"
    log = run_dir / "vins.log"
    play_log = run_dir / "rosbag_play.log"
    env = run_dir / "vins_env_manifest.txt"
    required = [source_vio, log, play_log, env]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        raise RuntimeError("repeat1 recovery inputs incomplete")
    log_text = log.read_text(encoding="utf-8", errors="ignore")
    play_text = play_log.read_text(encoding="utf-8", errors="ignore")
    env_text = env.read_text(encoding="utf-8", errors="ignore")
    if "Initialization finish!" not in log_text:
        raise RuntimeError("repeat1 recovery lacks initialization marker")
    if f"config_file: {CONFIG}" not in log_text:
        raise RuntimeError("repeat1 recovery config identity absent from VINS log")
    if f"result path {source_vio}" not in log_text:
        raise RuntimeError("repeat1 recovery result path absent from VINS log")
    if str(FEATURE_BAG) not in play_text or "Done." not in play_text:
        raise RuntimeError("repeat1 recovery bag identity/completion absent")
    if "VINS_WS=/home/ma/SLAM/VINS-Fusion-origin" not in env_text:
        raise RuntimeError("repeat1 recovery VINS workspace identity absent")
    if abs(source_vio.stat().st_mtime - play_log.stat().st_mtime) > 5.0:
        raise RuntimeError("repeat1 recovery output/play completion time mismatch")
    target = run_dir / "vins_output/vio.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_vio, target)
    make_receipt(run_dir, "1", target, recovery=True)
    (run_dir / "orchestration_recovery.txt").write_text(
        "The replay itself initialized and produced the configured vio.csv. "
        "The original wrapper returned rc=3 only because it checked a "
        "different scratch directory. The configured output was recovered "
        "without rerunning repeat1.\n",
        encoding="utf-8",
    )
    print("recovered successful donor-delete-only repeat1 without replay", flush=True)


def execute(port: int) -> int:
    rows = verify_lock()
    recover_repeat1_if_complete()
    if not no_vins_running():
        raise RuntimeError("refusing to overlap an existing vins_node")
    failures: list[str] = []
    for row in rows:
        repeat = row["repeat"]
        run_dir = (
            RUNTIME
            / "backend_replays/a02_0_900/donor_delete_only"
            / f"repeat{repeat}"
        )
        command = [
            "bash",
            str(CELL_RUNNER),
            repeat,
            row["feature_bag"],
            row["canonical_config"],
            str(CONFIG_SCRATCH),
            str(run_dir),
            str(port),
        ]
        print(f"start donor-delete-only repeat{repeat}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            print(f"failure donor-delete-only repeat{repeat}: rc={result.returncode}")
            failures.append(f"repeat{repeat}:rc{result.returncode}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--port", type=int, default=28791)
    args = parser.parse_args()
    if args.prepare_only == args.execute:
        raise SystemExit("choose exactly one of --prepare-only or --execute")
    if args.prepare_only:
        prepare()
        return 0
    return execute(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
