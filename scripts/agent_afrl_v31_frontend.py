#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs/afrl_v31_frontend"
KLT_CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"
HYBRID_CONFIG = ROOT / "uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml"


@dataclass(frozen=True)
class EvalCase:
    dataset: str
    window: str
    input_dir: Path
    start: int
    end: int
    label: str
    method: str
    config: Path
    semidense: str = "none"

    @property
    def output_csv(self) -> Path:
        return OUT_DIR / f"{self.dataset}_{self.window}_{self.label}.csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare AFRL cemetery frontend-only evidence for cross-dataset validation."
    )
    parser.add_argument("--force", action="store_true", help="Rerun existing frontend CSVs.")
    parser.add_argument("--skip-run", action="store_true", help="Only inspect/summarize existing outputs.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = [
        EvalCase(
            "afrl_fl",
            "080_130",
            ROOT / "datasets/afrl/samples/cemetery_fl_every5_800",
            80,
            130,
            "klt_adaptive_clahe",
            "klt",
            KLT_CONFIG,
        ),
        EvalCase(
            "afrl_fl",
            "080_130",
            ROOT / "datasets/afrl/samples/cemetery_fl_every5_800",
            80,
            130,
            "full_sp_lg_loftr",
            "hybrid_superpoint_lightglue",
            HYBRID_CONFIG,
            "loftr",
        ),
        EvalCase(
            "afrl_fr",
            "005_055",
            ROOT / "datasets/afrl/samples/cemetery_fr_every5_800",
            5,
            55,
            "klt_adaptive_clahe",
            "klt",
            KLT_CONFIG,
        ),
        EvalCase(
            "afrl_fr",
            "005_055",
            ROOT / "datasets/afrl/samples/cemetery_fr_every5_800",
            5,
            55,
            "full_sp_lg_loftr",
            "hybrid_superpoint_lightglue",
            HYBRID_CONFIG,
            "loftr",
        ),
    ]

    availability = inspect_availability()
    if not args.skip_run:
        for case in cases:
            run_case(case, force=args.force)
    rows = [summarize_case(case) for case in cases if case.output_csv.exists()]
    write_summary(availability, rows, OUT_DIR / "summary.md")
    write_metrics_csv(rows, OUT_DIR / "metrics_summary.csv")
    return 0


def inspect_availability() -> list[dict[str, str]]:
    roots = [
        ROOT / "datasets/afrl",
        ROOT / "datasets/full_downloads/afrl_hf",
        ROOT / "datasets/prepared_new",
    ]
    sequences = {
        "cemetery_fl": ("cemetery_fl", "afrl_cemetery_fl"),
        "cemetery_fr": ("cemetery_fr", "afrl_cemetery_fr"),
        "cave": ("cave",),
    }
    out = []
    for root in roots:
        for seq, needles in sequences.items():
            files = list(root.rglob("*")) if root.exists() else []
            matched = [p for p in files if any(n in str(p).lower() for n in needles)]
            images = [p for p in matched if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
            bags = [p for p in matched if p.suffix.lower() in {".bag", ".db3"} and ".parts" not in p.parts]
            calib = [
                p
                for p in matched
                if p.suffix.lower() in {".yaml", ".yml", ".json"}
                and re.search(r"calib|camchain|camera|imu", str(p), re.I)
            ]
            gt = [
                p
                for p in matched
                if p.suffix.lower() in {".txt", ".csv", ".tum", ".json"}
                and re.search(r"gt|ground|truth|colmap", str(p), re.I)
            ]
            out.append(
                {
                    "root": rel(root),
                    "sequence": seq,
                    "images": str(len(images)),
                    "image_hint": rel(parent_hint(images)),
                    "bag": rel(first_or_none(bags)),
                    "calib": rel(first_or_none(calib)),
                    "gt": rel(first_or_none(gt)),
                }
            )
    return out


def run_case(case: EvalCase, force: bool) -> None:
    if case.output_csv.exists() and not force and csv_complete(case):
        print(f"reuse {rel(case.output_csv)}")
        return
    cmd = [
        "python3",
        "-m",
        "uw_frontend.evaluation.run_frontend_eval",
        "--input",
        str(case.input_dir),
        "--output-csv",
        str(case.output_csv),
        "--method",
        case.method,
        "--config",
        str(case.config),
        "--preprocess",
        "adaptive_clahe",
        "--start-index",
        str(case.start),
        "--end-index",
        str(case.end),
        "--semidense-fallback-method",
        case.semidense,
    ]
    print("run " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def csv_complete(case: EvalCase) -> bool:
    try:
        with case.output_csv.open(newline="", encoding="utf-8") as handle:
            rows = sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return False
    return rows >= max(0, case.end - case.start + 1)


def summarize_case(case: EvalCase) -> dict[str, str]:
    with case.output_csv.open(newline="", encoding="utf-8") as handle:
        frame_rows = list(csv.DictReader(handle))
    row = {
        "dataset": case.dataset,
        "window": case.window,
        "method": case.label,
        "csv": rel(case.output_csv),
        "frames": str(len(frame_rows)),
    }
    for col, agg in [
        ("num_features", "mean"),
        ("grid_coverage", "median"),
        ("median_track_age", "median"),
        ("long_track_ratio", "median"),
        ("dropout_ratio", "mean"),
        ("fundamental_inlier_ratio", "median"),
        ("homography_inlier_ratio", "median"),
        ("median_epipolar_error", "median"),
        ("median_homography_error", "median"),
        ("runtime_ms", "median"),
        ("superpoint_lightglue_confirmed_tracks", "mean"),
        ("loftr_confirmed_tracks", "mean"),
    ]:
        values = numeric_values(frame_rows, col)
        row[f"{col}_{agg}"] = fmt(mean(values) if agg == "mean" else median(values))
    row["loftr_accepted_frames"] = str(
        sum("accepted_loftr_" in r.get("semidense_acceptance", "") for r in frame_rows)
    )
    row["loftr_accepted_tracks"] = str(
        sum(parse_accepted_loftr(r.get("semidense_acceptance", "")) for r in frame_rows)
    )
    return row


def write_metrics_csv(rows: list[dict[str, str]], path: Path) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(availability: list[dict[str, str]], rows: list[dict[str, str]], path: Path) -> None:
    pairs = compare_pairs(rows)
    lines = [
        "# AFRL v31 frontend evidence",
        "",
        "Frontend-only check for AFRL cemetery short windows. No VINS/ROS wrapper was launched.",
        "",
        "## Dataset availability",
        "",
        "| root | sequence | images | image hint | bag | calib | gt |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in availability:
        lines.append(
            f"| `{row['root']}` | `{row['sequence']}` | {row['images']} | `{row['image_hint']}` | "
            f"`{row['bag']}` | `{row['calib']}` | `{row['gt']}` |"
        )
    lines.extend(
        [
            "",
            "## Frontend metrics",
            "",
            "| dataset | window | method | frames | features mean | grid med | age med | dropout mean | F inlier med | epi err med | runtime med ms | LoFTR accepted | csv |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['dataset']}` | `{row['window']}` | `{row['method']}` | {row['frames']} | "
            f"{row['num_features_mean']} | {row['grid_coverage_median']} | {row['median_track_age_median']} | "
            f"{row['dropout_ratio_mean']} | {row['fundamental_inlier_ratio_median']} | "
            f"{row['median_epipolar_error_median']} | {row['runtime_ms_median']} | "
            f"{row['loftr_accepted_frames']}f/{row['loftr_accepted_tracks']}t | `{row['csv']}` |"
        )
    lines.extend(
        [
            "",
            "## KLT vs SP+LG+LoFTR deltas",
            "",
            "| dataset | window | delta grid | delta age | delta dropout | delta F inlier | delta epi err | delta runtime ms | decision |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for pair in pairs:
        lines.append(
            f"| `{pair['dataset']}` | `{pair['window']}` | {pair['delta_grid']} | {pair['delta_age']} | "
            f"{pair['delta_dropout']} | {pair['delta_f_inlier']} | {pair['delta_epi_err']} | "
            f"{pair['delta_runtime']} | {pair['decision']} |"
        )
    best = choose_vins_candidate(pairs)
    lines.extend(
        [
            "",
            "## VINS wrapper recommendation",
            "",
            best,
            "",
            "## Missing before cross-dataset VINS",
            "",
            "- `datasets/afrl/samples` has FL/FR image evidence only; no local cemetery FL/FR bag, calibration, or GT file was found there.",
            "- `datasets/prepared_new` currently has prepared FL images only; no prepared FR or cave image sequence was found.",
            "- `datasets/full_downloads/afrl_hf` currently exposes cave bag/calibration/Colmap GT, but not cemetery FL/FR assets in the local tree.",
            "- Before VINS wrapper work, confirm the AFRL image topic, IMU topic, camera-IMU calibration, and GT trajectory convention for the selected cemetery sequence.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 scripts/agent_afrl_v31_frontend.py",
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_pairs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key = {(r["dataset"], r["window"], r["method"]): r for r in rows}
    out = []
    for dataset, window in sorted({(r["dataset"], r["window"]) for r in rows}):
        klt = by_key.get((dataset, window, "klt_adaptive_clahe"))
        hybrid = by_key.get((dataset, window, "full_sp_lg_loftr"))
        if not klt or not hybrid:
            continue
        pair = {
            "dataset": dataset,
            "window": window,
            "delta_grid": delta(hybrid, klt, "grid_coverage_median"),
            "delta_age": delta(hybrid, klt, "median_track_age_median"),
            "delta_dropout": delta(hybrid, klt, "dropout_ratio_mean"),
            "delta_f_inlier": delta(hybrid, klt, "fundamental_inlier_ratio_median"),
            "delta_epi_err": delta(hybrid, klt, "median_epipolar_error_median"),
            "delta_runtime": delta(hybrid, klt, "runtime_ms_median"),
        }
        pair["decision"] = decision(pair)
        out.append(pair)
    return out


def choose_vins_candidate(pairs: list[dict[str, str]]) -> str:
    positives = [p for p in pairs if p["decision"].startswith("candidate")]
    if positives:
        best = sorted(positives, key=lambda p: (as_float(p["delta_grid"]), as_float(p["delta_age"])), reverse=True)[0]
        return (
            f"`{best['dataset']}` `{best['window']}` is the best next VINS-wrapper candidate: "
            "SP+LG+LoFTR improves frontend coverage/continuity without a large epipolar-error penalty."
        )
    return (
        "Do not promote SP+LG+LoFTR to the VINS wrapper from these short windows alone. "
        "Use KLT as the cemetery control and collect bag/calibration/GT first; revisit learned export after wrapper inputs are complete."
    )


def decision(pair: dict[str, str]) -> str:
    d_grid = as_float(pair["delta_grid"])
    d_age = as_float(pair["delta_age"])
    d_drop = as_float(pair["delta_dropout"])
    d_epi = as_float(pair["delta_epi_err"])
    if d_grid > 0.02 and d_age >= 0.0 and d_drop <= 0.02 and d_epi <= 0.01:
        return "candidate_positive"
    if d_grid >= -0.01 and d_drop <= 0.03 and d_epi <= 0.02:
        return "near_tie"
    return "KLT_control_preferred"


def numeric_values(rows: list[dict[str, str]], col: str) -> list[float]:
    values = []
    for row in rows:
        try:
            value = float(row.get(col, "nan"))
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def delta(new: dict[str, str], old: dict[str, str], key: str) -> str:
    return fmt(as_float(new[key]) - as_float(old[key]))


def as_float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return float("nan")


def fmt(value: float) -> str:
    if not math.isfinite(value):
        return "nan"
    return f"{value:.4f}"


def parse_accepted_loftr(text: str) -> int:
    match = re.search(r"accepted_loftr_(\d+)", text or "")
    return int(match.group(1)) if match else 0


def first_or_none(paths: list[Path]) -> Path | None:
    return sorted(paths)[0] if paths else None


def parent_hint(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return sorted(paths)[0].parent


def rel(path: Path | None) -> str:
    if path is None:
        return "missing"
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
