from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Select degraded frame windows from a quality scan CSV.")
    parser.add_argument("--quality-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--min-run", type=int, default=3, help="Minimum consecutive degraded samples.")
    parser.add_argument("--pad", type=int, default=30, help="Frame-index padding around each selected run.")
    parser.add_argument("--max-windows", type=int, default=10)
    args = parser.parse_args()

    scan = pd.read_csv(args.quality_csv)
    if scan.empty:
        raise ValueError(f"Empty quality scan: {args.quality_csv}")
    degraded = scan[scan["is_degraded"].astype(bool)].copy()
    windows = []
    if not degraded.empty:
        run = []
        previous_pos = None
        for row in degraded.itertuples(index=False):
            pos = int(row.frame_index)
            if previous_pos is None or _is_consecutive(scan, previous_pos, pos):
                run.append(row)
            else:
                _append_run(windows, run, args.pad, args.min_run)
                run = [row]
            previous_pos = pos
        _append_run(windows, run, args.pad, args.min_run)

    windows.sort(key=lambda item: (item["mean_quality"], -item["length"]))
    windows = windows[: args.max_windows]
    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "window_id",
                "start_index",
                "end_index",
                "length",
                "mean_quality",
                "mean_texture",
                "mean_degradation",
                "mean_flat_region",
                "reasons",
            ],
        )
        writer.writeheader()
        for idx, window in enumerate(windows):
            writer.writerow({"window_id": idx, **window})
    print(f"wrote {out}")
    if windows:
        for idx, window in enumerate(windows):
            print(
                f"{idx}: {window['start_index']}-{window['end_index']} "
                f"len={window['length']} q={window['mean_quality']:.3f} "
                f"tex={window['mean_texture']:.3f} "
                f"deg={window['mean_degradation']:.3f} "
                f"flat={window['mean_flat_region']:.3f} {window['reasons']}"
            )
    else:
        print("no degraded windows selected")
    return 0


def _is_consecutive(scan: pd.DataFrame, previous_frame_index: int, current_frame_index: int) -> bool:
    positions = scan["frame_index"].to_numpy()
    prev_pos = int((positions == previous_frame_index).argmax())
    cur_pos = int((positions == current_frame_index).argmax())
    return cur_pos == prev_pos + 1


def _append_run(windows: list[dict], run: list, pad: int, min_run: int) -> None:
    if len(run) < min_run:
        return
    qualities = [float(row.image_quality) for row in run]
    textures = [float(row.texture_score) for row in run]
    degradations = _row_values(run, "degradation_score")
    flat_regions = _row_values(run, "flat_region_ratio")
    reasons = sorted({str(row.degradation_reason) for row in run})
    start = max(0, int(run[0].frame_index) - pad)
    end = int(run[-1].frame_index) + pad
    windows.append(
        {
            "start_index": start,
            "end_index": end,
            "length": end - start + 1,
            "mean_quality": sum(qualities) / len(qualities),
            "mean_texture": sum(textures) / len(textures),
            "mean_degradation": sum(degradations) / len(degradations) if degradations else float("nan"),
            "mean_flat_region": sum(flat_regions) / len(flat_regions) if flat_regions else float("nan"),
            "reasons": ";".join(reasons),
        }
    )


def _row_values(run: list, attr: str) -> list[float]:
    values = []
    for row in run:
        if hasattr(row, attr):
            values.append(float(getattr(row, attr)))
    return values


if __name__ == "__main__":
    raise SystemExit(main())
