#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from scripts import audit_matched_birth_rawlk_pair_formal_v2 as audit
from scripts import audit_matched_birth_rawlk_pair_v1 as probe_audit
from scripts import build_matched_birth_r3_pass_formal900_adoption_v1 as adoption_builder
from scripts import matched_birth_rawlk_core_v1 as core


def _identity(path: Path) -> dict[str, object]:
    encoded = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _main_audit_arguments(root: Path, output: Path) -> list[str]:
    """Build a minimal real-filesystem CLI fixture with audit_pair mocked."""

    existing = root / "existing"
    existing.write_bytes(b"fixture\n")
    work = root / "work"
    work.mkdir()
    return [
        "--action", "audit",
        "--freeze-json", str(existing),
        "--source-feature-bag", str(existing),
        "--raw-image-bag", str(existing),
        "--camera-yaml", str(existing),
        "--xfeat-bag", str(existing),
        "--xfeat-manifest", str(existing),
        "--xfeat-diagnostics", str(existing),
        "--xfeat-legacy-manifest", str(existing),
        "--xfeat-work-directory", str(work),
        "--xfeat-attempt", str(existing),
        "--gftt-bag", str(existing),
        "--gftt-manifest", str(existing),
        "--gftt-diagnostics", str(existing),
        "--gftt-legacy-manifest", str(existing),
        "--gftt-work-directory", str(work),
        "--gftt-attempt", str(existing),
        "--image-topic", "/camera/image_raw",
        "--expected-published-frames", "900",
        "--pre-run-start-receipt", str(
            root / audit.R4_ROOT_ARTIFACT_NAMES["pre_run_start_receipt"]
        ),
        "--post-run-audit-json", str(output),
    ]


def _r3_inventory() -> list[dict[str, object]]:
    root = audit.PROMOTED_R3_ROOT
    paths = [root]
    paths.extend(root / name for name in audit.R3_ROOT_FILE_NAMES)
    for arm_name in audit.R3_ARM_DIRECTORIES.values():
        arm = root / arm_name
        paths.extend([arm, arm / "private_work"])
        paths.extend(arm / name for name in audit.R3_ARM_FILE_NAMES)
    rows = []
    for path in paths:
        observed = os.lstat(path)
        row = {
            "path": str(path),
            "kind": "directory" if stat.S_ISDIR(observed.st_mode) else "regular",
            "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
            "uid": int(observed.st_uid), "gid": int(observed.st_gid),
            "device_id": int(observed.st_dev), "inode": int(observed.st_ino),
            "nlink": int(observed.st_nlink), "size_bytes": int(observed.st_size),
        }
        if row["kind"] == "regular":
            encoded = path.read_bytes()
            row["size_bytes"] = len(encoded)
            row["sha256"] = hashlib.sha256(encoded).hexdigest()
        rows.append(row)
    rows.sort(key=lambda row: row["path"])
    if len(rows) != 24:
        raise AssertionError("live r3 fixture is not exact 24")
    return rows


def _synthetic_held_tree(root: Path) -> tuple[dict[str, object], dict[str, Path]]:
    """Create the exact 5-directory/19-file topology used by held tree checks."""

    root.mkdir(mode=0o700)
    root.chmod(0o700)
    paths: list[Path] = [root]
    named: dict[str, Path] = {}
    for name in audit.R3_ROOT_FILE_NAMES:
        path = root / name
        path.write_bytes((name + "\n").encode("utf-8"))
        path.chmod(0o444)
        paths.append(path)
        named[name] = path
    for arm_name in audit.R3_ARM_DIRECTORIES.values():
        arm = root / arm_name
        arm.mkdir(mode=0o700)
        arm.chmod(0o700)
        private = arm / "private_work"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        paths.extend((arm, private))
        named[f"{arm_name}/private_work"] = private
        for name in audit.R3_ARM_FILE_NAMES:
            path = arm / name
            path.write_bytes((arm_name + "/" + name + "\n").encode("utf-8"))
            path.chmod(0o444)
            paths.append(path)
            named[f"{arm_name}/{name}"] = path
    inventory = []
    for path in paths:
        observed = os.lstat(path)
        row = {
            "path": str(path),
            "kind": "directory" if stat.S_ISDIR(observed.st_mode) else "regular",
            "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
            "uid": int(observed.st_uid),
            "gid": int(observed.st_gid),
            "device_id": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "nlink": int(observed.st_nlink),
            "size_bytes": int(observed.st_size),
        }
        if row["kind"] == "regular":
            encoded = path.read_bytes()
            row["size_bytes"] = len(encoded)
            row["sha256"] = hashlib.sha256(encoded).hexdigest()
        inventory.append(row)
    inventory.sort(key=lambda row: str(row["path"]))
    snapshot = audit._held_tree_snapshot(
        root=root,
        arm_directories=audit.R3_ARM_DIRECTORIES,
        root_file_names=audit.R3_ROOT_FILE_NAMES,
        arm_file_names=audit.R3_ARM_FILE_NAMES,
        expected_inventory=inventory,
        label="synthetic active evidence",
    )
    return snapshot, named


def _synthetic_active_formal_tree(
    base: Path, *, action: str
) -> tuple[Path, Path, dict[str, Path]]:
    """Create one exact check-start or audit r4 topology for the new helper."""

    root = base / f"r4-{action}"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    inputs = base / f"inputs-{action}"
    inputs.mkdir(mode=0o700)

    def write_file(path: Path, payload: bytes) -> None:
        path.write_bytes(payload)
        path.chmod(0o444)

    source_bag = inputs / "source.bag"
    raw_bag = inputs / "raw.bag"
    camera_yaml = inputs / "camera.yaml"
    for path in (source_bag, raw_bag, camera_yaml):
        write_file(path, (path.name + "\n").encode("utf-8"))

    values: dict[str, Path] = {
        "freeze_json": root / audit.R4_ROOT_ARTIFACT_NAMES["freeze"],
        "source_bag": source_bag,
        "raw_bag": raw_bag,
        "camera_yaml": camera_yaml,
        "pre_run_start_receipt": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["pre_run_start_receipt"]
        ),
        "post_run_pair_seal": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
        ),
    }
    write_file(values["freeze_json"], b"synthetic freeze\n")
    if action == "audit":
        write_file(
            values["pre_run_start_receipt"], b"synthetic start receipt\n"
        )

    role_names = {
        "bag": "features.bag",
        "manifest": "export_manifest.json",
        "diagnostics": "raw_diagnostics.csv",
        "legacy_manifest": "legacy_primitive_manifest.json",
        "work_directory": "private_work",
        "attempt": "producer_attempt.json",
    }
    audit_only_names = (
        "producer_attempt.json",
        "launcher_start_receipt.json",
        "launcher_rc_receipt.json",
        "export_manifest.json",
        "features.bag",
        "raw_diagnostics.csv",
        "legacy_primitive_manifest.json",
    )
    for prefix, arm_id in (("xfeat", audit.XFEAT_ARM), ("gftt", audit.GFTT_ARM)):
        arm = root / audit.R4_ARM_DIRECTORIES[arm_id]
        arm.mkdir(mode=0o700)
        arm.chmod(0o700)
        write_file(arm / "command_contract.json", b"synthetic command\n")
        if action == "audit":
            private = arm / "private_work"
            private.mkdir(mode=0o700)
            private.chmod(0o700)
            for name in audit_only_names:
                write_file(arm / name, (name + "\n").encode("utf-8"))
        values.update(
            {
                f"{prefix}_bag": arm / role_names["bag"],
                f"{prefix}_manifest": arm / role_names["manifest"],
                f"{prefix}_diagnostics": arm / role_names["diagnostics"],
                f"{prefix}_legacy_manifest": arm
                / role_names["legacy_manifest"],
                f"{prefix}_work_directory": arm
                / role_names["work_directory"],
                f"{prefix}_attempt": arm / role_names["attempt"],
            }
        )
    output = (
        values["pre_run_start_receipt"]
        if action == "check-start"
        else values["post_run_pair_seal"]
    )
    return root, output, values


def _r3_projection() -> dict[str, object]:
    root = audit.PROMOTED_R3_ROOT
    freeze = json.loads((root / "probe16_freeze.json").read_bytes())
    contracts = {
        arm_id: json.loads(
            (root / arm_name / "command_contract.json").read_bytes()
        )
        for arm_id, arm_name in audit.R3_ARM_DIRECTORIES.items()
    }
    return audit._static_scientific_projection(
        freeze, command_contracts=contracts
    )


def _adoption_payload() -> dict[str, object]:
    root = audit.PROMOTED_R3_ROOT
    entries = _r3_inventory()
    contracts = {
        arm_id: json.loads(
            (root / arm_name / "command_contract.json").read_bytes()
        )
        for arm_id, arm_name in audit.R3_ARM_DIRECTORIES.items()
    }
    freeze = json.loads((root / "probe16_freeze.json").read_bytes())
    recorded_projection = probe_audit._continuation_scientific_projection(
        freeze, command_contracts=contracts
    )
    arm_roles = {}
    for arm_id, arm_name in audit.R3_ARM_DIRECTORIES.items():
        arm = root / arm_name
        arm_roles[arm_id] = {
            "command_contract": _identity(arm / "command_contract.json"),
            "attempt": _identity(arm / "producer_attempt.json"),
            "launcher_start_receipt": _identity(
                arm / "launcher_start_receipt.json"
            ),
            "launcher_rc_receipt": _identity(arm / "launcher_rc_receipt.json"),
            "manifest": _identity(arm / "export_manifest.json"),
            "feature_bag": _identity(arm / "features.bag"),
            "diagnostics": _identity(arm / "raw_diagnostics.csv"),
            "legacy_primitive_manifest": _identity(
                arm / "legacy_primitive_manifest.json"
            ),
        }
    process = {
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
    return {
        "schema_version": audit.ADOPTION_SCHEMA_VERSION,
        "status": audit.ADOPTION_STATUS,
        "scientific_role": "POST_PROBE_CONTRACT_PASS_GATED_FORMAL_SCALE_PROMOTION",
        "builder_identity": _identity(Path(adoption_builder.__file__)),
        "builder_execution_contract": {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": {},
            "authorized_write_once_argv": [],
            "runtime": {},
            "runtime_sha256": core._canonical_sha256({}),
        },
        "human_record": _identity(adoption_builder.HUMAN_RECORD),
        "source_namespace": {
            "root": str(root),
            "filesystem": {"filesystem_type": "ext4", "device_id": 66312},
            "tree_entry_count": 24,
            "directory_count": 5,
            "regular_file_count": 19,
            "exact_tree_inventory": entries,
            "role_bindings": {
                "freeze": _identity(root / "probe16_freeze.json"),
                "pre_run_start_receipt": _identity(
                    root / "probe16_pre_run_start_receipt.json"
                ),
                "post_run_pair_seal": _identity(
                    root / "probe16_post_run_pair_seal.json"
                ),
                "arms": arm_roles,
            },
        },
        "pass_qualification": {
            "freeze_status": "FROZEN",
            "start_status": "PASS_PRE_RUN_FREEZE_AND_ABSENCE",
            "seal_status": "PASS",
            "seal_pass": True,
            "required_gate_names": sorted(audit.R3_PASS_GATE_KEYS),
            "every_gate_pass": True,
            "per_arm_process": {
                arm_id: copy.deepcopy(process) for arm_id in audit.EXPECTED_ARMS
            },
        },
        "source_static_projection_sha256": hashlib.sha256(
            audit._canonical_bytes(recorded_projection)
        ).hexdigest(),
        "target": {
            "root": str(audit.ARTIFACT_NAMESPACE_ROOT),
            "arm_directories": {"xfeat": "xfeat_r4", "gftt": "gftt_r4"},
            "mode": "formal900",
            "allow_prefix_nonformal": False,
            "published_frames": 900,
            "raw_frames": 1800,
        },
        "formal_transition_contract": {
            "transform_id": "probe16_to_formal900_v1",
            "path_mapping": {
                str(root): str(audit.ARTIFACT_NAMESPACE_ROOT),
                str(root / "xfeat_r3"): str(
                    audit.ARTIFACT_NAMESPACE_ROOT / "xfeat_r4"
                ),
                str(root / "gftt_r3"): str(
                    audit.ARTIFACT_NAMESPACE_ROOT / "gftt_r4"
                ),
            },
            "mode_transition": {
                "allow_prefix_nonformal": [True, False],
                "published_frames": [16, 900],
                "raw_frames": [32, 1800],
            },
            "producer_argv_transition": {
                "remove_exact_terminal_suffix": ["--max-published-frames", "16"],
                "replacement_limit_flag_forbidden": True,
            },
        },
        "evidence_use_boundary": {
            "source_output_bytes_read_for_integrity": True,
            "source_contract_pass_used_for_promotion": True,
            "source_relative_metrics_used_for_target_configuration": False,
            "source_output_bytes_reused": False,
            "source_outcomes_exposed_to_target_builder": False,
            "target_outcomes_read_pre_freeze": False,
        },
        "claim_boundary": {
            "confirmatory": False,
            "detector_birth_source_only_within_this_frozen_carrier": True,
            "statistical_significance": False,
            "whole_slam_superiority": False,
        },
    }


class FormalPromotionAuditTests(unittest.TestCase):
    def test_live_hard_pinned_adoption_gate_is_sanitized(self) -> None:
        gate = audit._validate_formal900_adoption()
        self.assertTrue(gate["r3_pass_gate_validated"])
        self.assertFalse(gate["r3_outcomes_exposed_to_formal_builder"])
        self.assertEqual(
            gate["authorized_namespace_root"],
            str(audit.ARTIFACT_NAMESPACE_ROOT),
        )
        self.assertEqual(
            set(gate),
            {
                "identity", "authorized_namespace_root", "locked_inputs",
                "static_projection", "normalized_manifest_static_contracts",
                "normalized_producer_commands", "raw_outcome_marker_schemas",
                "probe_common_schedule_prefix", "infrastructure_incident",
                "source_probe_identities", "r3_pass_gate_validated",
                "r3_outcomes_exposed_to_formal_builder",
            },
        )
        self.assertNotIn("gates", gate)
        self.assertNotIn("seal", gate)

    def test_permit_and_human_record_are_held_through_semantics(self) -> None:
        for target_name in ("permit", "human"):
            with self.subTest(target_name=target_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                permit = root / "permit.json"
                human = root / "record.md"
                permit.write_bytes(audit._canonical_bytes({}))
                human.write_bytes(b"record\n")
                permit.chmod(0o444)
                human.chmod(0o444)
                identity = _identity(permit)

                def replace_while_held(*_args, **_kwargs):
                    target = permit if target_name == "permit" else human
                    target.unlink()
                    target.write_bytes(
                        audit._canonical_bytes({})
                        if target_name == "permit" else b"record\n"
                    )
                    target.chmod(0o444)
                    return {}

                with mock.patch.object(
                    audit, "FORMAL900_ADOPTION_PATH", permit
                ), mock.patch.object(
                    audit, "FORMAL900_ADOPTION_HUMAN_RECORD_PATH", human
                ), mock.patch.object(
                    audit, "_validate_formal900_adoption_semantic",
                    side_effect=replace_while_held,
                ), self.assertRaisesRegex(
                    audit.AuditFailure, "held single-link|drifted"
                ):
                    audit._validate_formal900_adoption(expected_identity=identity)

    def test_held_active_evidence_rejects_unlink_and_same_byte_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "formal"
            snapshot, paths = _synthetic_held_tree(root)
            evidence = paths["xfeat_r3/export_manifest.json"]
            original = evidence.read_bytes()
            try:
                evidence.unlink()
                evidence.write_bytes(original)
                evidence.chmod(0o444)
                with self.assertRaisesRegex(
                    audit.AuditFailure, "held single-link|final inventory|visible inode"
                ):
                    audit._finish_held_tree_snapshot(snapshot)
            finally:
                audit._close_held_tree_snapshot(snapshot)

    def test_held_locked_input_rejects_unlink_and_same_byte_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "locked-input.bag"
            original = b"locked bytes\n"
            path.write_bytes(original)
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                observed = os.fstat(descriptor)
                identity = (int(observed.st_dev), int(observed.st_ino))
                path.unlink()
                path.write_bytes(original)
                os.lseek(descriptor, 0, os.SEEK_SET)
                with self.assertRaisesRegex(audit.AuditFailure, "held single-link"):
                    audit._read_regular_descriptor_bytes(
                        descriptor,
                        expected_identity=identity,
                        label="held locked input",
                    )
            finally:
                os.close(descriptor)

    def test_held_active_directory_rejects_remove_and_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "formal"
            snapshot, paths = _synthetic_held_tree(root)
            private = paths["gftt_r3/private_work"]
            try:
                private.rmdir()
                private.mkdir(mode=0o700)
                private.chmod(0o700)
                with self.assertRaisesRegex(
                    audit.AuditFailure, "final inventory|visible inode"
                ):
                    audit._finish_held_tree_snapshot(snapshot)
            finally:
                audit._close_held_tree_snapshot(snapshot)

    def test_active_formal_snapshot_has_exact_independent_keysets_for_both_actions(
        self,
    ) -> None:
        for action in ("check-start", "audit"):
            with self.subTest(action=action), tempfile.TemporaryDirectory(
                dir=str(audit.WORKSPACE_ROOT)
            ) as temporary:
                root, output, values = _synthetic_active_formal_tree(
                    Path(temporary), action=action
                )
                snapshot = None
                with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root):
                    reserved = audit._open_reserved_output(output)
                    descriptor, parent_descriptor = reserved[:2]
                    try:
                        snapshot = audit._held_active_formal_snapshot(
                            action=action,
                            output=output,
                            output_descriptor=descriptor,
                            output_identity=reserved[2],
                            output_parent_descriptor=parent_descriptor,
                            **values,
                        )
                        expected_directories = {
                            root,
                            root / "xfeat_r4",
                            root / "gftt_r4",
                        }
                        expected_files = {
                            values["freeze_json"],
                            values["source_bag"],
                            values["raw_bag"],
                            values["camera_yaml"],
                            root / "xfeat_r4/command_contract.json",
                            root / "gftt_r4/command_contract.json",
                        }
                        if action == "audit":
                            expected_directories.update(
                                {
                                    root / "xfeat_r4/private_work",
                                    root / "gftt_r4/private_work",
                                }
                            )
                            expected_files.add(values["pre_run_start_receipt"])
                            expected_files.update(
                                root / arm / name
                                for arm in ("xfeat_r4", "gftt_r4")
                                for name in (
                                    "producer_attempt.json",
                                    "launcher_start_receipt.json",
                                    "launcher_rc_receipt.json",
                                    "export_manifest.json",
                                    "features.bag",
                                    "raw_diagnostics.csv",
                                    "legacy_primitive_manifest.json",
                                )
                            )
                        self.assertEqual(
                            set(snapshot["directory_records"]),
                            expected_directories,
                        )
                        self.assertEqual(
                            set(snapshot["file_records"]), expected_files
                        )
                        self.assertEqual(
                            set(snapshot["required_file_paths"]), expected_files
                        )
                        self.assertEqual(
                            len(snapshot["directory_records"]),
                            3 if action == "check-start" else 5,
                        )
                        self.assertEqual(
                            len(snapshot["file_records"]),
                            6 if action == "check-start" else 21,
                        )
                        audit._finish_held_active_formal_snapshot(snapshot)
                    finally:
                        if snapshot is not None:
                            audit._close_held_active_formal_snapshot(snapshot)
                        os.close(descriptor)
                        os.close(parent_descriptor)

    def test_active_formal_expected_path_miss_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=str(audit.WORKSPACE_ROOT)
        ) as temporary:
            root, output, values = _synthetic_active_formal_tree(
                Path(temporary), action="check-start"
            )
            snapshot = None
            with mock.patch.object(audit, "ARTIFACT_NAMESPACE_ROOT", root):
                reserved = audit._open_reserved_output(output)
                descriptor, parent_descriptor = reserved[:2]
                try:
                    snapshot = audit._held_active_formal_snapshot(
                        action="check-start",
                        output=output,
                        output_descriptor=descriptor,
                        output_identity=reserved[2],
                        output_parent_descriptor=parent_descriptor,
                        **values,
                    )
                    freeze = values["freeze_json"]
                    record = snapshot["file_records"].pop(freeze)
                    try:
                        with mock.patch.object(
                            audit, "_ACTIVE_FORMAL_SNAPSHOT", snapshot
                        ), self.assertRaisesRegex(
                            audit.AuditFailure,
                            "required held active file is absent",
                        ):
                            audit._held_active_identity_or_none(freeze)
                    finally:
                        snapshot["file_records"][freeze] = record
                    audit._finish_held_active_formal_snapshot(snapshot)
                finally:
                    if snapshot is not None:
                        audit._close_held_active_formal_snapshot(snapshot)
                    os.close(descriptor)
                    os.close(parent_descriptor)

    def test_live_r3_held_fd_gate_returns_sanitized_projection(self) -> None:
        payload = _adoption_payload()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adoption.json"
            path.write_bytes(audit._canonical_bytes(payload))
            path.chmod(0o444)
            identity = _identity(path)
            payload["builder_execution_contract"] = {
                "working_directory": str(audit.WORKSPACE_ROOT),
                "environment": dict(adoption_builder.launcher.FROZEN_ENVIRONMENT),
                "authorized_write_once_argv": [
                    "/usr/bin/python3.8", "-B", "-m",
                    "scripts.build_matched_birth_r3_pass_formal900_adoption_v1",
                    "--action", "write-once", "--output", str(path),
                ],
                "runtime": {},
                "runtime_sha256": core._canonical_sha256({}),
            }
            path.chmod(0o644)
            path.write_bytes(audit._canonical_bytes(payload))
            path.chmod(0o444)
            identity = _identity(path)
            with mock.patch.object(
                audit, "FORMAL900_ADOPTION_PATH", path
            ), mock.patch.object(audit, "_audit_runtime_observation", return_value={}):
                gate = audit._validate_formal900_adoption(
                    expected_identity=identity
                )
        self.assertTrue(gate["r3_pass_gate_validated"])
        self.assertFalse(gate["r3_outcomes_exposed_to_formal_builder"])
        self.assertNotIn("gates", gate)
        self.assertNotIn("seal", gate)
        self.assertEqual(len(audit.R3_PASS_GATE_KEYS), 12)

    def test_formal_mode_gate_rejects_probe_before_reconstruction(self) -> None:
        gate = {
            "locked_inputs": {"x": 1},
            "authorized_namespace_root": str(audit.ARTIFACT_NAMESPACE_ROOT),
        }
        with self.assertRaisesRegex(audit.AuditFailure, "exactly formal900"):
            audit._validate_formal900_mode_and_inputs(
                adoption_gate=gate,
                allow_prefix=True,
                expected_frames=16,
                locked_inputs={"x": 1},
            )

    def test_static_projection_rejects_common_contract_drift(self) -> None:
        root = audit.PROMOTED_R3_ROOT
        freeze = json.loads((root / "probe16_freeze.json").read_bytes())
        contracts = {
            arm_id: json.loads(
                (root / arm_name / "command_contract.json").read_bytes()
            )
            for arm_id, arm_name in audit.R3_ARM_DIRECTORIES.items()
        }
        expected = audit._static_scientific_projection(
            freeze, command_contracts=contracts
        )
        changed = copy.deepcopy(freeze)
        changed["expected_common_contract"]["carrier"]["feature_cap"] += 1
        changed["expected_common_contract_sha256"] = core._canonical_sha256(
            changed["expected_common_contract"]
        )
        observed = audit._static_scientific_projection(
            changed, command_contracts=contracts
        )
        self.assertNotEqual(expected, observed)

    def test_normalized_full_template_rejects_static_and_marker_minimum_drift(self) -> None:
        root = audit.PROMOTED_R3_ROOT
        freeze = json.loads((root / "probe16_freeze.json").read_bytes())
        arm_id = audit.XFEAT_ARM
        template = freeze["arms"][arm_id]["manifest_template"]
        expected = audit._normalized_manifest_static_contract(
            template, arm_id=arm_id
        )
        for label, mutate in (
            (
                "policy",
                lambda value: value["pair_difference_policy"].__setitem__(
                    "posthoc_candidate_or_observation_dose_matching_forbidden",
                    False,
                ),
            ),
            (
                "marker-minimum",
                lambda value: value["metrics"]["observations"][
                    audit.TEMPLATE_MARKER_KEY
                ].__setitem__("minimum", -1),
            ),
            (
                "fixed-per-frame-maximum",
                lambda value: value["metrics"]["observations_per_frame_max"][
                    audit.TEMPLATE_MARKER_KEY
                ].__setitem__("maximum", 349),
            ),
        ):
            with self.subTest(label=label):
                changed = copy.deepcopy(template)
                mutate(changed)
                self.assertNotEqual(
                    expected,
                    audit._normalized_manifest_static_contract(
                        changed, arm_id=arm_id
                    ),
                )
        scalable = copy.deepcopy(template)
        scalable["metrics"]["observations"][audit.TEMPLATE_MARKER_KEY][
            "maximum"
        ] += 1
        self.assertEqual(
            expected,
            audit._normalized_manifest_static_contract(
                scalable, arm_id=arm_id
            ),
        )

    def test_manifest_attempt_prefix_is_only_a_typed_schedule_delta(self) -> None:
        root = audit.PROMOTED_R3_ROOT
        arm_id = audit.XFEAT_ARM
        template = json.loads((root / "probe16_freeze.json").read_bytes())[
            "arms"
        ][arm_id]["manifest_template"]
        expected = audit._normalized_manifest_static_contract(
            template, arm_id=arm_id
        )
        formal = copy.deepcopy(template)
        formal["attempt"]["payload"]["prefix_nonformal"] = False
        self.assertEqual(
            expected,
            audit._normalized_manifest_static_contract(formal, arm_id=arm_id),
        )
        malformed = copy.deepcopy(template)
        malformed["attempt"]["payload"]["prefix_nonformal"] = 1
        with self.assertRaisesRegex(audit.AuditFailure, "prefix flag malformed"):
            audit._normalized_manifest_static_contract(
                malformed, arm_id=arm_id
            )

    def test_raw_outcome_marker_schema_rejects_binding_type_and_max_drift(self) -> None:
        root = audit.PROMOTED_R3_ROOT
        arm_id = audit.XFEAT_ARM
        template = json.loads((root / "probe16_freeze.json").read_bytes())[
            "arms"
        ][arm_id]["manifest_template"]
        expected = audit._raw_outcome_marker_schema(template, arm_id=arm_id)
        for key, value in (
            ("binding", "wrong_binding"),
            ("type", "float"),
            ("maximum", 349),
        ):
            changed = copy.deepcopy(template)
            changed["raw_frame_diagnostics"][17]["births"][
                audit.TEMPLATE_MARKER_KEY
            ][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                audit.AuditFailure, "raw outcome marker row 17"
            ):
                audit._raw_outcome_marker_schema(changed, arm_id=arm_id)
        self.assertEqual(
            expected["births"][audit.TEMPLATE_MARKER_KEY]["maximum"], 350
        )

    def test_main_rejects_unlink_and_recreate_of_held_output_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
            argv = _main_audit_arguments(root, output)
            foreign = b"foreign replacement must remain untouched\n"
            original_identity: tuple[int, int] | None = None

            def replace_reserved_name(**_kwargs):
                nonlocal original_identity
                observed = os.lstat(output)
                original_identity = (int(observed.st_dev), int(observed.st_ino))
                output.unlink()
                output.write_bytes(foreign)
                output.chmod(0o444)
                replacement = os.lstat(output)
                self.assertNotEqual(
                    original_identity,
                    (int(replacement.st_dev), int(replacement.st_ino)),
                )
                return {"schema_version": "test", "status": "PASS", "pass": True}

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(
                audit, "ARTIFACT_NAMESPACE_ROOT", root
            ), mock.patch.object(
                audit, "audit_pair", side_effect=replace_reserved_name
            ), mock.patch.object(
                audit, "_held_active_formal_snapshot", return_value={}
            ), mock.patch.object(
                audit, "_finish_held_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_late_validate_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_close_held_active_formal_snapshot"
            ), mock.patch.object(audit.sys, "stdout", stdout), mock.patch.object(
                audit.sys, "stderr", stderr
            ):
                rc = audit.main(argv)

            self.assertEqual(rc, 2)
            self.assertIsNotNone(original_identity)
            self.assertEqual(output.read_bytes(), foreign)
            self.assertIn("AUDIT_RECEIPT_WRITE_ERROR", stderr.getvalue())

    def test_main_fails_closed_when_parent_directory_fsync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
            argv = _main_audit_arguments(root, output)
            result = {"schema_version": "test", "status": "PASS", "pass": True}
            real_fsync = audit.os.fsync
            directory_fsync_attempts = 0

            def fail_directory_fsync(descriptor: int) -> None:
                nonlocal directory_fsync_attempts
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    directory_fsync_attempts += 1
                    raise OSError("forced parent directory fsync failure")
                real_fsync(descriptor)

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(
                audit, "ARTIFACT_NAMESPACE_ROOT", root
            ), mock.patch.object(
                audit, "audit_pair", return_value=result
            ), mock.patch.object(
                audit, "_held_active_formal_snapshot", return_value={}
            ), mock.patch.object(
                audit, "_finish_held_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_late_validate_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_close_held_active_formal_snapshot"
            ), mock.patch.object(
                audit.os, "fsync", side_effect=fail_directory_fsync
            ), mock.patch.object(audit.sys, "stdout", stdout), mock.patch.object(
                audit.sys, "stderr", stderr
            ):
                rc = audit.main(argv)

            self.assertEqual(rc, 2)
            self.assertGreaterEqual(directory_fsync_attempts, 1)
            self.assertTrue(os.path.lexists(output))
            published = output.read_bytes()
            if published:
                self.assertNotEqual(json.loads(published).get("status"), "PASS")
            self.assertIn("forced parent directory fsync failure", stderr.getvalue())

    def test_main_rejects_same_name_replacement_after_final_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
            argv = _main_audit_arguments(root, output)
            result = {"schema_version": "test", "status": "PASS", "pass": True}
            foreign = b"foreign replacement after final parent fsync\n"
            real_fsync = audit.os.fsync
            directory_fsync_attempts = 0
            replacement_injected = False
            original_identity: tuple[int, int] | None = None

            def replace_after_final_directory_fsync(descriptor: int) -> None:
                nonlocal directory_fsync_attempts
                nonlocal replacement_injected
                nonlocal original_identity
                real_fsync(descriptor)
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    directory_fsync_attempts += 1
                    # Reservation, first publication verification, then the
                    # final verification immediately before a PASS return.
                    if directory_fsync_attempts == 3:
                        observed = os.lstat(output)
                        original_identity = (
                            int(observed.st_dev),
                            int(observed.st_ino),
                        )
                        output.unlink()
                        output.write_bytes(foreign)
                        output.chmod(0o444)
                        replacement_injected = True

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(
                audit, "ARTIFACT_NAMESPACE_ROOT", root
            ), mock.patch.object(
                audit, "audit_pair", return_value=result
            ), mock.patch.object(
                audit, "_held_active_formal_snapshot", return_value={}
            ), mock.patch.object(
                audit, "_finish_held_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_late_validate_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_close_held_active_formal_snapshot"
            ), mock.patch.object(
                audit.os, "fsync", side_effect=replace_after_final_directory_fsync
            ), mock.patch.object(audit.sys, "stdout", stdout), mock.patch.object(
                audit.sys, "stderr", stderr
            ):
                rc = audit.main(argv)

            self.assertTrue(replacement_injected)
            self.assertEqual(directory_fsync_attempts, 3)
            self.assertIsNotNone(original_identity)
            visible = os.lstat(output)
            self.assertNotEqual(
                original_identity,
                (int(visible.st_dev), int(visible.st_ino)),
            )
            self.assertEqual(output.read_bytes(), foreign)
            self.assertEqual(rc, 2)
            self.assertNotIn('"status":"PASS"', stdout.getvalue())

    def test_main_close_error_preserves_decided_status_and_attempts_both_fds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
            argv = _main_audit_arguments(root, output)
            result = {"schema_version": "test", "status": "PASS", "pass": True}
            real_open_reserved_output = audit._open_reserved_output
            real_close = audit.os.close
            reserved_descriptors: dict[str, int] = {}
            close_attempts: list[int] = []
            close_failure_injected = False

            def capture_reserved_descriptors(path: Path):
                reserved = real_open_reserved_output(path)
                reserved_descriptors["output"] = reserved[0]
                reserved_descriptors["parent"] = reserved[1]
                return reserved

            def fail_after_closing_output_descriptor(descriptor: int) -> None:
                nonlocal close_failure_injected
                close_attempts.append(descriptor)
                if (
                    descriptor == reserved_descriptors.get("output")
                    and not close_failure_injected
                ):
                    close_failure_injected = True
                    real_close(descriptor)
                    raise OSError("forced output descriptor close failure")
                real_close(descriptor)

            stdout, stderr = io.StringIO(), io.StringIO()
            uncaught: BaseException | None = None
            rc: int | None = None
            try:
                with mock.patch.object(
                    audit, "ARTIFACT_NAMESPACE_ROOT", root
                ), mock.patch.object(
                    audit, "audit_pair", return_value=result
                ), mock.patch.object(
                    audit, "_held_active_formal_snapshot", return_value={}
                ), mock.patch.object(
                    audit, "_finish_held_active_formal_snapshot"
                ), mock.patch.object(
                    audit, "_late_validate_active_formal_snapshot"
                ), mock.patch.object(
                    audit, "_close_held_active_formal_snapshot"
                ), mock.patch.object(
                    audit,
                    "_open_reserved_output",
                    side_effect=capture_reserved_descriptors,
                ), mock.patch.object(
                    audit.os, "close", side_effect=fail_after_closing_output_descriptor
                ), mock.patch.object(
                    audit.sys, "stdout", stdout
                ), mock.patch.object(audit.sys, "stderr", stderr):
                    try:
                        rc = audit.main(argv)
                    except BaseException as exc:  # asserted below
                        uncaught = exc
            finally:
                # Keep this regression test leak-free even against the broken
                # implementation that abandons the parent after the first
                # close raises.
                parent_descriptor = reserved_descriptors.get("parent")
                if parent_descriptor is not None:
                    try:
                        os.fstat(parent_descriptor)
                    except OSError:
                        pass
                    else:
                        real_close(parent_descriptor)

            self.assertTrue(close_failure_injected)
            self.assertIsNone(uncaught)
            self.assertEqual(rc, 0)
            self.assertIn(reserved_descriptors["output"], close_attempts)
            self.assertIn(reserved_descriptors["parent"], close_attempts)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                {"output": str(output), "status": "PASS"},
            )
            for descriptor in reserved_descriptors.values():
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_main_fails_closed_on_held_output_readback_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
            argv = _main_audit_arguments(root, output)
            result = {"schema_version": "test", "status": "PASS", "pass": True}
            real_readback = audit._read_regular_descriptor_bytes
            injected = False

            def corrupt_first_held_readback(
                descriptor: int, *, expected_identity: tuple[int, int], label: str
            ):
                nonlocal injected
                encoded, observed = real_readback(
                    descriptor,
                    expected_identity=expected_identity,
                    label=label,
                )
                if not injected and label == "final held audit output":
                    injected = True
                    return encoded + b"corrupt", observed
                return encoded, observed

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(
                audit, "ARTIFACT_NAMESPACE_ROOT", root
            ), mock.patch.object(
                audit, "audit_pair", return_value=result
            ), mock.patch.object(
                audit, "_held_active_formal_snapshot", return_value={}
            ), mock.patch.object(
                audit, "_finish_held_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_late_validate_active_formal_snapshot"
            ), mock.patch.object(
                audit, "_close_held_active_formal_snapshot"
            ), mock.patch.object(
                audit,
                "_read_regular_descriptor_bytes",
                side_effect=corrupt_first_held_readback,
            ), mock.patch.object(audit.sys, "stdout", stdout), mock.patch.object(
                audit.sys, "stderr", stderr
            ):
                rc = audit.main(argv)

            self.assertTrue(injected)
            self.assertEqual(rc, 2)
            receipt = json.loads(output.read_bytes())
            self.assertEqual(receipt["status"], "ERROR")
            self.assertEqual(receipt["error"]["type"], "AuditFailure")
            self.assertIn("held audit output", receipt["error"]["message"])

    def test_normalized_command_allows_only_terminal_limit_removal_and_paths(self) -> None:
        root = audit.PROMOTED_R3_ROOT
        arm_id = audit.XFEAT_ARM
        command = json.loads(
            (
                root
                / audit.R3_ARM_DIRECTORIES[arm_id]
                / "command_contract.json"
            ).read_bytes()
        )
        expected = audit._normalized_producer_command(
            command, arm_id=arm_id, source_probe=True
        )
        changed = copy.deepcopy(command)
        changed["argv"][-4] = "--changed-attempt-option"
        self.assertNotEqual(
            expected,
            audit._normalized_producer_command(
                changed, arm_id=arm_id, source_probe=True
            ),
        )
        wrong_suffix = copy.deepcopy(command)
        wrong_suffix["argv"][-1] = "17"
        with self.assertRaisesRegex(audit.AuditFailure, "terminal limit suffix"):
            audit._normalized_producer_command(
                wrong_suffix, arm_id=arm_id, source_probe=True
            )
        for label, mutate in (
            (
                "fixed-option-value",
                lambda value: value["argv"].__setitem__(13, "/wrong/topic"),
            ),
            (
                "environment",
                lambda value: value["environment"].__setitem__(
                    "PYTHONHASHSEED", "1"
                ),
            ),
            (
                "working-directory",
                lambda value: value.__setitem__(
                    "working_directory", "/home/ma"
                ),
            ),
        ):
            changed = copy.deepcopy(command)
            mutate(changed)
            with self.subTest(label=label):
                self.assertNotEqual(
                    expected,
                    audit._normalized_producer_command(
                        changed, arm_id=arm_id, source_probe=True
                    ),
                )


if __name__ == "__main__":
    unittest.main()
