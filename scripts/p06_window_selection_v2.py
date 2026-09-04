#!/usr/bin/env python3
"""P06 window-selection v2 entrypoint with the unchanged frozen score rules."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Sequence

try:
    from scripts import p02_window_selection as core
except ModuleNotFoundError:  # direct ``python scripts/p06_window_selection_v2.py`` entry
    import p02_window_selection as core


PROTOCOL_VERSION = "isj-window-selection-v2"


def write_window_audit(
    path: Path,
    rows: Sequence[dict[str, object]],
    *,
    dataset_family: str,
    sequence: str,
) -> None:
    fields = [
        "protocol_version",
        "dataset_family",
        "sequence",
        "window_index",
        "window_start_s",
        "window_end_s",
        "input_frame_count",
        "grid_coverage_p50",
        "dropout_ratio_p50",
        "flat_region_ratio_p50",
        "degradation_score_p50",
        "grid_deficit_scaled",
        "dropout_scaled",
        "flat_region_scaled",
        "degradation_scaled",
        "frame_score_p25",
        "frame_score_p50",
        "frame_score_p75",
        "score",
        "texture_stratum",
        "selected_by_sequence_rule",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "dataset_family": dataset_family,
                    "sequence": sequence,
                    **row,
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--dataset-family", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--input-rate-hz", required=True, type=float)
    parser.add_argument("--window-duration-s", type=float, default=core.WINDOW_DURATION_S)
    parser.add_argument("--min-input-frames", type=int, default=core.MIN_INPUT_FRAMES)
    args = parser.parse_args()

    rows = core.build_fixed_windows(
        core.read_csv_rows(Path(args.metrics_csv)),
        input_rate_hz=args.input_rate_hz,
        window_duration_s=args.window_duration_s,
        min_input_frames=args.min_input_frames,
    )
    write_window_audit(
        Path(args.output_csv),
        rows,
        dataset_family=args.dataset_family,
        sequence=args.sequence,
    )
    print(f"wrote {len(rows)} v2 fixed windows to {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
