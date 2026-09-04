#!/usr/bin/env python3
"""Build the strict NTNU ORB-SLAM3 v23 cross-dataset analysis bundle."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
RUN_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/"
    "v23_crossdataset_20260730"
)
LOW_ROOT = RUN_ROOT / "ntnu_fjord4_s30_d10"
LOW_RUNS = LOW_ROOT / (
    "formal_finalonline_v23_lineagefirst_lateenforce_dualgateack_"
    "equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)
NORMAL_ROOT = RUN_ROOT / "ntnu_fjord4_s50_d20"
NORMAL_RUNS = NORMAL_ROOT / (
    "formal_noharm_v23_lateenforce_dualgateack_equalruntime_"
    "singlecpu2_noaslr_threearm_h100_q09"
)
DIAG_RUNS = LOW_ROOT / "diagnostic_n6_d20/full_v23_fivearm_h100_q09"
LOW_FRONTEND_STATS = Path(
    "/mnt/data/AQUA-FE_WS/online_positive_search_20260721/"
    "ntnu_fjord4_s30_d10/stats.csv"
)
NORMAL_FRONTEND_STATS = Path(
    "/mnt/data/AQUA-FE_WS/online_positive_search_20260721/"
    "ntnu_fjord4_s50_d20/stats.csv"
)
CAMERA_CONFIG = Path(
    "/mnt/data/AQUA-FE_WS/logs/orbslam3_validation/ntnu_fjord_cam0_mono.yaml"
)
OUTPUT = WORKSPACE / "papers/orb_v23_crossdataset_ntnu_20260730/analysis-output"
FIGURES = OUTPUT / "figures"

ROLE_ORDER = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
DISPLAY_ROLE = {
    "orb_only": "Native ORB",
    "drop": "Exact drop",
    "full_bridge_off": "Seeds, bridge off",
    "full_unbounded": "Unbounded lineage",
    "full": "v23 candidate",
}
ROLE_COLOR = {
    "orb_only": "#000000",
    "drop": "#7F7F7F",
    "full_bridge_off": "#56B4E9",
    "full_unbounded": "#E69F00",
    "full": "#0072B2",
}
PDF_METADATA = {
    "Creator": "AQUA-FE strict analysis builder",
    "CreationDate": datetime(2026, 7, 30, tzinfo=timezone.utc),
    "ModDate": datetime(2026, 7, 30, tzinfo=timezone.utc),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path)}


def parse_manifest(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def validate_evaluation(
    rows: list[dict[str, str]],
    roles: tuple[str, ...],
    repeats: range,
    trajectory_kind: str,
    label: str,
) -> None:
    expected = {(role, repeat) for role in roles for repeat in repeats}
    actual = [(row["role"], int(row["repeat"])) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError(
            f"{label}: expected role/repeat grid {sorted(expected)}, got {sorted(actual)}"
        )
    if len(set(actual)) != len(actual):
        raise RuntimeError(f"{label}: duplicate role/repeat rows")
    for row in rows:
        key = f"{label}:{row['role']}:r{row['repeat']}"
        if row["trajectory_kind"] != trajectory_kind:
            raise RuntimeError(f"{key}: wrong trajectory_kind")
        if row["status"] != "ok" or row["complete"] != "1":
            raise RuntimeError(f"{key}: incomplete or failed evaluation")
        if row["instrumentation_overflowed"] != "0":
            raise RuntimeError(f"{key}: instrumentation overflow")
        if row["instrumentation_conservation_ok"] != "1":
            raise RuntimeError(f"{key}: instrumentation conservation failed")
        for metric in ("ape_rmse_m", "rpe_rmse_m", "coverage_ratio"):
            value = float(row[metric])
            if not math.isfinite(value) or value < 0:
                raise RuntimeError(f"{key}: invalid {metric}={row[metric]}")
        if not 0 <= float(row["coverage_ratio"]) <= 1:
            raise RuntimeError(f"{key}: coverage outside [0, 1]")
        if int(row["output_poses"]) <= 0:
            raise RuntimeError(f"{key}: no output poses")


def validate_evaluation_pair(
    reconstructed: list[dict[str, str]],
    online: list[dict[str, str]],
    label: str,
) -> None:
    rec = metric_lookup(reconstructed)
    on = metric_lookup(online)
    if set(rec) != set(on):
        raise RuntimeError(f"{label}: reconstructed/online row grids differ")
    shared_fields = (
        "input_frames",
        "map_resets",
        "relocalizations",
        "attempted_seeds",
        "accepted_seeds",
        "seed_lineages_with_mappoint",
        "seed_lineages_surviving",
        "complete",
        "instrumentation_overflowed",
        "instrumentation_conservation_ok",
        "output_poses",
        "coverage_ratio",
        "status",
        "run_dir",
    )
    for key in rec:
        mismatches = [field for field in shared_fields if rec[key][field] != on[key][field]]
        if mismatches:
            raise RuntimeError(
                f"{label}:{key}: reconstructed/online metadata differ: {mismatches}"
            )


def collect_run_records(
    run_root: Path, roles: tuple[str, ...], repeats: range
) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for role in roles:
        for repeat in repeats:
            run_dir = run_root / f"{role}_r{repeat}"
            manifest_path = run_dir / "run_manifest.txt"
            snapshot_path = run_dir / "provenance/snapshot_sha256.txt"
            summary_path = run_dir / "instrumentation/seed_summary.json"
            manifest = parse_manifest(manifest_path)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            key = f"{role}_r{repeat}"
            if manifest.get("role") != role or manifest.get("repeat") != str(repeat):
                raise RuntimeError(f"{key}: manifest identity mismatch")
            if manifest.get("provenance_manifest_sha256") != sha256(snapshot_path):
                raise RuntimeError(f"{key}: frozen snapshot hash mismatch")
            if not summary["complete"] or summary.get("status") != "ok":
                raise RuntimeError(f"{key}: incomplete seed audit summary")
            if summary["events_overflowed"] or summary["related_mappoint_overflowed"]:
                raise RuntimeError(f"{key}: seed audit overflow")
            records[key] = {
                "manifest": artifact_record(manifest_path),
                "frozen_snapshot": artifact_record(snapshot_path),
                "seed_summary": artifact_record(summary_path),
                "frozen_contract": {
                    field: manifest.get(field, "")
                    for field in (
                        "role_order",
                        "binary_sha256",
                        "liborbslam3_sha256",
                        "runner_sha256",
                        "config_sha256",
                        "times_sha256",
                        "seed_sha256",
                        "external_lineage_pre_kf_outlier_purge_enforce",
                    )
                },
            }
    return records


def validate_frozen_lineage(
    record_groups: tuple[dict[str, dict[str, object]], ...],
    source_hashes: dict[str, str],
) -> None:
    all_records = [record for group in record_groups for record in group.values()]
    for manifest_field, source_field in (
        ("binary_sha256", "binary"),
        ("liborbslam3_sha256", "library"),
        ("runner_sha256", "runner"),
    ):
        frozen = {
            str(record["frozen_contract"][manifest_field]) for record in all_records
        }
        if frozen != {source_hashes[source_field]}:
            raise RuntimeError(
                f"frozen {manifest_field} does not match the analyzed live artifact: {frozen}"
            )
    for record in all_records:
        snapshot_path = Path(str(record["frozen_snapshot"]["path"]))
        tracking_hashes = {
            line.split()[0]
            for line in snapshot_path.read_text(encoding="utf-8").splitlines()
            if line.endswith("./sources/src/Tracking.cc")
        }
        if tracking_hashes != {source_hashes["tracking_source"]}:
            raise RuntimeError(f"{snapshot_path}: Tracking.cc lineage mismatch")


def diagnostic_event_boundary(run_root: Path) -> dict[str, int]:
    unbounded_path = run_root / "full_unbounded_r1/instrumentation/seed_events.csv"
    candidate_path = run_root / "full_r1/instrumentation/seed_events.csv"
    unbounded = read_csv(unbounded_path)
    candidate = read_csv(candidate_path)
    first_difference = next(
        (
            min(int(left["event_index"]), int(right["event_index"]))
            for left, right in zip(unbounded, candidate)
            if left != right
        ),
        -1,
    )
    candidate_outliers = [
        int(row["event_index"])
        for row in candidate
        if row["event"] == "frame_raw_association"
        and row["subtype"] == "2"
        and row["is_inlier"] == "0"
    ]
    if first_difference < 0 or not candidate_outliers:
        raise RuntimeError("diagnostic event boundary is not observable")
    if first_difference >= min(candidate_outliers):
        raise RuntimeError("diagnostic streams did not diverge before the first outlier")
    return {
        "first_differing_event_index": first_difference,
        "first_candidate_assisted_outlier_event_index": min(candidate_outliers),
        "candidate_assisted_outlier_events": len(candidate_outliers),
    }


def metric_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["role"], int(row["repeat"])): row for row in rows}


def pct(candidate: float, control: float) -> float:
    return 100.0 * (control - candidate) / control


def trajectory_path(run_root: Path, role: str, repeat: int, online: bool) -> Path:
    prefix = "online_f_" if online else "f_"
    candidates = [
        path
        for path in (run_root / f"{role}_r{repeat}").glob(f"{prefix}*.txt")
        if not path.name.endswith("_sec.txt")
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one {prefix} trajectory for {role} r{repeat}, got {candidates}"
        )
    return candidates[0]


def hash_matrix(run_root: Path, roles: tuple[str, ...], repeats: range) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for role in roles:
        result[role] = {}
        for kind, online in (("reconstructed", False), ("online", True)):
            result[role][kind] = [
                sha256(trajectory_path(run_root, role, repeat, online))
                for repeat in repeats
            ]
    return result


def v23_counters(run_root: Path, roles: tuple[str, ...], repeats: range) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for role in roles:
        for repeat in repeats:
            path = run_root / f"{role}_r{repeat}/instrumentation/seed_summary.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            output.append(
                {
                    "role": role,
                    "repeat": repeat,
                    "complete": data["complete"],
                    "assisted_matches": data["lineage_assisted_matches_consumed"],
                    "assisted_outliers": data["lineage_assisted_outliers_observed"],
                    "pre_kf_scans": data["lineage_pre_kf_outlier_purge_scans"],
                    "pre_kf_outliers": data[
                        "lineage_pre_kf_assisted_outliers_observed"
                    ],
                    "pre_kf_purged": data[
                        "lineage_pre_kf_assisted_outliers_purged"
                    ],
                    "events_overflowed": data["events_overflowed"],
                    "related_mappoint_overflowed": data[
                        "related_mappoint_overflowed"
                    ],
                    "seed_summary_path": str(path),
                    "seed_summary_sha256": sha256(path),
                }
            )
    return output


def write_summary_csv(
    low_reconstructed: list[dict[str, str]],
    low_online: list[dict[str, str]],
    normal_reconstructed: list[dict[str, str]],
    normal_online: list[dict[str, str]],
) -> None:
    fields = [
        "window",
        "trajectory_kind",
        "role",
        "repeat",
        "status",
        "complete",
        "output_poses",
        "coverage_ratio",
        "ape_rmse_m",
        "rpe_rmse_m",
        "attempted_seeds",
        "accepted_seeds",
        "seed_lineages_with_mappoint",
        "seed_lineages_surviving",
        "map_resets",
        "relocalizations",
        "instrumentation_overflowed",
        "instrumentation_conservation_ok",
        "lineage_assisted_matches_consumed",
        "lineage_assisted_outliers_observed",
        "lineage_pre_kf_outlier_purge_scans",
        "lineage_pre_kf_assisted_outliers_observed",
        "lineage_pre_kf_assisted_outliers_purged",
    ]
    groups = (
        ("low_texture_s30_d10", "reconstructed", low_reconstructed),
        ("low_texture_s30_d10", "online", low_online),
        ("normal_texture_s50_d20", "reconstructed", normal_reconstructed),
        ("normal_texture_s50_d20", "online", normal_online),
    )
    with (OUTPUT / "case_summary.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for window, kind, rows in groups:
            for row in rows:
                summary_path = (
                    Path(row["run_dir"]) / "instrumentation/seed_summary.json"
                )
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                action_fields = {
                    field: summary[field]
                    for field in fields
                    if field.startswith("lineage_")
                }
                writer.writerow(
                    {
                        "window": window,
                        "trajectory_kind": kind,
                        **{
                            field: row[field]
                            for field in fields[2:]
                            if not field.startswith("lineage_")
                        },
                        **action_fields,
                    }
                )


def figure_low_texture(
    reconstructed: list[dict[str, str]], online: list[dict[str, str]]
) -> None:
    data = {
        "Reconstructed APE": reconstructed,
        "Reconstructed RPE": reconstructed,
        "Online APE": online,
        "Online RPE": online,
    }
    metric = {
        "Reconstructed APE": "ape_rmse_m",
        "Reconstructed RPE": "rpe_rmse_m",
        "Online APE": "ape_rmse_m",
        "Online RPE": "rpe_rmse_m",
    }
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.1), constrained_layout=True)
    rng = np.random.default_rng(230730)
    for axis, title in zip(axes.flat, data):
        rows = data[title]
        lookup = metric_lookup(rows)
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            repeat = int(row["repeat"])
            native = float(lookup[("orb_only", repeat)][metric[title]])
            value = float(row[metric[title]])
            grouped[row["role"]].append(100.0 * (value / native - 1.0))
        positions = np.arange(len(ROLE_ORDER))
        values = [grouped[role] for role in ROLE_ORDER]
        box = axis.boxplot(
            values,
            positions=positions,
            widths=0.58,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "black", "linewidth": 1.2},
            whiskerprops={"linewidth": 1.0},
            capprops={"linewidth": 1.0},
        )
        for patch, role in zip(box["boxes"], ROLE_ORDER):
            patch.set_facecolor(ROLE_COLOR[role])
            patch.set_alpha(0.55)
        for index, role in enumerate(ROLE_ORDER):
            jitter = rng.normal(0.0, 0.035, size=len(grouped[role]))
            axis.scatter(
                np.full(len(grouped[role]), index) + jitter,
                grouped[role],
                color=ROLE_COLOR[role],
                edgecolor="white",
                linewidth=0.5,
                s=24,
                zorder=3,
            )
        axis.axhline(0.0, color="#666666", linestyle=":", linewidth=1.1)
        axis.axhline(5.0, color="#D55E00", linestyle="--", linewidth=1.1)
        axis.set_title(title, fontsize=10)
        axis.set_ylabel("Change vs matched native (%)")
        axis.set_xticks(positions)
        axis.set_xticklabels(
            ["Native", "Drop", "Bridge off", "Unbounded", "v23"],
            rotation=25,
            ha="right",
            fontsize=8,
        )
        axis.grid(axis="y", alpha=0.25)
        axis.tick_params(axis="y", labelsize=8)
        axis.text(
            0.98,
            5.0,
            "+5% harm limit",
            color="#D55E00",
            fontsize=7,
            ha="right",
            va="bottom",
            transform=axis.get_yaxis_transform(),
        )
    fig.suptitle("Lower is better; positive values indicate harm", fontsize=10)
    fig.savefig(
        FIGURES / "figure-01-low-texture-four-metric.pdf", metadata=PDF_METADATA
    )
    fig.savefig(FIGURES / "figure-01-low-texture-four-metric.png", dpi=300)
    plt.close(fig)


def figure_noharm(
    normal_reconstructed: list[dict[str, str]],
    normal_online: list[dict[str, str]],
) -> None:
    hashes = hash_matrix(NORMAL_RUNS, ("orb_only", "drop", "full"), range(1, 5))
    parity = np.zeros((2, 12), dtype=int)
    row_labels = ["Reconstructed", "Online"]
    column_labels: list[str] = []
    for repeat in range(1, 5):
        for role in ("orb_only", "drop", "full"):
            column_labels.append(f"r{repeat} {DISPLAY_ROLE[role]}")
    for row_index, kind in enumerate(("reconstructed", "online")):
        for repeat in range(1, 5):
            reference = hashes["orb_only"][kind][repeat - 1]
            for role_index, role in enumerate(("orb_only", "drop", "full")):
                column = (repeat - 1) * 3 + role_index
                parity[row_index, column] = int(
                    hashes[role][kind][repeat - 1] == reference
                )

    fig, axes = plt.subplots(
        2, 1, figsize=(7.0, 4.8), gridspec_kw={"height_ratios": [0.8, 1.7]},
        constrained_layout=True,
    )
    axes[0].imshow(parity, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for row in range(parity.shape[0]):
        for column in range(parity.shape[1]):
            axes[0].text(
                column,
                row,
                "=" if parity[row, column] else "x",
                ha="center",
                va="center",
                color="white" if parity[row, column] else "black",
                fontsize=8,
            )
    axes[0].set_yticks(np.arange(len(row_labels)))
    axes[0].set_yticklabels(row_labels, fontsize=7)
    axes[0].set_xticks(np.arange(len(column_labels)))
    axes[0].set_xticklabels(column_labels, rotation=40, ha="right", fontsize=7)
    axes[0].set_title(
        "Same-repeat byte parity vs native ORB; cross-repeat parity also verified",
        fontsize=10,
    )

    roles = ("orb_only", "drop", "full")
    positions = np.arange(len(roles))
    rec = metric_lookup(normal_reconstructed)
    online = metric_lookup(normal_online)
    series = (
        ("Reconstructed APE", rec, "ape_rmse_m", "#000000"),
        ("Reconstructed RPE", rec, "rpe_rmse_m", "#7F7F7F"),
        ("Online APE", online, "ape_rmse_m", "#0072B2"),
        ("Online RPE", online, "rpe_rmse_m", "#E69F00"),
    )
    width = 0.19
    for index, (label, lookup, key, color) in enumerate(series):
        offset = (index - 1.5) * width
        axes[1].bar(
            positions + offset,
            [float(lookup[(role, 1)][key]) for role in roles],
            width,
            color=color,
            alpha=0.85,
            label=label,
        )
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(["Native ORB", "Exact drop", "v23 candidate"], fontsize=8)
    axes[1].set_ylabel("RMSE (m)")
    axes[1].set_title(
        "Normal-texture reconstructed and online metrics (r1 shown; all repeats exact)",
        fontsize=10,
    )
    axes[1].legend(
        frameon=False,
        fontsize=7,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
    )
    axes[1].grid(axis="y", alpha=0.25)
    fig.savefig(
        FIGURES / "figure-02-normal-texture-exact-noharm.pdf", metadata=PDF_METADATA
    )
    fig.savefig(FIGURES / "figure-02-normal-texture-exact-noharm.png", dpi=300)
    plt.close(fig)


def main() -> None:
    low_reconstructed = read_csv(LOW_RUNS / "evaluation_reconstructed.csv")
    low_online = read_csv(LOW_RUNS / "evaluation_online.csv")
    normal_reconstructed = read_csv(NORMAL_RUNS / "evaluation_reconstructed.csv")
    normal_online = read_csv(NORMAL_RUNS / "evaluation_online.csv")
    diag_reconstructed = read_csv(DIAG_RUNS / "evaluation_reconstructed.csv")
    diag_online = read_csv(DIAG_RUNS / "evaluation_online.csv")
    low_frontend = read_csv(LOW_FRONTEND_STATS)
    normal_frontend = read_csv(NORMAL_FRONTEND_STATS)
    low_seed_stats_path = LOW_ROOT / "assets/seed_export_stats.json"
    normal_seed_stats_path = NORMAL_ROOT / "assets/seed_export_stats.json"
    low_seed_stats = json.loads(low_seed_stats_path.read_text(encoding="utf-8"))
    normal_seed_stats = json.loads(
        normal_seed_stats_path.read_text(encoding="utf-8")
    )

    validate_evaluation(
        low_reconstructed, ROLE_ORDER, range(1, 5), "reconstructed", "low"
    )
    validate_evaluation(low_online, ROLE_ORDER, range(1, 5), "online", "low")
    validate_evaluation_pair(low_reconstructed, low_online, "low")
    normal_roles = ("orb_only", "drop", "full")
    validate_evaluation(
        normal_reconstructed,
        normal_roles,
        range(1, 5),
        "reconstructed",
        "normal",
    )
    validate_evaluation(
        normal_online, normal_roles, range(1, 5), "online", "normal"
    )
    validate_evaluation_pair(normal_reconstructed, normal_online, "normal")
    validate_evaluation(
        diag_reconstructed,
        ROLE_ORDER,
        range(1, 2),
        "reconstructed",
        "diagnostic",
    )
    validate_evaluation(
        diag_online, ROLE_ORDER, range(1, 2), "online", "diagnostic"
    )
    validate_evaluation_pair(diag_reconstructed, diag_online, "diagnostic")

    low_rec = metric_lookup(low_reconstructed)
    low_on = metric_lookup(low_online)
    normal_rec = metric_lookup(normal_reconstructed)
    normal_on = metric_lookup(normal_online)
    diag_rec = metric_lookup(diag_reconstructed)
    diag_on = metric_lookup(diag_online)
    low_hashes = hash_matrix(LOW_RUNS, ROLE_ORDER, range(1, 5))
    normal_hashes = hash_matrix(NORMAL_RUNS, normal_roles, range(1, 5))
    low_counters = v23_counters(
        LOW_RUNS, ("full_unbounded", "full"), range(1, 5)
    )
    normal_counters = v23_counters(NORMAL_RUNS, ("full",), range(1, 5))

    normal_healthy_frames = sum(
        row["trigger_reason"] == "healthy" for row in normal_frontend
    )
    normal_grid_coverage_median = float(
        np.median([float(row["base_grid_coverage"]) for row in normal_frontend])
    )
    normal_selector_injections = sum(
        int(float(row["selector_injected_observations"] or 0))
        for row in normal_frontend
    )
    if (low_seed_stats["seed_ids"], low_seed_stats["seed_observations"]) != (1, 8):
        raise RuntimeError("low-texture seed asset is not the frozen 1-lineage/8-observation asset")
    if normal_seed_stats["seed_observations"] != 0 or normal_selector_injections != 0:
        raise RuntimeError("normal-texture asset is not a zero-injection no-harm case")

    low_full_ape_rec = np.array(
        [float(low_rec[("full", repeat)]["ape_rmse_m"]) for repeat in range(1, 5)]
    )
    low_native_ape_rec = np.array(
        [float(low_rec[("orb_only", repeat)]["ape_rmse_m"]) for repeat in range(1, 5)]
    )
    low_full_rpe_rec = np.array(
        [float(low_rec[("full", repeat)]["rpe_rmse_m"]) for repeat in range(1, 5)]
    )
    low_native_rpe_rec = np.array(
        [float(low_rec[("orb_only", repeat)]["rpe_rmse_m"]) for repeat in range(1, 5)]
    )
    low_full_ape_on = np.array(
        [float(low_on[("full", repeat)]["ape_rmse_m"]) for repeat in range(1, 5)]
    )
    low_native_ape_on = np.array(
        [float(low_on[("orb_only", repeat)]["ape_rmse_m"]) for repeat in range(1, 5)]
    )
    low_full_rpe_on = np.array(
        [float(low_on[("full", repeat)]["rpe_rmse_m"]) for repeat in range(1, 5)]
    )
    low_native_rpe_on = np.array(
        [float(low_on[("orb_only", repeat)]["rpe_rmse_m"]) for repeat in range(1, 5)]
    )

    # Every role and repeat shares one digest per trajectory kind.
    normal_exact = all(
        len(
            {
                normal_hashes[role][kind][repeat - 1]
                for role in ("orb_only", "drop", "full")
            }
        )
        == 1
        for kind in ("reconstructed", "online")
        for repeat in range(1, 5)
    ) and all(
        len(
            {
                normal_hashes[role][kind][repeat - 1]
                for role in ("orb_only", "drop", "full")
                for repeat in range(1, 5)
            }
        )
        == 1
        for kind in ("reconstructed", "online")
    )
    low_candidate_noharm = [
        all(
            float(candidate[key]) <= 1.05 * float(native[key])
            for candidate, native in (
                (low_rec[("full", repeat)], low_rec[("orb_only", repeat)]),
                (low_on[("full", repeat)], low_on[("orb_only", repeat)]),
            )
            for key in ("ape_rmse_m", "rpe_rmse_m")
        )
        for repeat in range(1, 5)
    ]
    if not normal_exact:
        raise RuntimeError("normal-texture trajectories do not satisfy exact byte parity")
    for kind in ("reconstructed", "online"):
        native_drop_hashes = {
            low_hashes[role][kind][repeat - 1]
            for role in ("orb_only", "drop")
            for repeat in range(1, 5)
        }
        if len(native_drop_hashes) != 1:
            raise RuntimeError(f"low-texture native/drop {kind} parity failed")
        if len(set(low_hashes["full"][kind][:3])) != 1:
            raise RuntimeError(f"low-texture v23 r1-r3 {kind} parity failed")

    source_hashes = {
        "analysis_script": sha256(Path(__file__).resolve()),
        "binary": sha256(
            Path(
                "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/"
                "Examples_old/Monocular/mono_euroc_old"
            )
        ),
        "library": sha256(
            Path(
                "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/"
                "lib/libORB_SLAM3.so"
            )
        ),
        "tracking_source": sha256(
            Path(
                "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/"
                "src/Tracking.cc"
            )
        ),
        "runner": sha256(WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        "evaluator": sha256(WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        "low_full_seeds": sha256(LOW_ROOT / "assets/full_seeds.txt"),
        "normal_full_seeds": sha256(NORMAL_ROOT / "assets/full_seeds.txt"),
    }
    low_run_records = collect_run_records(LOW_RUNS, ROLE_ORDER, range(1, 5))
    normal_run_records = collect_run_records(
        NORMAL_RUNS, normal_roles, range(1, 5)
    )
    diagnostic_run_records = collect_run_records(
        DIAG_RUNS, ROLE_ORDER, range(1, 2)
    )
    validate_frozen_lineage(
        (low_run_records, normal_run_records, diagnostic_run_records), source_hashes
    )
    diagnostic_counters = v23_counters(
        DIAG_RUNS, ("full_unbounded", "full"), range(1, 2)
    )
    diagnostic_boundary = diagnostic_event_boundary(DIAG_RUNS)
    seeded_acceptance = {
        (int(row["attempted_seeds"]), int(row["accepted_seeds"]))
        for row in low_reconstructed
        if row["role"] in ("full_bridge_off", "full_unbounded", "full")
    }
    if seeded_acceptance != {(8, 8)}:
        raise RuntimeError(f"unexpected low-texture seeded acceptance: {seeded_acceptance}")
    action_keys = (
        "assisted_matches",
        "assisted_outliers",
        "pre_kf_outliers",
        "pre_kf_purged",
    )
    if any(counter[key] for counter in low_counters for key in action_keys):
        raise RuntimeError("low-texture formal run unexpectedly contains v23 action")
    if any(counter[key] for counter in normal_counters for key in action_keys):
        raise RuntimeError("normal-texture no-harm run unexpectedly contains v23 action")
    normal_scan_counts = {counter["pre_kf_scans"] for counter in normal_counters}
    if len(normal_scan_counts) != 1:
        raise RuntimeError(f"normal pre-KF scan counts differ: {normal_scan_counts}")
    normal_scan_count = next(iter(normal_scan_counts))
    diagnostic_counter_lookup = {
        (str(counter["role"]), int(counter["repeat"])): counter
        for counter in diagnostic_counters
    }
    diagnostic_unbounded = diagnostic_counter_lookup[("full_unbounded", 1)]
    diagnostic_candidate = diagnostic_counter_lookup[("full", 1)]
    if diagnostic_boundary["candidate_assisted_outlier_events"] != diagnostic_candidate[
        "assisted_outliers"
    ]:
        raise RuntimeError("diagnostic event/counter outlier totals disagree")
    normal_reference_rec = normal_rec[("orb_only", 1)]
    normal_reference_on = normal_on[("orb_only", 1)]
    input_artifacts = {
        "low_evaluation_reconstructed": artifact_record(
            LOW_RUNS / "evaluation_reconstructed.csv"
        ),
        "low_evaluation_online": artifact_record(LOW_RUNS / "evaluation_online.csv"),
        "normal_evaluation_reconstructed": artifact_record(
            NORMAL_RUNS / "evaluation_reconstructed.csv"
        ),
        "normal_evaluation_online": artifact_record(
            NORMAL_RUNS / "evaluation_online.csv"
        ),
        "diagnostic_evaluation_reconstructed": artifact_record(
            DIAG_RUNS / "evaluation_reconstructed.csv"
        ),
        "diagnostic_evaluation_online": artifact_record(
            DIAG_RUNS / "evaluation_online.csv"
        ),
        "diagnostic_unbounded_events": artifact_record(
            DIAG_RUNS / "full_unbounded_r1/instrumentation/seed_events.csv"
        ),
        "diagnostic_candidate_events": artifact_record(
            DIAG_RUNS / "full_r1/instrumentation/seed_events.csv"
        ),
        "low_frontend_stats": artifact_record(LOW_FRONTEND_STATS),
        "normal_frontend_stats": artifact_record(NORMAL_FRONTEND_STATS),
        "low_seed_export_stats": artifact_record(low_seed_stats_path),
        "normal_seed_export_stats": artifact_record(normal_seed_stats_path),
        "low_native_times": artifact_record(
            Path(
                "/mnt/data/AQUA-FE_WS/orbslam3_validation/"
                "ntnu_fjord4_s30_d10/dataset/cam0_times.txt"
            )
        ),
        "normal_native_times": artifact_record(
            NORMAL_ROOT / "dataset/cam0_times.txt"
        ),
        "low_groundtruth": artifact_record(
            Path(
                "/mnt/data/AQUA-FE_WS/orbslam3_validation/"
                "ntnu_fjord4_s30_d10/dataset/groundtruth_tum.txt"
            )
        ),
        "normal_groundtruth": artifact_record(
            NORMAL_ROOT / "dataset/groundtruth_tum.txt"
        ),
        "camera_config": artifact_record(CAMERA_CONFIG),
    }
    provenance = {
        "source_hashes": source_hashes,
        "input_artifacts": input_artifacts,
        "low_texture_run_root": str(LOW_RUNS),
        "normal_texture_run_root": str(NORMAL_RUNS),
        "diagnostic_run_root": str(DIAG_RUNS),
        "frozen_run_records": {
            "low_texture": low_run_records,
            "normal_texture": normal_run_records,
            "diagnostic": diagnostic_run_records,
        },
        "frontend_summary": {
            "low_feature_frames": len(low_frontend),
            "low_seed_ids": low_seed_stats["seed_ids"],
            "low_seed_observations": low_seed_stats["seed_observations"],
            "normal_feature_frames": len(normal_frontend),
            "normal_healthy_frames": normal_healthy_frames,
            "normal_grid_coverage_median": normal_grid_coverage_median,
            "normal_selector_injected_observations": normal_selector_injections,
            "normal_seed_observations": normal_seed_stats["seed_observations"],
        },
        "low_trajectory_hashes": low_hashes,
        "normal_trajectory_hashes": normal_hashes,
        "low_v23_counters": low_counters,
        "normal_v23_counters": normal_counters,
        "diagnostic_v23_counters": diagnostic_counters,
        "diagnostic_event_boundary": diagnostic_boundary,
        "normal_exact_byte_parity": normal_exact,
    }
    FIGURES.mkdir(parents=True, exist_ok=True)
    write_summary_csv(
        low_reconstructed, low_online, normal_reconstructed, normal_online
    )
    figure_low_texture(low_reconstructed, low_online)
    figure_noharm(normal_reconstructed, normal_online)
    (OUTPUT / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )

    analysis = f"""# ORB-SLAM3 v23 NTNU cross-dataset strict analysis

## Analysis question and locked protocol

- Question 1: does frozen A10 v23 transfer without retuning to the independent low-texture NTNU fjord_4 `s30,d10` final-online lineage?
- Question 2: does the same frozen system preserve a non-overlapping normal-texture NTNU window, fjord_4 `s50,d20`?
- Frozen mechanism: lineage-first bridge, quality >= 0.9, projection <= 4 px, descriptor distance <= 100, no dose/grace/quarantine, pre-KeyFrame assisted-outlier purge enabled.
- Runtime contract: CPU2, LocalMapping/LoopClosing barriers, deterministic background gate, ASLR disabled, online trajectory export, four repeats with a role-order swap in r4.
- Primary acceptance: reconstructed and online APE/RPE; no-harm requires all four metrics within 5% of native ORB. Byte parity is stronger than the threshold criterion.
- Independent evidence unit for cross-window inference: window (`n=1` per texture condition here). The four repeats are paired runtime replications used only to diagnose determinism and role-order sensitivity.

## Main findings

### Low-texture final-online transfer fails

- The frozen selector exported {low_seed_stats["seed_ids"]} lineage with {low_seed_stats["seed_observations"]} observations; ORB accepted 8/8 in every seeded arm and repeat.
- The lineage never formed a MapPoint: `seed_lineages_with_mappoint=0`, assisted matches `0`, pre-KF assisted outliers/purges `0/0` in all candidate and unbounded runs.
- Native ORB and exact-drop are byte-identical across all four repeats.
- v23 candidate has reconstructed APE mean `{low_full_ape_rec.mean():.6f}` m versus native `{low_native_ape_rec.mean():.6f}` m, but online APE mean `{low_full_ape_on.mean():.6f}` m versus native `{low_native_ape_on.mean():.6f}` m.
- Candidate vs native mean relative changes (positive is improvement): reconstructed APE `{pct(low_full_ape_rec.mean(), low_native_ape_rec.mean()):.3f}%`, reconstructed RPE `{pct(low_full_rpe_rec.mean(), low_native_rpe_rec.mean()):.3f}%`, online APE `{pct(low_full_ape_on.mean(), low_native_ape_on.mean()):.3f}%`, online RPE `{pct(low_full_rpe_on.mean(), low_native_rpe_on.mean()):.3f}%`.
- Four-metric 5% no-harm passes `{sum(low_candidate_noharm)}/4` repeats. Therefore this is a real frozen cross-dataset negative result, not a v23 mechanism positive.
- Candidate is byte-identical in r1-r3 but follows an alternate natural map branch in the role-swapped r4. Unbounded follows its alternate branch in r2. With zero guard action, these branch changes cannot be attributed to the purge.

### Normal-texture no-harm passes exactly

- Frontend screening: {normal_healthy_frames}/{len(normal_frontend)} feature frames are `healthy`; median grid coverage is {normal_grid_coverage_median:.4f}; accepted learned observations are {normal_selector_injections}.
- All 12 runs produce {normal_reference_rec["output_poses"]}/{normal_reference_rec["input_frames"]} poses (coverage {float(normal_reference_rec["coverage_ratio"]):.10f}), zero reset, zero relocalization, complete instrumentation, and zero overflow.
- Reconstructed APE/RPE are `{float(normal_reference_rec["ape_rmse_m"]):.6f}/{float(normal_reference_rec["rpe_rmse_m"]):.6f}` m in every role and repeat; online APE/RPE are `{float(normal_reference_on["ape_rmse_m"]):.6f}/{float(normal_reference_on["rpe_rmse_m"]):.6f}` m in every role and repeat.
- Native ORB, exact-drop, and v23 candidate reconstructed trajectories are byte-identical within and across all four repeats. The same is true for online trajectories, including the r4 role-order swap.
- v23 candidate executes {normal_scan_count} pre-KF scans per repeat but has zero seed, assisted-match, outlier, or purge action. This supports exact no-harm under healthy-texture causal fallback.

### Diagnostic multi-lineage result does not rescue the transfer claim

- A separate historical `n6_d20` asset supplies 144 observations over 6 lineages. It is diagnostic only and is not the final-online method.
- One lineage forms and survives as a MapPoint. Unbounded consumes {diagnostic_unbounded["assisted_matches"]} assisted matches and observes {diagnostic_unbounded["assisted_outliers"]} assisted outlier without purging; candidate consumes {diagnostic_candidate["assisted_matches"]} matches, observes {diagnostic_candidate["assisted_outliers"]} assisted optimizer outliers, and purges {diagnostic_candidate["pre_kf_purged"]} pre-KF outlier.
- Candidate improves reconstructed APE relative to unbounded (`{float(diag_rec[("full",1)]["ape_rmse_m"]):.6f}` vs `{float(diag_rec[("full_unbounded",1)]["ape_rmse_m"]):.6f}` m) but slightly worsens reconstructed RPE (`{float(diag_rec[("full",1)]["rpe_rmse_m"]):.6f}` vs `{float(diag_rec[("full_unbounded",1)]["rpe_rmse_m"]):.6f}` m). It remains worse than native in reconstructed and online APE.
- Event streams first differ at event index {diagnostic_boundary["first_differing_event_index"]}, before the candidate's first assisted-outlier event at index {diagnostic_boundary["first_candidate_assisted_outlier_event_index"]}. This single run is not a same-prefix causal comparison; it only proves that v23 can encounter and purge an NTNU assisted outlier.

## What changed in the evidence

1. Normal-texture cross-dataset no-harm is now closed for this fixed NTNU window under a strict byte-parity criterion.
2. Low-texture cross-dataset v23 generalization is not established. The final-online lineage arrives too early to create persistent ORB state, and online APE violates no-harm.
3. The transfer bottleneck is now upstream of the v23 commit guard: ORB needs a useful post-initialization lineage/MapPoint before the guard can regulate its persistent commit.
4. Increasing lineage dose can create action, but the historical multi-lineage profile remains mixed and branch-sensitive; it must not replace the frozen negative result.

## Claim Candidates

- Claim:
  - Source evidence: normal-texture `s50,d20`, four repeats, three roles, reconstructed/online byte parity, role-order swap.
  - Allowed wording: "On a non-overlapping normal-texture NTNU window, the causal frontend exported no learned lineage and frozen v23 preserved native ORB output exactly across four repeats."
  - Forbidden stronger wording: "v23 is universally harmless on all normal scenes."
  - Uncertainty: one normal-texture window from one independent dataset.
  - Next check: repeat the same frozen no-harm protocol on UVVID or AQUALOC-real.
  - Decision: keep

- Claim:
  - Source evidence: low-texture `s30,d10`, four repeats, 8/8 seeds accepted, zero MapPoint/assisted/purge action, 0/4 four-metric no-harm.
  - Allowed wording: "The frozen final-online lineage did not transfer as an ORB positive on NTNU because its pre-initialization seeds failed to become persistent map observations."
  - Forbidden stronger wording: "v23 fails on NTNU" or "learned geometry is useless on NTNU."
  - Uncertainty: this diagnoses one low-dose final-online lineage and not every NTNU window.
  - Next check: select an independent window with a frozen post-init final-online lineage; do not tune v23.
  - Decision: keep as negative/boundary evidence

- Claim:
  - Source evidence: multi-lineage diagnostic has one actual purge but mixed metrics and no same-prefix event stream.
  - Allowed wording: "v23 can execute its assisted-outlier purge on NTNU, but the current diagnostic does not establish a trajectory benefit."
  - Forbidden stronger wording: "v23 mechanism has generalized causally to NTNU."
  - Uncertainty: single diagnostic run, historical high-dose profile, early map divergence.
  - Next check: no further tuning on this window; move to a frozen post-init lineage candidate.
  - Decision: weaken
"""
    (OUTPUT / "analysis-report.md").write_text(analysis, encoding="utf-8")

    low_table_rows = []
    for repeat in range(1, 5):
        low_table_rows.append(
            "| {r} | {ra:.6f}/{rr:.6f} | {oa:.6f}/{orr:.6f} | {nh} |".format(
                r=repeat,
                ra=float(low_rec[("full", repeat)]["ape_rmse_m"]),
                rr=float(low_rec[("full", repeat)]["rpe_rmse_m"]),
                oa=float(low_on[("full", repeat)]["ape_rmse_m"]),
                orr=float(low_on[("full", repeat)]["rpe_rmse_m"]),
                nh="pass" if low_candidate_noharm[repeat - 1] else "fail",
            )
        )
    stats = f"""# Statistical appendix

## Units and validity

- Low-texture sample: one fixed NTNU window, four deterministic repeats per role.
- Normal-texture sample: one fixed non-overlapping NTNU window, four deterministic repeats per role.
- Repeats are paired runtime replications, not independent datasets. No t-test, Wilcoxon test, or population-level p-value is valid here.
- Exact byte equality and deterministic role-order checks are the primary robustness evidence.

## Low-texture final-online descriptive statistics

| Metric | Native mean +/- SD | v23 mean +/- SD | Mean relative improvement |
| --- | ---: | ---: | ---: |
| Reconstructed APE | `{low_native_ape_rec.mean():.6f} +/- {low_native_ape_rec.std(ddof=1):.6f}` | `{low_full_ape_rec.mean():.6f} +/- {low_full_ape_rec.std(ddof=1):.6f}` | `{pct(low_full_ape_rec.mean(), low_native_ape_rec.mean()):.3f}%` |
| Reconstructed RPE | `{low_native_rpe_rec.mean():.6f} +/- {low_native_rpe_rec.std(ddof=1):.6f}` | `{low_full_rpe_rec.mean():.6f} +/- {low_full_rpe_rec.std(ddof=1):.6f}` | `{pct(low_full_rpe_rec.mean(), low_native_rpe_rec.mean()):.3f}%` |
| Online APE | `{low_native_ape_on.mean():.6f} +/- {low_native_ape_on.std(ddof=1):.6f}` | `{low_full_ape_on.mean():.6f} +/- {low_full_ape_on.std(ddof=1):.6f}` | `{pct(low_full_ape_on.mean(), low_native_ape_on.mean()):.3f}%` |
| Online RPE | `{low_native_rpe_on.mean():.6f} +/- {low_native_rpe_on.std(ddof=1):.6f}` | `{low_full_rpe_on.mean():.6f} +/- {low_full_rpe_on.std(ddof=1):.6f}` | `{pct(low_full_rpe_on.mean(), low_native_rpe_on.mean()):.3f}%` |

Per-repeat v23 candidate:

| Repeat | Reconstructed APE/RPE | Online APE/RPE | Four-metric 5% no-harm |
| --- | ---: | ---: | --- |
{chr(10).join(low_table_rows)}

- No-harm result: `{sum(low_candidate_noharm)}/4`.
- Candidate SD reflects two alternate role/batch branches, not measurement uncertainty about a population mean.
- All four native and exact-drop trajectories are byte-identical; candidate r1-r3 are byte-identical and r4 differs after role swap.

## Normal-texture exact result

| Kind | APE/RPE in all 12 arms | Poses / coverage | Resets / relocalizations | Byte parity |
| --- | ---: | ---: | ---: | --- |
| Reconstructed | `{float(normal_reference_rec["ape_rmse_m"]):.6f}/{float(normal_reference_rec["rpe_rmse_m"]):.6f}` | `{normal_reference_rec["output_poses"]} / {float(normal_reference_rec["coverage_ratio"]):.10f}` | `{normal_reference_rec["map_resets"]}/{normal_reference_rec["relocalizations"]}` | all roles and repeats identical |
| Online | `{float(normal_reference_on["ape_rmse_m"]):.6f}/{float(normal_reference_on["rpe_rmse_m"]):.6f}` | `{normal_reference_on["output_poses"]} / {float(normal_reference_on["coverage_ratio"]):.10f}` | `{normal_reference_on["map_resets"]}/{normal_reference_on["relocalizations"]}` | all roles and repeats identical |

- v23 scans: `{normal_scan_count}` per candidate repeat.
- Learned/assisted/outlier/purge actions: `0/0/0/0` in all repeats.
- Instrumentation: complete, conservation valid, zero event or MapPoint overflow in all 12 arms.
- This is an exact equality result; mean/SD, CI, and null-hypothesis tests add no information because all differences are exactly zero.

## Diagnostic boundary

| Role | Reconstructed APE/RPE | Online APE/RPE | Assisted matches | Assisted outliers | Pre-KF purged |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unbounded | `{float(diag_rec[("full_unbounded",1)]["ape_rmse_m"]):.6f}/{float(diag_rec[("full_unbounded",1)]["rpe_rmse_m"]):.6f}` | `{float(diag_on[("full_unbounded",1)]["ape_rmse_m"]):.6f}/{float(diag_on[("full_unbounded",1)]["rpe_rmse_m"]):.6f}` | {diagnostic_unbounded["assisted_matches"]} | {diagnostic_unbounded["assisted_outliers"]} | {diagnostic_unbounded["pre_kf_purged"]} |
| v23 | `{float(diag_rec[("full",1)]["ape_rmse_m"]):.6f}/{float(diag_rec[("full",1)]["rpe_rmse_m"]):.6f}` | `{float(diag_on[("full",1)]["ape_rmse_m"]):.6f}/{float(diag_on[("full",1)]["rpe_rmse_m"]):.6f}` | {diagnostic_candidate["assisted_matches"]} | {diagnostic_candidate["assisted_outliers"]} | {diagnostic_candidate["pre_kf_purged"]} |

The event streams first differ at event index {diagnostic_boundary["first_differing_event_index"]}, before the first candidate assisted-outlier event at index {diagnostic_boundary["first_candidate_assisted_outlier_event_index"]}; no paired causal effect size is reported.
"""
    (OUTPUT / "stats-appendix.md").write_text(stats, encoding="utf-8")

    catalog = """# Figure catalog

## Figure 1: Low-texture four-metric comparison

- Files: `figures/figure-01-low-texture-four-metric.pdf` and `.png`.
- Purpose: show every role and repeat as percentage change from its matched native ORB result across all four acceptance metrics, including alternate branches.
- Data: `case_summary.csv` plus hashed raw evaluation/selector/seed artifacts in `provenance.json`; NTNU fjord_4 `s30,d10`, n=4 paired runtime repeats per role.
- Caption requirements: state that lower is better, `0%` is matched native ORB, the dashed `+5%` line is the no-harm boundary, boxes summarize four repeats, and repeats are runtime replications rather than independent windows.
- Key observation: v23 lowers reconstructed APE on its dominant branch but worsens online APE beyond the 5% no-harm boundary; no purge action occurred.
- Interpretation: the frozen final-online lineage is not a valid cross-dataset ORB positive, and the failure is upstream of the pre-KF guard.
- Caveat: role-order/batch position changes one candidate and one unbounded map branch.

## Figure 2: Normal-texture exact no-harm

- Files: `figures/figure-02-normal-texture-exact-noharm.pdf` and `.png`.
- Purpose: demonstrate byte-level trajectory equality and identical metrics under healthy-texture fallback.
- Data: hashed raw evaluation/selector/seed artifacts in `provenance.json`; NTNU fjord_4 `s50,d20`, 4 repeats x 3 roles, reconstructed and online trajectories.
- Caption requirements: explain that each of the 24 cells compares one trajectory SHA-256 against same-repeat native ORB, cross-repeat equality was checked separately, and the lower panel includes reconstructed and online APE/RPE.
- Key observation: all equality cells pass; reconstructed and online outputs are identical within and across repeats, including the role-order swap.
- Interpretation: the frozen selector plus v23 runtime path has exact no-harm when the causal frontend admits no learned lineage.
- Caveat: this is one independent normal-texture window, not a universal no-harm theorem.
"""
    (OUTPUT / "figure-catalog.md").write_text(catalog, encoding="utf-8")

    print(f"wrote analysis bundle to {OUTPUT}")


if __name__ == "__main__":
    main()
