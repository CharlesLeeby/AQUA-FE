from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize LoFTR's role as a pairwise planar fallback.")
    parser.add_argument("--table-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    table = pd.read_csv(args.table_csv)
    report = _make_report(table)
    out = Path(args.output_md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {out}")
    return 0


def _make_report(table: pd.DataFrame) -> str:
    rows = []
    win_rows = []
    for dataset in sorted(table["dataset"].unique()):
        subset = table[table["dataset"] == dataset]
        loftr = subset[subset["method"] == "loftr"]
        proposed = subset[subset["method"] == "continuity_optimized"]
        backend = subset[subset["method"] == "backend_strict"]
        if loftr.empty or proposed.empty:
            continue
        loftr_row = loftr.iloc[0]
        prop_row = proposed.iloc[0]
        back_row = backend.iloc[0] if not backend.empty else None
        rows.append(
            {
                "dataset": dataset,
                "loftr_track_age": float(loftr_row["track_age_median"]),
                "proposed_track_age": float(prop_row["track_age_median"]),
                "loftr_dropout": float(loftr_row["dropout_mean"]),
                "proposed_dropout": float(prop_row["dropout_mean"]),
                "loftr_epi": float(loftr_row["epi_error_median"]),
                "backend_epi": float(back_row["epi_error_median"]) if back_row is not None else float("nan"),
                "loftr_f_inlier": float(loftr_row["f_inlier_median"]),
                "backend_f_inlier": float(back_row["f_inlier_median"]) if back_row is not None else float("nan"),
                "loftr_runtime_ms": float(loftr_row["runtime_ms_median"]),
            }
        )
        win_rows.append(
            {
                "dataset": dataset,
                "loftr_shorter_tracks": bool(float(loftr_row["track_age_median"]) < float(prop_row["track_age_median"])),
                "loftr_more_dropout": bool(float(loftr_row["dropout_mean"]) > float(prop_row["dropout_mean"])),
                "loftr_clean_pairwise_geometry": bool(float(loftr_row["f_inlier_median"]) >= 0.90),
            }
        )
    comp = pd.DataFrame(rows)
    wins = pd.DataFrame(win_rows)
    lines = ["# LoFTR Positioning", ""]
    lines.append(
        "LoFTR is evaluated as a strong pairwise/semi-dense matcher, not as the default long-track frontend."
    )
    lines.append("")
    lines.append("## Dataset Comparison")
    lines.append(_to_markdown(comp))
    lines.append("")
    if not wins.empty:
        lines.append("## Summary")
        lines.append(
            f"- LoFTR has shorter median tracks than the proposed continuity frontend on "
            f"{int(wins['loftr_shorter_tracks'].sum())}/{len(wins)} windows."
        )
        lines.append(
            f"- LoFTR has higher mean dropout than the proposed continuity frontend on "
            f"{int(wins['loftr_more_dropout'].sum())}/{len(wins)} windows."
        )
        lines.append(
            f"- LoFTR reaches high pairwise fundamental inlier ratios on "
            f"{int(wins['loftr_clean_pairwise_geometry'].sum())}/{len(wins)} windows."
        )
    lines.append("")
    lines.append("## Paper-Facing Interpretation")
    lines.append(
        "LoFTR should be described as an extreme low-texture or near-planar supplemental matcher. "
        "It can provide geometrically clean frame-pair correspondences, but because those correspondences "
        "are re-associated pairwise, they do not naturally preserve long feature identities. This is why "
        "it is better positioned as a gated fallback rather than as the main VO/VIO frontend."
    )
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
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
