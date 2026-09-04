#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ["1740_1820", "normal_0_100"]
RUNS = [
    ("klt_adaptive", "klt_adaptive_clahe"),
    ("default_full_sp_lg", "default_full_sp_lg_loftr"),
    ("churn_v2_precision_sp_lg", "churn_v2_precision_sp_lg_loftr"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(ROOT / "logs/agent_h07_churn_v2"))
    parser.add_argument("--output-md", default=str(ROOT / "logs/agent_h07_churn_v2/h07_churn_v2_report.md"))
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    rows = []
    for window in WINDOWS:
        for run, suffix in RUNS:
            csv_path = input_dir / f"h07_{window}_{suffix}.csv"
            if csv_path.exists():
                rows.append(_summarize(window, run, csv_path))
            else:
                rows.append({"window": window, "run": run, "csv": str(csv_path), "missing": True})
    summary = pd.DataFrame(rows)
    input_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(input_dir / "h07_churn_v2_summary.csv", index=False)
    Path(args.output_md).write_text(_report(summary, input_dir), encoding="utf-8")
    print(f"wrote {Path(args.output_md)}")
    return 0


def _summarize(window: str, run: str, csv_path: Path) -> dict[str, object]:
    df = pd.read_csv(csv_path)
    accepted_cols = [
        c
        for c in df.columns
        if c.endswith("_confirmed_tracks")
        and any(token in c for token in ["superpoint", "xfeat", "loftr", "learned"])
    ]
    learned_accepted = (
        df[accepted_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
        if accepted_cols
        else pd.Series(0, index=df.index)
    )
    return {
        "window": window,
        "run": run,
        "csv": str(csv_path),
        "missing": False,
        "frames": len(df),
        "features_mean": _mean(df, "num_features"),
        "grid_coverage_median": _median(df, "grid_coverage"),
        "grid_coverage_min": _min(df, "grid_coverage"),
        "dropout_ratio_median": _median(df, "dropout_ratio"),
        "dropout_ratio_mean": _mean(df, "dropout_ratio"),
        "mean_track_age_mean": _mean(df, "mean_track_age"),
        "median_track_age_median": _median(df, "median_track_age"),
        "long_track_ratio_mean": _mean(df, "long_track_ratio"),
        "median_epipolar_error_median": _median(df, "median_epipolar_error"),
        "median_epipolar_error_mean": _mean(df, "median_epipolar_error"),
        "fundamental_inlier_ratio_median": _median(df, "fundamental_inlier_ratio"),
        "homography_inlier_ratio_median": _median(df, "homography_inlier_ratio"),
        "learned_accepted_total": int(learned_accepted.sum()),
        "learned_accepted_frames": int((learned_accepted > 0).sum()),
        "tracker_modes": _counts(df, "tracker_mode"),
        "track_health_reasons": _counts(df, "track_health_reason"),
        "geometry_safe_events": _token_counts(df, "geometry_safe_acceptance"),
        "semidense_events": _counts(df, "semidense_acceptance"),
        "runtime_ms_median": _median(df, "runtime_ms"),
    }


def _report(summary: pd.DataFrame, input_dir: Path) -> str:
    available = summary[~summary.get("missing", False).astype(bool)].copy()
    lines = [
        "# H07 Churn v2 Report",
        "",
        "Scope: one default-off precision gate on top of the existing H07 two-frame learned probation and residual-neutral admission.",
        "",
        "Command:",
        "",
        "```bash",
        "bash scripts/agent_h07_churn_v2_run.sh",
        "```",
        "",
    ]
    missing = summary[summary.get("missing", False).astype(bool)]
    if not missing.empty:
        lines.extend(["## Status", "", "Incomplete run: missing CSVs."])
        for _, row in missing.iterrows():
            lines.append(f"- missing `{row['csv']}`")
        return "\n".join(lines) + "\n"

    keyed = available.set_index(["window", "run"])
    churn_eval = _eval_candidate(keyed, "1740_1820")
    normal_eval = _eval_candidate(keyed, "normal_0_100")
    promote = bool(churn_eval["clear_win"] and normal_eval["no_harm"])
    decision = (
        "Promote as experiment candidate: yes, but keep default-off pending broader validation."
        if promote
        else "Decision: keep as limitation. The focused gate is not a clear no-harm win."
    )

    lines.extend(
        [
            "## Decision",
            "",
            decision,
            "",
            "## Metrics",
            "",
            "| window | run | dropout med/mean | mean age | long-track mean | epi med | F inlier med | learned accepted |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for window in WINDOWS:
        for run, _ in RUNS:
            row = keyed.loc[(window, run)]
            lines.append(
                "| "
                + " | ".join(
                    [
                        window,
                        run,
                        f"{_fmt(row['dropout_ratio_median'])}/{_fmt(row['dropout_ratio_mean'])}",
                        _fmt(row["mean_track_age_mean"]),
                        _fmt(row["long_track_ratio_mean"]),
                        _fmt(row["median_epipolar_error_median"]),
                        _fmt(row["fundamental_inlier_ratio_median"]),
                        f"{int(row['learned_accepted_total'])} / {int(row['learned_accepted_frames'])} frames",
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Delta vs Baselines",
            "",
            _delta_line(churn_eval, "H07 1740-1820"),
            _delta_line(normal_eval, "H07 normal 0-100"),
            "",
            "## Gate Evidence",
            "",
        ]
    )
    for window in WINDOWS:
        row = keyed.loc[(window, "churn_v2_precision_sp_lg")]
        lines.extend(
            [
                f"### {window}",
                "",
                f"- tracker modes: `{row['tracker_modes']}`",
                f"- track health reasons: `{row['track_health_reasons']}`",
                f"- geometry-safe events: `{row['geometry_safe_events']}`",
                f"- semidense events: `{row['semidense_events']}`",
                "",
            ]
        )
    lines.append(f"Summary CSV: `{(input_dir / 'h07_churn_v2_summary.csv').relative_to(ROOT)}`")
    return "\n".join(lines) + "\n"


def _eval_candidate(keyed: pd.DataFrame, window: str) -> dict[str, object]:
    candidate = keyed.loc[(window, "churn_v2_precision_sp_lg")]
    klt = keyed.loc[(window, "klt_adaptive")]
    default = keyed.loc[(window, "default_full_sp_lg")]
    vs_klt = _baseline_delta(candidate, klt)
    vs_default = _baseline_delta(candidate, default)
    tiny = 0.005
    continuity_vs_default = bool(
        vs_default["dropout_median"] < -1e-6
        or vs_default["mean_age"] > 1e-6
        or vs_default["long_track"] > 1e-6
    )
    residual_ok_default = bool(vs_default["epi_median"] <= tiny)
    residual_ok_klt = bool(vs_klt["epi_median"] <= tiny)
    clear_win = bool(continuity_vs_default and residual_ok_default and residual_ok_klt)
    no_harm = bool(
        vs_default["dropout_median"] <= 0.01
        and vs_default["mean_age"] >= -0.10
        and vs_default["long_track"] >= -0.005
        and vs_default["epi_median"] <= tiny
    )
    return {
        "window": window,
        "vs_klt": vs_klt,
        "vs_default": vs_default,
        "clear_win": clear_win,
        "no_harm": no_harm,
    }


def _baseline_delta(candidate: pd.Series, baseline: pd.Series) -> dict[str, float]:
    return {
        "dropout_median": float(candidate["dropout_ratio_median"] - baseline["dropout_ratio_median"]),
        "dropout_mean": float(candidate["dropout_ratio_mean"] - baseline["dropout_ratio_mean"]),
        "mean_age": float(candidate["mean_track_age_mean"] - baseline["mean_track_age_mean"]),
        "long_track": float(candidate["long_track_ratio_mean"] - baseline["long_track_ratio_mean"]),
        "epi_median": float(candidate["median_epipolar_error_median"] - baseline["median_epipolar_error_median"]),
        "f_inlier": float(candidate["fundamental_inlier_ratio_median"] - baseline["fundamental_inlier_ratio_median"]),
    }


def _delta_line(eval_row: dict[str, object], label: str) -> str:
    vs_klt = eval_row["vs_klt"]
    vs_default = eval_row["vs_default"]
    return (
        f"- {label}: vs default dropout {_signed(vs_default['dropout_median'])}, "
        f"mean age {_signed(vs_default['mean_age'])}, long-track {_signed(vs_default['long_track'])}, "
        f"epi {_signed(vs_default['epi_median'])}; vs KLT epi {_signed(vs_klt['epi_median'])}; "
        f"clear_win={eval_row['clear_win']}, no_harm={eval_row['no_harm']}"
    )


def _mean(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").mean()) if col in df else float("nan")


def _median(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").median()) if col in df else float("nan")


def _min(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").min()) if col in df else float("nan")


def _counts(df: pd.DataFrame, col: str) -> str:
    if col not in df:
        return ""
    return ";".join(f"{key}:{value}" for key, value in df[col].fillna("").astype(str).value_counts().items() if key)


def _token_counts(df: pd.DataFrame, col: str) -> str:
    if col not in df:
        return ""
    counts: dict[str, int] = {}
    for text in df[col].fillna("").astype(str):
        for token in text.split(";"):
            token = token.strip()
            if token:
                counts[token] = counts.get(token, 0) + 1
    return ";".join(f"{key}:{value}" for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12])


def _fmt(value: object) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value != value:
        return "nan"
    return f"{value:.4f}"


def _signed(value: object) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value != value:
        return "nan"
    return f"{value:+.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
