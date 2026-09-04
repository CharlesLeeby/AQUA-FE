#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.evaluation.run_frontend_eval import load_config

OUT_DIR = ROOT / "logs" / "agent_three_layer_validation"

TASK_A_CONFIG = ROOT / "uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml"
FALLBACK_CONFIGS = [
    ROOT / "uw_frontend/configs/three_layer_frontend.yaml",
    ROOT / "uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml",
    ROOT / "uw_frontend/configs/paper_normal_safe_frontend.yaml",
    ROOT / "uw_frontend/configs/backend_strict_frontend.yaml",
]
KLT_CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"


@dataclass(frozen=True)
class WindowSpec:
    key: str
    dataset: str
    scene: str
    input_path: Path
    image_prefix: str | None
    start: int
    end: int
    expectation: str


@dataclass(frozen=True)
class MethodSpec:
    key: str
    display: str
    role: str
    method: str
    config_path: Path
    semidense: str = "none"


WINDOWS = [
    WindowSpec(
        key="h07_normal_0_50",
        dataset="AQUALOC-H07",
        scene="normal",
        input_path=ROOT / "datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz",
        image_prefix="harbor_images_sequence_07",
        start=0,
        end=50,
        expectation="no_harm",
    ),
    WindowSpec(
        key="h07_lowtexture_1740_1820",
        dataset="AQUALOC-H07",
        scene="lowtexture_extreme",
        input_path=ROOT / "datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz",
        image_prefix="harbor_images_sequence_07",
        start=1740,
        end=1820,
        expectation="stress_honest",
    ),
    WindowSpec(
        key="h06_lowcontrast_2280_2330",
        dataset="AQUALOC-H06",
        scene="lowcontrast",
        input_path=ROOT / "datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz",
        image_prefix="harbor_images_sequence_06",
        start=2280,
        end=2330,
        expectation="no_harm",
    ),
    WindowSpec(
        key="a06_planar_2210_2260",
        dataset="AQUALOC-A06",
        scene="planar_lowtexture",
        input_path=ROOT / "datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz",
        image_prefix="images_sequence_6",
        start=2210,
        end=2260,
        expectation="planar_positive",
    ),
    WindowSpec(
        key="afrl_fl_degraded_240_320",
        dataset="AFRL-FL",
        scene="degraded",
        input_path=ROOT / "datasets/afrl/samples/cemetery_fl_every5_800",
        image_prefix=None,
        start=240,
        end=320,
        expectation="degraded_no_harm",
    ),
]

SOURCE_GROUPS = {
    "sp_lg": [
        "superpoint_lightglue_tracks",
        "superpoint_lightglue_recovery_tracks",
        "superpoint_lightglue_init_tracks",
        "superpoint_lightglue_confirmed_tracks",
    ],
    "xfeat": [
        "xfeat_tracks",
        "xfeat_recovery_tracks",
        "xfeat_init_tracks",
        "xfeat_confirmed_tracks",
        "xfeat_star_tracks",
        "xfeat_star_recovery_tracks",
        "xfeat_star_init_tracks",
        "xfeat_star_confirmed_tracks",
    ],
    "loftr": [
        "loftr_tracks",
        "loftr_recovery_tracks",
        "loftr_init_tracks",
        "loftr_confirmed_tracks",
    ],
}

SUMMARY_COLUMNS = [
    "window",
    "dataset",
    "scene",
    "method",
    "role",
    "run_status",
    "frames",
    "features_mean",
    "grid_coverage_median",
    "mean_age",
    "median_age",
    "long_track_ratio",
    "dropout_mean",
    "dropout_ratio_mean",
    "dropout_ratio_median",
    "f_inlier_median",
    "h_inlier_median",
    "epipolar_median",
    "homography_residual_median",
    "runtime_ms_median",
    "runtime_ms_mean",
    "sp_lg_mean",
    "sp_lg_sum",
    "xfeat_mean",
    "xfeat_sum",
    "loftr_mean",
    "loftr_sum",
    "loftr_accepted_frames",
    "loftr_accepted_tracks",
    "tracker_modes",
    "semidense_events",
    "csv",
    "log",
]

NO_HARM_THRESHOLDS = {
    "grid_coverage_median": ("ge", -0.010, "grid"),
    "median_age": ("ge", -1.000, "median age"),
    "long_track_ratio": ("ge", -0.010, "long-track"),
    "dropout_ratio_mean": ("le", 0.010, "dropout ratio"),
    "f_inlier_median": ("ge", -0.020, "F inlier"),
    "h_inlier_median": ("ge", -0.020, "H inlier"),
    "epipolar_median": ("le", 0.010, "epipolar"),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and summarize a compact validation matrix for the three-layer frontend policy."
    )
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--force", action="store_true", help="Rerun existing CSVs.")
    parser.add_argument("--summary-only", action="store_true", help="Only summarize existing owned CSVs.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any subprocess fails.")
    parser.add_argument("--include-xfeat", action="store_true", help="Also run a three-layer XFeat variant.")
    parser.add_argument(
        "--windows",
        nargs="*",
        default=None,
        help="Optional subset of window keys. Default: compact five-window matrix.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path, config_status = choose_candidate_config()
    methods = build_methods(config_path, include_xfeat=args.include_xfeat)
    windows = select_windows(args.windows)

    run_records: list[dict[str, Any]] = []
    if not args.summary_only:
        run_records = run_matrix(windows, methods, output_dir, force=args.force, strict=args.strict)

    summary = summarize_matrix(windows, methods, output_dir, run_records)
    summary_csv = output_dir / "three_layer_validation_summary.csv"
    summary_md = output_dir / "three_layer_validation_summary.md"
    summary.to_csv(summary_csv, index=False)
    summary_md.write_text(markdown_table(summary, SUMMARY_COLUMNS[:-2]) + "\n", encoding="utf-8")

    decisions = build_decisions(summary)
    decisions_csv = output_dir / "three_layer_validation_decisions.csv"
    decisions.to_csv(decisions_csv, index=False)

    report = render_report(
        summary=summary,
        decisions=decisions,
        output_dir=output_dir,
        config_path=config_path,
        config_status=config_status,
        methods=methods,
        windows=windows,
    )
    report_path = output_dir / "three_layer_validation_report.md"
    report_path.write_text(report, encoding="utf-8")

    print(markdown_table(decisions, list(decisions.columns)))
    print(f"wrote {summary_csv}")
    print(f"wrote {summary_md}")
    print(f"wrote {decisions_csv}")
    print(f"wrote {report_path}")
    return 0


def choose_candidate_config() -> tuple[Path, str]:
    if TASK_A_CONFIG.exists():
        return TASK_A_CONFIG, "ready"
    for path in FALLBACK_CONFIGS:
        if path.exists():
            return path, "placeholder"
    raise FileNotFoundError("No Task A or fallback frontend config found.")


def build_methods(config_path: Path, include_xfeat: bool = False) -> list[MethodSpec]:
    methods = [
        MethodSpec(
            key="klt_adaptive_clahe",
            display="KLT adaptive CLAHE",
            role="baseline",
            method="klt",
            config_path=KLT_CONFIG,
        ),
        MethodSpec(
            key="three_layer_source_aware_sp_lg_loftr",
            display="Three-layer SP+LG with LoFTR fallback request",
            role="candidate",
            method="hybrid_superpoint_lightglue",
            config_path=config_path,
            semidense="loftr",
        ),
    ]
    if include_xfeat:
        methods.append(
            MethodSpec(
                key="three_layer_source_aware_xfeat_loftr",
                display="Three-layer XFeat with LoFTR fallback request",
                role="candidate",
                method="hybrid_xfeat",
                config_path=config_path,
                semidense="loftr",
            )
        )
    return methods


def select_windows(keys: list[str] | None) -> list[WindowSpec]:
    if not keys:
        return WINDOWS
    by_key = {window.key: window for window in WINDOWS}
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise ValueError(f"Unknown window key(s): {', '.join(missing)}")
    return [by_key[key] for key in keys]


def run_matrix(
    windows: list[WindowSpec],
    methods: list[MethodSpec],
    output_dir: Path,
    force: bool,
    strict: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for window in windows:
        if not window.input_path.exists():
            records.extend(
                {
                    "window": window.key,
                    "method": method.key,
                    "status": "SKIP_MISSING_INPUT",
                    "message": str(window.input_path),
                }
                for method in methods
            )
            continue
        for method in methods:
            csv_path = csv_for(output_dir, window, method)
            log_path = log_for(output_dir, window, method)
            if csv_path.exists() and not force:
                records.append(
                    {
                        "window": window.key,
                        "method": method.key,
                        "status": "SKIP_EXISTING",
                        "csv": str(csv_path),
                        "log": str(log_path),
                    }
                )
                continue
            status = run_one(window, method, csv_path, log_path)
            records.append(
                {
                    "window": window.key,
                    "method": method.key,
                    "status": status,
                    "csv": str(csv_path),
                    "log": str(log_path),
                }
            )
            if strict and status != "OK":
                raise RuntimeError(f"{window.key}/{method.key} failed; see {log_path}")
    return records


def run_one(window: WindowSpec, method: MethodSpec, csv_path: Path, log_path: Path) -> str:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "python3",
        "-m",
        "uw_frontend.evaluation.run_frontend_eval",
        "--input",
        str(window.input_path),
        "--output-csv",
        str(csv_path),
        "--method",
        method.method,
        "--config",
        str(method.config_path),
        "--preprocess",
        "adaptive_clahe",
        "--start-index",
        str(window.start),
        "--end-index",
        str(window.end),
    ]
    if window.image_prefix:
        command += ["--image-prefix", window.image_prefix]
    if method.semidense != "none":
        command += ["--semidense-fallback-method", method.semidense]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    return "OK" if result.returncode == 0 and csv_path.exists() else f"FAILED_{result.returncode}"


def summarize_matrix(
    windows: list[WindowSpec],
    methods: list[MethodSpec],
    output_dir: Path,
    run_records: list[dict[str, Any]],
) -> pd.DataFrame:
    run_status = {
        (record.get("window"), record.get("method")): record.get("status", "UNKNOWN")
        for record in run_records
    }
    rows: list[dict[str, Any]] = []
    for window in windows:
        for method in methods:
            csv_path = csv_for(output_dir, window, method)
            log_path = log_for(output_dir, window, method)
            status = run_status.get((window.key, method.key))
            if csv_path.exists() and csv_path.stat().st_size > 0:
                try:
                    row = summarize_csv(csv_path)
                    row["run_status"] = "OK" if status in {None, "SKIP_EXISTING", "OK"} else status
                except (EmptyDataError, pd.errors.ParserError):
                    row = empty_summary()
                    row["run_status"] = infer_failed_status(log_path, fallback=status or "FAILED_UNREADABLE_CSV")
            elif csv_path.exists():
                row = empty_summary()
                row["run_status"] = infer_failed_status(log_path, fallback=status or "FAILED_EMPTY_CSV")
            else:
                row = empty_summary()
                row["run_status"] = status or ("PENDING_MISSING_INPUT" if not window.input_path.exists() else "PENDING")
            row.update(
                {
                    "window": window.key,
                    "dataset": window.dataset,
                    "scene": window.scene,
                    "method": method.key,
                    "role": method.role,
                    "csv": display_path(csv_path) if csv_path.exists() else "",
                    "log": display_path(log_path) if log_path.exists() else "",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)[SUMMARY_COLUMNS]


def infer_failed_status(log_path: Path, fallback: str) -> str:
    if not log_path.exists():
        return fallback
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "AttributeError" in text:
        return "FAILED_ATTRIBUTEERROR"
    if "Traceback" in text:
        return "FAILED_TRACEBACK"
    return fallback


def summarize_csv(csv_path: Path) -> dict[str, Any]:
    df = pd.read_csv(csv_path)
    semidense = series_text(df, "semidense_acceptance")
    loftr_accepted = semidense.str.startswith("accepted_loftr_")
    return {
        "frames": len(df),
        "features_mean": mean(df, "num_features"),
        "grid_coverage_median": median(df, "grid_coverage"),
        "mean_age": mean(df, "mean_track_age"),
        "median_age": median(df, "median_track_age"),
        "long_track_ratio": mean(df, "long_track_ratio"),
        "dropout_mean": mean(df, "dropped_features"),
        "dropout_ratio_mean": mean(df, "dropout_ratio"),
        "dropout_ratio_median": median(df, "dropout_ratio"),
        "f_inlier_median": median(df, "fundamental_inlier_ratio"),
        "h_inlier_median": median(df, "homography_inlier_ratio"),
        "epipolar_median": median(df, "median_epipolar_error"),
        "homography_residual_median": median(df, "median_homography_error"),
        "runtime_ms_median": median(df, "runtime_ms"),
        "runtime_ms_mean": mean(df, "runtime_ms"),
        "sp_lg_mean": source_mean(df, SOURCE_GROUPS["sp_lg"]),
        "sp_lg_sum": source_sum(df, SOURCE_GROUPS["sp_lg"]),
        "xfeat_mean": source_mean(df, SOURCE_GROUPS["xfeat"]),
        "xfeat_sum": source_sum(df, SOURCE_GROUPS["xfeat"]),
        "loftr_mean": source_mean(df, SOURCE_GROUPS["loftr"]),
        "loftr_sum": source_sum(df, SOURCE_GROUPS["loftr"]),
        "loftr_accepted_frames": int(loftr_accepted.sum()) if len(loftr_accepted) else 0,
        "loftr_accepted_tracks": parse_accepted_loftr_tracks(semidense[loftr_accepted]),
        "tracker_modes": counts(df, "tracker_mode"),
        "semidense_events": counts(df, "semidense_acceptance"),
    }


def empty_summary() -> dict[str, Any]:
    return {
        "frames": 0,
        "features_mean": math.nan,
        "grid_coverage_median": math.nan,
        "mean_age": math.nan,
        "median_age": math.nan,
        "long_track_ratio": math.nan,
        "dropout_mean": math.nan,
        "dropout_ratio_mean": math.nan,
        "dropout_ratio_median": math.nan,
        "f_inlier_median": math.nan,
        "h_inlier_median": math.nan,
        "epipolar_median": math.nan,
        "homography_residual_median": math.nan,
        "runtime_ms_median": math.nan,
        "runtime_ms_mean": math.nan,
        "sp_lg_mean": math.nan,
        "sp_lg_sum": math.nan,
        "xfeat_mean": math.nan,
        "xfeat_sum": math.nan,
        "loftr_mean": math.nan,
        "loftr_sum": math.nan,
        "loftr_accepted_frames": 0,
        "loftr_accepted_tracks": 0,
        "tracker_modes": "",
        "semidense_events": "",
    }


def build_decisions(summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window, group in summary.groupby("window", sort=False):
        baseline_rows = group[group["method"] == "klt_adaptive_clahe"]
        if baseline_rows.empty:
            continue
        baseline = baseline_rows.iloc[0]
        for _, candidate in group[group["role"] == "candidate"].iterrows():
            rows.append(decide_window(candidate, baseline))
    return pd.DataFrame(rows)


def decide_window(candidate: pd.Series, baseline: pd.Series) -> dict[str, Any]:
    deltas = {
        "delta_grid": delta(candidate, baseline, "grid_coverage_median"),
        "delta_median_age": delta(candidate, baseline, "median_age"),
        "delta_long_track": delta(candidate, baseline, "long_track_ratio"),
        "delta_dropout_ratio": delta(candidate, baseline, "dropout_ratio_mean"),
        "delta_f_inlier": delta(candidate, baseline, "f_inlier_median"),
        "delta_h_inlier": delta(candidate, baseline, "h_inlier_median"),
        "delta_epipolar": delta(candidate, baseline, "epipolar_median"),
        "delta_runtime_ms": delta(candidate, baseline, "runtime_ms_median"),
    }
    expectation = expectation_for_window(str(candidate["window"]))
    base = {
        "window": candidate["window"],
        "scene": candidate["scene"],
        "candidate": candidate["method"],
        "frames": int(candidate["frames"]) if pd.notna(candidate["frames"]) else 0,
        "status": "PENDING",
        "decision": "",
        "loftr_accepted_tracks": int(candidate.get("loftr_accepted_tracks", 0) or 0),
        **deltas,
    }
    if candidate["run_status"] != "OK" or baseline["run_status"] != "OK":
        base["decision"] = f"candidate={candidate['run_status']}; baseline={baseline['run_status']}"
        return base

    no_harm_failures = no_harm_failures_for(candidate, baseline)
    if expectation == "no_harm":
        base["status"] = "PASS" if not no_harm_failures else "FAIL"
        base["decision"] = "near-tie/no-harm" if not no_harm_failures else "; ".join(no_harm_failures)
        return base

    if expectation == "planar_positive":
        positive = (
            deltas["delta_grid"] >= 0.010
            or deltas["delta_median_age"] >= 1.0
            or deltas["delta_long_track"] >= 0.010
            or deltas["delta_dropout_ratio"] <= -0.010
        )
        epi_ok = deltas["delta_epipolar"] <= 0.010
        loftr_active = int(candidate.get("loftr_accepted_tracks", 0) or 0) > 0 or float(candidate.get("loftr_sum", 0) or 0) > 0
        failures = []
        if not positive:
            failures.append("no coverage/continuity gain")
        if not epi_ok:
            failures.append(f"epipolar regression {deltas['delta_epipolar']:+.4f}")
        if not loftr_active:
            failures.append("LoFTR inactive")
        base["status"] = "PASS" if not failures else "FAIL"
        base["decision"] = "planar positive without epipolar regression" if not failures else "; ".join(failures)
        return base

    if expectation == "stress_honest":
        severe_regression = (
            deltas["delta_epipolar"] > 0.020
            or deltas["delta_dropout_ratio"] > 0.030
            or deltas["delta_grid"] < -0.030
        )
        improved = (
            deltas["delta_grid"] >= 0.010
            or deltas["delta_median_age"] >= 1.0
            or deltas["delta_dropout_ratio"] <= -0.010
        )
        if severe_regression:
            base["status"] = "FAIL"
            base["decision"] = "stress window regressed: " + "; ".join(no_harm_failures or ["see deltas"])
        elif improved:
            base["status"] = "PASS"
            base["decision"] = "stress window improved or tied"
        else:
            base["status"] = "REPORTED_UNSOLVED"
            base["decision"] = "reported honestly; no clear improvement"
        return base

    if expectation == "degraded_no_harm":
        base["status"] = "PASS" if not no_harm_failures else "FAIL"
        base["decision"] = "degraded no-harm/tie" if not no_harm_failures else "; ".join(no_harm_failures)
        return base

    base["status"] = "PENDING"
    base["decision"] = f"unknown expectation {expectation}"
    return base


def no_harm_failures_for(candidate: pd.Series, baseline: pd.Series) -> list[str]:
    failures: list[str] = []
    for metric, (direction, tolerance, label) in NO_HARM_THRESHOLDS.items():
        value = delta(candidate, baseline, metric)
        if not math.isfinite(value):
            failures.append(f"{label} missing")
            continue
        ok = value >= tolerance if direction == "ge" else value <= tolerance
        if not ok:
            failures.append(f"{label} {value:+.4f}")
    return failures


def render_report(
    summary: pd.DataFrame,
    decisions: pd.DataFrame,
    output_dir: Path,
    config_path: Path,
    config_status: str,
    methods: list[MethodSpec],
    windows: list[WindowSpec],
) -> str:
    cfg = load_config(config_path)
    hybrid = cfg.get("hybrid", {})
    effective_notes = [
        f"config_status: {config_status}",
        f"config: {display_path(config_path)}",
        f"candidate_method: {', '.join(method.method for method in methods if method.role == 'candidate')}",
        f"semidense_fallback_requested: {', '.join(method.semidense for method in methods if method.role == 'candidate')}",
        f"enable_semidense_fallback_initialization: {hybrid.get('enable_semidense_fallback_initialization', False)}",
        f"enable_learned_initialization: {hybrid.get('enable_learned_initialization', False)}",
        f"learned_init_requires_klt_confirmation: {hybrid.get('learned_init_requires_klt_confirmation', False)}",
        f"generated_at: {datetime.now().isoformat(timespec='seconds')}",
    ]

    compact_cols = [
        "window",
        "scene",
        "candidate",
        "status",
        "decision",
        "loftr_accepted_tracks",
        "delta_grid",
        "delta_median_age",
        "delta_long_track",
        "delta_dropout_ratio",
        "delta_epipolar",
        "delta_runtime_ms",
    ]
    method_cols = [
        "window",
        "method",
        "run_status",
        "frames",
        "grid_coverage_median",
        "median_age",
        "long_track_ratio",
        "dropout_ratio_mean",
        "f_inlier_median",
        "h_inlier_median",
        "epipolar_median",
        "runtime_ms_median",
        "sp_lg_mean",
        "xfeat_mean",
        "loftr_mean",
        "loftr_accepted_tracks",
    ]

    pending = summary[summary["run_status"].astype(str).str.startswith("PENDING")]
    failures = decisions[decisions["status"].isin(["FAIL", "PENDING"])] if not decisions.empty else pd.DataFrame()
    task_config_note = (
        "Task A config was found and used directly."
        if config_status == "ready"
        else "Task A config was not found; this report used the closest existing placeholder config."
    )
    if not bool(hybrid.get("enable_semidense_fallback_initialization", False)):
        task_config_note += (
            " The effective config leaves semidense fallback initialization disabled, "
            "so a LoFTR fallback request may remain inactive."
        )

    lines = [
        "# Three-Layer Frontend Validation",
        "",
        task_config_note,
        "",
        "## Effective Setup",
        "",
        "\n".join(f"- `{note}`" for note in effective_notes),
        "",
        "## Decision Summary",
        "",
        markdown_table(decisions, compact_cols),
        "",
        "## Metric Summary",
        "",
        markdown_table(summary, method_cols),
        "",
        "## Window Plan",
        "",
        markdown_table(pd.DataFrame([window.__dict__ for window in windows]), ["key", "dataset", "scene", "start", "end", "expectation"]),
        "",
        "## Notes",
        "",
        "- Normal and low-contrast windows are judged by near-tie/no-harm thresholds against KLT adaptive CLAHE.",
        "- The A06 planar window requires a coverage/continuity gain, no epipolar regression, and active LoFTR evidence.",
        "- H07 low-texture extreme is reported as solved only if it improves/ties without geometry regression; otherwise it is marked honestly as unresolved.",
        f"- Raw CSVs and subprocess logs are under `{display_path(output_dir)}`.",
    ]
    if not pending.empty:
        lines.extend(["", "## Pending Runs", "", markdown_table(pending, ["window", "method", "run_status", "log"])])
    if not failures.empty:
        lines.extend(["", "## Failed Or Pending Decisions", "", markdown_table(failures, compact_cols)])
    return "\n".join(lines) + "\n"


def expectation_for_window(window_key: str) -> str:
    for window in WINDOWS:
        if window.key == window_key:
            return window.expectation
    return "unknown"


def csv_for(output_dir: Path, window: WindowSpec, method: MethodSpec) -> Path:
    return output_dir / f"{window.key}_{method.key}.csv"


def log_for(output_dir: Path, window: WindowSpec, method: MethodSpec) -> Path:
    return output_dir / f"{window.key}_{method.key}.log"


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def mean(df: pd.DataFrame, column: str) -> float:
    if column not in df:
        return math.nan
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else math.nan


def median(df: pd.DataFrame, column: str) -> float:
    if column not in df:
        return math.nan
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.median()) if not values.empty else math.nan


def source_frame_totals(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    total = pd.Series([0.0] * len(df), index=df.index)
    for column in columns:
        if column in df:
            total = total + pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return total


def source_mean(df: pd.DataFrame, columns: list[str]) -> float:
    if df.empty:
        return math.nan
    return float(source_frame_totals(df, columns).mean())


def source_sum(df: pd.DataFrame, columns: list[str]) -> float:
    if df.empty:
        return math.nan
    return float(source_frame_totals(df, columns).sum())


def series_text(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df:
        return pd.Series([], dtype=str)
    return df[column].fillna("").astype(str)


def parse_accepted_loftr_tracks(values: pd.Series) -> int:
    total = 0
    for value in values:
        match = re.search(r"accepted_loftr_(\d+)", str(value))
        if match:
            total += int(match.group(1))
    return total


def counts(df: pd.DataFrame, column: str, limit: int = 8) -> str:
    if column not in df:
        return ""
    series = df[column].fillna("").astype(str)
    series = series[series != ""]
    if series.empty:
        return ""
    parts = [f"{key}:{value}" for key, value in series.value_counts().head(limit).items()]
    return ";".join(parts)


def delta(candidate: pd.Series, baseline: pd.Series, column: str) -> float:
    try:
        return float(candidate[column]) - float(baseline[column])
    except (KeyError, TypeError, ValueError):
        return math.nan


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_No rows._"
    existing = [column for column in columns if column in df.columns]
    rows = []
    for _, row in df[existing].iterrows():
        rows.append([format_value(row[column]) for column in existing])
    widths = [len(column) for column in existing]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    header = "| " + " | ".join(column.ljust(width) for column, width in zip(existing, widths)) + " |"
    sep = "| " + " | ".join("-" * width for width in widths) + " |"
    body = ["| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def format_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.4f}" if math.isfinite(value) else ""
    text = str(value)
    return text.replace("\n", " ").replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
