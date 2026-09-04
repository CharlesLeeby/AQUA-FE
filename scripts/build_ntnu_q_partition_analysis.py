#!/usr/bin/env python3
"""Build the strict NTNU quality-partition analysis bundle.

The bundle is deliberately development-only.  Three serial VINS replays are
technical repeats of one NTNU event, not three independent scientific units.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import rosbag


ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/validation_20260805/"
    "ntnu_s83_d30_q_partition_factorial"
)
DEFAULT_SUMMARY = VALIDATION_ROOT / "g0_all_replays_max350/common_support_summary.json"
DEFAULT_METRICS = VALIDATION_ROOT / "g0_all_replays_max350/common_support_metrics.csv"
DEFAULT_EVO = VALIDATION_ROOT / "g0_all_replays_max350/evo_crosscheck.json"
DEFAULT_BASE_BAG = ROOT / (
    "logs/ntnu_vins/"
    "external_hybrid_xfeat_every2_validation_20260804_"
    "ntnu_fjord1_s83_d30_xfeat_historical_profile_nativeq/features.bag"
)
DEFAULT_OUTPUT = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "ntnu_q_partition_20260805/analysis-output"
)
ESTIMATOR_SOURCE = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/"
    "vins_estimator/src/estimator/estimator.cpp"
)

ARM_ORDER = [
    "native_learned",
    "kltq1_only",
    "gfttq1_only",
    "baseq1_xfeatnative",
]
ARM_METADATA = {
    "native_learned": {
        "label": "Native classical q",
        "short_label": "Native",
        "source1_q": "native",
        "source2_q": "native",
    },
    "kltq1_only": {
        "label": "Source 1 / propagated q=1",
        "short_label": "Source 1\nq=1",
        "source1_q": "1",
        "source2_q": "native",
    },
    "gfttq1_only": {
        "label": "GFTT birth / source 2 q=1",
        "short_label": "GFTT birth\nq=1",
        "source1_q": "native",
        "source2_q": "1",
    },
    "baseq1_xfeatnative": {
        "label": "Classical sources 1+2 q=1; XFeat native",
        "short_label": "Classical\nq=1",
        "source1_q": "1",
        "source2_q": "1",
    },
}
AUDIT_FILES = {
    "kltq1_only": VALIDATION_ROOT
    / "learned_kltq1_gfttnative_xfeatnative_audit.json",
    "gfttq1_only": VALIDATION_ROOT
    / "learned_kltnative_gfttq1_xfeatnative_audit.json",
    "baseq1_xfeatnative": VALIDATION_ROOT
    / "learned_baseq1_xfeatnative_audit.json",
}
OKABE_ITO = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "vermillion": "#D55E00",
    "black": "#000000",
    "sky": "#56B4E9",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--evo", type=Path, default=DEFAULT_EVO)
    parser.add_argument("--base-bag", type=Path, default=DEFAULT_BASE_BAG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_replay_rows(summary_path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    payload = load_json(summary_path)
    support = payload.get("support")
    arms = payload.get("arms")
    if not isinstance(support, dict) or not isinstance(arms, dict):
        raise ValueError("common-support summary is missing support or arms")
    if support.get("ape_valid") is not True or support.get("rpe_valid") is not True:
        raise ValueError("quality-partition common support is invalid")

    rows: list[dict[str, object]] = []
    pattern = re.compile(r"^(.*)_r([123])$")
    for arm_name, metrics in arms.items():
        match = pattern.match(str(arm_name))
        if match is None or not isinstance(metrics, dict):
            raise ValueError(f"unexpected arm row: {arm_name}")
        arm_key, replay_text = match.groups()
        if arm_key not in {*ARM_ORDER, "globalq1_learned"}:
            raise ValueError(f"unexpected arm key: {arm_key}")
        rows.append(
            {
                "arm_key": arm_key,
                "replay": int(replay_text),
                "ape_rmse_m": float(metrics["ape_rmse_m"]),
                "rpe_rmse_m": float(metrics["rpe_rmse_m"]),
                "matched_count": int(metrics["matched_count"]),
                "rpe_pairs": int(metrics["rpe_pairs"]),
            }
        )
    rows.sort(key=lambda row: (str(row["arm_key"]), int(row["replay"])))
    expected = 5 * 3
    if len(rows) != expected:
        raise ValueError(f"expected {expected} replay rows, found {len(rows)}")
    for arm_key in {*ARM_ORDER, "globalq1_learned"}:
        repeats = [row for row in rows if row["arm_key"] == arm_key]
        if [row["replay"] for row in repeats] != [1, 2, 3]:
            raise ValueError(f"arm {arm_key} does not have replay slots 1,2,3")
    return rows, support


def summarize_replays(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["arm_key"])].append(row)
    summaries: list[dict[str, object]] = []
    for arm_key in [*ARM_ORDER, "globalq1_learned"]:
        group = grouped[arm_key]
        if len(group) != 3:
            raise ValueError(f"expected three technical replays for {arm_key}")
        ape = [float(row["ape_rmse_m"]) for row in group]
        rpe = [float(row["rpe_rmse_m"]) for row in group]
        metadata = ARM_METADATA.get(
            arm_key,
            {
                "label": "Global q=1 learned comparator",
                "short_label": "Global q=1",
                "source1_q": "1",
                "source2_q": "1",
            },
        )
        summaries.append(
            {
                "arm_key": arm_key,
                "label": metadata["label"],
                "source1_q": metadata["source1_q"],
                "source2_q": metadata["source2_q"],
                "technical_replays": 3,
                "scientific_units": 1,
                "ape_median_m": statistics.median(ape),
                "ape_min_m": min(ape),
                "ape_max_m": max(ape),
                "rpe_median_m": statistics.median(rpe),
                "rpe_min_m": min(rpe),
                "rpe_max_m": max(rpe),
            }
        )
    return summaries


def channel(msg, name: str) -> list[float]:
    for item in msg.channels:
        if item.name == name:
            return list(item.values)
    raise ValueError(f"feature message is missing channel {name}")


def analyze_lineages(base_bag: Path) -> tuple[dict[str, object], list[float]]:
    tracks: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    feature_frames = 0
    with rosbag.Bag(str(base_bag), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=["/feature_tracker/feature"]):
            ids = channel(msg, "id")
            sources = channel(msg, "source_code")
            quality = channel(msg, "quality")
            if not (len(ids) == len(sources) == len(quality) == len(msg.points)):
                raise ValueError(f"feature channel mismatch at frame {feature_frames}")
            for raw_id, raw_source, raw_q in zip(ids, sources, quality):
                feature_id = int(round(raw_id))
                source = int(round(raw_source))
                q = float(raw_q)
                if not math.isfinite(q) or q <= 0.0 or q > 1.0:
                    raise ValueError(f"invalid q for feature {feature_id}")
                tracks[feature_id].append((feature_frames, source, q))
            feature_frames += 1

    source_counts: dict[int, int] = defaultdict(int)
    for observations in tracks.values():
        for _frame, source, _q in observations:
            source_counts[source] += 1

    gftt_tracks: list[list[tuple[int, int, float]]] = []
    for feature_id, observations in tracks.items():
        source2_indices = [index for index, item in enumerate(observations) if item[1] == 2]
        if not source2_indices:
            continue
        if source2_indices != [0]:
            raise ValueError(
                f"source 2 is not a unique birth observation for feature {feature_id}"
            )
        if any(item[1] != 1 for item in observations[1:]):
            raise ValueError(f"GFTT-born feature {feature_id} has an unexpected later source")
        gftt_tracks.append(observations)

    factor_scale_deltas: list[float] = []
    factor_opportunities = 0
    positive_delta_opportunities = 0
    eligible_tracks = 0
    eligible_tracks_positive = 0
    for observations in gftt_tracks:
        if len(observations) < 4:
            continue
        eligible_tracks += 1
        birth_q = observations[0][2]
        has_positive = False
        for _frame, _source, current_q in observations[1:]:
            native_scale = math.sqrt(min(birth_q, current_q))
            q1_birth_scale = math.sqrt(current_q)
            delta = q1_birth_scale - native_scale
            factor_scale_deltas.append(delta)
            factor_opportunities += 1
            if delta > 1e-12:
                positive_delta_opportunities += 1
                has_positive = True
        if has_positive:
            eligible_tracks_positive += 1

    birth_q = [observations[0][2] for observations in gftt_tracks]
    result: dict[str, object] = {
        "schema_version": "aqua-fe-ntnu-q-partition-lineage-audit-v1",
        "contract_pass": True,
        "base_bag": str(base_bag),
        "base_bag_sha256": sha256(base_bag),
        "feature_frames": feature_frames,
        "track_count": len(tracks),
        "source_observation_counts": {
            str(key): value for key, value in sorted(source_counts.items())
        },
        "gftt_birth_observations": len(gftt_tracks),
        "gftt_birth_is_unique_first_observation": True,
        "gftt_singleton_tracks": sum(len(track) == 1 for track in gftt_tracks),
        "gftt_continued_as_source1_tracks": sum(len(track) > 1 for track in gftt_tracks),
        "gftt_birth_q_min": min(birth_q),
        "gftt_birth_q_median": statistics.median(birth_q),
        "gftt_birth_q_max": max(birth_q),
        "full_bag_tracks_with_at_least_four_observations": eligible_tracks,
        "full_bag_pair_opportunities_in_those_tracks": factor_opportunities,
        "pair_opportunities_with_increased_sqrt_q_if_birth_q_is_one": (
            positive_delta_opportunities
        ),
        "eligible_tracks_with_any_increased_sqrt_q": eligible_tracks_positive,
        "pair_opportunity_caveat": (
            "Static full-bag lineage diagnostic, not a count of repeated Ceres "
            "residual evaluations inside sliding-window optimization."
        ),
    }
    return result, factor_scale_deltas


def validate_audits() -> list[dict[str, object]]:
    rows = []
    for arm_key, path in AUDIT_FILES.items():
        audit = load_json(path)
        if audit.get("contract_pass") is not True:
            raise ValueError(f"quality partition audit did not pass: {path}")
        if int(audit["total_messages"]) != 6300:
            raise ValueError(f"unexpected message count: {path}")
        if int(audit["raw_equal_nonfeature_messages"]) != 6000:
            raise ValueError(f"non-feature copy audit failed: {path}")
        rows.append(
            {
                "arm_key": arm_key,
                "path": str(path),
                "sha256": sha256(path),
                "output_bag_sha256": str(audit["output_sha256"]),
                "selected_observations": int(audit["selected_observations"]),
                "untouched_observations": int(audit["untouched_observations"]),
                "contract_pass": True,
            }
        )
    return rows


def validate_evo(path: Path) -> float:
    payload = load_json(path)
    arms = payload.get("arms")
    if not isinstance(arms, dict) or len(arms) != 15:
        raise ValueError("evo cross-check does not contain 15 arms")
    maximum = 0.0
    for metrics in arms.values():
        maximum = max(
            maximum,
            float(metrics["ape_abs_diff_m"]),
            float(metrics["rpe_abs_diff_m"]),
        )
    if maximum >= 1e-6:
        raise ValueError(f"evo cross-check exceeds tolerance: {maximum}")
    return maximum


def replay_run_dir(arm_key: str, replay: int) -> Path:
    root = ROOT / "logs/ntnu_vins"
    if arm_key == "native_learned":
        return root / (
            "external_hybrid_xfeat_every2_validation_20260805_"
            f"ntnu_fjord1_s83_d30_qpart_nativeq_max350_r{replay}"
        )
    if arm_key == "globalq1_learned":
        return root / (
            "external_hybrid_xfeat_every2_validation_20260804_"
            f"ntnu_fjord1_s83_d30_learned_r{replay}"
        )
    suffix = {
        "baseq1_xfeatnative": "baseq1_xfeatnative",
        "kltq1_only": "kltq1",
        "gfttq1_only": "gfttq1",
    }[arm_key]
    return root / (
        "external_hybrid_xfeat_every2_validation_20260805_"
        f"ntnu_fjord1_s83_d30_qpart_{suffix}_r{replay}"
    )


def parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def build_replay_manifest() -> tuple[list[dict[str, object]], list[Path]]:
    rows: list[dict[str, object]] = []
    input_paths: list[Path] = []
    bag_hash_cache: dict[Path, str] = {}
    locked_config: dict[str, object] | None = None
    config_fields = (
        "imu",
        "num_of_cam",
        "multiple_thread",
        "max_cnt",
        "max_solver_time",
        "max_num_iterations",
        "keyframe_parallax",
        "td",
        "estimate_td",
    )
    for arm_key in [*ARM_ORDER, "globalq1_learned"]:
        for replay in (1, 2, 3):
            run_dir = replay_run_dir(arm_key, replay)
            vio = run_dir / "vins_output/vio.csv"
            config = run_dir / "vins_ntnu_external.yaml"
            metrics = run_dir / "ape.txt"
            replay_manifest = run_dir / "replay_manifest.txt"
            for path in (vio, config, metrics, replay_manifest):
                if not path.is_file():
                    raise FileNotFoundError(path)
                input_paths.append(path)
            storage = cv2.FileStorage(str(config), cv2.FILE_STORAGE_READ)
            if not storage.isOpened():
                raise ValueError(f"cannot parse OpenCV YAML: {config}")
            try:
                relevant = {
                    field: storage.getNode(field).real() for field in config_fields
                }
            finally:
                storage.release()
            if relevant["max_cnt"] != 350 or relevant["multiple_thread"] != 0:
                raise ValueError(f"replay config is not max_cnt=350/single-threaded: {config}")
            if locked_config is None:
                locked_config = relevant
            elif relevant != locked_config:
                raise ValueError(f"replay configuration drift: {config}")
            run_metrics = parse_key_values(metrics)
            if run_metrics.get("init_success") != "1":
                raise ValueError(f"replay did not initialize: {metrics}")
            if run_metrics.get("log_linear_solver_failures") != "0":
                raise ValueError(f"replay has a linear-solver failure: {metrics}")
            manifest = parse_key_values(replay_manifest)
            play_bag = Path(manifest["play_bag"]).resolve()
            if not play_bag.is_file():
                raise FileNotFoundError(play_bag)
            if play_bag not in bag_hash_cache:
                bag_hash_cache[play_bag] = sha256(play_bag)
            rows.append(
                {
                    "arm_key": arm_key,
                    "replay": replay,
                    "run_dir": str(run_dir),
                    "vio_csv": str(vio),
                    "vio_sha256": sha256(vio),
                    "config": str(config),
                    "config_sha256": sha256(config),
                    "play_bag": str(play_bag),
                    "play_bag_sha256": bag_hash_cache[play_bag],
                    "max_cnt": relevant["max_cnt"],
                    "multiple_thread": relevant["multiple_thread"],
                    "init_success": 1,
                    "linear_solver_failures": 0,
                    "failure_mentions": int(run_metrics["log_failure_mentions"]),
                }
            )
    global_hashes = {
        str(row["vio_sha256"])
        for row in rows
        if row["arm_key"] in {"globalq1_learned", "baseq1_xfeatnative"}
    }
    if len(global_hashes) != 1:
        raise ValueError(
            "global-q1 and classical-q1/XFeat-native trajectories are not byte-identical"
        )
    return rows, input_paths


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def figure_factorial(
    path_stem: Path,
    replay_rows: list[dict[str, object]],
    summaries: list[dict[str, object]],
) -> None:
    colors = [
        OKABE_ITO["blue"],
        OKABE_ITO["sky"],
        OKABE_ITO["orange"],
        OKABE_ITO["vermillion"],
    ]
    fig, ax = plt.subplots(figsize=(7.0, 3.8), constrained_layout=True)
    for position, arm_key in enumerate(ARM_ORDER):
        values = [
            float(row["rpe_rmse_m"])
            for row in replay_rows
            if row["arm_key"] == arm_key
        ]
        offsets = (-0.09, 0.0, 0.09)
        ax.scatter(
            [position + offset for offset in offsets],
            values,
            s=42,
            marker="o",
            facecolors=colors[position],
            edgecolors=OKABE_ITO["black"],
            linewidths=0.6,
            zorder=3,
        )
        median = next(
            float(row["rpe_median_m"])
            for row in summaries
            if row["arm_key"] == arm_key
        )
        ax.plot(
            [position - 0.18, position + 0.18],
            [median, median],
            color=OKABE_ITO["black"],
            linewidth=1.6,
            zorder=4,
        )
    ax.set_yscale("log")
    ax.set_ylabel("1 s translation RPE RMSE (m, log scale)")
    ax.set_xticks(range(len(ARM_ORDER)))
    ax.set_xticklabels([ARM_METADATA[key]["short_label"] for key in ARM_ORDER])
    ax.grid(axis="y", which="both", color="#B8B8B8", alpha=0.45, linewidth=0.6)
    ax.tick_params(axis="both", labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    for suffix in ("pdf", "png"):
        kwargs = {"dpi": 600} if suffix == "png" else {}
        fig.savefig(path_stem.with_suffix(f".{suffix}"), **kwargs)
    plt.close(fig)


def figure_lineage(path_stem: Path, lineage: dict[str, object], deltas: list[float]) -> None:
    positive = [value for value in deltas if value > 1e-12]
    zero_count = len(deltas) - len(positive)
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.2), constrained_layout=True)

    labels = ["GFTT births", "Continued", ">=4 obs", "Any upweight"]
    values = [
        int(lineage["gftt_birth_observations"]),
        int(lineage["gftt_continued_as_source1_tracks"]),
        int(lineage["full_bag_tracks_with_at_least_four_observations"]),
        int(lineage["eligible_tracks_with_any_increased_sqrt_q"]),
    ]
    axes[0].bar(
        range(len(values)),
        values,
        color=[OKABE_ITO["sky"], OKABE_ITO["blue"], OKABE_ITO["orange"], OKABE_ITO["vermillion"]],
        edgecolor=OKABE_ITO["black"],
        linewidth=0.5,
    )
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_xticklabels(labels, rotation=25, ha="right")
    axes[0].set_ylabel("Track count")
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[0].grid(axis="y", color="#B8B8B8", alpha=0.4, linewidth=0.6)

    axes[1].hist(
        positive,
        bins=30,
        color=OKABE_ITO["orange"],
        edgecolor=OKABE_ITO["black"],
        linewidth=0.35,
    )
    axes[1].set_xlabel("Increase in residual scale, sqrt(q)")
    axes[1].set_ylabel("Full-bag pair opportunities")
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].grid(axis="y", color="#B8B8B8", alpha=0.4, linewidth=0.6)
    axes[1].text(
        0.98,
        0.96,
        f"positive: {len(positive):,}\nunchanged: {zero_count:,}",
        transform=axes[1].transAxes,
        ha="right",
        va="top",
        fontsize=8,
    )
    for axis in axes:
        axis.tick_params(axis="both", labelsize=8)
    for suffix in ("pdf", "png"):
        kwargs = {"dpi": 600} if suffix == "png" else {}
        fig.savefig(path_stem.with_suffix(f".{suffix}"), **kwargs)
    plt.close(fig)


def fmt(value: object, digits: int = 6) -> str:
    return f"{float(value):.{digits}f}"


def by_key(summaries: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["arm_key"]): row for row in summaries}


def write_reports(
    output: Path,
    summaries: list[dict[str, object]],
    support: dict[str, object],
    lineage: dict[str, object],
    audits: list[dict[str, object]],
    evo_max: float,
    replay_manifest: list[dict[str, object]],
    inputs: dict[str, Path],
) -> None:
    summary = by_key(summaries)
    native = float(summary["native_learned"]["rpe_median_m"])
    ratios = {
        key: 100.0 * (float(summary[key]["rpe_median_m"]) / native - 1.0)
        for key in ARM_ORDER[1:]
    }
    base = summary["baseq1_xfeatnative"]
    global_q = summary["globalq1_learned"]
    exact_duplicate = all(
        float(base[field]) == float(global_q[field])
        for field in (
            "ape_median_m",
            "ape_min_m",
            "ape_max_m",
            "rpe_median_m",
            "rpe_min_m",
            "rpe_max_m",
        )
    )
    if not exact_duplicate:
        raise ValueError("classical-q1/XFeat-native and global-q1 trajectories differ")

    table_lines = [
        "| Classical q partition | APE median [min, max] (m) | 1 s RPE median [min, max] (m) |",
        "|---|---:|---:|",
    ]
    for key in ARM_ORDER:
        row = summary[key]
        table_lines.append(
            f"| {row['label']} | {fmt(row['ape_median_m'])} "
            f"[{fmt(row['ape_min_m'])}, {fmt(row['ape_max_m'])}] | "
            f"{fmt(row['rpe_median_m'])} "
            f"[{fmt(row['rpe_min_m'])}, {fmt(row['rpe_max_m'])}] |"
        )

    report = f"""# NTNU quality-partition analysis

Date: 2026-08-05
Status: `DEVELOPMENT_ONLY_STRICT_ANALYSIS`
Scientific unit: one selected NTNU `fjord1_s83_d30` event
Technical repeats: three serial single-threaded replays per arm

## Analysis question

Does the constant-q divergence arise from the eight XFeat observations, or
from changing the quality contract of the classical carrier while learned
geometry is held fixed?

All four factorial cells use the same learned-active feature geometry. Only
the declared `quality` and `sigma` entries differ. The shared G0 mask contains
{int(support['matched_count'])} poses and {int(support['rpe_pairs'])} one-second
RPE pairs, with {float(support['common_coverage']):.6f} coverage. APE and RPE
are both valid.

## Exact result

{os.linesep.join(table_lines)}

Relative to native classical q, the technical-replay median RPE is
{ratios['kltq1_only']:.1f}% higher when source 1 alone is set to q=1,
{ratios['gfttq1_only']:.1f}% higher when only GFTT birth observations are set
to q=1, and {ratios['baseq1_xfeatnative']:.1f}% higher when both classical
partitions are set to q=1. The GFTT-birth arm also has a visible third-replay
branch at {fmt(summary['gfttq1_only']['rpe_max_m'])} m; its median alone must
not hide that branch.

The classical-q1/XFeat-native arm and the earlier global-q1 arm have exactly
the same APE/RPE values in all three replays. Thus changing the eight XFeat q
values is not needed to reproduce this divergence.

## Mechanism audit

The frozen native bag contains {int(lineage['gftt_birth_observations']):,}
source-2 observations. Every one is the unique first observation of its track;
{int(lineage['gftt_continued_as_source1_tracks']):,} tracks later continue as
source 1 and {int(lineage['gftt_singleton_tracks']):,} are singletons. This
makes the source-2 arm a direct birth-observation intervention rather than a
generic GFTT lifetime rewrite.

VINS accepts tracks with at least four observations and weights each temporal
factor by `sqrt(min(first_q, current_q))`. In the static full-bag lineage
diagnostic, {int(lineage['full_bag_tracks_with_at_least_four_observations']):,}
GFTT-born tracks meet the four-observation threshold. Setting birth q to one
would increase residual scale for
{int(lineage['pair_opportunities_with_increased_sqrt_q_if_birth_q_is_one']):,}
of {int(lineage['full_bag_pair_opportunities_in_those_tracks']):,} lineage-pair
opportunities. This count explains how a one-message birth intervention can
persist, but it is not a count of runtime Ceres evaluations.

## What the counterexample now means

The divergence remains a real negative result under the counterfactual global
constant-q sensitivity contract, which is not the candidate's main contract.
It is not evidence that learned geometry is intrinsically
harmful: the same geometry is stable under native q, source-1-only q=1 is
stable in all three repeats, and the divergence is reproduced without changing
XFeat q. This matrix independently supports a `classical birth/propagation
quality x this VINS consumer` interaction while learned-active geometry is
fixed. Only when combined with the earlier learned-versus-drop crossover may
the broader result be described as a geometry-quality-backend interaction.

This resolves the attribution ambiguity, not the population-level method
question. One development event cannot establish learned superiority,
multi-sequence robustness, or a probability of divergence.

## Claim Candidates

- Claim:
  - Source evidence: fail-closed bag audits, 15-arm G0 evaluation, lineage audit, and VINS source contract.
  - Allowed wording: "On the NTNU development event, global q=1 divergence was reproduced by changing only classical quality; XFeat q was not the cause."
  - Forbidden stronger wording: "The learned method cannot diverge" or "native q guarantees stability."
  - Uncertainty: one selected event, one backend, three non-independent technical repeats.
  - Next check: preserve native-q and the contract guard in the held-out multi-sequence matrix.
  - Decision: keep

- Claim:
  - Source evidence: source-2 lineage identity plus VINS `min(first_q,current_q)` and `sqrt(q)` implementation.
  - Allowed wording: "Birth quality can cap the later influence of surviving classical replenishment tracks."
  - Forbidden stronger wording: "GFTT is generally unsafe" or "birth q is the only stability mechanism."
  - Uncertainty: source-2-only has one severe error branch, while deterministic divergence requires both classical partitions at q=1.
  - Next check: report this as a quality-interface ablation, not a tuned method result.
  - Decision: keep

## Artifact validity

- Three source-partition audits: PASS; all 6,000 non-feature messages are raw-byte equal per bag.
- Replay configuration: all 15 rows use `max_cnt=350` and `multiple_thread=0`.
- Replay health: all 15 rows initialize and have zero linear-solver failures.
- Common support: APE valid and RPE valid.
- Evo cross-check maximum absolute discrepancy: {evo_max:.3e} m (<1e-6 m).
- Scientific n: 1. No p-value, confidence interval, or population effect size is reported.
"""
    (output / "analysis-report.md").write_text(report, encoding="utf-8")

    stats = f"""# Statistical appendix

## Unit and reducer

- Primary metric: G0 common-support 1 s translation RPE RMSE; lower is better.
- Secondary metric: G0 common-support APE RMSE; lower is better.
- Scientific unit: one NTNU development event (`n=1`).
- Technical repeats: three serial single-threaded VINS replays per arm.
- Numeric reducer: median of the three evaluable technical repeats; full min-max range is retained.
- Failure reducer: all 15 replays are evaluable on this contrast. The high-error GFTT-birth replay is not reclassified as a formal hard failure because it initialized, retained valid support, and had no frozen solver-failure signature.

## Descriptive statistics

{os.linesep.join(table_lines)}

The individual replay rows are in `replay-metrics.csv`; medians and ranges are
in `factorial-summary.csv`. These repeats estimate numerical branch behavior
only. Mean +/- SD, replay-level confidence intervals, t-tests, Wilcoxon tests,
and p-values would incorrectly treat technical repeats as independent and are
therefore omitted.

## Comparability checks

- Shared support: {int(support['matched_count'])}/{int(support['grid_count'])} grid poses, {int(support['rpe_pairs'])} RPE pairs, {float(support['common_span_s']):.3f} s span.
- Bag topology: three audits PASS with 6,300 messages, 300 feature frames, and 6,000 raw-byte-equal non-feature messages each.
- Replay identity: every `vio.csv`, VINS YAML, played bag, initialization flag, and solver-failure count is recorded in `replay-input-manifest.csv`.
- Configuration equality: all 15 replay YAMLs agree on the frozen estimator fields, including `max_cnt=350` and `multiple_thread=0`.
- Changed fields: only predeclared source partitions in `quality` and `sigma`.
- Geometry and all other feature channels: equal by fail-closed audit.
- Evo independent implementation check: maximum absolute metric discrepancy {evo_max:.3e} m.

## Inferential blocker

There is one selected development event and no independent sequence-level
replication. No inferential test or population uncertainty interval is valid.
The held-out confirmatory matrix must use sequence as the independent unit.

## Mechanism-count caveat

The lineage counts in `lineage-audit.json` describe full-bag track histories.
They are not counts of residual blocks evaluated repeatedly inside each VINS
sliding-window optimization.
"""
    (output / "stats-appendix.md").write_text(stats, encoding="utf-8")

    catalog = f"""# Figure catalog

## Figure 1: `figures/figure-01-quality-partition-replays.pdf`

- Purpose: test whether classical quality partitions reproduce the q=1 divergence while learned geometry and XFeat q remain fixed.
- Data source: `{inputs['summary']}`.
- Plotted variables: one-second translation RPE RMSE for every technical replay; horizontal bars are technical-replay medians; log y axis is explicit.
- Sample size: one scientific event, three technical repeats per arm.
- Caption requirements: state that dots are non-independent technical repeats and that no uncertainty bar is shown.
- Key observation: source-1-only remains stable, source-2 birth q=1 has a one-of-three severe error branch, and joint classical q=1 diverges in all three repeats.
- Interpretation: with learned-active geometry fixed, the negative result is a classical quality/backend interaction, not a learned-q-only failure.
- Caveat: a log axis is required to retain all branches without clipping; it must not be read as a population effect plot.

## Figure 2: `figures/figure-02-gftt-birth-lineage.pdf`

- Purpose: show why changing one source-2 observation per GFTT-born track can affect later factors.
- Data source: `{inputs['base_bag']}` plus the frozen VINS weighting implementation.
- Plotted variables: track-count funnel and positive changes in `sqrt(q)` for static full-bag lineage-pair opportunities.
- Sample size: {int(lineage['gftt_birth_observations']):,} GFTT-born tracks; {int(lineage['full_bag_pair_opportunities_in_those_tracks']):,} diagnostic pair opportunities among full-bag tracks with at least four observations.
- Caption requirements: call these static lineage diagnostics, not runtime factor counts.
- Key observation: source 2 occurs exactly once at track birth and can cap later higher-q observations through `min(first_q,current_q)`.
- Interpretation: native birth reliability is an active part of this backend contract.
- Caveat: this mechanism localization comes from one development event and one VINS implementation.
"""
    (output / "figure-catalog.md").write_text(catalog, encoding="utf-8")


def write_hash_manifests(
    output: Path, inputs: dict[str, Path], replay_input_paths: list[Path]
) -> None:
    input_lines = [f"{sha256(path)}  {path}" for path in inputs.values()]
    for path in AUDIT_FILES.values():
        input_lines.append(f"{sha256(path)}  {path}")
    input_lines.append(f"{sha256(ESTIMATOR_SOURCE)}  {ESTIMATOR_SOURCE}")
    for path in sorted(set(replay_input_paths)):
        input_lines.append(f"{sha256(path)}  {path}")
    (output / "input-manifest.sha256").write_text(
        "\n".join(input_lines) + "\n", encoding="utf-8"
    )
    artifacts = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name != "analysis-artifact-manifest.sha256"
    )
    lines = [f"{sha256(path)}  {path.relative_to(output)}" for path in artifacts]
    (output / "analysis-artifact-manifest.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def build_bundle(args: argparse.Namespace) -> Path:
    inputs = {
        "summary": args.summary.resolve(),
        "metrics": args.metrics.resolve(),
        "evo": args.evo.resolve(),
        "base_bag": args.base_bag.resolve(),
    }
    for path in [*inputs.values(), ESTIMATOR_SOURCE, *AUDIT_FILES.values()]:
        if not path.is_file():
            raise FileNotFoundError(path)

    replay_rows, support = load_replay_rows(inputs["summary"])
    summaries = summarize_replays(replay_rows)
    audits = validate_audits()
    lineage, deltas = analyze_lineages(inputs["base_bag"])
    evo_max = validate_evo(inputs["evo"])
    replay_manifest, replay_input_paths = build_replay_manifest()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.force:
        raise FileExistsError(output)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent)))
    try:
        (temporary / "figures").mkdir()
        write_csv(temporary / "replay-metrics.csv", replay_rows)
        write_csv(temporary / "factorial-summary.csv", summaries)
        write_csv(temporary / "bag-audit-summary.csv", audits)
        write_csv(temporary / "replay-input-manifest.csv", replay_manifest)
        (temporary / "lineage-audit.json").write_text(
            json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        figure_factorial(
            temporary / "figures/figure-01-quality-partition-replays",
            replay_rows,
            summaries,
        )
        figure_lineage(
            temporary / "figures/figure-02-gftt-birth-lineage", lineage, deltas
        )
        write_reports(
            temporary,
            summaries,
            support,
            lineage,
            audits,
            evo_max,
            replay_manifest,
            inputs,
        )
        write_hash_manifests(temporary, inputs, replay_input_paths)
        if output.exists():
            shutil.rmtree(output)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def main() -> int:
    output = build_bundle(parse_args())
    print(f"NTNU_Q_PARTITION_ANALYSIS_OK output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
