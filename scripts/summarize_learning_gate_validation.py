#!/usr/bin/env python3
"""Build a compact paired report for learned-sidecar SLAM validation runs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag-prefix", default="slamgate_v1")
    parser.add_argument("--output-dir", default="logs/slam_learning_gate_validation")
    parser.add_argument("--h07-summary", default=None)
    parser.add_argument("--arch-summary", default=None)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h07_summary = Path(args.h07_summary) if args.h07_summary else out_dir / "h07_runs_summary.csv"
    arch_summary = Path(args.arch_summary) if args.arch_summary else out_dir / "archaeo_runs_summary.csv"
    frames = []
    for path in [h07_summary, arch_summary]:
        if path.exists():
            frames.append(pd.read_csv(path))
    if not frames:
        raise SystemExit("no summary CSVs found")
    df = pd.concat(frames, ignore_index=True)
    df = df[df["run"].astype(str).str.contains(str(args.tag_prefix), na=False)].copy()
    if df.empty:
        raise SystemExit(f"no runs matched tag prefix: {args.tag_prefix}")
    df["case"] = df["run"].map(infer_case)
    df["variant"] = df["run"].map(infer_variant)
    df = df[df["case"].notna() & df["variant"].notna()].copy()

    paired = build_pairs(df)
    detail_csv = out_dir / f"{args.tag_prefix}_detail.csv"
    pair_csv = out_dir / f"{args.tag_prefix}_paired.csv"
    report_md = out_dir / f"{args.tag_prefix}_report.md"
    df.to_csv(detail_csv, index=False)
    paired.to_csv(pair_csv, index=False)
    report_md.write_text(render_report(args.tag_prefix, paired, df), encoding="utf-8")
    print(f"wrote {detail_csv}")
    print(f"wrote {pair_csv}")
    print(f"wrote {report_md}")
    if not paired.empty:
        cols = [
            "case",
            "texture_role",
            "baseline_ape",
            "proposed_ape",
            "ape_delta",
            "ape_delta_pct",
            "baseline_rpe",
            "proposed_rpe",
            "exported_learned",
            "exported_loftr",
            "verdict",
        ]
        print(paired[cols].to_string(index=False))
    return 0


def infer_case(run: str) -> str | None:
    for token in [
        "h07_1660_1950",
        "a06_2100_2550",
        "a06_2280_2360",
        "a08_4480_4680",
        "a08_4520_4680",
        "a09_5800_6200",
    ]:
        if token in run:
            return token
    return None


def infer_variant(run: str) -> str | None:
    if run.endswith("_kltprotected") or "_kltprotected_" in run:
        return "protected_baseline"
    if run.endswith("_klt") or "_klt_" in run:
        return "baseline"
    if run.endswith("_proposed") or "_proposed_" in run:
        return "proposed"
    return None


def texture_role(case: str) -> str:
    if case.startswith("h07"):
        return "normal_no_harm"
    return "low_texture_gain"


def build_pairs(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case, group in df.groupby("case"):
        baseline = best_row(group[group["variant"] == "baseline"])
        proposed = best_row(group[group["variant"] == "proposed"])
        protected = best_row(group[group["variant"] == "protected_baseline"])
        if proposed is None:
            continue
        comparison = baseline if baseline is not None else protected
        if comparison is None:
            continue
        baseline_ape = as_float(comparison.get("se3_ape_rmse_m"))
        proposed_ape = as_float(proposed.get("se3_ape_rmse_m"))
        baseline_rpe = as_float(comparison.get("rpe_trans_rmse_m"))
        proposed_rpe = as_float(proposed.get("rpe_trans_rmse_m"))
        ape_delta = proposed_ape - baseline_ape
        rpe_delta = proposed_rpe - baseline_rpe
        role = texture_role(case)
        exported_learned = as_float(proposed.get("frontend_exported_learned_sum"))
        exported_loftr = as_float(proposed.get("frontend_exported_loftr_sum"))
        exported_non_loftr = as_float(proposed.get("frontend_exported_non_loftr_learned_sum"))
        exported_sp_lg = as_float(proposed.get("frontend_exported_sp_lg_sum"))
        exported_xfeat = as_float(proposed.get("frontend_exported_xfeat_sum"))
        degraded_frames = as_float(proposed.get("frontend_degraded_gate_frames"))
        baseline_init = as_float(comparison.get("init_success"))
        proposed_init = as_float(proposed.get("init_success"))
        baseline_coverage = as_float(comparison.get("output_coverage_ratio"))
        proposed_coverage = as_float(proposed.get("output_coverage_ratio"))
        if role == "normal_no_harm":
            ok = (
                proposed_init >= 1.0
                and proposed_coverage >= max(0.80, baseline_coverage - 0.03)
                and ape_delta <= max(0.003, baseline_ape * 0.03)
                and exported_learned <= 1.0
                and exported_loftr <= 1.0
            )
            verdict = "pass_no_harm" if ok else "inspect_normal_interference"
        else:
            ok = (
                proposed_init >= baseline_init
                and proposed_coverage >= max(0.70, baseline_coverage - 0.05)
                and ape_delta < -max(0.003, baseline_ape * 0.01)
                and exported_learned > 0.0
            )
            verdict = "pass_low_texture_gain" if ok else "needs_gate_or_window_tuning"
        rows.append(
            {
                "case": case,
                "texture_role": role,
                "baseline_run": "" if baseline is None else baseline.get("run"),
                "comparison_run": comparison.get("run"),
                "proposed_run": proposed.get("run"),
                "baseline_status": "" if baseline is None else baseline.get("status"),
                "proposed_status": proposed.get("status"),
                "baseline_ape": baseline_ape,
                "proposed_ape": proposed_ape,
                "ape_delta": ape_delta,
                "ape_delta_pct": 100.0 * ape_delta / baseline_ape if baseline_ape > 0 else np.nan,
                "baseline_rpe": baseline_rpe,
                "proposed_rpe": proposed_rpe,
                "rpe_delta": rpe_delta,
                "baseline_init_success": baseline_init,
                "proposed_init_success": proposed_init,
                "baseline_coverage": baseline_coverage,
                "proposed_coverage": proposed_coverage,
                "baseline_lost": as_float(comparison.get("tracking_lost_count_proxy")),
                "proposed_lost": as_float(proposed.get("tracking_lost_count_proxy")),
                "exported_learned": exported_learned,
                "exported_non_loftr_learned": exported_non_loftr,
                "exported_sp_lg": exported_sp_lg,
                "exported_xfeat": exported_xfeat,
                "exported_loftr": exported_loftr,
                "degraded_gate_frames": degraded_frames,
                "gate_reasons": proposed.get("frontend_gate_reasons", ""),
                "benefit_reasons": proposed.get("frontend_benefit_reasons", ""),
                "geometry_reasons": proposed.get("frontend_geometry_reasons", ""),
                "verdict": verdict,
            }
        )
        if protected is not None and proposed is not None:
            protected_ape = as_float(protected.get("se3_ape_rmse_m"))
            protected_rpe = as_float(protected.get("rpe_trans_rmse_m"))
            rows[-1]["protected_run"] = protected.get("run")
            rows[-1]["protected_ape"] = protected_ape
            rows[-1]["protected_rpe"] = protected_rpe
            rows[-1]["proposed_vs_protected_ape_delta"] = proposed_ape - protected_ape
            rows[-1]["proposed_vs_protected_ape_delta_pct"] = (
                100.0 * (proposed_ape - protected_ape) / protected_ape if protected_ape > 0 else np.nan
            )
            rows[-1]["proposed_vs_protected_rpe_delta"] = proposed_rpe - protected_rpe
    if not rows:
        return pd.DataFrame(
            columns=[
                "case",
                "texture_role",
                "baseline_run",
                "comparison_run",
                "proposed_run",
                "baseline_status",
                "proposed_status",
                "baseline_ape",
                "protected_ape",
                "proposed_ape",
                "ape_delta",
                "ape_delta_pct",
                "proposed_vs_protected_ape_delta",
                "proposed_vs_protected_ape_delta_pct",
                "baseline_rpe",
                "protected_rpe",
                "proposed_rpe",
                "rpe_delta",
                "proposed_vs_protected_rpe_delta",
                "baseline_init_success",
                "proposed_init_success",
                "baseline_coverage",
                "proposed_coverage",
                "baseline_lost",
                "proposed_lost",
                "exported_learned",
                "exported_non_loftr_learned",
                "exported_sp_lg",
                "exported_xfeat",
                "exported_loftr",
                "degraded_gate_frames",
                "gate_reasons",
                "benefit_reasons",
                "geometry_reasons",
                "verdict",
            ]
        )
    return pd.DataFrame(rows).sort_values("case")


def best_row(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    ok = df[df["status"] == "ok"].copy()
    if ok.empty:
        return df.iloc[0]
    return ok.sort_values("se3_ape_rmse_m").iloc[0]


def as_float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out


def render_report(tag_prefix: str, paired: pd.DataFrame, detail: pd.DataFrame) -> str:
    lines = [
        f"# SLAM learned-gate validation: `{tag_prefix}`",
        "",
        "Goal: learned/LoFTR modules stay out of normal-texture VINS when KLT is healthy, and enter only as a confirmed sidecar on low-texture windows where they improve trajectory metrics.",
        "",
    ]
    if paired.empty:
        lines.append("No complete baseline/proposed pairs were found.")
        return "\n".join(lines) + "\n"
    show_cols = [
        "case",
        "texture_role",
        "baseline_ape",
        "protected_ape",
        "proposed_ape",
        "ape_delta_pct",
        "proposed_vs_protected_ape_delta_pct",
            "baseline_rpe",
            "protected_rpe",
            "proposed_rpe",
            "baseline_coverage",
            "proposed_coverage",
            "exported_learned",
            "exported_non_loftr_learned",
            "exported_sp_lg",
            "exported_xfeat",
            "exported_loftr",
            "degraded_gate_frames",
        "verdict",
    ]
    lines.append(markdown_table(paired[show_cols]))
    lines.extend(["", "## Interpretation", ""])
    for _, row in paired.iterrows():
        case = str(row["case"])
        verdict = str(row["verdict"])
        learned = as_float(row["exported_learned"])
        non_loftr = as_float(row.get("exported_non_loftr_learned", float("nan")))
        loftr = as_float(row["exported_loftr"])
        delta_pct = as_float(row["ape_delta_pct"])
        if verdict == "pass_no_harm":
            lines.append(
                f"- `{case}` passes no-harm: learned={learned:.0f}, LoFTR={loftr:.0f}, "
                f"APE change={delta_pct:.2f}%."
            )
        elif verdict == "pass_low_texture_gain":
            lines.append(
                f"- `{case}` passes low-texture gain: non-LoFTR learned={non_loftr:.0f}, "
                f"LoFTR={loftr:.0f}, APE change={delta_pct:.2f}%."
            )
        else:
            lines.append(
                f"- `{case}` needs inspection: learned={learned:.0f}, LoFTR={loftr:.0f}, "
                f"APE change={delta_pct:.2f}%, reasons={row.get('gate_reasons', '')}."
            )
    lines.extend(["", "## Runs", ""])
    lines.append(
        markdown_table(
            detail[["case", "variant", "run", "status", "se3_ape_rmse_m", "rpe_trans_rmse_m"]]
        )
    )
    return "\n".join(lines) + "\n"


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    headers = [str(col) for col in df.columns]
    rows = []
    for _, row in df.iterrows():
        rows.append([format_cell(row[col]) for col in df.columns])
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not np.isfinite(value):
            return ""
        return f"{value:.6g}"
    text = str(value)
    if text.lower() == "nan":
        return ""
    return text.replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
