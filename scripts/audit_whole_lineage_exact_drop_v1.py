#!/usr/bin/env python3
"""Fail-closed, frontend-only audit of a whole-lineage exact-drop ROS bag."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import itertools
import json
import math
import os
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

import rosbag


SCHEMA_VERSION = "aqua-fe-whole-lineage-exact-drop-audit-v1"
FEATURE_TOPIC = "/feature_tracker/feature"
LEARNED_SOURCE_CODES = frozenset({10, 20, 30})
KLT_SOURCE_CODE = 1
MAX_EXACT_FLOAT32_ID = 16_777_216
OUTCOME_BOUNDARY = "FRONTEND_BAG_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class AuditViolation(ValueError):
    """Raised when P -> D is not an exact whole-lineage deletion."""


@dataclass(frozen=True)
class FrameView:
    ids: Tuple[int, ...]
    source_codes: Tuple[int, ...]
    learned_markers: Tuple[bool, ...]
    channel_names: Tuple[str, ...]


@dataclass
class LineageState:
    feature_id: int
    birth_feature_frame: int
    birth_observation_index: int
    birth_record_stamp: Tuple[int, int]
    birth_header_stamp: Tuple[int, int]
    last_feature_frame: int
    total_observations: int = 0
    learned_marked_observations: int = 0
    unmarked_continuation_observations: int = 0
    klt_continuation_observations: int = 0
    feature_frames: set = field(default_factory=set)
    source_code_histogram: Counter = field(default_factory=Counter)

    def observe(self, *, frame_index: int, source_code: int, learned_marker: bool) -> None:
        self.last_feature_frame = int(frame_index)
        self.total_observations += 1
        self.feature_frames.add(int(frame_index))
        self.source_code_histogram[int(source_code)] += 1
        if learned_marker:
            self.learned_marked_observations += 1
        else:
            self.unmarked_continuation_observations += 1
            if int(source_code) == KLT_SOURCE_CODE:
                self.klt_continuation_observations += 1

    def as_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "birth_feature_frame": self.birth_feature_frame,
            "birth_observation_index": self.birth_observation_index,
            "birth_record_stamp": _stamp_dict(self.birth_record_stamp),
            "birth_header_stamp": _stamp_dict(self.birth_header_stamp),
            "last_feature_frame": self.last_feature_frame,
            "feature_frames": len(self.feature_frames),
            "total_observations": self.total_observations,
            "learned_marked_observations": self.learned_marked_observations,
            "unmarked_continuation_observations": self.unmarked_continuation_observations,
            "klt_source_code_1_continuation_observations": self.klt_continuation_observations,
            "source_code_histogram": {
                str(key): self.source_code_histogram[key]
                for key in sorted(self.source_code_histogram)
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposed-bag", type=Path, required=True)
    parser.add_argument("--drop-bag", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC)
    parser.add_argument(
        "--learned-source-code",
        action="append",
        type=int,
        dest="learned_source_codes",
        help="Learned birth source code; repeat to override the default 10,20,30 set.",
    )
    parser.add_argument("--producer-stats-csv", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_sha256(path: Path) -> Optional[str]:
    try:
        return sha256(path) if path.is_file() else None
    except OSError:
        return None


def _stamp_tuple(stamp) -> Tuple[int, int]:
    return int(stamp.secs), int(stamp.nsecs)


def _stamp_dict(stamp: Tuple[int, int]) -> dict:
    return {"secs": int(stamp[0]), "nsecs": int(stamp[1])}


def _deserialize(raw_message):
    if not isinstance(raw_message, tuple) or len(raw_message) != 5:
        raise AuditViolation("unsupported rosbag raw-message tuple")
    _msg_type, serialized, _md5sum, _position, pytype = raw_message
    if not isinstance(serialized, bytes):
        raise AuditViolation("ROS serialized payload is not bytes")
    message = pytype()
    message.deserialize(serialized)
    return message


def _serialize(message) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def _exact_nonnegative_int(value: float, *, label: str) -> int:
    number = float(value)
    if (
        not math.isfinite(number)
        or not number.is_integer()
        or number < 0
        or number > MAX_EXACT_FLOAT32_ID
    ):
        raise AuditViolation(f"{label} is not an exact nonnegative float32 integer: {value!r}")
    return int(number)


def _feature_view(message, *, label: str) -> FrameView:
    count = len(message.points)
    names = tuple(str(channel.name) for channel in message.channels)
    if len(names) != len(set(names)):
        raise AuditViolation(f"{label}: duplicate feature channel name")
    required = {"id", "source_code", "is_learned"}
    missing = required.difference(names)
    if missing:
        raise AuditViolation(f"{label}: missing required channels {sorted(missing)}")
    for channel in message.channels:
        if len(channel.values) != count:
            raise AuditViolation(
                f"{label}: channel {channel.name!r} length {len(channel.values)} != points {count}"
            )
    channels = {channel.name: channel.values for channel in message.channels}
    ids = tuple(
        _exact_nonnegative_int(value, label=f"{label}: id[{index}]")
        for index, value in enumerate(channels["id"])
    )
    if len(ids) != len(set(ids)):
        raise AuditViolation(f"{label}: duplicate feature id within one frame")
    source_codes = tuple(
        _exact_nonnegative_int(value, label=f"{label}: source_code[{index}]")
        for index, value in enumerate(channels["source_code"])
    )
    learned_flags = []
    for index, value in enumerate(channels["is_learned"]):
        number = float(value)
        if not math.isfinite(number) or number not in (0.0, 1.0):
            raise AuditViolation(f"{label}: is_learned[{index}] is not binary")
        learned_flags.append(number > 0.5)
    return FrameView(
        ids=ids,
        source_codes=source_codes,
        learned_markers=tuple(learned_flags),
        channel_names=names,
    )


def discover_learned_born_lineages(
    proposed_bag: Path,
    *,
    feature_topic: str,
    learned_source_codes: Iterable[int],
) -> Tuple[Dict[int, LineageState], dict]:
    learned_codes = frozenset(int(code) for code in learned_source_codes)
    if not learned_codes:
        raise AuditViolation("learned source-code set must not be empty")
    first_occurrence: Dict[int, Tuple[int, int, bool]] = {}
    lineages: Dict[int, LineageState] = {}
    feature_frames = 0
    observations = 0

    with rosbag.Bag(str(proposed_bag), "r") as bag:
        for _topic, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            frame_index = feature_frames
            feature_frames += 1
            view = _feature_view(message, label=f"P feature frame {frame_index}")
            observations += len(view.ids)
            for observation_index, (feature_id, source_code, learned_flag) in enumerate(
                zip(view.ids, view.source_codes, view.learned_markers)
            ):
                marker = bool(learned_flag or source_code in learned_codes)
                if feature_id not in first_occurrence:
                    first_occurrence[feature_id] = (frame_index, observation_index, marker)
                    if marker:
                        lineages[feature_id] = LineageState(
                            feature_id=feature_id,
                            birth_feature_frame=frame_index,
                            birth_observation_index=observation_index,
                            birth_record_stamp=_stamp_tuple(record_stamp),
                            birth_header_stamp=_stamp_tuple(message.header.stamp),
                            last_feature_frame=frame_index,
                        )
                elif marker and feature_id not in lineages:
                    first_frame, first_index, _first_marker = first_occurrence[feature_id]
                    raise AuditViolation(
                        "learned provenance appears after an unmarked first observation: "
                        f"id={feature_id} first={first_frame}:{first_index} "
                        f"marker={frame_index}:{observation_index}"
                    )
                state = lineages.get(feature_id)
                if state is not None:
                    state.observe(
                        frame_index=frame_index,
                        source_code=source_code,
                        learned_marker=marker,
                    )

    if feature_frames == 0:
        raise AuditViolation("proposed bag contains no feature frames")
    if not lineages:
        raise AuditViolation("proposed bag contains no learned-born lineage; D is not applicable")
    return lineages, {
        "feature_frames": feature_frames,
        "observations": observations,
        "distinct_feature_ids": len(first_occurrence),
    }


def _filter_expected_message(message, keep: Sequence[bool]):
    expected = copy.deepcopy(message)
    expected.points = [point for point, keep_value in zip(expected.points, keep) if keep_value]
    for channel in expected.channels:
        channel.values = [
            float(value)
            for value, keep_value in zip(channel.values, keep)
            if keep_value
        ]
    return expected


def _assert_semantic_message_equal(expected, actual, *, frame_index: int) -> None:
    if expected.header != actual.header:
        raise AuditViolation(f"D feature frame {frame_index}: header differs from exact drop")
    if expected.points != actual.points:
        raise AuditViolation(f"D feature frame {frame_index}: point fields/order differ")
    expected_names = tuple(channel.name for channel in expected.channels)
    actual_names = tuple(channel.name for channel in actual.channels)
    if expected_names != actual_names:
        raise AuditViolation(f"D feature frame {frame_index}: channel names/order differ")
    for expected_channel, actual_channel in zip(expected.channels, actual.channels):
        if list(expected_channel.values) != list(actual_channel.values):
            raise AuditViolation(
                f"D feature frame {frame_index}: channel {expected_channel.name!r} values differ"
            )


def _digest_text(digest, value: str) -> None:
    raw = value.encode("utf-8")
    digest.update(struct.pack(">I", len(raw)))
    digest.update(raw)


def _digest_record(
    digest,
    *,
    message_index: int,
    topic: str,
    timestamp: Tuple[int, int],
    msg_type: str,
    md5sum: str,
    payload: bytes,
) -> None:
    digest.update(struct.pack(">QqI", int(message_index), int(timestamp[0]), int(timestamp[1])))
    _digest_text(digest, topic)
    _digest_text(digest, msg_type)
    _digest_text(digest, md5sum)
    digest.update(struct.pack(">Q", len(payload)))
    digest.update(payload)


def _digest_topology_record(
    digest, *, message_index: int, topic: str, timestamp: Tuple[int, int], msg_type: str, md5sum: str
) -> None:
    digest.update(struct.pack(">QqI", int(message_index), int(timestamp[0]), int(timestamp[1])))
    _digest_text(digest, topic)
    _digest_text(digest, msg_type)
    _digest_text(digest, md5sum)


def _raw_contract(raw_message, *, label: str) -> Tuple[str, bytes, str]:
    if not isinstance(raw_message, tuple) or len(raw_message) != 5:
        raise AuditViolation(f"{label}: unsupported rosbag raw-message tuple")
    msg_type, payload, md5sum, _position, _pytype = raw_message
    if not isinstance(payload, bytes):
        raise AuditViolation(f"{label}: serialized payload is not bytes")
    return str(msg_type), payload, str(md5sum)


def _resolve_declared_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    return path.resolve()


def audit_producer_stats(
    stats_csv: Path,
    *,
    proposed_bag: Path,
    drop_bag: Path,
    summary: dict,
) -> dict:
    with stats_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if len(rows) != 1:
        raise AuditViolation("producer stats CSV must contain exactly one data row")
    row = rows[0]
    required_fields = {
        "feature_frames",
        "frames_with_drops",
        "dropped_observations",
        "kept_learned_observations",
        "learned_track_ids",
        "kept_observations",
        "input_bag",
        "output_bag",
        "drop_learned",
        "drop_learned_track_lineage",
        "keep_learned_selected_indices",
        "drop_source_code",
        "learned_id_min",
        "learned_min_total_observations",
        "learned_max_observations",
        "learned_max_per_frame",
        "keep_learned_ids",
        "keep_learned_track_lineage_ids",
    }
    missing = required_fields.difference(row)
    if missing:
        raise AuditViolation(f"producer stats missing fields {sorted(missing)}")
    if _resolve_declared_path(row["input_bag"]) != proposed_bag.resolve():
        raise AuditViolation("producer stats input_bag does not name audited P bag")
    if _resolve_declared_path(row["output_bag"]) != drop_bag.resolve():
        raise AuditViolation("producer stats output_bag does not name audited D bag")

    expected_counts = {
        "feature_frames": summary["feature_frames"],
        "frames_with_drops": summary["frames_with_drops"],
        "dropped_observations": summary["dropped_observations"],
        "kept_learned_observations": 0,
        "learned_track_ids": summary["learned_lineages"],
        "kept_observations": summary["drop_observations"],
    }
    for key, expected in expected_counts.items():
        try:
            actual = int(row[key])
        except (TypeError, ValueError):
            raise AuditViolation(f"producer stats {key} is not an integer")
        if actual != int(expected):
            raise AuditViolation(f"producer stats {key}={actual} != audited {expected}")

    exact_drop_controls = {
        "drop_learned": "0",
        "drop_learned_track_lineage": "1",
        "keep_learned_selected_indices": "",
        "drop_source_code": "",
        "learned_id_min": "0",
        "learned_min_total_observations": "0",
        "learned_max_observations": "0",
        "learned_max_per_frame": "0",
        "keep_learned_ids": "",
        "keep_learned_track_lineage_ids": "",
    }
    for key, expected in exact_drop_controls.items():
        if str(row[key]).strip() != expected:
            raise AuditViolation(
                f"producer stats contains non-exact-drop control {key}={row[key]!r}"
            )
    return {
        "contract_pass": True,
        "path": str(stats_csv),
        "sha256": sha256(stats_csv),
        "validated_counts": expected_counts,
        "validated_exact_drop_controls": exact_drop_controls,
    }


def audit_bags(
    *,
    proposed_bag: Path,
    drop_bag: Path,
    feature_topic: str = FEATURE_TOPIC,
    learned_source_codes: Iterable[int] = LEARNED_SOURCE_CODES,
    producer_stats_csv: Optional[Path] = None,
) -> dict:
    proposed_bag = Path(proposed_bag)
    drop_bag = Path(drop_bag)
    if not proposed_bag.is_file() or not drop_bag.is_file():
        raise AuditViolation("both P and D bags must exist as regular files")
    if proposed_bag.resolve() == drop_bag.resolve():
        raise AuditViolation("P and D bags must be distinct files")
    learned_codes = tuple(sorted(set(int(code) for code in learned_source_codes)))
    lineages, proposed_scan = discover_learned_born_lineages(
        proposed_bag,
        feature_topic=str(feature_topic),
        learned_source_codes=learned_codes,
    )
    drop_ids = frozenset(lineages)

    topology_digest = hashlib.sha256()
    nonfeature_digest = hashlib.sha256()
    proposed_feature_digest = hashlib.sha256()
    expected_drop_feature_digest = hashlib.sha256()
    actual_drop_feature_digest = hashlib.sha256()
    total_messages = 0
    feature_frames = 0
    nonfeature_messages = 0
    proposed_observations = 0
    drop_observations = 0
    dropped_observations = 0
    frames_with_drops = 0

    with rosbag.Bag(str(proposed_bag), "r") as left_bag, rosbag.Bag(str(drop_bag), "r") as right_bag:
        left_messages = left_bag.read_messages(raw=True, return_connection_header=True)
        right_messages = right_bag.read_messages(raw=True, return_connection_header=True)
        for message_index, pair in enumerate(
            itertools.zip_longest(left_messages, right_messages, fillvalue=None)
        ):
            left, right = pair
            if left is None or right is None:
                raise AuditViolation("P and D message counts differ")
            total_messages += 1
            left_stamp = _stamp_tuple(left.timestamp)
            right_stamp = _stamp_tuple(right.timestamp)
            if left.topic != right.topic or left_stamp != right_stamp:
                raise AuditViolation(f"message topic/order/timestamp differs at index {message_index}")
            left_type, left_payload, left_md5 = _raw_contract(
                left.message, label=f"P message {message_index}"
            )
            right_type, right_payload, right_md5 = _raw_contract(
                right.message, label=f"D message {message_index}"
            )
            if (left_type, left_md5) != (right_type, right_md5):
                raise AuditViolation(f"message type/md5 differs at index {message_index}")
            _digest_topology_record(
                topology_digest,
                message_index=message_index,
                topic=left.topic,
                timestamp=left_stamp,
                msg_type=left_type,
                md5sum=left_md5,
            )

            if left.topic != feature_topic:
                if left_payload != right_payload:
                    raise AuditViolation(
                        f"non-feature serialized payload differs at message {message_index}"
                    )
                nonfeature_messages += 1
                _digest_record(
                    nonfeature_digest,
                    message_index=message_index,
                    topic=left.topic,
                    timestamp=left_stamp,
                    msg_type=left_type,
                    md5sum=left_md5,
                    payload=left_payload,
                )
                continue

            frame_index = feature_frames
            feature_frames += 1
            left_message = _deserialize(left.message)
            right_message = _deserialize(right.message)
            left_view = _feature_view(left_message, label=f"P feature frame {frame_index}")
            _feature_view(right_message, label=f"D feature frame {frame_index}")
            proposed_observations += len(left_view.ids)
            keep = tuple(feature_id not in drop_ids for feature_id in left_view.ids)
            frame_drops = len(keep) - sum(1 for value in keep if value)
            if frame_drops:
                frames_with_drops += 1
                dropped_observations += frame_drops
            expected_message = _filter_expected_message(left_message, keep)
            expected_payload = _serialize(expected_message)
            if expected_payload != right_payload:
                _assert_semantic_message_equal(
                    expected_message, right_message, frame_index=frame_index
                )
                raise AuditViolation(
                    f"D feature frame {frame_index}: serialized payload differs despite semantic equality"
                )
            drop_observations += len(right_message.points)
            for digest, payload in (
                (proposed_feature_digest, left_payload),
                (expected_drop_feature_digest, expected_payload),
                (actual_drop_feature_digest, right_payload),
            ):
                _digest_record(
                    digest,
                    message_index=message_index,
                    topic=left.topic,
                    timestamp=left_stamp,
                    msg_type=left_type,
                    md5sum=left_md5,
                    payload=payload,
                )

    if feature_frames != int(proposed_scan["feature_frames"]):
        raise AuditViolation("feature-frame count changed between P scans")
    lineage_observations = sum(state.total_observations for state in lineages.values())
    if dropped_observations != lineage_observations:
        raise AuditViolation(
            "dropped observation count does not equal all learned-lineage observations"
        )
    if proposed_observations - dropped_observations != drop_observations:
        raise AuditViolation("P - dropped observation count does not equal D")
    if expected_drop_feature_digest.digest() != actual_drop_feature_digest.digest():
        raise AuditViolation("expected and actual D feature-sequence digests differ")

    summary = {
        "total_messages": total_messages,
        "nonfeature_messages": nonfeature_messages,
        "feature_frames": feature_frames,
        "proposed_observations": proposed_observations,
        "drop_observations": drop_observations,
        "dropped_observations": dropped_observations,
        "frames_with_drops": frames_with_drops,
        "learned_lineages": len(lineages),
        "learned_birth_observations": len(lineages),
        "learned_marked_observations": sum(
            state.learned_marked_observations for state in lineages.values()
        ),
        "unmarked_continuation_observations": sum(
            state.unmarked_continuation_observations for state in lineages.values()
        ),
        "klt_source_code_1_continuation_observations": sum(
            state.klt_continuation_observations for state in lineages.values()
        ),
    }
    producer_stats = None
    if producer_stats_csv is not None:
        producer_stats = audit_producer_stats(
            Path(producer_stats_csv),
            proposed_bag=proposed_bag,
            drop_bag=drop_bag,
            summary=summary,
        )

    expected_hash = expected_drop_feature_digest.hexdigest()
    actual_hash = actual_drop_feature_digest.hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_pass": True,
        "decision": "PASS_EXACT_WHOLE_LINEAGE_DROP",
        "outcome_boundary": OUTCOME_BOUNDARY,
        "forbidden_outcomes_accessed": [],
        "inputs": {
            "proposed_bag": str(proposed_bag),
            "proposed_bag_sha256": sha256(proposed_bag),
            "drop_bag": str(drop_bag),
            "drop_bag_sha256": sha256(drop_bag),
            "feature_topic": str(feature_topic),
        },
        "auditor": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
        "learned_birth_contract": {
            "source_codes": list(learned_codes),
            "is_learned_threshold": 0.5,
            "birth_rule": "first ID occurrence must carry is_learned=1 or learned source_code",
            "continuation_rule": "drop every later observation with a learned-born ID regardless of source",
            "late_marker_policy": "FAIL_CLOSED",
        },
        "checks": {
            "message_count_order_topic_type_md5_record_timestamp_exact": True,
            "nonfeature_serialized_bytes_exact": True,
            "feature_header_and_record_timestamps_exact": True,
            "learned_births_and_all_lineage_continuations_absent_from_drop": True,
            "non_dropped_observation_order_fields_channels_exact": True,
            "drop_feature_payload_equals_filtered_proposed_payload_byte_for_byte": True,
            "producer_stats_contract_exact": producer_stats is not None,
        },
        "summary": summary,
        "digests": {
            "message_topology_sha256": topology_digest.hexdigest(),
            "common_nonfeature_sequence_sha256": nonfeature_digest.hexdigest(),
            "proposed_feature_sequence_sha256": proposed_feature_digest.hexdigest(),
            "expected_drop_feature_sequence_sha256": expected_hash,
            "actual_drop_feature_sequence_sha256": actual_hash,
            "expected_equals_actual_drop_feature_sequence": expected_hash == actual_hash,
        },
        "learned_lineages": [lineages[key].as_dict() for key in sorted(lineages)],
        "producer_stats": producer_stats,
    }


def write_json_no_clobber(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _failure_payload(args: argparse.Namespace, error: Exception) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_pass": False,
        "decision": "FAIL_CLOSED",
        "outcome_boundary": OUTCOME_BOUNDARY,
        "forbidden_outcomes_accessed": [],
        "error_type": type(error).__name__,
        "error": str(error),
        "inputs": {
            "proposed_bag": str(args.proposed_bag),
            "proposed_bag_sha256": _safe_sha256(args.proposed_bag),
            "drop_bag": str(args.drop_bag),
            "drop_bag_sha256": _safe_sha256(args.drop_bag),
            "feature_topic": str(args.feature_topic),
        },
    }


def main() -> int:
    args = parse_args()
    learned_codes = (
        LEARNED_SOURCE_CODES
        if args.learned_source_codes is None
        else frozenset(args.learned_source_codes)
    )
    try:
        result = audit_bags(
            proposed_bag=args.proposed_bag,
            drop_bag=args.drop_bag,
            feature_topic=str(args.feature_topic),
            learned_source_codes=learned_codes,
            producer_stats_csv=args.producer_stats_csv,
        )
    except Exception as error:
        try:
            write_json_no_clobber(args.audit_json, _failure_payload(args, error))
        except Exception as report_error:
            print(f"WHOLE_LINEAGE_EXACT_DROP_AUDIT report failure: {report_error}", file=sys.stderr)
        print(f"WHOLE_LINEAGE_EXACT_DROP_AUDIT FAIL_CLOSED: {error}", file=sys.stderr)
        return 1
    write_json_no_clobber(args.audit_json, result)
    summary = result["summary"]
    print(
        "WHOLE_LINEAGE_EXACT_DROP_AUDIT PASS "
        f"messages={summary['total_messages']} features={summary['feature_frames']} "
        f"lineages={summary['learned_lineages']} dropped={summary['dropped_observations']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
