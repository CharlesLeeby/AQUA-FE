#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

WINDOWS: list[dict[str, Any]] = [
    {
        "dataset": "aqualoc_h07_normal_mid",
        "start": 0,
        "end": 100,
        "evidence": "existing_inactive_gate",
        "baseline_dir": ROOT / "logs/paper_texture_breadth",
        "baseline_prefix": "aqualoc_h07_normal_mid_0_100",
    },
    {
        "dataset": "aqualoc_h07_lowtex_extreme",
        "start": 1740,
        "end": 1820,
        "evidence": "fresh_tuned_probe",
        "baseline_dir": ROOT / "logs/paper_texture_breadth",
        "baseline_prefix": "aqualoc_h07_lowtex_extreme_1740_1820",
    },
    {
        "dataset": "aqualoc_h06_lowcontrast",
        "start": 2360,
        "end": 2440,
        "evidence": "existing_inactive_gate",
        "baseline_dir": ROOT / "logs/paper_texture_breadth",
        "baseline_prefix": "aqualoc_h06_lowcontrast_2360_2440",
    },
    {
        "dataset": "afrl_fl_degraded_extreme",
        "start": 240,
        "end": 320,
        "evidence": "fresh_tuned_probe",
        "baseline_dir": ROOT / "logs/paper_texture_breadth",
        "baseline_prefix": "afrl_fl_degraded_extreme_240_320",
    },
    {
        "dataset": "afrl_fr_long_005_410",
        "start": 5,
        "end": 410,
        "evidence": "existing_baseline_only",
        "baseline_dir": ROOT / "logs/multidataset",
        "baseline_prefix": "afrl_cemetery_fr_005_410",
        "klt_override": ROOT / "logs/multidataset/afrl_cemetery_fr_005_410_klt.csv",
        "reference_loftr": ROOT / "logs/opt_eval/long_window_v2/afrl_fr_loftr_005_410.csv",
        "reference_sp_lg": ROOT / "logs/opt_eval/long_window_v2/afrl_fr_superpoint_lightglue_005_410.csv",
    },
]

METHODS = [
    ("klt_adaptive_clahe", "klt_adaptive_clahe"),
    ("normal_safe_sp_lg", "normal_safe_sp_lg"),
    ("current_full_sp_lg_loftr", "full_sp_lg_loftr"),
    ("a06_tuned_quality_sp_lg_loftr", "a06_tuned_quality_sp_lg_loftr"),
]

NUMERIC_METRICS = [
    "frames",
    "features_mean",
    "grid_cov_median",
    "track_age_median",
    "track_age_mean",
    "long_track_ratio_mean",
    "dropout_mean",
    "dropout_ratio_median",
    "f_inlier_median",
    "h_inlier_median",
    "epi_error_median",
    "homography_error_median",
    "runtime_ms_median",
    "loftr_init_mean",
    "loftr_init_total",
    "loftr_accepted_frames",
    "loftr_accepted_tracks",
]

COMPARISON_CHECKS = [
    ("grid_cov_median", "ge", -0.005, "grid coverage"),
    ("track_age_median", "ge", -0.5, "track age"),
    ("long_track_ratio_mean", "ge", -0.005, "long-track ratio"),
    ("dropout_mean", "le", 0.5, "dropout mean"),
    ("dropout_ratio_median", "le", 0.005, "dropout ratio"),
    ("f_inlier_median", "ge", -0.020, "F inlier"),
    ("h_inlier_median", "ge", -0.020, "H inlier"),
    ("epi_error_median", "le", 0.005, "epipolar residual"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "logs/agent_loftr_noharm"),
        help="Directory for owned no-harm logs and summaries.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = _build_metrics(output_dir)
    metrics_csv = output_dir / "loftr_noharm_metrics.csv"
    metrics.to_csv(metrics_csv, index=False)

    comparisons = _build_comparisons(metrics)
    summary_csv = output_dir / "loftr_noharm_summary.csv"
    comparisons.to_csv(summary_csv, index=False)

    summary_md = output_dir / "loftr_noharm_summary.md"
    summary_md.write_text(_to_markdown(_summary_view(comparisons)) + "\n", encoding="utf-8")

    report_md = output_dir / "loftr_noharm_report.md"
    report_md.write_text(_report(metrics, comparisons, output_dir), encoding="utf-8")

    print(_summary_view(comparisons).to_string(index=False))
    print(f"wrote {metrics_csv}")
    print(f"wrote {summary_csv}")
    print(f"wrote {summary_md}")
    print(f"wrote {report_md}")
    return 0


def _build_metrics(output_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        for role, source_suffix in METHODS:
            csv_path = _csv_for(window, role, source_suffix, output_dir)
            inferred = False
            if csv_path is None and role == "a06_tuned_quality_sp_lg_loftr" and window["evidence"] == "existing_inactive_gate":
                current_full = _csv_for(window, "current_full_sp_lg_loftr", "full_sp_lg_loftr", output_dir)
                if current_full is not None and _loftr_inactive(current_full):
                    csv_path = current_full
                    inferred = True
            if csv_path is None:
                rows.append(
                    {
                        "dataset": window["dataset"],
                        "window": f"{window['start']}-{window['end']}",
                        "method": role,
                        "missing": True,
                        "evidence": window["evidence"],
                    }
                )
                continue
            row = _summarize_csv(csv_path)
            row.update(
                {
                    "dataset": window["dataset"],
                    "window": f"{window['start']}-{window['end']}",
                    "method": role,
                    "missing": False,
                    "evidence": "inferred_tuned_inactive" if inferred else window["evidence"],
                    "csv": _display_path(csv_path),
                    "provenance": "fresh_or_owned" if output_dir in csv_path.parents else "existing_log",
                }
            )
            rows.append(row)
    table = pd.DataFrame(rows)
    return table[["dataset", "window", "method", "missing", "evidence", "provenance", *NUMERIC_METRICS, "semidense_events", "csv"]]


def _csv_for(
    window: dict[str, Any],
    role: str,
    source_suffix: str,
    output_dir: Path,
) -> Path | None:
    owned = output_dir / f"{window['dataset']}_{window['start']}_{window['end']}_{role}.csv"
    if owned.exists():
        return owned
    if role == "a06_tuned_quality_sp_lg_loftr":
        return None
    if role == "klt_adaptive_clahe" and "klt_override" in window:
        override = Path(window["klt_override"])
        return override if override.exists() else None
    baseline_dir = Path(window["baseline_dir"])
    baseline = baseline_dir / f"{window['baseline_prefix']}_{source_suffix}.csv"
    if baseline.exists():
        return baseline
    return None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _loftr_inactive(csv_path: Path) -> bool:
    df = pd.read_csv(csv_path)
    if "loftr_init_tracks" in df and pd.to_numeric(df["loftr_init_tracks"], errors="coerce").fillna(0).sum() != 0:
        return False
    if "semidense_acceptance" not in df:
        return True
    accepted = df["semidense_acceptance"].fillna("").astype(str).str.startswith("accepted_loftr_")
    return not bool(accepted.any())


def _summarize_csv(csv_path: Path) -> dict[str, Any]:
    df = pd.read_csv(csv_path)
    semidense = df["semidense_acceptance"].fillna("").astype(str) if "semidense_acceptance" in df else pd.Series([], dtype=str)
    accepted = semidense.str.startswith("accepted_loftr_") if len(semidense) else pd.Series([], dtype=bool)
    accepted_tracks = 0
    for value in semidense[accepted] if len(semidense) else []:
        match = re.search(r"accepted_loftr_(\d+)", value)
        if match:
            accepted_tracks += int(match.group(1))
    return {
        "frames": len(df),
        "features_mean": _mean(df, "num_features"),
        "grid_cov_median": _median(df, "grid_coverage"),
        "track_age_median": _median(df, "median_track_age"),
        "track_age_mean": _mean(df, "mean_track_age"),
        "long_track_ratio_mean": _mean(df, "long_track_ratio"),
        "dropout_mean": _mean(df, "dropped_features"),
        "dropout_ratio_median": _median(df, "dropout_ratio"),
        "f_inlier_median": _median(df, "fundamental_inlier_ratio"),
        "h_inlier_median": _median(df, "homography_inlier_ratio"),
        "epi_error_median": _median(df, "median_epipolar_error"),
        "homography_error_median": _median(df, "median_homography_error"),
        "runtime_ms_median": _median(df, "runtime_ms"),
        "loftr_init_mean": _mean(df, "loftr_init_tracks"),
        "loftr_init_total": _sum(df, "loftr_init_tracks"),
        "loftr_accepted_frames": int(accepted.sum()) if len(accepted) else 0,
        "loftr_accepted_tracks": int(accepted_tracks),
        "semidense_events": _counts(df, "semidense_acceptance"),
    }


def _build_comparisons(metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    available = metrics[~metrics["missing"].astype(bool)]
    for (dataset, window), group in available.groupby(["dataset", "window"], sort=False):
        by_method = group.set_index("method")
        tuned = by_method.loc["a06_tuned_quality_sp_lg_loftr"] if "a06_tuned_quality_sp_lg_loftr" in by_method.index else None
        klt = by_method.loc["klt_adaptive_clahe"] if "klt_adaptive_clahe" in by_method.index else None
        full = by_method.loc["current_full_sp_lg_loftr"] if "current_full_sp_lg_loftr" in by_method.index else None
        klt_eval = _compare(tuned, klt)
        full_eval = _compare(tuned, full)
        overall = _overall_status(klt_eval["status"], full_eval["status"])
        rows.append(
            {
                "dataset": dataset,
                "window": window,
                "frames": int(tuned["frames"]) if tuned is not None else 0,
                "status_vs_klt": klt_eval["status"],
                "status_vs_current_full": full_eval["status"],
                "overall_status": overall,
                "loftr_accepted_frames": int(tuned["loftr_accepted_frames"]) if tuned is not None else 0,
                "loftr_accepted_tracks": int(tuned["loftr_accepted_tracks"]) if tuned is not None else 0,
                "delta_grid_vs_klt": klt_eval.get("delta_grid_cov_median", math.nan),
                "delta_age_vs_klt": klt_eval.get("delta_track_age_median", math.nan),
                "delta_long_vs_klt": klt_eval.get("delta_long_track_ratio_mean", math.nan),
                "delta_dropout_vs_klt": klt_eval.get("delta_dropout_mean", math.nan),
                "delta_dropout_ratio_vs_klt": klt_eval.get("delta_dropout_ratio_median", math.nan),
                "delta_epi_vs_klt": klt_eval.get("delta_epi_error_median", math.nan),
                "delta_f_inlier_vs_klt": klt_eval.get("delta_f_inlier_median", math.nan),
                "delta_h_inlier_vs_klt": klt_eval.get("delta_h_inlier_median", math.nan),
                "delta_grid_vs_current_full": full_eval.get("delta_grid_cov_median", math.nan),
                "delta_age_vs_current_full": full_eval.get("delta_track_age_median", math.nan),
                "delta_long_vs_current_full": full_eval.get("delta_long_track_ratio_mean", math.nan),
                "delta_dropout_vs_current_full": full_eval.get("delta_dropout_mean", math.nan),
                "delta_dropout_ratio_vs_current_full": full_eval.get("delta_dropout_ratio_median", math.nan),
                "delta_epi_vs_current_full": full_eval.get("delta_epi_error_median", math.nan),
                "delta_f_inlier_vs_current_full": full_eval.get("delta_f_inlier_median", math.nan),
                "delta_h_inlier_vs_current_full": full_eval.get("delta_h_inlier_median", math.nan),
                "fail_reasons_vs_klt": klt_eval["fail_reasons"],
                "fail_reasons_vs_current_full": full_eval["fail_reasons"],
            }
        )
    return pd.DataFrame(rows)


def _compare(tuned: pd.Series | None, baseline: pd.Series | None) -> dict[str, Any]:
    if tuned is None:
        return {"status": "MISSING_TUNED", "fail_reasons": "tuned CSV missing"}
    if baseline is None:
        return {"status": "MISSING_BASELINE", "fail_reasons": "baseline CSV missing"}
    result: dict[str, Any] = {}
    failures: list[str] = []
    for metric, direction, tolerance, label in COMPARISON_CHECKS:
        delta = float(tuned[metric]) - float(baseline[metric])
        result[f"delta_{metric}"] = delta
        if direction == "ge":
            ok = delta >= tolerance
        else:
            ok = delta <= tolerance
        if not ok:
            failures.append(f"{label} {delta:+.4f}")
    result["status"] = "PASS" if not failures else "FAIL"
    result["fail_reasons"] = "; ".join(failures)
    return result


def _overall_status(status_vs_klt: str, status_vs_full: str) -> str:
    statuses = [status_vs_klt, status_vs_full]
    if any(status.startswith("MISSING") for status in statuses):
        return "INCOMPLETE"
    return "PASS" if all(status == "PASS" for status in statuses) else "FAIL"


def _summary_view(comparisons: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "dataset",
        "window",
        "overall_status",
        "status_vs_klt",
        "status_vs_current_full",
        "loftr_accepted_frames",
        "loftr_accepted_tracks",
        "delta_grid_vs_klt",
        "delta_age_vs_klt",
        "delta_dropout_vs_klt",
        "delta_epi_vs_klt",
        "delta_grid_vs_current_full",
        "delta_age_vs_current_full",
        "delta_dropout_vs_current_full",
        "delta_epi_vs_current_full",
    ]
    return comparisons[cols].copy()


def _report(metrics: pd.DataFrame, comparisons: pd.DataFrame, output_dir: Path) -> str:
    non_a06 = comparisons[~comparisons["dataset"].str.contains("a06", case=False, na=False)]
    pass_count = int(non_a06["overall_status"].eq("PASS").sum())
    fail_count = int(non_a06["overall_status"].eq("FAIL").sum())
    incomplete_count = int(non_a06["overall_status"].eq("INCOMPLETE").sum())
    promote = bool(fail_count == 0 and incomplete_count == 0 and pass_count > 0)
    decision = (
        "Global promotion is supported by this representative frontend CSV pass."
        if promote
        else "Do not globally promote from this evidence; keep the gate scheduled for A06-like sparse planar windows."
    )
    lines = [
        "# A06 LoFTR Residual-Neutral Cross-Dataset No-Harm Report",
        "",
        "Date: 2026-05-12",
        "",
        "## Scope",
        "",
        "This is a frontend-only CSV validation. No ROS/VINS runs were launched. The test applies the A06 `a06_loftr_residual_neutral_quality.yaml` gate to non-A06 representative windows and compares it with existing or freshly generated `KLT + adaptive CLAHE` and current full `SP+LG+LoFTR` CSVs.",
        "",
        "No default frontend, VINS, or tracker source files were modified.",
        "",
        "## Commands",
        "",
        "```bash",
        "bash scripts/agent_loftr_noharm_run.sh",
        "python3 scripts/agent_loftr_noharm_summary.py --output-dir logs/agent_loftr_noharm",
        "```",
        "",
        "The runner expands to frontend CSV evaluations using `python3 -m uw_frontend.evaluation.run_frontend_eval`; existing texture-breadth baselines are reused for H07, H06, and AFRL-FL. AFRL-FR is included as an existing-log caution because a direct tuned-gate short run was intentionally skipped to keep compute compact.",
        "",
        "## Decision",
        "",
        f"{decision}",
        "",
        f"Representative non-A06 windows: {pass_count} pass, {fail_count} fail, {incomplete_count} incomplete.",
        "",
        "## Pass/Fail Summary",
        "",
        _to_markdown(_summary_view(comparisons)),
        "",
        "Evidence tags in the full metrics table distinguish fresh tuned probes from inactive-gate inference. Inferred rows reuse existing current-full CSVs only when LoFTR accepted zero frames and the semidense gate stayed inactive/rejected.",
        "",
        "## Full Metrics",
        "",
        _to_markdown(
            metrics[
                [
                    "dataset",
                    "window",
                    "method",
                    "evidence",
                    "provenance",
                    "frames",
                    "grid_cov_median",
                    "track_age_median",
                    "long_track_ratio_mean",
                    "dropout_mean",
                    "dropout_ratio_median",
                    "f_inlier_median",
                    "h_inlier_median",
                    "epi_error_median",
                    "runtime_ms_median",
                    "loftr_accepted_frames",
                    "loftr_accepted_tracks",
                    "semidense_events",
                    "csv",
                ]
            ]
        ),
        "",
        "## Failure Details",
        "",
    ]
    failures = comparisons[
        comparisons["overall_status"].isin(["FAIL", "INCOMPLETE"])
    ]
    if failures.empty:
        lines.append("No representative non-A06 window failed the no-harm checks.")
    else:
        for _, row in failures.iterrows():
            reasons = []
            if row["fail_reasons_vs_klt"]:
                reasons.append(f"vs KLT: {row['fail_reasons_vs_klt']}")
            if row["fail_reasons_vs_current_full"]:
                reasons.append(f"vs current full: {row['fail_reasons_vs_current_full']}")
            lines.append(f"- {row['dataset']} {row['window']}: {' | '.join(reasons)}")
    reference_notes = _reference_notes()
    if reference_notes:
        lines.extend(["", "## Existing-Log Cautions", ""])
        lines.extend(reference_notes)
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{(output_dir / 'loftr_noharm_metrics.csv').relative_to(ROOT)}`",
            f"- `{(output_dir / 'loftr_noharm_summary.csv').relative_to(ROOT)}`",
            f"- `{(output_dir / 'loftr_noharm_summary.md').relative_to(ROOT)}`",
            f"- `{(output_dir / 'loftr_noharm_report.md').relative_to(ROOT)}`",
            "",
        ]
    )
    return "\n".join(lines)


def _reference_notes() -> list[str]:
    notes: list[str] = []
    for window in WINDOWS:
        reference = window.get("reference_loftr")
        klt = window.get("klt_override")
        if not reference or not klt:
            continue
        ref_path = Path(reference)
        klt_path = Path(klt)
        if not ref_path.exists() or not klt_path.exists():
            continue
        ref = _summarize_csv(ref_path)
        base = _summarize_csv(klt_path)
        notes.append(
            "- "
            + f"{window['dataset']} {window['start']}-{window['end']}: direct tuned gate was not run. "
            + "Existing pure LoFTR long-window baseline is not no-harm vs KLT "
            + f"(grid {ref['grid_cov_median'] - base['grid_cov_median']:+.4f}, "
            + f"age {ref['track_age_median'] - base['track_age_median']:+.4f}, "
            + f"dropout {ref['dropout_mean'] - base['dropout_mean']:+.4f}, "
            + f"epi {ref['epi_error_median'] - base['epi_error_median']:+.4f})."
        )
    return notes


def _mean(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").mean()) if col in df else math.nan


def _median(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").median()) if col in df else math.nan


def _sum(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").sum()) if col in df else math.nan


def _counts(df: pd.DataFrame, col: str) -> str:
    if col not in df:
        return ""
    return ";".join(
        f"{key}:{value}"
        for key, value in df[col].fillna("").astype(str).value_counts().items()
        if key
    )


def _to_markdown(df: pd.DataFrame) -> str:
    headers = [str(col) for col in df.columns]
    rows = [[_fmt(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [
        max([len(headers[idx])] + [len(row[idx]) for row in rows])
        for idx in range(len(headers))
    ]
    lines = [
        "| " + " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return f"{value:.4f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bool):
        return str(value)
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
