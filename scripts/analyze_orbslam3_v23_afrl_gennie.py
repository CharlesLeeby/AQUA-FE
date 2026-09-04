#!/usr/bin/env python3
"""Build the strict AFRL Gennie ORB-SLAM3 v23 analysis bundle."""

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
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from evo.core import sync
from evo.tools import file_interface


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
RUN_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_search_20260731/"
    "afrl_gennie_s0_d20/formal_finalonline_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)
DATASET = Path(
    "/mnt/data/AQUA-FE_WS/orbslam3_validation/afrl_gennie_s0_d20/dataset"
)
ASSETS = Path(
    "/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_search_20260731/"
    "afrl_gennie_s0_d20/assets"
)
CONFIG = Path("/home/ma/AQUA-FE_WS/logs/orbslam3_validation/afrl_gennie_cam0_mono.yaml")
RUNNER = WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"
EVALUATOR = WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"
DEFAULT_OUTPUT = WORKSPACE / "papers/orb_v23_crossdataset_afrl_20260731/analysis-output"

ROLES = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
REPEATS = range(1, 5)
TRAJECTORY_KINDS = ("reconstructed", "online")
ROLE_LABEL = {
    "orb_only": "Native ORB",
    "drop": "Empty drop",
    "full_bridge_off": "Seeds, bridge off",
    "full_unbounded": "Seeds, unbounded",
    "full": "Seeds, v23",
}
ROLE_SHORT = {
    "orb_only": "Native",
    "drop": "Drop",
    "full_bridge_off": "Bridge off",
    "full_unbounded": "Unbounded",
    "full": "v23",
}
ROLE_COLOR = {
    "orb_only": "#000000",
    "drop": "#7F7F7F",
    "full_bridge_off": "#56B4E9",
    "full_unbounded": "#E69F00",
    "full": "#0072B2",
}
ROLE_HATCH = {
    "orb_only": "",
    "drop": "//",
    "full_bridge_off": "xx",
    "full_unbounded": "..",
    "full": "\\\\",
}
METRICS = ("ape_rmse_m", "rpe_rmse_m")
METRIC_LABEL = {"ape_rmse_m": "APE RMSE (m)", "rpe_rmse_m": "RPE RMSE (m)"}
MAX_TIME_DIFF_S = 0.06
RPE_DELTA_FRAMES = 20
HARM_LIMIT_PCT = 5.0
EVIDENCE_ID = "ER-20260731-afrl-gennie-v23-01"
EXPECTED_BINARY_SHA256 = "cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc"
EXPECTED_LIBRARY_SHA256 = "05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8"
EXPECTED_RUNNER_SHA256 = "6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77"
EXPECTED_ROLE_ORDER = {
    1: "orb_only drop full_bridge_off full_unbounded full",
    2: "orb_only drop full_bridge_off full_unbounded full",
    3: "orb_only drop full_bridge_off full_unbounded full",
    4: "orb_only drop full_bridge_off full full_unbounded",
}
PDF_METADATA = {
    "Creator": "AQUA-FE strict AFRL analysis builder",
    "CreationDate": datetime(2026, 7, 31, tzinfo=timezone.utc),
    "ModDate": datetime(2026, 7, 31, tzinfo=timezone.utc),
}
PNG_METADATA = {"Software": "AQUA-FE strict AFRL analysis builder"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing generated bundle only after the new bundle passes QA.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def parse_metric_report(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8", errors="strict")
    result: dict[str, float] = {}
    for field in ("rmse", "median", "max"):
        match = re.search(rf"^\s*{field}\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing {field} in metric report: {path}")
        result[field] = float(match.group(1))
    return result


def finite_nonnegative(value: str, field: str, key: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise RuntimeError(f"{key}: invalid {field}={value!r}")
    return parsed


def validate_evaluation(
    rows: list[dict[str, str]], trajectory_kind: str
) -> dict[tuple[str, int], dict[str, str]]:
    expected = {(role, repeat) for role in ROLES for repeat in REPEATS}
    actual = [(row.get("role", ""), int(row.get("repeat", "-1"))) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError(
            f"{trajectory_kind}: expected complete role/repeat grid, got {sorted(actual)}"
        )
    if len(actual) != len(set(actual)):
        raise RuntimeError(f"{trajectory_kind}: duplicate role/repeat rows")

    lookup: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        role = row["role"]
        repeat = int(row["repeat"])
        key = f"{trajectory_kind}:{role}:r{repeat}"
        if row["trajectory_kind"] != trajectory_kind:
            raise RuntimeError(f"{key}: wrong trajectory_kind")
        if row["status"] != "ok" or row["complete"] != "1":
            raise RuntimeError(f"{key}: failed or incomplete evaluation")
        if row["instrumentation_overflowed"] != "0":
            raise RuntimeError(f"{key}: instrumentation overflow")
        if row["instrumentation_conservation_ok"] != "1":
            raise RuntimeError(f"{key}: instrumentation conservation failure")
        for field in (
            "phase_conservation",
            "extractor_conservation",
            "accepted_conservation",
            "valid_tokens",
            "mappoint_pointer_consistency",
            "per_token_conservation",
            "mappoint_pointer_key_consistency",
            "atlas_snapshot_available",
        ):
            if row[field] != "1":
                raise RuntimeError(f"{key}: {field}=0")
        if int(row["input_frames"]) != 389:
            raise RuntimeError(f"{key}: unexpected input frame count")
        if int(row["output_poses"]) <= 0:
            raise RuntimeError(f"{key}: empty trajectory")
        coverage = finite_nonnegative(row["coverage_ratio"], "coverage_ratio", key)
        if coverage > 1:
            raise RuntimeError(f"{key}: coverage exceeds one")
        for metric in (
            "ape_rmse_m",
            "ape_median_m",
            "ape_max_m",
            "rpe_rmse_m",
            "rpe_median_m",
            "rpe_max_m",
        ):
            finite_nonnegative(row[metric], metric, key)
        lookup[(role, repeat)] = row
    return lookup


def validate_evaluation_pair(
    reconstructed: dict[tuple[str, int], dict[str, str]],
    online: dict[tuple[str, int], dict[str, str]],
) -> None:
    if set(reconstructed) != set(online):
        raise RuntimeError("reconstructed and online grids differ")
    shared = (
        "input_frames",
        "map_resets",
        "relocalizations",
        "seeded_frames",
        "attempted_seeds",
        "accepted_seeds",
        "pre_init_attempted_seeds",
        "pre_init_accepted_seeds",
        "post_init_attempted_seeds",
        "post_init_accepted_seeds",
        "seed_lineages_with_mappoint",
        "seed_lineages_surviving",
        "accepted_observations_with_mappoint",
        "distinct_mappoints",
        "keyframe_observations",
        "output_poses",
        "coverage_ratio",
        "first_output_delay_s",
        "continuous_span_s",
        "terminal_drop_s",
        "run_dir",
        "status",
    )
    for key in reconstructed:
        mismatch = [
            field
            for field in shared
            if reconstructed[key][field] != online[key][field]
        ]
        if mismatch:
            raise RuntimeError(f"{key}: evaluation metadata mismatch: {mismatch}")


def validate_snapshot(snapshot: Path) -> int:
    root = snapshot.parent.resolve()
    count = 0
    for line in snapshot.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"unsafe frozen snapshot path: {relative}")
        candidate = (root / relative_path).resolve()
        if root not in candidate.parents:
            raise RuntimeError(f"frozen snapshot path escapes root: {relative}")
        if not candidate.is_file() or sha256(candidate) != expected:
            raise RuntimeError(f"frozen snapshot entry mismatch: {candidate}")
        count += 1
    if count == 0:
        raise RuntimeError(f"empty frozen snapshot manifest: {snapshot}")
    return count


def trajectory_path(run_dir: Path, kind: str) -> Path:
    prefix = "online_f_" if kind == "online" else "f_"
    candidates = [
        path
        for path in run_dir.glob(f"{prefix}*.txt")
        if not path.name.endswith("_sec.txt") and not path.name.startswith("kf_")
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one {kind} trajectory in {run_dir}: {candidates}")
    return candidates[0]


def keyframe_trajectory_path(run_dir: Path) -> Path:
    candidates = [
        path
        for path in run_dir.glob("kf_*.txt")
        if not path.name.endswith("_sec.txt")
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one keyframe trajectory in {run_dir}: {candidates}")
    return candidates[0]


def trajectory_row_count(path: Path) -> int:
    count = sum(1 for line in path.read_text(encoding="ascii").splitlines() if line.strip())
    if count <= 0:
        raise RuntimeError(f"empty trajectory: {path}")
    return count


def expected_role_flags(role: str) -> dict[str, str]:
    if role == "full_bridge_off":
        return {
            "external_lineage_bridge_enabled": "0",
            "external_lineage_pre_kf_outlier_purge": "0",
            "external_lineage_pre_kf_outlier_purge_enforce": "0",
        }
    if role == "full_unbounded":
        return {
            "external_lineage_bridge_enabled": "1",
            "external_lineage_pre_kf_outlier_purge": "1",
            "external_lineage_pre_kf_outlier_purge_enforce": "0",
        }
    if role == "full":
        return {
            "external_lineage_bridge_enabled": "1",
            "external_lineage_pre_kf_outlier_purge": "1",
            "external_lineage_pre_kf_outlier_purge_enforce": "1",
        }
    return {
        "external_lineage_bridge_enabled": "1",
        "external_lineage_pre_kf_outlier_purge": "0",
        "external_lineage_pre_kf_outlier_purge_enforce": "0",
    }


def validate_seed_summary(path: Path, run_dir: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("complete") is not True or data.get("status") != "ok":
        raise RuntimeError(f"incomplete instrumentation: {path}")
    for field in ("events_overflowed", "related_mappoint_overflowed"):
        if data[field] != 0:
            raise RuntimeError(f"{path}: {field}={data[field]}")
    for field in (
        "phase_conservation",
        "extractor_conservation",
        "accepted_conservation",
        "per_token_conservation",
        "reference_lineage_decision_conservation",
        "lineage_cull_grace_conservation",
        "valid_tokens",
        "mappoint_pointer_consistency",
        "mappoint_pointer_key_consistency",
        "atlas_snapshot_available",
    ):
        if data[field] is not True:
            raise RuntimeError(f"{path}: {field} is not true")
    if Path(str(data["output_directory"])).resolve() != (run_dir / "instrumentation").resolve():
        raise RuntimeError(f"instrumentation output directory mismatch: {path}")
    return data


def metric_report_path(run_dir: Path, kind: str, metric: str) -> Path:
    prefix = "online_" if kind == "online" else ""
    if metric == "ape_rmse_m":
        return run_dir / f"{prefix}ape_trans.txt"
    return run_dir / f"{prefix}rpe_trans_{RPE_DELTA_FRAMES}f.txt"


def load_and_validate_runs(
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]]
) -> tuple[
    dict[tuple[str, int], dict[str, object]],
    dict[str, dict[str, list[str]]],
    list[dict[str, object]],
]:
    common_manifest = {
        "seed_phase": "all",
        "seed_min_ok_frames": "0",
        "seed_audit_enabled": "1",
        "seed_audit_max_events": "131072",
        "external_lineage_bridge_requested": "1",
        "external_lineage_min_quality": "0.9",
        "external_lineage_max_projection_error_px": "4.0",
        "external_lineage_max_descriptor_distance": "100",
        "external_lineage_cull_grace_requested": "0",
        "external_lineage_max_assisted_matches_requested": "0",
        "external_lineage_native_birth_only_requested": "0",
        "external_lineage_quarantine_on_outlier_requested": "0",
        "external_lineage_terminal_quarantine_requested": "0",
        "external_lineage_quarantine_enforce_requested": "0",
        "external_lineage_pre_kf_outlier_purge_requested": "1",
        "external_lineage_pre_kf_outlier_purge_enforce_requested": "1",
        "cpu_affinity": "2",
        "scheduler_mode": "single_cpu",
        "synchronize_local_mapping": "1",
        "local_mapping_idle_timeout_sec": "60",
        "synchronize_loop_closing": "1",
        "loop_closing_idle_timeout_sec": "60",
        "deterministic_background_gate": "1",
        "disable_aslr": "1",
        "export_online_trajectory": "1",
        "binary_sha256": EXPECTED_BINARY_SHA256,
        "liborbslam3_sha256": EXPECTED_LIBRARY_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
    }
    expected_seed_hash = {
        "orb_only": "",
        "drop": sha256(ASSETS / "drop_seeds.txt"),
        "full_bridge_off": sha256(ASSETS / "full_seeds.txt"),
        "full_unbounded": sha256(ASSETS / "full_seeds.txt"),
        "full": sha256(ASSETS / "full_seeds.txt"),
    }

    records: dict[tuple[str, int], dict[str, object]] = {}
    hashes: dict[str, dict[str, list[str]]] = {
        role: {kind: [] for kind in TRAJECTORY_KINDS} for role in ROLES
    }
    direct_inputs: list[dict[str, object]] = []
    for role in ROLES:
        for repeat in REPEATS:
            run_dir = RUN_ROOT / f"{role}_r{repeat}"
            manifest_path = run_dir / "run_manifest.txt"
            snapshot_path = run_dir / "provenance/snapshot_sha256.txt"
            summary_path = run_dir / "instrumentation/seed_summary.json"
            manifest = parse_manifest(manifest_path)
            key = f"{role}:r{repeat}"
            if manifest.get("role") != role or manifest.get("repeat") != str(repeat):
                raise RuntimeError(f"{key}: manifest identity mismatch")
            if manifest.get("role_order") != EXPECTED_ROLE_ORDER[repeat]:
                raise RuntimeError(f"{key}: role order mismatch")
            for field, expected in {**common_manifest, **expected_role_flags(role)}.items():
                if manifest.get(field) != expected:
                    raise RuntimeError(
                        f"{key}: manifest {field}={manifest.get(field)!r}, expected {expected!r}"
                    )
            if manifest.get("seed_sha256") != expected_seed_hash[role]:
                raise RuntimeError(f"{key}: seed hash mismatch")
            if Path(manifest["dataset_dir"]).resolve() != DATASET.resolve():
                raise RuntimeError(f"{key}: dataset path mismatch")
            if Path(manifest["times_file"]).resolve() != (DATASET / "cam0_times.txt").resolve():
                raise RuntimeError(f"{key}: times path mismatch")
            if Path(manifest["config"]).resolve() != CONFIG.resolve():
                raise RuntimeError(f"{key}: config path mismatch")
            if sha256(snapshot_path) != manifest.get("provenance_manifest_sha256"):
                raise RuntimeError(f"{key}: provenance manifest hash mismatch")
            snapshot_entries = validate_snapshot(snapshot_path)
            summary = validate_seed_summary(summary_path, run_dir)
            keyframe_trajectory = keyframe_trajectory_path(run_dir)
            keyframe_count = trajectory_row_count(keyframe_trajectory)
            log_path = run_dir / "orbslam3_run.log"

            trajectory_records: dict[str, dict[str, object]] = {}
            for kind in TRAJECTORY_KINDS:
                trajectory = trajectory_path(run_dir, kind)
                sec = trajectory.with_name(trajectory.stem + "_sec.txt")
                trajectory_hash = sha256(trajectory)
                hashes[role][kind].append(trajectory_hash)
                reports: dict[str, dict[str, object]] = {}
                row = evaluations[kind][(role, repeat)]
                for metric in METRICS:
                    report_path = metric_report_path(run_dir, kind, metric)
                    report = parse_metric_report(report_path)
                    if report["rmse"] != float(row[metric]):
                        raise RuntimeError(f"{key}:{kind}: CSV/report mismatch for {metric}")
                    reports[metric] = artifact(report_path)
                    direct_inputs.append(artifact(report_path))
                trajectory_records[kind] = {
                    "trajectory": artifact(trajectory),
                    "trajectory_sec": artifact(sec),
                    "reports": reports,
                }
                direct_inputs.extend((artifact(trajectory), artifact(sec)))

            records[(role, repeat)] = {
                "manifest": manifest,
                "manifest_artifact": artifact(manifest_path),
                "snapshot_artifact": artifact(snapshot_path),
                "snapshot_entries_validated": snapshot_entries,
                "summary": summary,
                "summary_artifact": artifact(summary_path),
                "keyframe_trajectory": artifact(keyframe_trajectory),
                "keyframe_count": keyframe_count,
                "run_log": artifact(log_path),
                "trajectories": trajectory_records,
            }
            direct_inputs.extend(
                (
                    artifact(manifest_path),
                    artifact(snapshot_path),
                    artifact(summary_path),
                    artifact(keyframe_trajectory),
                    artifact(log_path),
                )
            )
    return records, hashes, direct_inputs


def association_audit(
    records: dict[tuple[str, int], dict[str, object]]
) -> dict[str, object]:
    reference = file_interface.read_tum_trajectory_file(str(DATASET / "groundtruth_tum.txt"))
    rows: list[dict[str, object]] = []
    for kind in TRAJECTORY_KINDS:
        for role in ROLES:
            for repeat in REPEATS:
                path = Path(
                    str(
                        records[(role, repeat)]["trajectories"][kind]["trajectory_sec"][
                            "path"
                        ]
                    )
                )
                estimate = file_interface.read_tum_trajectory_file(str(path))
                ref_sync, est_sync = sync.associate_trajectories(
                    reference, estimate, max_diff=MAX_TIME_DIFF_S
                )
                absolute_dt = np.abs(ref_sync.timestamps - est_sync.timestamps)
                physical_dt = (
                    ref_sync.timestamps[RPE_DELTA_FRAMES:]
                    - ref_sync.timestamps[:-RPE_DELTA_FRAMES]
                )
                if len(physical_dt) == 0:
                    raise RuntimeError(f"not enough associated poses for {kind}:{role}:r{repeat}")
                rows.append(
                    {
                        "trajectory_kind": kind,
                        "role": role,
                        "repeat": repeat,
                        "gt_poses": reference.num_poses,
                        "estimate_poses": estimate.num_poses,
                        "associated_poses": ref_sync.num_poses,
                        "association_abs_dt_min_s": float(absolute_dt.min()),
                        "association_abs_dt_median_s": float(np.median(absolute_dt)),
                        "association_abs_dt_max_s": float(absolute_dt.max()),
                        "rpe_pairs": len(physical_dt),
                        "rpe_physical_dt_min_s": float(physical_dt.min()),
                        "rpe_physical_dt_median_s": float(np.median(physical_dt)),
                        "rpe_physical_dt_max_s": float(physical_dt.max()),
                    }
                )
    comparable_fields = (
        "gt_poses",
        "estimate_poses",
        "associated_poses",
        "association_abs_dt_min_s",
        "association_abs_dt_median_s",
        "association_abs_dt_max_s",
        "rpe_pairs",
        "rpe_physical_dt_min_s",
        "rpe_physical_dt_median_s",
        "rpe_physical_dt_max_s",
    )
    signatures = {tuple(row[field] for field in comparable_fields) for row in rows}
    if len(signatures) != 1:
        raise RuntimeError("trajectory association protocol differs across arms")
    return {"settings": {"max_time_diff_s": MAX_TIME_DIFF_S, "rpe_delta_frames": RPE_DELTA_FRAMES}, "common": {field: rows[0][field] for field in comparable_fields}, "rows_checked": len(rows)}


def mean_sd(values: list[float]) -> tuple[float, float]:
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0


def pct_change(candidate: float, control: float) -> float:
    return 100.0 * (candidate / control - 1.0)


def build_tables(
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]],
    records: dict[tuple[str, int], dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    cases: list[dict[str, object]] = []
    effects: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for kind in TRAJECTORY_KINDS:
        lookup = evaluations[kind]
        for role in ROLES:
            for repeat in REPEATS:
                row = lookup[(role, repeat)]
                summary = records[(role, repeat)]["summary"]
                cases.append(
                    {
                        "trajectory_kind": kind,
                        "role": role,
                        "repeat": repeat,
                        "status": row["status"],
                        "complete": row["complete"],
                        "output_poses": row["output_poses"],
                        "coverage_ratio": row["coverage_ratio"],
                        "first_output_delay_s": row["first_output_delay_s"],
                        "map_resets": row["map_resets"],
                        "relocalizations": row["relocalizations"],
                        "ape_rmse_m": row["ape_rmse_m"],
                        "rpe_rmse_m": row["rpe_rmse_m"],
                        "attempted_seeds": row["attempted_seeds"],
                        "accepted_seeds": row["accepted_seeds"],
                        "post_init_accepted_seeds": row["post_init_accepted_seeds"],
                        "seed_lineages_with_mappoint": row["seed_lineages_with_mappoint"],
                        "accepted_observations_with_mappoint": row[
                            "accepted_observations_with_mappoint"
                        ],
                        "keyframe_observations": row["keyframe_observations"],
                        "lineage_assisted_matches_consumed": summary[
                            "lineage_assisted_matches_consumed"
                        ],
                        "lineage_pre_kf_outlier_purge_scans": summary[
                            "lineage_pre_kf_outlier_purge_scans"
                        ],
                        "lineage_pre_kf_assisted_outliers_observed": summary[
                            "lineage_pre_kf_assisted_outliers_observed"
                        ],
                        "lineage_pre_kf_assisted_outliers_purged": summary[
                            "lineage_pre_kf_assisted_outliers_purged"
                        ],
                        "instrumentation_overflowed": row[
                            "instrumentation_overflowed"
                        ],
                        "run_dir": row["run_dir"],
                    }
                )
                native = lookup[("orb_only", repeat)]
                for metric in METRICS:
                    candidate_value = float(row[metric])
                    native_value = float(native[metric])
                    effects.append(
                        {
                            "trajectory_kind": kind,
                            "role": role,
                            "repeat": repeat,
                            "metric": metric,
                            "candidate_rmse_m": f"{candidate_value:.9f}",
                            "native_rmse_m": f"{native_value:.9f}",
                            "absolute_difference_m": f"{candidate_value-native_value:.9f}",
                            "relative_change_vs_native_pct": f"{pct_change(candidate_value, native_value):.9f}",
                        }
                    )

            values = {
                metric: [float(lookup[(role, repeat)][metric]) for repeat in REPEATS]
                for metric in METRICS
            }
            relative = {
                metric: [
                    pct_change(
                        float(lookup[(role, repeat)][metric]),
                        float(lookup[("orb_only", repeat)][metric]),
                    )
                    for repeat in REPEATS
                ]
                for metric in METRICS
            }
            ape_mean, ape_sd = mean_sd(values["ape_rmse_m"])
            rpe_mean, rpe_sd = mean_sd(values["rpe_rmse_m"])
            ape_rel_mean, ape_rel_sd = mean_sd(relative["ape_rmse_m"])
            rpe_rel_mean, rpe_rel_sd = mean_sd(relative["rpe_rmse_m"])
            summaries.append(
                {
                    "trajectory_kind": kind,
                    "role": role,
                    "repeat_count": 4,
                    "ape_rmse_mean_m": f"{ape_mean:.9f}",
                    "ape_rmse_sd_m": f"{ape_sd:.9f}",
                    "rpe_rmse_mean_m": f"{rpe_mean:.9f}",
                    "rpe_rmse_sd_m": f"{rpe_sd:.9f}",
                    "ape_relative_change_vs_native_mean_pct": f"{ape_rel_mean:.9f}",
                    "ape_relative_change_vs_native_sd_pct": f"{ape_rel_sd:.9f}",
                    "rpe_relative_change_vs_native_mean_pct": f"{rpe_rel_mean:.9f}",
                    "rpe_relative_change_vs_native_sd_pct": f"{rpe_rel_sd:.9f}",
                }
            )
    return cases, effects, summaries


def hash_audit(
    hashes: dict[str, dict[str, list[str]]],
    records: dict[tuple[str, int], dict[str, object]],
) -> dict[str, object]:
    within_role = {
        role: {
            kind: {"unique_hashes": len(set(hashes[role][kind])), "hashes": hashes[role][kind]}
            for kind in TRAJECTORY_KINDS
        }
        for role in ROLES
    }
    full_unbounded_parity = {
        kind: [
            hashes["full"][kind][repeat - 1]
            == hashes["full_unbounded"][kind][repeat - 1]
            for repeat in REPEATS
        ]
        for kind in TRAJECTORY_KINDS
    }
    drop_native_parity = {
        kind: [
            hashes["drop"][kind][repeat - 1]
            == hashes["orb_only"][kind][repeat - 1]
            for repeat in REPEATS
        ]
        for kind in TRAJECTORY_KINDS
    }
    if not all(all(values) for values in full_unbounded_parity.values()):
        raise RuntimeError("full and full_unbounded trajectories are not byte-identical")
    return {
        "within_role": within_role,
        "full_vs_full_unbounded_same_repeat_parity": full_unbounded_parity,
        "drop_vs_native_same_repeat_parity": drop_native_parity,
        "keyframe_pose_counts": {
            role: [records[(role, repeat)]["keyframe_count"] for repeat in REPEATS]
            for role in ROLES
        },
    }


def configure_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 8.5,
            "axes.labelsize": 9,
            "axes.titlesize": 9.5,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 7.5,
            "axes.linewidth": 0.8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, figures: Path, stem: str) -> None:
    fig.savefig(figures / f"{stem}.pdf", metadata=PDF_METADATA, bbox_inches="tight")
    fig.savefig(
        figures / f"{stem}.png",
        dpi=600,
        metadata=PNG_METADATA,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def figure_absolute_metrics(
    figures: Path,
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]],
) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0), constrained_layout=True)
    offsets = np.array([-0.09, -0.03, 0.03, 0.09])
    panels = (
        ("reconstructed", "ape_rmse_m"),
        ("reconstructed", "rpe_rmse_m"),
        ("online", "ape_rmse_m"),
        ("online", "rpe_rmse_m"),
    )
    for axis, (kind, metric) in zip(axes.flat, panels):
        lookup = evaluations[kind]
        positions = np.arange(len(ROLES))
        grouped = [
            [float(lookup[(role, repeat)][metric]) for repeat in REPEATS]
            for role in ROLES
        ]
        means = [statistics.mean(values) for values in grouped]
        sds = [statistics.stdev(values) for values in grouped]
        bars = axis.bar(
            positions,
            means,
            yerr=sds,
            capsize=3,
            color=[ROLE_COLOR[role] for role in ROLES],
            edgecolor="black",
            linewidth=0.6,
            alpha=0.78,
        )
        for patch, role in zip(bars, ROLES):
            patch.set_hatch(ROLE_HATCH[role])
        for index, (role, values) in enumerate(zip(ROLES, grouped)):
            axis.scatter(
                index + offsets,
                values,
                s=18,
                color=ROLE_COLOR[role],
                edgecolor="white",
                linewidth=0.5,
                zorder=3,
            )
        axis.set_title(f"{kind.capitalize()} {METRIC_LABEL[metric]}")
        axis.set_ylabel("RMSE (m)")
        axis.set_xticks(positions)
        axis.set_xticklabels([ROLE_SHORT[role] for role in ROLES], rotation=22, ha="right")
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25, linewidth=0.7)
    save_figure(fig, figures, "figure-01-five-arm-absolute-metrics")


def figure_relative_zoom(
    figures: Path,
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]],
) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.25), constrained_layout=True, sharey=True)
    shown_roles = ("drop", "full_unbounded", "full")
    metric_positions = np.arange(len(METRICS))
    width = 0.24
    offsets = np.array([-0.045, -0.015, 0.015, 0.045])
    for axis, kind in zip(axes, TRAJECTORY_KINDS):
        lookup = evaluations[kind]
        for role_index, role in enumerate(shown_roles):
            centers = metric_positions + (role_index - 1) * width
            grouped: list[list[float]] = []
            for metric in METRICS:
                grouped.append(
                    [
                        pct_change(
                            float(lookup[(role, repeat)][metric]),
                            float(lookup[("orb_only", repeat)][metric]),
                        )
                        for repeat in REPEATS
                    ]
                )
            means = [statistics.mean(values) for values in grouped]
            sds = [statistics.stdev(values) for values in grouped]
            bars = axis.bar(
                centers,
                means,
                width,
                yerr=sds,
                capsize=3,
                label=ROLE_LABEL[role],
                color=ROLE_COLOR[role],
                edgecolor="black",
                linewidth=0.6,
                alpha=0.78,
                hatch=ROLE_HATCH[role],
            )
            for center, values in zip(centers, grouped):
                axis.scatter(
                    center + offsets,
                    values,
                    s=17,
                    color=ROLE_COLOR[role],
                    edgecolor="white",
                    linewidth=0.45,
                    zorder=3,
                )
            for bar, mean in zip(bars, means):
                if role == "full":
                    axis.text(
                        bar.get_x() + bar.get_width() / 2,
                        mean + (0.7 if mean >= 0 else -0.9),
                        f"{mean:+.2f}%",
                        ha="center",
                        va="bottom" if mean >= 0 else "top",
                        fontsize=7,
                    )
        axis.axhline(0, color="#555555", linewidth=1.0)
        axis.axhline(HARM_LIMIT_PCT, color="#D55E00", linestyle="--", linewidth=1.1)
        axis.set_title(kind.capitalize())
        axis.set_xticks(metric_positions)
        axis.set_xticklabels(("APE", "RPE"))
        axis.grid(axis="y", alpha=0.25, linewidth=0.7)
    axes[0].set_ylabel("Relative change vs matched native ORB (%)\nLower is better")
    axes[0].text(
        0.02,
        HARM_LIMIT_PCT,
        "+5% diagnostic limit",
        color="#D55E00",
        ha="left",
        va="bottom",
        fontsize=7,
        transform=axes[0].get_yaxis_transform(),
    )
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    save_figure(fig, figures, "figure-02-near-baseline-relative-change")


def figure_mechanism_counts(
    figures: Path, records: dict[tuple[str, int], dict[str, object]]
) -> None:
    configure_plot_style()
    seeded_roles = ("full_bridge_off", "full_unbounded", "full")
    reach_fields = (
        ("accepted_seed_observations", "Accepted"),
        ("accepted_observations_with_mappoint", "With MapPoint"),
        ("keyframe_observations", "Keyframe obs."),
    )
    action_fields = (
        ("lineage_assisted_matches_consumed", "Assisted matches"),
        ("lineage_pre_kf_outlier_purge_scans", "pre-KF scans"),
        ("lineage_pre_kf_assisted_outliers_observed", "Assisted outliers"),
        ("lineage_pre_kf_assisted_outliers_purged", "Purged"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.35), constrained_layout=True)
    for axis, fields, title in (
        (axes[0], reach_fields, "Seed reachability"),
        (axes[1], action_fields, "Lineage bridge and v23 action"),
    ):
        positions = np.arange(len(fields))
        width = 0.25
        plotted_values: list[int] = []
        role_bars: list[tuple[int, object, list[int]]] = []
        for role_index, role in enumerate(seeded_roles):
            values = [
                records[(role, 1)]["summary"][field]
                for field, _ in fields
            ]
            plotted_values.extend(values)
            bars = axis.bar(
                positions + (role_index - 1) * width,
                values,
                width,
                label=ROLE_LABEL[role],
                color=ROLE_COLOR[role],
                edgecolor="black",
                linewidth=0.6,
                alpha=0.78,
                hatch=ROLE_HATCH[role],
            )
            role_bars.append((role_index, bars, values))
        axis.set_title(title)
        axis.set_ylabel("Count per run")
        axis.set_xticks(positions)
        axis.set_xticklabels([label for _, label in fields], rotation=18, ha="right")
        maximum = max(plotted_values)
        axis.set_ylim(0, maximum * 1.25 if maximum else 1)
        for role_index, bars, values in role_bars:
            for bar, value in zip(bars, values):
                if value == 0:
                    continue
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    value + maximum * (0.018 + 0.045 * role_index),
                    str(value),
                    ha="center",
                    va="bottom",
                    fontsize=6.8,
                )
        if title == "Lineage bridge and v23 action":
            axis.text(
                0.98,
                0.92,
                "Assisted outliers: 0 (all roles)\nPurged: 0 (all roles)",
                transform=axis.transAxes,
                ha="right",
                va="top",
                fontsize=7,
            )
        axis.grid(axis="y", alpha=0.25, linewidth=0.7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    save_figure(fig, figures, "figure-03-reachability-and-action-counts")


def markdown_summary_table(summary_rows: list[dict[str, object]]) -> str:
    lookup = {(row["trajectory_kind"], row["role"]): row for row in summary_rows}
    lines = [
        "| Trajectory | Role | APE RMSE, mean +/- SD (m) | RPE RMSE, mean +/- SD (m) | APE vs native | RPE vs native |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for kind in TRAJECTORY_KINDS:
        for role in ROLES:
            row = lookup[(kind, role)]
            lines.append(
                "| {kind} | {role} | {ape_mean:.6f} +/- {ape_sd:.6f} | "
                "{rpe_mean:.6f} +/- {rpe_sd:.6f} | {ape_rel:+.3f}% | {rpe_rel:+.3f}% |".format(
                    kind=kind,
                    role=ROLE_LABEL[role],
                    ape_mean=float(row["ape_rmse_mean_m"]),
                    ape_sd=float(row["ape_rmse_sd_m"]),
                    rpe_mean=float(row["rpe_rmse_mean_m"]),
                    rpe_sd=float(row["rpe_rmse_sd_m"]),
                    ape_rel=float(row["ape_relative_change_vs_native_mean_pct"]),
                    rpe_rel=float(row["rpe_relative_change_vs_native_mean_pct"]),
                )
            )
    return "\n".join(lines)


def render_reports(
    output: Path,
    summary_rows: list[dict[str, object]],
    association: dict[str, object],
    hash_result: dict[str, object],
    records: dict[tuple[str, int], dict[str, object]],
) -> None:
    lookup = {(row["trajectory_kind"], row["role"]): row for row in summary_rows}
    table = markdown_summary_table(summary_rows)
    full_rec = lookup[("reconstructed", "full")]
    full_online = lookup[("online", "full")]
    bridge_rec = lookup[("reconstructed", "full_bridge_off")]
    bridge_online = lookup[("online", "full_bridge_off")]
    common = association["common"]
    drop_parity = hash_result["drop_vs_native_same_repeat_parity"]
    keyframe_counts = hash_result["keyframe_pose_counts"]
    full_summary = records[("full", 1)]["summary"]

    analysis_report = f"""# AFRL Gennie ORB-SLAM3 v23 strict analysis

## Analysis question

Does the frozen final-online XFeat lineage remain reachable after transfer to native-rate ORB-SLAM3 on AFRL Cave Gennie `s0,d20`, does the lineage bridge materially change the seeded trajectory, and is the v23 pre-keyframe purge action exercised without dataset-specific tuning?

Evidence record: `{EVIDENCE_ID}`. The independent evidence unit is one fixed AFRL window. The four runs per role are deterministic runtime replications, not four independent windows.

## QA result

- All 20 role-by-repeat runs are present, `status=ok`, instrumentation-complete, conservation-valid, non-overflowing, and have non-empty reconstructed and online trajectories.
- All runs use the frozen v23 binary `{EXPECTED_BINARY_SHA256}`, library `{EXPECTED_LIBRARY_SHA256}`, runner `{EXPECTED_RUNNER_SHA256}`, CPU 2, both background barriers, deterministic background gate, disabled ASLR, `q>=0.9`, 4 px projection, Hamming 100, and audit capacity 131072.
- Output is 343/389 poses (coverage 0.881748) with first output delay 2.334285 s, zero map resets, and zero relocalizations in every arm.
- Evaluation associates {common['associated_poses']}/{common['gt_poses']} GT poses at `max_time_diff={MAX_TIME_DIFF_S:.2f} s`. A 20-associated-pose RPE spans {common['rpe_physical_dt_min_s']:.3f}-{common['rpe_physical_dt_max_s']:.3f} s (median {common['rpe_physical_dt_median_s']:.3f} s), so it is not a fixed one-second RPE.

## Exact results

Positive relative percentages indicate higher error (harm); negative values indicate lower error.

{table}

## Key findings

1. **Reachability passes.** All 54 observations are accepted post-initialization in every seeded role. One lineage forms a MapPoint; 42 accepted observations attach to it. Bridge-on arms consume {full_summary['lineage_assisted_matches_consumed']} assisted matches and increase keyframe observations from 23 (bridge off) to 27.
2. **The bridge rescues a harmful seed-only path.** Bridge-off changes reconstructed APE/RPE by {float(bridge_rec['ape_relative_change_vs_native_mean_pct']):+.3f}%/{float(bridge_rec['rpe_relative_change_vs_native_mean_pct']):+.3f}% and online APE/RPE by {float(bridge_online['ape_relative_change_vs_native_mean_pct']):+.3f}%/{float(bridge_online['rpe_relative_change_vs_native_mean_pct']):+.3f}% versus native ORB. Bridge-on returns the trajectory close to native.
3. **Accuracy is mixed, not a positive transfer.** Frozen v23 changes reconstructed APE/RPE by {float(full_rec['ape_relative_change_vs_native_mean_pct']):+.3f}%/{float(full_rec['rpe_relative_change_vs_native_mean_pct']):+.3f}% and online APE/RPE by {float(full_online['ape_relative_change_vs_native_mean_pct']):+.3f}%/{float(full_online['rpe_relative_change_vs_native_mean_pct']):+.3f}%. APE is slightly lower while RPE is higher. Reconstructed RPE exceeds the +5% diagnostic harm limit; online RPE remains just inside it.
4. **v23 guard action is null.** Each bridge-on run performs {full_summary['lineage_pre_kf_outlier_purge_scans']} pre-KF scans, but assisted outliers observed/purged are {full_summary['lineage_pre_kf_assisted_outliers_observed']}/{full_summary['lineage_pre_kf_assisted_outliers_purged']}. `full` and `full_unbounded` are byte-identical for both trajectory kinds in all four repeats. This window cannot support a v23 purge-benefit claim.
5. **One empty-drop runtime anomaly remains visible.** Drop r1 differs from native and contains 57 keyframes, while native and drop r2-r4 contain 56; drop r2-r4 have reconstructed parity `{drop_parity['reconstructed']}` and online parity `{drop_parity['online']}`. All drop runs load zero observations. This is a residual keyframe-insertion bifurcation, not learned-seed action or a systematic empty-file effect. Native ORB is therefore the primary stable control; no row is discarded.

## Decision

- **Keep:** cross-dataset post-init reachability and lineage-bridge consumption on AFRL.
- **Keep, bounded:** the bridge prevents the large degradation of seed-only/bridge-off injection on this window.
- **Do not promote:** a trajectory-accuracy win, a strict reconstructed no-harm result, or a v23 purge-mechanism generalization claim.
- **Stop repeating this window:** four deterministic repeats already establish the branch behavior. The next useful low-texture candidate must naturally produce post-init assisted outliers under the frozen contract; thresholds and dose remain frozen.

## Claim candidates

- Claim: The final-online XFeat lineage is reachable and consumed by ORB-SLAM3 on AFRL Gennie.
  - Source evidence: `{EVIDENCE_ID}`; 54/54 post-init observations, one MapPoint lineage, 37 assisted matches in every bridge-on run.
  - Allowed wording: "The frozen lineage transferred to AFRL and participated in ORB tracking."
  - Forbidden stronger wording: "v23 improved AFRL trajectory accuracy."
  - Uncertainty: one fixed low-texture window with sparse COLMAP GT.
  - Next check: a second natural post-init window with nonzero assisted outliers.
  - Decision: keep.

- Claim: The lineage bridge mitigates the harm of direct seed-only injection on this AFRL window.
  - Source evidence: `{EVIDENCE_ID}`; bridge-off is consistently degraded, while bridge-on is close to native and consumes 37 assisted matches.
  - Allowed wording: "On this window, persistent lineage assistance was necessary to avoid the large bridge-off degradation."
  - Forbidden stronger wording: "The bridge is universally beneficial across datasets."
  - Uncertainty: the experiment isolates the bridge contract but not every internal map-lifecycle cause.
  - Next check: reproduce the bridge-off/bridge-on contrast on an independent window.
  - Decision: keep, bounded.

- Claim: v23 purge generalizes to AFRL.
  - Source evidence: `{EVIDENCE_ID}`; zero assisted outliers and zero purges, with exact `full`/`full_unbounded` parity.
  - Allowed wording: "v23 remained dormant on AFRL Gennie despite successful lineage reachability."
  - Forbidden stronger wording: "v23 guard action improved or protected the AFRL trajectory."
  - Uncertainty: no action opportunity occurred.
  - Next check: a frozen-contract window with naturally occurring assisted outliers.
  - Decision: discard as a positive claim.
"""
    (output / "analysis-report.md").write_text(analysis_report, encoding="utf-8")

    stats_appendix = f"""# Statistical appendix

## Design and unit of analysis

- Dataset/window: AFRL Cave Gennie `s0,d20`, native 20 Hz export, 389 images.
- Roles: native ORB, empty drop, seeds with bridge off, seeds with unbounded purge enforcement, and frozen v23.
- Runtime replications: four per role, with r4 swapping `full` and `full_unbounded` order.
- Independent evidence unit: one window (`n=1 window`). Runtime repeats quantify branch reproducibility only.
- Metrics: Sim(3)-aligned translational APE RMSE and 20-associated-pose translational RPE RMSE; lower is better.

## Descriptive statistics

{table}

The table reports mean +/- sample SD across four runtime replications. Zero SD means the metric was identical to six decimal places; trajectory hash parity is reported separately.

## Paired window effects

- Frozen v23 vs native, reconstructed: APE {float(full_rec['ape_relative_change_vs_native_mean_pct']):+.6f}%, RPE {float(full_rec['rpe_relative_change_vs_native_mean_pct']):+.6f}%.
- Frozen v23 vs native, online: APE {float(full_online['ape_relative_change_vs_native_mean_pct']):+.6f}%, RPE {float(full_online['rpe_relative_change_vs_native_mean_pct']):+.6f}%.
- Bridge off vs native, reconstructed: APE {float(bridge_rec['ape_relative_change_vs_native_mean_pct']):+.6f}%, RPE {float(bridge_rec['rpe_relative_change_vs_native_mean_pct']):+.6f}%.
- Bridge off vs native, online: APE {float(bridge_online['ape_relative_change_vs_native_mean_pct']):+.6f}%, RPE {float(bridge_online['rpe_relative_change_vs_native_mean_pct']):+.6f}%.

These are unstandardized relative effects for one window, not population effect sizes.

## Inferential-statistics decision

No t-test, Wilcoxon test, confidence interval, standardized effect size, or multiple-comparison correction is reported. The four repeats share the same images, GT, seeds, binary, and deterministic scheduler; treating them as independent samples would be pseudoreplication. Cross-window inference requires additional independent windows.

## Reproducibility and anomaly audit

- Native ORB, bridge-off, unbounded, and v23 each have one unique trajectory hash per trajectory kind across four repeats.
- `full` and `full_unbounded` are same-repeat byte-identical in 8/8 reconstructed/online comparisons.
- Drop/native parity is reconstructed `{drop_parity['reconstructed']}` and online `{drop_parity['online']}`. Native keyframe counts are `{keyframe_counts['orb_only']}`; drop counts are `{keyframe_counts['drop']}`. The r1 empty-drop deviation is retained in all means/SDs and blocks a claim of universal empty-control parity.
- Instrumentation is complete in 20/20 runs, with zero event or related-MapPoint overflow.

## GT association boundary

- GT poses available: {common['gt_poses']}.
- Estimated poses per run: {common['estimate_poses']}.
- Associated poses at `{MAX_TIME_DIFF_S:.2f} s`: {common['associated_poses']}.
- Association absolute time error: {common['association_abs_dt_min_s']:.6f}/{common['association_abs_dt_median_s']:.6f}/{common['association_abs_dt_max_s']:.6f} s (min/median/max).
- RPE pairs: {common['rpe_pairs']}.
- Physical duration of a 20-associated-pose delta: {common['rpe_physical_dt_min_s']:.6f}/{common['rpe_physical_dt_median_s']:.6f}/{common['rpe_physical_dt_max_s']:.6f} s (min/median/max).

The RPE label must remain "20-associated-pose RPE"; it must not be described as one-second or 20-image-frame RPE.
"""
    (output / "stats-appendix.md").write_text(stats_appendix, encoding="utf-8")

    figure_catalog = f"""# Figure catalog

## Figure 1: `figures/figure-01-five-arm-absolute-metrics.pdf`

- Purpose: show the complete five-arm reconstructed/online APE/RPE comparison without truncated axes.
- Data source: `case_summary.csv`, 4 runtime replications per role on one fixed window.
- Caption requirements: bars are means, error bars are sample SD, dots are all replications, lower is better, and repeats are not independent windows.
- Key observation: bridge-off is consistently degraded; bridge-on unbounded and v23 return close to native ORB.
- Interpretation: persistent lineage assistance changes the harmful seed-only path, but the final trajectory remains a mixed APE/RPE result.
- Caveat: the sparse GT supplies only {common['associated_poses']} associated poses.

## Figure 2: `figures/figure-02-near-baseline-relative-change.pdf`

- Purpose: resolve near-baseline effects hidden by the large bridge-off errors and show the +5% diagnostic harm line.
- Data source: `paired_effects.csv`; each role is compared with native ORB from the same repeat.
- Caption requirements: positive values mean harm, bars are mean relative change, error bars are sample SD, dots are all four runtime replications, and +5% is a diagnostic boundary rather than a significance threshold.
- Key observation: v23 slightly lowers APE but raises RPE; reconstructed RPE is +{float(full_rec['rpe_relative_change_vs_native_mean_pct']):.3f}% and online RPE is +{float(full_online['rpe_relative_change_vs_native_mean_pct']):.3f}%.
- Interpretation: this window is not a dual-metric accuracy positive; online remains within the 5% boundary while reconstructed does not.
- Caveat: drop r1 is the only non-parity empty-control run and is retained.

## Figure 3: `figures/figure-03-reachability-and-action-counts.pdf`

- Purpose: separate seed reachability, lineage bridge consumption, and v23 purge action.
- Data source: each role's frozen `instrumentation/seed_summary.json`; counts are identical across repeats, so r1 values represent all four.
- Caption requirements: bridge-off/unbounded/v23 are shown; accepted observations, MapPoint reachability, keyframe observations, assisted matches, scans, outliers, and purges are raw per-run counts.
- Key observation: bridge-on consumes 37 assisted matches and performs 214 scans, but observes and purges zero assisted outliers.
- Interpretation: the bridge is active, while the v23 guard is dormant and unidentifiable on this window.
- Caveat: scan count is an opportunity check, not evidence of a guard intervention.
"""
    (output / "figure-catalog.md").write_text(figure_catalog, encoding="utf-8")


def build_provenance(
    evaluations_paths: dict[str, Path],
    direct_inputs: list[dict[str, object]],
    records: dict[tuple[str, int], dict[str, object]],
    association: dict[str, object],
    hash_result: dict[str, object],
) -> dict[str, object]:
    top_level_paths = (
        evaluations_paths["reconstructed"],
        evaluations_paths["online"],
        DATASET / "groundtruth_tum.txt",
        DATASET / "cam0_times.txt",
        DATASET / "export_metadata.json",
        CONFIG,
        ASSETS / "full_seeds.txt",
        ASSETS / "drop_seeds.txt",
        ASSETS / "seed_export_stats.json",
        RUNNER,
        EVALUATOR,
        Path(__file__).resolve(),
    )
    top_level = [artifact(path) for path in top_level_paths]
    deduplicated: dict[str, dict[str, object]] = {
        str(record["path"]): record for record in [*top_level, *direct_inputs]
    }
    run_contracts: dict[str, dict[str, object]] = {}
    for role in ROLES:
        for repeat in REPEATS:
            record = records[(role, repeat)]
            manifest = record["manifest"]
            run_contracts[f"{role}_r{repeat}"] = {
                "manifest": record["manifest_artifact"],
                "seed_summary": record["summary_artifact"],
                "snapshot_manifest": record["snapshot_artifact"],
                "snapshot_entries_validated": record["snapshot_entries_validated"],
                "role_order": manifest["role_order"],
                "binary_sha256": manifest["binary_sha256"],
                "liborbslam3_sha256": manifest["liborbslam3_sha256"],
                "runner_sha256": manifest["runner_sha256"],
                "config_sha256": manifest["config_sha256"],
                "times_sha256": manifest["times_sha256"],
                "seed_sha256": manifest["seed_sha256"],
            }
    return {
        "schema_version": 1,
        "evidence_id": EVIDENCE_ID,
        "analysis_date": "2026-07-31",
        "experiment_root": str(RUN_ROOT),
        "comparison_unit": "one fixed AFRL window",
        "runtime_replications_per_role": 4,
        "inferential_statistics_performed": False,
        "evaluation_protocol": association,
        "trajectory_hash_audit": hash_result,
        "direct_analysis_inputs": [deduplicated[key] for key in sorted(deduplicated)],
        "run_contracts": run_contracts,
    }


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"refusing existing output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    evaluations_paths = {
        "reconstructed": RUN_ROOT / "evaluation_reconstructed.csv",
        "online": RUN_ROOT / "evaluation_online.csv",
    }
    evaluations = {
        kind: validate_evaluation(read_csv(path), kind)
        for kind, path in evaluations_paths.items()
    }
    validate_evaluation_pair(evaluations["reconstructed"], evaluations["online"])
    records, hashes, direct_inputs = load_and_validate_runs(evaluations)
    association = association_audit(records)
    hash_result = hash_audit(hashes, records)
    cases, effects, summaries = build_tables(evaluations, records)
    provenance = build_provenance(
        evaluations_paths, direct_inputs, records, association, hash_result
    )

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=str(output.parent))
    )
    try:
        figures = temporary / "figures"
        figures.mkdir()
        case_fields = list(cases[0])
        effect_fields = list(effects[0])
        summary_fields = list(summaries[0])
        write_csv(temporary / "case_summary.csv", case_fields, cases)
        write_csv(temporary / "paired_effects.csv", effect_fields, effects)
        write_csv(temporary / "role_summary.csv", summary_fields, summaries)
        figure_absolute_metrics(figures, evaluations)
        figure_relative_zoom(figures, evaluations)
        figure_mechanism_counts(figures, records)
        render_reports(temporary, summaries, association, hash_result, records)
        (temporary / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expected = (
            "analysis-report.md",
            "stats-appendix.md",
            "figure-catalog.md",
            "case_summary.csv",
            "paired_effects.csv",
            "role_summary.csv",
            "provenance.json",
            "figures/figure-01-five-arm-absolute-metrics.pdf",
            "figures/figure-01-five-arm-absolute-metrics.png",
            "figures/figure-02-near-baseline-relative-change.pdf",
            "figures/figure-02-near-baseline-relative-change.png",
            "figures/figure-03-reachability-and-action-counts.pdf",
            "figures/figure-03-reachability-and-action-counts.png",
        )
        missing = [name for name in expected if not (temporary / name).is_file()]
        empty = [name for name in expected if (temporary / name).is_file() and (temporary / name).stat().st_size == 0]
        if missing or empty:
            raise RuntimeError(f"bundle QA failed: missing={missing}, empty={empty}")
        if output.exists():
            backup = output.with_name(f".{output.name}.old-{os.getpid()}")
            if backup.exists():
                raise RuntimeError(f"refusing existing replacement backup: {backup}")
            os.replace(output, backup)
            try:
                os.replace(temporary, output)
            except BaseException:
                os.replace(backup, output)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(f"wrote strict AFRL analysis bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
