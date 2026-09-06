#!/usr/bin/env python3
"""Freeze all-and-only active admission-continuation lineages into a matched plan."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import audit_frontend_coverage_monotone_router_v2_actions as common


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_admission_continuation_v1"
BUILDER = ROOT / "scripts/build_gftt_matched_lineage_control.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    output = PAPER / "matched_control_plan.json"
    lock_path = PAPER / "matched_control_plan.lock.json"
    if output.exists() or lock_path.exists():
        raise RuntimeError(
            "refusing to overwrite frozen matched-control plan or lock"
        )
    action_path = PAPER / "action_audit.csv"
    frontend_path = PAPER / "frontend_audit.csv"
    frontend_rows = common.read_csv(frontend_path)
    active = [
        row
        for row in frontend_rows
        if row["arm"] != "klt" and int(row["admitted_sidecars"]) > 0
    ]
    actions = common.read_csv(action_path)
    observed_frames: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for row in actions:
        slug, arm = row["run_slug"], row["arm"]
        frame = int(row["selected_feature_index"])
        for track_id in json.loads(row["admitted_ids_json"]):
            observed_frames[(slug, arm, int(track_id))].append(frame)

    cells: list[dict[str, object]] = []
    for row in active:
        slug, arm = row["run_slug"], row["arm"]
        first_frame: dict[int, list[int]] = defaultdict(list)
        sparse = False
        for (item_slug, item_arm, track_id), frames in observed_frames.items():
            if (item_slug, item_arm) != (slug, arm):
                continue
            unique = sorted(set(frames))
            first_frame[unique[0]].append(track_id)
            sparse |= unique != list(range(unique[0], unique[-1] + 1))
        birth_groups = [
            sorted(first_frame[frame]) for frame in sorted(first_frame)
        ]
        if not birth_groups:
            raise RuntimeError(f"active cell lacks lineage IDs: {slug} {arm}")
        cells.append(
            {
                "run_slug": slug,
                "arm": arm,
                "target_bag_sha256": row["feature_bag_sha256"],
                "birth_groups": birth_groups,
                "allow_sparse_target_schedule": sparse,
            }
        )

    payload = {
        "schema_version": "aqua-fe-admission-continuation-v1-matched-plan-v1",
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "scientific_role": "retrospective same-ID/frame/dose matched-GFTT control before any backend replay",
        "selection_basis": "all and only action-positive arm-windows in the frozen 6x3 admission-continuation frontend matrix",
        "action_audit_sha256": sha256(action_path),
        "frontend_audit_sha256": sha256(frontend_path),
        "builder": {
            "path": str(BUILDER.relative_to(ROOT)),
            "sha256": sha256(BUILDER),
            "preserve_target_ids": True,
            "parameters": {
                "max_candidates": 512,
                "quality_level": 0.01,
                "min_distance": 18,
                "block_size": 7,
                "exclusion_radius": 18,
                "max_image_dt": 0.002,
                "max_fb_error": 1.0,
                "control_source_code": 0
            },
            "known_limitation": "Retrospective source control matched to the learned intervention's IDs, frames, and dose; it is not an online detector-isolation control."
        },
        "cells": cells,
        "lineages_total": sum(
            len(group) for cell in cells for group in cell["birth_groups"]
        ),
        "action_positive_cells_total": len(cells),
        "backend_results_seen_before_freeze": False
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lock = {
        "schema_version": (
            "aqua-fe-admission-continuation-v1-matched-plan-lock-v1"
        ),
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "experiment_id": "EXP-20260906-012",
        "backend_results_seen_before_freeze": False,
        "matched_control_plan": str(output.relative_to(ROOT)),
        "matched_control_plan_sha256": sha256(output),
        "builder": str(BUILDER.relative_to(ROOT)),
        "builder_sha256": sha256(BUILDER),
        "action_audit_sha256": sha256(action_path),
        "frontend_audit_sha256": sha256(frontend_path),
    }
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cells": len(cells),
                "lineages": payload["lineages_total"],
                "plan_sha256": lock["matched_control_plan_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
