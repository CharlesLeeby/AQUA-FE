#!/usr/bin/env python3
"""Build a matched protected-KLT vs XFeat-sidecar comparison table.

The input is the CSV produced by scripts/summarize_run_evidence.py for
scripts/run_afrl_lowtexture_support_xfeat_validation.sh with RUN_VARIANTS=pair.
Rows are paired by the FR window label embedded in the run name.  This avoids
mixing plain KLT runs with the protected sidecar export contract.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path


WINDOW_RE = re.compile(r"(fr\d+_\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = list(csv.DictReader(Path(args.input_csv).open(newline="", encoding="utf-8")))
    grouped: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        run = row.get("run", "")
        match = WINDOW_RE.search(run)
        if not match:
            continue
        window = match.group(1)
        if "protected_klt" in run or "external_klt" in run:
            kind = "klt"
        elif "hybrid_xfeat" in run or run.endswith("_export"):
            kind = "xfeat"
        else:
            continue
        grouped.setdefault(window, {})[kind] = row

    out_rows = []
    for window in sorted(grouped, key=window_key):
        pair = grouped[window]
        klt = pair.get("klt")
        xfeat = pair.get("xfeat")
        if not klt or not xfeat:
            out_rows.append({"window": window, "decision": "missing_pair"})
            continue
        klt_ape = f(klt.get("se3_ape_rmse_m"))
        xfeat_ape = f(xfeat.get("se3_ape_rmse_m"))
        klt_rpe = f(klt.get("rpe_trans_rmse_m"))
        xfeat_rpe = f(xfeat.get("rpe_trans_rmse_m"))
        learned_obs = f(xfeat.get("published_learned_observations"))
        exact_decision = decide(klt_ape, xfeat_ape, klt_rpe, xfeat_rpe, learned_obs)
        out_rows.append(
            {
                "window": window,
                "klt_run": klt.get("run", ""),
                "xfeat_run": xfeat.get("run", ""),
                "klt_ape": fmt(klt_ape),
                "xfeat_ape": fmt(xfeat_ape),
                "ape_delta": fmt(xfeat_ape - klt_ape),
                "ape_rel_pct": fmt(rel_pct(klt_ape, xfeat_ape)),
                "klt_rpe": fmt(klt_rpe),
                "xfeat_rpe": fmt(xfeat_rpe),
                "rpe_delta": fmt(xfeat_rpe - klt_rpe),
                "rpe_rel_pct": fmt(rel_pct(klt_rpe, xfeat_rpe)),
                "published_xfeat_obs": fmt(f(xfeat.get("published_learned_observations"))),
                "published_loftr_obs": fmt(f(xfeat.get("published_loftr_observations"))),
                "x_feature_frames": xfeat.get("feature_frames", ""),
                "klt_init_success": klt.get("init_success", ""),
                "xfeat_init_success": xfeat.get("init_success", ""),
                "klt_lost_proxy": klt.get("tracking_lost_count_proxy", ""),
                "xfeat_lost_proxy": xfeat.get("tracking_lost_count_proxy", ""),
                "decision": exact_decision,
            }
        )

    fields = [
        "window",
        "klt_run",
        "xfeat_run",
        "klt_ape",
        "xfeat_ape",
        "ape_delta",
        "ape_rel_pct",
        "klt_rpe",
        "xfeat_rpe",
        "rpe_delta",
        "rpe_rel_pct",
        "published_xfeat_obs",
        "published_loftr_obs",
        "x_feature_frames",
        "klt_init_success",
        "xfeat_init_success",
        "klt_lost_proxy",
        "xfeat_lost_proxy",
        "decision",
    ]
    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in out_rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    print(f"wrote {output}")
    return 0


def window_key(item: str) -> tuple[int, int, str]:
    match = re.match(r"fr(\d+)_(\d+)$", item)
    if not match:
        return (10**9, 10**9, item)
    return (int(match.group(1)), int(match.group(2)), item)


def f(value: object) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def fmt(value: float) -> str:
    if not math.isfinite(value):
        return ""
    return f"{value:.6f}"


def rel_pct(base: float, value: float) -> float:
    if not math.isfinite(base) or not math.isfinite(value) or abs(base) < 1e-12:
        return math.nan
    return (base - value) / base * 100.0


def decide(klt_ape: float, xfeat_ape: float, klt_rpe: float, xfeat_rpe: float, learned_obs: float) -> str:
    if not all(math.isfinite(v) for v in (klt_ape, xfeat_ape, klt_rpe, xfeat_rpe)):
        return "missing_metrics"
    if learned_obs <= 0.0:
        return "no_export_no_harm" if xfeat_ape <= klt_ape * 1.002 and xfeat_rpe <= klt_rpe * 1.002 else "no_export_contract_drift"
    ape_gain = klt_ape - xfeat_ape
    rpe_gain = klt_rpe - xfeat_rpe
    ape_tol = max(0.001, 0.003 * klt_ape)
    rpe_tol = max(0.0005, 0.003 * klt_rpe)
    if ape_gain > ape_tol and rpe_gain >= -rpe_tol:
        return "positive"
    if ape_gain >= -ape_tol and rpe_gain >= -rpe_tol:
        return "no_harm_guardrail"
    if ape_gain > ape_tol and rpe_gain < -rpe_tol:
        return "mixed_ape_positive"
    return "negative"


if __name__ == "__main__":
    raise SystemExit(main())
