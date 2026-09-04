#!/usr/bin/env python3
"""Build a compact cross-window report for learned-sidecar VINS evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag-prefix", default="crossv36")
    parser.add_argument(
        "--base-summary",
        default=str(ROOT / "logs/backend_evidence_compact.csv"),
        help="Existing paper-safe A06/H07 repeated evidence table.",
    )
    parser.add_argument(
        "--cross-evidence",
        default="",
        help="Evidence CSV emitted by summarize_run_evidence.py. Defaults to logs/<tag>_a08_a09_evidence.csv.",
    )
    parser.add_argument("--output-csv", default=str(ROOT / "logs/cross_window_learned_validation.csv"))
    parser.add_argument("--output-md", default=str(ROOT / "logs/cross_window_learned_validation.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_path = Path(args.base_summary)
    cross_path = Path(args.cross_evidence) if args.cross_evidence else ROOT / "logs" / f"{args.tag_prefix}_a08_a09_evidence.csv"
    rows = []
    rows.extend(_load_base_rows(base_path))
    rows.extend(_load_cross_rows(cross_path))
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(["window", "variant"]).reset_index(drop=True)

    output_csv = Path(args.output_csv)
    output_md = Path(args.output_md)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_csv, index=False)
    output_md.write_text(_markdown_report(table, base_path, cross_path), encoding="utf-8")
    print(table.to_string(index=False))
    print(f"wrote {output_csv}")
    print(f"wrote {output_md}")
    return 0


def _load_base_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    out = []
    for _, row in df.iterrows():
        variant = str(row.get("variant", ""))
        window = str(row.get("window", ""))
        role = "klt" if variant.lower() in {"klt", "no-loftr"} else "learned_sidecar"
        learned = _float(row.get("learned_exported_median"))
        loftr = _float(row.get("loftr_exported_median"))
        claim = _claim(window, role, _float(row.get("ape_rmse_median")), learned, loftr, str(row.get("status", "")))
        out.append(
            {
                "window": window,
                "variant": variant,
                "role": role,
                "repeats": _int(row.get("repeats")),
                "ape_rmse_median": _float(row.get("ape_rmse_median")),
                "rpe_rmse_median": _float(row.get("rpe_rmse_median")),
                "coverage_median": _float(row.get("coverage_median")),
                "init_success_all": _int(row.get("init_success_all")),
                "learned_exported_median": learned,
                "loftr_exported_median": loftr,
                "claim_bucket": claim,
                "source": _display(path),
            }
        )
    return out


def _load_cross_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    rows = []
    window_tokens = df["run"].astype(str).str.extract(r"(a0[89]_\d+_\d+)")[0]
    for window, sub in df.groupby(window_tokens):
        if not isinstance(window, str):
            continue
        for variant, pattern in [
            ("KLT", "_klt_rep"),
            ("LoFTR sidecar", r"formal_loftr|_loftr_rep"),
        ]:
            group = sub[sub["run"].astype(str).str.contains(pattern, regex=True, na=False)]
            if group.empty:
                continue
            learned = _median(group, "exported_learned_features_sum")
            loftr = _median(group, "exported_loftr_features_sum")
            role = "klt" if variant == "KLT" else "learned_sidecar"
            ape = _median(group, "se3_ape_rmse_m")
            rows.append(
                {
                    "window": window.replace("_", " ").upper(),
                    "variant": variant,
                    "role": role,
                    "repeats": len(group),
                    "ape_rmse_median": ape,
                    "rpe_rmse_median": _median(group, "rpe_trans_rmse_m"),
                    "coverage_median": _median(group, "output_coverage_ratio"),
                    "init_success_all": int((pd.to_numeric(group["init_success"], errors="coerce") == 1).all()),
                    "learned_exported_median": learned,
                    "loftr_exported_median": loftr,
                    "claim_bucket": _claim(window, role, ape, learned, loftr, ""),
                    "source": _display(path),
                }
            )
    return rows


def _claim(window: str, role: str, ape: float, learned: float, loftr: float, status: str) -> str:
    text = f"{window} {status}".lower()
    if role == "klt":
        return "baseline"
    if "h07" in text and learned <= 0:
        return "normal_texture_no_harm"
    if "a06" in text and loftr > 0 and np.isfinite(ape):
        return "low_texture_positive"
    if "a08" in text and loftr > 0:
        return "non_a06_neutral_no_harm"
    if "a09" in text and loftr > 0:
        return "gate_regression_boundary"
    if learned <= 0:
        return "gated_out_no_harm"
    return "exploratory"


def _markdown_report(table: pd.DataFrame, base_path: Path, cross_path: Path) -> str:
    if table.empty:
        return "# Cross-Window Learned-Sidecar Validation\n\nNo input evidence was found.\n"
    view = table.copy()
    for col in ["ape_rmse_median", "rpe_rmse_median", "coverage_median", "learned_exported_median", "loftr_exported_median"]:
        view[col] = view[col].map(_fmt)
    lines = [
        "# Cross-Window Learned-Sidecar Validation",
        "",
        "This table separates positive evidence, no-harm controls, and boundary cases for the learned sidecar.",
        "",
        f"- Base evidence: `{_display(base_path)}`",
        f"- Cross-window evidence: `{_display(cross_path)}`",
        "",
        _to_markdown(
            view[
                [
                    "window",
                    "variant",
                    "repeats",
                    "ape_rmse_median",
                    "rpe_rmse_median",
                    "coverage_median",
                    "learned_exported_median",
                    "loftr_exported_median",
                    "claim_bucket",
                ]
            ]
        ),
        "",
        "Interpretation:",
        "",
        "- A06 remains the strongest low-texture positive: sparse LoFTR observations enter VINS and reduce APE/RPE.",
        "- H07 remains a normal-texture no-harm control: learned export is gated out and the trajectory stays KLT-like.",
        "- A08 4520-4680 is useful as non-A06 no-harm/neutral evidence: sparse LoFTR export does not materially change APE.",
        "- A09 5920-6060 is a boundary case: the old LoFTR6 export does not improve trajectory accuracy, so formal defaults should reject similar non-stable segments unless stricter gates pass.",
        "",
    ]
    return "\n".join(lines)


def _median(df: pd.DataFrame, col: str) -> float:
    if col not in df:
        return float("nan")
    return float(np.nanmedian(pd.to_numeric(df[col], errors="coerce")))


def _to_markdown(df: pd.DataFrame) -> str:
    columns = list(df.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _int(value: object) -> int:
    value = _float(value)
    if not np.isfinite(value):
        return 0
    return int(value)


def _fmt(value: object) -> str:
    value = _float(value)
    if not np.isfinite(value):
        return ""
    return f"{value:.6f}"


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
