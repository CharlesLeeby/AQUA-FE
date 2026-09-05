#!/usr/bin/env python3
"""Freeze the v3 backend plan, including identity-audited KLT reuse."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
V2_RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_coverage_monotone_router_v2"
)
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_delayed_newborn_slot_v3"
)
PLAN = PAPER / "backend_replay_plan.csv"
LOCK = PAPER / "backend_execution_lock.json"
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")
VINS_NODE = VINS_WS / "devel/lib/vins/vins_node"
VINS_LIB = VINS_WS / "devel/lib/libvins_lib.so"


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
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if "=" in line
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if PLAN.exists() or LOCK.exists():
        raise RuntimeError("refusing to overwrite a frozen v3 backend plan or lock")
    decision = json.loads((PAPER / "decision.json").read_text(encoding="utf-8"))
    if decision.get("decision") != "FRONTEND_GO":
        raise RuntimeError("v3 frontend decision is not FRONTEND_GO")
    matched_audit = read_csv(PAPER / "matched_control_audit.csv")
    if len(matched_audit) != 7 or any(row["status"] != "PASS" for row in matched_audit):
        raise RuntimeError("matched-control audit is not 7/7 PASS")
    frontend = read_csv(PAPER / "frontend_audit.csv")
    front_by_cell = {(row["run_slug"], row["arm"]): row for row in frontend}
    window_by_slug = {
        row["run_slug"]: row for row in read_csv(PAPER / "development_windows.csv")
    }
    v2_plan = read_csv(V2_PAPER / "backend_smoke_plan.csv")
    v2_klt = {
        (row["run_slug"], int(row["repeat"])): row
        for row in v2_plan if row["cell_id"] == "klt"
    }
    node_hash = sha256(VINS_NODE)
    lib_hash = sha256(VINS_LIB)
    rows: list[dict[str, object]] = []
    active_slugs = sorted({row["run_slug"] for row in matched_audit})
    for slug in active_slugs:
        window = window_by_slug[slug]
        klt_front = front_by_cell[(slug, "klt")]
        for repeat in range(1, 4):
            source = v2_klt[(slug, repeat)]
            if source["feature_bag_sha256"] != klt_front["feature_bag_sha256"]:
                raise RuntimeError(f"KLT feature identity mismatch: {slug}")
            if source["vins_node_sha256"] != node_hash or source["vins_lib_sha256"] != lib_hash:
                raise RuntimeError(f"KLT backend binary identity mismatch: {slug}")
            replay_dir = V2_RUNTIME / "backend_replays" / slug / "klt" / f"repeat{repeat}"
            receipt_path = replay_dir / "replay_receipt.txt"
            receipt = parse_receipt(receipt_path)
            vio = replay_dir / "vins_output/vio.csv"
            expected = {
                "window_id": source["window_id"],
                "run_slug": slug,
                "cell_id": "klt",
                "repeat": str(repeat),
                "feature_bag_sha256": source["feature_bag_sha256"],
                "canonical_config_sha256": source["canonical_config_sha256"],
                "vins_node_sha256": node_hash,
                "vins_lib_sha256": lib_hash,
            }
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"KLT replay receipt identity mismatch: {slug}/r{repeat}")
            if not vio.is_file() or receipt.get("vio_csv_sha256") != sha256(vio):
                raise RuntimeError(f"KLT trajectory identity mismatch: {slug}/r{repeat}")
            rows.append({
                "window_id": window["window_id"], "run_slug": slug,
                "cell_id": "klt", "source_arm": "klt", "backend_role": "fresh_klt",
                "repeat": repeat, "execution": "REUSED_FROZEN_V2_REPLAY",
                "feature_bag": source["feature_bag"],
                "feature_bag_sha256": source["feature_bag_sha256"],
                "canonical_config": source["canonical_config"],
                "canonical_config_sha256": source["canonical_config_sha256"],
                "camera_config": source["camera_config"],
                "camera_config_sha256": source["camera_config_sha256"],
                "vins_node_sha256": node_hash, "vins_lib_sha256": lib_hash,
                "replay_dir": str(replay_dir),
                "source_experiment": "EXP-20260904-005",
            })

        for audit in sorted(
            (row for row in matched_audit if row["run_slug"] == slug),
            key=lambda row: row["arm"],
        ):
            arm = audit["arm"]
            learned = front_by_cell[(slug, arm)]
            klt_source = v2_klt[(slug, 1)]
            cells = (
                (arm, arm, "learned_active", Path(learned["run_dir"]) / "features.bag"),
                (
                    f"matched_gftt_for_{arm}", arm, "matched_classical",
                    Path(audit["control_bag"]),
                ),
            )
            for cell_id, source_arm, role, bag in cells:
                for repeat in range(1, 4):
                    replay_dir = RUNTIME / "backend_replays" / slug / cell_id / f"repeat{repeat}"
                    rows.append({
                        "window_id": window["window_id"], "run_slug": slug,
                        "cell_id": cell_id, "source_arm": source_arm,
                        "backend_role": role, "repeat": repeat,
                        "execution": "NEW_V3_REPLAY", "feature_bag": str(bag),
                        "feature_bag_sha256": sha256(bag),
                        "canonical_config": klt_source["canonical_config"],
                        "canonical_config_sha256": klt_source["canonical_config_sha256"],
                        "camera_config": klt_source["camera_config"],
                        "camera_config_sha256": klt_source["camera_config_sha256"],
                        "vins_node_sha256": node_hash, "vins_lib_sha256": lib_hash,
                        "replay_dir": str(replay_dir), "source_experiment": "EXP-20260905-008",
                    })
    if len(rows) != 54:
        raise RuntimeError(f"expected 54 total rows, got {len(rows)}")
    if sum(row["execution"] == "NEW_V3_REPLAY" for row in rows) != 42:
        raise RuntimeError("expected 42 new v3 replays")
    write_csv(PLAN, rows)

    identity_paths = [
        PAPER / "preregistration.md", PAPER / "development_windows.csv",
        PAPER / "arms.csv", PAPER / "method_lock.json", PAPER / "decision.json",
        PAPER / "frontend_audit.csv", PAPER / "matched_control_plan.json",
        PAPER / "matched_control_plan_amendment.json", PAPER / "matched_control_audit.csv",
        PLAN, ROOT / "scripts/run_frontend_delayed_newborn_slot_v3_backend.py",
        ROOT / "scripts/run_frontend_delayed_newborn_slot_v3_backend_cell.sh",
    ]
    lock = {
        "schema_version": "aqua-fe-delayed-newborn-slot-v3-backend-lock-v1",
        "experiment_id": "EXP-20260905-008",
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "plan_rows_total": len(rows), "new_replays": 42, "reused_klt_replays": 12,
        "backend_results_seen_before_freeze": False,
        "reuse_contract": "exact feature bag, canonical YAML, camera YAML, VINS binary/library and receipt-bound trajectory",
        "files": [{"path": str(path), "sha256": sha256(path)} for path in identity_paths],
        "vins_workspace": str(VINS_WS), "vins_node_sha256": node_hash,
        "vins_lib_sha256": lib_hash,
    }
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rows": 54, "new": 42, "reused": 12}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
