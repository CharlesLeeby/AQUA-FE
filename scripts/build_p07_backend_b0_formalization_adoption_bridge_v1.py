#!/usr/bin/env python3
"""Bind the frozen B0 v1 materializer to the formalization adoption authority.

The already-frozen B0 v1 sources cannot be edited after the unplanned queue
formalization.  This additive bridge therefore has two immutable stages:

* a pre-materialization lock that must exist before the v1 executor is called;
* a post-materialization closeout that binds the resulting intent, receipt and
  final B0 play-input contract.

Neither stage authorizes a backend replay, G0 evaluation, ROS, or VINS.
"""

from __future__ import annotations

import argparse
import contextvars
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence

try:
    from scripts import build_p07_backend_b0_materialization_lock_v1 as b0_plan
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import run_p07_backend_b0_materialization_v1 as b0_runtime
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_b0_materialization_lock_v1 as b0_plan  # type: ignore
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_review_evidence_v1 as review_evidence  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import run_p07_backend_b0_materialization_v1 as b0_runtime  # type: ignore


ROOT = queue_builder.ROOT
P07 = queue_builder.P07
PRELOCK = P07 / "backend_b0_formalization_adoption_prelock_v1.json"
ACTION_INTENT = P07 / "backend_b0_formalization_adoption_action_intent_v1.json"
CLOSEOUT = P07 / "backend_b0_formalization_adoption_closeout_v1.json"
PRELOCK_SCHEMA = "isj-p07-backend-b0-formalization-adoption-prelock-v1"
PRELOCK_STATUS = "FROZEN_ADOPTION_AUTHORITY_BEFORE_B0_MATERIALIZATION"
PRELOCK_HASH = "b0_adoption_prelock_hash"
ACTION_INTENT_SCHEMA = "isj-p07-backend-b0-formalization-adoption-action-intent-v1"
ACTION_INTENT_STATUS = "FROZEN_ADOPTED_B0_ACTION_BEFORE_FIRST_CACHE_MUTATION"
ACTION_INTENT_HASH = "b0_adoption_action_intent_hash"
CLOSEOUT_SCHEMA = "isj-p07-backend-b0-formalization-adoption-closeout-v1"
CLOSEOUT_STATUS = "PASS_B0_MATERIALIZATION_BOUND_TO_ADOPTION"
CLOSEOUT_HASH = "b0_adoption_closeout_hash"
OUTCOME_BOUNDARY = "B0_INPUT_PREPARATION_ONLY_NO_BACKEND_REPLAY_G0_VINS_APE_RPE"
HEX64 = re.compile(r"[0-9a-f]{64}")
CACHE_MUTATION_DISPOSITIONS = {
    "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
    "EXACT_COPY_REQUIRED_OR_RECONCILE",
}
FORMAL_ABSENCE_PATHS = (
    ACTION_INTENT.relative_to(ROOT).as_posix(),
    b0_plan.INTENT.relative_to(ROOT).as_posix(),
    b0_plan.RECEIPT.relative_to(ROOT).as_posix(),
    b0_plan.FINAL_OUTPUT.relative_to(ROOT).as_posix(),
    CLOSEOUT.relative_to(ROOT).as_posix(),
)
RELATED_PROCESS_PROTOCOL = "PYTHON_B0_EXECUTE_OR_AQUALOC_CONVERTER_EXACT_ARGV_V1"
_LOCKS_HELD: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "p07_b0_adoption_bridge_locks_held", default=False
)

BRIDGE_BUILDER = "scripts/build_p07_backend_b0_formalization_adoption_bridge_v1.py"
BRIDGE_RUNNER = "scripts/run_p07_backend_b0_materialization_adopted_v1.py"
BRIDGE_TEST = "scripts/tests/test_p07_backend_b0_formalization_adoption_bridge_v1.py"
FROZEN_B0_SOURCES = (
    "scripts/build_p07_backend_b0_materialization_lock_v1.py",
    "scripts/run_p07_backend_b0_materialization_v1.py",
    "scripts/tests/test_p07_backend_b0_materialization_v1.py",
)
REQUIRED_SOURCE_PATHS = tuple(sorted((*FROZEN_B0_SOURCES, BRIDGE_BUILDER, BRIDGE_RUNNER, BRIDGE_TEST)))

PRELOCK_KEYS = {
    "schema_version",
    "status",
    "frozen_at",
    "formalization_adoption",
    "formalization_review_evidence",
    "b0_materialization_plan",
    "source_artifacts",
    "source_artifacts_hash",
    "cache_namespace_pre_state",
    "formal_output_pre_state",
    "process_quiescence",
    "authorization",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    PRELOCK_HASH,
}
ACTION_INTENT_KEYS = {
    "schema_version",
    "status",
    "recorded_at",
    "formalization_adoption",
    "formalization_review_evidence",
    "pre_materialization_lock",
    "b0_materialization_plan",
    "wrapper_argv",
    "wrapper_argv_hash",
    "frozen_runtime_call",
    "plan_source_hashes",
    "source_artifacts",
    "source_artifacts_hash",
    "cache_namespace_pre_state",
    "formal_output_pre_state",
    "process_quiescence",
    "authorization",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    ACTION_INTENT_HASH,
}
CLOSEOUT_KEYS = {
    "schema_version",
    "status",
    "closed_at",
    "formalization_adoption",
    "formalization_review_evidence",
    "pre_materialization_lock",
    "materialization_action_intent",
    "b0_materialization_plan",
    "b0_materialization_intent",
    "b0_materialization_receipt",
    "b0_play_inputs",
    "cache_finalization",
    "artifact_time_order",
    "no_partial_or_staging_entries",
    "process_quiescence",
    "authorization",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    CLOSEOUT_HASH,
}
AUTHORIZATION = {
    "b0_input_materialization_authorized_by_prelock": True,
    "backend_replay_authorized": False,
    "g0_evaluation_authorized": False,
    "ros_authorized": False,
    "vins_authorized": False,
}


class B0AdoptionBridgeError(RuntimeError):
    """The additive B0 adoption bridge is absent, malformed, or drifted."""


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise B0AdoptionBridgeError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise B0AdoptionBridgeError("timestamp must include timezone")
    return parsed


@contextmanager
def governance_locks() -> Iterator[None]:
    """Take the global formal mutex before the frozen B0 action mutex."""

    if _LOCKS_HELD.get():
        raise B0AdoptionBridgeError("B0 adoption governance locks are not reentrant")
    with queue_builder.formal_io.global_formal_lock():
        with queue_builder.formal_io.global_formal_lock(b0_runtime.ACTION_FLOCK):
            token = _LOCKS_HELD.set(True)
            try:
                yield
            finally:
                _LOCKS_HELD.reset(token)


def require_governance_locks() -> None:
    if not _LOCKS_HELD.get():
        raise B0AdoptionBridgeError("global+B0 governance mutexes are required")


@contextmanager
def reuse_held_locks_for_frozen_runtime() -> Iterator[None]:
    """Let the frozen v1 executor reuse the bridge-owned global/B0 flocks."""

    require_governance_locks()
    original = queue_builder.formal_io.global_formal_lock
    allowed = {
        queue_builder.formal_io.GLOBAL_FLOCK.absolute(),
        b0_runtime.ACTION_FLOCK.absolute(),
    }

    @contextmanager
    def already_held(path: Path = queue_builder.formal_io.GLOBAL_FLOCK) -> Iterator[None]:
        if Path(path).absolute() not in allowed:
            raise B0AdoptionBridgeError(f"frozen runtime requested an unheld mutex: {path}")
        yield

    queue_builder.formal_io.global_formal_lock = already_held
    try:
        yield
    finally:
        queue_builder.formal_io.global_formal_lock = original


def _cache_prefixes(name: str) -> tuple[str, ...]:
    return (
        f".{name}.partial",
        f".{name}.staging",
        f"{name}.partial",
        f"{name}.staging",
    )


def _lexical_namespace_state(
    root: Path, relative: str, *, prefixes: Sequence[str] = ()
) -> dict[str, object]:
    """Inspect one lexical leaf and sibling namespace without following links."""

    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise B0AdoptionBridgeError(f"unsafe lexical path: {relative}")
    descriptors: list[int] = []
    try:
        current = queue_builder.formal_io._open_root_dirfd(root.absolute())
        descriptors.append(current)
        walked: list[str] = []
        for component in pure.parts[:-1]:
            walked.append(component)
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return {
                    "path": pure.as_posix(),
                    "lexical_state": "ABSENT",
                    "parent_state": "ABSENT",
                    "first_absent_component": "/".join(walked),
                    "matching_partial_or_staging_entries": [],
                }
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise B0AdoptionBridgeError(
                    f"lexical parent is not a direct directory: {'/'.join(walked)}"
                )
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            descriptors.append(child)
            current = child
        parent_info = os.fstat(current)
        try:
            leaf_info = os.stat(pure.name, dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            lexical_state = "ABSENT"
        else:
            lexical_state = (
                "SYMLINK"
                if stat.S_ISLNK(leaf_info.st_mode)
                else "REGULAR"
                if stat.S_ISREG(leaf_info.st_mode)
                else "OTHER"
            )
        names = sorted(
            name for name in os.listdir(current) if any(name.startswith(p) for p in prefixes)
        )
        return {
            "path": pure.as_posix(),
            "lexical_state": lexical_state,
            "parent_state": "DIRECTORY",
            "parent_device": int(parent_info.st_dev),
            "parent_inode": int(parent_info.st_ino),
            "matching_partial_or_staging_entries": names,
        }
    except OSError as error:
        raise B0AdoptionBridgeError(f"cannot inspect lexical namespace: {relative}") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture_cache_namespace_absence(
    plan: Mapping[str, Any], *, root: Path = ROOT
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    recipes = plan.get("recipes")
    if not isinstance(recipes, list):
        raise B0AdoptionBridgeError("B0 plan recipes are absent")
    for recipe in sorted(recipes, key=lambda item: str(item.get("target_path", ""))):
        if recipe.get("disposition") not in CACHE_MUTATION_DISPOSITIONS:
            continue
        relative = str(recipe.get("target_path", ""))
        state = _lexical_namespace_state(
            root, relative, prefixes=_cache_prefixes(PurePosixPath(relative).name)
        )
        if state["lexical_state"] != "ABSENT" or state[
            "matching_partial_or_staging_entries"
        ]:
            raise B0AdoptionBridgeError(f"B0 cache namespace is not pristine: {relative}")
        result.append(
            {
                "window_id": str(recipe.get("window_id", "")),
                "target_path": relative,
                "expected_sha256": str(recipe.get("expected_sha256", "")),
                "expected_size_bytes": int(recipe.get("expected_size_bytes", 0)),
                "recipe_hash": str(recipe.get("recipe_hash", "")),
                "namespace": state,
            }
        )
    if not result:
        raise B0AdoptionBridgeError("B0 plan has no governed cache mutation target")
    return result


def capture_formal_output_absence(*, root: Path = ROOT) -> list[dict[str, object]]:
    result = [_lexical_namespace_state(root, relative) for relative in FORMAL_ABSENCE_PATHS]
    if any(item["lexical_state"] != "ABSENT" for item in result):
        present = [item["path"] for item in result if item["lexical_state"] != "ABSENT"]
        raise B0AdoptionBridgeError(f"B0 formal output already exists: {present}")
    return result


def _hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(queue_builder.canonical_json(clone).encode("utf-8")).hexdigest()


def _relative(path: Path, *, root: Path) -> str:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as error:
        raise B0AdoptionBridgeError(f"path escapes workspace: {path}") from error
    if not relative.parts or ".." in relative.parts:
        raise B0AdoptionBridgeError(f"unsafe workspace path: {path}")
    return relative.as_posix()


def _strict_json(root: Path, relative: str, *, label: str) -> tuple[dict[str, Any], dict[str, object]]:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise B0AdoptionBridgeError(f"unsafe {label} path")
    try:
        content, _identity = queue_builder.formal_io.read_direct_bytes(root, pure.as_posix())
    except Exception as error:
        raise B0AdoptionBridgeError(f"missing or unsafe {label}") from error

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise B0AdoptionBridgeError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise B0AdoptionBridgeError(f"invalid {label} JSON") from error
    if not isinstance(value, dict) or content != queue_builder.json_bytes(value):
        raise B0AdoptionBridgeError(f"noncanonical {label} JSON")
    return value, {
        "path": pure.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _record(root: Path, relative: str, *, label: str) -> dict[str, object]:
    pure = PurePosixPath(relative)
    try:
        _content, observed = queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            root, root.joinpath(*pure.parts), label=label
        )
    except Exception as error:
        raise B0AdoptionBridgeError(f"missing or unsafe {label}: {relative}") from error
    return {
        "path": pure.as_posix(),
        "sha256": str(observed["sha256"]),
        "size_bytes": int(observed["size_bytes"]),
    }


def _validate_record_shape(value: object, *, expected_path: str | None = None, label: str) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256", "size_bytes"}
        or not isinstance(value.get("path"), str)
        or not HEX64.fullmatch(str(value.get("sha256", "")))
        or not isinstance(value.get("size_bytes"), int)
        or int(value["size_bytes"]) <= 0
        or (expected_path is not None and value.get("path") != expected_path)
    ):
        raise B0AdoptionBridgeError(f"invalid {label} record")
    return dict(value)


def _validate_adoption_binding_shape(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != adoption.ADOPTION_AUTHORITY_BINDING_KEYS
        or value.get("path") != adoption.OUTPUT_RELATIVE
        or not HEX64.fullmatch(str(value.get("sha256", "")))
        or not isinstance(value.get("size_bytes"), int)
        or int(value["size_bytes"]) <= 0
        or not HEX64.fullmatch(
            str(value.get(adoption.SELF_HASH_FIELD, ""))
        )
    ):
        raise B0AdoptionBridgeError("B0 adoption authority binding shape mismatch")
    return dict(value)


def _validate_review_evidence_binding_shape(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != review_evidence.AUTHORITY_BINDING_KEYS
        or value.get("path") != review_evidence.OUTPUT_RELATIVE
        or not HEX64.fullmatch(str(value.get("sha256", "")))
        or not isinstance(value.get("size_bytes"), int)
        or int(value["size_bytes"]) <= 0
        or not HEX64.fullmatch(str(value.get(review_evidence.SELF_HASH_FIELD, "")))
    ):
        raise B0AdoptionBridgeError("B0 review-evidence authority binding shape mismatch")
    return dict(value)


def _artifact_list_hash(records: Sequence[Mapping[str, object]]) -> str:
    return hashlib.sha256(queue_builder.canonical_json([dict(v) for v in records]).encode()).hexdigest()


def _validate_cache_absence_shape(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise B0AdoptionBridgeError("B0 cache absence snapshot is not a list")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "window_id",
                "target_path",
                "expected_sha256",
                "expected_size_bytes",
                "recipe_hash",
                "namespace",
            }
            or not isinstance(item.get("window_id"), str)
            or not isinstance(item.get("target_path"), str)
            or not HEX64.fullmatch(str(item.get("expected_sha256", "")))
            or not HEX64.fullmatch(str(item.get("recipe_hash", "")))
            or not isinstance(item.get("expected_size_bytes"), int)
            or int(item["expected_size_bytes"]) <= 0
            or item["target_path"] in seen
        ):
            raise B0AdoptionBridgeError("invalid/duplicate B0 cache absence record")
        namespace = item.get("namespace")
        if (
            not isinstance(namespace, dict)
            or namespace.get("path") != item["target_path"]
            or namespace.get("lexical_state") != "ABSENT"
            or namespace.get("matching_partial_or_staging_entries") != []
            or namespace.get("parent_state") not in {"ABSENT", "DIRECTORY"}
        ):
            raise B0AdoptionBridgeError("B0 cache namespace was not lexically absent")
        seen.add(str(item["target_path"]))
        result.append(dict(item))
    return result


def _validate_formal_absence_shape(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or [item.get("path") for item in value if isinstance(item, dict)] != list(FORMAL_ABSENCE_PATHS):
        raise B0AdoptionBridgeError("B0 formal absence path/order mismatch")
    for item in value:
        if not isinstance(item, dict) or item.get("lexical_state") != "ABSENT":
            raise B0AdoptionBridgeError("B0 formal output was not lexically absent")
    return [dict(item) for item in value]


def related_materializer_processes() -> list[dict[str, object]]:
    """Return only executable B0/converter processes, never textual search tools."""

    result: list[dict[str, object]] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            raw = (proc / "cmdline").read_bytes()
            fields = [part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part]
            stat_fields = (proc / "stat").read_text(encoding="ascii").split()
        except (OSError, UnicodeError):
            continue
        if not fields or "python" not in PurePosixPath(fields[0]).name.lower():
            continue
        old_execute = any(arg.endswith(FROZEN_B0_SOURCES[1]) for arg in fields) and "--execute" in fields
        converter = any(
            fields[index] == "-m"
            and index + 1 < len(fields)
            and fields[index + 1] == "uw_frontend.datasets.aqualoc_raw_to_rosbag"
            for index in range(len(fields))
        )
        if old_execute or converter:
            result.append(
                {
                    "pid": int(proc.name),
                    "start_ticks": int(stat_fields[21]),
                    "argv_sha256": hashlib.sha256(raw).hexdigest(),
                    "role": "FROZEN_B0_EXECUTOR" if old_execute else "AQUALOC_CONVERTER",
                }
            )
    return sorted(result, key=lambda item: int(item["pid"]))


def capture_process_quiescence() -> dict[str, object]:
    matches = related_materializer_processes()
    if matches:
        raise B0AdoptionBridgeError(f"related B0 materializer process is active: {matches}")
    return {
        "protocol": RELATED_PROCESS_PROTOCOL,
        "matching_process_count": 0,
        "no_related_process_active": True,
    }


def _validate_process_quiescence_shape(value: object) -> None:
    if value != {
        "protocol": RELATED_PROCESS_PROTOCOL,
        "matching_process_count": 0,
        "no_related_process_active": True,
    }:
        raise B0AdoptionBridgeError("B0 process-quiescence evidence drift")


def plan_source_hashes(plan: Mapping[str, Any]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for recipe in plan.get("recipes", []):
        key = (str(recipe.get("source_raw_path", "")), str(recipe.get("source_raw_sha256", "")))
        if not key[0] or not HEX64.fullmatch(key[1]):
            raise B0AdoptionBridgeError("invalid B0 plan source hash")
        grouped.setdefault(key, []).append(str(recipe.get("window_id", "")))
    return [
        {"path": path, "sha256": digest, "window_ids": sorted(windows)}
        for (path, digest), windows in sorted(grouped.items())
    ]


def _self_reference(record: Mapping[str, object], *, field: str, digest: str) -> dict[str, object]:
    result = dict(record)
    result[field] = digest
    return result


def build_prelock_payload(
    *,
    frozen_at: str,
    adoption_binding: Mapping[str, object],
    review_evidence_binding: Mapping[str, object] | None = None,
    plan_record: Mapping[str, object],
    plan_hash: str,
    source_artifacts: Sequence[Mapping[str, object]],
    cache_namespace_pre_state: Sequence[Mapping[str, object]] = (),
    formal_output_pre_state: Sequence[Mapping[str, object]] | None = None,
    process_quiescence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    queue_builder.allocation_stamp(frozen_at)
    if review_evidence_binding is None:  # Backward-compatible synthetic fixture only.
        review_evidence_binding = {
            "path": review_evidence.OUTPUT_RELATIVE,
            "sha256": "0" * 64,
            "size_bytes": 1,
            review_evidence.SELF_HASH_FIELD: "0" * 64,
        }
    if formal_output_pre_state is None:
        formal_output_pre_state = [
            {"path": path, "lexical_state": "ABSENT", "parent_state": "DIRECTORY", "parent_device": 1, "parent_inode": 1, "matching_partial_or_staging_entries": []}
            for path in FORMAL_ABSENCE_PATHS
        ]
    if process_quiescence is None:
        process_quiescence = {
            "protocol": RELATED_PROCESS_PROTOCOL,
            "matching_process_count": 0,
            "no_related_process_active": True,
        }
    artifacts = [dict(item) for item in source_artifacts]
    payload: dict[str, object] = {
        "schema_version": PRELOCK_SCHEMA,
        "status": PRELOCK_STATUS,
        "frozen_at": frozen_at,
        "formalization_adoption": dict(adoption_binding),
        "formalization_review_evidence": dict(review_evidence_binding),
        "b0_materialization_plan": _self_reference(
            plan_record, field=b0_plan.SELF_HASH, digest=plan_hash
        ),
        "source_artifacts": artifacts,
        "source_artifacts_hash": _artifact_list_hash(artifacts),
        "cache_namespace_pre_state": [dict(item) for item in cache_namespace_pre_state],
        "formal_output_pre_state": [dict(item) for item in formal_output_pre_state],
        "process_quiescence": dict(process_quiescence),
        "authorization": dict(AUTHORIZATION),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[PRELOCK_HASH] = _hash(payload, PRELOCK_HASH)
    return payload


def validate_prelock_payload(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    verify_files: bool = True,
    require_preaction_absence: bool = False,
) -> str:
    if (
        set(payload) != PRELOCK_KEYS
        or payload.get("schema_version") != PRELOCK_SCHEMA
        or payload.get("status") != PRELOCK_STATUS
        or payload.get(PRELOCK_HASH) != _hash(payload, PRELOCK_HASH)
        or payload.get("authorization") != AUTHORIZATION
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0AdoptionBridgeError("B0 adoption prelock schema/status/hash drift")
    queue_builder.allocation_stamp(str(payload.get("frozen_at", "")))
    binding = _validate_adoption_binding_shape(payload.get("formalization_adoption"))
    evidence_binding = _validate_review_evidence_binding_shape(
        payload.get("formalization_review_evidence")
    )
    plan_ref = payload.get("b0_materialization_plan")
    plan_relative = _relative(b0_plan.OUTPUT, root=ROOT)
    if (
        not isinstance(plan_ref, dict)
        or set(plan_ref) != {"path", "sha256", "size_bytes", b0_plan.SELF_HASH}
        or plan_ref.get("path") != plan_relative
    ):
        raise B0AdoptionBridgeError("B0 prelock plan reference mismatch")
    records = payload.get("source_artifacts")
    if not isinstance(records, list) or [item.get("path") for item in records if isinstance(item, dict)] != list(REQUIRED_SOURCE_PATHS):
        raise B0AdoptionBridgeError("B0 prelock source artifact set mismatch")
    for expected, record in zip(REQUIRED_SOURCE_PATHS, records):
        _validate_record_shape(record, expected_path=expected, label="B0 bridge source")
    if payload.get("source_artifacts_hash") != _artifact_list_hash(records):
        raise B0AdoptionBridgeError("B0 bridge source artifact aggregate drift")
    cache_snapshot = _validate_cache_absence_shape(payload.get("cache_namespace_pre_state"))
    formal_snapshot = _validate_formal_absence_shape(payload.get("formal_output_pre_state"))
    _validate_process_quiescence_shape(payload.get("process_quiescence"))
    if verify_files:
        try:
            adoption.validate_adoption_authority_binding(binding, root=root)
        except adoption.AdoptionError as error:
            raise B0AdoptionBridgeError("B0 prelock adoption authority drift") from error
        try:
            review_evidence.validate_review_evidence_authority_binding(
                evidence_binding, root=root
            )
        except review_evidence.ReviewEvidenceError as error:
            raise B0AdoptionBridgeError("B0 prelock review-evidence authority drift") from error
        plan, observed = _strict_json(root, plan_relative, label="frozen B0 plan")
        if observed != {key: plan_ref[key] for key in ("path", "sha256", "size_bytes")}:
            raise B0AdoptionBridgeError("B0 prelock plan bytes drift")
        try:
            b0_plan.validate_plan_payload(plan, require_live_artifacts=True, root=root)
        except b0_plan.B0MaterializationError as error:
            raise B0AdoptionBridgeError("frozen B0 plan semantic drift") from error
        if plan.get(b0_plan.SELF_HASH) != plan_ref.get(b0_plan.SELF_HASH):
            raise B0AdoptionBridgeError("B0 prelock plan self-hash drift")
        for expected, record in zip(REQUIRED_SOURCE_PATHS, records):
            if _record(root, expected, label="B0 bridge source") != record:
                raise B0AdoptionBridgeError(f"B0 bridge source drift: {expected}")
        if require_preaction_absence:
            if capture_cache_namespace_absence(plan, root=root) != cache_snapshot:
                raise B0AdoptionBridgeError("B0 cache absence snapshot drift")
            if capture_formal_output_absence(root=root) != formal_snapshot:
                raise B0AdoptionBridgeError("B0 formal absence snapshot drift")
            capture_process_quiescence()
    return str(payload[PRELOCK_HASH])


def build_live_prelock(*, frozen_at: str, root: Path = ROOT) -> dict[str, object]:
    root = root.absolute()
    plan, plan_record = _strict_json(
        root, _relative(b0_plan.OUTPUT, root=ROOT), label="frozen B0 plan"
    )
    b0_plan.validate_plan_payload(plan, require_live_artifacts=True, root=root)
    artifacts = [_record(root, path, label="B0 bridge source") for path in REQUIRED_SOURCE_PATHS]
    payload = build_prelock_payload(
        frozen_at=frozen_at,
        adoption_binding=adoption.adoption_authority_binding(root=root),
        review_evidence_binding=review_evidence.review_evidence_authority_binding(root=root),
        plan_record=plan_record,
        plan_hash=str(plan[b0_plan.SELF_HASH]),
        source_artifacts=artifacts,
        cache_namespace_pre_state=capture_cache_namespace_absence(plan, root=root),
        formal_output_pre_state=capture_formal_output_absence(root=root),
        process_quiescence=capture_process_quiescence(),
    )
    validate_prelock_payload(
        payload, root=root, verify_files=True, require_preaction_absence=True
    )
    return payload


def load_prelock(
    *, root: Path = ROOT, require_preaction_absence: bool = False
) -> tuple[dict[str, object], dict[str, object]]:
    payload, record = _strict_json(
        root.absolute(), _relative(PRELOCK, root=ROOT), label="B0 adoption prelock"
    )
    validate_prelock_payload(
        payload,
        root=root.absolute(),
        verify_files=True,
        require_preaction_absence=require_preaction_absence,
    )
    return payload, record


def canonical_wrapper_argv(
    *, action_started_at: str, completed_at: str, closed_at: str, timeout_s: int
) -> list[str]:
    if timeout_s <= 0:
        raise B0AdoptionBridgeError("B0 materialization timeout must be positive")
    for value in (action_started_at, completed_at, closed_at):
        queue_builder.allocation_stamp(value)
    if not (_timestamp(action_started_at) < _timestamp(completed_at) < _timestamp(closed_at)):
        raise B0AdoptionBridgeError("B0 action/completion/closeout timestamps are not strict")
    return [
        "python3",
        BRIDGE_RUNNER,
        "--execute",
        "--action-started-at",
        action_started_at,
        "--completed-at",
        completed_at,
        "--closed-at",
        closed_at,
        "--timeout-s",
        str(timeout_s),
    ]


def _frozen_runtime_call(*, completed_at: str, timeout_s: int) -> dict[str, object]:
    return {
        "kind": "IN_PROCESS_CALL_TO_HASH_BOUND_FROZEN_V1_EXECUTOR",
        "source_path": FROZEN_B0_SOURCES[1],
        "callable": "execute",
        "keyword_arguments": {"completed_at": completed_at, "timeout_s": timeout_s},
    }


def build_action_intent_payload(
    *,
    recorded_at: str,
    completed_at: str,
    closed_at: str,
    timeout_s: int,
    adoption_binding: Mapping[str, object],
    review_evidence_binding: Mapping[str, object],
    prelock_record: Mapping[str, object],
    prelock_hash: str,
    plan_record: Mapping[str, object],
    plan_hash: str,
    wrapper_argv: Sequence[str],
    plan_sources: Sequence[Mapping[str, object]],
    source_artifacts: Sequence[Mapping[str, object]],
    cache_namespace_pre_state: Sequence[Mapping[str, object]],
    formal_output_pre_state: Sequence[Mapping[str, object]],
    process_quiescence: Mapping[str, object],
) -> dict[str, object]:
    expected_argv = canonical_wrapper_argv(
        action_started_at=recorded_at,
        completed_at=completed_at,
        closed_at=closed_at,
        timeout_s=timeout_s,
    )
    if list(wrapper_argv) != expected_argv:
        raise B0AdoptionBridgeError("wrapper argv is not canonical/exact")
    artifacts = [dict(item) for item in source_artifacts]
    payload: dict[str, object] = {
        "schema_version": ACTION_INTENT_SCHEMA,
        "status": ACTION_INTENT_STATUS,
        "recorded_at": recorded_at,
        "formalization_adoption": dict(adoption_binding),
        "formalization_review_evidence": dict(review_evidence_binding),
        "pre_materialization_lock": _self_reference(
            prelock_record, field=PRELOCK_HASH, digest=prelock_hash
        ),
        "b0_materialization_plan": _self_reference(
            plan_record, field=b0_plan.SELF_HASH, digest=plan_hash
        ),
        "wrapper_argv": expected_argv,
        "wrapper_argv_hash": hashlib.sha256(
            queue_builder.canonical_json(expected_argv).encode()
        ).hexdigest(),
        "frozen_runtime_call": _frozen_runtime_call(
            completed_at=completed_at, timeout_s=timeout_s
        ),
        "plan_source_hashes": [dict(item) for item in plan_sources],
        "source_artifacts": artifacts,
        "source_artifacts_hash": _artifact_list_hash(artifacts),
        "cache_namespace_pre_state": [dict(item) for item in cache_namespace_pre_state],
        "formal_output_pre_state": [dict(item) for item in formal_output_pre_state],
        "process_quiescence": dict(process_quiescence),
        "authorization": dict(AUTHORIZATION),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[ACTION_INTENT_HASH] = _hash(payload, ACTION_INTENT_HASH)
    return payload


def validate_action_intent_payload(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    verify_files: bool = True,
    require_preaction_absence: bool = False,
) -> str:
    if (
        set(payload) != ACTION_INTENT_KEYS
        or payload.get("schema_version") != ACTION_INTENT_SCHEMA
        or payload.get("status") != ACTION_INTENT_STATUS
        or payload.get(ACTION_INTENT_HASH) != _hash(payload, ACTION_INTENT_HASH)
        or payload.get("authorization") != AUTHORIZATION
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0AdoptionBridgeError("B0 adoption action-intent schema/status/hash drift")
    recorded_at = str(payload.get("recorded_at", ""))
    call = payload.get("frozen_runtime_call")
    if not isinstance(call, dict) or set(call) != {
        "kind", "source_path", "callable", "keyword_arguments"
    }:
        raise B0AdoptionBridgeError("B0 frozen runtime call binding malformed")
    kwargs = call.get("keyword_arguments")
    if (
        call.get("kind") != "IN_PROCESS_CALL_TO_HASH_BOUND_FROZEN_V1_EXECUTOR"
        or call.get("source_path") != FROZEN_B0_SOURCES[1]
        or call.get("callable") != "execute"
        or not isinstance(kwargs, dict)
        or set(kwargs) != {"completed_at", "timeout_s"}
    ):
        raise B0AdoptionBridgeError("B0 frozen runtime call drift")
    argv = canonical_wrapper_argv(
        action_started_at=recorded_at,
        completed_at=str(kwargs["completed_at"]),
        closed_at=str(payload.get("wrapper_argv", ["", "", "", "", "", "", "", "", ""])[8]),
        timeout_s=int(kwargs["timeout_s"]),
    )
    if (
        payload.get("wrapper_argv") != argv
        or payload.get("wrapper_argv_hash")
        != hashlib.sha256(queue_builder.canonical_json(argv).encode()).hexdigest()
    ):
        raise B0AdoptionBridgeError("B0 action wrapper argv drift")
    adoption_binding = _validate_adoption_binding_shape(payload.get("formalization_adoption"))
    evidence_binding = _validate_review_evidence_binding_shape(payload.get("formalization_review_evidence"))
    prelock_ref = payload.get("pre_materialization_lock")
    plan_ref = payload.get("b0_materialization_plan")
    if (
        not isinstance(prelock_ref, dict)
        or set(prelock_ref) != {"path", "sha256", "size_bytes", PRELOCK_HASH}
        or prelock_ref.get("path") != _relative(PRELOCK, root=ROOT)
        or not isinstance(plan_ref, dict)
        or set(plan_ref) != {"path", "sha256", "size_bytes", b0_plan.SELF_HASH}
        or plan_ref.get("path") != _relative(b0_plan.OUTPUT, root=ROOT)
    ):
        raise B0AdoptionBridgeError("B0 action prelock/plan reference mismatch")
    records = payload.get("source_artifacts")
    if not isinstance(records, list) or [item.get("path") for item in records if isinstance(item, dict)] != list(REQUIRED_SOURCE_PATHS):
        raise B0AdoptionBridgeError("B0 action source artifact set mismatch")
    for expected, record in zip(REQUIRED_SOURCE_PATHS, records):
        _validate_record_shape(record, expected_path=expected, label="B0 action source")
    if payload.get("source_artifacts_hash") != _artifact_list_hash(records):
        raise B0AdoptionBridgeError("B0 action source aggregate drift")
    cache_snapshot = _validate_cache_absence_shape(payload.get("cache_namespace_pre_state"))
    formal_snapshot = _validate_formal_absence_shape(payload.get("formal_output_pre_state"))
    _validate_process_quiescence_shape(payload.get("process_quiescence"))
    if verify_files:
        root = root.absolute()
        prelock, prelock_record = load_prelock(root=root, require_preaction_absence=require_preaction_absence)
        plan, plan_record = _strict_json(root, _relative(b0_plan.OUTPUT, root=ROOT), label="B0 action plan")
        b0_plan.validate_plan_payload(plan, require_live_artifacts=True, root=root)
        if (
            prelock_ref != _self_reference(prelock_record, field=PRELOCK_HASH, digest=str(prelock[PRELOCK_HASH]))
            or plan_ref != _self_reference(plan_record, field=b0_plan.SELF_HASH, digest=str(plan[b0_plan.SELF_HASH]))
            or prelock.get("formalization_adoption") != adoption_binding
            or prelock.get("formalization_review_evidence") != evidence_binding
            or prelock.get("source_artifacts") != records
            or payload.get("plan_source_hashes") != plan_source_hashes(plan)
        ):
            raise B0AdoptionBridgeError("B0 action transitive authority/source drift")
        adoption.validate_adoption_authority_binding(adoption_binding, root=root)
        review_evidence.validate_review_evidence_authority_binding(evidence_binding, root=root)
        for expected, record in zip(REQUIRED_SOURCE_PATHS, records):
            if _record(root, expected, label="B0 action source") != record:
                raise B0AdoptionBridgeError(f"B0 action source drift: {expected}")
        if require_preaction_absence:
            if capture_cache_namespace_absence(plan, root=root) != cache_snapshot:
                raise B0AdoptionBridgeError("B0 action cache absence drift")
            if capture_formal_output_absence(root=root) != formal_snapshot:
                raise B0AdoptionBridgeError("B0 action formal absence drift")
            capture_process_quiescence()
    return str(payload[ACTION_INTENT_HASH])


def build_live_action_intent(
    *,
    recorded_at: str,
    completed_at: str,
    closed_at: str,
    timeout_s: int,
    wrapper_argv: Sequence[str],
    root: Path = ROOT,
) -> dict[str, object]:
    require_governance_locks()
    root = root.absolute()
    prelock, prelock_record = load_prelock(root=root, require_preaction_absence=True)
    plan, plan_record = _strict_json(root, _relative(b0_plan.OUTPUT, root=ROOT), label="B0 action plan")
    payload = build_action_intent_payload(
        recorded_at=recorded_at,
        completed_at=completed_at,
        closed_at=closed_at,
        timeout_s=timeout_s,
        adoption_binding=adoption.adoption_authority_binding(root=root),
        review_evidence_binding=review_evidence.review_evidence_authority_binding(root=root),
        prelock_record=prelock_record,
        prelock_hash=str(prelock[PRELOCK_HASH]),
        plan_record=plan_record,
        plan_hash=str(plan[b0_plan.SELF_HASH]),
        wrapper_argv=wrapper_argv,
        plan_sources=plan_source_hashes(plan),
        source_artifacts=prelock["source_artifacts"],
        cache_namespace_pre_state=capture_cache_namespace_absence(plan, root=root),
        formal_output_pre_state=capture_formal_output_absence(root=root),
        process_quiescence=capture_process_quiescence(),
    )
    validate_action_intent_payload(payload, root=root, verify_files=True, require_preaction_absence=True)
    return payload


def load_action_intent(
    *, root: Path = ROOT, require_preaction_absence: bool = False
) -> tuple[dict[str, object], dict[str, object]]:
    payload, record = _strict_json(root.absolute(), _relative(ACTION_INTENT, root=ROOT), label="B0 adoption action intent")
    validate_action_intent_payload(
        payload,
        root=root.absolute(),
        verify_files=True,
        require_preaction_absence=require_preaction_absence,
    )
    return payload, record


def build_closeout_payload(
    *,
    closed_at: str,
    adoption_binding: Mapping[str, object],
    prelock_record: Mapping[str, object],
    prelock_hash: str,
    plan_record: Mapping[str, object],
    plan_hash: str,
    intent_record: Mapping[str, object],
    intent_hash: str,
    receipt_record: Mapping[str, object],
    receipt_hash: str,
    final_record: Mapping[str, object],
    final_hash: str,
    review_evidence_binding: Mapping[str, object] | None = None,
    action_intent_record: Mapping[str, object] | None = None,
    action_intent_hash: str | None = None,
    cache_finalization: Sequence[Mapping[str, object]] = (),
    artifact_time_order: Mapping[str, object] | None = None,
    process_quiescence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    queue_builder.allocation_stamp(closed_at)
    if review_evidence_binding is None:  # Legacy synthetic fixture compatibility only.
        review_evidence_binding = {
            "path": review_evidence.OUTPUT_RELATIVE,
            "sha256": "0" * 64,
            "size_bytes": 1,
            review_evidence.SELF_HASH_FIELD: "0" * 64,
        }
    if action_intent_record is None:
        action_intent_record = {
            "path": _relative(ACTION_INTENT, root=ROOT),
            "sha256": "0" * 64,
            "size_bytes": 1,
        }
    if action_intent_hash is None:
        action_intent_hash = "0" * 64
    if artifact_time_order is None:
        def synthetic_timed(path: str, token: str, when: int) -> dict[str, object]:
            return {
                "path": path,
                "sha256": token * 64,
                "size_bytes": 1,
                "device": 1,
                "inode": when,
                "nlink": 1,
                "mtime_ns": when,
                "ctime_ns": when,
            }

        artifact_time_order = {
            "policy": "PRELOCK_LT_ACTION_LT_V1_INTENT_LE_EACH_CACHE_LE_RECEIPT_LE_FINAL_BY_MTIME_AND_CTIME_NS_WITH_HASH_INODE_CONTENT_CHAIN",
            "formal_artifacts": {
                "pre_materialization_lock": synthetic_timed(
                    _relative(PRELOCK, root=ROOT), "a", 10
                ),
                "materialization_action_intent": synthetic_timed(
                    _relative(ACTION_INTENT, root=ROOT), "b", 20
                ),
                "b0_materialization_intent": synthetic_timed(
                    _relative(b0_plan.INTENT, root=ROOT), "c", 30
                ),
                "b0_materialization_receipt": synthetic_timed(
                    _relative(b0_plan.RECEIPT, root=ROOT), "d", 40
                ),
                "b0_play_inputs": synthetic_timed(
                    _relative(b0_plan.FINAL_OUTPUT, root=ROOT), "e", 50
                ),
            },
        }
    if process_quiescence is None:
        process_quiescence = {
            "protocol": RELATED_PROCESS_PROTOCOL,
            "matching_process_count": 0,
            "no_related_process_active": True,
        }
    payload: dict[str, object] = {
        "schema_version": CLOSEOUT_SCHEMA,
        "status": CLOSEOUT_STATUS,
        "closed_at": closed_at,
        "formalization_adoption": dict(adoption_binding),
        "formalization_review_evidence": dict(review_evidence_binding),
        "pre_materialization_lock": _self_reference(
            prelock_record, field=PRELOCK_HASH, digest=prelock_hash
        ),
        "materialization_action_intent": _self_reference(
            action_intent_record, field=ACTION_INTENT_HASH, digest=action_intent_hash
        ),
        "b0_materialization_plan": _self_reference(
            plan_record, field=b0_plan.SELF_HASH, digest=plan_hash
        ),
        "b0_materialization_intent": _self_reference(
            intent_record, field=b0_runtime.INTENT_HASH, digest=intent_hash
        ),
        "b0_materialization_receipt": _self_reference(
            receipt_record, field=b0_runtime.RECEIPT_HASH, digest=receipt_hash
        ),
        "b0_play_inputs": _self_reference(
            final_record, field=common.B0_PLAY_INPUTS_SELF_HASH, digest=final_hash
        ),
        "cache_finalization": [dict(item) for item in cache_finalization],
        "artifact_time_order": dict(artifact_time_order),
        "no_partial_or_staging_entries": True,
        "process_quiescence": dict(process_quiescence),
        "authorization": {
            "b0_input_materialization_completed": True,
            "backend_replay_authorized": False,
            "g0_evaluation_authorized": False,
            "ros_authorized": False,
            "vins_authorized": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[CLOSEOUT_HASH] = _hash(payload, CLOSEOUT_HASH)
    return payload


def _load_b0_outputs(root: Path) -> dict[str, tuple[dict[str, Any], dict[str, object]]]:
    mapping = {
        "plan": b0_plan.OUTPUT,
        "intent": b0_plan.INTENT,
        "receipt": b0_plan.RECEIPT,
        "final": b0_plan.FINAL_OUTPUT,
    }
    return {
        key: _strict_json(root, _relative(path, root=ROOT), label=f"B0 {key}")
        for key, path in mapping.items()
    }


def _timed_file_record(root: Path, relative: str, *, label: str) -> dict[str, object]:
    """Hash one direct single-link file and bind stable inode plus ns timestamps."""

    try:
        with queue_builder.formal_io._parent_dirfd(root.absolute(), relative) as (parent_fd, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise B0AdoptionBridgeError(f"{label} is not a direct single-link file")
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(fd)
                reachable = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            finally:
                os.close(fd)
    except OSError as error:
        raise B0AdoptionBridgeError(f"cannot bind timed {label}: {relative}") from error
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or identity(after) != identity(reachable) or size != after.st_size:
        raise B0AdoptionBridgeError(f"{label} changed during timed hash")
    return {
        "path": relative,
        "sha256": digest.hexdigest(),
        "size_bytes": int(size),
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "nlink": int(after.st_nlink),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
    }


def _strictly_before(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return max(int(left["mtime_ns"]), int(left["ctime_ns"])) < min(
        int(right["mtime_ns"]), int(right["ctime_ns"])
    )


def _not_after(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    """Allow an fs timestamp tie only when neither mtime nor ctime reverses."""

    return int(left["mtime_ns"]) <= int(right["mtime_ns"]) and int(
        left["ctime_ns"]
    ) <= int(right["ctime_ns"])


def wait_past_action_filesystem_time(
    *, root: Path = ROOT, timeout_s: float = 2.0, margin_ns: int = 1_000_000
) -> dict[str, object]:
    """Boundedly fence the old executor beyond the durable action ctime/mtime."""

    require_governance_locks()
    if timeout_s <= 0 or margin_ns < 0:
        raise B0AdoptionBridgeError("invalid B0 action filesystem fence")
    record = _timed_file_record(
        root.absolute(), _relative(ACTION_INTENT, root=ROOT), label="B0 action fence"
    )
    threshold = max(int(record["mtime_ns"]), int(record["ctime_ns"])) + margin_ns
    deadline = time.monotonic() + timeout_s
    while time.time_ns() <= threshold:
        if time.monotonic() >= deadline:
            raise B0AdoptionBridgeError("B0 action filesystem-time fence timed out")
        time.sleep(0.001)
    return record


def capture_cache_finalization(
    plan: Mapping[str, Any], receipt: Mapping[str, Any], *, root: Path = ROOT
) -> list[dict[str, object]]:
    observations = {
        str(item.get("window_id")): item
        for item in receipt.get("observations", [])
        if isinstance(item, dict)
    }
    result: list[dict[str, object]] = []
    for recipe in sorted(plan.get("recipes", []), key=lambda item: str(item.get("target_path", ""))):
        if recipe.get("disposition") not in CACHE_MUTATION_DISPOSITIONS:
            continue
        relative = str(recipe["target_path"])
        namespace = _lexical_namespace_state(
            root, relative, prefixes=_cache_prefixes(PurePosixPath(relative).name)
        )
        if namespace.get("lexical_state") != "REGULAR" or namespace.get(
            "matching_partial_or_staging_entries"
        ) != []:
            raise B0AdoptionBridgeError(f"B0 finalized cache namespace drift: {relative}")
        timed = _timed_file_record(root, relative, label="finalized B0 cache")
        observation = observations.get(str(recipe["window_id"]))
        integrity = observation.get("bag_integrity") if isinstance(observation, dict) else None
        expected_counts = recipe.get("expected_topic_counts")
        if (
            not isinstance(observation, dict)
            or observation.get("materialization_action") != "MATERIALIZED_AND_LINKED_NOREPLACE"
            or observation.get("sha256") != timed["sha256"]
            or int(observation.get("size_bytes", -1)) != timed["size_bytes"]
            or int(observation.get("device", -1)) != timed["device"]
            or int(observation.get("inode", -1)) != timed["inode"]
            or timed["sha256"] != recipe.get("expected_sha256")
            or timed["size_bytes"] != int(recipe.get("expected_size_bytes", -1))
            or not isinstance(integrity, dict)
            or integrity.get("trajectory_values_interpreted") is not False
            or (
                expected_counts is not None
                and integrity.get("topic_counts")
                != {str(key): int(value) for key, value in expected_counts.items()}
            )
        ):
            raise B0AdoptionBridgeError(f"B0 finalized cache/receipt identity drift: {relative}")
        result.append(
            {
                **timed,
                "window_id": str(recipe["window_id"]),
                "recipe_hash": str(recipe["recipe_hash"]),
                "materialization_action": "MATERIALIZED_AND_LINKED_NOREPLACE",
                "topic_counts": dict(integrity.get("topic_counts", {})),
                "camera_topic": str(integrity.get("camera_topic", "")),
                "matching_partial_or_staging_entries": [],
            }
        )
    if not result:
        raise B0AdoptionBridgeError("B0 closeout has no finalized governed cache")
    return result


def capture_artifact_time_order(
    *, root: Path = ROOT, cache_finalization: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    records = {
        "pre_materialization_lock": _timed_file_record(root, _relative(PRELOCK, root=ROOT), label="B0 prelock"),
        "materialization_action_intent": _timed_file_record(root, _relative(ACTION_INTENT, root=ROOT), label="B0 action intent"),
        "b0_materialization_intent": _timed_file_record(root, _relative(b0_plan.INTENT, root=ROOT), label="B0 v1 intent"),
        "b0_materialization_receipt": _timed_file_record(root, _relative(b0_plan.RECEIPT, root=ROOT), label="B0 v1 receipt"),
        "b0_play_inputs": _timed_file_record(root, _relative(b0_plan.FINAL_OUTPUT, root=ROOT), label="B0 play inputs"),
    }
    if not _strictly_before(records["pre_materialization_lock"], records["materialization_action_intent"]):
        raise B0AdoptionBridgeError("B0 prelock/action filesystem order is not strict")
    if not _strictly_before(records["materialization_action_intent"], records["b0_materialization_intent"]):
        raise B0AdoptionBridgeError("B0 action/v1-intent filesystem order is not strict")
    for cache in cache_finalization:
        if not _not_after(records["b0_materialization_intent"], cache) or not _not_after(cache, records["b0_materialization_receipt"]):
            raise B0AdoptionBridgeError("B0 intent/cache/receipt filesystem order is not strict")
    if not _not_after(records["b0_materialization_receipt"], records["b0_play_inputs"]):
        raise B0AdoptionBridgeError("B0 receipt/final filesystem order is not strict")
    return {
        "policy": "PRELOCK_LT_ACTION_LT_V1_INTENT_LE_EACH_CACHE_LE_RECEIPT_LE_FINAL_BY_MTIME_AND_CTIME_NS_WITH_HASH_INODE_CONTENT_CHAIN",
        "formal_artifacts": records,
    }


def _validate_timed_record(value: object, *, expected_path: str, label: str) -> dict[str, object]:
    keys = {"path", "sha256", "size_bytes", "device", "inode", "nlink", "mtime_ns", "ctime_ns"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("path") != expected_path
        or not HEX64.fullmatch(str(value.get("sha256", "")))
        or any(not isinstance(value.get(key), int) or int(value[key]) <= 0 for key in ("size_bytes", "device", "inode", "nlink", "mtime_ns", "ctime_ns"))
        or value.get("nlink") != 1
    ):
        raise B0AdoptionBridgeError(f"invalid timed {label} record")
    return dict(value)


def validate_artifact_time_order(
    value: object, cache_finalization: Sequence[Mapping[str, object]]
) -> None:
    if not isinstance(value, dict) or set(value) != {"policy", "formal_artifacts"} or value.get("policy") != "PRELOCK_LT_ACTION_LT_V1_INTENT_LE_EACH_CACHE_LE_RECEIPT_LE_FINAL_BY_MTIME_AND_CTIME_NS_WITH_HASH_INODE_CONTENT_CHAIN":
        raise B0AdoptionBridgeError("B0 artifact time-order policy drift")
    records = value.get("formal_artifacts")
    paths = {
        "pre_materialization_lock": _relative(PRELOCK, root=ROOT),
        "materialization_action_intent": _relative(ACTION_INTENT, root=ROOT),
        "b0_materialization_intent": _relative(b0_plan.INTENT, root=ROOT),
        "b0_materialization_receipt": _relative(b0_plan.RECEIPT, root=ROOT),
        "b0_play_inputs": _relative(b0_plan.FINAL_OUTPUT, root=ROOT),
    }
    if not isinstance(records, dict) or set(records) != set(paths):
        raise B0AdoptionBridgeError("B0 timed formal artifact role set drift")
    checked = {role: _validate_timed_record(records[role], expected_path=path, label=role) for role, path in paths.items()}
    if not _strictly_before(checked["pre_materialization_lock"], checked["materialization_action_intent"]) or not _strictly_before(checked["materialization_action_intent"], checked["b0_materialization_intent"]):
        raise B0AdoptionBridgeError("B0 prelock/action/intent order drift")
    for cache in cache_finalization:
        if not _not_after(checked["b0_materialization_intent"], cache) or not _not_after(cache, checked["b0_materialization_receipt"]):
            raise B0AdoptionBridgeError("B0 intent/cache/receipt order drift")
    if not _not_after(checked["b0_materialization_receipt"], checked["b0_play_inputs"]):
        raise B0AdoptionBridgeError("B0 receipt/final order drift")


def validate_closeout_payload(
    payload: Mapping[str, object], *, root: Path = ROOT, verify_files: bool = True
) -> str:
    expected_authorization = {
        "b0_input_materialization_completed": True,
        "backend_replay_authorized": False,
        "g0_evaluation_authorized": False,
        "ros_authorized": False,
        "vins_authorized": False,
    }
    if (
        set(payload) != CLOSEOUT_KEYS
        or payload.get("schema_version") != CLOSEOUT_SCHEMA
        or payload.get("status") != CLOSEOUT_STATUS
        or payload.get(CLOSEOUT_HASH) != _hash(payload, CLOSEOUT_HASH)
        or payload.get("authorization") != expected_authorization
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0AdoptionBridgeError("B0 adoption closeout schema/status/hash drift")
    queue_builder.allocation_stamp(str(payload.get("closed_at", "")))
    refs = {
        "prelock": (payload.get("pre_materialization_lock"), _relative(PRELOCK, root=ROOT), PRELOCK_HASH),
        "action": (payload.get("materialization_action_intent"), _relative(ACTION_INTENT, root=ROOT), ACTION_INTENT_HASH),
        "plan": (payload.get("b0_materialization_plan"), _relative(b0_plan.OUTPUT, root=ROOT), b0_plan.SELF_HASH),
        "intent": (payload.get("b0_materialization_intent"), _relative(b0_plan.INTENT, root=ROOT), b0_runtime.INTENT_HASH),
        "receipt": (payload.get("b0_materialization_receipt"), _relative(b0_plan.RECEIPT, root=ROOT), b0_runtime.RECEIPT_HASH),
        "final": (payload.get("b0_play_inputs"), _relative(b0_plan.FINAL_OUTPUT, root=ROOT), common.B0_PLAY_INPUTS_SELF_HASH),
    }
    for label, (reference, path, field) in refs.items():
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256", "size_bytes", field} or reference.get("path") != path:
            raise B0AdoptionBridgeError(f"B0 closeout {label} reference mismatch")
    binding = _validate_adoption_binding_shape(payload.get("formalization_adoption"))
    evidence_binding = _validate_review_evidence_binding_shape(
        payload.get("formalization_review_evidence")
    )
    cache_finalization = payload.get("cache_finalization")
    if not isinstance(cache_finalization, list):
        raise B0AdoptionBridgeError("B0 closeout cache finalization is not a list")
    cache_keys = {
        "path", "sha256", "size_bytes", "device", "inode", "nlink", "mtime_ns", "ctime_ns",
        "window_id", "recipe_hash", "materialization_action", "topic_counts", "camera_topic",
        "matching_partial_or_staging_entries",
    }
    for cache in cache_finalization:
        if (
            not isinstance(cache, dict)
            or set(cache) != cache_keys
            or cache.get("materialization_action") != "MATERIALIZED_AND_LINKED_NOREPLACE"
            or cache.get("matching_partial_or_staging_entries") != []
            or not isinstance(cache.get("topic_counts"), dict)
            or not HEX64.fullmatch(str(cache.get("recipe_hash", "")))
        ):
            raise B0AdoptionBridgeError("B0 closeout cache finalization shape drift")
        timed_part = {key: cache[key] for key in {"path", "sha256", "size_bytes", "device", "inode", "nlink", "mtime_ns", "ctime_ns"}}
        _validate_timed_record(timed_part, expected_path=str(cache["path"]), label="B0 cache")
    validate_artifact_time_order(payload.get("artifact_time_order"), cache_finalization)
    if payload.get("no_partial_or_staging_entries") is not True:
        raise B0AdoptionBridgeError("B0 closeout does not prove partial/staging absence")
    _validate_process_quiescence_shape(payload.get("process_quiescence"))
    if verify_files:
        try:
            adoption.validate_adoption_authority_binding(binding, root=root)
        except adoption.AdoptionError as error:
            raise B0AdoptionBridgeError("B0 closeout adoption authority drift") from error
        try:
            review_evidence.validate_review_evidence_authority_binding(
                evidence_binding, root=root
            )
        except review_evidence.ReviewEvidenceError as error:
            raise B0AdoptionBridgeError("B0 closeout review-evidence authority drift") from error
        prelock, prelock_record = load_prelock(root=root)
        action, action_record = load_action_intent(root=root)
        if refs["prelock"][0] != _self_reference(prelock_record, field=PRELOCK_HASH, digest=str(prelock[PRELOCK_HASH])):
            raise B0AdoptionBridgeError("B0 closeout prelock drift")
        if refs["action"][0] != _self_reference(action_record, field=ACTION_INTENT_HASH, digest=str(action[ACTION_INTENT_HASH])):
            raise B0AdoptionBridgeError("B0 closeout action-intent drift")
        if (
            prelock.get("formalization_adoption") != binding
            or action.get("formalization_adoption") != binding
            or prelock.get("formalization_review_evidence") != evidence_binding
            or action.get("formalization_review_evidence") != evidence_binding
            or action.get("pre_materialization_lock") != refs["prelock"][0]
        ):
            raise B0AdoptionBridgeError("B0 closeout/prelock/action authority mismatch")
        loaded = _load_b0_outputs(root)
        plan, plan_record = loaded["plan"]
        intent, intent_record = loaded["intent"]
        receipt, receipt_record = loaded["receipt"]
        final, final_record = loaded["final"]
        try:
            b0_plan.validate_plan_payload(plan, require_live_artifacts=True, root=root)
            b0_runtime.validate_intent_payload(intent, plan)
            b0_runtime.validate_receipt_payload(receipt, plan, intent)
            common.validate_b0_play_inputs_shape(final, plan["queue_bindings"])
        except Exception as error:
            raise B0AdoptionBridgeError("B0 closeout scientific-input contract drift") from error
        expected_refs = {
            "plan": _self_reference(plan_record, field=b0_plan.SELF_HASH, digest=str(plan[b0_plan.SELF_HASH])),
            "intent": _self_reference(intent_record, field=b0_runtime.INTENT_HASH, digest=str(intent[b0_runtime.INTENT_HASH])),
            "receipt": _self_reference(receipt_record, field=b0_runtime.RECEIPT_HASH, digest=str(receipt[b0_runtime.RECEIPT_HASH])),
            "final": _self_reference(final_record, field=common.B0_PLAY_INPUTS_SELF_HASH, digest=str(final[common.B0_PLAY_INPUTS_SELF_HASH])),
        }
        for label, expected in expected_refs.items():
            if refs[label][0] != expected:
                raise B0AdoptionBridgeError(f"B0 closeout {label} byte/self-hash drift")
        if (
            intent.get("materialization_lock") != plan_record
            or receipt.get("materialization_lock_hash") != plan.get(b0_plan.SELF_HASH)
            or receipt.get("materialization_intent_hash") != intent.get(b0_runtime.INTENT_HASH)
            or final.get("materialization_receipt") != receipt_record
            or final.get("materialization_receipt_hash") != receipt.get(b0_runtime.RECEIPT_HASH)
            or final.get("materialization_intent_hash") != intent.get(b0_runtime.INTENT_HASH)
        ):
            raise B0AdoptionBridgeError("B0 closeout plan/intent/receipt/final chain drift")
        if not (
            _timestamp(str(prelock["frozen_at"]))
            < _timestamp(str(action["recorded_at"]))
            < _timestamp(str(intent["recorded_at"]))
            < _timestamp(str(payload["closed_at"]))
        ) or _timestamp(str(receipt["completed_at"])) >= _timestamp(str(payload["closed_at"])):
            raise B0AdoptionBridgeError("B0 closeout content timestamp order drift")
        observed_cache = capture_cache_finalization(plan, receipt, root=root)
        if observed_cache != cache_finalization:
            raise B0AdoptionBridgeError("B0 closeout cache finalization live drift")
        observed_order = capture_artifact_time_order(
            root=root, cache_finalization=observed_cache
        )
        if observed_order != payload.get("artifact_time_order"):
            raise B0AdoptionBridgeError("B0 closeout filesystem timeline live drift")
        for relative in (
            _relative(PRELOCK, root=ROOT),
            _relative(ACTION_INTENT, root=ROOT),
            _relative(b0_plan.INTENT, root=ROOT),
            _relative(b0_plan.RECEIPT, root=ROOT),
            _relative(b0_plan.FINAL_OUTPUT, root=ROOT),
        ):
            state = _lexical_namespace_state(
                root, relative, prefixes=_cache_prefixes(PurePosixPath(relative).name)
            )
            if state.get("matching_partial_or_staging_entries") != []:
                raise B0AdoptionBridgeError(f"B0 formal partial/staging residue: {relative}")
        capture_process_quiescence()
    return str(payload[CLOSEOUT_HASH])


def build_live_closeout(*, closed_at: str, root: Path = ROOT) -> dict[str, object]:
    require_governance_locks()
    root = root.absolute()
    prelock, prelock_record = load_prelock(root=root)
    action, action_record = load_action_intent(root=root)
    loaded = _load_b0_outputs(root)
    plan, plan_record = loaded["plan"]
    intent, intent_record = loaded["intent"]
    receipt, receipt_record = loaded["receipt"]
    final, final_record = loaded["final"]
    cache_finalization = capture_cache_finalization(plan, receipt, root=root)
    artifact_time_order = capture_artifact_time_order(
        root=root, cache_finalization=cache_finalization
    )
    payload = build_closeout_payload(
        closed_at=closed_at,
        adoption_binding=adoption.adoption_authority_binding(root=root),
        review_evidence_binding=review_evidence.review_evidence_authority_binding(root=root),
        prelock_record=prelock_record,
        prelock_hash=str(prelock[PRELOCK_HASH]),
        action_intent_record=action_record,
        action_intent_hash=str(action[ACTION_INTENT_HASH]),
        plan_record=plan_record,
        plan_hash=str(plan[b0_plan.SELF_HASH]),
        intent_record=intent_record,
        intent_hash=str(intent[b0_runtime.INTENT_HASH]),
        receipt_record=receipt_record,
        receipt_hash=str(receipt[b0_runtime.RECEIPT_HASH]),
        final_record=final_record,
        final_hash=str(final[common.B0_PLAY_INPUTS_SELF_HASH]),
        cache_finalization=cache_finalization,
        artifact_time_order=artifact_time_order,
        process_quiescence=capture_process_quiescence(),
    )
    validate_closeout_payload(payload, root=root, verify_files=True)
    return payload


def load_closeout(*, root: Path = ROOT) -> tuple[dict[str, object], dict[str, object]]:
    payload, record = _strict_json(
        root.absolute(), _relative(CLOSEOUT, root=ROOT), label="B0 adoption closeout"
    )
    validate_closeout_payload(payload, root=root.absolute(), verify_files=True)
    return payload, record


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _publish_json_locked(
    *,
    root: Path,
    relative: str,
    payload: Mapping[str, object],
    pre_guard: Callable[[], None],
    post_guard: Callable[[], None],
    pre_link_hook: Callable[[], None] | None = None,
    post_link_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Own-inode rollback transaction; caller must hold both governance locks."""

    require_governance_locks()
    root = root.absolute()
    content = queue_builder.json_bytes(payload)
    with queue_builder.formal_io._parent_dirfd(root, relative) as (parent_fd, name):
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(relative)
        pre_guard()
        temporary = f".{name}.partial.{os.getpid()}.{os.urandom(12).hex()}"
        temp_fd = -1
        staged: os.stat_result | None = None
        linked = False
        temp_present = False
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
            temp_present = True
            queue_builder.formal_io._write_all(temp_fd, content)
            os.fsync(temp_fd)
            staged = os.fstat(temp_fd)
            if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1 or staged.st_size != len(content):
                raise B0AdoptionBridgeError("staged B0 bridge artifact identity drift")
            if pre_link_hook is not None:
                pre_link_hook()
            pre_guard()
            os.link(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            linked = True
            queue_builder.formal_io._fsync_directory(parent_fd)
            if post_link_hook is not None:
                post_link_hook()
            post_guard()
            reachable = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if staged is None or not _same_inode(staged, reachable):
                raise B0AdoptionBridgeError("published B0 bridge inode drift")
            os.unlink(temporary, dir_fd=parent_fd)
            temp_present = False
            queue_builder.formal_io._fsync_directory(parent_fd)
            observed, opened = queue_builder.formal_io._read_direct_at(parent_fd, name)
            if (
                not _same_inode(staged, opened)
                or opened.st_nlink != 1
                or observed != content
            ):
                raise B0AdoptionBridgeError("published B0 bridge bytes/link drift")
            post_guard()
            return {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        except BaseException:
            if linked and staged is not None:
                try:
                    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    current = None
                if current is not None and _same_inode(current, staged):
                    os.unlink(name, dir_fd=parent_fd)
                    queue_builder.formal_io._fsync_directory(parent_fd)
            raise
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if temp_present:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                queue_builder.formal_io._fsync_directory(parent_fd)


def _post_action_guard(payload: Mapping[str, object], *, root: Path) -> None:
    validate_action_intent_payload(payload, root=root, verify_files=True)
    plan, _record_value = _strict_json(
        root, _relative(b0_plan.OUTPUT, root=ROOT), label="B0 action post-link plan"
    )
    if capture_cache_namespace_absence(plan, root=root) != payload.get(
        "cache_namespace_pre_state"
    ):
        raise B0AdoptionBridgeError("B0 action post-link cache absence drift")
    for expected in FORMAL_ABSENCE_PATHS:
        if expected == _relative(ACTION_INTENT, root=ROOT):
            continue
        if _lexical_namespace_state(root, expected).get("lexical_state") != "ABSENT":
            raise B0AdoptionBridgeError(f"B0 action post-link formal collision: {expected}")
    capture_process_quiescence()


def publish_prelock(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    _pre_link_test_hook: Callable[[], None] | None = None,
    _post_link_test_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    root = root.absolute()
    with governance_locks():
        guard = lambda: validate_prelock_payload(
            payload, root=root, verify_files=True, require_preaction_absence=True
        )
        return _publish_json_locked(
            root=root,
            relative=_relative(PRELOCK, root=ROOT),
            payload=payload,
            pre_guard=guard,
            post_guard=guard,
            pre_link_hook=_pre_link_test_hook,
            post_link_hook=_post_link_test_hook,
        )


def freeze_live_prelock(
    *,
    frozen_at: str,
    root: Path = ROOT,
    _pre_link_test_hook: Callable[[], None] | None = None,
    _post_link_test_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    root = root.absolute()
    with governance_locks():
        payload = build_live_prelock(frozen_at=frozen_at, root=root)
        guard = lambda: validate_prelock_payload(
            payload, root=root, verify_files=True, require_preaction_absence=True
        )
        _publish_json_locked(
            root=root,
            relative=_relative(PRELOCK, root=ROOT),
            payload=payload,
            pre_guard=guard,
            post_guard=guard,
            pre_link_hook=_pre_link_test_hook,
            post_link_hook=_post_link_test_hook,
        )
        return payload


def publish_action_intent_locked(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    _pre_link_test_hook: Callable[[], None] | None = None,
    _post_link_test_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    require_governance_locks()
    root = root.absolute()
    pre_guard = lambda: validate_action_intent_payload(
        payload, root=root, verify_files=True, require_preaction_absence=True
    )
    return _publish_json_locked(
        root=root,
        relative=_relative(ACTION_INTENT, root=ROOT),
        payload=payload,
        pre_guard=pre_guard,
        post_guard=lambda: _post_action_guard(payload, root=root),
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def publish_closeout_locked(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    _pre_link_test_hook: Callable[[], None] | None = None,
    _post_link_test_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    require_governance_locks()
    root = root.absolute()
    guard = lambda: validate_closeout_payload(payload, root=root, verify_files=True)
    return _publish_json_locked(
        root=root,
        relative=_relative(CLOSEOUT, root=ROOT),
        payload=payload,
        pre_guard=guard,
        post_guard=guard,
        pre_link_hook=_pre_link_test_hook,
        post_link_hook=_post_link_test_hook,
    )


def publish_closeout(payload: Mapping[str, object], *, root: Path = ROOT) -> dict[str, object]:
    with governance_locks():
        return publish_closeout_locked(payload, root=root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--write-prelock", action="store_true")
    args = parser.parse_args()
    if args.write_prelock:
        payload = freeze_live_prelock(frozen_at=args.frozen_at)
        print(f"P07_B0_ADOPTION_PRELOCK_FROZEN hash={payload[PRELOCK_HASH]}")
    else:
        payload = build_live_prelock(frozen_at=args.frozen_at)
        print(json.dumps({
            "mode": "READ_ONLY_PREVIEW",
            "status": payload["status"],
            PRELOCK_HASH: payload[PRELOCK_HASH],
            "execution_authorized": False,
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
