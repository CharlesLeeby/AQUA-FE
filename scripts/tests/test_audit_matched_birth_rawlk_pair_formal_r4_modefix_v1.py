#!/usr/bin/env python3

from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from scripts import audit_matched_birth_rawlk_pair_formal_r4_modefix_v1 as audit
from scripts import build_matched_birth_formal900_r4_mode_false_negative_adoption_v1 as builder


def _identity(path: Path) -> dict[str, object]:
    encoded = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _args() -> object:
    frozen = json.loads(
        (audit.R4_ROOT / "formal900_freeze.json").read_text()
    )["authoritative_commands"]["post_run_audit"]["argv"]
    values = list(frozen[4:]) + [
        "--continuation-adoption-json", str(audit.CONTINUATION_PATH),
        "--continuation-seal-json", str(audit.CONTINUATION_SEAL_PATH),
    ]
    return audit.build_parser().parse_args(values)


def _authorization_payload(args: object) -> dict[str, object]:
    builder_identity = _identity(audit.ADOPTION_BUILDER_PATH)
    corrected = audit._corrected_auditor_identity()
    authorization = {
        "adoption_record": {
            "path": str(audit.CONTINUATION_PATH),
            "schema_version": audit.ADOPTION_SCHEMA_VERSION,
            "builder_identity": builder_identity,
        },
        "corrected_auditor": corrected,
        "old_error_seal": {
            "path": str(audit.OLD_ERROR_SEAL_PATH),
            "size_bytes": audit.OLD_ERROR_SEAL_SIZE,
            "sha256": audit.OLD_ERROR_SEAL_SHA256,
        },
        "continuation_seal": {
            "path": str(audit.CONTINUATION_SEAL_PATH),
            "required_pre_run_state": "ABSENT",
            "publication_mode_octal": "0444",
            "write_once_no_clobber": True,
        },
        "authorized_argv": audit._authorized_argv(args),
        "environment": dict(audit.sealed_launcher.FROZEN_ENVIRONMENT),
        "working_directory": str(audit.WORKSPACE_ROOT),
        "authorized_invocation_count": 1,
        "detector_or_producer_rerun_authorized": False,
        "r4_chmod_authorized": False,
        "old_error_seal_replacement_authorized": False,
        "other_scientific_or_governance_change_authorized": False,
        "vins_authorized_before_corrected_pass": False,
        "vins_authorization_on_corrected_error_or_fail": False,
        "vins_authorization_on_corrected_strict_pass": True,
    }
    return {
        "schema_version": audit.ADOPTION_SCHEMA_VERSION,
        "status": "ADOPTED_CONSUMED_R4_FOR_ONE_MODE_CORRECTED_AUDIT_ONLY",
        "scientific_role": "POST_RESULT_INFRASTRUCTURE_RECOVERY_NO_RESULT_SELECTION",
        "builder_identity": builder_identity,
        "builder_execution_contract": {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": dict(audit.sealed_launcher.FROZEN_ENVIRONMENT),
            "authorized_write_once_argv": [],
            "producer_started": False,
            "auditor_started": False,
            "vins_started": False,
            "evidence_held_and_rechecked_through_write_once": True,
        },
        "human_record": {},
        "incident": {
            "classification": "AUDITOR_ROLE_MODE_FALSE_NEGATIVE",
            "old_error_seal": {**authorization["old_error_seal"], "mode_octal": "0444"},
            "namespace_consumed_no_retry": True,
            "scientific_pair_pass_not_yet_established": True,
            "scientific_pair_fail_not_established": True,
        },
        "source_namespace": {},
        "execution_qualification": {},
        "mode_false_negative_qualification": {
            "frozen_auditor_uniform_governed_regular_mode_octal": "0444",
            "failed_role": "producer_result_regular_file",
            "failed_path": str(audit.R4_ROOT / "xfeat_r4/export_manifest.json"),
            "observed_and_correct_result_role_mode_octal": "0664",
            "scientific_result_validation_reached_by_old_auditor": False,
        },
        "continuation_authorization": authorization,
        "outcome_firewall": {
            "result_files_read_only_for_integrity_and_schedule_qualification": True,
            "result_values_exposed_in_permit": False,
            "relative_arm_comparison_exposed_in_permit": False,
            "result_dependent_continuation_configuration": False,
            "only_inventory_governance_and_mode_correction_exposed": True,
        },
        "claim_boundary": {
            "confirmatory": False,
            "statistical_significance": False,
            "whole_slam_superiority": False,
            "current_pair_contract_pass": False,
            "current_pair_contract_fail": False,
            "corrected_strict_pass_required_before_vins": True,
        },
    }


class CorrectedFormalR4AuditTests(unittest.TestCase):
    def test_schema_keysets_are_exact_builder_canonical_sets(self) -> None:
        args = _args()
        payload = _authorization_payload(args)
        self.assertEqual(set(payload), set(builder.RECORD_KEYS))
        self.assertEqual(
            set(payload["continuation_authorization"]),
            set(builder.CONTINUATION_AUTHORIZATION_KEYS),
        )
        self.assertEqual(
            set(payload["continuation_authorization"]["adoption_record"]),
            set(builder.ADOPTION_RECORD_KEYS),
        )
        self.assertEqual(
            set(payload["continuation_authorization"]["continuation_seal"]),
            set(builder.CONTINUATION_SEAL_KEYS),
        )

    def test_authorized_argv_keeps_old_output_and_appends_only_continuation(self) -> None:
        args = _args()
        actual = audit._authorized_argv(args)
        frozen = json.loads(
            (audit.R4_ROOT / "formal900_freeze.json").read_text()
        )["authoritative_commands"]["post_run_audit"]["argv"]
        expected = list(frozen)
        expected[3] = "scripts.audit_matched_birth_rawlk_pair_formal_r4_modefix_v1"
        expected.extend(
            [
                "--continuation-adoption-json", str(audit.CONTINUATION_PATH),
                "--continuation-seal-json", str(audit.CONTINUATION_SEAL_PATH),
            ]
        )
        self.assertEqual(actual, expected)
        index = actual.index("--post-run-audit-json")
        self.assertEqual(actual[index + 1], str(audit.OLD_ERROR_SEAL_PATH))

    def test_mode_correction_is_only_role_mode_delta_and_outcome_blind(self) -> None:
        contract = audit._mode_correction_contract()
        self.assertEqual(
            contract["scope"], "active_r4_snapshot_regular_file_mode_predicate_only"
        )
        self.assertEqual(
            contract["corrected_role_modes"]["scientific_outputs"]["mode_octal"],
            "0664",
        )
        self.assertEqual(
            contract["corrected_role_modes"]["governance_arm_records"]["mode_octal"],
            "0444",
        )
        self.assertFalse(contract["producer_or_detector_rerun"])
        self.assertFalse(contract["outcome_dependent_configuration_or_branching"])
        source = Path(audit.__file__).read_text()
        self.assertNotIn('result["metrics"]', source)
        self.assertNotIn("get(\"metrics\")", source)

    def test_authorization_accepts_builder_shaped_payload_and_rejects_metric(self) -> None:
        args = _args()
        payload = _authorization_payload(args)
        held = {"payload": payload, "identity": {"path": "permit", "size_bytes": 1, "sha256": "0" * 64}}
        with mock.patch.dict(os.environ, audit.sealed_launcher.FROZEN_ENVIRONMENT, clear=True):
            gate = audit._validate_continuation_authorization(held, args=args)
        self.assertEqual(gate["builder_identity"], payload["builder_identity"])
        tampered = copy.deepcopy(payload)
        tampered["execution_qualification"]["metrics"] = {"winner": "xfeat"}
        held["payload"] = tampered
        with mock.patch.dict(os.environ, audit.sealed_launcher.FROZEN_ENVIRONMENT, clear=True):
            with self.assertRaises(audit.old.AuditFailure):
                audit._validate_continuation_authorization(held, args=args)

    def test_held_r4_snapshot_exact_modes_and_rejects_replacement(self) -> None:
        common = {
            "freeze_json": audit.R4_ROOT / "formal900_freeze.json",
            "source_bag": Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag"),
            "raw_bag": Path("/mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"),
            "camera_yaml": Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/aqualoc_archaeo02_pinhole.yaml"),
            "xfeat_bag": audit.R4_ROOT / "xfeat_r4/features.bag",
            "xfeat_manifest": audit.R4_ROOT / "xfeat_r4/export_manifest.json",
            "xfeat_diagnostics": audit.R4_ROOT / "xfeat_r4/raw_diagnostics.csv",
            "xfeat_legacy_manifest": audit.R4_ROOT / "xfeat_r4/legacy_primitive_manifest.json",
            "xfeat_work_directory": audit.R4_ROOT / "xfeat_r4/private_work",
            "xfeat_attempt": audit.R4_ROOT / "xfeat_r4/producer_attempt.json",
            "gftt_bag": audit.R4_ROOT / "gftt_r4/features.bag",
            "gftt_manifest": audit.R4_ROOT / "gftt_r4/export_manifest.json",
            "gftt_diagnostics": audit.R4_ROOT / "gftt_r4/raw_diagnostics.csv",
            "gftt_legacy_manifest": audit.R4_ROOT / "gftt_r4/legacy_primitive_manifest.json",
            "gftt_work_directory": audit.R4_ROOT / "gftt_r4/private_work",
            "gftt_attempt": audit.R4_ROOT / "gftt_r4/producer_attempt.json",
            "pre_run_start_receipt": audit.R4_ROOT / "formal900_pre_run_start_receipt.json",
            "old_error_seal": audit.OLD_ERROR_SEAL_PATH,
        }
        snapshot = audit._held_corrected_r4_snapshot(**common)
        try:
            self.assertEqual(len(snapshot["directory_records"]), 5)
            governed = [r for r in snapshot["file_records"].values() if r["governed"]]
            self.assertEqual(len(governed), 19)
            self.assertEqual(
                {r["expected_mode_octal"] for r in governed}, {"0444", "0664"}
            )
            with tempfile.TemporaryDirectory() as directory:
                foreign = Path(directory) / "foreign"
                foreign.write_bytes(b"replacement")
                target = audit.R4_ROOT / "xfeat_r4/export_manifest.json"
                with mock.patch.object(os, "lstat", side_effect=lambda path: os.stat(foreign) if Path(path) == target else os.stat(path)):
                    with self.assertRaises(audit.old.AuditFailure):
                        audit.old._finish_held_active_formal_snapshot(snapshot)
        finally:
            audit._close_corrected_snapshot(snapshot)

    def test_tampered_adoption_inventory_rejected(self) -> None:
        snapshot = {
            "directory_records": {},
            "file_records": {},
        }
        held = {"payload": {"source_namespace": {"exact_tree_inventory": []}}}
        with self.assertRaises((audit.old.AuditFailure, KeyError)):
            audit._validate_adoption_snapshot_binding(held, snapshot)

    def test_publisher_is_o_excl_0444_and_rejects_visible_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "seal.json"
            (
                descriptor,
                parent_descriptor,
                output_identity,
                parent_identity,
                initial_entries,
            ) = audit.old._open_reserved_output(output)
            try:
                encoded = audit.old._publish_reserved_output(
                    output=output,
                    descriptor=descriptor,
                    parent_descriptor=parent_descriptor,
                    output_identity=output_identity,
                    parent_identity=parent_identity,
                    initial_parent_entries=initial_entries,
                    payload={"pass": True, "status": "PASS"},
                )
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                self.assertEqual(output.read_bytes(), encoded)
                with self.assertRaises(FileExistsError):
                    audit.old._open_reserved_output(output)
                foreign = root / "foreign"
                foreign.write_bytes(b"foreign\n")
                os.replace(foreign, output)
                with self.assertRaises(audit.old.AuditFailure):
                    audit.old._verify_reserved_output(
                        output=output,
                        descriptor=descriptor,
                        parent_descriptor=parent_descriptor,
                        output_identity=output_identity,
                        parent_identity=parent_identity,
                        initial_parent_entries=initial_entries,
                        expected_bytes=encoded,
                    )
            finally:
                os.close(descriptor)
                os.close(parent_descriptor)

    def test_delegated_envelope_pass_fail_and_error_do_not_authorize_early_vins(self) -> None:
        base = {
            "schema_version": audit.old.SCHEMA_VERSION,
            "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
            "claim_boundary": {
                "detector_birth_source_only_within_this_frozen_carrier": True,
                "whole_slam_superiority": False,
                "confirmatory": False,
                "statistical_significance": False,
            },
        }
        snapshot = {"directory_records": {}, "file_records": {}}
        with mock.patch.object(audit, "_snapshot_inventory", return_value=[]):
            passed = audit._continuation_envelope(
                result={**base, "status": "PASS", "pass": True},
                old_auditor_identity={}, old_error_gate={},
                authorization_gate={}, snapshot=snapshot,
            )
            failed = audit._continuation_envelope(
                result={**base, "status": "FAIL", "pass": False},
                old_auditor_identity={}, old_error_gate={},
                authorization_gate={}, snapshot=snapshot,
            )
        self.assertTrue(
            passed["claim_boundary"]["vins_authorized_by_this_seal_only_after_contract_pass"]
        )
        self.assertFalse(
            failed["claim_boundary"]["vins_authorized_by_this_seal_only_after_contract_pass"]
        )
        with self.assertRaises(audit.old.AuditFailure):
            audit._continuation_envelope(
                result={**base, "status": "ERROR", "pass": False},
                old_auditor_identity={}, old_error_gate={},
                authorization_gate={}, snapshot=snapshot,
            )

    def test_old_error_identity_and_reason_are_exact(self) -> None:
        payload = audit.OLD_ERROR_SEAL_PATH.read_bytes()
        record = {
            "identity": {
                "path": str(audit.OLD_ERROR_SEAL_PATH),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            "payload": payload,
        }
        gate = audit._old_error_gate(
            {"file_records": {audit.OLD_ERROR_SEAL_PATH: record}}
        )
        self.assertEqual(gate["payload"], audit._expected_old_error_payload())
        corrupted = copy.deepcopy(record)
        corrupted["payload"] = payload + b"x"
        with self.assertRaises(audit.old.AuditFailure):
            audit._old_error_gate(
                {"file_records": {audit.OLD_ERROR_SEAL_PATH: corrupted}}
            )

    def test_builder_source_held_identity_rejects_same_name_replacement(self) -> None:
        claim = _identity(audit.ADOPTION_BUILDER_PATH)
        held = audit._open_held_builder_source(claim)
        try:
            with tempfile.TemporaryDirectory() as directory:
                foreign = Path(directory) / "builder.py"
                foreign.write_bytes(held["bytes"])
                with mock.patch.object(
                    os,
                    "lstat",
                    side_effect=lambda path: (
                        os.stat(foreign)
                        if Path(path) == audit.ADOPTION_BUILDER_PATH
                        else os.stat(path)
                    ),
                ):
                    with self.assertRaises(audit.old.AuditFailure):
                        audit._finish_held_builder_source(held)
        finally:
            audit._close_held_builder_source(held)

    def test_main_delegates_exact_old_pair_and_publishes_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.write_bytes(b"fixture\n")
            work = root / "work"
            work.mkdir()
            adoption = root / "adoption.json"
            adoption.write_bytes(b"{}")
            old_error = root / "old-error.json"
            old_error.write_bytes(b"{}")
            output = root / "fresh-seal.json"
            argv = [
                "--action", "audit",
                "--source-feature-bag", str(evidence),
                "--raw-image-bag", str(evidence),
                "--camera-yaml", str(evidence),
                "--freeze-json", str(evidence),
                "--xfeat-bag", str(evidence),
                "--xfeat-manifest", str(evidence),
                "--xfeat-diagnostics", str(evidence),
                "--xfeat-legacy-manifest", str(evidence),
                "--xfeat-work-directory", str(work),
                "--xfeat-attempt", str(evidence),
                "--gftt-bag", str(evidence),
                "--gftt-manifest", str(evidence),
                "--gftt-diagnostics", str(evidence),
                "--gftt-legacy-manifest", str(evidence),
                "--gftt-work-directory", str(work),
                "--gftt-attempt", str(evidence),
                "--image-topic", "/camera/image_raw",
                "--expected-published-frames", "900",
                "--pre-run-start-receipt", str(evidence),
                "--post-run-audit-json", str(old_error),
                "--continuation-adoption-json", str(adoption),
                "--continuation-seal-json", str(output),
            ]
            snapshot = {"action": "audit"}
            source_hold = {"identity": {}, "required_mode": 0o664}
            authorization_hold = {
                "payload": {"continuation_authorization": {"corrected_auditor": {}}}
            }
            delegated = {
                "status": "PASS", "pass": True,
                "claim_boundary": {
                    "detector_birth_source_only_within_this_frozen_carrier": True,
                    "whole_slam_superiority": False,
                    "confirmatory": False,
                    "statistical_significance": False,
                },
            }
            envelope = {"status": "PASS", "pass": True}
            with contextlib.ExitStack() as stack:
                for target, value in (
                    ("OLD_ERROR_SEAL_PATH", old_error),
                    ("CONTINUATION_PATH", adoption),
                    ("CONTINUATION_SEAL_PATH", output),
                ):
                    stack.enter_context(mock.patch.object(audit, target, value))
                for target, value in (
                    ("_validate_old_auditor_identity", {}),
                    ("_open_held_source", source_hold),
                    ("_open_held_continuation", authorization_hold),
                    ("_open_held_self_source", source_hold),
                    ("_validate_continuation_authorization", {"builder_identity": {}}),
                    ("_open_held_builder_source", source_hold),
                    ("_held_corrected_r4_snapshot", snapshot),
                    ("_old_error_gate", {}),
                    ("_continuation_envelope", envelope),
                ):
                    stack.enter_context(mock.patch.object(audit, target, return_value=value))
                for target in (
                    "_validate_adoption_snapshot_binding", "_finish_held_continuation",
                    "_finish_held_builder_source", "_finish_held_self_source",
                    "_close_corrected_snapshot", "_close_held_continuation",
                    "_close_held_builder_source", "_close_held_self_source",
                    "_close_held_source", "_finish_held_source",
                ):
                    stack.enter_context(mock.patch.object(audit, target))
                stack.enter_context(mock.patch.object(audit.old, "_finish_held_active_formal_snapshot"))
                stack.enter_context(mock.patch.object(audit.old, "_late_validate_active_formal_snapshot"))
                stack.enter_context(mock.patch.object(audit.old, "_open_reserved_output", return_value=(101, 102, (1, 2), (1, 3), ())))
                pair = stack.enter_context(mock.patch.object(audit.old, "audit_pair", return_value=delegated))
                publish = stack.enter_context(mock.patch.object(audit.old, "_publish_reserved_output", return_value=b"seal"))
                stack.enter_context(mock.patch.object(audit.old, "_verify_reserved_output"))
                stack.enter_context(mock.patch.object(os, "close"))
                rc = audit.main(argv)
            self.assertEqual(rc, 0)
            self.assertEqual(pair.call_count, 1)
            self.assertEqual(pair.call_args.kwargs["post_run_pair_seal"], old_error)
            self.assertIs(pair.call_args.kwargs["held_snapshot"], snapshot)
            self.assertEqual(publish.call_count, 1)

    def test_main_old_audit_error_consumes_fresh_error_and_returns_two(self) -> None:
        # Exercise the terminal failure branch without touching the governed
        # namespaces: once a fresh descriptor is reserved, an old-audit error
        # is converted to an immutable ERROR envelope and can never authorize VINS.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing"
            existing.write_bytes(b"x")
            work = root / "work"
            work.mkdir()
            adoption = root / "adoption"
            adoption.write_bytes(b"{}")
            old_error = root / "old-error"
            old_error.write_bytes(b"{}")
            output = root / "output"
            argv = [
                "--source-feature-bag", str(existing), "--raw-image-bag", str(existing),
                "--camera-yaml", str(existing), "--freeze-json", str(existing),
                "--xfeat-bag", str(existing), "--xfeat-manifest", str(existing),
                "--xfeat-diagnostics", str(existing), "--xfeat-legacy-manifest", str(existing),
                "--xfeat-work-directory", str(work), "--xfeat-attempt", str(existing),
                "--gftt-bag", str(existing), "--gftt-manifest", str(existing),
                "--gftt-diagnostics", str(existing), "--gftt-legacy-manifest", str(existing),
                "--gftt-work-directory", str(work), "--gftt-attempt", str(existing),
                "--image-topic", "/camera/image_raw", "--expected-published-frames", "900",
                "--pre-run-start-receipt", str(existing), "--post-run-audit-json", str(old_error),
                "--continuation-adoption-json", str(adoption), "--continuation-seal-json", str(output),
            ]
            snapshot = {"action": "audit"}
            held = {"identity": {}, "required_mode": 0o664, "payload": {"continuation_authorization": {"corrected_auditor": {}}}}
            with contextlib.ExitStack() as stack:
                for target, value in (
                    ("OLD_ERROR_SEAL_PATH", old_error),
                    ("CONTINUATION_PATH", adoption),
                    ("CONTINUATION_SEAL_PATH", output),
                ):
                    stack.enter_context(mock.patch.object(audit, target, value))
                for target, value in (
                    ("_validate_old_auditor_identity", {}),
                    ("_open_held_source", held),
                    ("_open_held_continuation", held),
                    ("_open_held_self_source", held),
                    ("_validate_continuation_authorization", {"builder_identity": {}}),
                    ("_open_held_builder_source", held),
                    ("_held_corrected_r4_snapshot", snapshot),
                    ("_old_error_gate", {}),
                ):
                    stack.enter_context(mock.patch.object(audit, target, return_value=value))
                for target in (
                    "_validate_adoption_snapshot_binding", "_finish_held_continuation",
                    "_finish_held_builder_source", "_finish_held_self_source",
                    "_close_corrected_snapshot", "_close_held_continuation",
                    "_close_held_builder_source", "_close_held_self_source",
                    "_close_held_source", "_finish_held_source",
                ):
                    stack.enter_context(mock.patch.object(audit, target))
                stack.enter_context(mock.patch.object(audit.old, "_finish_held_active_formal_snapshot"))
                stack.enter_context(mock.patch.object(audit.old, "_open_reserved_output", return_value=(101, 102, (1, 2), (1, 3), ())))
                stack.enter_context(mock.patch.object(audit.old, "audit_pair", side_effect=audit.old.AuditFailure("scientific gate error")))
                publish = stack.enter_context(mock.patch.object(audit.old, "_publish_reserved_output", return_value=b"error"))
                stack.enter_context(mock.patch.object(os, "close"))
                rc = audit.main(argv)
            self.assertEqual(rc, 2)
            self.assertEqual(publish.call_count, 1)
            failure = publish.call_args.kwargs["payload"]
            self.assertEqual(failure["status"], "ERROR")
            self.assertFalse(failure["claim_boundary"]["detector_rerun_or_r4_mutation_authorized"])


if __name__ == "__main__":
    unittest.main()
