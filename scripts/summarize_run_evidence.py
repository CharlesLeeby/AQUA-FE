#!/usr/bin/env python3
"""Summarize whether a VINS run contains real learned/LoFTR backend evidence.

This is intentionally lightweight: it reads the already-written `ape.txt` and
`frontend_metrics.csv` in each run directory and emits one CSV row per run.
When the replayed feature bag carries source channels, it also audits the
observations actually published to VINS.  This distinguishes an exported bag
from a filtered source-removal ablation that reuses the same frontend metrics.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path


APE_KEYS = [
    "se3_ape_rmse_m",
    "se3_ape_median_m",
    "rpe_trans_rmse_m",
    "rpe_trans_median_m",
    "output_coverage_ratio",
    "first_output_delay_s",
    "init_success",
    "tracking_lost_count_proxy",
    "log_linear_solver_failures",
    "log_failure_mentions",
    "log_restart_mentions",
]

METRIC_SUM_KEYS = [
    "exported_features",
    "exported_learned_features",
    "exported_non_loftr_learned_features",
    "exported_sp_lg_features",
    "exported_xfeat_features",
    "exported_loftr_features",
    "exported_recovered_features",
    "learned_candidate_count",
    "learned_confirmed_count",
    "recovered_count",
    "source_selection_dropped",
    "learned_export_gate_degraded",
    "learned_export_gate_dropped",
    "learned_export_geometry_dropped",
    "learned_export_benefit_dropped",
    "init_klt_only_active",
    "low_parallax_learned_holdoff_active",
]

METRIC_MEDIAN_KEYS = [
    "exported_features",
    "median_track_age",
    "median_quality",
    "median_backend_quality",
    "median_classical_backend_quality",
    "median_learned_backend_quality",
    "classical_track_count",
    "classical_grid_coverage",
    "learned_export_grid_gain",
    "learned_export_new_cells",
    "classical_motion_px",
    "classical_median_age",
]

REASON_KEYS = [
    "learned_export_gate_reason",
    "learned_export_benefit_reason",
    "learned_export_geometry_reason",
    "recovery_reason",
    "geometry_mode",
]

FEATURE_TOPIC = "/feature_tracker/feature"
LEARNED_SOURCE_CODES = {10, 20, 30}
LOFTR_SOURCE_CODE = 30
LEARNED_ID_MIN = 10_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True, help="Run directories to summarize.")
    parser.add_argument("--output-csv", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = [summarize_run(Path(item)) for item in args.runs]
    fields = [
        "run_dir",
        "run",
        "has_ape",
        "has_frontend_metrics",
        *APE_KEYS,
        "feature_frames",
        *[f"{key}_sum" for key in METRIC_SUM_KEYS],
        *[f"{key}_median" for key in METRIC_MEDIAN_KEYS],
        *[f"{key}_counts" for key in REASON_KEYS],
        "published_feature_bag",
        "published_feature_bag_audit_status",
        "published_feature_observations",
        "published_learned_observations",
        "published_loftr_observations",
        "learned_really_exported",
        "loftr_really_exported",
        "safe_no_harm_candidate",
        "learned_positive_candidate",
        "warning",
    ]
    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    print(f"wrote {output}")
    print(f"runs={len(rows)}")
    positive = [row for row in rows if row.get("learned_positive_candidate") == "1"]
    no_harm = [row for row in rows if row.get("safe_no_harm_candidate") == "1"]
    print(f"learned_export_candidate_runs={len(positive)} safe_no_harm_candidates={len(no_harm)}")
    return 0


def summarize_run(run_dir: Path) -> dict[str, object]:
    row: dict[str, object] = {
        "run_dir": str(run_dir),
        "run": run_dir.name,
    }
    ape = parse_ape(run_dir / "ape.txt")
    replay_manifest = parse_ape(run_dir / "replay_manifest.txt")
    row["has_ape"] = "1" if ape else "0"
    for key in APE_KEYS:
        row[key] = ape.get(key, "")
    metrics = parse_frontend_metrics(run_dir / "frontend_metrics.csv")
    row.update(metrics)
    feature_bag = (
        ape.get("play_bag", "")
        or ape.get("feature_bag", "")
        or replay_manifest.get("play_bag", "")
        or replay_manifest.get("feature_bag", "")
    )
    if not feature_bag and (run_dir / "features.bag").exists():
        feature_bag = str(run_dir / "features.bag")
    published = audit_published_feature_bag(feature_bag)
    row.update(published)
    learned_sum = as_float(row.get("published_learned_observations"))
    loftr_sum = as_float(row.get("published_loftr_observations"))
    if not finite(learned_sum):
        learned_sum = as_float(row.get("exported_learned_features_sum"))
    if not finite(loftr_sum):
        loftr_sum = as_float(row.get("exported_loftr_features_sum"))
    ape_rmse = as_float(row.get("se3_ape_rmse_m"))
    init = as_float(row.get("init_success"))
    coverage = as_float(row.get("output_coverage_ratio"))
    lost = as_float(row.get("tracking_lost_count_proxy"))
    row["learned_really_exported"] = "1" if learned_sum > 0.0 else "0"
    row["loftr_really_exported"] = "1" if loftr_sum > 0.0 else "0"
    row["safe_no_harm_candidate"] = (
        "1"
        if learned_sum <= 0.0 and finite(ape_rmse) and init >= 1.0 and coverage >= 0.5
        else "0"
    )
    row["learned_positive_candidate"] = (
        "1"
        if learned_sum > 0.0
        and finite(ape_rmse)
        and init >= 1.0
        and coverage >= 0.5
        and lost <= 1.0
        else "0"
    )
    warnings: list[str] = []
    if not ape:
        warnings.append("missing_ape")
    if metrics["has_frontend_metrics"] != "1":
        warnings.append("missing_frontend_metrics")
    if row.get("published_feature_bag_audit_status") == "source_channels_missing":
        warnings.append("published_bag_not_source_auditable")
    if learned_sum > 0.0 and not finite(as_float(row.get("median_learned_backend_quality_median"))):
        warnings.append("learned_export_without_learned_q_median")
    row["warning"] = "|".join(warnings)
    return row


def parse_ape(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            out[key] = value
    return out


def parse_frontend_metrics(path: Path) -> dict[str, object]:
    out: dict[str, object] = {"has_frontend_metrics": "0", "feature_frames": 0}
    for key in METRIC_SUM_KEYS:
        out[f"{key}_sum"] = ""
    for key in METRIC_MEDIAN_KEYS:
        out[f"{key}_median"] = ""
    for key in REASON_KEYS:
        out[f"{key}_counts"] = ""
    if not path.exists():
        return out

    sums = {key: 0.0 for key in METRIC_SUM_KEYS}
    values = {key: [] for key in METRIC_MEDIAN_KEYS}
    counters = {key: Counter() for key in REASON_KEYS}
    frames = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for csv_row in csv.DictReader(handle):
            frames += 1
            for key in METRIC_SUM_KEYS:
                sums[key] += as_float(csv_row.get(key))
            for key in METRIC_MEDIAN_KEYS:
                value = as_float(csv_row.get(key))
                if finite(value):
                    values[key].append(value)
            for key in REASON_KEYS:
                reason = normalize_reason(csv_row.get(key))
                if reason:
                    counters[key][reason] += 1

    out["has_frontend_metrics"] = "1"
    out["feature_frames"] = frames
    for key, value in sums.items():
        out[f"{key}_sum"] = format_float(value)
    for key, items in values.items():
        out[f"{key}_median"] = format_float(median(items)) if items else ""
    for key, counter in counters.items():
        out[f"{key}_counts"] = ";".join(
            f"{reason}:{count}" for reason, count in counter.most_common(8)
        )
    return out


def audit_published_feature_bag(path_value: object) -> dict[str, object]:
    out: dict[str, object] = {
        "published_feature_bag": "" if path_value is None else str(path_value),
        "published_feature_bag_audit_status": "unavailable",
        "published_feature_observations": "",
        "published_learned_observations": "",
        "published_loftr_observations": "",
    }
    path_text = str(path_value).strip() if path_value is not None else ""
    if not path_text:
        return out
    bag_path = Path(path_text)
    if not bag_path.exists():
        out["published_feature_bag_audit_status"] = "missing_bag"
        return out
    try:
        import rosbag
    except ImportError:
        out["published_feature_bag_audit_status"] = "rosbag_import_failed"
        return out

    total = 0
    learned = 0
    loftr = 0
    high_id_learned = 0
    source_channels_seen = False
    try:
        with rosbag.Bag(str(bag_path), "r") as bag:
            for _topic, msg, _stamp in bag.read_messages(topics=[FEATURE_TOPIC]):
                count = len(msg.points)
                total += count
                is_learned = optional_channel_values(msg, "is_learned", count)
                source_code = optional_channel_values(msg, "source_code", count)
                feature_id = optional_channel_values(msg, "id", count)
                if is_learned is not None or source_code is not None:
                    source_channels_seen = True
                for index in range(count):
                    learned_flag = is_learned is not None and float(is_learned[index]) > 0.5
                    code = (
                        int(round(float(source_code[index])))
                        if source_code is not None
                        else 0
                    )
                    if learned_flag or code in LEARNED_SOURCE_CODES:
                        learned += 1
                    if code == LOFTR_SOURCE_CODE:
                        loftr += 1
                    if feature_id is not None and float(feature_id[index]) >= LEARNED_ID_MIN:
                        high_id_learned += 1
    except Exception:
        out["published_feature_bag_audit_status"] = "bag_read_failed"
        return out
    out["published_feature_observations"] = total
    if not source_channels_seen:
        out["published_feature_bag_audit_status"] = (
            "high_id_compat_audited" if high_id_learned > 0 else "source_channels_missing"
        )
        if high_id_learned > 0:
            out["published_learned_observations"] = high_id_learned
            out["published_loftr_observations"] = high_id_learned
        return out
    out["published_feature_bag_audit_status"] = "source_channels_audited"
    out["published_learned_observations"] = learned
    out["published_loftr_observations"] = loftr
    return out


def optional_channel_values(msg: object, name: str, length: int) -> list[float] | None:
    for channel in msg.channels:
        if channel.name == name and len(channel.values) == length:
            return list(channel.values)
    return None


def normalize_reason(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "none", "n/a"}:
        return ""
    return text


def as_float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result


def finite(value: float) -> bool:
    return math.isfinite(value)


def median(items: list[float]) -> float:
    if not items:
        return float("nan")
    ordered = sorted(items)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def format_float(value: float) -> str:
    if not finite(value):
        return ""
    return f"{value:.6g}"


if __name__ == "__main__":
    raise SystemExit(main())
