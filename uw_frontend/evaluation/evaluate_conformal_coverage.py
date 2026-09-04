from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from uw_frontend.quality.conformal_calibrator import (
    MondrianConformalCalibrator,
    assign_mondrian_buckets,
    coverage_mask,
)
from uw_frontend.quality.feature_confidence import ReliabilityCalibrator, quality_to_sigma


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate split/Mondrian conformal coverage for per-feature q_i reliability."
    )
    parser.add_argument("--calibration-csv", action="append", required=True)
    parser.add_argument("--test-csv", action="append", default=None)
    parser.add_argument("--model-json", default=None, help="Existing ReliabilityCalibrator JSON.")
    parser.add_argument(
        "--prediction-column",
        default=None,
        help="Column containing q_hat. If omitted, use model-json, then calibrated_quality/q_hat/quality/base_quality.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--alpha",
        type=float,
        action="append",
        default=None,
        help="Miscoverage level. Repeat for multiple levels. Default: 0.20, 0.10, 0.05.",
    )
    parser.add_argument(
        "--score-type",
        choices=["survival_abs_error", "residual_ratio"],
        default="survival_abs_error",
    )
    parser.add_argument("--label-column", default="label")
    parser.add_argument("--residual-column", default=None)
    parser.add_argument(
        "--residual-from-epipolar-score",
        action="store_true",
        help=(
            "Use epipolar_score as a residual proxy via residual = -scale * log(score). "
            "This matches reliability_features._residual_score and is a proxy, not a "
            "raw per-feature reprojection residual."
        ),
    )
    parser.add_argument("--epipolar-score-scale", type=float, default=3.0)
    parser.add_argument("--sigma-column", default=None)
    parser.add_argument(
        "--bucket-column",
        default="auto",
        help="Mondrian bucket column. Use auto for geometry_mode, inferred geometry, source, then global.",
    )
    parser.add_argument("--no-infer-geometry-mode", action="store_true")
    parser.add_argument("--min-bucket-rows", type=int, default=200)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--sigma-scale-floor", type=float, default=1.0)
    parser.add_argument(
        "--fit-temperature",
        action="store_true",
        help="Also report a scalar temperature-scaled q_hat fitted on calibration NLL.",
    )
    args = parser.parse_args()

    alphas = args.alpha if args.alpha else [0.20, 0.10, 0.05]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    calibrator = ReliabilityCalibrator.from_json(args.model_json) if args.model_json else None
    cal = _load_logs(args.calibration_csv, max_rows=args.max_rows)
    test = _load_logs(args.test_csv or args.calibration_csv, max_rows=args.max_rows)
    cal = _add_predictions(cal, calibrator, args.prediction_column, label="calibration")
    test = _add_predictions(test, calibrator, args.prediction_column, label="test")
    if args.fit_temperature:
        temperature = _fit_temperature(cal["q_hat"].to_numpy(dtype=np.float32), cal[args.label_column].to_numpy(dtype=np.float32))
        cal["q_temp"] = _temperature_scale(cal["q_hat"].to_numpy(dtype=np.float32), temperature)
        test["q_temp"] = _temperature_scale(test["q_hat"].to_numpy(dtype=np.float32), temperature)
    else:
        temperature = float("nan")

    cal_buckets = assign_mondrian_buckets(
        cal,
        bucket_column=args.bucket_column,
        infer_geometry_mode=not args.no_infer_geometry_mode,
    )
    test_buckets = assign_mondrian_buckets(
        test,
        bucket_column=args.bucket_column,
        infer_geometry_mode=not args.no_infer_geometry_mode,
    )
    cal["mondrian_bucket"] = cal_buckets
    test["mondrian_bucket"] = test_buckets

    summary_rows = []
    bucket_rows = []
    conformal_models = []
    for alpha in alphas:
        model = MondrianConformalCalibrator.fit(
            cal["q_hat"].to_numpy(dtype=np.float32),
            alpha=float(alpha),
            score_type=args.score_type,
            labels=_optional_values(cal, args.label_column),
            residuals=_residual_values(cal, args),
            sigma_hat=_sigma_values(cal, args),
            buckets=cal_buckets,
            bucket_column=args.bucket_column,
            min_bucket_rows=args.min_bucket_rows,
            sigma_scale_floor=args.sigma_scale_floor,
            metadata={
                "calibration_csv": args.calibration_csv,
                "test_csv": args.test_csv or args.calibration_csv,
                "model_json": args.model_json,
                "temperature": temperature,
            },
        )
        model_path = out_dir / f"mondrian_conformal_alpha{alpha:g}.json"
        model.to_json(model_path)
        conformal_models.append(model_path)
        covered = coverage_mask(
            model,
            test["q_hat"].to_numpy(dtype=np.float32),
            labels=_optional_values(test, args.label_column),
            residuals=_residual_values(test, args),
            sigma_hat=_sigma_values(test, args),
            buckets=test_buckets,
        )
        summary_rows.append(_coverage_row("mondrian", alpha, test, covered, model.global_quantile))
        bucket_rows.extend(_bucket_coverage_rows("mondrian", alpha, test, covered, model))

        global_model = MondrianConformalCalibrator.fit(
            cal["q_hat"].to_numpy(dtype=np.float32),
            alpha=float(alpha),
            score_type=args.score_type,
            labels=_optional_values(cal, args.label_column),
            residuals=_residual_values(cal, args),
            sigma_hat=_sigma_values(cal, args),
            buckets=np.full((len(cal),), "global", dtype=object),
            bucket_column="global",
            min_bucket_rows=args.min_bucket_rows,
            sigma_scale_floor=args.sigma_scale_floor,
            metadata={"kind": "global"},
        )
        global_covered = coverage_mask(
            global_model,
            test["q_hat"].to_numpy(dtype=np.float32),
            labels=_optional_values(test, args.label_column),
            residuals=_residual_values(test, args),
            sigma_hat=_sigma_values(test, args),
            buckets=np.full((len(test),), "global", dtype=object),
        )
        summary_rows.append(_coverage_row("global", alpha, test, global_covered, global_model.global_quantile))
        bucket_rows.extend(_bucket_coverage_rows("global", alpha, test, global_covered, global_model))

    point_rows = _point_metric_rows(test, q_columns=["base_quality", "q_hat"] + (["q_temp"] if args.fit_temperature else []))
    reliability_rows = _reliability_bin_rows(test, q_columns=["base_quality", "q_hat"] + (["q_temp"] if args.fit_temperature else []))

    summary = pd.DataFrame(summary_rows)
    bucket_table = pd.DataFrame(bucket_rows)
    point_table = pd.DataFrame(point_rows)
    reliability_table = pd.DataFrame(reliability_rows)

    summary_csv = out_dir / "conformal_coverage_summary.csv"
    bucket_csv = out_dir / "conformal_coverage_by_bucket.csv"
    point_csv = out_dir / "point_reliability_metrics.csv"
    bins_csv = out_dir / "reliability_diagram_bins.csv"
    report_md = out_dir / "conformal_coverage_report.md"
    summary.to_csv(summary_csv, index=False)
    bucket_table.to_csv(bucket_csv, index=False)
    point_table.to_csv(point_csv, index=False)
    reliability_table.to_csv(bins_csv, index=False)
    report_md.write_text(
        _make_report(
            summary=summary,
            bucket_table=bucket_table,
            point_table=point_table,
            reliability_table=reliability_table,
            model_paths=conformal_models,
            args=args,
            temperature=temperature,
        ),
        encoding="utf-8",
    )

    print(f"wrote {summary_csv}")
    print(f"wrote {bucket_csv}")
    print(f"wrote {point_csv}")
    print(f"wrote {bins_csv}")
    for path in conformal_models:
        print(f"wrote {path}")
    print(f"wrote {report_md}")
    print(summary.to_string(index=False))
    return 0


def _load_logs(paths: list[str] | None, max_rows: int | None) -> pd.DataFrame:
    if not paths:
        raise ValueError("no CSV paths provided")
    frames = []
    for raw_path in paths:
        path = Path(raw_path)
        df = pd.read_csv(path)
        if "dataset" not in df.columns:
            df["dataset"] = _dataset_from_path(path)
        df["input_csv"] = str(path)
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    if "label" in merged.columns:
        merged = merged[(merged["label"] == 0) | (merged["label"] == 1)].copy()
    if max_rows and len(merged) > int(max_rows):
        merged = merged.sample(n=int(max_rows), random_state=17).reset_index(drop=True)
    return merged.reset_index(drop=True)


def _add_predictions(
    df: pd.DataFrame,
    calibrator: ReliabilityCalibrator | None,
    prediction_column: str | None,
    *,
    label: str,
) -> pd.DataFrame:
    out = df.copy()
    if prediction_column:
        if prediction_column not in out.columns:
            raise ValueError(f"{label}: prediction column {prediction_column!r} is missing")
        out["q_hat"] = np.clip(out[prediction_column].to_numpy(dtype=np.float32), 0.0, 1.0)
        return out
    if calibrator is not None:
        missing = [name for name in calibrator.feature_names if name not in out.columns]
        if missing:
            raise ValueError(f"{label}: missing calibrator feature columns: {missing}")
        x = out[calibrator.feature_names].to_numpy(dtype=np.float32)
        base = out["base_quality"].to_numpy(dtype=np.float32) if "base_quality" in out.columns else None
        sources = out["source"].to_numpy(dtype=object) if "source" in out.columns else None
        out["q_hat"] = calibrator.predict(x, base, sources)
        return out
    for candidate in ["q_hat", "calibrated_quality", "quality", "base_quality"]:
        if candidate in out.columns:
            out["q_hat"] = np.clip(out[candidate].to_numpy(dtype=np.float32), 0.0, 1.0)
            return out
    raise ValueError(f"{label}: no q prediction source found")


def _optional_values(df: pd.DataFrame, column: str | None) -> np.ndarray | None:
    if not column or column not in df.columns:
        return None
    return df[column].to_numpy(dtype=np.float32)


def _residual_values(df: pd.DataFrame, args: argparse.Namespace) -> np.ndarray | None:
    if args.score_type != "residual_ratio":
        return None
    if args.residual_from_epipolar_score:
        if "epipolar_score" not in df.columns:
            raise ValueError("--residual-from-epipolar-score requires epipolar_score in the CSV")
        score = np.clip(df["epipolar_score"].to_numpy(dtype=np.float32), 1e-6, 1.0)
        return (-float(args.epipolar_score_scale) * np.log(score)).astype(np.float32)
    candidates = [args.residual_column] if args.residual_column else []
    candidates.extend(["reprojection_error", "epipolar_error", "homography_error", "residual"])
    for column in candidates:
        if column and column in df.columns:
            return df[column].to_numpy(dtype=np.float32)
    raise ValueError("residual_ratio requires --residual-column or a residual column in the CSV")


def _sigma_values(df: pd.DataFrame, args: argparse.Namespace) -> np.ndarray | None:
    if args.score_type != "residual_ratio":
        return None
    if args.sigma_column and args.sigma_column in df.columns:
        return df[args.sigma_column].to_numpy(dtype=np.float32)
    if "visual_sigma" in df.columns:
        return df["visual_sigma"].to_numpy(dtype=np.float32)
    return quality_to_sigma(df["q_hat"].to_numpy(dtype=np.float32))


def _coverage_row(kind: str, alpha: float, df: pd.DataFrame, covered: np.ndarray, quantile: float) -> dict:
    nominal = 1.0 - float(alpha)
    empirical = float(np.mean(covered)) if len(covered) else float("nan")
    return {
        "kind": kind,
        "alpha": float(alpha),
        "nominal_coverage": nominal,
        "empirical_coverage": empirical,
        "coverage_error_pp": 100.0 * (empirical - nominal),
        "rows": int(len(df)),
        "datasets": int(df["dataset"].nunique()) if "dataset" in df else 0,
        "global_quantile": float(quantile),
    }


def _bucket_coverage_rows(
    kind: str,
    alpha: float,
    df: pd.DataFrame,
    covered: np.ndarray,
    model: MondrianConformalCalibrator,
) -> list[dict]:
    rows = []
    work = df.copy()
    work["covered"] = np.asarray(covered, dtype=bool)
    for (dataset, bucket), group in work.groupby(["dataset", "mondrian_bucket"], dropna=False):
        bucket_model = (model.buckets or {}).get(str(bucket))
        rows.append(
            {
                "kind": kind,
                "alpha": float(alpha),
                "dataset": dataset,
                "bucket": bucket,
                "rows": int(len(group)),
                "nominal_coverage": 1.0 - float(alpha),
                "empirical_coverage": float(group["covered"].mean()) if len(group) else float("nan"),
                "coverage_error_pp": 100.0 * (float(group["covered"].mean()) - (1.0 - float(alpha))),
                "quantile": float(bucket_model.quantile) if bucket_model else float(model.global_quantile),
                "uses_global": bool(bucket_model.uses_global) if bucket_model else True,
            }
        )
    return rows


def _point_metric_rows(df: pd.DataFrame, q_columns: list[str]) -> list[dict]:
    rows = []
    if "label" not in df.columns:
        return rows
    y = df["label"].to_numpy(dtype=np.float32)
    for q_col in q_columns:
        if q_col not in df.columns:
            continue
        p = np.clip(df[q_col].to_numpy(dtype=np.float32), 0.0, 1.0)
        rows.append(
            {
                "scope": "pooled",
                "bucket": "all",
                "q_column": q_col,
                "rows": int(len(df)),
                "positive_rate": float(np.mean(y)),
                "brier": _brier(y, p),
                "ece": _ece(y, p),
            }
        )
        for bucket, group in df.groupby("mondrian_bucket", dropna=False):
            idx = group.index.to_numpy()
            rows.append(
                {
                    "scope": "bucket",
                    "bucket": str(bucket),
                    "q_column": q_col,
                    "rows": int(len(group)),
                    "positive_rate": float(np.mean(y[idx])),
                    "brier": _brier(y[idx], p[idx]),
                    "ece": _ece(y[idx], p[idx]),
                }
            )
    return rows


def _reliability_bin_rows(df: pd.DataFrame, q_columns: list[str], bins: int = 10) -> list[dict]:
    rows = []
    if "label" not in df.columns:
        return rows
    y = df["label"].to_numpy(dtype=np.float32)
    for q_col in q_columns:
        if q_col not in df.columns:
            continue
        p = np.clip(df[q_col].to_numpy(dtype=np.float32), 0.0, 1.0)
        for lo in np.linspace(0.0, 1.0 - 1.0 / bins, bins):
            hi = lo + 1.0 / bins
            mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
            if not np.any(mask):
                continue
            rows.append(
                {
                    "scope": "pooled",
                    "bucket": "all",
                    "q_column": q_col,
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "count": int(np.count_nonzero(mask)),
                    "pred_mean": float(np.mean(p[mask])),
                    "empirical": float(np.mean(y[mask])),
                    "abs_gap": abs(float(np.mean(p[mask])) - float(np.mean(y[mask]))),
                }
            )
    return rows


def _fit_temperature(q: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(np.asarray(q, dtype=np.float32), 1e-4, 1.0 - 1e-4)
    y = np.asarray(y, dtype=np.float32)
    logits = np.log(q / (1.0 - q))
    candidates = np.linspace(0.5, 5.0, 91)
    losses = []
    for temp in candidates:
        p = 1.0 / (1.0 + np.exp(-np.clip(logits / float(temp), -30.0, 30.0)))
        losses.append(-float(np.mean(y * np.log(p + 1e-8) + (1.0 - y) * np.log(1.0 - p + 1e-8))))
    return float(candidates[int(np.argmin(losses))])


def _temperature_scale(q: np.ndarray, temperature: float) -> np.ndarray:
    q = np.clip(np.asarray(q, dtype=np.float32), 1e-4, 1.0 - 1e-4)
    logits = np.log(q / (1.0 - q))
    return (1.0 / (1.0 + np.exp(-np.clip(logits / float(temperature), -30.0, 30.0)))).astype(np.float32)


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.clip(p, 0.0, 1.0) - y) ** 2)) if len(y) else float("nan")


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    if len(y) == 0:
        return float("nan")
    p = np.clip(np.asarray(p, dtype=np.float32), 0.0, 1.0)
    y = np.asarray(y, dtype=np.float32)
    ece = 0.0
    for lo in np.linspace(0.0, 1.0 - 1.0 / bins, bins):
        hi = lo + 1.0 / bins
        mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        if not np.any(mask):
            continue
        ece += float(np.count_nonzero(mask)) / len(y) * abs(float(np.mean(p[mask])) - float(np.mean(y[mask])))
    return float(ece)


def _dataset_from_path(path: Path) -> str:
    stem = path.stem
    for suffix in ["_reliability", "_tracks", "_track_log"]:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _make_report(
    *,
    summary: pd.DataFrame,
    bucket_table: pd.DataFrame,
    point_table: pd.DataFrame,
    reliability_table: pd.DataFrame,
    model_paths: list[Path],
    args: argparse.Namespace,
    temperature: float,
) -> str:
    lines = [
        "# Mondrian Conformal Feature Reliability Coverage",
        "",
        "## Setup",
        "",
        f"- score_type: `{args.score_type}`",
        f"- bucket_column: `{args.bucket_column}`",
        f"- min_bucket_rows: {args.min_bucket_rows}",
        f"- calibration_csv: `{args.calibration_csv}`",
        f"- test_csv: `{args.test_csv or args.calibration_csv}`",
        f"- reliability_model: `{args.model_json}`",
        f"- temperature: `{temperature:.4f}`" if temperature == temperature else "- temperature: `not fitted`",
        "",
        "## Coverage Summary",
        "",
        _to_markdown(summary),
        "",
        "## Point Reliability Metrics",
        "",
        _to_markdown(point_table),
        "",
        "## Output Models",
        "",
    ]
    for path in model_paths:
        lines.append(f"- `{path}`")
    if not bucket_table.empty:
        lines.extend(["", "## Bucket Coverage Preview", "", _to_markdown(bucket_table.head(40))])
    if not reliability_table.empty:
        lines.extend(["", "## Reliability Diagram Preview", "", _to_markdown(reliability_table.head(30))])
    return "\n".join(lines) + "\n"


def _to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    headers = [str(col) for col in df.columns]
    rows = [[_fmt(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    header = "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    body = ["| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |" for row in rows]
    return "\n".join([header, sep] + body)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.6g}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
