#!/usr/bin/env python3
"""Independent exact audit for a matched XFeat/GFTT birth + raw-LK pair.

Exit 0 means the two newly exported bags satisfy the shared carrier contract.
Exit 1 is a contract/scientific failure; exit 2 is malformed input/runtime.
This tool never writes bags or constructs a detector.  It imports the two
wrapper specifications only to derive their fixed arm contracts and paths;
all result evidence is independently read from frozen files.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import marshal
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import types
from typing import Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import cv2
import numpy as np
import rosbag

from scripts import audit_superpoint_lk_carrier_v1 as audit_base
from scripts import export_matched_gftt_birth_rawlk_v1 as matched_gftt
from scripts import export_matched_xfeat_birth_rawlk_v1 as matched_xfeat
from scripts import matched_birth_rawlk_core_v1 as core


SCHEMA_VERSION = "aqua-fe-detector-birth-rawlk-matched-pair-audit-v1"
FREEZE_SCHEMA_VERSION = (
    "aqua-fe-detector-birth-rawlk-matched-pair-audit-freeze-v1"
)
ARTIFACT_FILESYSTEM_SCHEMA = "aqua-fe-matched-birth-artifact-filesystem-v1"
ARTIFACT_FILESYSTEM_ENVELOPE_SCHEMA = (
    "aqua-fe-matched-birth-artifact-filesystem-envelope-v1"
)
ARTIFACT_CAPABILITY_SCHEMA = (
    "aqua-fe-matched-birth-artifact-publication-capability-v1"
)
CONTINUATION_CONTRACT_SCHEMA = (
    "aqua-fe-matched-birth-probe16-scientific-continuation-v1"
)
TERMINATED_R2_ROOT = (
    WORKSPACE_ROOT / "experiments/matched_birth_a02_4500_6300_r2"
)
ARTIFACT_NAMESPACE_ROOT = (
    WORKSPACE_ROOT / "experiments/matched_birth_a02_4500_6300_r3"
)
EXT4_SUPER_MAGIC = 0xEF53
R1_INFRASTRUCTURE_INCIDENT_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_prerun_infrastructure_incident_v1.json"
)
R1_INFRASTRUCTURE_INCIDENT_SIZE = 11718
R1_INFRASTRUCTURE_INCIDENT_SHA256 = (
    "8a4a0e7bbde9fe918fc8f292bc1f5c27b8eaea90184876810b16d21879b1feb7"
)
INFRASTRUCTURE_INCIDENT_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_probe16_audit_incident_v2.json"
)
INFRASTRUCTURE_INCIDENT_SIZE = 16416
INFRASTRUCTURE_INCIDENT_SHA256 = (
    "b0aa91d71eb2cc0f8cb0cd5495b1b0a4325040f8133988367a9573c8f202838c"
)
INFRASTRUCTURE_INCIDENT_MD_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_probe16_audit_incident_v2.md"
)
INFRASTRUCTURE_INCIDENT_MD_SIZE = 2510
INFRASTRUCTURE_INCIDENT_MD_SHA256 = (
    "3c27368c7c75e3ef9f0586e19026aba3f45584e5488ba4169a9455af9d1ce302"
)
HISTORICAL_AUDITOR_PYC_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_auditor_at_failure.cpython-38.pyc"
)
TERMINATED_R1_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/matched_birth_control_probes/"
    "a02_4500_6300_prefix16"
)
TERMINATED_R1_DIRECTORY_IDENTITIES = {
    "root": {
        "path": str(TERMINATED_R1_ROOT), "device_id": 2050, "inode": 547079,
        "uid": 1000, "gid": 1000, "mode_octal": "0755", "nlink": 1,
    },
    "xfeat": {
        "path": str(TERMINATED_R1_ROOT / "xfeat_r1"),
        "device_id": 2050, "inode": 547080, "uid": 1000, "gid": 1000,
        "mode_octal": "0755", "nlink": 1,
    },
    "gftt": {
        "path": str(TERMINATED_R1_ROOT / "gftt_r1"),
        "device_id": 2050, "inode": 547081, "uid": 1000, "gid": 1000,
        "mode_octal": "0755", "nlink": 1,
    },
}
FEATURE_TOPIC_DEFAULT = "/feature_tracker/feature"
EXPECTED_CHANNELS = tuple(core.primitive.CHANNEL_NAMES)
EXPECTED_ARMS = {
    "XFEAT_BIRTH_RAWLK_MATCHED_V1": {"source_code": 20, "is_learned": 1},
    "GFTT_BIRTH_RAWLK_MATCHED_V1": {"source_code": 21, "is_learned": 0},
}
XFEAT_ARM = "XFEAT_BIRTH_RAWLK_MATCHED_V1"
GFTT_ARM = "GFTT_BIRTH_RAWLK_MATCHED_V1"
_XFEAT_LEXICAL_ROOT = WORKSPACE_ROOT / "external_tools" / "accelerated_features"
_XFEAT_CANONICAL_ROOT = _XFEAT_LEXICAL_ROOT.resolve(strict=True)
XFEAT_LEXICAL_IDENTITY_ALIASES = {
    f"{XFEAT_ARM}.code_artifacts.detector_runtime.license.file": (
        _XFEAT_LEXICAL_ROOT / "LICENSE",
        _XFEAT_CANONICAL_ROOT / "LICENSE",
    ),
    **{
        f"{XFEAT_ARM}.code_artifacts.detector_runtime.closure.{label}": (
            _XFEAT_LEXICAL_ROOT / relative,
            _XFEAT_CANONICAL_ROOT / relative,
        )
        for label, relative in {
            "xfeat.py": "modules/xfeat.py",
            "model.py": "modules/model.py",
            "interpolator.py": "modules/interpolator.py",
            "xfeat.pt": "weights/xfeat.pt",
        }.items()
    },
}
EXPECTED_PUBLISHED_FRAMES = 900
EXPECTED_RAW_FRAMES = 1800
PROBE_PUBLISHED_FRAMES = 16
NORMALIZED_TOLERANCE = 1e-6
VELOCITY_TOLERANCE = 1e-5
COMMON_DIAGNOSTIC_FIELDS = (
    "raw_index",
    "header_stamp_ns",
    "published",
    "adaptive_clahe_applied",
    "raw_image_sha256",
    "processed_image_sha256",
)
INT_DIAGNOSTIC_FIELDS = frozenset(
    {
        "raw_index",
        "header_stamp_ns",
        "tracked_before",
        "tracked_after",
        "dropped",
        "slots_before_detect",
        "detector_candidates",
        "births",
        "output_tracks",
    }
)
BOOL_DIAGNOSTIC_FIELDS = frozenset(
    {"published", "adaptive_clahe_applied", "detector_called"}
)
HASH_DIAGNOSTIC_FIELDS = frozenset(
    {"raw_image_sha256", "processed_image_sha256"}
)
FLOAT_DIAGNOSTIC_FIELDS = frozenset(
    {"fb_median_px", "fb_p95_px", "ncc_median"}
)
IDENTITY_KEYS = frozenset({"path", "size_bytes", "sha256"})
MANIFEST_TOP_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "formal_eligible",
        "formal_eligibility_reason",
        "scientific_role",
        "prefix",
        "attempt",
        "inputs",
        "common_contract",
        "common_contract_sha256",
        "arm_contract",
        "arm_contract_sha256",
        "pair_difference_policy",
        "code_artifacts",
        "outputs",
        "legacy_prepublication_rebind",
        "nonfeature_stream_before",
        "nonfeature_stream_after",
        "metrics",
        "diagnostics_streams",
        "raw_frame_diagnostics",
        "runtime",
    }
)
FREEZE_TOP_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "scientific_role",
        "auditor_identity",
        "audit_code_closure",
        "audit_runtime",
        "fixed_semantics",
        "locked_inputs",
        "audit_paths",
        "expected_common_contract",
        "expected_common_contract_sha256",
        "arms",
        "allowed_pair_scalar_differences",
        "required_pair_scalar_differences",
        "freeze_builder_identity",
        "authoritative_commands",
        "launcher_receipt_contract",
        "publication_contract",
        "infrastructure_incident",
        "artifact_filesystem_contract",
    }
)
FREEZE_ARM_KEYS = frozenset(
    {
        "paths",
        "pre_run_required_absent",
        "manifest_template",
        "manifest_template_sha256",
        "dynamic_scalar_paths",
        "attempt",
    }
)
FREEZE_PATH_KEYS = frozenset(
    {
        "feature_bag",
        "manifest_json",
        "diagnostics_csv",
        "legacy_primitive_manifest",
        "private_work_directory",
        "attempt_json",
    }
)
ATTEMPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "attempt_count",
        "process_start_count",
        "no_retry",
        "arm_id",
        "prefix_nonformal",
        "requested_inputs",
        "reserved_outputs",
        "producer",
    }
)
EXPECTED_AUDIT_PYTHONPATH = (
    "/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:"
    "/opt/ros/noetic/lib/python3/dist-packages"
)
EXPECTED_WRAPPERS = {
    XFEAT_ARM: WORKSPACE_ROOT / "scripts/export_matched_xfeat_birth_rawlk_v1.py",
    GFTT_ARM: WORKSPACE_ROOT / "scripts/export_matched_gftt_birth_rawlk_v1.py",
}
EXPECTED_ARM_CONTRACTS = {
    XFEAT_ARM: core.arm_contract(matched_xfeat.XFEAT_METHOD_SPEC),
    GFTT_ARM: core.arm_contract(matched_gftt.GFTT_METHOD_SPEC),
}
PAIR_ALLOWED_RAW_OUTCOME_FIELDS = frozenset(
    set(core.DIAGNOSTIC_FIELDS) - set(COMMON_DIAGNOSTIC_FIELDS)
)
TEMPLATE_MARKER_KEY = "$dynamic_scalar"
DYNAMIC_RULE_KEYS = frozenset(
    {"type", "types", "minimum", "maximum", "pattern", "binding"}
)
DYNAMIC_TYPES = frozenset({"bool", "int", "float", "string", "null"})
KNOWN_DYNAMIC_BINDINGS = frozenset(
    {
        "live_attempt_size",
        "live_attempt_sha256",
        "live_feature_bag_size",
        "live_feature_bag_sha256",
        "live_diagnostics_size",
        "live_diagnostics_sha256",
        "live_legacy_manifest_size",
        "live_legacy_manifest_sha256",
        "elapsed_wall_ms",
        "diagnostic_outcome",
        "detector_runtime_outcome",
        "metric_outcome",
    }
)
XFEAT_TORCH_BINARY_KEYS = frozenset(
    {"torch_init", "torch_C", "libtorch_cpu", "libtorch_python", "libc10", "libgomp"}
)
XFEAT_TORCH_PYTHON_KEYS = frozenset(
    {
        "nn_init", "nn_functional", "serialization", "modules_init",
        "module", "container", "conv", "batchnorm", "instancenorm",
        "activation", "pooling", "linear",
    }
)
XFEAT_TORCH_IMPORT_KEYS = frozenset(
    matched_xfeat.FROZEN_TORCH_IMPORT_MODULES
)
XFEAT_TQDM_KEYS = frozenset(matched_xfeat.FROZEN_TQDM_FILES)
METRIC_DYNAMIC_LEAVES = frozenset(
    {
        "observations",
        "observations_per_frame_min",
        "observations_per_frame_median",
        "observations_per_frame_max",
        "unique_ids",
        "published_first_occurrences",
        "published_continuations",
        "raw_births",
        "raw_drops",
        "detector_candidates",
    }
)
MANDATORY_PAIR_DIFFERENCES = frozenset(
    {
        "/arm_contract/arm_id",
        "/arm_contract/detector/family",
        "/arm_contract/detector/implementation_id",
        "/arm_contract/provenance/source_code",
        "/arm_contract/provenance/is_learned",
        "/arm_contract_sha256",
        "/attempt/payload/arm_id",
        "/attempt/payload/producer/wrapper_requested",
        "/attempt/payload/reserved_outputs/feature_bag",
        "/attempt/payload/reserved_outputs/manifest_json",
        "/attempt/payload/reserved_outputs/diagnostics_csv",
        "/attempt/payload/reserved_outputs/legacy_primitive_manifest",
        "/attempt/payload/reserved_outputs/private_work_directory",
        "/code_artifacts/wrapper/path",
        "/code_artifacts/wrapper/sha256",
        "/code_artifacts/detector_dependencies/legacy_detector_adapter/@type",
        "/code_artifacts/detector_dependencies/legacy_detector_adapter/sha256",
        "/code_artifacts/detector_dependencies/xfeat_modules_initializer/@type",
        "/code_artifacts/detector_dependencies/xfeat_modules_initializer/sha256",
        "/outputs/feature_bag/path",
        "/outputs/raw_diagnostics_csv/path",
        "/outputs/legacy_primitive_manifest/path",
        "/legacy_prepublication_rebind/primitive_reported_work_bag_path",
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/path",
        "/legacy_prepublication_rebind/published_feature_bag_identity/path",
    }
    | {
        f"/code_artifacts/detector_dependencies/{label}/{leaf}"
        for label in matched_xfeat.FROZEN_TQDM_FILES
        for leaf in ("@type", "sha256")
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _dynamic_marker(
    scalar_type: str | list[str],
    binding: str,
    *,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    pattern: str | None = None,
) -> dict[str, object]:
    rule: dict[str, object] = {"binding": binding}
    if type(scalar_type) is list:
        rule["types"] = scalar_type
    else:
        rule["type"] = scalar_type
    if minimum is not None:
        rule["minimum"] = minimum
    if maximum is not None:
        rule["maximum"] = maximum
    if pattern is not None:
        rule["pattern"] = pattern
    return {TEMPLATE_MARKER_KEY: rule}


def _mode_raw_frames(*, allow_prefix: bool, expected_frames: int) -> int:
    if allow_prefix is False and expected_frames == EXPECTED_PUBLISHED_FRAMES:
        return EXPECTED_RAW_FRAMES
    if allow_prefix is True and expected_frames == PROBE_PUBLISHED_FRAMES:
        return 2 * PROBE_PUBLISHED_FRAMES
    raise AuditFailure(
        "matched audit mode must be exactly formal900 or nonformal probe16"
    )


def _mandatory_dynamic_rules(
    arm_id: str,
    *,
    allow_prefix: bool = False,
    expected_frames: int = EXPECTED_PUBLISHED_FRAMES,
) -> dict[str, object]:
    """Code-authoritative outcome leaves; none may be frozen to observed values."""

    if arm_id not in EXPECTED_ARMS:
        raise AuditFailure(f"unknown arm for mandatory dynamic rules: {arm_id}")
    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )
    rules: dict[str, object] = {
        "/attempt/identity/size_bytes": _dynamic_marker("int", "live_attempt_size", minimum=1),
        "/attempt/identity/sha256": _dynamic_marker("string", "live_attempt_sha256", pattern=r"[0-9a-f]{64}"),
        "/outputs/feature_bag/size_bytes": _dynamic_marker("int", "live_feature_bag_size", minimum=1),
        "/outputs/feature_bag/sha256": _dynamic_marker("string", "live_feature_bag_sha256", pattern=r"[0-9a-f]{64}"),
        "/outputs/raw_diagnostics_csv/size_bytes": _dynamic_marker("int", "live_diagnostics_size", minimum=1),
        "/outputs/raw_diagnostics_csv/sha256": _dynamic_marker("string", "live_diagnostics_sha256", pattern=r"[0-9a-f]{64}"),
        "/outputs/legacy_primitive_manifest/size_bytes": _dynamic_marker("int", "live_legacy_manifest_size", minimum=1),
        "/outputs/legacy_primitive_manifest/sha256": _dynamic_marker("string", "live_legacy_manifest_sha256", pattern=r"[0-9a-f]{64}"),
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/size_bytes": _dynamic_marker("int", "live_feature_bag_size", minimum=1),
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/sha256": _dynamic_marker("string", "live_feature_bag_sha256", pattern=r"[0-9a-f]{64}"),
        "/legacy_prepublication_rebind/published_feature_bag_identity/size_bytes": _dynamic_marker("int", "live_feature_bag_size", minimum=1),
        "/legacy_prepublication_rebind/published_feature_bag_identity/sha256": _dynamic_marker("string", "live_feature_bag_sha256", pattern=r"[0-9a-f]{64}"),
        "/runtime/elapsed_wall_ms": _dynamic_marker("float", "elapsed_wall_ms", minimum=0.0),
        "/code_artifacts/detector_runtime/runtime/detect_calls": _dynamic_marker("int", "detector_runtime_outcome", minimum=1, maximum=expected_raw_frames),
        "/code_artifacts/detector_runtime/runtime/candidate_total": _dynamic_marker("int", "detector_runtime_outcome", minimum=0, maximum=expected_raw_frames * core.MAX_CANDIDATES),
    }
    metric_ranges = {
        "observations": ("int", 0, expected_frames * core.FEATURE_CAP),
        "observations_per_frame_min": ("int", 0, core.FEATURE_CAP),
        "observations_per_frame_median": ("float", 0.0, float(core.FEATURE_CAP)),
        "observations_per_frame_max": ("int", 0, core.FEATURE_CAP),
        "unique_ids": ("int", 0, expected_raw_frames * core.FEATURE_CAP),
        "published_first_occurrences": ("int", 0, expected_raw_frames * core.FEATURE_CAP),
        "published_continuations": ("int", 0, expected_frames * core.FEATURE_CAP),
        "raw_births": ("int", 0, expected_raw_frames * core.FEATURE_CAP),
        "raw_drops": ("int", 0, expected_raw_frames * core.FEATURE_CAP),
        "detector_candidates": ("int", 0, expected_raw_frames * core.MAX_CANDIDATES),
    }
    for name, (kind, minimum, maximum) in metric_ranges.items():
        rules[f"/metrics/{name}"] = _dynamic_marker(kind, "metric_outcome", minimum=minimum, maximum=maximum)
    for index in range(expected_raw_frames):
        base = f"/raw_frame_diagnostics/{index}"
        for name in ("tracked_before", "tracked_after", "dropped", "slots_before_detect", "births", "output_tracks"):
            rules[f"{base}/{name}"] = _dynamic_marker("int", "diagnostic_outcome", minimum=0, maximum=core.FEATURE_CAP)
        rules[f"{base}/detector_called"] = _dynamic_marker("bool", "diagnostic_outcome")
        rules[f"{base}/detector_candidates"] = _dynamic_marker("int", "diagnostic_outcome", minimum=0, maximum=core.MAX_CANDIDATES)
        for name in ("fb_median_px", "fb_p95_px"):
            rules[f"{base}/{name}"] = _dynamic_marker(["float", "null"], "diagnostic_outcome", minimum=0.0, maximum=1.000001)
        rules[f"{base}/ncc_median"] = _dynamic_marker(["float", "null"], "diagnostic_outcome", minimum=core.primitive.NCC_MIN, maximum=1.000001)
    if arm_id == XFEAT_ARM:
        timing_counts = {"warmup": (0, 1), "steady_state": (0, expected_raw_frames - 1), "all": (1, expected_raw_frames)}
        for group, (minimum, maximum) in timing_counts.items():
            base = f"/code_artifacts/detector_runtime/runtime/detect_ms/{group}"
            rules[f"{base}/count"] = _dynamic_marker("int", "detector_runtime_outcome", minimum=minimum, maximum=maximum)
            rules[f"{base}/total_ms"] = _dynamic_marker("float", "detector_runtime_outcome", minimum=0.0)
            for name in ("median_ms", "p90_ms"):
                rules[f"{base}/{name}"] = _dynamic_marker(["float", "null"], "detector_runtime_outcome", minimum=0.0)
    return rules


def _pointer_value(value: object, pointer: str) -> object:
    current = value
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if type(current) is list else current[token]
    return current


class AuditFailure(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_path(path: Path, *, label: str) -> Path:
    lexical = Path(path).expanduser().absolute()
    if lexical.is_symlink():
        raise AuditFailure(f"{label} must not be a leaf symlink: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise AuditFailure(f"{label} is missing or unresolved: {lexical}: {exc}") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise AuditFailure(f"{label} must be a regular file: {resolved}")
    observed = resolved.stat()
    if not stat.S_ISREG(observed.st_mode) or int(observed.st_nlink) != 1:
        raise AuditFailure(f"{label} must be a single-link regular file: {resolved}")
    return resolved


def _canonical_future_path(path: Path, *, label: str) -> Path:
    lexical = Path(path).expanduser().absolute()
    canonical = lexical.resolve(strict=False)
    if lexical != canonical:
        raise AuditFailure(f"{label} must use its canonical resolved spelling: {canonical}")
    parent = canonical.parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_symlink():
        raise AuditFailure(f"{label} parent must be a canonical directory: {parent}")
    return canonical


def _file_identity(path: Path, *, label: str = "file") -> dict[str, object]:
    resolved = _regular_path(path, label=label)
    return {
        "path": str(resolved),
        "size_bytes": int(resolved.stat().st_size),
        "sha256": _sha256_file(resolved),
    }


class _StatFS(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long), ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong), ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong), ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong), ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long), ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long), ("f_spare", ctypes.c_long * 4),
    ]


def _statfs_magic(path: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(_StatFS)]
    libc.statfs.restype = ctypes.c_int
    observed = _StatFS()
    if libc.statfs(os.fsencode(path), ctypes.byref(observed)) != 0:
        raise AuditFailure(
            f"statfs failed for {path}: errno={ctypes.get_errno()}"
        )
    bits = ctypes.sizeof(ctypes.c_long) * 8
    return int(observed.f_type) & ((1 << bits) - 1)


def _fstatfs_magic(descriptor: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFS)]
    libc.fstatfs.restype = ctypes.c_int
    observed = _StatFS()
    if libc.fstatfs(descriptor, ctypes.byref(observed)) != 0:
        raise AuditFailure(
            f"fstatfs failed for descriptor {descriptor}: errno={ctypes.get_errno()}"
        )
    bits = ctypes.sizeof(ctypes.c_long) * 8
    return int(observed.f_type) & ((1 << bits) - 1)


def _mountinfo_unescape(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _mountinfo_contract(path: Path) -> dict[str, object]:
    """Return the longest-prefix Linux mountinfo record for a canonical path."""

    resolved = path.resolve(strict=True)
    candidates: list[tuple[int, dict[str, object]]] = []
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AuditFailure("cannot read /proc/self/mountinfo") from exc
    for line in lines:
        if " - " not in line:
            raise AuditFailure("malformed /proc/self/mountinfo record")
        left_raw, right_raw = line.split(" - ", 1)
        left = left_raw.split()
        right = right_raw.split()
        if len(left) < 6 or len(right) < 3:
            raise AuditFailure("malformed /proc/self/mountinfo fields")
        mount_point = Path(_mountinfo_unescape(left[4]))
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        candidates.append(
            (
                len(os.fspath(mount_point)),
                {
                    "mount_point": str(mount_point),
                    "filesystem_type": right[0],
                    "source": _mountinfo_unescape(right[1]),
                    "mount_options": left[5].split(","),
                    "super_options": right[2].split(","),
                },
            )
        )
    if not candidates:
        raise AuditFailure(f"no mountinfo record covers {resolved}")
    return max(candidates, key=lambda item: item[0])[1]


def _expected_artifact_capability_attestation() -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_CAPABILITY_SCHEMA,
        "status": "PASS_BEFORE_ANY_GOVERNED_O_EXCL_PUBLICATION",
        "non_governed_private_probe_directory_mode_0700": True,
        "o_excl_single_link_regular_file": True,
        "fchmod_0444_fd_and_visible": True,
        "write_fsync_reopen_nofollow_inode_and_bytes": True,
        "parent_directory_fsync": True,
        "renameat2_noreplace_eexist_preserved_both": True,
        "renameat2_noreplace_success_preserved_source_inode": True,
        "cleanup_complete": True,
    }


def _artifact_filesystem_contract(paths: Sequence[Path]) -> dict[str, object]:
    """Rebuild the ext4/same-device contract for every governed r2 path."""

    if len(paths) != 21:
        raise AuditFailure("artifact filesystem contract requires exactly 21 paths")
    root_raw = os.fspath(ARTIFACT_NAMESPACE_ROOT)
    if not ARTIFACT_NAMESPACE_ROOT.is_absolute() or os.path.normpath(root_raw) != root_raw:
        raise AuditFailure("artifact namespace root is not canonical absolute")
    try:
        root = ARTIFACT_NAMESPACE_ROOT.resolve(strict=True)
    except OSError as exc:
        raise AuditFailure("artifact namespace root does not exist") from exc
    if root != ARTIFACT_NAMESPACE_ROOT:
        raise AuditFailure("artifact namespace root contains a symlink")
    root_stat = os.lstat(root)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or int(root_stat.st_uid) != int(os.getuid())
        or bool(stat.S_IMODE(root_stat.st_mode) & 0o022)
        or (stat.S_IMODE(root_stat.st_mode) & 0o300) != 0o300
    ):
        raise AuditFailure("artifact namespace root ownership/type contract failed")
    root_magic = _statfs_magic(root)
    if root_magic != EXT4_SUPER_MAGIC:
        raise AuditFailure(
            f"artifact namespace root filesystem is not ext4: 0x{root_magic:x}"
        )
    root_mount = _mountinfo_contract(root)
    if (
        root_mount["filesystem_type"] != "ext4"
        or "rw" not in root_mount["mount_options"]
    ):
        raise AuditFailure(
            "artifact namespace root mount is not writable ext4: "
            f"{root_mount['mount_point']}:{root_mount['filesystem_type']}"
        )
    canonical_paths: list[str] = []
    parent_rows: dict[str, dict[str, object]] = {}
    shared_device: int | None = None
    for value in paths:
        raw = os.fspath(value)
        path = Path(raw)
        if not path.is_absolute() or os.path.normpath(raw) != raw:
            raise AuditFailure(f"governed artifact path is not canonical: {raw!r}")
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AuditFailure(f"governed artifact escapes r2 namespace: {path}") from exc
        parent = path.parent
        try:
            resolved_parent = parent.resolve(strict=True)
        except OSError as exc:
            raise AuditFailure(f"governed artifact parent does not exist: {parent}") from exc
        if resolved_parent != parent:
            raise AuditFailure(f"governed artifact parent contains a symlink: {parent}")
        parent_stat = os.lstat(parent)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or int(parent_stat.st_uid) != int(os.getuid())
            or bool(stat.S_IMODE(parent_stat.st_mode) & 0o022)
            or (stat.S_IMODE(parent_stat.st_mode) & 0o300) != 0o300
        ):
            raise AuditFailure(f"governed artifact parent contract failed: {parent}")
        magic = _statfs_magic(parent)
        if magic != EXT4_SUPER_MAGIC:
            raise AuditFailure(
                f"governed artifact filesystem is not ext4: {parent}: 0x{magic:x}"
            )
        parent_mount = _mountinfo_contract(parent)
        if parent_mount != root_mount:
            raise AuditFailure(
                f"governed artifact parent is on a distinct mount: {parent}"
            )
        device = int(parent_stat.st_dev)
        if shared_device is None:
            shared_device = device
        elif device != shared_device:
            raise AuditFailure("governed artifact parents span multiple devices")
        canonical_paths.append(str(path))
        parent_rows[str(parent)] = {
            "path": str(parent), "device_id": device,
            "inode": int(parent_stat.st_ino),
            "mode_octal": format(stat.S_IMODE(parent_stat.st_mode), "04o"),
            "uid": int(parent_stat.st_uid), "gid": int(parent_stat.st_gid),
            "filesystem_magic_hex": f"0x{magic:x}",
        }
    if len(canonical_paths) != len(set(canonical_paths)):
        raise AuditFailure("governed artifact paths are not unique")
    if shared_device != int(root_stat.st_dev):
        raise AuditFailure(
            "governed artifact parents are not on the namespace-root device"
        )
    return {
        "schema_version": ARTIFACT_FILESYSTEM_SCHEMA,
        "namespace_root": str(root),
        "allowed_filesystem": "ext4",
        "allowed_filesystem_magic_hex": f"0x{EXT4_SUPER_MAGIC:x}",
        "mount_contract": root_mount,
        "shared_device_id": shared_device,
        "governed_paths": sorted(canonical_paths),
        "parent_directories": [parent_rows[key] for key in sorted(parent_rows)],
        "namespace_root_identity": {
            "path": str(root),
            "device_id": int(root_stat.st_dev),
            "inode": int(root_stat.st_ino),
            "mode_octal": format(stat.S_IMODE(root_stat.st_mode), "04o"),
            "uid": int(root_stat.st_uid),
            "gid": int(root_stat.st_gid),
            "nlink": int(root_stat.st_nlink),
        },
    }


def _artifact_filesystem_envelope(paths: Sequence[Path]) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_FILESYSTEM_ENVELOPE_SCHEMA,
        "static_contract": _artifact_filesystem_contract(paths),
        "builder_prepublication_capability_probe": (
            _expected_artifact_capability_attestation()
        ),
    }


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write made no progress")
        offset += written


def _replace_reserved_fd_payload(descriptor: int, payload: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    _write_all(descriptor, payload)
    os.fsync(descriptor)


def _load_canonical_object(path: Path, *, label: str) -> dict[str, object]:
    path = _regular_path(path, label=label)
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if type(payload) is not dict or path.read_bytes() != _canonical_bytes(payload):
        raise AuditFailure(f"{label} is not canonical object JSON: {path}")
    return payload


def _read_regular_descriptor_bytes(
    descriptor: int, *, expected_identity: tuple[int, int], label: str
) -> tuple[bytes, os.stat_result]:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or int(before.st_nlink) != 1
        or (int(before.st_dev), int(before.st_ino)) != expected_identity
    ):
        raise AuditFailure(f"{label} is not the held single-link regular inode")
    chunks: list[bytes] = []
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        chunks.append(block)
    payload = b"".join(chunks)
    after = os.fstat(descriptor)
    if (
        (int(after.st_dev), int(after.st_ino)) != expected_identity
        or int(after.st_size) != len(payload)
        or int(after.st_mtime_ns) != int(before.st_mtime_ns)
        or int(after.st_ctime_ns) != int(before.st_ctime_ns)
    ):
        raise AuditFailure(f"{label} changed while its held descriptor was read")
    return payload, after


def _read_regular_nofollow(path: Path, *, label: str) -> tuple[bytes, os.stat_result]:
    lexical = Path(path).expanduser().absolute()
    if lexical.resolve(strict=True) != lexical:
        raise AuditFailure(f"{label} path is not canonical and symlink-free: {lexical}")
    visible_before = os.lstat(lexical)
    descriptor = os.open(
        str(lexical),
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        held = os.fstat(descriptor)
        identity = (int(held.st_dev), int(held.st_ino))
        if identity != (int(visible_before.st_dev), int(visible_before.st_ino)):
            raise AuditFailure(f"{label} changed between lstat and open")
        payload, after = _read_regular_descriptor_bytes(
            descriptor, expected_identity=identity, label=label
        )
        visible_after = os.lstat(lexical)
        if (int(visible_after.st_dev), int(visible_after.st_ino)) != identity:
            raise AuditFailure(f"{label} visible path changed during read")
        return payload, after
    finally:
        os.close(descriptor)


def _load_canonical_object_single_fd(
    path: Path, *, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    encoded, observed = _read_regular_nofollow(path, label=label)
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if type(payload) is not dict or encoded != _canonical_bytes(payload):
        raise AuditFailure(f"{label} is not canonical object JSON: {path}")
    return payload, {
        "path": str(Path(path).resolve(strict=True)),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _directory_identity(path: Path, observed: os.stat_result) -> dict[str, object]:
    return {
        "path": str(path),
        "device_id": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "uid": int(observed.st_uid),
        "gid": int(observed.st_gid),
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
        "nlink": int(observed.st_nlink),
    }


def _open_held_directory(
    path_or_name: Path | str,
    *,
    label: str,
    expected: Mapping[str, object],
    parent_descriptor: int | None = None,
) -> int:
    raw = os.fspath(path_or_name)
    descriptor = os.open(
        raw,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_descriptor,
    )
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode):
            raise AuditFailure(f"{label} is not a held directory")
        _strict_equal(
            _directory_identity(Path(expected["path"]), observed),
            expected,
            label=f"{label} identity",
        )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _terminated_r1_required_absences() -> list[dict[str, str]]:
    root = TERMINATED_R1_ROOT
    rows = [
        ("global.freeze_json", WORKSPACE_ROOT / "papers/a02_4500_6300_matched_birth_probe16_freeze_v1.json"),
        ("global.pre_run_start_receipt", WORKSPACE_ROOT / "papers/a02_4500_6300_matched_birth_probe16_start_receipt_v1.json"),
        ("global.post_run_pair_seal", WORKSPACE_ROOT / "papers/a02_4500_6300_matched_birth_probe16_pair_audit_v1.json"),
    ]
    artifacts = (
        ("attempt_json", "producer_attempt.json"),
        ("manifest_json", "export_manifest.json"),
        ("feature_bag", "features.bag"),
        ("legacy_primitive_manifest", "legacy_primitive_manifest.json"),
        ("diagnostics_csv", "raw_diagnostics.csv"),
        ("private_work_directory", "private_work"),
        ("command_contract", "command_contract.json"),
        ("launcher_start_receipt", "launcher_start_receipt.json"),
        ("launcher_rc_receipt", "launcher_rc_receipt.json"),
    )
    for arm in ("xfeat", "gftt"):
        for role, name in artifacts:
            if arm == "xfeat" and role == "command_contract":
                continue
            rows.append((f"{arm}.{role}", root / f"{arm}_r1" / name))
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher
    rows.append(("shared.pycache_prefix", sealed_launcher.PYCACHE_PREFIX))
    return [
        {"role": role, "path": str(path), "state": "ABSENT"}
        for role, path in rows
    ]


def _validate_r1_infrastructure_incident() -> dict[str, object]:
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    incident, identity = _load_canonical_object_single_fd(
        R1_INFRASTRUCTURE_INCIDENT_PATH,
        label="matched pre-run infrastructure incident",
    )
    incident_stat = os.lstat(R1_INFRASTRUCTURE_INCIDENT_PATH)
    if (
        int(incident_stat.st_uid) != int(os.getuid())
        or stat.S_IMODE(incident_stat.st_mode) != 0o444
    ):
        raise AuditFailure("matched pre-run infrastructure incident is not mode-0444 owned")
    if (
        identity["size_bytes"] != R1_INFRASTRUCTURE_INCIDENT_SIZE
        or identity["sha256"] != R1_INFRASTRUCTURE_INCIDENT_SHA256
    ):
        raise AuditFailure("matched pre-run infrastructure incident identity drift")
    if (
        incident.get("schema_version")
        != "aqua-fe-matched-birth-prerun-infrastructure-incident-v1"
        or incident.get("status")
        != "SEALED_THREE_BUILDER_FAILURES_R1_NAMESPACE_TERMINATED"
        or incident.get("scientific_role")
        != "INFRASTRUCTURE_FAILURE_BEFORE_ANY_MATCHED_DETECTOR_PRODUCER_START"
        or incident.get("producer_started") is not False
        or incident.get("persistent_raw_stream_artifact") is not False
        or incident.get("captured_from_orchestrator_transcript") is not True
    ):
        raise AuditFailure("matched pre-run infrastructure incident semantic drift")
    history = incident.get("attempt_history")
    if (
        type(history) is not list
        or len(history) != 3
        or any(type(item) is not dict for item in history)
        or [item.get("ordinal") for item in history] != [1, 2, 3]
        or [item.get("return_code") for item in history] != [2, 2, 2]
        or [item.get("producer_process_start_count") for item in history] != [0, 0, 0]
        or [item.get("all_governed_artifact_files_created") for item in history]
        != [0, 0, 1]
    ):
        raise AuditFailure("matched pre-run incident history drift")
    invocation = incident.get("builder_invocation")
    if type(invocation) is not dict or invocation.get("repeated_count") != 3:
        raise AuditFailure("matched pre-run builder invocation record drift")
    if invocation.get("working_directory") != str(WORKSPACE_ROOT):
        raise AuditFailure("matched pre-run builder cwd drift")
    _strict_equal(
        invocation.get("environment_contract"),
        sealed_launcher.FROZEN_ENVIRONMENT,
        label="matched pre-run builder environment",
    )
    argv = invocation.get("argv")
    if type(argv) is not list or any(type(item) is not str for item in argv):
        raise AuditFailure("matched pre-run builder argv is malformed")
    if (
        hashlib.sha256(_canonical_bytes(argv)).hexdigest()
        != "5ffdd71738a6713096a54f4a52581b81796db481ff5c0fa35b939aa00ec0eb54"
        or invocation.get("canonical_argv_sha256")
        != "5ffdd71738a6713096a54f4a52581b81796db481ff5c0fa35b939aa00ec0eb54"
    ):
        raise AuditFailure("matched pre-run builder argv identity drift")
    expected_absences = _terminated_r1_required_absences()
    _strict_equal(
        incident.get("required_absences"), expected_absences,
        label="matched pre-run required absences",
    )
    for row in expected_absences:
        if os.path.lexists(row["path"]):
            raise AuditFailure(f"terminated r1 absent path appeared: {row['role']}")
    _strict_equal(
        incident.get("supersession_policy"),
        {
            "new_namespace_root": str(TERMINATED_R2_ROOT),
            "old_orphan_is_non_authoritative": True,
            "old_r1_delete_or_reuse_forbidden": True,
            "requires_ext4_preflight_before_any_new_publication": True,
        },
        label="matched pre-run supersession policy",
    )
    old = incident.get("old_namespace")
    if type(old) is not dict or type(old.get("orphan_command_contract")) is not dict:
        raise AuditFailure("matched pre-run old namespace record is malformed")
    if old.get("root") != str(TERMINATED_R1_ROOT):
        raise AuditFailure("matched pre-run old namespace root drift")
    _strict_equal(
        old.get("filesystem"),
        {"filesystem_magic_hex": "0x65735546", "filesystem_type": "fuseblk"},
        label="terminated r1 filesystem",
    )
    _strict_equal(
        old.get("xfeat_directory"),
        {
            "path": str(TERMINATED_R1_ROOT / "xfeat_r1"),
            "mode_octal": "0755",
            "required_entries": ["command_contract.json"],
        },
        label="terminated r1 XFeat directory record",
    )
    _strict_equal(
        old.get("gftt_directory"),
        {
            "path": str(TERMINATED_R1_ROOT / "gftt_r1"),
            "mode_octal": "0755",
            "required_empty": True,
        },
        label="terminated r1 GFTT directory record",
    )
    orphan = old["orphan_command_contract"]
    root_descriptor = _open_held_directory(
        TERMINATED_R1_ROOT,
        label="terminated r1 root",
        expected=TERMINATED_R1_DIRECTORY_IDENTITIES["root"],
    )
    xfeat_descriptor: int | None = None
    gftt_descriptor: int | None = None
    orphan_descriptor: int | None = None
    try:
        if set(os.listdir(root_descriptor)) != {"xfeat_r1", "gftt_r1"}:
            raise AuditFailure("terminated r1 root directory tree drift")
        if _fstatfs_magic(root_descriptor) != 0x65735546:
            raise AuditFailure("terminated r1 held filesystem magic drift")
        xfeat_descriptor = _open_held_directory(
            "xfeat_r1",
            label="terminated r1 XFeat directory",
            expected=TERMINATED_R1_DIRECTORY_IDENTITIES["xfeat"],
            parent_descriptor=root_descriptor,
        )
        gftt_descriptor = _open_held_directory(
            "gftt_r1",
            label="terminated r1 GFTT directory",
            expected=TERMINATED_R1_DIRECTORY_IDENTITIES["gftt"],
            parent_descriptor=root_descriptor,
        )
        if set(os.listdir(xfeat_descriptor)) != {"command_contract.json"}:
            raise AuditFailure("terminated r1 XFeat directory tree drift")
        if os.listdir(gftt_descriptor):
            raise AuditFailure("terminated r1 GFTT directory is no longer empty")
        visible = os.stat(
            "command_contract.json",
            dir_fd=xfeat_descriptor,
            follow_symlinks=False,
        )
        orphan_descriptor = os.open(
            "command_contract.json",
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=xfeat_descriptor,
        )
        held = os.fstat(orphan_descriptor)
        held_identity = (int(held.st_dev), int(held.st_ino))
        if held_identity != (int(visible.st_dev), int(visible.st_ino)):
            raise AuditFailure("terminated r1 orphan changed before held open")
        encoded, observed = _read_regular_descriptor_bytes(
            orphan_descriptor,
            expected_identity=held_identity,
            label="terminated r1 orphan",
        )
        visible_after = os.stat(
            "command_contract.json",
            dir_fd=xfeat_descriptor,
            follow_symlinks=False,
        )
        if (int(visible_after.st_dev), int(visible_after.st_ino)) != held_identity:
            raise AuditFailure("terminated r1 orphan visible inode drift")
        live_orphan = {
            "path": str(TERMINATED_R1_ROOT / "xfeat_r1/command_contract.json"),
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "file_type": "regular",
            "expected_mode_octal": "0444",
            "observed_mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
            "symlink": False,
            "uid": int(observed.st_uid), "gid": int(observed.st_gid),
            "nlink": int(observed.st_nlink), "device_id": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mtime_ns": str(int(observed.st_mtime_ns)),
        }
        _strict_equal(live_orphan, orphan, label="terminated r1 orphan identity")
        if set(os.listdir(root_descriptor)) != {"xfeat_r1", "gftt_r1"}:
            raise AuditFailure("terminated r1 root directory changed during validation")
        if set(os.listdir(xfeat_descriptor)) != {"command_contract.json"}:
            raise AuditFailure("terminated r1 XFeat directory changed during validation")
        if os.listdir(gftt_descriptor):
            raise AuditFailure("terminated r1 GFTT directory changed during validation")
        for label, path, descriptor in (
            ("root", TERMINATED_R1_ROOT, root_descriptor),
            ("xfeat", TERMINATED_R1_ROOT / "xfeat_r1", xfeat_descriptor),
            ("gftt", TERMINATED_R1_ROOT / "gftt_r1", gftt_descriptor),
        ):
            visible_directory = os.lstat(path)
            held_directory = os.fstat(descriptor)
            if (
                stat.S_ISLNK(visible_directory.st_mode)
                or not stat.S_ISDIR(visible_directory.st_mode)
                or (int(visible_directory.st_dev), int(visible_directory.st_ino))
                != (int(held_directory.st_dev), int(held_directory.st_ino))
            ):
                raise AuditFailure(f"terminated r1 {label} visible directory drift")
        for row in expected_absences:
            if os.path.lexists(row["path"]):
                raise AuditFailure(
                    f"terminated r1 absent path appeared during validation: {row['role']}"
                )
    finally:
        for descriptor in (orphan_descriptor, gftt_descriptor, xfeat_descriptor):
            if descriptor is not None:
                os.close(descriptor)
        os.close(root_descriptor)
    return {"identity": identity, "payload": incident, "orphan": live_orphan}


R2_ROOT_FILE_NAMES = frozenset(
    {
        "probe16_freeze.json",
        "probe16_pre_run_start_receipt.json",
        "probe16_post_run_pair_seal.json",
    }
)
R2_ARM_FILE_NAMES = frozenset(
    {
        "command_contract.json",
        "producer_attempt.json",
        "launcher_start_receipt.json",
        "launcher_rc_receipt.json",
        "export_manifest.json",
        "features.bag",
        "raw_diagnostics.csv",
        "legacy_primitive_manifest.json",
    }
)


def _retired_r2_held_snapshot(
    expected_inventory: object,
) -> dict[str, object]:
    """Hold every r2 directory and file inode until the final exact relist."""

    if type(expected_inventory) is not list or any(
        type(row) is not dict for row in expected_inventory
    ):
        raise AuditFailure("terminated r2 expected inventory is malformed")
    expected_by_path = {
        row.get("path"): row for row in expected_inventory
    }
    if len(expected_by_path) != 24 or None in expected_by_path:
        raise AuditFailure("terminated r2 expected inventory is not exact 24")

    root = TERMINATED_R2_ROOT
    if root.expanduser().absolute() != root or root.resolve(strict=True) != root:
        raise AuditFailure("terminated r2 root is not canonical and symlink-free")
    directory_descriptors: dict[Path, int] = {}
    file_descriptors: dict[Path, int] = {}
    file_payloads: dict[str, bytes] = {}

    def expected_row(path: Path, kind: str) -> Mapping[str, object]:
        row = expected_by_path.get(str(path))
        if type(row) is not dict or row.get("kind") != kind:
            raise AuditFailure(f"terminated r2 expected {kind} row missing: {path}")
        return row

    def open_directory(
        path: Path, name: str | None, parent_descriptor: int | None
    ) -> int:
        raw = str(path) if name is None else name
        visible = (
            os.lstat(path)
            if parent_descriptor is None
            else os.stat(raw, dir_fd=parent_descriptor, follow_symlinks=False)
        )
        descriptor = os.open(
            raw,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        held = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(held.st_mode)
            or stat.S_ISLNK(visible.st_mode)
            or (int(visible.st_dev), int(visible.st_ino))
            != (int(held.st_dev), int(held.st_ino))
        ):
            os.close(descriptor)
            raise AuditFailure(f"terminated r2 directory open race: {path}")
        directory_descriptors[path] = descriptor
        return descriptor

    def directory_row(path: Path) -> dict[str, object]:
        observed = os.fstat(directory_descriptors[path])
        return {
            "path": str(path), "kind": "directory",
            "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
            "uid": int(observed.st_uid), "gid": int(observed.st_gid),
            "device_id": int(observed.st_dev), "inode": int(observed.st_ino),
            "nlink": int(observed.st_nlink), "size_bytes": int(observed.st_size),
        }

    def open_file(path: Path, name: str, parent_descriptor: int) -> None:
        visible = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        held = os.fstat(descriptor)
        identity = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or identity != (int(visible.st_dev), int(visible.st_ino))
        ):
            os.close(descriptor)
            raise AuditFailure(f"terminated r2 file open race: {path}")
        payload, _ = _read_regular_descriptor_bytes(
            descriptor, expected_identity=identity, label=f"terminated r2 {path.name}"
        )
        file_descriptors[path] = descriptor
        file_payloads[str(path)] = payload

    try:
        root_fd = open_directory(root, None, None)
        if _fstatfs_magic(root_fd) != EXT4_SUPER_MAGIC:
            raise AuditFailure("terminated r2 filesystem identity drift")
        if set(os.listdir(root_fd)) != R2_ROOT_FILE_NAMES | {"xfeat_r2", "gftt_r2"}:
            raise AuditFailure("terminated r2 root listing drift")
        for arm_name in ("xfeat_r2", "gftt_r2"):
            arm_path = root / arm_name
            arm_fd = open_directory(arm_path, arm_name, root_fd)
            if set(os.listdir(arm_fd)) != R2_ARM_FILE_NAMES | {"private_work"}:
                raise AuditFailure(f"terminated r2 {arm_name} listing drift")
            private_path = arm_path / "private_work"
            private_fd = open_directory(private_path, "private_work", arm_fd)
            if os.listdir(private_fd):
                raise AuditFailure(f"terminated r2 {arm_name} private work is not empty")
        for name in sorted(R2_ROOT_FILE_NAMES):
            open_file(root / name, name, root_fd)
        for arm_name in ("xfeat_r2", "gftt_r2"):
            arm_path = root / arm_name
            arm_fd = directory_descriptors[arm_path]
            for name in sorted(R2_ARM_FILE_NAMES):
                open_file(arm_path / name, name, arm_fd)

        rows = [directory_row(path) for path in directory_descriptors]
        for path, descriptor in file_descriptors.items():
            observed = os.fstat(descriptor)
            payload = file_payloads[str(path)]
            rows.append(
                {
                    "path": str(path), "kind": "regular",
                    "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
                    "uid": int(observed.st_uid), "gid": int(observed.st_gid),
                    "device_id": int(observed.st_dev), "inode": int(observed.st_ino),
                    "nlink": int(observed.st_nlink), "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        rows.sort(key=lambda row: str(row["path"]))
        _strict_equal(rows, expected_inventory, label="terminated r2 held tree inventory")

        if set(os.listdir(root_fd)) != R2_ROOT_FILE_NAMES | {"xfeat_r2", "gftt_r2"}:
            raise AuditFailure("terminated r2 root changed during held snapshot")
        for arm_name in ("xfeat_r2", "gftt_r2"):
            arm_path = root / arm_name
            arm_fd = directory_descriptors[arm_path]
            if set(os.listdir(arm_fd)) != R2_ARM_FILE_NAMES | {"private_work"}:
                raise AuditFailure(f"terminated r2 {arm_name} changed during held snapshot")
            if os.listdir(directory_descriptors[arm_path / "private_work"]):
                raise AuditFailure(f"terminated r2 {arm_name} private work changed")
        for path, descriptor in {**directory_descriptors, **file_descriptors}.items():
            visible = os.lstat(path)
            held = os.fstat(descriptor)
            if (
                stat.S_ISLNK(visible.st_mode)
                or (int(visible.st_dev), int(visible.st_ino))
                != (int(held.st_dev), int(held.st_ino))
            ):
                raise AuditFailure(f"terminated r2 visible inode drift: {path}")
        return {
            "inventory": rows,
            "file_payloads": file_payloads,
            "directory_descriptors": directory_descriptors,
            "file_descriptors": file_descriptors,
        }
    except BaseException:
        for descriptor in list(file_descriptors.values()) + list(
            reversed(tuple(directory_descriptors.values()))
        ):
            os.close(descriptor)
        raise


def _finish_retired_r2_held_snapshot(snapshot: Mapping[str, object]) -> None:
    directories = snapshot["directory_descriptors"]
    files = snapshot["file_descriptors"]
    payloads = snapshot["file_payloads"]
    root_fd = directories[TERMINATED_R2_ROOT]
    if set(os.listdir(root_fd)) != R2_ROOT_FILE_NAMES | {"xfeat_r2", "gftt_r2"}:
        raise AuditFailure("terminated r2 root changed before snapshot close")
    for arm_name in ("xfeat_r2", "gftt_r2"):
        arm_path = TERMINATED_R2_ROOT / arm_name
        if set(os.listdir(directories[arm_path])) != R2_ARM_FILE_NAMES | {
            "private_work"
        }:
            raise AuditFailure(f"terminated r2 {arm_name} changed before snapshot close")
        if os.listdir(directories[arm_path / "private_work"]):
            raise AuditFailure(f"terminated r2 {arm_name} private work changed")
    final_rows: list[dict[str, object]] = []
    for path, descriptor in directories.items():
        observed = os.fstat(descriptor)
        final_rows.append(
            {
                "path": str(path), "kind": "directory",
                "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
                "uid": int(observed.st_uid), "gid": int(observed.st_gid),
                "device_id": int(observed.st_dev), "inode": int(observed.st_ino),
                "nlink": int(observed.st_nlink), "size_bytes": int(observed.st_size),
            }
        )
    for path, descriptor in files.items():
        held = os.fstat(descriptor)
        identity = (int(held.st_dev), int(held.st_ino))
        os.lseek(descriptor, 0, os.SEEK_SET)
        encoded, final_stat = _read_regular_descriptor_bytes(
            descriptor, expected_identity=identity,
            label=f"terminated r2 final held {path.name}",
        )
        if encoded != payloads[str(path)]:
            raise AuditFailure(f"terminated r2 held bytes changed: {path}")
        final_rows.append(
            {
                "path": str(path), "kind": "regular",
                "mode_octal": format(stat.S_IMODE(final_stat.st_mode), "04o"),
                "uid": int(final_stat.st_uid), "gid": int(final_stat.st_gid),
                "device_id": int(final_stat.st_dev), "inode": int(final_stat.st_ino),
                "nlink": int(final_stat.st_nlink), "size_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    final_rows.sort(key=lambda row: str(row["path"]))
    _strict_equal(
        final_rows, snapshot["inventory"],
        label="terminated r2 final held stat/bytes inventory",
    )
    for path, descriptor in {**directories, **files}.items():
        visible = os.lstat(path)
        held = os.fstat(descriptor)
        if (
            stat.S_ISLNK(visible.st_mode)
            or (int(visible.st_dev), int(visible.st_ino))
            != (int(held.st_dev), int(held.st_ino))
        ):
            raise AuditFailure(f"terminated r2 visible inode drift at close: {path}")


def _close_retired_r2_held_snapshot(snapshot: Mapping[str, object]) -> None:
    for descriptor in list(snapshot["file_descriptors"].values()) + list(
        reversed(tuple(snapshot["directory_descriptors"].values()))
    ):
        os.close(descriptor)


def _continuation_scientific_projection(
    freeze: Mapping[str, object],
    *,
    command_contracts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Project the complete preregistered producer science, never outcomes."""

    fixed = _require_exact_keys(
        freeze.get("fixed_semantics"),
        {
            "manifest_schema_version", "attempt_schema_version", "feature_topic",
            "image_topic", "expected_arms", "diagnostic_fields",
            "common_diagnostic_fields", "allow_prefix_nonformal",
            "expected_published_frames", "expected_raw_frames",
        },
        label="continuation fixed semantics",
    )
    locked = _require_exact_keys(
        freeze.get("locked_inputs"),
        {"source_feature_bag", "raw_image_bag", "camera_yaml"},
        label="continuation locked inputs",
    )
    common = freeze.get("expected_common_contract")
    if type(common) is not dict:
        raise AuditFailure("continuation expected common contract is malformed")
    common_sha = freeze.get("expected_common_contract_sha256")
    if common_sha != core._canonical_sha256(common):
        raise AuditFailure("continuation expected common contract hash mismatch")
    arms = _require_exact_keys(
        freeze.get("arms"), set(EXPECTED_ARMS), label="continuation arms"
    )
    contracts = _require_exact_keys(
        command_contracts, set(EXPECTED_ARMS),
        label="continuation producer command contracts",
    )
    projected_arms: dict[str, object] = {}
    for arm_id in (XFEAT_ARM, GFTT_ARM):
        arm = _require_exact_keys(
            arms[arm_id], FREEZE_ARM_KEYS, label=f"continuation {arm_id} arm"
        )
        template = arm.get("manifest_template")
        if type(template) is not dict:
            raise AuditFailure(f"continuation {arm_id} manifest template malformed")
        if arm.get("manifest_template_sha256") != core._canonical_sha256(template):
            raise AuditFailure(f"continuation {arm_id} manifest template hash mismatch")
        arm_contract = template.get("arm_contract")
        arm_sha = template.get("arm_contract_sha256")
        if type(arm_contract) is not dict or arm_sha != core._canonical_sha256(
            arm_contract
        ):
            raise AuditFailure(f"continuation {arm_id} arm contract hash mismatch")
        if template.get("common_contract_sha256") != common_sha:
            raise AuditFailure(f"continuation {arm_id} common hash mismatch")
        _strict_equal(
            template.get("common_contract"), common,
            label=f"continuation {arm_id} common contract",
        )
        projected_arms[arm_id] = {
            "paths": copy.deepcopy(arm.get("paths")),
            "pre_run_required_absent": arm.get("pre_run_required_absent"),
            "manifest_template": copy.deepcopy(template),
            "dynamic_scalar_paths": copy.deepcopy(arm.get("dynamic_scalar_paths")),
            "attempt": copy.deepcopy(arm.get("attempt")),
            "producer_command_contract": copy.deepcopy(contracts[arm_id]),
        }
    allowed = freeze.get("allowed_pair_scalar_differences")
    required = freeze.get("required_pair_scalar_differences")
    if (
        type(allowed) is not list
        or type(required) is not list
        or any(type(value) is not str for value in [*allowed, *required])
    ):
        raise AuditFailure("continuation pair-difference policy is malformed")
    return {
        "schema_version": CONTINUATION_CONTRACT_SCHEMA,
        "freeze_schema_version": freeze.get("schema_version"),
        "freeze_status": freeze.get("status"),
        "scientific_role": freeze.get("scientific_role"),
        "mode": {
            "allow_prefix_nonformal": fixed["allow_prefix_nonformal"],
            "expected_published_frames": fixed["expected_published_frames"],
            "expected_raw_frames": fixed["expected_raw_frames"],
        },
        "locked_inputs": copy.deepcopy(locked),
        "fixed_semantics": copy.deepcopy(fixed),
        "expected_common_contract": copy.deepcopy(common),
        "expected_common_contract_sha256": common_sha,
        "arms": projected_arms,
        "allowed_pair_scalar_differences": copy.deepcopy(allowed),
        "required_pair_scalar_differences": copy.deepcopy(required),
        "publication_contract": copy.deepcopy(freeze.get("publication_contract")),
        "launcher_receipt_contract": copy.deepcopy(
            freeze.get("launcher_receipt_contract")
        ),
    }


def _remap_retired_r2_science_paths(value: object) -> object:
    """Apply the sole authorized r2-to-r3 artifact-path transformation."""

    path_mappings = (
        (
            str(TERMINATED_R2_ROOT / "xfeat_r2"),
            str(ARTIFACT_NAMESPACE_ROOT / "xfeat_r3"),
        ),
        (
            str(TERMINATED_R2_ROOT / "gftt_r2"),
            str(ARTIFACT_NAMESPACE_ROOT / "gftt_r3"),
        ),
        (str(TERMINATED_R2_ROOT), str(ARTIFACT_NAMESPACE_ROOT)),
    )
    if type(value) is dict:
        return {
            key: _remap_retired_r2_science_paths(child)
            for key, child in value.items()
        }
    if type(value) is list:
        return [_remap_retired_r2_science_paths(child) for child in value]
    if type(value) is str:
        for old, new in path_mappings:
            if value == old or value.startswith(old + os.sep):
                return new + value[len(old):]
    return copy.deepcopy(value)


def _validate_continuation_scientific_projection(
    freeze: Mapping[str, object],
    *,
    incident_gate: Mapping[str, object],
    allow_prefix: bool,
    expected_frames: int,
    candidate_command_contracts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Require a new freeze to be the exact science-preserving r2 continuation."""

    continuation = incident_gate.get("continuation_contract")
    if type(continuation) is not dict:
        raise AuditFailure("infrastructure incident lacks continuation contract")
    _require_exact_keys(
        continuation,
        {
            "schema_version", "freeze_schema_version", "freeze_status",
            "scientific_role", "mode", "locked_inputs", "fixed_semantics",
            "expected_common_contract", "expected_common_contract_sha256", "arms",
            "allowed_pair_scalar_differences", "required_pair_scalar_differences",
            "publication_contract", "launcher_receipt_contract",
        },
        label="incident continuation contract",
    )
    if continuation["schema_version"] != CONTINUATION_CONTRACT_SCHEMA:
        raise AuditFailure("incident continuation contract schema mismatch")
    _validate_continuation_mode_and_inputs(
        incident_gate=incident_gate,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        locked_inputs=freeze.get("locked_inputs"),
    )
    observed = _continuation_scientific_projection(
        freeze, command_contracts=candidate_command_contracts
    )
    expected = _remap_retired_r2_science_paths(continuation)
    _strict_equal(
        observed, expected,
        label="continuation scientific configuration",
    )
    return observed


def _validate_continuation_mode_and_inputs(
    *,
    incident_gate: Mapping[str, object],
    allow_prefix: bool,
    expected_frames: int,
    locked_inputs: Mapping[str, object],
) -> None:
    """Fail before bag reconstruction when a continuation changes mode or inputs."""

    continuation = incident_gate.get("continuation_contract")
    if type(continuation) is not dict:
        raise AuditFailure("infrastructure incident lacks continuation contract")
    expected_mode = {
        "allow_prefix_nonformal": bool(allow_prefix),
        "expected_published_frames": int(expected_frames),
        "expected_raw_frames": _mode_raw_frames(
            allow_prefix=allow_prefix, expected_frames=expected_frames
        ),
    }
    _strict_equal(
        continuation.get("mode"), expected_mode,
        label="continuation probe mode",
    )
    _strict_equal(
        locked_inputs, continuation.get("locked_inputs"),
        label="continuation locked inputs",
    )


def _retired_r2_json(path: Path, *, label: str) -> dict[str, object]:
    encoded, _ = _read_regular_nofollow(path, label=label)
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise AuditFailure(f"{label} is not a JSON object")
    return payload


def _retired_r2_file_identity(path: Path, *, label: str) -> dict[str, object]:
    encoded, _ = _read_regular_nofollow(path, label=label)
    return {
        "path": str(path.resolve(strict=True)),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _historical_auditor_branch_contract(pyc_bytes: bytes) -> dict[str, object]:
    """Mechanically identify the frozen legacy-reason branch without executing it."""

    if len(pyc_bytes) < 16:
        raise AuditFailure("historical auditor bytecode is truncated")
    try:
        root = marshal.loads(pyc_bytes[16:])
    except (EOFError, ValueError, TypeError) as exc:
        raise AuditFailure("historical auditor bytecode cannot be decoded") from exc
    if not isinstance(root, types.CodeType):
        raise AuditFailure("historical auditor root is not a code object")

    def walk(code: types.CodeType):
        for value in code.co_consts:
            if isinstance(value, types.CodeType):
                yield value
                yield from walk(value)

    matches = [code for code in walk(root) if code.co_name == "_validate_legacy_manifest"]
    if len(matches) != 1:
        raise AuditFailure("historical legacy validator code object is not unique")
    code = matches[0]
    parameters = list(code.co_varnames[: code.co_argcount + code.co_kwonlyargcount])
    string_constants = sorted(
        value for value in code.co_consts if type(value) is str
    )
    required = {
        "full_export_from_frozen_cli_production_factory",
        "full_export_from_frozen_matched_cli_factory",
        " legacy formal eligibility reason mismatch",
        " matched formal eligibility reason mismatch",
    }
    if (
        parameters != ["arm_id", "legacy_path", "feature_bag", "matched_manifest"]
        or "allow_prefix" in parameters
        or not required.issubset(string_constants)
        or "explicit_prefix_is_nonformal" in string_constants
    ):
        raise AuditFailure("historical auditor legacy-reason branch semantic drift")
    return {
        "code_object_name": code.co_name,
        "parameters": parameters,
        "required_full_reason_constants": sorted(required),
        "explicit_prefix_reason_constant_absent": True,
        "allow_prefix_parameter_absent": True,
        "interpretation": (
            "mechanical bytecode inference: the historical validator accepted no "
            "allow_prefix parameter and embedded only the two full-export reason checks"
        ),
    }


_ACTIVE_RETIRED_R2_SNAPSHOT: dict[str, object] | None = None


def _decode_retired_r2_snapshot_json(
    path: Path, encoded: bytes, *, label: str
) -> dict[str, object]:
    """Decode one held r2 JSON payload and enforce its exact frozen codec."""

    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise AuditFailure(f"{label} is not a JSON object")
    expected = (
        (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if path.name == "legacy_primitive_manifest.json"
        else _canonical_bytes(payload)
    )
    if encoded != expected:
        raise AuditFailure(f"{label} does not use its frozen canonical JSON codec")
    return payload


def _validate_infrastructure_incident_impl() -> dict[str, object]:
    global _ACTIVE_RETIRED_R2_SNAPSHOT
    prior = _validate_r1_infrastructure_incident()
    incident, identity = _load_canonical_object_single_fd(
        INFRASTRUCTURE_INCIDENT_PATH,
        label="matched probe16 audit infrastructure incident",
    )
    incident_stat = os.lstat(INFRASTRUCTURE_INCIDENT_PATH)
    if (
        int(incident_stat.st_uid) != int(os.getuid())
        or stat.S_IMODE(incident_stat.st_mode) != 0o444
    ):
        raise AuditFailure("matched probe16 audit incident is not mode-0444 owned")
    if (
        identity["size_bytes"] != INFRASTRUCTURE_INCIDENT_SIZE
        or identity["sha256"] != INFRASTRUCTURE_INCIDENT_SHA256
    ):
        raise AuditFailure("matched probe16 audit incident identity drift")
    _require_exact_keys(
        incident,
        {
            "schema_version", "status", "scientific_role",
            "prior_infrastructure_incident", "human_record",
            "terminated_namespace", "execution", "failure_analysis",
            "supersession_policy",
        },
        label="matched probe16 audit incident",
    )
    if (
        incident["schema_version"]
        != "aqua-fe-matched-birth-probe16-audit-incident-v1"
        or incident["status"]
        != "SEALED_R2_EXPORTS_RC0_POST_AUDIT_FALSE_NEGATIVE_NAMESPACE_TERMINATED"
        or incident["scientific_role"]
        != "AUDIT_INFRASTRUCTURE_FAILURE_AFTER_NONFORMAL_PREFIX_PRODUCERS"
    ):
        raise AuditFailure("matched probe16 audit incident semantic drift")
    _strict_equal(
        incident["prior_infrastructure_incident"], prior["identity"],
        label="matched probe16 prior incident identity",
    )
    live_human = _retired_r2_file_identity(
        INFRASTRUCTURE_INCIDENT_MD_PATH, label="matched probe16 human incident"
    )
    human_stat = os.lstat(INFRASTRUCTURE_INCIDENT_MD_PATH)
    if (
        live_human["size_bytes"] != INFRASTRUCTURE_INCIDENT_MD_SIZE
        or live_human["sha256"] != INFRASTRUCTURE_INCIDENT_MD_SHA256
        or int(human_stat.st_uid) != int(os.getuid())
        or stat.S_IMODE(human_stat.st_mode) != 0o444
    ):
        raise AuditFailure("matched probe16 human incident identity drift")
    _strict_equal(
        incident["human_record"], live_human,
        label="matched probe16 human incident claim",
    )

    terminated = _require_exact_keys(
        incident["terminated_namespace"],
        {
            "root", "filesystem", "tree_inventory", "tree_entry_count",
            "delete_modify_complete_or_reuse_forbidden",
        },
        label="terminated r2 namespace",
    )
    if (
        terminated["root"] != str(TERMINATED_R2_ROOT)
        or terminated["filesystem"]
        != {"filesystem_type": "ext4", "device_id": 66312}
        or terminated["delete_modify_complete_or_reuse_forbidden"] is not True
        or terminated["tree_entry_count"] != 24
    ):
        raise AuditFailure("terminated r2 namespace policy drift")
    snapshot = _retired_r2_held_snapshot(terminated["tree_inventory"])
    if _ACTIVE_RETIRED_R2_SNAPSHOT is not None:
        _close_retired_r2_held_snapshot(snapshot)
        raise AuditFailure("nested terminated r2 snapshot is forbidden")
    _ACTIVE_RETIRED_R2_SNAPSHOT = snapshot
    live_inventory = snapshot["inventory"]
    snapshot_payloads = snapshot["file_payloads"]

    def snapshot_bytes(path: Path, *, label: str) -> bytes:
        encoded = snapshot_payloads.get(str(path))
        if type(encoded) is not bytes:
            raise AuditFailure(f"{label} is absent from the held r2 snapshot")
        return encoded

    def snapshot_json(path: Path, *, label: str) -> dict[str, object]:
        return _decode_retired_r2_snapshot_json(
            path, snapshot_bytes(path, label=label), label=label
        )

    def snapshot_identity(path: Path, *, label: str) -> dict[str, object]:
        encoded = snapshot_bytes(path, label=label)
        return {
            "path": str(path),
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    execution = _require_exact_keys(
        incident["execution"],
        {
            "freeze", "freeze_status", "pre_run_start_receipt", "pre_run_status",
            "arms", "post_run_error_seal", "post_run_error_payload",
            "observed_audit_return_code", "audit_return_code_source",
            "formal900_started", "vins_started", "evaluator_started",
            "shared_pycache_prefix_absent_after_terminal_error",
        },
        label="terminated r2 execution",
    )
    freeze_path = TERMINATED_R2_ROOT / "probe16_freeze.json"
    start_path = TERMINATED_R2_ROOT / "probe16_pre_run_start_receipt.json"
    seal_path = TERMINATED_R2_ROOT / "probe16_post_run_pair_seal.json"
    freeze = snapshot_json(freeze_path, label="terminated r2 freeze")
    start = snapshot_json(start_path, label="terminated r2 start receipt")
    seal = snapshot_json(seal_path, label="terminated r2 error seal")
    for claim, path, label in (
        (execution["freeze"], freeze_path, "terminated r2 freeze"),
        (execution["pre_run_start_receipt"], start_path, "terminated r2 start receipt"),
        (execution["post_run_error_seal"], seal_path, "terminated r2 error seal"),
    ):
        _strict_equal(
            claim, snapshot_identity(path, label=label), label=f"{label} identity"
        )
    expected_error = {
        "claim_boundary": {
            "contract_pass": False,
            "output_namespace_consumed_no_retry": True,
        },
        "error": {
            "message": "XFEAT_BIRTH_RAWLK_MATCHED_V1 legacy formal eligibility reason mismatch",
            "type": "AuditFailure",
        },
        "pass": False,
        "schema_version": SCHEMA_VERSION,
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "status": "ERROR",
    }
    if (
        execution["freeze_status"] != "FROZEN"
        or freeze.get("status") != "FROZEN"
        or execution["pre_run_status"] != "PASS_PRE_RUN_FREEZE_AND_ABSENCE"
        or start.get("status") != "PASS_PRE_RUN_FREEZE_AND_ABSENCE"
    ):
        raise AuditFailure("terminated r2 freeze/start status drift")
    _strict_equal(seal, expected_error, label="terminated r2 error seal payload")
    _strict_equal(
        execution["post_run_error_payload"], expected_error,
        label="terminated r2 recorded error payload",
    )
    if (
        execution["observed_audit_return_code"] != 2
        or execution["audit_return_code_source"]
        != "orchestrator_transcript_not_independent_receipt"
        or execution["formal900_started"] is not False
        or execution["vins_started"] is not False
        or execution["evaluator_started"] is not False
        or execution["shared_pycache_prefix_absent_after_terminal_error"] is not True
        or os.path.lexists(
            "/tmp/aqua-fe-a02-matched-birth-rawlk-empty-pycache-v1"
        )
    ):
        raise AuditFailure("terminated r2 execution boundary drift")

    frozen_arm_paths = {
        arm_id: {
            role: Path(path)
            for role, path in freeze["arms"][arm_id]["paths"].items()
        }
        for arm_id in (XFEAT_ARM, GFTT_ARM)
    }
    frozen_audit_paths = {
        role: Path(path) for role, path in freeze["audit_paths"].items()
    }
    snapshot_rows = {row["path"]: row for row in live_inventory}
    snapshot_contracts: dict[str, dict[str, object]] = {}
    snapshot_receipts: dict[str, dict[str, object]] = {}
    for arm_id, directory in (
        (XFEAT_ARM, TERMINATED_R2_ROOT / "xfeat_r2"),
        (GFTT_ARM, TERMINATED_R2_ROOT / "gftt_r2"),
    ):
        command_path = directory / "command_contract.json"
        start_path = directory / "launcher_start_receipt.json"
        rc_path = directory / "launcher_rc_receipt.json"
        snapshot_contracts[arm_id] = snapshot_json(
            command_path, label=f"{arm_id} held command contract"
        )
        snapshot_receipts[arm_id] = {
            "start": snapshot_json(
                start_path, label=f"{arm_id} held launcher start"
            ),
            "rc": snapshot_json(rc_path, label=f"{arm_id} held launcher RC"),
            "start_identity": snapshot_identity(
                start_path, label=f"{arm_id} held launcher start"
            ),
            "rc_identity": snapshot_identity(
                rc_path, label=f"{arm_id} held launcher RC"
            ),
            "start_mode": int(
                str(snapshot_rows[str(start_path)]["mode_octal"]), 8
            ),
            "rc_mode": int(str(snapshot_rows[str(rc_path)]["mode_octal"]), 8),
        }
    historical_governance = _validate_governance_contract(
        freeze,
        freeze_json=freeze_path,
        source_bag=Path(freeze["locked_inputs"]["source_feature_bag"]["path"]),
        raw_bag=Path(freeze["locked_inputs"]["raw_image_bag"]["path"]),
        camera_yaml=Path(freeze["locked_inputs"]["camera_yaml"]["path"]),
        arm_paths=frozen_arm_paths,
        audit_paths=frozen_audit_paths,
        feature_topic="/feature_tracker/feature",
        image_topic="/camera/image_raw",
        allow_prefix=True,
        expected_frames=16,
        in_memory_command_contracts=snapshot_contracts,
        historical_builder_record_only=True,
    )
    historical_launcher = _validate_launcher_receipts(
        {"governance": historical_governance},
        in_memory_receipts=snapshot_receipts,
        in_memory_command_contracts=snapshot_contracts,
    )

    arm_records = _require_exact_keys(
        execution["arms"], {XFEAT_ARM, GFTT_ARM}, label="terminated r2 arms"
    )
    common_hashes: set[str] = set()
    for arm_id, directory in (
        (XFEAT_ARM, TERMINATED_R2_ROOT / "xfeat_r2"),
        (GFTT_ARM, TERMINATED_R2_ROOT / "gftt_r2"),
    ):
        record = _require_exact_keys(
            arm_records[arm_id],
            {
                "attempt", "attempt_count", "process_start_count", "no_retry",
                "launcher_start_receipt", "launcher_rc_receipt", "producer_process",
                "manifest", "legacy_manifest", "status", "formal_eligible",
                "matched_reason", "legacy_reason", "common_contract_sha256",
                "metrics", "outputs",
            },
            label=f"terminated r2 {arm_id}",
        )
        attempt_path = directory / "producer_attempt.json"
        command_path = directory / "command_contract.json"
        launcher_start = directory / "launcher_start_receipt.json"
        launcher_rc = directory / "launcher_rc_receipt.json"
        manifest_path = directory / "export_manifest.json"
        legacy_path = directory / "legacy_primitive_manifest.json"
        for claim, path, label in (
            (record["attempt"], attempt_path, "attempt"),
            (record["launcher_start_receipt"], launcher_start, "launcher start"),
            (record["launcher_rc_receipt"], launcher_rc, "launcher RC"),
            (record["manifest"], manifest_path, "matched manifest"),
            (record["legacy_manifest"], legacy_path, "legacy manifest"),
        ):
            _strict_equal(
                claim,
                snapshot_identity(path, label=f"{arm_id} {label}"),
                label=f"terminated r2 {arm_id} {label} identity",
            )
        attempt = snapshot_json(attempt_path, label=f"{arm_id} attempt")
        contract = snapshot_json(command_path, label=f"{arm_id} command contract")
        start_receipt = snapshot_json(
            launcher_start, label=f"{arm_id} launcher start receipt"
        )
        rc = snapshot_json(launcher_rc, label=f"{arm_id} launcher RC")
        manifest = snapshot_json(manifest_path, label=f"{arm_id} manifest")
        legacy = snapshot_json(legacy_path, label=f"{arm_id} legacy manifest")
        frozen_command = freeze["authoritative_commands"]["arms"][arm_id]
        _strict_equal(
            frozen_command["command_contract"],
            snapshot_identity(command_path, label=f"{arm_id} command contract"),
            label=f"terminated r2 {arm_id} frozen command identity",
        )
        _strict_equal(
            historical_launcher[arm_id]["start_receipt"],
            snapshot_identity(launcher_start, label=f"{arm_id} launcher start"),
            label=f"terminated r2 {arm_id} historical start receipt",
        )
        _strict_equal(
            historical_launcher[arm_id]["rc_receipt"],
            snapshot_identity(launcher_rc, label=f"{arm_id} launcher RC"),
            label=f"terminated r2 {arm_id} historical RC receipt",
        )
        _strict_equal(
            rc.get("start_receipt"),
            snapshot_identity(launcher_start, label=f"{arm_id} launcher start"),
            label=f"terminated r2 {arm_id} RC-to-start binding",
        )
        _strict_equal(
            rc.get("command_contract"),
            snapshot_identity(command_path, label=f"{arm_id} command contract"),
            label=f"terminated r2 {arm_id} RC-to-command binding",
        )
        _strict_equal(
            start_receipt.get("launcher_invocation", {}).get("process_command_line"),
            frozen_command["launcher_argv"],
            label=f"terminated r2 {arm_id} launcher invocation argv",
        )
        _strict_equal(
            rc.get("actual_execution"),
            {
                "argv": contract["argv"],
                "environment": contract["environment"],
                "working_directory": contract["working_directory"],
                "shell": False,
            },
            label=f"terminated r2 {arm_id} actual execution",
        )
        if (
            record["attempt_count"] != 1
            or record["process_start_count"] != 1
            or record["no_retry"] is not True
            or attempt.get("attempt_count") != 1
            or attempt.get("process_start_count") != 1
            or attempt.get("no_retry") is not True
        ):
            raise AuditFailure(f"terminated r2 {arm_id} attempt drift")
        _strict_equal(
            record["producer_process"], rc.get("producer_process"),
            label=f"terminated r2 {arm_id} producer process",
        )
        producer = rc.get("producer_process")
        if (
            type(producer) is not dict
            or producer.get("producer_return_code") != 0
            or producer.get("process_start_count") != 1
            or producer.get("launch_attempt_count") != 1
            or producer.get("natural_end_observed") is not True
            or producer.get("exited_normally") is not True
            or producer.get("retry_performed") is not False
            or producer.get("timed_out") is not False
            or producer.get("terminated_by_signal") is not False
        ):
            raise AuditFailure(f"terminated r2 {arm_id} producer receipt drift")
        _strict_equal(
            manifest.get("attempt"),
            {
                "identity": snapshot_identity(attempt_path, label=f"{arm_id} attempt"),
                "payload": attempt,
            },
            label=f"terminated r2 {arm_id} attempt-to-manifest binding",
        )
        expected_outputs = {
            "feature_bag": snapshot_identity(
                directory / "features.bag", label=f"{arm_id} feature bag"
            ),
            "raw_diagnostics_csv": snapshot_identity(
                directory / "raw_diagnostics.csv", label=f"{arm_id} diagnostics"
            ),
            "legacy_primitive_manifest": snapshot_identity(
                legacy_path, label=f"{arm_id} legacy manifest"
            ),
        }
        _strict_equal(
            manifest.get("outputs"), expected_outputs,
            label=f"terminated r2 {arm_id} manifest live outputs",
        )
        _strict_equal(
            record["outputs"], expected_outputs,
            label=f"terminated r2 {arm_id} incident live outputs",
        )
        legacy_output = legacy.get("output_bag")
        if type(legacy_output) is not dict:
            raise AuditFailure(f"terminated r2 {arm_id} legacy output is malformed")
        _strict_equal(
            {key: legacy_output[key] for key in ("size_bytes", "sha256")},
            {
                key: expected_outputs["feature_bag"][key]
                for key in ("size_bytes", "sha256")
            },
            label=f"terminated r2 {arm_id} legacy feature identity",
        )
        for key in (
            "status", "formal_eligible", "formal_eligibility_reason",
            "common_contract_sha256", "metrics", "outputs",
        ):
            recorded_key = {
                "formal_eligibility_reason": "matched_reason"
            }.get(key, key)
            _strict_equal(
                record[recorded_key], manifest.get(key),
                label=f"terminated r2 {arm_id} manifest {key}",
            )
        _strict_equal(
            record["legacy_reason"], legacy.get("formal_eligibility_reason"),
            label=f"terminated r2 {arm_id} legacy reason",
        )
        if (
            record["status"] != "PREFIX_NONFORMAL"
            or record["formal_eligible"] is not False
            or record["matched_reason"] != "explicit_prefix_is_nonformal"
            or record["legacy_reason"] != "explicit_prefix_is_nonformal"
        ):
            raise AuditFailure(f"terminated r2 {arm_id} prefix evidence drift")
        common_hashes.add(str(record["common_contract_sha256"]))
    if common_hashes != {
        "3c1ab137f199894f32ee9d882f06ff180d5dad4461e63f93b9220b09b4f2232a"
    }:
        raise AuditFailure("terminated r2 common contract hash drift")

    failure = _require_exact_keys(
        incident["failure_analysis"],
        {
            "auditor_at_failure", "frozen_post_audit_command_sha256",
            "historical_auditor_pyc",
            "only_failure_message", "actual_prefix_reason", "frozen_bug",
            "correct_mapping",
            "detector_carrier_input_schedule_threshold_or_output_bytes_changed",
            "r2_outputs_adopted_as_passed_pair_evidence",
        },
        label="terminated r2 failure analysis",
    )
    _strict_equal(
        failure["auditor_at_failure"], freeze.get("auditor_identity"),
        label="terminated r2 frozen auditor identity",
    )
    if failure["frozen_post_audit_command_sha256"] != hashlib.sha256(
        _canonical_bytes(freeze["authoritative_commands"]["post_run_audit"])
    ).hexdigest():
        raise AuditFailure("terminated r2 post-audit command hash drift")
    pyc_claim = _require_exact_keys(
        failure["historical_auditor_pyc"],
        {"path", "size_bytes", "sha256", "header_source_size"},
        label="terminated r2 historical auditor bytecode",
    )
    pyc_path = Path(str(pyc_claim["path"]))
    if pyc_path != HISTORICAL_AUDITOR_PYC_PATH:
        raise AuditFailure("historical auditor bytecode evidence path drift")
    pyc_bytes, _ = _read_regular_nofollow(
        pyc_path, label="terminated r2 historical auditor bytecode"
    )
    pyc_stat = os.lstat(pyc_path)
    if (
        int(pyc_stat.st_uid) != int(os.getuid())
        or int(pyc_stat.st_nlink) != 1
        or stat.S_IMODE(pyc_stat.st_mode) != 0o444
    ):
        raise AuditFailure("historical auditor bytecode is not sealed mode-0444 evidence")
    _strict_equal(
        {key: pyc_claim[key] for key in ("path", "size_bytes", "sha256")},
        {
            "path": str(pyc_path),
            "size_bytes": len(pyc_bytes),
            "sha256": hashlib.sha256(pyc_bytes).hexdigest(),
        },
        label="terminated r2 historical auditor bytecode identity",
    )
    if (
        len(pyc_bytes) < 16
        or int.from_bytes(pyc_bytes[4:8], "little") != 0
        or int.from_bytes(pyc_bytes[12:16], "little")
        != int(pyc_claim["header_source_size"])
        or int(pyc_claim["header_source_size"])
        != int(failure["auditor_at_failure"]["size_bytes"])
    ):
        raise AuditFailure("terminated r2 historical auditor bytecode header drift")
    _historical_auditor_branch_contract(pyc_bytes)
    _strict_equal(
        {
            "only_failure_message": failure["only_failure_message"],
            "actual_prefix_reason": failure["actual_prefix_reason"],
            "frozen_bug": failure["frozen_bug"],
            "correct_mapping": failure["correct_mapping"],
            "detector_carrier_input_schedule_threshold_or_output_bytes_changed": failure[
                "detector_carrier_input_schedule_threshold_or_output_bytes_changed"
            ],
            "r2_outputs_adopted_as_passed_pair_evidence": failure[
                "r2_outputs_adopted_as_passed_pair_evidence"
            ],
        },
        {
            "only_failure_message": expected_error["error"]["message"],
            "actual_prefix_reason": "explicit_prefix_is_nonformal",
            "frozen_bug": (
                "legacy cross-binding unconditionally required full-export reasons "
                "even when allow_prefix was true"
            ),
            "correct_mapping": {
                "probe16": {
                    "legacy": "explicit_prefix_is_nonformal",
                    "matched": "explicit_prefix_is_nonformal",
                },
                "formal900": {
                    "legacy": "full_export_from_frozen_cli_production_factory",
                    "matched": "full_export_from_frozen_matched_cli_factory",
                },
            },
            "detector_carrier_input_schedule_threshold_or_output_bytes_changed": False,
            "r2_outputs_adopted_as_passed_pair_evidence": False,
        },
        label="terminated r2 failure predicate",
    )
    _strict_equal(
        incident["supersession_policy"],
        {
            "new_namespace_root": str(ARTIFACT_NAMESPACE_ROOT),
            "old_r1_incident_and_orphan_must_remain_exact": True,
            "old_r2_tree_must_remain_exact": True,
            "old_r2_delete_modify_complete_or_reuse_forbidden": True,
            "requires_fresh_outcome_blind_freeze_and_start_check": True,
            "requires_same_probe16_scientific_configuration": True,
            "permitted_change_categories": [
                "mode-aware legacy/matched eligibility-reason audit mapping",
                "additive incident and namespace governance",
                "tests and live code-closure identities",
            ],
            "scientific_parameter_or_algorithm_change_forbidden": True,
        },
        label="terminated r2 supersession policy",
    )
    continuation = _continuation_scientific_projection(
        freeze, command_contracts=snapshot_contracts
    )
    _strict_equal(
        continuation["mode"],
        {
            "allow_prefix_nonformal": True,
            "expected_published_frames": PROBE_PUBLISHED_FRAMES,
            "expected_raw_frames": 2 * PROBE_PUBLISHED_FRAMES,
        },
        label="terminated r2 continuation probe mode",
    )
    _strict_equal(
        continuation["fixed_semantics"],
        _fixed_semantics(
            feature_topic=FEATURE_TOPIC_DEFAULT,
            image_topic="/camera/image_raw",
            allow_prefix=True,
            expected_frames=PROBE_PUBLISHED_FRAMES,
        ),
        label="terminated r2 continuation fixed semantics",
    )
    _finish_retired_r2_held_snapshot(snapshot)
    return {
        "identity": identity,
        "prior_incident": prior["identity"],
        "authorized_namespace_root": str(ARTIFACT_NAMESPACE_ROOT),
        "continuation_contract": continuation,
        "governance_evidence": {
            "retired_r2_evidence_read_for_governance": True,
            "retired_r2_outcomes_used_for_scientific_projection": False,
            "candidate_r3_outcomes_read": False,
            "historical_builder_identity_scope": (
                "recorded_in_held_r2_freeze_not_live_byte_revalidated"
            ),
        },
    }


def _validate_infrastructure_incident() -> dict[str, object]:
    global _ACTIVE_RETIRED_R2_SNAPSHOT
    if _ACTIVE_RETIRED_R2_SNAPSHOT is not None:
        raise AuditFailure("terminated r2 snapshot lifecycle is already active")
    try:
        return _validate_infrastructure_incident_impl()
    finally:
        snapshot = _ACTIVE_RETIRED_R2_SNAPSHOT
        _ACTIVE_RETIRED_R2_SNAPSHOT = None
        if snapshot is not None:
            _close_retired_r2_held_snapshot(snapshot)


def _load_manifest(path: Path) -> dict[str, object]:
    return _load_canonical_object(path, label="manifest")


def _load_pretty_object(path: Path, *, label: str) -> dict[str, object]:
    path = _regular_path(path, label=label)
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid UTF-8 JSON: {path}") from exc
    expected = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if type(payload) is not dict or path.read_bytes() != expected:
        raise AuditFailure(f"{label} is not canonical pretty object JSON: {path}")
    return payload


def _require_exact_keys(
    value: object, expected: frozenset[str] | set[str], *, label: str
) -> Mapping[str, object]:
    if type(value) is not dict:
        raise AuditFailure(f"{label} must be an object")
    observed = set(value)
    if observed != set(expected):
        raise AuditFailure(
            f"{label} exact keyset mismatch: missing={sorted(set(expected)-observed)} "
            f"extra={sorted(observed-set(expected))}"
        )
    return value


def _strict_differences(
    actual: object, expected: object, path: tuple[object, ...] = ()
) -> list[str]:
    """Return recursive, type-sensitive differences (bool/int/float differ)."""

    here = _json_pointer(path)
    if type(actual) is not type(expected):
        return [here]
    if type(expected) is dict:
        result: list[str] = []
        actual_keys = set(actual)
        expected_keys = set(expected)
        for key in sorted(actual_keys ^ expected_keys):
            result.append(_json_pointer(path + (key,)))
        for key in sorted(actual_keys & expected_keys):
            result.extend(_strict_differences(actual[key], expected[key], path + (key,)))
        return result
    if type(expected) is list:
        result = []
        if len(actual) != len(expected):
            result.append(_json_pointer(path + ("@length",)))
        for index in range(min(len(actual), len(expected))):
            result.extend(
                _strict_differences(actual[index], expected[index], path + (index,))
            )
        for index in range(min(len(actual), len(expected)), max(len(actual), len(expected))):
            result.append(_json_pointer(path + (index,)))
        return result
    return [] if actual == expected else [here]


def _strict_equal(actual: object, expected: object, *, label: str) -> None:
    differences = _strict_differences(actual, expected)
    if differences:
        raise AuditFailure(
            f"{label} exact recursive mismatch at {differences[:12]}"
        )


def _json_pointer(path: tuple[object, ...]) -> str:
    if not path:
        return ""
    return "/" + "/".join(
        str(item).replace("~", "~0").replace("/", "~1") for item in path
    )


def _flatten(
    value: object, prefix: tuple[object, ...] = ()
) -> dict[tuple[object, ...], tuple[str, object]]:
    result: dict[tuple[object, ...], tuple[str, object]] = {}
    if isinstance(value, dict):
        result[prefix + ("@type",)] = ("type", "dict")
        for key in sorted(value):
            result.update(_flatten(value[key], prefix + (str(key),)))
    elif isinstance(value, list):
        result[prefix + ("@type",)] = ("type", "list")
        result[prefix + ("@length",)] = ("length", len(value))
        for index, item in enumerate(value):
            result.update(_flatten(item, prefix + (index,)))
    else:
        result[prefix] = (type(value).__name__, value)
    return result


def _pair_scalar_differences(left: object, right: object) -> list[str]:
    left_flat = _flatten(left)
    right_flat = _flatten(right)
    return sorted(
        _json_pointer(path)
        for path in set(left_flat) | set(right_flat)
        if left_flat.get(path) != right_flat.get(path)
    )


def _pair_difference_path_allowed(pointer: str) -> bool:
    exact = {
        "/arm_contract/arm_id",
        "/arm_contract/detector/family",
        "/arm_contract/detector/implementation_id",
        "/arm_contract/provenance/source_code",
        "/arm_contract/provenance/is_learned",
        "/arm_contract_sha256",
        "/attempt/identity/path",
        "/attempt/identity/size_bytes",
        "/attempt/identity/sha256",
        "/attempt/payload/arm_id",
        "/attempt/payload/reserved_outputs/feature_bag",
        "/attempt/payload/reserved_outputs/manifest_json",
        "/attempt/payload/reserved_outputs/diagnostics_csv",
        "/attempt/payload/reserved_outputs/legacy_primitive_manifest",
        "/attempt/payload/reserved_outputs/private_work_directory",
        "/attempt/payload/producer/wrapper_requested",
        "/code_artifacts/wrapper/path",
        "/code_artifacts/wrapper/size_bytes",
        "/code_artifacts/wrapper/sha256",
        "/outputs/feature_bag/path",
        "/outputs/feature_bag/size_bytes",
        "/outputs/feature_bag/sha256",
        "/outputs/raw_diagnostics_csv/path",
        "/outputs/raw_diagnostics_csv/size_bytes",
        "/outputs/raw_diagnostics_csv/sha256",
        "/outputs/legacy_primitive_manifest/path",
        "/outputs/legacy_primitive_manifest/size_bytes",
        "/outputs/legacy_primitive_manifest/sha256",
        "/legacy_prepublication_rebind/primitive_reported_work_bag_path",
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/path",
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/size_bytes",
        "/legacy_prepublication_rebind/primitive_reported_output_identity_after_path_rebind/sha256",
        "/legacy_prepublication_rebind/published_feature_bag_identity/path",
        "/legacy_prepublication_rebind/published_feature_bag_identity/size_bytes",
        "/legacy_prepublication_rebind/published_feature_bag_identity/sha256",
        "/runtime/elapsed_wall_ms",
    }
    if pointer in exact:
        return True
    if pointer.startswith("/arm_contract/detector/contract/"):
        return True
    if pointer.startswith("/code_artifacts/detector_dependencies/"):
        return True
    if pointer.startswith("/code_artifacts/detector_runtime/"):
        return True
    if pointer.startswith("/metrics/") and pointer.rsplit("/", 1)[-1] in METRIC_DYNAMIC_LEAVES:
        return True
    parts = pointer.split("/")
    # ['', 'raw_frame_diagnostics', '<index>', '<field>', ...]
    return bool(
        len(parts) >= 4
        and parts[1] == "raw_frame_diagnostics"
        and parts[2].isdigit()
        and parts[3] in PAIR_ALLOWED_RAW_OUTCOME_FIELDS
    )


def _audit_runtime_observation() -> dict[str, object]:
    # This is the declared deterministic initialization for the independent
    # common-preprocessing recomputation, not a repair of environment drift.
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    if _canonical_bytes(dict(os.environ)) != _canonical_bytes(
        sealed_launcher.FROZEN_ENVIRONMENT
    ):
        raise AuditFailure("audit process environment is not the exact frozen environment")
    core._configure_runtime()
    if os.environ.get("PYTHONPATH") != core.EXPECTED_PYTHONPATH:
        raise AuditFailure("audit PYTHONPATH is not the frozen explicit path")
    try:
        runtime = core._runtime_identity(strict=True)
    except (RuntimeError, OSError, ValueError) as exc:
        raise AuditFailure(f"audit numeric runtime mismatch: {exc}") from exc
    return {
        "core_runtime": runtime,
        "pythonpath": os.environ.get("PYTHONPATH"),
        "path": os.environ.get("PATH"),
        "lang": os.environ.get("LANG"),
        "lc_all": os.environ.get("LC_ALL"),
        "sys_path": list(sys.path),
        "sitecustomize": runtime["sitecustomize"],
        "usercustomize_absent": runtime["usercustomize_absent"],
        "pycache_prefix": runtime["pycache_prefix"],
    }


def _audit_code_closure() -> dict[str, object]:
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    return {
        "pair_auditor": _file_identity(Path(__file__), label="pair auditor"),
        "feature_audit_base": _file_identity(
            Path(audit_base.__file__), label="feature audit base"
        ),
        "matched_core": _file_identity(Path(core.__file__), label="matched core"),
        "frozen_primitive": _file_identity(
            Path(core.primitive.__file__), label="frozen primitive"
        ),
        "uw_frontend_package_initializer": _file_identity(
            Path(core.EXPECTED_SHARED_PACKAGE_INITIALIZERS["uw_frontend"]["path"]),
            label="uw_frontend package initializer",
        ),
        "uw_frontend_quality_package_initializer": _file_identity(
            Path(
                core.EXPECTED_SHARED_PACKAGE_INITIALIZERS[
                    "uw_frontend_quality"
                ]["path"]
            ),
            label="uw_frontend.quality package initializer",
        ),
        "xfeat_modules_package_initializer": _file_identity(
            matched_xfeat.XFEAT_MODULES_INITIALIZER,
            label="XFeat modules package initializer",
        ),
        "xfeat_wrapper": _file_identity(
            Path(matched_xfeat.__file__), label="matched XFeat wrapper"
        ),
        "gftt_wrapper": _file_identity(
            Path(matched_gftt.__file__), label="matched GFTT wrapper"
        ),
        "legacy_xfeat_adapter": _file_identity(
            Path(matched_xfeat.legacy_xfeat.__file__), label="legacy XFeat adapter"
        ),
        "sealed_arm_launcher": _file_identity(
            Path(sealed_launcher.__file__), label="sealed arm launcher"
        ),
    }


def _fixed_semantics(
    *, feature_topic: str, image_topic: str, allow_prefix: bool, expected_frames: int
) -> dict[str, object]:
    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )
    return {
        "manifest_schema_version": core.SCHEMA_VERSION,
        "attempt_schema_version": "aqua-fe-detector-birth-rawlk-attempt-v1",
        "feature_topic": feature_topic,
        "image_topic": image_topic,
        "allow_prefix_nonformal": bool(allow_prefix),
        "expected_published_frames": expected_frames,
        "expected_raw_frames": expected_raw_frames,
        "diagnostic_fields": list(core.DIAGNOSTIC_FIELDS),
        "common_diagnostic_fields": list(COMMON_DIAGNOSTIC_FIELDS),
        "expected_arms": EXPECTED_ARMS,
    }


def _auditor_argv(
    *,
    action: str,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    arm_paths: Mapping[str, Mapping[str, Path]],
    audit_paths: Mapping[str, Path],
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
) -> list[str]:
    argv = [
        "/usr/bin/python3.8", "-B", "-m",
        "scripts.audit_matched_birth_rawlk_pair_v1",
        "--action", action,
        "--source-feature-bag", str(source_bag),
        "--raw-image-bag", str(raw_bag),
        "--camera-yaml", str(camera_yaml),
        "--freeze-json", str(freeze_json),
        "--xfeat-bag", str(arm_paths[XFEAT_ARM]["feature_bag"]),
        "--xfeat-manifest", str(arm_paths[XFEAT_ARM]["manifest_json"]),
        "--xfeat-diagnostics", str(arm_paths[XFEAT_ARM]["diagnostics_csv"]),
        "--xfeat-legacy-manifest", str(arm_paths[XFEAT_ARM]["legacy_primitive_manifest"]),
        "--xfeat-work-directory", str(arm_paths[XFEAT_ARM]["private_work_directory"]),
        "--xfeat-attempt", str(arm_paths[XFEAT_ARM]["attempt_json"]),
        "--gftt-bag", str(arm_paths[GFTT_ARM]["feature_bag"]),
        "--gftt-manifest", str(arm_paths[GFTT_ARM]["manifest_json"]),
        "--gftt-diagnostics", str(arm_paths[GFTT_ARM]["diagnostics_csv"]),
        "--gftt-legacy-manifest", str(arm_paths[GFTT_ARM]["legacy_primitive_manifest"]),
        "--gftt-work-directory", str(arm_paths[GFTT_ARM]["private_work_directory"]),
        "--gftt-attempt", str(arm_paths[GFTT_ARM]["attempt_json"]),
        "--feature-topic", feature_topic,
        "--image-topic", image_topic,
    ]
    if allow_prefix:
        argv.append("--allow-prefix")
    argv.extend([
        "--expected-published-frames", str(expected_frames),
        "--pre-run-start-receipt", str(audit_paths["pre_run_start_receipt"]),
        "--post-run-audit-json", str(audit_paths["post_run_pair_seal"]),
    ])
    return argv


def _validate_governance_contract(
    freeze: Mapping[str, object],
    *,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    arm_paths: Mapping[str, Mapping[str, Path]],
    audit_paths: Mapping[str, Path],
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    in_memory_command_contracts: Mapping[str, Mapping[str, object]] | None = None,
    historical_builder_record_only: bool = False,
) -> dict[str, object]:
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    expected_builder_path = (
        WORKSPACE_ROOT / "scripts/build_matched_birth_rawlk_pair_freeze_v1.py"
    ).resolve(strict=True)
    if not historical_builder_record_only:
        builder = _validate_identity_claim(
            freeze["freeze_builder_identity"], label="freeze.freeze_builder_identity"
        )
    else:
        builder = dict(
            _require_exact_keys(
                freeze["freeze_builder_identity"], IDENTITY_KEYS,
                label="historical freeze builder identity",
            )
        )
        if (
            type(builder["path"]) is not str
            or type(builder["size_bytes"]) is not int
            or builder["size_bytes"] < 0
            or type(builder["sha256"]) is not str
            or not _SHA256_RE.fullmatch(builder["sha256"])
        ):
            raise AuditFailure("historical freeze builder recorded identity malformed")
    if builder["path"] != str(expected_builder_path):
        raise AuditFailure(
            "historical freeze builder path drift"
            if historical_builder_record_only
            else "freeze builder identity is not the exact live builder"
        )
    commands = _require_exact_keys(
        freeze["authoritative_commands"],
        {"check_start", "arms", "post_run_audit"},
        label="freeze.authoritative_commands",
    )
    expected_audit_common = {
        "working_directory": str(WORKSPACE_ROOT),
        "environment": dict(sealed_launcher.FROZEN_ENVIRONMENT),
    }
    for role, action in (("check_start", "check-start"), ("post_run_audit", "audit")):
        expected = {
            **expected_audit_common,
            "argv": _auditor_argv(
                action=action,
                freeze_json=freeze_json,
                source_bag=source_bag,
                raw_bag=raw_bag,
                camera_yaml=camera_yaml,
                arm_paths=arm_paths,
                audit_paths=audit_paths,
                feature_topic=feature_topic,
                image_topic=image_topic,
                allow_prefix=allow_prefix,
                expected_frames=expected_frames,
            ),
        }
        _strict_equal(commands[role], expected, label=f"freeze.command.{role}")
    arm_commands = _require_exact_keys(
        commands["arms"], set(EXPECTED_ARMS), label="freeze.authoritative_commands.arms"
    )
    validated_contracts: dict[str, dict[str, object]] = {}
    for arm_id, value in arm_commands.items():
        command = _require_exact_keys(
            value,
            {
                "working_directory", "environment", "command_contract",
                "launcher_argv", "launcher_start_receipt", "launcher_rc_receipt",
            },
            label=f"freeze.authoritative_commands.arms.{arm_id}",
        )
        if command["working_directory"] != str(WORKSPACE_ROOT):
            raise AuditFailure(f"freeze {arm_id} launcher working directory drift")
        _strict_equal(
            command["environment"], sealed_launcher.FROZEN_ENVIRONMENT,
            label=f"freeze {arm_id} launcher environment",
        )
        if in_memory_command_contracts is None:
            contract_identity = _validate_identity_claim(
                command["command_contract"],
                label=f"freeze {arm_id} command contract",
            )
            contract = _load_canonical_object(
                Path(contract_identity["path"]), label=f"{arm_id} command contract"
            )
        else:
            contract = dict(in_memory_command_contracts[arm_id])
            encoded_contract = _canonical_bytes(contract)
            contract_identity = {
                "path": command["command_contract"]["path"],
                "size_bytes": len(encoded_contract),
                "sha256": hashlib.sha256(encoded_contract).hexdigest(),
            }
            _strict_equal(
                command["command_contract"], contract_identity,
                label=f"freeze {arm_id} in-memory command identity",
            )
        start_path = Path(command["launcher_start_receipt"])
        rc_path = Path(command["launcher_rc_receipt"])
        frozen_paths = freeze["arms"][arm_id]["paths"]
        producer_values = {
            "--source-feature-bag": freeze["locked_inputs"]["source_feature_bag"]["path"],
            "--raw-image-bag": freeze["locked_inputs"]["raw_image_bag"]["path"],
            "--camera-yaml": freeze["locked_inputs"]["camera_yaml"]["path"],
            "--output-bag": frozen_paths["feature_bag"],
            "--image-topic": image_topic,
            "--feature-topic": feature_topic,
            "--manifest-json": frozen_paths["manifest_json"],
            "--diagnostics-csv": frozen_paths["diagnostics_csv"],
            "--legacy-manifest-json": frozen_paths["legacy_primitive_manifest"],
            "--work-directory": frozen_paths["private_work_directory"],
            "--attempt-json": frozen_paths["attempt_json"],
        }
        if allow_prefix:
            producer_values[sealed_launcher.OPTIONAL_LIMIT] = str(expected_frames)
        expected_contract = sealed_launcher.build_command_contract(
            arm_id,
            producer_values,
            start_receipt=start_path,
            rc_receipt=rc_path,
        )
        _strict_equal(contract, expected_contract, label=f"freeze {arm_id} rebuilt command")
        validated_contracts[arm_id] = copy.deepcopy(contract)
        expected_launcher_argv = [
            "/usr/bin/python3.8", "-B", "-m",
            "scripts.run_matched_birth_arm_once_v1",
            "--start-receipt", str(start_path),
            "--rc-receipt", str(rc_path),
            "--command-contract-json", contract_identity["path"],
        ]
        _strict_equal(
            command["launcher_argv"], expected_launcher_argv,
            label=f"freeze {arm_id} launcher argv",
        )
    receipt = _require_exact_keys(
        freeze["launcher_receipt_contract"],
        {"command_contract_schema", "start_receipt_schema", "rc_receipt_schema", "launcher_identity", "supervision"},
        label="freeze.launcher_receipt_contract",
    )
    if (
        type(receipt["command_contract_schema"]) is not str
        or receipt["command_contract_schema"]
        != sealed_launcher.COMMAND_CONTRACT_SCHEMA
        or type(receipt["start_receipt_schema"]) is not str
        or receipt["start_receipt_schema"] != sealed_launcher.START_RECEIPT_SCHEMA
        or type(receipt["rc_receipt_schema"]) is not str
        or receipt["rc_receipt_schema"] != sealed_launcher.RC_RECEIPT_SCHEMA
    ):
        raise AuditFailure("freeze launcher receipt contract mismatch")
    _strict_equal(
        receipt["supervision"],
        sealed_launcher.EXPECTED_SUPERVISION,
        label="freeze.launcher_receipt_contract.supervision",
    )
    launcher_identity = _validate_identity_claim(
        receipt["launcher_identity"], label="freeze launcher"
    )
    _strict_equal(
        launcher_identity,
        _file_identity(Path(sealed_launcher.__file__), label="live sealed launcher"),
        label="freeze launcher exact live identity",
    )
    return {
        "commands": commands,
        "launcher_identity": launcher_identity,
        "launcher_receipt_paths": sorted(
            str(commands["arms"][arm][key])
            for arm in EXPECTED_ARMS
            for key in ("launcher_start_receipt", "launcher_rc_receipt")
        ),
        "command_contract_identities": {
            arm: commands["arms"][arm]["command_contract"] for arm in EXPECTED_ARMS
        },
        "command_contracts": validated_contracts,
    }


def _validate_identity_claim(claim: object, *, label: str) -> dict[str, object]:
    mapping = _require_exact_keys(claim, IDENTITY_KEYS, label=label)
    path_value = mapping["path"]
    if type(path_value) is not str or not path_value:
        raise AuditFailure(f"{label}.path must be a nonempty string")
    if type(mapping["size_bytes"]) is not int or mapping["size_bytes"] < 0:
        raise AuditFailure(f"{label}.size_bytes must be a nonnegative integer")
    if type(mapping["sha256"]) is not str or not _SHA256_RE.fullmatch(mapping["sha256"]):
        raise AuditFailure(f"{label}.sha256 is malformed")
    lexical_alias = XFEAT_LEXICAL_IDENTITY_ALIASES.get(label)
    if lexical_alias is not None:
        expected_lexical, expected_canonical = lexical_alias
        if path_value != str(expected_lexical):
            raise AuditFailure(f"{label}.path is not the frozen lexical XFeat path")
        if Path(path_value).resolve(strict=True) != expected_canonical:
            raise AuditFailure(f"{label}.path does not resolve to the pinned XFeat target")
        live = _file_identity(expected_canonical, label=label)
        if (
            mapping["size_bytes"] != live["size_bytes"]
            or mapping["sha256"] != live["sha256"]
        ):
            raise AuditFailure(f"{label} lexical alias bytes mismatch")
    else:
        live = _file_identity(Path(path_value), label=label)
        _strict_equal(mapping, live, label=f"{label}:live_identity")
    return dict(mapping)


def _validate_nested_identity_claims(value: object, *, label: str) -> None:
    if type(value) is dict:
        if set(value) == set(IDENTITY_KEYS):
            _validate_identity_claim(value, label=label)
            return
        for key, child in value.items():
            _validate_nested_identity_claims(child, label=f"{label}.{key}")
    elif type(value) is list:
        for index, child in enumerate(value):
            _validate_nested_identity_claims(child, label=f"{label}[{index}]")


def _dynamic_rule(marker: object, *, pointer: str) -> Mapping[str, object]:
    container = _require_exact_keys(marker, {TEMPLATE_MARKER_KEY}, label=f"template{pointer}")
    rule = container[TEMPLATE_MARKER_KEY]
    if (
        type(rule) is not dict
        or not set(rule).issubset(DYNAMIC_RULE_KEYS)
        or "binding" not in rule
        or (("type" in rule) == ("types" in rule))
    ):
        raise AuditFailure(f"dynamic rule keyset invalid at {pointer}")
    if "type" in rule:
        if rule["type"] not in DYNAMIC_TYPES:
            raise AuditFailure(f"dynamic scalar type invalid at {pointer}")
    else:
        if rule["types"] != ["float", "null"]:
            raise AuditFailure(f"dynamic scalar union invalid at {pointer}")
        nullable_diagnostic = bool(
            re.fullmatch(
                r"/raw_frame_diagnostics/(?:0|[1-9][0-9]*)/"
                r"(?:fb_median_px|fb_p95_px|ncc_median)",
                pointer,
            )
        )
        nullable_timing = bool(
            re.fullmatch(
                r"/code_artifacts/detector_runtime/runtime/detect_ms/"
                r"(?:warmup|steady_state|all)/(?:median_ms|p90_ms)",
                pointer,
            )
        )
        if not (nullable_diagnostic or nullable_timing):
            raise AuditFailure(f"nullable dynamic scalar is not permitted at {pointer}")
    for bound in ("minimum", "maximum"):
        if bound in rule and (
            type(rule[bound]) not in (int, float)
            or isinstance(rule[bound], bool)
            or not math.isfinite(float(rule[bound]))
        ):
            raise AuditFailure(f"dynamic {bound} invalid at {pointer}")
    if "minimum" in rule and "maximum" in rule and rule["minimum"] > rule["maximum"]:
        raise AuditFailure(f"dynamic range inverted at {pointer}")
    if "pattern" in rule:
        if type(rule["pattern"]) is not str:
            raise AuditFailure(f"dynamic pattern invalid at {pointer}")
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            raise AuditFailure(f"dynamic pattern malformed at {pointer}") from exc
    if "binding" in rule and rule["binding"] not in KNOWN_DYNAMIC_BINDINGS:
        raise AuditFailure(f"unknown dynamic binding at {pointer}")
    _validate_dynamic_binding_pointer(rule, pointer=pointer)
    return rule


def _validate_dynamic_binding_pointer(
    rule: Mapping[str, object], *, pointer: str
) -> None:
    binding = rule.get("binding")
    allowed = False
    if binding == "live_attempt_size":
        allowed = pointer == "/attempt/identity/size_bytes"
    elif binding == "live_attempt_sha256":
        allowed = pointer == "/attempt/identity/sha256"
    elif binding == "live_feature_bag_size":
        allowed = pointer in {
            "/outputs/feature_bag/size_bytes",
            "/legacy_prepublication_rebind/"
            "primitive_reported_output_identity_after_path_rebind/size_bytes",
            "/legacy_prepublication_rebind/"
            "published_feature_bag_identity/size_bytes",
        }
    elif binding == "live_feature_bag_sha256":
        allowed = pointer in {
            "/outputs/feature_bag/sha256",
            "/legacy_prepublication_rebind/"
            "primitive_reported_output_identity_after_path_rebind/sha256",
            "/legacy_prepublication_rebind/"
            "published_feature_bag_identity/sha256",
        }
    elif binding == "live_diagnostics_size":
        allowed = pointer == "/outputs/raw_diagnostics_csv/size_bytes"
    elif binding == "live_diagnostics_sha256":
        allowed = pointer == "/outputs/raw_diagnostics_csv/sha256"
    elif binding == "live_legacy_manifest_size":
        allowed = pointer == "/outputs/legacy_primitive_manifest/size_bytes"
    elif binding == "live_legacy_manifest_sha256":
        allowed = pointer == "/outputs/legacy_primitive_manifest/sha256"
    elif binding == "elapsed_wall_ms":
        allowed = pointer == "/runtime/elapsed_wall_ms"
    elif binding == "metric_outcome":
        allowed = pointer.startswith("/metrics/") and pointer.rsplit("/", 1)[-1] in METRIC_DYNAMIC_LEAVES
    elif binding == "diagnostic_outcome":
        parts = pointer.split("/")
        allowed = bool(
            len(parts) == 4
            and parts[1] == "raw_frame_diagnostics"
            and parts[2].isdigit()
            and 0 <= int(parts[2]) < EXPECTED_RAW_FRAMES
            and parts[3] in PAIR_ALLOWED_RAW_OUTCOME_FIELDS
        )
    elif binding == "detector_runtime_outcome":
        base = "/code_artifacts/detector_runtime/runtime/"
        suffix = pointer[len(base) :] if pointer.startswith(base) else ""
        allowed = suffix in {"detect_calls", "candidate_total"} or suffix.startswith(
            "detect_ms/"
        )
    if not allowed:
        raise AuditFailure(
            f"dynamic binding {binding!r} is not permitted at fixed pointer {pointer}"
        )


def _template_dynamic_paths(
    template: object, path: tuple[object, ...] = ()
) -> list[str]:
    if type(template) is dict and set(template) == {TEMPLATE_MARKER_KEY}:
        pointer = _json_pointer(path)
        _dynamic_rule(template, pointer=pointer)
        return [pointer]
    if type(template) is dict:
        result: list[str] = []
        for key in sorted(template):
            result.extend(_template_dynamic_paths(template[key], path + (key,)))
        return result
    if type(template) is list:
        result = []
        for index, item in enumerate(template):
            result.extend(_template_dynamic_paths(item, path + (index,)))
        return result
    return []


def _validate_dynamic_value(actual: object, rule: Mapping[str, object], *, pointer: str) -> None:
    expected_types = [rule["type"]] if "type" in rule else list(rule["types"])
    type_ok = any(
        {
            "bool": type(actual) is bool,
            "int": type(actual) is int,
            "float": type(actual) is float and math.isfinite(actual),
            "string": type(actual) is str,
            "null": actual is None,
        }[expected_type]
        for expected_type in expected_types
    )
    if not type_ok:
        raise AuditFailure(
            f"dynamic value at {pointer} has type {type(actual).__name__}, "
            f"expected one of {expected_types}"
        )
    if type(actual) in (int, float) and not isinstance(actual, bool):
        if "minimum" in rule and actual < rule["minimum"]:
            raise AuditFailure(f"dynamic value below minimum at {pointer}")
        if "maximum" in rule and actual > rule["maximum"]:
            raise AuditFailure(f"dynamic value above maximum at {pointer}")
    if "pattern" in rule and re.fullmatch(rule["pattern"], actual) is None:
        raise AuditFailure(f"dynamic string pattern mismatch at {pointer}")


def _match_manifest_template(
    actual: object,
    template: object,
    *,
    path: tuple[object, ...] = (),
) -> list[str]:
    pointer = _json_pointer(path)
    if type(template) is dict and set(template) == {TEMPLATE_MARKER_KEY}:
        _validate_dynamic_value(actual, _dynamic_rule(template, pointer=pointer), pointer=pointer)
        return [pointer]
    if type(actual) is not type(template):
        raise AuditFailure(f"manifest/template type mismatch at {pointer}")
    if type(template) is dict:
        if set(actual) != set(template):
            raise AuditFailure(
                f"manifest/template keyset mismatch at {pointer}: "
                f"missing={sorted(set(template)-set(actual))} extra={sorted(set(actual)-set(template))}"
            )
        result: list[str] = []
        for key in sorted(template):
            result.extend(
                _match_manifest_template(actual[key], template[key], path=path + (key,))
            )
        return result
    if type(template) is list:
        if len(actual) != len(template):
            raise AuditFailure(f"manifest/template list length mismatch at {pointer}")
        result = []
        for index, item in enumerate(template):
            result.extend(
                _match_manifest_template(actual[index], item, path=path + (index,))
            )
        return result
    if actual != template:
        raise AuditFailure(f"manifest/template fixed leaf mismatch at {pointer}")
    return []


def _validate_freeze(
    freeze: Mapping[str, object],
    *,
    freeze_json: Path,
    runtime: Mapping[str, object],
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    arm_paths: Mapping[str, Mapping[str, Path]],
    audit_paths: Mapping[str, Path],
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    in_memory_command_contracts: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    _require_exact_keys(freeze, FREEZE_TOP_KEYS, label="freeze")
    if feature_topic != FEATURE_TOPIC_DEFAULT:
        raise AuditFailure("feature topic differs from frozen consumer contract")
    if image_topic != "/camera/image_raw":
        raise AuditFailure("image topic differs from frozen A02 contract")
    if freeze["schema_version"] != FREEZE_SCHEMA_VERSION:
        raise AuditFailure("freeze schema mismatch")
    if freeze["status"] != "FROZEN" or freeze["scientific_role"] != (
        "post_result_development_exploratory_detector_birth_ablation"
    ):
        raise AuditFailure("freeze status/scientific role mismatch")
    incident_gate = _validate_infrastructure_incident()
    _strict_equal(
        freeze["infrastructure_incident"],
        incident_gate["identity"],
        label="freeze.infrastructure_incident",
    )
    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )
    _strict_equal(
        freeze["fixed_semantics"],
        _fixed_semantics(
            feature_topic=feature_topic,
            image_topic=image_topic,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        ),
        label="freeze.fixed_semantics",
    )
    live_closure = _audit_code_closure()
    _strict_equal(
        freeze["auditor_identity"],
        live_closure["pair_auditor"],
        label="freeze.auditor_identity",
    )
    _strict_equal(
        freeze["audit_code_closure"],
        live_closure,
        label="freeze.audit_code_closure",
    )
    _strict_equal(freeze["audit_runtime"], runtime, label="freeze.audit_runtime")
    core_runtime = runtime.get("core_runtime")
    if (
        type(core_runtime) is not dict
        or runtime.get("pycache_prefix") != str(sealed_launcher.PYCACHE_PREFIX)
        or core_runtime.get("pycache_prefix")
        != str(sealed_launcher.PYCACHE_PREFIX)
    ):
        raise AuditFailure("freeze audit runtime pycache prefix drift")
    publication_contract = _require_exact_keys(
        freeze["publication_contract"],
        {
            "commit_marker_role",
            "freeze_published_last",
            "orphan_contracts_non_authoritative",
            "result_outcomes_read",
            "producer_started",
        },
        label="freeze.publication_contract",
    )
    _strict_equal(
        publication_contract,
        {
            "commit_marker_role": "freeze",
            "freeze_published_last": True,
            "orphan_contracts_non_authoritative": True,
            "result_outcomes_read": False,
            "producer_started": False,
        },
        label="freeze.publication_contract",
    )
    governance = _validate_governance_contract(
        freeze,
        freeze_json=freeze_json,
        source_bag=source_bag,
        raw_bag=raw_bag,
        camera_yaml=camera_yaml,
        arm_paths=arm_paths,
        audit_paths=audit_paths,
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        in_memory_command_contracts=in_memory_command_contracts,
    )
    locked_inputs = _require_exact_keys(
        freeze["locked_inputs"],
        {"source_feature_bag", "raw_image_bag", "camera_yaml"},
        label="freeze.locked_inputs",
    )
    live_inputs = {
        "source_feature_bag": _file_identity(source_bag, label="source bag"),
        "raw_image_bag": _file_identity(raw_bag, label="raw bag"),
        "camera_yaml": _file_identity(camera_yaml, label="camera YAML"),
    }
    _strict_equal(locked_inputs, live_inputs, label="freeze.locked_inputs:live")
    expected_audit_paths = {
        key: str(value.expanduser().resolve(strict=False))
        for key, value in audit_paths.items()
    }
    _strict_equal(
        freeze["audit_paths"],
        expected_audit_paths,
        label="freeze.audit_paths:cli",
    )
    if set(expected_audit_paths) != {"pre_run_start_receipt", "post_run_pair_seal"}:
        raise AuditFailure("audit path role keyset mismatch")
    if len(set(expected_audit_paths.values())) != 2:
        raise AuditFailure("pre-run start receipt and post-run seal paths alias")
    common = freeze["expected_common_contract"]
    if type(common) is not dict:
        raise AuditFailure("freeze.expected_common_contract must be an object")
    if freeze["expected_common_contract_sha256"] != core._canonical_sha256(common):
        raise AuditFailure("freeze expected common-contract SHA mismatch")
    live_common = core.common_contract(strict_runtime=True)
    _strict_equal(
        common,
        live_common,
        label="freeze.expected_common_contract:live",
    )
    common_runtime = common.get("runtime") if type(common) is dict else None
    if (
        type(common_runtime) is not dict
        or common_runtime.get("pycache_prefix") != str(sealed_launcher.PYCACHE_PREFIX)
    ):
        raise AuditFailure("freeze common runtime pycache prefix drift")
    _strict_equal(
        core_runtime,
        common_runtime,
        label="freeze audit/common core runtime cross-binding",
    )
    common_rows, reconstruction = _reconstruct_common_diagnostics(
        source_bag=source_bag,
        raw_bag=raw_bag,
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    _camera_matrix, _distortion, camera_model = core.primitive.load_camera_model(
        camera_yaml
    )
    nonfeature_stream = core._call_trusted_rosbag_scoped(
        core.primitive._nonfeature_digest,
        source_bag,
        feature_topic,
        reconstruction["cutoff_feature_record_stamp_ns"],
    )
    arms = _require_exact_keys(freeze["arms"], set(EXPECTED_ARMS), label="freeze.arms")
    all_paths: list[str] = []
    for arm_id in (XFEAT_ARM, GFTT_ARM):
        arm = _require_exact_keys(arms[arm_id], FREEZE_ARM_KEYS, label=f"freeze.arms.{arm_id}")
        paths = _require_exact_keys(
            arm["paths"], FREEZE_PATH_KEYS, label=f"freeze.arms.{arm_id}.paths"
        )
        expected_paths = {
            key: str(value.expanduser().resolve(strict=False))
            for key, value in arm_paths[arm_id].items()
        }
        _strict_equal(paths, expected_paths, label=f"freeze.arms.{arm_id}.paths:cli")
        all_paths.extend(expected_paths.values())
        if arm["pre_run_required_absent"] is not True:
            raise AuditFailure(f"freeze {arm_id} does not attest all four paths absent pre-run")
        if type(arm["manifest_template"]) is not dict or type(arm["attempt"]) is not dict:
            raise AuditFailure(f"freeze {arm_id} manifest template/attempt must be objects")
        if arm["manifest_template_sha256"] != core._canonical_sha256(arm["manifest_template"]):
            raise AuditFailure(f"freeze {arm_id} manifest template hash mismatch")
        dynamic_paths = _template_dynamic_paths(arm["manifest_template"])
        mandatory_rules = _mandatory_dynamic_rules(
            arm_id,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        )
        if (
            type(arm["dynamic_scalar_paths"]) is not list
            or arm["dynamic_scalar_paths"] != sorted(mandatory_rules)
            or sorted(set(dynamic_paths)) != sorted(mandatory_rules)
        ):
            raise AuditFailure(f"freeze {arm_id} dynamic scalar path list mismatch")
        for pointer, rule in mandatory_rules.items():
            _strict_equal(
                _pointer_value(arm["manifest_template"], pointer),
                rule,
                label=f"freeze {arm_id} mandatory dynamic rule {pointer}",
            )
        _require_exact_keys(arm["manifest_template"], MANIFEST_TOP_KEYS, label=f"freeze {arm_id} manifest template")
        expected_symbolic = _symbolic_manifest_expected(
            arm_id=arm_id,
            paths=paths,
            expected_attempt=arm["attempt"],
            locked_inputs=locked_inputs,
            expected_common=common,
            feature_topic=feature_topic,
            image_topic=image_topic,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
            common_rows=common_rows,
            reconstruction=reconstruction,
            camera_normalization_model=camera_model,
            nonfeature_stream=nonfeature_stream,
        )
        _validate_manifest_template_symbolic(
            arm["manifest_template"],
            arm_id=arm_id,
            paths=paths,
            expected_attempt=arm["attempt"],
            locked_inputs=locked_inputs,
            expected_common=common,
            feature_topic=feature_topic,
            image_topic=image_topic,
            expected_frames=expected_frames,
            allow_prefix=allow_prefix,
            expected_symbolic=expected_symbolic,
        )
        _strict_equal(
            arm["manifest_template"]["arm_contract"],
            EXPECTED_ARM_CONTRACTS[arm_id],
            label=f"freeze {arm_id} arm contract",
        )
        if arm["manifest_template"]["arm_contract_sha256"] != core._canonical_sha256(
            EXPECTED_ARM_CONTRACTS[arm_id]
        ):
            raise AuditFailure(f"freeze {arm_id} arm contract hash mismatch")
        _strict_equal(
            arm["manifest_template"]["common_contract"],
            common,
            label=f"freeze {arm_id} common contract",
        )
        if arm["manifest_template"]["common_contract_sha256"] != core._canonical_sha256(common):
            raise AuditFailure(f"freeze {arm_id} common contract hash mismatch")
        _require_exact_keys(arm["attempt"], ATTEMPT_KEYS, label=f"freeze {arm_id} attempt")
        _validate_attempt(
            arm["attempt"],
            arm_id=arm_id,
            paths=paths,
            locked_inputs=locked_inputs,
            allow_prefix=allow_prefix,
        )
    _validate_continuation_scientific_projection(
        freeze,
        incident_gate=incident_gate,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        candidate_command_contracts=governance["command_contracts"],
    )
    if len(all_paths) != len(set(all_paths)):
        raise AuditFailure("freeze arm artifact paths alias each other")
    input_paths = {str(path.resolve(strict=True)) for path in (source_bag, raw_bag, camera_yaml)}
    if len(input_paths) != 3:
        raise AuditFailure("freeze locked input paths alias each other")
    if input_paths & set(all_paths):
        raise AuditFailure("freeze output path aliases a locked input")
    if set(expected_audit_paths.values()) & (set(all_paths) | input_paths):
        raise AuditFailure("freeze audit receipt path aliases an artifact or locked input")
    launcher_receipts = governance["launcher_receipt_paths"]
    contract_paths = [
        identity["path"]
        for identity in governance["command_contract_identities"].values()
    ]
    reserved_union = all_paths + list(expected_audit_paths.values()) + launcher_receipts
    if len(reserved_union) != len(set(reserved_union)):
        raise AuditFailure("freeze producer/audit/launcher reserved paths alias")
    if set(launcher_receipts) & (input_paths | set(contract_paths)):
        raise AuditFailure("freeze launcher receipt aliases input/command contract")
    if set(contract_paths) & (input_paths | set(all_paths) | set(expected_audit_paths.values())):
        raise AuditFailure("freeze command contract aliases governed artifacts")
    governed_paths = [
        freeze_json,
        *(Path(path) for path in all_paths),
        *(Path(path) for path in expected_audit_paths.values()),
        *(Path(path) for path in contract_paths),
        *(Path(path) for path in launcher_receipts),
    ]
    if len(governed_paths) != 21 or len({str(path) for path in governed_paths}) != 21:
        raise AuditFailure("freeze governed r2 filesystem path set is not exact 21")
    live_filesystem = _artifact_filesystem_envelope(governed_paths)
    _strict_equal(
        freeze["artifact_filesystem_contract"],
        live_filesystem,
        label="freeze.artifact_filesystem_contract:live",
    )
    if (
        live_filesystem["static_contract"]["namespace_root"]
        != incident_gate["authorized_namespace_root"]
    ):
        raise AuditFailure("freeze r2 filesystem root is not incident-authorized")
    allowed = freeze["allowed_pair_scalar_differences"]
    if (
        type(allowed) is not list
        or any(type(item) is not str or not item.startswith("/") for item in allowed)
        or allowed != sorted(set(allowed))
    ):
        raise AuditFailure("freeze recursive scalar allowlist is not sorted/exact")
    forbidden = [item for item in allowed if not _pair_difference_path_allowed(item)]
    if forbidden:
        raise AuditFailure(f"freeze scalar allowlist contains forbidden paths: {forbidden[:8]}")
    required = freeze["required_pair_scalar_differences"]
    if (
        type(required) is not list
        or any(type(item) is not str or not item.startswith("/") for item in required)
        or required != sorted(set(required))
        or not set(required).issubset(allowed)
    ):
        raise AuditFailure("freeze required recursive scalar differences invalid")
    if required != sorted(MANDATORY_PAIR_DIFFERENCES):
        raise AuditFailure(
            "freeze required detector/provenance differences are not code-exact"
        )
    template_observed = set(
        _pair_scalar_differences(
            arms[XFEAT_ARM]["manifest_template"],
            arms[GFTT_ARM]["manifest_template"],
        )
    )
    expected_allowed = sorted(
        template_observed
        | set(arms[XFEAT_ARM]["dynamic_scalar_paths"])
        | set(arms[GFTT_ARM]["dynamic_scalar_paths"])
    )
    if allowed != expected_allowed:
        raise AuditFailure(
            "freeze scalar allowlist is not the code-authoritative union of "
            "static and mandatory dynamic leaves"
        )
    missing_static = sorted(set(required) - template_observed)
    if missing_static:
        raise AuditFailure(
            "freeze templates omit mandatory static detector/namespace differences: "
            f"{missing_static[:12]}"
        )
    unexpected_template = sorted(template_observed - set(allowed))
    if unexpected_template:
        raise AuditFailure(
            "freeze templates contain unallowed recursive differences: "
            f"{unexpected_template[:12]}"
        )
    _strict_equal(
        _audit_runtime_observation(),
        runtime,
        label="freeze audit runtime after locked-bag reconstruction",
    )
    return {
        "locked_inputs": live_inputs,
        "common_contract": common,
        "arms": arms,
        "allowed_pair_scalar_differences": allowed,
        "required_pair_scalar_differences": required,
        "governance": governance,
        "audit_paths": expected_audit_paths,
        "infrastructure_incident": incident_gate["identity"],
        "artifact_filesystem_contract": live_filesystem,
    }


def _pre_run_start_receipt_payload(
    *,
    freeze_json: Path,
    gate: Mapping[str, object],
    arm_paths: Mapping[str, Mapping[str, Path]],
) -> dict[str, object]:
    """Build the one canonical receipt later required byte-for-byte by audit."""

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PRE_RUN_FREEZE_AND_ABSENCE",
        "pass": True,
        "scientific_role": (
            "post_result_development_exploratory_detector_birth_ablation"
        ),
        "pre_run_freeze": _file_identity(freeze_json, label="pre-run freeze"),
        "audit_code_closure": _audit_code_closure(),
        "locked_inputs": gate["locked_inputs"],
        "infrastructure_incident": gate["infrastructure_incident"],
        "artifact_filesystem_contract": gate["artifact_filesystem_contract"],
        "reserved_paths_absent": sorted(
            {
                str(path.expanduser().resolve(strict=False))
                for paths in arm_paths.values()
                for path in paths.values()
            }
            | set(gate["governance"]["launcher_receipt_paths"])
            | {gate["audit_paths"]["post_run_pair_seal"]}
        ),
        "claim_boundary": {
            "authorizes_exactly_one_attempt_per_arm": True,
            "does_not_contain_result_outcomes": True,
            "post_run_pair_audit_still_required": True,
        },
    }


def _validate_launcher_receipts(
    gate: Mapping[str, object],
    *,
    in_memory_receipts: Mapping[str, Mapping[str, object]] | None = None,
    in_memory_command_contracts: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Bind each successful producer to its frozen one-shot supervisor."""

    from scripts import run_matched_birth_arm_once_v1 as sealed_launcher

    result: dict[str, object] = {}
    commands = gate["governance"]["commands"]["arms"]
    for arm_id in (XFEAT_ARM, GFTT_ARM):
        command = commands[arm_id]
        start_path = Path(command["launcher_start_receipt"])
        rc_path = Path(command["launcher_rc_receipt"])
        memory = None if in_memory_receipts is None else in_memory_receipts[arm_id]
        start = (
            _load_canonical_object(start_path, label=f"{arm_id} launcher start receipt")
            if memory is None else dict(memory["start"])
        )
        _require_exact_keys(
            start,
            {
                "schema_version", "status", "attempt_count",
                "launcher_parent_pid", "launcher_process_start_count",
                "reserved_producer_process_start_count",
                "producer_process_started_at_receipt", "no_retry",
                "no_deletion", "requested_launcher_argv",
                "requested_start_receipt", "requested_rc_receipt",
                "launcher_invocation", "receipt_created_unix_time_ns",
            },
            label=f"{arm_id}.launcher_start",
        )
        expected_start = {
            "schema_version": sealed_launcher.START_RECEIPT_SCHEMA,
            "status": "START_NAMESPACE_CONSUMED_PREVALIDATION",
            "attempt_count": 1,
            "launcher_process_start_count": 1,
            "reserved_producer_process_start_count": 1,
            "producer_process_started_at_receipt": False,
            "no_retry": True,
            "no_deletion": True,
            "requested_launcher_argv": command["launcher_argv"][4:],
            "requested_start_receipt": str(start_path),
            "requested_rc_receipt": str(rc_path),
        }
        for key, expected in expected_start.items():
            _strict_equal(start[key], expected, label=f"{arm_id}.launcher_start.{key}")
        for key in ("launcher_parent_pid", "receipt_created_unix_time_ns"):
            if type(start[key]) is not int or start[key] <= 0:
                raise AuditFailure(f"{arm_id} launcher start {key} invalid")
        invocation = _require_exact_keys(
            start["launcher_invocation"],
            {
                "process_command_line", "working_directory", "environment",
                "sys_executable", "proc_executable", "launcher_source",
            },
            label=f"{arm_id}.launcher_start.launcher_invocation",
        )
        for key, expected in {
            "process_command_line": command["launcher_argv"],
            "working_directory": str(WORKSPACE_ROOT),
            "environment": sealed_launcher.FROZEN_ENVIRONMENT,
            "sys_executable": "/usr/bin/python3.8",
            "proc_executable": _file_identity(
                Path("/usr/bin/python3.8"), label="frozen Python executable"
            ),
            "launcher_source": gate["governance"]["launcher_identity"],
        }.items():
            _strict_equal(
                invocation[key], expected,
                label=f"{arm_id}.launcher_start.launcher_invocation.{key}",
            )
        start_mode = (
            stat.S_IMODE(start_path.stat().st_mode)
            if memory is None else int(memory["start_mode"])
        )
        if start_mode != 0o444:
            raise AuditFailure(f"{arm_id} launcher start receipt mode is not 0444")

        rc = (
            _load_canonical_object(rc_path, label=f"{arm_id} launcher RC receipt")
            if memory is None else dict(memory["rc"])
        )
        _require_exact_keys(
            rc,
            {
                "schema_version", "status", "arm_id", "start_receipt",
                "command_contract", "actual_execution", "producer_process",
                "pycache_contract", "timing", "launcher",
            },
            label=f"{arm_id}.launcher_rc",
        )
        for key, expected in {
            "schema_version": sealed_launcher.RC_RECEIPT_SCHEMA,
            "status": "PROCESS_ENDED",
            "arm_id": arm_id,
        }.items():
            _strict_equal(rc[key], expected, label=f"{arm_id}.launcher_rc.{key}")
        _strict_equal(
            rc["start_receipt"],
            (
                _file_identity(start_path, label=f"{arm_id} launcher start")
                if memory is None else memory["start_identity"]
            ),
            label=f"{arm_id}.launcher_rc.start_receipt",
        )
        _strict_equal(
            rc["command_contract"], command["command_contract"],
            label=f"{arm_id}.launcher_rc.command_contract",
        )
        contract = (
            _load_canonical_object(
                Path(command["command_contract"]["path"]),
                label=f"{arm_id} frozen command contract",
            )
            if in_memory_command_contracts is None
            else dict(in_memory_command_contracts[arm_id])
        )
        _strict_equal(
            rc["actual_execution"],
            {
                "argv": contract["argv"],
                "environment": contract["environment"],
                "working_directory": contract["working_directory"],
                "shell": False,
            },
            label=f"{arm_id}.launcher_rc.actual_execution",
        )
        process = _require_exact_keys(
            rc["producer_process"],
            {
                "pid", "launch_attempt_count", "process_start_count",
                "producer_return_code", "natural_end_observed",
                "exited_normally", "terminated_by_signal", "signal_number",
                "supervisor_sent_signal", "timed_out", "timeout_seconds",
                "retry_performed",
            },
            label=f"{arm_id}.launcher_rc.producer_process",
        )
        if type(process["pid"]) is not int or process["pid"] <= 0:
            raise AuditFailure(f"{arm_id} launcher child PID invalid")
        expected_process = {
            "launch_attempt_count": 1,
            "process_start_count": 1,
            "producer_return_code": 0,
            "natural_end_observed": True,
            "exited_normally": True,
            "terminated_by_signal": False,
            "signal_number": None,
            "supervisor_sent_signal": False,
            "timed_out": False,
            "timeout_seconds": None,
            "retry_performed": False,
        }
        for key, expected in expected_process.items():
            _strict_equal(process[key], expected, label=f"{arm_id}.process.{key}")
        _strict_equal(
            rc["pycache_contract"],
            {
                "prefix": str(sealed_launcher.PYCACHE_PREFIX),
                "absent_pre": True,
                "absent_post": True,
                "deleted_by_launcher": False,
            },
            label=f"{arm_id}.launcher_rc.pycache",
        )
        timing = _require_exact_keys(
            rc["timing"],
            {"child_launch_unix_time_ns", "child_end_unix_time_ns"},
            label=f"{arm_id}.launcher_rc.timing",
        )
        if (
            any(type(timing[key]) is not int or timing[key] <= 0 for key in timing)
            or timing["child_end_unix_time_ns"] < timing["child_launch_unix_time_ns"]
        ):
            raise AuditFailure(f"{arm_id} launcher timing invalid")
        launcher_record = _require_exact_keys(
            rc["launcher"],
            {"parent_pid", "source", "no_retry", "no_deletion"},
            label=f"{arm_id}.launcher_rc.launcher",
        )
        if launcher_record["parent_pid"] != start["launcher_parent_pid"]:
            raise AuditFailure(f"{arm_id} launcher parent PID cross-binding mismatch")
        _strict_equal(
            launcher_record["source"],
            gate["governance"]["launcher_identity"],
            label=f"{arm_id}.launcher_rc.launcher_source",
        )
        if launcher_record["no_retry"] is not True or launcher_record["no_deletion"] is not True:
            raise AuditFailure(f"{arm_id} launcher governance flags drift")
        rc_mode = (
            stat.S_IMODE(rc_path.stat().st_mode)
            if memory is None else int(memory["rc_mode"])
        )
        if rc_mode != 0o444:
            raise AuditFailure(f"{arm_id} launcher RC receipt mode is not 0444")
        result[arm_id] = {
            "pass": True,
            "start_receipt": (
                _file_identity(start_path, label=f"{arm_id} start")
                if memory is None else memory["start_identity"]
            ),
            "rc_receipt": (
                _file_identity(rc_path, label=f"{arm_id} RC")
                if memory is None else memory["rc_identity"]
            ),
            "producer_process_start_count": 1,
            "producer_return_code": 0,
        }
    return result


def check_pre_run_start(
    *,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    xfeat_bag: Path,
    xfeat_manifest: Path,
    xfeat_diagnostics: Path,
    xfeat_legacy_manifest: Path,
    xfeat_work_directory: Path,
    xfeat_attempt: Path,
    gftt_bag: Path,
    gftt_manifest: Path,
    gftt_diagnostics: Path,
    gftt_legacy_manifest: Path,
    gftt_work_directory: Path,
    gftt_attempt: Path,
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    pre_run_start_receipt: Path,
    post_run_pair_seal: Path,
) -> dict[str, object]:
    runtime = _audit_runtime_observation()
    freeze = _load_canonical_object(freeze_json, label="pre-run freeze")
    arm_paths = {
        XFEAT_ARM: {
            "feature_bag": xfeat_bag,
            "manifest_json": xfeat_manifest,
            "diagnostics_csv": xfeat_diagnostics,
            "legacy_primitive_manifest": xfeat_legacy_manifest,
            "private_work_directory": xfeat_work_directory,
            "attempt_json": xfeat_attempt,
        },
        GFTT_ARM: {
            "feature_bag": gftt_bag,
            "manifest_json": gftt_manifest,
            "diagnostics_csv": gftt_diagnostics,
            "legacy_primitive_manifest": gftt_legacy_manifest,
            "private_work_directory": gftt_work_directory,
            "attempt_json": gftt_attempt,
        },
    }
    gate = _validate_freeze(
        freeze,
        freeze_json=freeze_json,
        runtime=runtime,
        source_bag=source_bag,
        raw_bag=raw_bag,
        camera_yaml=camera_yaml,
        arm_paths=arm_paths,
        audit_paths={
            "pre_run_start_receipt": pre_run_start_receipt,
            "post_run_pair_seal": post_run_pair_seal,
        },
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    present = sorted(
        str(path.expanduser().resolve(strict=False))
        for paths in arm_paths.values()
        for path in paths.values()
        if os.path.lexists(path)
    )
    present.extend(
        path for path in gate["governance"]["launcher_receipt_paths"]
        if os.path.lexists(path)
    )
    present = sorted(set(present))
    if present:
        raise AuditFailure(f"pre-run reserved artifact paths are not absent: {present}")
    # The current start receipt may already be the held O_EXCL reservation in
    # main(); the post-run seal must still be absent at this stage.
    if os.path.lexists(post_run_pair_seal):
        raise AuditFailure("post-run pair seal path is not absent at start")
    return _pre_run_start_receipt_payload(
        freeze_json=freeze_json,
        gate=gate,
        arm_paths=arm_paths,
    )


def _validate_attempt(
    payload: Mapping[str, object],
    *,
    arm_id: str,
    paths: Mapping[str, str],
    locked_inputs: Mapping[str, object],
    allow_prefix: bool = False,
) -> None:
    _require_exact_keys(payload, ATTEMPT_KEYS, label=f"{arm_id}.attempt")
    expected_scalar = {
        "schema_version": "aqua-fe-detector-birth-rawlk-attempt-v1",
        "status": "ATTEMPT_CONSUMED_PROCESS_ENTERED_PRECHECK",
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "arm_id": arm_id,
        "prefix_nonformal": bool(allow_prefix),
    }
    for key, expected in expected_scalar.items():
        if type(payload[key]) is not type(expected) or payload[key] != expected:
            raise AuditFailure(f"{arm_id}.attempt.{key} mismatch")
    _strict_equal(
        payload["requested_inputs"],
        {
            "source_feature_bag": locked_inputs["source_feature_bag"]["path"],
            "raw_image_bag": locked_inputs["raw_image_bag"]["path"],
            "camera_yaml": locked_inputs["camera_yaml"]["path"],
        },
        label=f"{arm_id}.attempt.requested_inputs",
    )
    _strict_equal(
        payload["reserved_outputs"],
        {
            "feature_bag": paths["feature_bag"],
            "manifest_json": paths["manifest_json"],
            "diagnostics_csv": paths["diagnostics_csv"],
            "legacy_primitive_manifest": paths["legacy_primitive_manifest"],
            "private_work_directory": paths["private_work_directory"],
        },
        label=f"{arm_id}.attempt.reserved_outputs",
    )
    producer = _require_exact_keys(
        payload["producer"],
        {"matched_core_requested", "wrapper_requested"},
        label=f"{arm_id}.attempt.producer",
    )
    if producer["matched_core_requested"] != str(Path(core.__file__).resolve(strict=True)):
        raise AuditFailure(f"{arm_id} attempt matched-core requested path mismatch")
    if producer["wrapper_requested"] != str(EXPECTED_WRAPPERS[arm_id].resolve(strict=True)):
        raise AuditFailure(f"{arm_id} attempt wrapper requested path mismatch")


def _validate_manifest_exact(
    payload: Mapping[str, object],
    *,
    expected: Mapping[str, object],
    expected_attempt: Mapping[str, object],
    attempt_path: Path,
    arm_id: str,
    paths: Mapping[str, str],
    locked_inputs: Mapping[str, object],
    expected_common: Mapping[str, object],
    allow_prefix: bool = False,
    expected_frames: int = EXPECTED_PUBLISHED_FRAMES,
) -> None:
    _require_exact_keys(payload, MANIFEST_TOP_KEYS, label=f"{arm_id}.manifest")
    _match_manifest_template(payload, expected)
    if payload["schema_version"] != core.SCHEMA_VERSION:
        raise AuditFailure(f"{arm_id} manifest schema mismatch")
    expected_status = "PREFIX_NONFORMAL" if allow_prefix else "FULL"
    expected_eligible = not allow_prefix
    expected_reason = (
        "explicit_prefix_is_nonformal"
        if allow_prefix
        else "full_export_from_frozen_matched_cli_factory"
    )
    if (
        payload["status"] != expected_status
        or payload["formal_eligible"] is not expected_eligible
    ):
        raise AuditFailure(f"{arm_id} export mode/status mismatch")
    if payload["formal_eligibility_reason"] != expected_reason:
        raise AuditFailure(f"{arm_id} formal eligibility reason mismatch")
    if payload["scientific_role"] != (
        "post_result_development_exploratory_detector_birth_ablation"
    ):
        raise AuditFailure(f"{arm_id} scientific role mismatch")
    _strict_equal(payload["common_contract"], expected_common, label=f"{arm_id}.common_contract")
    if payload["common_contract_sha256"] != core._canonical_sha256(expected_common):
        raise AuditFailure(f"{arm_id} common contract hash mismatch")
    arm = _require_exact_keys(
        payload["arm_contract"], {"arm_id", "detector", "provenance"}, label=f"{arm_id}.arm_contract"
    )
    if arm["arm_id"] != arm_id:
        raise AuditFailure(f"{arm_id} arm identifier mismatch")
    _strict_equal(
        arm,
        EXPECTED_ARM_CONTRACTS[arm_id],
        label=f"{arm_id}.arm_contract:live_wrapper_spec",
    )
    _strict_equal(
        arm["provenance"],
        {**EXPECTED_ARMS[arm_id], "backend_inert_for_frozen_consumer": True},
        label=f"{arm_id}.provenance",
    )
    if payload["arm_contract_sha256"] != core._canonical_sha256(arm):
        raise AuditFailure(f"{arm_id} arm contract hash mismatch")
    inputs = _require_exact_keys(
        payload["inputs"],
        {
            "source_feature_bag",
            "raw_image_bag",
            "camera_yaml",
            "camera_normalization_model",
            "feature_topic",
            "image_topic",
        },
        label=f"{arm_id}.inputs",
    )
    for key in ("source_feature_bag", "raw_image_bag", "camera_yaml"):
        _strict_equal(inputs[key], locked_inputs[key], label=f"{arm_id}.inputs.{key}")
    prefix = _require_exact_keys(
        payload["prefix"],
        {
            "requested_max_published_frames",
            "source_total_published_frames",
            "selected_published_frames",
            "cutoff_feature_record_stamp_ns",
        },
        label=f"{arm_id}.prefix",
    )
    expected_requested = expected_frames if allow_prefix else None
    if prefix["requested_max_published_frames"] != expected_requested:
        raise AuditFailure(f"{arm_id} prefix request mismatch")
    if allow_prefix:
        if type(prefix["cutoff_feature_record_stamp_ns"]) is not int:
            raise AuditFailure(f"{arm_id} prefix cutoff must be an integer stamp")
    elif prefix["cutoff_feature_record_stamp_ns"] is not None:
        raise AuditFailure(f"{arm_id} formal cutoff must be null")
    if prefix["selected_published_frames"] != expected_frames:
        raise AuditFailure(f"{arm_id} selected publication count mismatch")
    attempt_container = _require_exact_keys(
        payload["attempt"], {"identity", "payload"}, label=f"{arm_id}.manifest.attempt"
    )
    attempt_live = _load_canonical_object(attempt_path, label=f"{arm_id} attempt")
    _strict_equal(attempt_live, expected_attempt, label=f"{arm_id}.attempt:freeze")
    _strict_equal(attempt_container["payload"], attempt_live, label=f"{arm_id}.attempt:manifest")
    _strict_equal(
        attempt_container["identity"],
        _file_identity(attempt_path, label=f"{arm_id} attempt"),
        label=f"{arm_id}.attempt.identity",
    )
    if stat.S_IMODE(attempt_path.stat().st_mode) != 0o444:
        raise AuditFailure(f"{arm_id} attempt file mode is not immutable 0444")
    _validate_attempt(
        attempt_live,
        arm_id=arm_id,
        paths=paths,
        locked_inputs=locked_inputs,
        allow_prefix=allow_prefix,
    )
    outputs = _require_exact_keys(
        payload["outputs"],
        {"feature_bag", "raw_diagnostics_csv", "legacy_primitive_manifest"},
        label=f"{arm_id}.outputs",
    )
    _strict_equal(
        outputs["feature_bag"],
        _file_identity(Path(paths["feature_bag"]), label=f"{arm_id} feature bag"),
        label=f"{arm_id}.outputs.feature_bag",
    )
    _strict_equal(
        outputs["raw_diagnostics_csv"],
        _file_identity(Path(paths["diagnostics_csv"]), label=f"{arm_id} diagnostics"),
        label=f"{arm_id}.outputs.raw_diagnostics_csv",
    )
    _strict_equal(
        outputs["legacy_primitive_manifest"],
        _file_identity(
            Path(paths["legacy_primitive_manifest"]),
            label=f"{arm_id} legacy primitive manifest",
        ),
        label=f"{arm_id}.outputs.legacy_primitive_manifest",
    )
    rebind = _require_exact_keys(
        payload["legacy_prepublication_rebind"],
        {
            "primitive_reported_work_bag_path",
            "primitive_reported_output_identity_after_path_rebind",
            "published_feature_bag_identity",
            "reason",
        },
        label=f"{arm_id}.legacy_prepublication_rebind",
    )
    expected_private_bag = str(
        Path(paths["private_work_directory"]) / "primitive_features.bag"
    )
    if rebind["primitive_reported_work_bag_path"] != expected_private_bag:
        raise AuditFailure(f"{arm_id} legacy primitive work-bag path mismatch")
    _strict_equal(
        rebind["primitive_reported_output_identity_after_path_rebind"],
        outputs["feature_bag"],
        label=f"{arm_id}.legacy_prepublication_rebind.rebound_identity",
    )
    _strict_equal(
        rebind["published_feature_bag_identity"],
        outputs["feature_bag"],
        label=f"{arm_id}.legacy_prepublication_rebind.published_identity",
    )
    if rebind["reason"] != (
        "frozen_primitive_writes_inside_private_work_directory; "
        "matched_transaction_publishes_the_identical_held_inode"
    ):
        raise AuditFailure(f"{arm_id} legacy prepublication rebind reason mismatch")
    _require_exact_keys(
        payload["code_artifacts"],
        {
            "matched_core",
            "frozen_primitive_module",
            "wrapper",
            "detector_dependencies",
            "detector_runtime",
        },
        label=f"{arm_id}.code_artifacts",
    )
    _validate_nested_identity_claims(payload["code_artifacts"], label=f"{arm_id}.code_artifacts")
    code = payload["code_artifacts"]
    _strict_equal(
        code["matched_core"],
        _file_identity(Path(core.__file__), label="matched core"),
        label=f"{arm_id}.code_artifacts.matched_core",
    )
    _strict_equal(
        code["frozen_primitive_module"],
        _file_identity(Path(core.primitive.__file__), label="frozen primitive"),
        label=f"{arm_id}.code_artifacts.frozen_primitive_module",
    )
    _strict_equal(
        code["wrapper"],
        _file_identity(EXPECTED_WRAPPERS[arm_id], label=f"{arm_id} wrapper"),
        label=f"{arm_id}.code_artifacts.wrapper",
    )
    expected_dependency_keys = (
        {
            "legacy_detector_adapter",
            "xfeat_modules_initializer",
            "xfeat_source",
            "xfeat_model_source",
            "xfeat_interpolator_source",
            "xfeat_weight",
            "xfeat_license",
            *matched_xfeat.FROZEN_TQDM_FILES.keys(),
        }
        if arm_id == XFEAT_ARM
        else set()
    )
    _require_exact_keys(
        code["detector_dependencies"],
        expected_dependency_keys,
        label=f"{arm_id}.code_artifacts.detector_dependencies",
    )
    _validate_detector_metadata_schema(code["detector_runtime"], arm_id=arm_id)
    runtime = _require_exact_keys(
        payload["runtime"],
        {
            "elapsed_wall_ms",
            "common_runtime",
            "post_factory_runtime",
            "post_carrier_runtime",
            "post_metadata_runtime",
        },
        label=f"{arm_id}.runtime",
    )
    if type(runtime["elapsed_wall_ms"]) is not float or not math.isfinite(runtime["elapsed_wall_ms"]) or runtime["elapsed_wall_ms"] < 0.0:
        raise AuditFailure(f"{arm_id}.runtime.elapsed_wall_ms invalid")
    for key in (
        "common_runtime",
        "post_factory_runtime",
        "post_carrier_runtime",
        "post_metadata_runtime",
    ):
        _strict_equal(runtime[key], expected_common["runtime"], label=f"{arm_id}.runtime.{key}")
    _require_exact_keys(
        payload["metrics"],
        {
            "raw_frames_processed",
            "published_frames",
            "observations",
            "observations_per_frame_min",
            "observations_per_frame_median",
            "observations_per_frame_max",
            "unique_ids",
            "published_first_occurrences",
            "published_continuations",
            "raw_births",
            "raw_drops",
            "adaptive_clahe_frames",
            "detector_candidates",
        },
        label=f"{arm_id}.metrics",
    )
    _require_exact_keys(
        payload["diagnostics_streams"],
        {
            "row_count",
            "raw_schedule_sha256",
            "raw_and_processed_pixels_sha256",
            "common_row_fields",
        },
        label=f"{arm_id}.diagnostics_streams",
    )
    for key in ("nonfeature_stream_before", "nonfeature_stream_after"):
        stream = _require_exact_keys(
            payload[key], {"message_count", "ordered_sha256", "topics"}, label=f"{arm_id}.{key}"
        )
        if type(stream["topics"]) is not dict:
            raise AuditFailure(f"{arm_id}.{key}.topics must be an object")
        for topic, topic_payload in stream["topics"].items():
            _require_exact_keys(topic_payload, {"count", "sha256"}, label=f"{arm_id}.{key}.{topic}")


def _validate_manifest_template_symbolic(
    template: Mapping[str, object],
    *,
    arm_id: str,
    paths: Mapping[str, str],
    expected_attempt: Mapping[str, object],
    locked_inputs: Mapping[str, object],
    expected_common: Mapping[str, object],
    feature_topic: str,
    image_topic: str,
    expected_frames: int,
    allow_prefix: bool,
    expected_symbolic: Mapping[str, object] | None = None,
) -> None:
    """Validate every fixed template leaf without pretending outcomes exist."""

    _require_exact_keys(template, MANIFEST_TOP_KEYS, label=f"{arm_id}.symbolic_manifest")
    if expected_symbolic is not None:
        _strict_equal(
            template,
            expected_symbolic,
            label=f"{arm_id}.symbolic_manifest:code_authoritative_projection",
        )
    expected_status = "PREFIX_NONFORMAL" if allow_prefix else "FULL"
    expected_reason = (
        "explicit_prefix_is_nonformal"
        if allow_prefix
        else "full_export_from_frozen_matched_cli_factory"
    )
    for key, expected in {
        "schema_version": core.SCHEMA_VERSION,
        "status": expected_status,
        "formal_eligible": not allow_prefix,
        "formal_eligibility_reason": expected_reason,
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
    }.items():
        _strict_equal(template[key], expected, label=f"{arm_id}.symbolic.{key}")
    prefix = _require_exact_keys(
        template["prefix"],
        {"requested_max_published_frames", "source_total_published_frames", "selected_published_frames", "cutoff_feature_record_stamp_ns"},
        label=f"{arm_id}.symbolic.prefix",
    )
    if prefix["requested_max_published_frames"] != (expected_frames if allow_prefix else None):
        raise AuditFailure(f"{arm_id} symbolic requested frame count mismatch")
    if prefix["selected_published_frames"] != expected_frames:
        raise AuditFailure(f"{arm_id} symbolic selected frame count mismatch")
    if not allow_prefix and prefix["cutoff_feature_record_stamp_ns"] is not None:
        raise AuditFailure(f"{arm_id} symbolic formal cutoff must be null")
    attempt = _require_exact_keys(template["attempt"], {"identity", "payload"}, label=f"{arm_id}.symbolic.attempt")
    _strict_equal(attempt["payload"], expected_attempt, label=f"{arm_id}.symbolic.attempt.payload")
    if attempt["identity"]["path"] != paths["attempt_json"]:
        raise AuditFailure(f"{arm_id} symbolic attempt identity path mismatch")
    inputs = _require_exact_keys(
        template["inputs"],
        {"source_feature_bag", "raw_image_bag", "camera_yaml", "camera_normalization_model", "feature_topic", "image_topic"},
        label=f"{arm_id}.symbolic.inputs",
    )
    for key in locked_inputs:
        _strict_equal(inputs[key], locked_inputs[key], label=f"{arm_id}.symbolic.inputs.{key}")
    if inputs["feature_topic"] != feature_topic or inputs["image_topic"] != image_topic:
        raise AuditFailure(f"{arm_id} symbolic topics mismatch")
    _strict_equal(template["common_contract"], expected_common, label=f"{arm_id}.symbolic.common")
    _strict_equal(template["arm_contract"], EXPECTED_ARM_CONTRACTS[arm_id], label=f"{arm_id}.symbolic.arm")
    outputs = _require_exact_keys(template["outputs"], {"feature_bag", "raw_diagnostics_csv", "legacy_primitive_manifest"}, label=f"{arm_id}.symbolic.outputs")
    for role, path_key in (("feature_bag", "feature_bag"), ("raw_diagnostics_csv", "diagnostics_csv"), ("legacy_primitive_manifest", "legacy_primitive_manifest")):
        if outputs[role]["path"] != paths[path_key]:
            raise AuditFailure(f"{arm_id} symbolic {role} path mismatch")
    rebind = template["legacy_prepublication_rebind"]
    if rebind["primitive_reported_work_bag_path"] != str(Path(paths["private_work_directory"]) / "primitive_features.bag"):
        raise AuditFailure(f"{arm_id} symbolic private work bag mismatch")
    for role in ("primitive_reported_output_identity_after_path_rebind", "published_feature_bag_identity"):
        if rebind[role]["path"] != paths["feature_bag"]:
            raise AuditFailure(f"{arm_id} symbolic rebind final path mismatch")
    rows = template["raw_frame_diagnostics"]
    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )
    if type(rows) is not list or len(rows) != expected_raw_frames:
        raise AuditFailure(
            f"{arm_id} symbolic diagnostics must contain "
            f"{expected_raw_frames} rows"
        )
    for index, row in enumerate(rows):
        _require_exact_keys(row, set(core.DIAGNOSTIC_FIELDS), label=f"{arm_id}.symbolic.raw[{index}]")
        if row["raw_index"] != index:
            raise AuditFailure(f"{arm_id} symbolic raw index mismatch at {index}")


def _validate_detector_metadata_schema(value: object, *, arm_id: str) -> None:
    if arm_id == GFTT_ARM:
        metadata = _require_exact_keys(
            value,
            {"identity", "api", "runtime", "frozen_detector_parameters"},
            label="GFTT.detector_runtime",
        )
        _require_exact_keys(
            metadata["api"],
            {
                "call",
                "score",
                "matcher_called",
                "descriptor_computation",
                "carrier_thinning_inside_detector",
            },
            label="GFTT.detector_runtime.api",
        )
        _require_exact_keys(
            metadata["runtime"],
            {
                "opencv_version",
                "numpy_version",
                "detect_calls",
                "candidate_total",
                "input_shapes",
                "input_shapes_hw",
            },
            label="GFTT.detector_runtime.runtime",
        )
        parameters = _require_exact_keys(
            metadata["frozen_detector_parameters"],
            {
                "max_corners",
                "quality_level",
                "min_distance_px",
                "block_size",
                "use_harris",
                "harris_k",
            },
            label="GFTT.detector_runtime.frozen_detector_parameters",
        )
        contract = EXPECTED_ARM_CONTRACTS[GFTT_ARM]["detector"]["contract"]
        _strict_equal(
            parameters,
            {
                "max_corners": contract["max_corners"],
                "quality_level": contract["quality_level"],
                "min_distance_px": contract["internal_min_distance_px"],
                "block_size": contract["block_size"],
                "use_harris": contract["use_harris_detector"],
                "harris_k": contract[
                    "harris_k_api_argument_inert_when_non_harris"
                ],
            },
            label="GFTT.detector_runtime.frozen_detector_parameters:arm_contract",
        )
        return
    metadata = _require_exact_keys(
        value,
        {
            "identity",
            "repository",
            "license",
            "closure",
            "api",
            "runtime",
            "matched_runtime_contract",
            "matched_torch_binary_contract",
            "matched_torch_python_contract",
            "matched_torch_import_origin_contract",
            "matched_package_initializer_contract",
            "matched_tqdm_import_contract",
            "optional_matcher_dependency_contract",
        },
        label="XFeat.detector_runtime",
    )
    _require_exact_keys(
        metadata["repository"],
        {
            "path",
            "upstream",
            "commit",
            "dirty",
            "dirty_classification",
            "status_porcelain_v1",
            "dirty_path_content_and_mode_proofs",
            "unstaged_summary",
            "staged_summary",
            "content_identity_caveat",
            "license_spdx",
        },
        label="XFeat.detector_runtime.repository",
    )
    license_payload = _require_exact_keys(
        metadata["license"], {"spdx", "file"}, label="XFeat.detector_runtime.license"
    )
    _require_exact_keys(license_payload["file"], IDENTITY_KEYS, label="XFeat.detector_runtime.license.file")
    closure = _require_exact_keys(
        metadata["closure"],
        {"xfeat.py", "model.py", "interpolator.py", "xfeat.pt"},
        label="XFeat.detector_runtime.closure",
    )
    for label, identity in closure.items():
        _require_exact_keys(identity, IDENTITY_KEYS, label=f"XFeat.detector_runtime.closure.{label}")
    _require_exact_keys(
        metadata["api"],
        {
            "call",
            "top_k",
            "detection_threshold",
            "carrier_consumes",
            "keypoint_coordinates",
            "score_values",
            "input_adaptation",
            "matcher_called",
            "descriptor_computation",
        },
        label="XFeat.detector_runtime.api",
    )
    _require_exact_keys(
        metadata["runtime"],
        {
            "device",
            "torch_version",
            "opencv_version",
            "numpy_version",
            "imported_module_paths",
            "detect_calls",
            "gray_input_shapes_hw",
            "rgb_tensor_input_shapes_bchw",
            "timing_clock",
            "cuda_timing_sync",
            "warmup_policy",
            "detect_ms_scope",
            "detect_ms",
            "candidate_total",
            "input_shapes",
        },
        label="XFeat.detector_runtime.runtime",
    )
    _require_exact_keys(
        metadata["matched_runtime_contract"],
        {"device", "torch_num_threads", "torch_num_interop_threads", "deterministic_algorithms"},
        label="XFeat.matched_runtime_contract",
    )
    _require_exact_keys(
        metadata["matched_torch_binary_contract"],
        XFEAT_TORCH_BINARY_KEYS,
        label="XFeat.matched_torch_binary_contract",
    )
    _require_exact_keys(
        metadata["matched_torch_python_contract"],
        XFEAT_TORCH_PYTHON_KEYS,
        label="XFeat.matched_torch_python_contract",
    )
    import_origins = _require_exact_keys(
        metadata["matched_torch_import_origin_contract"],
        XFEAT_TORCH_IMPORT_KEYS,
        label="XFeat.matched_torch_import_origin_contract",
    )
    expected_origins = matched_xfeat.static_torch_import_origin_contract()
    for label, item in import_origins.items():
        _require_exact_keys(
            item,
            {"module", "file", "spec_origin"},
            label=f"XFeat.matched_torch_import_origin_contract.{label}",
        )
        _strict_equal(
            item,
            expected_origins[label],
            label=f"XFeat.matched_torch_import_origin_contract.{label}:static",
        )
    package_initializer = _require_exact_keys(
        metadata["matched_package_initializer_contract"],
        {"module", "file", "spec_origin", "loader", "package_path"},
        label="XFeat.matched_package_initializer_contract",
    )
    _require_exact_keys(
        package_initializer["file"],
        IDENTITY_KEYS,
        label="XFeat.matched_package_initializer_contract.file",
    )
    _strict_equal(
        package_initializer,
        matched_xfeat.static_xfeat_package_initializer_contract(),
        label="XFeat.matched_package_initializer_contract:static",
    )
    tqdm_contract = _require_exact_keys(
        metadata["matched_tqdm_import_contract"],
        XFEAT_TQDM_KEYS,
        label="XFeat.matched_tqdm_import_contract",
    )
    expected_tqdm = matched_xfeat.static_tqdm_import_contract()
    for label, item in tqdm_contract.items():
        _require_exact_keys(
            item,
            {"module", "file", "spec_origin", "loader", "package_path"},
            label=f"XFeat.matched_tqdm_import_contract.{label}",
        )
        _require_exact_keys(
            item["file"],
            IDENTITY_KEYS,
            label=f"XFeat.matched_tqdm_import_contract.{label}.file",
        )
        _strict_equal(
            item,
            expected_tqdm[label],
            label=f"XFeat.matched_tqdm_import_contract.{label}:static",
        )
    _strict_equal(
        metadata["optional_matcher_dependency_contract"],
        matched_xfeat.expected_optional_matcher_dependency_contract(),
        label="XFeat.optional_matcher_dependency_contract",
    )


def _symbolic_detector_metadata(
    *,
    arm_id: str,
    image_shapes_hw: Sequence[Sequence[int]],
    mandatory_rules: Mapping[str, object],
) -> dict[str, object]:
    """Build detector metadata from frozen code/runtime, never from outcomes."""

    if arm_id == GFTT_ARM:
        contract = EXPECTED_ARM_CONTRACTS[GFTT_ARM]["detector"]["contract"]
        metadata = {
            "identity": "opencv_GFTT_detector_only_matched_birth_v1",
            "api": {
                "call": "cv2.goodFeaturesToTrack",
                "score": "cv2.cornerMinEigenVal_at_returned_integral_pixel",
                "matcher_called": False,
                "descriptor_computation": False,
                "carrier_thinning_inside_detector": False,
            },
            "runtime": {
                "opencv_version": str(cv2.__version__),
                "numpy_version": str(np.__version__),
                "detect_calls": 0,
                "candidate_total": 0,
                "input_shapes": [list(item) for item in image_shapes_hw],
                "input_shapes_hw": [list(item) for item in image_shapes_hw],
            },
            "frozen_detector_parameters": {
                "max_corners": contract["max_corners"],
                "quality_level": contract["quality_level"],
                "min_distance_px": contract["internal_min_distance_px"],
                "block_size": contract["block_size"],
                "use_harris": contract["use_harris_detector"],
                "harris_k": contract[
                    "harris_k_api_argument_inert_when_non_harris"
                ],
            },
        }
        runtime = metadata["runtime"]
    elif arm_id == XFEAT_ARM:
        # Static identity/runtime observation only.  No detector object, model
        # constructor, image, or inference API is touched here.
        legacy = matched_xfeat.legacy_xfeat
        closure = legacy._validate_runtime_closure()
        repository = legacy._repository_metadata()
        torch_dependencies = matched_xfeat.static_torch_dependency_contract()
        torch_import_origins = (
            matched_xfeat.static_torch_import_origin_contract()
        )
        package_initializer = (
            matched_xfeat.static_xfeat_package_initializer_contract()
        )
        tqdm_contract = matched_xfeat.static_tqdm_import_contract()
        optional_matcher = (
            matched_xfeat.expected_optional_matcher_dependency_contract()
        )
        metadata = {
            "identity": "official_verlab_XFeat_sparse_detectAndCompute_proposals_only",
            "repository": repository,
            "license": {"spdx": "Apache-2.0", "file": closure["LICENSE"]},
            "closure": {
                label: identity for label, identity in closure.items()
                if label != "LICENSE"
            },
            "api": {
                "call": "XFeat.detectAndCompute(tensor, top_k=2048)[0]",
                "top_k": legacy.XFEAT_TOP_K,
                "detection_threshold": legacy.XFEAT_DETECTION_THRESHOLD,
                "carrier_consumes": ["keypoints", "scores"],
                "keypoint_coordinates": "official_original_image_coordinates_unmodified",
                "score_values": "official_native_sparse_scores_unmodified",
                "input_adaptation": (
                    "frozen literature input is mono/255; this wrapper repeats mono "
                    "into RGB after /255 for the official PyTorch B,C,H,W path. "
                    "XFeatModel.forward averages channels to one, so the repeated "
                    "channels recover the same normalized mono values"
                ),
                "matcher_called": False,
                "descriptor_computation": (
                    "official detectAndCompute computes 64-D descriptors internally; "
                    "the adapter discards them and does not use them for LK or matching"
                ),
            },
            "runtime": {
                "device": "cpu",
                "torch_version": "2.2.2+cpu",
                "opencv_version": str(cv2.__version__),
                "numpy_version": str(np.__version__),
                "imported_module_paths": {
                    "modules": package_initializer["file"]["path"],
                    **{
                        item["module"]: item["file"]["path"]
                        for item in tqdm_contract.values()
                    },
                    "modules.xfeat": str(legacy.XFEAT_SOURCE.resolve(strict=True)),
                    "modules.model": str(legacy.XFEAT_MODEL_SOURCE.resolve(strict=True)),
                    "modules.interpolator": str(
                        legacy.XFEAT_INTERPOLATOR_SOURCE.resolve(strict=True)
                    ),
                },
                "detect_calls": 0,
                "gray_input_shapes_hw": [list(item) for item in image_shapes_hw],
                "rgb_tensor_input_shapes_bchw": [
                    [1, 3, int(item[0]), int(item[1])]
                    for item in image_shapes_hw
                ],
                "timing_clock": "time.perf_counter",
                "cuda_timing_sync": "synchronize_before_and_after_when_cuda",
                "warmup_policy": "first_detect_call_separate",
                "detect_ms_scope": (
                    "gray-to-repeated-RGB tensor conversion, official "
                    "detectAndCompute call, CUDA synchronization when applicable, "
                    "and keypoint/score transfer; lazy model loading is excluded"
                ),
                "detect_ms": {
                    group: {
                        "count": 0,
                        "median_ms": None,
                        "p90_ms": None,
                        "total_ms": 0.0,
                    }
                    for group in ("warmup", "steady_state", "all")
                },
                "candidate_total": 0,
                "input_shapes": [list(item) for item in image_shapes_hw],
            },
            "matched_runtime_contract": {
                "device": "cpu",
                "torch_num_threads": 1,
                "torch_num_interop_threads": 1,
                "deterministic_algorithms": True,
            },
            "matched_torch_binary_contract": torch_dependencies[
                "matched_torch_binary_contract"
            ],
            "matched_torch_python_contract": torch_dependencies[
                "matched_torch_python_contract"
            ],
            "matched_torch_import_origin_contract": torch_import_origins,
            "matched_package_initializer_contract": package_initializer,
            "matched_tqdm_import_contract": tqdm_contract,
            "optional_matcher_dependency_contract": optional_matcher,
        }
        runtime = metadata["runtime"]
    else:
        raise AuditFailure(f"unknown symbolic detector arm: {arm_id}")
    runtime["detect_calls"] = copy.deepcopy(
        mandatory_rules["/code_artifacts/detector_runtime/runtime/detect_calls"]
    )
    runtime["candidate_total"] = copy.deepcopy(
        mandatory_rules["/code_artifacts/detector_runtime/runtime/candidate_total"]
    )
    if arm_id == XFEAT_ARM:
        for group in ("warmup", "steady_state", "all"):
            for leaf in ("count", "median_ms", "p90_ms", "total_ms"):
                pointer = (
                    "/code_artifacts/detector_runtime/runtime/detect_ms/"
                    f"{group}/{leaf}"
                )
                runtime["detect_ms"][group][leaf] = copy.deepcopy(
                    mandatory_rules[pointer]
                )
    _validate_detector_metadata_schema(metadata, arm_id=arm_id)
    return metadata


def _symbolic_manifest_expected(
    *,
    arm_id: str,
    paths: Mapping[str, str],
    expected_attempt: Mapping[str, object],
    locked_inputs: Mapping[str, object],
    expected_common: Mapping[str, object],
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    common_rows: Sequence[Mapping[str, object]],
    reconstruction: Mapping[str, object],
    camera_normalization_model: str,
    nonfeature_stream: Mapping[str, object],
) -> dict[str, object]:
    """Return the unique outcome-blind manifest template for one arm."""

    rules = _mandatory_dynamic_rules(
        arm_id,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )

    def marker(pointer: str) -> object:
        return copy.deepcopy(rules[pointer])

    rows: list[dict[str, object]] = []
    for index, common_row in enumerate(common_rows):
        row = dict(common_row)
        for field in set(core.DIAGNOSTIC_FIELDS) - set(COMMON_DIAGNOSTIC_FIELDS):
            row[field] = marker(f"/raw_frame_diagnostics/{index}/{field}")
        rows.append(row)
    metrics: dict[str, object] = {
        "raw_frames_processed": len(common_rows),
        "published_frames": expected_frames,
        "adaptive_clahe_frames": sum(
            bool(row["adaptive_clahe_applied"]) for row in common_rows
        ),
    }
    for leaf in METRIC_DYNAMIC_LEAVES:
        metrics[leaf] = marker(f"/metrics/{leaf}")
    detector_dependencies = {
        str(label): _file_identity(Path(path), label=f"{arm_id} detector dependency {label}")
        for label, path in (
            matched_xfeat.XFEAT_METHOD_SPEC.detector_code_artifacts
            if arm_id == XFEAT_ARM
            else matched_gftt.GFTT_METHOD_SPEC.detector_code_artifacts
        )
    }
    feature_identity = {
        "path": paths["feature_bag"],
        "size_bytes": marker("/outputs/feature_bag/size_bytes"),
        "sha256": marker("/outputs/feature_bag/sha256"),
    }
    return {
        "schema_version": core.SCHEMA_VERSION,
        "status": "PREFIX_NONFORMAL" if allow_prefix else "FULL",
        "formal_eligible": not allow_prefix,
        "formal_eligibility_reason": (
            "explicit_prefix_is_nonformal"
            if allow_prefix
            else "full_export_from_frozen_matched_cli_factory"
        ),
        "scientific_role": (
            "post_result_development_exploratory_detector_birth_ablation"
        ),
        "prefix": {
            "requested_max_published_frames": (
                expected_frames if allow_prefix else None
            ),
            "source_total_published_frames": EXPECTED_PUBLISHED_FRAMES,
            "selected_published_frames": expected_frames,
            "cutoff_feature_record_stamp_ns": reconstruction[
                "cutoff_feature_record_stamp_ns"
            ],
        },
        "attempt": {
            "identity": {
                "path": paths["attempt_json"],
                "size_bytes": marker("/attempt/identity/size_bytes"),
                "sha256": marker("/attempt/identity/sha256"),
            },
            "payload": copy.deepcopy(dict(expected_attempt)),
        },
        "inputs": {
            **copy.deepcopy(dict(locked_inputs)),
            "camera_normalization_model": camera_normalization_model,
            "feature_topic": feature_topic,
            "image_topic": image_topic,
        },
        "common_contract": copy.deepcopy(dict(expected_common)),
        "common_contract_sha256": core._canonical_sha256(expected_common),
        "arm_contract": copy.deepcopy(EXPECTED_ARM_CONTRACTS[arm_id]),
        "arm_contract_sha256": core._canonical_sha256(
            EXPECTED_ARM_CONTRACTS[arm_id]
        ),
        "pair_difference_policy": {
            "no_wildcard_allowlist": True,
            "freeze_must_pin_every_detector_specific_leaf": True,
            "only_semantic_categories": [
                "detector_adapter_identity_and_frozen_parameters",
                "truthful_backend_inert_detector_provenance",
                "detector_candidates_births_survival_ids_and_trajectory_outcomes",
                "detector_runtime_and_output_artifact_identity",
            ],
            "posthoc_candidate_or_observation_dose_matching_forbidden": True,
        },
        "code_artifacts": {
            "matched_core": _file_identity(Path(core.__file__), label="matched core"),
            "frozen_primitive_module": _file_identity(
                Path(core.primitive.__file__), label="frozen primitive"
            ),
            "wrapper": _file_identity(
                EXPECTED_WRAPPERS[arm_id], label=f"{arm_id} wrapper"
            ),
            "detector_dependencies": detector_dependencies,
            "detector_runtime": _symbolic_detector_metadata(
                arm_id=arm_id,
                image_shapes_hw=reconstruction["image_shapes_hw"],
                mandatory_rules=rules,
            ),
        },
        "outputs": {
            "feature_bag": feature_identity,
            "raw_diagnostics_csv": {
                "path": paths["diagnostics_csv"],
                "size_bytes": marker("/outputs/raw_diagnostics_csv/size_bytes"),
                "sha256": marker("/outputs/raw_diagnostics_csv/sha256"),
            },
            "legacy_primitive_manifest": {
                "path": paths["legacy_primitive_manifest"],
                "size_bytes": marker(
                    "/outputs/legacy_primitive_manifest/size_bytes"
                ),
                "sha256": marker(
                    "/outputs/legacy_primitive_manifest/sha256"
                ),
            },
        },
        "legacy_prepublication_rebind": {
            "primitive_reported_work_bag_path": str(
                Path(paths["private_work_directory"]) / "primitive_features.bag"
            ),
            "primitive_reported_output_identity_after_path_rebind": {
                "path": paths["feature_bag"],
                "size_bytes": marker(
                    "/legacy_prepublication_rebind/"
                    "primitive_reported_output_identity_after_path_rebind/size_bytes"
                ),
                "sha256": marker(
                    "/legacy_prepublication_rebind/"
                    "primitive_reported_output_identity_after_path_rebind/sha256"
                ),
            },
            "published_feature_bag_identity": {
                "path": paths["feature_bag"],
                "size_bytes": marker(
                    "/legacy_prepublication_rebind/"
                    "published_feature_bag_identity/size_bytes"
                ),
                "sha256": marker(
                    "/legacy_prepublication_rebind/"
                    "published_feature_bag_identity/sha256"
                ),
            },
            "reason": (
                "frozen_primitive_writes_inside_private_work_directory; "
                "matched_transaction_publishes_the_identical_held_inode"
            ),
        },
        "nonfeature_stream_before": copy.deepcopy(dict(nonfeature_stream)),
        "nonfeature_stream_after": copy.deepcopy(dict(nonfeature_stream)),
        "metrics": metrics,
        "diagnostics_streams": {
            "row_count": len(common_rows),
            "raw_schedule_sha256": reconstruction["raw_schedule_sha256"],
            "raw_and_processed_pixels_sha256": reconstruction[
                "raw_and_processed_pixels_sha256"
            ],
            "common_row_fields": list(COMMON_DIAGNOSTIC_FIELDS),
        },
        "raw_frame_diagnostics": rows,
        "runtime": {
            "elapsed_wall_ms": marker("/runtime/elapsed_wall_ms"),
            "common_runtime": copy.deepcopy(expected_common["runtime"]),
            "post_factory_runtime": copy.deepcopy(expected_common["runtime"]),
            "post_carrier_runtime": copy.deepcopy(expected_common["runtime"]),
            "post_metadata_runtime": copy.deepcopy(expected_common["runtime"]),
        },
    }


def _manifest_pair_contract(
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    expected_left: Mapping[str, object],
    expected_right: Mapping[str, object],
    allowed_pair_scalar_differences: Sequence[str],
    required_pair_scalar_differences: Sequence[str],
) -> dict[str, object]:
    violations: list[str] = []
    for actual, expected, label in (
        (left, expected_left, XFEAT_ARM),
        (right, expected_right, GFTT_ARM),
    ):
        try:
            _require_exact_keys(actual, MANIFEST_TOP_KEYS, label=f"{label}.actual")
            _require_exact_keys(expected, MANIFEST_TOP_KEYS, label=f"{label}.template")
            _match_manifest_template(actual, expected)
        except AuditFailure as exc:
            violations.append(f"{label}:freeze:{exc}")
    observed = _pair_scalar_differences(left, right)
    unexpected = sorted(set(observed) - set(allowed_pair_scalar_differences))
    missing_required = sorted(set(required_pair_scalar_differences) - set(observed))
    violations.extend(f"unexpected_pair_difference:{path}" for path in unexpected[:40])
    violations.extend(f"missing_required_pair_difference:{path}" for path in missing_required[:40])
    forbidden = [path for path in observed if not _pair_difference_path_allowed(path)]
    violations.extend(f"forbidden_pair_difference:{path}" for path in forbidden[:40])
    return {
        "pass": not violations,
        "violations": violations[:80],
        "observed_recursive_scalar_differences": observed,
        "common_contract_sha256": left.get("common_contract_sha256"),
    }


def _validate_legacy_manifest(
    *,
    arm_id: str,
    legacy_path: Path,
    feature_bag: Path,
    matched_manifest: Mapping[str, object],
    allow_prefix: bool,
) -> dict[str, object]:
    if type(allow_prefix) is not bool:
        raise AuditFailure(f"{arm_id} legacy allow_prefix must be a boolean")
    legacy = _load_pretty_object(legacy_path, label=f"{arm_id} legacy manifest")
    _require_exact_keys(
        legacy,
        {
            "schema_version",
            "status",
            "formal_eligible",
            "formal_eligibility_reason",
            "detector_origin",
            "prefix",
            "inputs",
            "algorithm",
            "algorithm_config_sha256",
            "code_artifacts",
            "output_bag",
            "nonfeature_stream_before",
            "nonfeature_stream_after",
            "metrics",
            "raw_frame_diagnostics",
        },
        label=f"{arm_id}.legacy_manifest",
    )
    for key in (
        "schema_version",
        "status",
        "formal_eligible",
        "prefix",
        "inputs",
        "nonfeature_stream_before",
        "nonfeature_stream_after",
        "metrics",
        "raw_frame_diagnostics",
    ):
        _strict_equal(
            legacy[key], matched_manifest[key], label=f"{arm_id}.legacy.{key}"
        )
    expected_legacy_reason = (
        "explicit_prefix_is_nonformal"
        if allow_prefix
        else "full_export_from_frozen_cli_production_factory"
    )
    expected_matched_reason = (
        "explicit_prefix_is_nonformal"
        if allow_prefix
        else "full_export_from_frozen_matched_cli_factory"
    )
    if legacy["formal_eligibility_reason"] != expected_legacy_reason:
        raise AuditFailure(f"{arm_id} legacy formal eligibility reason mismatch")
    if matched_manifest["formal_eligibility_reason"] != expected_matched_reason:
        raise AuditFailure(f"{arm_id} matched formal eligibility reason mismatch")
    if legacy["detector_origin"] != "cli_production_factory":
        raise AuditFailure(f"{arm_id} legacy detector origin is not formal CLI")
    algorithm = {
        "common_contract": matched_manifest["common_contract"],
        "common_contract_sha256": matched_manifest["common_contract_sha256"],
        "arm_contract": matched_manifest["arm_contract"],
        "arm_contract_sha256": matched_manifest["arm_contract_sha256"],
    }
    _strict_equal(legacy["algorithm"], algorithm, label=f"{arm_id}.legacy.algorithm")
    if legacy["algorithm_config_sha256"] != core._canonical_sha256(algorithm):
        raise AuditFailure(f"{arm_id} legacy algorithm hash mismatch")
    legacy_code = legacy["code_artifacts"]
    expected_legacy_code = {
        "exporter": matched_manifest["code_artifacts"]["wrapper"],
        "carrier_base": matched_manifest["code_artifacts"][
            "frozen_primitive_module"
        ],
        **matched_manifest["code_artifacts"]["detector_dependencies"],
        "klt_reference_source": matched_manifest["common_contract"][
            "implementation"
        ]["klt_reference_source"],
        "quality_reference_source": matched_manifest["common_contract"][
            "implementation"
        ]["quality_reference_source"],
        "detector": matched_manifest["code_artifacts"]["detector_runtime"],
    }
    _strict_equal(
        legacy_code,
        expected_legacy_code,
        label=f"{arm_id}.legacy.code_artifacts",
    )
    output = _require_exact_keys(
        legacy["output_bag"], IDENTITY_KEYS, label=f"{arm_id}.legacy.output_bag"
    )
    live_output = _file_identity(feature_bag, label=f"{arm_id} feature bag")
    if output["size_bytes"] != live_output["size_bytes"] or output["sha256"] != live_output["sha256"]:
        raise AuditFailure(f"{arm_id} legacy output bag bytes mismatch")
    # The primitive was deliberately given a private work pathname.  Only
    # that stale path leaf may differ; bytes are bound above and the matched
    # manifest binds the final public path.
    expected_legacy_output_path = matched_manifest["legacy_prepublication_rebind"][
        "primitive_reported_work_bag_path"
    ]
    if type(output["path"]) is not str or output["path"] != expected_legacy_output_path:
        raise AuditFailure(
            f"{arm_id} legacy output path does not match the frozen prepublication rebind"
        )
    work_dir = Path(
        matched_manifest["attempt"]["payload"]["reserved_outputs"]["private_work_directory"]
    )
    if work_dir.is_symlink() or not work_dir.is_dir():
        raise AuditFailure(f"{arm_id} private work directory is not a directory")
    work_stat = work_dir.stat()
    if int(work_stat.st_uid) != int(os.getuid()):
        raise AuditFailure(f"{arm_id} private work directory owner mismatch")
    if stat.S_IMODE(work_stat.st_mode) != 0o700:
        raise AuditFailure(f"{arm_id} private work directory mode is not 0700")
    if list(work_dir.iterdir()):
        raise AuditFailure(f"{arm_id} successful private work directory is not empty")
    return {
        "pass": True,
        "legacy_manifest": _file_identity(legacy_path, label=f"{arm_id} legacy manifest"),
        "private_work_directory": {
            "path": str(work_dir.resolve(strict=True)),
            "mode_octal": "0700",
            "entry_count": 0,
        },
    }


def _parse_diagnostic_scalar(field: str, value: str) -> object:
    if field in INT_DIAGNOSTIC_FIELDS:
        try:
            parsed = int(value, 10)
        except ValueError as exc:
            raise AuditFailure(f"diagnostic {field} is not an integer") from exc
        if str(parsed) != value:
            raise AuditFailure(f"diagnostic {field} integer is not canonical")
        return parsed
    if field in BOOL_DIAGNOSTIC_FIELDS:
        if value not in ("True", "False"):
            raise AuditFailure(f"diagnostic {field} boolean is not canonical")
        return value == "True"
    if field in HASH_DIAGNOSTIC_FIELDS:
        if not _SHA256_RE.fullmatch(value):
            raise AuditFailure(f"diagnostic {field} hash is malformed")
        return value
    if field in FLOAT_DIAGNOSTIC_FIELDS:
        if value == "":
            return None
        try:
            parsed = float(value)
        except ValueError as exc:
            raise AuditFailure(f"diagnostic {field} is not a float") from exc
        if not math.isfinite(parsed) or str(parsed) != value:
            raise AuditFailure(f"diagnostic {field} float is not canonical finite text")
        return parsed
    raise AuditFailure(f"unknown diagnostic field {field}")


def _read_diagnostics(path: Path) -> list[dict[str, object]]:
    path = _regular_path(path, label="diagnostics")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != core.DIAGNOSTIC_FIELDS:
            raise AuditFailure("diagnostics schema mismatch")
        rows = []
        for row in reader:
            if None in row or set(row) != set(core.DIAGNOSTIC_FIELDS):
                raise AuditFailure("diagnostics row has extra or missing columns")
            rows.append(
                {
                    field: _parse_diagnostic_scalar(field, row[field])
                    for field in core.DIAGNOSTIC_FIELDS
                }
            )
    return rows


def _validate_diagnostic_rows_shape(
    rows: Sequence[Mapping[str, object]], *, arm_id: str,
    expected_raw_frames: int = EXPECTED_RAW_FRAMES,
) -> None:
    if len(rows) != expected_raw_frames:
        raise AuditFailure(
            f"{arm_id} diagnostics row count is not {expected_raw_frames}"
        )
    previous_output = 0
    previous_stamp = 0
    for index, row in enumerate(rows):
        _require_exact_keys(row, set(core.DIAGNOSTIC_FIELDS), label=f"{arm_id}.diagnostics[{index}]")
        if row["raw_index"] != index:
            raise AuditFailure(f"{arm_id} diagnostics raw index mismatch at {index}")
        if type(row["header_stamp_ns"]) is not int or row["header_stamp_ns"] <= previous_stamp:
            raise AuditFailure(f"{arm_id} diagnostics stamps are not strictly increasing")
        previous_stamp = row["header_stamp_ns"]
        for field in INT_DIAGNOSTIC_FIELDS - {"raw_index", "header_stamp_ns"}:
            if type(row[field]) is not int or row[field] < 0:
                raise AuditFailure(f"{arm_id} diagnostics {field} invalid at {index}")
        if row["tracked_before"] != previous_output:
            raise AuditFailure(f"{arm_id} diagnostics carrier continuity mismatch at {index}")
        if row["dropped"] != row["tracked_before"] - row["tracked_after"]:
            raise AuditFailure(f"{arm_id} diagnostics drop arithmetic mismatch at {index}")
        if row["slots_before_detect"] != core.FEATURE_CAP - row["tracked_after"]:
            raise AuditFailure(f"{arm_id} diagnostics slot arithmetic mismatch at {index}")
        if row["detector_called"] is not (row["slots_before_detect"] > 0):
            raise AuditFailure(f"{arm_id} diagnostics detector-call rule mismatch at {index}")
        if row["detector_candidates"] > core.MAX_CANDIDATES:
            raise AuditFailure(f"{arm_id} detector candidate cap exceeded at {index}")
        if row["births"] > row["detector_candidates"] or row["births"] > row["slots_before_detect"]:
            raise AuditFailure(f"{arm_id} diagnostics births invalid at {index}")
        if row["output_tracks"] != row["tracked_after"] + row["births"] or row["output_tracks"] > core.FEATURE_CAP:
            raise AuditFailure(f"{arm_id} diagnostics output arithmetic mismatch at {index}")
        if not row["detector_called"] and (row["detector_candidates"] or row["births"]):
            raise AuditFailure(f"{arm_id} detector emitted without a call at {index}")
        for field in FLOAT_DIAGNOSTIC_FIELDS:
            value = row[field]
            if value is not None and (
                type(value) is not float or not math.isfinite(value)
            ):
                raise AuditFailure(
                    f"{arm_id} diagnostics {field} must be null or finite float at {index}"
                )
        for field in ("fb_median_px", "fb_p95_px"):
            value = row[field]
            if value is not None and not (0.0 <= value <= core.primitive.LK_FB_MAX_PX + 1e-6):
                raise AuditFailure(f"{arm_id} diagnostics {field} outside LK gate at {index}")
        ncc_value = row["ncc_median"]
        if ncc_value is not None and not (
            core.primitive.NCC_MIN <= ncc_value <= 1.0 + 1e-6
        ):
            raise AuditFailure(f"{arm_id} diagnostics ncc_median outside NCC gate at {index}")
        if (
            row["fb_median_px"] is not None
            and row["fb_p95_px"] is not None
            and row["fb_median_px"] > row["fb_p95_px"]
        ):
            raise AuditFailure(f"{arm_id} diagnostics FB percentiles inverted at {index}")
        previous_output = row["output_tracks"]


def _diagnostics_pair(
    left: Sequence[Mapping[str, object]], right: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    violations: list[str] = []
    if len(left) != len(right):
        violations.append("row_count")
    for index, (a, b) in enumerate(zip(left, right)):
        for field in COMMON_DIAGNOSTIC_FIELDS:
            if a.get(field) != b.get(field):
                violations.append(f"row{index}:{field}")
    return {"pass": not violations, "violations": violations[:40], "row_count": len(left)}


def _reconstruct_common_diagnostics(
    *,
    source_bag: Path,
    raw_bag: Path,
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool = False,
    expected_frames: int = EXPECTED_PUBLISHED_FRAMES,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Independently rebuild the common pixel/schedule evidence."""

    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )

    schedule, source_total = core._call_trusted_rosbag_scoped(
        core.primitive.read_source_schedule,
        source_bag,
        feature_topic,
        expected_frames if allow_prefix else None,
    )
    if source_total != EXPECTED_PUBLISHED_FRAMES or len(schedule) != expected_frames:
        raise AuditFailure(
            "locked source schedule total/selection mismatch: "
            f"total={source_total} selected={len(schedule)} expected={expected_frames}"
        )
    raw_frames = core._call_trusted_rosbag_scoped(
        core.primitive.read_raw_frames,
        raw_bag,
        image_topic,
        schedule[0].header_stamp_ns,
        schedule[-1].header_stamp_ns,
    )
    if len(raw_frames) != expected_raw_frames:
        raise AuditFailure(
            f"locked raw window contains {len(raw_frames)}, expected {expected_raw_frames}"
        )
    publish_indices = core.primitive._schedule_raw_indices(schedule, raw_frames)
    if publish_indices.tolist() != list(range(1, expected_raw_frames, 2)):
        raise AuditFailure("locked raw/source schedule is not exact odd raw indices")
    published = set(int(item) for item in publish_indices)
    rows: list[dict[str, object]] = []
    image_shapes: set[tuple[int, int]] = set()
    for index, frame in enumerate(raw_frames):
        raw = np.asarray(frame.image, dtype=np.uint8)
        if raw.ndim != 2 or not raw.flags.c_contiguous:
            raw = np.ascontiguousarray(raw)
        image_shapes.add((int(raw.shape[0]), int(raw.shape[1])))
        raw_before = core._array_sha256(raw)
        processed, enhanced = core.primitive.adaptive_clahe(raw)
        processed = np.asarray(processed, dtype=np.uint8)
        if processed.shape != raw.shape or processed.ndim != 2:
            raise AuditFailure(f"common preprocess geometry drift at raw row {index}")
        if core._array_sha256(raw) != raw_before:
            raise AuditFailure(f"common preprocess mutated locked raw row {index}")
        rows.append(
            {
                "raw_index": index,
                "header_stamp_ns": int(frame.header_stamp_ns),
                "published": index in published,
                "adaptive_clahe_applied": bool(enhanced),
                "raw_image_sha256": raw_before,
                "processed_image_sha256": core._array_sha256(processed),
            }
        )
    return rows, {
        "source_total_published_frames": source_total,
        "selected_published_frames": len(schedule),
        "cutoff_feature_record_stamp_ns": (
            int(schedule[-1].record_stamp_ns) if allow_prefix else None
        ),
        "raw_row_count": len(rows),
        "published_raw_indices_sha256": hashlib.sha256(
            np.asarray(publish_indices, dtype="<i8").tobytes()
        ).hexdigest(),
        "raw_schedule_sha256": core._diagnostics_schedule_stream(rows),
        "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(rows),
        "image_shapes_hw": [list(item) for item in sorted(image_shapes)],
    }


def _validate_diagnostics_binding(
    *,
    arm_id: str,
    manifest: Mapping[str, object],
    csv_rows: Sequence[Mapping[str, object]],
    reconstructed_common: Sequence[Mapping[str, object]],
    image_shapes_hw: Sequence[Sequence[int]],
    allow_prefix: bool = False,
    expected_frames: int = EXPECTED_PUBLISHED_FRAMES,
) -> dict[str, object]:
    expected_raw_frames = _mode_raw_frames(
        allow_prefix=allow_prefix, expected_frames=expected_frames
    )
    embedded = manifest["raw_frame_diagnostics"]
    if type(embedded) is not list:
        raise AuditFailure(f"{arm_id} embedded diagnostics must be a list")
    _validate_diagnostic_rows_shape(
        embedded, arm_id=arm_id, expected_raw_frames=expected_raw_frames
    )
    _validate_diagnostic_rows_shape(
        csv_rows, arm_id=arm_id, expected_raw_frames=expected_raw_frames
    )
    _strict_equal(csv_rows, embedded, label=f"{arm_id}:CSV_vs_manifest_diagnostics")
    if len(reconstructed_common) != expected_raw_frames:
        raise AuditFailure("independent raw reconstruction row count drift")
    for index, (observed, rebuilt) in enumerate(zip(embedded, reconstructed_common)):
        observed_common = {field: observed[field] for field in COMMON_DIAGNOSTIC_FIELDS}
        _strict_equal(
            observed_common,
            rebuilt,
            label=f"{arm_id}:raw_reconstruction[{index}]",
        )
    streams = manifest["diagnostics_streams"]
    expected_streams = {
        "row_count": expected_raw_frames,
        "raw_schedule_sha256": core._diagnostics_schedule_stream(embedded),
        "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(embedded),
        "common_row_fields": list(COMMON_DIAGNOSTIC_FIELDS),
    }
    _strict_equal(streams, expected_streams, label=f"{arm_id}.diagnostics_streams")
    metrics = manifest["metrics"]
    expected_metrics = {
        "raw_frames_processed": len(embedded),
        "published_frames": sum(bool(row["published"]) for row in embedded),
        "raw_births": sum(int(row["births"]) for row in embedded),
        "raw_drops": sum(int(row["dropped"]) for row in embedded),
        "adaptive_clahe_frames": sum(
            bool(row["adaptive_clahe_applied"]) for row in embedded
        ),
        "detector_candidates": sum(
            int(row["detector_candidates"]) for row in embedded
        ),
    }
    for key, expected in expected_metrics.items():
        if type(metrics[key]) is not type(expected) or metrics[key] != expected:
            raise AuditFailure(f"{arm_id}.metrics.{key} does not match diagnostics")
    detector = manifest["code_artifacts"]["detector_runtime"]
    detector_runtime = detector.get("runtime") if type(detector) is dict else None
    if type(detector_runtime) is not dict:
        raise AuditFailure(f"{arm_id} detector runtime metadata is absent")
    expected_calls = sum(bool(row["detector_called"]) for row in embedded)
    expected_candidates = sum(int(row["detector_candidates"]) for row in embedded)
    if (
        type(detector_runtime.get("detect_calls")) is not int
        or detector_runtime["detect_calls"] != expected_calls
    ):
        raise AuditFailure(f"{arm_id} detector runtime call count mismatch")
    if (
        type(detector_runtime.get("candidate_total")) is not int
        or detector_runtime["candidate_total"] != expected_candidates
    ):
        raise AuditFailure(f"{arm_id} detector runtime candidate total mismatch")
    _strict_equal(
        detector_runtime.get("input_shapes"),
        list(image_shapes_hw),
        label=f"{arm_id}.detector_runtime.input_shapes",
    )
    observed_shapes = detector_runtime.get("gray_input_shapes_hw", detector_runtime.get("input_shapes_hw"))
    _strict_equal(
        observed_shapes,
        list(image_shapes_hw),
        label=f"{arm_id}.detector_runtime.input_shapes_hw",
    )
    if arm_id == XFEAT_ARM:
        matched_runtime = detector.get("matched_runtime_contract")
        _strict_equal(
            matched_runtime,
            {
                "device": "cpu",
                "torch_num_threads": 1,
                "torch_num_interop_threads": 1,
                "deterministic_algorithms": True,
            },
            label=f"{arm_id}.matched_runtime_contract",
        )
        torch_contract = _require_exact_keys(
            detector.get("matched_torch_binary_contract"),
            XFEAT_TORCH_BINARY_KEYS,
            label=f"{arm_id}.matched_torch_binary_contract",
        )
        for label, identity in torch_contract.items():
            _validate_identity_claim(
                identity, label=f"{arm_id}.matched_torch_binary_contract.{label}"
            )
        torch_python_contract = _require_exact_keys(
            detector.get("matched_torch_python_contract"),
            XFEAT_TORCH_PYTHON_KEYS,
            label=f"{arm_id}.matched_torch_python_contract",
        )
        for label, identity in torch_python_contract.items():
            _validate_identity_claim(
                identity, label=f"{arm_id}.matched_torch_python_contract.{label}"
            )
        torch_import_origins = _require_exact_keys(
            detector.get("matched_torch_import_origin_contract"),
            XFEAT_TORCH_IMPORT_KEYS,
            label=f"{arm_id}.matched_torch_import_origin_contract",
        )
        expected_import_origins = (
            matched_xfeat.static_torch_import_origin_contract()
        )
        for label, item in torch_import_origins.items():
            _require_exact_keys(
                item,
                {"module", "file", "spec_origin"},
                label=f"{arm_id}.matched_torch_import_origin_contract.{label}",
            )
            _strict_equal(
                item,
                expected_import_origins[label],
                label=(
                    f"{arm_id}.matched_torch_import_origin_contract."
                    f"{label}:live"
                ),
            )
        tqdm_imports = _require_exact_keys(
            detector.get("matched_tqdm_import_contract"),
            XFEAT_TQDM_KEYS,
            label=f"{arm_id}.matched_tqdm_import_contract",
        )
        expected_tqdm = matched_xfeat.static_tqdm_import_contract()
        for label, item in tqdm_imports.items():
            _strict_equal(
                item,
                expected_tqdm[label],
                label=f"{arm_id}.matched_tqdm_import_contract.{label}:live",
            )
        _strict_equal(
            detector.get("optional_matcher_dependency_contract"),
            matched_xfeat.expected_optional_matcher_dependency_contract(),
            label=f"{arm_id}.optional_matcher_dependency_contract",
        )
        tensor_shapes = detector_runtime.get("rgb_tensor_input_shapes_bchw")
        expected_tensor_shapes = [
            [1, 3, int(shape[0]), int(shape[1])] for shape in image_shapes_hw
        ]
        _strict_equal(
            tensor_shapes,
            expected_tensor_shapes,
            label=f"{arm_id}.detector_runtime.tensor_shapes",
        )
        timing = _require_exact_keys(
            detector_runtime.get("detect_ms"),
            {"warmup", "steady_state", "all"},
            label=f"{arm_id}.detector_runtime.detect_ms",
        )
        expected_counts = {
            "warmup": min(expected_calls, 1),
            "steady_state": max(expected_calls - 1, 0),
            "all": expected_calls,
        }
        for label, count in expected_counts.items():
            distribution = _require_exact_keys(
                timing[label],
                {"count", "median_ms", "p90_ms", "total_ms"},
                label=f"{arm_id}.detect_ms.{label}",
            )
            if distribution["count"] != count:
                raise AuditFailure(f"{arm_id} detect timing count mismatch: {label}")
            if count == 0:
                _strict_equal(
                    distribution,
                    {"count": 0, "median_ms": None, "p90_ms": None, "total_ms": 0.0},
                    label=f"{arm_id}.detect_ms.{label}:empty",
                )
            else:
                for field in ("median_ms", "p90_ms", "total_ms"):
                    value = distribution[field]
                    if type(value) is not float or not math.isfinite(value) or value < 0.0:
                        raise AuditFailure(f"{arm_id} detect timing {label}.{field} invalid")
    else:
        if detector_runtime.get("opencv_version") != core.EXPECTED_OPENCV_VERSION:
            raise AuditFailure("GFTT detector OpenCV runtime mismatch")
        if detector_runtime.get("numpy_version") != core.EXPECTED_NUMPY_VERSION:
            raise AuditFailure("GFTT detector NumPy runtime mismatch")
        _validate_detector_metadata_schema(detector, arm_id=GFTT_ARM)
    return {
        "pass": True,
        "row_count": len(embedded),
        "detector_calls": expected_calls,
        "detector_candidates": expected_candidates,
        "raw_schedule_sha256": expected_streams["raw_schedule_sha256"],
        "raw_and_processed_pixels_sha256": expected_streams[
            "raw_and_processed_pixels_sha256"
        ],
    }


def _serialized_nonfeature(
    path: Path,
    feature_topic: str,
    cutoff_record_stamp_ns: int | None = None,
) -> dict[str, object]:
    def read_stream() -> dict[str, object]:
        digest = hashlib.sha256()
        topics: dict[str, dict[str, object]] = {}
        count = 0
        with rosbag.Bag(str(path), "r") as bag:
            for topic, message, stamp, connection in bag.read_messages(
                return_connection_header=True
            ):
                if (
                    cutoff_record_stamp_ns is not None
                    and int(stamp.to_nsec()) > cutoff_record_stamp_ns
                ):
                    break
                if topic == feature_topic:
                    continue
                buffer = io.BytesIO()
                message.serialize(buffer)
                raw = buffer.getvalue()
                type_name = str(getattr(message, "_type", ""))
                md5 = str(getattr(message, "_md5sum", ""))
                topic_bytes = str(topic).encode()
                type_bytes = type_name.encode()
                md5_bytes = md5.encode()
                framed = (
                    struct.pack("<I", len(topic_bytes)) + topic_bytes
                    + struct.pack("<I", len(type_bytes)) + type_bytes
                    + struct.pack("<I", len(md5_bytes)) + md5_bytes
                    + struct.pack("<qQ", int(stamp.to_nsec()), len(raw)) + raw
                )
                digest.update(framed)
                state = topics.setdefault(
                    str(topic), {"count": 0, "digest": hashlib.sha256()}
                )
                state["count"] = int(state["count"]) + 1
                state["digest"].update(framed)
                count += 1
        return {
            "count": count,
            "sha256": digest.hexdigest(),
            "topics": {
                key: {
                    "count": value["count"],
                    "sha256": value["digest"].hexdigest(),
                }
                for key, value in sorted(topics.items())
            },
        }

    return core._call_trusted_rosbag_scoped(read_stream)


def _feature_contract(
    source_bag: Path,
    candidate_bag: Path,
    camera_yaml: Path,
    *,
    arm_id: str,
    feature_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    raw_diagnostics: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    reference = core._call_trusted_rosbag_scoped(
        audit_base.load_feature_frames, source_bag, feature_topic
    )
    candidate = core._call_trusted_rosbag_scoped(
        audit_base.load_feature_frames, candidate_bag, feature_topic
    )
    if allow_prefix:
        reference = reference[:expected_frames]
    camera = audit_base.load_camera_model(camera_yaml)
    violations: list[str] = []
    if len(candidate) != expected_frames or len(reference) != expected_frames:
        violations.append("frame_count")
    expected_provenance = EXPECTED_ARMS[arm_id]
    retired: set[int] = set()
    seen: set[int] = set()
    previous_ids: set[int] = set()
    previous = None
    max_seen_id = -1
    published_diagnostics: list[Mapping[str, object]] = []
    if raw_diagnostics is not None:
        published_diagnostics = [row for row in raw_diagnostics if row["published"]]
        if len(published_diagnostics) != expected_frames:
            violations.append("diagnostics_published_frame_count")
    max_normalized_error = 0.0
    max_velocity_error = 0.0
    for index, (ref, frame) in enumerate(zip(reference, candidate)):
        diagnostic = (
            published_diagnostics[index]
            if index < len(published_diagnostics)
            else None
        )
        if (
            ref.record_stamp_ns,
            ref.header_stamp_ns,
            ref.header_seq,
            ref.header_frame_id,
        ) != (
            frame.record_stamp_ns,
            frame.header_stamp_ns,
            frame.header_seq,
            frame.header_frame_id,
        ):
            violations.append(f"frame{index}:schedule")
        if frame.schema != EXPECTED_CHANNELS:
            violations.append(f"frame{index}:schema")
        if frame.decode_violations:
            violations.append(f"frame{index}:decode")
        if len(frame.ids) > core.FEATURE_CAP:
            violations.append(f"frame{index}:count")
        if diagnostic is not None and len(frame.ids) != diagnostic["output_tracks"]:
            violations.append(f"frame{index}:diagnostics_output_tracks")
        ids = [int(item) for item in frame.ids]
        current = set(ids)
        if any(item < 0 for item in ids):
            violations.append(f"frame{index}:negative_id")
        if len(current) != len(ids):
            violations.append(f"frame{index}:duplicate_id")
        if ids != sorted(ids):
            violations.append(f"frame{index}:id_serialization_order")
        if current & retired:
            violations.append(f"frame{index}:revival")
        new_ids = sorted(current - seen)
        # IDs may legitimately have gaps: births on an unpublished raw frame
        # can die before their first publication.  They may never backfill or
        # reuse an ID below one already observed, however.
        if new_ids and new_ids[0] <= max_seen_id:
            violations.append(f"frame{index}:new_id_not_monotonic")
        if new_ids:
            max_seen_id = new_ids[-1]
        if diagnostic is not None:
            raw_row_index = int(diagnostic["raw_index"])
            cumulative_births = sum(
                int(row["births"])
                for row in raw_diagnostics[: raw_row_index + 1]
            )
            if ids and max(ids) >= cumulative_births:
                violations.append(f"frame{index}:id_not_bounded_by_raw_births")
        retired.update(previous_ids - current)
        seen.update(current)
        for name, value in {
            "camera_id": 0.0,
            "gx": 0.0,
            "gy": 0.0,
            "gz": 0.0,
            "quality": 1.0,
            "sigma": 1.0,
            **expected_provenance,
        }.items():
            values = np.asarray(frame.channels.get(name, ()), dtype=np.float64)
            if values.shape != (len(ids),) or not np.all(values == value):
                violations.append(f"frame{index}:{name}")
        if not np.all(frame.point_z == 1.0):
            violations.append(f"frame{index}:point_z")
        if not (
            np.isfinite(frame.pixels).all()
            and np.isfinite(frame.normalized).all()
            and np.isfinite(frame.velocities).all()
        ):
            violations.append(f"frame{index}:nonfinite")
        if len(ids):
            expected_norm = camera.undistort_points(frame.pixels)
            error = np.linalg.norm(expected_norm - frame.normalized, axis=1)
            max_normalized_error = max(max_normalized_error, float(np.max(error)))
            if max_normalized_error > NORMALIZED_TOLERANCE:
                violations.append(f"frame{index}:normalized")
        expected_velocity = np.zeros_like(frame.velocities, dtype=np.float64)
        if previous is not None:
            dt = (frame.header_stamp_ns - previous.header_stamp_ns) * 1e-9
            previous_by_id = {int(fid): pos for pos, fid in enumerate(previous.ids)}
            for pos, fid in enumerate(frame.ids):
                old = previous_by_id.get(int(fid))
                if old is not None:
                    expected_velocity[pos] = (
                        frame.normalized[pos] - previous.normalized[old]
                    ) / dt
        if len(ids):
            if previous is None:
                new_positions = list(range(len(ids)))
            else:
                previous_id_set = {int(item) for item in previous.ids}
                new_positions = [
                    pos for pos, fid in enumerate(ids) if fid not in previous_id_set
                ]
            if new_positions and not np.all(
                frame.velocities[np.asarray(new_positions, dtype=np.int64)] == 0.0
            ):
                violations.append(f"frame{index}:birth_velocity_not_exact_zero")
            velocity_error = np.linalg.norm(frame.velocities - expected_velocity, axis=1)
            max_velocity_error = max(max_velocity_error, float(np.max(velocity_error)))
            if max_velocity_error > VELOCITY_TOLERANCE:
                violations.append(f"frame{index}:velocity")
        previous_ids = current
        previous = frame
    return {
        "pass": not violations,
        "violations": violations[:60],
        "frame_count": len(candidate),
        "unique_id_count": len(seen),
        "max_normalized_error": max_normalized_error,
        "max_velocity_error": max_velocity_error,
        "metrics": {
            "observations": int(sum(len(frame.ids) for frame in candidate)),
            "observations_per_frame_min": int(
                min((len(frame.ids) for frame in candidate), default=0)
            ),
            "observations_per_frame_median": float(
                np.median([len(frame.ids) for frame in candidate])
                if candidate
                else 0.0
            ),
            "observations_per_frame_max": int(
                max((len(frame.ids) for frame in candidate), default=0)
            ),
            "unique_ids": len(seen),
            "published_first_occurrences": len(seen),
            "published_continuations": int(
                sum(len(frame.ids) for frame in candidate) - len(seen)
            ),
        },
    }


def audit_pair(
    *,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    xfeat_bag: Path,
    xfeat_manifest: Path,
    xfeat_diagnostics: Path,
    xfeat_legacy_manifest: Path,
    xfeat_work_directory: Path,
    xfeat_attempt: Path,
    gftt_bag: Path,
    gftt_manifest: Path,
    gftt_diagnostics: Path,
    gftt_legacy_manifest: Path,
    gftt_work_directory: Path,
    gftt_attempt: Path,
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
    pre_run_start_receipt: Path,
    post_run_pair_seal: Path,
) -> dict[str, object]:
    runtime = _audit_runtime_observation()
    freeze = _load_canonical_object(freeze_json, label="pre-run freeze")
    arm_paths = {
        XFEAT_ARM: {
            "feature_bag": xfeat_bag,
            "manifest_json": xfeat_manifest,
            "diagnostics_csv": xfeat_diagnostics,
            "legacy_primitive_manifest": xfeat_legacy_manifest,
            "private_work_directory": xfeat_work_directory,
            "attempt_json": xfeat_attempt,
        },
        GFTT_ARM: {
            "feature_bag": gftt_bag,
            "manifest_json": gftt_manifest,
            "diagnostics_csv": gftt_diagnostics,
            "legacy_primitive_manifest": gftt_legacy_manifest,
            "private_work_directory": gftt_work_directory,
            "attempt_json": gftt_attempt,
        },
    }
    freeze_gate = _validate_freeze(
        freeze,
        freeze_json=freeze_json,
        runtime=runtime,
        source_bag=source_bag,
        raw_bag=raw_bag,
        camera_yaml=camera_yaml,
        arm_paths=arm_paths,
        audit_paths={
            "pre_run_start_receipt": pre_run_start_receipt,
            "post_run_pair_seal": post_run_pair_seal,
        },
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    launcher_gate = _validate_launcher_receipts(freeze_gate)
    xmanifest = _load_manifest(xfeat_manifest)
    gmanifest = _load_manifest(gftt_manifest)
    start_receipt = _load_canonical_object(
        pre_run_start_receipt, label="pre-run start receipt"
    )
    _strict_equal(
        start_receipt,
        _pre_run_start_receipt_payload(
            freeze_json=freeze_json,
            gate=freeze_gate,
            arm_paths=arm_paths,
        ),
        label="pre-run start receipt exact replay",
    )
    for arm_id, manifest, attempt_path in (
        (XFEAT_ARM, xmanifest, xfeat_attempt),
        (GFTT_ARM, gmanifest, gftt_attempt),
    ):
        frozen_arm = freeze_gate["arms"][arm_id]
        _validate_manifest_exact(
            manifest,
            expected=frozen_arm["manifest_template"],
            expected_attempt=frozen_arm["attempt"],
            attempt_path=attempt_path,
            arm_id=arm_id,
            paths=frozen_arm["paths"],
            locked_inputs=freeze_gate["locked_inputs"],
            expected_common=freeze_gate["common_contract"],
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        )
    xlegacy_gate = _validate_legacy_manifest(
        arm_id=XFEAT_ARM,
        legacy_path=xfeat_legacy_manifest,
        feature_bag=xfeat_bag,
        matched_manifest=xmanifest,
        allow_prefix=allow_prefix,
    )
    glegacy_gate = _validate_legacy_manifest(
        arm_id=GFTT_ARM,
        legacy_path=gftt_legacy_manifest,
        feature_bag=gftt_bag,
        matched_manifest=gmanifest,
        allow_prefix=allow_prefix,
    )
    manifest_gate = _manifest_pair_contract(
        xmanifest,
        gmanifest,
        expected_left=freeze_gate["arms"][XFEAT_ARM]["manifest_template"],
        expected_right=freeze_gate["arms"][GFTT_ARM]["manifest_template"],
        allowed_pair_scalar_differences=freeze_gate[
            "allowed_pair_scalar_differences"
        ],
        required_pair_scalar_differences=freeze_gate[
            "required_pair_scalar_differences"
        ],
    )
    xdiag = _read_diagnostics(xfeat_diagnostics)
    gdiag = _read_diagnostics(gftt_diagnostics)
    rebuilt_common, reconstruction = _reconstruct_common_diagnostics(
        source_bag=source_bag,
        raw_bag=raw_bag,
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    xdiag_gate = _validate_diagnostics_binding(
        arm_id=XFEAT_ARM,
        manifest=xmanifest,
        csv_rows=xdiag,
        reconstructed_common=rebuilt_common,
        image_shapes_hw=reconstruction["image_shapes_hw"],
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    gdiag_gate = _validate_diagnostics_binding(
        arm_id=GFTT_ARM,
        manifest=gmanifest,
        csv_rows=gdiag,
        reconstructed_common=rebuilt_common,
        image_shapes_hw=reconstruction["image_shapes_hw"],
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    diagnostics_gate = _diagnostics_pair(xdiag, gdiag)
    cutoff = xmanifest["prefix"]["cutoff_feature_record_stamp_ns"]
    _strict_equal(
        cutoff,
        gmanifest["prefix"]["cutoff_feature_record_stamp_ns"],
        label="pair prefix cutoff",
    )
    xnon = _serialized_nonfeature(xfeat_bag, feature_topic, cutoff)
    gnon = _serialized_nonfeature(gftt_bag, feature_topic, cutoff)
    snon = _serialized_nonfeature(source_bag, feature_topic, cutoff)
    producer_nonfeature = core._call_trusted_rosbag_scoped(
        core.primitive._nonfeature_digest,
        source_bag,
        feature_topic,
        cutoff,
    )
    for manifest, arm_id in ((xmanifest, XFEAT_ARM), (gmanifest, GFTT_ARM)):
        _strict_equal(
            manifest["nonfeature_stream_before"],
            producer_nonfeature,
            label=f"{arm_id}.nonfeature_before:locked_source",
        )
        _strict_equal(
            manifest["nonfeature_stream_after"],
            producer_nonfeature,
            label=f"{arm_id}.nonfeature_after:locked_source",
        )
    nonfeature_gate = {
        "pass": xnon == gnon == snon,
        "source": snon,
        "xfeat": xnon,
        "gftt": gnon,
        "producer_format": producer_nonfeature,
    }
    xfeature = _feature_contract(
        source_bag,
        xfeat_bag,
        camera_yaml,
        arm_id=XFEAT_ARM,
        feature_topic=feature_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        raw_diagnostics=xdiag,
    )
    gfeature = _feature_contract(
        source_bag,
        gftt_bag,
        camera_yaml,
        arm_id=GFTT_ARM,
        feature_topic=feature_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        raw_diagnostics=gdiag,
    )
    for feature_gate, manifest, arm_id in (
        (xfeature, xmanifest, XFEAT_ARM),
        (gfeature, gmanifest, GFTT_ARM),
    ):
        for key, expected in feature_gate["metrics"].items():
            if (
                type(manifest["metrics"].get(key)) is not type(expected)
                or manifest["metrics"].get(key) != expected
            ):
                raise AuditFailure(f"{arm_id}.metrics.{key} does not match feature bag")
    _strict_equal(
        _audit_runtime_observation(),
        runtime,
        label="post-run audit runtime after all rosbag reconstruction",
    )
    gates = {
        "manifest_pair": manifest_gate,
        "freeze_and_locked_inputs": {"pass": True},
        "one_shot_launcher_receipts": {
            "pass": True,
            "arms": launcher_gate,
        },
        "independent_raw_reconstruction": {"pass": True, **reconstruction},
        "xfeat_diagnostics_manifest_csv_raw_binding": xdiag_gate,
        "gftt_diagnostics_manifest_csv_raw_binding": gdiag_gate,
        "xfeat_legacy_transport_evidence": xlegacy_gate,
        "gftt_legacy_transport_evidence": glegacy_gate,
        "processed_image_and_schedule_pair": diagnostics_gate,
        "nonfeature_exact": nonfeature_gate,
        "xfeat_feature_contract": xfeature,
        "gftt_feature_contract": gfeature,
    }
    passed = all(bool(item.get("pass")) for item in gates.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "scientific_role": (
            "post_result_development_exploratory_detector_birth_ablation"
        ),
        "allow_prefix_nonformal": bool(allow_prefix),
        "expected_published_frames": expected_frames,
        "inputs": {
            **freeze_gate["locked_inputs"],
            "pre_run_freeze": _file_identity(freeze_json, label="pre-run freeze"),
            "infrastructure_incident": freeze_gate["infrastructure_incident"],
            "artifact_filesystem_contract": freeze_gate[
                "artifact_filesystem_contract"
            ],
            "audit_code_closure": _audit_code_closure(),
        },
        "post_run_outcome_seal": {
            "pre_run_freeze": _file_identity(freeze_json, label="pre-run freeze"),
            "pre_run_start_receipt": _file_identity(
                pre_run_start_receipt, label="pre-run start receipt"
            ),
            "arms": {
                XFEAT_ARM: {
                    "feature_bag": _file_identity(xfeat_bag, label="XFeat feature bag"),
                    "manifest": _file_identity(xfeat_manifest, label="XFeat manifest"),
                    "diagnostics": _file_identity(xfeat_diagnostics, label="XFeat diagnostics"),
                    "legacy_primitive_manifest": _file_identity(
                        xfeat_legacy_manifest, label="XFeat legacy manifest"
                    ),
                    "attempt": _file_identity(xfeat_attempt, label="XFeat attempt"),
                    "launcher_start_receipt": launcher_gate[XFEAT_ARM]["start_receipt"],
                    "launcher_rc_receipt": launcher_gate[XFEAT_ARM]["rc_receipt"],
                },
                GFTT_ARM: {
                    "feature_bag": _file_identity(gftt_bag, label="GFTT feature bag"),
                    "manifest": _file_identity(gftt_manifest, label="GFTT manifest"),
                    "diagnostics": _file_identity(gftt_diagnostics, label="GFTT diagnostics"),
                    "legacy_primitive_manifest": _file_identity(
                        gftt_legacy_manifest, label="GFTT legacy manifest"
                    ),
                    "attempt": _file_identity(gftt_attempt, label="GFTT attempt"),
                    "launcher_start_receipt": launcher_gate[GFTT_ARM]["start_receipt"],
                    "launcher_rc_receipt": launcher_gate[GFTT_ARM]["rc_receipt"],
                },
            },
        },
        "gates": gates,
        "claim_boundary": {
            "detector_birth_source_only_within_this_frozen_carrier": True,
            "whole_slam_superiority": False,
            "confirmatory": False,
            "statistical_significance": False,
        },
    }


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("check-start", "audit"), default="audit")
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--freeze-json", required=True)
    parser.add_argument("--xfeat-bag", required=True)
    parser.add_argument("--xfeat-manifest", required=True)
    parser.add_argument("--xfeat-diagnostics", required=True)
    parser.add_argument("--xfeat-legacy-manifest", required=True)
    parser.add_argument("--xfeat-work-directory", required=True)
    parser.add_argument("--xfeat-attempt", required=True)
    parser.add_argument("--gftt-bag", required=True)
    parser.add_argument("--gftt-manifest", required=True)
    parser.add_argument("--gftt-diagnostics", required=True)
    parser.add_argument("--gftt-legacy-manifest", required=True)
    parser.add_argument("--gftt-work-directory", required=True)
    parser.add_argument("--gftt-attempt", required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC_DEFAULT)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--allow-prefix", action="store_true")
    parser.add_argument("--expected-published-frames", type=_positive, required=True)
    parser.add_argument("--pre-run-start-receipt", required=True)
    parser.add_argument("--post-run-audit-json", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pre_run_start_receipt = _canonical_future_path(
            Path(args.pre_run_start_receipt), label="pre-run start receipt"
        )
        post_run_pair_seal = _canonical_future_path(
            Path(args.post_run_audit_json), label="post-run pair seal"
        )
        if pre_run_start_receipt == post_run_pair_seal:
            raise AuditFailure("pre-run start and post-run seal paths alias")
        output = (
            pre_run_start_receipt
            if args.action == "check-start"
            else post_run_pair_seal
        )
    except (AuditFailure, OSError) as exc:
        print(f"AUDIT_ERROR:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    descriptor = None
    try:
        descriptor = os.open(
            str(output),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o444,
        )
        os.fchmod(descriptor, 0o444)
        output_stat = os.fstat(descriptor)
        if not stat.S_ISREG(output_stat.st_mode) or int(output_stat.st_nlink) != 1:
            raise AuditFailure("audit output reservation is not a single-link regular file")
        common_arguments = {
            "freeze_json": Path(args.freeze_json).resolve(strict=True),
            "source_bag": Path(args.source_feature_bag).resolve(strict=True),
            "raw_bag": Path(args.raw_image_bag).resolve(strict=True),
            "camera_yaml": Path(args.camera_yaml).resolve(strict=True),
            "xfeat_bag": Path(args.xfeat_bag).resolve(strict=args.action == "audit"),
            "xfeat_manifest": Path(args.xfeat_manifest).resolve(strict=args.action == "audit"),
            "xfeat_diagnostics": Path(args.xfeat_diagnostics).resolve(strict=args.action == "audit"),
            "xfeat_legacy_manifest": Path(args.xfeat_legacy_manifest).resolve(strict=args.action == "audit"),
            "xfeat_work_directory": Path(args.xfeat_work_directory).resolve(strict=args.action == "audit"),
            "xfeat_attempt": Path(args.xfeat_attempt).resolve(strict=args.action == "audit"),
            "gftt_bag": Path(args.gftt_bag).resolve(strict=args.action == "audit"),
            "gftt_manifest": Path(args.gftt_manifest).resolve(strict=args.action == "audit"),
            "gftt_diagnostics": Path(args.gftt_diagnostics).resolve(strict=args.action == "audit"),
            "gftt_legacy_manifest": Path(args.gftt_legacy_manifest).resolve(strict=args.action == "audit"),
            "gftt_work_directory": Path(args.gftt_work_directory).resolve(strict=args.action == "audit"),
            "gftt_attempt": Path(args.gftt_attempt).resolve(strict=args.action == "audit"),
            "feature_topic": args.feature_topic,
            "image_topic": args.image_topic,
            "allow_prefix": bool(args.allow_prefix),
            "expected_frames": int(args.expected_published_frames),
            "pre_run_start_receipt": pre_run_start_receipt,
            "post_run_pair_seal": post_run_pair_seal,
        }
        result = (
            check_pre_run_start(**common_arguments)
            if args.action == "check-start"
            else audit_pair(**common_arguments)
        )
        encoded = _canonical_bytes(result)
        _replace_reserved_fd_payload(descriptor, encoded)
        print(_canonical_bytes({"status": result["status"], "output": str(output)}).decode().rstrip())
        return 0 if result["pass"] else 1
    except Exception as exc:
        if descriptor is not None:
            failure = {
                "schema_version": SCHEMA_VERSION,
                "status": "ERROR",
                "pass": False,
                "scientific_role": (
                    "post_result_development_exploratory_detector_birth_ablation"
                ),
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "claim_boundary": {
                    "contract_pass": False,
                    "output_namespace_consumed_no_retry": True,
                },
            }
            try:
                _replace_reserved_fd_payload(descriptor, _canonical_bytes(failure))
            except BaseException as write_exc:
                print(
                    f"AUDIT_RECEIPT_WRITE_ERROR:{type(write_exc).__name__}:{write_exc}",
                    file=sys.stderr,
                )
        print(f"AUDIT_ERROR:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
