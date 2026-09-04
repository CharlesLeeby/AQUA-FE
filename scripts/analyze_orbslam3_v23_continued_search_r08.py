#!/usr/bin/env python3
"""Build the R08 evidence bundle for three continued ORB-v23 search windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
DEFAULT_OUTPUT = (
    WORKSPACE
    / "papers/orb_v23_continued_search_r08_20260806/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_h05_followup_20260805/analysis-output/window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_continued_search_r08_20260806/analysis-output/analysis-report.md"
)

ROLES = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
REPEATS = (1, 2, 3, 4)
EXPECTED_ORDERS = {
    1: "orb_only drop full_bridge_off full_unbounded full",
    2: "orb_only drop full_bridge_off full_unbounded full",
    3: "orb_only drop full_bridge_off full_unbounded full",
    4: "orb_only drop full_bridge_off full full_unbounded",
}
TRAJECTORY_PATTERNS = {
    "reconstructed": "f_*.txt",
    "online": "online_f_*.txt",
    "keyframe": "kf_*.txt",
}
COUNTER_FIELDS = (
    "loaded_seed_observations",
    "attempted_seed_observations",
    "accepted_seed_observations",
    "seed_lineages_loaded",
    "seed_lineages_accepted",
    "seed_lineages_with_mappoint",
    "seed_lineages_surviving",
    "accepted_observations_with_mappoint",
    "distinct_mappoints",
    "keyframe_observations",
    "lineage_assisted_matches_consumed",
    "lineage_assisted_outliers_observed",
    "lineage_pre_kf_outlier_purge_scans",
    "lineage_pre_kf_assisted_outliers_observed",
    "lineage_pre_kf_assisted_outliers_purged",
    "events_overflowed",
    "related_mappoint_overflowed",
    "phase_conservation",
    "extractor_conservation",
    "accepted_conservation",
    "per_token_conservation",
    "valid_tokens",
    "mappoint_pointer_consistency",
    "mappoint_pointer_key_consistency",
    "atlas_snapshot_available",
)


def formal(path: str) -> Path:
    return DATA_ROOT / path


WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "AFRL_Cemetery_FR_25_45",
        "dataset": "AFRL",
        "sequence": "Cemetery-FR",
        "window": "s25_d20",
        "level": "action_positive_metric_mixed_native_negative_noharm",
        "selector_name": "n3_d14_min8_ignore0_clean",
        "texture_profile": "operational degraded/low-grid",
        "base_klt_profile": "upstream 350-target; exported classical control 171-180",
        "operational_low_texture": True,
        "sparse_base_klt_low_texture": False,
        "formal_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260805/"
            "afrl_cemetery_fr25_45/"
            "formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
            "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
        ),
        "stats": formal(
            "online_positive_search_20260805/afrl_cemetery_fr25_45/"
            "clean_ignore0_frozen_v3/stats.csv"
        ),
        "selector_root": formal(
            "orbslam3_seeded_validation/multilineage/afrl_cemetery_fr25_45/"
            "n3_d14_min8_ignore0_clean_20260805"
        ),
        "seed_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260805/"
            "afrl_cemetery_fr25_45/assets_n3_d14_min8_ignore0_clean"
        ),
        "dataset_root": formal(
            "orbslam3_validation/afrl_cemetery_fr25_45_clean_20260805/dataset"
        ),
        "raw_bag": formal(
            "datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag"
        ),
        "historical_bag": formal(
            "logs/afrl_cave_v31/"
            "external_hybrid_xfeat_every2_may29_active_v5_afrl_fr25_45_probe/"
            "features.bag"
        ),
        "camera_config": formal(
            "logs/afrl_cave_v31/"
            "external_hybrid_xfeat_every2_may29_active_v5_afrl_fr25_45_probe/"
            "afrl_cave_cam0_pinhole.yaml"
        ),
        "orb_config": WORKSPACE
        / "logs/orbslam3_validation/afrl_cemetery_fr_cam1_half_mono.yaml",
        "rpe_delta": 20,
        "rpe_label": "20-associated-pose",
        "association_s": 0.06,
    },
    {
        "window_id": "A08_0_400",
        "dataset": "AQUALOC",
        "sequence": "A08",
        "window": "0-400",
        "level": "action_positive_metric_mixed_native_negative_noharm",
        "selector_name": "n3_d14_min8_ignore0_clean",
        "texture_profile": "normal/mixed",
        "base_klt_profile": "near-saturated 323-350",
        "operational_low_texture": False,
        "sparse_base_klt_low_texture": False,
        "formal_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260805/"
            "aqualoc_a08_0_400/"
            "formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
            "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
        ),
        "stats": formal(
            "online_positive_search_20260805/aqualoc_a08_0_400/"
            "clean_ignore0/stats.csv"
        ),
        "selector_root": formal(
            "orbslam3_seeded_validation/multilineage/aqualoc_a08_0_400/"
            "n3_d14_min8_ignore0_clean_20260805"
        ),
        "seed_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260805/"
            "aqualoc_a08_0_400/assets_n3_d14_min8_ignore0_clean"
        ),
        "dataset_root": formal(
            "orbslam3_validation/aqualoc_a08_0_400_clean_20260805/dataset"
        ),
        "raw_bag": formal("datasets/aqualoc/rosbags/archaeo08_0_400.bag"),
        "historical_bag": formal(
            "logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul15screen7_a08_0_400_probe/"
            "features.bag"
        ),
        "camera_config": formal(
            "logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul15screen7_a08_0_400_probe/"
            "aqualoc_archaeo08_pinhole.yaml"
        ),
        "orb_config": WORKSPACE
        / "logs/orbslam3_validation/aqualoc_archaeo_mono.yaml",
        "rpe_delta": 1,
        "rpe_label": "1-associated-pose",
        "association_s": 0.06,
    },
    {
        "window_id": "A02_5600_6000",
        "dataset": "AQUALOC",
        "sequence": "A02",
        "window": "5600-6000",
        "level": "project_strict_bridge_off_and_unbounded_caveat",
        "selector_name": "n3_d14_min8_ignore0_clean",
        "texture_profile": "operational degraded/low-grid",
        "base_klt_profile": "near-saturated 322-350",
        "operational_low_texture": True,
        "sparse_base_klt_low_texture": False,
        "formal_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
            "aqualoc_a02_5600_6000/"
            "formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
            "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
        ),
        "stats": formal(
            "online_positive_search_20260806/aqualoc_a02_5600_6000/"
            "clean_ignore0/stats.csv"
        ),
        "selector_root": formal(
            "orbslam3_seeded_validation/multilineage/aqualoc_a02_5600_6000/"
            "n3_d14_min8_ignore0_clean_20260806"
        ),
        "seed_root": formal(
            "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
            "aqualoc_a02_5600_6000/assets_n3_d14_min8_ignore0_clean"
        ),
        "dataset_root": formal(
            "orbslam3_validation/aqualoc_a02_5600_6000_clean_20260806/dataset"
        ),
        "raw_bag": formal("datasets/aqualoc/rosbags/archaeo02_5600_6000.bag"),
        "historical_bag": formal(
            "logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul15screen5_a02_5600_6000_probe/"
            "features.bag"
        ),
        "camera_config": formal(
            "logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul15screen5_a02_5600_6000_probe/"
            "aqualoc_archaeo02_pinhole.yaml"
        ),
        "orb_config": WORKSPACE
        / "logs/orbslam3_validation/aqualoc_archaeo_mono.yaml",
        "rpe_delta": 1,
        "rpe_label": "1-associated-pose",
        "association_s": 0.06,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing empty CSV: {path}")
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_manifest(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
        for key, value in (line.split("=", 1),)
    }


def one_file(directory: Path, pattern: str) -> Path:
    matches = [
        path for path in directory.glob(pattern) if not path.name.endswith("_sec.txt")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern} in {directory}, got {matches}")
    return matches[0]


def verify_snapshot(path: Path) -> int:
    count = 0
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        candidate = (path.parent / relative).resolve()
        if not candidate.is_file() or sha256(candidate) != expected:
            raise RuntimeError(f"snapshot mismatch: {candidate}")
        count += 1
    return count


def improvement(control: float, full_value: float) -> float:
    return (control - full_value) / control * 100.0


def evaluate_window(config: dict[str, Any]) -> dict[str, Any]:
    root: Path = config["formal_root"]
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]] = {}
    for kind in ("reconstructed", "online"):
        path = root / f"evaluation_{kind}.csv"
        rows = read_csv(path)
        lookup = {(row["role"], int(row["repeat"])): row for row in rows}
        expected = {(role, repeat) for role in ROLES for repeat in REPEATS}
        if len(rows) != 20 or set(lookup) != expected:
            raise RuntimeError(f"incomplete {kind} grid: {root}")
        if any(row["status"] != "ok" for row in rows):
            raise RuntimeError(f"non-ok {kind} evaluation: {root}")
        evaluations[kind] = lookup

    counter_signatures: dict[str, set[tuple[Any, ...]]] = {
        role: set() for role in ROLES
    }
    trajectory_hashes = {
        kind: {role: set() for role in ROLES} for kind in TRAJECTORY_PATTERNS
    }
    action: dict[str, dict[str, Any]] = {}
    snapshot_entries = 0
    snapshot_counts: Counter[int] = Counter()
    for repeat in REPEATS:
        for role in ROLES:
            run = root / f"{role}_r{repeat}"
            manifest = parse_manifest(run / "run_manifest.txt")
            if manifest.get("role_order") != EXPECTED_ORDERS[repeat]:
                raise RuntimeError(f"wrong role order: {run}")
            summary = json.loads(
                (run / "instrumentation/seed_summary.json").read_text(encoding="utf-8")
            )
            if summary.get("complete") is not True or summary.get("status") != "ok":
                raise RuntimeError(f"incomplete audit: {run}")
            signature = tuple(summary[field] for field in COUNTER_FIELDS)
            counter_signatures[role].add(signature)
            if repeat == 1:
                lineages = read_csv(run / "instrumentation/seed_lineages.csv")
                action[role] = {
                    "attempted": int(summary["attempted_seed_observations"]),
                    "accepted": int(summary["accepted_seed_observations"]),
                    "pre_init_attempted": sum(
                        int(row["pre_init_attempted"]) for row in lineages
                    ),
                    "post_init_attempted": sum(
                        int(row["post_init_attempted"]) for row in lineages
                    ),
                    "post_init_accepted": sum(
                        int(row["post_init_accepted"]) for row in lineages
                    ),
                    "mappoint_lineages": int(summary["seed_lineages_with_mappoint"]),
                    "distinct_mappoints": int(summary["distinct_mappoints"]),
                    "matches": int(summary["lineage_assisted_matches_consumed"]),
                    "outliers": int(summary["lineage_assisted_outliers_observed"]),
                    "pre_kf_observed": int(
                        summary["lineage_pre_kf_assisted_outliers_observed"]
                    ),
                    "pre_kf_purged": int(
                        summary["lineage_pre_kf_assisted_outliers_purged"]
                    ),
                    "scans": int(summary["lineage_pre_kf_outlier_purge_scans"]),
                }
            for kind, pattern in TRAJECTORY_PATTERNS.items():
                trajectory_hashes[kind][role].add(sha256(one_file(run, pattern)))
            count = verify_snapshot(run / "provenance/snapshot_sha256.txt")
            snapshot_entries += count
            snapshot_counts[count] += 1

    if any(len(items) != 1 for items in counter_signatures.values()):
        raise RuntimeError(f"counter nondeterminism: {root}")
    for kinds in trajectory_hashes.values():
        if any(len(items) != 1 for items in kinds.values()):
            raise RuntimeError(f"trajectory nondeterminism: {root}")
    if snapshot_entries != 576 or snapshot_counts != Counter({28: 4, 29: 16}):
        raise RuntimeError(
            f"unexpected snapshot contract: {root}: {snapshot_entries}, {snapshot_counts}"
        )

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for kind, lookup in evaluations.items():
        metrics[kind] = {}
        for role in ROLES:
            rows = [lookup[(role, repeat)] for repeat in REPEATS]
            ape = {float(row["ape_rmse_m"]) for row in rows}
            rpe = {float(row["rpe_rmse_m"]) for row in rows}
            if len(ape) != 1 or len(rpe) != 1:
                raise RuntimeError(f"metric nondeterminism: {root}, {kind}, {role}")
            metrics[kind][role] = {"ape": ape.pop(), "rpe": rpe.pop()}

    improvements: dict[str, dict[str, float]] = {}
    for control in ("orb_only", "drop", "full_bridge_off", "full_unbounded"):
        changes: dict[str, float] = {}
        for kind in ("reconstructed", "online"):
            for metric in ("ape", "rpe"):
                changes[f"{kind}_{metric}"] = improvement(
                    metrics[kind][control][metric], metrics[kind]["full"][metric]
                )
        improvements[control] = changes

    stats = read_csv(config["stats"])
    base_tracks = [float(row["base_tracks"]) for row in stats]
    base_grid = [float(row["base_grid_coverage"]) for row in stats]
    seeds = [
        line.split()
        for line in (config["seed_root"] / "full_seeds.txt")
        .read_text(encoding="ascii")
        .splitlines()
        if line and not line.startswith("#")
    ]
    qualities = [float(row[4]) for row in seeds]
    native = evaluations["reconstructed"][("orb_only", 1)]

    return {
        "config": config,
        "action": action,
        "metrics": metrics,
        "improvements": improvements,
        "counter_signatures": {role: len(items) for role, items in counter_signatures.items()},
        "trajectory_hashes": {
            kind: {role: len(items) for role, items in roles.items()}
            for kind, roles in trajectory_hashes.items()
        },
        "snapshot_entries": snapshot_entries,
        "snapshot_counts": dict(snapshot_counts),
        "frontend_frames": len(stats),
        "base_track_min": min(base_tracks),
        "base_track_mean": statistics.mean(base_tracks),
        "base_track_max": max(base_tracks),
        "base_grid_min": min(base_grid),
        "base_grid_mean": statistics.mean(base_grid),
        "base_grid_max": max(base_grid),
        "low_grid_frames": sum(value <= 0.80 for value in base_grid),
        "seed_quality_min": min(qualities),
        "seed_quality_below_0p9": sum(value < 0.9 for value in qualities),
        "output_poses": int(native["output_poses"]),
        "input_frames": int(native["input_frames"]),
        "coverage": float(native["coverage_ratio"]),
    }


def format_metric(result: dict[str, Any], role: str, kind: str) -> str:
    metric = result["metrics"][kind][role]
    return f"{metric['ape']:.6f} / {metric['rpe']:.6f}"


def formal_summary(result: dict[str, Any]) -> dict[str, Any]:
    config = result["config"]
    full = result["action"]["full"]
    unbounded = result["action"]["full_unbounded"]
    changes = result["improvements"]
    return {
        "window_id": config["window_id"],
        "selector": config["selector_name"],
        "level": config["level"],
        "formal_runs_ok": "20/20",
        "post_init_accepted": f"{full['post_init_accepted']}/{full['post_init_attempted']}",
        "map_point_lineages": full["mappoint_lineages"],
        "distinct_mappoints": full["distinct_mappoints"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "pre_kf_scans": full["scans"],
        "unbounded_matches": unbounded["matches"],
        "unbounded_outliers": unbounded["outliers"],
        "unbounded_pre_kf_observed": unbounded["pre_kf_observed"],
        "unbounded_pre_kf_purged": unbounded["pre_kf_purged"],
        "reconstructed_native_ape_m": result["metrics"]["reconstructed"]["orb_only"]["ape"],
        "reconstructed_native_rpe_m": result["metrics"]["reconstructed"]["orb_only"]["rpe"],
        "reconstructed_bridge_off_ape_m": result["metrics"]["reconstructed"]["full_bridge_off"]["ape"],
        "reconstructed_bridge_off_rpe_m": result["metrics"]["reconstructed"]["full_bridge_off"]["rpe"],
        "reconstructed_unbounded_ape_m": result["metrics"]["reconstructed"]["full_unbounded"]["ape"],
        "reconstructed_unbounded_rpe_m": result["metrics"]["reconstructed"]["full_unbounded"]["rpe"],
        "reconstructed_full_ape_m": result["metrics"]["reconstructed"]["full"]["ape"],
        "reconstructed_full_rpe_m": result["metrics"]["reconstructed"]["full"]["rpe"],
        "online_native_ape_m": result["metrics"]["online"]["orb_only"]["ape"],
        "online_native_rpe_m": result["metrics"]["online"]["orb_only"]["rpe"],
        "online_bridge_off_ape_m": result["metrics"]["online"]["full_bridge_off"]["ape"],
        "online_bridge_off_rpe_m": result["metrics"]["online"]["full_bridge_off"]["rpe"],
        "online_unbounded_ape_m": result["metrics"]["online"]["full_unbounded"]["ape"],
        "online_unbounded_rpe_m": result["metrics"]["online"]["full_unbounded"]["rpe"],
        "online_full_ape_m": result["metrics"]["online"]["full"]["ape"],
        "online_full_rpe_m": result["metrics"]["online"]["full"]["rpe"],
        "full_vs_native_improvements": f"{sum(value > 0 for value in changes['orb_only'].values())}/4",
        "full_vs_bridge_off_improvements": f"{sum(value > 0 for value in changes['full_bridge_off'].values())}/4",
        "full_vs_unbounded_improvements": f"{sum(value > 0 for value in changes['full_unbounded'].values())}/4",
        "coverage": f"{result['output_poses']}/{result['input_frames']}",
        "rpe_delta_associated_poses": config["rpe_delta"],
        "texture_profile": config["texture_profile"],
        "base_track_min": f"{result['base_track_min']:.0f}",
        "base_track_mean": f"{result['base_track_mean']:.6f}",
        "base_track_max": f"{result['base_track_max']:.0f}",
        "base_grid_min": f"{result['base_grid_min']:.6f}",
        "base_grid_mean": f"{result['base_grid_mean']:.6f}",
        "base_grid_max": f"{result['base_grid_max']:.6f}",
        "low_base_grid_frames": f"{result['low_grid_frames']}/{result['frontend_frames']}",
        "seed_quality_min": f"{result['seed_quality_min']:.9f}",
        "seed_quality_below_0p9": result["seed_quality_below_0p9"],
        "formal_root": str(config["formal_root"]),
    }


def roster_row(result: dict[str, Any]) -> dict[str, Any]:
    config = result["config"]
    full = result["action"]["full"]
    return {
        "window_id": config["window_id"],
        "dataset": config["dataset"],
        "sequence": config["sequence"],
        "window": config["window"],
        "level": config["level"],
        "independent_window": "true",
        "primary_selector": config["selector_name"],
        "accepted_post_init": f"{full['post_init_accepted']}/{full['post_init_attempted']}",
        "seed_lineages_with_mappoint": full["mappoint_lineages"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "texture_profile": config["texture_profile"],
        "base_klt_profile": config["base_klt_profile"],
        "operational_low_texture": str(config["operational_low_texture"]).lower(),
        "sparse_base_klt_low_texture": str(config["sparse_base_klt_low_texture"]).lower(),
        "source_report": REPORT_RELATIVE,
        "formal_root": str(config["formal_root"]),
    }


def build_report(results: list[dict[str, Any]], counts: dict[str, int]) -> str:
    lines = [
        "# ORB-SLAM3 v23 continued positive search R08",
        "",
        "Date: 2026-08-06",
        "",
        "## Decision",
        "",
        "Three independent clean windows passed the complete post-init action chain.",
        "AFRL Cemetery FR `25-45 s` and AQUALOC A08 `0-400` are stable",
        "action-positive no-harm cases but remain native-negative. AQUALOC A02",
        "`5600-6000` is a new project-strict window because v23 improves native/drop",
        "in reconstructed and online APE/RPE. It is not all-control strict because",
        "bridge-off is better in all four metrics and unbounded is better in three.",
        "",
        "No selector threshold, seed row, q gate, projection gate, descriptor gate,",
        "dose, ORB binary, library, runner, or phase rule was changed.",
        "",
        "## Frozen validation",
        "",
        "All 60 formal runs completed with status `ok`. Each role's action counters",
        "and reconstructed, online, and keyframe trajectories are identical across",
        "four repeats. Repeat 4 swaps `full` and `full_unbounded` in every window.",
        "All 60 provenance manifests and all `1728/1728` listed SHA-256 entries pass.",
        "",
    ]
    for result in results:
        c = result["config"]
        action = result["action"]
        full = action["full"]
        unbounded = action["full_unbounded"]
        native_changes = result["improvements"]["orb_only"]
        bridge_changes = result["improvements"]["full_bridge_off"]
        unbounded_changes = result["improvements"]["full_unbounded"]
        lines.extend(
            [
                f"## {c['window_id']}",
                "",
                f"Classification: `{c['level']}`. RPE is {c['rpe_label']} with",
                f"a `{c['association_s']:.2f} s` association threshold.",
                "",
                "| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                f"| Bridge off | {action['full_bridge_off']['post_init_accepted']}/{action['full_bridge_off']['post_init_attempted']} | {action['full_bridge_off']['mappoint_lineages']} / {action['full_bridge_off']['distinct_mappoints']} | 0 | 0 | 0 / 0 | 0 |",
                f"| Unbounded | {unbounded['post_init_accepted']}/{unbounded['post_init_attempted']} | {unbounded['mappoint_lineages']} / {unbounded['distinct_mappoints']} | {unbounded['matches']} | {unbounded['outliers']} | {unbounded['pre_kf_observed']} / 0 | {unbounded['scans']} |",
                f"| Frozen v23 | {full['post_init_accepted']}/{full['post_init_attempted']} | {full['mappoint_lineages']} / {full['distinct_mappoints']} | {full['matches']} | {full['outliers']} | {full['pre_kf_observed']} / {full['pre_kf_purged']} | {full['scans']} |",
                "",
                "| Role | Reconstructed APE / RPE | Online APE / RPE |",
                "| --- | --- | --- |",
                f"| Native ORB | `{format_metric(result, 'orb_only', 'reconstructed')}` | `{format_metric(result, 'orb_only', 'online')}` |",
                f"| Empty drop | `{format_metric(result, 'drop', 'reconstructed')}` | `{format_metric(result, 'drop', 'online')}` |",
                f"| Bridge off | `{format_metric(result, 'full_bridge_off', 'reconstructed')}` | `{format_metric(result, 'full_bridge_off', 'online')}` |",
                f"| Unbounded | `{format_metric(result, 'full_unbounded', 'reconstructed')}` | `{format_metric(result, 'full_unbounded', 'online')}` |",
                f"| Frozen v23 | `{format_metric(result, 'full', 'reconstructed')}` | `{format_metric(result, 'full', 'online')}` |",
                "",
                "v23 improvement percentages (positive is better):",
                "",
                f"- versus native: reconstructed APE/RPE `{native_changes['reconstructed_ape']:.3f}% / {native_changes['reconstructed_rpe']:.3f}%`; online `{native_changes['online_ape']:.3f}% / {native_changes['online_rpe']:.3f}%`",
                f"- versus bridge-off: `{sum(value > 0 for value in bridge_changes.values())}/4` metrics improve",
                f"- versus unbounded: `{sum(value > 0 for value in unbounded_changes.values())}/4` metrics improve",
                "",
                f"Texture: {c['texture_profile']}; tracks min/mean/max",
                f"`{result['base_track_min']:.0f} / {result['base_track_mean']:.3f} / {result['base_track_max']:.0f}`;",
                f"grid min/mean/max `{result['base_grid_min']:.6f} / {result['base_grid_mean']:.6f} / {result['base_grid_max']:.6f}`;",
                f"`{result['low_grid_frames']}/{result['frontend_frames']}` frames are at or below `0.80`.",
                "",
                f"Formal root: `{c['formal_root']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Updated denominator",
            "",
            f"- mechanism/action-positive: `{counts['action_positive']}`",
            f"- project strict: `{counts['project_strict']}`",
            f"- all-control repeatwise strict: `{counts['all_control_strict']}`",
            f"- operational degraded/low-grid: `{counts['operational_low_grid']}/{counts['action_positive']}`",
            f"- operational low-grid among project strict: `{counts['strict_operational_low_grid']}/{counts['project_strict']}`",
            f"- sparse base-KLT positives: `{counts['sparse_base_klt']}/{counts['action_positive']}`",
            "",
            "## Claim boundary",
            "",
            "- Count each of the three windows once; all are independent and development-only.",
            "- Add A02 `5600-6000` to project-strict evidence with explicit bridge-off and unbounded caveats.",
            "- Count AFRL FR `25-45 s` and A08 `0-400` as mechanism/action-positive no-harm windows, not trajectory-improvement windows.",
            "- Do not call any of the three all-control strict or untouched confirmatory.",
            "- None uses a deliberately sparse base-KLT profile.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"output exists; pass --replace: {output}")
    results = [evaluate_window(config) for config in WINDOWS]

    prior = read_csv(PRIOR_ROSTER)
    if len(prior) != 12 or len({row["window_id"] for row in prior}) != 12:
        raise RuntimeError("prior roster is not the expected 12-window snapshot")
    roster = prior + [roster_row(result) for result in results]
    if len(roster) != 15 or len({row["window_id"] for row in roster}) != 15:
        raise RuntimeError("updated roster is not 15 unique windows")
    project_strict = sum(
        "project_strict" in row["level"] or row["level"] == "repeatwise_strict"
        for row in roster
    )
    all_control_strict = sum(
        "audit_strict" in row["level"] or row["level"] == "repeatwise_strict"
        for row in roster
    )
    operational_low = sum(row["operational_low_texture"] == "true" for row in roster)
    sparse = sum(row["sparse_base_klt_low_texture"] == "true" for row in roster)
    strict_low = sum(
        row["operational_low_texture"] == "true"
        and ("project_strict" in row["level"] or row["level"] == "repeatwise_strict")
        for row in roster
    )
    counts = {
        "action_positive": len(roster),
        "project_strict": project_strict,
        "all_control_strict": all_control_strict,
        "operational_low_grid": operational_low,
        "strict_operational_low_grid": strict_low,
        "sparse_base_klt": sparse,
    }
    expected_counts = {
        "action_positive": 15,
        "project_strict": 5,
        "all_control_strict": 2,
        "operational_low_grid": 8,
        "strict_operational_low_grid": 3,
        "sparse_base_klt": 0,
    }
    if counts != expected_counts:
        raise RuntimeError(f"unexpected roster counts: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        write_csv(temp / "formal_summary.csv", [formal_summary(result) for result in results])
        write_csv(temp / "window_roster.csv", roster)
        artifacts: list[tuple[str, Path]] = [
            ("analysis_builder", Path(__file__).resolve()),
            ("orb_binary", Path("/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/Examples_old/Monocular/mono_euroc_old")),
            ("orb_library", Path("/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/lib/libORB_SLAM3.so")),
            ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
            ("dataset_exporter", WORKSPACE / "scripts/prepare_orbslam3_aqualoc_bag.py"),
            ("selector_runner", WORKSPACE / "scripts/prepare_causal_multilineage_bag.sh"),
            ("sidecar_generator", WORKSPACE / "uw_frontend/ros/xfeat_seed_sidecar_node.py"),
            ("sidecar_config", WORKSPACE / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml"),
            ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ]
        for result in results:
            config = result["config"]
            prefix = config["window_id"].lower()
            artifacts.extend(
                [
                    (f"{prefix}_raw_bag", config["raw_bag"]),
                    (f"{prefix}_historical_bag", config["historical_bag"]),
                    (f"{prefix}_sidecar_camera", config["camera_config"]),
                    (f"{prefix}_orb_camera", config["orb_config"]),
                    (f"{prefix}_clean_stats", config["stats"]),
                    (f"{prefix}_selector_manifest", config["selector_root"] / "manifest.txt"),
                    (f"{prefix}_selector_lineages", config["selector_root"] / "lineage_selection.csv"),
                    (f"{prefix}_full_bag", config["selector_root"] / "full_merged.bag"),
                    (f"{prefix}_full_seeds", config["seed_root"] / "full_seeds.txt"),
                    (f"{prefix}_dataset_metadata", config["dataset_root"] / "export_metadata.json"),
                    (f"{prefix}_dataset_times", config["dataset_root"] / "cam0_times.txt"),
                    (f"{prefix}_dataset_gt", config["dataset_root"] / "groundtruth_tum.txt"),
                    (f"{prefix}_evaluation_reconstructed", config["formal_root"] / "evaluation_reconstructed.csv"),
                    (f"{prefix}_evaluation_online", config["formal_root"] / "evaluation_online.csv"),
                ]
            )
        provenance_rows = []
        for name, path in artifacts:
            resolved = path.resolve()
            if not resolved.is_file():
                raise RuntimeError(f"missing provenance artifact: {resolved}")
            provenance_rows.append(
                {"artifact": name, "sha256": sha256(resolved), "path": str(resolved)}
            )
        write_csv(temp / "provenance.csv", provenance_rows)

        validation = {
            "schema_version": 3,
            "date": "2026-08-06",
            "added_windows": 3,
            "updated_counts": counts,
            "snapshot_manifests": sum(20 for _ in results),
            "snapshot_manifests_verified": sum(20 for _ in results),
            "snapshot_entries": sum(result["snapshot_entries"] for result in results),
            "snapshot_entries_verified": sum(result["snapshot_entries"] for result in results),
            "windows": {
                result["config"]["window_id"]: {
                    "action_positive": True,
                    "level": result["config"]["level"],
                    "project_strict": "project_strict" in result["config"]["level"],
                    "all_control_strict": False,
                    "repeat4_order_swapped": True,
                    "formal_runs": 20,
                    "formal_runs_ok": 20,
                    "full_vs_native_improvements": sum(
                        value > 0 for value in result["improvements"]["orb_only"].values()
                    ),
                    "full_vs_bridge_off_improvements": sum(
                        value > 0 for value in result["improvements"]["full_bridge_off"].values()
                    ),
                    "full_vs_unbounded_improvements": sum(
                        value > 0 for value in result["improvements"]["full_unbounded"].values()
                    ),
                    "operational_low_grid": result["config"]["operational_low_texture"],
                    "sparse_base_klt": result["config"]["sparse_base_klt_low_texture"],
                    "low_grid_frames_le_0p80": result["low_grid_frames"],
                    "frontend_frames": result["frontend_frames"],
                    "role_counter_signatures": result["counter_signatures"],
                    "role_reconstructed_hashes": result["trajectory_hashes"]["reconstructed"],
                    "role_online_hashes": result["trajectory_hashes"]["online"],
                    "role_keyframe_hashes": result["trajectory_hashes"]["keyframe"],
                    "snapshot_entries": result["snapshot_entries"],
                }
                for result in results
            },
        }
        (temp / "validation_summary.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="ascii"
        )
        (temp / "analysis-report.md").write_text(
            build_report(results, counts), encoding="ascii"
        )

        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(f"wrote validated R08 bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
