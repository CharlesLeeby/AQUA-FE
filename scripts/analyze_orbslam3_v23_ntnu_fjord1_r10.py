#!/usr/bin/env python3
"""Build the R10 evidence bundle for NTNU fjord1 s30,d30."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import analyze_orbslam3_v23_a01_r09 as r09
import analyze_orbslam3_v23_continued_search_r08 as r08


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
DEFAULT_OUTPUT = (
    WORKSPACE / "papers/orb_v23_ntnu_fjord1_r10_20260806/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE / "papers/orb_v23_a01_r09_20260806/analysis-output/window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_ntnu_fjord1_r10_20260806/analysis-output/analysis-report.md"
)
FORMAL_SUFFIX = (
    "formal_n3_d14_min8_ignore0_clean_legacyid_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)
CANONICAL_MESSAGE_SHA256 = (
    "7cd79f97918957be564b426733946f8d719311c6e19143a4772dae1e245b8829"
)
FULL_SEEDS_SHA256 = (
    "4a5805f863c50a96c09910e34a64b43bb171db0088aacf18db1ef4aca339226f"
)
FEATURE_TIMES_SHA256 = (
    "13da054a1d8c2542fd2e04043e3a8c47e00104da4cf90c1b18955802370c6862"
)


def data(path: str) -> Path:
    return DATA_ROOT / path


CONFIG: dict[str, Any] = {
    "window_id": "NTNU_fjord1_s30_d30",
    "dataset": "NTNU",
    "sequence": "fjord1",
    "window": "s30_d30",
    "level": "action_positive_metric_negative_native_negative_non_strict",
    "selector_name": "n3_d14_min8_ignore0_clean_legacyid",
    "texture_profile": "operational degraded/low-grid",
    "base_klt_profile": (
        "180 cap; 95-180 mean 167.827; grid mean 0.553241"
    ),
    "operational_low_texture": True,
    "sparse_base_klt_low_texture": False,
    "formal_root": data(
        "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
        f"ntnu_fjord1_s30_d30/{FORMAL_SUFFIX}"
    ),
    "clean_root": data(
        "online_positive_search_20260806/ntnu_fjord1_s30_d30/"
        "clean_ignore0_legacyid"
    ),
    "stats": data(
        "online_positive_search_20260806/ntnu_fjord1_s30_d30/"
        "clean_ignore0_legacyid/stats.csv"
    ),
    "selector_root": data(
        "orbslam3_seeded_validation/multilineage/ntnu_fjord1_s30_d30/"
        "n3_d14_min8_ignore0_clean_legacyid_20260806"
    ),
    "seed_root": data(
        "orbslam3_seeded_validation/postinit_candidate_search_20260806/"
        "ntnu_fjord1_s30_d30/assets_n3_d14_min8_ignore0_clean_legacyid"
    ),
    "dataset_root": data(
        "orbslam3_validation/ntnu_fjord1_s30_d30_clean_20260806/dataset"
    ),
    "raw_bag": data(
        "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_1/fjord_1.bag"
    ),
    "raw_gt": data(
        "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_1/"
        "fjord_1_baseline.tum"
    ),
    "historical_bag": data(
        "logs/ntnu_vins/"
        "external_hybrid_xfeat_every2_paperpair_fjord_1_s30_d30_hybrid_xfeat/"
        "features.bag"
    ),
    "camera_config": data(
        "logs/ntnu_vins/"
        "external_hybrid_xfeat_every2_paperpair_fjord_1_s30_d30_hybrid_xfeat/"
        "ntnu_cam0_kannala_brandt.yaml"
    ),
    "orb_config": WORKSPACE / "logs/orbslam3_validation/ntnu_fjord_cam0_mono.yaml",
    "rpe_delta": 20,
    "rpe_label": "20-associated-poses",
    "association_s": 0.02,
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


def canonical_bag_digest(path: Path) -> tuple[int, str]:
    ros_python = Path("/opt/ros/noetic/lib/python3/dist-packages")
    if str(ros_python) not in sys.path:
        sys.path.insert(0, str(ros_python))
    import rosbag  # type: ignore[import-not-found]

    digest = hashlib.sha256()
    messages = 0
    with rosbag.Bag(str(path)) as bag:
        for topic, message, stamp in bag.read_messages():
            normalized = copy.deepcopy(message)
            if topic == "/feature_tracker/feature":
                normalized.channels = [
                    channel
                    for channel in normalized.channels
                    if channel.name not in {"source_code", "is_learned"}
                ]
            buffer = io.BytesIO()
            normalized.serialize(buffer)
            digest.update(topic.encode("utf-8"))
            digest.update(stamp.to_nsec().to_bytes(8, "little"))
            digest.update(buffer.getvalue())
            messages += 1
    return messages, digest.hexdigest()


def audit_source_contract() -> dict[str, Any]:
    clean_root: Path = CONFIG["clean_root"]
    selector_root: Path = CONFIG["selector_root"]
    seed_root: Path = CONFIG["seed_root"]
    dataset_root: Path = CONFIG["dataset_root"]

    base = one_csv_row(clean_root / "base_drop_stats.csv")
    expected_base = {
        "feature_frames": "300",
        "frames_with_drops": "8",
        "dropped_observations": "15",
        "kept_learned_observations": "0",
        "learned_track_ids": "7",
        "kept_observations": "50348",
        "drop_learned": "0",
        "drop_learned_track_lineage": "1",
        "learned_id_min": "1000000",
    }
    for key, expected in expected_base.items():
        if base.get(key) != expected:
            raise RuntimeError(f"legacy clean contract mismatch: {key}={base.get(key)}")

    normalization = one_csv_row(
        selector_root / "source_channel_normalization_stats.csv"
    )
    expected_normalization = {
        "feature_frames": "300",
        "observations": "50486",
        "learned_observations": "138",
        "source_code_channels_added": "208",
        "is_learned_channels_added": "208",
        "existing_channels_verified": "92",
        "learned_id_min": "1000000",
        "learned_source_code": "20",
    }
    for key, expected in expected_normalization.items():
        if normalization.get(key) != expected:
            raise RuntimeError(
                f"source normalization contract mismatch: {key}={normalization.get(key)}"
            )

    selector = r08.parse_manifest(selector_root / "manifest.txt")
    expected_selector = {
        "max_lineages": "3",
        "min_distance_px": "14",
        "ignore_zero_base_speeds": "0",
        "min_observations": "8",
        "rearm_absent_frames": "0",
    }
    for key, expected in expected_selector.items():
        if selector.get(key) != expected:
            raise RuntimeError(f"selector contract mismatch: {key}={selector.get(key)}")

    seed_export = json.loads(
        (seed_root / "seed_export_stats.json").read_text(encoding="utf-8")
    )
    expected_seed_export = {
        "source_messages": 300,
        "mapped_feature_frames": 300,
        "seed_ids": 3,
        "seed_frames": 92,
        "seed_observations": 138,
        "max_timestamp_difference_ns": 0,
        "rejected_nonfinite": 0,
        "rejected_out_of_bounds": 0,
        "source_code": 20,
    }
    for key, expected in expected_seed_export.items():
        if seed_export.get(key) != expected:
            raise RuntimeError(f"seed export contract mismatch: {key}={seed_export.get(key)}")
    if r08.sha256(seed_root / "full_seeds.txt") != FULL_SEEDS_SHA256:
        raise RuntimeError("full seed SHA-256 mismatch")
    if r08.sha256(seed_root / "feature_times.txt") != FEATURE_TIMES_SHA256:
        raise RuntimeError("feature-times SHA-256 mismatch")

    metadata = json.loads(
        (dataset_root / "export_metadata.json").read_text(encoding="utf-8")
    )
    expected_metadata = {
        "start_offset_sec": 30.0,
        "duration_sec": 30.0,
        "every_n": 1,
        "image_count": 599,
        "image_width": 720,
        "image_height": 540,
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise RuntimeError(f"dataset export mismatch: {key}={metadata.get(key)}")

    original_bag = selector_root / "full_merged.bag"
    normalized_bag = selector_root / "full_merged_source_normalized.bag"
    original_messages, original_sha = canonical_bag_digest(original_bag)
    normalized_messages, normalized_sha = canonical_bag_digest(normalized_bag)
    if (
        original_messages != 6300
        or normalized_messages != 6300
        or original_sha != CANONICAL_MESSAGE_SHA256
        or normalized_sha != CANONICAL_MESSAGE_SHA256
    ):
        raise RuntimeError(
            "source normalization changed canonical messages: "
            f"original={original_messages}/{original_sha}, "
            f"normalized={normalized_messages}/{normalized_sha}"
        )

    return {
        "legacy_clean_frames": int(base["feature_frames"]),
        "legacy_clean_frames_with_drops": int(base["frames_with_drops"]),
        "legacy_observations_removed": int(base["dropped_observations"]),
        "legacy_native_observations_kept": int(base["kept_observations"]),
        "normalization_frames": int(normalization["feature_frames"]),
        "normalization_observations": int(normalization["observations"]),
        "normalization_learned_observations": int(
            normalization["learned_observations"]
        ),
        "source_code_channels_added": int(
            normalization["source_code_channels_added"]
        ),
        "is_learned_channels_added": int(
            normalization["is_learned_channels_added"]
        ),
        "canonical_messages": original_messages,
        "canonical_sha256": original_sha,
        "canonical_equal_after_added_channels_removed": True,
        "seed_ids": seed_export["seed_ids"],
        "seed_frames": seed_export["seed_frames"],
        "seed_observations": seed_export["seed_observations"],
        "seed_max_timestamp_difference_ns": seed_export[
            "max_timestamp_difference_ns"
        ],
        "full_seeds_sha256": FULL_SEEDS_SHA256,
        "feature_times_sha256": FEATURE_TIMES_SHA256,
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
            "# ORB-SLAM3 v23 NTNU fjord1 evidence closure R10",
            "",
            "Date: 2026-08-06",
            "",
            "## Decision",
            "",
            "NTNU fjord1 `s30,d30` is a new independent cross-dataset",
            "mechanism/action-positive window. The frozen full role consumes natural",
            "assisted outliers and performs an enforced pre-KF purge. It is",
            "operational low-grid, but native-negative in all four reconstructed and",
            "online APE/RPE comparisons. It is non-strict development evidence, not",
            "trajectory-positive or no-harm evidence.",
            "",
            "No selector, bridge, dose, phase, binary, library, runner, or evaluator",
            "threshold was changed.",
            "",
            "## Frozen validation",
            "",
            "All `20/20` formal runs have status `ok`. Each role has one counter",
            "signature and one reconstructed, online, and keyframe SHA-256 across four",
            "repeats. Repeat 4 swaps `full` and `full_unbounded`. All 20 snapshot",
            "manifests and all `576/576` listed entries pass independent SHA-256",
            "verification.",
            "",
            f"Classification: `{CONFIG['level']}`. Evaluation uses a `0.02 s`",
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
            "v23 change versus native (positive is better):",
            "",
            f"- reconstructed APE/RPE: `{changes['orb_only']['reconstructed_ape']:.3f}% / {changes['orb_only']['reconstructed_rpe']:.3f}%`",
            f"- online APE/RPE: `{changes['orb_only']['online_ape']:.3f}% / {changes['orb_only']['online_rpe']:.3f}%`",
            f"- improved metrics: native `{improvement_counts['orb_only']}/4`; bridge-off `{improvement_counts['full_bridge_off']}/4`; unbounded `{improvement_counts['full_unbounded']}/4`",
            "",
            "## Legacy source contract",
            "",
            f"The valid clean rebuild removes {source['legacy_observations_removed']} old",
            f"high-ID learned observations from {source['legacy_clean_frames_with_drops']}",
            f"frames and keeps {source['legacy_native_observations_kept']} native",
            "observations. The earlier source-code-only clean directory is invalid and",
            "is not used by this bundle.",
            "",
            f"The normalized selector bag contains {source['normalization_frames']}",
            f"feature frames, {source['normalization_observations']} observations, and",
            f"{source['normalization_learned_observations']} learned observations.",
            f"It adds {source['source_code_channels_added']} `source_code` and",
            f"{source['is_learned_channels_added']} `is_learned` channels. Removing",
            f"those added channels yields the same {source['canonical_messages']}-message",
            f"canonical SHA-256 `{source['canonical_sha256']}` before and after",
            "normalization.",
            "",
            f"Seed export is {source['seed_ids']} IDs, {source['seed_frames']} frames,",
            f"and {source['seed_observations']} observations with",
            f"{source['seed_max_timestamp_difference_ns']} ns maximum timestamp error.",
            "No seed is non-finite or out of bounds, and every accepted seed is",
            "post-init in formal instrumentation.",
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
            "- Count NTNU fjord1 `s30,d30` once as development-only action evidence.",
            "- Do not call it trajectory-positive, no-harm, project strict, or all-control strict.",
            "- Do not use the invalid non-legacy-ID clean directory as evidence.",
            "- This is cross-dataset development evidence, not untouched confirmation.",
            "",
            f"Formal root: `{CONFIG['formal_root']}`",
            "",
        ]
    )


def provenance_artifacts() -> list[tuple[str, Path]]:
    clean_root: Path = CONFIG["clean_root"]
    selector_root: Path = CONFIG["selector_root"]
    seed_root: Path = CONFIG["seed_root"]
    dataset_root: Path = CONFIG["dataset_root"]
    formal_root: Path = CONFIG["formal_root"]
    return [
        ("analysis_builder", Path(__file__).resolve()),
        (
            "analysis_core_r08",
            WORKSPACE / "scripts/analyze_orbslam3_v23_continued_search_r08.py",
        ),
        ("prior_r09_builder", WORKSPACE / "scripts/analyze_orbslam3_v23_a01_r09.py"),
        ("prior_roster", PRIOR_ROSTER),
        ("legacy_clean_filter", WORKSPACE / "scripts/filter_feature_bag_by_channel.py"),
        (
            "source_channel_normalizer",
            WORKSPACE / "scripts/normalize_feature_source_channels.py",
        ),
        ("selector_runner", WORKSPACE / "scripts/prepare_causal_multilineage_bag.sh"),
        ("sidecar_generator", WORKSPACE / "uw_frontend/ros/xfeat_seed_sidecar_node.py"),
        (
            "sidecar_config",
            WORKSPACE
            / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml",
        ),
        ("dataset_exporter", WORKSPACE / "scripts/prepare_orbslam3_euroc_segment.py"),
        ("seed_exporter", WORKSPACE / "scripts/export_orbslam3_confirmed_seeds.py"),
        ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        ("raw_bag", CONFIG["raw_bag"]),
        ("raw_groundtruth", CONFIG["raw_gt"]),
        ("historical_feature_bag", CONFIG["historical_bag"]),
        ("historical_camera", CONFIG["camera_config"]),
        ("orb_camera", CONFIG["orb_config"]),
        ("clean_base_stats", clean_root / "base_drop_stats.csv"),
        ("clean_frontend_stats", CONFIG["stats"]),
        ("selector_manifest", selector_root / "manifest.txt"),
        ("selector_lineages", selector_root / "lineage_selection.csv"),
        ("selector_full_bag", selector_root / "full_merged.bag"),
        (
            "selector_normalized_bag",
            selector_root / "full_merged_source_normalized.bag",
        ),
        (
            "source_normalization_stats",
            selector_root / "source_channel_normalization_stats.csv",
        ),
        ("full_seeds", seed_root / "full_seeds.txt"),
        ("drop_seeds", seed_root / "drop_seeds.txt"),
        ("feature_times", seed_root / "feature_times.txt"),
        ("seed_export_stats", seed_root / "seed_export_stats.json"),
        ("dataset_metadata", dataset_root / "export_metadata.json"),
        ("dataset_times", dataset_root / "cam0_times.txt"),
        ("dataset_groundtruth", dataset_root / "groundtruth_tum.txt"),
        (
            "evaluation_reconstructed",
            formal_root / "evaluation_reconstructed.csv",
        ),
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
        "orb_only": 0,
        "drop": 0,
        "full_bridge_off": 4,
        "full_unbounded": 2,
    }
    if improvement_counts != expected_improvements:
        raise RuntimeError(f"unexpected trajectory classification: {improvement_counts}")

    full = result["action"]["full"]
    full_signature = (
        full["post_init_accepted"],
        full["post_init_attempted"],
        full["pre_init_attempted"],
        full["mappoint_lineages"],
        full["distinct_mappoints"],
        full["matches"],
        full["outliers"],
        full["pre_kf_purged"],
        full["pre_kf_observed"],
        full["scans"],
    )
    if full_signature != (138, 138, 0, 3, 7, 48, 4, 2, 2, 261):
        raise RuntimeError(f"unexpected frozen full action: {full_signature}")
    unbounded = result["action"]["full_unbounded"]
    unbounded_signature = (
        unbounded["post_init_accepted"],
        unbounded["post_init_attempted"],
        unbounded["pre_init_attempted"],
        unbounded["mappoint_lineages"],
        unbounded["distinct_mappoints"],
        unbounded["matches"],
        unbounded["outliers"],
        unbounded["pre_kf_purged"],
        unbounded["pre_kf_observed"],
        unbounded["scans"],
    )
    if unbounded_signature != (138, 138, 0, 3, 8, 46, 4, 0, 2, 227):
        raise RuntimeError(f"unexpected unbounded action: {unbounded_signature}")

    source = audit_source_contract()
    prior = r08.read_csv(PRIOR_ROSTER)
    if len(prior) != 16 or len({row["window_id"] for row in prior}) != 16:
        raise RuntimeError("prior R09 roster is not 16 unique windows")
    if any(row["window_id"] == CONFIG["window_id"] for row in prior):
        raise RuntimeError("NTNU fjord1 s30,d30 already exists in prior roster")
    roster = prior + [roster_row(result)]
    if len(roster) != 17 or len({row["window_id"] for row in roster}) != 17:
        raise RuntimeError("R10 roster is not 17 unique windows")

    counts = r09.roster_counts(roster)
    expected_counts = {
        "action_positive": 17,
        "project_strict": 5,
        "all_control_strict": 2,
        "operational_low_grid": 10,
        "strict_operational_low_grid": 3,
        "sparse_base_klt": 0,
    }
    if counts != expected_counts:
        raise RuntimeError(f"unexpected R10 roster counts: {counts}")

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
            "date": "2026-08-06",
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
                    "native_negative": True,
                    "non_strict": True,
                    "project_strict": False,
                    "all_control_strict": False,
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
    print(f"wrote validated R10 NTNU fjord1 bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
