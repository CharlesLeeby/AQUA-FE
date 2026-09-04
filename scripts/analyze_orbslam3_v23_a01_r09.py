#!/usr/bin/env python3
"""Build the R09 A01 evidence bundle and audit the excluded A03 formal grid."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import analyze_orbslam3_v23_continued_search_r08 as r08


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
DEFAULT_OUTPUT = (
    WORKSPACE / "papers/orb_v23_a01_r09_20260806/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_continued_search_r08_20260806/analysis-output/window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_a01_r09_20260806/analysis-output/analysis-report.md"
)
FORMAL_SUFFIX = (
    "formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)


def data(path: str) -> Path:
    return DATA_ROOT / path


A01_CONFIG: dict[str, Any] = {
    "window_id": "A01_6800_7200",
    "dataset": "AQUALOC",
    "sequence": "A01",
    "window": "6800-7200",
    "level": "action_positive_metric_negative_native_negative_non_strict",
    "selector_name": "n3_d14_min8_ignore0_clean",
    "texture_profile": "operational degraded/low-grid",
    "base_klt_profile": "near-saturated 326-350; grid mean 0.744306",
    "operational_low_texture": True,
    "sparse_base_klt_low_texture": False,
    "formal_root": data(
        "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
        f"aqualoc_a01_6800_7200/{FORMAL_SUFFIX}"
    ),
    "stats": data(
        "online_positive_search_20260806/aqualoc_a01_6800_7200/"
        "clean_ignore0/stats.csv"
    ),
    "selector_root": data(
        "orbslam3_seeded_validation/multilineage/aqualoc_a01_6800_7200/"
        "n3_d14_min8_ignore0_clean_20260806"
    ),
    "seed_root": data(
        "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
        "aqualoc_a01_6800_7200/assets_n3_d14_min8_ignore0_clean"
    ),
    "dataset_root": data(
        "orbslam3_validation/aqualoc_a01_6800_7200_clean_20260806/dataset"
    ),
    "raw_bag": data("datasets/aqualoc/rosbags/archaeo01_6800_7200.bag"),
    "historical_bag": data(
        "logs/aqualoc_archaeo_vins/"
        "external_hybrid_xfeat_every2_jul16screen10_a01_6800_7200_probe/"
        "features.bag"
    ),
    "camera_config": data(
        "logs/aqualoc_archaeo_vins/"
        "external_hybrid_xfeat_every2_jul16screen10_a01_6800_7200_probe/"
        "aqualoc_archaeo01_pinhole.yaml"
    ),
    "orb_config": WORKSPACE / "logs/orbslam3_validation/aqualoc_archaeo_mono.yaml",
    "rpe_delta": 1,
    "rpe_label": "1-associated-pose",
    "association_s": 0.06,
}

A03_FORMAL_ROOT = data(
    "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
    f"aqualoc_a03_3200_3600/{FORMAL_SUFFIX}"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def action_record(run: Path, summary: dict[str, Any]) -> dict[str, Any]:
    lineages = r08.read_csv(run / "instrumentation/seed_lineages.csv")
    return {
        "post_init_attempted": sum(
            int(row["post_init_attempted"]) for row in lineages
        ),
        "post_init_accepted": sum(
            int(row["post_init_accepted"]) for row in lineages
        ),
        "pre_init_attempted": sum(
            int(row["pre_init_attempted"]) for row in lineages
        ),
        "map_point_lineages": int(summary["seed_lineages_with_mappoint"]),
        "distinct_mappoints": int(summary["distinct_mappoints"]),
        "assisted_matches": int(summary["lineage_assisted_matches_consumed"]),
        "assisted_outliers": int(summary["lineage_assisted_outliers_observed"]),
        "pre_kf_observed": int(
            summary["lineage_pre_kf_assisted_outliers_observed"]
        ),
        "pre_kf_purged": int(
            summary["lineage_pre_kf_assisted_outliers_purged"]
        ),
        "pre_kf_scans": int(summary["lineage_pre_kf_outlier_purge_scans"]),
    }


def audit_a03_nondeterminism() -> dict[str, Any]:
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]] = {}
    expected_grid = {
        (role, repeat) for role in r08.ROLES for repeat in r08.REPEATS
    }
    for kind in ("reconstructed", "online"):
        rows = r08.read_csv(A03_FORMAL_ROOT / f"evaluation_{kind}.csv")
        lookup = {(row["role"], int(row["repeat"])): row for row in rows}
        if len(rows) != 20 or set(lookup) != expected_grid:
            raise RuntimeError(f"incomplete A03 {kind} evaluation grid")
        if any(row["status"] != "ok" for row in rows):
            raise RuntimeError(f"non-ok A03 {kind} evaluation")
        evaluations[kind] = lookup

    counter_signatures = {role: set() for role in r08.ROLES}
    counter_by_repeat: dict[str, dict[int, tuple[Any, ...]]] = {
        role: {} for role in r08.ROLES
    }
    trajectory_hashes = {
        kind: {role: set() for role in r08.ROLES}
        for kind in r08.TRAJECTORY_PATTERNS
    }
    trajectory_by_repeat = {
        kind: {role: {} for role in r08.ROLES}
        for kind in r08.TRAJECTORY_PATTERNS
    }
    snapshot_entries = 0
    snapshot_counts: Counter[int] = Counter()
    full_actions: dict[int, dict[str, Any]] = {}

    for repeat in r08.REPEATS:
        for role in r08.ROLES:
            run = A03_FORMAL_ROOT / f"{role}_r{repeat}"
            manifest = r08.parse_manifest(run / "run_manifest.txt")
            if manifest.get("role_order") != r08.EXPECTED_ORDERS[repeat]:
                raise RuntimeError(f"wrong A03 role order: {run}")
            summary = json.loads(
                (run / "instrumentation/seed_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            if summary.get("complete") is not True or summary.get("status") != "ok":
                raise RuntimeError(f"incomplete A03 instrumentation: {run}")
            signature = tuple(summary[field] for field in r08.COUNTER_FIELDS)
            counter_signatures[role].add(signature)
            counter_by_repeat[role][repeat] = signature
            if role == "full":
                full_actions[repeat] = action_record(run, summary)
            for kind, pattern in r08.TRAJECTORY_PATTERNS.items():
                digest = r08.sha256(r08.one_file(run, pattern))
                trajectory_hashes[kind][role].add(digest)
                trajectory_by_repeat[kind][role][repeat] = digest
            count = r08.verify_snapshot(run / "provenance/snapshot_sha256.txt")
            snapshot_entries += count
            snapshot_counts[count] += 1

    expected_uniques = {role: 1 for role in r08.ROLES}
    expected_uniques["full"] = 2
    observed_counter_uniques = {
        role: len(items) for role, items in counter_signatures.items()
    }
    if observed_counter_uniques != expected_uniques:
        raise RuntimeError(
            f"unexpected A03 counter signatures: {observed_counter_uniques}"
        )
    for kind, roles in trajectory_hashes.items():
        observed = {role: len(items) for role, items in roles.items()}
        if observed != expected_uniques:
            raise RuntimeError(f"unexpected A03 {kind} hashes: {observed}")
    if snapshot_entries != 576 or snapshot_counts != Counter({28: 4, 29: 16}):
        raise RuntimeError(
            f"unexpected A03 snapshot contract: {snapshot_entries}, {snapshot_counts}"
        )

    full_counter_modes = counter_by_repeat["full"]
    if not (
        full_counter_modes[1] == full_counter_modes[2]
        and full_counter_modes[3] == full_counter_modes[4]
        and full_counter_modes[1] != full_counter_modes[3]
    ):
        raise RuntimeError("A03 full counters do not form the expected r1/r2, r3/r4 split")

    metric_signatures: dict[str, dict[str, int]] = {}
    full_metrics: dict[str, dict[int, tuple[float, float]]] = {}
    for kind, lookup in evaluations.items():
        metric_signatures[kind] = {}
        full_metrics[kind] = {}
        for role in r08.ROLES:
            values = {
                (
                    float(lookup[(role, repeat)]["ape_rmse_m"]),
                    float(lookup[(role, repeat)]["rpe_rmse_m"]),
                )
                for repeat in r08.REPEATS
            }
            metric_signatures[kind][role] = len(values)
            if len(values) != expected_uniques[role]:
                raise RuntimeError(
                    f"unexpected A03 {kind} metric signatures for {role}: {values}"
                )
        for repeat in r08.REPEATS:
            row = lookup[("full", repeat)]
            full_metrics[kind][repeat] = (
                float(row["ape_rmse_m"]),
                float(row["rpe_rmse_m"]),
            )
            hashes = trajectory_by_repeat[kind]["full"]
            if not (
                hashes[1] == hashes[2]
                and hashes[3] == hashes[4]
                and hashes[1] != hashes[3]
            ):
                raise RuntimeError(
                    f"A03 full {kind} trajectories do not form the expected split"
                )
        if not (
            full_metrics[kind][1] == full_metrics[kind][2]
            and full_metrics[kind][3] == full_metrics[kind][4]
            and full_metrics[kind][1] != full_metrics[kind][3]
        ):
            raise RuntimeError(
                f"A03 full {kind} metrics do not form the expected split"
            )

    keyframe_hashes = trajectory_by_repeat["keyframe"]["full"]
    if not (
        keyframe_hashes[1] == keyframe_hashes[2]
        and keyframe_hashes[3] == keyframe_hashes[4]
        and keyframe_hashes[1] != keyframe_hashes[3]
    ):
        raise RuntimeError("A03 full keyframe trajectories do not form the expected split")

    expected_actions = {
        1: (3, 22, 56, 17, 9, 9),
        2: (3, 22, 56, 17, 9, 9),
        3: (2, 33, 57, 15, 10, 10),
        4: (2, 33, 57, 15, 10, 10),
    }
    for repeat, action in full_actions.items():
        observed = (
            action["map_point_lineages"],
            action["distinct_mappoints"],
            action["assisted_matches"],
            action["assisted_outliers"],
            action["pre_kf_observed"],
            action["pre_kf_purged"],
        )
        if observed != expected_actions[repeat]:
            raise RuntimeError(
                f"unexpected A03 full action for repeat {repeat}: {observed}"
            )

    def mode(repeat: int) -> dict[str, Any]:
        action = full_actions[repeat]
        return {
            "repeats": "1,2" if repeat == 1 else "3,4",
            "action": action,
            "reconstructed_ape_m": full_metrics["reconstructed"][repeat][0],
            "reconstructed_rpe_m": full_metrics["reconstructed"][repeat][1],
            "online_ape_m": full_metrics["online"][repeat][0],
            "online_rpe_m": full_metrics["online"][repeat][1],
            "reconstructed_sha256": trajectory_by_repeat["reconstructed"]["full"][repeat],
            "online_sha256": trajectory_by_repeat["online"]["full"][repeat],
            "keyframe_sha256": trajectory_by_repeat["keyframe"]["full"][repeat],
        }

    return {
        "window_id": "A03_3200_3600",
        "decision": "formal_nondeterministic_no_go",
        "action_positive": False,
        "included_in_roster": False,
        "formal_runs": 20,
        "formal_runs_ok": 20,
        "repeat4_order_swapped": True,
        "role_counter_signatures": observed_counter_uniques,
        "role_reconstructed_hashes": {
            role: len(items)
            for role, items in trajectory_hashes["reconstructed"].items()
        },
        "role_online_hashes": {
            role: len(items)
            for role, items in trajectory_hashes["online"].items()
        },
        "role_keyframe_hashes": {
            role: len(items)
            for role, items in trajectory_hashes["keyframe"].items()
        },
        "role_reconstructed_metric_signatures": metric_signatures["reconstructed"],
        "role_online_metric_signatures": metric_signatures["online"],
        "snapshot_manifests": 20,
        "snapshot_manifests_verified": 20,
        "snapshot_entries": snapshot_entries,
        "snapshot_entries_verified": snapshot_entries,
        "full_modes": {"r1_r2": mode(1), "r3_r4": mode(3)},
        "formal_root": str(A03_FORMAL_ROOT),
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
        "accepted_post_init": (
            f"{full['post_init_accepted']}/{full['post_init_attempted']}"
        ),
        "seed_lineages_with_mappoint": full["mappoint_lineages"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "texture_profile": config["texture_profile"],
        "base_klt_profile": config["base_klt_profile"],
        "operational_low_texture": "true",
        "sparse_base_klt_low_texture": "false",
        "source_report": REPORT_RELATIVE,
        "formal_root": str(config["formal_root"]),
    }


def roster_counts(roster: list[dict[str, str]]) -> dict[str, int]:
    return {
        "action_positive": len(roster),
        "project_strict": sum(
            "project_strict" in row["level"] or row["level"] == "repeatwise_strict"
            for row in roster
        ),
        "all_control_strict": sum(
            "audit_strict" in row["level"] or row["level"] == "repeatwise_strict"
            for row in roster
        ),
        "operational_low_grid": sum(
            row["operational_low_texture"] == "true" for row in roster
        ),
        "strict_operational_low_grid": sum(
            row["operational_low_texture"] == "true"
            and (
                "project_strict" in row["level"]
                or row["level"] == "repeatwise_strict"
            )
            for row in roster
        ),
        "sparse_base_klt": sum(
            row["sparse_base_klt_low_texture"] == "true" for row in roster
        ),
    }


def build_report(
    result: dict[str, Any], a03: dict[str, Any], counts: dict[str, int]
) -> str:
    action = result["action"]
    full = action["full"]
    unbounded = action["full_unbounded"]
    native_changes = result["improvements"]["orb_only"]
    mode12 = a03["full_modes"]["r1_r2"]
    mode34 = a03["full_modes"]["r3_r4"]
    lines = [
        "# ORB-SLAM3 v23 A01 evidence closure R09",
        "",
        "Date: 2026-08-06",
        "",
        "## Decision",
        "",
        "AQUALOC A01 `6800-7200` is a new independent mechanism/action-positive",
        "window. It is operational low-grid, but it is native-negative in all four",
        "reconstructed and online APE/RPE comparisons. It is neither project strict",
        "nor all-control strict, and it must not be presented as no-harm evidence.",
        "",
        "AQUALOC A03 `3200-3600` completed a formal matrix but is a",
        "formal-nondeterministic No-Go. It is recorded below and excluded from the",
        "roster and every positive denominator.",
        "",
        "No selector threshold, seed row, q gate, projection gate, descriptor gate,",
        "dose, ORB binary, library, runner, or phase rule was changed.",
        "",
        "## Frozen validation",
        "",
        "All 20 A01 formal runs completed with status `ok`. Each role has one action",
        "counter signature and one reconstructed, online, and keyframe trajectory",
        "hash across four repeats. Repeat 4 swaps `full` and `full_unbounded`.",
        "All 20 A01 provenance manifests and all `576/576` listed SHA-256 entries",
        "pass. The resulting roster contains 16 unique fixed intervals.",
        "",
        "## A01_6800_7200",
        "",
        f"Classification: `{A01_CONFIG['level']}`. RPE is 1-associated-pose with",
        "a `0.06 s` association threshold.",
        "",
        "| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Bridge off | {action['full_bridge_off']['post_init_accepted']}/{action['full_bridge_off']['post_init_attempted']} | {action['full_bridge_off']['mappoint_lineages']} / {action['full_bridge_off']['distinct_mappoints']} | 0 | 0 | 0 / 0 | 0 |",
        f"| Unbounded | {unbounded['post_init_accepted']}/{unbounded['post_init_attempted']} | {unbounded['mappoint_lineages']} / {unbounded['distinct_mappoints']} | {unbounded['matches']} | {unbounded['outliers']} | {unbounded['pre_kf_observed']} / 0 | {unbounded['scans']} |",
        f"| Frozen v23 | {full['post_init_accepted']}/{full['post_init_attempted']} | {full['mappoint_lineages']} / {full['distinct_mappoints']} | {full['matches']} | {full['outliers']} | {full['pre_kf_observed']} / {full['pre_kf_purged']} | {full['scans']} |",
        "",
        "| Role | Reconstructed APE / RPE | Online APE / RPE |",
        "| --- | --- | --- |",
        f"| Native ORB | `{r08.format_metric(result, 'orb_only', 'reconstructed')}` | `{r08.format_metric(result, 'orb_only', 'online')}` |",
        f"| Empty drop | `{r08.format_metric(result, 'drop', 'reconstructed')}` | `{r08.format_metric(result, 'drop', 'online')}` |",
        f"| Bridge off | `{r08.format_metric(result, 'full_bridge_off', 'reconstructed')}` | `{r08.format_metric(result, 'full_bridge_off', 'online')}` |",
        f"| Unbounded | `{r08.format_metric(result, 'full_unbounded', 'reconstructed')}` | `{r08.format_metric(result, 'full_unbounded', 'online')}` |",
        f"| Frozen v23 | `{r08.format_metric(result, 'full', 'reconstructed')}` | `{r08.format_metric(result, 'full', 'online')}` |",
        "",
        "v23 change versus native (positive is better):",
        "",
        f"- reconstructed APE/RPE: `{native_changes['reconstructed_ape']:.3f}% / {native_changes['reconstructed_rpe']:.3f}%`",
        f"- online APE/RPE: `{native_changes['online_ape']:.3f}% / {native_changes['online_rpe']:.3f}%`",
        "- improved metrics: `0/4`; bridge-off `0/4`; unbounded `0/4`",
        "",
        f"Texture: {A01_CONFIG['texture_profile']}; tracks min/mean/max",
        f"`{result['base_track_min']:.0f} / {result['base_track_mean']:.3f} / {result['base_track_max']:.0f}`;",
        f"grid min/mean/max `{result['base_grid_min']:.6f} / {result['base_grid_mean']:.6f} / {result['base_grid_max']:.6f}`;",
        f"`{result['low_grid_frames']}/{result['frontend_frames']}` frames are at or below `0.80`.",
        "",
        f"Formal root: `{A01_CONFIG['formal_root']}`",
        "",
        "## A03_3200_3600 No-Go",
        "",
        "A03 is pure post-init and completes the action chain, but the frozen `full`",
        "role splits into two repeat modes while all four controls remain deterministic:",
        "",
        "| Repeats | MP lineages / MPs | Matches | Outliers | Purge | Reconstructed APE / RPE | Online APE / RPE |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        f"| r1/r2 | {mode12['action']['map_point_lineages']} / {mode12['action']['distinct_mappoints']} | {mode12['action']['assisted_matches']} | {mode12['action']['assisted_outliers']} | {mode12['action']['pre_kf_purged']}/{mode12['action']['pre_kf_observed']} | `{mode12['reconstructed_ape_m']:.6f} / {mode12['reconstructed_rpe_m']:.6f}` | `{mode12['online_ape_m']:.6f} / {mode12['online_rpe_m']:.6f}` |",
        f"| r3/r4 | {mode34['action']['map_point_lineages']} / {mode34['action']['distinct_mappoints']} | {mode34['action']['assisted_matches']} | {mode34['action']['assisted_outliers']} | {mode34['action']['pre_kf_purged']}/{mode34['action']['pre_kf_observed']} | `{mode34['reconstructed_ape_m']:.6f} / {mode34['reconstructed_rpe_m']:.6f}` | `{mode34['online_ape_m']:.6f} / {mode34['online_rpe_m']:.6f}` |",
        "",
        "The full-role counter, reconstructed, online, keyframe, and metric signature",
        "counts are all `2`; every other role has `1`. r3 already uses the standard",
        "role order and matches swapped-order r4, so the split is not an r4 order",
        "effect. Its 20 manifests and `576/576` entries pass, which isolates the",
        "failure to formal repeat determinism rather than incomplete provenance.",
        "",
        f"Formal root: `{A03_FORMAL_ROOT}`",
        "",
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
        "- Count A01 once as development-only action/mechanism evidence.",
        "- Do not claim A01 as trajectory-positive, no-harm, project strict, or all-control strict.",
        "- Keep A03 out of the roster and all positive denominators.",
        "- Neither result is untouched confirmatory evidence.",
        "",
    ]
    return "\n".join(lines)


def provenance_artifacts(result: dict[str, Any]) -> list[tuple[str, Path]]:
    config = result["config"]
    artifacts: list[tuple[str, Path]] = [
        ("analysis_builder", Path(__file__).resolve()),
        (
            "analysis_core_r08",
            WORKSPACE / "scripts/analyze_orbslam3_v23_continued_search_r08.py",
        ),
        ("prior_roster", PRIOR_ROSTER),
        (
            "orb_binary",
            Path(
                "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/"
                "Examples_old/Monocular/mono_euroc_old"
            ),
        ),
        (
            "orb_library",
            Path(
                "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/"
                "lib/libORB_SLAM3.so"
            ),
        ),
        ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        ("dataset_exporter", WORKSPACE / "scripts/prepare_orbslam3_aqualoc_bag.py"),
        ("selector_runner", WORKSPACE / "scripts/prepare_causal_multilineage_bag.sh"),
        ("sidecar_generator", WORKSPACE / "uw_frontend/ros/xfeat_seed_sidecar_node.py"),
        (
            "sidecar_config",
            WORKSPACE
            / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml",
        ),
        ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ("a01_raw_bag", config["raw_bag"]),
        ("a01_historical_bag", config["historical_bag"]),
        ("a01_sidecar_camera", config["camera_config"]),
        ("a01_orb_camera", config["orb_config"]),
        ("a01_clean_stats", config["stats"]),
        ("a01_selector_manifest", config["selector_root"] / "manifest.txt"),
        (
            "a01_selector_lineages",
            config["selector_root"] / "lineage_selection.csv",
        ),
        ("a01_full_bag", config["selector_root"] / "full_merged.bag"),
        ("a01_full_seeds", config["seed_root"] / "full_seeds.txt"),
        (
            "a01_dataset_metadata",
            config["dataset_root"] / "export_metadata.json",
        ),
        ("a01_dataset_times", config["dataset_root"] / "cam0_times.txt"),
        ("a01_dataset_gt", config["dataset_root"] / "groundtruth_tum.txt"),
        (
            "a01_evaluation_reconstructed",
            config["formal_root"] / "evaluation_reconstructed.csv",
        ),
        (
            "a01_evaluation_online",
            config["formal_root"] / "evaluation_online.csv",
        ),
        (
            "a03_evaluation_reconstructed",
            A03_FORMAL_ROOT / "evaluation_reconstructed.csv",
        ),
        ("a03_evaluation_online", A03_FORMAL_ROOT / "evaluation_online.csv"),
    ]
    for repeat in r08.REPEATS:
        run = A03_FORMAL_ROOT / f"full_r{repeat}"
        prefix = f"a03_full_r{repeat}"
        artifacts.extend(
            [
                (f"{prefix}_run_manifest", run / "run_manifest.txt"),
                (
                    f"{prefix}_seed_summary",
                    run / "instrumentation/seed_summary.json",
                ),
                (
                    f"{prefix}_seed_lineages",
                    run / "instrumentation/seed_lineages.csv",
                ),
                (
                    f"{prefix}_snapshot_manifest",
                    run / "provenance/snapshot_sha256.txt",
                ),
                (f"{prefix}_reconstructed", r08.one_file(run, "f_*.txt")),
                (f"{prefix}_online", r08.one_file(run, "online_f_*.txt")),
                (f"{prefix}_keyframe", r08.one_file(run, "kf_*.txt")),
            ]
        )
    return artifacts


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"output exists; pass --replace: {output}")

    result = r08.evaluate_window(A01_CONFIG)
    improvement_counts = {
        control: sum(value > 0 for value in changes.values())
        for control, changes in result["improvements"].items()
    }
    if improvement_counts != {
        "orb_only": 0,
        "drop": 0,
        "full_bridge_off": 0,
        "full_unbounded": 0,
    }:
        raise RuntimeError(f"A01 is not fully native-negative: {improvement_counts}")
    full = result["action"]["full"]
    if (
        full["post_init_accepted"],
        full["post_init_attempted"],
        full["mappoint_lineages"],
        full["distinct_mappoints"],
        full["matches"],
        full["outliers"],
        full["pre_kf_purged"],
        full["pre_kf_observed"],
    ) != (230, 232, 3, 4, 158, 6, 2, 2):
        raise RuntimeError(f"unexpected A01 action signature: {full}")

    a03 = audit_a03_nondeterminism()
    prior = r08.read_csv(PRIOR_ROSTER)
    if len(prior) != 15 or len({row["window_id"] for row in prior}) != 15:
        raise RuntimeError("prior R08 roster is not 15 unique windows")
    if any(row["window_id"] in {"A01_6800_7200", "A03_3200_3600"} for row in prior):
        raise RuntimeError("A01 or excluded A03 already exists in the prior roster")
    roster = prior + [roster_row(result)]
    if len(roster) != 16 or len({row["window_id"] for row in roster}) != 16:
        raise RuntimeError("R09 roster is not 16 unique windows")
    if any(row["window_id"] == "A03_3200_3600" for row in roster):
        raise RuntimeError("formal-nondeterministic A03 entered the R09 roster")

    counts = roster_counts(roster)
    expected_counts = {
        "action_positive": 16,
        "project_strict": 5,
        "all_control_strict": 2,
        "operational_low_grid": 9,
        "strict_operational_low_grid": 3,
        "sparse_base_klt": 0,
    }
    if counts != expected_counts:
        raise RuntimeError(f"unexpected R09 roster counts: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        r08.write_csv(temp / "formal_summary.csv", [r08.formal_summary(result)])
        r08.write_csv(temp / "window_roster.csv", roster)

        provenance_rows = []
        for name, path in provenance_artifacts(result):
            resolved = path.resolve()
            if not resolved.is_file():
                raise RuntimeError(f"missing provenance artifact: {resolved}")
            provenance_rows.append(
                {"artifact": name, "sha256": r08.sha256(resolved), "path": str(resolved)}
            )
        r08.write_csv(temp / "provenance.csv", provenance_rows)

        validation = {
            "schema_version": 4,
            "date": "2026-08-06",
            "added_windows": 1,
            "excluded_formal_windows": 1,
            "roster_rows": len(roster),
            "roster_unique_windows": len({row["window_id"] for row in roster}),
            "updated_counts": counts,
            "snapshot_manifests": 40,
            "snapshot_manifests_verified": 40,
            "snapshot_entries": result["snapshot_entries"] + a03["snapshot_entries"],
            "snapshot_entries_verified": (
                result["snapshot_entries"] + a03["snapshot_entries"]
            ),
            "windows": {
                "A01_6800_7200": {
                    "action_positive": True,
                    "level": A01_CONFIG["level"],
                    "native_negative": True,
                    "non_strict": True,
                    "project_strict": False,
                    "all_control_strict": False,
                    "repeat4_order_swapped": True,
                    "formal_runs": 20,
                    "formal_runs_ok": 20,
                    "full_vs_native_improvements": 0,
                    "full_vs_bridge_off_improvements": 0,
                    "full_vs_unbounded_improvements": 0,
                    "operational_low_grid": True,
                    "sparse_base_klt": False,
                    "low_grid_frames_le_0p80": result["low_grid_frames"],
                    "frontend_frames": result["frontend_frames"],
                    "role_counter_signatures": result["counter_signatures"],
                    "role_reconstructed_hashes": result["trajectory_hashes"]["reconstructed"],
                    "role_online_hashes": result["trajectory_hashes"]["online"],
                    "role_keyframe_hashes": result["trajectory_hashes"]["keyframe"],
                    "snapshot_manifests": 20,
                    "snapshot_manifests_verified": 20,
                    "snapshot_entries": result["snapshot_entries"],
                    "snapshot_entries_verified": result["snapshot_entries"],
                    "formal_root": str(A01_CONFIG["formal_root"]),
                }
            },
            "no_go_windows": {"A03_3200_3600": a03},
        }
        (temp / "validation_summary.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        (temp / "analysis-report.md").write_text(
            build_report(result, a03, counts), encoding="ascii"
        )

        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(f"wrote validated R09 A01 bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
