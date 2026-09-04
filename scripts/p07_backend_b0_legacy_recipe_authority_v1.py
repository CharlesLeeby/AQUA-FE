#!/usr/bin/env python3
"""Build a nonformal live authority for the 17 reusable P07 B0 recipes.

The authority contains exactly sixteen AQUALOC recipes and the one AFRL
dedicated-short-bag recipe produced by the legacy v1 builder contract.  NTNU
is intentionally excluded: this module never opens or hashes the 26.57 GB
fjord bag.  The default CLI is a read-only JSON preview and this module has no
publication or execution entry point.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from scripts import build_p07_backend_b0_materialization_lock_v1 as legacy
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    import build_p07_backend_b0_materialization_lock_v1 as legacy  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUILDER_RELATIVE = "scripts/p07_backend_b0_legacy_recipe_authority_v1.py"
TEST_RELATIVE = "scripts/tests/test_p07_backend_b0_legacy_recipe_authority_v1.py"
SCHEMA_VERSION = "isj-p07-backend-b0-legacy-recipe-authority-v1"
STATUS = "NONFORMAL_LIVE_VALIDATED_LEGACY_RECIPE_AUTHORITY_NO_EXECUTION"
SELF_HASH_FIELD = "legacy_recipe_authority_hash"
OUTCOME_BOUNDARY = "B0_INPUT_RECIPE_GOVERNANCE_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
AFRL_WINDOW_ID = "afrl:bus_outside:0001"
AFRL_SOURCE_PATH = (
    "logs/afrl_cave_v31/external_klt_every2_"
    "isj_p07_afrl_bus_outside_0001_b1_attempt01/cave_gennie_short.bag"
)
AFRL_TARGET_PATH = "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag"
FROZEN_LEGACY_B0_BINDINGS_SHA256 = (
    "c297bfcac743b5523fd1e808e70f99f22c1a38eb2070f685bdc0ca8bc0c04b1a"
)
FROZEN_LEGACY_RECIPES_SHA256 = (
    "920e46b79154af02ec33de5faac60f75ab39601e83254ac8eaa6df482d324a7c"
)
FROZEN_INPUT_ARTIFACTS_SHA256 = (
    "09d82d084f7993234577c0dc7cf3034ee1d464afd8ee19d6d7837754f57123d6"
)
FROZEN_INPUT_ARTIFACT_PATHS_SHA256 = (
    "b9805a545cf955a916f9657bd6bc2c798ef84ec4a5bee12b5d9c8eaec15566a1"
)
FROZEN_INPUT_ARTIFACT_COUNT = 73
FROZEN_DEPENDENCY_SOURCES_SHA256 = (
    "bdfb905649604cc47976b0eb1462c87cff7ca2f8279fb687e4eeda7d5c105196"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_WINDOW_ROWS: Tuple[Tuple[str, str, str, str, str, int], ...] = (
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
)
WINDOWS: Mapping[str, Mapping[str, Any]] = {
    row[0]: {
        "window_id": row[0],
        "dataset_family": row[1],
        "sequence": row[2],
        "window_start_s": row[3],
        "window_end_s": row[4],
        "input_frame_count": row[5],
    }
    for row in _WINDOW_ROWS
}

_RAW_PATHS: Mapping[Tuple[str, str], str] = {
    **{
        ("aqualoc_archaeology", sequence): (
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_sequence_%d_raw_data.tar.gz" % int(sequence[1:])
        )
        for sequence in ("A01", "A02", "A03", "A04", "A07", "A08", "A10")
    },
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

DEPENDENCY_SOURCE_PATHS = (
    # Self/test records would require a recursive file hash.  The frozen
    # dependency authority therefore covers only independently hashable
    # runtime dependencies; source/test bytes are guarded by the release hash
    # fuse rather than being represented as payload-supplied evidence.
    "scripts/build_p07_backend_b0_materialization_lock_v1.py",
    "scripts/build_p07_backend_replay_queue_v1.py",
    "scripts/validate_p07_backend_replay_queue_v1.py",
    "scripts/p07_backend_replay_common_v1.py",
    "scripts/p07_backend_formal_io_v1.py",
    "scripts/p07_g0_publisher_v1.py",
    "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
)


class LegacyRecipeAuthorityError(RuntimeError):
    """The 17-recipe authority is incomplete, drifted, or ambiguous."""


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise LegacyRecipeAuthorityError("authority is not canonical JSON") from error


def document_hash(payload: Mapping[str, Any], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _record(value: Any, *, label: str) -> Dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"path", "sha256", "size_bytes"}
        or not isinstance(value.get("path"), str)
        or not value["path"]
        or _SHA256.fullmatch(str(value.get("sha256", ""))) is None
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
    ):
        raise LegacyRecipeAuthorityError("invalid %s record" % label)
    return dict(value)


def _reference_path(family: str, sequence: str) -> str:
    number = int(sequence[1:])
    if family == "aqualoc_archaeology":
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


def _argv_value(argv: Any, flag: str) -> str:
    if not isinstance(argv, list) or argv.count(flag) != 1:
        raise LegacyRecipeAuthorityError("recipe argv lacks one %s" % flag)
    index = argv.index(flag)
    if index + 1 >= len(argv) or not isinstance(argv[index + 1], str):
        raise LegacyRecipeAuthorityError("recipe argv value is malformed: %s" % flag)
    return argv[index + 1]


def _validate_identity(value: Any, source_path: str, source_sha: str) -> None:
    keys = {
        "path", "path_kind", "symlink_components", "resolved_target_path",
        "resolved_target_identity", "expected_sha256", "sha256_verified",
        "observed_sha256",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or value.get("path") != source_path
        or value.get("expected_sha256") != source_sha
        or value.get("sha256_verified") is not True
        or value.get("observed_sha256") != source_sha
        or value.get("path_kind")
        not in {"PLAIN_REGULAR_FILE", "CANONICAL_SYMLINK_TARGET"}
        or not isinstance(value.get("symlink_components"), list)
        or not isinstance(value.get("resolved_target_path"), str)
        or not isinstance(value.get("resolved_target_identity"), Mapping)
        or set(value["resolved_target_identity"])
        != {"device", "inode", "mode", "size_bytes", "mtime_ns", "owner_uid"}
        or any(type(item) is not int for item in value["resolved_target_identity"].values())
    ):
        raise LegacyRecipeAuthorityError("source identity/path/hash drift")
    components = value["symlink_components"]
    if (value["path_kind"] == "PLAIN_REGULAR_FILE") != (len(components) == 0):
        raise LegacyRecipeAuthorityError("source identity symlink kind drift")
    for component in components:
        if (
            not isinstance(component, Mapping)
            or set(component) != {"path", "link_target", "lstat_identity"}
            or not isinstance(component.get("path"), str)
            or not isinstance(component.get("link_target"), str)
            or not isinstance(component.get("lstat_identity"), Mapping)
            or set(component["lstat_identity"])
            != {"device", "inode", "mode", "size_bytes", "mtime_ns", "owner_uid"}
            or any(type(item) is not int for item in component["lstat_identity"].values())
        ):
            raise LegacyRecipeAuthorityError("source symlink component drift")


_BASE_RECIPE_KEYS = {
    "window_id", "dataset_family", "sequence", "runner_start",
    "runner_end_or_duration", "runner_unit", "target_path", "expected_sha256",
    "expected_size_bytes", "expected_topic_counts", "camera_topic", "disposition",
    "derivation_kind", "source_raw_path", "source_raw_sha256",
    "source_path_identity", "converter_argv_template", "evidence",
    "held_out_trajectory_outcome_read", "source_provenance_hash", "recipe_hash",
}


def _validate_recipe(recipe: Any) -> Dict[str, Any]:
    if not isinstance(recipe, Mapping):
        raise LegacyRecipeAuthorityError("legacy recipe is not an object")
    window_id = recipe.get("window_id")
    window = WINDOWS.get(str(window_id))
    if window is None:
        raise LegacyRecipeAuthorityError("unknown or excluded legacy recipe window")
    expected_keys = set(_BASE_RECIPE_KEYS)
    if window_id == "aqualoc_archaeology:A04:0002":
        expected_keys.add("a04_layout_recovery")
    if window_id == AFRL_WINDOW_ID:
        expected_keys.update({"expected_camera_stamp_range_ns", "source_input_contract"})
    clone = _clone(recipe)
    if (
        set(clone) != expected_keys
        or clone.get("dataset_family") != window["dataset_family"]
        or clone.get("sequence") != window["sequence"]
        or clone.get("recipe_hash") != legacy.document_hash(clone, "recipe_hash")
        or clone.get("held_out_trajectory_outcome_read") is not False
        or _SHA256.fullmatch(str(clone.get("expected_sha256", ""))) is None
        or _SHA256.fullmatch(str(clone.get("source_raw_sha256", ""))) is None
        or _SHA256.fullmatch(str(clone.get("source_provenance_hash", ""))) is None
        or type(clone.get("expected_size_bytes")) is not int
        or clone["expected_size_bytes"] <= 0
    ):
        raise LegacyRecipeAuthorityError("legacy recipe schema/hash drift")
    _validate_identity(
        clone.get("source_path_identity"),
        str(clone.get("source_raw_path")),
        str(clone.get("source_raw_sha256")),
    )
    evidence = clone.get("evidence")
    if not isinstance(evidence, list):
        raise LegacyRecipeAuthorityError("legacy recipe evidence drift")
    if window_id != AFRL_WINDOW_ID:
        for index, item in enumerate(evidence):
            _record(item, label="recipe evidence[%d]" % index)

    family = str(window["dataset_family"])
    if family.startswith("aqualoc_"):
        sequence = str(window["sequence"])
        number = int(sequence[1:])
        start = int(window["window_start_s"]) * 20
        end = int(window["window_end_s"]) * 20
        prefix = "archaeo" if family == "aqualoc_archaeology" else "harbor"
        source = _RAW_PATHS[(family, sequence)]
        counts = clone.get("expected_topic_counts")
        if (
            clone.get("source_raw_path") != source
            or _argv_value(clone.get("converter_argv_template"), "--input") != source
            or _argv_value(clone.get("converter_argv_template"), "--gt-txt")
            != _reference_path(family, sequence)
            or _argv_value(clone.get("converter_argv_template"), "--start-index")
            != str(start)
            or _argv_value(clone.get("converter_argv_template"), "--end-index")
            != str(end)
            or clone.get("runner_start") != str(start)
            or clone.get("runner_end_or_duration") != str(end)
            or clone.get("runner_unit") != "frame"
            or clone.get("target_path")
            != "datasets/aqualoc/rosbags/%s%02d_%d_%d.bag"
            % (prefix, number, start, end)
            or clone.get("camera_topic") != "/camera/image_raw"
            or clone.get("derivation_kind") != "PREMATERIALIZED_WINDOW_BAG"
            or clone.get("disposition")
            not in {"PREMATERIALIZED_EXACT_REUSE", "REBUILD_REQUIRED_OR_EXACT_RECONCILE"}
            or not isinstance(counts, Mapping)
            or set(counts) != {"/camera/image_raw", "/rtimulib_node/imu", "/aqualoc/colmap_gt"}
            or counts.get("/camera/image_raw") != int(window["input_frame_count"]) + 1
            or any(type(count) is not int or count <= 0 for count in counts.values())
        ):
            raise LegacyRecipeAuthorityError("AQUALOC recipe scientific drift")
        recovery = clone.get("a04_layout_recovery")
        if window_id == "aqualoc_archaeology:A04:0002":
            if (
                not isinstance(recovery, Mapping)
                or set(recovery) != {
                    "execution_raw_root_argument", "q55_frozen_raw_root_argument",
                    "semantic_equivalence", "expected_topic_counts",
                    "q55_recovery_lock", "q55_recovery_closeout", "raw_materialization",
                }
                or recovery.get("execution_raw_root_argument") != "."
                or recovery.get("q55_frozen_raw_root_argument") != ""
                or recovery.get("semantic_equivalence")
                != "BOUND_CONVERTER_MEMBER_PATH_IGNORES_EMPTY_AND_DOT_COMPONENTS"
                or recovery.get("expected_topic_counts") != counts
            ):
                raise LegacyRecipeAuthorityError("A04 recovery drift")
            for key in ("q55_recovery_lock", "q55_recovery_closeout", "raw_materialization"):
                _record(recovery[key], label="A04 %s" % key)
    else:
        counts = clone.get("expected_topic_counts")
        stamps = clone.get("expected_camera_stamp_range_ns")
        contract = clone.get("source_input_contract")
        if (
            clone.get("source_raw_path") != AFRL_SOURCE_PATH
            or clone.get("target_path") != AFRL_TARGET_PATH
            or clone.get("source_raw_sha256") != clone.get("expected_sha256")
            or clone.get("runner_start") != "45"
            or clone.get("runner_end_or_duration") != "45"
            or clone.get("runner_unit") != "second"
            or clone.get("camera_topic") != "/camera/image_raw"
            or clone.get("disposition") != "EXACT_COPY_REQUIRED_OR_RECONCILE"
            or clone.get("derivation_kind") != "PREMATERIALIZED_WINDOW_BAG"
            or clone.get("converter_argv_template")
            != ["INTERNAL_EXACT_COPY_NOREPLACE", AFRL_SOURCE_PATH, "{OUTPUT}"]
            or not isinstance(counts, Mapping)
            or counts != {"/afrl/colmap_gt": 565, "/camera/image_raw": 565, "/imu/imu": 4500}
            or not isinstance(stamps, Mapping)
            or set(stamps) != {"first", "last"}
            or any(type(value) is not int for value in stamps.values())
            or stamps["first"] >= stamps["last"]
            or not isinstance(contract, Mapping)
            or set(contract) != {
                "topic_counts", "camera_stamp_range_ns", "camera_stamp_source",
                "trajectory_values_interpreted",
            }
            or contract.get("topic_counts") != counts
            or contract.get("camera_stamp_range_ns") != stamps
            or contract.get("camera_stamp_source") != "sensor_msgs/Image.header.stamp"
            or contract.get("trajectory_values_interpreted") is not False
            or len(evidence) != 3
        ):
            raise LegacyRecipeAuthorityError("AFRL short-bag recipe drift")
        _record(evidence[0], label="AFRL audit evidence")
        _record(evidence[1], label="AFRL output manifest evidence")
        manifest = evidence[2]
        if (
            not isinstance(manifest, Mapping)
            or set(manifest) != {
                "classification", "path", "sha256", "size_bytes",
                "vins_csv_absent", "vins_output_empty",
            }
            or manifest.get("classification")
            != "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME"
            or manifest.get("vins_csv_absent") is not True
            or manifest.get("vins_output_empty") is not True
        ):
            raise LegacyRecipeAuthorityError("AFRL replay manifest evidence drift")
        _record(
            {key: manifest[key] for key in ("path", "sha256", "size_bytes")},
            label="AFRL replay manifest file",
        )
    return clone


def build_authority_payload(
    *,
    recipes: Sequence[Mapping[str, Any]],
    queue_bindings: Sequence[Mapping[str, Any]],
    input_artifacts: Sequence[Mapping[str, Any]],
    dependency_sources: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    validated = [_validate_recipe(recipe) for recipe in recipes]
    if [recipe["window_id"] for recipe in validated] != sorted(WINDOWS):
        raise LegacyRecipeAuthorityError("recipes are not exact canonical 17-window order")
    bindings = [_clone(binding) for binding in queue_bindings]
    artifacts = [_record(item, label="input artifact") for item in input_artifacts]
    dependencies = [_record(item, label="dependency source") for item in dependency_sources]
    sorted_artifacts = sorted(artifacts, key=lambda item: item["path"])
    sorted_dependencies = sorted(dependencies, key=lambda item: item["path"])
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "recipe_count": 17,
        "aqualoc_recipe_count": 16,
        "afrl_recipe_count": 1,
        "ntnu_recipe_count": 0,
        "window_ids": sorted(WINDOWS),
        "recipes": validated,
        "recipes_sha256": _canonical_sha256(validated),
        "queue_bindings": bindings,
        "queue_bindings_sha256": _canonical_sha256(bindings),
        "input_artifacts": sorted_artifacts,
        "input_artifact_paths_sha256": _canonical_sha256(
            [item["path"] for item in sorted_artifacts]
        ),
        "input_artifacts_sha256": _canonical_sha256(sorted_artifacts),
        "dependency_sources": sorted_dependencies,
        "dependency_sources_sha256": _canonical_sha256(sorted_dependencies),
        "policy": {
            "ntnu_excluded": True,
            "ntnu_raw_bag_opened_or_hashed": False,
            "formal_artifact_published": False,
            "materialization_authorized": False,
            "vins_execution_authorized": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
        SELF_HASH_FIELD: "",
    }
    payload[SELF_HASH_FIELD] = document_hash(payload, SELF_HASH_FIELD)
    validate_authority_payload(payload)
    return payload


def _validate_bindings(bindings: Any, recipes: Mapping[str, Mapping[str, Any]]) -> None:
    if not isinstance(bindings, list) or len(bindings) != 51:
        raise LegacyRecipeAuthorityError("authority requires exact 17 x 3 B0 bindings")
    keys = {
        "queue_index", "run_id", "window_id", "arm", "dataset_family", "sequence",
        "runner_start", "runner_end_or_duration", "runner_unit", "source_run_id",
        "source_provenance_kind", "source_provenance_hash",
    }
    seen = set()
    indices = set()
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != keys:
            raise LegacyRecipeAuthorityError("queue binding schema drift")
        window_id = str(binding.get("window_id", ""))
        recipe = recipes.get(window_id)
        try:
            queue_index = int(binding["queue_index"])
        except (TypeError, ValueError, KeyError) as error:
            raise LegacyRecipeAuthorityError("queue binding index drift") from error
        identity = (window_id, str(binding.get("run_id", "")))
        if (
            recipe is None
            or identity in seen
            or queue_index in indices
            or type(binding.get("queue_index")) is not int
            or binding.get("arm") != queue_builder.B0
            or binding.get("dataset_family") != recipe["dataset_family"]
            or binding.get("sequence") != recipe["sequence"]
            or binding.get("source_run_id") != "B0_NATIVE_DATA:%s" % window_id
            or binding.get("source_provenance_kind") != "B0_NATIVE_DATA_IDENTITY_V1"
            or binding.get("source_provenance_hash") != recipe["source_provenance_hash"]
            or (
                binding.get("runner_start"), binding.get("runner_end_or_duration"),
                binding.get("runner_unit"),
            )
            != (
                recipe["runner_start"], recipe["runner_end_or_duration"],
                recipe["runner_unit"],
            )
        ):
            raise LegacyRecipeAuthorityError("queue binding provenance drift")
        seen.add(identity)
        indices.add(queue_index)
    per_window = {window_id: 0 for window_id in recipes}
    for binding in bindings:
        per_window[str(binding["window_id"])] += 1
    if set(per_window.values()) != {3}:
        raise LegacyRecipeAuthorityError("queue bindings are not three per recipe")


def validate_authority_payload(payload: Mapping[str, Any]) -> str:
    expected_keys = {
        "schema_version", "status", "recipe_count", "aqualoc_recipe_count",
        "afrl_recipe_count", "ntnu_recipe_count", "window_ids", "recipes",
        "recipes_sha256", "queue_bindings", "queue_bindings_sha256",
        "input_artifacts", "input_artifact_paths_sha256",
        "input_artifacts_sha256", "dependency_sources",
        "dependency_sources_sha256", "policy",
        "held_out_trajectory_outcome_read", "outcome_boundary", SELF_HASH_FIELD,
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise LegacyRecipeAuthorityError("authority top-level schema drift")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != document_hash(payload, SELF_HASH_FIELD)
        or payload.get("recipe_count") != 17
        or payload.get("aqualoc_recipe_count") != 16
        or payload.get("afrl_recipe_count") != 1
        or payload.get("ntnu_recipe_count") != 0
        or payload.get("recipes_sha256") != FROZEN_LEGACY_RECIPES_SHA256
        or payload.get("recipes_sha256")
        != _canonical_sha256(payload.get("recipes"))
        or payload.get("queue_bindings_sha256")
        != FROZEN_LEGACY_B0_BINDINGS_SHA256
        or payload.get("queue_bindings_sha256")
        != _canonical_sha256(payload.get("queue_bindings"))
        or payload.get("input_artifact_paths_sha256")
        != FROZEN_INPUT_ARTIFACT_PATHS_SHA256
        or payload.get("input_artifacts_sha256")
        != FROZEN_INPUT_ARTIFACTS_SHA256
        or payload.get("dependency_sources_sha256")
        != FROZEN_DEPENDENCY_SOURCES_SHA256
        or payload.get("window_ids") != sorted(WINDOWS)
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
        or payload.get("policy") != {
            "ntnu_excluded": True,
            "ntnu_raw_bag_opened_or_hashed": False,
            "formal_artifact_published": False,
            "materialization_authorized": False,
            "vins_execution_authorized": False,
        }
    ):
        raise LegacyRecipeAuthorityError("authority status/count/hash/policy drift")
    recipes_raw = payload.get("recipes")
    if not isinstance(recipes_raw, list):
        raise LegacyRecipeAuthorityError("authority recipes are absent")
    recipes = [_validate_recipe(recipe) for recipe in recipes_raw]
    if [recipe["window_id"] for recipe in recipes] != sorted(WINDOWS):
        raise LegacyRecipeAuthorityError("authority recipe coverage/order drift")
    by_window = {recipe["window_id"]: recipe for recipe in recipes}
    _validate_bindings(payload.get("queue_bindings"), by_window)
    for name in ("input_artifacts", "dependency_sources"):
        values = payload.get(name)
        if not isinstance(values, list) or not values:
            raise LegacyRecipeAuthorityError("authority %s are absent" % name)
        records = [_record(item, label=name) for item in values]
        paths = [record["path"] for record in records]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise LegacyRecipeAuthorityError("authority %s order/uniqueness drift" % name)
    dependency_paths = {item["path"] for item in payload["dependency_sources"]}
    if (
        dependency_paths != set(DEPENDENCY_SOURCE_PATHS)
        or payload["dependency_sources_sha256"]
        != _canonical_sha256(payload["dependency_sources"])
    ):
        raise LegacyRecipeAuthorityError("dependency source closure drift")
    artifact_paths = [item["path"] for item in payload["input_artifacts"]]
    if (
        len(artifact_paths) != FROZEN_INPUT_ARTIFACT_COUNT
        or payload["input_artifact_paths_sha256"]
        != _canonical_sha256(artifact_paths)
        or payload["input_artifacts_sha256"]
        != _canonical_sha256(payload["input_artifacts"])
    ):
        raise LegacyRecipeAuthorityError("input artifact exact allowlist/authority drift")
    return str(payload[SELF_HASH_FIELD])


def _build_afrl_recipe(
    window: Mapping[str, str],
    b1_source: Mapping[str, Any],
    *,
    root: Path,
) -> Dict[str, Any]:
    audit, observed_audit = legacy._json_snapshot(
        root / str(b1_source["input_audit_path"]), root=root, label="AFRL B1 audit"
    )
    expected_audit = b1_source.get("input_audit_sha256")
    if expected_audit and expected_audit != observed_audit["sha256"]:
        raise LegacyRecipeAuthorityError("AFRL B1 audit hash drift")
    manifests = audit.get("afrl_replay_manifest")
    if not isinstance(manifests, list) or len(manifests) != 1:
        raise LegacyRecipeAuthorityError("AFRL audit lacks one replay manifest")
    provenance = b1_source.get("source_provenance")
    if not isinstance(provenance, Mapping):
        raise LegacyRecipeAuthorityError("AFRL source provenance is absent")
    output_record = provenance.get("output_hash_manifest")
    audit_record = provenance.get("audit")
    if not isinstance(output_record, Mapping) or not isinstance(audit_record, Mapping):
        raise LegacyRecipeAuthorityError("AFRL audit/manifest provenance is absent")
    expected = legacy._hash_manifest_entry(
        root=root, record=output_record, expected_path=AFRL_SOURCE_PATH
    )
    snapshot = legacy._bound_file_snapshot_or_absent(
        root, AFRL_SOURCE_PATH, label="AFRL frozen short bag"
    )
    if snapshot is None:
        raise LegacyRecipeAuthorityError("AFRL short bag is absent")
    source_content, source_record = snapshot
    if source_record["sha256"] != expected:
        raise LegacyRecipeAuthorityError("AFRL short bag hash/manifest drift")
    contract = legacy._bag_input_contract_bytes(source_content, "/camera/image_raw")
    identity = legacy._capture_source_identity(
        root=root, relative=AFRL_SOURCE_PATH, expected_sha256=expected,
        expected_record=source_record,
    )
    recipe: Dict[str, Any] = {
        "window_id": window["window_id"],
        "dataset_family": "afrl",
        "sequence": window["sequence"],
        "runner_start": queue_builder.number(window["window_start_s"]),
        "runner_end_or_duration": queue_builder.number(
            float(window["window_end_s"]) - float(window["window_start_s"])
        ),
        "runner_unit": "second",
        "target_path": AFRL_TARGET_PATH,
        "expected_sha256": expected,
        "expected_size_bytes": source_record["size_bytes"],
        "expected_topic_counts": contract["topic_counts"],
        "expected_camera_stamp_range_ns": contract["camera_stamp_range_ns"],
        "camera_topic": "/camera/image_raw",
        "disposition": "EXACT_COPY_REQUIRED_OR_RECONCILE",
        "derivation_kind": "PREMATERIALIZED_WINDOW_BAG",
        "source_raw_path": AFRL_SOURCE_PATH,
        "source_raw_sha256": expected,
        "source_path_identity": identity,
        "converter_argv_template": [
            "INTERNAL_EXACT_COPY_NOREPLACE", AFRL_SOURCE_PATH, "{OUTPUT}"
        ],
        "source_input_contract": contract,
        "evidence": [dict(audit_record), dict(output_record), dict(manifests[0])],
        "held_out_trajectory_outcome_read": False,
        "recipe_hash": "",
    }
    recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")
    return recipe


def build_live_authority(root: Path = ROOT) -> Dict[str, Any]:
    """Read-only live preview; deliberately selects windows before recipe work."""

    workspace = Path(root).absolute()
    queue_rows, queue_lock, backend_records = legacy._read_backend_inputs(root=workspace)
    manifest_path = workspace / queue_builder.MANIFEST.relative_to(queue_builder.ROOT)
    manifest_content, manifest_record = legacy._snapshot(
        manifest_path, root=workspace, label="dataset manifest v4"
    )
    _fields, all_windows = queue_builder._parse_csv_content(
        manifest_path, manifest_content
    )
    windows = {
        str(row["window_id"]): dict(row)
        for row in all_windows
        if str(row.get("window_id")) in WINDOWS
    }
    if set(windows) != set(WINDOWS):
        raise LegacyRecipeAuthorityError("live dataset manifest lacks exact legacy windows")
    eligibility_path = workspace / (
        "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
    )
    eligibility, eligibility_record = legacy._eligibility_rows_snapshot(
        eligibility_path, root=workspace
    )
    checksum_path = workspace / (
        "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt"
    )
    checksums, checksum_record = legacy._checksum_manifest_snapshot(
        checksum_path, root=workspace
    )
    receipts = legacy._receipt_by_window(workspace)
    b0_sources = legacy._source_by_window(queue_lock, queue_builder.B0)
    b1_sources = legacy._source_by_window(queue_lock, queue_builder.B1)

    recipes: List[Dict[str, Any]] = []
    for window_id in sorted(WINDOWS):
        window = windows[window_id]
        family = str(window["dataset_family"])
        eligibility_row = eligibility.get((family, str(window["sequence"])))
        if eligibility_row is None:
            raise LegacyRecipeAuthorityError("live eligibility lacks %s" % window_id)
        if family.startswith("aqualoc_"):
            recipe = legacy._aqualoc_recipe(
                window, b1_sources[window_id], eligibility_row, checksums, receipts,
                root=workspace,
            )
        elif family == "afrl":
            recipe = _build_afrl_recipe(window, b1_sources[window_id], root=workspace)
        else:
            raise LegacyRecipeAuthorityError("NTNU entered legacy recipe loop")
        recipe["source_provenance_hash"] = b0_sources[window_id][
            "source_provenance_hash"
        ]
        recipe["recipe_hash"] = legacy.document_hash(recipe, "recipe_hash")
        recipes.append(recipe)

    selected_rows = [
        dict(row) for row in queue_rows
        if row.get("arm") == queue_builder.B0 and row.get("window_id") in WINDOWS
    ]
    bindings = [
        {
            "queue_index": int(row["queue_index"]), "run_id": row["run_id"],
            "window_id": row["window_id"], "arm": row["arm"],
            "dataset_family": row["dataset_family"], "sequence": row["sequence"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"], "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
        }
        for row in selected_rows
    ]

    input_records: Dict[str, Dict[str, Any]] = {
        record["path"]: dict(record)
        for record in list(backend_records.values())
        + [manifest_record, eligibility_record, checksum_record]
    }
    for recipe in recipes:
        source_identity = recipe["source_path_identity"]
        input_records[str(recipe["source_raw_path"])] = {
            "path": str(recipe["source_raw_path"]),
            "sha256": str(recipe["source_raw_sha256"]),
            "size_bytes": int(
                source_identity["resolved_target_identity"]["size_bytes"]
            ),
        }
        if recipe["disposition"] == "PREMATERIALIZED_EXACT_REUSE":
            input_records[str(recipe["target_path"])] = {
                "path": str(recipe["target_path"]),
                "sha256": str(recipe["expected_sha256"]),
                "size_bytes": int(recipe["expected_size_bytes"]),
            }
        for item in recipe["evidence"]:
            input_records[str(item["path"])] = {
                key: item[key] for key in ("path", "sha256", "size_bytes")
            }
        recovery = recipe.get("a04_layout_recovery")
        if isinstance(recovery, Mapping):
            for key in ("q55_recovery_lock", "q55_recovery_closeout", "raw_materialization"):
                item = recovery[key]
                input_records[str(item["path"])] = dict(item)
        if str(recipe["dataset_family"]).startswith("aqualoc_"):
            reference = _reference_path(
                str(recipe["dataset_family"]), str(recipe["sequence"])
            )
            input_records[reference] = legacy._record(
                workspace / reference, root=workspace
            )
    for window_id in WINDOWS:
        audit_path = str(b1_sources[window_id]["input_audit_path"])
        input_records[audit_path] = legacy._record(
            workspace / audit_path, root=workspace
        )
    dependencies = [
        legacy._record(workspace / relative, root=workspace)
        for relative in DEPENDENCY_SOURCE_PATHS
    ]
    return build_authority_payload(
        recipes=recipes,
        queue_bindings=bindings,
        input_artifacts=list(input_records.values()),
        dependency_sources=dependencies,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    payload = build_live_authority(args.root)
    print(canonical_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FROZEN_DEPENDENCY_SOURCES_SHA256", "FROZEN_INPUT_ARTIFACTS_SHA256",
    "FROZEN_INPUT_ARTIFACT_PATHS_SHA256", "FROZEN_LEGACY_B0_BINDINGS_SHA256",
    "FROZEN_LEGACY_RECIPES_SHA256", "LegacyRecipeAuthorityError",
    "SCHEMA_VERSION", "SELF_HASH_FIELD", "STATUS", "WINDOWS",
    "build_authority_payload", "build_live_authority", "canonical_json",
    "document_hash", "validate_authority_payload",
]
