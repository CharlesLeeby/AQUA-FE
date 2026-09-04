#!/usr/bin/env python3
"""Outcome-blind MIMIR-UW window screening for AQUA-FE positive search.

This is the MIMIR-UW adapter for the frozen P06 window-selection protocol.  It
runs only KLT plus image-quality metrics, builds non-overlapping 45 s windows,
and never reads learned-feature or trajectory outcomes while selecting windows.
The selected low-texture windows are then suitable inputs to
``run_paper_sidecar_profiles.sh mimir_uw_loftr_v31_pair``.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
DEFAULT_DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/mimir_uw/slam_subset")
DEFAULT_OUTPUT = Path("/mnt/data/AQUA-FE_WS/logs/mimir_positive_search_v1")
KLT_CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"


@dataclass(frozen=True)
class SequenceSpec:
    environment: str
    track: str
    image_dir: Path
    camera_csv: Path
    input_rate_hz: float

    @property
    def sequence(self) -> str:
        return f"{self.environment}/{self.track}"

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.sequence.lower()).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--every-n", type=int, default=2)
    parser.add_argument("--window-duration-s", type=float, default=45.0)
    parser.add_argument("--min-input-frames", type=int, default=200)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--include", default="", help="Optional regex over ENV/TRACK.")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def discover_sequences(dataset_root: Path, include: str) -> list[SequenceSpec]:
    include_re = re.compile(include) if include else None
    sequences: list[SequenceSpec] = []
    for camera_csv in sorted(dataset_root.glob("*/*/auv0/rgb/cam0/data.csv")):
        track_root = camera_csv.parents[3]
        environment = track_root.parent.name
        track = track_root.name
        sequence = f"{environment}/{track}"
        if include_re and not include_re.search(sequence):
            continue
        image_dir = camera_csv.parent / "data"
        if not image_dir.is_dir():
            continue
        sequences.append(
            SequenceSpec(
                environment=environment,
                track=track,
                image_dir=image_dir,
                camera_csv=camera_csv,
                input_rate_hz=median_rate_hz(camera_csv),
            )
        )
    if not sequences:
        raise RuntimeError(f"no MIMIR-UW sequences found under {dataset_root}")
    return sequences


def median_rate_hz(camera_csv: Path) -> float:
    stamps: list[int] = []
    with camera_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            try:
                stamps.append(int(row[0]))
            except (IndexError, ValueError):
                continue
    unique = sorted(set(stamps))
    deltas = [(right - left) * 1e-9 for left, right in zip(unique, unique[1:]) if right > left]
    if not deltas:
        raise ValueError(f"not enough timestamps in {camera_csv}")
    return 1.0 / statistics.median(deltas)


def run_sequence(
    spec: SequenceSpec,
    *,
    output_root: Path,
    every_n: int,
    window_duration_s: float,
    min_input_frames: int,
    force: bool,
) -> tuple[Path, Path]:
    screening_dir = output_root / "screening"
    windows_dir = output_root / "windows"
    screening_dir.mkdir(parents=True, exist_ok=True)
    windows_dir.mkdir(parents=True, exist_ok=True)
    metrics_csv = screening_dir / f"{spec.slug}_klt_e{every_n}.csv"
    metrics_log = metrics_csv.with_suffix(".log")
    window_csv = windows_dir / f"{spec.slug}_windows.csv"

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": f"{ROOT}:{env.get('PYTHONPATH', '')}",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
    )
    if force or not metrics_complete(spec, metrics_csv, every_n):
        command = [
            sys.executable,
            "-m",
            "uw_frontend.evaluation.run_frontend_eval",
            "--input",
            os.fspath(spec.image_dir),
            "--output-csv",
            os.fspath(metrics_csv),
            "--method",
            "klt",
            "--config",
            os.fspath(KLT_CONFIG),
            "--preprocess",
            "adaptive_clahe",
            "--every-n",
            str(every_n),
        ]
        with metrics_log.open("w", encoding="utf-8") as handle:
            subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=True,
            )

    if force or not window_csv.is_file():
        command = [
            sys.executable,
            os.fspath(ROOT / "scripts/p06_window_selection_v2.py"),
            "--metrics-csv",
            os.fspath(metrics_csv),
            "--output-csv",
            os.fspath(window_csv),
            "--dataset-family",
            "MIMIR-UW",
            "--sequence",
            spec.sequence,
            "--input-rate-hz",
            f"{spec.input_rate_hz:.12f}",
            "--window-duration-s",
            f"{window_duration_s:.9f}",
            "--min-input-frames",
            str(min_input_frames),
        ]
        subprocess.run(command, cwd=ROOT, env=env, check=True)
    return metrics_csv, window_csv


def metrics_complete(spec: SequenceSpec, metrics_csv: Path, every_n: int) -> bool:
    """Reject interrupted streaming CSVs instead of treating existence as completion."""

    if not metrics_csv.is_file():
        return False
    image_count = sum(
        1
        for path in spec.image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    expected_rows = (image_count + every_n - 1) // every_n
    with metrics_csv.open("r", encoding="utf-8", errors="replace") as handle:
        observed_rows = max(0, sum(1 for _line in handle) - 1)
    return observed_rows == expected_rows


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError(f"refusing to write empty result: {path}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(
    results: dict[str, tuple[SequenceSpec, Path, Path]], output_root: Path
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    all_rows: list[dict[str, object]] = []
    for sequence in sorted(results):
        spec, metrics_csv, window_csv = results[sequence]
        for source in read_rows(window_csv):
            row: dict[str, object] = {
                **source,
                "environment": spec.environment,
                "track": spec.track,
                "input_rate_hz": spec.input_rate_hz,
                "image_dir": os.fspath(spec.image_dir),
                "klt_metrics_csv": os.fspath(metrics_csv),
                "window_audit_csv": os.fspath(window_csv),
            }
            all_rows.append(row)
    all_rows.sort(key=lambda row: (str(row["sequence"]), float(row["window_start_s"])))
    selected_low = [
        row
        for row in all_rows
        if str(row.get("texture_stratum")) == "low"
        and truthy(row.get("selected_by_sequence_rule"))
    ]
    selected_low.sort(key=lambda row: (-float(row["score"]), str(row["sequence"])))
    write_csv(output_root / "all_windows.csv", all_rows)
    if selected_low:
        write_csv(output_root / "selected_low_windows.csv", selected_low)
    write_report(output_root / "summary.md", all_rows, selected_low)
    return all_rows, selected_low


def write_report(
    path: Path,
    all_rows: list[dict[str, object]],
    selected_low: list[dict[str, object]],
) -> None:
    lines = [
        "# MIMIR-UW AQUA-FE positive-window screening",
        "",
        "Frozen selector: `isj-window-selection-v2`; outcome-blind KLT/image-quality screening.",
        "No learned-feature or VINS outcome is read during selection.",
        "",
        f"- fixed windows: {len(all_rows)}",
        f"- selected low-texture windows: {len(selected_low)}",
        "",
        "| rank | sequence | seconds | score | grid p50 | dropout p50 | flat p50 | degradation p50 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(selected_low, start=1):
        start = float(row["window_start_s"])
        end = float(row["window_end_s"])
        lines.append(
            f"| {rank} | {row['sequence']} | {start:.0f}-{end:.0f} | "
            f"{float(row['score']):.4f} | {float(row['grid_coverage_p50']):.4f} | "
            f"{float(row['dropout_ratio_p50']):.4f} | "
            f"{float(row['flat_region_ratio_p50']):.4f} | "
            f"{float(row['degradation_score_p50']):.4f} |"
        )
    lines.extend(["", "## Three-arm export-only probes", ""])
    for row in selected_low:
        start = float(row["window_start_s"])
        duration = float(row["window_end_s"]) - start
        lines.append(
            "```bash\n"
            f"RUN_VINS=0 bash scripts/run_paper_sidecar_profiles.sh "
            f"mimir_uw_loftr_v31_pair {row['environment']} {row['track']} "
            f"{start:g} {duration:g}\n"
            "```"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.every_n < 1 or args.jobs < 1:
        raise SystemExit("--every-n and --jobs must be positive")
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    sequences = discover_sequences(args.dataset_root.resolve(), args.include)
    results: dict[str, tuple[SequenceSpec, Path, Path]] = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                run_sequence,
                spec,
                output_root=output_root,
                every_n=args.every_n,
                window_duration_s=args.window_duration_s,
                min_input_frames=args.min_input_frames,
                force=args.force,
            ): spec
            for spec in sequences
        }
        for future in as_completed(futures):
            spec = futures[future]
            metrics_csv, window_csv = future.result()
            results[spec.sequence] = (spec, metrics_csv, window_csv)
            print(f"completed {spec.sequence}: {window_csv}", flush=True)
    all_rows, selected_low = aggregate(results, output_root)
    print(f"wrote {len(all_rows)} windows to {output_root / 'all_windows.csv'}")
    print(f"selected low-texture windows: {len(selected_low)}")
    for rank, row in enumerate(selected_low, start=1):
        print(
            f"{rank:02d} {row['sequence']} "
            f"{float(row['window_start_s']):.0f}-{float(row['window_end_s']):.0f}s "
            f"score={float(row['score']):.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
