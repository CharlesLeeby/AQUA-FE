#!/usr/bin/env python3
"""Summarize Harbor07 raw and persistent frontend coverage into CSV files."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


INPUT = Path("/home/ma/gftt_admission_persistent_coverage/h07")
OUTPUT = Path("/home/ma/AQUA-FE_WS/logs/gftt_admission_persistent_coverage")
PROFILES = ("off", "v2", "v3")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summaries = {
        profile: json.loads((INPUT / profile / "summary.json").read_text(encoding="utf-8"))
        for profile in PROFILES
    }
    fields = {
        "raw_coverage_median": "selected_median_output_grid_coverage",
        "raw_coverage_p10": "selected_p10_output_grid_coverage",
        "age_ge2_tracks_median": "selected_median_age_ge2_tracks",
        "age_ge2_tracks_p10": "selected_p10_age_ge2_tracks",
        "age_ge2_coverage_median": "selected_median_age_ge2_grid_coverage",
        "age_ge2_coverage_p10": "selected_p10_age_ge2_grid_coverage",
        "age_ge3_tracks_median": "selected_median_age_ge3_tracks",
        "age_ge3_tracks_p10": "selected_p10_age_ge3_tracks",
        "age_ge3_coverage_median": "selected_median_age_ge3_grid_coverage",
        "age_ge3_coverage_p10": "selected_p10_age_ge3_grid_coverage",
        "lifetime_median": "all_lifetime_median_selected_frames",
        "lifetime_p75": "all_lifetime_p75_selected_frames",
    }
    summary_rows = []
    for profile, summary in summaries.items():
        row = {
            "dataset": "harbor07_1660_1720",
            "profile": profile,
            "processed_frames": summary["processed_frames"],
            "selected_frames": summary["selected_frames"],
        }
        row.update({output_name: summary[source_name] for output_name, source_name in fields.items()})
        row["artifact_dir"] = str(INPUT / profile)
        summary_rows.append(row)
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUTPUT / "persistent_coverage_summary.csv", index=False)

    frame_tables = {}
    for profile in PROFILES:
        frame = pd.read_csv(INPUT / profile / "per_frame.csv")
        frame = frame.loc[frame["selected_for_output"] == 1, [
            "raw_frame_index",
            "output_tracks",
            "output_grid_coverage",
            "output_age_ge2_tracks",
            "output_age_ge2_grid_coverage",
            "output_age_ge3_tracks",
            "output_age_ge3_grid_coverage",
        ]].copy()
        frame = frame.rename(
            columns={column: f"{profile}_{column}" for column in frame.columns if column != "raw_frame_index"}
        )
        frame_tables[profile] = frame
    paired = frame_tables["off"]
    for profile in ("v2", "v3"):
        paired = paired.merge(
            frame_tables[profile],
            on="raw_frame_index",
            how="inner",
            validate="one_to_one",
        )
    if len(paired) != 30:
        raise RuntimeError(f"expected 30 paired selected frames, got {len(paired)}")
    paired.to_csv(OUTPUT / "persistent_coverage_paired_frames.csv", index=False)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
