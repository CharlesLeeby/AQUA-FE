#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from scripts import audit_matched_birth_rawlk_pair_v1 as audit
from scripts import audit_superpoint_lk_carrier_v1 as audit_base
from scripts import matched_birth_rawlk_core_v1 as core
from scripts import run_matched_birth_arm_once_v1 as launcher
from scripts import build_matched_birth_rawlk_pair_freeze_v1 as freeze_builder


def _full_manifest(arm_id: str) -> dict[str, object]:
    """Small values, but the complete producer top-level schema."""

    source, learned = (
        (20, 1) if arm_id == audit.XFEAT_ARM else (21, 0)
    )
    return {
        "schema_version": core.SCHEMA_VERSION,
        "status": "FULL",
        "formal_eligible": True,
        "formal_eligibility_reason": "full_export_from_frozen_matched_cli_factory",
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "prefix": {},
        "attempt": {"identity": {}, "payload": {"arm_id": arm_id}},
        "inputs": {"locked": True},
        "common_contract": {"carrier": {"lk_win_size": [21, 21]}},
        "common_contract_sha256": "a" * 64,
        "arm_contract": {
            "arm_id": arm_id,
            "detector": {
                "family": "xfeat" if source == 20 else "gftt",
                "implementation_id": "x" if source == 20 else "g",
                "contract": {"max": 2048},
            },
            "provenance": {
                "source_code": source,
                "is_learned": learned,
                "backend_inert_for_frozen_consumer": True,
            },
        },
        "arm_contract_sha256": ("b" if source == 20 else "c") * 64,
        "pair_difference_policy": {"no_wildcard_allowlist": True},
        "code_artifacts": {
            "wrapper": {"path": arm_id, "size_bytes": 1, "sha256": ("d" if source == 20 else "e") * 64},
            "detector_dependencies": (
                {
                    "legacy_detector_adapter": {
                        "path": "x", "size_bytes": 1, "sha256": "f" * 64
                    },
                    "xfeat_modules_initializer": {
                        "path": "modules-init", "size_bytes": 1,
                        "sha256": "9" * 64,
                    },
                    **{
                        label: {
                            "path": label, "size_bytes": 1,
                            "sha256": "8" * 64,
                        }
                        for label in audit.matched_xfeat.FROZEN_TQDM_FILES
                    },
                }
                if source == 20 else {}
            ),
            "detector_runtime": {"identity": arm_id},
        },
        "outputs": {
            "feature_bag": {"path": arm_id + ".bag", "size_bytes": 1, "sha256": ("1" if source == 20 else "2") * 64},
            "raw_diagnostics_csv": {"path": arm_id + ".csv", "size_bytes": 1, "sha256": ("3" if source == 20 else "4") * 64},
            "legacy_primitive_manifest": {"path": arm_id + ".legacy.json", "size_bytes": 1, "sha256": ("5" if source == 20 else "6") * 64},
        },
        "legacy_prepublication_rebind": {
            "primitive_reported_work_bag_path": arm_id + ".work/primitive_features.bag",
            "primitive_reported_output_identity_after_path_rebind": {
                "path": arm_id + ".bag",
                "size_bytes": 1,
                "sha256": ("1" if source == 20 else "2") * 64,
            },
            "published_feature_bag_identity": {
                "path": arm_id + ".bag",
                "size_bytes": 1,
                "sha256": ("1" if source == 20 else "2") * 64,
            },
            "reason": (
                "frozen_primitive_writes_inside_private_work_directory; "
                "matched_transaction_publishes_the_identical_held_inode"
            ),
        },
        "nonfeature_stream_before": {"same": True},
        "nonfeature_stream_after": {"same": True},
        "metrics": {"observations": 1},
        "diagnostics_streams": {"row_count": 1800},
        "raw_frame_diagnostics": [],
        "runtime": {
            "elapsed_wall_ms": 1.0,
            "common_runtime": {},
            "post_factory_runtime": {},
            "post_carrier_runtime": {},
            "post_metadata_runtime": {},
        },
    }


def _diagnostic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    output = 0
    for index in range(audit.EXPECTED_RAW_FRAMES):
        tracked_before = output
        tracked_after = output
        slots = core.FEATURE_CAP - tracked_after
        called = slots > 0
        candidates = 1 if called else 0
        births = 1 if called else 0
        output = tracked_after + births
        rows.append(
            {
                "raw_index": index,
                "header_stamp_ns": 1_000 + index,
                "published": bool(index % 2),
                "adaptive_clahe_applied": bool(index % 3 == 0),
                "raw_image_sha256": f"{index:064x}"[-64:],
                "processed_image_sha256": f"{index + 1:064x}"[-64:],
                "tracked_before": tracked_before,
                "tracked_after": tracked_after,
                "dropped": 0,
                "slots_before_detect": slots,
                "detector_called": called,
                "detector_candidates": candidates,
                "births": births,
                "output_tracks": output,
                "fb_median_px": None,
                "fb_p95_px": None,
                "ncc_median": None,
            }
        )
    return rows


def _common_reconstruction_fixture() -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = [
        {key: row[key] for key in audit.COMMON_DIAGNOSTIC_FIELDS}
        for row in _diagnostic_rows()
    ]
    return rows, {
        "source_total_published_frames": 900,
        "selected_published_frames": 900,
        "cutoff_feature_record_stamp_ns": None,
        "raw_row_count": 1800,
        "published_raw_indices_sha256": "1" * 64,
        "raw_schedule_sha256": core._diagnostics_schedule_stream(rows),
        "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(rows),
        "image_shapes_hw": [[8, 8]],
    }


def _write_launcher_receipts(freeze: dict[str, object]) -> dict[str, object]:
    gate = {
        "governance": {
            "commands": freeze["authoritative_commands"],
            "launcher_identity": freeze["launcher_receipt_contract"]["launcher_identity"],
        }
    }
    for offset, arm_id in enumerate((audit.XFEAT_ARM, audit.GFTT_ARM)):
        command = freeze["authoritative_commands"]["arms"][arm_id]
        start_path = Path(command["launcher_start_receipt"])
        rc_path = Path(command["launcher_rc_receipt"])
        start = {
            "schema_version": launcher.START_RECEIPT_SCHEMA,
            "status": "START_NAMESPACE_CONSUMED_PREVALIDATION",
            "attempt_count": 1,
            "launcher_parent_pid": 1000 + offset,
            "launcher_process_start_count": 1,
            "reserved_producer_process_start_count": 1,
            "producer_process_started_at_receipt": False,
            "no_retry": True,
            "no_deletion": True,
            "requested_launcher_argv": command["launcher_argv"][4:],
            "requested_start_receipt": str(start_path),
            "requested_rc_receipt": str(rc_path),
            "launcher_invocation": {
                "process_command_line": command["launcher_argv"],
                "working_directory": str(audit.WORKSPACE_ROOT),
                "environment": copy.deepcopy(launcher.FROZEN_ENVIRONMENT),
                "sys_executable": "/usr/bin/python3.8",
                "proc_executable": audit._file_identity(Path("/usr/bin/python3.8")),
                "launcher_source": freeze["launcher_receipt_contract"]["launcher_identity"],
            },
            "receipt_created_unix_time_ns": 10_000 + offset,
        }
        start_path.write_bytes(audit._canonical_bytes(start))
        start_path.chmod(0o444)
        contract = audit._load_canonical_object(
            Path(command["command_contract"]["path"]), label="test command"
        )
        rc = {
            "schema_version": launcher.RC_RECEIPT_SCHEMA,
            "status": "PROCESS_ENDED",
            "arm_id": arm_id,
            "start_receipt": audit._file_identity(start_path),
            "command_contract": command["command_contract"],
            "actual_execution": {
                "argv": contract["argv"],
                "environment": contract["environment"],
                "working_directory": contract["working_directory"],
                "shell": False,
            },
            "producer_process": {
                "pid": 2000 + offset,
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
            },
            "pycache_contract": {
                "prefix": str(launcher.PYCACHE_PREFIX),
                "absent_pre": True,
                "absent_post": True,
                "deleted_by_launcher": False,
            },
            "timing": {
                "child_launch_unix_time_ns": 20_000 + offset,
                "child_end_unix_time_ns": 30_000 + offset,
            },
            "launcher": {
                "parent_pid": 1000 + offset,
                "source": freeze["launcher_receipt_contract"]["launcher_identity"],
                "no_retry": True,
                "no_deletion": True,
            },
        }
        rc_path.write_bytes(audit._canonical_bytes(rc))
        rc_path.chmod(0o444)
    return gate


def _attempt(arm_id: str, paths: dict[str, str], inputs: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "aqua-fe-detector-birth-rawlk-attempt-v1",
        "status": "ATTEMPT_CONSUMED_PROCESS_ENTERED_PRECHECK",
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "arm_id": arm_id,
        "prefix_nonformal": False,
        "requested_inputs": {
            key: value["path"] for key, value in inputs.items()
        },
        "reserved_outputs": {
            key: paths[key]
            for key in (
                "feature_bag",
                "manifest_json",
                "diagnostics_csv",
                "legacy_primitive_manifest",
                "private_work_directory",
            )
        },
        "producer": {
            "matched_core_requested": str(Path(core.__file__).resolve()),
            "wrapper_requested": str(audit.EXPECTED_WRAPPERS[arm_id].resolve()),
        },
    }


def _set_pointer(value: object, pointer: str, replacement: object) -> None:
    tokens = pointer.split("/")[1:]
    current = value
    for raw in tokens[:-1]:
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if type(current) is list else current[token]
    leaf = tokens[-1].replace("~1", "/").replace("~0", "~")
    if type(current) is list:
        current[int(leaf)] = copy.deepcopy(replacement)
    else:
        current[leaf] = copy.deepcopy(replacement)


def _materialize_template(template: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(template)
    for pointer in audit._template_dynamic_paths(template):
        rule = audit._dynamic_rule(audit._pointer_value(template, pointer), pointer=pointer)
        if "types" in rule and "null" in rule["types"]:
            value = None
        elif rule.get("type") == "string":
            value = "0" * 64
        elif rule.get("type") == "bool":
            value = False
        elif rule.get("type") == "float":
            value = float(rule.get("minimum", 0.0))
        else:
            value = int(rule.get("minimum", 0))
        _set_pointer(result, pointer, value)
    return result


def _synthetic_freeze(root: Path) -> tuple[dict[str, object], dict[str, dict[str, Path]], dict[str, Path]]:
    source, raw, camera = root / "source.bag", root / "raw.bag", root / "camera.yaml"
    source.write_bytes(b"source")
    raw.write_bytes(b"raw")
    camera.write_bytes(b"camera")
    locked = {
        "source_feature_bag": audit._file_identity(source),
        "raw_image_bag": audit._file_identity(raw),
        "camera_yaml": audit._file_identity(camera),
    }
    frozen_core_runtime = {"pycache_prefix": str(launcher.PYCACHE_PREFIX)}
    frozen_runtime = {
        "core_runtime": copy.deepcopy(frozen_core_runtime),
        "pycache_prefix": str(launcher.PYCACHE_PREFIX),
    }
    common = {
        "runtime": copy.deepcopy(frozen_core_runtime),
        "carrier": {"lk_win_size": [21, 21]},
    }
    arms: dict[str, object] = {}
    arm_paths: dict[str, dict[str, Path]] = {}
    command_contract_paths: dict[str, Path] = {}
    launcher_starts: dict[str, Path] = {}
    launcher_rcs: dict[str, Path] = {}
    for label, arm_id in (("xfeat", audit.XFEAT_ARM), ("gftt", audit.GFTT_ARM)):
        paths = {
            "feature_bag": root / f"{label}.bag",
            "manifest_json": root / f"{label}.manifest.json",
            "diagnostics_csv": root / f"{label}.csv",
            "legacy_primitive_manifest": root / f"{label}.legacy.json",
            "private_work_directory": root / f"{label}.work",
            "attempt_json": root / f"{label}.attempt.json",
        }
        arm_paths[arm_id] = paths
        template = _full_manifest(arm_id)
        template["common_contract"] = copy.deepcopy(common)
        template["common_contract_sha256"] = core._canonical_sha256(common)
        template["arm_contract"] = copy.deepcopy(audit.EXPECTED_ARM_CONTRACTS[arm_id])
        template["arm_contract_sha256"] = core._canonical_sha256(template["arm_contract"])
        path_strings = {key: str(path.resolve(strict=False)) for key, path in paths.items()}
        attempt = _attempt(arm_id, path_strings, locked)
        template["attempt"] = {
            "identity": {"path": path_strings["attempt_json"], "size_bytes": 1, "sha256": "a" * 64},
            "payload": copy.deepcopy(attempt),
        }
        template["outputs"] = {
            "feature_bag": {"path": path_strings["feature_bag"], "size_bytes": 1, "sha256": ("1" if label == "xfeat" else "2") * 64},
            "raw_diagnostics_csv": {"path": path_strings["diagnostics_csv"], "size_bytes": 1, "sha256": ("3" if label == "xfeat" else "4") * 64},
            "legacy_primitive_manifest": {"path": path_strings["legacy_primitive_manifest"], "size_bytes": 1, "sha256": ("5" if label == "xfeat" else "6") * 64},
        }
        template["legacy_prepublication_rebind"] = {
            "primitive_reported_work_bag_path": str(
                Path(path_strings["private_work_directory"]) / "primitive_features.bag"
            ),
            "primitive_reported_output_identity_after_path_rebind": copy.deepcopy(
                template["outputs"]["feature_bag"]
            ),
            "published_feature_bag_identity": copy.deepcopy(
                template["outputs"]["feature_bag"]
            ),
            "reason": (
                "frozen_primitive_writes_inside_private_work_directory; "
                "matched_transaction_publishes_the_identical_held_inode"
            ),
        }
        template["prefix"] = {
            "requested_max_published_frames": None,
            "source_total_published_frames": 900,
            "selected_published_frames": 900,
            "cutoff_feature_record_stamp_ns": None,
        }
        template["inputs"] = {
            **copy.deepcopy(locked),
            "camera_normalization_model": "pinhole",
            "feature_topic": "/feature_tracker/feature",
            "image_topic": "/camera/image_raw",
        }
        template["pair_difference_policy"] = {
            "no_wildcard_allowlist": True,
            "freeze_must_pin_every_detector_specific_leaf": True,
            "only_semantic_categories": [
                "detector_adapter_identity_and_frozen_parameters",
                "truthful_backend_inert_detector_provenance",
                "detector_candidates_births_survival_ids_and_trajectory_outcomes",
                "detector_runtime_and_output_artifact_identity",
            ],
            "posthoc_candidate_or_observation_dose_matching_forbidden": True,
        }
        template["raw_frame_diagnostics"] = _diagnostic_rows()
        template["metrics"] = {
            "raw_frames_processed": 1800,
            "published_frames": 900,
            "adaptive_clahe_frames": 600,
            **{name: 0.0 if name == "observations_per_frame_median" else 0 for name in audit.METRIC_DYNAMIC_LEAVES},
        }
        template["diagnostics_streams"] = {
            "row_count": 1800,
            "raw_schedule_sha256": core._diagnostics_schedule_stream(template["raw_frame_diagnostics"]),
            "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(template["raw_frame_diagnostics"]),
            "common_row_fields": list(audit.COMMON_DIAGNOSTIC_FIELDS),
        }
        template["nonfeature_stream_before"] = {"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}}
        template["nonfeature_stream_after"] = copy.deepcopy(template["nonfeature_stream_before"])
        template["runtime"] = {
            "elapsed_wall_ms": 0.0,
            "common_runtime": {},
            "post_factory_runtime": {},
            "post_carrier_runtime": {},
            "post_metadata_runtime": {},
        }
        # These tests target freeze mechanics; live detector metadata is
        # supplied by the code-authoritative projection mock below.
        template["code_artifacts"] = {
            "matched_core": audit._file_identity(Path(core.__file__)),
            "frozen_primitive_module": audit._file_identity(Path(core.primitive.__file__)),
            "wrapper": audit._file_identity(audit.EXPECTED_WRAPPERS[arm_id]),
            "detector_dependencies": (
                {
                    str(label): audit._file_identity(Path(path))
                    for label, path in (
                        audit.matched_xfeat.XFEAT_METHOD_SPEC.detector_code_artifacts
                    )
                }
                if arm_id == audit.XFEAT_ARM
                else {}
            ),
            "detector_runtime": {"runtime": {"detect_calls": 0, "candidate_total": 0}},
        }
        mandatory_rules = audit._mandatory_dynamic_rules(arm_id)
        if arm_id == audit.XFEAT_ARM:
            template["code_artifacts"]["detector_runtime"]["runtime"]["detect_ms"] = {
                group: {leaf: 0 for leaf in ("count", "median_ms", "p90_ms", "total_ms")}
                for group in ("warmup", "steady_state", "all")
            }
        for pointer, marker in mandatory_rules.items():
            _set_pointer(template, pointer, marker)
        dynamic_paths = sorted(audit._template_dynamic_paths(template))
        arms[arm_id] = {
            "paths": path_strings,
            "pre_run_required_absent": True,
            "manifest_template": template,
            "manifest_template_sha256": core._canonical_sha256(template),
            "dynamic_scalar_paths": dynamic_paths,
            "attempt": attempt,
        }
        command_contract_paths[arm_id] = root / f"{label}.command.json"
        launcher_starts[arm_id] = root / f"{label}.launch-start.json"
        launcher_rcs[arm_id] = root / f"{label}.launch-rc.json"
    allowed = sorted(
        set(audit._pair_scalar_differences(
            arms[audit.XFEAT_ARM]["manifest_template"],
            arms[audit.GFTT_ARM]["manifest_template"],
        ))
        | set(arms[audit.XFEAT_ARM]["dynamic_scalar_paths"])
        | set(arms[audit.GFTT_ARM]["dynamic_scalar_paths"])
    )
    audit_paths = {
        "pre_run_start_receipt": root / "start.json",
        "post_run_pair_seal": root / "seal.json",
    }
    freeze = {
        "schema_version": audit.FREEZE_SCHEMA_VERSION,
        "status": "FROZEN",
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "auditor_identity": audit._audit_code_closure()["pair_auditor"],
        "audit_code_closure": audit._audit_code_closure(),
        "audit_runtime": copy.deepcopy(frozen_runtime),
        "fixed_semantics": audit._fixed_semantics(
            feature_topic="/feature_tracker/feature",
            image_topic="/camera/image_raw",
            allow_prefix=False,
            expected_frames=900,
        ),
        "locked_inputs": locked,
        "audit_paths": {key: str(value.resolve(strict=False)) for key, value in audit_paths.items()},
        "expected_common_contract": common,
        "expected_common_contract_sha256": core._canonical_sha256(common),
        "arms": arms,
        "allowed_pair_scalar_differences": allowed,
        "required_pair_scalar_differences": sorted(audit.MANDATORY_PAIR_DIFFERENCES),
        "freeze_builder_identity": audit._file_identity(Path(freeze_builder.__file__)),
        "authoritative_commands": {},
        "launcher_receipt_contract": {
            "command_contract_schema": launcher.COMMAND_CONTRACT_SCHEMA,
            "start_receipt_schema": launcher.START_RECEIPT_SCHEMA,
            "rc_receipt_schema": launcher.RC_RECEIPT_SCHEMA,
            "launcher_identity": audit._file_identity(Path(launcher.__file__)),
            "supervision": copy.deepcopy(launcher.EXPECTED_SUPERVISION),
        },
        "publication_contract": {
            "commit_marker_role": "freeze",
            "freeze_published_last": True,
            "orphan_contracts_non_authoritative": True,
            "result_outcomes_read": False,
            "producer_started": False,
        },
        "infrastructure_incident": {
            "path": str(audit.INFRASTRUCTURE_INCIDENT_PATH),
            "size_bytes": audit.INFRASTRUCTURE_INCIDENT_SIZE,
            "sha256": audit.INFRASTRUCTURE_INCIDENT_SHA256,
        },
        "artifact_filesystem_contract": {
            "schema_version": audit.ARTIFACT_FILESYSTEM_ENVELOPE_SCHEMA,
            "static_contract": {
                "namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
            },
            "builder_prepublication_capability_probe": (
                audit._expected_artifact_capability_attestation()
            ),
        },
    }
    freeze_path = root / "freeze.json"
    arm_commands = {}
    for arm_id in audit.EXPECTED_ARMS:
        p = arms[arm_id]["paths"]
        values = {
            "--source-feature-bag": locked["source_feature_bag"]["path"],
            "--raw-image-bag": locked["raw_image_bag"]["path"],
            "--camera-yaml": locked["camera_yaml"]["path"],
            "--output-bag": p["feature_bag"],
            "--image-topic": "/camera/image_raw",
            "--feature-topic": "/feature_tracker/feature",
            "--manifest-json": p["manifest_json"],
            "--diagnostics-csv": p["diagnostics_csv"],
            "--legacy-manifest-json": p["legacy_primitive_manifest"],
            "--work-directory": p["private_work_directory"],
            "--attempt-json": p["attempt_json"],
        }
        contract = launcher.build_command_contract(
            arm_id, values,
            start_receipt=launcher_starts[arm_id],
            rc_receipt=launcher_rcs[arm_id],
        )
        command_contract_paths[arm_id].write_bytes(audit._canonical_bytes(contract))
        arm_commands[arm_id] = {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": copy.deepcopy(launcher.FROZEN_ENVIRONMENT),
            "command_contract": audit._file_identity(command_contract_paths[arm_id]),
            "launcher_argv": [
                "/usr/bin/python3.8", "-B", "-m", "scripts.run_matched_birth_arm_once_v1",
                "--start-receipt", str(launcher_starts[arm_id]),
                "--rc-receipt", str(launcher_rcs[arm_id]),
                "--command-contract-json", str(command_contract_paths[arm_id]),
            ],
            "launcher_start_receipt": str(launcher_starts[arm_id]),
            "launcher_rc_receipt": str(launcher_rcs[arm_id]),
        }
    common_command = {
        "working_directory": str(audit.WORKSPACE_ROOT),
        "environment": copy.deepcopy(launcher.FROZEN_ENVIRONMENT),
    }
    freeze["authoritative_commands"] = {
        "check_start": {
            **common_command,
            "argv": audit._auditor_argv(
                action="check-start", freeze_json=freeze_path,
                source_bag=source, raw_bag=raw, camera_yaml=camera,
                arm_paths=arm_paths, audit_paths=audit_paths,
                feature_topic="/feature_tracker/feature", image_topic="/camera/image_raw",
                allow_prefix=False, expected_frames=900,
            ),
        },
        "arms": arm_commands,
        "post_run_audit": {
            **common_command,
            "argv": audit._auditor_argv(
                action="audit", freeze_json=freeze_path,
                source_bag=source, raw_bag=raw, camera_yaml=camera,
                arm_paths=arm_paths, audit_paths=audit_paths,
                feature_topic="/feature_tracker/feature", image_topic="/camera/image_raw",
                allow_prefix=False, expected_frames=900,
            ),
        },
    }
    return freeze, arm_paths, {"source": source, "raw": raw, "camera": camera, "freeze": freeze_path, **audit_paths}


def _synthetic_continuation(freeze: dict[str, object]) -> dict[str, object]:
    contracts = {
        arm_id: audit._load_canonical_object(
            Path(
                freeze["authoritative_commands"]["arms"][arm_id][
                    "command_contract"
                ]["path"]
            ),
            label=f"synthetic {arm_id} command contract",
        )
        for arm_id in audit.EXPECTED_ARMS
    }
    return audit._continuation_scientific_projection(
        freeze, command_contracts=contracts
    )


def _infrastructure_patches(freeze: dict[str, object]):
    namespace_root = freeze["artifact_filesystem_contract"]["static_contract"][
        "namespace_root"
    ]
    continuation = _synthetic_continuation(freeze)
    return (
        mock.patch.object(
            audit,
            "_validate_infrastructure_incident",
            return_value={
                "identity": copy.deepcopy(freeze["infrastructure_incident"]),
                "authorized_namespace_root": namespace_root,
                "continuation_contract": continuation,
            },
        ),
        mock.patch.object(
            audit,
            "_artifact_filesystem_envelope",
            return_value=copy.deepcopy(freeze["artifact_filesystem_contract"]),
        ),
    )


def _retired_r2_continuation_candidate():
    root = audit.TERMINATED_R2_ROOT
    freeze = audit._load_canonical_object(
        root / "probe16_freeze.json", label="test retired r2 freeze"
    )
    candidate = audit._remap_retired_r2_science_paths(freeze)
    contracts = {
        audit.XFEAT_ARM: audit._load_canonical_object(
            root / "xfeat_r2/command_contract.json", label="test r2 XFeat command"
        ),
        audit.GFTT_ARM: audit._load_canonical_object(
            root / "gftt_r2/command_contract.json", label="test r2 GFTT command"
        ),
    }
    contracts = audit._remap_retired_r2_science_paths(contracts)
    for arm_id in audit.EXPECTED_ARMS:
        template = candidate["arms"][arm_id]["manifest_template"]
        candidate["arms"][arm_id]["manifest_template_sha256"] = (
            core._canonical_sha256(template)
        )
    return candidate, contracts


def _diagnostic_manifest(rows: list[dict[str, object]], arm_id: str = audit.GFTT_ARM) -> dict[str, object]:
    calls = sum(bool(row["detector_called"]) for row in rows)
    candidates = sum(int(row["detector_candidates"]) for row in rows)
    runtime = {
        "opencv_version": core.EXPECTED_OPENCV_VERSION,
        "numpy_version": core.EXPECTED_NUMPY_VERSION,
        "detect_calls": calls,
        "candidate_total": candidates,
        "input_shapes": [[8, 8]],
        "input_shapes_hw": [[8, 8]],
    }
    detector = (
        audit.matched_gftt.GFTTBirthDetector().artifact_metadata()
        if arm_id == audit.GFTT_ARM
        else {"runtime": runtime}
    )
    detector["runtime"] = runtime
    return {
        "raw_frame_diagnostics": rows,
        "diagnostics_streams": {
            "row_count": len(rows),
            "raw_schedule_sha256": core._diagnostics_schedule_stream(rows),
            "raw_and_processed_pixels_sha256": core._diagnostics_common_stream(rows),
            "common_row_fields": list(audit.COMMON_DIAGNOSTIC_FIELDS),
        },
        "metrics": {
            "raw_frames_processed": len(rows),
            "published_frames": sum(bool(row["published"]) for row in rows),
            "raw_births": sum(int(row["births"]) for row in rows),
            "raw_drops": 0,
            "adaptive_clahe_frames": sum(bool(row["adaptive_clahe_applied"]) for row in rows),
            "detector_candidates": candidates,
        },
        "code_artifacts": {"detector_runtime": detector},
    }


def _frame(index: int, stamp: int, ids: list[int], normalized: list[list[float]], velocities: list[list[float]], *, source: int = 20, learned: int = 1) -> audit_base.FeatureFrame:
    count = len(ids)
    normalized_array = np.asarray(normalized, dtype=np.float64).reshape(count, 2)
    channels = {
        name: np.zeros(count, dtype=np.float64) for name in core.primitive.CHANNEL_NAMES
    }
    channels["id"] = np.asarray(ids, dtype=np.float64)
    channels["p_u"] = normalized_array[:, 0].copy()
    channels["p_v"] = normalized_array[:, 1].copy()
    channels["quality"][:] = 1.0
    channels["sigma"][:] = 1.0
    channels["source_code"][:] = float(source)
    channels["is_learned"][:] = float(learned)
    channels["velocity_x"] = np.asarray(velocities, dtype=np.float64).reshape(count, 2)[:, 0]
    channels["velocity_y"] = np.asarray(velocities, dtype=np.float64).reshape(count, 2)[:, 1]
    return audit_base.FeatureFrame(
        index=index,
        record_stamp_ns=stamp,
        header_stamp_ns=stamp,
        header_seq=index,
        header_frame_id="camera",
        schema=tuple(core.primitive.CHANNEL_NAMES),
        channels=channels,
        ids=np.asarray(ids, dtype=np.int64),
        pixels=normalized_array.copy(),
        normalized=normalized_array.copy(),
        point_z=np.ones(count, dtype=np.float64),
        velocities=np.asarray(velocities, dtype=np.float64).reshape(count, 2),
    )


def _gftt_manifest_fixture(root: Path) -> tuple[dict[str, object], dict[str, object], dict[str, str], dict[str, object]]:
    """Construct a complete producer-shaped GFTT manifest using live code identities."""

    source, raw, camera = root / "source.bag", root / "raw.bag", root / "camera.yaml"
    source.write_bytes(b"source")
    raw.write_bytes(b"raw")
    camera.write_bytes(b"camera")
    locked = {
        "source_feature_bag": audit._file_identity(source),
        "raw_image_bag": audit._file_identity(raw),
        "camera_yaml": audit._file_identity(camera),
    }
    paths = {
        "feature_bag": str((root / "gftt.bag").resolve()),
        "manifest_json": str((root / "gftt.manifest.json").resolve()),
        "diagnostics_csv": str((root / "gftt.csv").resolve()),
        "legacy_primitive_manifest": str((root / "gftt.legacy.json").resolve()),
        "private_work_directory": str((root / "gftt.work").resolve()),
        "attempt_json": str((root / "gftt.attempt.json").resolve()),
    }
    Path(paths["feature_bag"]).write_bytes(b"bag")
    Path(paths["diagnostics_csv"]).write_bytes(b"diagnostics")
    Path(paths["legacy_primitive_manifest"]).write_bytes(b"legacy-placeholder")
    Path(paths["private_work_directory"]).mkdir(mode=0o700)
    attempt = _attempt(audit.GFTT_ARM, paths, locked)
    Path(paths["attempt_json"]).write_bytes(audit._canonical_bytes(attempt))
    Path(paths["attempt_json"]).chmod(0o444)
    implementation = {
        "quality_reference_source": audit._file_identity(core.primitive.QUALITY_REFERENCE_SOURCE),
        "klt_reference_source": audit._file_identity(core.primitive.KLT_REFERENCE_SOURCE),
    }
    common = {"runtime": {}, "implementation": implementation}
    stream = {"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}}
    detector_metadata = audit.matched_gftt.GFTTBirthDetector().artifact_metadata()
    manifest = {
        "schema_version": core.SCHEMA_VERSION,
        "status": "FULL",
        "formal_eligible": True,
        "formal_eligibility_reason": "full_export_from_frozen_matched_cli_factory",
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "prefix": {
            "requested_max_published_frames": None,
            "source_total_published_frames": 900,
            "selected_published_frames": 900,
            "cutoff_feature_record_stamp_ns": None,
        },
        "attempt": {
            "identity": audit._file_identity(Path(paths["attempt_json"])),
            "payload": copy.deepcopy(attempt),
        },
        "inputs": {
            **copy.deepcopy(locked),
            "camera_normalization_model": {"model": "synthetic"},
            "feature_topic": "/feature_tracker/feature",
            "image_topic": "/camera/image_raw",
        },
        "common_contract": common,
        "common_contract_sha256": core._canonical_sha256(common),
        "arm_contract": copy.deepcopy(audit.EXPECTED_ARM_CONTRACTS[audit.GFTT_ARM]),
        "arm_contract_sha256": core._canonical_sha256(audit.EXPECTED_ARM_CONTRACTS[audit.GFTT_ARM]),
        "pair_difference_policy": {"no_wildcard_allowlist": True},
        "code_artifacts": {
            "matched_core": audit._file_identity(Path(core.__file__)),
            "frozen_primitive_module": audit._file_identity(Path(core.primitive.__file__)),
            "wrapper": audit._file_identity(audit.EXPECTED_WRAPPERS[audit.GFTT_ARM]),
            "detector_dependencies": {},
            "detector_runtime": detector_metadata,
        },
        "outputs": {
            "feature_bag": audit._file_identity(Path(paths["feature_bag"])),
            "raw_diagnostics_csv": audit._file_identity(Path(paths["diagnostics_csv"])),
            "legacy_primitive_manifest": audit._file_identity(Path(paths["legacy_primitive_manifest"])),
        },
        "legacy_prepublication_rebind": {
            "primitive_reported_work_bag_path": str(
                Path(paths["private_work_directory"]) / "primitive_features.bag"
            ),
            "primitive_reported_output_identity_after_path_rebind": audit._file_identity(
                Path(paths["feature_bag"])
            ),
            "published_feature_bag_identity": audit._file_identity(
                Path(paths["feature_bag"])
            ),
            "reason": (
                "frozen_primitive_writes_inside_private_work_directory; "
                "matched_transaction_publishes_the_identical_held_inode"
            ),
        },
        "nonfeature_stream_before": copy.deepcopy(stream),
        "nonfeature_stream_after": copy.deepcopy(stream),
        "metrics": {
            "raw_frames_processed": 1800,
            "published_frames": 900,
            "observations": 0,
            "observations_per_frame_min": 0,
            "observations_per_frame_median": 0.0,
            "observations_per_frame_max": 0,
            "unique_ids": 0,
            "published_first_occurrences": 0,
            "published_continuations": 0,
            "raw_births": 0,
            "raw_drops": 0,
            "adaptive_clahe_frames": 0,
            "detector_candidates": 0,
        },
        "diagnostics_streams": {
            "row_count": 1800,
            "raw_schedule_sha256": "1" * 64,
            "raw_and_processed_pixels_sha256": "2" * 64,
            "common_row_fields": list(audit.COMMON_DIAGNOSTIC_FIELDS),
        },
        "raw_frame_diagnostics": [],
        "runtime": {
            "elapsed_wall_ms": 1.0,
            "common_runtime": {},
            "post_factory_runtime": {},
            "post_carrier_runtime": {},
            "post_metadata_runtime": {},
        },
    }
    return manifest, attempt, paths, locked


class _IdentityCamera:
    def undistort_points(self, pixels):
        return np.asarray(pixels, dtype=np.float64)


class MatchedPairAuditTests(unittest.TestCase):
    def test_live_infrastructure_incident_and_terminated_tree_are_exact(self) -> None:
        gate = audit._validate_infrastructure_incident()
        self.assertEqual(
            gate["identity"]["sha256"], audit.INFRASTRUCTURE_INCIDENT_SHA256
        )
        self.assertEqual(
            gate["prior_incident"]["sha256"],
            audit.R1_INFRASTRUCTURE_INCIDENT_SHA256,
        )
        self.assertNotIn("payload", gate)
        self.assertNotIn("retired_r2_inventory", gate)
        self.assertEqual(
            gate["authorized_namespace_root"], str(audit.ARTIFACT_NAMESPACE_ROOT)
        )
        self.assertEqual(
            gate["governance_evidence"],
            {
                "retired_r2_evidence_read_for_governance": True,
                "retired_r2_outcomes_used_for_scientific_projection": False,
                "candidate_r3_outcomes_read": False,
                "historical_builder_identity_scope": (
                    "recorded_in_held_r2_freeze_not_live_byte_revalidated"
                ),
            },
        )
        pyc_bytes = audit.HISTORICAL_AUDITOR_PYC_PATH.read_bytes()
        branch = audit._historical_auditor_branch_contract(pyc_bytes)
        self.assertTrue(branch["allow_prefix_parameter_absent"])
        self.assertTrue(branch["explicit_prefix_reason_constant_absent"])
        with mock.patch.object(
            audit.os,
            "listdir",
            return_value=["xfeat_r1", "gftt_r1", "foreign"],
        ), self.assertRaisesRegex(audit.AuditFailure, "root directory tree drift"):
            audit._validate_infrastructure_incident()

    def test_retired_r2_probe16_continuation_projection_is_exact_and_outcome_blind(self) -> None:
        gate = audit._validate_infrastructure_incident()
        candidate, contracts = _retired_r2_continuation_candidate()
        observed = audit._validate_continuation_scientific_projection(
            candidate,
            incident_gate=gate,
            allow_prefix=True,
            expected_frames=16,
            candidate_command_contracts=contracts,
        )
        self.assertEqual(
            observed,
            audit._remap_retired_r2_science_paths(gate["continuation_contract"]),
        )
        encoded = audit._canonical_bytes(gate["continuation_contract"])
        incident = json.loads(audit.INFRASTRUCTURE_INCIDENT_PATH.read_bytes())
        self.assertNotIn(b'"execution"', encoded)
        for arm in incident["execution"]["arms"].values():
            self.assertNotIn(arm["outputs"]["feature_bag"]["sha256"].encode(), encoded)

    def test_retired_r2_continuation_rejects_formal_mode_and_input_drift(self) -> None:
        gate = audit._validate_infrastructure_incident()
        candidate, contracts = _retired_r2_continuation_candidate()
        with self.assertRaisesRegex(audit.AuditFailure, "continuation probe mode"):
            audit._validate_continuation_scientific_projection(
                candidate,
                incident_gate=gate,
                allow_prefix=False,
                expected_frames=900,
                candidate_command_contracts=contracts,
            )
        drifted = copy.deepcopy(candidate)
        drifted["locked_inputs"]["raw_image_bag"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(audit.AuditFailure, "continuation locked inputs"):
            audit._validate_continuation_scientific_projection(
                drifted,
                incident_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                candidate_command_contracts=contracts,
            )

    def test_retired_r2_continuation_rejects_self_consistent_science_drift(self) -> None:
        gate = audit._validate_infrastructure_incident()
        candidate, contracts = _retired_r2_continuation_candidate()
        changed_common = copy.deepcopy(candidate["expected_common_contract"])
        changed_common["carrier"]["lk_win_size"] = [19, 19]
        changed_sha = core._canonical_sha256(changed_common)
        candidate["expected_common_contract"] = changed_common
        candidate["expected_common_contract_sha256"] = changed_sha
        for arm_id in audit.EXPECTED_ARMS:
            template = candidate["arms"][arm_id]["manifest_template"]
            template["common_contract"] = copy.deepcopy(changed_common)
            template["common_contract_sha256"] = changed_sha
            candidate["arms"][arm_id]["manifest_template_sha256"] = (
                core._canonical_sha256(template)
            )
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate,
                incident_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                candidate_command_contracts=contracts,
            )

        candidate, contracts = _retired_r2_continuation_candidate()
        template = candidate["arms"][audit.XFEAT_ARM]["manifest_template"]
        template["arm_contract"]["detector"]["contract"]["detection_threshold"] = 0.06
        template["arm_contract_sha256"] = core._canonical_sha256(
            template["arm_contract"]
        )
        candidate["arms"][audit.XFEAT_ARM]["manifest_template_sha256"] = (
            core._canonical_sha256(template)
        )
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate,
                incident_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                candidate_command_contracts=contracts,
            )

    def test_retired_r2_continuation_rejects_prefix_and_command_drift(self) -> None:
        gate = audit._validate_infrastructure_incident()
        candidate, contracts = _retired_r2_continuation_candidate()
        template = candidate["arms"][audit.GFTT_ARM]["manifest_template"]
        template["prefix"]["cutoff_feature_record_stamp_ns"] += 1
        candidate["arms"][audit.GFTT_ARM]["manifest_template_sha256"] = (
            core._canonical_sha256(template)
        )
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate,
                incident_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                candidate_command_contracts=contracts,
            )

        candidate, contracts = _retired_r2_continuation_candidate()
        argv = contracts[audit.XFEAT_ARM]["argv"]
        limit = argv.index("--max-published-frames")
        argv[limit + 1] = "17"
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate,
                incident_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                candidate_command_contracts=contracts,
            )

    def test_retired_r2_continuation_rejects_fixed_attempt_env_and_cwd_drift(self) -> None:
        gate = audit._validate_infrastructure_incident()

        candidate, contracts = _retired_r2_continuation_candidate()
        candidate["fixed_semantics"]["diagnostic_fields"] = list(
            reversed(candidate["fixed_semantics"]["diagnostic_fields"])
        )
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate, incident_gate=gate, allow_prefix=True,
                expected_frames=16, candidate_command_contracts=contracts,
            )

        candidate, contracts = _retired_r2_continuation_candidate()
        candidate["arms"][audit.GFTT_ARM]["attempt"]["status"] = "DRIFT"
        with self.assertRaisesRegex(
            audit.AuditFailure, "continuation scientific configuration"
        ):
            audit._validate_continuation_scientific_projection(
                candidate, incident_gate=gate, allow_prefix=True,
                expected_frames=16, candidate_command_contracts=contracts,
            )

        for leaf, value in (
            ("environment", {"DRIFT": "1"}),
            ("working_directory", "/tmp"),
        ):
            with self.subTest(command_leaf=leaf):
                candidate, contracts = _retired_r2_continuation_candidate()
                contracts[audit.XFEAT_ARM][leaf] = value
                with self.assertRaisesRegex(
                    audit.AuditFailure, "continuation scientific configuration"
                ):
                    audit._validate_continuation_scientific_projection(
                        candidate, incident_gate=gate, allow_prefix=True,
                        expected_frames=16, candidate_command_contracts=contracts,
                    )

    def test_infrastructure_incident_mode_must_remain_0444(self) -> None:
        real_lstat = audit.os.lstat

        def wrong_incident_mode(path):
            observed = real_lstat(path)
            if Path(path) == audit.INFRASTRUCTURE_INCIDENT_PATH:
                values = list(observed)
                values[0] = stat.S_IFREG | 0o644
                return os.stat_result(values)
            return observed

        with mock.patch.object(
            audit.os, "lstat", side_effect=wrong_incident_mode
        ), self.assertRaisesRegex(audit.AuditFailure, "mode-0444"):
            audit._validate_infrastructure_incident()

    def test_retired_r2_tree_identity_drift_is_rejected(self) -> None:
        incident = json.loads(audit.INFRASTRUCTURE_INCIDENT_PATH.read_bytes())
        drifted = copy.deepcopy(
            incident["terminated_namespace"]["tree_inventory"]
        )
        feature_row = next(
            row for row in drifted if row["path"].endswith("/xfeat_r2/features.bag")
        )
        feature_row["sha256"] = "0" * 64
        with self.assertRaisesRegex(audit.AuditFailure, "held tree inventory"):
            audit._retired_r2_held_snapshot(drifted)

    def test_retired_r2_root_relist_drift_is_rejected(self) -> None:
        incident = json.loads(audit.INFRASTRUCTURE_INCIDENT_PATH.read_bytes())
        inventory = incident["terminated_namespace"]["tree_inventory"]
        real_listdir = audit.os.listdir
        first = True

        def injected(descriptor):
            nonlocal first
            observed = real_listdir(descriptor)
            if first:
                first = False
                return [*observed, "foreign"]
            return observed

        with mock.patch.object(
            audit.os, "listdir", side_effect=injected
        ), self.assertRaisesRegex(audit.AuditFailure, "root listing drift"):
            audit._retired_r2_held_snapshot(inventory)

    def test_retired_r2_final_mode_drift_is_rejected(self) -> None:
        incident = json.loads(audit.INFRASTRUCTURE_INCIDENT_PATH.read_bytes())
        snapshot = audit._retired_r2_held_snapshot(
            incident["terminated_namespace"]["tree_inventory"]
        )
        target = snapshot["file_descriptors"][
            audit.TERMINATED_R2_ROOT / "probe16_freeze.json"
        ]
        real_fstat = audit.os.fstat

        def changed_mode(descriptor):
            observed = real_fstat(descriptor)
            if descriptor == target:
                class ModeDrift:
                    st_mode = stat.S_IFREG | 0o644

                    def __getattr__(self, name):
                        return getattr(observed, name)

                return ModeDrift()
            return observed

        try:
            with mock.patch.object(
                audit.os, "fstat", side_effect=changed_mode
            ), self.assertRaisesRegex(audit.AuditFailure, "final held stat/bytes"):
                audit._finish_retired_r2_held_snapshot(snapshot)
        finally:
            audit._close_retired_r2_held_snapshot(snapshot)

    def test_retired_r2_historical_launcher_chain_is_revalidated(self) -> None:
        real = audit._validate_launcher_receipts
        calls = []

        def recorded(gate, **kwargs):
            self.assertIsNotNone(audit._ACTIVE_RETIRED_R2_SNAPSHOT)
            for descriptor in audit._ACTIVE_RETIRED_R2_SNAPSHOT[
                "file_descriptors"
            ].values():
                os.fstat(descriptor)
            calls.append(copy.deepcopy(gate["governance"]["commands"]["arms"]))
            return real(gate, **kwargs)

        with mock.patch.object(
            audit, "_validate_launcher_receipts", side_effect=recorded
        ):
            audit._validate_infrastructure_incident()
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]), {audit.XFEAT_ARM, audit.GFTT_ARM})

    def test_retired_r2_semantics_never_reopen_historical_paths(self) -> None:
        real_governance = audit._validate_governance_contract
        real_open = audit.os.open
        semantic_started = False

        def begin_semantics(*args, **kwargs):
            nonlocal semantic_started
            semantic_started = True
            return real_governance(*args, **kwargs)

        def guarded_open(path, *args, **kwargs):
            if semantic_started and str(path).startswith(str(audit.TERMINATED_R2_ROOT)):
                raise AssertionError(f"historical path reopened: {path}")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(
            audit, "_validate_governance_contract", side_effect=begin_semantics
        ), mock.patch.object(
            audit.os, "open", side_effect=guarded_open
        ):
            audit._validate_infrastructure_incident()

    def test_retired_r2_snapshot_json_codec_is_exact(self) -> None:
        freeze = audit.TERMINATED_R2_ROOT / "probe16_freeze.json"
        original = freeze.read_bytes()
        self.assertEqual(
            audit._decode_retired_r2_snapshot_json(
                freeze, original, label="terminated r2 freeze"
            )["status"],
            "FROZEN",
        )
        with self.assertRaisesRegex(audit.AuditFailure, "canonical JSON codec"):
            audit._decode_retired_r2_snapshot_json(
                freeze, b" " + original, label="terminated r2 freeze"
            )
        legacy = audit.TERMINATED_R2_ROOT / "xfeat_r2/legacy_primitive_manifest.json"
        pretty = legacy.read_bytes()
        self.assertEqual(
            audit._decode_retired_r2_snapshot_json(
                legacy, pretty, label="terminated r2 legacy"
            )["status"],
            "PREFIX_NONFORMAL",
        )
        with self.assertRaisesRegex(audit.AuditFailure, "canonical JSON codec"):
            audit._decode_retired_r2_snapshot_json(
                legacy,
                audit._canonical_bytes(json.loads(pretty)),
                label="terminated r2 legacy",
            )

    def test_retired_r2_launcher_chain_failure_is_not_ignored(self) -> None:
        with mock.patch.object(
            audit,
            "_validate_launcher_receipts",
            side_effect=audit.AuditFailure("synthetic historical RC/start drift"),
        ), self.assertRaisesRegex(audit.AuditFailure, "historical RC/start drift"):
            audit._validate_infrastructure_incident()
        self.assertIsNone(audit._ACTIVE_RETIRED_R2_SNAPSHOT)

    def test_historical_auditor_bytecode_identity_drift_is_rejected(self) -> None:
        real_reader = audit._read_regular_nofollow

        def corrupted(path, *, label):
            encoded, observed = real_reader(path, label=label)
            if Path(path) == audit.HISTORICAL_AUDITOR_PYC_PATH:
                encoded = encoded[:-1] + bytes([encoded[-1] ^ 1])
            return encoded, observed

        with mock.patch.object(
            audit, "_read_regular_nofollow", side_effect=corrupted
        ), self.assertRaisesRegex(audit.AuditFailure, "bytecode identity"):
            audit._validate_infrastructure_incident()

    def test_single_fd_reader_rejects_a_symlink_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_bytes(b"{}\n")
            alias = root / "alias.json"
            alias.symlink_to(target)
            with self.assertRaisesRegex(audit.AuditFailure, "canonical and symlink-free"):
                audit._read_regular_nofollow(alias, label="synthetic alias")

    def test_freeze_incident_identity_is_not_self_attested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            live_identity = copy.deepcopy(freeze["infrastructure_incident"])
            freeze["infrastructure_incident"]["sha256"] = "0" * 64
            with mock.patch.object(
                audit,
                "_validate_infrastructure_incident",
                return_value={
                    "identity": live_identity,
                    "authorized_namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
                },
            ), self.assertRaisesRegex(audit.AuditFailure, "infrastructure_incident"):
                audit._validate_freeze(
                    freeze,
                    freeze_json=paths["freeze"],
                    runtime=freeze["audit_runtime"],
                    source_bag=paths["source"],
                    raw_bag=paths["raw"],
                    camera_yaml=paths["camera"],
                    arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw",
                    allow_prefix=False,
                    expected_frames=900,
                )

    def test_freeze_filesystem_envelope_is_not_self_attested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            live_envelope = copy.deepcopy(freeze["artifact_filesystem_contract"])
            freeze["artifact_filesystem_contract"]["builder_prepublication_capability_probe"][
                "cleanup_complete"
            ] = False
            with mock.patch.object(
                audit,
                "_validate_infrastructure_incident",
                return_value={
                    "identity": copy.deepcopy(freeze["infrastructure_incident"]),
                    "authorized_namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
                    "continuation_contract": _synthetic_continuation(freeze),
                },
            ), mock.patch.object(
                audit,
                "_artifact_filesystem_envelope",
                return_value=live_envelope,
            ), mock.patch.object(
                core, "common_contract", return_value=freeze["expected_common_contract"]
            ), mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=_common_reconstruction_fixture(),
            ), mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ), mock.patch.object(
                audit, "_symbolic_manifest_expected",
                side_effect=lambda *, arm_id, **_kwargs: copy.deepcopy(
                    freeze["arms"][arm_id]["manifest_template"]
                ),
            ), mock.patch.object(
                audit, "_audit_runtime_observation",
                return_value=freeze["audit_runtime"],
            ), self.assertRaisesRegex(audit.AuditFailure, "artifact_filesystem_contract"):
                audit._validate_freeze(
                    freeze,
                    freeze_json=paths["freeze"],
                    runtime=freeze["audit_runtime"],
                    source_bag=paths["source"], raw_bag=paths["raw"],
                    camera_yaml=paths["camera"], arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw", allow_prefix=False,
                    expected_frames=900,
                )

    def test_real_locked_reconstruction_restores_strict_runtime(self) -> None:
        if dict(os.environ) != launcher.FROZEN_ENVIRONMENT:
            self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))
            result = subprocess.run(
                [
                    "/usr/bin/python3.8",
                    "-B",
                    "-m",
                    "unittest",
                    (
                        "scripts.tests.test_audit_matched_birth_rawlk_pair_v1."
                        "MatchedPairAuditTests."
                        "test_real_locked_reconstruction_restores_strict_runtime"
                    ),
                ],
                cwd=str(core.WORKSPACE_ROOT),
                env=dict(launcher.FROZEN_ENVIRONMENT),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout}\nstderr={result.stderr}",
            )
            self.assertIn("OK", result.stderr)
            self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))
            return

        source = Path(
            "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/"
            "features.bag"
        )
        raw = Path(
            "/mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/"
            "archaeo02_4500_6300.bag"
        )
        before_path = list(audit.sys.path)
        before_runtime = audit._audit_runtime_observation()
        rows, reconstruction = audit._reconstruct_common_diagnostics(
            source_bag=source,
            raw_bag=raw,
            feature_topic=audit.FEATURE_TOPIC_DEFAULT,
            image_topic="/camera/image_raw",
            allow_prefix=True,
            expected_frames=16,
        )
        self.assertEqual(len(rows), 32)
        self.assertEqual(reconstruction["source_total_published_frames"], 900)
        serialized = audit._serialized_nonfeature(
            source,
            audit.FEATURE_TOPIC_DEFAULT,
            reconstruction["cutoff_feature_record_stamp_ns"],
        )
        self.assertGreater(serialized["count"], 0)
        self.assertEqual(audit.sys.path, before_path)
        self.assertEqual(audit._audit_runtime_observation(), before_runtime)
        self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))

    def test_launcher_start_and_rc_receipts_are_exactly_cross_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, _arm_paths, _paths = _synthetic_freeze(Path(temporary))
            gate = _write_launcher_receipts(freeze)
            observed = audit._validate_launcher_receipts(gate)
            self.assertEqual(set(observed), set(audit.EXPECTED_ARMS))
            rc_path = Path(
                freeze["authoritative_commands"]["arms"][audit.XFEAT_ARM][
                    "launcher_rc_receipt"
                ]
            )
            rc = json.loads(rc_path.read_text(encoding="utf-8"))
            rc["actual_execution"]["environment"]["PYTHONHASHSEED"] = "1"
            rc_path.chmod(0o644)
            rc_path.write_bytes(audit._canonical_bytes(rc))
            rc_path.chmod(0o444)
            with self.assertRaisesRegex(audit.AuditFailure, "actual_execution"):
                audit._validate_launcher_receipts(gate)

    def test_xfeat_five_frozen_lexical_aliases_resolve_to_pinned_bytes(self) -> None:
        self.assertEqual(len(audit.XFEAT_LEXICAL_IDENTITY_ALIASES), 5)
        for label, (lexical, canonical) in audit.XFEAT_LEXICAL_IDENTITY_ALIASES.items():
            claim = {
                "path": str(lexical),
                "size_bytes": canonical.stat().st_size,
                "sha256": audit._sha256_file(canonical),
            }
            self.assertEqual(audit._validate_identity_claim(claim, label=label), claim)
            with self.assertRaisesRegex(audit.AuditFailure, "frozen lexical"):
                audit._validate_identity_claim(
                    dict(claim, path=str(canonical)), label=label
                )
            with self.assertRaisesRegex(audit.AuditFailure, "bytes mismatch"):
                audit._validate_identity_claim(
                    dict(claim, sha256="0" * 64), label=label
                )

    def test_complete_synthetic_freeze_passes_and_all_mandatory_paths_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            infra = _infrastructure_patches(freeze)
            self.assertTrue(
                all(
                    audit._pair_difference_path_allowed(pointer)
                    for pointer in audit.MANDATORY_PAIR_DIFFERENCES
                )
            )
            with mock.patch.object(
                core, "common_contract", return_value=freeze["expected_common_contract"]
            ), mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=_common_reconstruction_fixture(),
            ), mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ), mock.patch.object(
                audit, "_symbolic_manifest_expected",
                side_effect=lambda *, arm_id, **_kwargs: copy.deepcopy(
                    freeze["arms"][arm_id]["manifest_template"]
                ),
            ), mock.patch.object(
                audit,
                "_audit_runtime_observation",
                return_value=freeze["audit_runtime"],
            ), infra[0], infra[1]:
                gate = audit._validate_freeze(
                    freeze,
                    freeze_json=paths["freeze"],
                    runtime=freeze["audit_runtime"],
                    source_bag=paths["source"],
                    raw_bag=paths["raw"],
                    camera_yaml=paths["camera"],
                    arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw",
                    allow_prefix=False,
                    expected_frames=900,
                )
            self.assertEqual(set(gate["arms"]), set(audit.EXPECTED_ARMS))

    def test_launcher_supervision_json_types_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            infra = _infrastructure_patches(freeze)
            freeze["launcher_receipt_contract"]["supervision"]["no_retry"] = 1
            with mock.patch.object(
                core, "common_contract", return_value=freeze["expected_common_contract"]
            ), mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=_common_reconstruction_fixture(),
            ), mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ), infra[0], infra[1], self.assertRaisesRegex(audit.AuditFailure, "supervision"):
                audit._validate_freeze(
                    freeze,
                    freeze_json=paths["freeze"],
                    runtime=freeze["audit_runtime"],
                    source_bag=paths["source"],
                    raw_bag=paths["raw"],
                    camera_yaml=paths["camera"],
                    arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw",
                    allow_prefix=False,
                    expected_frames=900,
                )

    def test_freeze_cannot_replace_or_omit_a_mandatory_outcome_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            infra = _infrastructure_patches(freeze)
            arm = freeze["arms"][audit.XFEAT_ARM]
            pointer = "/outputs/feature_bag/size_bytes"
            _set_pointer(arm["manifest_template"], pointer, 123)
            arm["dynamic_scalar_paths"].remove(pointer)
            arm["manifest_template_sha256"] = core._canonical_sha256(
                arm["manifest_template"]
            )
            with mock.patch.object(
                core, "common_contract", return_value=freeze["expected_common_contract"]
            ), mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=_common_reconstruction_fixture(),
            ), mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ), infra[0], infra[1], self.assertRaisesRegex(audit.AuditFailure, "dynamic scalar path"):
                audit._validate_freeze(
                    freeze, freeze_json=paths["freeze"], runtime=freeze["audit_runtime"],
                    source_bag=paths["source"], raw_bag=paths["raw"],
                    camera_yaml=paths["camera"], arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw", allow_prefix=False,
                    expected_frames=900,
                )

    def test_freeze_rejects_forbidden_dynamic_legacy_binding_and_path_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, arm_paths, paths = _synthetic_freeze(Path(temporary))
            infra = _infrastructure_patches(freeze)
            marker = {
                audit.TEMPLATE_MARKER_KEY: {
                    "type": "int",
                    "minimum": 0,
                    "binding": "live_legacy_manifest_size",
                }
            }
            with self.assertRaisesRegex(audit.AuditFailure, "not permitted"):
                audit._dynamic_rule(marker, pointer="/outputs/feature_bag/size_bytes")
            freeze["arms"][audit.GFTT_ARM]["paths"]["private_work_directory"] = (
                freeze["arms"][audit.XFEAT_ARM]["paths"]["private_work_directory"]
            )
            with mock.patch.object(
                core, "common_contract", return_value=freeze["expected_common_contract"]
            ), mock.patch.object(
                audit, "_reconstruct_common_diagnostics",
                return_value=_common_reconstruction_fixture(),
            ), mock.patch.object(
                core.primitive, "load_camera_model",
                return_value=(None, None, "pinhole"),
            ), mock.patch.object(
                core.primitive, "_nonfeature_digest",
                return_value={"message_count": 0, "ordered_sha256": "0" * 64, "topics": {}},
            ), infra[0], infra[1], self.assertRaisesRegex(audit.AuditFailure, "paths:cli|alias|rebuilt command"):
                audit._validate_freeze(
                    freeze,
                    freeze_json=paths["freeze"],
                    runtime=freeze["audit_runtime"],
                    source_bag=paths["source"],
                    raw_bag=paths["raw"],
                    camera_yaml=paths["camera"],
                    arm_paths=arm_paths,
                    audit_paths={
                        "pre_run_start_receipt": paths["pre_run_start_receipt"],
                        "post_run_pair_seal": paths["post_run_pair_seal"],
                    },
                    feature_topic="/feature_tracker/feature",
                    image_topic="/camera/image_raw",
                    allow_prefix=False,
                    expected_frames=900,
                )

    def test_full_gftt_manifest_exact_schema_and_live_code_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest, attempt, paths, locked = _gftt_manifest_fixture(Path(temporary))
            audit._validate_manifest_exact(
                manifest,
                expected=copy.deepcopy(manifest),
                expected_attempt=attempt,
                attempt_path=Path(paths["attempt_json"]),
                arm_id=audit.GFTT_ARM,
                paths=paths,
                locked_inputs=locked,
                expected_common=manifest["common_contract"],
            )
            bad = copy.deepcopy(manifest)
            bad["code_artifacts"]["detector_runtime"]["frozen_detector_parameters"][
                "max_corners"
            ] = 2047
            with self.assertRaisesRegex(audit.AuditFailure, "fixed leaf mismatch|arm_contract"):
                audit._validate_manifest_exact(
                    bad,
                    expected=manifest,
                    expected_attempt=attempt,
                    attempt_path=Path(paths["attempt_json"]),
                    arm_id=audit.GFTT_ARM,
                    paths=paths,
                    locked_inputs=locked,
                    expected_common=manifest["common_contract"],
                )

    def test_xfeat_torch_import_origin_contract_is_static_exact(self) -> None:
        metadata = audit._symbolic_detector_metadata(
            arm_id=audit.XFEAT_ARM,
            image_shapes_hw=[[8, 8]],
            mandatory_rules=audit._mandatory_dynamic_rules(audit.XFEAT_ARM),
        )
        expected = audit.matched_xfeat.static_torch_import_origin_contract()
        self.assertEqual(
            set(metadata["matched_torch_import_origin_contract"]),
            set(audit.matched_xfeat.FROZEN_TORCH_IMPORT_MODULES),
        )
        self.assertEqual(
            metadata["matched_torch_import_origin_contract"], expected
        )
        self.assertEqual(
            metadata["matched_package_initializer_contract"],
            audit.matched_xfeat.static_xfeat_package_initializer_contract(),
        )
        self.assertEqual(
            metadata["matched_tqdm_import_contract"],
            audit.matched_xfeat.static_tqdm_import_contract(),
        )
        self.assertEqual(
            metadata["optional_matcher_dependency_contract"],
            audit.matched_xfeat.expected_optional_matcher_dependency_contract(),
        )
        bad = copy.deepcopy(metadata)
        label = next(iter(audit.XFEAT_TORCH_IMPORT_KEYS))
        bad["matched_torch_import_origin_contract"][label]["module"] += ".drift"
        with self.assertRaisesRegex(audit.AuditFailure, "import_origin_contract"):
            audit._validate_detector_metadata_schema(bad, arm_id=audit.XFEAT_ARM)
        bad_package = copy.deepcopy(metadata)
        bad_package["matched_package_initializer_contract"]["package_path"] = [
            "/tmp/poisoned-modules"
        ]
        with self.assertRaisesRegex(audit.AuditFailure, "package_initializer"):
            audit._validate_detector_metadata_schema(
                bad_package, arm_id=audit.XFEAT_ARM
            )
        bad_tqdm = copy.deepcopy(metadata)
        bad_tqdm["matched_tqdm_import_contract"]["tqdm_init"]["loader"] = (
            "PoisonedLoader"
        )
        with self.assertRaisesRegex(audit.AuditFailure, "tqdm_import_contract"):
            audit._validate_detector_metadata_schema(
                bad_tqdm, arm_id=audit.XFEAT_ARM
            )
        bad_optional = copy.deepcopy(metadata)
        bad_optional["optional_matcher_dependency_contract"][
            "official_kornia_available"
        ] = True
        with self.assertRaisesRegex(audit.AuditFailure, "optional_matcher"):
            audit._validate_detector_metadata_schema(
                bad_optional, arm_id=audit.XFEAT_ARM
            )

    def test_producer_shaped_xfeat_initializer_metadata_fails_closed(self) -> None:
        metadata = audit._symbolic_detector_metadata(
            arm_id=audit.XFEAT_ARM,
            image_shapes_hw=[[8, 8]],
            mandatory_rules=audit._mandatory_dynamic_rules(audit.XFEAT_ARM),
        )
        runtime = metadata["runtime"]
        runtime["detect_calls"] = 1
        runtime["candidate_total"] = 1
        runtime["detect_ms"] = {
            "warmup": {
                "count": 1,
                "median_ms": 1.0,
                "p90_ms": 1.0,
                "total_ms": 1.0,
            },
            "steady_state": {
                "count": 0,
                "median_ms": None,
                "p90_ms": None,
                "total_ms": 0.0,
            },
            "all": {
                "count": 1,
                "median_ms": 1.0,
                "p90_ms": 1.0,
                "total_ms": 1.0,
            },
        }
        audit._validate_detector_metadata_schema(metadata, arm_id=audit.XFEAT_ARM)

        mutations = (
            ("origin", ("spec_origin",), "/tmp/poisoned-modules-init.py"),
            ("loader", ("loader",), "PoisonedLoader"),
            ("hash", ("file", "sha256"), "0" * 64),
            ("file_path", ("file", "path"), "/tmp/poisoned-modules-init.py"),
            ("package_path", ("package_path",), ["/tmp/poisoned-modules"]),
        )
        for label, path, value in mutations:
            with self.subTest(label=label):
                bad = copy.deepcopy(metadata)
                target = bad["matched_package_initializer_contract"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(
                    audit.AuditFailure, "package_initializer"
                ):
                    audit._validate_detector_metadata_schema(
                        bad, arm_id=audit.XFEAT_ARM
                    )

    def test_real_shaped_legacy_manifest_reason_and_empty_private_work_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _attempt_payload, paths, _locked = _gftt_manifest_fixture(root)
            work = Path(paths["private_work_directory"])
            algorithm = {
                "common_contract": manifest["common_contract"],
                "common_contract_sha256": manifest["common_contract_sha256"],
                "arm_contract": manifest["arm_contract"],
                "arm_contract_sha256": manifest["arm_contract_sha256"],
            }
            legacy = {
                key: copy.deepcopy(manifest[key])
                for key in (
                    "schema_version", "status", "formal_eligible", "prefix", "inputs",
                    "nonfeature_stream_before", "nonfeature_stream_after", "metrics",
                    "raw_frame_diagnostics",
                )
            }
            legacy.update(
                {
                    "formal_eligibility_reason": "full_export_from_frozen_cli_production_factory",
                    "detector_origin": "cli_production_factory",
                    "algorithm": algorithm,
                    "algorithm_config_sha256": core._canonical_sha256(algorithm),
                    "code_artifacts": {
                        "exporter": manifest["code_artifacts"]["wrapper"],
                        "carrier_base": manifest["code_artifacts"]["frozen_primitive_module"],
                        "klt_reference_source": manifest["common_contract"]["implementation"]["klt_reference_source"],
                        "quality_reference_source": manifest["common_contract"]["implementation"]["quality_reference_source"],
                        "detector": manifest["code_artifacts"]["detector_runtime"],
                    },
                    "output_bag": {
                        **audit._file_identity(Path(paths["feature_bag"])),
                        "path": manifest["legacy_prepublication_rebind"][
                            "primitive_reported_work_bag_path"
                        ],
                    },
                }
            )
            legacy_path = Path(paths["legacy_primitive_manifest"])
            legacy_path.write_text(
                json.dumps(legacy, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            gate = audit._validate_legacy_manifest(
                arm_id=audit.GFTT_ARM,
                legacy_path=legacy_path,
                feature_bag=Path(paths["feature_bag"]),
                matched_manifest=manifest,
                allow_prefix=False,
            )
            self.assertTrue(gate["pass"])
            bad_path = copy.deepcopy(legacy)
            bad_path["output_bag"]["path"] = str(work / "other.bag")
            legacy_path.write_text(
                json.dumps(bad_path, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(audit.AuditFailure, "prepublication rebind"):
                audit._validate_legacy_manifest(
                    arm_id=audit.GFTT_ARM,
                    legacy_path=legacy_path,
                    feature_bag=Path(paths["feature_bag"]),
                    matched_manifest=manifest,
                    allow_prefix=False,
                )
            legacy_path.write_text(
                json.dumps(legacy, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            (work / "unexpected").write_bytes(b"x")
            with self.assertRaisesRegex(audit.AuditFailure, "not empty"):
                audit._validate_legacy_manifest(
                    arm_id=audit.GFTT_ARM,
                    legacy_path=legacy_path,
                    feature_bag=Path(paths["feature_bag"]),
                    matched_manifest=manifest,
                    allow_prefix=False,
                )

    def test_legacy_manifest_reason_is_exact_for_prefix_and_formal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest, _attempt_payload, paths, _locked = _gftt_manifest_fixture(
                Path(temporary)
            )
            legacy_path = Path(paths["legacy_primitive_manifest"])

            def write_legacy(reason: str) -> None:
                algorithm = {
                    "common_contract": manifest["common_contract"],
                    "common_contract_sha256": manifest["common_contract_sha256"],
                    "arm_contract": manifest["arm_contract"],
                    "arm_contract_sha256": manifest["arm_contract_sha256"],
                }
                legacy = {
                    key: copy.deepcopy(manifest[key])
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
                    )
                }
                legacy.update(
                    {
                        "formal_eligibility_reason": reason,
                        "detector_origin": "cli_production_factory",
                        "algorithm": algorithm,
                        "algorithm_config_sha256": core._canonical_sha256(
                            algorithm
                        ),
                        "code_artifacts": {
                            "exporter": manifest["code_artifacts"]["wrapper"],
                            "carrier_base": manifest["code_artifacts"][
                                "frozen_primitive_module"
                            ],
                            "klt_reference_source": manifest["common_contract"][
                                "implementation"
                            ]["klt_reference_source"],
                            "quality_reference_source": manifest[
                                "common_contract"
                            ]["implementation"]["quality_reference_source"],
                            "detector": manifest["code_artifacts"][
                                "detector_runtime"
                            ],
                        },
                        "output_bag": {
                            **audit._file_identity(Path(paths["feature_bag"])),
                            "path": manifest["legacy_prepublication_rebind"][
                                "primitive_reported_work_bag_path"
                            ],
                        },
                    }
                )
                legacy_path.write_text(
                    json.dumps(
                        legacy, indent=2, sort_keys=True, allow_nan=False
                    )
                    + "\n",
                    encoding="utf-8",
                )

            def validate(*, allow_prefix: bool) -> dict[str, object]:
                return audit._validate_legacy_manifest(
                    arm_id=audit.GFTT_ARM,
                    legacy_path=legacy_path,
                    feature_bag=Path(paths["feature_bag"]),
                    matched_manifest=manifest,
                    allow_prefix=allow_prefix,
                )

            formal_legacy_reason = (
                "full_export_from_frozen_cli_production_factory"
            )
            formal_matched_reason = (
                "full_export_from_frozen_matched_cli_factory"
            )
            prefix_reason = "explicit_prefix_is_nonformal"

            write_legacy(formal_legacy_reason)
            self.assertTrue(validate(allow_prefix=False)["pass"])
            write_legacy(prefix_reason)
            with self.assertRaisesRegex(
                audit.AuditFailure, "legacy formal eligibility reason mismatch"
            ):
                validate(allow_prefix=False)
            write_legacy(formal_legacy_reason)
            manifest["formal_eligibility_reason"] = prefix_reason
            with self.assertRaisesRegex(
                audit.AuditFailure, "matched formal eligibility reason mismatch"
            ):
                validate(allow_prefix=False)

            manifest.update(
                {
                    "status": "PREFIX_NONFORMAL",
                    "formal_eligible": False,
                    "formal_eligibility_reason": prefix_reason,
                    "prefix": {
                        "requested_max_published_frames": 16,
                        "source_total_published_frames": 900,
                        "selected_published_frames": 16,
                        "cutoff_feature_record_stamp_ns": 123,
                    },
                }
            )
            write_legacy(prefix_reason)
            self.assertTrue(validate(allow_prefix=True)["pass"])
            write_legacy(formal_legacy_reason)
            with self.assertRaisesRegex(
                audit.AuditFailure, "legacy formal eligibility reason mismatch"
            ):
                validate(allow_prefix=True)
            write_legacy(prefix_reason)
            manifest["formal_eligibility_reason"] = formal_matched_reason
            with self.assertRaisesRegex(
                audit.AuditFailure, "matched formal eligibility reason mismatch"
            ):
                validate(allow_prefix=True)

    def test_tiny_manifest_cannot_self_authorize(self) -> None:
        tiny = {"schema_version": core.SCHEMA_VERSION, "arm_contract": {"arm_id": audit.XFEAT_ARM}}
        result = audit._manifest_pair_contract(
            tiny,
            tiny,
            expected_left=tiny,
            expected_right=tiny,
            allowed_pair_scalar_differences=[],
            required_pair_scalar_differences=[],
        )
        self.assertFalse(result["pass"])
        self.assertIn("exact keyset mismatch", result["violations"][0])

    def test_both_arms_same_common_drift_still_fails_against_freeze(self) -> None:
        expected_x = _full_manifest(audit.XFEAT_ARM)
        expected_g = _full_manifest(audit.GFTT_ARM)
        actual_x, actual_g = copy.deepcopy(expected_x), copy.deepcopy(expected_g)
        actual_x["common_contract"]["carrier"]["lk_win_size"] = [23, 23]
        actual_g["common_contract"]["carrier"]["lk_win_size"] = [23, 23]
        allowed = audit._pair_scalar_differences(expected_x, expected_g)
        result = audit._manifest_pair_contract(
            actual_x,
            actual_g,
            expected_left=expected_x,
            expected_right=expected_g,
            allowed_pair_scalar_differences=allowed,
            required_pair_scalar_differences=[],
        )
        self.assertFalse(result["pass"])
        self.assertTrue(any("fixed leaf mismatch" in item for item in result["violations"]))

    def test_identical_dynamic_output_bytes_do_not_create_a_directional_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze, _arm_paths, _paths = _synthetic_freeze(Path(temporary))
            expected_x = freeze["arms"][audit.XFEAT_ARM]["manifest_template"]
            expected_g = freeze["arms"][audit.GFTT_ARM]["manifest_template"]
            xfeat = _materialize_template(expected_x)
            gftt = _materialize_template(expected_g)
            for output_key in (
                "feature_bag", "raw_diagnostics_csv", "legacy_primitive_manifest"
            ):
                gftt["outputs"][output_key]["size_bytes"] = xfeat["outputs"][output_key]["size_bytes"]
                gftt["outputs"][output_key]["sha256"] = xfeat["outputs"][output_key]["sha256"]
            allowed = freeze["allowed_pair_scalar_differences"]
            result = audit._manifest_pair_contract(
                xfeat,
                gftt,
                expected_left=expected_x,
                expected_right=expected_g,
                allowed_pair_scalar_differences=allowed,
                required_pair_scalar_differences=sorted(audit.MANDATORY_PAIR_DIFFERENCES),
            )
            self.assertTrue(result["pass"], result)

    def test_missing_unknown_and_scalar_type_drift_fail(self) -> None:
        expected_x = _full_manifest(audit.XFEAT_ARM)
        expected_g = _full_manifest(audit.GFTT_ARM)
        for mutation in ("missing", "unknown", "bool_for_int", "reorder"):
            actual_x, actual_g = copy.deepcopy(expected_x), copy.deepcopy(expected_g)
            if mutation == "missing":
                del actual_x["runtime"]
            elif mutation == "unknown":
                actual_x["unknown"] = 1
            elif mutation == "bool_for_int":
                actual_x["metrics"]["observations"] = True
            else:
                actual_x["arm_contract"]["detector"]["contract"] = {"order": [2, 1]}
                expected_x2 = copy.deepcopy(expected_x)
                expected_x2["arm_contract"]["detector"]["contract"] = {"order": [1, 2]}
                expected_x = expected_x2
            result = audit._manifest_pair_contract(
                actual_x,
                actual_g,
                expected_left=expected_x,
                expected_right=expected_g,
                allowed_pair_scalar_differences=audit._pair_scalar_differences(expected_x, expected_g),
                required_pair_scalar_differences=[],
            )
            self.assertFalse(result["pass"], mutation)

    def test_dynamic_binding_cannot_replace_fixed_common_leaf(self) -> None:
        marker = {audit.TEMPLATE_MARKER_KEY: {"type": "int", "binding": "metric_outcome"}}
        with self.assertRaisesRegex(audit.AuditFailure, "not permitted"):
            audit._dynamic_rule(marker, pointer="/common_contract/carrier/feature_cap")

    def test_feature_identity_binding_is_limited_to_output_and_two_rebind_echoes(self) -> None:
        size_marker = {
            audit.TEMPLATE_MARKER_KEY: {
                "type": "int",
                "minimum": 0,
                "binding": "live_feature_bag_size",
            }
        }
        sha_marker = {
            audit.TEMPLATE_MARKER_KEY: {
                "type": "string",
                "pattern": "[0-9a-f]{64}",
                "binding": "live_feature_bag_sha256",
            }
        }
        for stem in (
            "/outputs/feature_bag",
            "/legacy_prepublication_rebind/"
            "primitive_reported_output_identity_after_path_rebind",
            "/legacy_prepublication_rebind/published_feature_bag_identity",
        ):
            audit._dynamic_rule(size_marker, pointer=stem + "/size_bytes")
            audit._dynamic_rule(sha_marker, pointer=stem + "/sha256")
        with self.assertRaisesRegex(audit.AuditFailure, "not permitted"):
            audit._dynamic_rule(
                size_marker,
                pointer="/legacy_prepublication_rebind/primitive_reported_work_bag_path",
            )

    def test_dynamic_template_is_type_sensitive_and_no_unknown(self) -> None:
        template = {
            "fixed": 1,
            "metric": {audit.TEMPLATE_MARKER_KEY: {"type": "int", "minimum": 0, "binding": "metric_outcome"}},
        }
        with self.assertRaisesRegex(audit.AuditFailure, "type mismatch"):
            audit._match_manifest_template({"fixed": True, "metric": 1}, template)
        with self.assertRaisesRegex(audit.AuditFailure, "keyset"):
            audit._match_manifest_template({"fixed": 1, "metric": 1, "unknown": 2}, template)

    def test_nullable_dynamic_float_rules_accept_null_or_finite_and_reject_bad_values(self) -> None:
        marker = {
            audit.TEMPLATE_MARKER_KEY: {
                "types": ["float", "null"],
                "minimum": 0.0,
                "maximum": 1.000001,
                "binding": "diagnostic_outcome",
            }
        }
        pointer = "/raw_frame_diagnostics/0/fb_median_px"
        rule = audit._dynamic_rule(marker, pointer=pointer)
        audit._validate_dynamic_value(None, rule, pointer=pointer)
        audit._validate_dynamic_value(0.5, rule, pointer=pointer)
        for value in (float("nan"), -0.1, 1.1):
            with self.assertRaises(audit.AuditFailure):
                audit._validate_dynamic_value(value, rule, pointer=pointer)

    def test_diagnostics_reader_rejects_trailing_extra_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "diag.csv"
            header = ",".join(core.DIAGNOSTIC_FIELDS)
            values = []
            for field in core.DIAGNOSTIC_FIELDS:
                if field in audit.BOOL_DIAGNOSTIC_FIELDS:
                    values.append("0")
                elif field in audit.HASH_DIAGNOSTIC_FIELDS:
                    values.append("0" * 64)
                elif field in audit.FLOAT_DIAGNOSTIC_FIELDS:
                    values.append("")
                else:
                    values.append("0")
            path.write_text(header + "\n" + ",".join(values) + ",hidden\n", encoding="utf-8")
            with self.assertRaisesRegex(audit.AuditFailure, "extra or missing"):
                audit._read_diagnostics(path)

    def test_diagnostics_bind_manifest_stream_and_locked_raw_rows(self) -> None:
        rows = _diagnostic_rows()
        manifest = _diagnostic_manifest(rows)
        rebuilt = [{key: row[key] for key in audit.COMMON_DIAGNOSTIC_FIELDS} for row in rows]
        result = audit._validate_diagnostics_binding(
            arm_id=audit.GFTT_ARM,
            manifest=manifest,
            csv_rows=copy.deepcopy(rows),
            reconstructed_common=rebuilt,
            image_shapes_hw=[[8, 8]],
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["detector_candidates"], 350)

    def test_both_diagnostics_same_forgery_fails_raw_reconstruction(self) -> None:
        rows = _diagnostic_rows()
        forged = copy.deepcopy(rows)
        forged[17]["processed_image_sha256"] = "f" * 64
        manifest = _diagnostic_manifest(forged)
        rebuilt = [{key: row[key] for key in audit.COMMON_DIAGNOSTIC_FIELDS} for row in rows]
        with self.assertRaisesRegex(audit.AuditFailure, "raw_reconstruction"):
            audit._validate_diagnostics_binding(
                arm_id=audit.GFTT_ARM,
                manifest=manifest,
                csv_rows=forged,
                reconstructed_common=rebuilt,
                image_shapes_hw=[[8, 8]],
            )

    def test_csv_change_without_manifest_change_fails(self) -> None:
        rows = _diagnostic_rows()
        csv_rows = copy.deepcopy(rows)
        csv_rows[2]["adaptive_clahe_applied"] = not csv_rows[2]["adaptive_clahe_applied"]
        with self.assertRaisesRegex(audit.AuditFailure, "CSV_vs_manifest"):
            audit._validate_diagnostics_binding(
                arm_id=audit.GFTT_ARM,
                manifest=_diagnostic_manifest(rows),
                csv_rows=csv_rows,
                reconstructed_common=[{key: row[key] for key in audit.COMMON_DIAGNOSTIC_FIELDS} for row in rows],
                image_shapes_hw=[[8, 8]],
            )

    def test_diagnostics_missing_row_and_candidate_2049_fail(self) -> None:
        rows = _diagnostic_rows()
        with self.assertRaisesRegex(audit.AuditFailure, "row count"):
            audit._validate_diagnostic_rows_shape(rows[:-1], arm_id=audit.GFTT_ARM)
        bad = copy.deepcopy(rows)
        bad[0]["detector_candidates"] = 2049
        with self.assertRaisesRegex(audit.AuditFailure, "candidate cap"):
            audit._validate_diagnostic_rows_shape(bad, arm_id=audit.GFTT_ARM)

    def test_runtime_candidate_total_mismatch_fails(self) -> None:
        rows = _diagnostic_rows()
        manifest = _diagnostic_manifest(rows)
        manifest["code_artifacts"]["detector_runtime"]["runtime"]["candidate_total"] += 1
        with self.assertRaisesRegex(audit.AuditFailure, "candidate total"):
            audit._validate_diagnostics_binding(
                arm_id=audit.GFTT_ARM,
                manifest=manifest,
                csv_rows=rows,
                reconstructed_common=[{key: row[key] for key in audit.COMMON_DIAGNOSTIC_FIELDS} for row in rows],
                image_shapes_hw=[[8, 8]],
            )

    def test_locked_raw_reconstruction_is_1800_and_recomputes_pixels(self) -> None:
        schedule = [core.primitive.ScheduleFrame(None, 2 * index + 1, 2 * index + 1) for index in range(900)]
        raw = [core.primitive.RawFrame(index + 1, np.full((8, 8), index % 251, np.uint8)) for index in range(1800)]
        with mock.patch.object(core.primitive, "read_source_schedule", return_value=(schedule, 900)), mock.patch.object(core.primitive, "read_raw_frames", return_value=raw), mock.patch.object(core.primitive, "_schedule_raw_indices", return_value=np.arange(1, 1800, 2)), mock.patch.object(core.primitive, "adaptive_clahe", side_effect=lambda image: (np.asarray(image) + np.uint8(1), True)):
            rows, evidence = audit._reconstruct_common_diagnostics(
                source_bag=Path("source"),
                raw_bag=Path("raw"),
                feature_topic="/f",
                image_topic="/i",
            )
        self.assertEqual(len(rows), 1800)
        self.assertEqual(evidence["raw_row_count"], 1800)
        self.assertTrue(all(row["adaptive_clahe_applied"] for row in rows))
        self.assertNotEqual(rows[0]["raw_image_sha256"], rows[0]["processed_image_sha256"])

    def test_feature_id_gaps_pass_but_revival_and_half_dt_fail(self) -> None:
        frames = [
            _frame(0, 1_000_000_000, [1], [[0.0, 0.0]], [[0.0, 0.0]]),
            _frame(1, 3_000_000_000, [1, 3], [[1.0, 0.0], [0.0, 1.0]], [[0.5, 0.0], [0.0, 0.0]]),
        ]
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[frames, frames]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM, feature_topic="/f", allow_prefix=False, expected_frames=2)
        self.assertTrue(result["pass"], result)
        bad_velocity = copy.deepcopy(frames)
        bad_velocity[1].velocities[0, 0] = 1.0
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[frames, bad_velocity]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM, feature_topic="/f", allow_prefix=False, expected_frames=2)
        self.assertFalse(result["pass"])
        self.assertIn("frame1:velocity", result["violations"])
        revival = frames + [_frame(2, 5_000_000_000, [2], [[0.0, 0.0]], [[0.0, 0.0]])]
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[revival, revival]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM, feature_topic="/f", allow_prefix=False, expected_frames=3)
        self.assertFalse(result["pass"])
        self.assertIn("frame2:new_id_not_monotonic", result["violations"])

    def test_feature_frames_bind_published_diagnostic_counts_and_birth_id_ceiling(self) -> None:
        frames = [
            _frame(0, 1_000_000_000, [0], [[0.0, 0.0]], [[0.0, 0.0]]),
            _frame(1, 3_000_000_000, [0, 2], [[1.0, 0.0], [0.0, 1.0]], [[0.5, 0.0], [0.0, 0.0]]),
        ]
        diagnostics = [
            {"raw_index": 0, "published": True, "births": 2, "output_tracks": 1},
            {"raw_index": 1, "published": True, "births": 2, "output_tracks": 2},
        ]
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[frames, frames]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(
                Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM,
                feature_topic="/f", allow_prefix=False, expected_frames=2,
                raw_diagnostics=diagnostics,
            )
        self.assertTrue(result["pass"], result)
        wrong_count = copy.deepcopy(diagnostics)
        wrong_count[1]["output_tracks"] = 1
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[frames, frames]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(
                Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM,
                feature_topic="/f", allow_prefix=False, expected_frames=2,
                raw_diagnostics=wrong_count,
            )
        self.assertFalse(result["pass"])
        self.assertIn("frame1:diagnostics_output_tracks", result["violations"])
        too_few_births = copy.deepcopy(diagnostics)
        too_few_births[0]["births"] = 1
        too_few_births[1]["births"] = 1
        with mock.patch.object(audit_base, "load_feature_frames", side_effect=[frames, frames]), mock.patch.object(audit_base, "load_camera_model", return_value=_IdentityCamera()):
            result = audit._feature_contract(
                Path("s"), Path("c"), Path("y"), arm_id=audit.XFEAT_ARM,
                feature_topic="/f", allow_prefix=False, expected_frames=2,
                raw_diagnostics=too_few_births,
            )
        self.assertFalse(result["pass"])
        self.assertIn("frame1:id_not_bounded_by_raw_births", result["violations"])

    def test_single_link_regular_file_gate_rejects_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "a", root / "b"
            first.write_bytes(b"x")
            os.link(first, second)
            with self.assertRaisesRegex(audit.AuditFailure, "single-link"):
                audit._regular_path(first, label="test")

    def test_write_all_survives_short_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            original_write = os.write

            def short_write(fd, payload):
                return original_write(fd, payload[: max(1, min(3, len(payload)))])

            try:
                with mock.patch.object(audit.os, "write", side_effect=short_write):
                    audit._replace_reserved_fd_payload(descriptor, b"abcdefghijk")
            finally:
                os.close(descriptor)
            self.assertEqual(path.read_bytes(), b"abcdefghijk")

    def test_failure_receipt_is_retained_and_second_attempt_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.write_bytes(b"x")
            work = root / "work"
            work.mkdir()
            output = root / "audit.json"
            args = [
                "--freeze-json", str(existing), "--source-feature-bag", str(existing),
                "--raw-image-bag", str(existing), "--camera-yaml", str(existing),
                "--xfeat-bag", str(existing), "--xfeat-manifest", str(existing),
                "--xfeat-diagnostics", str(existing), "--xfeat-legacy-manifest", str(existing),
                "--xfeat-work-directory", str(work), "--xfeat-attempt", str(existing),
                "--gftt-bag", str(existing), "--gftt-manifest", str(existing),
                "--gftt-diagnostics", str(existing), "--gftt-legacy-manifest", str(existing),
                "--gftt-work-directory", str(work), "--gftt-attempt", str(existing),
                "--image-topic", "/i", "--expected-published-frames", "900",
                "--pre-run-start-receipt", str(root / "start.json"),
                "--post-run-audit-json", str(output),
            ]
            with mock.patch.object(audit, "audit_pair", side_effect=audit.AuditFailure("boom")):
                self.assertEqual(audit.main(args), 2)
                first = output.read_bytes()
                self.assertEqual(json.loads(first)["status"], "ERROR")
                self.assertEqual(audit.main(args), 2)
                self.assertEqual(output.read_bytes(), first)

    def test_unexpected_runtime_failure_also_retains_canonical_error_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.write_bytes(b"x")
            work = root / "work"
            work.mkdir()
            output = root / "audit.json"
            args = [
                "--freeze-json", str(existing), "--source-feature-bag", str(existing),
                "--raw-image-bag", str(existing), "--camera-yaml", str(existing),
                "--xfeat-bag", str(existing), "--xfeat-manifest", str(existing),
                "--xfeat-diagnostics", str(existing), "--xfeat-legacy-manifest", str(existing),
                "--xfeat-work-directory", str(work), "--xfeat-attempt", str(existing),
                "--gftt-bag", str(existing), "--gftt-manifest", str(existing),
                "--gftt-diagnostics", str(existing), "--gftt-legacy-manifest", str(existing),
                "--gftt-work-directory", str(work), "--gftt-attempt", str(existing),
                "--image-topic", "/i", "--expected-published-frames", "900",
                "--pre-run-start-receipt", str(root / "start.json"),
                "--post-run-audit-json", str(output),
            ]
            with mock.patch.object(audit, "audit_pair", side_effect=RuntimeError("runtime-drift")):
                self.assertEqual(audit.main(args), 2)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "ERROR")
            self.assertEqual(receipt["error"]["type"], "RuntimeError")
            self.assertEqual(receipt["error"]["message"], "runtime-drift")

    def test_check_start_rejects_any_reserved_path_appearing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze = root / "freeze.json"
            freeze.write_bytes(audit._canonical_bytes({"x": 1}))
            source = root / "source"
            source.write_bytes(b"x")
            paths = [root / f"reserved{index}" for index in range(12)]
            kwargs = dict(
                freeze_json=freeze, source_bag=source, raw_bag=source,
                camera_yaml=source, xfeat_bag=paths[0], xfeat_manifest=paths[1],
                xfeat_diagnostics=paths[2], xfeat_legacy_manifest=paths[3],
                xfeat_work_directory=paths[4], xfeat_attempt=paths[5],
                gftt_bag=paths[6], gftt_manifest=paths[7], gftt_diagnostics=paths[8],
                gftt_legacy_manifest=paths[9], gftt_work_directory=paths[10],
                gftt_attempt=paths[11], feature_topic="/f", image_topic="/i",
                allow_prefix=False, expected_frames=900,
                pre_run_start_receipt=root / "start.json",
                post_run_pair_seal=root / "seal.json",
            )
            fake_gate = {
                "locked_inputs": {"source": 1},
                "governance": {"launcher_receipt_paths": []},
                "audit_paths": {"post_run_pair_seal": str(root / "seal.json")},
                "infrastructure_incident": {"path": "incident"},
                "artifact_filesystem_contract": {"schema_version": "filesystem"},
            }
            with mock.patch.object(audit, "_audit_runtime_observation", return_value={}), mock.patch.object(audit, "_validate_freeze", return_value=fake_gate):
                result = audit.check_pre_run_start(**kwargs)
                self.assertTrue(result["pass"])
                paths[9].write_bytes(b"appeared")
                with self.assertRaisesRegex(audit.AuditFailure, "not absent"):
                    audit.check_pre_run_start(**kwargs)

    def test_audit_code_closure_detects_base_identity_drift(self) -> None:
        original = audit._audit_code_closure()
        self.assertEqual(
            {
                "uw_frontend_package_initializer",
                "uw_frontend_quality_package_initializer",
                "xfeat_modules_package_initializer",
            },
            {
                key
                for key in original
                if key.endswith("package_initializer")
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            replacement = Path(temporary) / "base.py"
            replacement.write_bytes(b"different")
            with mock.patch.object(audit.audit_base, "__file__", str(replacement)):
                changed = audit._audit_code_closure()
            with mock.patch.object(
                audit.matched_xfeat,
                "XFEAT_MODULES_INITIALIZER",
                replacement,
            ):
                changed_initializer = audit._audit_code_closure()
        self.assertNotEqual(original["feature_audit_base"], changed["feature_audit_base"])
        self.assertNotEqual(
            original["xfeat_modules_package_initializer"],
            changed_initializer["xfeat_modules_package_initializer"],
        )


if __name__ == "__main__":
    unittest.main()
