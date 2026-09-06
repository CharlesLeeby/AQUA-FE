#!/usr/bin/env python3
"""Freeze identity-audited backend replays for EXP-20260906-012."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_admission_continuation_v1"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
V2_RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_admission_continuation_v1"
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


def validate_reused_klt(
    source: dict[str, str],
    slug: str,
    repeat: int,
    fresh_bag_sha256: str,
    node_hash: str,
    lib_hash: str,
) -> Path:
    if source["feature_bag_sha256"] != fresh_bag_sha256:
        raise RuntimeError(f"fresh/v2 KLT feature identity mismatch: {slug}")
    if source["vins_node_sha256"] != node_hash:
        raise RuntimeError(f"KLT VINS node identity mismatch: {slug}")
    if source["vins_lib_sha256"] != lib_hash:
        raise RuntimeError(f"KLT VINS library identity mismatch: {slug}")
    replay = V2_RUNTIME / "backend_replays" / slug / "klt" / f"repeat{repeat}"
    receipt = parse_receipt(replay / "replay_receipt.txt")
    vio = replay / "vins_output/vio.csv"
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
    return replay


def main() -> int:
    if PLAN.exists() or LOCK.exists():
        raise RuntimeError("refusing to overwrite a frozen backend plan or lock")
    decision = json.loads((PAPER / "decision.json").read_text(encoding="utf-8"))
    if decision.get("decision") != "FRONTEND_GO":
        raise RuntimeError("frontend decision is not FRONTEND_GO")
    matched = read_csv(PAPER / "matched_control_audit.csv")
    active_count = int(decision["active_arm_windows"])
    if len(matched) != active_count or any(row["status"] != "PASS" for row in matched):
        raise RuntimeError("matched-control audit is incomplete or failed")
    frontend = read_csv(PAPER / "frontend_audit.csv")
    if len(frontend) != 18:
        raise RuntimeError("frontend matrix is not 18/18")
    front_by_cell = {(row["run_slug"], row["arm"]): row for row in frontend}
    windows = read_csv(PAPER / "development_windows.csv")
    window_by_slug = {row["run_slug"]: row for row in windows}
    v2_plan = read_csv(V2_PAPER / "backend_smoke_plan.csv")
    v2_klt = {
        (row["run_slug"], int(row["repeat"])): row
        for row in v2_plan
        if row["cell_id"] == "klt"
    }
    node_hash = sha256(VINS_NODE)
    lib_hash = sha256(VINS_LIB)
    rows: list[dict[str, object]] = []

    # Validate and register all six frozen KLT controls. They are reused results,
    # not independent replays in this experiment.
    for window in windows:
        slug = window["run_slug"]
        fresh = front_by_cell[(slug, "klt")]
        for repeat in range(1, 4):
            source = v2_klt[(slug, repeat)]
            replay = validate_reused_klt(
                source,
                slug,
                repeat,
                fresh["feature_bag_sha256"],
                node_hash,
                lib_hash,
            )
            rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": slug,
                    "cell_id": "klt",
                    "source_arm": "klt",
                    "backend_role": "fresh_klt",
                    "repeat": repeat,
                    "execution": "REUSED_FROZEN_V2_REPLAY",
                    "feature_bag": source["feature_bag"],
                    "feature_bag_sha256": source["feature_bag_sha256"],
                    "canonical_config": source["canonical_config"],
                    "canonical_config_sha256": source["canonical_config_sha256"],
                    "camera_config": source["camera_config"],
                    "camera_config_sha256": source["camera_config_sha256"],
                    "vins_node_sha256": node_hash,
                    "vins_lib_sha256": lib_hash,
                    "replay_dir": str(replay),
                    "source_experiment": "EXP-20260904-005",
                }
            )

    for audit in sorted(matched, key=lambda row: (row["run_slug"], row["arm"])):
        slug, arm = audit["run_slug"], audit["arm"]
        learned = front_by_cell[(slug, arm)]
        source = v2_klt[(slug, 1)]
        cells = (
            (arm, "learned_active", Path(learned["feature_bag"])),
            (
                f"matched_gftt_for_{arm}",
                "matched_classical",
                Path(audit["control_bag"]),
            ),
        )
        for cell_id, role, bag in cells:
            for repeat in range(1, 4):
                replay = RUNTIME / "backend_replays" / slug / cell_id / f"repeat{repeat}"
                rows.append(
                    {
                        "window_id": window_by_slug[slug]["window_id"],
                        "run_slug": slug,
                        "cell_id": cell_id,
                        "source_arm": arm,
                        "backend_role": role,
                        "repeat": repeat,
                        "execution": "NEW_ADMISSION_CONTINUATION_REPLAY",
                        "feature_bag": str(bag),
                        "feature_bag_sha256": sha256(bag),
                        "canonical_config": source["canonical_config"],
                        "canonical_config_sha256": source["canonical_config_sha256"],
                        "camera_config": source["camera_config"],
                        "camera_config_sha256": source["camera_config_sha256"],
                        "vins_node_sha256": node_hash,
                        "vins_lib_sha256": lib_hash,
                        "replay_dir": str(replay),
                        "source_experiment": "EXP-20260906-012",
                    }
                )

    expected_rows = 18 + 6 * active_count
    expected_new = 6 * active_count
    if len(rows) != expected_rows:
        raise RuntimeError(f"expected {expected_rows} rows, got {len(rows)}")
    if sum(row["execution"] == "NEW_ADMISSION_CONTINUATION_REPLAY" for row in rows) != expected_new:
        raise RuntimeError("new backend replay count mismatch")
    write_csv(PLAN, rows)

    identity_paths = [
        PAPER / "preregistration.md",
        PAPER / "development_windows.csv",
        PAPER / "arms.csv",
        PAPER / "method_lock.json",
        PAPER / "decision.json",
        PAPER / "frontend_audit.csv",
        PAPER / "matched_control_plan.json",
        PAPER / "matched_control_plan.lock.json",
        PAPER / "matched_control_audit.csv",
        PLAN,
        ROOT / "scripts/run_frontend_admission_continuation_v1_backend.py",
        ROOT / "scripts/run_frontend_admission_continuation_v1_backend_cell.sh",
        ROOT / "scripts/freeze_frontend_admission_continuation_v1_backend_plan.py",
        ROOT / "scripts/finalize_frontend_admission_continuation_v1_backend.py",
        ROOT / "scripts/finalize_frontend_coverage_monotone_router_v2_backend.py",
        ROOT / "scripts/audit_frontend_admission_continuation_v1.py",
        ROOT / "scripts/build_gftt_matched_lineage_control.py",
        ROOT / "scripts/evaluate_vins_common_support_dual_scale.py",
    ]
    lock = {
        "schema_version": "aqua-fe-admission-continuation-v1-backend-lock-v1",
        "experiment_id": "EXP-20260906-012",
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "plan_rows_total": expected_rows,
        "new_replays": expected_new,
        "reused_klt_replays": 18,
        "active_arm_windows": active_count,
        "backend_results_seen_before_freeze": False,
        "reuse_contract": (
            "exact fresh/v2 KLT feature bag, canonical YAML, camera YAML, "
            "VINS binary/library, receipt and trajectory identities"
        ),
        "files": [
            {"path": str(path), "sha256": sha256(path)}
            for path in identity_paths
        ],
        "vins_workspace": str(VINS_WS),
        "vins_node_sha256": node_hash,
        "vins_lib_sha256": lib_hash,
    }
    LOCK.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "rows": expected_rows,
                "new": expected_new,
                "reused": 18,
                "active_cells": active_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
