#!/usr/bin/env python3
"""Conservative pairwise decision table for learned-sidecar VINS evidence.

The script reads `scripts/summarize_run_evidence.py` output and an optional
hand-written pairing CSV. It is intentionally conservative: a learned run is
not considered useful unless it has nonzero learned export, successful VINS
initialization, no lost-tracking proxy, and improves APE by a configurable
margin over a matched KLT/protected baseline.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import pandas as pd


DEFAULT_FIELDS = [
    "case",
    "dataset",
    "texture_role",
    "baseline_run",
    "candidate_run",
    "baseline_ape",
    "candidate_ape",
    "ape_delta",
    "ape_delta_pct",
    "baseline_rpe",
    "candidate_rpe",
    "rpe_delta",
    "baseline_coverage",
    "candidate_coverage",
    "candidate_init",
    "candidate_lost",
    "exported_learned",
    "exported_xfeat",
    "exported_loftr",
    "candidate_gate_reasons",
    "candidate_benefit_reasons",
    "decision",
    "allowed_claim",
    "blocker",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-csv", default="logs/may20c_all_run_evidence.csv")
    parser.add_argument("--pair-csv", default="")
    parser.add_argument("--output-csv", default="logs/may20c_pairwise_decisions.csv")
    parser.add_argument("--output-md", default="logs/may20c_pairwise_decisions.md")
    parser.add_argument("--min-ape-gain-pct", type=float, default=1.0)
    parser.add_argument("--min-ape-gain-abs", type=float, default=0.003)
    args = parser.parse_args()

    evidence = pd.read_csv(args.evidence_csv)
    rows: list[dict[str, object]] = []
    if args.pair_csv:
        rows.extend(read_pair_spec(Path(args.pair_csv), evidence, args))
    else:
        rows.extend(infer_known_pairs(evidence, args))

    rows = sorted(rows, key=lambda r: (str(r["dataset"]), str(r["case"]), str(r["candidate_run"])))
    out_csv = Path(args.output_csv)
    out_md = Path(args.output_md)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DEFAULT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in DEFAULT_FIELDS})
    out_md.write_text(render_markdown(rows), encoding="utf-8")
    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    print(pd.DataFrame(rows)[["case", "dataset", "decision", "ape_delta_pct", "exported_learned"]].to_string(index=False))
    return 0


def read_pair_spec(path: Path, evidence: pd.DataFrame, args: argparse.Namespace) -> list[dict[str, object]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for spec in csv.DictReader(handle):
            base = lookup_run(evidence, spec["baseline_run"])
            cand = lookup_run(evidence, spec["candidate_run"])
            rows.append(decide_pair(spec, base, cand, args))
    return rows


def infer_known_pairs(evidence: pd.DataFrame, args: argparse.Namespace) -> list[dict[str, object]]:
    specs = [
        {
            "case": "AQUALOC_A06_2210_2700",
            "dataset": "AQUALOC",
            "texture_role": "low_texture_planar",
            "baseline_run": "external_klt_every2_slamgate_v24_a06_2210_2700_klt_denseinit",
            "candidate_run": "external_hybrid_superpoint_lightglue_every2_slamgate_v26_a06_2210_2700_proposed_sorted_loftr6",
        },
        {
            "case": "AQUALOC_H07_1660_1950",
            "dataset": "AQUALOC",
            "texture_role": "normal_texture_no_harm",
            "baseline_run": "external_klt_every2_slamgate_v26_h07_1660_1950_klt_sorted",
            "candidate_run": "external_hybrid_superpoint_lightglue_every2_slamgate_v26_h07_1660_1950_proposed_sorted",
        },
        {
            "case": "AFRL_FL_80_110_latest_strict",
            "dataset": "AFRL",
            "texture_role": "low_support_candidate",
            "baseline_run": "external_klt_every3_may20b_afrl_fl_80_110_klt_strictcontract",
            "candidate_run": "external_hybrid_xfeat_every3_may20b_afrl_fl_80_110_xfeat_strictgate",
        },
        {
            "case": "AFRL_FR_80_110_latest_strict",
            "dataset": "AFRL",
            "texture_role": "low_support_candidate",
            "baseline_run": "external_klt_every3_may20b_afrl_fr_80_110_klt_strictcontract",
            "candidate_run": "external_hybrid_xfeat_every3_may20b_afrl_fr_80_110_xfeat_strictgate",
        },
        {
            "case": "NTNU_fjord1_0_60_strict_export",
            "dataset": "NTNU",
            "texture_role": "normal_or_false_positive_guard",
            "baseline_run": "external_klt_every2_may20_ntnu_fjord1_0_30_protected_klt",
            "candidate_run": "external_hybrid_xfeat_every3_may20b_ntnu_fjord1_xfeat_strictgate",
        },
        {
            "case": "Tank_short_no_harm",
            "dataset": "Tank",
            "texture_role": "normal_or_high_support",
            "baseline_run": "external_klt_every1_formal150_scale05_50_70",
            "candidate_run": "external_proposed_every1_formal_scale05_50_70",
        },
    ]
    rows = []
    for spec in specs:
        base = lookup_run(evidence, spec["baseline_run"])
        cand = lookup_run(evidence, spec["candidate_run"])
        rows.append(decide_pair(spec, base, cand, args))
    return rows


def lookup_run(evidence: pd.DataFrame, run_name: str) -> pd.Series | None:
    if not run_name:
        return None
    exact = evidence[evidence["run"].astype(str) == run_name]
    if not exact.empty:
        return exact.iloc[0]
    contains = evidence[evidence["run"].astype(str).str.contains(re.escape(run_name), na=False)]
    if not contains.empty:
        return contains.iloc[0]
    return None


def decide_pair(
    spec: dict[str, str],
    baseline: pd.Series | None,
    candidate: pd.Series | None,
    args: argparse.Namespace,
) -> dict[str, object]:
    row: dict[str, object] = {
        "case": spec.get("case", ""),
        "dataset": spec.get("dataset", infer_dataset(spec.get("case", ""))),
        "texture_role": spec.get("texture_role", ""),
        "baseline_run": spec.get("baseline_run", ""),
        "candidate_run": spec.get("candidate_run", ""),
    }
    blockers: list[str] = []
    if baseline is None:
        blockers.append("missing_baseline")
    if candidate is None:
        blockers.append("missing_candidate")
    if blockers:
        row["decision"] = "blocked"
        row["allowed_claim"] = "none"
        row["blocker"] = "|".join(blockers)
        return row

    base_ape = f(baseline.get("se3_ape_rmse_m"))
    cand_ape = f(candidate.get("se3_ape_rmse_m"))
    base_rpe = f(baseline.get("rpe_trans_rmse_m"))
    cand_rpe = f(candidate.get("rpe_trans_rmse_m"))
    base_cov = f(baseline.get("output_coverage_ratio"))
    cand_cov = f(candidate.get("output_coverage_ratio"))
    init = f(candidate.get("init_success"))
    lost = f(candidate.get("tracking_lost_count_proxy"))
    learned = f(candidate.get("exported_learned_features_sum"))
    xfeat = f(candidate.get("exported_xfeat_features_sum"))
    loftr = f(candidate.get("exported_loftr_features_sum"))
    ape_delta = cand_ape - base_ape
    rpe_delta = cand_rpe - base_rpe
    ape_delta_pct = 100.0 * ape_delta / base_ape if finite(base_ape) and base_ape > 0 else math.nan
    row.update(
        {
            "baseline_ape": fmt(base_ape),
            "candidate_ape": fmt(cand_ape),
            "ape_delta": fmt(ape_delta),
            "ape_delta_pct": fmt(ape_delta_pct),
            "baseline_rpe": fmt(base_rpe),
            "candidate_rpe": fmt(cand_rpe),
            "rpe_delta": fmt(rpe_delta),
            "baseline_coverage": fmt(base_cov),
            "candidate_coverage": fmt(cand_cov),
            "candidate_init": fmt(init),
            "candidate_lost": fmt(lost),
            "exported_learned": fmt(learned),
            "exported_xfeat": fmt(xfeat),
            "exported_loftr": fmt(loftr),
            "candidate_gate_reasons": candidate.get("learned_export_gate_reason_counts", ""),
            "candidate_benefit_reasons": candidate.get("learned_export_benefit_reason_counts", ""),
        }
    )

    if not finite(cand_ape):
        blockers.append("missing_candidate_ape")
    if init < 1.0:
        blockers.append("init_failed")
    if lost > 0.0:
        blockers.append("lost_tracking")

    role = str(spec.get("texture_role", ""))
    no_harm_role = "normal" in role or "no_harm" in role or "guard" in role
    if no_harm_role:
        if blockers:
            decision = "blocked"
            claim = "none"
        elif learned <= 0.0 and abs_or_small(ape_delta, base_ape, tol_abs=0.003, tol_pct=3.0):
            decision = "keep_no_harm_zero_export"
            claim = "learned sidecars are suppressed and do not change backend input in this control"
        elif learned <= 0.0:
            decision = "no_learned_causal_claim"
            claim = "zero learned export; any trajectory delta is replay/config variation"
        else:
            decision = "unsafe_for_no_harm"
            claim = "none"
            blockers.append("learned_exported_in_no_harm_control")
    else:
        gain_abs = -ape_delta
        gain_pct = -ape_delta_pct if finite(ape_delta_pct) else math.nan
        if blockers:
            decision = "blocked"
            claim = "none"
        elif learned <= 0.0:
            decision = "no_learned_causal_claim"
            claim = "no learned export; cannot attribute improvement to learned methods"
        elif gain_abs >= args.min_ape_gain_abs and finite(gain_pct) and gain_pct >= args.min_ape_gain_pct:
            decision = "keep_learned_positive"
            source = "LoFTR" if loftr > 0 and loftr >= xfeat else "XFeat/SP+LG"
            claim = f"{source} sidecar improves APE under this low-support window"
        elif ape_delta <= 0.0 and rpe_delta <= 0.0:
            decision = "near_tie_supporting_only"
            claim = "learned export is not harmful here, but gain is too small for a main claim"
        else:
            decision = "reject_or_tune_gate"
            claim = "none"
            blockers.append("no_ape_gain")
    row["decision"] = decision
    row["allowed_claim"] = claim
    row["blocker"] = "|".join(blockers)
    return row


def abs_or_small(delta: float, baseline: float, *, tol_abs: float, tol_pct: float) -> bool:
    if not finite(delta):
        return False
    if abs(delta) <= tol_abs:
        return True
    if finite(baseline) and baseline > 0:
        return abs(100.0 * delta / baseline) <= tol_pct
    return False


def infer_dataset(case: str) -> str:
    case = case.lower()
    if "aqualoc" in case or case.startswith("a"):
        return "AQUALOC"
    if "ntnu" in case or "fjord" in case:
        return "NTNU"
    if "afrl" in case:
        return "AFRL"
    if "tank" in case:
        return "Tank"
    return "unknown"


def f(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out


def finite(value: float) -> bool:
    return math.isfinite(value)


def fmt(value: float) -> str:
    return "" if not finite(value) else f"{value:.6f}"


def render_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# May20c Pairwise Learned-Sidecar Decisions",
        "",
        "This table is a conservative decision layer over existing VINS/frontend logs.",
        "A positive learned claim requires nonzero learned export and a matched APE gain.",
        "",
        table(rows),
        "",
        "## Claim Rules",
        "",
        "- `keep_learned_positive`: usable as trajectory evidence.",
        "- `keep_no_harm_zero_export`: usable as normal-texture/no-harm evidence.",
        "- `near_tie_supporting_only`: mention only as boundary/supporting evidence.",
        "- `reject_or_tune_gate`: do not keep this gate/window as evidence.",
        "- `no_learned_causal_claim`: any improvement cannot be attributed to learned methods.",
        "",
    ]
    return "\n".join(lines)


def table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "_No rows._"
    cols = [
        "case",
        "dataset",
        "texture_role",
        "baseline_ape",
        "candidate_ape",
        "ape_delta_pct",
        "exported_learned",
        "exported_xfeat",
        "exported_loftr",
        "decision",
        "blocker",
    ]
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(row.get(col, "")) for col in cols) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
