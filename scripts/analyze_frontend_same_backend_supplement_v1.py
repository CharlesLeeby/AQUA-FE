#!/usr/bin/env python3
"""Analyze the preregistered long-window same-backend supplement."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import median
import struct
import subprocess
import sys

import analyze_frontend_same_backend_comparison_v1 as core
import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison_supplemental_v1"

WINDOWS = (
    core.Window("a03_5000_5900", "aqualoc_archaeo", "3", 5000, 5900),
    core.Window("a01_16200_17100", "aqualoc_archaeo", "1", 16200, 17100),
    core.Window("a07_900_1800", "aqualoc_archaeo", "7", 900, 1800),
    core.Window("a07_1800_2700", "aqualoc_archaeo", "7", 1800, 2700),
    core.Window("h07_0_1000", "aqualoc_real", "7", 0, 1000),
    core.Window("h01_0_900", "aqualoc_real", "1", 0, 900),
    core.Window("fjord5_s60_d30", "ntnu", "fjord_5", 60, 30),
    core.Window("fjord6_s45_d45", "ntnu", "fjord_6", 45, 45),
)


def run_dir(window: core.Window, arm: str, repeat: int) -> Path:
    method = core.ARMS[arm][1]
    roots = {
        "aqualoc_archaeo": ROOT / "logs/aqualoc_archaeo_vins",
        "aqualoc_real": ROOT / "logs/aqualoc_real_vins",
        "ntnu": ROOT / "logs/ntnu_vins",
    }
    return roots[window.family] / f"external_{method}_every2_fsbcs1_{window.window_id}_{arm}_r{repeat}"


def config_path(window: core.Window, arm: str, repeat: int) -> Path:
    names = {
        "aqualoc_archaeo": "vins_aqualoc_archaeo_external.yaml",
        "aqualoc_real": "vins_aqualoc_external.yaml",
        "ntnu": "vins_ntnu_external.yaml",
    }
    return run_dir(window, arm, repeat) / names[window.family]


def evaluator_args(window: core.Window, eligible_rows: list[dict[str, object]]) -> list[str]:
    args = [sys.executable, str(core.EVAL_SCRIPT)]
    if window.family in {"aqualoc_archaeo", "aqualoc_real"}:
        reference_bag = run_dir(window, "klt", 1) / "features.bag"
        args += ["--reference-bag", str(reference_bag), "--reference-topic", "/aqualoc/colmap_gt"]
        if window.family == "aqualoc_archaeo":
            args += [
                "--nominal-reference-rate-hz", "1", "--evaluation-rate-hz", "1",
                "--max-reference-gap-s", "2.5", "--nominal-estimate-rate-hz", "10",
                "--max-estimate-gap-s", "0.25",
            ]
        else:
            args += [
                "--nominal-reference-rate-hz", "4", "--evaluation-rate-hz", "2",
                "--max-reference-gap-s", "0.625", "--nominal-estimate-rate-hz", "10",
                "--max-estimate-gap-s", "0.25",
            ]
    else:
        subset = "subset-fjord" if window.sequence.startswith("fjord_") else "subset-mclab"
        reference = ROOT / f"datasets/full_downloads/ntnu_hf/{subset}/{window.sequence}/{window.sequence}_baseline.tum"
        # The registered NTNU offset is relative to the raw bag start, not to
        # the first baseline pose.  Use the timestamps of the actual selected
        # image sequence so the evaluation grid is byte-for-byte tied to the
        # exported input instead of silently shifting it by the bag/GT lead-in.
        metrics_path = run_dir(window, "klt", 1) / "frontend_metrics.csv"
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            timestamps = [float(row["timestamp"]) for row in csv.DictReader(handle)]
        if len(timestamps) < 2:
            raise RuntimeError(f"missing NTNU selected-frame timestamps: {metrics_path}")
        start = min(timestamps)
        end = max(timestamps)
        args += [
            "--reference-tum", str(reference), "--nominal-reference-rate-hz", "50",
            "--evaluation-rate-hz", "10", "--max-reference-gap-s", "0.05",
            "--nominal-estimate-rate-hz", "6.6666667", "--max-estimate-gap-s", "0.375",
            "--window-start-s", format(start, ".17g"), "--window-end-s", format(end, ".17g"),
        ]
    for row in eligible_rows:
        name = f"{row['arm']}_r{row['repeat']}"
        args += ["--arm", f"{name}={row['vio_csv']}"]
        args += ["--arm-config", f"{name}={config_path(window, str(row['arm']), int(row['repeat']))}"]
    args += [
        "--rpe-delta-s", "1.0", "--min-ape-poses", "30", "--min-ape-span-s", "10",
        "--min-common-coverage", "0.70", "--min-rpe-pairs", "10",
        "--contrast-name", f"fsbcs1_{window.window_id}_all9",
        "--output-dir", str(OUT / "common_support" / window.window_id), "--run-evo",
    ]
    return args


def audit_effective_frontend_inputs(
    grouped: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Audit the exact feature-message stream consumed by VINS."""

    rows = core.audit_effective_frontend_inputs(grouped)
    grouped_lookup = {
        (str(row["window"]), str(row["arm"])): row
        for row in grouped
    }

    def topic_digest(path: Path, topic: str) -> tuple[str, int]:
        digest = hashlib.sha256()
        count = 0
        with rosbag.Bag(str(path)) as bag:
            for _, message, stamp in bag.read_messages(topics=[topic]):
                buffer = io.BytesIO()
                message.serialize(buffer)
                payload = buffer.getvalue()
                digest.update(struct.pack("<qI", stamp.to_nsec(), len(payload)))
                digest.update(payload)
                count += 1
        return digest.hexdigest(), count

    for row in rows:
        window_id = str(row["window"])
        window = next(item for item in WINDOWS if item.window_id == window_id)
        imu_topic = (
            "/alphasense_driver_ros/imu"
            if window.family == "ntnu"
            else "/rtimulib_node/imu"
        )
        feature_hashes: dict[str, str] = {}
        imu_hashes: dict[str, str] = {}
        for arm in core.ARMS:
            bag_path = Path(str(grouped_lookup[(window_id, arm)]["feature_bag"]))
            feature_hash, feature_count = topic_digest(bag_path, "/feature_tracker/feature")
            imu_hash, imu_count = topic_digest(bag_path, imu_topic)
            feature_hashes[arm] = feature_hash
            imu_hashes[arm] = imu_hash
            row[f"{arm}_feature_topic_sha256"] = feature_hash
            row[f"{arm}_feature_topic_messages"] = feature_count
            row[f"{arm}_imu_topic_sha256"] = imu_hash
            row[f"{arm}_imu_topic_messages"] = imu_count
        row["imu_semantic_equal_all_arms"] = int(len(set(imu_hashes.values())) == 1)
        hashes = feature_hashes
        distinct = len(set(hashes.values()))
        row["distinct_feature_topic_count"] = distinct
        if distinct == 1:
            row["equality_relation"] = "KLT=SP+LG=XFeat-seed"
            row["attribution_status"] = "NO_FRONTEND_ATTRIBUTION_IDENTICAL_BACKEND_INPUT"
        elif hashes["klt"] == hashes["splg"]:
            row["equality_relation"] = "KLT=SP+LG;XFeat-seed_distinct"
            row["attribution_status"] = "KLT_VS_SPLG_NOT_ATTRIBUTABLE"
        elif hashes["klt"] == hashes["xfeat_seed"]:
            row["equality_relation"] = "KLT=XFeat-seed;SP+LG_distinct"
            row["attribution_status"] = "XFEAT_VS_KLT_NOT_ATTRIBUTABLE"
        elif hashes["splg"] == hashes["xfeat_seed"]:
            row["equality_relation"] = "SP+LG=XFeat-seed;KLT_distinct"
            row["attribution_status"] = "XFEAT_VS_SPLG_NOT_ATTRIBUTABLE"
        else:
            row["equality_relation"] = "all_distinct"
            row["attribution_status"] = "EFFECTIVE_INPUTS_DISTINCT"
        row["attribution_basis"] = "FEATURE_TOPIC_SEMANTIC_SHA256"
        row["xfeat_vs_klt_attributable"] = int(
            hashes["xfeat_seed"] != hashes["klt"]
        )
        row["xfeat_vs_splg_attributable"] = int(
            hashes["xfeat_seed"] != hashes["splg"]
        )
        row["splg_vs_klt_attributable"] = int(
            hashes["splg"] != hashes["klt"]
        )
    core.write_csv(OUT / "effective_frontend_input_audit.csv", rows)
    return rows


def collect_frontend_activation(grouped: list[dict[str, object]]) -> None:
    """Summarize whether a nominal learned arm changed backend input."""

    bag_hash = {
        (str(row["window"]), str(row["arm"])): str(row["feature_bag_sha256"])
        for row in grouped
    }
    output: list[dict[str, object]] = []
    numeric_fields = (
        "learned_candidate_count",
        "learned_confirmed_count",
        "exported_learned_features",
        "exported_sp_lg_features",
        "exported_xfeat_features",
    )
    for window in WINDOWS:
        for arm in core.ARMS:
            path = run_dir(window, arm, 1) / "frontend_metrics.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                metrics = list(csv.DictReader(handle))
            totals = {
                field: int(sum(float(row.get(field, "0") or 0) for row in metrics))
                for field in numeric_fields
            }
            active_frames = sum(
                float(row.get("exported_learned_features", "0") or 0) > 0
                for row in metrics
            )
            output.append({
                "window": window.window_id,
                "arm": arm,
                "selected_frames": len(metrics),
                **{f"{field}_total": value for field, value in totals.items()},
                "frames_with_exported_learned_features": active_frames,
                "feature_bag_sha256": bag_hash[(window.window_id, arm)],
            })
    core.write_csv(OUT / "frontend_activation.csv", output)


def audit_backend_feature_budget(grouped: list[dict[str, object]]) -> None:
    """Check the actual PointCloud count received by the VINS backend."""

    output: list[dict[str, object]] = []
    for row in grouped:
        counts: list[int] = []
        with rosbag.Bag(str(row["feature_bag"])) as bag:
            for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
                counts.append(len(message.points))
        if not counts:
            raise RuntimeError(f"no backend feature messages: {row['feature_bag']}")
        over = [count for count in counts if count > 350]
        output.append({
            "window": row["window"],
            "arm": row["arm"],
            "configured_feature_budget": 350,
            "feature_messages": len(counts),
            "points_min": min(counts),
            "points_median": median(counts),
            "points_max": max(counts),
            "messages_over_budget": len(over),
            "max_budget_excess": max(over) - 350 if over else 0,
            "budget_contract_status": "PASS" if not over else "FAIL",
        })
    core.write_csv(OUT / "backend_feature_budget_audit.csv", output)


def artifact_manifest() -> None:
    names = (
        "windows.csv", "arms.csv", "contract.json", "preregistration.md", "preregistration.sha256",
        "runtime_weight_lock.json", "runability_repeats.csv", "runability.csv",
        "backend_config_audit.csv", "effective_frontend_input_audit.csv",
        "frontend_activation.csv", "pairwise_attribution_windows.csv",
        "pairwise_attributable_effects.csv",
        "backend_feature_budget_audit.csv",
        "common_support_status.csv", "accuracy_repeats.csv", "accuracy.csv",
        "report.md", "analysis-report.md", "stats-appendix.md", "figure-catalog.md",
        "trajectory_scale_audit.csv",
    )
    paths = [OUT / name for name in names]
    for directory in (OUT / "common_support", OUT / "analysis-output"):
        if directory.is_dir():
            paths.extend(path for path in sorted(directory.rglob("*")) if path.is_file())
    paths.extend([
        ROOT / "scripts/run_frontend_same_backend_supplement_v1.py",
        ROOT / "scripts/analyze_frontend_same_backend_supplement_v1.py",
        ROOT / "scripts/report_frontend_same_backend_supplement_v1.py",
        ROOT / "scripts/analyze_frontend_same_backend_comparison_v1.py",
        ROOT / "scripts/report_frontend_same_backend_comparison_v1.py",
        ROOT / "scripts/evaluate_vins_common_support.py",
        ROOT / "scripts/trajectory_eval_core.py",
        ROOT / "uw_frontend/ros/export_vins_features.py",
        ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
        Path("/home/ma/.cache/torch/hub/checkpoints/superpoint_v1.pth"),
        Path("/home/ma/.cache/torch/hub/checkpoints/superpoint_lightglue_v0-1_arxiv.pth"),
        ROOT / "external_tools/accelerated_features/weights/xfeat.pt",
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
    ])
    for window in WINDOWS:
        for arm in core.ARMS:
            paths.append(run_dir(window, arm, 1) / "features.bag")
            for repeat in range(1, 4):
                run = run_dir(window, arm, repeat)
                paths.extend([
                    run / "fsbc_cell_complete.json", run / "vins_output/vio.csv",
                    run / "vins.log", run / "frontend_metrics.csv", run / "fsbc_console.log",
                    config_path(window, arm, repeat),
                ])
    lines = []
    seen: set[Path] = set()
    for path in paths:
        if path.is_file():
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            lines.append(f"{core.sha256(path)}  {resolved}\n")
    (OUT / "artifacts.sha256").write_text("".join(lines), encoding="utf-8")


def configure_core() -> None:
    core.OUT = OUT
    core.WINDOWS = WINDOWS
    core.run_dir = run_dir
    core.config_path = config_path
    core.evaluator_args = evaluator_args
    core.artifact_manifest = artifact_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("collect", "evaluate", "all"), default="all", nargs="?")
    args = parser.parse_args()
    configure_core()
    raw, grouped = core.collect_runability()
    audit_effective_frontend_inputs(grouped)
    collect_frontend_activation(grouped)
    audit_backend_feature_budget(grouped)
    audit = core.audit_backend_configs()
    if args.stage in {"evaluate", "all"}:
        core.evaluate_common_support(raw, grouped, audit)
    core.collect_accuracy()
    artifact_manifest()
    print(f"runability={OUT / 'runability.csv'}")
    print(f"accuracy={OUT / 'accuracy.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
