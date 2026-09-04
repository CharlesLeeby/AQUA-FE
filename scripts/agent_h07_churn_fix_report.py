#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
V2_SUMMARY = ROOT / "logs/paper_texture_churn_gate_v2/churn_gate_v2_summary.csv"


RUNS = [
    ("klt_adaptive", "h07_1740_1820_klt_adaptive_clahe.csv"),
    ("default_full_sp_lg", "h07_1740_1820_default_full_sp_lg_loftr.csv"),
    ("churn_residual_neutral_sp_lg", "h07_1740_1820_churn_residual_neutral_sp_lg_loftr.csv"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(ROOT / "logs/agent_h07_churn_fix"))
    parser.add_argument("--output-md", default=str(ROOT / "logs/agent_h07_churn_fix/churn_fix_report.md"))
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    rows = []
    for label, name in RUNS:
        csv_path = input_dir / name
        if not csv_path.exists():
            rows.append({"run": label, "csv": str(csv_path), "missing": True})
            continue
        rows.append(_summarize(label, csv_path))
    summary = pd.DataFrame(rows)
    summary.to_csv(input_dir / "churn_fix_summary.csv", index=False)
    Path(args.output_md).write_text(_report(summary, input_dir), encoding="utf-8")
    print(f"wrote {Path(args.output_md)}")
    return 0


def _summarize(label: str, csv_path: Path) -> dict[str, object]:
    df = pd.read_csv(csv_path)
    confirmed_cols = [
        c
        for c in df.columns
        if c.endswith("_confirmed_tracks")
        and any(token in c for token in ["superpoint", "xfeat", "loftr", "learned"])
    ]
    learned_accepted = (
        df[confirmed_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
        if confirmed_cols
        else pd.Series(0, index=df.index)
    )
    return {
        "run": label,
        "csv": str(csv_path),
        "missing": False,
        "frames": len(df),
        "features_mean": _mean(df, "num_features"),
        "grid_coverage_median": _median(df, "grid_coverage"),
        "grid_coverage_min": _min(df, "grid_coverage"),
        "dropout_ratio_median": _median(df, "dropout_ratio"),
        "dropout_ratio_mean": _mean(df, "dropout_ratio"),
        "median_track_age_median": _median(df, "median_track_age"),
        "mean_track_age_mean": _mean(df, "mean_track_age"),
        "long_track_ratio_mean": _mean(df, "long_track_ratio"),
        "fundamental_inlier_ratio_median": _median(df, "fundamental_inlier_ratio"),
        "homography_inlier_ratio_median": _median(df, "homography_inlier_ratio"),
        "median_epipolar_error_median": _median(df, "median_epipolar_error"),
        "median_epipolar_error_mean": _mean(df, "median_epipolar_error"),
        "median_homography_error_median": _median(df, "median_homography_error"),
        "learned_accepted_total": int(learned_accepted.sum()),
        "learned_accepted_frames": int((learned_accepted > 0).sum()),
        "tracker_modes": _counts(df, "tracker_mode"),
        "track_health_reasons": _counts(df, "track_health_reason"),
        "geometry_safe_events": _token_counts(df, "geometry_safe_acceptance"),
        "semidense_events": _counts(df, "semidense_acceptance"),
        "runtime_ms_median": _median(df, "runtime_ms"),
    }


def _report(summary: pd.DataFrame, input_dir: Path) -> str:
    available = summary[~summary.get("missing", False).astype(bool)].set_index("run")
    lines = [
        "# H07 Churn Residual-Neutral Fix Report",
        "",
        "本报告由 `scripts/agent_h07_churn_fix_report.py` 从本目录 CSV 复算生成。实验只写入 `logs/agent_h07_churn_fix/`，没有改默认 frontend 配置。",
        "",
        "## Commands",
        "",
        "```bash",
        "bash scripts/agent_h07_churn_fix_run.sh",
        "```",
        "",
        "核心运行命令由脚本展开为以下三条：",
        "",
        "```bash",
        "python3 -m uw_frontend.evaluation.run_frontend_eval --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz --image-prefix harbor_images_sequence_07 --output-csv logs/agent_h07_churn_fix/h07_1740_1820_klt_adaptive_clahe.csv --method klt --config uw_frontend/configs/klt_frontend.yaml --preprocess adaptive_clahe --start-index 1740 --end-index 1820",
        "python3 -m uw_frontend.evaluation.run_frontend_eval --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz --image-prefix harbor_images_sequence_07 --output-csv logs/agent_h07_churn_fix/h07_1740_1820_default_full_sp_lg_loftr.csv --method hybrid_superpoint_lightglue --config uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml --preprocess adaptive_clahe --start-index 1740 --end-index 1820 --semidense-fallback-method loftr",
        "python3 -m uw_frontend.evaluation.run_frontend_eval --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz --image-prefix harbor_images_sequence_07 --output-csv logs/agent_h07_churn_fix/h07_1740_1820_churn_residual_neutral_sp_lg_loftr.csv --method hybrid_superpoint_lightglue --config uw_frontend/configs/experiments/h07_churn_residual_neutral.yaml --preprocess adaptive_clahe --start-index 1740 --end-index 1820 --semidense-fallback-method loftr",
        "```",
        "",
    ]
    if len(available) < 3:
        lines.extend(["## Status", "", "实验不完整：至少一个目标 CSV 缺失。"])
        for _, row in summary.iterrows():
            if bool(row.get("missing", False)):
                lines.append(f"- missing: `{row['csv']}`")
        return "\n".join(lines) + "\n"

    klt = available.loc["klt_adaptive"]
    default = available.loc["default_full_sp_lg"]
    churn = available.loc["churn_residual_neutral_sp_lg"]
    v2_delta = _v2_epi_delta()
    klt_eval = _baseline_eval(churn, klt, v2_delta)
    default_eval = _baseline_eval(churn, default, v2_delta)
    pass_labels = []
    if klt_eval["pass"]:
        pass_labels.append("KLT adaptive")
    if default_eval["pass"]:
        pass_labels.append("default full SP-LG")
    pass_experiment = bool(pass_labels)
    fixed_decision = (
        "是否固定到默认配置：不固定。当前只是 H07 1740-1820 的局部结果；需要跨窗口/跨数据集验证后再考虑进入默认。"
        if klt_eval["pass"]
        else "是否固定到默认配置：不固定。当前只在 H07 1740-1820 上相对 default full 局部通过；相对 KLT adaptive 仍有 residual 上升，因此只能保留为实验配置。"
    )

    lines.extend(
        [
            "## Status",
            "",
            (
                "实验达到本轮局部验收：相对 "
                + "、".join(pass_labels)
                + " 至少一个 churn proxy 改善，且 epipolar residual 不升高或升高不超过 v2 增量的 75%。"
                if pass_experiment
                else "实验未达到本轮局部验收：不能同时满足 churn proxy 改善和 residual-neutral/near-neutral。"
            ),
            "",
            fixed_decision,
            "",
            "## Metrics",
            "",
            "| run | dropout med/mean | mean age | median age | long-track mean | grid med/min | epi med | F inlier med | learned accepted |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label in ["klt_adaptive", "default_full_sp_lg", "churn_residual_neutral_sp_lg"]:
        row = available.loc[label]
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    f"{_fmt(row['dropout_ratio_median'])}/{_fmt(row['dropout_ratio_mean'])}",
                    _fmt(row["mean_track_age_mean"]),
                    _fmt(row["median_track_age_median"]),
                    _fmt(row["long_track_ratio_mean"]),
                    f"{_fmt(row['grid_coverage_median'])}/{_fmt(row['grid_coverage_min'])}",
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
            f"- vs KLT adaptive: dropout median {_signed(klt_eval['dropout_delta'])}, mean age {_signed(klt_eval['age_delta'])}, long-track {_signed(klt_eval['long_delta'])}, epi {_signed(klt_eval['epi_delta'])}, pass={klt_eval['pass']}",
            f"- vs default full SP-LG: dropout median {_signed(default_eval['dropout_delta'])}, mean age {_signed(default_eval['age_delta'])}, long-track {_signed(default_eval['long_delta'])}, epi {_signed(default_eval['epi_delta'])}, pass={default_eval['pass']}",
            f"- v2 median epipolar delta reference: {_fmt(v2_delta)}",
            "",
            "## Gate Evidence",
            "",
            f"- tracker modes: `{churn['tracker_modes']}`",
            f"- track health reasons: `{churn['track_health_reasons']}`",
            f"- geometry-safe events: `{churn['geometry_safe_events']}`",
            f"- semidense events: `{churn['semidense_events']}`",
            "",
        ]
    )
    if not pass_experiment:
        lines.extend(
            [
                "## Failure Reason",
                "",
                "当前 residual-neutral 策略会把 learned promotion 压得很保守；若 learned accepted 为 0 或非常少，dropout/age/long-track ratio 难以明显改善。若放宽 gate，历史 v2 已显示 epipolar residual 会变差，因此本轮不应进入默认配置。",
                "",
            ]
        )
    lines.append(f"Summary CSV: `{(input_dir / 'churn_fix_summary.csv').relative_to(ROOT)}`")
    return "\n".join(lines) + "\n"


def _baseline_eval(churn: pd.Series, baseline: pd.Series, v2_delta: float) -> dict[str, object]:
    dropout_delta = float(churn["dropout_ratio_median"] - baseline["dropout_ratio_median"])
    age_delta = float(churn["mean_track_age_mean"] - baseline["mean_track_age_mean"])
    long_delta = float(churn["long_track_ratio_mean"] - baseline["long_track_ratio_mean"])
    epi_delta = float(churn["median_epipolar_error_median"] - baseline["median_epipolar_error_median"])
    continuity_ok = bool(dropout_delta < 0.0 or age_delta > 0.0 or long_delta > 0.0)
    residual_ok = bool(epi_delta <= 0.0)
    residual_less_than_v2 = bool(v2_delta == v2_delta and 0.0 < epi_delta <= 0.75 * v2_delta)
    return {
        "dropout_delta": dropout_delta,
        "age_delta": age_delta,
        "long_delta": long_delta,
        "epi_delta": epi_delta,
        "pass": bool(continuity_ok and (residual_ok or residual_less_than_v2)),
    }


def _v2_epi_delta() -> float:
    if not V2_SUMMARY.exists():
        return float("nan")
    table = pd.read_csv(V2_SUMMARY)
    subset = table[
        table["dataset"].eq("aqualoc_h07_lowtex_extreme")
        & table["method"].isin(["full_sp_lg_loftr", "klt_adaptive_clahe"])
    ]
    if subset.empty:
        return float("nan")
    by_method = subset.set_index("method")
    if "full_sp_lg_loftr" not in by_method.index or "klt_adaptive_clahe" not in by_method.index:
        return float("nan")
    return float(
        by_method.loc["full_sp_lg_loftr", "epi_error_median"]
        - by_method.loc["klt_adaptive_clahe", "epi_error_median"]
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
