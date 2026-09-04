#!/usr/bin/env python3
"""Build the frozen ORB-v23 A02 phase-aligned follow-up evidence bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
FORMAL_ROOT = DATA_ROOT / (
    "orbslam3_seeded_validation/postinit_candidate_search_20260804/"
    "aqualoc_a02_8520_9000/"
    "formal_n3_d14_min8_ignore0_preroll40_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)
DATASET = DATA_ROOT / "orbslam3_validation/aqualoc_a02_8520_9000/dataset"
SEED_ROOT = DATA_ROOT / (
    "orbslam3_seeded_validation/postinit_candidate_search_20260804/"
    "aqualoc_a02_8600_9000/assets_n3_d14_min8_ignore0"
)
SELECTOR_ROOT = DATA_ROOT / (
    "orbslam3_seeded_validation/multilineage/aqualoc_a02_8600_9000/"
    "n3_d14_min8_ignore0_20260804"
)
STATS = DATA_ROOT / "online_positive_search_20260721/a02_8600_9000/stats.csv"
DEFAULT_OUTPUT = WORKSPACE / "papers/orb_v23_a02_preroll_followup_20260804/analysis-output"
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_a06_followup_20260804/analysis-output/window_roster.csv"
)

ROLES = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
REPEATS = (1, 2, 3, 4)
EXPECTED_ORDERS = {
    1: "orb_only drop full_bridge_off full_unbounded full",
    2: "orb_only drop full_bridge_off full_unbounded full",
    3: "orb_only drop full_bridge_off full_unbounded full",
    4: "orb_only drop full_bridge_off full full_unbounded",
}
EXPECTED_HASHES = {
    "binary_sha256": "cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc",
    "liborbslam3_sha256": "05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8",
    "runner_sha256": "6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77",
}
COMMON_MANIFEST = {
    "seed_phase": "all",
    "seed_min_ok_frames": "0",
    "seed_audit_enabled": "1",
    "seed_audit_max_events": "131072",
    "external_lineage_bridge_requested": "1",
    "external_lineage_min_quality": "0.9",
    "external_lineage_max_projection_error_px": "4",
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
}
ROLE_MANIFEST = {
    "orb_only": ("1", "0", "0"),
    "drop": ("1", "0", "0"),
    "full_bridge_off": ("0", "0", "0"),
    "full_unbounded": ("1", "1", "0"),
    "full": ("1", "1", "1"),
}
CONSERVATION_FIELDS = (
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
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def validate_snapshot_manifests(runs: list[dict[str, Any]]) -> dict[str, Any]:
    expected_entries = {"orb_only": 28, **{role: 29 for role in ROLES if role != "orb_only"}}
    entries_by_run: dict[tuple[str, int], dict[str, str]] = {}
    snapshot_hashes_by_role: dict[str, set[str]] = defaultdict(set)
    total_entries = 0

    for run in runs:
        role = str(run["role"])
        repeat = int(run["repeat"])
        run_dir = Path(run["run_dir"])
        manifest = run["manifest"]
        snapshot = run_dir / "provenance/snapshot_sha256.txt"
        require_equal(
            manifest.get("provenance_manifest"),
            str(snapshot),
            f"{run_dir} provenance manifest path",
        )
        if not snapshot.is_file():
            raise RuntimeError(f"missing provenance snapshot: {snapshot}")
        snapshot_hash = sha256(snapshot)
        require_equal(
            manifest.get("provenance_manifest_sha256"),
            snapshot_hash,
            f"{run_dir} provenance manifest hash",
        )
        snapshot_hashes_by_role[role].add(snapshot_hash)

        entries: dict[str, str] = {}
        for line_number, line in enumerate(
            snapshot.read_text(encoding="ascii").splitlines(), start=1
        ):
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or len(parts[0]) != 64 or not parts[1].startswith("./"):
                raise RuntimeError(f"malformed snapshot line {snapshot}:{line_number}")
            expected_hash, relative = parts
            if relative in entries:
                raise RuntimeError(f"duplicate snapshot path {snapshot}:{relative}")
            artifact_path = (snapshot.parent / relative).resolve()
            if not artifact_path.is_file():
                raise RuntimeError(f"missing snapshot artifact: {artifact_path}")
            require_equal(
                sha256(artifact_path),
                expected_hash,
                f"{run_dir} snapshot artifact {relative}",
            )
            entries[relative] = expected_hash

        require_equal(
            len(entries),
            expected_entries[role],
            f"{run_dir} snapshot entry count",
        )
        if role == "orb_only":
            require_equal(
                manifest.get("seed_file"), "", f"{run_dir} native seed file"
            )
            require_equal(
                manifest.get("seed_sha256"), "", f"{run_dir} native seed hash"
            )
            require_equal(
                "./inputs/seeds.txt" in entries,
                False,
                f"{run_dir} native seed snapshot",
            )
        else:
            if not manifest.get("seed_file") or not manifest.get("seed_sha256"):
                raise RuntimeError(f"missing seeded provenance fields: {run_dir}")
            require_equal(
                entries.get("./inputs/seeds.txt"),
                manifest["seed_sha256"],
                f"{run_dir} seed snapshot hash",
            )

        entries_by_run[(role, repeat)] = entries
        total_entries += len(entries)

    common_paths = set.intersection(*(set(entries) for entries in entries_by_run.values()))
    require_equal(len(common_paths), 28, "snapshot common path count")
    for relative in sorted(common_paths):
        hashes = {entries[relative] for entries in entries_by_run.values()}
        require_equal(len(hashes), 1, f"snapshot common hash {relative}")

    union_paths = set.union(*(set(entries) for entries in entries_by_run.values()))
    require_equal(len(union_paths), 29, "snapshot union path count")
    require_equal(total_entries, 576, "snapshot total entry count")
    require_equal(
        {role: len(hashes) for role, hashes in snapshot_hashes_by_role.items()},
        {role: 1 for role in ROLES},
        "per-role snapshot hash determinism",
    )
    require_equal(
        len({value for hashes in snapshot_hashes_by_role.values() for value in hashes}),
        3,
        "snapshot content group count",
    )

    return {
        "snapshot_manifests": len(entries_by_run),
        "snapshot_manifests_verified": len(entries_by_run),
        "snapshot_entries": total_entries,
        "snapshot_entries_verified": total_entries,
        "snapshot_common_paths": len(common_paths),
        "snapshot_union_paths": len(union_paths),
        "snapshot_content_groups": 3,
        "snapshot_orb_only_runs_28_entries": sum(
            role == "orb_only" for role, _ in entries_by_run
        ),
        "snapshot_seeded_runs_29_entries": sum(
            role != "orb_only" for role, _ in entries_by_run
        ),
    }


def trajectory_path(run_dir: Path, manifest: dict[str, str], online: bool) -> Path:
    prefix = "online_f" if online else "f"
    return run_dir / f"{prefix}_{manifest['tag']}_{manifest['role']}_r{manifest['repeat']}.txt"


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{context}: expected {expected!r}, got {actual!r}")


def validate_run(role: str, repeat: int) -> dict[str, Any]:
    run_dir = FORMAL_ROOT / f"{role}_r{repeat}"
    manifest_path = run_dir / "run_manifest.txt"
    summary_path = run_dir / "instrumentation/seed_summary.json"
    if not manifest_path.is_file() or not summary_path.is_file():
        raise RuntimeError(f"missing formal artifacts: {run_dir}")
    manifest = parse_manifest(manifest_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    require_equal(manifest.get("role"), role, f"{run_dir} role")
    require_equal(manifest.get("repeat"), str(repeat), f"{run_dir} repeat")
    require_equal(manifest.get("role_order"), EXPECTED_ORDERS[repeat], f"{run_dir} order")
    for key, value in EXPECTED_HASHES.items():
        require_equal(manifest.get(key), value, f"{run_dir} {key}")
    for key, value in COMMON_MANIFEST.items():
        require_equal(manifest.get(key), value, f"{run_dir} {key}")
    bridge, purge, enforce = ROLE_MANIFEST[role]
    require_equal(manifest.get("external_lineage_bridge_enabled"), bridge, f"{run_dir} bridge")
    require_equal(manifest.get("external_lineage_pre_kf_outlier_purge"), purge, f"{run_dir} purge")
    require_equal(
        manifest.get("external_lineage_pre_kf_outlier_purge_enforce"),
        enforce,
        f"{run_dir} enforce",
    )

    require_equal(summary.get("complete"), True, f"{run_dir} complete")
    require_equal(summary.get("status"), "ok", f"{run_dir} status")
    require_equal(int(summary.get("events_overflowed", -1)), 0, f"{run_dir} event overflow")
    require_equal(
        int(summary.get("related_mappoint_overflowed", -1)),
        0,
        f"{run_dir} MapPoint overflow",
    )
    for field in CONSERVATION_FIELDS:
        require_equal(summary.get(field), True, f"{run_dir} {field}")

    reconstructed = trajectory_path(run_dir, manifest, online=False)
    online = trajectory_path(run_dir, manifest, online=True)
    if not reconstructed.is_file() or not online.is_file():
        raise RuntimeError(f"missing trajectories: {run_dir}")
    return {
        "role": role,
        "repeat": repeat,
        "run_dir": run_dir,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "summary": summary,
        "summary_path": summary_path,
        "reconstructed_sha256": sha256(reconstructed),
        "online_sha256": sha256(online),
    }


def validate_evaluation(kind: str) -> tuple[list[dict[str, str]], dict[str, dict[str, float]]]:
    path = FORMAL_ROOT / f"evaluation_{kind}.csv"
    rows = read_csv(path)
    require_equal(len(rows), 20, f"{kind} evaluation row count")
    by_key = {(row["role"], int(row["repeat"])): row for row in rows}
    require_equal(len(by_key), 20, f"{kind} unique evaluation rows")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for role in ROLES:
        for repeat in REPEATS:
            row = by_key.get((role, repeat))
            if row is None:
                raise RuntimeError(f"missing {kind} evaluation row: {role} r{repeat}")
            require_equal(row["status"], "ok", f"{kind} {role} r{repeat} status")
            require_equal(row["trajectory_kind"], kind, f"{kind} {role} r{repeat} kind")
            require_equal(int(row["input_frames"]), 233, f"{kind} {role} r{repeat} frames")
            require_equal(int(row["pre_init_accepted_seeds"]), 0, f"{kind} {role} r{repeat} pre-init")
            expected_post = 0 if role in {"orb_only", "drop"} else 375
            require_equal(
                int(row["post_init_accepted_seeds"]),
                expected_post,
                f"{kind} {role} r{repeat} post-init",
            )
            require_equal(int(row["instrumentation_overflowed"]), 0, f"{kind} {role} overflow")
            require_equal(int(row["instrumentation_conservation_ok"]), 1, f"{kind} {role} conservation")
            grouped[role].append(row)

    metrics: dict[str, dict[str, float]] = {}
    for role, role_rows in grouped.items():
        ape_values = [float(row["ape_rmse_m"]) for row in role_rows]
        rpe_values = [float(row["rpe_rmse_m"]) for row in role_rows]
        if len(set(ape_values)) != 1 or len(set(rpe_values)) != 1:
            raise RuntimeError(f"non-deterministic {kind} metrics for {role}")
        metrics[role] = {
            "ape": statistics.mean(ape_values),
            "rpe": statistics.mean(rpe_values),
            "poses": float(role_rows[0]["output_poses"]),
            "coverage": float(role_rows[0]["coverage_ratio"]),
        }
    return rows, metrics


def pct(candidate: float, reference: float) -> float:
    return (candidate / reference - 1.0) * 100.0


def artifact(name: str, path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"missing provenance artifact: {path}")
    return {"artifact": name, "sha256": sha256(path), "path": str(path.resolve())}


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        if not args.replace:
            raise SystemExit(f"output exists; pass --replace: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    runs = [validate_run(role, repeat) for repeat in REPEATS for role in ROLES]
    snapshot_checks = validate_snapshot_manifests(runs)
    for role in ROLES:
        role_runs = [run for run in runs if run["role"] == role]
        if len({run["reconstructed_sha256"] for run in role_runs}) != 1:
            raise RuntimeError(f"reconstructed trajectory hash mismatch: {role}")
        if len({run["online_sha256"] for run in role_runs}) != 1:
            raise RuntimeError(f"online trajectory hash mismatch: {role}")
        summary_signatures = {
            json.dumps(run["summary"], sort_keys=True).replace(str(run["summary"].get("output_directory")), "")
            for run in role_runs
        }
        if len(summary_signatures) != 1:
            # output_directory is the only run-specific summary field.
            normalized = []
            for run in role_runs:
                value = dict(run["summary"])
                value.pop("output_directory", None)
                normalized.append(json.dumps(value, sort_keys=True))
            if len(set(normalized)) != 1:
                raise RuntimeError(f"action counter mismatch: {role}")

    reconstructed_rows, reconstructed = validate_evaluation("reconstructed")
    online_rows, online = validate_evaluation("online")
    full_summary = next(run["summary"] for run in runs if run["role"] == "full")
    unbounded_summary = next(
        run["summary"] for run in runs if run["role"] == "full_unbounded"
    )

    seed_rows = [
        line.split()
        for line in (SEED_ROOT / "full_seeds.txt").read_text(encoding="ascii").splitlines()
        if line and not line.startswith("#")
    ]
    require_equal(len(seed_rows), 375, "seed row count")
    qualities = [float(row[4]) for row in seed_rows]
    seed_bearing_timestamps = len({int(row[0]) for row in seed_rows})
    require_equal(seed_bearing_timestamps, 185, "seed-bearing timestamp count")
    times = [int(line) for line in (DATASET / "cam0_times.txt").read_text().splitlines() if line]
    old_times = [int(line) for line in (SEED_ROOT / "feature_times.txt").read_text().splitlines() if line]
    require_equal(len(times), 233, "expanded image-time count")
    require_equal(len(old_times), 193, "seed image-time count")
    require_equal(times[40:], old_times, "40-frame prefix / original suffix")
    require_equal(sum(int(row[0]) < old_times[0] for row in seed_rows), 0, "prefix seed count")

    texture_rows = read_csv(STATS)
    grid = [float(row["base_grid_coverage"]) for row in texture_rows]
    tracks = [float(row["base_tracks"]) for row in texture_rows]
    low_grid = sum(value <= 0.80 for value in grid)
    require_equal(len(texture_rows), 193, "texture row count")
    require_equal(low_grid, 189, "low-grid frame count")

    rec_native = reconstructed["orb_only"]
    rec_full = reconstructed["full"]
    rec_unbounded = reconstructed["full_unbounded"]
    online_native = online["orb_only"]
    online_full = online["full"]
    online_unbounded = online["full_unbounded"]

    formal_summary = [{
        "window_id": "A02_8520_9000",
        "selector": "n3_d14_min8_ignore0_preroll40",
        "level": "action_positive_metric_mixed_phase_aligned_extension",
        "formal_runs_ok": "20/20",
        "post_init_accepted": "375/375",
        "map_point_lineages": int(full_summary["seed_lineages_with_mappoint"]),
        "distinct_mappoints": int(full_summary["distinct_mappoints"]),
        "assisted_matches": int(full_summary["lineage_assisted_matches_consumed"]),
        "assisted_outliers": int(full_summary["lineage_assisted_outliers_observed"]),
        "pre_kf_purged": f"{int(full_summary['lineage_pre_kf_assisted_outliers_purged'])}/{int(full_summary['lineage_pre_kf_assisted_outliers_observed'])}",
        "pre_kf_scans": int(full_summary["lineage_pre_kf_outlier_purge_scans"]),
        "unbounded_matches": int(unbounded_summary["lineage_assisted_matches_consumed"]),
        "unbounded_outliers": int(unbounded_summary["lineage_assisted_outliers_observed"]),
        "unbounded_pre_kf_observed": int(unbounded_summary["lineage_pre_kf_assisted_outliers_observed"]),
        "reconstructed_native_ape_m": f"{rec_native['ape']:.6f}",
        "reconstructed_native_rpe_m": f"{rec_native['rpe']:.6f}",
        "reconstructed_bridge_off_ape_m": f"{reconstructed['full_bridge_off']['ape']:.6f}",
        "reconstructed_bridge_off_rpe_m": f"{reconstructed['full_bridge_off']['rpe']:.6f}",
        "reconstructed_unbounded_ape_m": f"{rec_unbounded['ape']:.6f}",
        "reconstructed_unbounded_rpe_m": f"{rec_unbounded['rpe']:.6f}",
        "reconstructed_full_ape_m": f"{rec_full['ape']:.6f}",
        "reconstructed_full_rpe_m": f"{rec_full['rpe']:.6f}",
        "online_native_ape_m": f"{online_native['ape']:.6f}",
        "online_native_rpe_m": f"{online_native['rpe']:.6f}",
        "online_bridge_off_ape_m": f"{online['full_bridge_off']['ape']:.6f}",
        "online_bridge_off_rpe_m": f"{online['full_bridge_off']['rpe']:.6f}",
        "online_unbounded_ape_m": f"{online_unbounded['ape']:.6f}",
        "online_unbounded_rpe_m": f"{online_unbounded['rpe']:.6f}",
        "online_full_ape_m": f"{online_full['ape']:.6f}",
        "online_full_rpe_m": f"{online_full['rpe']:.6f}",
        "texture_profile": "operational_degraded_low_grid_not_sparse",
        "base_track_min": f"{min(tracks):.0f}",
        "base_track_mean": f"{statistics.mean(tracks):.6f}",
        "base_grid_min": f"{min(grid):.6f}",
        "base_grid_mean": f"{statistics.mean(grid):.6f}",
        "low_base_grid_action_frames": f"{low_grid}/193",
        "known_low_grid_full_window_lower_bound": f"{low_grid}/233",
        "seed_quality_min": f"{min(qualities):.9f}",
        "seed_quality_below_0p9": sum(value < 0.9 for value in qualities),
        "formal_root": str(FORMAL_ROOT),
    }]
    write_csv(output / "a02_preroll_formal_summary.csv", formal_summary)

    screening_rows = [
        {
            "candidate_id": "A03_5000_5400",
            "selector": "n3_d14_min8_ignore0",
            "attempted": 79,
            "pre_init_accepted": 59,
            "post_init_accepted": 18,
            "map_point_lineages": 0,
            "distinct_mappoints": 0,
            "assisted_matches": 0,
            "assisted_outliers": 0,
            "pre_kf_outliers": 0,
            "purged": 0,
            "decision": "exclude_mixed_phase_no_mappoint",
        },
        {
            "candidate_id": "A07_10800_11200",
            "selector": "n3_d14_min8_ignore0",
            "attempted": 263,
            "pre_init_accepted": 36,
            "post_init_accepted": 226,
            "map_point_lineages": 2,
            "distinct_mappoints": 8,
            "assisted_matches": 36,
            "assisted_outliers": 4,
            "pre_kf_outliers": 0,
            "purged": 0,
            "decision": "exclude_mixed_phase_action_null",
        },
        {
            "candidate_id": "A10_400_800_n3",
            "selector": "n3_d14_min8_ignore0",
            "attempted": 115,
            "pre_init_accepted": 0,
            "post_init_accepted": 115,
            "map_point_lineages": 3,
            "distinct_mappoints": 8,
            "assisted_matches": 43,
            "assisted_outliers": 2,
            "pre_kf_outliers": 0,
            "purged": 0,
            "decision": "existing_window_action_null_selector_variant",
        },
        {
            "candidate_id": "AFRL_Bus_s320_d20",
            "selector": "n3_d14_min8_ignore0",
            "attempted": 234,
            "pre_init_accepted": 195,
            "post_init_accepted": 39,
            "map_point_lineages": 1,
            "distinct_mappoints": 1,
            "assisted_matches": 16,
            "assisted_outliers": 0,
            "pre_kf_outliers": 0,
            "purged": 0,
            "decision": "exclude_mixed_phase_action_null",
        },
        {
            "candidate_id": "A02_8600_9000",
            "selector": "n3_d14_min8_ignore0",
            "attempted": 375,
            "pre_init_accepted": 21,
            "post_init_accepted": 354,
            "map_point_lineages": 2,
            "distinct_mappoints": 8,
            "assisted_matches": 261,
            "assisted_outliers": 17,
            "pre_kf_outliers": 12,
            "purged": 12,
            "decision": "same_cluster_precursor_exclude_mixed_phase",
        },
        {
            "candidate_id": "A02_8520_9000",
            "selector": "n3_d14_min8_ignore0_preroll40",
            "attempted": 375,
            "pre_init_accepted": 0,
            "post_init_accepted": 375,
            "map_point_lineages": int(full_summary["seed_lineages_with_mappoint"]),
            "distinct_mappoints": int(full_summary["distinct_mappoints"]),
            "assisted_matches": int(full_summary["lineage_assisted_matches_consumed"]),
            "assisted_outliers": int(full_summary["lineage_assisted_outliers_observed"]),
            "pre_kf_outliers": int(full_summary["lineage_pre_kf_assisted_outliers_observed"]),
            "purged": int(full_summary["lineage_pre_kf_assisted_outliers_purged"]),
            "decision": "promote_action_positive_metric_mixed_phase_aligned_extension",
        },
    ]
    write_csv(output / "screening_summary.csv", screening_rows)

    roster = read_csv(PRIOR_ROSTER)
    if any(row["window_id"] == "A02_8520_9000" for row in roster):
        raise RuntimeError("A02 expanded window already present in prior roster")
    roster.append({
        "window_id": "A02_8520_9000",
        "dataset": "AQUALOC",
        "sequence": "A02",
        "window": "8520-9000",
        "level": "action_positive_metric_mixed_phase_aligned_extension",
        "independent_window": "true",
        "primary_selector": "n3_d14_min8_ignore0_preroll40",
        "accepted_post_init": "375/375",
        "seed_lineages_with_mappoint": str(full_summary["seed_lineages_with_mappoint"]),
        "assisted_matches": str(full_summary["lineage_assisted_matches_consumed"]),
        "assisted_outliers": str(full_summary["lineage_assisted_outliers_observed"]),
        "pre_kf_purged": f"{full_summary['lineage_pre_kf_assisted_outliers_purged']}/{full_summary['lineage_pre_kf_assisted_outliers_observed']}",
        "texture_profile": "operational degraded/low-grid; 40-frame unseeded prefix",
        "base_klt_profile": "350 saturated in 193-frame action region",
        "operational_low_texture": "true",
        "sparse_base_klt_low_texture": "false",
        "source_report": "logs/orb_v23_a02_preroll_action_search_20260804.md",
        "formal_root": str(FORMAL_ROOT),
    })
    require_equal(len(roster), 10, "updated roster size")
    require_equal(sum(row["operational_low_texture"] == "true" for row in roster), 5, "low-grid roster count")
    require_equal(sum(row["sparse_base_klt_low_texture"] == "true" for row in roster), 0, "sparse roster count")
    write_csv(output / "window_roster.csv", roster)

    provenance = [
        artifact(
            "orb_binary",
            Path("/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/Examples_old/Monocular/mono_euroc_old"),
        ),
        artifact(
            "orb_library",
            Path("/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage/lib/libORB_SLAM3.so"),
        ),
        artifact("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        artifact("aqualoc_camera_config", DATA_ROOT / "logs/orbslam3_validation/aqualoc_archaeo_mono.yaml"),
        artifact("a02_full_bag", DATA_ROOT / "datasets/aqualoc/full_bags/archaeo_sequence_2/archaeo_sequence_2.bag"),
        artifact("a02_dataset_metadata", DATASET / "export_metadata.json"),
        artifact("a02_dataset_times", DATASET / "cam0_times.txt"),
        artifact("a02_dataset_groundtruth", DATASET / "groundtruth_tum.txt"),
        artifact("a02_selector_manifest", SELECTOR_ROOT / "manifest.txt"),
        artifact("a02_seed_file", SEED_ROOT / "full_seeds.txt"),
        artifact("a02_action_stats", STATS),
        artifact("a02_evaluation_reconstructed", FORMAL_ROOT / "evaluation_reconstructed.csv"),
        artifact("a02_evaluation_online", FORMAL_ROOT / "evaluation_online.csv"),
        artifact("dataset_exporter", WORKSPACE / "scripts/prepare_orbslam3_euroc_segment.py"),
        artifact("groundtruth_converter", WORKSPACE / "scripts/convert_indexed_groundtruth_to_tum.py"),
    ]
    write_csv(output / "provenance.csv", provenance)

    checks = {
        "schema_version": 2,
        "formal_runs": 20,
        "formal_runs_ok": 20,
        "role_counter_signatures": {role: 1 for role in ROLES},
        "role_reconstructed_hashes": {role: 1 for role in ROLES},
        "role_online_hashes": {role: 1 for role in ROLES},
        "repeat4_order_swapped": True,
        "prefix_frames": 40,
        "expanded_frames": 233,
        "original_action_frames": 193,
        "original_feature_timeline_frames": 193,
        "seed_bearing_timestamps": seed_bearing_timestamps,
        "original_times_exact_suffix": True,
        "prefix_seed_rows": 0,
        "action_positive": True,
        "metric_class": "metric_mixed",
        "project_strict": False,
        "all_control_strict": False,
        "updated_action_positive_windows": 10,
        "updated_project_strict_windows": 4,
        "updated_all_control_strict_windows": 2,
        "updated_operational_low_grid_windows": 5,
        "updated_sparse_base_klt_windows": 0,
        "provenance_artifacts": len(provenance),
        "provenance_artifacts_hashed": len(provenance),
        **snapshot_checks,
    }
    (output / "validation_summary.json").write_text(
        json.dumps(checks, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )

    report = f"""# ORB-SLAM3 v23 A02 phase-aligned follow-up

Date: 2026-08-04

## Decision

AQUALOC A02 `8520-9000` is a new fixed-interval frozen-v23
mechanism/action-positive window. It is a phase-aligned extension of the
excluded mixed-phase `8600-9000` precursor and counts once for this time
cluster. Its trajectory result is metric-mixed, not project strict.

The expanded input adds 40 unseeded 10 Hz native frames before the exact
193-frame `8600-9000` suffix. The 375 seed rows, their timestamps, qualities,
selector, and SHA-256 remain unchanged. All 375 observations were accepted
post-initialization.

## Frozen contract and determinism

- binary SHA-256: `{EXPECTED_HASHES['binary_sha256']}`
- library SHA-256: `{EXPECTED_HASHES['liborbslam3_sha256']}`
- runner SHA-256: `{EXPECTED_HASHES['runner_sha256']}`
- bridge gate `q >= 0.9`, projection `4 px`, Hamming `100`
- seed phase `all`, minimum consecutive OK frames `0`
- CPU2, LocalMapping and LoopClosing barriers, deterministic background gate,
  ASLR disabled, audit capacity 131072, online trajectory export enabled
- pre-KF purge enabled and enforced only in `full`
- APE/RPE: Sim(3)-aligned translation, association `0.06 s`, RPE delta `1`

All 20 formal runs completed with status `ok`. Per-role action counters and
both trajectory hashes were identical across four repeats. Repeat 4 swapped
`full` and `full_unbounded`. No overflow or conservation failure occurred.

All 20 provenance manifests passed their role-aware contract: four native
`orb_only` snapshots contain 28 entries because their seed path and seed hash
are empty, while the 16 seeded snapshots contain 29 entries. All `576/576`
listed artifacts exist and match their SHA-256; the 28 common frozen paths are
identical across every run, and the manifests form only the three expected
native, drop, and full-family content groups.

## Formal action

| Role | Post-init | MapPoint lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 375 | 2 / 8 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 375 | {unbounded_summary['seed_lineages_with_mappoint']} / {unbounded_summary['distinct_mappoints']} | {unbounded_summary['lineage_assisted_matches_consumed']} | {unbounded_summary['lineage_assisted_outliers_observed']} | {unbounded_summary['lineage_pre_kf_assisted_outliers_observed']} / 0 | {unbounded_summary['lineage_pre_kf_outlier_purge_scans']} |
| Frozen v23 | 375 | {full_summary['seed_lineages_with_mappoint']} / {full_summary['distinct_mappoints']} | {full_summary['lineage_assisted_matches_consumed']} | {full_summary['lineage_assisted_outliers_observed']} | {full_summary['lineage_pre_kf_assisted_outliers_observed']} / {full_summary['lineage_pre_kf_assisted_outliers_purged']} | {full_summary['lineage_pre_kf_outlier_purge_scans']} |

## Formal metrics

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `{rec_native['ape']:.6f} / {rec_native['rpe']:.6f}` | `{online_native['ape']:.6f} / {online_native['rpe']:.6f}` |
| Empty drop | `{reconstructed['drop']['ape']:.6f} / {reconstructed['drop']['rpe']:.6f}` | `{online['drop']['ape']:.6f} / {online['drop']['rpe']:.6f}` |
| Bridge off | `{reconstructed['full_bridge_off']['ape']:.6f} / {reconstructed['full_bridge_off']['rpe']:.6f}` | `{online['full_bridge_off']['ape']:.6f} / {online['full_bridge_off']['rpe']:.6f}` |
| Unbounded | `{rec_unbounded['ape']:.6f} / {rec_unbounded['rpe']:.6f}` | `{online_unbounded['ape']:.6f} / {online_unbounded['rpe']:.6f}` |
| Frozen v23 | `{rec_full['ape']:.6f} / {rec_full['rpe']:.6f}` | `{online_full['ape']:.6f} / {online_full['rpe']:.6f}` |

Relative to native/drop, v23 changes reconstructed APE/RPE by
`{pct(rec_full['ape'], rec_native['ape']):+.3f}% / {pct(rec_full['rpe'], rec_native['rpe']):+.3f}%`
and online APE/RPE by
`{pct(online_full['ape'], online_native['ape']):+.3f}% / {pct(online_full['rpe'], online_native['rpe']):+.3f}%`.
Relative to unbounded, all four v23 metrics improve:
`{pct(rec_full['ape'], rec_unbounded['ape']):+.3f}% / {pct(rec_full['rpe'], rec_unbounded['rpe']):+.3f}%`
reconstructed and
`{pct(online_full['ape'], online_unbounded['ape']):+.3f}% / {pct(online_full['rpe'], online_unbounded['rpe']):+.3f}%`
online.

Reconstructed APE still worsens relative to native, so the classification is
action-positive and metric-mixed. It is not project strict or all-control
strict.

## Texture classification

The 193-frame action region has base KLT `350/350` in every frame, grid
coverage min/mean `{min(grid):.6f}/{statistics.mean(grid):.6f}`, and
`{low_grid}/193` frames at grid `<= 0.80`. Even treating all 40 unseeded prefix
frames as non-low, the full-window lower bound is `{low_grid}/233 = {100 * low_grid / 233:.1f}%`.

The window is operational degraded/low-grid, but not sparse base-KLT in the
action region.

## Updated denominator

- mechanism/action-positive: `10`
- project strict: `4`
- all-control repeatwise strict: `2`
- operational degraded/low-grid among all positives: `5/10 = 50%`
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/10`

## Claim boundary

- Count `8520-9000` once; do not also count the overlapping excluded
  `8600-9000` precursor.
- Keep the deterministic purge action and online improvement.
- Do not claim reconstructed APE improvement, project-strict status, or sparse
  base-KLT behavior.
- Treat the 40-frame prefix as phase alignment for the fixed interval, not as
  a selector, threshold, seed, or v23 change.

No ORB source, v23 threshold, binary, library, runner, seed row, or selector
parameter was changed.
"""
    (output / "analysis-report.md").write_text(report, encoding="ascii")

    # Keep evaluator rows in the bundle without duplicating the large report files.
    write_csv(output / "evaluation_reconstructed.csv", reconstructed_rows)
    write_csv(output / "evaluation_online.csv", online_rows)
    print(f"wrote A02 phase-aligned evidence bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
