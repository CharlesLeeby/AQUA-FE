#!/usr/bin/env python3
"""Audit one frozen P07 A02 M/P export without trajectory outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import rosbag

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


FEATURE_TOPIC = "/feature_tracker/feature"
LEARNED_SOURCE_CODES = frozenset({10, 20, 30})
REQUIRED_CHANNELS = {
    "id",
    "camera_id",
    "p_u",
    "p_v",
    "velocity_x",
    "velocity_y",
    "gx",
    "gy",
    "gz",
    "quality",
    "sigma",
    "source_code",
    "is_learned",
}
FORBIDDEN_OUTCOME_NAMES = {
    "ape.csv",
    "ape.txt",
    "common_support_metrics.csv",
    "common_support_summary.json",
    "replay_manifest.txt",
    "rpe.csv",
    "rpe.txt",
    "trajectory.csv",
    "vins.log",
    "vins_output.log",
    "vio.csv",
}
M_CONTRACT_HASH = "4e31a9a29e8ee2198535de6b0bce01550b17077434e8e01ed68057822d4eace4"
P_CONTRACT_HASH = "39eaea6d26e6f5a881ef2b17b898cbda75c7aba8087ce447fe897e2fe0bdfce0"
SUMMARY_UNIQUE_KEYS = {
    "dataset_family",
    "profile",
    "probe_run",
    "final_run",
    "feature_bag",
}
VALID_P_PROFILES = {
    "mirror_densecap",
    "klt_safe_fallback",
    "oldcontract_microburst",
    "late_dense_normal",
    "degraded_mature_dense",
    "degraded_early_dense",
    "degraded_early_long",
    "degraded_early_sparse_mature",
    "low_grid_rejected_rich",
    "mature_lineage",
}


class AuditViolation(ValueError):
    """Raised when an export violates the frozen P07 M/P contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving the workspace logs symlink."""

    return Path(os.path.abspath(os.fspath(path)))


def display_path(path: Path) -> str:
    absolute = lexical_absolute(path)
    try:
        return absolute.relative_to(governance.ROOT).as_posix()
    except ValueError:
        return str(absolute)


def queue_row(index: int) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if int(row["queue_index"]) == index
    ]
    if len(matches) != 1:
        raise AuditViolation(f"expected one queue row for index {index}")
    row = matches[0]
    if row["arm"] not in {governance.M_ARM, governance.P_ARM}:
        raise AuditViolation(f"M/P auditor cannot audit arm {row['arm']}")
    observed = hashlib.sha256(row["command"].encode("utf-8")).hexdigest()
    if observed != row["command_sha256"]:
        raise AuditViolation("queue command hash mismatch")
    return row


def allocation_row(index: int) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.ALLOCATION_CSV)
        if int(row["queue_index"]) == index
    ]
    if len(matches) != 1:
        raise AuditViolation(f"expected one allocation row for index {index}")
    return matches[0]


def manifest_row(window_id: str) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.MANIFEST)
        if row["window_id"] == window_id
    ]
    if len(matches) != 1:
        raise AuditViolation(f"expected one manifest row for {window_id}")
    return matches[0]


def parse_guard_path(command_log: Path) -> Path:
    text = command_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"\bdecision=([^\s]+_decision\.json)", text)
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise AuditViolation(f"expected one guard decision in log, found {unique}")
    path = Path(unique[0])
    if not path.is_absolute():
        path = governance.ROOT / path
    return lexical_absolute(path)


def validate_guard(path: Path, arm: str) -> dict[str, object]:
    if not path.is_file():
        raise AuditViolation(f"missing guard decision: {path}")
    guard = json.loads(path.read_text(encoding="utf-8"))
    if arm == governance.M_ARM:
        expected = {
            "schema_version": "aqua-fe-p05-xfeat-backend-guard-decision-v1",
            "action": "ALLOW_M_XFEAT",
            "contract_hash": M_CONTRACT_HASH,
            "contract_pass": True,
            "counts_as_modern_baseline": True,
            "result_label": "M_XFEAT_PAIRWISE_NATIVEQ_V1",
            "run_vins": False,
        }
    elif arm == governance.P_ARM:
        expected = {
            "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
            "action": "ALLOW_LEARNED",
            "contract_hash": P_CONTRACT_HASH,
            "contract_pass": True,
            "counts_as_proposed_result": True,
            "result_label": "P_LEGACY_NATIVEQ",
        }
    else:  # pragma: no cover - queue_row rejects this first.
        raise AuditViolation(f"unsupported arm: {arm}")
    differences = {
        key: {"expected": value, "observed": guard.get(key)}
        for key, value in expected.items()
        if guard.get(key) != value
    }
    if differences or guard.get("reasons") != []:
        raise AuditViolation(
            f"guard is not the exact frozen PASS: differences={differences} "
            f"reasons={guard.get('reasons')}"
        )
    return guard


def parse_arbitration_summary(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    values: dict[str, list[str]] = defaultdict(list)
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or "=" not in raw:
            raise AuditViolation(f"invalid arbitration summary line {line_number}")
        key, value = raw.split("=", 1)
        if not key:
            raise AuditViolation(f"empty arbitration key on line {line_number}")
        values[key].append(value)
    for key in SUMMARY_UNIQUE_KEYS:
        if len(values.get(key, [])) != 1:
            raise AuditViolation(
                f"arbitration summary requires exactly one {key}, "
                f"found {values.get(key, [])}"
            )
    flattened = {key: entries[-1] for key, entries in values.items()}
    duplicates = {key: entries for key, entries in values.items() if len(entries) > 1}
    return flattened, duplicates


def _assert_immediate_tagged_child(path: Path, root: Path, tag: str, label: str) -> None:
    path = lexical_absolute(path)
    root = lexical_absolute(root)
    if path.parent != root or tag not in path.name:
        raise AuditViolation(
            f"{label} is not an immediate tagged child of the frozen root: {path}"
        )


def find_p_summary(row: dict[str, str]) -> Path:
    root = lexical_absolute(governance.ROOT / row["expected_run_root"])
    candidates = sorted(
        lexical_absolute(path)
        for path in root.glob(f"*{row['tag']}*/arbitration_summary.txt")
        if path.is_file()
    )
    if len(candidates) != 1:
        raise AuditViolation(
            f"expected one P arbitration summary for tag {row['tag']}, found {candidates}"
        )
    if candidates[0].parent.parent != root:
        raise AuditViolation("P arbitration summary is not directly under expected_run_root")
    return candidates[0]


def resolve_run_artifacts(
    row: dict[str, str],
) -> tuple[Path, Path, Path | None, dict[str, str] | None, dict[str, list[str]]]:
    root = lexical_absolute(governance.ROOT / row["expected_run_root"])
    if row["arm"] == governance.M_ARM:
        feature_bag = lexical_absolute(governance.ROOT / row["expected_feature_bag"])
        return feature_bag.parent, feature_bag, None, None, {}

    summary_path = find_p_summary(row)
    summary, duplicates = parse_arbitration_summary(summary_path)
    if summary["dataset_family"] != "aqualoc_archaeo":
        raise AuditViolation("A02 P arbitration summary has the wrong dataset family")
    if summary["profile"] not in VALID_P_PROFILES:
        raise AuditViolation(f"unfrozen P arbitration profile: {summary['profile']}")
    final_run = lexical_absolute(Path(summary["final_run"]))
    feature_bag = lexical_absolute(Path(summary["feature_bag"]))
    probe_run = lexical_absolute(Path(summary["probe_run"]))
    _assert_immediate_tagged_child(final_run, root, row["tag"], "final_run")
    _assert_immediate_tagged_child(probe_run, root, row["tag"], "probe_run")
    if final_run != summary_path.parent:
        raise AuditViolation("summary parent does not equal summary final_run")
    if feature_bag != final_run / "features.bag":
        raise AuditViolation("summary feature_bag does not equal final_run/features.bag")
    return final_run, feature_bag, probe_run, summary, duplicates


def expected_feature_frames(manifest: dict[str, str], dataset_family: str) -> int:
    input_frames = int(manifest["input_frame_count"])
    frame_offset = 0 if dataset_family == "afrl" else 1
    if input_frames <= frame_offset:
        return 0
    return ((input_frames - 1 - frame_offset) // 2) + 1


def channels(message) -> dict[str, list[float]]:
    names = [channel.name for channel in message.channels]
    if len(names) != len(set(names)):
        raise AuditViolation("duplicate feature channel")
    return {channel.name: list(channel.values) for channel in message.channels}


def _exact_nonnegative_int(value: float, label: str) -> int:
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or number < 0:
        raise AuditViolation(f"{label} is not an exact nonnegative integer")
    return int(number)


def audit_feature_bag(path: Path, *, arm: str, expected_frames: int) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AuditViolation(f"missing or empty feature bag: {path}")
    topic_counts: Counter[str] = Counter()
    source_counts: Counter[int] = Counter()
    learned_flags: Counter[int] = Counter()
    feature_counts: list[int] = []
    feature_stamps: list[float] = []
    q_min = float("inf")
    q_max = float("-inf")
    sigma_min = float("inf")
    sigma_max = float("-inf")
    observations = 0
    finite_names = ("p_u", "p_v", "velocity_x", "velocity_y", "gx", "gy", "gz")

    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _record_stamp in bag.read_messages():
            topic_counts[topic] += 1
            if topic != FEATURE_TOPIC:
                continue
            count = len(message.points)
            if count < 0 or count > 350:
                raise AuditViolation(f"feature cap violated: {count}")
            feature_counts.append(count)
            feature_stamps.append(float(message.header.stamp.to_sec()))
            values = channels(message)
            if set(values) != REQUIRED_CHANNELS:
                raise AuditViolation(
                    f"feature channel set mismatch: {sorted(set(values) ^ REQUIRED_CHANNELS)}"
                )
            if any(len(values[name]) != count for name in REQUIRED_CHANNELS):
                raise AuditViolation("feature channel length mismatch")
            ids = [
                _exact_nonnegative_int(value, f"id[{index}]")
                for index, value in enumerate(values["id"])
            ]
            if len(ids) != len(set(ids)):
                raise AuditViolation("duplicate feature ID within a frame")
            if any(_exact_nonnegative_int(value, "camera_id") != 0 for value in values["camera_id"]):
                raise AuditViolation("camera_id must be zero")
            if any(
                not math.isfinite(float(value))
                for name in finite_names
                for value in values[name]
            ):
                raise AuditViolation("non-finite feature geometry channel")
            if any(
                not all(math.isfinite(float(value)) for value in (point.x, point.y, point.z))
                for point in message.points
            ):
                raise AuditViolation("non-finite feature point geometry")

            for index, (raw_source, raw_learned, raw_q, raw_sigma) in enumerate(
                zip(
                    values["source_code"],
                    values["is_learned"],
                    values["quality"],
                    values["sigma"],
                )
            ):
                source = _exact_nonnegative_int(raw_source, f"source_code[{index}]")
                learned = _exact_nonnegative_int(raw_learned, f"is_learned[{index}]")
                if learned not in {0, 1}:
                    raise AuditViolation("is_learned must be binary")
                if arm == governance.M_ARM and (source != 20 or learned != 1):
                    raise AuditViolation("M requires source_code=20 and is_learned=1")
                if arm == governance.P_ARM and source not in {1, 2, 10, 20, 30}:
                    raise AuditViolation(f"P contains unsupported source code {source}")
                q = float(raw_q)
                sigma = float(raw_sigma)
                if not math.isfinite(q) or q < 0.8 - 1e-6 or q > 1.0 + 1e-6:
                    raise AuditViolation(f"quality outside [0.8,1]: {q}")
                if not math.isfinite(sigma) or not math.isclose(
                    sigma, 1.0 / math.sqrt(q), rel_tol=0.0, abs_tol=2e-6
                ):
                    raise AuditViolation("sigma is inconsistent with native q")
                source_counts[source] += 1
                learned_flags[learned] += 1
                observations += 1
                q_min = min(q_min, q)
                q_max = max(q_max, q)
                sigma_min = min(sigma_min, sigma)
                sigma_max = max(sigma_max, sigma)

    if len(feature_counts) != expected_frames:
        raise AuditViolation(
            f"feature frame count mismatch: {len(feature_counts)} != {expected_frames}"
        )
    if observations == 0:
        raise AuditViolation("feature bag contains no observations")
    if any(right <= left for left, right in zip(feature_stamps, feature_stamps[1:])):
        raise AuditViolation("feature timestamps are not strictly increasing")
    if topic_counts["/rtimulib_node/imu"] != 9091:
        raise AuditViolation("A02 export does not contain exactly 9091 copied IMU messages")
    if topic_counts["/aqualoc/colmap_gt"] != 46:
        raise AuditViolation("A02 export does not contain exactly 46 copied reference messages")
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "topic_counts": dict(sorted(topic_counts.items())),
        "feature_frames": len(feature_counts),
        "feature_observations": observations,
        "zero_feature_frames": sum(count == 0 for count in feature_counts),
        "min_features_per_frame": min(feature_counts),
        "max_features_per_frame": max(feature_counts),
        "source_counts": {str(key): value for key, value in sorted(source_counts.items())},
        "is_learned_counts": {
            str(key): value for key, value in sorted(learned_flags.items())
        },
        "quality_min": q_min,
        "quality_max": q_max,
        "sigma_min": sigma_min,
        "sigma_max": sigma_max,
        "feature_start_stamp": feature_stamps[0],
        "feature_end_stamp": feature_stamps[-1],
    }


def _count_column(rows: list[dict[str, str]], key: str) -> list[int]:
    counts: list[int] = []
    for row_number, row in enumerate(rows, 2):
        raw = row.get(key, "")
        try:
            value = float(raw)
        except ValueError as exc:
            raise AuditViolation(f"invalid {key} on metrics row {row_number}") from exc
        if not math.isfinite(value) or not value.is_integer() or value < 0:
            raise AuditViolation(f"non-count {key} on metrics row {row_number}")
        counts.append(int(value))
    return counts


def audit_metrics(path: Path, *, arm: str, bag_stats: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        raise AuditViolation(f"missing frontend metrics: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise AuditViolation("invalid frontend metrics header")
        rows = list(reader)
    if not rows or any(None in row for row in rows):
        raise AuditViolation("empty or ragged frontend metrics")
    if len(rows) != int(bag_stats["feature_frames"]):
        raise AuditViolation("metrics row count does not match feature frames")
    exported = _count_column(rows, "exported_features")
    if sum(exported) != int(bag_stats["feature_observations"]):
        raise AuditViolation("metrics exported feature total does not match bag")
    if arm == governance.M_ARM:
        xfeat = _count_column(rows, "exported_xfeat_features")
        if xfeat != exported:
            raise AuditViolation("M metrics do not report every observation as XFeat")
        if any(
            count > 0 and not (row.get("export_source_histogram") or "").startswith("xfeat:")
            for count, row in zip(exported, rows)
        ):
            raise AuditViolation("M metrics contain a non-XFeat source histogram")
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "rows": len(rows),
        "exported_feature_observations": sum(exported),
    }


def learned_lineage_stats(path: Path) -> dict[str, object]:
    first_occurrence: dict[int, tuple[int, int, bool]] = {}
    lineage_ids: set[int] = set()
    lineage_observations: Counter[int] = Counter()
    birth_rows: list[dict[str, int]] = []
    feature_frames = 0
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, message, _stamp in bag.read_messages(topics=[FEATURE_TOPIC]):
            frame_index = feature_frames
            feature_frames += 1
            values = channels(message)
            count = len(message.points)
            for name in ("id", "source_code", "is_learned"):
                if name not in values or len(values[name]) != count:
                    raise AuditViolation(f"lineage scan missing or mis-sized {name}")
            for observation_index, (raw_id, raw_source, raw_learned) in enumerate(
                zip(values["id"], values["source_code"], values["is_learned"])
            ):
                feature_id = _exact_nonnegative_int(raw_id, "lineage id")
                source = _exact_nonnegative_int(raw_source, "lineage source_code")
                learned = _exact_nonnegative_int(raw_learned, "lineage is_learned")
                if learned not in {0, 1}:
                    raise AuditViolation("lineage is_learned must be binary")
                marker = bool(learned or source in LEARNED_SOURCE_CODES)
                if feature_id not in first_occurrence:
                    first_occurrence[feature_id] = (frame_index, observation_index, marker)
                    if marker:
                        lineage_ids.add(feature_id)
                        birth_rows.append(
                            {
                                "feature_id": feature_id,
                                "birth_feature_frame": frame_index,
                                "birth_observation_index": observation_index,
                            }
                        )
                elif marker and feature_id not in lineage_ids:
                    first_frame, first_index, _ = first_occurrence[feature_id]
                    raise AuditViolation(
                        "learned provenance appears after an unmarked first observation: "
                        f"id={feature_id} first={first_frame}:{first_index} "
                        f"marker={frame_index}:{observation_index}"
                    )
                if feature_id in lineage_ids:
                    lineage_observations[feature_id] += 1
    return {
        "accepted_learned_born_lineage_count": len(lineage_ids),
        "learned_born_feature_ids": sorted(lineage_ids),
        "learned_born_observations": sum(lineage_observations.values()),
        "lineage_observation_counts": {
            str(key): lineage_observations[key] for key in sorted(lineage_observations)
        },
        "births": birth_rows,
        "feature_frames": feature_frames,
        "distinct_feature_ids": len(first_occurrence),
        "birth_rule": "first ID occurrence has is_learned=1 or source_code in {10,20,30}",
        "late_marker_policy": "FAIL_CLOSED",
    }


def forbidden_outcomes(run_dirs: list[Path]) -> list[str]:
    found: list[str] = []
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        for path in run_dir.rglob("*"):
            if path.is_file() and path.name.lower() in FORBIDDEN_OUTCOME_NAMES:
                found.append(display_path(path))
    return sorted(set(found))


def corresponding_b1_bag(window_id: str) -> Path:
    rows = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if row["window_id"] == window_id and row["arm"] == governance.B1
    ]
    if len(rows) != 1 or not rows[0]["expected_feature_bag"]:
        raise AuditViolation(f"expected one B1 bag allocation for {window_id}")
    return lexical_absolute(governance.ROOT / rows[0]["expected_feature_bag"])


def build_audit(
    *, index: int, command_log: Path, attestation: Path
) -> dict[str, object]:
    row = queue_row(index)
    allocation = allocation_row(index)
    manifest = manifest_row(row["window_id"])
    if index not in {2, 3} or row["window_id"] != "aqualoc_archaeology:A02:0005":
        raise AuditViolation("M/P auditor v2 is frozen only for A02 queue indices 2 and 3")
    if allocation["run_id"] == "" or allocation["arm"] != row["arm"]:
        raise AuditViolation("queue/allocation identity mismatch")

    command_text = command_log.read_text(encoding="utf-8", errors="replace")
    if row["arm"] == governance.M_ARM:
        if "P05 XFeat backend contract PASS" not in command_text or "contract rejected M" in command_text:
            raise AuditViolation("M command log does not prove the non-fallback guard branch")
    else:
        if "native-q backend contract PASS" not in command_text or "contract rejected learned" in command_text:
            raise AuditViolation("P command log does not prove the non-fallback guard branch")
    guard_path = parse_guard_path(command_log)
    guard = validate_guard(guard_path, row["arm"])

    run_dir, feature_bag, probe_run, summary, duplicates = resolve_run_artifacts(row)
    metrics_path = run_dir / "frontend_metrics.csv"
    expected_frames = expected_feature_frames(manifest, row["dataset_family"])
    bag = audit_feature_bag(feature_bag, arm=row["arm"], expected_frames=expected_frames)
    metrics = audit_metrics(metrics_path, arm=row["arm"], bag_stats=bag)
    if not attestation.is_file():
        raise AuditViolation(f"missing arm attestation: {attestation}")
    attested = json.loads(attestation.read_text(encoding="utf-8"))

    lineage: dict[str, object] | None = None
    zero_action: dict[str, object] | None = None
    if row["arm"] == governance.M_ARM:
        if (
            attested.get("schema_version") != "aqua-fe-p05-xfeat-bag-attestation-v1"
            or attested.get("status") != "PASS"
            or attested.get("contract_pass") is not True
            or attested.get("backend_contract_hash") != M_CONTRACT_HASH
            or attested.get("feature_bag_sha256") != bag["sha256"]
            or int(attested.get("bag_audit", {}).get("feature_frames", -1)) != expected_frames
            or int(attested.get("bag_audit", {}).get("feature_observations", -1))
            != int(bag["feature_observations"])
        ):
            raise AuditViolation("M P05 attestation does not bind the audited bag")
    else:
        if (
            attested.get("schema_version") != "aqua-fe-nativeq-bag-attestation-v1"
            or attested.get("contract_pass") is not True
            or attested.get("backend_contract_hash") != P_CONTRACT_HASH
            or attested.get("feature_bag_sha256") != bag["sha256"]
            or int(attested.get("feature_frames", -1)) != expected_frames
            or int(attested.get("feature_observations", -1))
            != int(bag["feature_observations"])
        ):
            raise AuditViolation("P native-q attestation does not bind the audited bag")
        lineage = learned_lineage_stats(feature_bag)
        if lineage["feature_frames"] != expected_frames:
            raise AuditViolation("P lineage scan frame count mismatch")
        if int(lineage["accepted_learned_born_lineage_count"]) == 0:
            b1_bag = corresponding_b1_bag(row["window_id"])
            if not b1_bag.is_file():
                raise AuditViolation("zero-action P cannot be checked because B1 is missing")
            b1_hash = sha256(b1_bag)
            if bag["sha256"] != b1_hash:
                raise AuditViolation("zero-action P is not byte-identical to frozen B1")
            zero_action = {
                "status": "PASS_BYTE_IDENTICAL_TO_B1",
                "b1_feature_bag": display_path(b1_bag),
                "b1_feature_bag_sha256": b1_hash,
                "p_feature_bag_sha256": bag["sha256"],
            }

    run_dirs = [run_dir]
    if probe_run is not None and probe_run not in run_dirs:
        run_dirs.append(probe_run)
    forbidden = forbidden_outcomes(run_dirs)
    if forbidden:
        raise AuditViolation(f"trajectory outcome artifact found: {forbidden}")

    return {
        "schema_version": "isj-p07-mp-frontend-export-audit-v2",
        "status": "PASS",
        "queue_index": index,
        "run_id": allocation["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "command_sha256": row["command_sha256"],
        "checks": {
            "queue_allocation_exact": True,
            "guard_exact_nonfallback_pass": True,
            "complete_13_channel_schema": True,
            "feature_cap_and_native_q_pass": True,
            "metrics_match_bag": True,
            "sensor_and_reference_topics_exact": True,
            "arm_attestation_bound": True,
            "p_final_run_summary_bound": row["arm"] == governance.P_ARM,
            "no_trajectory_outcome_artifacts": True,
        },
        "guard": {
            "path": display_path(guard_path),
            "sha256": sha256(guard_path),
            "schema_version": guard["schema_version"],
            "action": guard["action"],
            "contract_hash": guard["contract_hash"],
        },
        "run_dir": display_path(run_dir),
        "probe_run": display_path(probe_run) if probe_run is not None else None,
        "feature_bag": bag,
        "frontend_metrics": metrics,
        "attestation": {
            "path": display_path(attestation),
            "sha256": sha256(attestation),
            "schema_version": attested["schema_version"],
        },
        "arbitration_summary": (
            {
                "path": display_path(run_dir / "arbitration_summary.txt"),
                "sha256": sha256(run_dir / "arbitration_summary.txt"),
                "profile": summary["profile"],
                "duplicate_diagnostic_keys": sorted(duplicates),
            }
            if summary is not None
            else None
        ),
        "learned_lineages": lineage,
        "zero_action_identity": zero_action,
        "forbidden_outcome_artifacts": [],
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--command-log", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    payload = build_audit(
        index=args.queue_index,
        command_log=args.command_log,
        attestation=args.attestation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"P07_MP_FRONTEND_EXPORT_AUDIT_V2_PASS queue_index={args.queue_index} "
        f"frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
