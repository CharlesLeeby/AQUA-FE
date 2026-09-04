#!/usr/bin/env python3
"""Build a paper-facing evidence matrix for learned-sidecar VINS runs.

This script is deliberately conservative. It does not try to prove that every
underwater sequence improves; it separates:

* low-texture learned-positive pairs,
* normal-texture no-trigger/no-harm pairs,
* caution rows where learned export is mixed or not causal.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path


APE_KEYS = {
    "ape": "se3_ape_rmse_m",
    "rpe": "rpe_trans_rmse_m",
    "coverage": "output_coverage_ratio",
    "init": "init_success",
    "lost": "tracking_lost_count_proxy",
    "failures": "log_linear_solver_failures",
}
SUM_KEYS = [
    "exported_learned_features",
    "exported_non_loftr_learned_features",
    "exported_sp_lg_features",
    "exported_xfeat_features",
    "exported_loftr_features",
    "learned_candidate_count",
    "learned_confirmed_count",
    "learned_export_gate_degraded",
]


@dataclass(frozen=True)
class PairSpec:
    case: str
    texture_role: str
    source_role: str
    baseline: Path
    proposed: Path
    notes: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-csv", default="logs/paper_sidecar_evidence_matrix.csv")
    parser.add_argument("--output-md", default="logs/paper_sidecar_evidence_matrix.md")
    parser.add_argument("--include-current-paperpair", action="store_true")
    args = parser.parse_args()

    specs = default_specs()
    if args.include_current_paperpair:
        specs.extend(discover_current_paperpairs())

    rows = [summarize_pair(spec) for spec in specs]
    output_csv = Path(args.output_csv)
    output_md = Path(args.output_md)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "case",
        "texture_role",
        "source_role",
        "baseline_run",
        "proposed_run",
        "baseline_ape",
        "proposed_ape",
        "ape_delta",
        "ape_delta_pct",
        "baseline_rpe",
        "proposed_rpe",
        "rpe_delta",
        "rpe_delta_pct",
        "baseline_coverage",
        "proposed_coverage",
        "baseline_init",
        "proposed_init",
        "baseline_lost",
        "proposed_lost",
        "exported_learned",
        "exported_non_loftr",
        "exported_sp_lg",
        "exported_xfeat",
        "exported_loftr",
        "learned_candidates",
        "learned_confirmed",
        "degraded_frames",
        "verdict",
        "claim_strength",
        "notes",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    output_md.write_text(render_markdown(rows), encoding="utf-8")
    print(f"wrote {output_csv}")
    print(f"wrote {output_md}")
    for row in rows:
        print(
            f"{row['case']}: {row['verdict']} "
            f"ape {row['baseline_ape']} -> {row['proposed_ape']} "
            f"learned={row['exported_learned']}"
        )
    return 0


def default_specs() -> list[PairSpec]:
    root = Path("logs")
    return [
        PairSpec(
            case="AQUALOC A06 2210-2460",
            texture_role="low-texture planar",
            source_role="LoFTR extreme planar sidecar",
            baseline=root
            / "aqualoc_archaeo_vins"
            / "external_klt_every2_slamgate_v31_a06_2210_2460_klt_sorted",
            proposed=root
            / "aqualoc_archaeo_vins"
            / "external_hybrid_superpoint_lightglue_every2_slamgate_v31_a06_2210_2460_proposed_loftr6",
            notes="Replicated in replay_v32; no-LoFTR ablation returns to KLT-level error.",
        ),
        PairSpec(
            case="AQUALOC A06 2210-2700",
            texture_role="low-texture planar long",
            source_role="LoFTR extreme planar sidecar",
            baseline=root
            / "aqualoc_archaeo_vins"
            / "external_klt_every2_slamgate_v26_a06_2210_2700_klt_sorted",
            proposed=root
            / "aqualoc_archaeo_vins"
            / "external_hybrid_superpoint_lightglue_every2_slamgate_v26_a06_2210_2700_proposed_sorted_loftr6",
            notes="Longer A06 window; sparse LoFTR sidecars improve APE/RPE.",
        ),
        PairSpec(
            case="NTNU fjord1 0-30",
            texture_role="low KLT support",
            source_role="XFeat weak-cell sidecar",
            baseline=root
            / "ntnu_vins"
            / "external_klt_every2_may20_ntnu_fjord1_0_30_countcap220_protected_klt",
            proposed=root
            / "ntnu_vins"
            / "external_hybrid_xfeat_every2_may20_ntnu_fjord1_0_30_countcap220_wide_export",
            notes="Cross-dataset XFeat sidecar positive; KLT output coverage is low.",
        ),
        PairSpec(
            case="NTNU fjord4 0-30",
            texture_role="low/uneven support",
            source_role="XFeat weak-cell sidecar",
            baseline=root / "ntnu_vins" / "external_klt_every2_may19_vins_ntnu_fjord4_0_30_klt",
            proposed=root
            / "ntnu_vins"
            / "external_hybrid_xfeat_every2_may20_ntnu_fjord4_0_30_countcap220_wide_export",
            notes="Moderate cross-dataset XFeat gain; solver failure count remains inherited from KLT.",
        ),
        PairSpec(
            case="AQUALOC H07 1660-1950",
            texture_role="normal texture",
            source_role="scheduler no-trigger",
            baseline=root / "aqualoc_real_vins" / "external_klt_every2_slamgate_v26_h07_1660_1950_klt_sorted",
            proposed=root
            / "aqualoc_real_vins"
            / "external_hybrid_superpoint_lightglue_every2_slamgate_v26_h07_1660_1950_proposed_sorted",
            notes="Clean no-harm: proposed exports zero learned/LoFTR and matches KLT trajectory.",
        ),
        PairSpec(
            case="AFRL FL230-260",
            texture_role="normal/high-support caution",
            source_role="countcap no-trigger",
            baseline=root / "afrl_cave_v31" / "external_klt_every3_may19_vins_afrl_fl_230_260_klt",
            proposed=root / "afrl_cave_v31" / "external_hybrid_xfeat_every3_may20_afrl_fl_230_260_countcap220_export",
            notes="Count cap blocks learned export in a high-support window; remaining delta is not learned contribution.",
        ),
    ]


def discover_current_paperpairs() -> list[PairSpec]:
    root = Path("logs")
    specs: list[PairSpec] = []
    ntnu = root / "ntnu_vins"
    for proposed in ntnu.glob("external_hybrid_xfeat_every2_paperpair_*_hybrid_xfeat"):
        stem = proposed.name.replace("external_hybrid_xfeat_every2_", "").replace("_hybrid_xfeat", "")
        baseline = ntnu / f"external_klt_every2_{stem}_protected_klt"
        if baseline.exists():
            specs.append(
                PairSpec(
                    case=stem,
                    texture_role="paperpair discovered",
                    source_role="XFeat weak-cell sidecar",
                    baseline=baseline,
                    proposed=proposed,
                    notes="Discovered from current paperpair runs.",
                )
            )
    return specs


def summarize_pair(spec: PairSpec) -> dict[str, object]:
    base_ape = parse_ape(spec.baseline / "ape.txt")
    prop_ape = parse_ape(spec.proposed / "ape.txt")
    prop_metrics = parse_frontend(spec.proposed / "frontend_metrics.csv")

    baseline_ape = fnum(base_ape.get("se3_ape_rmse_m"))
    proposed_ape = fnum(prop_ape.get("se3_ape_rmse_m"))
    baseline_rpe = fnum(base_ape.get("rpe_trans_rmse_m"))
    proposed_rpe = fnum(prop_ape.get("rpe_trans_rmse_m"))
    baseline_cov = fnum(base_ape.get("output_coverage_ratio"))
    proposed_cov = fnum(prop_ape.get("output_coverage_ratio"))
    exported_learned = prop_metrics.get("exported_learned_features", 0.0)
    exported_loftr = prop_metrics.get("exported_loftr_features", 0.0)

    ape_delta = proposed_ape - baseline_ape
    rpe_delta = proposed_rpe - baseline_rpe
    verdict, strength = verdict_for(
        spec,
        baseline_ape,
        proposed_ape,
        baseline_rpe,
        proposed_rpe,
        baseline_cov,
        proposed_cov,
        exported_learned,
        exported_loftr,
    )
    return {
        "case": spec.case,
        "texture_role": spec.texture_role,
        "source_role": spec.source_role,
        "baseline_run": str(spec.baseline),
        "proposed_run": str(spec.proposed),
        "baseline_ape": fmt(baseline_ape),
        "proposed_ape": fmt(proposed_ape),
        "ape_delta": fmt(ape_delta),
        "ape_delta_pct": fmt(100.0 * ape_delta / baseline_ape if baseline_ape > 0 else float("nan")),
        "baseline_rpe": fmt(baseline_rpe),
        "proposed_rpe": fmt(proposed_rpe),
        "rpe_delta": fmt(rpe_delta),
        "rpe_delta_pct": fmt(100.0 * rpe_delta / baseline_rpe if baseline_rpe > 0 else float("nan")),
        "baseline_coverage": fmt(baseline_cov),
        "proposed_coverage": fmt(proposed_cov),
        "baseline_init": fmt(fnum(base_ape.get("init_success"))),
        "proposed_init": fmt(fnum(prop_ape.get("init_success"))),
        "baseline_lost": fmt(fnum(base_ape.get("tracking_lost_count_proxy"))),
        "proposed_lost": fmt(fnum(prop_ape.get("tracking_lost_count_proxy"))),
        "exported_learned": fmt(exported_learned),
        "exported_non_loftr": fmt(prop_metrics.get("exported_non_loftr_learned_features", 0.0)),
        "exported_sp_lg": fmt(prop_metrics.get("exported_sp_lg_features", 0.0)),
        "exported_xfeat": fmt(prop_metrics.get("exported_xfeat_features", 0.0)),
        "exported_loftr": fmt(exported_loftr),
        "learned_candidates": fmt(prop_metrics.get("learned_candidate_count", 0.0)),
        "learned_confirmed": fmt(prop_metrics.get("learned_confirmed_count", 0.0)),
        "degraded_frames": fmt(prop_metrics.get("learned_export_gate_degraded", 0.0)),
        "verdict": verdict,
        "claim_strength": strength,
        "notes": spec.notes,
    }


def verdict_for(
    spec: PairSpec,
    baseline_ape: float,
    proposed_ape: float,
    baseline_rpe: float,
    proposed_rpe: float,
    baseline_cov: float,
    proposed_cov: float,
    exported_learned: float,
    exported_loftr: float,
) -> tuple[str, str]:
    if not math.isfinite(baseline_ape) or not math.isfinite(proposed_ape):
        return "incomplete", "do_not_use"
    normal = "normal" in spec.texture_role or "high-support" in spec.texture_role
    if normal:
        if exported_learned <= 0.0 and proposed_ape <= baseline_ape + max(0.003, 0.03 * baseline_ape):
            return "pass_no_trigger_no_harm", "strong" if abs(proposed_ape - baseline_ape) < 1e-6 else "moderate"
        if exported_learned <= 0.0:
            return "no_trigger_but_profile_delta", "caution"
        return "inspect_normal_learned_export", "caution"
    if exported_learned <= 0.0:
        return "no_learned_causal_evidence", "do_not_use_as_positive"
    ape_gain = baseline_ape - proposed_ape
    rpe_gain = baseline_rpe - proposed_rpe
    cov_ok = proposed_cov >= min(1.0, baseline_cov + 0.01) or proposed_cov >= baseline_cov - 0.03
    if ape_gain > max(0.003, 0.03 * baseline_ape) and rpe_gain >= -max(0.003, 0.03 * baseline_rpe) and cov_ok:
        if ape_gain > 0.15 * baseline_ape and rpe_gain > 0.10 * baseline_rpe:
            return "pass_low_texture_learned_gain", "strong"
        return "pass_low_texture_learned_gain", "moderate"
    if exported_loftr > 0.0 or exported_learned > 0.0:
        return "mixed_learned_export", "caution"
    return "needs_tuning", "do_not_use_as_positive"


def parse_ape(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            out[key] = value
    return out


def parse_frontend(path: Path) -> dict[str, float]:
    sums = {key: 0.0 for key in SUM_KEYS}
    if not path.exists():
        return sums
    with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            for key in SUM_KEYS:
                sums[key] += fnum(row.get(key), 0.0)
    return sums


def fnum(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def fmt(value: float) -> str:
    if not math.isfinite(value):
        return ""
    if abs(value) >= 100:
        return f"{value:.3f}"
    return f"{value:.6f}"


def render_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Paper Sidecar Evidence Matrix",
        "",
        "This table separates trajectory-level learned positives from no-trigger/no-harm controls and caution rows.",
        "",
        "| case | role | source | baseline APE/RPE | proposed APE/RPE | learned/XFeat/LoFTR | verdict | strength |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        learned = f"{row['exported_learned']} / {row['exported_xfeat']} / {row['exported_loftr']}"
        lines.append(
            f"| {row['case']} | {row['texture_role']} | {row['source_role']} | "
            f"{row['baseline_ape']} / {row['baseline_rpe']} | "
            f"{row['proposed_ape']} / {row['proposed_rpe']} | "
            f"{learned} | {row['verdict']} | {row['claim_strength']} |"
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- Use `pass_low_texture_learned_gain` rows as trajectory-level support for learned sidecars.",
            "- Use `pass_no_trigger_no_harm` rows to show the scheduler suppresses learned export in normal/high-support imagery.",
            "- Caution rows are useful for explaining why learned methods are sidecars, not replacements.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
