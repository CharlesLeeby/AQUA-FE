#!/usr/bin/env python3
"""Audit any frozen P07 B1/M/P frontend export without trajectory access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import rosbag

try:
    from scripts import audit_p07_mp_frontend_export_v2 as base
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_mp_frontend_export_v2 as base  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


AuditViolation = base.AuditViolation
FEATURE_TOPIC = base.FEATURE_TOPIC
REQUIRED_CHANNELS = base.REQUIRED_CHANNELS
LEARNED_SOURCE_CODES = base.LEARNED_SOURCE_CODES
M_CONTRACT_HASH = base.M_CONTRACT_HASH
P_CONTRACT_HASH = base.P_CONTRACT_HASH
B1_CONTRACT_HASH = P_CONTRACT_HASH
FORBIDDEN_OUTCOME_NAMES = base.FORBIDDEN_OUTCOME_NAMES

lexical_absolute = base.lexical_absolute
display_path = base.display_path
sha256 = base.sha256
allocation_row = base.allocation_row
manifest_row = base.manifest_row
parse_guard_path = base.parse_guard_path
parse_arbitration_summary = base.parse_arbitration_summary
expected_feature_frames = base.expected_feature_frames
channels = base.channels
_exact_nonnegative_int = base._exact_nonnegative_int
learned_lineage_stats = base.learned_lineage_stats
forbidden_outcomes = base.forbidden_outcomes
corresponding_b1_bag = base.corresponding_b1_bag


P_SUMMARY_FAMILY = {
    "aqualoc_archaeology": "aqualoc_archaeo",
    "aqualoc_harbor": "aqualoc_real",
    "ntnu": "ntnu",
    "afrl": "afrl",
}

SENSOR_TOPIC_REQUIREMENTS = {
    "aqualoc_archaeology": ("/rtimulib_node/imu", "/aqualoc/colmap_gt"),
    "aqualoc_harbor": ("/rtimulib_node/imu", "/aqualoc/colmap_gt"),
    "ntnu": ("/alphasense_driver_ros/imu",),
    "afrl": ("/imu/imu", "/afrl/colmap_gt"),
}


def queue_row(index: int) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if int(row["queue_index"]) == index
    ]
    if len(matches) != 1:
        raise AuditViolation(f"expected one queue row for index {index}")
    row = matches[0]
    if row["arm"] not in {governance.B1, governance.M_ARM, governance.P_ARM}:
        raise AuditViolation(f"unsupported frontend arm {row['arm']}")
    observed = hashlib.sha256(row["command"].encode("utf-8")).hexdigest()
    if observed != row["command_sha256"]:
        raise AuditViolation("queue command hash mismatch")
    return row


def validate_guard(path: Path, arm: str) -> dict[str, object]:
    if arm != governance.B1:
        return base.validate_guard(path, arm)
    if not path.is_file():
        raise AuditViolation(f"missing guard decision: {path}")
    guard = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
        "action": "ALLOW_B1_KLT_NATIVEQ",
        "contract_hash": B1_CONTRACT_HASH,
        "contract_pass": True,
        "counts_as_b1": True,
        "counts_as_proposed_result": False,
        "result_label": "B1_KLT_NATIVEQ_V3",
    }
    differences = {
        key: {"expected": value, "observed": guard.get(key)}
        for key, value in expected.items()
        if guard.get(key) != value
    }
    if differences or guard.get("reasons") != []:
        raise AuditViolation(
            f"B1 guard is not the exact frozen PASS: differences={differences} "
            f"reasons={guard.get('reasons')}"
        )
    return guard


def _assert_immediate_tagged_child(path: Path, root: Path, tag: str, label: str) -> None:
    path = lexical_absolute(path)
    root = lexical_absolute(root)
    if path.parent != root or tag not in path.name:
        raise AuditViolation(
            f"{label} is not an immediate tagged child of the frozen root: {path}"
        )


def resolve_run_artifacts(
    row: dict[str, str],
) -> tuple[Path, Path, Path | None, dict[str, str] | None, dict[str, list[str]]]:
    root = lexical_absolute(governance.ROOT / row["expected_run_root"])
    if row["arm"] in {governance.B1, governance.M_ARM}:
        feature_bag = lexical_absolute(governance.ROOT / row["expected_feature_bag"])
        return feature_bag.parent, feature_bag, None, None, {}

    summary_path = base.find_p_summary(row)
    summary, duplicates = parse_arbitration_summary(summary_path)
    expected_family = P_SUMMARY_FAMILY.get(row["dataset_family"])
    if summary["dataset_family"] != expected_family:
        raise AuditViolation(
            "P arbitration dataset family mismatch: "
            f"{summary['dataset_family']} != {expected_family}"
        )
    if summary["profile"] not in base.VALID_P_PROFILES:
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


def audit_feature_bag(
    path: Path,
    *,
    arm: str,
    expected_frames: int,
    dataset_family: str,
) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AuditViolation(f"missing or empty feature bag: {path}")
    required_topics = SENSOR_TOPIC_REQUIREMENTS.get(dataset_family)
    if required_topics is None:
        raise AuditViolation(f"unsupported dataset family {dataset_family}")

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
            if count < 0 or count > 350 or (arm == governance.B1 and count == 0):
                raise AuditViolation(f"invalid feature count for {arm}: {count}")
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
                _exact_nonnegative_int(value, f"id[{idx}]")
                for idx, value in enumerate(values["id"])
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

            for idx, (raw_source, raw_learned, raw_q, raw_sigma) in enumerate(
                zip(
                    values["source_code"],
                    values["is_learned"],
                    values["quality"],
                    values["sigma"],
                )
            ):
                source = _exact_nonnegative_int(raw_source, f"source_code[{idx}]")
                learned = _exact_nonnegative_int(raw_learned, f"is_learned[{idx}]")
                if learned not in {0, 1}:
                    raise AuditViolation("is_learned must be binary")
                if arm == governance.B1 and (source not in {1, 2} or learned != 0):
                    raise AuditViolation("B1 must contain classical, unmarked observations only")
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
    missing_topics = [topic for topic in required_topics if topic_counts[topic] <= 0]
    if missing_topics:
        raise AuditViolation(f"copied sensor/reference topics missing: {missing_topics}")
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "topic_counts": dict(sorted(topic_counts.items())),
        "required_sensor_reference_topics": list(required_topics),
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


def audit_metrics(path: Path, *, arm: str, bag_stats: dict[str, object]) -> dict[str, object]:
    result = base.audit_metrics(path, arm=arm, bag_stats=bag_stats)
    if arm != governance.B1:
        return result
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    learned_columns = (
        "exported_learned_features",
        "exported_non_loftr_learned_features",
        "exported_sp_lg_features",
        "exported_xfeat_features",
        "exported_loftr_features",
    )
    for name in learned_columns:
        if rows and name in rows[0] and any(int(float(row.get(name) or 0)) for row in rows):
            raise AuditViolation(f"B1 metrics report learned export in {name}")
    return result


def _command_guard_marker(arm: str) -> tuple[str, str]:
    if arm == governance.B1:
        return "B1_KLT_NATIVEQ_GUARD action=ALLOW_B1_KLT_NATIVEQ", "contract rejected B1"
    if arm == governance.M_ARM:
        return "P05 XFeat backend contract PASS", "contract rejected M"
    return "native-q backend contract PASS", "contract rejected learned"


def build_audit(
    *, index: int, command_log: Path, attestation: Path
) -> dict[str, object]:
    row = queue_row(index)
    allocation = allocation_row(index)
    manifest = manifest_row(row["window_id"])
    if allocation["run_id"] == "" or allocation["arm"] != row["arm"]:
        raise AuditViolation("queue/allocation identity mismatch")

    required_marker, forbidden_marker = _command_guard_marker(row["arm"])
    command_text = command_log.read_text(encoding="utf-8", errors="replace")
    if required_marker not in command_text or forbidden_marker in command_text:
        raise AuditViolation("command log does not prove the non-fallback guard branch")
    guard_path = parse_guard_path(command_log)
    guard = validate_guard(guard_path, row["arm"])

    run_dir, feature_bag, probe_run, summary, duplicates = resolve_run_artifacts(row)
    metrics_path = run_dir / "frontend_metrics.csv"
    expected_frames = expected_feature_frames(manifest, row["dataset_family"])
    bag = audit_feature_bag(
        feature_bag,
        arm=row["arm"],
        expected_frames=expected_frames,
        dataset_family=row["dataset_family"],
    )
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
            raise AuditViolation("native-q attestation does not bind the audited bag")
        if row["arm"] == governance.B1:
            if int(attested.get("learned_observations", -1)) != 0:
                raise AuditViolation("B1 native-q attestation reports learned observations")
        else:
            lineage = learned_lineage_stats(feature_bag)
            if lineage["feature_frames"] != expected_frames:
                raise AuditViolation("P lineage scan frame count mismatch")
            if int(lineage["accepted_learned_born_lineage_count"]) == 0:
                b1_bag = corresponding_b1_bag(row["window_id"])
                if b1_bag.is_file():
                    b1_hash = sha256(b1_bag)
                    if bag["sha256"] != b1_hash:
                        raise AuditViolation("zero-action P is not byte-identical to frozen B1")
                    zero_action = {
                        "status": "PASS_BYTE_IDENTICAL_TO_B1",
                        "b1_feature_bag": display_path(b1_bag),
                        "b1_feature_bag_sha256": b1_hash,
                        "p_feature_bag_sha256": bag["sha256"],
                    }
                else:
                    zero_action = {
                        "status": "DEFERRED_UNTIL_FROZEN_B1_EXPORT",
                        "b1_feature_bag": display_path(b1_bag),
                        "p_feature_bag_sha256": bag["sha256"],
                    }

    run_dirs = [run_dir]
    if probe_run is not None and probe_run not in run_dirs:
        run_dirs.append(probe_run)
    forbidden = forbidden_outcomes(run_dirs)
    if forbidden:
        raise AuditViolation(f"trajectory outcome artifact found: {forbidden}")

    return {
        "schema_version": "isj-p07-frontend-export-audit-v3",
        "status": "PASS",
        "queue_index": index,
        "run_id": allocation["run_id"],
        "window_id": row["window_id"],
        "dataset_family": row["dataset_family"],
        "arm": row["arm"],
        "command_sha256": row["command_sha256"],
        "checks": {
            "queue_allocation_exact": True,
            "guard_exact_nonfallback_pass": True,
            "complete_13_channel_schema": True,
            "feature_cap_and_native_q_pass": True,
            "metrics_match_bag": True,
            "required_sensor_reference_topics_present": True,
            "arm_attestation_bound": True,
            "p_final_run_summary_bound": row["arm"] == governance.P_ARM,
            "zero_action_identity_terminal_or_deferred": (
                zero_action is None
                or zero_action["status"] in {
                    "PASS_BYTE_IDENTICAL_TO_B1",
                    "DEFERRED_UNTIL_FROZEN_B1_EXPORT",
                }
            ),
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
        f"P07_FRONTEND_EXPORT_AUDIT_V3_PASS queue_index={args.queue_index} "
        f"arm={payload['arm']} frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
