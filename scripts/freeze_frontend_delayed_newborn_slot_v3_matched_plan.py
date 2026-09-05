#!/usr/bin/env python3
"""Freeze all-and-only active v3 lineages into a matched-control plan."""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
BUILDER = ROOT / "scripts/build_gftt_matched_lineage_control.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    output = PAPER / "matched_control_plan.json"
    if output.exists():
        raise RuntimeError(f"refusing to overwrite frozen plan: {output}")
    action_path = PAPER / "action_audit.csv"
    opportunity_path = PAPER / "opportunity_audit.csv"
    active = [
        row for row in read_csv(opportunity_path)
        if int(row["promoted_observations"]) > 0
    ]
    actions = [
        row for row in read_csv(action_path)
        if int(row.get("promoted_observations", "0") or 0) > 0
    ]
    first_frame: dict[tuple[str, str, int], int] = {}
    for row in actions:
        key_prefix = (row["run_slug"], row["arm"])
        frame = int(row["selected_feature_index"])
        for track_id in json.loads(row["promoted_ids_json"]):
            key = (*key_prefix, int(track_id))
            first_frame[key] = min(frame, first_frame.get(key, frame))

    cells: list[dict[str, object]] = []
    for row in active:
        slug, arm = row["run_slug"], row["arm"]
        grouped: dict[int, list[int]] = defaultdict(list)
        for (item_slug, item_arm, track_id), frame in first_frame.items():
            if (item_slug, item_arm) == (slug, arm):
                grouped[frame].append(track_id)
        birth_groups = [sorted(grouped[frame]) for frame in sorted(grouped)]
        if not birth_groups:
            raise RuntimeError(f"active cell lacks lineage IDs: {slug} {arm}")
        cells.append(
            {
                "run_slug": slug,
                "arm": arm,
                "target_bag_sha256": row["feature_bag_sha256"],
                "birth_groups": birth_groups,
            }
        )
    payload = {
        "schema_version": "aqua-fe-delayed-newborn-slot-v3-matched-plan-v1",
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "scientific_role": "retrospective same-ID/frame/dose matched-GFTT control before any v3 backend replay",
        "selection_basis": "all and only action-positive arm-windows in the frozen 6x3 v3 export matrix",
        "action_audit_sha256": sha256(action_path),
        "opportunity_audit_sha256": sha256(opportunity_path),
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
                "control_source_code": 0,
            },
            "known_limitation": (
                "Lineages with different first-publication frames are applied "
                "in deterministic ascending-frame stages. This is a retrospective "
                "dose/slot source control, not an online detector-isolation control."
            ),
        },
        "cells": cells,
        "lineages_total": sum(len(group) for cell in cells for group in cell["birth_groups"]),
        "action_positive_cells_total": len(cells),
        "backend_results_seen_before_freeze": False,
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"cells": len(cells), "lineages": payload["lineages_total"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
