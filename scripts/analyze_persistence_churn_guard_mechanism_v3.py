#!/usr/bin/env python3
"""Quantify GFTT birth persistence behind the v2 failure and v3 guard."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import numpy as np

from analyze_persistence_singlechain_frontend_v2 import CASES, load


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_churn_guard_v3"
V2_RUNTIME = ROOT / "artifacts/frontend_persistence_singlechain_v2"
FRAMES = {
    "a06_s000_d045": (1, 2, 3),
    "a09_6000_6800": (2, 3, 4),
    "a06_s045_d045": (2, 3, 4),
}
def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    victim_rows: list[dict[str, str]]
    with (ROOT / "papers/frontend_persistence_singlechain_v2/replacement_victims.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        victim_rows = list(csv.DictReader(stream))
    victim_by_frame = {
        (row["window"], int(row["selected_feature_index"])): int(row["track_id"])
        for row in victim_rows
    }
    output: list[dict[str, object]] = []
    for case in CASES:
        if case.window not in FRAMES:
            continue
        klt = load(case.klt_bag)
        lifetime = Counter(
            int(track_id)
            for frame in klt
            for track_id in frame["ids"]
        )
        v2_bag = V2_RUNTIME / "shadow_root/logs" / case.family / (
            f"external_hybrid_xfeat_every2_pscv2_{case.window}/features.bag"
        )
        v2 = load(v2_bag)
        v2_lifetime = Counter(
            int(track_id)
            for frame in v2
            for track_id, learned in zip(frame["ids"], frame["learned"])
            if learned
        )
        for frame_index in FRAMES[case.window]:
            frame = klt[frame_index]
            births = [
                int(track_id)
                for track_id, source in zip(frame["ids"], frame["sources"])
                if int(source) == 2
            ]
            lifetimes = np.asarray([lifetime[track_id] for track_id in births], dtype=float)
            learned_ids = [
                int(track_id)
                for track_id, learned in zip(
                    v2[frame_index]["ids"], v2[frame_index]["learned"]
                )
                if learned
            ]
            victim = victim_by_frame[(case.window, frame_index)]
            learned_id = learned_ids[0]
            victim_lifetime = int(lifetime[victim])
            learned_lifetime = int(v2_lifetime[learned_id])
            output.append(
                {
                    "window": case.window,
                    "selected_feature_index": frame_index,
                    "gftt_birth_count": len(births),
                    "mirror_count": len(frame["ids"]),
                    "gftt_birth_reserve_ratio": len(births) / len(frame["ids"]),
                    "all_gftt_lifetime_median_frames": float(np.median(lifetimes)),
                    "all_gftt_lifetime_mean_frames": float(np.mean(lifetimes)),
                    "all_gftt_singleton_fraction": float(np.mean(lifetimes == 1)),
                    "all_gftt_lifetime_ge10_fraction": float(np.mean(lifetimes >= 10)),
                    "all_gftt_lifetime_max_frames": int(np.max(lifetimes)),
                    "v2_victim_id": victim,
                    "v2_victim_lifetime_frames": victim_lifetime,
                    "v2_xfeat_id": learned_id,
                    "v2_xfeat_lifetime_frames": learned_lifetime,
                    "replacement_persistence_relation": (
                        "XFEAT_GREATER" if learned_lifetime > victim_lifetime else (
                            "TIE" if learned_lifetime == victim_lifetime else "GFTT_GREATER"
                        )
                    ),
                }
            )
    write_csv(PAPER / "birth_lifetime_evidence.csv", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
