#!/usr/bin/env python3
"""Materialize and freeze the 20 P07 B0 play inputs without running VINS.

The default action is a read-only preflight.  ``--execute`` is required to run
the frozen AQUALOC converter recipes.  Target bags are linked no-replace from
same-directory temporary files; an existing target is never removed or
replaced.  The receipt is published before the B0 play-input contract, which
is the commit/authorization document consumed by backend replay.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

try:
    from scripts import build_p07_backend_b0_materialization_lock_v1 as plan_builder
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_backend_replay_common_v1 as common
except ModuleNotFoundError:  # Direct execution.
    import build_p07_backend_b0_materialization_lock_v1 as plan_builder  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore


ROOT = queue_builder.ROOT
PLAN = plan_builder.OUTPUT
INTENT = plan_builder.INTENT
RECEIPT = plan_builder.RECEIPT
FINAL = plan_builder.FINAL_OUTPUT
RECEIPT_SCHEMA = "isj-p07-backend-b0-materialization-receipt-v1"
RECEIPT_STATUS = "PASS_ALL_B0_INPUTS_EXACT_AND_OUTCOME_BLIND"
RECEIPT_HASH = "materialization_receipt_hash"
INTENT_SCHEMA = "isj-p07-backend-b0-materialization-intent-v1"
INTENT_STATUS = "FROZEN_BEFORE_FIRST_B0_TARGET_MUTATION"
INTENT_HASH = "materialization_intent_hash"
ACTION_FLOCK = Path("/tmp/aquafe_p07_backend_b0_materialization_v1.lock")
OUTCOME_BOUNDARY = "B0_INPUT_PREPARATION_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
_SHA = plan_builder._SHA


class B0MaterializationRuntimeError(RuntimeError):
    """The frozen B0 preparation contract cannot be executed safely."""


def document_hash(payload: Mapping[str, object], field: str) -> str:
    return plan_builder.document_hash(payload, field)


def _safe_workspace_path(root: Path, raw: str) -> Path:
    pure = PurePosixPath(raw)
    if not raw or pure.is_absolute() or ".." in pure.parts:
        raise B0MaterializationRuntimeError(f"unsafe B0 path: {raw!r}")
    return root.joinpath(*pure.parts)


def _bound_path_state(root: Path, path: Path, *, label: str) -> str:
    try:
        return queue_builder.rooted_io.path_state_bound_input_rooted(
            root, path, label=label
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError(f"unsafe {label}: {path}") from error


def _resolved_bound_path(root: Path, raw: str) -> Path:
    lexical = _safe_workspace_path(root, raw)
    relative = lexical.absolute().relative_to(root.absolute())
    parts = relative.parts
    if parts and parts[0] in queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS:
        return queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS[parts[0]].joinpath(
            *parts[1:]
        )
    return lexical.absolute()


def _file_record(root: Path, path: Path) -> dict[str, object]:
    relative = path.absolute().relative_to(root.absolute()).as_posix()
    content, _identity = queue_builder.formal_io.read_direct_bytes(root, relative)
    return {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _portable_record(record: Mapping[str, object]) -> dict[str, object]:
    return {key: record[key] for key in ("path", "sha256", "size_bytes")}


@contextmanager
def _sealed_bag_snapshot(content: bytes):
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
        raise B0MaterializationRuntimeError(
            "platform lacks sealed B0 inspection support"
        )
    descriptor = os.memfd_create("p07-b0-inspection", os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise B0MaterializationRuntimeError(
                    "short write to sealed B0 inspection snapshot"
                )
            view = view[written:]
        os.fsync(descriptor)
        seals = (
            fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise B0MaterializationRuntimeError("sealed B0 inspection flags differ")
        os.lseek(descriptor, 0, os.SEEK_SET)
        yield Path(f"/proc/self/fd/{descriptor}")
    finally:
        os.close(descriptor)


def _inspect_bound_bag_snapshot(
    root: Path,
    path: Path,
    recipe: Mapping[str, Any],
    *,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    try:
        content, record = (
            queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
                root, path, label="B0 bag inspection input"
            )
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError(
            f"B0 bag is absent/not direct: {path}"
        ) from error
    if (
        record["sha256"] != recipe["expected_sha256"]
        or int(record["size_bytes"]) != int(recipe["expected_size_bytes"])
    ):
        raise B0MaterializationRuntimeError(f"B0 target hash/size drift: {path}")
    try:
        relative = path.absolute().relative_to(root.absolute()).as_posix()
        identity = common.capture_canonical_input_identity(
            root,
            relative,
            expected_sha256=str(recipe["expected_sha256"]),
            verify_sha256=True,
        )
    except (ValueError, common.BackendReplayViolation) as error:
        raise B0MaterializationRuntimeError(
            f"B0 target path/link/identity drift: {path}"
        ) from error
    with _sealed_bag_snapshot(content) as sealed_path:
        bag = dict(bag_inspector(sealed_path, recipe))
    try:
        common.revalidate_canonical_input_identity(
            root, identity, verify_sha256=True
        )
        final_content, final_record = (
            queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
                root, path, label="B0 bag post-inspection input"
            )
        )
    except (
        common.BackendReplayViolation,
        queue_builder.rooted_io.gov.G0GovernanceError,
    ) as error:
        raise B0MaterializationRuntimeError(
            f"B0 target changed during sealed inspection: {path}"
        ) from error
    if final_content != content or final_record != record:
        raise B0MaterializationRuntimeError(
            f"B0 target bytes changed during sealed inspection: {path}"
        )
    return dict(record), dict(identity), bag


def _verify_record(root: Path, record: Mapping[str, object], *, label: str) -> Path:
    path = _safe_workspace_path(root, str(record.get("path", "")))
    try:
        observed = _file_record(root, path)
    except (
        OSError,
        ValueError,
        queue_builder.formal_io.FormalIOError,
    ) as error:
        raise B0MaterializationRuntimeError(f"missing {label}: {path}") from error
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise B0MaterializationRuntimeError(f"{label} hash/size/path drift: {path}")
    return path


def load_frozen_plan(*, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, object]]:
    relative = PLAN.relative_to(ROOT).as_posix()
    try:
        content, identity = queue_builder.formal_io.read_direct_bytes(root, relative)
        payload = json.loads(content)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        queue_builder.formal_io.FormalIOError,
    ) as error:
        raise B0MaterializationRuntimeError("cannot read direct frozen B0 plan") from error
    if not isinstance(payload, dict):
        raise B0MaterializationRuntimeError("frozen B0 plan is not an object")
    try:
        plan_builder.validate_plan_payload(
            payload, require_live_artifacts=True, root=root
        )
    except plan_builder.B0MaterializationError as error:
        raise B0MaterializationRuntimeError(
            f"frozen B0 plan artifact/schema drift: {error}"
        ) from error
    for record in payload.get("artifacts", []):
        if not isinstance(record, dict):
            raise B0MaterializationRuntimeError("invalid B0 plan artifact record")
        _verify_record(root, record, label="B0 plan artifact")
    return payload, {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        **identity,
    }


def _clean_converter_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "FEATURE_BAG_OVERRIDE",
        "SHORT_BAG",
        "VINS_WORKSPACE",
        "VINS_BIN",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "RUN_VINS": "0",
            "RUN_EVALUATION": "0",
            "EXPORT_FEATURES": "0",
            "FORCE_EXPORT": "0",
        }
    )
    return environment


def _header_stamp_ns(message: object) -> int:
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None or not hasattr(stamp, "to_nsec"):
        raise B0MaterializationRuntimeError("camera message lacks header stamp")
    value = int(stamp.to_nsec())
    if value <= 0:
        raise B0MaterializationRuntimeError("camera message has non-positive header stamp")
    return value


def inspect_rosbag(path: Path, recipe: Mapping[str, Any]) -> dict[str, object]:
    """Inspect only bag metadata and camera header stamps, never trajectory values."""

    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as error:
        raise B0MaterializationRuntimeError("rosbag is unavailable") from error
    procfd = re.fullmatch(r"/proc/self/fd/([0-9]+)", os.fspath(path))
    if procfd is None:
        raise B0MaterializationRuntimeError(
            "B0 bag inspection requires a sealed /proc/self/fd input"
        )
    try:
        info = os.fstat(int(procfd.group(1)))
    except OSError as error:
        raise B0MaterializationRuntimeError(
            f"sealed B0 bag descriptor is unavailable: {path}"
        ) from error
    if not stat.S_ISREG(info.st_mode):
        raise B0MaterializationRuntimeError(
            f"sealed B0 bag descriptor is not regular: {path}"
        )
    camera = str(recipe["camera_topic"])
    stamps: list[int] = []
    selected_record_start_ns: int | None = None
    selected_record_end_ns: int | None = None
    with rosbag.Bag(str(path), "r") as bag:
        topic_info = bag.get_type_and_topic_info().topics
        counts = {
            str(topic): int(info.message_count)
            for topic, info in topic_info.items()
        }
        expected_counts = recipe.get("expected_topic_counts")
        if expected_counts is not None and counts != {
            str(key): int(value) for key, value in expected_counts.items()
        }:
            raise B0MaterializationRuntimeError(
                f"B0 topic-count drift for {recipe['window_id']}: {counts}"
            )
        start_ns: int | None = None
        end_ns: int | None = None
        if recipe.get("disposition") == "DIRECT_RAW_WINDOW_PLAYBACK":
            bag_start_ns = int(round(float(bag.get_start_time()) * 1_000_000_000))
            start_ns = bag_start_ns + int(
                round(float(recipe["runner_start"]) * 1_000_000_000)
            )
            end_ns = start_ns + int(
                round(float(recipe["runner_end_or_duration"]) * 1_000_000_000)
            )
            selected_record_start_ns, selected_record_end_ns = start_ns, end_ns
        previous = -1
        for _topic, message, record_stamp in bag.read_messages(topics=[camera]):
            record_ns = int(record_stamp.to_nsec())
            if start_ns is not None and not (start_ns <= record_ns <= int(end_ns)):
                continue
            stamp_ns = _header_stamp_ns(message)
            if stamp_ns <= previous:
                raise B0MaterializationRuntimeError("camera header stamps are not increasing")
            previous = stamp_ns
            stamps.append(stamp_ns)
    if len(stamps) < 2:
        raise B0MaterializationRuntimeError(
            f"B0 evaluation window has fewer than two camera messages: {path}"
        )
    try:
        common.validate_absolute_ros_epoch_window(
            stamps[0], stamps[-1], label="B0 inspected camera window"
        )
    except common.BackendReplayViolation as error:
        raise B0MaterializationRuntimeError(
            "B0 camera stamps are not absolute epoch ns"
        ) from error
    expected_range = recipe.get("expected_camera_stamp_range_ns")
    if expected_range is not None and expected_range != {
        "first": stamps[0],
        "last": stamps[-1],
    }:
        raise B0MaterializationRuntimeError("B0 camera stamp-range drift")
    return {
        "topic_counts": dict(sorted(counts.items())),
        "camera_topic": camera,
        "selected_camera_count": len(stamps),
        "start_ros_time_ns": stamps[0],
        "end_ros_time_ns": stamps[-1],
        "selected_record_start_ns": selected_record_start_ns,
        "selected_record_end_ns": selected_record_end_ns,
        "stamp_source": "sensor_msgs/Image.header.stamp",
        "trajectory_values_interpreted": False,
    }


def inspect_exact_target(
    root: Path,
    recipe: Mapping[str, Any],
    *,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]] = inspect_rosbag,
) -> dict[str, object]:
    path = _safe_workspace_path(root, str(recipe["target_path"]))
    record, identity, bag = _inspect_bound_bag_snapshot(
        root, path, recipe, bag_inspector=bag_inspector
    )
    target = identity["resolved_target_identity"]
    return {
        "window_id": recipe["window_id"],
        "target_path": recipe["target_path"],
        "sha256": record["sha256"],
        "size_bytes": int(record["size_bytes"]),
        "device": int(target["device"]),
        "inode": int(target["inode"]),
        "recipe_hash": recipe["recipe_hash"],
        "bag_integrity": bag,
        "held_out_trajectory_outcome_read": False,
    }


def _fsync_directory(fd: int) -> None:
    os.fsync(fd)


def _ensure_exact_cache_parent(root: Path, recipe: Mapping[str, Any]) -> Path:
    target = _safe_workspace_path(root, str(recipe["target_path"]))
    if recipe.get("disposition") != "EXACT_COPY_REQUIRED_OR_RECONCILE":
        if _bound_path_state(
            root, target.parent, label="B0 materialization parent"
        ) != "DIRECTORY":
            raise B0MaterializationRuntimeError(
                "B0 materialization parent is absent/not direct"
            )
        return _resolved_bound_path(root, str(recipe["target_path"])).parent
    if str(recipe["target_path"]) != (
        "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag"
    ):
        raise B0MaterializationRuntimeError("unallowlisted B0 copy-cache target")
    datasets = _resolved_bound_path(root, "datasets/.root-probe").parent
    _bound_path_state(root, root / "datasets/.root-probe", label="B0 datasets root")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        parent_fd = queue_builder.rooted_io._open_absolute_directory(
            datasets, label="B0 datasets target"
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError("B0 datasets target is unsafe") from error
    descriptors = [parent_fd]
    try:
        for component in ("p07_backend_b0_inputs", "afrl"):
            try:
                os.mkdir(component, 0o755, dir_fd=parent_fd)
                _fsync_directory(parent_fd)
            except FileExistsError:
                pass
            info = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise B0MaterializationRuntimeError("B0 cache parent is not direct")
            child_fd = os.open(component, flags, dir_fd=parent_fd)
            descriptors.append(child_fd)
            parent_fd = child_fd
        result = datasets / "p07_backend_b0_inputs" / "afrl"
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if _bound_path_state(
        root, target.parent, label="B0 dedicated cache parent"
    ) != "DIRECTORY":
        raise B0MaterializationRuntimeError(
            "B0 dedicated cache parent is not canonically reachable"
        )
    return result


def _copy_exact_source(
    root: Path,
    source: Path,
    temporary: Path,
    recipe: Mapping[str, Any],
) -> dict[str, object]:
    try:
        source_content, source_record = (
            queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
                root, source, label="AFRL exact-copy source"
            )
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError("AFRL B0 copy source is unsafe") from error
    if (
        source_record["sha256"] != recipe["source_raw_sha256"]
        or source_record["sha256"] != recipe["expected_sha256"]
    ):
        raise B0MaterializationRuntimeError("AFRL B0 copy source hash drift")
    try:
        parent_fd = queue_builder.rooted_io._open_absolute_directory(
            temporary.parent, label="AFRL B0 copy target parent"
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError("AFRL B0 copy target parent is unsafe") from error
    target_fd: int | None = None
    try:
        target_fd = os.open(
            temporary.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        copied = 0
        digest = hashlib.sha256()
        for offset in range(0, len(source_content), 1024 * 1024):
            chunk = source_content[offset : offset + 1024 * 1024]
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise B0MaterializationRuntimeError("short AFRL B0 cache write")
                copied += written
                view = view[written:]
        os.fsync(target_fd)
        return {
            "kind": "INTERNAL_EXACT_COPY_NOREPLACE",
            "source_size_bytes": int(source_record["size_bytes"]),
            "copied_size_bytes": copied,
            "copied_sha256": digest.hexdigest(),
            "run_vins": False,
        }
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)


def publish_materialized_target_no_clobber(
    root: Path, temporary: Path, recipe: Mapping[str, Any]
) -> None:
    """Link a staged bag into its exact target name without replacing a winner."""

    target = _safe_workspace_path(root, str(recipe["target_path"]))
    resolved_parent = _resolved_bound_path(root, str(recipe["target_path"])).parent
    if _bound_path_state(
        root, target.parent, label="B0 publication parent"
    ) != "DIRECTORY":
        raise B0MaterializationRuntimeError("B0 target parent is not direct/reachable")
    if temporary.parent != resolved_parent:
        raise B0MaterializationRuntimeError("B0 temporary is not in resolved target parent")
    try:
        parent_fd = queue_builder.rooted_io._open_absolute_directory(
            resolved_parent, label="B0 publication parent"
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError("B0 publication parent is unsafe") from error
    try:
        if _bound_path_state(
            root, target.parent, label="B0 publication parent revalidation"
        ) != "DIRECTORY":
            raise B0MaterializationRuntimeError("B0 target parent reachability drift")
        try:
            os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(target)
        temp_info = os.stat(temporary.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(temp_info.st_mode):
            raise B0MaterializationRuntimeError("staged B0 target is not regular")
        try:
            os.link(
                temporary.name,
                target.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            # Never unlink or inspect-as-authoritative the race winner.
            raise FileExistsError(target) from error
        _fsync_directory(parent_fd)
        final_info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            final_info.st_dev != temp_info.st_dev
            or final_info.st_ino != temp_info.st_ino
            or final_info.st_size != temp_info.st_size
        ):
            raise B0MaterializationRuntimeError("B0 hardlink publication identity drift")
        # The staged name is ours and is removed only after the no-replace link
        # succeeds.  A race winner is never touched.  The canonical target must
        # be a single-link regular file before any downstream inspection.
        os.unlink(temporary.name, dir_fd=parent_fd)
        _fsync_directory(parent_fd)
        single = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(single.st_mode)
            or single.st_nlink != 1
            or single.st_dev != temp_info.st_dev
            or single.st_ino != temp_info.st_ino
            or single.st_size != temp_info.st_size
        ):
            raise B0MaterializationRuntimeError(
                "B0 hardlink publication did not reach single-link final state"
            )
        if _bound_path_state(
            root, target, label="B0 published target"
        ) != "FILE":
            raise B0MaterializationRuntimeError(
                "B0 published target is not canonically reachable"
            )
    finally:
        os.close(parent_fd)


def _verify_source(
    root: Path, recipe: Mapping[str, Any], cache: dict[str, dict[str, object]]
) -> dict[str, object]:
    raw = str(recipe["source_raw_path"])
    frozen_identity = recipe.get("source_path_identity")
    if not isinstance(frozen_identity, dict):
        raise B0MaterializationRuntimeError("B0 source path identity is absent")
    if raw in cache:
        observed = cache[raw]
        if observed.get("source_path_identity") != frozen_identity:
            raise B0MaterializationRuntimeError(
                f"B0 repeated source has conflicting identity: {raw}"
            )
    else:
        try:
            revalidated = common.revalidate_canonical_input_identity(
                root, frozen_identity, verify_sha256=True
            )
        except common.BackendReplayViolation as error:
            raise B0MaterializationRuntimeError(
                f"B0 source path/link/target drift: {raw}"
            ) from error
        path = _safe_workspace_path(root, raw)
        try:
            source_record = (
                queue_builder.rooted_io.direct_file_record_bound_input_rooted(
                    root, path, label="B0 runtime source"
                )
            )
        except queue_builder.rooted_io.gov.G0GovernanceError as error:
            raise B0MaterializationRuntimeError(f"B0 source is missing: {raw}") from error
        if (
            source_record["sha256"] != revalidated["observed_sha256"]
            or int(source_record["size_bytes"])
            != int(revalidated["resolved_target_identity"]["size_bytes"])
        ):
            raise B0MaterializationRuntimeError(
                f"B0 source changed across identity revalidation: {raw}"
            )
        observed = {
            "path": raw,
            "sha256": revalidated["observed_sha256"],
            "size_bytes": int(
                revalidated["resolved_target_identity"]["size_bytes"]
            ),
            "source_path_identity": dict(frozen_identity),
        }
        cache[raw] = observed
    if observed["sha256"] != recipe["source_raw_sha256"]:
        raise B0MaterializationRuntimeError(f"B0 source hash drift: {raw}")
    return dict(observed)


def build_intent_payload(
    *,
    recorded_at: str,
    plan: Mapping[str, Any],
    plan_record: Mapping[str, object],
) -> dict[str, object]:
    queue_builder.allocation_stamp(recorded_at)
    payload: dict[str, object] = {
        "schema_version": INTENT_SCHEMA,
        "status": INTENT_STATUS,
        "recorded_at": recorded_at,
        "materialization_lock": dict(plan_record),
        "materialization_lock_hash": plan[plan_builder.SELF_HASH],
        "targets": [
            {
                "window_id": item["window_id"],
                "target_path": item["target_path"],
                "expected_sha256": item["expected_sha256"],
                "expected_size_bytes": item["expected_size_bytes"],
                "recipe_hash": item["recipe_hash"],
                "allowed_pre_state": "ABSENT_OR_EXACT_RECONCILE",
            }
            for item in plan["recipes"]
        ],
        "target_count": 20,
        "mutation_policy": {
            "same_directory_stage": True,
            "hardlink_no_replace": True,
            "race_winner_never_unlinked": True,
            "resume_requires_same_plan_and_exact_targets": True,
            "receipt_then_play_input_lock_commit_last": True,
        },
        "vins_execution_allowed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[INTENT_HASH] = document_hash(payload, INTENT_HASH)
    return payload


def validate_intent_payload(
    payload: Mapping[str, Any], plan: Mapping[str, Any]
) -> None:
    targets = payload.get("targets")
    expected = [
        {
            "window_id": item["window_id"],
            "target_path": item["target_path"],
            "expected_sha256": item["expected_sha256"],
            "expected_size_bytes": item["expected_size_bytes"],
            "recipe_hash": item["recipe_hash"],
            "allowed_pre_state": "ABSENT_OR_EXACT_RECONCILE",
        }
        for item in plan["recipes"]
    ]
    if (
        payload.get("schema_version") != INTENT_SCHEMA
        or payload.get("status") != INTENT_STATUS
        or payload.get(INTENT_HASH) != document_hash(payload, INTENT_HASH)
        or payload.get("materialization_lock_hash")
        != plan.get(plan_builder.SELF_HASH)
        or payload.get("target_count") != 20
        or targets != expected
        or payload.get("mutation_policy")
        != {
            "same_directory_stage": True,
            "hardlink_no_replace": True,
            "race_winner_never_unlinked": True,
            "resume_requires_same_plan_and_exact_targets": True,
            "receipt_then_play_input_lock_commit_last": True,
        }
        or payload.get("vins_execution_allowed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0MaterializationRuntimeError("B0 mutation intent drift")


def ensure_durable_intent(
    *,
    root: Path,
    recorded_at: str,
    plan: Mapping[str, Any],
    plan_record: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, object]]:
    relative = INTENT.relative_to(ROOT).as_posix()
    expected = build_intent_payload(
        recorded_at=recorded_at, plan=plan, plan_record=plan_record
    )
    if queue_builder.formal_io.destination_exists(root, relative):
        try:
            content, identity = queue_builder.formal_io.read_direct_bytes(root, relative)
            payload = json.loads(content)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            queue_builder.formal_io.FormalIOError,
        ) as error:
            raise B0MaterializationRuntimeError("cannot reconcile B0 mutation intent") from error
        if not isinstance(payload, dict) or payload != expected:
            raise B0MaterializationRuntimeError("existing B0 mutation intent is not exact")
        validate_intent_payload(payload, plan)
        return payload, _portable_record({
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            **identity,
        })
    record = queue_builder.formal_io.publish_json_no_clobber(root, relative, expected)
    validate_intent_payload(expected, plan)
    return expected, _portable_record(record)


def _converter_argv(recipe: Mapping[str, Any], temporary: Path) -> list[str]:
    template = recipe.get("converter_argv_template")
    if not isinstance(template, list) or template.count("{OUTPUT}") != 1:
        raise B0MaterializationRuntimeError("B0 converter template token drift")
    argv = [str(temporary) if value == "{OUTPUT}" else str(value) for value in template]
    if argv[:3] != ["python3", "-m", "uw_frontend.datasets.aqualoc_raw_to_rosbag"]:
        raise B0MaterializationRuntimeError("unallowlisted B0 converter entrypoint")
    if recipe["window_id"] == "aqualoc_archaeology:A04:0002":
        try:
            raw_root = argv[argv.index("--raw-root") + 1]
        except (ValueError, IndexError) as error:
            raise B0MaterializationRuntimeError("A04 converter lacks --raw-root") from error
        if raw_root != ".":
            raise B0MaterializationRuntimeError("A04 converter must execute --raw-root .")
    return argv


def materialize_or_reconcile(
    root: Path,
    recipe: Mapping[str, Any],
    *,
    source_cache: dict[str, dict[str, object]],
    timeout_s: int,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]] = inspect_rosbag,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> tuple[dict[str, object], dict[str, object]]:
    source = _verify_source(root, recipe, source_cache)
    target = _safe_workspace_path(root, str(recipe["target_path"]))
    target_state = _bound_path_state(root, target, label="B0 materialization target")
    if target_state == "FILE":
        observation = inspect_exact_target(root, recipe, bag_inspector=bag_inspector)
        observation["materialization_action"] = "RECONCILED_EXACT_EXISTING"
        return observation, source
    if target_state != "ABSENT":
        raise B0MaterializationRuntimeError("B0 target is not a direct file/absence")
    if recipe["disposition"] not in {
        "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
        "EXACT_COPY_REQUIRED_OR_RECONCILE",
    }:
        raise B0MaterializationRuntimeError(f"required prematerialized B0 target missing: {target}")
    required = int(recipe["expected_size_bytes"]) + plan_builder.CAPACITY_RESERVE_BYTES
    resolved_parent = _ensure_exact_cache_parent(root, recipe)
    if shutil.disk_usage(resolved_parent).free < required:
        raise B0MaterializationRuntimeError("B0 target capacity gate failed")
    temporary_name = f".{target.name}.partial.{os.getpid()}.{secrets.token_hex(12)}"
    temporary = resolved_parent / temporary_name
    temporary_lexical = target.parent / temporary_name
    try:
        temp_parent_fd = queue_builder.rooted_io._open_absolute_directory(
            resolved_parent, label="B0 temporary parent"
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationRuntimeError("B0 temporary parent is unsafe") from error
    try:
        try:
            os.stat(temporary_name, dir_fd=temp_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(temporary)
    finally:
        os.close(temp_parent_fd)
    is_copy = recipe["disposition"] == "EXACT_COPY_REQUIRED_OR_RECONCILE"
    argv = None if is_copy else _converter_argv(recipe, temporary)
    try:
        if is_copy:
            copy_record = _copy_exact_source(
                root,
                _safe_workspace_path(root, str(recipe["source_raw_path"])),
                temporary,
                recipe,
            )
            if (
                copy_record["copied_sha256"] != recipe["expected_sha256"]
                or copy_record["copied_size_bytes"] != recipe["expected_size_bytes"]
            ):
                raise B0MaterializationRuntimeError("AFRL B0 exact-copy drift")
            completed = None
        else:
            completed = subprocess_runner(
                argv,
                cwd=root,
                env=_clean_converter_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
            if int(completed.returncode) != 0:
                raise B0MaterializationRuntimeError(
                    f"B0 converter failed rc={completed.returncode}"
                )
        staged = _inspect_external_staged(
            root, temporary_lexical, recipe, bag_inspector=bag_inspector
        )
        publish_materialized_target_no_clobber(root, temporary, recipe)
        observation = inspect_exact_target(root, recipe, bag_inspector=bag_inspector)
        if any(
            staged[key] != observation[key]
            for key in ("sha256", "size_bytes", "device", "inode")
        ):
            raise B0MaterializationRuntimeError("B0 target changed during hardlink publish")
        observation["materialization_action"] = "MATERIALIZED_AND_LINKED_NOREPLACE"
        if is_copy:
            observation["copy"] = copy_record
        else:
            output = getattr(completed, "stdout", b"") or b""
            observation["converter"] = {
                "argv": argv,
                "returncode": int(completed.returncode),
                "stdout_sha256": hashlib.sha256(output).hexdigest(),
                "stdout_size_bytes": len(output),
                "run_vins": False,
            }
        return observation, source
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        directory_fd = queue_builder.rooted_io._open_absolute_directory(
            resolved_parent, label="B0 cleanup parent"
        )
        try:
            _fsync_directory(directory_fd)
        finally:
            os.close(directory_fd)


def _inspect_external_staged(
    root: Path,
    path: Path,
    recipe: Mapping[str, Any],
    *,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]],
) -> dict[str, object]:
    record, identity, bag = _inspect_bound_bag_snapshot(
        root, path, recipe, bag_inspector=bag_inspector
    )
    target = identity["resolved_target_identity"]
    return {
        "sha256": record["sha256"],
        "size_bytes": int(record["size_bytes"]),
        "device": int(target["device"]),
        "inode": int(target["inode"]),
        "bag_integrity": bag,
    }


def build_receipt_payload(
    *,
    completed_at: str,
    plan: Mapping[str, Any],
    plan_record: Mapping[str, object],
    intent: Mapping[str, Any],
    intent_record: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
    source_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    queue_builder.allocation_stamp(completed_at)
    payload: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "completed_at": completed_at,
        "materialization_lock": dict(plan_record),
        "materialization_lock_hash": plan[plan_builder.SELF_HASH],
        "materialization_intent": dict(intent_record),
        "materialization_intent_hash": intent[INTENT_HASH],
        "observations": [dict(item) for item in observations],
        "source_revalidation": [dict(item) for item in source_records],
        "window_count": 20,
        "all_targets_sha256_and_topic_counts_verified": True,
        "all_camera_windows_from_header_stamps": True,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[RECEIPT_HASH] = document_hash(payload, RECEIPT_HASH)
    return payload


def validate_receipt_payload(
    payload: Mapping[str, Any],
    plan: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> None:
    observations = payload.get("observations")
    if (
        payload.get("schema_version") != RECEIPT_SCHEMA
        or payload.get("status") != RECEIPT_STATUS
        or payload.get(RECEIPT_HASH) != document_hash(payload, RECEIPT_HASH)
        or payload.get("materialization_lock_hash") != plan.get(plan_builder.SELF_HASH)
        or payload.get("materialization_intent_hash") != intent.get(INTENT_HASH)
        or payload.get("window_count") != 20
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or not isinstance(observations, list)
        or len(observations) != 20
    ):
        raise B0MaterializationRuntimeError("B0 materialization receipt drift")
    if {item.get("window_id") for item in observations if isinstance(item, dict)} != {
        item["window_id"] for item in plan["recipes"]
    }:
        raise B0MaterializationRuntimeError("B0 receipt window coverage drift")
    recipe_by_window = {item["window_id"]: item for item in plan["recipes"]}
    for observation in observations:
        if not isinstance(observation, dict):
            raise B0MaterializationRuntimeError("invalid B0 receipt observation")
        recipe = recipe_by_window[str(observation["window_id"])]
        integrity = observation.get("bag_integrity")
        if not isinstance(integrity, dict):
            raise B0MaterializationRuntimeError("B0 receipt target/window drift")
        try:
            common.validate_absolute_ros_epoch_window(
                integrity.get("start_ros_time_ns"),
                integrity.get("end_ros_time_ns"),
                label="B0 receipt camera window",
            )
        except common.BackendReplayViolation as error:
            raise B0MaterializationRuntimeError(
                "B0 receipt target/window drift"
            ) from error
        expected_stamp_range = recipe.get("expected_camera_stamp_range_ns")
        if (
            observation.get("target_path") != recipe["target_path"]
            or observation.get("sha256") != recipe["expected_sha256"]
            or int(observation.get("size_bytes", -1)) != int(recipe["expected_size_bytes"])
            or observation.get("recipe_hash") != recipe["recipe_hash"]
            or (
                expected_stamp_range is not None
                and expected_stamp_range
                != {
                    "first": integrity["start_ros_time_ns"],
                    "last": integrity["end_ros_time_ns"],
                }
            )
            or integrity.get("trajectory_values_interpreted") is not False
        ):
            raise B0MaterializationRuntimeError("B0 receipt target/window drift")


def build_b0_play_inputs_payload(
    *,
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_record: Mapping[str, object],
    root: Path,
) -> dict[str, object]:
    by_window = {
        str(item["window_id"]): item for item in receipt["observations"]
    }
    entries: list[dict[str, object]] = []
    ids: dict[str, str] = {}
    for recipe in plan["recipes"]:
        window_id = str(recipe["window_id"])
        observation = by_window[window_id]
        integrity = observation["bag_integrity"]
        identity = common.capture_canonical_input_identity(
            root,
            str(recipe["target_path"]),
            expected_sha256=str(recipe["expected_sha256"]),
            verify_sha256=True,
        )
        derivation: dict[str, object] = {
            "kind": recipe["derivation_kind"],
            "source_raw_path": recipe["source_raw_path"],
            "source_raw_sha256": recipe["source_raw_sha256"],
        }
        derivation["derivation_hash"] = common.canonical_json_hash(
            derivation, "derivation_hash"
        )
        id_payload = {
            "window_id": window_id,
            "target_path": recipe["target_path"],
            "expected_sha256": recipe["expected_sha256"],
            "start_ros_time_ns": integrity["start_ros_time_ns"],
            "end_ros_time_ns": integrity["end_ros_time_ns"],
            "source_provenance_hash": recipe["source_provenance_hash"],
        }
        play_input_id = common.sha256_bytes(
            json.dumps(id_payload, sort_keys=True, separators=(",", ":")).encode()
        )
        ids[window_id] = play_input_id
        entries.append(
            {
                "play_input_id": play_input_id,
                "window_id": window_id,
                "dataset_family": recipe["dataset_family"],
                "sequence": recipe["sequence"],
                "runner_start": recipe["runner_start"],
                "runner_end_or_duration": recipe["runner_end_or_duration"],
                "runner_unit": recipe["runner_unit"],
                "expected_sha256": recipe["expected_sha256"],
                "source_provenance_hash": recipe["source_provenance_hash"],
                "path_identity": identity,
                "derivation": derivation,
                "evaluation_window": {
                    "start_ros_time_ns": int(integrity["start_ros_time_ns"]),
                    "end_ros_time_ns": int(integrity["end_ros_time_ns"]),
                    "camera_topic": recipe["camera_topic"],
                    "stamp_source": "sensor_msgs/Image.header.stamp",
                    "boundary_rule": (
                        "FIRST_INCLUDED_CAMERA_STAMP_TO_LAST_INCLUDED_CAMERA_STAMP_INCLUSIVE"
                    ),
                    "derivation_evidence": dict(receipt_record),
                },
            }
        )
    bindings = [
        {**dict(binding), "play_input_id": ids[str(binding["window_id"])]}
        for binding in plan["queue_bindings"]
    ]
    payload: dict[str, object] = {
        "schema_version": common.B0_PLAY_INPUTS_SCHEMA,
        "status": common.B0_PLAY_INPUTS_STATUS,
        "materialization_lock_hash": plan[plan_builder.SELF_HASH],
        "materialization_receipt": dict(receipt_record),
        "materialization_receipt_hash": receipt[RECEIPT_HASH],
        "materialization_intent_hash": receipt["materialization_intent_hash"],
        "entries": entries,
        "queue_bindings": bindings,
        "policy": {
            "all_b0_queue_rows_bound": True,
            "full_sha256_before_and_after_each_replay": True,
            "path_link_target_identity_before_and_after_each_replay": True,
            "preparation_must_not_create_or_replace_play_input": True,
            "derived_inputs_materialized_before_execution_lock": True,
            "trajectory_values_interpreted": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[common.B0_PLAY_INPUTS_SELF_HASH] = common.canonical_json_hash(
        payload, common.B0_PLAY_INPUTS_SELF_HASH
    )
    common.validate_b0_play_inputs_shape(payload, plan["queue_bindings"])
    return payload


def _receipt_record_from_bytes(root: Path, content: bytes) -> dict[str, object]:
    return {
        "path": RECEIPT.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def execute(
    *,
    completed_at: str,
    timeout_s: int,
    root: Path = ROOT,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]] = inspect_rosbag,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    plan, plan_record = load_frozen_plan(root=root)
    final_relative = FINAL.relative_to(ROOT).as_posix()
    receipt_relative = RECEIPT.relative_to(ROOT).as_posix()
    with queue_builder.formal_io.global_formal_lock(ACTION_FLOCK):
        if queue_builder.formal_io.destination_exists(root, final_relative):
            raise FileExistsError(FINAL)
        intent, intent_record = ensure_durable_intent(
            root=root,
            recorded_at=completed_at,
            plan=plan,
            plan_record=plan_record,
        )
        source_cache: dict[str, dict[str, object]] = {}
        observations: list[dict[str, object]] = []
        if queue_builder.formal_io.destination_exists(root, receipt_relative):
            try:
                receipt_bytes, _receipt_identity = (
                    queue_builder.formal_io.read_direct_bytes(root, receipt_relative)
                )
                receipt = json.loads(receipt_bytes)
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValueError,
                queue_builder.formal_io.FormalIOError,
            ) as error:
                raise B0MaterializationRuntimeError(
                    "cannot reconcile B0 materialization receipt"
                ) from error
            if not isinstance(receipt, dict):
                raise B0MaterializationRuntimeError("existing B0 receipt is not an object")
            validate_receipt_payload(receipt, plan, intent)
            if receipt.get("completed_at") != completed_at:
                raise B0MaterializationRuntimeError(
                    "B0 resume timestamp differs from durable intent/receipt"
                )
            frozen_observations = {
                str(item["window_id"]): item for item in receipt["observations"]
            }
            for recipe in plan["recipes"]:
                _verify_source(root, recipe, source_cache)
                observed = inspect_exact_target(
                    root, recipe, bag_inspector=bag_inspector
                )
                frozen = frozen_observations[str(recipe["window_id"])]
                for key in (
                    "target_path",
                    "sha256",
                    "size_bytes",
                    "device",
                    "inode",
                    "recipe_hash",
                    "bag_integrity",
                ):
                    if observed.get(key) != frozen.get(key):
                        raise B0MaterializationRuntimeError(
                            f"B0 receipt resume target drift: {recipe['window_id']}:{key}"
                        )
        else:
            for recipe in plan["recipes"]:
                observation, _source = materialize_or_reconcile(
                    root,
                    recipe,
                    source_cache=source_cache,
                    timeout_s=timeout_s,
                    bag_inspector=bag_inspector,
                    subprocess_runner=subprocess_runner,
                )
                observations.append(observation)
            receipt = build_receipt_payload(
                completed_at=completed_at,
                plan=plan,
                plan_record=plan_record,
                intent=intent,
                intent_record=intent_record,
                observations=observations,
                source_records=[source_cache[key] for key in sorted(source_cache)],
            )
            validate_receipt_payload(receipt, plan, intent)
            receipt_bytes = queue_builder.json_bytes(receipt)
        receipt_record = _receipt_record_from_bytes(root, receipt_bytes)
        final = build_b0_play_inputs_payload(
            plan=plan,
            receipt=receipt,
            receipt_record=receipt_record,
            root=root,
        )
        queue_builder.formal_io.publish_bundle_commit_last(
            root,
            [(receipt_relative, receipt_bytes)],
            commit_artifact=(final_relative, queue_builder.json_bytes(final)),
        )
        return final


def preflight(
    *,
    root: Path = ROOT,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, object]] = inspect_rosbag,
) -> dict[str, object]:
    plan, plan_record = load_frozen_plan(root=root)
    required = int(plan["capacity"]["required_free_bytes"])
    capacity_path = queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS.get(
        "datasets", root / "datasets"
    )
    free = shutil.disk_usage(capacity_path).free
    if free < required:
        raise B0MaterializationRuntimeError("B0 preflight capacity gate failed")
    if queue_builder.formal_io.destination_exists(
        root, FINAL.relative_to(ROOT).as_posix()
    ):
        raise FileExistsError(FINAL)
    source_cache: dict[str, dict[str, object]] = {}
    reconcile_count = 0
    missing_count = 0
    for recipe in plan["recipes"]:
        _verify_source(root, recipe, source_cache)
        target = _safe_workspace_path(root, str(recipe["target_path"]))
        state = _bound_path_state(root, target, label="B0 preflight target")
        if state == "FILE":
            inspect_exact_target(root, recipe, bag_inspector=bag_inspector)
            reconcile_count += 1
        elif state == "ABSENT" and recipe["disposition"] in {
            "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
            "EXACT_COPY_REQUIRED_OR_RECONCILE",
        }:
            missing_count += 1
        else:
            raise B0MaterializationRuntimeError(
                f"required prematerialized B0 target is missing: {target}"
            )
    formal_state = "PLAN_ONLY"
    intent_relative = INTENT.relative_to(ROOT).as_posix()
    receipt_relative = RECEIPT.relative_to(ROOT).as_posix()
    intent: dict[str, Any] | None = None
    if queue_builder.formal_io.destination_exists(root, intent_relative):
        content, _identity = queue_builder.formal_io.read_direct_bytes(
            root, intent_relative
        )
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise B0MaterializationRuntimeError("invalid existing B0 intent") from error
        if not isinstance(value, dict):
            raise B0MaterializationRuntimeError("existing B0 intent is not an object")
        validate_intent_payload(value, plan)
        if value.get("materialization_lock") != plan_record:
            raise B0MaterializationRuntimeError("B0 intent/plan artifact identity drift")
        intent = value
        formal_state = "INTENT_DURABLE_RESUME"
    if queue_builder.formal_io.destination_exists(root, receipt_relative):
        if intent is None:
            raise B0MaterializationRuntimeError("B0 receipt exists without intent")
        content, _identity = queue_builder.formal_io.read_direct_bytes(
            root, receipt_relative
        )
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise B0MaterializationRuntimeError("invalid existing B0 receipt") from error
        if not isinstance(value, dict):
            raise B0MaterializationRuntimeError("existing B0 receipt is not an object")
        validate_receipt_payload(value, plan, intent)
        formal_state = "RECEIPT_DURABLE_CLOSEOUT_PENDING"
    return {
        "status": "READY_FOR_EXPLICIT_EXECUTE_OR_EXACT_RESUME",
        "window_count": 20,
        "required_free_bytes": required,
        "observed_free_bytes": free,
        "materialization_lock_hash": plan[plan_builder.SELF_HASH],
        "formal_state": formal_state,
        "exact_existing_target_count": reconcile_count,
        "missing_authorized_target_count": missing_count,
        "source_record_count": len(source_cache),
        "held_out_trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--completed-at")
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(preflight(), indent=2, sort_keys=True))
        return 0
    if not args.completed_at:
        parser.error("--completed-at is required with --execute")
    payload = execute(completed_at=args.completed_at, timeout_s=args.timeout_s)
    print(
        "P07_B0_PLAY_INPUTS_FROZEN "
        f"hash={payload[common.B0_PLAY_INPUTS_SELF_HASH]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
