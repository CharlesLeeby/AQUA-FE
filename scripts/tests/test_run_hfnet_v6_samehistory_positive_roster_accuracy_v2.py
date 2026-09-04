#!/usr/bin/env python3
"""Fail-closed tests for the cache-adjudicated accuracy controller v2."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v2.py"
WATCHDOG = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py"
BUILDER = ROOT / "scripts/build_hfnet_v6_samehistory_positive_accuracy_supersession_v2.py"
ADJUDICATOR = ROOT / "scripts/adjudicate_hfnet_v6_samehistory_positive_roster_cache_contract_v1.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load(CONTROLLER, "_test_accuracy_controller_v2")
W = load(WATCHDOG, "_test_zero_kf_watchdog_producer_v1")
B = load(BUILDER, "_test_accuracy_supersession_builder_v2_for_controller")
A = load(ADJUDICATOR, "_test_cache_adjudicator_v1_for_accuracy_controller")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(C.canonical_json_bytes(value))


def snapshot(path: Path):
    return C.BASE.snapshot_file(path, f"fixture:{path.name}")[0]


def raw_receipt(case_id: str, trajectory_identity: dict, stdout_identity: dict) -> dict:
    return {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-result-v2",
        "status": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
        "case_id": case_id,
        "failure_codes": ["FROZEN_CONTRACT_DRIFT", "POST_AUDIT_INCOMPLETE"],
        "post_audit_errors": [
            "FROZEN_CONTRACT_POST_AUDIT:ContractError:DERIVED_FILE_DRIFT:local_cache"
        ],
        "execution": {
            "raw_returncode": 0,
            "timed_out": False,
            "termination": None,
            "supervisor_error": None,
            "child_reaped_before_post_audit": True,
            "popen_invocations": 1,
            "retry_performed": False,
            "retry_permitted": False,
        },
        "support": {
            "trajectory": {
                "identity": trajectory_identity,
                "valid": True,
                "coverage_fraction": 0.91,
                "longest_contiguous_fraction": 0.88,
            },
            "keyframes": {"valid": True, "pose_count": 7},
            "log": {
                "valid": True,
                "final_atlas_nonempty": True,
                "initialization_count": 1,
                "accepted_support_unresolved_reset_events": [],
                "accepted_support_reinitialization_frame_ids": [],
            },
        },
        "pins": {"stdout": stdout_identity},
        "terminal_contract": {
            "attempt_consumed": True,
            "claim_without_result_is_terminal_fail": True,
            "retry_after_pass_or_fail": False,
        },
    }


class BundleFixture:
    """A real watchdog producer receipt wrapped in synthetic immutable pins."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.case_id = C.REMAINING_CASES[0]
        self.case_spec = root / "case.json"
        self.prepared = root / "prepared.json"
        self.stdout = root / "headless.stdout.log"
        self.trajectory = root / "result/trajectory.txt"
        self.raw_path = root / "run_result.json"
        self.pre_path = root / "adjudication/case.prestart.json"
        self.adjud_path = root / "adjudication/case.runability_adjudication.json"
        self.watchdog_path = root / "watchdog/case.json"
        self.delta_path = root / "delta.json"
        self.binary = root / "hfnet_binary"
        for path, payload in (
            (self.case_spec, b"{}\n"),
            (self.prepared, b"{}\n"),
            (self.stdout, b"Shutdown\nEnd of saving trajectory.\n"),
            (self.trajectory, b"0 0 0 0 0 0 0 1\n"),
            (self.binary, b"fixture-binary\n"),
            (self.delta_path, b"{}\n"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.delta_snapshot = snapshot(self.delta_path)
        self.trajectory_snapshot = snapshot(self.trajectory)
        self.stdout_snapshot = snapshot(self.stdout)
        self.raw = raw_receipt(
            self.case_id,
            self.trajectory_snapshot.identity,
            self.stdout_snapshot.identity,
        )
        write_json(self.raw_path, self.raw)
        self.raw_snapshot = snapshot(self.raw_path)
        self.code = {
            "cache_contract_adjudicator": snapshot(C.CACHE_ADJUDICATOR),
            "cache_contract_governance_addendum": snapshot(C.CACHE_CONTRACT_ADDENDUM),
            "zero_kf_watchdog": snapshot(W.SUPERVISOR),
            "zero_kf_watchdog_protocol": snapshot(C.ZERO_KF_WATCHDOG_PROTOCOL),
            "v2_runner": snapshot(W.RUNNER),
            "v2_roster_pointer": snapshot(W.PUBLICATION_POINTER),
        }
        self.pre = {
            "schema_version": C.PRESTART_SCHEMA,
            "status": "FROZEN_PROSPECTIVE_CACHE_SEED_BOUNDARY_NOT_STARTED",
            "case_id": self.case_id,
            "validator": self.code["cache_contract_adjudicator"].identity,
            "governance_addendum": self.code[
                "cache_contract_governance_addendum"
            ].identity,
            "zero_kf_watchdog": self.code["zero_kf_watchdog"].identity,
            "zero_kf_watchdog_protocol": self.code[
                "zero_kf_watchdog_protocol"
            ].identity,
            "v2_runner": self.code["v2_runner"].identity,
            "accuracy_authority_supersession": self.delta_snapshot.identity,
        }
        write_json(self.pre_path, self.pre)
        self.pre_snapshot = snapshot(self.pre_path)
        contract = W.CaseContract(
            case_id=self.case_id,
            case_spec=self.case_spec,
            case_spec_identity=snapshot(self.case_spec).identity,
            prepared_manifest=self.prepared,
            prepared_manifest_identity=snapshot(self.prepared).identity,
            attempt_root=root,
            stdout_log=self.stdout,
            trajectory=self.trajectory,
            run_result=self.raw_path,
            receipt=self.watchdog_path,
            expected_hfnet_argv=(str(self.binary),),
            expected_hfnet_executable=str(self.binary),
            expected_hfnet_binary_identity=snapshot(self.binary).identity,
            authorization_token="fixture-not-serialized",
        )
        outcome = W.MonitorOutcome(
            runner_returncode=2,
            runner_reaped=True,
            child=None,
            child_discovered_at_utc=None,
            signature_first_observed_at_utc=None,
            signature_evidence=None,
            signal_attempted=False,
            sigterm_sent=False,
            sigterm_sent_at_utc=None,
            signal_delivery=None,
            post_signal_identity_state=None,
            runner_popen_invocations=1,
            monitoring_errors=[],
        )
        self.watchdog = W.build_receipt(
            contract,
            outcome,
            started_at_utc="2026-08-28T19:00:00+00:00",
            token_pipe_delivery_error=None,
            supervisor_pre=W.identity(W.SUPERVISOR),
        )
        self.row = {
            "case_id": self.case_id,
            "case_spec": snapshot(self.case_spec).identity,
            "prepared_manifest": snapshot(self.prepared).identity,
            "future_hfnet_outputs_observed_absent": {
                "terminal_runability_result": str(self.raw_path),
                "trajectory": str(self.trajectory),
            },
        }
        self.delta = {
            "cache_adjudication_contract": {
                "prestart_receipt_pattern": str(self.pre_path),
                "terminal_receipt_pattern": str(self.adjud_path),
                "raw_status_required_for_correction": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
                "raw_failure_code_set_required": [
                    "FROZEN_CONTRACT_DRIFT",
                    "POST_AUDIT_INCOMPLETE",
                ],
                "sole_post_audit_error_required": (
                    "FROZEN_CONTRACT_POST_AUDIT:ContractError:"
                    "DERIVED_FILE_DRIFT:local_cache"
                ),
            },
            "future_namespaces": {
                "zero_kf_watchdog_receipt_pattern": str(self.watchdog_path)
            },
        }
        self.publish_watchdog_and_adjudication()

    def publish_watchdog_and_adjudication(self) -> None:
        write_json(self.watchdog_path, self.watchdog)
        self.watchdog_snapshot = snapshot(self.watchdog_path)
        self.adjudication = {
            "schema_version": C.ADJUDICATION_SCHEMA,
            "status": "PASS",
            "role": C.ADJUDICATION_ROLE,
            "effective_runability_status": "PASS",
            "adjudication_status": C.ADJUDICATION_PASS,
            "case_id": self.case_id,
            "validator": self.code["cache_contract_adjudicator"].identity,
            "failure_codes": [],
            "support": self.raw["support"],
            "support_trajectory_identity": self.trajectory_snapshot.identity,
            "execution": self.raw["execution"],
            "accuracy_computed": False,
            "raw_runability_receipt": self.raw_snapshot.identity,
            "prestart_receipt": self.pre_snapshot.identity,
            "zero_kf_watchdog_receipt": self.watchdog_snapshot.identity,
            "cache_contract_delta_seal": self.code[
                "cache_contract_governance_addendum"
            ].identity,
            "accuracy_authority_supersession": self.delta_snapshot.identity,
            "terminal_contract": {
                "attempt_consumed": True,
                "retry_after_pass_or_fail": False,
                "replacement_adjudication_permitted": False,
            },
            "pins": {
                "validator": self.code["cache_contract_adjudicator"].identity,
                "governance_addendum": self.code[
                    "cache_contract_governance_addendum"
                ].identity,
                "accuracy_authority_supersession": self.delta_snapshot.identity,
                "v2_runner": self.code["v2_runner"].identity,
                "v2_run_result": self.raw_snapshot.identity,
            },
            "adjudicated_at_utc": "2026-08-28T19:01:00Z",
            "roster_global_lock": {
                "path": "/fixture/.gpu_serial.lock",
                "pid": 123,
                "acquired_at_utc": "2026-08-28T19:00:59Z",
            },
        }
        write_json(self.adjud_path, self.adjudication)
        self.adjud_snapshot = snapshot(self.adjud_path)

    def replay_result(self) -> dict:
        return {"zero_kf_watchdog_receipt": self.watchdog_snapshot.identity}


class AccuracyControllerTests(unittest.TestCase):
    def test_dry_delta_is_accepted_by_both_pinned_consumers(self) -> None:
        with B.global_serial_lock() as evidence, tempfile.TemporaryDirectory() as temporary:
            document = B.build_document(evidence)
            B.validate_document(document)
            path = Path(temporary) / "accuracy_supersession_v2.json"
            write_json(path, document)
            observed = snapshot(path)
            with mock.patch.object(C, "DEFAULT_DELTA_SEAL", path):
                code = C.validate_delta_seal(document, observed)
            self.assertEqual(
                code["cache_contract_adjudicator"].identity,
                C.CACHE_ADJUDICATOR_EXPECTED,
            )
            with mock.patch.object(A, "ACCURACY_SUPERSESSION", path):
                adopted = A.validate_accuracy_supersession(C.REMAINING_CASES[0])
            self.assertEqual(adopted.identity, observed.identity)

    def test_semantic_projection_ignores_only_controller_self(self) -> None:
        delta = {
            "analysis_code_identities": {
                "formal_accuracy_controller_v2": {"path": "/a", "size_bytes": 1, "sha256": "1" * 64}
            },
            "future_accuracy_controller_contract": {
                "active_controller": {"path": "/a", "size_bytes": 1, "sha256": "1" * 64}
            },
            "publication_contract": {
                "global_serial_lock_contract": {
                    "path": "/x",
                    "mode": "EXCLUSIVE_NONBLOCKING_FLOCK",
                    "scope": "scope",
                    "held_through_double_build_and_publication": True,
                }
            },
            "scientific": {"threshold": 0.70},
        }
        first = C.delta_semantic_projection_sha256(delta)
        changed_normalized = copy.deepcopy(delta)
        changed_normalized["analysis_code_identities"]["formal_accuracy_controller_v2"] = {
            "path": "/b", "size_bytes": 9, "sha256": "9" * 64
        }
        changed_normalized["future_accuracy_controller_contract"]["active_controller"] = {
            "path": "/b", "size_bytes": 9, "sha256": "9" * 64
        }
        self.assertEqual(first, C.delta_semantic_projection_sha256(changed_normalized))
        changed_lock = copy.deepcopy(delta)
        changed_lock["publication_contract"]["global_serial_lock_contract"][
            "held_through_double_build_and_publication"
        ] = False
        self.assertNotEqual(first, C.delta_semantic_projection_sha256(changed_lock))
        changed_science = copy.deepcopy(delta)
        changed_science["scientific"]["threshold"] = 0.69
        self.assertNotEqual(first, C.delta_semantic_projection_sha256(changed_science))

    def test_actual_watchdog_producer_passive_rc2_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            self.assertEqual(fixture.raw["execution"]["raw_returncode"], 0)
            self.assertEqual(fixture.watchdog["execution"]["runner_returncode"], 2)
            with mock.patch.object(
                C,
                "_recompute_and_match_adjudication",
                return_value=fixture.replay_result(),
            ):
                bundle = C.validate_adjudication_bundle(
                    fixture.delta,
                    fixture.delta_snapshot,
                    fixture.code,
                    fixture.row,
                    fixture.case_id,
                )
            self.assertEqual(bundle.watchdog["status"], C.WATCHDOG_PASSIVE_STATUS)

    def test_watchdog_tampering_cannot_be_promoted(self) -> None:
        for mutation in (
            "returncode",
            "signal",
            "monitoring_error",
            "result_pin",
            "zero_kf_status",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = BundleFixture(Path(temporary))
                if mutation == "returncode":
                    fixture.watchdog["execution"]["runner_returncode"] = 0
                else:
                    if mutation == "signal":
                        fixture.watchdog["watchdog_action"]["signal_attempt_count"] = 1
                    elif mutation == "monitoring_error":
                        fixture.watchdog["observations"]["monitoring_errors"] = ["fixture"]
                    elif mutation == "result_pin":
                        fixture.watchdog["pins"]["runner_result_at_receipt"] = None
                    else:
                        fixture.watchdog["status"] = (
                            "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_SAVE_HANG"
                        )
                fixture.publish_watchdog_and_adjudication()
                with mock.patch.object(
                    C,
                    "_recompute_and_match_adjudication",
                    return_value=fixture.replay_result(),
                ):
                    with self.assertRaises(C.ControllerError):
                        C.validate_adjudication_bundle(
                            fixture.delta,
                            fixture.delta_snapshot,
                            fixture.code,
                            fixture.row,
                            fixture.case_id,
                        )

    def test_missing_watchdog_receipt_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            fixture.watchdog_path.unlink()
            with mock.patch.object(
                C,
                "_recompute_and_match_adjudication",
                return_value=fixture.replay_result(),
            ):
                with self.assertRaises(C.ControllerError):
                    C.validate_adjudication_bundle(
                        fixture.delta,
                        fixture.delta_snapshot,
                        fixture.code,
                        fixture.row,
                        fixture.case_id,
                    )

    def test_raw_extra_failure_and_plaintext_token_fail_closed(self) -> None:
        delta = {
            "cache_adjudication_contract": {
                "raw_status_required_for_correction": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
                "raw_failure_code_set_required": [
                    "FROZEN_CONTRACT_DRIFT",
                    "POST_AUDIT_INCOMPLETE",
                ],
                "sole_post_audit_error_required": (
                    "FROZEN_CONTRACT_POST_AUDIT:ContractError:"
                    "DERIVED_FILE_DRIFT:local_cache"
                ),
            }
        }
        raw = raw_receipt("case", {"path": "/t", "size_bytes": 1, "sha256": "a" * 64}, {})
        raw["failure_codes"].append("NO_VALID_TRAJECTORY")
        with self.assertRaises(C.ControllerError):
            C._validate_raw_cache_only_pass_candidate(raw, "case", delta)
        raw["failure_codes"] = ["FROZEN_CONTRACT_DRIFT", "POST_AUDIT_INCOMPLETE"]
        raw["leak"] = C.AUTHORIZATION_TOKEN
        with self.assertRaisesRegex(C.ControllerError, "PLAINTEXT_TOKEN"):
            C._validate_raw_cache_only_pass_candidate(raw, "case", delta)

    def test_published_adjudicator_api_identity_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = []
            for name in ("case.json", "adjud.json", "raw.json", "pre.json", "delta.json", "validator.py"):
                path = root / name
                path.write_bytes(b"{}\n")
                files.append(path)
            case, adjud, raw, pre, delta, validator = map(snapshot, files)
            row = {"case_id": C.REMAINING_CASES[0], "case_spec": case.identity}

            class Validator:
                @staticmethod
                def validate_published_adjudication(_path: Path) -> dict:
                    return {
                        "schema_version": C.ADJUDICATION_SCHEMA,
                        "status": "PASS_PUBLISHED_ADJUDICATION_EXACTLY_RECOMPUTED",
                        "case_id": row["case_id"],
                        "receipt_identity": adjud.identity,
                        "validator": validator.identity,
                        "raw_runability_receipt": raw.identity,
                        "prestart_receipt": pre.identity,
                        "zero_kf_watchdog_receipt": {"path": "/w", "size_bytes": 1, "sha256": "f" * 64},
                        "accuracy_authority_supersession": delta.identity,
                        "accuracy_computed": False,
                    }

            with mock.patch.object(C, "_load_cache_adjudicator", return_value=Validator):
                result = C._recompute_and_match_adjudication(
                    {}, adjud, raw, pre, delta, {"cache_contract_adjudicator": validator}, row
                )
                self.assertEqual(result["receipt_identity"], adjud.identity)
                original = Validator.validate_published_adjudication

                def forged(path: Path) -> dict:
                    value = original(path)
                    value["receipt_identity"] = raw.identity
                    return value

                Validator.validate_published_adjudication = staticmethod(forged)
                with self.assertRaisesRegex(C.ControllerError, "PUBLISHED_REPLAY"):
                    C._recompute_and_match_adjudication(
                        {}, adjud, raw, pre, delta, {"cache_contract_adjudicator": validator}, row
                    )

    def test_v2_reverification_wraps_every_ledger_pass(self) -> None:
        class Ledger:
            def __init__(self) -> None:
                self.count = 0

            def verify_all(self) -> dict:
                self.count += 1
                return {"count": self.count}

        class Context:
            def __init__(self) -> None:
                self.ledger = Ledger()
                self.row = {"case_id": C.REMAINING_CASES[0]}

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "delta.json"
            path.write_bytes(b"{}\n")
            delta_snapshot = snapshot(path)
            code = {"x": delta_snapshot}
            context = Context()
            with mock.patch.object(
                C, "read_delta_seal", return_value=({}, delta_snapshot, code)
            ), mock.patch.object(C, "_validate_lock_extension", return_value=None) as validate:
                C._install_v2_reverification(
                    context, {}, {}, delta_snapshot, code, C.REMAINING_CASES[0]
                )
                context.ledger.verify_all()
                context.ledger.verify_all()
            self.assertEqual(context.ledger.count, 2)
            self.assertEqual(validate.call_count, 2)

    def test_a05_is_not_a_cli_choice(self) -> None:
        self.assertNotIn("a05_3300_3700", C.REMAINING_CASES)
        self.assertTrue(all(case_id in C.REMAINING_CASES for case_id in C.REMAINING_CASES))

    def test_noncanonical_delta_path_is_rejected_before_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "copied_delta.json"
            write_json(path, {"schema_version": C.DELTA_SCHEMA, "status": C.DELTA_STATUS})
            value, observed = C.BASE.read_canonical_json_path(path, "copied_delta")
            with self.assertRaisesRegex(C.ControllerError, "NONCANONICAL_PATH"):
                C.validate_delta_seal(value, observed)

    def test_v1_core_normalizes_raw_cache_receipt_to_fail(self) -> None:
        raw = raw_receipt(
            C.REMAINING_CASES[0],
            {"path": "/t", "size_bytes": 1, "sha256": "a" * 64},
            {},
        )
        self.assertEqual(C.BASE._runability_status(raw, C.REMAINING_CASES[0]), "FAIL")
        self.assertNotEqual(C.EXECUTION_LOCK_ROOT.name, "_accuracy_execution_locks_v1")

    def test_direct_v1_controller_derives_a_different_lock_namespace(self) -> None:
        seal, _snapshot = C.BASE.read_canonical_json_identity(
            C.BASE_SEAL_EXPECTED, "parent_v1_seal_fixture"
        )
        v1_lock, _bridge = C.BASE.execution_lock_paths(seal, C.REMAINING_CASES[0])
        v2_lock = C.EXECUTION_LOCK_ROOT / f"{C.REMAINING_CASES[0]}.json"
        self.assertEqual(v1_lock.parent.name, "_accuracy_execution_locks_v1")
        self.assertEqual(v2_lock.parent.name, "_accuracy_execution_locks_v2")
        self.assertNotEqual(v1_lock, v2_lock)


if __name__ == "__main__":
    unittest.main()
