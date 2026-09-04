from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CsvSpec:
    dataset: str
    csv_path: Path


CAUSE_GROUPS = {
    "low_track_count": {"low_track_count", "few_tracks"},
    "low_grid_coverage": {"low_grid_coverage", "poor_grid_coverage"},
    "low_texture_or_flat": {"low_texture", "very_low_texture", "flat_regions", "mostly_flat", "low_grid_texture"},
    "underwater_visibility": {"underwater_degradation", "backscatter_or_low_contrast", "illumination_nonuniformity"},
    "geometry_degraded": {"low_geometry_inlier_ratio", "high_fb_error"},
    "dropout": {"high_dropout"},
    "track_health": {"low_track_health", "track_health_decline", "persistent_low_track_health"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize quality-guided frontend trigger explainability.")
    parser.add_argument("--spec", action="append", type=_parse_spec, required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()

    mode_rows = []
    cause_rows = []
    reason_rows = []
    geometry_rows = []
    for spec in args.spec:
        df = pd.read_csv(spec.csv_path)
        mode_rows.extend(_mode_rows(spec.dataset, df))
        cause_rows.append(_cause_row(spec.dataset, df))
        reason_rows.extend(_reason_rows(spec.dataset, df))
        geometry_rows.extend(_geometry_rows(spec.dataset, df))

    mode_df = pd.DataFrame(mode_rows)
    cause_df = pd.DataFrame(cause_rows)
    reason_df = pd.DataFrame(reason_rows)
    geometry_df = pd.DataFrame(geometry_rows)

    out = Path(args.output_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    mode_csv = out.with_name(out.name + "_modes.csv")
    cause_csv = out.with_name(out.name + "_causes.csv")
    reason_csv = out.with_name(out.name + "_top_reasons.csv")
    geometry_csv = out.with_name(out.name + "_geometry_modes.csv")
    report_md = out.with_name(out.name + "_report.md")
    mode_df.to_csv(mode_csv, index=False)
    cause_df.to_csv(cause_csv, index=False)
    reason_df.to_csv(reason_csv, index=False)
    geometry_df.to_csv(geometry_csv, index=False)
    report_md.write_text(_make_report(mode_df, cause_df, reason_df, geometry_df), encoding="utf-8")
    print(_make_report(mode_df, cause_df, reason_df, geometry_df))
    print(f"wrote {report_md}")
    return 0


def _parse_spec(raw: str) -> CsvSpec:
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("spec must be dataset:path.csv")
    return CsvSpec(parts[0], Path(parts[1]))


def _mode_rows(dataset: str, df: pd.DataFrame) -> list[dict]:
    total = max(1, len(df))
    rows = []
    for mode, count in df.get("tracker_mode", pd.Series(dtype=object)).value_counts().items():
        rows.append({"dataset": dataset, "tracker_mode": mode, "frames": int(count), "ratio": float(count / total)})
    return rows


def _cause_row(dataset: str, df: pd.DataFrame) -> dict:
    total = max(1, len(df))
    tokens_per_frame = []
    for _, row in df.iterrows():
        tokens = set()
        for col in [
            "tracker_recovery_reason",
            "scheduler_reason",
            "track_health_reason",
            "geometry_reason",
        ]:
            if col in df:
                tokens |= _split_reason(row.get(col, ""))
        tokens_per_frame.append(tokens)
    out = {"dataset": dataset, "frames": len(df)}
    for group, keys in CAUSE_GROUPS.items():
        count = sum(1 for tokens in tokens_per_frame if tokens & keys)
        out[group + "_frames"] = int(count)
        out[group + "_ratio"] = float(count / total)
    return out


def _reason_rows(dataset: str, df: pd.DataFrame, top_k: int = 8) -> list[dict]:
    rows = []
    for col in ["tracker_recovery_reason", "scheduler_reason", "track_health_reason", "geometry_reason"]:
        if col not in df:
            continue
        total = max(1, len(df))
        for reason, count in df[col].value_counts().head(top_k).items():
            rows.append(
                {
                    "dataset": dataset,
                    "field": col,
                    "reason": reason,
                    "frames": int(count),
                    "ratio": float(count / total),
                }
            )
    return rows


def _geometry_rows(dataset: str, df: pd.DataFrame) -> list[dict]:
    if "geometry_mode" not in df:
        return []
    total = max(1, len(df))
    return [
        {
            "dataset": dataset,
            "geometry_mode": mode,
            "frames": int(count),
            "ratio": float(count / total),
        }
        for mode, count in df["geometry_mode"].value_counts().items()
    ]


def _split_reason(value: object) -> set[str]:
    if value is None:
        return set()
    text = str(value)
    if text in {"", "nan", "n/a", "healthy", "disabled"}:
        return set()
    return {item for item in text.replace(";", "+").split("+") if item and item not in {"healthy", "disabled"}}


def _make_report(
    mode_df: pd.DataFrame,
    cause_df: pd.DataFrame,
    reason_df: pd.DataFrame,
    geometry_df: pd.DataFrame,
) -> str:
    lines = ["# Frontend Trigger Explainability", ""]
    lines.append("## Tracker Modes")
    lines.append(_to_markdown(mode_df))
    lines.append("")
    lines.append("## Trigger Cause Families")
    lines.append(_to_markdown(cause_df))
    lines.append("")
    lines.append("## Geometry Modes")
    lines.append(_to_markdown(geometry_df))
    lines.append("")
    lines.append("## Top Raw Reasons")
    lines.append(_to_markdown(reason_df))
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
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
