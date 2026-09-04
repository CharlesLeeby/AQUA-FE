#!/usr/bin/env python3
"""Build a compact backend-evidence table from summarized VINS runs."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", default="logs/backend_evidence_current_with_afrl_v33.csv")
    parser.add_argument("--output-csv", default="logs/backend_evidence_compact.csv")
    parser.add_argument("--output-md", default="logs/backend_evidence_compact.md")
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.input_csv).open(encoding="utf-8")))
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[_labels(row["run"])].append(row)

    compact = [_summarize(window, variant, items) for (window, variant), items in sorted(grouped.items())]
    _write_csv(Path(args.output_csv), compact)
    Path(args.output_md).write_text(_to_markdown(compact), encoding="utf-8")
    print(f"wrote {args.output_csv}")
    print(f"wrote {args.output_md}")
    return 0


def _labels(run: str) -> tuple[str, str]:
    name = run.lower()
    if "a06_2210_2460" in name:
        window = "A06 2210-2460"
    elif "a06_2210_2700" in name:
        window = "A06 2210-2700"
    elif "a06_2210_2900" in name:
        window = "A06 2210-2900"
    elif "h07_1660_1950" in name:
        window = "H07 1660-1950"
    elif "fr_5_55" in name:
        window = "AFRL FR 5-55"
    elif "h07_1740_1820" in name:
        window = "H07 1740-1820"
    else:
        window = "Other"

    if "constq" in name:
        variant = "LoFTR const-q"
    elif "noloftr" in name:
        variant = "no-LoFTR"
    elif "sp_lg_loftr" in name or ("loftr" in name and "klt" not in name):
        variant = "LoFTR sidecar"
    elif "proposed" in name:
        variant = "Proposed"
    elif "klt" in name:
        variant = "KLT"
    else:
        variant = "Other"
    return window, variant


def _summarize(window: str, variant: str, rows: list[dict[str, str]]) -> dict[str, str]:
    def med(key: str) -> float:
        values = [_float(row.get(key)) for row in rows]
        values = [value for value in values if math.isfinite(value)]
        return statistics.median(values) if values else float("nan")

    init_values = [_float(row.get("init_success")) for row in rows]
    init_all = bool(init_values) and all(value >= 1.0 for value in init_values if math.isfinite(value))
    learned = med("exported_learned_features_sum")
    loftr = med("exported_loftr_features_sum")
    status = "baseline_or_ablation"
    if "AFRL" in window or window == "H07 1740-1820":
        status = "boundary_not_trajectory_evidence"
    elif "H07" in window and learned <= 0.0:
        status = "no_harm_control"
    elif learned > 0.0:
        status = "low_texture_positive"
    return {
        "window": window,
        "variant": variant,
        "repeats": str(len(rows)),
        "ape_rmse_median": _fmt(med("se3_ape_rmse_m")),
        "rpe_rmse_median": _fmt(med("rpe_trans_rmse_m")),
        "coverage_median": _fmt(med("output_coverage_ratio")),
        "init_success_all": "1" if init_all else "0",
        "learned_exported_median": _fmt(learned),
        "loftr_exported_median": _fmt(loftr),
        "status": status,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "window",
        "variant",
        "repeats",
        "ape_rmse_median",
        "rpe_rmse_median",
        "coverage_median",
        "init_success_all",
        "learned_exported_median",
        "loftr_exported_median",
        "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _to_markdown(rows: list[dict[str, str]]) -> str:
    fields = [
        "window",
        "variant",
        "repeats",
        "ape_rmse_median",
        "rpe_rmse_median",
        "coverage_median",
        "init_success_all",
        "learned_exported_median",
        "loftr_exported_median",
        "status",
    ]
    lines = ["| " + " | ".join(fields) + " |", "|" + "|".join(["---"] * len(fields)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row.get(field, "") for field in fields) + " |")
    return "\n".join(lines) + "\n"


def _float(value: object) -> float:
    try:
        return float("" if value is None else value)
    except (TypeError, ValueError):
        return float("nan")


def _fmt(value: float) -> str:
    return "" if not math.isfinite(value) else f"{value:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
