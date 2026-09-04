#!/usr/bin/env python3
"""Audit one frozen P07 A01 B1/P/M export without trajectory outcomes."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

import rosbag

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_mp_frontend_export_v2 as v2
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_mp_frontend_export_v2 as v2  # type: ignore


FEATURE_TOPIC = v2.FEATURE_TOPIC
REQUIRED_CHANNELS = v2.REQUIRED_CHANNELS
P_CONTRACT_HASH = v2.P_CONTRACT_HASH
M_CONTRACT_HASH = v2.M_CONTRACT_HASH
A01_WINDOW_ID = "aqualoc_archaeology:A01:0018"
ALLOWED_INDICES = (4, 5, 6)

AuditViolation = v2.AuditViolation
sha256 = v2.sha256
display_path = v2.display_path
lexical_absolute = v2.lexical_absolute
parse_guard_path = v2.parse_guard_path
parse_arbitration_summary = v2.parse_arbitration_summary
learned_lineage_stats = v2.learned_lineage_stats
forbidden_outcomes = v2.forbidden_outcomes


def queue_row(index: int) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if int(row["queue_index"]) == index
    ]
    if len(matches) != 1:
        raise AuditViolation(f"expected one queue row for index {index}")
    row = matches[0]
    if index not in ALLOWED_INDICES or row["window_id"] != A01_WINDOW_ID:
        raise AuditViolation("A01 auditor v3 allows only queue indices 4, 5, and 6")
    if row["arm"] not in {governance.B1, governance.P_ARM, governance.M_ARM}:
        raise AuditViolation(f"unsupported A01 arm: {row['arm']}")
    observed = v2.hashlib.sha256(row["command"].encode("utf-8")).hexdigest()
    if observed != row["command_sha256"]:
        raise AuditViolation("queue command hash mismatch")
    return row


def allocation_row(index: int) -> dict[str, str]:
    return v2.allocation_row(index)


def manifest_row(window_id: str) -> dict[str, str]:
    return v2.manifest_row(window_id)


def validate_guard(path: Path, arm: str) -> dict[str, object]:
    if arm != governance.B1:
        return v2.validate_guard(path, arm)
    if not path.is_file():
        raise AuditViolation(f"missing B1 guard decision: {path}")
    guard = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
        "action": "ALLOW_B1_KLT_NATIVEQ",
        "contract_hash": P_CONTRACT_HASH,
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


def expected_raw_bag(row: dict[str, str], allocation: dict[str, str]) -> Path:
    sequence_number = int(row["sequence"][1:])
    return lexical_absolute(
        governance.ROOT
        / (
            f"datasets/aqualoc/rosbags/archaeo{sequence_number:02d}_"
            f"{allocation['window_start']}_{allocation['window_end']}.bag"
        )
    )


def audit_raw_bag(path: Path, *, expected_images: int) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AuditViolation(f"missing or empty A01 raw bag: {path}")
    with rosbag.Bag(str(path), "r") as bag:
        info = bag.get_type_and_topic_info().topics
        counts = {topic: int(value.message_count) for topic, value in info.items()}
    if counts.get("/camera/image_raw") != expected_images:
        raise AuditViolation(
            f"A01 raw image count mismatch: {counts.get('/camera/image_raw')} != {expected_images}"
        )
    if counts.get("/rtimulib_node/imu", 0) <= 0:
        raise AuditViolation("A01 raw bag has no IMU messages")
    if counts.get("/aqualoc/colmap_gt", 0) <= 0:
        raise AuditViolation("A01 raw bag has no reference messages")
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "topic_counts": dict(sorted(counts.items())),
    }


def _exact_nonnegative_int(value: float, label: str) -> int:
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or number < 0:
        raise AuditViolation(f"{label} is not an exact nonnegative integer")
    return int(number)


def audit_feature_bag(
    path: Path,
    *,
    arm: str,
    expected_frames: int,
    raw_stats: dict[str, object],
) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AuditViolation(f"missing or empty feature bag: {path}")
    topic_counts: Counter[str] = Counter()
    source_counts: Counter[int] = Counter()
    learned_flags: Counter[int] = Counter()
    feature_counts: list[int] = []
    feature_stamps: list[float] = []
    observations = 0
    q_min = float("inf")
    q_max = float("-inf")
    sigma_min = float("inf")
    sigma_max = float("-inf")
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
            values = v2.channels(message)
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
            if any(
                _exact_nonnegative_int(value, "camera_id") != 0
                for value in values["camera_id"]
            ):
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
                if arm == governance.B1 and (source not in {1, 2} or learned != 0):
                    raise AuditViolation("B1 requires classical source 1/2 and is_learned=0")
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
    raw_topics = raw_stats["topic_counts"]
    for topic in ("/rtimulib_node/imu", "/aqualoc/colmap_gt"):
        if topic_counts[topic] != int(raw_topics[topic]):
            raise AuditViolation(
                f"copied topic count mismatch for {topic}: "
                f"{topic_counts[topic]} != {raw_topics[topic]}"
            )
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


def audit_metrics(path: Path, *, arm: str, bag_stats: dict[str, object]) -> dict[str, object]:
    result = v2.audit_metrics(path, arm=arm, bag_stats=bag_stats)
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


def resolve_run_artifacts(
    row: dict[str, str],
) -> tuple[Path, Path, Path | None, dict[str, str] | None, dict[str, list[str]]]:
    if row["arm"] in {governance.B1, governance.M_ARM}:
        feature_bag = lexical_absolute(governance.ROOT / row["expected_feature_bag"])
        return feature_bag.parent, feature_bag, None, None, {}
    return v2.resolve_run_artifacts(row)


def corresponding_b1_bag(window_id: str) -> Path:
    rows = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if row["window_id"] == window_id and row["arm"] == governance.B1
    ]
    if len(rows) != 1 or not rows[0]["expected_feature_bag"]:
        raise AuditViolation(f"expected one B1 bag for {window_id}")
    return lexical_absolute(governance.ROOT / rows[0]["expected_feature_bag"])


def build_audit(
    *, index: int, command_log: Path, attestation: Path
) -> dict[str, object]:
    row = queue_row(index)
    allocation = allocation_row(index)
    manifest = manifest_row(row["window_id"])
    if allocation["arm"] != row["arm"] or allocation["window_id"] != row["window_id"]:
        raise AuditViolation("queue/allocation identity mismatch")
    command_text = command_log.read_text(encoding="utf-8", errors="replace")
    if row["arm"] == governance.B1:
        if "B1_KLT_NATIVEQ_GUARD action=ALLOW_B1_KLT_NATIVEQ" not in command_text:
            raise AuditViolation("B1 command log does not prove exact guard PASS")
    elif row["arm"] == governance.M_ARM:
        if "P05 XFeat backend contract PASS" not in command_text or "contract rejected M" in command_text:
            raise AuditViolation("M command log does not prove the nonfallback guard branch")
    else:
        if "native-q backend contract PASS" not in command_text or "contract rejected learned" in command_text:
            raise AuditViolation("P command log does not prove the nonfallback guard branch")
    guard_path = parse_guard_path(command_log)
    guard = validate_guard(guard_path, row["arm"])

    raw_path = expected_raw_bag(row, allocation)
    expected_images = int(allocation["window_end"]) - int(allocation["window_start"]) + 1
    raw = audit_raw_bag(raw_path, expected_images=expected_images)
    run_dir, feature_bag, probe_run, summary, duplicates = resolve_run_artifacts(row)
    expected_frames = v2.expected_feature_frames(manifest, row["dataset_family"])
    bag = audit_feature_bag(
        feature_bag,
        arm=row["arm"],
        expected_frames=expected_frames,
        raw_stats=raw,
    )
    metrics = audit_metrics(
        run_dir / "frontend_metrics.csv", arm=row["arm"], bag_stats=bag
    )
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
            raise AuditViolation("M attestation does not bind the audited bag")
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
        if row["arm"] == governance.B1 and int(attested.get("learned_observations", -1)) != 0:
            raise AuditViolation("B1 attestation reports learned observations")
        if row["arm"] == governance.P_ARM:
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
        "schema_version": "isj-p07-a01-frontend-export-audit-v3",
        "status": "PASS",
        "queue_index": index,
        "run_id": allocation["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "command_sha256": row["command_sha256"],
        "checks": {
            "queue_allocation_exact": True,
            "guard_exact_nonfallback_pass": True,
            "raw_bag_and_copied_topics_exact": True,
            "complete_13_channel_schema": True,
            "feature_cap_and_native_q_pass": True,
            "metrics_match_bag": True,
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
        "raw_bag": raw,
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
        f"P07_A01_FRONTEND_EXPORT_AUDIT_V3_PASS queue_index={args.queue_index} "
        f"frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
