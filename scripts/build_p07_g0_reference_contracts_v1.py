#!/usr/bin/env python3
"""Build outcome-blind absolute-reference contracts for P07 G0.

The formal builder is intentionally separate from replay/evaluation.  For
AQUALOC and AFRL it reads only the frozen B1 bag reference-topic timestamps;
for NTNU it filters the checksum-bound baseline TUM timestamps by the frozen
relative selection interval.  Pose values and backend trajectories are never
read.  The resulting first/last *reference samples* are stored as exact
integer nanoseconds and are shared by every arm/replay of a window.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from decimal import Decimal, InvalidOperation
import fcntl
import io
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

try:
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
except ModuleNotFoundError:
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore


SCHEMA_VERSION = "isj-p07-g0-reference-contracts-v1"
STATUS = "FROZEN_ABSOLUTE_REFERENCE_ENDPOINTS_PREOUTCOME"
OUTCOME_BOUNDARY = (
    "REFERENCE_TIMESTAMP_IDENTITY_ONLY_NO_BACKEND_TRAJECTORY_APE_RPE_RESULT_READ"
)
CHECKS = {
    "reference_only_no_backend_trajectory_read": True,
    "absolute_integer_ns_endpoints": True,
    "first_last_actual_reference_samples_not_nominal_duration": True,
    "same_window_contract_shared_across_arms_replays": True,
    "queue_relative_seconds_not_used_as_absolute_epoch": True,
}

REFERENCE_TOPICS = {
    "aqualoc_archaeology": "/aqualoc/colmap_gt",
    "aqualoc_harbor": "/aqualoc/colmap_gt",
    "afrl": "/afrl/colmap_gt",
}


def decimal_seconds_to_ns(value: str) -> int:
    try:
        scaled = Decimal(value.strip()) * Decimal(1_000_000_000)
    except (InvalidOperation, AttributeError) as error:
        raise gov.G0GovernanceError(f"invalid reference timestamp: {value!r}") from error
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise gov.G0GovernanceError(
            f"reference timestamp has sub-nanosecond precision: {value!r}"
        )
    result = int(integral)
    if result < 100_000_000 * 1_000_000_000:
        raise gov.G0GovernanceError(
            "reference timestamps must be absolute epoch nanoseconds"
        )
    return result


def ns_to_decimal_seconds(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise gov.G0GovernanceError("nanosecond timestamp must be an integer")
    return format(Decimal(value) / Decimal(1_000_000_000), "f")


def tum_timestamp_ns_bytes(content: bytes, *, label: str) -> list[int]:
    values: list[int] = []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid TUM UTF-8: {label}") from error
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token = stripped.split()[0]
        try:
            value = decimal_seconds_to_ns(token)
        except gov.G0GovernanceError as error:
            raise gov.G0GovernanceError(
                f"{label}:{line_number}: invalid TUM timestamp"
            ) from error
        values.append(value)
    if len(values) < 2 or any(right <= left for left, right in zip(values, values[1:])):
        raise gov.G0GovernanceError(
            f"TUM reference timestamps are not strictly increasing: {label}"
        )
    return values


def tum_timestamp_ns(path: Path, *, root: Path | None = None) -> list[int]:
    anchor = root if root is not None else path.parent
    content = publisher.read_bytes_bound_input_rooted(
        anchor, path, label="TUM reference"
    )
    return tum_timestamp_ns_bytes(content, label=gov.display_path(anchor, path))


@contextmanager
def _sealed_snapshot_path(content: bytes) -> Iterator[Path]:
    required_os = ("memfd_create", "MFD_ALLOW_SEALING")
    required_fcntl = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    if any(not hasattr(os, name) for name in required_os) or any(
        not hasattr(fcntl, name) for name in required_fcntl
    ):
        raise gov.G0GovernanceError("platform lacks sealed memfd support")
    descriptor = os.memfd_create(
        "p07-g0-reference-snapshot", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise gov.G0GovernanceError("short write to reference snapshot")
            view = view[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
        seals = (
            fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise gov.G0GovernanceError("reference snapshot seals differ")
        yield Path(f"/proc/self/fd/{descriptor}")
    finally:
        os.close(descriptor)


def rosbag_topic_timestamp_ns(path: Path, topic: str) -> list[int]:
    try:
        import rosbag
    except ImportError as error:
        raise gov.G0GovernanceError("rosbag is required to freeze bag reference timestamps") from error
    values: list[int] = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, bag_time in bag.read_messages(topics=[topic]):
            stamp = getattr(getattr(message, "header", None), "stamp", None)
            if stamp is None:
                stamp = bag_time
            if hasattr(stamp, "to_nsec"):
                value = int(stamp.to_nsec())
            elif hasattr(stamp, "secs") and hasattr(stamp, "nsecs"):
                value = int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs)
            else:
                raise gov.G0GovernanceError("reference message timestamp lacks ns identity")
            values.append(value)
    if len(values) < 2 or any(right <= left for left, right in zip(values, values[1:])):
        raise gov.G0GovernanceError(
            f"bag reference topic timestamps are not strictly increasing: {path}:{topic}"
        )
    if values[0] < 100_000_000 * 1_000_000_000:
        raise gov.G0GovernanceError("bag reference timestamps are not absolute epoch ns")
    return values


def _require_strict_absolute_timestamps(
    timestamps_ns: Iterable[int], *, label: str
) -> list[int]:
    values = list(timestamps_ns)
    if (
        len(values) < 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
        or any(right <= left for left, right in zip(values, values[1:]))
    ):
        raise gov.G0GovernanceError(
            f"reference timestamps are not strict integer nanoseconds: {label}"
        )
    if values[0] < 100_000_000 * 1_000_000_000:
        raise gov.G0GovernanceError(
            f"reference timestamps are not absolute epoch nanoseconds: {label}"
        )
    return values


def select_relative_interval(
    timestamps_ns: Iterable[int], start_s: str, end_s: str
) -> tuple[int, int, int]:
    values = list(timestamps_ns)
    if len(values) < 2:
        raise gov.G0GovernanceError("reference has fewer than two timestamps")
    try:
        start_scaled = Decimal(start_s) * Decimal(1_000_000_000)
        end_scaled = Decimal(end_s) * Decimal(1_000_000_000)
        start_integral = start_scaled.to_integral_value()
        end_integral = end_scaled.to_integral_value()
    except (InvalidOperation, ValueError) as error:
        raise gov.G0GovernanceError("relative selection interval is not exact to ns") from error
    if start_scaled != start_integral or end_scaled != end_integral:
        raise gov.G0GovernanceError("relative selection interval is not exact to ns")
    start_delta = int(start_integral)
    end_delta = int(end_integral)
    if start_delta < 0 or end_delta <= start_delta:
        raise gov.G0GovernanceError("invalid relative selection interval")
    origin = values[0]
    lower = origin + start_delta
    upper = origin + end_delta
    selected = [value for value in values if lower <= value <= upper]
    if len(selected) < 2:
        raise gov.G0GovernanceError("relative interval contains fewer than two reference samples")
    return selected[0], selected[-1], len(selected)


def _reference_audit_rows(
    content: bytes, *, label: str
) -> dict[tuple[str, str], dict[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid reference audit UTF-8: {label}") from error
    rows = [dict(row) for row in csv.DictReader(io.StringIO(text, newline=""))]
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("dataset_family", ""), row.get("sequence", ""))
        if key in result:
            raise gov.G0GovernanceError(f"duplicate reference audit identity: {key}")
        result[key] = row
    return result


def _csv_rows(content: bytes, *, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid {label} UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    if not fields or len(fields) != len(set(fields)) or any(
        set(row) != set(fields) for row in rows
    ):
        raise gov.G0GovernanceError(f"malformed {label} CSV")
    return fields, rows


def build_reference_contracts(
    queue_rows: Iterable[Mapping[str, str]],
    *,
    root: Path,
    reference_audit_path: Path,
    source_backend_queue: Mapping[str, object],
    bag_timestamp_reader: Callable[[Path, str], list[int]] = rosbag_topic_timestamp_ns,
) -> dict[str, Any]:
    rows = [dict(row) for row in queue_rows]
    by_window: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_window.setdefault(row["window_id"], []).append(row)
    if len(by_window) != 20:
        raise gov.G0GovernanceError("reference contract builder requires exactly 20 windows")
    audit_bytes, reference_audit_record = (
        publisher.read_bytes_and_record_bound_input_rooted(
            root, reference_audit_path, label="reference audit"
        )
    )
    audit_rows = _reference_audit_rows(
        audit_bytes, label=gov.display_path(root, reference_audit_path)
    )
    contracts: list[dict[str, Any]] = []
    for window_id in sorted(by_window):
        window_rows = by_window[window_id]
        identities = {
            (
                row["dataset_family"],
                row["sequence"],
                row["window_start_s"],
                row["window_end_s"],
            )
            for row in window_rows
        }
        if len(identities) != 1:
            raise gov.G0GovernanceError(f"mixed window identity in backend queue: {window_id}")
        family, sequence, relative_start, relative_end = next(iter(identities))
        audit = audit_rows.get((family, sequence))
        if audit is None:
            raise gov.G0GovernanceError(f"missing reference audit row for {(family, sequence)}")
        if audit.get("eligibility") not in (
            "ELIGIBLE",
            "ELIGIBLE_WITH_REFERENCE_CAVEAT",
        ):
            raise gov.G0GovernanceError(f"reference is not eligible for {window_id}")

        if family in REFERENCE_TOPICS:
            b1_rows = [row for row in window_rows if row["arm"] == evaluation_arm_b1()]
            if len(b1_rows) != 3:
                raise gov.G0GovernanceError(f"{window_id} lacks three B1 reference carriers")
            bags = {
                (row["feature_bag"], row["feature_bag_sha256"])
                for row in b1_rows
            }
            if len(bags) != 1:
                raise gov.G0GovernanceError(f"{window_id} has mixed B1 reference bags")
            bag_value, bag_hash = next(iter(bags))
            bag = gov.workspace_path(root, bag_value, label="B1 reference bag")
            bag_bytes, artifact = publisher.read_bytes_and_record_bound_input_rooted(
                root, bag, label=f"B1 reference bag {window_id}"
            )
            if artifact["sha256"] != bag_hash:
                raise gov.G0GovernanceError(f"B1 reference bag drift: {bag}")
            topic = REFERENCE_TOPICS[family]
            with _sealed_snapshot_path(bag_bytes) as snapshot_path:
                stamps = _require_strict_absolute_timestamps(
                    bag_timestamp_reader(snapshot_path, topic),
                    label=f"B1 reference bag {window_id}:{topic}",
                )
            start_ns, end_ns, count = stamps[0], stamps[-1], len(stamps)
            kind = "bag"
            derivation = "FROZEN_WINDOW_B1_BAG_REFERENCE_TOPIC_FIRST_LAST_SAMPLE"
        elif family == "ntnu":
            reference = gov.workspace_path(
                root, audit.get("reference_path"), label="NTNU baseline reference"
            )
            reference_bytes, artifact = (
                publisher.read_bytes_and_record_bound_input_rooted(
                    root, reference, label=f"NTNU reference {window_id}"
                )
            )
            expected_reference_hash = audit.get("reference_sha256")
            if artifact["sha256"] != expected_reference_hash:
                raise gov.G0GovernanceError(
                    f"NTNU reference checksum differs from audit: {reference}"
                )
            timestamps = tum_timestamp_ns_bytes(
                reference_bytes, label=gov.display_path(root, reference)
            )
            start_ns, end_ns, count = select_relative_interval(
                timestamps, relative_start, relative_end
            )
            topic = None
            kind = "tum"
            derivation = "CHECKSUM_BOUND_BASELINE_TUM_FILTERED_BY_FROZEN_RELATIVE_INTERVAL"
        else:
            raise gov.G0GovernanceError(f"unsupported P07 reference family: {family}")

        if end_ns <= start_ns:
            raise gov.G0GovernanceError(f"nonpositive reference support for {window_id}")
        contract: dict[str, object] = {
            "kind": kind,
            "path": artifact["path"],
            **({"topic": topic} if topic is not None else {}),
            "nominal_reference_rate_hz": float(audit["nominal_reference_rate_hz"]),
            "nominal_estimate_rate_hz": float(audit["nominal_estimate_rate_hz"]),
            "window_start_s": float(Decimal(start_ns) / Decimal(1_000_000_000)),
            "window_end_s": float(Decimal(end_ns) / Decimal(1_000_000_000)),
            "window_start_ns": start_ns,
            "window_end_ns": end_ns,
            "max_reference_gap_s": float(audit["max_reference_gap_s"]),
            "max_estimate_gap_s": float(audit["max_estimate_interp_gap_s"]),
            "reference_time_offset_s": float(audit["timestamp_offset_s"]),
        }
        record = {
            "window_id": window_id,
            "dataset_family": family,
            "sequence": sequence,
            "selection_relative_start_s": relative_start,
            "selection_relative_end_s": relative_end,
            "actual_reference_first_ns": start_ns,
            "actual_reference_last_ns": end_ns,
            "actual_reference_first_s_exact": ns_to_decimal_seconds(start_ns),
            "actual_reference_last_s_exact": ns_to_decimal_seconds(end_ns),
            "reference_samples_in_window": count,
            "derivation": derivation,
            "reference_artifact": artifact,
            "reference_contract": contract,
        }
        record["reference_contract_hash"] = gov.canonical_json_hash(record)
        contracts.append(record)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "windows": len(contracts),
        "source_backend_queue": dict(source_backend_queue),
        "contracts": contracts,
        "reference_audit": reference_audit_record,
        "checks": dict(CHECKS),
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload["reference_contracts_hash"] = gov.canonical_json_hash(payload)
    return payload


def evaluation_arm_b1() -> str:
    # Kept behind a function so this source remains importable without the
    # runtime/backend queue builder.
    return "B1_klt_nativeq_v3"


def validate_reference_contracts(
    payload: Mapping[str, Any],
    *,
    root: Path,
    verify_artifacts: bool = True,
    bag_timestamp_reader: Callable[[Path, str], list[int]] = rosbag_topic_timestamp_ns,
) -> str:
    if not verify_artifacts:
        raise gov.G0GovernanceError(
            "reference-contract artifact rederivation cannot be disabled"
        )
    expected_top_keys = {
        "schema_version",
        "status",
        "windows",
        "source_backend_queue",
        "contracts",
        "reference_audit",
        "checks",
        "outcome_boundary",
        "reference_contracts_hash",
    }
    if set(payload) != expected_top_keys:
        raise gov.G0GovernanceError("reference-contract top-level keys differ")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("status") != STATUS:
        raise gov.G0GovernanceError("unexpected reference-contract schema/status")
    if payload.get("windows") != 20:
        raise gov.G0GovernanceError("reference-contract window count differs")
    if payload.get("checks") != CHECKS or payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise gov.G0GovernanceError("reference-contract audit policy differs")
    digest = gov.validate_self_hash(
        payload, "reference_contracts_hash", label="reference contracts"
    )
    queue_record = payload.get("source_backend_queue")
    audit_record = payload.get("reference_audit")
    if not isinstance(queue_record, Mapping) or not isinstance(audit_record, Mapping):
        raise gov.G0GovernanceError("reference contracts lack queue/audit records")
    queue_path = gov.workspace_path(
        root, queue_record.get("path"), label="reference source backend queue"
    )
    audit_path = gov.workspace_path(
        root, audit_record.get("path"), label="reference audit"
    )
    queue_bytes, observed_queue = publisher.read_bytes_and_record_bound_input_rooted(
        root, queue_path, label="reference source backend queue"
    )
    audit_bytes, observed_audit = publisher.read_bytes_and_record_bound_input_rooted(
        root, audit_path, label="reference audit"
    )
    for expected, observed, label in (
        (queue_record, observed_queue, "source backend queue"),
        (audit_record, observed_audit, "reference audit"),
    ):
        if any(
            expected.get(key) != observed.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise gov.G0GovernanceError(f"reference {label} record drift")
    _queue_fields, queue_rows = _csv_rows(queue_bytes, label="source backend queue")
    audit_rows = _reference_audit_rows(audit_bytes, label="reference audit")
    queue_by_window: dict[str, list[dict[str, str]]] = {}
    for row in queue_rows:
        queue_by_window.setdefault(row.get("window_id", ""), []).append(row)
    if len(queue_by_window) != 20:
        raise gov.G0GovernanceError("source backend queue does not contain 20 windows")
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != 20:
        raise gov.G0GovernanceError("reference contracts must contain 20 windows")
    expected_record_keys = {
        "window_id",
        "dataset_family",
        "sequence",
        "selection_relative_start_s",
        "selection_relative_end_s",
        "actual_reference_first_ns",
        "actual_reference_last_ns",
        "actual_reference_first_s_exact",
        "actual_reference_last_s_exact",
        "reference_samples_in_window",
        "derivation",
        "reference_artifact",
        "reference_contract",
        "reference_contract_hash",
    }
    contract_base_keys = {
        "kind",
        "path",
        "nominal_reference_rate_hz",
        "nominal_estimate_rate_hz",
        "window_start_s",
        "window_end_s",
        "window_start_ns",
        "window_end_ns",
        "max_reference_gap_s",
        "max_estimate_gap_s",
        "reference_time_offset_s",
    }
    artifact_records: dict[str, dict[str, object]] = {}
    artifact_semantics: dict[str, tuple[str, str | None]] = {}
    bag_timestamp_cache: dict[tuple[str, str], list[int]] = {}
    tum_timestamp_cache: dict[str, list[int]] = {}
    seen: set[str] = set()
    for record in contracts:
        if not isinstance(record, Mapping) or set(record) != expected_record_keys:
            raise gov.G0GovernanceError("invalid reference contract record")
        window_id = record.get("window_id")
        if not isinstance(window_id, str) or window_id in seen:
            raise gov.G0GovernanceError("duplicate/invalid reference contract window")
        seen.add(window_id)
        expected = gov.require_hash(
            record.get("reference_contract_hash"), "reference_contract_hash"
        )
        core = dict(record)
        core.pop("reference_contract_hash")
        if gov.canonical_json_hash(core) != expected:
            raise gov.G0GovernanceError(f"reference contract self-hash mismatch: {window_id}")
        contract = record.get("reference_contract")
        if not isinstance(contract, Mapping):
            raise gov.G0GovernanceError("missing reference core contract")
        family = record.get("dataset_family")
        sequence = record.get("sequence")
        if not isinstance(family, str) or not isinstance(sequence, str):
            raise gov.G0GovernanceError("invalid reference dataset identity")
        window_rows = queue_by_window.get(window_id, [])
        queue_identity = {
            (
                row.get("dataset_family"),
                row.get("sequence"),
                row.get("window_start_s"),
                row.get("window_end_s"),
            )
            for row in window_rows
        }
        expected_identity = {
            (
                family,
                sequence,
                record.get("selection_relative_start_s"),
                record.get("selection_relative_end_s"),
            )
        }
        if queue_identity != expected_identity:
            raise gov.G0GovernanceError(
                f"reference/queue window identity mismatch: {window_id}"
            )
        audit = audit_rows.get((family, sequence))
        if audit is None:
            raise gov.G0GovernanceError(f"reference audit lacks {window_id}")
        start_ns = contract.get("window_start_ns")
        end_ns = contract.get("window_end_ns")
        if (
            isinstance(start_ns, bool)
            or not isinstance(start_ns, int)
            or isinstance(end_ns, bool)
            or not isinstance(end_ns, int)
            or start_ns < 100_000_000 * 1_000_000_000
            or end_ns <= start_ns
        ):
            raise gov.G0GovernanceError("reference contract lacks absolute ns endpoints")
        if record.get("actual_reference_first_ns") != start_ns or record.get(
            "actual_reference_last_ns"
        ) != end_ns:
            raise gov.G0GovernanceError("reference endpoint derivation mismatch")
        if (
            record.get("actual_reference_first_s_exact") != ns_to_decimal_seconds(start_ns)
            or record.get("actual_reference_last_s_exact") != ns_to_decimal_seconds(end_ns)
            or contract.get("window_start_s")
            != float(Decimal(start_ns) / Decimal(1_000_000_000))
            or contract.get("window_end_s")
            != float(Decimal(end_ns) / Decimal(1_000_000_000))
            or isinstance(record.get("reference_samples_in_window"), bool)
            or not isinstance(record.get("reference_samples_in_window"), int)
            or int(record["reference_samples_in_window"]) < 2
        ):
            raise gov.G0GovernanceError("reference endpoint/count encoding differs")
        artifact = record.get("reference_artifact")
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise gov.G0GovernanceError("reference artifact record missing")
        if contract.get("path") != artifact.get("path"):
            raise gov.G0GovernanceError("reference contract/artifact path mismatch")
        artifact_path = gov.workspace_path(
            root,
            artifact.get("path"),
            label=f"reference artifact {window_id}",
        )
        artifact_key = os.fspath(artifact_path)
        artifact_bytes: bytes | None = None
        observed_artifact = artifact_records.get(artifact_key)
        if observed_artifact is None:
            artifact_bytes, observed_artifact = (
                publisher.read_bytes_and_record_bound_input_rooted(
                    root,
                    artifact_path,
                    label=f"reference artifact {window_id}",
                )
            )
            artifact_records[artifact_key] = observed_artifact
        if any(
            artifact.get(key) != observed_artifact.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise gov.G0GovernanceError(
                f"reference artifact bound-input record differs: {window_id}"
            )
        expected_contract_keys = set(contract_base_keys)
        expected_derivation: str
        derived_start_ns: int
        derived_end_ns: int
        derived_count: int
        if family in REFERENCE_TOPICS:
            expected_contract_keys.add("topic")
            expected_derivation = (
                "FROZEN_WINDOW_B1_BAG_REFERENCE_TOPIC_FIRST_LAST_SAMPLE"
            )
            if contract.get("kind") != "bag" or contract.get("topic") != REFERENCE_TOPICS[family]:
                raise gov.G0GovernanceError("bag reference kind/topic differs")
            b1_rows = [
                row for row in window_rows if row.get("arm") == evaluation_arm_b1()
            ]
            carriers = {
                (row.get("feature_bag"), row.get("feature_bag_sha256"))
                for row in b1_rows
            }
            if len(b1_rows) != 3 or carriers != {
                (artifact.get("path"), artifact.get("sha256"))
            }:
                raise gov.G0GovernanceError("reference B1 carrier binding differs")
            topic = REFERENCE_TOPICS[family]
            semantics = ("bag", topic)
            prior_semantics = artifact_semantics.setdefault(artifact_key, semantics)
            if prior_semantics != semantics:
                raise gov.G0GovernanceError(
                    f"reference artifact parsing semantics differ: {window_id}"
                )
            bag_key = (artifact_key, topic)
            timestamps = bag_timestamp_cache.get(bag_key)
            if timestamps is None:
                if artifact_bytes is None:
                    raise gov.G0GovernanceError(
                        f"reference artifact snapshot cache incomplete: {window_id}"
                    )
                with _sealed_snapshot_path(artifact_bytes) as snapshot_path:
                    timestamps = _require_strict_absolute_timestamps(
                        bag_timestamp_reader(snapshot_path, topic),
                        label=f"reference artifact {window_id}:{topic}",
                    )
                bag_timestamp_cache[bag_key] = timestamps
            derived_start_ns = timestamps[0]
            derived_end_ns = timestamps[-1]
            derived_count = len(timestamps)
        elif family == "ntnu":
            expected_derivation = (
                "CHECKSUM_BOUND_BASELINE_TUM_FILTERED_BY_FROZEN_RELATIVE_INTERVAL"
            )
            if (
                contract.get("kind") != "tum"
                or artifact.get("path") != audit.get("reference_path")
                or artifact.get("sha256") != audit.get("reference_sha256")
            ):
                raise gov.G0GovernanceError("NTNU reference checksum/path differs")
            semantics = ("tum", None)
            prior_semantics = artifact_semantics.setdefault(artifact_key, semantics)
            if prior_semantics != semantics:
                raise gov.G0GovernanceError(
                    f"reference artifact parsing semantics differ: {window_id}"
                )
            timestamps = tum_timestamp_cache.get(artifact_key)
            if timestamps is None:
                if artifact_bytes is None:
                    raise gov.G0GovernanceError(
                        f"reference artifact snapshot cache incomplete: {window_id}"
                    )
                timestamps = tum_timestamp_ns_bytes(
                    artifact_bytes,
                    label=gov.display_path(root, artifact_path),
                )
                tum_timestamp_cache[artifact_key] = timestamps
            derived_start_ns, derived_end_ns, derived_count = select_relative_interval(
                timestamps,
                record.get("selection_relative_start_s"),
                record.get("selection_relative_end_s"),
            )
        else:
            raise gov.G0GovernanceError(f"unsupported reference family: {family}")
        if (
            start_ns != derived_start_ns
            or end_ns != derived_end_ns
            or record.get("reference_samples_in_window") != derived_count
        ):
            raise gov.G0GovernanceError(
                f"reference artifact-derived endpoint/count mismatch: {window_id}"
            )
        if set(contract) != expected_contract_keys or record.get("derivation") != expected_derivation:
            raise gov.G0GovernanceError("reference contract schema/derivation differs")
        expected_numeric = {
            "nominal_reference_rate_hz": float(audit["nominal_reference_rate_hz"]),
            "nominal_estimate_rate_hz": float(audit["nominal_estimate_rate_hz"]),
            "max_reference_gap_s": float(audit["max_reference_gap_s"]),
            "max_estimate_gap_s": float(audit["max_estimate_interp_gap_s"]),
            "reference_time_offset_s": float(audit["timestamp_offset_s"]),
        }
        if any(contract.get(key) != value for key, value in expected_numeric.items()):
            raise gov.G0GovernanceError("reference audit-derived numeric fields differ")
    if seen != set(queue_by_window):
        raise gov.G0GovernanceError("reference/queue window sets differ")
    return digest


def _publication_guard_records(
    payload: Mapping[str, Any]
) -> list[Mapping[str, object]]:
    queue_record = payload.get("source_backend_queue")
    audit_record = payload.get("reference_audit")
    contracts = payload.get("contracts")
    if (
        not isinstance(queue_record, Mapping)
        or not isinstance(audit_record, Mapping)
        or not isinstance(contracts, list)
    ):
        raise gov.G0GovernanceError(
            "reference contracts lack transactional source bindings"
        )
    records: list[Mapping[str, object]] = [queue_record, audit_record]
    for contract in contracts:
        artifact = contract.get("reference_artifact") if isinstance(contract, Mapping) else None
        if not isinstance(artifact, Mapping):
            raise gov.G0GovernanceError(
                "reference transactional artifact is malformed"
            )
        records.append(artifact)
    return records


def publish_reference_contracts_transactional(
    *,
    root: Path,
    output: Path,
    payload: Mapping[str, Any],
    queue_path: Path,
    reference_audit_path: Path,
    bag_timestamp_reader: Callable[[Path, str], list[int]] = rosbag_topic_timestamp_ns,
) -> dict[str, object]:
    def validate_fresh_rebuild() -> None:
        queue_bytes, queue_record = publisher.read_bytes_and_record_bound_input_rooted(
            root, queue_path, label="backend queue"
        )
        _fields, rows = _csv_rows(queue_bytes, label="backend queue")
        rebuilt = build_reference_contracts(
            rows,
            root=root,
            reference_audit_path=reference_audit_path,
            source_backend_queue=queue_record,
            bag_timestamp_reader=bag_timestamp_reader,
        )
        if gov._exact_json_equal(rebuilt, payload) is not True:
            raise gov.G0GovernanceError(
                "reference contracts differ from fresh live rebuild"
            )

    return publisher.publish_json_transactional_rooted(
        root,
        output,
        payload,
        guard_records=_publication_guard_records(payload),
        validate=validate_fresh_rebuild,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--reference-audit", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    queue_bytes, queue_record = publisher.read_bytes_and_record_bound_input_rooted(
        args.root, args.queue, label="backend queue"
    )
    _fields, rows = _csv_rows(queue_bytes, label="backend queue")
    payload = build_reference_contracts(
        rows,
        root=args.root,
        reference_audit_path=args.reference_audit,
        source_backend_queue=queue_record,
    )
    if args.publish:
        if args.output is None:
            raise SystemExit("--publish requires --output")
        publish_reference_contracts_transactional(
            root=args.root,
            output=args.output,
            payload=payload,
            queue_path=args.queue,
            reference_audit_path=args.reference_audit,
        )
    elif args.output is not None:
        raise SystemExit("--output without --publish is forbidden; use stdout preview")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
