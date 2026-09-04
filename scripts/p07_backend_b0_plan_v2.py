#!/usr/bin/env python3
"""Pure, additive core plan for the corrected P07 B0 inputs.

This module has no filesystem mutations or network effects.  Standalone
validation read-verifies the exact frozen backend queue CSV so queue rows are
anchored outside the self-hashed core.  It deliberately does not publish a
formal artifact and does not authorize materialization or VINS.  A later
formal wrapper must validate and bind the v1 plan, checksum overlay, queue,
review/adoption authorities, and materializer implementation.

The core reuses the validated v1 AQUALOC and AFRL recipes verbatim.  It only
supersedes the three v1 NTNU full-bag playback recipes with audited, closed
record-time fan-out recipes whose products are replayed as whole 45-second
bags (there is no second 45/90/135-second playback offset).
"""

from __future__ import annotations

import copy
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

try:
    from scripts import build_p07_backend_b0_materialization_lock_v1 as v1_plan
    from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as hf_correction
    from scripts import p07_backend_b0_legacy_recipe_authority_v1 as legacy_recipe_authority
    from scripts import p07_ntnu_window_fanout_v1 as ntnu_fanout
except ModuleNotFoundError:  # direct ``python scripts/...`` import
    import build_p07_backend_b0_materialization_lock_v1 as v1_plan  # type: ignore
    import build_p07_backend_hf_checksum_semantics_correction_v1 as hf_correction  # type: ignore
    import p07_backend_b0_legacy_recipe_authority_v1 as legacy_recipe_authority  # type: ignore
    import p07_ntnu_window_fanout_v1 as ntnu_fanout  # type: ignore


SCHEMA_VERSION = "isj-p07-backend-b0-core-plan-v2"
STATUS = "CORE_VALIDATED_NOT_FORMAL_AND_NOT_EXECUTION_AUTHORITY"
SELF_HASH_FIELD = "core_plan_hash"
OUTCOME_BOUNDARY = "B0_INPUT_PLANNING_ONLY_NO_VINS_APE_RPE_TRAJECTORY"

B0_ARM = "B0_native_vins_origin_v1"
B1_ARM = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
ARMS = (B0_ARM, B1_ARM, P_ARM, M_ARM)
REPLAY_INDICES = (1, 2, 3)

NTNU_SOURCE_PATH = (
    "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_6/fjord_6.bag"
)
_NTNU_HF_SCOPE = tuple(
    spec for spec in hf_correction.SCOPE_SPECS
    if spec.local_relative == NTNU_SOURCE_PATH
)
if len(_NTNU_HF_SCOPE) != 1:
    raise RuntimeError("HF correction scope lost the unique NTNU fjord_6 authority")
_NTNU_HF_SPEC = _NTNU_HF_SCOPE[0]
NTNU_SOURCE_CONTENT_SHA256 = _NTNU_HF_SPEC.lfs_oid
NTNU_SOURCE_XET_HASH = _NTNU_HF_SPEC.xet_hash
NTNU_SOURCE_SIZE_BYTES = _NTNU_HF_SPEC.size_bytes
NTNU_RECORD_T0_NS = 1_700_603_707_886_577_184
NTNU_CAMERA_TOPIC = "/alphasense_driver_ros/cam0"
NTNU_IMU_TOPIC = "/alphasense_driver_ros/imu"
NTNU_BOUNDARY_RULE = "ROS1_VIEW_RECORD_TIME_CLOSED_INTERVAL"

AFRL_RAW_PATH = "datasets/full_downloads/afrl_hf/ros1_bags/bus_outside.bag"
_AFRL_HF_SCOPE = tuple(
    spec for spec in hf_correction.SCOPE_SPECS
    if spec.local_relative == AFRL_RAW_PATH
)
if len(_AFRL_HF_SCOPE) != 1:
    raise RuntimeError("HF correction scope lost the unique AFRL bus authority")
_AFRL_HF_SPEC = _AFRL_HF_SCOPE[0]
AFRL_RAW_CONTENT_SHA256 = _AFRL_HF_SPEC.lfs_oid
AFRL_RAW_XET_HASH = _AFRL_HF_SPEC.xet_hash
AFRL_RAW_SIZE_BYTES = _AFRL_HF_SPEC.size_bytes
AFRL_TARGET_PATH = "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag"
AFRL_BUS_CAMCHAIN_PATH = (
    "datasets/full_downloads/afrl_hf/camera_imu_parameters/"
    "camchain_bus_outside.yaml"
)
AFRL_BUS_CAMCHAIN_SHA256 = (
    "61fe329f4d0938db73b697f2e03b7ac9ebbf76f4a84c0843573f5c0b4144cda1"
)
AFRL_IMU_PATH = "datasets/full_downloads/afrl_hf/camera_imu_parameters/imu.yaml"
AFRL_IMU_SHA256 = (
    "07c9a4377133d6f9ba2d91c29dbcbfbb5d8b070c6005d47fb947ff70a1f236a5"
)

EFFECTIVE_RESOLVER_SCHEMA = "isj-p07-backend-effective-checksum-resolver-v1"
EFFECTIVE_DIGEST_AUTHORITY = (
    "FROZEN_OFFICIAL_API_LFS_OID_PLUS_MATCHING_LOCAL_FULL_SHA256"
)
MATERIALIZATION_ONLY_ROLE = (
    "MATERIALIZATION_PROVENANCE_ONLY_NOT_RUNTIME_REPLAY_INPUT"
)

# These four literals are intentional import-time tripwires.  The values used
# by the plan above come directly from SCOPE_SPECS; the assertions make a
# correction-source edit visible instead of silently changing B0 science.
for _label, _actual, _authoritative in (
    ("NTNU historical Xet", NTNU_SOURCE_XET_HASH, "51a31fb3b019ad3168f776ec579e241c3aa57d6b5dd5e3710d5d918de6650a69"),
    ("NTNU effective content", NTNU_SOURCE_CONTENT_SHA256, "3ef9093f47209e900c0367ad8924b71974c903857dda63349b52d00aeba46d77"),
    ("AFRL historical Xet", AFRL_RAW_XET_HASH, "96e9bced3dc85700d3e2ba3da187b4a2c70395ba4fbb0df985c387da16c331eb"),
    ("AFRL effective content", AFRL_RAW_CONTENT_SHA256, "ff17bc711d71668c775fbe0de0cb9305a2e02969a42e996b994b7863df79b10d"),
):
    if _actual != _authoritative:
        raise RuntimeError("HF correction authoritative %s value drift" % _label)

V1_AUTHORITY_ENVELOPE_SCHEMA = "isj-p07-b0-v1-plan-authority-envelope-v1"
V1_AUTHORITY_ENVELOPE_HASH = "authority_envelope_hash"
REUSED_RECIPE_AUTHORITY_FIELD = "reused_recipe_authority_binding"
LEGACY_RECIPE_AUTHORITY_KIND = "VALIDATED_LEGACY_17_RECIPE_AUTHORITY_V1"
COMPLETE_V1_RECIPE_AUTHORITY_KIND = "COMPLETE_CANONICALLY_VALIDATED_V1_B0_PLAN"
REUSED_RECIPE_CONTENT_SCOPE = (
    "EXACT_16_AQUALOC_PLUS_1_AFRL_RECIPE_ARRAY_CANONICAL_JSON"
)
QUEUE_ROW_HASH_SCHEMA = "isj-p07-backend-immutable-queue-row-v1"
QUEUE_AUTHORITY_ENVELOPE_SCHEMA = "isj-p07-backend-queue-authority-envelope-v1"
QUEUE_AUTHORITY_ENVELOPE_HASH = "queue_authority_envelope_hash"
FROZEN_QUEUE_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv"
)
FROZEN_QUEUE_SHA256 = "2f6c71393e0b88de04ea750b99e7cb6c88e08e0906e1f55a2401b8ccdd554e11"
FROZEN_QUEUE_SIZE_BYTES = 471_028
ROOT = Path(__file__).resolve().parents[1]

_QUEUE_AUTHORITY_SENTINEL = object()

_AQUALOC_RAW_PATHS: Mapping[Tuple[str, str], str] = {
    ("aqualoc_archaeology", sequence): (
        "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
        "archaeo_sequence_%d_raw_data.tar.gz" % int(sequence[1:])
    )
    for sequence in ("A01", "A02", "A03", "A04", "A07", "A08", "A10")
}
_AQUALOC_RAW_PATHS = {
    **_AQUALOC_RAW_PATHS,
    **{
        ("aqualoc_harbor", sequence): (
            "datasets/full_downloads/aqualoc/Harbor_sites_sequences/"
            "harbor_sequence_%02d_raw_data.tar.gz" % int(sequence[1:])
        )
        for sequence in ("H01", "H02", "H03", "H04", "H05")
    },
    ("aqualoc_harbor", "H06"): (
        "datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz"
    ),
}



_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_WORKSPACE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


class B0CorePlanV2Error(RuntimeError):
    """The additive B0 v2 core is incomplete, drifted, or ambiguous."""


# These are the single audited NTNU constants used by the plan.  The fan-out
# materializer accepts these values as inputs; it must not maintain a second
# independent table.
NTNU_WINDOW_SPECS: Tuple[Mapping[str, Any], ...] = (
    {
        "window_id": "ntnu:fjord_6:0001",
        "window_start_s": "45",
        "window_end_s": "90",
        "target_path": (
            "datasets/p07_backend_b0_inputs/ntnu/fjord_6_0001_s45_d45.bag"
        ),
        "start_offset_ns": 45_000_000_000,
        "end_offset_ns": 90_000_000_000,
        "absolute_record_start_ns": 1_700_603_752_886_577_184,
        "absolute_record_end_ns": 1_700_603_797_886_577_184,
        "camera_record_first_ns": 1_700_603_752_914_501_792,
        "camera_record_last_ns": 1_700_603_797_864_780_480,
        "camera_header_evaluation_first_ns": 1_700_603_752_857_818_564,
        "camera_header_evaluation_last_ns": 1_700_603_797_807_323_202,
        "camera_count": 900,
        "imu_count": 8998,
    },
    {
        "window_id": "ntnu:fjord_6:0002",
        "window_start_s": "90",
        "window_end_s": "135",
        "target_path": (
            "datasets/p07_backend_b0_inputs/ntnu/fjord_6_0002_s90_d45.bag"
        ),
        "start_offset_ns": 90_000_000_000,
        "end_offset_ns": 135_000_000_000,
        "absolute_record_start_ns": 1_700_603_797_886_577_184,
        "absolute_record_end_ns": 1_700_603_842_886_577_184,
        "camera_record_first_ns": 1_700_603_797_914_808_992,
        "camera_record_last_ns": 1_700_603_842_863_863_488,
        "camera_header_evaluation_first_ns": 1_700_603_797_857_322_802,
        "camera_header_evaluation_last_ns": 1_700_603_842_806_847_552,
        "camera_count": 900,
        "imu_count": 9000,
    },
    {
        "window_id": "ntnu:fjord_6:0003",
        "window_start_s": "135",
        "window_end_s": "180",
        "target_path": (
            "datasets/p07_backend_b0_inputs/ntnu/fjord_6_0003_s135_d45.bag"
        ),
        "start_offset_ns": 135_000_000_000,
        "end_offset_ns": 180_000_000_000,
        "absolute_record_start_ns": 1_700_603_842_886_577_184,
        "absolute_record_end_ns": 1_700_603_887_886_577_184,
        "camera_record_first_ns": 1_700_603_842_913_566_816,
        "camera_record_last_ns": 1_700_603_887_863_993_632,
        "camera_header_evaluation_first_ns": 1_700_603_842_856_847_252,
        "camera_header_evaluation_last_ns": 1_700_603_887_806_385_749,
        "camera_count": 900,
        "imu_count": 8997,
    },
)


# Exact identity and window coordinates of the already frozen P07 selection.
# Values are normalized to integer-second strings to make CSV spelling (45 vs
# 45.0) irrelevant without weakening the scientific interval contract.
_FROZEN_WINDOW_ROWS: Tuple[Tuple[str, str, str, str, str, int], ...] = (
    ("afrl:bus_outside:0001", "afrl", "bus_outside", "45", "90", 565),
    ("aqualoc_archaeology:A01:0003", "aqualoc_archaeology", "A01", "135", "180", 900),
    ("aqualoc_archaeology:A01:0018", "aqualoc_archaeology", "A01", "810", "855", 900),
    ("aqualoc_archaeology:A02:0005", "aqualoc_archaeology", "A02", "225", "270", 900),
    ("aqualoc_archaeology:A03:0001", "aqualoc_archaeology", "A03", "45", "90", 900),
    ("aqualoc_archaeology:A04:0002", "aqualoc_archaeology", "A04", "90", "135", 900),
    ("aqualoc_archaeology:A07:0001", "aqualoc_archaeology", "A07", "45", "90", 900),
    ("aqualoc_archaeology:A07:0002", "aqualoc_archaeology", "A07", "90", "135", 900),
    ("aqualoc_archaeology:A08:0002", "aqualoc_archaeology", "A08", "90", "135", 900),
    ("aqualoc_archaeology:A10:0007", "aqualoc_archaeology", "A10", "315", "360", 900),
    ("aqualoc_archaeology:A10:0013", "aqualoc_archaeology", "A10", "585", "630", 900),
    ("aqualoc_harbor:H01:0000", "aqualoc_harbor", "H01", "0", "45", 900),
    ("aqualoc_harbor:H02:0007", "aqualoc_harbor", "H02", "315", "360", 900),
    ("aqualoc_harbor:H03:0001", "aqualoc_harbor", "H03", "45", "90", 900),
    ("aqualoc_harbor:H04:0003", "aqualoc_harbor", "H04", "135", "180", 900),
    ("aqualoc_harbor:H05:0002", "aqualoc_harbor", "H05", "90", "135", 900),
    ("aqualoc_harbor:H06:0000", "aqualoc_harbor", "H06", "0", "45", 900),
    ("ntnu:fjord_6:0001", "ntnu", "fjord_6", "45", "90", 900),
    ("ntnu:fjord_6:0002", "ntnu", "fjord_6", "90", "135", 900),
    ("ntnu:fjord_6:0003", "ntnu", "fjord_6", "135", "180", 900),
)

FROZEN_WINDOWS: Mapping[str, Mapping[str, Any]] = {
    item[0]: {
        "window_id": item[0],
        "dataset_family": item[1],
        "sequence": item[2],
        "window_start_s": item[3],
        "window_end_s": item[4],
        "input_frame_count": item[5],
    }
    for item in _FROZEN_WINDOW_ROWS
}

_NTNU_BY_WINDOW = {str(item["window_id"]): item for item in NTNU_WINDOW_SPECS}
_AQUALOC_FAMILIES = ("aqualoc_archaeology", "aqualoc_harbor")

_V1_BASE_RECIPE_KEYS = {
    "window_id",
    "dataset_family",
    "sequence",
    "runner_start",
    "runner_end_or_duration",
    "runner_unit",
    "target_path",
    "expected_sha256",
    "expected_size_bytes",
    "expected_topic_counts",
    "camera_topic",
    "disposition",
    "derivation_kind",
    "source_raw_path",
    "source_raw_sha256",
    "source_path_identity",
    "converter_argv_template",
    "evidence",
    "held_out_trajectory_outcome_read",
    "source_provenance_hash",
    "recipe_hash",
}


def canonical_json(value: object) -> str:
    """Return the canonical representation used for every core self-hash."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise B0CorePlanV2Error("core value is not finite canonical JSON") from error


def document_hash(payload: Mapping[str, Any], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _clone_json(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _number(value: Any, *, label: str) -> str:
    if isinstance(value, bool):
        raise B0CorePlanV2Error("%s is not numeric" % label)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise B0CorePlanV2Error("%s is not numeric" % label) from error
    if not parsed.is_finite():
        raise B0CorePlanV2Error("%s is not finite" % label)
    normalized = parsed.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise B0CorePlanV2Error("%s is not a positive integer" % label)
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise B0CorePlanV2Error("%s is not a positive integer" % label) from error
    if result <= 0 or str(value).strip() not in {str(result), "%s.0" % result}:
        raise B0CorePlanV2Error("%s is not a canonical positive integer" % label)
    return result


def _workspace_path(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or ".." in value.split("/")
        or not _SAFE_WORKSPACE_PATH.fullmatch(value)
    ):
        raise B0CorePlanV2Error("unsafe %s" % label)
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise B0CorePlanV2Error("invalid %s" % label)
    return value


_FILE_RECORD_KEYS = {"path", "sha256", "size_bytes"}
_AFRL_REPLAY_MANIFEST_EVIDENCE_KEYS = _FILE_RECORD_KEYS | {
    "classification",
    "vins_csv_absent",
    "vins_output_empty",
}
_STAT_IDENTITY_KEYS = {
    "device", "inode", "mode", "size_bytes", "mtime_ns", "owner_uid"
}
_SOURCE_IDENTITY_KEYS = {
    "path", "path_kind", "symlink_components", "resolved_target_path",
    "resolved_target_identity", "expected_sha256", "sha256_verified",
    "observed_sha256",
}


def _validate_file_record(value: Any, *, label: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _FILE_RECORD_KEYS
        or not isinstance(value.get("path"), str)
        or not value["path"]
        or _SHA256.fullmatch(str(value.get("sha256", ""))) is None
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
    ):
        raise B0CorePlanV2Error("%s record schema drift" % label)


def _validate_afrl_replay_manifest_evidence(value: Any) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _AFRL_REPLAY_MANIFEST_EVIDENCE_KEYS
        or value.get("classification")
        != "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME"
        or value.get("vins_csv_absent") is not True
        or value.get("vins_output_empty") is not True
    ):
        raise B0CorePlanV2Error("AFRL replay-manifest evidence schema drift")
    _validate_file_record(
        {key: value[key] for key in _FILE_RECORD_KEYS},
        label="AFRL replay-manifest evidence",
    )


def _validate_stat_identity(value: Any, *, label: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _STAT_IDENTITY_KEYS
        or any(type(value.get(key)) is not int for key in _STAT_IDENTITY_KEYS)
        or value["size_bytes"] <= 0
    ):
        raise B0CorePlanV2Error("%s identity schema drift" % label)


def _validate_source_identity(
    value: Any, *, source_path: str, source_sha256: str
) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != _SOURCE_IDENTITY_KEYS
        or value.get("path") != source_path
        or value.get("path_kind")
        not in {"PLAIN_REGULAR_FILE", "CANONICAL_SYMLINK_TARGET"}
        or not isinstance(value.get("resolved_target_path"), str)
        or not value["resolved_target_path"]
        or value.get("expected_sha256") != source_sha256
        or value.get("sha256_verified") is not True
        or value.get("observed_sha256") != source_sha256
        or not isinstance(value.get("symlink_components"), list)
    ):
        raise B0CorePlanV2Error("v1 source identity/path/hash drift")
    _validate_stat_identity(value["resolved_target_identity"], label="resolved target")
    if not stat.S_ISREG(int(value["resolved_target_identity"]["mode"])):
        raise B0CorePlanV2Error("v1 resolved target is not a regular file")
    components = value["symlink_components"]
    if (value["path_kind"] == "PLAIN_REGULAR_FILE") != (not components):
        raise B0CorePlanV2Error("v1 source symlink-kind drift")
    previous = ""
    for component in components:
        if (
            not isinstance(component, dict)
            or set(component) != {"path", "link_target", "lstat_identity"}
            or not isinstance(component.get("path"), str)
            or not component["path"]
            or not isinstance(component.get("link_target"), str)
            or (previous and not component["path"].startswith(previous.rstrip("/") + "/"))
        ):
            raise B0CorePlanV2Error("v1 source symlink component schema drift")
        _validate_stat_identity(component["lstat_identity"], label="symlink lstat")
        if not stat.S_ISLNK(int(component["lstat_identity"]["mode"])):
            raise B0CorePlanV2Error("v1 symlink component is not a symlink")
        previous = component["path"]


def _expected_aqualoc_reference(window: Mapping[str, Any]) -> str:
    sequence = str(window["sequence"])
    number = int(sequence[1:])
    if window["dataset_family"] == "aqualoc_archaeology":
        return (
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_%02d.txt"
            % number
        )
    return (
        "datasets/full_downloads/aqualoc/Harbor_sites_sequences/"
        "harbor_groundtruth_files/new_harbor_colmap_traj_sequence_%02d.txt"
        % number
    )


def _normalize_windows(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise B0CorePlanV2Error("frozen windows must be a sequence")
    normalized: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise B0CorePlanV2Error("frozen window is not an object")
        window_id = raw.get("window_id")
        if not isinstance(window_id, str) or window_id in normalized:
            raise B0CorePlanV2Error("duplicate or invalid frozen window")
        expected = FROZEN_WINDOWS.get(window_id)
        if expected is None:
            raise B0CorePlanV2Error("unknown frozen window: %s" % window_id)
        try:
            observed = {
                "window_id": window_id,
                "dataset_family": raw["dataset_family"],
                "sequence": raw["sequence"],
                "window_start_s": _number(
                    raw["window_start_s"], label="window_start_s"
                ),
                "window_end_s": _number(
                    raw["window_end_s"], label="window_end_s"
                ),
                "input_frame_count": _positive_int(
                    raw["input_frame_count"], label="input_frame_count"
                ),
            }
        except KeyError as error:
            raise B0CorePlanV2Error("frozen window lacks a required field") from error
        if observed != expected:
            raise B0CorePlanV2Error("frozen window definition drift: %s" % window_id)
        normalized[window_id] = observed
    if set(normalized) != set(FROZEN_WINDOWS):
        raise B0CorePlanV2Error("frozen window coverage is not the exact P07 set")
    return normalized


def _recipe_hash(recipe: Mapping[str, Any]) -> str:
    return document_hash(recipe, "recipe_hash")


def _validate_common_v1_recipe(
    recipe: Mapping[str, Any], window: Mapping[str, Any]
) -> Dict[str, Any]:
    allowed = set(_V1_BASE_RECIPE_KEYS)
    if window["window_id"] == "aqualoc_archaeology:A04:0002":
        allowed.add("a04_layout_recovery")
    if window["dataset_family"] == "afrl":
        allowed.update({"expected_camera_stamp_range_ns", "source_input_contract"})
    if set(recipe) != allowed:
        raise B0CorePlanV2Error(
            "v1 recipe schema drift: %s" % window["window_id"]
        )
    clone = _clone_json(recipe)
    if (
        clone.get("window_id") != window["window_id"]
        or clone.get("dataset_family") != window["dataset_family"]
        or clone.get("sequence") != window["sequence"]
        or clone.get("recipe_hash") != _recipe_hash(clone)
        or clone.get("held_out_trajectory_outcome_read") is not False
    ):
        raise B0CorePlanV2Error("v1 recipe identity/hash/outcome drift")
    _workspace_path(clone.get("target_path"), label="v1 target path")
    _workspace_path(clone.get("source_raw_path"), label="v1 source path")
    _sha(clone.get("expected_sha256"), label="v1 expected SHA-256")
    source_sha = _sha(clone.get("source_raw_sha256"), label="v1 source SHA-256")
    _sha(clone.get("source_provenance_hash"), label="v1 provenance SHA-256")
    _positive_int(clone.get("expected_size_bytes"), label="v1 expected size")
    identity = clone.get("source_path_identity")
    _validate_source_identity(
        identity,
        source_path=str(clone["source_raw_path"]),
        source_sha256=source_sha,
    )
    evidence = clone.get("evidence")
    if not isinstance(evidence, list):
        raise B0CorePlanV2Error("v1 evidence is not a list")
    for index, record in enumerate(evidence):
        if (
            window["dataset_family"] == "afrl"
            and index == 2
            and isinstance(record, dict)
            and set(record) == _AFRL_REPLAY_MANIFEST_EVIDENCE_KEYS
        ):
            _validate_afrl_replay_manifest_evidence(record)
        else:
            _validate_file_record(record, label="v1 evidence[%d]" % index)
    return clone


def _expected_aqualoc_argv(
    recipe: Mapping[str, Any], window: Mapping[str, Any]
) -> List[str]:
    family = str(window["dataset_family"])
    sequence = str(window["sequence"])
    number = int(sequence[1:])
    pad = "%02d" % number
    start = int(Decimal(str(window["window_start_s"])) * 20)
    end = int(Decimal(str(window["window_end_s"])) * 20)
    source = _AQUALOC_RAW_PATHS.get((family, sequence))
    if source is None:
        raise B0CorePlanV2Error("AQUALOC raw-input authority is absent")
    reference = _expected_aqualoc_reference(window)
    raw_root = "." if sequence == "A04" else ""
    if family == "aqualoc_archaeology" and sequence != "A04":
        raw_root = "raw_data"
    if family == "aqualoc_archaeology":
        result = [
            "python3",
            "-m",
            "uw_frontend.datasets.aqualoc_raw_to_rosbag",
            "--input",
            source,
            "--output-bag",
            "{OUTPUT}",
            "--sequence-name",
            "archaeo_sequence_%d" % number,
            "--raw-root",
            raw_root,
            "--image-dir",
            "images_sequence_%d" % number,
            "--image-csv",
            "img_sequence_%d.csv" % number,
            "--imu-csv",
            "imu_sequence_%d.csv" % number,
            "--gt-txt",
            reference,
        ]
    else:
        result = [
            "python3",
            "-m",
            "uw_frontend.datasets.aqualoc_raw_to_rosbag",
            "--input",
            source,
            "--output-bag",
            "{OUTPUT}",
            "--sequence-name",
            "harbor_sequence_%s" % pad,
            "--image-dir",
            "harbor_images_sequence_%s" % pad,
            "--image-csv",
            "harbor_img_sequence_%s.csv" % pad,
            "--imu-csv",
            "harbor_imu_sequence_%s.csv" % pad,
            "--gt-txt",
            reference,
        ]
    result.extend(
        [
            "--start-index",
            str(start),
            "--end-index",
            str(end),
            "--image-topic",
            "/camera/image_raw",
            "--imu-topic",
            "/rtimulib_node/imu",
            "--gt-topic",
            "/aqualoc/colmap_gt",
        ]
    )
    return result


def _validate_aqualoc_v1_recipe(
    recipe: Mapping[str, Any], window: Mapping[str, Any]
) -> Dict[str, Any]:
    clone = _validate_common_v1_recipe(recipe, window)
    start = str(int(Decimal(str(window["window_start_s"])) * 20))
    end = str(int(Decimal(str(window["window_end_s"])) * 20))
    prefix = "archaeo" if window["dataset_family"] == "aqualoc_archaeology" else "harbor"
    number = int(str(window["sequence"])[1:])
    expected_target = "datasets/aqualoc/rosbags/%s%02d_%s_%s.bag" % (
        prefix,
        number,
        start,
        end,
    )
    counts = clone.get("expected_topic_counts")
    authoritative_source = _AQUALOC_RAW_PATHS.get(
        (str(window["dataset_family"]), str(window["sequence"]))
    )
    if (
        authoritative_source is None
        or clone.get("source_raw_path") != authoritative_source
        or clone.get("source_path_identity", {}).get("path") != authoritative_source
        or _number(clone.get("runner_start"), label="AQUALOC runner start")
        != start
        or _number(clone.get("runner_end_or_duration"), label="AQUALOC runner end")
        != end
        or clone.get("runner_unit") != "frame"
        or clone.get("target_path") != expected_target
        or clone.get("camera_topic") != "/camera/image_raw"
        or clone.get("derivation_kind") != "PREMATERIALIZED_WINDOW_BAG"
        or clone.get("disposition")
        not in {
            "PREMATERIALIZED_EXACT_REUSE",
            "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
        }
        or not isinstance(counts, dict)
        or set(counts)
        != {"/camera/image_raw", "/rtimulib_node/imu", "/aqualoc/colmap_gt"}
        or counts.get("/camera/image_raw") != int(window["input_frame_count"]) + 1
        or any(not isinstance(value, int) or value <= 0 for value in counts.values())
    ):
        raise B0CorePlanV2Error("AQUALOC v1 scientific recipe drift")
    template = clone.get("converter_argv_template")
    if not isinstance(template, list):
        raise B0CorePlanV2Error("AQUALOC v1 converter argv is absent")
    try:
        expected_argv = _expected_aqualoc_argv(clone, window)
    except (ValueError, IndexError, TypeError) as error:
        raise B0CorePlanV2Error("AQUALOC v1 converter argv is malformed") from error
    if template != expected_argv:
        raise B0CorePlanV2Error("AQUALOC v1 converter argv drift")
    if window["window_id"] == "aqualoc_archaeology:A04:0002":
        recovery = clone.get("a04_layout_recovery")
        if (
            not isinstance(recovery, dict)
            or set(recovery)
            != {
                "execution_raw_root_argument",
                "q55_frozen_raw_root_argument",
                "semantic_equivalence",
                "expected_topic_counts",
                "q55_recovery_lock",
                "q55_recovery_closeout",
                "raw_materialization",
            }
            or recovery.get("execution_raw_root_argument") != "."
            or recovery.get("q55_frozen_raw_root_argument") != ""
            or recovery.get("semantic_equivalence")
            != "BOUND_CONVERTER_MEMBER_PATH_IGNORES_EMPTY_AND_DOT_COMPONENTS"
            or recovery.get("expected_topic_counts") != counts
        ):
            raise B0CorePlanV2Error("A04 v1 recovery contract drift")
        for key in ("q55_recovery_lock", "q55_recovery_closeout", "raw_materialization"):
            _validate_file_record(recovery[key], label="A04 %s" % key)
    return clone


def _validate_afrl_v1_recipe(
    recipe: Mapping[str, Any], window: Mapping[str, Any]
) -> Dict[str, Any]:
    clone = _validate_common_v1_recipe(recipe, window)
    counts = clone.get("expected_topic_counts")
    stamp_range = clone.get("expected_camera_stamp_range_ns")
    source_contract = clone.get("source_input_contract")
    template = clone.get("converter_argv_template")
    if (
        _number(clone.get("runner_start"), label="AFRL runner start") != "45"
        or _number(clone.get("runner_end_or_duration"), label="AFRL runner duration")
        != "45"
        or clone.get("runner_unit") != "second"
        or clone.get("target_path") != AFRL_TARGET_PATH
        or clone.get("camera_topic") != "/camera/image_raw"
        or clone.get("disposition") != "EXACT_COPY_REQUIRED_OR_RECONCILE"
        or clone.get("derivation_kind") != "PREMATERIALIZED_WINDOW_BAG"
        or clone.get("source_raw_sha256") != clone.get("expected_sha256")
        or template
        != [
            "INTERNAL_EXACT_COPY_NOREPLACE",
            clone.get("source_raw_path"),
            "{OUTPUT}",
        ]
        or not isinstance(counts, dict)
        or counts
        != {
            "/afrl/colmap_gt": 565,
            "/camera/image_raw": 565,
            "/imu/imu": 4500,
        }
        or not isinstance(stamp_range, dict)
        or set(stamp_range) != {"first", "last"}
        or not all(isinstance(stamp_range[key], int) for key in stamp_range)
        or stamp_range["first"] >= stamp_range["last"]
        or not isinstance(source_contract, dict)
        or set(source_contract)
        != {
            "topic_counts",
            "camera_stamp_range_ns",
            "camera_stamp_source",
            "trajectory_values_interpreted",
        }
        or source_contract.get("topic_counts") != counts
        or source_contract.get("camera_stamp_range_ns") != stamp_range
        or source_contract.get("camera_stamp_source")
        != "sensor_msgs/Image.header.stamp"
        or source_contract.get("trajectory_values_interpreted") is not False
        or not isinstance(clone.get("evidence"), list)
        or len(clone["evidence"]) != 3
    ):
        raise B0CorePlanV2Error("AFRL v1 dedicated-short-bag recipe drift")
    return clone


def make_v1_authority_envelope(validated_plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Wrap a complete v1 plan after the canonical v1 validator accepts it."""

    if not isinstance(validated_plan, Mapping):
        raise B0CorePlanV2Error("v1 plan authority is not an object")
    detached = _clone_json(validated_plan)
    try:
        v1_plan.validate_plan_payload(detached, require_live_artifacts=False)
    except (TypeError, ValueError, v1_plan.B0MaterializationError) as error:
        raise B0CorePlanV2Error("v1 plan authority failed its canonical validator") from error
    encoded = canonical_json(detached).encode("utf-8")
    envelope: Dict[str, Any] = {
        "schema_version": V1_AUTHORITY_ENVELOPE_SCHEMA,
        "authority_kind": COMPLETE_V1_RECIPE_AUTHORITY_KIND,
        "validator_contract": {
            "module": "scripts.build_p07_backend_b0_materialization_lock_v1",
            "schema_version": v1_plan.SCHEMA,
            "status": v1_plan.STATUS,
            "self_hash_field": v1_plan.SELF_HASH,
            "require_live_artifacts": False,
        },
        "plan_content_sha256": hashlib.sha256(encoded).hexdigest(),
        "plan_size_bytes": len(encoded),
        "plan_self_hash": detached[v1_plan.SELF_HASH],
        "plan": detached,
        V1_AUTHORITY_ENVELOPE_HASH: "",
    }
    envelope[V1_AUTHORITY_ENVELOPE_HASH] = document_hash(
        envelope, V1_AUTHORITY_ENVELOPE_HASH
    )
    return envelope


def _validated_v1_plan_from_envelope(source: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(source, Mapping) or set(source) != {
        "schema_version",
        "authority_kind",
        "validator_contract",
        "plan_content_sha256",
        "plan_size_bytes",
        "plan_self_hash",
        "plan",
        V1_AUTHORITY_ENVELOPE_HASH,
    }:
        raise B0CorePlanV2Error("complete v1 authority envelope is required")
    expected_contract = {
        "module": "scripts.build_p07_backend_b0_materialization_lock_v1",
        "schema_version": v1_plan.SCHEMA,
        "status": v1_plan.STATUS,
        "self_hash_field": v1_plan.SELF_HASH,
        "require_live_artifacts": False,
    }
    raw_plan = source.get("plan")
    if not isinstance(raw_plan, Mapping):
        raise B0CorePlanV2Error("v1 authority envelope lacks its plan")
    detached = _clone_json(raw_plan)
    encoded = canonical_json(detached).encode("utf-8")
    if (
        source.get("schema_version") != V1_AUTHORITY_ENVELOPE_SCHEMA
        or source.get("authority_kind")
        != COMPLETE_V1_RECIPE_AUTHORITY_KIND
        or source.get("validator_contract") != expected_contract
        or source.get("plan_content_sha256")
        != hashlib.sha256(encoded).hexdigest()
        or source.get("plan_size_bytes") != len(encoded)
        or source.get("plan_self_hash") != detached.get(v1_plan.SELF_HASH)
        or source.get(V1_AUTHORITY_ENVELOPE_HASH)
        != document_hash(source, V1_AUTHORITY_ENVELOPE_HASH)
    ):
        raise B0CorePlanV2Error("v1 authority envelope/hash/validator drift")
    try:
        v1_plan.validate_plan_payload(detached, require_live_artifacts=False)
    except (TypeError, ValueError, v1_plan.B0MaterializationError) as error:
        raise B0CorePlanV2Error("v1 authority plan failed canonical validation") from error
    return detached


def _canonical_reused_recipe_content_sha256(
    recipes: Mapping[str, Mapping[str, Any]],
) -> str:
    ordered = [_clone_json(recipes[window_id]) for window_id in sorted(recipes)]
    return hashlib.sha256(canonical_json(ordered).encode("utf-8")).hexdigest()


def _reused_recipe_authority_binding(
    authority_kind: str,
    recipes: Mapping[str, Mapping[str, Any]],
    authority_self_hash: Any,
) -> Dict[str, Any]:
    if authority_kind == LEGACY_RECIPE_AUTHORITY_KIND:
        schema_version = legacy_recipe_authority.SCHEMA_VERSION
        authority_recipe_count = 17
        self_hash_field = legacy_recipe_authority.SELF_HASH_FIELD
    elif authority_kind == COMPLETE_V1_RECIPE_AUTHORITY_KIND:
        schema_version = V1_AUTHORITY_ENVELOPE_SCHEMA
        authority_recipe_count = 20
        self_hash_field = V1_AUTHORITY_ENVELOPE_HASH
    else:
        raise B0CorePlanV2Error("unknown reused-recipe authority kind")
    if len(recipes) != 17:
        raise B0CorePlanV2Error("reused-recipe authority must expose exactly 17 recipes")
    return {
        "authority_kind": authority_kind,
        "authority_schema_version": schema_version,
        "authority_self_hash_field": self_hash_field,
        "authority_self_hash": _sha(
            authority_self_hash, label="reused-recipe authority self-hash"
        ),
        "authority_recipe_count": authority_recipe_count,
        "reused_recipe_count": 17,
        "content_scope": REUSED_RECIPE_CONTENT_SCOPE,
        "canonical_content_sha256": _canonical_reused_recipe_content_sha256(recipes),
    }


def _extract_reused_recipes(
    source: Mapping[str, Any],
    windows: Mapping[str, Mapping[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    if not isinstance(source, Mapping):
        raise B0CorePlanV2Error("reused-recipe authority is not an object")
    source_before = canonical_json(source)
    detached = json.loads(source_before)
    if not isinstance(detached, dict):
        raise B0CorePlanV2Error("reused-recipe authority snapshot is not an object")

    schema_version = detached.get("schema_version")
    if schema_version == legacy_recipe_authority.SCHEMA_VERSION:
        authority_kind = LEGACY_RECIPE_AUTHORITY_KIND
        try:
            legacy_recipe_authority.validate_authority_payload(detached)
        except (
            TypeError,
            ValueError,
            legacy_recipe_authority.LegacyRecipeAuthorityError,
        ) as error:
            raise B0CorePlanV2Error(
                "legacy 17-recipe authority failed canonical validation"
            ) from error
        raw = detached.get("recipes")
        required_coverage = {
            window_id
            for window_id, window in windows.items()
            if window["dataset_family"] in _AQUALOC_FAMILIES + ("afrl",)
        }
        if set(legacy_recipe_authority.WINDOWS) != required_coverage:
            raise B0CorePlanV2Error("legacy authority/core reused-window scope drift")
        if not isinstance(raw, list) or len(raw) != 17:
            raise B0CorePlanV2Error(
                "validated legacy authority must expose exactly 17 recipes"
            )
    elif schema_version == V1_AUTHORITY_ENVELOPE_SCHEMA:
        authority_kind = COMPLETE_V1_RECIPE_AUTHORITY_KIND
        plan = _validated_v1_plan_from_envelope(detached)
        raw = plan.get("recipes")
        required_coverage = set(windows)
        if not isinstance(raw, list) or len(raw) != 20:
            raise B0CorePlanV2Error(
                "validated v1 plan must expose exactly 20 recipes"
            )
    else:
        raise B0CorePlanV2Error("unknown reused-recipe authority schema")

    if canonical_json(source) != source_before:
        raise B0CorePlanV2Error("reused-recipe authority changed while snapshotted")
    seen: Dict[str, Mapping[str, Any]] = {}
    for recipe in raw:
        if not isinstance(recipe, Mapping):
            raise B0CorePlanV2Error("reused recipe is not an object")
        window_id = recipe.get("window_id")
        if not isinstance(window_id, str) or window_id in seen:
            raise B0CorePlanV2Error("duplicate or invalid reused recipe")
        if window_id not in windows:
            raise B0CorePlanV2Error("reused recipe references an unknown window")
        seen[window_id] = recipe
    expected_reused = {
        window_id
        for window_id, window in windows.items()
        if window["dataset_family"] in _AQUALOC_FAMILIES + ("afrl",)
    }
    if set(seen) != required_coverage:
        raise B0CorePlanV2Error("reused-recipe authority coverage drift")
    result: Dict[str, Dict[str, Any]] = {}
    for window_id in sorted(expected_reused):
        window = windows[window_id]
        recipe = seen[window_id]
        if window["dataset_family"] in _AQUALOC_FAMILIES:
            result[window_id] = _validate_aqualoc_v1_recipe(recipe, window)
        else:
            result[window_id] = _validate_afrl_v1_recipe(recipe, window)
    authority_self_hash = (
        detached.get(legacy_recipe_authority.SELF_HASH_FIELD)
        if authority_kind == LEGACY_RECIPE_AUTHORITY_KIND
        else detached.get(V1_AUTHORITY_ENVELOPE_HASH)
    )
    binding = _reused_recipe_authority_binding(
        authority_kind, result, authority_self_hash
    )
    if (
        authority_kind == LEGACY_RECIPE_AUTHORITY_KIND
        and detached.get("recipes_sha256") != binding["canonical_content_sha256"]
    ):
        raise B0CorePlanV2Error("legacy authority canonical recipe aggregate drift")
    return result, binding


def _normalize_effective_records(
    raw: Union[Mapping[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    items: List[Tuple[Optional[str], Mapping[str, Any]]] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if not isinstance(value, Mapping):
                raise B0CorePlanV2Error("effective checksum record is not an object")
            items.append((str(key), value))
    elif not isinstance(raw, (str, bytes)) and isinstance(raw, Sequence):
        for value in raw:
            if not isinstance(value, Mapping):
                raise B0CorePlanV2Error("effective checksum record is not an object")
            items.append((None, value))
    else:
        raise B0CorePlanV2Error("effective checksum records are malformed")
    result: Dict[str, Dict[str, Any]] = {}
    expected = {
        NTNU_SOURCE_PATH: (
            NTNU_SOURCE_XET_HASH,
            NTNU_SOURCE_CONTENT_SHA256,
            NTNU_SOURCE_SIZE_BYTES,
        ),
        AFRL_RAW_PATH: (AFRL_RAW_XET_HASH, AFRL_RAW_CONTENT_SHA256, AFRL_RAW_SIZE_BYTES),
    }
    for supplied_key, record in items:
        clone = _clone_json(record)
        path = clone.get("path")
        if supplied_key is not None and supplied_key != path:
            raise B0CorePlanV2Error("effective checksum mapping key/path drift")
        if not isinstance(path, str) or path in result or path not in expected:
            raise B0CorePlanV2Error("unknown or duplicate effective checksum path")
        base_hash, content_hash, size = expected[path]
        if (
            set(clone)
            != {
                "resolver_schema_version",
                "path",
                "base_manifest_sha256",
                "base_digest_semantics",
                "effective_content_sha256",
                "effective_digest_authority",
                "correction_applied",
                "size_bytes",
            }
            or clone.get("resolver_schema_version") != EFFECTIVE_RESOLVER_SCHEMA
            or clone.get("base_manifest_sha256") != base_hash
            or clone.get("base_digest_semantics") != "HUGGINGFACE_XET_HASH"
            or clone.get("effective_content_sha256") != content_hash
            or clone.get("effective_digest_authority") != EFFECTIVE_DIGEST_AUTHORITY
            or clone.get("correction_applied") is not True
            or clone.get("size_bytes") != size
        ):
            raise B0CorePlanV2Error("effective checksum authority/value drift")
        result[path] = clone
    if set(result) != set(expected):
        raise B0CorePlanV2Error("both scoped effective checksum records are required")
    return result


class ValidatedQueueAuthority(dict):
    """Detached rows proven to come from the exact frozen backend queue bytes."""

    def __init__(self, payload: Mapping[str, Any], *, token: object) -> None:
        if token is not _QUEUE_AUTHORITY_SENTINEL:
            raise B0CorePlanV2Error("queue authority must be created from frozen bytes")
        super().__init__(payload)
        self._validation_token = token


def _parse_frozen_queue_bytes(content: bytes) -> List[Dict[str, str]]:
    if (
        not isinstance(content, bytes)
        or len(content) != FROZEN_QUEUE_SIZE_BYTES
        or hashlib.sha256(content).hexdigest() != FROZEN_QUEUE_SHA256
    ):
        raise B0CorePlanV2Error("backend queue bytes differ from frozen authority")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as error:
        raise B0CorePlanV2Error("frozen backend queue CSV is malformed") from error
    required = {
        "queue_index", "run_id", "window_id", "dataset_family", "sequence",
        "window_start_s", "window_end_s", "runner_start",
        "runner_end_or_duration", "runner_unit", "arm", "replay_index",
        "source_run_id", "source_provenance_kind", "source_provenance_hash",
    }
    if (
        len(rows) != 240
        or reader.fieldnames is None
        or len(reader.fieldnames) != len(set(reader.fieldnames))
        or not required.issubset(reader.fieldnames)
        or any(None in row or any(not isinstance(value, str) for value in row.values()) for row in rows)
    ):
        raise B0CorePlanV2Error("frozen backend queue CSV shape drift")
    return [dict(row) for row in rows]


def _full_queue_row_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(row)).encode("utf-8")).hexdigest()


def make_queue_authority_envelope(content: bytes) -> ValidatedQueueAuthority:
    rows = _parse_frozen_queue_bytes(content)
    row_hashes = [_full_queue_row_hash(row) for row in rows]
    payload: Dict[str, Any] = {
        "schema_version": QUEUE_AUTHORITY_ENVELOPE_SCHEMA,
        "authority_record": {
            "path": FROZEN_QUEUE_RELATIVE,
            "sha256": FROZEN_QUEUE_SHA256,
            "size_bytes": FROZEN_QUEUE_SIZE_BYTES,
        },
        "row_count": 240,
        "rows": rows,
        "full_row_hashes": row_hashes,
        "ordered_full_row_hashes_sha256": hashlib.sha256(
            canonical_json(row_hashes).encode("utf-8")
        ).hexdigest(),
        QUEUE_AUTHORITY_ENVELOPE_HASH: "",
    }
    payload[QUEUE_AUTHORITY_ENVELOPE_HASH] = document_hash(
        payload, QUEUE_AUTHORITY_ENVELOPE_HASH
    )
    return ValidatedQueueAuthority(payload, token=_QUEUE_AUTHORITY_SENTINEL)


def _rows_from_queue_authority(value: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if (
        not isinstance(value, ValidatedQueueAuthority)
        or getattr(value, "_validation_token", None) is not _QUEUE_AUTHORITY_SENTINEL
        or set(value) != {
            "schema_version", "authority_record", "row_count", "rows",
            "full_row_hashes", "ordered_full_row_hashes_sha256",
            QUEUE_AUTHORITY_ENVELOPE_HASH,
        }
        or value.get("schema_version") != QUEUE_AUTHORITY_ENVELOPE_SCHEMA
        or value.get("authority_record")
        != {
            "path": FROZEN_QUEUE_RELATIVE,
            "sha256": FROZEN_QUEUE_SHA256,
            "size_bytes": FROZEN_QUEUE_SIZE_BYTES,
        }
        or value.get("row_count") != 240
        or value.get(QUEUE_AUTHORITY_ENVELOPE_HASH)
        != document_hash(value, QUEUE_AUTHORITY_ENVELOPE_HASH)
    ):
        raise B0CorePlanV2Error("validated frozen queue authority is required")
    rows = value.get("rows")
    hashes = value.get("full_row_hashes")
    if (
        not isinstance(rows, list)
        or len(rows) != 240
        or not isinstance(hashes, list)
        or hashes != [_full_queue_row_hash(row) for row in rows]
        or value.get("ordered_full_row_hashes_sha256")
        != hashlib.sha256(canonical_json(hashes).encode("utf-8")).hexdigest()
    ):
        raise B0CorePlanV2Error("queue authority rows/hash aggregate drift")
    return _clone_json(rows)


def _read_live_frozen_queue(root: Path = ROOT) -> Tuple[bytes, os.stat_result]:
    path = Path(root).absolute() / FROZEN_QUEUE_RELATIVE
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise B0CorePlanV2Error("live frozen queue is not a direct regular file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise B0CorePlanV2Error("cannot read live frozen queue authority") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    ):
        raise B0CorePlanV2Error("live frozen queue changed while read")
    return b"".join(chunks), after


def load_live_queue_authority(root: Path = ROOT) -> ValidatedQueueAuthority:
    content, _identity = _read_live_frozen_queue(root)
    return make_queue_authority_envelope(content)


def _normalize_queue_rows(
    rows: Sequence[Mapping[str, Any]],
    windows: Mapping[str, Mapping[str, Any]],
    reused: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or len(rows) != 240:
        raise B0CorePlanV2Error("frozen queue must contain exactly 240 rows")
    normalized: List[Dict[str, Any]] = []
    indices = set()
    run_ids = set()
    combinations = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise B0CorePlanV2Error("queue row is not an object")
        try:
            queue_index = int(row["queue_index"])
            replay_index = int(row["replay_index"])
            run_id = row["run_id"]
            window_id = row["window_id"]
            arm = row["arm"]
        except (KeyError, TypeError, ValueError) as error:
            raise B0CorePlanV2Error("queue identity fields are malformed") from error
        if (
            isinstance(row.get("queue_index"), bool)
            or isinstance(row.get("replay_index"), bool)
            or not isinstance(run_id, str)
            or not run_id
            or not isinstance(window_id, str)
            or window_id not in windows
            or arm not in ARMS
            or replay_index not in REPLAY_INDICES
            or queue_index in indices
            or run_id in run_ids
            or (window_id, arm, replay_index) in combinations
        ):
            raise B0CorePlanV2Error("unknown or duplicate queue identity")
        window = windows[window_id]
        start = _number(row.get("runner_start"), label="queue runner start")
        end_or_duration = _number(
            row.get("runner_end_or_duration"), label="queue runner end/duration"
        )
        unit = row.get("runner_unit")
        if window["dataset_family"] == "ntnu":
            expected_runner = (window["window_start_s"], "45", "second")
        else:
            recipe = reused[window_id]
            expected_runner = (
                _number(recipe["runner_start"], label="recipe runner start"),
                _number(
                    recipe["runner_end_or_duration"], label="recipe runner end/duration"
                ),
                recipe["runner_unit"],
            )
        if (
            row.get("dataset_family") != window["dataset_family"]
            or row.get("sequence") != window["sequence"]
            or _number(row.get("window_start_s"), label="queue window start")
            != window["window_start_s"]
            or _number(row.get("window_end_s"), label="queue window end")
            != window["window_end_s"]
            or (start, end_or_duration, unit) != expected_runner
            or not isinstance(row.get("source_run_id"), str)
            or not row.get("source_run_id")
            or not isinstance(row.get("source_provenance_kind"), str)
            or not row.get("source_provenance_kind")
            or _SHA256.fullmatch(str(row.get("source_provenance_hash", ""))) is None
        ):
            raise B0CorePlanV2Error("queue/window/runner/provenance drift")
        if arm == B0_ARM and (
            row.get("source_run_id") != "B0_NATIVE_DATA:%s" % window_id
            or row.get("source_provenance_kind") != "B0_NATIVE_DATA_IDENTITY_V1"
        ):
            raise B0CorePlanV2Error("B0 queue source provenance drift")
        normalized_row = {
                "queue_index": queue_index,
                "run_id": run_id,
                "window_id": window_id,
                "dataset_family": window["dataset_family"],
                "sequence": window["sequence"],
                "window_start_s": window["window_start_s"],
                "window_end_s": window["window_end_s"],
                "runner_start": start,
                "runner_end_or_duration": end_or_duration,
                "runner_unit": unit,
                "arm": arm,
                "replay_index": replay_index,
                "source_run_id": row["source_run_id"],
                "source_provenance_kind": row["source_provenance_kind"],
                "source_provenance_hash": row["source_provenance_hash"],
            }
        normalized_row["immutable_queue_row_hash"] = _immutable_queue_row_hash(
            normalized_row
        )
        normalized.append(normalized_row)
        indices.add(queue_index)
        run_ids.add(run_id)
        combinations.add((window_id, arm, replay_index))
    expected_combinations = {
        (window_id, arm, replay_index)
        for window_id in windows
        for arm in ARMS
        for replay_index in REPLAY_INDICES
    }
    if indices != set(range(1, 241)) or combinations != expected_combinations:
        raise B0CorePlanV2Error("queue is not the exact 20 x 4 x 3 allocation")
    normalized.sort(key=lambda item: int(item["queue_index"]))
    return normalized


def _immutable_queue_row_hash(row: Mapping[str, Any]) -> str:
    seed = {
        "schema_version": QUEUE_ROW_HASH_SCHEMA,
        "queue_index": row.get("queue_index"),
        "run_id": row.get("run_id"),
        "window_id": row.get("window_id"),
        "dataset_family": row.get("dataset_family"),
        "sequence": row.get("sequence"),
        "runner_start": row.get("runner_start"),
        "runner_end_or_duration": row.get("runner_end_or_duration"),
        "runner_unit": row.get("runner_unit"),
        "arm": row.get("arm"),
        "replay_index": row.get("replay_index"),
        "source_run_id": row.get("source_run_id"),
        "source_provenance_kind": row.get("source_provenance_kind"),
        "source_provenance_hash": row.get("source_provenance_hash"),
    }
    return hashlib.sha256(canonical_json(seed).encode("utf-8")).hexdigest()


def _fanout_contract() -> Dict[str, Any]:
    expected_fields = ("window_id", "start_offset_ns", "end_offset_ns")
    if tuple(ntnu_fanout.RecordWindow.__dataclass_fields__) != expected_fields:
        raise B0CorePlanV2Error("fanout RecordWindow field contract drift")
    windows = tuple(
        ntnu_fanout.RecordWindow(
            str(spec["window_id"]),
            int(spec["start_offset_ns"]),
            int(spec["end_offset_ns"]),
        )
        for spec in NTNU_WINDOW_SPECS
    )
    try:
        validated = ntnu_fanout._validate_windows(windows)
    except (TypeError, ValueError, ntnu_fanout.NTNUWindowFanoutError) as error:
        raise B0CorePlanV2Error("fanout RecordWindow validation failed") from error
    if validated != windows or tuple(ntnu_fanout.DEFAULT_TOPICS) != (
        NTNU_CAMERA_TOPIC,
        NTNU_IMU_TOPIC,
    ):
        raise B0CorePlanV2Error("fanout windows/topics contract drift")
    return {
        "module_schema_version": ntnu_fanout.SCHEMA_VERSION,
        "record_window_fields": list(expected_fields),
        "selection_semantics": ntnu_fanout.SELECTION_SEMANTICS,
        "topics": list(ntnu_fanout.DEFAULT_TOPICS),
        "windows": [
            {
                "window_id": window.window_id,
                "start_offset_ns": window.start_offset_ns,
                "end_offset_ns": window.end_offset_ns,
            }
            for window in windows
        ],
        "formal_wrapper_must_bind_fanout_source_hash": True,
    }


def _entry_id_seed(entry: Mapping[str, Any]) -> Dict[str, Any]:
    target = entry["target"]
    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": entry["window_id"],
        "target_path": target["path"],
        "materialization_kind": entry["materialization"]["kind"],
    }


def _finish_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    entry["entry_id"] = hashlib.sha256(
        canonical_json(_entry_id_seed(entry)).encode("utf-8")
    ).hexdigest()
    entry["entry_hash"] = document_hash(entry, "entry_hash")
    return entry


def _build_reused_entry(
    window: Mapping[str, Any],
    recipe: Mapping[str, Any],
    effective: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    family = str(window["dataset_family"])
    materialization: Dict[str, Any] = {
        "kind": (
            "VALIDATED_V1_AQUALOC_RECIPE_REUSE"
            if family in _AQUALOC_FAMILIES
            else "VALIDATED_V1_AFRL_DEDICATED_SHORT_BAG_REUSE"
        ),
        "v1_recipe": _clone_json(recipe),
    }
    calibration: Optional[Dict[str, Any]] = None
    if family == "afrl":
        materialization["upstream_raw_dataset_provenance"] = {
            **_clone_json(effective[AFRL_RAW_PATH]),
            "runtime_role": MATERIALIZATION_ONLY_ROLE,
        }
        calibration = {
            "camera": {
                "path": AFRL_BUS_CAMCHAIN_PATH,
                "sha256": AFRL_BUS_CAMCHAIN_SHA256,
                "sequence": "bus_outside",
            },
            "imu": {"path": AFRL_IMU_PATH, "sha256": AFRL_IMU_SHA256},
            "correction_kind": "SEQUENCE_SPECIFIC_BUS_CAMCHAIN_PLUS_SHARED_IMU",
        }
    entry: Dict[str, Any] = {
        "entry_id": "",
        "entry_hash": "",
        "window_id": window["window_id"],
        "dataset_family": family,
        "sequence": window["sequence"],
        "window_definition": {
            "start_s": window["window_start_s"],
            "end_s": window["window_end_s"],
            "input_frame_count": window["input_frame_count"],
        },
        "target": {
            "path": recipe["target_path"],
            "content_sha256": recipe["expected_sha256"],
            "size_bytes": recipe["expected_size_bytes"],
            "identity_status": "EXACT_CONTENT_IDENTITY_FROM_VALIDATED_V1_RECIPE",
        },
        "materialization": materialization,
        "preparation": {
            "runner_start": _number(
                recipe["runner_start"], label="reused recipe runner start"
            ),
            "runner_end_or_duration": _number(
                recipe["runner_end_or_duration"],
                label="reused recipe runner end/duration",
            ),
            "runner_unit": recipe["runner_unit"],
        },
        "replay": {
            "runtime_input_path": recipe["target_path"],
            "whole_materialized_bag": True,
            "slice": None,
        },
        "calibration": calibration,
        "b0_source_provenance_hash": recipe["source_provenance_hash"],
        "held_out_trajectory_outcome_read": False,
    }
    return _finish_entry(entry)


def _build_ntnu_entry(
    window: Mapping[str, Any],
    spec: Mapping[str, Any],
    source_record: Mapping[str, Any],
    b0_source_provenance_hash: str,
) -> Dict[str, Any]:
    source_provenance = _clone_json(source_record)
    source_provenance["runtime_role"] = MATERIALIZATION_ONLY_ROLE
    entry: Dict[str, Any] = {
        "entry_id": "",
        "entry_hash": "",
        "window_id": window["window_id"],
        "dataset_family": "ntnu",
        "sequence": "fjord_6",
        "window_definition": {
            "start_s": window["window_start_s"],
            "end_s": window["window_end_s"],
            "input_frame_count": window["input_frame_count"],
        },
        "target": {
            "path": spec["target_path"],
            "content_sha256": None,
            "size_bytes": None,
            "identity_status": "TO_BE_ESTABLISHED_BY_FORMAL_MATERIALIZATION",
        },
        "materialization": {
            "kind": "ROS1_CLOSED_RECORD_TIME_DERIVED_WINDOW_FANOUT",
            "source_provenance": source_provenance,
            "selection": {
                "boundary_rule": NTNU_BOUNDARY_RULE,
                "record_time_t0_ns": NTNU_RECORD_T0_NS,
                "start_offset_ns": spec["start_offset_ns"],
                "end_offset_ns": spec["end_offset_ns"],
                "absolute_record_start_ns": spec["absolute_record_start_ns"],
                "absolute_record_end_ns": spec["absolute_record_end_ns"],
            },
            "expected_output": {
                "topic_counts": {
                    NTNU_CAMERA_TOPIC: spec["camera_count"],
                    NTNU_IMU_TOPIC: spec["imu_count"],
                },
                "camera_record_bounds_ns": {
                    "first": spec["camera_record_first_ns"],
                    "last": spec["camera_record_last_ns"],
                },
                "camera_header_evaluation_bounds_ns": {
                    "first": spec["camera_header_evaluation_first_ns"],
                    "last": spec["camera_header_evaluation_last_ns"],
                },
                "camera_topic": NTNU_CAMERA_TOPIC,
                "imu_topic": NTNU_IMU_TOPIC,
                "trajectory_values_interpreted": False,
            },
        },
        "preparation": {
            "runner_start": "0",
            "runner_end_or_duration": "45",
            "runner_unit": "second",
        },
        "replay": {
            "runtime_input_path": spec["target_path"],
            "whole_materialized_bag": True,
            "slice": None,
        },
        "calibration": None,
        "b0_source_provenance_hash": b0_source_provenance_hash,
        "held_out_trajectory_outcome_read": False,
    }
    return _finish_entry(entry)


def build_core_plan(
    *,
    frozen_windows: Sequence[Mapping[str, Any]],
    validated_v1_plan_or_recipes: Mapping[str, Any],
    effective_checksum_records: Union[
        Mapping[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]
    ],
    frozen_queue_authority: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build and internally validate the side-effect-free B0 v2 core."""

    windows = _normalize_windows(frozen_windows)
    reused, reused_recipe_authority_binding = _extract_reused_recipes(
        validated_v1_plan_or_recipes, windows
    )
    effective = _normalize_effective_records(effective_checksum_records)
    queue = _normalize_queue_rows(
        _rows_from_queue_authority(frozen_queue_authority), windows, reused
    )
    b0_hashes: Dict[str, str] = {}
    for row in queue:
        if row["arm"] != B0_ARM:
            continue
        window_id = str(row["window_id"])
        value = str(row["source_provenance_hash"])
        if window_id in b0_hashes and b0_hashes[window_id] != value:
            raise B0CorePlanV2Error("B0 provenance differs across replays")
        b0_hashes[window_id] = value

    entries: List[Dict[str, Any]] = []
    for window_id in sorted(windows):
        window = windows[window_id]
        if window["dataset_family"] == "ntnu":
            entries.append(
                _build_ntnu_entry(
                    window,
                    _NTNU_BY_WINDOW[window_id],
                    effective[NTNU_SOURCE_PATH],
                    b0_hashes[window_id],
                )
            )
        else:
            if reused[window_id]["source_provenance_hash"] != b0_hashes[window_id]:
                raise B0CorePlanV2Error("v1 recipe/B0 queue provenance hash drift")
            entries.append(_build_reused_entry(window, reused[window_id], effective))
    by_window = {str(entry["window_id"]): entry for entry in entries}

    preparation_mappings = [
        {
            "queue_index": row["queue_index"],
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "dataset_family": row["dataset_family"],
            "sequence": row["sequence"],
            "arm": row["arm"],
            "replay_index": row["replay_index"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"],
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
            "immutable_queue_row_hash": row["immutable_queue_row_hash"],
            "entry_id": by_window[str(row["window_id"])]["entry_id"],
            "runtime_input_path": by_window[str(row["window_id"])]["target"]["path"],
            "replay_slice": None,
        }
        for row in queue
    ]
    b0_bindings = [
        {
            "queue_index": row["queue_index"],
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "dataset_family": row["dataset_family"],
            "sequence": row["sequence"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"],
            "replay_index": row["replay_index"],
            "arm": row["arm"],
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
            "immutable_queue_row_hash": row["immutable_queue_row_hash"],
            "entry_id": by_window[str(row["window_id"])]["entry_id"],
        }
        for row in queue
        if row["arm"] == B0_ARM
    ]
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "window_count": 20,
        "entry_count": 20,
        "aqualoc_entry_count": 16,
        "afrl_entry_count": 1,
        "ntnu_entry_count": 3,
        "b0_binding_count": 60,
        "preparation_mapping_count": 240,
        REUSED_RECIPE_AUTHORITY_FIELD: reused_recipe_authority_binding,
        "frozen_queue_authority": {
            "record": {
                "path": FROZEN_QUEUE_RELATIVE,
                "sha256": FROZEN_QUEUE_SHA256,
                "size_bytes": FROZEN_QUEUE_SIZE_BYTES,
            },
            "queue_row_hash_schema": QUEUE_ROW_HASH_SCHEMA,
            "ordered_selected_row_hashes": [
                row["immutable_queue_row_hash"] for row in queue
            ],
            "ordered_selected_row_hashes_sha256": hashlib.sha256(
                canonical_json(
                    [row["immutable_queue_row_hash"] for row in queue]
                ).encode("utf-8")
            ).hexdigest(),
        },
        "entries": entries,
        "b0_bindings": b0_bindings,
        "preparation_mappings": preparation_mappings,
        "fanout_contract": _fanout_contract(),
        "policy": {
            "validated_v1_aqualoc_afrl_science_reused": True,
            "ntnu_full_raw_runtime_playback_forbidden": True,
            "derived_ntnu_bags_replayed_whole_without_secondary_slice": True,
            "formal_authority_bindings_included": False,
            "formal_materialization_authorized": False,
            "vins_execution_authorized": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH_FIELD] = document_hash(payload, SELF_HASH_FIELD)
    validate_core_plan(
        payload,
        validated_v1_plan_or_recipes=validated_v1_plan_or_recipes,
    )
    return payload


def _validate_entry_common(entry: Mapping[str, Any]) -> None:
    if set(entry) != {
        "entry_id",
        "entry_hash",
        "window_id",
        "dataset_family",
        "sequence",
        "window_definition",
        "target",
        "materialization",
        "preparation",
        "replay",
        "calibration",
        "b0_source_provenance_hash",
        "held_out_trajectory_outcome_read",
    }:
        raise B0CorePlanV2Error("entry schema expansion/drift")
    window_id = entry.get("window_id")
    expected_window = FROZEN_WINDOWS.get(str(window_id))
    if expected_window is None:
        raise B0CorePlanV2Error("entry references an unknown window")
    target = entry.get("target")
    replay = entry.get("replay")
    preparation = entry.get("preparation")
    materialization = entry.get("materialization")
    expected_definition = {
        "start_s": expected_window["window_start_s"],
        "end_s": expected_window["window_end_s"],
        "input_frame_count": expected_window["input_frame_count"],
    }
    if (
        entry.get("dataset_family") != expected_window["dataset_family"]
        or entry.get("sequence") != expected_window["sequence"]
        or entry.get("window_definition") != expected_definition
        or entry.get("held_out_trajectory_outcome_read") is not False
        or _SHA256.fullmatch(str(entry.get("b0_source_provenance_hash", ""))) is None
        or not isinstance(target, dict)
        or set(target)
        != {"path", "content_sha256", "size_bytes", "identity_status"}
        or not isinstance(replay, dict)
        or replay
        != {
            "runtime_input_path": target.get("path"),
            "whole_materialized_bag": True,
            "slice": None,
        }
        or not isinstance(preparation, dict)
        or set(preparation)
        != {"runner_start", "runner_end_or_duration", "runner_unit"}
        or not isinstance(materialization, dict)
        or not isinstance(materialization.get("kind"), str)
        or not materialization["kind"]
        or entry.get("entry_id")
        != hashlib.sha256(canonical_json(_entry_id_seed(entry)).encode("utf-8")).hexdigest()
        or entry.get("entry_hash") != document_hash(entry, "entry_hash")
    ):
        raise B0CorePlanV2Error("entry identity/window/target/replay/hash drift")
    _workspace_path(target.get("path"), label="entry target path")


def _validate_ntnu_entry(entry: Mapping[str, Any]) -> None:
    window_id = str(entry["window_id"])
    spec = _NTNU_BY_WINDOW.get(window_id)
    if spec is None:
        raise B0CorePlanV2Error("unknown NTNU entry")
    materialization = entry.get("materialization")
    target = entry["target"]
    source = materialization.get("source_provenance") if isinstance(materialization, dict) else None
    if not isinstance(source, dict):
        raise B0CorePlanV2Error("NTNU materialization source is absent")
    effective_record = dict(source)
    role = effective_record.pop("runtime_role", None)
    _normalize_effective_records(
        [
            effective_record,
            {
                "resolver_schema_version": EFFECTIVE_RESOLVER_SCHEMA,
                "path": AFRL_RAW_PATH,
                "base_manifest_sha256": AFRL_RAW_XET_HASH,
                "base_digest_semantics": "HUGGINGFACE_XET_HASH",
                "effective_content_sha256": AFRL_RAW_CONTENT_SHA256,
                "effective_digest_authority": EFFECTIVE_DIGEST_AUTHORITY,
                "correction_applied": True,
                "size_bytes": AFRL_RAW_SIZE_BYTES,
            },
        ]
    )
    expected_materialization = {
        "kind": "ROS1_CLOSED_RECORD_TIME_DERIVED_WINDOW_FANOUT",
        "source_provenance": {**effective_record, "runtime_role": MATERIALIZATION_ONLY_ROLE},
        "selection": {
            "boundary_rule": NTNU_BOUNDARY_RULE,
            "record_time_t0_ns": NTNU_RECORD_T0_NS,
            "start_offset_ns": spec["start_offset_ns"],
            "end_offset_ns": spec["end_offset_ns"],
            "absolute_record_start_ns": spec["absolute_record_start_ns"],
            "absolute_record_end_ns": spec["absolute_record_end_ns"],
        },
        "expected_output": {
            "topic_counts": {
                NTNU_CAMERA_TOPIC: spec["camera_count"],
                NTNU_IMU_TOPIC: spec["imu_count"],
            },
            "camera_record_bounds_ns": {
                "first": spec["camera_record_first_ns"],
                "last": spec["camera_record_last_ns"],
            },
            "camera_header_evaluation_bounds_ns": {
                "first": spec["camera_header_evaluation_first_ns"],
                "last": spec["camera_header_evaluation_last_ns"],
            },
            "camera_topic": NTNU_CAMERA_TOPIC,
            "imu_topic": NTNU_IMU_TOPIC,
            "trajectory_values_interpreted": False,
        },
    }
    if (
        role != MATERIALIZATION_ONLY_ROLE
        or target
        != {
            "path": spec["target_path"],
            "content_sha256": None,
            "size_bytes": None,
            "identity_status": "TO_BE_ESTABLISHED_BY_FORMAL_MATERIALIZATION",
        }
        or materialization != expected_materialization
        or entry.get("preparation")
        != {
            "runner_start": "0",
            "runner_end_or_duration": "45",
            "runner_unit": "second",
        }
        or entry.get("calibration") is not None
        or entry["replay"]["runtime_input_path"] == NTNU_SOURCE_PATH
    ):
        raise B0CorePlanV2Error("NTNU audited fan-out/replay contract drift")
    selection = materialization["selection"]
    if (
        selection["absolute_record_start_ns"]
        != NTNU_RECORD_T0_NS + selection["start_offset_ns"]
        or selection["absolute_record_end_ns"]
        != NTNU_RECORD_T0_NS + selection["end_offset_ns"]
    ):
        raise B0CorePlanV2Error("NTNU record-time T0/offset arithmetic drift")
    # The full source path is permitted only in materialization provenance.
    scrubbed = copy.deepcopy(entry)
    del scrubbed["materialization"]["source_provenance"]
    if NTNU_SOURCE_PATH in canonical_json(scrubbed):
        raise B0CorePlanV2Error("NTNU full raw bag acquired a runtime role")


def _validate_reused_entry(entry: Mapping[str, Any]) -> None:
    family = str(entry["dataset_family"])
    materialization = entry.get("materialization")
    if not isinstance(materialization, dict) or not isinstance(
        materialization.get("v1_recipe"), dict
    ):
        raise B0CorePlanV2Error("reused entry lacks a v1 recipe")
    window = FROZEN_WINDOWS[str(entry["window_id"])]
    recipe = materialization["v1_recipe"]
    if family in _AQUALOC_FAMILIES:
        if set(materialization) != {"kind", "v1_recipe"} or materialization.get(
            "kind"
        ) != "VALIDATED_V1_AQUALOC_RECIPE_REUSE":
            raise B0CorePlanV2Error("AQUALOC reuse materialization drift")
        validated = _validate_aqualoc_v1_recipe(recipe, window)
        if entry.get("calibration") is not None:
            raise B0CorePlanV2Error("AQUALOC core invented a calibration binding")
    elif family == "afrl":
        if set(materialization) != {
            "kind",
            "v1_recipe",
            "upstream_raw_dataset_provenance",
        } or materialization.get("kind") != (
            "VALIDATED_V1_AFRL_DEDICATED_SHORT_BAG_REUSE"
        ):
            raise B0CorePlanV2Error("AFRL reuse materialization drift")
        validated = _validate_afrl_v1_recipe(recipe, window)
        provenance = materialization["upstream_raw_dataset_provenance"]
        if not isinstance(provenance, dict):
            raise B0CorePlanV2Error("AFRL raw provenance is absent")
        record = dict(provenance)
        role = record.pop("runtime_role", None)
        _normalize_effective_records(
            [
                record,
                {
                    "resolver_schema_version": EFFECTIVE_RESOLVER_SCHEMA,
                    "path": NTNU_SOURCE_PATH,
                    "base_manifest_sha256": NTNU_SOURCE_XET_HASH,
                    "base_digest_semantics": "HUGGINGFACE_XET_HASH",
                    "effective_content_sha256": NTNU_SOURCE_CONTENT_SHA256,
                    "effective_digest_authority": EFFECTIVE_DIGEST_AUTHORITY,
                    "correction_applied": True,
                    "size_bytes": NTNU_SOURCE_SIZE_BYTES,
                },
            ]
        )
        expected_calibration = {
            "camera": {
                "path": AFRL_BUS_CAMCHAIN_PATH,
                "sha256": AFRL_BUS_CAMCHAIN_SHA256,
                "sequence": "bus_outside",
            },
            "imu": {"path": AFRL_IMU_PATH, "sha256": AFRL_IMU_SHA256},
            "correction_kind": "SEQUENCE_SPECIFIC_BUS_CAMCHAIN_PLUS_SHARED_IMU",
        }
        if role != MATERIALIZATION_ONLY_ROLE or entry.get("calibration") != expected_calibration:
            raise B0CorePlanV2Error("AFRL checksum/calibration correction drift")
    else:
        raise B0CorePlanV2Error("unexpected reused-entry family")
    target = entry["target"]
    expected_target = {
        "path": validated["target_path"],
        "content_sha256": validated["expected_sha256"],
        "size_bytes": validated["expected_size_bytes"],
        "identity_status": "EXACT_CONTENT_IDENTITY_FROM_VALIDATED_V1_RECIPE",
    }
    expected_preparation = {
        "runner_start": _number(validated["runner_start"], label="runner start"),
        "runner_end_or_duration": _number(
            validated["runner_end_or_duration"], label="runner end/duration"
        ),
        "runner_unit": validated["runner_unit"],
    }
    if (
        target != expected_target
        or entry.get("preparation") != expected_preparation
        or entry.get("b0_source_provenance_hash")
        != validated["source_provenance_hash"]
    ):
        raise B0CorePlanV2Error("reused v1 target/science/provenance drift")


def validate_core_plan(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    validated_v1_plan_or_recipes: Optional[Mapping[str, Any]] = None,
) -> str:
    """Strictly validate a built core, including re-hashed semantic tampering.

    Supplying ``validated_v1_plan_or_recipes`` additionally revalidates the
    detached external authority and exactly rebuilds its core binding.  Formal
    wrappers should use that stronger form when adopting this nonformal core.
    """

    if set(payload) != {
        "schema_version",
        "status",
        "window_count",
        "entry_count",
        "aqualoc_entry_count",
        "afrl_entry_count",
        "ntnu_entry_count",
        "b0_binding_count",
        "preparation_mapping_count",
        REUSED_RECIPE_AUTHORITY_FIELD,
        "frozen_queue_authority",
        "entries",
        "b0_bindings",
        "preparation_mappings",
        "fanout_contract",
        "policy",
        "held_out_trajectory_outcome_read",
        "outcome_boundary",
        SELF_HASH_FIELD,
    }:
        raise B0CorePlanV2Error("core top-level schema expansion/drift")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != document_hash(payload, SELF_HASH_FIELD)
        or payload.get("window_count") != 20
        or payload.get("entry_count") != 20
        or payload.get("aqualoc_entry_count") != 16
        or payload.get("afrl_entry_count") != 1
        or payload.get("ntnu_entry_count") != 3
        or payload.get("b0_binding_count") != 60
        or payload.get("preparation_mapping_count") != 240
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
        or payload.get("fanout_contract") != _fanout_contract()
    ):
        raise B0CorePlanV2Error("core schema/status/count/self-hash drift")
    expected_policy = {
        "validated_v1_aqualoc_afrl_science_reused": True,
        "ntnu_full_raw_runtime_playback_forbidden": True,
        "derived_ntnu_bags_replayed_whole_without_secondary_slice": True,
        "formal_authority_bindings_included": False,
        "formal_materialization_authorized": False,
        "vins_execution_authorized": False,
    }
    if payload.get("policy") != expected_policy:
        raise B0CorePlanV2Error("core non-authorizing policy drift")
    entries = payload.get("entries")
    bindings = payload.get("b0_bindings")
    mappings = payload.get("preparation_mappings")
    if (
        not isinstance(entries, list)
        or len(entries) != 20
        or not isinstance(bindings, list)
        or len(bindings) != 60
        or not isinstance(mappings, list)
        or len(mappings) != 240
    ):
        raise B0CorePlanV2Error("core lists/counts are incomplete")
    by_window: Dict[str, Mapping[str, Any]] = {}
    by_id: Dict[str, Mapping[str, Any]] = {}
    families: Dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise B0CorePlanV2Error("entry is not an object")
        _validate_entry_common(entry)
        window_id = str(entry["window_id"])
        entry_id = str(entry["entry_id"])
        if window_id in by_window or entry_id in by_id:
            raise B0CorePlanV2Error("duplicate entry identity")
        if entry["dataset_family"] == "ntnu":
            _validate_ntnu_entry(entry)
        else:
            _validate_reused_entry(entry)
        family = str(entry["dataset_family"])
        families[family] = families.get(family, 0) + 1
        by_window[window_id] = entry
        by_id[entry_id] = entry
    if [entry["window_id"] for entry in entries] != sorted(FROZEN_WINDOWS):
        raise B0CorePlanV2Error("entry order is not canonical window order")
    if set(by_window) != set(FROZEN_WINDOWS) or families != {
        "afrl": 1,
        "aqualoc_archaeology": 10,
        "aqualoc_harbor": 6,
        "ntnu": 3,
    }:
        raise B0CorePlanV2Error("entry frozen-window/family coverage drift")

    reused_from_entries = {
        window_id: _clone_json(entry["materialization"]["v1_recipe"])
        for window_id, entry in by_window.items()
        if entry["dataset_family"] != "ntnu"
    }
    observed_recipe_authority = payload.get(REUSED_RECIPE_AUTHORITY_FIELD)
    if not isinstance(observed_recipe_authority, Mapping):
        raise B0CorePlanV2Error("reused-recipe authority binding is absent")
    try:
        rebuilt_recipe_authority = _reused_recipe_authority_binding(
            str(observed_recipe_authority.get("authority_kind")),
            reused_from_entries,
            observed_recipe_authority.get("authority_self_hash"),
        )
    except (TypeError, ValueError) as error:
        raise B0CorePlanV2Error("reused-recipe authority binding is malformed") from error
    if _clone_json(observed_recipe_authority) != rebuilt_recipe_authority:
        raise B0CorePlanV2Error("reused-recipe authority binding/content drift")
    if validated_v1_plan_or_recipes is not None:
        authority_recipes, exact_recipe_authority = _extract_reused_recipes(
            validated_v1_plan_or_recipes, FROZEN_WINDOWS
        )
        if (
            authority_recipes != reused_from_entries
            or exact_recipe_authority != rebuilt_recipe_authority
        ):
            raise B0CorePlanV2Error(
                "core recipes do not exactly rebuild from supplied authority"
            )

    reused_for_queue = {
        window_id: entry["materialization"]["v1_recipe"]
        for window_id, entry in by_window.items()
        if entry["dataset_family"] != "ntnu"
    }
    live_authority = load_live_queue_authority(root)
    live_queue = _normalize_queue_rows(
        _rows_from_queue_authority(live_authority), FROZEN_WINDOWS, reused_for_queue
    )
    live_hashes = [row["immutable_queue_row_hash"] for row in live_queue]
    expected_queue_authority = {
        "record": {
            "path": FROZEN_QUEUE_RELATIVE,
            "sha256": FROZEN_QUEUE_SHA256,
            "size_bytes": FROZEN_QUEUE_SIZE_BYTES,
        },
        "queue_row_hash_schema": QUEUE_ROW_HASH_SCHEMA,
        "ordered_selected_row_hashes": live_hashes,
        "ordered_selected_row_hashes_sha256": hashlib.sha256(
            canonical_json(live_hashes).encode("utf-8")
        ).hexdigest(),
    }
    if payload.get("frozen_queue_authority") != expected_queue_authority:
        raise B0CorePlanV2Error("core mappings are not bound to the live frozen queue")

    mapping_keys = set()
    mapping_by_queue: Dict[int, Mapping[str, Any]] = {}
    for mapping in mappings:
        if not isinstance(mapping, Mapping) or set(mapping) != {
            "queue_index",
            "run_id",
            "window_id",
            "dataset_family",
            "sequence",
            "arm",
            "replay_index",
            "runner_start",
            "runner_end_or_duration",
            "runner_unit",
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
            "immutable_queue_row_hash",
            "entry_id",
            "runtime_input_path",
            "replay_slice",
        }:
            raise B0CorePlanV2Error("preparation mapping schema drift")
        try:
            queue_index = int(mapping["queue_index"])
            replay_index = int(mapping["replay_index"])
        except (TypeError, ValueError) as error:
            raise B0CorePlanV2Error("preparation mapping identity is malformed") from error
        window_id = str(mapping.get("window_id", ""))
        arm = mapping.get("arm")
        key = (window_id, arm, replay_index)
        entry = by_window.get(window_id)
        if entry is not None and entry["dataset_family"] == "ntnu":
            expected_mapping_runner = (
                FROZEN_WINDOWS[window_id]["window_start_s"], "45", "second"
            )
        elif entry is not None:
            expected_mapping_runner = (
                entry["preparation"]["runner_start"],
                entry["preparation"]["runner_end_or_duration"],
                entry["preparation"]["runner_unit"],
            )
        else:
            expected_mapping_runner = None
        if (
            entry is None
            or type(mapping.get("queue_index")) is not int
            or type(mapping.get("replay_index")) is not int
            or arm not in ARMS
            or replay_index not in REPLAY_INDICES
            or key in mapping_keys
            or queue_index in mapping_by_queue
            or not isinstance(mapping.get("run_id"), str)
            or not mapping["run_id"]
            or mapping.get("immutable_queue_row_hash")
            != _immutable_queue_row_hash(mapping)
            or mapping.get("dataset_family") != entry["dataset_family"]
            or mapping.get("sequence") != entry["sequence"]
            or (
                mapping.get("runner_start"),
                mapping.get("runner_end_or_duration"),
                mapping.get("runner_unit"),
            ) != expected_mapping_runner
            or not isinstance(mapping.get("source_run_id"), str)
            or not mapping["source_run_id"]
            or not isinstance(mapping.get("source_provenance_kind"), str)
            or not mapping["source_provenance_kind"]
            or _SHA256.fullmatch(str(mapping.get("source_provenance_hash", ""))) is None
            or mapping.get("entry_id") != entry["entry_id"]
            or mapping.get("runtime_input_path") != entry["target"]["path"]
            or mapping.get("replay_slice") is not None
        ):
            raise B0CorePlanV2Error("preparation mapping identity/target/slice drift")
        mapping_keys.add(key)
        mapping_by_queue[queue_index] = mapping
    expected_mapping_keys = {
        (window_id, arm, replay_index)
        for window_id in FROZEN_WINDOWS
        for arm in ARMS
        for replay_index in REPLAY_INDICES
    }
    if (
        mapping_keys != expected_mapping_keys
        or set(mapping_by_queue) != set(range(1, 241))
        or len({mapping["run_id"] for mapping in mappings}) != 240
        or [mapping["queue_index"] for mapping in mappings] != list(range(1, 241))
        or [mapping["immutable_queue_row_hash"] for mapping in mappings]
        != live_hashes
    ):
        raise B0CorePlanV2Error("preparation mapping 20 x 4 x 3 coverage drift")

    binding_keys = set()
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != {
            "queue_index",
            "run_id",
            "window_id",
            "dataset_family",
            "sequence",
            "runner_start",
            "runner_end_or_duration",
            "runner_unit",
            "replay_index",
            "arm",
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
            "immutable_queue_row_hash",
            "entry_id",
        }:
            raise B0CorePlanV2Error("B0 binding schema drift")
        try:
            queue_index = int(binding["queue_index"])
            replay_index = int(binding["replay_index"])
        except (TypeError, ValueError) as error:
            raise B0CorePlanV2Error("B0 binding identity is malformed") from error
        window_id = str(binding.get("window_id", ""))
        key = (window_id, replay_index)
        entry = by_window.get(window_id)
        mapping = mapping_by_queue.get(queue_index)
        expected_window = FROZEN_WINDOWS.get(window_id)
        if entry is None or expected_window is None:
            raise B0CorePlanV2Error("B0 binding references an unknown entry")
        if expected_window["dataset_family"] == "ntnu":
            expected_runner = (expected_window["window_start_s"], "45", "second")
        else:
            recipe = entry["materialization"]["v1_recipe"]
            expected_runner = (
                _number(recipe["runner_start"], label="binding runner start"),
                _number(
                    recipe["runner_end_or_duration"], label="binding runner end/duration"
                ),
                recipe["runner_unit"],
            )
        if (
            key in binding_keys
            or type(binding.get("queue_index")) is not int
            or type(binding.get("replay_index")) is not int
            or binding.get("arm") != B0_ARM
            or replay_index not in REPLAY_INDICES
            or binding.get("dataset_family") != entry["dataset_family"]
            or binding.get("sequence") != entry["sequence"]
            or (
                binding.get("runner_start"),
                binding.get("runner_end_or_duration"),
                binding.get("runner_unit"),
            )
            != expected_runner
            or binding.get("source_run_id") != "B0_NATIVE_DATA:%s" % window_id
            or binding.get("source_provenance_kind") != "B0_NATIVE_DATA_IDENTITY_V1"
            or binding.get("source_provenance_hash")
            != entry["b0_source_provenance_hash"]
            or binding.get("immutable_queue_row_hash")
            != _immutable_queue_row_hash(binding)
            or binding.get("entry_id") != entry["entry_id"]
            or mapping is None
            or mapping.get("run_id") != binding.get("run_id")
            or mapping.get("window_id") != window_id
            or mapping.get("arm") != B0_ARM
            or mapping.get("replay_index") != replay_index
            or mapping.get("immutable_queue_row_hash")
            != binding.get("immutable_queue_row_hash")
        ):
            raise B0CorePlanV2Error("B0 binding queue/window/provenance drift")
        binding_keys.add(key)
    if [binding["queue_index"] for binding in bindings] != sorted(
        binding["queue_index"] for binding in bindings
    ):
        raise B0CorePlanV2Error("B0 binding order is not canonical queue order")
    if binding_keys != {
        (window_id, replay_index)
        for window_id in FROZEN_WINDOWS
        for replay_index in REPLAY_INDICES
    }:
        raise B0CorePlanV2Error("B0 binding 20 x 3 coverage drift")
    return str(payload[SELF_HASH_FIELD])


__all__ = [
    "AFRL_BUS_CAMCHAIN_PATH",
    "AFRL_IMU_PATH",
    "AFRL_RAW_PATH",
    "AFRL_TARGET_PATH",
    "ARMS",
    "B0CorePlanV2Error",
    "B0_ARM",
    "FROZEN_WINDOWS",
    "FROZEN_QUEUE_RELATIVE",
    "FROZEN_QUEUE_SHA256",
    "FROZEN_QUEUE_SIZE_BYTES",
    "COMPLETE_V1_RECIPE_AUTHORITY_KIND",
    "LEGACY_RECIPE_AUTHORITY_KIND",
    "REUSED_RECIPE_AUTHORITY_FIELD",
    "V1_AUTHORITY_ENVELOPE_HASH",
    "V1_AUTHORITY_ENVELOPE_SCHEMA",
    "NTNU_BOUNDARY_RULE",
    "NTNU_RECORD_T0_NS",
    "NTNU_SOURCE_PATH",
    "NTNU_WINDOW_SPECS",
    "SELF_HASH_FIELD",
    "ValidatedQueueAuthority",
    "build_core_plan",
    "canonical_json",
    "document_hash",
    "make_v1_authority_envelope",
    "make_queue_authority_envelope",
    "load_live_queue_authority",
    "validate_core_plan",
]
