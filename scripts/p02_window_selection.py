#!/usr/bin/env python3
"""Outcome-blind KLT/image-quality window scoring for the ISJ protocol."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


PROTOCOL_VERSION = "isj-window-selection-v1"
WINDOW_DURATION_S = 45.0
MIN_INPUT_FRAMES = 200
LOW_PERCENTILE = 0.80
NORMAL_PERCENTILE = 0.20
TAU_LOW = 0.17
TAU_NORMAL = 0.10


@dataclass(frozen=True)
class ScoreComponents:
    grid_coverage_p50: float
    dropout_ratio_p50: float
    flat_region_ratio_p50: float
    degradation_score_p50: float
    grid_deficit_scaled: float
    dropout_scaled: float
    flat_region_scaled: float
    degradation_scaled: float
    frame_score_p25: float
    frame_score_p50: float
    frame_score_p75: float
    score: float


def clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def linear_quantile(values: Sequence[float], probability: float) -> float:
    """Return the Hyndman-Fan type-7 quantile used by the frozen protocol."""

    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        raise ValueError("quantile requires at least one finite value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability outside [0, 1]: {probability}")
    position = (len(finite) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return finite[lower]
    fraction = position - lower
    return finite[lower] * (1.0 - fraction) + finite[upper] * fraction


def score_metric_rows(rows: Sequence[Mapping[str, str | float | int]]) -> ScoreComponents:
    if not rows:
        raise ValueError("cannot score an empty window")

    columns = {
        field: _bounded_column(rows, field)
        for field in (
            "grid_coverage",
            "dropout_ratio",
            "flat_region_ratio",
            "degradation_score",
        )
    }
    grid_p50 = linear_quantile(columns["grid_coverage"], 0.50)
    dropout_p50 = linear_quantile(columns["dropout_ratio"], 0.50)
    flat_p50 = linear_quantile(columns["flat_region_ratio"], 0.50)
    degradation_p50 = linear_quantile(columns["degradation_score"], 0.50)

    # All four source metrics have physical support [0, 1]. The feature scaling
    # is therefore a frozen direction correction plus clipping, not a fitted
    # transform that could leak held-out sequence information.
    grid_scaled = clip01(1.0 - grid_p50)
    dropout_scaled = clip01(dropout_p50)
    flat_scaled = clip01(flat_p50)
    degradation_scaled = clip01(degradation_p50)
    frame_scores = [
        (
            (1.0 - grid)
            + dropout
            + flat
            + degradation
        )
        / 4.0
        for grid, dropout, flat, degradation in zip(
            columns["grid_coverage"],
            columns["dropout_ratio"],
            columns["flat_region_ratio"],
            columns["degradation_score"],
        )
    ]
    score_p25 = linear_quantile(frame_scores, 0.25)
    score_p50 = linear_quantile(frame_scores, 0.50)
    score_p75 = linear_quantile(frame_scores, 0.75)
    return ScoreComponents(
        grid_coverage_p50=grid_p50,
        dropout_ratio_p50=dropout_p50,
        flat_region_ratio_p50=flat_p50,
        degradation_score_p50=degradation_p50,
        grid_deficit_scaled=grid_scaled,
        dropout_scaled=dropout_scaled,
        flat_region_scaled=flat_scaled,
        degradation_scaled=degradation_scaled,
        frame_score_p25=score_p25,
        frame_score_p50=score_p50,
        frame_score_p75=score_p75,
        score=score_p50,
    )


def classify_scores(
    scores: Sequence[float],
    *,
    tau_low: float = TAU_LOW,
    tau_normal: float = TAU_NORMAL,
    low_percentile: float = LOW_PERCENTILE,
    normal_percentile: float = NORMAL_PERCENTILE,
) -> list[str]:
    if tau_normal >= tau_low:
        raise ValueError("tau_normal must be strictly below tau_low")
    low_cut = linear_quantile(scores, low_percentile)
    normal_cut = linear_quantile(scores, normal_percentile)
    labels: list[str] = []
    for score in scores:
        if score >= tau_low and score >= low_cut:
            labels.append("low")
        elif score <= tau_normal and score <= normal_cut:
            labels.append("normal")
        else:
            labels.append("unclassified")
    return labels


def select_within_sequence(
    windows: Sequence[dict[str, object]], max_per_stratum: int = 2
) -> list[dict[str, object]]:
    """Apply the frozen stable score/start tie-break without changing windows."""

    selected: set[int] = set()
    low = sorted(
        (item for item in windows if item["texture_stratum"] == "low"),
        key=lambda item: (-float(item["score"]), float(item["window_start_s"])),
    )
    normal = sorted(
        (item for item in windows if item["texture_stratum"] == "normal"),
        key=lambda item: (float(item["score"]), float(item["window_start_s"])),
    )
    for item in low[:max_per_stratum] + normal[:max_per_stratum]:
        selected.add(int(item["window_index"]))

    output: list[dict[str, object]] = []
    for item in windows:
        row = dict(item)
        row["selected_by_sequence_rule"] = int(row["window_index"]) in selected
        output.append(row)
    return output


def build_fixed_windows(
    rows: Sequence[Mapping[str, str]],
    *,
    input_rate_hz: float,
    window_duration_s: float = WINDOW_DURATION_S,
    min_input_frames: int = MIN_INPUT_FRAMES,
) -> list[dict[str, object]]:
    if input_rate_hz <= 0.0:
        raise ValueError("input_rate_hz must be positive")
    if window_duration_s <= 0.0:
        raise ValueError("window_duration_s must be positive")
    _assert_klt_only(rows)
    timed_rows = _rows_with_relative_time(rows, input_rate_hz)
    if not timed_rows:
        return []

    last_time = timed_rows[-1][0]
    full_window_count = int(math.floor((last_time + 1.0 / input_rate_hz) / window_duration_s))
    windows: list[dict[str, object]] = []
    for window_index in range(full_window_count):
        start = window_index * window_duration_s
        end = start + window_duration_s
        members = [row for stamp, row in timed_rows if start <= stamp < end]
        if len(members) < min_input_frames:
            continue
        components = score_metric_rows(members)
        windows.append(
            {
                "window_index": window_index,
                "window_start_s": start,
                "window_end_s": end,
                "input_frame_count": len(members),
                **components.__dict__,
            }
        )

    labels = classify_scores([float(item["score"]) for item in windows]) if windows else []
    for item, label in zip(windows, labels):
        item["texture_stratum"] = label
    return select_within_sequence(windows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def _bounded_column(
    rows: Sequence[Mapping[str, str | float | int]], field: str
) -> list[float]:
    values: list[float] = []
    for row in rows:
        if field not in row:
            raise ValueError(f"required KLT/image metric is missing: {field}")
        try:
            value = float(row[field])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric required metric: {field}") from exc
        if not math.isfinite(value):
            raise ValueError(f"non-finite required metric: {field}")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"required metric outside [0, 1]: {field}={value}")
        values.append(value)
    return values


def _assert_klt_only(rows: Sequence[Mapping[str, str]]) -> None:
    for row in rows:
        mode = str(row.get("tracker_mode", "klt")).strip().lower()
        if mode not in {"", "klt", "n/a"}:
            raise ValueError(f"non-KLT tracker_mode in screening input: {mode}")
        for field, value in row.items():
            name = field.lower()
            if not name.endswith("_tracks"):
                continue
            if not any(token in name for token in ("xfeat", "superpoint", "loftr", "learned")):
                continue
            try:
                count = float(value or 0)
            except ValueError:
                count = 0.0
            if count != 0.0:
                raise ValueError(f"learned track count in screening input: {field}={value}")


def _rows_with_relative_time(
    rows: Sequence[Mapping[str, str]], input_rate_hz: float
) -> list[tuple[float, Mapping[str, str]]]:
    timed: list[tuple[float, Mapping[str, str]]] = []
    timestamp_field = "timestamp" if rows and "timestamp" in rows[0] else None
    if timestamp_field:
        stamps = [float(row[timestamp_field]) for row in rows]
        origin = min(stamps)
        timed = sorted((stamp - origin, row) for stamp, row in zip(stamps, rows))
    else:
        indices = [int(float(row["frame_index"])) for row in rows]
        origin = min(indices)
        timed = sorted(((index - origin) / input_rate_hz, row) for index, row in zip(indices, rows))
    return timed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--dataset-family", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--input-rate-hz", required=True, type=float)
    parser.add_argument("--window-duration-s", type=float, default=WINDOW_DURATION_S)
    parser.add_argument("--min-input-frames", type=int, default=MIN_INPUT_FRAMES)
    args = parser.parse_args()

    rows = build_fixed_windows(
        read_csv_rows(Path(args.metrics_csv)),
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
    print(f"wrote {len(rows)} fixed windows to {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
