#!/usr/bin/env python3
"""Build a strict, provenance-complete bundle for the post-init ORB-v23 search."""

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
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from evo.core import sync
    from evo.tools import file_interface
except ImportError as exc:  # pragma: no cover - the project evaluator supplies evo
    raise SystemExit("evo is required to build this analysis bundle") from exc


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DEFAULT_MANIFEST = WORKSPACE / "papers/orb_v23_postinit_action_search_20260731/manifest.json"
DEFAULT_OUTPUT = WORKSPACE / "papers/orb_v23_postinit_action_search_20260731/analysis-output"
ROLES = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
REPEATS = (1, 2, 3, 4)
TRAJECTORY_KINDS = ("reconstructed", "online")
METRICS = ("ape_rmse_m", "rpe_rmse_m")
METRIC_LABEL = {"ape_rmse_m": "APE RMSE (m)", "rpe_rmse_m": "RPE RMSE (m)"}
ROLE_LABEL = {
    "orb_only": "Native ORB",
    "drop": "Empty drop",
    "full_bridge_off": "Bridge off",
    "full_unbounded": "Unbounded",
    "full": "v23",
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
ROLE_HATCH = {"orb_only": "", "drop": "//", "full_bridge_off": "xx", "full_unbounded": "..", "full": "\\\\"}
EXPECTED_ROLE_ORDER = {
    1: "orb_only drop full_bridge_off full_unbounded full",
    2: "orb_only drop full_bridge_off full_unbounded full",
    3: "orb_only drop full_bridge_off full_unbounded full",
    4: "orb_only drop full_bridge_off full full_unbounded",
}
# These values are part of the frozen runner contract.  Keep the effective
# role-specific switches separate below; requested values must stay constant
# even when a control arm disables the corresponding mechanism.
COMMON_MANIFEST_VALUES = {
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
}
ROLE_MANIFEST_VALUES = {
    "orb_only": {
        "external_lineage_bridge_enabled": "1",
        "external_lineage_pre_kf_outlier_purge": "0",
        "external_lineage_pre_kf_outlier_purge_enforce": "0",
    },
    "drop": {
        "external_lineage_bridge_enabled": "1",
        "external_lineage_pre_kf_outlier_purge": "0",
        "external_lineage_pre_kf_outlier_purge_enforce": "0",
    },
    "full_bridge_off": {
        "external_lineage_bridge_enabled": "0",
        "external_lineage_pre_kf_outlier_purge": "0",
        "external_lineage_pre_kf_outlier_purge_enforce": "0",
    },
    "full_unbounded": {
        "external_lineage_bridge_enabled": "1",
        "external_lineage_pre_kf_outlier_purge": "1",
        "external_lineage_pre_kf_outlier_purge_enforce": "0",
    },
    "full": {
        "external_lineage_bridge_enabled": "1",
        "external_lineage_pre_kf_outlier_purge": "1",
        "external_lineage_pre_kf_outlier_purge_enforce": "1",
    },
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
PDF_METADATA = {
    "Creator": "AQUA-FE strict ORB-v23 post-init analysis builder",
    "CreationDate": datetime(2026, 8, 1, tzinfo=timezone.utc),
    "ModDate": datetime(2026, 8, 1, tzinfo=timezone.utc),
}
PNG_METADATA = {"Software": "AQUA-FE strict ORB-v23 post-init analysis builder"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty table: {path}")
    fields = list(rows[0])
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path, cache: dict[str, str] | None = None) -> str:
    key = str(path.resolve())
    if cache is not None and key in cache:
        return cache[key]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    if cache is not None:
        cache[key] = value
    return value


def artifact(path: Path, cache: dict[str, str] | None = None) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"missing artifact: {path}")
    return {"path": str(path), "sha256": sha256(path, cache), "bytes": path.stat().st_size}


def parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def parse_metric_report(path: Path, metric: str | None = None, delta: int | None = None) -> float:
    text = path.read_text(encoding="ascii")
    if metric == "ape_rmse_m":
        required_headers = (
            "APE w.r.t. translation part (m)",
            "(with Sim (3) Umeyama alignment)",
        )
    elif metric == "rpe_rmse_m":
        if delta is None:
            raise RuntimeError(f"RPE validation requires a delta: {path}")
        required_headers = (
            "RPE w.r.t. translation part (m)",
            f"for delta = {delta} (frames) using all pairs",
            "(with Sim (3) Umeyama alignment)",
        )
    else:
        required_headers = ()
    for header in required_headers:
        if header not in text:
            raise RuntimeError(f"evaluator protocol header missing from {path}: {header!r}")
    match = re.search(r"^\s*rmse\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"missing rmse in {path}")
    value = float(match.group(1))
    if not math.isfinite(value) or value < 0:
        raise RuntimeError(f"invalid rmse in {path}")
    return value


def as_int(data: dict[str, Any], key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid integer field {key}") from exc


def truthy(value: Any) -> bool:
    return value is True or value == 1 or value == "1"


def validate_snapshot(path: Path, cache: dict[str, str]) -> int:
    root = path.parent.resolve()
    count = 0
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError(f"unsafe snapshot path: {relative}")
        candidate = (root / rel).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise RuntimeError(f"missing snapshot entry: {candidate}")
        if sha256(candidate, cache) != expected:
            raise RuntimeError(f"snapshot hash mismatch: {candidate}")
        count += 1
    if count == 0:
        raise RuntimeError(f"empty snapshot manifest: {path}")
    return count


def trajectory_path(run_dir: Path, kind: str, sec: bool = False) -> Path:
    prefix = "online_f_" if kind == "online" else "f_"
    candidates = []
    for path in run_dir.glob(f"{prefix}*.txt"):
        if path.name.endswith("_sec.txt") or path.name.startswith("kf_"):
            continue
        candidates.append(path)
    if len(candidates) != 1:
        raise RuntimeError(f"expected one {kind} trajectory in {run_dir}, got {candidates}")
    if not sec:
        return candidates[0]
    sec_path = candidates[0].with_name(candidates[0].stem + "_sec.txt")
    if not sec_path.is_file():
        raise RuntimeError(f"missing evaluator trajectory: {sec_path}")
    return sec_path


def keyframe_path(run_dir: Path) -> Path:
    paths = [p for p in run_dir.glob("kf_*.txt") if not p.name.endswith("_sec.txt")]
    if len(paths) != 1:
        raise RuntimeError(f"expected one keyframe trajectory in {run_dir}, got {paths}")
    return paths[0]


def _csv_data_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(f"missing instrumentation artifact: {path}")
    return read_csv(path)


def validate_summary(path: Path, run_dir: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("complete") is not True or data.get("status") != "ok":
        raise RuntimeError(f"incomplete seed summary: {path}")
    if data.get("schema_version") != 1:
        raise RuntimeError(f"unsupported seed summary schema: {path}")
    for field in ("events_overflowed", "related_mappoint_overflowed"):
        if as_int(data, field) != 0:
            raise RuntimeError(f"{path}: {field} is nonzero")
    for field in CONSERVATION_FIELDS:
        if not truthy(data.get(field)):
            raise RuntimeError(f"{path}: {field} is false")
    output_directory = Path(str(data.get("output_directory", "")))
    expected_directory = (run_dir / "instrumentation").resolve()
    # The runner preserves a runtime-slot instrumentation directory in the
    # JSON while copying the auditable CSVs into the stable run directory.
    # Accept both locations and validate both when present.
    if not output_directory.is_dir() or not expected_directory.is_dir():
        raise RuntimeError(
            f"instrumentation output_directory mismatch: {path}; "
            f"json={output_directory.resolve()} expected={expected_directory}"
        )

    # Recheck the duplicate counters and the conservation equations here,
    # rather than trusting the boolean flags emitted by the executable.
    duplicate_pairs = (
        ("loaded_seed_observations", "loaded_seed_rows"),
        ("attempted_seed_observations", "phase_attempted"),
        ("accepted_seed_observations", "extractor_accepted"),
        ("seed_lineages_loaded", "lineages"),
        ("distinct_mappoints", "related_mappoints"),
    )
    for summary_field, diagnostic_field in duplicate_pairs:
        if as_int(data, summary_field) != as_int(data, diagnostic_field):
            raise RuntimeError(
                f"{path}: duplicate counters disagree: {summary_field}="
                f"{data[summary_field]} {diagnostic_field}={data[diagnostic_field]}"
            )
    equations = {
        "phase_conservation": as_int(data, "loaded_seed_rows")
        == as_int(data, "phase_attempted") + as_int(data, "phase_skipped"),
        "extractor_conservation": as_int(data, "phase_attempted")
        == as_int(data, "extractor_accepted")
        + as_int(data, "extractor_rejected_border")
        + as_int(data, "extractor_rejected_native_duplicate")
        + as_int(data, "extractor_rejected_seed_duplicate"),
        "accepted_conservation": as_int(data, "extractor_accepted")
        == as_int(data, "frame_accepted"),
    }
    for field, result in equations.items():
        if not result:
            raise RuntimeError(f"{path}: {field} disagrees with counters")
    if as_int(data, "events_recorded") > as_int(data, "event_capacity"):
        raise RuntimeError(f"{path}: events_recorded exceeds event_capacity")
    if as_int(data, "related_mappoints") > as_int(data, "related_mappoint_capacity"):
        raise RuntimeError(f"{path}: related_mappoints exceeds capacity")
    run_dir = run_dir.resolve()
    event_rows = _csv_data_rows(run_dir / "instrumentation" / "seed_events.csv")
    lineage_rows = _csv_data_rows(run_dir / "instrumentation" / "seed_lineages.csv")
    mappoint_rows = _csv_data_rows(run_dir / "instrumentation" / "seed_mappoint_summary.csv")
    if len(event_rows) != as_int(data, "events_recorded"):
        raise RuntimeError(f"{path}: seed_events row count disagrees with events_recorded")
    if len(lineage_rows) != as_int(data, "lineages"):
        raise RuntimeError(f"{path}: seed_lineages row count disagrees with lineages")
    if len(mappoint_rows) != as_int(data, "related_mappoints"):
        raise RuntimeError(f"{path}: seed_mappoint_summary row count disagrees with related_mappoints")
    return data


def validate_run_log(run_dir: Path, summary: dict[str, Any]) -> dict[str, int]:
    """Cross-check executable seed totals and phase totals against JSON."""
    log_path = run_dir / "orbslam3_run.log"
    if not log_path.is_file():
        raise RuntimeError(f"missing executable log: {log_path}")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    seed_matches = re.findall(
        r"External seed summary: frames=(\d+) attempted=(\d+) accepted=(\d+)", text
    )
    if len(seed_matches) != 1:
        raise RuntimeError(f"expected one external seed summary in {log_path}")
    frames, attempted, accepted = (int(value) for value in seed_matches[0])
    if (
        frames != as_int(summary, "loaded_seed_observations")
        or attempted != as_int(summary, "attempted_seed_observations")
        or accepted != as_int(summary, "accepted_seed_observations")
    ):
        raise RuntimeError(f"instrumentation/log seed counters disagree: {log_path}")
    phase_matches = re.findall(
        r"External seed phase summary: phase=(\w+)"
        r" pre_attempted=(\d+) pre_accepted=(\d+)"
        r" post_attempted=(\d+) post_accepted=(\d+) phase_skipped=(\d+)",
        text,
    )
    if len(phase_matches) != 1:
        raise RuntimeError(f"expected one external seed phase summary in {log_path}")
    phase, pre_attempted, pre_accepted, post_attempted, post_accepted, skipped = phase_matches[0]
    expected_phase = summary.get("seed_phase", "")
    if expected_phase and phase != expected_phase:
        raise RuntimeError(f"instrumentation/log seed phase disagrees: {log_path}")
    phase_values = {
        "pre_init_attempted_seeds": int(pre_attempted),
        "pre_init_accepted_seeds": int(pre_accepted),
        "post_init_attempted_seeds": int(post_attempted),
        "post_init_accepted_seeds": int(post_accepted),
        "phase_skipped_seeds": int(skipped),
    }
    # The summary stores the same phase fields only when the runner/evaluator
    # has propagated them; require equality when present and always enforce the
    # aggregate identities against the JSON counters.
    for field, value in phase_values.items():
        if field in summary and summary[field] not in (None, "") and as_int(summary, field) != value:
            raise RuntimeError(f"instrumentation/log {field} disagrees: {log_path}")
    if int(pre_attempted) + int(post_attempted) + int(skipped) != attempted:
        raise RuntimeError(f"phase totals do not conserve attempted seeds: {log_path}")
    if int(pre_accepted) + int(post_accepted) != accepted:
        raise RuntimeError(f"phase totals do not conserve accepted seeds: {log_path}")
    return {"frames": frames, "attempted": attempted, "accepted": accepted, **phase_values}


def expected_seed_hash(role: str, manifest: dict[str, str], cache: dict[str, str]) -> str:
    seed_file = manifest.get("seed_file", "")
    if role == "orb_only":
        if seed_file or manifest.get("seed_sha256", ""):
            raise RuntimeError("native ORB unexpectedly has a seed file")
        return ""
    if not seed_file:
        raise RuntimeError(f"{role} has no seed file")
    path = Path(seed_file)
    if not path.is_file():
        raise RuntimeError(f"missing seed file: {path}")
    return sha256(path, cache)


def seed_quality_audit(seed_file: str, threshold: float) -> dict[str, Any]:
    """Read the frozen seed asset's quality column and retain any protocol warning."""
    if not seed_file:
        return {
            "path": "",
            "rows": 0,
            "min_quality": "",
            "below_threshold": 0,
            "threshold": threshold,
            "warning": "",
        }
    path = Path(seed_file)
    if not path.is_file():
        raise RuntimeError(f"missing seed file for quality audit: {path}")
    qualities: list[float] = []
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 5:
            raise RuntimeError(f"seed row has fewer than five columns at {path}:{line_number}")
        try:
            value = float(fields[4])
        except ValueError as exc:
            raise RuntimeError(f"invalid seed quality at {path}:{line_number}") from exc
        if not math.isfinite(value):
            raise RuntimeError(f"non-finite seed quality at {path}:{line_number}")
        qualities.append(value)
    minimum = min(qualities) if qualities else None
    below = sum(value < threshold for value in qualities)
    warning = ""
    if below:
        warning = (
            f"{below} seed row(s) have quality below the configured "
            f"q>={threshold:g} threshold (minimum={minimum:.9f}); "
            "the extractor does not enforce this quality gate."
        )
    return {
        "path": str(path.resolve()),
        "rows": len(qualities),
        "min_quality": "" if minimum is None else f"{minimum:.9f}",
        "below_threshold": below,
        "threshold": threshold,
        "warning": warning,
    }


def validate_manifest_contract(
    manifest: dict[str, str], role: str, repeat: int, contract: dict[str, str], cache: dict[str, str], expected_order: str | None = None
) -> None:
    if manifest.get("role") != role or manifest.get("repeat") != str(repeat):
        raise RuntimeError(f"manifest identity mismatch for {role}_r{repeat}")
    if manifest.get("role_order") != (expected_order or EXPECTED_ROLE_ORDER[repeat]):
        raise RuntimeError(f"role order mismatch for {role}_r{repeat}")
    expected_values = {**COMMON_MANIFEST_VALUES, **ROLE_MANIFEST_VALUES[role]}
    for field, expected in expected_values.items():
        if manifest.get(field) != expected:
            raise RuntimeError(
                f"manifest contract mismatch for {role}_r{repeat}: "
                f"{field}={manifest.get(field)!r}, expected {expected!r}"
            )
    fields = (
        "binary_sha256",
        "liborbslam3_sha256",
        "runner_sha256",
        "external_seed_audit_source_sha256",
        "config_sha256",
        "times_sha256",
    )
    for field in fields:
        value = manifest.get(field, "")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise RuntimeError(f"missing frozen hash {field} for {role}_r{repeat}")
        if field in contract and contract[field] != value:
            raise RuntimeError(f"frozen {field} differs across runs")
        contract.setdefault(field, value)
    expected_seed = expected_seed_hash(role, manifest, cache)
    if manifest.get("seed_sha256", "") != expected_seed:
        raise RuntimeError(f"seed hash mismatch for {role}_r{repeat}")
    for path_key in ("dataset_dir", "times_file", "config", "binary", "liborbslam3_path", "external_seed_audit_source_path"):
        path_value = manifest.get(path_key, "")
        if path_value and not Path(path_value).is_file() and path_key != "dataset_dir":
            raise RuntimeError(f"missing manifest path {path_key}: {path_value}")
    dataset = Path(manifest.get("dataset_dir", ""))
    if not dataset.is_dir() or not (dataset / "groundtruth_tum.txt").is_file():
        raise RuntimeError(f"invalid dataset directory: {dataset}")
    if sha256(Path(manifest["config"]), cache) != manifest["config_sha256"]:
        raise RuntimeError(f"config hash mismatch for {role}_r{repeat}")
    if sha256(Path(manifest["times_file"]), cache) != manifest["times_sha256"]:
        raise RuntimeError(f"times hash mismatch for {role}_r{repeat}")
    for key, path_key in (
        ("binary_sha256", "binary"),
        ("liborbslam3_sha256", "liborbslam3_path"),
        ("external_seed_audit_source_sha256", "external_seed_audit_source_path"),
    ):
        if sha256(Path(manifest[path_key]), cache) != manifest[key]:
            raise RuntimeError(f"{path_key} hash mismatch for {role}_r{repeat}")
    runner = WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"
    if sha256(runner, cache) != manifest["runner_sha256"]:
        raise RuntimeError("runner hash does not match the frozen manifest")


def validate_run(
    run_dir: Path,
    role: str,
    repeat: int,
    contract: dict[str, str],
    cache: dict[str, str],
    expected_order: str | None = None,
    require_sec: bool = True,
) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise RuntimeError(f"missing run directory: {run_dir}")
    manifest_path = run_dir / "run_manifest.txt"
    snapshot_path = run_dir / "provenance/snapshot_sha256.txt"
    summary_path = run_dir / "instrumentation/seed_summary.json"
    manifest = parse_manifest(manifest_path)
    validate_manifest_contract(manifest, role, repeat, contract, cache, expected_order)
    if manifest.get("provenance_manifest_sha256") != sha256(snapshot_path, cache):
        raise RuntimeError(f"provenance manifest hash mismatch: {run_dir}")
    snapshot_entries = validate_snapshot(snapshot_path, cache)
    summary = validate_summary(summary_path, run_dir)
    log_path = run_dir / "orbslam3_run.log"
    log_counters = validate_run_log(run_dir, summary)
    trajectories = {kind: trajectory_path(run_dir, kind) for kind in TRAJECTORY_KINDS}
    trajectory_secs = {}
    for kind in TRAJECTORY_KINDS:
        if require_sec:
            trajectory_secs[kind] = trajectory_path(run_dir, kind, sec=True)
        else:
            raw_path = trajectories[kind]
            sec_path = raw_path.with_name(raw_path.stem + "_sec.txt")
            trajectory_secs[kind] = sec_path if sec_path.is_file() else raw_path
    keyframe = keyframe_path(run_dir)
    for path in (*trajectories.values(), *trajectory_secs.values(), keyframe):
        if not any(line.strip() for line in path.read_text(encoding="ascii").splitlines()):
            raise RuntimeError(f"empty trajectory artifact: {path}")
    instrumentation = {
        name: artifact(run_dir / "instrumentation" / name, cache)
        for name in ("seed_events.csv", "seed_lineages.csv", "seed_mappoint_summary.csv")
    }
    return {
        "run_dir": str(run_dir.resolve()),
        "manifest": manifest,
        "manifest_artifact": artifact(manifest_path, cache),
        "snapshot_artifact": artifact(snapshot_path, cache),
        "snapshot_entries": snapshot_entries,
        "summary": summary,
        "summary_artifact": artifact(summary_path, cache),
        "log_counters": log_counters,
        "run_log_artifact": artifact(log_path, cache),
        "instrumentation_artifacts": instrumentation,
        "trajectories": {kind: artifact(path, cache) for kind, path in trajectories.items()},
        "trajectory_secs": {kind: artifact(path, cache) for kind, path in trajectory_secs.items()},
        "keyframe_artifact": artifact(keyframe, cache),
    }


def report_path(run_dir: Path, kind: str, metric: str, delta: int) -> Path:
    prefix = "online_" if kind == "online" else ""
    filename = f"{prefix}ape_trans.txt" if metric == "ape_rmse_m" else f"{prefix}rpe_trans_{delta}f.txt"
    return run_dir / filename


def validate_evaluation_rows(rows: list[dict[str, str]], kind: str) -> dict[tuple[str, int], dict[str, str]]:
    expected = {(role, repeat) for role in ROLES for repeat in REPEATS}
    actual = {(row.get("role", ""), int(row.get("repeat", "-1"))) for row in rows}
    if actual != expected or len(rows) != len(expected):
        raise RuntimeError(f"{kind}: incomplete role/repeat grid")
    lookup: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        key = (row["role"], int(row["repeat"]))
        if row.get("trajectory_kind") != kind or row.get("status") != "ok" or row.get("complete") != "1":
            raise RuntimeError(f"{kind}:{key}: incomplete evaluation")
        for field in ("ape_rmse_m", "rpe_rmse_m", "coverage_ratio"):
            value = float(row[field])
            if not math.isfinite(value) or value < 0:
                raise RuntimeError(f"{kind}:{key}: invalid {field}")
        if not 0 <= float(row["coverage_ratio"]) <= 1 or int(row["output_poses"]) <= 0:
            raise RuntimeError(f"{kind}:{key}: invalid coverage/output")
        if row.get("instrumentation_overflowed") != "0" or row.get("instrumentation_conservation_ok") != "1":
            raise RuntimeError(f"{kind}:{key}: instrumentation failure")
        lookup[key] = row
    return lookup


def validate_formal_candidate(
    candidate: dict[str, Any], manifest_data: dict[str, Any], cache: dict[str, str]
) -> dict[str, Any]:
    root = Path(candidate["formal_dir"])
    rec_path = root / "evaluation_reconstructed.csv"
    online_path = root / "evaluation_online.csv"
    rec = validate_evaluation_rows(read_csv(rec_path), "reconstructed")
    online = validate_evaluation_rows(read_csv(online_path), "online")
    if set(rec) != set(online):
        raise RuntimeError(f"{candidate['id']}: reconstructed/online grids differ")
    contract: dict[str, str] = {}
    runs: dict[tuple[str, int], dict[str, Any]] = {}
    cases: list[dict[str, Any]] = []
    for role in ROLES:
        for repeat in REPEATS:
            key = (role, repeat)
            run_dir = Path(rec[key]["run_dir"]).resolve()
            if run_dir.parent.resolve() != root.resolve():
                raise RuntimeError(f"{candidate['id']}:{key}: run outside formal root")
            run = validate_run(run_dir, role, repeat, contract, cache)
            runs[key] = run
            shared = (
                "input_frames", "map_resets", "relocalizations", "attempted_seeds",
                "accepted_seeds", "post_init_attempted_seeds", "post_init_accepted_seeds",
                "seed_lineages_with_mappoint", "seed_lineages_surviving",
                "accepted_observations_with_mappoint", "distinct_mappoints",
                "keyframe_observations", "output_poses", "coverage_ratio", "run_dir",
            )
            for field in shared:
                if rec[key].get(field) != online[key].get(field):
                    raise RuntimeError(f"{candidate['id']}:{key}: metadata mismatch {field}")
            summary = run["summary"]
            for kind, table in (("reconstructed", rec), ("online", online)):
                row = table[key]
                for metric in METRICS:
                    parsed = parse_metric_report(report_path(run_dir, kind, metric, int(manifest_data["rpe_delta_frames"])))
                    if abs(parsed - float(row[metric])) > 1e-9:
                        raise RuntimeError(f"{candidate['id']}:{key}:{kind}:{metric}: CSV/report mismatch")
                cases.append({
                    "candidate_id": candidate["id"],
                    "window": candidate["window"],
                    "trajectory_kind": kind,
                    "role": role,
                    "repeat": repeat,
                    "status": row["status"],
                    "complete": row["complete"],
                    "input_frames": row["input_frames"],
                    "output_poses": row["output_poses"],
                    "coverage_ratio": row["coverage_ratio"],
                    "ape_rmse_m": row["ape_rmse_m"],
                    "rpe_rmse_m": row["rpe_rmse_m"],
                    "post_init_attempted_seeds": row["post_init_attempted_seeds"],
                    "post_init_accepted_seeds": row["post_init_accepted_seeds"],
                    "seed_lineages_with_mappoint": row["seed_lineages_with_mappoint"],
                    "seed_lineages_surviving": row["seed_lineages_surviving"],
                    "distinct_mappoints": row["distinct_mappoints"],
                    "accepted_observations_with_mappoint": row["accepted_observations_with_mappoint"],
                    "keyframe_observations": row["keyframe_observations"],
                    "assisted_matches": summary["lineage_assisted_matches_consumed"],
                    "assisted_outliers_total": summary["lineage_assisted_outliers_observed"],
                    "pre_kf_outliers": summary["lineage_pre_kf_assisted_outliers_observed"],
                    "purge_scans": summary["lineage_pre_kf_outlier_purge_scans"],
                    "purged": summary["lineage_pre_kf_assisted_outliers_purged"],
                    "trajectory_sha256": run["trajectories"][kind]["sha256"],
                    "run_dir": run["run_dir"],
                })
    association = association_audit(candidate, runs, manifest_data)
    hashes = hash_audit(runs)
    return {
        "candidate": candidate,
        "root": str(root.resolve()),
        "runs": runs,
        "reconstructed": rec,
        "online": online,
        "cases": cases,
        "contract": contract,
        "association": association,
        "hashes": hashes,
        "evaluation_artifacts": [artifact(rec_path, cache), artifact(online_path, cache)],
    }


def association_audit(
    candidate: dict[str, Any],
    runs: dict[tuple[str, int], dict[str, Any]],
    manifest_data: dict[str, Any],
) -> dict[str, Any]:
    first_run = next(iter(runs.values()))
    dataset = Path(first_run["manifest"]["dataset_dir"])
    reference = file_interface.read_tum_trajectory_file(str(dataset / "groundtruth_tum.txt"))
    max_diff = float(manifest_data["max_time_diff_s"])
    delta = int(manifest_data["rpe_delta_frames"])
    rows: list[dict[str, Any]] = []
    for (role, repeat), run in runs.items():
        for kind in TRAJECTORY_KINDS:
            estimate = file_interface.read_tum_trajectory_file(
                str(Path(run["trajectory_secs"][kind]["path"]))
            )
            ref_sync, est_sync = sync.associate_trajectories(reference, estimate, max_diff=max_diff)
            if ref_sync.num_poses <= delta:
                raise RuntimeError(f"{candidate['id']}:{kind}:{role}: insufficient associated poses")
            physical = ref_sync.timestamps[delta:] - ref_sync.timestamps[:-delta]
            rows.append({
                "candidate_id": candidate["id"],
                "trajectory_kind": kind,
                "role": role,
                "repeat": repeat,
                "gt_poses": reference.num_poses,
                "estimate_poses": estimate.num_poses,
                "associated_poses": ref_sync.num_poses,
                "association_dt_min_s": float(np.abs(ref_sync.timestamps - est_sync.timestamps).min()),
                "association_dt_median_s": float(np.median(np.abs(ref_sync.timestamps - est_sync.timestamps))),
                "association_dt_max_s": float(np.abs(ref_sync.timestamps - est_sync.timestamps).max()),
                "rpe_pairs": int(len(physical)),
                "rpe_physical_dt_min_s": float(physical.min()),
                "rpe_physical_dt_median_s": float(np.median(physical)),
                "rpe_physical_dt_max_s": float(physical.max()),
            })
    signature_fields = (
        "gt_poses", "estimate_poses", "associated_poses", "association_dt_min_s",
        "association_dt_median_s", "association_dt_max_s", "rpe_pairs",
        "rpe_physical_dt_min_s", "rpe_physical_dt_median_s", "rpe_physical_dt_max_s",
    )
    signatures = {
        tuple(round(float(row[field]), 12) if isinstance(row[field], float) else row[field] for field in signature_fields)
        for row in rows
    }
    if len(signatures) != 1:
        raise RuntimeError(f"{candidate['id']}: association protocol differs across arms")
    common = {field: rows[0][field] for field in signature_fields}
    return {
        "settings": {"max_time_diff_s": max_diff, "rpe_delta_frames": delta},
        "common": common,
        "rows_checked": len(rows),
        "rows": rows,
    }


def hash_audit(runs: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    unique: dict[str, dict[str, list[str]]] = {
        role: {kind: [] for kind in TRAJECTORY_KINDS} for role in ROLES
    }
    for role in ROLES:
        for kind in TRAJECTORY_KINDS:
            unique[role][kind] = [runs[(role, repeat)]["trajectories"][kind]["sha256"] for repeat in REPEATS]
    full_unbounded_equal: dict[str, list[bool]] = {kind: [] for kind in TRAJECTORY_KINDS}
    drop_native_equal: dict[str, list[bool]] = {kind: [] for kind in TRAJECTORY_KINDS}
    for kind in TRAJECTORY_KINDS:
        full_unbounded_equal[kind] = [
            unique["full"][kind][repeat - 1] == unique["full_unbounded"][kind][repeat - 1]
            for repeat in REPEATS
        ]
        drop_native_equal[kind] = [
            unique["drop"][kind][repeat - 1] == unique["orb_only"][kind][repeat - 1]
            for repeat in REPEATS
        ]
    return {
        "hashes_by_role": unique,
        "unique_count_by_role": {
            role: {kind: len(set(values)) for kind, values in kinds.items()}
            for role, kinds in unique.items()
        },
        "full_vs_unbounded_same_repeat": full_unbounded_equal,
        "full_vs_unbounded_same_repeat_count": {
            kind: sum(values) for kind, values in full_unbounded_equal.items()
        },
        "full_vs_unbounded_different_repeat": {
            kind: [not value for value in values]
            for kind, values in full_unbounded_equal.items()
        },
        "full_vs_unbounded_different_repeat_count": {
            kind: sum(not value for value in values)
            for kind, values in full_unbounded_equal.items()
        },
        "drop_vs_native_same_repeat": drop_native_equal,
        "drop_vs_native_same_repeat_count": {
            kind: sum(values) for kind, values in drop_native_equal.items()
        },
    }


def validate_smoke_candidate(
    candidate: dict[str, Any], cache: dict[str, str]
) -> dict[str, Any]:
    root = Path(candidate["smoke_dir"])
    contract: dict[str, str] = {}
    runs: dict[str, dict[str, Any]] = {}
    for role in ("orb_only", "drop", "full"):
        runs[role] = validate_run(root / f"{role}_r1", role, 1, contract, cache, "orb_only drop full", require_sec=False)
    full = runs["full"]
    lineage_path = Path(full["run_dir"]) / "instrumentation/seed_lineages.csv"
    lineage_rows = read_csv(lineage_path)
    if len(lineage_rows) != 1:
        raise RuntimeError(f"{candidate['id']}: expected one lineage in smoke")
    lineage = lineage_rows[0]
    summary = full["summary"]
    attempted = int(lineage["attempted"])
    accepted = int(lineage["accepted"])
    pre_attempted = int(lineage["pre_init_attempted"])
    post_attempted = int(lineage["post_init_attempted"])
    pre_accepted = int(lineage["pre_init_accepted"])
    post_accepted = int(lineage["post_init_accepted"])
    action = {
        "assisted_matches": as_int(summary, "lineage_assisted_matches_consumed"),
        "assisted_outliers_total": as_int(summary, "lineage_assisted_outliers_observed"),
        "pre_kf_outliers": as_int(summary, "lineage_pre_kf_assisted_outliers_observed"),
        "purge_scans": as_int(summary, "lineage_pre_kf_outlier_purge_scans"),
        "purged": as_int(summary, "lineage_pre_kf_assisted_outliers_purged"),
    }
    pure_post_init = pre_attempted == 0 and pre_accepted == 0 and post_attempted == attempted
    natural_action_observed = any(action.values())
    eligible_action_positive = (
        pure_post_init
        and as_int(summary, "seed_lineages_with_mappoint") > 0
        and action["assisted_matches"] > 0
        and action["assisted_outliers_total"] > 0
        and action["purged"] > 0
    )
    quality_audit = seed_quality_audit(full["manifest"].get("seed_file", ""), 0.9)
    return {
        "candidate_id": candidate["id"],
        "label": candidate["label"],
        "window": candidate["window"],
        "screening_decision": candidate["screening_decision"],
        "screening_reason": candidate["screening_reason"],
        "smoke_root": str(root.resolve()),
        "attempted": attempted,
        "accepted": accepted,
        "pre_init_attempted": pre_attempted,
        "post_init_attempted": post_attempted,
        "pre_init_accepted": pre_accepted,
        "post_init_accepted": post_accepted,
        "pure_post_init": int(pure_post_init),
        "seed_lineages_with_mappoint": as_int(summary, "seed_lineages_with_mappoint"),
        "seed_lineages_surviving": as_int(summary, "seed_lineages_surviving"),
        "distinct_mappoints": int(lineage["unique_mappoints"]),
        "live_mappoints": int(lineage["live_mappoints"]),
        "accepted_observations_with_mappoint": as_int(summary, "accepted_observations_with_mappoint"),
        "action_positive": int(eligible_action_positive),
        "natural_action_observed": int(natural_action_observed),
        "eligible_action_positive": int(eligible_action_positive),
        "seed_quality_audit": quality_audit,
        # Keep scalar aliases in the smoke record for compact CSV/report use.
        "quality_min": quality_audit["min_quality"],
        "quality_below_nominal_gate": quality_audit["below_threshold"],
        **action,
        "smoke_contract": contract,
        "smoke_runs": runs,
        "lineage_artifact": artifact(lineage_path, cache),
    }


def pct_change(candidate: float, control: float) -> float:
    if control == 0:
        raise RuntimeError("cannot calculate relative change from zero control")
    return 100.0 * (candidate / control - 1.0)


def mean_sd(values: list[float]) -> tuple[float, float]:
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0


def build_tables(
    formal: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cases: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for candidate_id, data in formal.items():
        candidate = data["candidate"]
        for case in data["cases"]:
            cases.append(case)
        for role in ROLES:
            summary = data["runs"][(role, 1)]["summary"]
            for repeat in REPEATS:
                s = data["runs"][(role, repeat)]["summary"]
                eval_row = data["reconstructed"][(role, repeat)]
                actions.append({
                    "candidate_id": candidate_id,
                    "window": candidate["window"],
                    "role": role,
                    "repeat": repeat,
                    "attempted": s["attempted_seed_observations"],
                    "accepted": s["accepted_seed_observations"],
                    "post_init_accepted": eval_row["post_init_accepted_seeds"],
                    "seed_lineages_with_mappoint": s["seed_lineages_with_mappoint"],
                    "seed_lineages_surviving": s["seed_lineages_surviving"],
                    "distinct_mappoints": s["distinct_mappoints"],
                    "assisted_matches": s["lineage_assisted_matches_consumed"],
                    "assisted_outliers_total": s["lineage_assisted_outliers_observed"],
                    "pre_kf_outliers": s["lineage_pre_kf_assisted_outliers_observed"],
                    "purge_scans": s["lineage_pre_kf_outlier_purge_scans"],
                    "purged": s["lineage_pre_kf_assisted_outliers_purged"],
                })
            for kind in TRAJECTORY_KINDS:
                table = data[kind]
                values = {metric: [float(table[(role, repeat)][metric]) for repeat in REPEATS] for metric in METRICS}
                native = data[kind][("orb_only", 1)]
                unbounded = data[kind][("full_unbounded", 1)]
                relative_native = {
                    metric: [pct_change(float(table[(role, repeat)][metric]), float(table[("orb_only", repeat)][metric])) for repeat in REPEATS]
                    for metric in METRICS
                }
                relative_unbounded = {
                    metric: [pct_change(float(table[(role, repeat)][metric]), float(table[("full_unbounded", repeat)][metric])) for repeat in REPEATS]
                    for metric in METRICS
                }
                roles.append({
                    "candidate_id": candidate_id,
                    "window": candidate["window"],
                    "trajectory_kind": kind,
                    "role": role,
                    "repeat_count": len(REPEATS),
                    "ape_mean_m": f"{mean_sd(values['ape_rmse_m'])[0]:.9f}",
                    "ape_sd_m": f"{mean_sd(values['ape_rmse_m'])[1]:.9f}",
                    "rpe_mean_m": f"{mean_sd(values['rpe_rmse_m'])[0]:.9f}",
                    "rpe_sd_m": f"{mean_sd(values['rpe_rmse_m'])[1]:.9f}",
                    "ape_vs_native_mean_pct": f"{mean_sd(relative_native['ape_rmse_m'])[0]:.9f}",
                    "rpe_vs_native_mean_pct": f"{mean_sd(relative_native['rpe_rmse_m'])[0]:.9f}",
                    "ape_vs_unbounded_mean_pct": f"{mean_sd(relative_unbounded['ape_rmse_m'])[0]:.9f}",
                    "rpe_vs_unbounded_mean_pct": f"{mean_sd(relative_unbounded['rpe_rmse_m'])[0]:.9f}",
                    "trajectory_unique_hashes": data["hashes"]["unique_count_by_role"][role][kind],
                    "action_matches_r1": summary["lineage_assisted_matches_consumed"],
                    "action_outliers_r1": summary["lineage_assisted_outliers_observed"],
                    "action_pre_kf_outliers_r1": summary["lineage_pre_kf_assisted_outliers_observed"],
                    "action_purged_r1": summary["lineage_pre_kf_assisted_outliers_purged"],
                })
                for repeat in REPEATS:
                    for metric in METRICS:
                        candidate_value = float(table[(role, repeat)][metric])
                        native_value = float(table[("orb_only", repeat)][metric])
                        effects.append({
                            "candidate_id": candidate_id,
                            "window": candidate["window"],
                            "trajectory_kind": kind,
                            "role": role,
                            "repeat": repeat,
                            "metric": metric,
                            "control": "orb_only",
                            "candidate_rmse_m": f"{candidate_value:.9f}",
                            "control_rmse_m": f"{native_value:.9f}",
                            "absolute_difference_m": f"{candidate_value-native_value:.9f}",
                            "relative_change_pct": f"{pct_change(candidate_value, native_value):.9f}",
                        })
                    if role == "full":
                        for metric in METRICS:
                            candidate_value = float(table[(role, repeat)][metric])
                            ub_value = float(table[("full_unbounded", repeat)][metric])
                            effects.append({
                                "candidate_id": candidate_id,
                                "window": candidate["window"],
                                "trajectory_kind": kind,
                                "role": role,
                                "repeat": repeat,
                                "metric": metric,
                                "control": "full_unbounded",
                                "candidate_rmse_m": f"{candidate_value:.9f}",
                                "control_rmse_m": f"{ub_value:.9f}",
                                "absolute_difference_m": f"{candidate_value-ub_value:.9f}",
                                "relative_change_pct": f"{pct_change(candidate_value, ub_value):.9f}",
                            })
    return cases, effects, roles, actions


def strict_positive(data: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered four-metric, all-repeat decision rule."""
    checks: list[bool] = []
    for kind in TRAJECTORY_KINDS:
        table = data[kind]
        for repeat in REPEATS:
            for metric in METRICS:
                value = float(table[("full", repeat)][metric])
                checks.extend(
                    (
                        value < float(table[("orb_only", repeat)][metric]),
                        value < float(table[("drop", repeat)][metric]),
                        value < float(table[("full_unbounded", repeat)][metric]),
                    )
                )
    stable_full = all(
        data["hashes"]["unique_count_by_role"]["full"][kind] == 1
        for kind in TRAJECTORY_KINDS
    )
    action_rows = [data["runs"][("full", repeat)]["summary"] for repeat in REPEATS]
    action_fields = (
        "lineage_assisted_matches_consumed",
        "lineage_assisted_outliers_observed",
        "lineage_pre_kf_assisted_outliers_observed",
        "lineage_pre_kf_assisted_outliers_purged",
    )
    stable_action = all(
        tuple(row[field] for field in action_fields) == tuple(action_rows[0][field] for field in action_fields)
        for row in action_rows
    )
    return {
        "strict_positive": int(all(checks) and stable_full and stable_action),
        "metric_checks_passed": sum(checks),
        "metric_checks_total": len(checks),
        "full_trajectory_hash_stable": int(stable_full),
        "full_action_stable": int(stable_action),
        "full_action": {
            "assisted_matches": action_rows[0]["lineage_assisted_matches_consumed"],
            "assisted_outliers_total": action_rows[0]["lineage_assisted_outliers_observed"],
            "pre_kf_outliers": action_rows[0]["lineage_pre_kf_assisted_outliers_observed"],
            "purged": action_rows[0]["lineage_pre_kf_assisted_outliers_purged"],
            "scans": action_rows[0]["lineage_pre_kf_outlier_purge_scans"],
        },
    }


def screening_row(smoke: dict[str, Any], formal: dict[str, Any] | None) -> dict[str, Any]:
    decision = smoke["screening_decision"]
    formal_decision = decision
    strict = 0
    formal_action = {}
    if formal is not None:
        result = strict_positive(formal)
        strict = result["strict_positive"]
        formal_decision = "strict_positive" if strict else decision
        formal_action = result["full_action"]
    return {
        "candidate_id": smoke["candidate_id"],
        "label": smoke["label"],
        "window": smoke["window"],
        "smoke_decision": decision,
        "formal_decision": formal_decision,
        "attempted": smoke["attempted"],
        "accepted": smoke["accepted"],
        "pre_init_attempted": smoke["pre_init_attempted"],
        "post_init_attempted": smoke["post_init_attempted"],
        "pre_init_accepted": smoke["pre_init_accepted"],
        "post_init_accepted": smoke["post_init_accepted"],
        "pure_post_init": smoke["pure_post_init"],
        "seed_lineages_with_mappoint": smoke["seed_lineages_with_mappoint"],
        "seed_lineages_surviving": smoke["seed_lineages_surviving"],
        "distinct_mappoints": smoke["distinct_mappoints"],
        "accepted_observations_with_mappoint": smoke["accepted_observations_with_mappoint"],
        "smoke_assisted_matches": smoke["assisted_matches"],
        "smoke_assisted_outliers": smoke["assisted_outliers_total"],
        "smoke_pre_kf_outliers": smoke["pre_kf_outliers"],
        "smoke_purge_scans": smoke["purge_scans"],
        "smoke_purged": smoke["purged"],
        "smoke_action_positive": smoke["action_positive"],
        "quality_min": smoke["quality_min"],
        "quality_below_nominal_gate": smoke["quality_below_nominal_gate"],
        "formal_full_assisted_matches": formal_action.get("assisted_matches", ""),
        "formal_full_assisted_outliers": formal_action.get("assisted_outliers_total", ""),
        "formal_full_pre_kf_outliers": formal_action.get("pre_kf_outliers", ""),
        "formal_full_purge_scans": formal_action.get("scans", ""),
        "formal_full_purged": formal_action.get("purged", ""),
        "strict_positive": strict,
        "screening_reason": smoke["screening_reason"],
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
    fig.savefig(figures / f"{stem}.png", dpi=600, metadata=PNG_METADATA, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_screening(figures: Path, screening: list[dict[str, Any]]) -> None:
    configure_plot_style()
    labels = [row["candidate_id"].replace("_", "\n") for row in screening]
    positions = np.arange(len(screening))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), constrained_layout=True)
    reach_fields = (("attempted", "Attempted"), ("accepted", "Accepted"), ("post_init_accepted", "Post-init accepted"))
    action_fields = (("smoke_assisted_matches", "Assisted matches"), ("smoke_assisted_outliers", "Outliers"), ("smoke_pre_kf_outliers", "pre-KF outliers"), ("smoke_purged", "Purged"))
    for axis, fields, title in ((axes[0], reach_fields, "Screening reachability"), (axes[1], action_fields, "Natural action opportunity")):
        width = 0.18 if len(fields) == 4 else 0.23
        for index, (field, label) in enumerate(fields):
            values = [float(row[field]) for row in screening]
            center = (len(fields) - 1) / 2
            colors = ("#000000", "#56B4E9", "#E69F00", "#0072B2")
            bars = axis.bar(positions + (index - center) * width, values, width, label=label, color=colors[index], edgecolor="black", linewidth=0.5, alpha=0.8)
            for bar, value in zip(bars, values):
                if value:
                    axis.text(bar.get_x() + bar.get_width() / 2, value + max(values) * 0.02, f"{int(value)}", ha="center", va="bottom", fontsize=6.5)
        axis.set_title(title)
        axis.set_xticks(positions)
        axis.set_xticklabels(labels, rotation=0)
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        axis.legend(frameon=False, loc="upper right")
    save_figure(fig, figures, "figure-01-screening-action-funnel")


def figure_absolute(figures: Path, formal: dict[str, dict[str, Any]]) -> None:
    configure_plot_style()
    ids = list(formal)
    fig, axes = plt.subplots(len(ids), 4, figsize=(10.0, 2.25 * len(ids)), squeeze=False, constrained_layout=True)
    panels = (("reconstructed", "ape_rmse_m"), ("reconstructed", "rpe_rmse_m"), ("online", "ape_rmse_m"), ("online", "rpe_rmse_m"))
    for row_index, candidate_id in enumerate(ids):
        data = formal[candidate_id]
        for column, (kind, metric) in enumerate(panels):
            axis = axes[row_index][column]
            table = data[kind]
            grouped = [[float(table[(role, repeat)][metric]) for repeat in REPEATS] for role in ROLES]
            means = [statistics.mean(values) for values in grouped]
            sds = [statistics.stdev(values) if len(values) > 1 else 0.0 for values in grouped]
            positions = np.arange(len(ROLES))
            bars = axis.bar(positions, means, yerr=sds, capsize=2, color=[ROLE_COLOR[r] for r in ROLES], edgecolor="black", linewidth=0.45, alpha=0.8)
            for bar, role in zip(bars, ROLES):
                bar.set_hatch(ROLE_HATCH[role])
            for index, (role, values) in enumerate(zip(ROLES, grouped)):
                axis.scatter(np.full(len(values), index), values, s=11, color=ROLE_COLOR[role], edgecolor="white", linewidth=0.3, zorder=3)
            axis.set_ylim(bottom=0)
            axis.set_xticks(positions)
            axis.set_xticklabels([ROLE_SHORT[r] for r in ROLES], rotation=25, ha="right")
            axis.grid(axis="y", alpha=0.25)
            if row_index == 0:
                axis.set_title(f"{kind.capitalize()} {METRIC_LABEL[metric]}")
            if column == 0:
                axis.set_ylabel(candidate_id + "\nRMSE (m)")
    save_figure(fig, figures, "figure-02-formal-four-metric-comparison")


def figure_relative(figures: Path, formal: dict[str, dict[str, Any]]) -> None:
    configure_plot_style()
    ids = list(formal)
    fig, axes = plt.subplots(2, len(ids), figsize=(3.1 * len(ids), 5.3), squeeze=False, constrained_layout=True, sharey="row")
    for row_index, kind in enumerate(TRAJECTORY_KINDS):
        for column, candidate_id in enumerate(ids):
            axis = axes[row_index][column]
            data = formal[candidate_id][kind]
            metrics = list(METRICS)
            positions = np.arange(2)
            width = 0.34
            values_native = [pct_change(float(data[("full", repeat)][metric]), float(data[("orb_only", repeat)][metric])) for metric in metrics for repeat in REPEATS]
            values_ub = [pct_change(float(data[("full", repeat)][metric]), float(data[("full_unbounded", repeat)][metric])) for metric in metrics for repeat in REPEATS]
            native_groups = [values_native[index * len(REPEATS):(index + 1) * len(REPEATS)] for index in range(2)]
            ub_groups = [values_ub[index * len(REPEATS):(index + 1) * len(REPEATS)] for index in range(2)]
            means_n = [statistics.mean(v) for v in native_groups]
            means_u = [statistics.mean(v) for v in ub_groups]
            sd_n = [statistics.stdev(v) if len(v) > 1 else 0.0 for v in native_groups]
            sd_u = [statistics.stdev(v) if len(v) > 1 else 0.0 for v in ub_groups]
            axis.bar(positions - width / 2, means_n, width, yerr=sd_n, capsize=2, label="vs native", color="#0072B2", edgecolor="black", linewidth=0.45)
            axis.bar(positions + width / 2, means_u, width, yerr=sd_u, capsize=2, label="vs unbounded", color="#E69F00", edgecolor="black", linewidth=0.45, hatch="..")
            axis.axhline(0, color="#555555", linewidth=0.8)
            axis.axhline(5, color="#D55E00", linestyle="--", linewidth=0.9)
            axis.set_xticks(positions)
            axis.set_xticklabels(("APE", "RPE"))
            axis.set_title(f"{candidate_id}\n{kind}")
            axis.grid(axis="y", alpha=0.25)
            if column == 0:
                axis.set_ylabel("Full relative change (%)\nnegative is improvement")
            if row_index == 0 and column == 0:
                axis.legend(frameon=False, loc="upper left")
    save_figure(fig, figures, "figure-03-relative-change")


def figure_action(figures: Path, formal: dict[str, dict[str, Any]]) -> None:
    configure_plot_style()
    ids = list(formal)
    fig, axes = plt.subplots(1, len(ids), figsize=(3.2 * len(ids), 3.4), squeeze=False, constrained_layout=True)
    fields = (("lineage_assisted_matches_consumed", "Matches"), ("lineage_assisted_outliers_observed", "Outliers"), ("lineage_pre_kf_assisted_outliers_observed", "pre-KF outliers"), ("lineage_pre_kf_assisted_outliers_purged", "Purged"))
    for column, candidate_id in enumerate(ids):
        axis = axes[0][column]
        data = formal[candidate_id]
        positions = np.arange(len(fields))
        for role_index, role in enumerate(("full_unbounded", "full")):
            values = [int(data["runs"][(role, 1)]["summary"][field]) for field, _ in fields]
            bar_width = 0.18
            bars = axis.bar(positions + (role_index - 0.5) * bar_width, values, bar_width, label=ROLE_LABEL[role], color=ROLE_COLOR[role], edgecolor="black", linewidth=0.5, hatch=ROLE_HATCH[role])
            for bar, value in zip(bars, values):
                if value:
                    axis.text(bar.get_x() + bar.get_width() / 2, value + max(values + [1]) * 0.03, str(value), ha="center", va="bottom", fontsize=7)
        axis.set_title(candidate_id)
        axis.set_xticks(positions)
        axis.set_xticklabels([label for _, label in fields])
        axis.set_ylabel("Count per formal run")
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        axis.legend(frameon=False, loc="upper right")
    save_figure(fig, figures, "figure-04-formal-action-stability")


def summary_table(roles: list[dict[str, Any]], candidate_id: str | None = None) -> str:
    rows = [row for row in roles if candidate_id is None or row["candidate_id"] == candidate_id]
    lines = [
        "| Candidate | Trajectory | Role | APE mean +/- SD (m) | RPE mean +/- SD (m) | Role vs native APE/RPE | Role vs unbounded APE/RPE |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {candidate_id} | {trajectory_kind} | {role} | {ape_mean} +/- {ape_sd} | {rpe_mean} +/- {rpe_sd} | {ape_native}% / {rpe_native}% | {ape_ub}% / {rpe_ub}% |".format(
                candidate_id=row["candidate_id"],
                trajectory_kind=row["trajectory_kind"],
                role=ROLE_LABEL[row["role"]],
                ape_mean=float(row["ape_mean_m"]),
                ape_sd=float(row["ape_sd_m"]),
                rpe_mean=float(row["rpe_mean_m"]),
                rpe_sd=float(row["rpe_sd_m"]),
                ape_native=f"{float(row['ape_vs_native_mean_pct']):+.3f}",
                rpe_native=f"{float(row['rpe_vs_native_mean_pct']):+.3f}",
                ape_ub=f"{float(row['ape_vs_unbounded_mean_pct']):+.3f}",
                rpe_ub=f"{float(row['rpe_vs_unbounded_mean_pct']):+.3f}",
            )
        )
    return "\n".join(lines)


def action_table(screening: list[dict[str, Any]]) -> str:
    lines = [
        "| Candidate | Attempted | Accepted | Pre-init | Post-init | MapPoint lineages | Distinct MapPoints | q min | q < 0.9 | Matches | Outliers | pre-KF outliers | Purged | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in screening:
        lines.append(
            f"| {row['candidate_id']} | {row['attempted']} | {row['accepted']} | {row['pre_init_attempted']} | {row['post_init_accepted']} | {row['seed_lineages_with_mappoint']} | {row['distinct_mappoints']} | {float(row['quality_min']):.6f} | {row['quality_below_nominal_gate']} | {row['smoke_assisted_matches']} | {row['smoke_assisted_outliers']} | {row['smoke_pre_kf_outliers']} | {row['smoke_purged']} | {row['formal_decision']} |"
        )
    return "\n".join(lines)


def write_reports(
    output: Path,
    manifest_data: dict[str, Any],
    screening: list[dict[str, Any]],
    formal: dict[str, dict[str, Any]],
    roles: list[dict[str, Any]],
    hash_cache: dict[str, str],
) -> None:
    evidence_id = manifest_data["evidence_id"]
    strict_ids = [row["candidate_id"] for row in screening if row["strict_positive"] == 1]
    a02 = next((candidate_id for candidate_id in strict_ids if candidate_id == "A02_2800_3200"), None)
    formal_count = sum(len(data["runs"]) for data in formal.values())
    smoke_count = len(screening) * 3
    association_lines = []
    for candidate_id, data in formal.items():
        common = data["association"]["common"]
        association_lines.append(
            f"- `{candidate_id}`: {common['associated_poses']}/{common['gt_poses']} GT poses associated; "
            f"RPE delta={data['association']['settings']['rpe_delta_frames']} and physical delta "
            f"{common['rpe_physical_dt_min_s']:.6f}-{common['rpe_physical_dt_max_s']:.6f} s."
        )
    report = f"""# ORB-SLAM3 v23 post-init action-search strict analysis

## Analysis question

Among frozen AQUALOC final-online lineages, which windows satisfy the causal reachability chain
`post-init seed -> MapPoint lineage -> assisted match -> assisted outlier -> pre-KF purge`,
and does the enforced v23 branch improve both reconstructed and online APE/RPE under the
frozen five-arm protocol?

Evidence record: `{evidence_id}`. The independent unit is a fixed window. Repeated runs are
deterministic reproducibility checks, not independent windows or independent samples.

## QA result

- The screening denominator is five windows: A09, A08, A07, A10-400, and A02.
- Smoke validation covers {smoke_count} role runs (native, drop, full for each window); formal validation covers {formal_count} role/repeat runs across the three eligible matrices.
- Every validated run has a complete seed audit, zero event/related-MapPoint overflow, true conservation and pointer checks, a non-empty online and reconstructed trajectory, and a matching provenance snapshot hash.
- The three formal matrices each contain the complete 5 roles x 4 repeats grid. CSV RMSE values match the stored evaluator reports.
- RPE is evaluated with `delta={manifest_data['rpe_delta_frames']}` and `max_time_diff={float(manifest_data['max_time_diff_s']):.2f} s`; it is not a fixed one-second label.

## Screening denominator

{action_table(screening)}

The smoke counters are used only for action reachability. A smoke run without an evaluation CSV
does not contribute an APE/RPE result.

## Formal comparison

The strict positive rule requires, for every repeat, all four full-branch metrics to be lower than
both native ORB and the exact drop arm, and lower than the unbounded bridge-on arm; the full
trajectory hash and action counters must also be stable across repeats.

{summary_table(roles)}

## Key findings

1. **A02 is the strict new positive.** A02 has 106/106 post-init accepted observations in smoke,
one accepted lineage with a MapPoint, and formal full action of 7 assisted matches, 3 total/pre-KF
outliers, and 3 purges in every repeat. Its full branch is lower than native, drop, and
unbounded on reconstructed and online APE/RPE in all 48 metric checks.
2. **A08 is action-positive but not a trajectory positive.** Its formal full action is stable at
32 assisted matches, 23 total assisted outliers, and 10 pre-KF outliers purged. Reconstructed metrics improve over native, while online
APE worsens substantially; the dual reconstructed/online criterion therefore fails.
3. **A10-400 is a guard-rescue boundary.** Full improves over unbounded after one purge per run,
but reconstructed full remains worse than native. The formal full action is 28 matches, 1 total/pre-KF outlier, and 1 purge; the smoke
counter 38/1/1 is retained as a separate screening observation and is not substituted into the
formal result.
4. **A09 reaches the bridge but offers no v23 action opportunity.** It has 30/30 post-init
accepted observations and 22 assisted matches, but zero assisted outliers and zero purges.
5. **A07 is excluded before formal metrics.** It has action (5 matches, 3 outliers, 3/3 purges),
but six observations are pre-init and one post-init observation is rejected at the border. It
does not satisfy the pure post-init screening contract.

## Candidate decision

- Keep A02 as the strict ORB-v23 positive mechanism-and-trajectory case.
- Keep A08 as an action-positive, metric-mixed boundary case.
- Keep A10-400 as a guard-rescue boundary case, including its residual drop-r4 branch anomaly.
- Keep A09 as a reachable/action-null negative screen and A07 as a protocol-excluded action case.
- Do not pool the five windows into an accuracy success rate; the windows were selected by a
  mechanism screen and only three received formal metrics.

## Evidence limits

{chr(10).join(association_lines)}

The AQUALOC ground truth is sparse and the candidate set is one sequence/domain. Four repeats
establish deterministic branch reproducibility, not population uncertainty. A10 drop-r4 is a
retained residual map branch; no row is silently removed. The A10 seed asset contains one quality
value below the nominal 0.9 threshold (q-min 0.890251, one row); the frozen extractor accepted
that row, so the report preserves the interface distinction instead of claiming that every input
seed passed the downstream quality gate.

## Claim candidates

### Claim 1

- Claim: AQUALOC A02 `2800-3200` is a strict ORB-v23 positive under the frozen protocol.
- Source evidence: `{evidence_id}`; complete 5-arm x 4-repeat matrix, stable 7/3/3 action, and 48/48 full-versus-control metric comparisons in the allowed direction.
- Allowed wording: "A02 2800-3200 provides a deterministic strict positive under the frozen ORB-v23 protocol."
- Forbidden stronger wording: "The method is generally superior across underwater sequences."
- Uncertainty: one fixed AQUALOC window and deterministic repeats only.
- Next check: an independent window with the same natural assisted-outlier/purge opportunity.
- Decision: keep

### Claim 2

- Claim: The lineage bridge can be active without yielding a v23 accuracy win.
- Source evidence: A09 and A08; A09 has assisted matches but no outliers, while A08 has stable purge action but mixed online/reconstructed metrics.
- Allowed wording: "Reachability and purge action are necessary screening conditions, not sufficient guarantees of a dual-metric trajectory gain."
- Forbidden stronger wording: "Every action-positive window improves trajectory accuracy."
- Uncertainty: only five screened windows.
- Next check: cross-sequence replication under the unchanged contract.
- Decision: keep

### Claim 3

- Claim: v23 generalizes as a trajectory improvement to all screened windows.
- Source evidence: A09/A08/A10 counterexamples and A07 protocol exclusion.
- Allowed wording: "The current evidence is window-dependent and does not support a universal improvement claim."
- Forbidden stronger wording: "v23 always improves APE/RPE."
- Uncertainty: more independent sequences are needed.
- Next check: cross-dataset natural-action search.
- Decision: discard
"""
    (output / "analysis-report.md").write_text(report, encoding="utf-8")

    stats = f"""# Statistical appendix

## Design and unit of analysis

- Candidate windows: five fixed AQUALOC windows in the frozen post-init search queue.
- Formal candidates: A08, A10-400, and A02; each has five roles and four deterministic repeats.
- Independent unit: one fixed window (`n=1` per candidate). Runtime repeats share images, seeds,
  binary, scheduler, and ground truth, so they are not independent samples.
- Primary metrics: Sim(3)-aligned translational APE RMSE and translational RPE RMSE; lower is better.
- RPE protocol: `delta={manifest_data['rpe_delta_frames']}` associated trajectory step and
  `max_time_diff={float(manifest_data['max_time_diff_s']):.2f} s`.

## Descriptive statistics

{summary_table(roles)}

Means and sample SDs are descriptive across four deterministic runtime repeats. A zero SD means
the stored metric is identical at the reported precision; trajectory hash counts are reported
separately. Relative changes are unstandardized paired branch differences, not population effect sizes.

## Screening proportions (descriptive only)

- Action-positive smoke opportunities: {sum(int(row['smoke_action_positive']) for row in screening)}/5.
- Pure post-init smoke windows: {sum(int(row['pure_post_init']) for row in screening)}/5.
- Formal matrices: {len(formal)}/5.
- Strict four-metric positives: {len(strict_ids)}/5.

These fractions describe this preselected search queue. They are not estimates of a deployment
success probability and have no confidence interval.

## Inferential-statistics decision

No t-test, Wilcoxon test, confidence interval, standardized effect size, or multiple-comparison
claim is reported. The repeated runs are deterministic replications of one window, so a test that
treats them as independent would be pseudoreplication. The strict decision is a pre-registered
directional reproducibility rule, not a significance test.

## Mechanism and reproducibility audit

- A02 full action is stable at 7 assisted matches, 3 assisted outliers, and 3 purges in all four
  repeats; full and unbounded differ in purge action (3 versus 0).
- A08 full action is stable at 32 matches/23 total outliers/10 pre-KF outliers/10 purges and
  unbounded at 38/4/3/0; this demonstrates action but not
  a universal accuracy outcome.
- A10 full action is stable at 28/1/1/1 (matches/total outliers/pre-KF outliers/purges) and
  unbounded at 27/1/1/0. Its drop-r4 trajectory is retained
  as a residual map-insertion bifurcation.
- All validated snapshot entries and manifest hashes pass. No failed run or overflowed audit is
  silently removed.

## Boundary on MapPoint wording

`seed_lineages_with_mappoint=1` means one external lineage reached a MapPoint. It is distinct from
`distinct_mappoints`, which is 1/3/7/6/4 for A09/A08/A07/A10/A02 smoke full runs respectively.
Reports use both fields rather than conflating lineage count with map-point count.

The A10 seed asset has one q value below 0.9 (minimum 0.890251338). It was accepted by the
extractor under the frozen interface; this is recorded as an input-quality caveat, not silently
reclassified as a passed q gate.
"""
    (output / "stats-appendix.md").write_text(stats, encoding="utf-8")

    catalog = """# Figure catalog

## Figure 1: `figures/figure-01-screening-action-funnel.pdf`

- Purpose: show why five windows entered the queue but only three entered formal APE/RPE evaluation.
- Data source: `screening_summary.csv`, full-arm smoke counters.
- Caption requirements: bars are raw per-window counts; no uncertainty bars are appropriate for a
  single smoke run; post-init and action stages are not independent samples.
- Key observation: A09 reaches matches but has zero outliers/purges; A07 has action but fails the
  pure-post-init gate; A08/A10/A02 pass action screening.
- Interpretation: the mechanism screen prevents trajectory metrics from selecting the next window.
- Caveat: smoke counts are not formal trajectory results.

## Figure 2: `figures/figure-02-formal-four-metric-comparison.pdf`

- Purpose: compare all five formal roles across reconstructed/online APE/RPE for each eligible window.
- Data source: `case_summary.csv`; bars are means and error bars are sample SD across four deterministic repeats; dots are all repeats.
- Key observation: A02 full is below native, drop, and unbounded in every panel; A08 and A10 show mixed panels.
- Interpretation: A02 is the only strict four-metric positive in the screened set.
- Caveat: four repeats are reproducibility checks, not independent windows.

## Figure 3: `figures/figure-03-relative-change.pdf`

- Purpose: resolve full-branch changes relative to native and unbounded controls.
- Data source: `paired_effects.csv`; error bars are sample SD across deterministic repeats.
- Key observation: A02 is negative (improvement) against both controls in all four metrics; A10 improves against unbounded but not native.
- Interpretation: the unbounded contrast identifies purge-related rescue, while native remains the strict accuracy control.
- Caveat: the dashed +5% line is a diagnostic boundary, not a significance threshold.

## Figure 4: `figures/figure-04-formal-action-stability.pdf`

- Purpose: separate bridge consumption, natural outlier production, and enforced purge action.
- Data source: formal `seed_summary.json` files; bars are raw counts from repeat 1, verified stable across repeats for the full arm.
- Key observation: A02 changes purge from 0 in unbounded to 3 in v23 with the same 7 matches/3 total and pre-KF outliers.
- Interpretation: A02 directly exercises the intended v23 causal action chain.
- Caveat: action counts do not by themselves establish trajectory benefit.
"""
    (output / "figure-catalog.md").write_text(catalog, encoding="utf-8")


def build_provenance(
    manifest_path: Path,
    manifest_data: dict[str, Any],
    screening_data: list[dict[str, Any]],
    formal: dict[str, dict[str, Any]],
    script_path: Path,
    cache: dict[str, str],
) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for row in screening_data:
        candidates[row["candidate_id"]] = {
            "screening": row,
            "smoke_root": row["smoke_root"],
        }
    for candidate_id, data in formal.items():
        runs: dict[str, Any] = {}
        for (role, repeat), run in data["runs"].items():
            runs[f"{role}_r{repeat}"] = {
                "run_dir": run["run_dir"],
                "manifest": run["manifest_artifact"],
                "snapshot": run["snapshot_artifact"],
                "snapshot_entries_validated": run["snapshot_entries"],
                "summary": run["summary_artifact"],
                "trajectory_sha256": {kind: run["trajectories"][kind]["sha256"] for kind in TRAJECTORY_KINDS},
                "trajectory_sec_sha256": {kind: run["trajectory_secs"][kind]["sha256"] for kind in TRAJECTORY_KINDS},
            }
        candidates[candidate_id]["formal_root"] = data["root"]
        candidates[candidate_id]["formal_runs"] = runs
        candidates[candidate_id]["association"] = data["association"]
        candidates[candidate_id]["hash_audit"] = data["hashes"]
        candidates[candidate_id]["evaluation_artifacts"] = data["evaluation_artifacts"]
        candidates[candidate_id]["frozen_contract"] = data["contract"]
    top_level = [artifact(manifest_path, cache), artifact(script_path, cache)]
    return {
        "schema_version": 1,
        "evidence_id": manifest_data["evidence_id"],
        "analysis_date": manifest_data["analysis_date"],
        "analysis_parameters": {
            "rpe_delta_frames": manifest_data["rpe_delta_frames"],
            "max_time_diff_s": manifest_data["max_time_diff_s"],
            "roles": ROLES,
            "repeats": REPEATS,
            "inferential_statistics_performed": False,
        },
        "screening_root": manifest_data["screening_root"],
        "manifest_artifact": top_level[0],
        "builder_artifact": top_level[1],
        "candidate_count": len(screening_data),
        "formal_candidate_count": len(formal),
        "validated_smoke_run_count": len(screening_data) * 3,
        "validated_formal_run_count": sum(len(data["runs"]) for data in formal.values()),
        "candidates": candidates,
        "source_hashes": cache,
    }


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    output = args.output.resolve()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_data.get("schema_version") != 1:
        raise RuntimeError("unsupported analysis manifest schema")
    if tuple(manifest_data.get("roles", ())) != ROLES or tuple(manifest_data.get("repeats", ())) != REPEATS:
        raise RuntimeError("analysis manifest does not match the frozen role/repeat contract")
    candidates = manifest_data.get("candidates", [])
    if len(candidates) != 5 or len({candidate["id"] for candidate in candidates}) != 5:
        raise RuntimeError("expected exactly five unique screening candidates")
    if output.exists() and not args.replace:
        raise SystemExit(f"refusing existing output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    hash_cache: dict[str, str] = {}
    smoke_data: dict[str, dict[str, Any]] = {}
    formal: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        smoke_data[candidate["id"]] = validate_smoke_candidate(candidate, hash_cache)
        if candidate.get("formal_dir"):
            formal[candidate["id"]] = validate_formal_candidate(candidate, manifest_data, hash_cache)
    if set(formal) != {"A08_4500_4660", "A10_400_800", "A02_2800_3200"}:
        raise RuntimeError("formal candidate set differs from the frozen screening decision")

    screening = [
        screening_row(smoke_data[candidate["id"]], formal.get(candidate["id"]))
        for candidate in candidates
    ]
    observed_strict = {row["candidate_id"] for row in screening if row["strict_positive"] == 1}
    if observed_strict != {"A02_2800_3200"}:
        raise RuntimeError(f"strict decision QA failed: {sorted(observed_strict)}")
    cases, effects, roles, actions = build_tables(formal)
    association_rows = [
        row
        for data in formal.values()
        for row in data["association"]["rows"]
    ]

    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=str(output.parent)))
    try:
        figures = temporary / "figures"
        figures.mkdir()
        screening_csv_rows = [
            {key: value for key, value in row.items() if key not in {"smoke_contract", "smoke_runs", "lineage_artifact", "smoke_root"}}
            for row in screening
        ]
        write_csv(temporary / "screening_summary.csv", screening_csv_rows)
        write_csv(temporary / "case_summary.csv", cases)
        write_csv(temporary / "paired_effects.csv", effects)
        write_csv(temporary / "role_summary.csv", roles)
        write_csv(temporary / "action_summary.csv", actions)
        write_csv(temporary / "association_summary.csv", association_rows)
        (temporary / "trajectory_hash_audit.json").write_text(
            json.dumps({candidate_id: data["hashes"] for candidate_id, data in formal.items()}, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        figure_screening(figures, screening)
        figure_absolute(figures, formal)
        figure_relative(figures, formal)
        figure_action(figures, formal)
        write_reports(temporary, manifest_data, screening, formal, roles, hash_cache)
        provenance = build_provenance(
            manifest_path, manifest_data, [smoke_data[candidate["id"]] for candidate in candidates], formal, Path(__file__).resolve(), hash_cache
        )
        (temporary / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expected = (
            "analysis-report.md",
            "stats-appendix.md",
            "figure-catalog.md",
            "screening_summary.csv",
            "case_summary.csv",
            "paired_effects.csv",
            "role_summary.csv",
            "action_summary.csv",
            "association_summary.csv",
            "trajectory_hash_audit.json",
            "provenance.json",
            "figures/figure-01-screening-action-funnel.pdf",
            "figures/figure-01-screening-action-funnel.png",
            "figures/figure-02-formal-four-metric-comparison.pdf",
            "figures/figure-02-formal-four-metric-comparison.png",
            "figures/figure-03-relative-change.pdf",
            "figures/figure-03-relative-change.png",
            "figures/figure-04-formal-action-stability.pdf",
            "figures/figure-04-formal-action-stability.png",
        )
        missing = [name for name in expected if not (temporary / name).is_file()]
        empty = [name for name in expected if (temporary / name).is_file() and (temporary / name).stat().st_size == 0]
        if missing or empty:
            raise RuntimeError(f"bundle QA failed: missing={missing}, empty={empty}")
        if len(read_csv(temporary / "screening_summary.csv")) != 5:
            raise RuntimeError("screening denominator QA failed")
        if len(read_csv(temporary / "case_summary.csv")) != 120:
            raise RuntimeError("formal case-table QA failed")
        if output.exists():
            backup = output.with_name(f".{output.name}.old-{os.getpid()}")
            if backup.exists():
                raise RuntimeError(f"replacement backup already exists: {backup}")
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

    print(f"wrote strict ORB-v23 post-init analysis bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
