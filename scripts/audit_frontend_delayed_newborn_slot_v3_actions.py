#!/usr/bin/env python3
"""Audit v3 actions and exact startup protection against fresh KLT."""

from __future__ import annotations

import csv
from pathlib import Path

import audit_frontend_coverage_monotone_router_v2_actions as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_delayed_newborn_slot_v3"
)
SHADOW = RUNTIME / "shadow_root"


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"dnr3_{window['run_slug']}_{arm['arm']}"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = SHADOW
    base.run_dir = run_dir
    result = base.main()

    windows = base.read_csv(PAPER / "development_windows.csv")
    arms = base.read_csv(PAPER / "arms.csv")
    klt_arm = next(arm for arm in arms if arm["arm"] == "klt")
    learned_arms = [arm for arm in arms if arm["arm"] != "klt"]
    rows: list[dict[str, object]] = []
    for window in windows:
        klt_frames = base.load_feature_frames(
            run_dir(window, klt_arm) / "features.bag"
        )
        for arm in learned_arms:
            candidate_frames = base.load_feature_frames(
                run_dir(window, arm) / "features.bag"
            )
            count = min(32, len(klt_frames), len(candidate_frames))
            mismatches = [
                index
                for index in range(count)
                if klt_frames[index]["bytes"] != candidate_frames[index]["bytes"]
            ]
            rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "arm": arm["arm"],
                    "protected_frame_count_expected": 32,
                    "protected_frame_count_compared": count,
                    "protected_feature_messages_exact": not mismatches and count == 32,
                    "mismatch_indices": ";".join(map(str, mismatches)),
                    "status": "PASS" if not mismatches and count == 32 else "FAIL",
                }
            )
    write_csv(PAPER / "startup_protection_audit.csv", rows)
    return result if result != 0 else (0 if all(r["status"] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    raise SystemExit(main())
