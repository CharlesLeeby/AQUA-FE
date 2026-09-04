#!/usr/bin/env python3
"""Summarize instrumented external-seed lineage and MapPoint survival."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


TRUE_SUMMARY_FIELDS = (
    "phase_conservation",
    "extractor_conservation",
    "accepted_conservation",
    "per_token_conservation",
    "valid_tokens",
    "mappoint_pointer_consistency",
    "mappoint_pointer_key_consistency",
    "atlas_snapshot_available",
)
RUN_METRICS = (
    "lineage_to_mappoint_rate",
    "lineage_with_mappoint_survival_rate",
    "accepted_observation_to_mappoint_rate",
    "mappoint_final_observations_median",
    "mappoint_max_observations_median",
    "mappoint_raw_frame_matches_median",
    "mappoint_frame_matches_median",
    "mappoint_seed_kf_observations_median",
    "mappoint_seed_match_frame_span_median",
    "mappoint_seed_match_duration_s_median",
    "mappoint_found_ratio_median",
    "mappoint_final_kf_observers_median",
    "mappoint_historical_kf_observers_median",
    "mappoint_covisibility_pairs_median",
    "mappoint_covisibility_weight_sum_median",
    "mappoint_covisibility_weight_max_median",
    "reference_lineage_candidates",
    "reference_lineage_accepted",
    "reference_lineage_rejected_occupied",
    "reference_lineage_rejected_depth",
    "reference_lineage_rejected_bounds",
    "reference_lineage_rejected_reprojection",
    "reference_lineage_rejected_descriptor",
    "lineage_cull_grace_events",
    "lineage_cull_grace_observation_erasure_deferred",
    "lineage_cull_grace_low_observation_deferred",
    "lineage_cull_grace_completed",
    "lineage_cull_grace_expired",
)
EVENT_SUMMARY_FIELDS = {
    "phase_attempted": "phase_attempted",
    "phase_skipped": "phase_skipped",
    "extract_accepted": "extractor_accepted",
    "extract_rejected_border": "extractor_rejected_border",
    "extract_rejected_native_duplicate": "extractor_rejected_native_duplicate",
    "extract_rejected_seed_duplicate": "extractor_rejected_seed_duplicate",
    "frame_accepted": "frame_accepted",
    "frame_raw_association": "raw_association_events",
    "frame_final": "frame_final",
}
REFERENCE_DECISION_FIELDS = {
    0: "reference_lineage_accepted",
    1: "reference_lineage_rejected_occupied",
    2: "reference_lineage_rejected_depth",
    3: "reference_lineage_rejected_bounds",
    4: "reference_lineage_rejected_reprojection",
    5: "reference_lineage_rejected_descriptor",
}
LINEAGE_CULL_GRACE_FIELDS = {
    0: "lineage_cull_grace_observation_erasure_deferred",
    1: "lineage_cull_grace_low_observation_deferred",
    2: "lineage_cull_grace_completed",
    3: "lineage_cull_grace_expired",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        metavar="NAME=RUNS_ROOT[,EVALUATOR_CSV]",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def parse_group(value: str) -> tuple[str, Path, Path | None]:
    if "=" not in value:
        raise SystemExit(f"invalid --group {value!r}")
    name, raw_paths = value.split("=", 1)
    parts = raw_paths.split(",", 1)
    runs_root = Path(parts[0]).resolve()
    evaluator_csv = Path(parts[1]).resolve() if len(parts) == 2 else None
    if not name or not runs_root.is_dir():
        raise SystemExit(f"invalid group name or runs root: {value!r}")
    if evaluator_csv is not None and not evaluator_csv.is_file():
        raise SystemExit(f"missing evaluator CSV: {evaluator_csv}")
    return name, runs_root, evaluator_csv


def safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else math.nan


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric_median(frame: pd.DataFrame, field: str) -> float:
    if field not in frame or frame.empty:
        return math.nan
    values = pd.to_numeric(frame[field], errors="coerce").dropna()
    return float(values.median()) if not values.empty else math.nan


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in result:
            raise SystemExit(f"invalid or duplicate manifest line: {path}")
        result[key] = value
    return result


def lineage_ids(value: object) -> set[int]:
    if pd.isna(value) or str(value).strip() == "":
        return set()
    return {int(token) for token in str(value).split(";") if token.strip()}


def validate_cross_artifact_contract(
    run_dir: Path,
    repeat: int,
    summary: dict[str, object],
    events: pd.DataFrame,
    lineages: pd.DataFrame,
    mappoints: pd.DataFrame,
) -> None:
    manifest = parse_manifest(run_dir / "run_manifest.txt")
    if (
        manifest.get("role") != "full"
        or int(manifest.get("repeat", -1)) != repeat
        or manifest.get("seed_audit_enabled") != "1"
        or not manifest.get("seed_file")
        or not manifest.get("seed_sha256")
        or Path(manifest.get("seed_audit_dir", "")).resolve()
        != (run_dir / "instrumentation").resolve()
    ):
        raise SystemExit(f"full run manifest contract failed: {run_dir}")
    required_event_columns = {"event", "lineage_id", "map_id", "mp_id"}
    if not required_event_columns.issubset(events.columns):
        raise SystemExit(f"seed_events.csv missing columns in {run_dir}")
    if len(events) != int(summary["events_recorded"]):
        raise SystemExit(f"event row count disagrees with JSON in {run_dir}")
    event_counts = events["event"].astype(str).value_counts()
    for event, field in EVENT_SUMMARY_FIELDS.items():
        if int(event_counts.get(event, 0)) != int(summary[field]):
            raise SystemExit(f"event count {event} disagrees with JSON in {run_dir}")
    if "reference_lineage_decisions" in summary:
        if "subtype" not in events.columns:
            raise SystemExit(f"reference decision subtype missing in {run_dir}")
        decisions = events[events["event"].astype(str) == "reference_lineage_decision"]
        if len(decisions) != int(summary["reference_lineage_decisions"]):
            raise SystemExit(f"reference decision count disagrees with JSON in {run_dir}")
        subtypes = pd.to_numeric(decisions["subtype"], errors="coerce")
        for subtype, field in REFERENCE_DECISION_FIELDS.items():
            if field not in summary or int((subtypes == subtype).sum()) != int(summary[field]):
                raise SystemExit(f"reference decision subtype {subtype} disagrees in {run_dir}")
        if summary.get("reference_lineage_decision_conservation") is not True:
            raise SystemExit(f"reference decision conservation failed in {run_dir}")
    if "lineage_cull_grace_events" in summary:
        if "subtype" not in events.columns:
            raise SystemExit(f"lineage cull grace subtype missing in {run_dir}")
        grace_events = events[events["event"].astype(str) == "lineage_cull_grace"]
        if len(grace_events) != int(summary["lineage_cull_grace_events"]):
            raise SystemExit(f"lineage cull grace count disagrees with JSON in {run_dir}")
        subtypes = pd.to_numeric(grace_events["subtype"], errors="coerce")
        for subtype, field in LINEAGE_CULL_GRACE_FIELDS.items():
            if field not in summary or int((subtypes == subtype).sum()) != int(summary[field]):
                raise SystemExit(f"lineage cull grace subtype {subtype} disagrees in {run_dir}")
        if summary.get("lineage_cull_grace_conservation") is not True:
            raise SystemExit(f"lineage cull grace conservation failed in {run_dir}")

    required_lineage_columns = {
        "lineage_id",
        "input_observations",
        "attempted",
        "phase_skipped",
        "accepted",
        "unique_mappoints",
        "live_mappoints",
    }
    if not required_lineage_columns.issubset(lineages.columns):
        raise SystemExit(f"seed_lineages.csv missing columns in {run_dir}")
    if lineages["lineage_id"].duplicated().any():
        raise SystemExit(f"duplicate lineage IDs in {run_dir}")
    if len(lineages) != int(summary["lineages"]) or len(lineages) != int(
        summary["seed_lineages_loaded"]
    ):
        raise SystemExit(f"lineage row count disagrees with JSON in {run_dir}")
    sum_contract = {
        "input_observations": "loaded_seed_observations",
        "attempted": "attempted_seed_observations",
        "phase_skipped": "phase_skipped",
        "accepted": "accepted_seed_observations",
    }
    for column, field in sum_contract.items():
        if int(pd.to_numeric(lineages[column]).sum()) != int(summary[field]):
            raise SystemExit(f"lineage sum {column} disagrees with JSON in {run_dir}")
    if int((pd.to_numeric(lineages["accepted"]) > 0).sum()) != int(
        summary["seed_lineages_accepted"]
    ):
        raise SystemExit(f"accepted lineage count disagrees with JSON in {run_dir}")
    if int((pd.to_numeric(lineages["unique_mappoints"]) > 0).sum()) != int(
        summary["seed_lineages_with_mappoint"]
    ):
        raise SystemExit(f"MapPoint lineage count disagrees with JSON in {run_dir}")
    if int((pd.to_numeric(lineages["live_mappoints"]) > 0).sum()) != int(
        summary["seed_lineages_surviving"]
    ):
        raise SystemExit(f"surviving lineage count disagrees with JSON in {run_dir}")

    required_mappoint_columns = {
        "map_id",
        "mp_id",
        "all_lineages",
        "seed_kf_observations",
        "historical_kf_observers",
        "surviving",
    }
    if not required_mappoint_columns.issubset(mappoints.columns):
        raise SystemExit(f"seed_mappoint_summary.csv missing columns in {run_dir}")
    if mappoints.duplicated(["map_id", "mp_id"]).any():
        raise SystemExit(f"duplicate MapPoint keys in {run_dir}")
    if len(mappoints) != int(summary["related_mappoints"]):
        raise SystemExit(f"MapPoint row count disagrees with JSON in {run_dir}")
    known_lineages = set(pd.to_numeric(lineages["lineage_id"]).astype(int))
    referenced_lineages: set[int] = set()
    for value in mappoints["all_lineages"]:
        referenced_lineages.update(lineage_ids(value))
    if not referenced_lineages.issubset(known_lineages):
        raise SystemExit(f"MapPoint CSV references unknown lineage IDs in {run_dir}")
    if int((mappoints["all_lineages"].map(lineage_ids).map(bool)).sum()) != int(
        summary["distinct_mappoints"]
    ):
        raise SystemExit(f"distinct MapPoint count disagrees with JSON in {run_dir}")
    if int(pd.to_numeric(mappoints["historical_kf_observers"]).sum()) != int(
        summary["keyframe_observations"]
    ):
        raise SystemExit(f"keyframe observation sum disagrees with JSON in {run_dir}")


def validate_summary(path: Path, expected_dir: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SystemExit(f"invalid instrumentation schema: {path}")
    if data.get("complete") is not True or data.get("status") != "ok":
        raise SystemExit(f"incomplete instrumentation summary: {path}")
    if Path(str(data.get("output_directory", ""))).resolve() != expected_dir.resolve():
        raise SystemExit(f"instrumentation output_directory mismatch: {path}")
    if data.get("events_overflowed") != 0 or data.get("related_mappoint_overflowed") != 0:
        raise SystemExit(f"instrumentation overflow: {path}")
    failed = [field for field in TRUE_SUMMARY_FIELDS if data.get(field) is not True]
    if failed:
        raise SystemExit(f"instrumentation integrity fields failed {failed}: {path}")
    return data


def load_group(
    name: str, runs_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_rows: list[dict[str, object]] = []
    lineage_frames: list[pd.DataFrame] = []
    mappoint_frames: list[pd.DataFrame] = []
    run_dirs: list[tuple[int, Path]] = []
    for path in runs_root.iterdir():
        match = re.fullmatch(r"full_r(\d+)", path.name)
        if match and path.is_dir():
            run_dirs.append((int(match.group(1)), path.resolve()))
    run_dirs.sort()
    if not run_dirs:
        raise SystemExit(f"no full_rN directories under {runs_root}")

    for repeat, run_dir in run_dirs:
        instrumentation = run_dir / "instrumentation"
        artifacts = {
            name: instrumentation / name
            for name in (
                "seed_events.csv",
                "seed_mappoint_summary.csv",
                "seed_lineages.csv",
                "seed_summary.json",
            )
        }
        if not all(path.is_file() and path.stat().st_size > 0 for path in artifacts.values()):
            raise SystemExit(f"missing or empty instrumentation artifacts: {run_dir}")
        summary = validate_summary(artifacts["seed_summary.json"], instrumentation)
        events = pd.read_csv(artifacts["seed_events.csv"])
        lineages = pd.read_csv(artifacts["seed_lineages.csv"])
        mappoints = pd.read_csv(artifacts["seed_mappoint_summary.csv"])
        validate_cross_artifact_contract(
            run_dir, repeat, summary, events, lineages, mappoints
        )
        lineages.insert(0, "repeat", repeat)
        lineages.insert(0, "group", name)
        lineages["run_dir"] = str(run_dir)
        mappoints.insert(0, "repeat", repeat)
        mappoints.insert(0, "group", name)
        mappoints["run_dir"] = str(run_dir)
        lineage_frames.append(lineages)
        mappoint_frames.append(mappoints)

        accepted_lineages = int(summary["seed_lineages_accepted"])
        mappoint_lineages = int(summary["seed_lineages_with_mappoint"])
        surviving_lineages = int(summary["seed_lineages_surviving"])
        accepted_observations = int(summary["accepted_seed_observations"])
        observations_with_mappoint = int(summary["accepted_observations_with_mappoint"])
        reference_hook = "reference_lineage_decisions" in summary
        reference_counts = {
            field: int(summary.get(field, 0))
            for field in REFERENCE_DECISION_FIELDS.values()
        }
        lineage_grace_hook = "lineage_cull_grace_events" in summary
        lineage_grace_counts = {
            field: int(summary.get(field, 0))
            for field in LINEAGE_CULL_GRACE_FIELDS.values()
        }
        run_rows.append(
            {
                "group": name,
                "repeat": repeat,
                "run_dir": str(run_dir),
                "loaded_seed_observations": int(summary["loaded_seed_observations"]),
                "accepted_seed_observations": accepted_observations,
                "seed_lineages_loaded": int(summary["seed_lineages_loaded"]),
                "seed_lineages_accepted": accepted_lineages,
                "seed_lineages_with_mappoint": mappoint_lineages,
                "seed_lineages_surviving": surviving_lineages,
                "distinct_mappoints": int(summary["distinct_mappoints"]),
                "distinct_keyframes": int(summary["distinct_keyframes"]),
                "lineage_to_mappoint_rate": safe_rate(mappoint_lineages, accepted_lineages),
                "lineage_with_mappoint_survival_rate": safe_rate(
                    surviving_lineages, mappoint_lineages
                ),
                "accepted_observation_to_mappoint_rate": safe_rate(
                    observations_with_mappoint, accepted_observations
                ),
                "mappoint_final_observations_median": numeric_median(
                    mappoints, "final_observations"
                ),
                "mappoint_max_observations_median": numeric_median(
                    mappoints, "max_observations"
                ),
                "mappoint_raw_frame_matches_median": numeric_median(
                    mappoints, "raw_frame_matches"
                ),
                "mappoint_frame_matches_median": numeric_median(mappoints, "frame_matches"),
                "mappoint_seed_kf_observations_median": numeric_median(
                    mappoints, "seed_kf_observations"
                ),
                "mappoint_seed_match_frame_span_median": numeric_median(
                    mappoints, "seed_match_frame_span"
                ),
                "mappoint_seed_match_duration_s_median": numeric_median(
                    mappoints, "seed_match_duration_s"
                ),
                "mappoint_found_ratio_median": numeric_median(mappoints, "found_ratio"),
                "mappoint_final_kf_observers_median": numeric_median(
                    mappoints, "final_kf_observers"
                ),
                "mappoint_historical_kf_observers_median": numeric_median(
                    mappoints, "historical_kf_observers"
                ),
                "mappoint_covisibility_pairs_median": numeric_median(
                    mappoints, "covisibility_pairs"
                ),
                "mappoint_covisibility_weight_sum_median": numeric_median(
                    mappoints, "covisibility_weight_sum"
                ),
                "mappoint_covisibility_weight_max_median": numeric_median(
                    mappoints, "covisibility_weight_max"
                ),
                "reference_lineage_candidates": int(
                    summary.get("reference_lineage_decisions", 0)
                ),
                **reference_counts,
                "reference_lineage_decision_hook_complete": int(reference_hook),
                "lineage_cull_grace_events": int(
                    summary.get("lineage_cull_grace_events", 0)
                ),
                **lineage_grace_counts,
                "lineage_cull_grace_hook_complete": int(lineage_grace_hook),
                "raw_association_hook_complete": 0,
                "raw_association_limitation": (
                    "motion_model_early_match_threshold_not_hooked"
                    if reference_hook
                    else "early_match_threshold_returns_not_hooked"
                ),
                "cross_artifact_integrity_ok": 1,
            }
        )
    return (
        pd.DataFrame(run_rows),
        pd.concat(lineage_frames, ignore_index=True),
        pd.concat(mappoint_frames, ignore_index=True),
    )


def evaluator_wins(path: Path | None, runs_root: Path) -> dict[str, object]:
    empty = {
        "full_vs_orb_pairs": math.nan,
        "full_vs_orb_double_wins": math.nan,
        "full_vs_drop_pairs": math.nan,
        "full_vs_drop_double_wins": math.nan,
        "full_vs_bridge_off_pairs": math.nan,
        "full_vs_bridge_off_double_wins": math.nan,
    }
    if path is None:
        return empty
    frame = pd.read_csv(path)
    required_columns = {
        "role",
        "repeat",
        "run_dir",
        "coverage_ratio",
        "ape_rmse_m",
        "rpe_rmse_m",
    }
    if not required_columns.issubset(frame.columns):
        missing = sorted(required_columns.difference(frame.columns))
        raise SystemExit(f"evaluator CSV missing columns {missing}: {path}")

    frame = frame.copy()
    frame["role"] = frame["role"].astype(str)
    frame["repeat"] = frame["repeat"].astype(int)
    if frame.duplicated(["role", "repeat"]).any():
        raise SystemExit(f"duplicate evaluator role/repeat rows: {path}")

    allowed_roles = {
        "orb_only",
        "drop",
        "full_bridge_off",
        "full_lineage_no_grace",
        "full",
    }
    unexpected_roles = sorted(set(frame["role"]).difference(allowed_roles))
    if unexpected_roles:
        raise SystemExit(f"unexpected evaluator roles {unexpected_roles}: {path}")

    required_roles = ("orb_only", "drop", "full")
    repeat_sets = {
        role: set(frame.loc[frame["role"] == role, "repeat"].tolist())
        for role in required_roles
    }
    expected_repeats = repeat_sets["full"]
    if not expected_repeats or any(
        repeats != expected_repeats for repeats in repeat_sets.values()
    ):
        raise SystemExit(f"incomplete evaluator matrix: {path}")
    for optional_role in ("full_bridge_off", "full_lineage_no_grace"):
        optional_repeats = set(
            frame.loc[frame["role"] == optional_role, "repeat"].tolist()
        )
        if optional_repeats and optional_repeats != expected_repeats:
            raise SystemExit(f"incomplete evaluator matrix: {path}")

    for row in frame.itertuples(index=False):
        expected_dir = (runs_root / f"{row.role}_r{int(row.repeat)}").resolve()
        if Path(str(row.run_dir)).resolve() != expected_dir:
            raise SystemExit(f"evaluator run_dir does not match runs root: {path}")
    indexed = frame.set_index(["role", "repeat"])
    result: dict[str, object] = {}
    baselines = [("orb", "orb_only"), ("drop", "drop")]
    if "full_bridge_off" in set(frame["role"]):
        baselines.append(("bridge_off", "full_bridge_off"))
    for label, baseline in baselines:
        pairs = wins = 0
        for repeat in sorted(expected_repeats):
            full = indexed.loc[("full", repeat)]
            control = indexed.loc[(baseline, repeat)]
            if not math.isclose(
                float(full.coverage_ratio),
                float(control.coverage_ratio),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                continue
            pairs += 1
            wins += int(
                float(full.ape_rmse_m) < float(control.ape_rmse_m)
                and float(full.rpe_rmse_m) < float(control.rpe_rmse_m)
            )
        result[f"full_vs_{label}_pairs"] = pairs
        result[f"full_vs_{label}_double_wins"] = wins
    for field, value in empty.items():
        result.setdefault(field, value)
    return result


def group_summary(per_run: pd.DataFrame, win_rows: dict[str, dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, frame in per_run.groupby("group", sort=False):
        row: dict[str, object] = {
            "group": name,
            "runs": len(frame),
            "all_integrity_checks_ok": int(
                (frame["cross_artifact_integrity_ok"] == 1).all()
            ),
            "raw_association_hook_complete": 0,
            "reference_lineage_decision_hook_complete": int(
                (frame["reference_lineage_decision_hook_complete"] == 1).all()
            ),
            "lineage_cull_grace_hook_complete": int(
                (frame["lineage_cull_grace_hook_complete"] == 1).all()
            ),
            **win_rows[name],
        }
        for metric in RUN_METRICS:
            values = pd.to_numeric(frame[metric], errors="coerce").dropna().to_numpy(dtype=float)
            row[f"{metric}_median"] = float(np.median(values)) if len(values) else math.nan
            row[f"{metric}_q1"] = float(np.quantile(values, 0.25)) if len(values) else math.nan
            row[f"{metric}_q3"] = float(np.quantile(values, 0.75)) if len(values) else math.nan
            row[f"{metric}_min"] = float(np.min(values)) if len(values) else math.nan
            row[f"{metric}_max"] = float(np.max(values)) if len(values) else math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, output: Path) -> None:
    lines = [
        "# ORB-SLAM3 seed MapPoint survival 诊断",
        "",
        "该汇总只描述 lineage/MapPoint 进入、匹配与最终 Atlas 状态。reference-KF lineage",
        "候选有独立完整决策事件；motion-model 仍漏记低于最小匹配阈值直接返回的失败帧，",
        "因此全局 raw-match 数仍是下界，不能用于完整漏斗结论。",
        "",
        "| group | runs | lineage→MP | conditional lineage survival | ref cand/accept | grace events/expired | final obs | match span | duration s | found ratio | final KF | covis max | full 双胜 ORB/drop/bridge-off |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        orb = f"{int(row.full_vs_orb_double_wins)}/{int(row.full_vs_orb_pairs)}" if math.isfinite(row.full_vs_orb_pairs) else "-"
        drop = f"{int(row.full_vs_drop_double_wins)}/{int(row.full_vs_drop_pairs)}" if math.isfinite(row.full_vs_drop_pairs) else "-"
        bridge_off = f"{int(row.full_vs_bridge_off_double_wins)}/{int(row.full_vs_bridge_off_pairs)}" if math.isfinite(row.full_vs_bridge_off_pairs) else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.group),
                    str(int(row.runs)),
                    f"{row.lineage_to_mappoint_rate_median:.3f}",
                    f"{row.lineage_with_mappoint_survival_rate_median:.3f}",
                    f"{row.reference_lineage_candidates_median:.1f}/{row.reference_lineage_accepted_median:.1f}",
                    f"{row.lineage_cull_grace_events_median:.1f}/{row.lineage_cull_grace_expired_median:.1f}",
                    f"{row.mappoint_final_observations_median_median:.1f}",
                    f"{row.mappoint_seed_match_frame_span_median_median:.1f}",
                    f"{row.mappoint_seed_match_duration_s_median_median:.3f}",
                    f"{row.mappoint_found_ratio_median_median:.4f}",
                    f"{row.mappoint_final_kf_observers_median_median:.1f}",
                    f"{row.mappoint_covisibility_weight_max_median_median:.1f}",
                    f"{orb} / {drop} / {bridge_off}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "MapPoint survival 本身不是充分条件：必须与同批 counterbalanced full/drop/ORB-only",
            "轨迹收益一起解释，不能把 surviving MapPoint 自动写成后端有效贡献。",
            "表中 rate 是 per-run rate 的中位数；MapPoint 数值先取 run 内中位数，再跨 run 取中位数，",
            "不是 pooled-observation 统计。conditional lineage survival 的分母仅含已形成 MapPoint 的 lineage。",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_frames: list[pd.DataFrame] = []
    lineage_frames: list[pd.DataFrame] = []
    mappoint_frames: list[pd.DataFrame] = []
    wins: dict[str, dict[str, object]] = {}
    input_manifest: list[dict[str, object]] = []
    for raw_group in args.group:
        name, runs_root, evaluator_csv = parse_group(raw_group)
        per_run, per_lineage, per_mappoint = load_group(name, runs_root)
        run_frames.append(per_run)
        lineage_frames.append(per_lineage)
        mappoint_frames.append(per_mappoint)
        wins[name] = evaluator_wins(evaluator_csv, runs_root)
        artifact_paths = sorted(
            [
                path
                for run_dir in runs_root.glob("full_r*")
                for path in (
                    run_dir / "run_manifest.txt",
                    run_dir / "instrumentation" / "seed_events.csv",
                    run_dir / "instrumentation" / "seed_mappoint_summary.csv",
                    run_dir / "instrumentation" / "seed_lineages.csv",
                    run_dir / "instrumentation" / "seed_summary.json",
                )
            ]
        )
        input_manifest.append(
            {
                "group": name,
                "runs_root": str(runs_root),
                "evaluator_csv": str(evaluator_csv) if evaluator_csv else "",
                "evaluator_csv_sha256": file_sha256(evaluator_csv)
                if evaluator_csv
                else "",
                "artifact_sha256": {
                    str(path): file_sha256(path) for path in artifact_paths
                },
            }
        )
    per_run = pd.concat(run_frames, ignore_index=True)
    per_lineage = pd.concat(lineage_frames, ignore_index=True)
    per_mappoint = pd.concat(mappoint_frames, ignore_index=True)
    summary = group_summary(per_run, wins)
    per_run.to_csv(output / "mappoint_survival_per_run.csv", index=False, float_format="%.12g")
    per_lineage.to_csv(
        output / "mappoint_survival_per_lineage.csv", index=False, float_format="%.12g"
    )
    per_mappoint.to_csv(
        output / "mappoint_survival_per_mappoint.csv", index=False, float_format="%.12g"
    )
    summary.to_csv(output / "mappoint_survival_group_summary.csv", index=False, float_format="%.12g")
    write_report(summary, output / "mappoint-survival-diagnostic.md")
    script_path = Path(__file__).resolve()
    output_names = [
        "mappoint_survival_per_run.csv",
        "mappoint_survival_per_lineage.csv",
        "mappoint_survival_per_mappoint.csv",
        "mappoint_survival_group_summary.csv",
        "mappoint-survival-diagnostic.md",
    ]
    (output / "mappoint_survival_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": [str(script_path), *sys.argv[1:]],
                "analyzer_sha256": file_sha256(script_path),
                "inputs": input_manifest,
                "output_sha256": {
                    name: file_sha256(output / name) for name in output_names
                },
                "raw_association_hook_complete": False,
                "reference_lineage_decision_hook_complete": bool(
                    (summary["reference_lineage_decision_hook_complete"] == 1).all()
                ),
                "lineage_cull_grace_hook_complete": bool(
                    (summary["lineage_cull_grace_hook_complete"] == 1).all()
                ),
                "all_cross_artifact_integrity_checks_ok": bool(
                    (summary["all_integrity_checks_ok"] == 1).all()
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote MapPoint survival diagnostics to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
