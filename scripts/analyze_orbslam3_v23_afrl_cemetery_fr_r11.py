#!/usr/bin/env python3
"""Build the R11 evidence bundle for AFRL Cemetery-FR s230,d30."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import analyze_orbslam3_v23_a01_r09 as r09
import analyze_orbslam3_v23_continued_search_r08 as r08


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
DEFAULT_OUTPUT = (
    WORKSPACE / "papers/orb_v23_afrl_cemetery_fr_r11_20260807/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_ntnu_fjord1_r10_20260806/analysis-output/window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_afrl_cemetery_fr_r11_20260807/analysis-output/analysis-report.md"
)
FORMAL_SUFFIX = (
    "formal_n3_d14_min8_ignore0_clean_halfres_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)

KLT_FEATURES_SHA256 = (
    "ad07cdba539e20070711fb190a5f338022dfaece3212a700149f508743fab2c7"
)
SHORT_BAG_SHA256 = (
    "dc4392a4f76cd79669c21940594a2f974b6af8f71179cfb7ffe4cf3f2b5fb68f"
)
SIDECAR_SHA256 = (
    "35adc1aaa869d98ad59efb27b0f0a85edafb3075fad08ddfb36b52e810484f1a"
)
FULL_MERGED_SHA256 = (
    "6bcfe118d1407412890b48a79721fd5cbe21c547c67e3d10d2602fa65c912953"
)
FULL_SEEDS_SHA256 = (
    "0b44f98c1d46517f8312c05c1a8bfae0c109c9babb8ed964cc6ceb2b2a090d25"
)
FEATURE_TIMES_SHA256 = (
    "90b6c0a39c52afafe272db47ebf1474dc87091b6cf613284416da85f008f2743"
)


def data(path: str) -> Path:
    return DATA_ROOT / path


KLT_ROOT = data(
    "online_positive_search_20260806/afrl_cemetery_fr_s230_d30/"
    "halfres_klt_clean_20260806"
)
CLEAN_ROOT = data(
    "online_positive_search_20260806/afrl_cemetery_fr_s230_d30/"
    "clean_halfres_ignore0_20260807"
)
SELECTOR_ROOT = data(
    "orbslam3_seeded_validation/multilineage/afrl_cemetery_fr_s230_d30/"
    "n3_d14_min8_ignore0_clean_halfres_20260807"
)
SEED_ROOT = data(
    "orbslam3_seeded_validation/postinit_candidate_search_20260807/"
    "afrl_cemetery_fr_s230_d30/assets_n3_d14_min8_ignore0_clean_halfres"
)
DATASET_ROOT = data(
    "orbslam3_validation/afrl_cemetery_fr_s230_d30_clean_halfres_20260807/"
    "dataset"
)

CONFIG: dict[str, Any] = {
    "window_id": "AFRL_Cemetery_FR_s230_d30",
    "dataset": "AFRL",
    "sequence": "Cemetery-FR",
    "window": "s230_d30",
    "level": "repeatwise_strict",
    "selector_name": "n3_d14_min8_ignore0_clean_halfres",
    "texture_profile": "operational degraded/low-grid",
    "base_klt_profile": (
        "243-350 mean 315.968; frozen gate grid mean 0.723921 at 800x600"
    ),
    "operational_low_texture": True,
    "sparse_base_klt_low_texture": False,
    "formal_root": data(
        "orbslam3_seeded_validation/postinit_candidate_search_20260807/"
        f"afrl_cemetery_fr_s230_d30/{FORMAL_SUFFIX}"
    ),
    "clean_root": CLEAN_ROOT,
    "stats": CLEAN_ROOT / "stats.csv",
    "selector_root": SELECTOR_ROOT,
    "seed_root": SEED_ROOT,
    "dataset_root": DATASET_ROOT,
    "raw_bag": data("datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag"),
    "camera_config": KLT_ROOT / "afrl_cave_cam0_pinhole.yaml",
    "orb_config": (
        WORKSPACE / "logs/orbslam3_validation/afrl_cemetery_fr_cam1_half_mono.yaml"
    ),
    "rpe_delta": 20,
    "rpe_label": "20-associated-poses",
    "association_s": 0.06,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def one_csv_row(path: Path) -> dict[str, str]:
    rows = r08.read_csv(path)
    if len(rows) != 1:
        raise RuntimeError(f"expected one CSV row in {path}, got {len(rows)}")
    return rows[0]


def require_sha(path: Path, expected: str, label: str) -> None:
    observed = r08.sha256(path)
    if observed != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: {observed}")


def audit_feature_bag(
    path: Path, topic: str, width: int, height: int
) -> dict[str, Any]:
    ros_python = Path("/opt/ros/noetic/lib/python3/dist-packages")
    if str(ros_python) not in sys.path:
        sys.path.insert(0, str(ros_python))
    import rosbag  # type: ignore[import-not-found]

    frames = 0
    observations = 0
    ids: list[int] = []
    source_codes: Counter[int] = Counter()
    learned_codes: Counter[int] = Counter()
    out_of_bounds = 0
    required = {"id", "p_u", "p_v", "source_code", "is_learned"}
    with rosbag.Bag(str(path)) as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            frames += 1
            channels = {channel.name: channel.values for channel in message.channels}
            missing = required.difference(channels)
            if missing:
                raise RuntimeError(f"missing channels {sorted(missing)} in {path}")
            count = len(message.points)
            if any(len(channels[name]) != count for name in required):
                raise RuntimeError(f"channel length mismatch in {path}")
            observations += count
            ids.extend(int(round(value)) for value in channels["id"])
            source_codes.update(
                int(round(value)) for value in channels["source_code"]
            )
            learned_codes.update(
                int(round(value)) for value in channels["is_learned"]
            )
            out_of_bounds += sum(
                not (0.0 <= u < width and 0.0 <= v < height)
                for u, v in zip(channels["p_u"], channels["p_v"])
            )
    if frames == 0 or observations == 0:
        raise RuntimeError(f"empty feature topic {topic} in {path}")
    return {
        "frames": frames,
        "observations": observations,
        "unique_ids": len(set(ids)),
        "high_id_observations": sum(value >= 10_000_000 for value in ids),
        "source_codes": dict(sorted(source_codes.items())),
        "learned_codes": dict(sorted(learned_codes.items())),
        "out_of_bounds": out_of_bounds,
    }


def audit_source_contract() -> dict[str, Any]:
    base = one_csv_row(CLEAN_ROOT / "base_drop_stats.csv")
    expected_base = {
        "feature_frames": "278",
        "frames_with_drops": "0",
        "dropped_observations": "0",
        "kept_learned_observations": "0",
        "learned_track_ids": "0",
        "kept_observations": "87839",
        "drop_learned": "0",
        "drop_learned_track_lineage": "1",
        "learned_id_min": "10000000",
    }
    for key, expected in expected_base.items():
        if base.get(key) != expected:
            raise RuntimeError(f"clean base contract mismatch: {key}={base.get(key)}")

    selector = r08.parse_manifest(SELECTOR_ROOT / "manifest.txt")
    expected_selector = {
        "max_lineages": "3",
        "min_distance_px": "14",
        "ignore_zero_base_speeds": "0",
        "min_observations": "8",
        "rearm_absent_frames": "0",
        "drop_bag_sha256": KLT_FEATURES_SHA256,
        "full_bag_sha256": FULL_MERGED_SHA256,
    }
    for key, expected in expected_selector.items():
        if selector.get(key) != expected:
            raise RuntimeError(f"selector contract mismatch: {key}={selector.get(key)}")

    sidecar_stats = r08.read_csv(CLEAN_ROOT / "stats.csv")
    triggers = [row for row in sidecar_stats if row["triggered"] == "1"]
    trigger_frames = [int(row["frame_index"]) for row in triggers]
    trigger_added = [int(row["added_seeds"]) for row in triggers]
    if len(sidecar_stats) != 278 or trigger_frames != [16, 28, 45]:
        raise RuntimeError(
            f"sidecar trigger contract mismatch: {len(sidecar_stats)}, {trigger_frames}"
        )
    if trigger_added != [50, 50, 50]:
        raise RuntimeError(f"sidecar trigger dose mismatch: {trigger_added}")

    seed_export = json.loads(
        (SEED_ROOT / "seed_export_stats.json").read_text(encoding="utf-8")
    )
    expected_seed_export = {
        "source_messages": 278,
        "mapped_feature_frames": 278,
        "seed_ids": 3,
        "seed_frames": 43,
        "seed_observations": 47,
        "max_timestamp_difference_ns": 0,
        "rejected_nonfinite": 0,
        "rejected_out_of_bounds": 0,
        "rejected_by_stride": 0,
        "rejected_by_lineage_maturity": 0,
        "source_code": 20,
    }
    for key, expected in expected_seed_export.items():
        if seed_export.get(key) != expected:
            raise RuntimeError(f"seed export contract mismatch: {key}={seed_export.get(key)}")

    metadata = json.loads(
        (DATASET_ROOT / "export_metadata.json").read_text(encoding="utf-8")
    )
    expected_metadata = {
        "requested_image_count": 278,
        "kept_images": 278,
        "image_width": 800,
        "image_height": 600,
        "imu_count": 3000,
        "gt_count": 556,
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise RuntimeError(f"dataset export mismatch: {key}={metadata.get(key)}")

    require_sha(KLT_ROOT / "features.bag", KLT_FEATURES_SHA256, "fresh KLT bag")
    require_sha(KLT_ROOT / "cave_gennie_short.bag", SHORT_BAG_SHA256, "short bag")
    require_sha(CLEAN_ROOT / "base_drop.bag", KLT_FEATURES_SHA256, "clean base")
    require_sha(CLEAN_ROOT / "sidecar.bag", SIDECAR_SHA256, "sidecar")
    require_sha(SELECTOR_ROOT / "full_merged.bag", FULL_MERGED_SHA256, "full bag")
    require_sha(SEED_ROOT / "full_seeds.txt", FULL_SEEDS_SHA256, "full seeds")
    require_sha(SEED_ROOT / "feature_times.txt", FEATURE_TIMES_SHA256, "feature times")
    require_sha(DATASET_ROOT / "cam0_times.txt", FEATURE_TIMES_SHA256, "dataset times")

    fresh_bag = audit_feature_bag(
        KLT_ROOT / "features.bag", "/feature_tracker/feature", 800, 600
    )
    expected_fresh_bag = {
        "frames": 278,
        "observations": 87839,
        "unique_ids": 11538,
        "high_id_observations": 0,
        "source_codes": {1: 87489, 2: 350},
        "learned_codes": {0: 87839},
        "out_of_bounds": 0,
    }
    if fresh_bag != expected_fresh_bag:
        raise RuntimeError(f"fresh KLT bag audit mismatch: {fresh_bag}")

    sidecar_bag = audit_feature_bag(
        CLEAN_ROOT / "sidecar.bag", "/feature_tracker/sidecar", 800, 600
    )
    expected_sidecar_bag = {
        "frames": 278,
        "observations": 602,
        "unique_ids": 150,
        "high_id_observations": 0,
        "source_codes": {20: 602},
        "learned_codes": {1: 602},
        "out_of_bounds": 0,
    }
    if sidecar_bag != expected_sidecar_bag:
        raise RuntimeError(f"sidecar bag audit mismatch: {sidecar_bag}")

    full_bag = audit_feature_bag(
        SELECTOR_ROOT / "full_merged.bag",
        "/feature_tracker/feature",
        800,
        600,
    )
    expected_full_bag = {
        "frames": 278,
        "observations": 87886,
        "unique_ids": 11541,
        "high_id_observations": 47,
        "source_codes": {1: 87489, 2: 350, 20: 47},
        "learned_codes": {0: 87839, 1: 47},
        "out_of_bounds": 0,
    }
    if full_bag != expected_full_bag:
        raise RuntimeError(f"selected full bag audit mismatch: {full_bag}")

    return {
        "fresh_klt_frames": int(base["feature_frames"]),
        "fresh_klt_observations": int(base["kept_observations"]),
        "learned_observations_removed": int(base["dropped_observations"]),
        "sidecar_frames": len(sidecar_stats),
        "sidecar_triggers": len(triggers),
        "sidecar_trigger_frames": trigger_frames,
        "sidecar_candidates": sum(trigger_added),
        "seed_ids": seed_export["seed_ids"],
        "seed_frames": seed_export["seed_frames"],
        "seed_observations": seed_export["seed_observations"],
        "seed_max_timestamp_difference_ns": seed_export[
            "max_timestamp_difference_ns"
        ],
        "image_count": metadata["kept_images"],
        "image_width": metadata["image_width"],
        "image_height": metadata["image_height"],
        "klt_features_sha256": KLT_FEATURES_SHA256,
        "sidecar_sha256": SIDECAR_SHA256,
        "full_bag_sha256": FULL_MERGED_SHA256,
        "full_seeds_sha256": FULL_SEEDS_SHA256,
        "feature_times_sha256": FEATURE_TIMES_SHA256,
        "fresh_bag_audit": fresh_bag,
        "sidecar_bag_audit": sidecar_bag,
        "selected_full_bag_audit": full_bag,
    }


def roster_row(result: dict[str, Any]) -> dict[str, Any]:
    full = result["action"]["full"]
    return {
        "window_id": CONFIG["window_id"],
        "dataset": CONFIG["dataset"],
        "sequence": CONFIG["sequence"],
        "window": CONFIG["window"],
        "level": CONFIG["level"],
        "independent_window": "true",
        "primary_selector": CONFIG["selector_name"],
        "accepted_post_init": (
            f"{full['post_init_accepted']}/{full['post_init_attempted']}"
        ),
        "seed_lineages_with_mappoint": full["mappoint_lineages"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "texture_profile": CONFIG["texture_profile"],
        "base_klt_profile": CONFIG["base_klt_profile"],
        "operational_low_texture": "true",
        "sparse_base_klt_low_texture": "false",
        "source_report": REPORT_RELATIVE,
        "formal_root": str(CONFIG["formal_root"]),
    }


def build_report(
    result: dict[str, Any], source: dict[str, Any], counts: dict[str, int]
) -> str:
    action = result["action"]
    full = action["full"]
    unbounded = action["full_unbounded"]
    changes = result["improvements"]
    improvement_counts = {
        control: sum(value > 0 for value in values.values())
        for control, values in changes.items()
    }
    return "\n".join(
        [
            "# ORB-SLAM3 v23 AFRL Cemetery-FR evidence closure R11",
            "",
            "Date: 2026-08-07",
            "",
            "## Decision",
            "",
            "AFRL Cemetery-FR `s230,d30` is a new independent cross-dataset",
            "repeatwise-strict action and trajectory-positive window. Frozen v23",
            "improves reconstructed and online APE/RPE against native ORB, empty",
            "drop, bridge-off, and unbounded controls in all comparisons.",
            "",
            "No selector, bridge, dose, phase, binary, library, runner, camera, or",
            "evaluator threshold was changed.",
            "",
            "## Frozen validation",
            "",
            "All `20/20` formal runs have status `ok`. Each role has one counter",
            "signature and one reconstructed, online, and keyframe SHA-256 across four",
            "repeats. Repeat 4 swaps `full` and `full_unbounded`. All 20 snapshot",
            "manifests and all `576/576` entries pass SHA-256 verification.",
            "",
            f"Classification: `{CONFIG['level']}`. Evaluation uses a `0.06 s`",
            "association threshold and 20-associated-pose RPE.",
            "",
            "| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| Bridge off | {action['full_bridge_off']['post_init_accepted']}/{action['full_bridge_off']['post_init_attempted']} | {action['full_bridge_off']['mappoint_lineages']} / {action['full_bridge_off']['distinct_mappoints']} | 0 | 0 | 0 / 0 | 0 |",
            f"| Unbounded | {unbounded['post_init_accepted']}/{unbounded['post_init_attempted']} | {unbounded['mappoint_lineages']} / {unbounded['distinct_mappoints']} | {unbounded['matches']} | {unbounded['outliers']} | {unbounded['pre_kf_observed']} / {unbounded['pre_kf_purged']} | {unbounded['scans']} |",
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
            "Frozen v23 change versus native (positive is better):",
            "",
            f"- reconstructed APE/RPE: `{changes['orb_only']['reconstructed_ape']:.3f}% / {changes['orb_only']['reconstructed_rpe']:.3f}%`",
            f"- online APE/RPE: `{changes['orb_only']['online_ape']:.3f}% / {changes['orb_only']['online_rpe']:.3f}%`",
            f"- improved metrics: native `{improvement_counts['orb_only']}/4`; bridge-off `{improvement_counts['full_bridge_off']}/4`; unbounded `{improvement_counts['full_unbounded']}/4`",
            "",
            "## Fresh source contract",
            "",
            f"The clean rebuild contains {source['fresh_klt_frames']} feature frames",
            f"and {source['fresh_klt_observations']} native observations. It removes",
            f"{source['learned_observations_removed']} observations: there is no",
            "historical learned lineage in the base. All feature coordinates are from",
            "the cam1 front-right 800x600 contract.",
            "",
            f"The frozen sidecar runs {source['sidecar_triggers']} triggers at frames",
            f"{source['sidecar_trigger_frames']} and proposes {source['sidecar_candidates']}",
            f"candidates. The frozen selector exports {source['seed_ids']} IDs,",
            f"{source['seed_frames']} frames, and {source['seed_observations']}",
            f"observations with {source['seed_max_timestamp_difference_ns']} ns maximum",
            "timestamp error. No exported seed is non-finite or out of bounds.",
            "",
            "## Texture and denominator",
            "",
            f"Tracks min/mean/max are `{result['base_track_min']:.0f} / {result['base_track_mean']:.3f} / {result['base_track_max']:.0f}`;",
            f"grid min/mean/max are `{result['base_grid_min']:.6f} / {result['base_grid_mean']:.6f} / {result['base_grid_max']:.6f}`;",
            f"`{result['low_grid_frames']}/{result['frontend_frames']}` frames are at or below `0.80`.",
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
            "- Count AFRL Cemetery-FR `s230,d30` once as development evidence.",
            "- It is project strict and all-control repeatwise strict under this frozen grid.",
            "- It is cross-dataset development evidence, not untouched confirmation.",
            "- The generic KLT camera filename says cam0, but its parameters and all",
            "  ORB inputs are the cam1 front-right half-resolution calibration.",
            "",
            f"Formal root: `{CONFIG['formal_root']}`",
            "",
        ]
    )


def provenance_artifacts() -> list[tuple[str, Path]]:
    formal_root: Path = CONFIG["formal_root"]
    return [
        (
            "analysis_builder",
            WORKSPACE / "scripts/analyze_orbslam3_v23_afrl_cemetery_fr_r11.py",
        ),
        ("clean_filter", WORKSPACE / "scripts/filter_feature_bag_by_channel.py"),
        ("selector_runner", WORKSPACE / "scripts/prepare_causal_multilineage_bag.sh"),
        (
            "selector_node",
            WORKSPACE / "uw_frontend/ros/causal_lineage_shadow_node.py",
        ),
        (
            "sidecar_generator_frozen",
            CLEAN_ROOT / "provenance/xfeat_seed_sidecar_node_9afc.py",
        ),
        (
            "sidecar_config",
            WORKSPACE
            / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml",
        ),
        (
            "dataset_exporter",
            WORKSPACE / "scripts/prepare_orbslam3_aqualoc_bag.py",
        ),
        ("seed_exporter", WORKSPACE / "scripts/export_orbslam3_confirmed_seeds.py"),
        ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        ("raw_bag", CONFIG["raw_bag"]),
        ("short_bag", KLT_ROOT / "cave_gennie_short.bag"),
        ("fresh_klt_bag", KLT_ROOT / "features.bag"),
        ("fresh_klt_metrics", KLT_ROOT / "frontend_metrics.csv"),
        ("fresh_klt_manifest", KLT_ROOT / "replay_manifest.txt"),
        ("fresh_klt_camera", CONFIG["camera_config"]),
        ("orb_camera", CONFIG["orb_config"]),
        ("clean_base_stats", CLEAN_ROOT / "base_drop_stats.csv"),
        ("clean_base_bag", CLEAN_ROOT / "base_drop.bag"),
        ("sidecar_stats", CLEAN_ROOT / "stats.csv"),
        ("sidecar_bag", CLEAN_ROOT / "sidecar.bag"),
        ("selector_manifest", SELECTOR_ROOT / "manifest.txt"),
        ("selector_lineages", SELECTOR_ROOT / "lineage_selection.csv"),
        ("selector_drop_bag", SELECTOR_ROOT / "drop_whole_lineage.bag"),
        ("selector_full_bag", SELECTOR_ROOT / "full_merged.bag"),
        ("full_seeds", SEED_ROOT / "full_seeds.txt"),
        ("drop_seeds", SEED_ROOT / "drop_seeds.txt"),
        ("feature_times", SEED_ROOT / "feature_times.txt"),
        ("seed_export_stats", SEED_ROOT / "seed_export_stats.json"),
        ("dataset_metadata", DATASET_ROOT / "export_metadata.json"),
        ("dataset_times", DATASET_ROOT / "cam0_times.txt"),
        ("dataset_groundtruth", DATASET_ROOT / "groundtruth_tum.txt"),
        ("evaluation_reconstructed", formal_root / "evaluation_reconstructed.csv"),
        ("evaluation_online", formal_root / "evaluation_online.csv"),
    ]


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"output exists; pass --replace: {output}")

    result = r08.evaluate_window(CONFIG)
    improvement_counts = {
        control: sum(value > 0 for value in changes.values())
        for control, changes in result["improvements"].items()
    }
    expected_improvements = {
        "orb_only": 4,
        "drop": 4,
        "full_bridge_off": 4,
        "full_unbounded": 4,
    }
    if improvement_counts != expected_improvements:
        raise RuntimeError(f"unexpected trajectory classification: {improvement_counts}")

    expected_actions = {
        "full_bridge_off": (47, 47, 0, 1, 8, 0, 0, 0, 0, 0),
        "full_unbounded": (47, 47, 0, 1, 17, 20, 3, 0, 1, 272),
        "full": (47, 47, 0, 1, 18, 19, 3, 1, 1, 272),
    }
    for role, expected in expected_actions.items():
        action = result["action"][role]
        observed = (
            action["post_init_accepted"],
            action["post_init_attempted"],
            action["pre_init_attempted"],
            action["mappoint_lineages"],
            action["distinct_mappoints"],
            action["matches"],
            action["outliers"],
            action["pre_kf_purged"],
            action["pre_kf_observed"],
            action["scans"],
        )
        if observed != expected:
            raise RuntimeError(f"unexpected {role} action: {observed}")

    source = audit_source_contract()
    prior = r08.read_csv(PRIOR_ROSTER)
    if len(prior) != 17 or len({row["window_id"] for row in prior}) != 17:
        raise RuntimeError("prior R10 roster is not 17 unique windows")
    if any(row["window_id"] == CONFIG["window_id"] for row in prior):
        raise RuntimeError("AFRL Cemetery-FR s230,d30 already exists in prior roster")
    roster = prior + [roster_row(result)]
    if len(roster) != 18 or len({row["window_id"] for row in roster}) != 18:
        raise RuntimeError("R11 roster is not 18 unique windows")

    counts = r09.roster_counts(roster)
    expected_counts = {
        "action_positive": 18,
        "project_strict": 6,
        "all_control_strict": 3,
        "operational_low_grid": 11,
        "strict_operational_low_grid": 4,
        "sparse_base_klt": 0,
    }
    if counts != expected_counts:
        raise RuntimeError(f"unexpected R11 roster counts: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        r08.write_csv(temp / "formal_summary.csv", [r08.formal_summary(result)])
        r08.write_csv(temp / "window_roster.csv", roster)

        provenance_rows = []
        for name, path in provenance_artifacts():
            resolved = path.resolve()
            if not resolved.is_file():
                raise RuntimeError(f"missing provenance artifact: {resolved}")
            provenance_rows.append(
                {
                    "artifact": name,
                    "sha256": r08.sha256(resolved),
                    "path": str(resolved),
                }
            )
        r08.write_csv(temp / "provenance.csv", provenance_rows)

        validation = {
            "schema_version": 5,
            "date": "2026-08-07",
            "added_windows": 1,
            "roster_rows": len(roster),
            "roster_unique_windows": len({row["window_id"] for row in roster}),
            "updated_counts": counts,
            "snapshot_manifests": 20,
            "snapshot_manifests_verified": 20,
            "snapshot_entries": result["snapshot_entries"],
            "snapshot_entries_verified": result["snapshot_entries"],
            "source_contract": source,
            "windows": {
                CONFIG["window_id"]: {
                    "action_positive": True,
                    "level": CONFIG["level"],
                    "native_negative": False,
                    "non_strict": False,
                    "project_strict": True,
                    "all_control_strict": True,
                    "repeat4_order_swapped": True,
                    "formal_runs": 20,
                    "formal_runs_ok": 20,
                    "full_vs_native_improvements": improvement_counts["orb_only"],
                    "full_vs_bridge_off_improvements": improvement_counts[
                        "full_bridge_off"
                    ],
                    "full_vs_unbounded_improvements": improvement_counts[
                        "full_unbounded"
                    ],
                    "operational_low_grid": True,
                    "sparse_base_klt": False,
                    "low_grid_frames_le_0p80": result["low_grid_frames"],
                    "frontend_frames": result["frontend_frames"],
                    "role_counter_signatures": result["counter_signatures"],
                    "role_reconstructed_hashes": result["trajectory_hashes"][
                        "reconstructed"
                    ],
                    "role_online_hashes": result["trajectory_hashes"]["online"],
                    "role_keyframe_hashes": result["trajectory_hashes"]["keyframe"],
                    "snapshot_manifests": 20,
                    "snapshot_manifests_verified": 20,
                    "snapshot_entries": result["snapshot_entries"],
                    "snapshot_entries_verified": result["snapshot_entries"],
                    "formal_root": str(CONFIG["formal_root"]),
                }
            },
        }
        (temp / "validation_summary.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        (temp / "analysis-report.md").write_text(
            build_report(result, source, counts), encoding="ascii"
        )

        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(f"wrote validated R11 AFRL Cemetery-FR bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
