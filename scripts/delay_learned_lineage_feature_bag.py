#!/usr/bin/env python3
"""Delay learned-born VINS feature lineages by exact prefix censorship.

The tool never shifts timestamps or synthesizes coordinates.  It discovers
feature IDs whose first observation is learned-marked, then either removes
their observations before a registered feature-frame index (``delay``) or
removes their complete lineages (``drop``).  All other observations and all
non-feature records are preserved and audited after writing.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import rosbag


FEATURE_TOPIC = "/feature_tracker/feature"
MAX_EXACT_FLOAT32_ID = 16_777_216


class InterventionError(RuntimeError):
    pass


@dataclass
class Lineage:
    feature_id: int
    first_frame: int
    last_frame: int
    observations: int = 0
    learned_observations: int = 0
    first_retained_frame: int | None = None
    retained_observations: int = 0
    removed_observations: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-json", required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC)
    parser.add_argument("--mode", choices=("delay", "drop"), required=True)
    parser.add_argument("--target-feature-frame", type=int)
    parser.add_argument(
        "--learned-source-code",
        action="append",
        type=int,
        default=[],
        help="Repeat for each learned source code; defaults to 10,20,30.",
    )
    args = parser.parse_args()

    input_bag = Path(args.input_bag).resolve()
    output_bag = Path(args.output_bag).resolve()
    stats_json = Path(args.stats_json).resolve()
    learned_codes = set(args.learned_source_code) or {10, 20, 30}
    if not input_bag.is_file():
        raise InterventionError(f"missing input bag: {input_bag}")
    if input_bag == output_bag:
        raise InterventionError("input and output bags must differ")
    if args.mode == "delay" and args.target_feature_frame is None:
        raise InterventionError("delay mode requires --target-feature-frame")
    if args.mode == "delay" and int(args.target_feature_frame) < 0:
        raise InterventionError("target feature frame must be nonnegative")

    lineages, discovery = discover_lineages(
        input_bag,
        feature_topic=args.feature_topic,
        learned_codes=learned_codes,
    )
    if not lineages:
        raise InterventionError("input bag contains no learned-born lineages")

    output_bag.parent.mkdir(parents=True, exist_ok=True)
    transform = rewrite_bag(
        input_bag,
        output_bag,
        feature_topic=args.feature_topic,
        mode=args.mode,
        target_feature_frame=args.target_feature_frame,
        lineages=lineages,
    )
    audit = audit_exact_intervention(
        input_bag,
        output_bag,
        feature_topic=args.feature_topic,
        mode=args.mode,
        target_feature_frame=args.target_feature_frame,
        target_ids=set(lineages),
    )

    retained = sum(item.retained_observations for item in lineages.values())
    if args.mode == "delay" and retained <= 0:
        output_bag.unlink(missing_ok=True)
        raise InterventionError(
            "delay intervention retained no learned-born observations at/after target"
        )

    payload = {
        "schema_version": 1,
        "input_bag": str(input_bag),
        "output_bag": str(output_bag),
        "input_sha256": sha256(input_bag),
        "output_sha256": sha256(output_bag),
        "feature_topic": args.feature_topic,
        "mode": args.mode,
        "target_feature_frame": args.target_feature_frame,
        "learned_source_codes": sorted(learned_codes),
        "discovery": discovery,
        "transform": transform,
        "audit": audit,
        "lineages": [asdict(lineages[key]) for key in sorted(lineages)],
    }
    stats_json.parent.mkdir(parents=True, exist_ok=True)
    stats_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"mode={args.mode} target={args.target_feature_frame} "
        f"lineages={len(lineages)} removed={transform['removed_observations']} "
        f"retained_targeted={retained} audit={audit['status']}"
    )
    print(f"wrote {output_bag}")
    print(f"wrote {stats_json}")
    return 0


def discover_lineages(
    bag_path: Path,
    *,
    feature_topic: str,
    learned_codes: set[int],
) -> tuple[dict[int, Lineage], dict[str, int]]:
    first_seen: dict[int, tuple[int, bool]] = {}
    lineages: dict[int, Lineage] = {}
    feature_frames = 0
    observations = 0
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            frame = feature_frames
            feature_frames += 1
            view = feature_view(msg, label=f"feature frame {frame}")
            observations += len(view["ids"])
            for feature_id, source_code, learned_flag in zip(
                view["ids"], view["source_codes"], view["learned_flags"]
            ):
                marker = bool(learned_flag or source_code in learned_codes)
                if feature_id not in first_seen:
                    first_seen[feature_id] = (frame, marker)
                    if marker:
                        lineages[feature_id] = Lineage(
                            feature_id=feature_id,
                            first_frame=frame,
                            last_frame=frame,
                        )
                elif marker and feature_id not in lineages:
                    first_frame, _ = first_seen[feature_id]
                    raise InterventionError(
                        "learned marker appears after an unmarked birth: "
                        f"id={feature_id} first_frame={first_frame} marker_frame={frame}"
                    )
                state = lineages.get(feature_id)
                if state is not None:
                    state.last_frame = frame
                    state.observations += 1
                    if marker:
                        state.learned_observations += 1
    if feature_frames == 0:
        raise InterventionError("input bag has no feature frames")
    return lineages, {
        "feature_frames": feature_frames,
        "observations": observations,
        "distinct_feature_ids": len(first_seen),
        "learned_born_lineages": len(lineages),
    }


def rewrite_bag(
    input_bag: Path,
    output_bag: Path,
    *,
    feature_topic: str,
    mode: str,
    target_feature_frame: int | None,
    lineages: dict[int, Lineage],
) -> dict[str, int]:
    target_ids = set(lineages)
    feature_frame = 0
    message_count = 0
    input_observations = 0
    output_observations = 0
    removed_observations = 0
    frames_with_removals = 0
    with rosbag.Bag(str(input_bag), "r") as source, rosbag.Bag(str(output_bag), "w") as target:
        for topic, msg, stamp in source.read_messages():
            message_count += 1
            if topic == feature_topic:
                view = feature_view(msg, label=f"feature frame {feature_frame}")
                input_observations += len(view["ids"])
                remove = removal_mask(
                    view["ids"],
                    feature_frame=feature_frame,
                    target_ids=target_ids,
                    mode=mode,
                    target_feature_frame=target_feature_frame,
                )
                if any(remove):
                    frames_with_removals += 1
                keep = [not item for item in remove]
                for feature_id, remove_item in zip(view["ids"], remove):
                    state = lineages.get(feature_id)
                    if state is None:
                        continue
                    if remove_item:
                        state.removed_observations += 1
                    else:
                        state.retained_observations += 1
                        if state.first_retained_frame is None:
                            state.first_retained_frame = feature_frame
                removed_observations += sum(remove)
                filter_message(msg, keep)
                output_observations += len(msg.points)
                feature_frame += 1
            target.write(topic, msg, stamp)
    return {
        "messages": message_count,
        "feature_frames": feature_frame,
        "input_observations": input_observations,
        "output_observations": output_observations,
        "removed_observations": removed_observations,
        "frames_with_removals": frames_with_removals,
        "retained_targeted_observations": sum(
            item.retained_observations for item in lineages.values()
        ),
    }


def audit_exact_intervention(
    input_bag: Path,
    output_bag: Path,
    *,
    feature_topic: str,
    mode: str,
    target_feature_frame: int | None,
    target_ids: set[int],
) -> dict[str, int | str]:
    feature_frame = 0
    records = 0
    exact_nonfeature_records = 0
    exact_unmodified_feature_frames = 0
    modified_feature_frames = 0
    with rosbag.Bag(str(input_bag), "r") as source, rosbag.Bag(str(output_bag), "r") as target:
        source_iter = source.read_messages()
        target_iter = target.read_messages()
        while True:
            try:
                source_record = next(source_iter)
            except StopIteration:
                source_record = None
            try:
                target_record = next(target_iter)
            except StopIteration:
                target_record = None
            if source_record is None or target_record is None:
                if source_record is not None or target_record is not None:
                    raise InterventionError("input/output bag record counts differ")
                break
            source_topic, source_msg, source_stamp = source_record
            target_topic, target_msg, target_stamp = target_record
            records += 1
            if source_topic != target_topic or source_stamp != target_stamp:
                raise InterventionError(f"record topology differs at message {records - 1}")
            if source_topic != feature_topic:
                if serialize(source_msg) != serialize(target_msg):
                    raise InterventionError(f"non-feature payload differs at message {records - 1}")
                exact_nonfeature_records += 1
                continue
            source_view = feature_view(source_msg, label=f"audit source frame {feature_frame}")
            expected = copy.deepcopy(source_msg)
            remove = removal_mask(
                source_view["ids"],
                feature_frame=feature_frame,
                target_ids=target_ids,
                mode=mode,
                target_feature_frame=target_feature_frame,
            )
            filter_message(expected, [not item for item in remove])
            if serialize(expected) != serialize(target_msg):
                raise InterventionError(
                    f"output is not the exact registered removal at feature frame {feature_frame}"
                )
            if any(remove):
                modified_feature_frames += 1
            else:
                exact_unmodified_feature_frames += 1
            feature_frame += 1
    return {
        "status": "passed",
        "records": records,
        "feature_frames": feature_frame,
        "exact_nonfeature_records": exact_nonfeature_records,
        "exact_unmodified_feature_frames": exact_unmodified_feature_frames,
        "modified_feature_frames": modified_feature_frames,
    }


def removal_mask(
    ids: Iterable[int],
    *,
    feature_frame: int,
    target_ids: set[int],
    mode: str,
    target_feature_frame: int | None,
) -> list[bool]:
    if mode == "drop":
        return [feature_id in target_ids for feature_id in ids]
    if mode != "delay" or target_feature_frame is None:
        raise InterventionError(f"unsupported intervention mode: {mode}")
    before_target = feature_frame < int(target_feature_frame)
    return [before_target and feature_id in target_ids for feature_id in ids]


def feature_view(msg, *, label: str) -> dict[str, list[int | bool]]:
    count = len(msg.points)
    channels = {channel.name: list(channel.values) for channel in msg.channels}
    missing = {"id", "source_code", "is_learned"}.difference(channels)
    if missing:
        raise InterventionError(f"{label}: missing channels {sorted(missing)}")
    for name, values in channels.items():
        if len(values) != count:
            raise InterventionError(
                f"{label}: channel {name!r} length {len(values)} != points {count}"
            )
    ids = [exact_nonnegative_int(value, label=f"{label} id") for value in channels["id"]]
    if len(ids) != len(set(ids)):
        raise InterventionError(f"{label}: duplicate feature ID")
    sources = [
        exact_nonnegative_int(value, label=f"{label} source_code")
        for value in channels["source_code"]
    ]
    learned_flags: list[bool] = []
    for value in channels["is_learned"]:
        number = float(value)
        if not math.isfinite(number) or number not in (0.0, 1.0):
            raise InterventionError(f"{label}: is_learned is not binary")
        learned_flags.append(number > 0.5)
    return {"ids": ids, "source_codes": sources, "learned_flags": learned_flags}


def filter_message(msg, keep: list[bool]) -> None:
    if len(msg.points) != len(keep):
        raise InterventionError("point/keep length mismatch")
    msg.points = [point for point, keep_item in zip(msg.points, keep) if keep_item]
    for channel in msg.channels:
        if len(channel.values) != len(keep):
            raise InterventionError(f"channel {channel.name!r} is not observation-aligned")
        channel.values = [
            float(value)
            for value, keep_item in zip(channel.values, keep)
            if keep_item
        ]


def exact_nonnegative_int(value: float, *, label: str) -> int:
    number = float(value)
    if (
        not math.isfinite(number)
        or not number.is_integer()
        or number < 0
        or number > MAX_EXACT_FLOAT32_ID
    ):
        raise InterventionError(f"{label}: invalid exact float32 integer {value!r}")
    return int(number)


def serialize(msg) -> bytes:
    stream = io.BytesIO()
    msg.serialize(stream)
    return stream.getvalue()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
