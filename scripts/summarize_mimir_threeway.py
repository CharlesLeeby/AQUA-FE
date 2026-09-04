#!/usr/bin/env python3
"""Build the same-window MIMIR comparison for KLT, original VINS, and AQUA-FE."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Dict, List


RECEIPT_FIELDS = (
    "matched",
    "se3_ape_rmse_m",
    "se3_ape_median_m",
    "rpe_trans_rmse_m",
    "rpe_trans_median_m",
    "output_coverage_ratio",
    "first_output_delay_s",
    "init_success",
    "tracking_lost_count_proxy",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paired-csv", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--ours-prefix", default="mimir_threeway_v1")
    parser.add_argument("--frontend-evidence", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    return parser.parse_args()


def parse_kv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def pose_count(run_dir: Path) -> int:
    path = run_dir / "vins_output" / "vio.csv"
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(bool(line.strip()) for line in handle)


def metrics(run_dir: Path) -> Dict[str, object]:
    receipt = parse_kv(run_dir / "ape.txt")
    poses = pose_count(run_dir)
    result: Dict[str, object] = {
        "run_dir": str(run_dir),
        "has_trajectory": int(poses > 0),
        "pose_count": poses,
    }
    for key in RECEIPT_FIELDS:
        result[key] = receipt.get(key, "")
    return result


def finite_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def fmt(value: object, digits: int = 3) -> str:
    number = finite_float(value)
    return f"{number:.{digits}f}" if math.isfinite(number) else "--"


def stem_from_prior(row: Dict[str, str]) -> str:
    # The prior run directory already contains the exact canonical window stem.
    name = Path(row["klt_run_dir"]).name
    prefix = "mimir_klt_vs_original_v1_"
    suffix = "_klt_vins_seed0"
    if not (name.startswith(prefix) and name.endswith(suffix)):
        raise ValueError(f"unexpected KLT run name: {name}")
    return name[len(prefix) : -len(suffix)]


def load_frontend(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["run"]: row for row in csv.DictReader(handle)}


def build_rows(
    prior_rows: List[Dict[str, str]],
    run_root: Path,
    ours_prefix: str,
    frontend: Dict[str, Dict[str, str]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for prior in prior_rows:
        stem = stem_from_prior(prior)
        ours_dir = run_root / f"{ours_prefix}_{stem}_ours_vins_seed0"
        export_name = f"{ours_prefix}_{stem}_ours_export"
        export = frontend.get(export_name, {})
        ours = metrics(ours_dir)
        row: Dict[str, object] = dict(prior)
        for key, value in ours.items():
            row[f"ours_{key}"] = value
        row.update(
            {
                "ours_export_run_dir": str(run_root / export_name),
                "ours_feature_frames": export.get("feature_frames", ""),
                "ours_published_feature_observations": export.get(
                    "published_feature_observations", ""
                ),
                "ours_published_learned_observations": export.get(
                    "published_learned_observations", ""
                ),
                "ours_published_loftr_observations": export.get(
                    "published_loftr_observations", ""
                ),
                "ours_source_audit_status": export.get(
                    "published_feature_bag_audit_status", ""
                ),
                "ours_exported_features_median": export.get(
                    "exported_features_median", ""
                ),
                "ours_classical_grid_coverage_median": export.get(
                    "classical_grid_coverage_median", ""
                ),
            }
        )
        passed = [
            arm
            for arm in ("klt", "original", "ours")
            if str(row.get(f"{arm}_init_success", "")) == "1"
        ]
        row["strict_pass_arms"] = "+".join(passed) if passed else "none"
        for baseline in ("klt", "original"):
            both_pass = baseline in passed and "ours" in passed
            ours_ape = finite_float(row.get("ours_se3_ape_rmse_m"))
            baseline_ape = finite_float(row.get(f"{baseline}_se3_ape_rmse_m"))
            row[f"fair_ape_ours_minus_{baseline}_m"] = (
                ours_ape - baseline_ape
                if both_pass and math.isfinite(ours_ape) and math.isfinite(baseline_ape)
                else ""
            )
        rows.append(row)
    return rows


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: List[Dict[str, object]]) -> None:
    totals = {}
    for arm in ("klt", "original", "ours"):
        totals[arm] = {
            "trajectory": sum(int(row[f"{arm}_has_trajectory"]) for row in rows),
            "pass": sum(str(row.get(f"{arm}_init_success", "")) == "1" for row in rows),
        }
    shared_ours_klt = sum(
        str(row.get("ours_init_success", "")) == "1"
        and str(row.get("klt_init_success", "")) == "1"
        for row in rows
    )
    shared_ours_original = sum(
        str(row.get("ours_init_success", "")) == "1"
        and str(row.get("original_init_success", "")) == "1"
        for row in rows
    )
    observations = sum(
        int(finite_float(row["ours_published_feature_observations"]))
        for row in rows
        if math.isfinite(finite_float(row["ours_published_feature_observations"]))
    )
    learned = sum(
        int(finite_float(row["ours_published_learned_observations"]))
        for row in rows
        if math.isfinite(finite_float(row["ours_published_learned_observations"]))
    )
    loftr = sum(
        int(finite_float(row["ours_published_loftr_observations"]))
        for row in rows
        if math.isfinite(finite_float(row["ours_published_loftr_observations"]))
    )
    learned_windows = sum(finite_float(row["ours_published_learned_observations"]) > 0 for row in rows)
    loftr_windows = sum(finite_float(row["ours_published_loftr_observations"]) > 0 for row in rows)
    audited = sum(row["ours_source_audit_status"] == "source_channels_audited" for row in rows)
    lines = [
        "# MIMIR-UW three-way frontend comparison",
        "",
        "All arms use the same nine selected low-texture 45 s raw windows, timestamps,",
        "calibration, test VINS tree, and `VINS_INITIAL_RANSAC_SEED=0`.",
        "AQUA-FE is the final `proposed_safe` profile: full KLT mirror backbone plus",
        "strictly gated SuperPoint-LightGlue/LoFTR sidecars.",
        "",
        "## Aggregate result",
        "",
        "| Arm | Any trajectory | Strict initialization gate |",
        "|---|---:|---:|",
        f"| Pure KLT external features | {totals['klt']['trajectory']}/9 | {totals['klt']['pass']}/9 |",
        f"| Original VINS image tracker | {totals['original']['trajectory']}/9 | {totals['original']['pass']}/9 |",
        f"| AQUA-FE `proposed_safe` | {totals['ours']['trajectory']}/9 | {totals['ours']['pass']}/9 |",
        "",
        "The strict gate requires at least 10 matched poses, first output within 15 s,",
        "and at least 50% duration coverage.",
        f"AQUA-FE and KLT both pass in {shared_ours_klt}/9 windows; AQUA-FE and original VINS both pass in {shared_ours_original}/9.",
        "Only those shared-pass windows support a fair paired APE/RPE comparison.",
        "",
        "## Per-window receipts",
        "",
        "| Window | KLT poses/gate; APE/RPE | Original poses/gate; APE/RPE | AQUA-FE poses/gate; APE/RPE | Pass arms |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        window = f"`{row['sequence']}` {row['window_start_s']}--{row['window_end_s']} s"
        cells = []
        for arm in ("klt", "original", "ours"):
            gate = row.get(f"{arm}_init_success", "") or "--"
            cells.append(
                f"{row[f'{arm}_pose_count']}/{gate}; "
                f"{fmt(row.get(f'{arm}_se3_ape_rmse_m'))}/{fmt(row.get(f'{arm}_rpe_trans_rmse_m'))}"
            )
        lines.append(
            f"| {window} | {cells[0]} | {cells[1]} | {cells[2]} | `{row['strict_pass_arms']}` |"
        )
    ratio = 100.0 * learned / observations if observations else 0.0
    if learned > 0:
        source_interpretation = (
            "This verifies that learned sidecars were actually present in the evaluated "
            "safe-system output rather than inferred from the profile label."
        )
    else:
        source_interpretation = (
            "No learned sidecar survived the safe export gates in these windows; the "
            "evaluated bags are therefore classical mirror-backbone outputs of the full "
            "profile, not evidence of learned-sidecar contribution."
        )
    lines.extend(
        [
            "",
            "## AQUA-FE source audit",
            "",
            f"All {audited}/9 feature bags are source-channel auditable.",
            f"Across them AQUA-FE published {observations} observations, including {learned} learned observations ({ratio:.2f}%) in {learned_windows}/9 windows and {loftr} LoFTR observations in {loftr_windows}/9 windows.",
            source_interpretation,
            "",
            "## Interpretation guardrails",
            "",
            "A small APE from a short or late partial trajectory is not counted as a win.",
            "Initialization and coverage are the primary endpoints; APE/RPE are compared only when both relevant arms pass the strict gate.",
            "MIMIR monocular-inertial scale can remain poorly conditioned, so large absolute APE values are retained rather than hidden.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    with args.paired_csv.open(newline="", encoding="utf-8") as handle:
        prior_rows = list(csv.DictReader(handle))
    if len(prior_rows) != 9:
        raise SystemExit(f"expected 9 prior rows, got {len(prior_rows)}")
    frontend = load_frontend(args.frontend_evidence)
    rows = build_rows(prior_rows, args.run_root, args.ours_prefix, frontend)
    write_csv(args.output_csv, rows)
    write_markdown(args.output_md, rows)
    print(f"wrote {args.output_csv}")
    print(f"wrote {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
