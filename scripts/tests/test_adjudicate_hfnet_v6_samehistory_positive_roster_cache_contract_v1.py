from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "adjudicate_hfnet_v6_samehistory_positive_roster_cache_contract_v1.py"
)
SPEC = importlib.util.spec_from_file_location("cache_contract_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


def identity(path: Path) -> dict[str, object]:
    return subject.snapshot_regular(path, path.name).identity


class CacheContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.model = self.root / "attempt/run_local_model/HFNet-RT"
        self.model.mkdir(parents=True)
        self.onnx = self.model / "HF-Net.onnx"
        self.cache = self.model / "HF-Net.cache"
        self.shared = self.root / "shared/HF-Net.cache"
        self.shared.parent.mkdir()
        self.onnx.write_bytes(b"onnx")
        self.shared.write_bytes(b"seed-cache")
        self.cache.write_bytes(b"seed-cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def audit_model(self, *, require_seed: bool = True) -> dict[str, object]:
        return subject.audit_model_directory(
            self.onnx,
            self.cache,
            self.shared,
            identity(self.onnx),
            identity(self.shared),
            require_seed=require_seed,
        )

    def test_exact_seed_regular_isolated_two_file_closure_passes(self) -> None:
        result = self.audit_model()
        self.assertTrue(result["local_cache_isolated_from_shared_seed"])
        self.assertTrue(result["local_cache_matches_shared_seed"])
        self.assertEqual(result["closure"], ["HF-Net.cache", "HF-Net.onnx"])

    def test_post_mutation_is_allowed_but_recorded(self) -> None:
        pre = self.audit_model()
        self.cache.write_bytes(b"updated-cache")
        result = self.audit_model(require_seed=False)
        self.assertFalse(result["local_cache_matches_shared_seed"])
        subject.require_local_cache_in_place(pre, result)
        with self.assertRaisesRegex(subject.ContractError, "LOCAL_CACHE_PRESTART_NOT_EXACT_SEED"):
            self.audit_model(require_seed=True)

    def test_post_cache_replacement_fails_even_with_regular_local_file(self) -> None:
        pre = self.audit_model()
        replacement = self.model / "replacement.cache"
        replacement.write_bytes(b"updated-cache")
        os.replace(replacement, self.cache)
        post = self.audit_model(require_seed=False)
        with self.assertRaisesRegex(subject.ContractError, "LOCAL_CACHE_INODE_REPLACED"):
            subject.require_local_cache_in_place(pre, post)

    def test_extra_model_entry_fails_closure(self) -> None:
        (self.model / "unexpected.engine").write_bytes(b"x")
        with self.assertRaisesRegex(subject.ContractError, "LOCAL_MODEL_DIRECTORY_CLOSURE"):
            self.audit_model()

    def test_cache_symlink_fails(self) -> None:
        self.cache.unlink()
        self.cache.symlink_to(self.shared)
        with self.assertRaisesRegex(subject.ContractError, "LOCAL_MODEL_ENTRY_SYMLINK"):
            self.audit_model()

    def test_cache_hardlink_to_shared_seed_fails(self) -> None:
        self.cache.unlink()
        os.link(self.shared, self.cache)
        with self.assertRaisesRegex(subject.ContractError, "LOCAL_CACHE_ALIASES_SHARED_SEED"):
            self.audit_model()

    def timing_logs(self) -> tuple[bytes, bytes, int]:
        raw_path = str(self.cache.parent) + "//HF-Net.cache"
        sizes = [(10, 12), (12, 12), (12, 15), (15, 15)]
        lines: list[str] = []
        for loaded, saved in sizes:
            lines.extend(
                [
                    f"Loaded {loaded} bytes of timing cache from {raw_path}",
                    f"Loaded {loaded} bytes of timing cache from {raw_path}",
                    f"Saved {saved} bytes of timing cache to {raw_path}",
                ]
            )
        stdout = "\n".join(
            f"Successfully loaded HFNet TensorRT model. Mode: level-{index}"
            for index in range(4)
        )
        return ("\n".join(lines) + "\n").encode(), (stdout + "\n").encode(), 15

    def test_exact_four_level_timing_event_chain_passes(self) -> None:
        stderr, stdout, post = self.timing_logs()
        result = subject.audit_timing_cache_events(
            stderr, stdout, self.cache, 10, post
        )
        self.assertEqual(result["event_count"], 12)
        self.assertEqual(result["pyramid_model_count"], 4)

    def test_timing_cache_wrong_path_fails(self) -> None:
        stderr, stdout, post = self.timing_logs()
        logged_path = (str(self.cache.parent) + "//HF-Net.cache").encode()
        stderr = stderr.replace(logged_path, b"/tmp/other.cache")
        with self.assertRaisesRegex(subject.ContractError, "TIMING_CACHE_PATH_NOT_CANONICAL_LOCAL"):
            subject.audit_timing_cache_events(stderr, stdout, self.cache, 10, post)

    def test_timing_cache_write_error_fails(self) -> None:
        stderr, stdout, post = self.timing_logs()
        stderr += f"Could not write timing cache to: {self.cache}\n".encode()
        with self.assertRaisesRegex(subject.ContractError, "TIMING_CACHE_MESSAGE_UNRECOGNIZED"):
            subject.audit_timing_cache_events(stderr, stdout, self.cache, 10, post)

    def test_timing_cache_missing_level_fails(self) -> None:
        stderr, stdout, post = self.timing_logs()
        shortened = b"\n".join(stderr.splitlines()[:-3]) + b"\n"
        with self.assertRaisesRegex(subject.ContractError, "TIMING_CACHE_EVENT_SEQUENCE"):
            subject.audit_timing_cache_events(shortened, stdout, self.cache, 10, post)

    def test_timing_cache_broken_size_chain_fails(self) -> None:
        stderr, stdout, post = self.timing_logs()
        stderr = stderr.replace(b"Loaded 12 bytes", b"Loaded 13 bytes", 1)
        with self.assertRaisesRegex(subject.ContractError, "TIMING_CACHE_FIRST_LOAD_SIZE"):
            subject.audit_timing_cache_events(stderr, stdout, self.cache, 10, post)

    def test_exact_cache_only_runner_incident_is_the_only_carveout(self) -> None:
        retained, carved, proven = subject.derive_failure_codes(
            list(subject.CACHE_CONSEQUENT_FAILURE_CODES),
            [subject.EXPECTED_CACHE_POST_ERROR],
            cache_changed=True,
        )
        self.assertEqual(retained, [])
        self.assertEqual(carved, list(subject.CACHE_CONSEQUENT_FAILURE_CODES))
        self.assertTrue(proven)

    def test_any_other_runner_failure_is_retained(self) -> None:
        retained, carved, proven = subject.derive_failure_codes(
            [*subject.CACHE_CONSEQUENT_FAILURE_CODES, "TRAJECTORY_INVALID"],
            [subject.EXPECTED_CACHE_POST_ERROR],
            cache_changed=True,
        )
        self.assertEqual(retained, ["TRAJECTORY_INVALID"])
        self.assertEqual(carved, list(subject.CACHE_CONSEQUENT_FAILURE_CODES))
        self.assertTrue(proven)

    def test_other_post_audit_error_cannot_be_carved_out(self) -> None:
        retained, carved, proven = subject.derive_failure_codes(
            list(subject.CACHE_CONSEQUENT_FAILURE_CODES),
            ["SOMETHING_ELSE"],
            cache_changed=True,
        )
        self.assertIn("NON_CACHE_OR_UNPROVEN_POST_AUDIT_ERROR", retained)
        self.assertEqual(carved, [])
        self.assertFalse(proven)

    def test_changed_cache_without_frozen_v2_error_fails(self) -> None:
        with self.assertRaisesRegex(
            subject.ContractError,
            "CACHE_CHANGED_WITHOUT_FROZEN_V2_POST_AUDIT_ERROR",
        ):
            subject.derive_failure_codes([], [], cache_changed=True)

    def test_a05_is_permanently_excluded(self) -> None:
        with self.assertRaisesRegex(subject.ContractError, "A05_CONSUMED_RE_ADJUDICATION_FORBIDDEN"):
            subject._case_id({"case_id": "a05_3300_3700"})

    def test_independent_scientific_audit_recomputes_pass(self) -> None:
        trajectory = {
            "valid": True,
            "coverage_fraction": 0.8,
            "longest_contiguous_fraction": 0.8,
            "pose_count": 8,
            "identity": {"path": "/tmp/t", "size_bytes": 1, "sha256": "1" * 64},
        }
        keyframes = {"valid": True, "pose_count": 2}
        base_log = {
            "valid": True,
            "final_atlas_nonempty": True,
            "initialization_count": 1,
        }
        accepted = {
            "first_relative_index": 0,
            "last_relative_index": 7,
            "proven_early_reset_events": [],
            "unresolved_reset_events": [],
            "reinitialization_frame_ids": [],
        }
        expected_log = {
            **base_log,
            "accepted_support_first_relative_index": 0,
            "accepted_support_last_relative_index": 7,
            "proven_early_reset_events": [],
            "accepted_support_unresolved_reset_events": [],
            "accepted_support_reinitialization_frame_ids": [],
        }
        raw = {
            "execution": {
                "raw_returncode": 0,
                "timed_out": False,
                "supervisor_error": None,
                "child_reaped_before_post_audit": True,
                "popen_invocations": 1,
            },
            "support": {
                "camera_count": 10,
                "trajectory": trajectory,
                "keyframes": keyframes,
                "log": expected_log,
            },
        }
        with mock.patch.object(subject.BASE, "selected_timestamps", return_value=list(range(10))), mock.patch.object(
            subject.V2, "parse_trajectory", side_effect=[trajectory, keyframes]
        ), mock.patch.object(subject.BASE, "parse_log", return_value=dict(base_log)), mock.patch.object(
            subject.BASE, "events_in_accepted_support", return_value=accepted
        ):
            result = subject.independent_scientific_runability_audit(
                {"case_id": "a07_10800_11200"},
                {"result_dir": self.root, "stdout": self.root / "stdout"},
                raw,
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failure_codes"], [])

    def test_accuracy_supersession_binds_validator_identity_and_cases(self) -> None:
        seal = self.root / "accuracy_supersession.json"
        value = {
            "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-accuracy-supersession-v2",
            "status": "SEALED_POST_A05_CACHE_VALIDATOR_INCIDENT_BEFORE_REMAINING_NINE_NO_METRICS",
            "remaining_cases": list(subject.PROSPECTIVE_CASES),
            "a05_terminal_boundary": {"status": "FAIL"},
            "analysis_code_identities": {
                "cache_contract_adjudicator": subject.snapshot_regular(
                    subject.VALIDATOR, "validator_self"
                ).identity,
                "zero_kf_watchdog": dict(subject.WATCHDOG_IDENTITY),
                "formal_accuracy_controller_v2": {
                    "path": "/tmp/future",
                    "size_bytes": 1,
                    "sha256": "2" * 64,
                },
            },
            "authorities": {
                "cache_contract_governance_addendum": dict(subject.ADDENDUM_IDENTITY),
                "zero_kf_watchdog_protocol": dict(subject.WATCHDOG_PROTOCOL_IDENTITY),
            },
            "zero_kf_watchdog_contract": {
                "accuracy_promotable_status": subject.WATCHDOG_PASSIVE_STATUS,
                "pass_requires_runner_reaped": True,
                "pass_requires_zero_signal_attempts": True,
                "pass_requires_zero_signals": True,
                "pass_requires_empty_monitoring_errors": True,
                "raw_runability_receipt_exact_pin_required": True,
                "supervisor_pre_post_exact_code_identity_required": True,
                "runner_claim_chain_exactly_validated_by_adjudicator": True,
                "zero_kf_or_supervision_error_promotable": False,
            },
        }
        seal.write_bytes(subject.canonical_json_bytes(value))
        with mock.patch.object(subject, "ACCURACY_SUPERSESSION", seal):
            observed = subject.validate_accuracy_supersession("a07_10800_11200")
        self.assertEqual(observed.identity, identity(seal))

    def watchdog_fixture(self) -> tuple[dict[str, object], dict[str, Path], dict[str, object], object, object, object]:
        case_id = "a07_10800_11200"
        spec = self.root / "case.json"
        prepared_path = self.root / "prepared.json"
        stdout = self.root / "stdout.log"
        result_path = self.root / "run_result.json"
        result_dir = self.root / "results"
        binary = self.root / "hfnet"
        pointer = self.root / "pointer.json"
        prefreeze = self.root / "prefreeze.json"
        for path, payload in (
            (spec, b"{}\n"),
            (prepared_path, b"{}\n"),
            (stdout, b"normal\n"),
            (binary, b"binary"),
            (pointer, b"pointer"),
            (prefreeze, b"prefreeze"),
        ):
            path.write_bytes(payload)
        result_dir.mkdir()
        trajectory = result_dir / "trajectory.txt"
        trajectory.write_bytes(b"0 0 0 0 0 0 0 1\n")
        raw = {
            "status": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
            "execution": {"raw_returncode": 0},
        }
        result_path.write_bytes(subject.canonical_json_bytes(raw))
        launch_argv = [str(binary), "config.yaml", str(result_dir) + "/", "dataset", "times"]
        prepared = {
            "stack": {"binary": identity(binary)},
            "launch": {"argv": launch_argv},
        }
        paths = {"result_dir": result_dir, "stdout": stdout}
        return (
            prepared,
            paths,
            raw,
            subject.snapshot_regular(result_path, "result"),
            subject.snapshot_regular(prepared_path, "prepared"),
            subject.snapshot_regular(stdout, "stdout"),
            spec,
            pointer,
            prefreeze,
        )

    def write_watchdog_receipt(
        self,
        root: Path,
        fixture: tuple[object, ...],
        *,
        status: str = subject.WATCHDOG_PASSIVE_STATUS,
        result_pin: dict[str, object] | None = None,
    ) -> Path:
        prepared, paths, raw, result_snapshot, prepared_snapshot, stdout_snapshot, spec, pointer, prefreeze = fixture
        case_id = "a07_10800_11200"
        action = {
            "sigterm_sent": False,
            "sigterm_sent_at_utc": None,
            "signal_attempt_count": 0,
            "signal_count": 0,
            "signal": None,
            "signal_scope": None,
            "process_group_signaled": False,
            "sigkill_sent": False,
            "other_process_signaled": False,
            "signal_delivery": None,
            "post_signal_identity_state": None,
        }
        signature = None
        if status == subject.WATCHDOG_ZERO_KF_STATUS:
            action.update(
                {
                    "sigterm_sent": True,
                    "sigterm_sent_at_utc": "2026-01-01T00:00:40+00:00",
                    "signal_attempt_count": 1,
                    "signal_count": 1,
                    "signal": "SIGTERM",
                    "signal_scope": "PIDFD_EXACT_CHILD_ONLY",
                    "signal_delivery": "SIGTERM_SENT_VIA_PIDFD_TO_EXACT_VALIDATED_HFNET_CHILD",
                    "post_signal_identity_state": "EXACT_CHILD_EXITED_OR_PROC_ENTRY_GONE_AFTER_SIGTERM",
                }
            )
            signature = {
                "confirmed": True,
                "shutdown_observed": True,
                "saving_trajectory_observed": True,
                "complete_atlas_rows_observed": True,
                "every_reported_atlas_map_zero_keyframes": True,
                "trajectory_absent": True,
                "end_of_saving_absent": True,
                "atlas_map_count": 1,
                "map_keyframes_by_id": [[0, 0]],
            }
            (paths["result_dir"] / "trajectory.txt").unlink()
        receipt = {
            "schema_version": subject.WATCHDOG_RECEIPT_SCHEMA,
            "status": status,
            "case_id": case_id,
            "started_at_utc": "2026-01-01T00:00:00+00:00",
            "ended_at_utc": "2026-01-01T00:01:00+00:00",
            "fixed_signature_grace_seconds": 30.0,
            "signature_contract": {
                "ordered_shutdown_before_saving": True,
                "complete_reported_atlas_map_id_set_required": True,
                "every_reported_atlas_map_zero_keyframes_required": True,
                "trajectory_must_remain_absent": str(paths["result_dir"] / "trajectory.txt"),
                "end_of_saving_must_remain_absent": True,
                "continuous_for_fixed_grace": True,
            },
            "execution": {
                "runner_entry": str(subject.V2_RUNNER),
                "runner_action": "run",
                "case_spec": str(spec),
                "authorization_transport": "ANONYMOUS_PIPE_TO_IN_MEMORY_RUNPY_ARGV",
                "authorization_token_in_os_argv": False,
                "authorization_token_in_environment": False,
                "authorization_token_serialized_in_receipt": False,
                "runner_popen_invocations": 1,
                "hfnet_popen_authority_remains_with_frozen_runner": True,
                "retry_performed": False,
                "retry_permitted": False,
                "runner_returncode": 2,
                "runner_reaped": True,
            },
            "watchdog_action": action,
            "observations": {
                "child_discovered_at_utc": "2026-01-01T00:00:01+00:00",
                "exact_hfnet_child": {
                    "pid": 1001,
                    "ppid": 1000,
                    "starttime_ticks": 99,
                    "executable": os.path.realpath(str(prepared["stack"]["binary"]["path"])),
                    "argv": prepared["launch"]["argv"],
                },
                "signature_first_observed_at_utc": (
                    "2026-01-01T00:00:10+00:00"
                    if status == subject.WATCHDOG_ZERO_KF_STATUS
                    else None
                ),
                "signature_evidence": signature,
                "monitoring_errors": [],
            },
            "pins": {
                "supervisor_pre": dict(subject.WATCHDOG_IDENTITY),
                "supervisor_post": dict(subject.WATCHDOG_IDENTITY),
                "frozen_runner": dict(subject.V2_RUNNER_IDENTITY),
                "roster_pointer": identity(pointer),
                "accuracy_prefreeze_seal": identity(prefreeze),
                "case_spec": identity(spec),
                "prepared_manifest": prepared_snapshot.identity,
                "hfnet_binary": prepared["stack"]["binary"],
                "stdout_log_at_receipt": stdout_snapshot.identity,
                "trajectory_at_receipt": subject._optional_regular_identity(
                    paths["result_dir"] / "trajectory.txt", "trajectory"
                ),
                "runner_result_at_receipt": result_pin or result_snapshot.identity,
            },
            "terminal_contract": {
                "receipt_path": str(root / f"{case_id}.json"),
                "receipt_outside_attempt_directory": True,
                "receipt_publication": "TEMP_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC",
                "watchdog_retry_after_receipt": False,
                "watchdog_never_fabricates_or_edits_runner_outputs": True,
            },
        }
        path = root / f"{case_id}.json"
        root.mkdir()
        path.write_bytes(subject.canonical_json_bytes(receipt))
        return path

    def validate_watchdog_fixture(self, fixture: tuple[object, ...], receipt_root: Path):
        prepared, paths, raw, result_snapshot, prepared_snapshot, stdout_snapshot, spec, pointer, prefreeze = fixture
        with mock.patch.object(subject, "WATCHDOG_RECEIPT_ROOT", receipt_root), mock.patch.object(
            subject, "WATCHDOG_ROSTER_POINTER", pointer
        ), mock.patch.object(subject, "WATCHDOG_ACCURACY_PREFREEZE_SEAL", prefreeze):
            return subject.validate_zero_kf_watchdog_receipt(
                "a07_10800_11200",
                spec,
                prepared,
                paths,
                raw,
                result_snapshot,
                prepared_snapshot,
                stdout_snapshot,
            )

    def test_passive_zero_signal_watchdog_is_promotable(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        self.write_watchdog_receipt(receipt_root, fixture)
        evidence, _snapshot, promotable = self.validate_watchdog_fixture(fixture, receipt_root)
        self.assertTrue(promotable)
        self.assertTrue(evidence["promotable_passive"])

    def test_zero_kf_watchdog_intervention_never_promotes(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        self.write_watchdog_receipt(
            receipt_root, fixture, status=subject.WATCHDOG_ZERO_KF_STATUS
        )
        evidence, _snapshot, promotable = self.validate_watchdog_fixture(fixture, receipt_root)
        self.assertFalse(promotable)
        self.assertTrue(evidence["zero_kf_intervention"])

    def test_watchdog_error_status_fails_closed(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        path = self.write_watchdog_receipt(receipt_root, fixture)
        value = json.loads(path.read_text())
        value["status"] = "WATCHDOG_SUPERVISION_ERROR_FAIL_CLOSED"
        value["observations"]["monitoring_errors"] = ["RUNNER_NOT_REAPED"]
        path.write_bytes(subject.canonical_json_bytes(value))
        with self.assertRaisesRegex(subject.ContractError, "WATCHDOG_RECEIPT_NOT_NORMAL"):
            self.validate_watchdog_fixture(fixture, receipt_root)

    def test_watchdog_raw_result_pin_mismatch_fails_closed(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        self.write_watchdog_receipt(
            receipt_root,
            fixture,
            result_pin={"path": "/wrong", "size_bytes": 1, "sha256": "0" * 64},
        )
        with self.assertRaisesRegex(subject.ContractError, "WATCHDOG_RESULT_PIN"):
            self.validate_watchdog_fixture(fixture, receipt_root)

    def test_watchdog_missing_receipt_fails_closed(self) -> None:
        fixture = self.watchdog_fixture()
        with self.assertRaisesRegex(subject.ContractError, "FILE_LSTAT_FAILED"):
            self.validate_watchdog_fixture(fixture, self.root / "missing-watchdog")

    def test_passive_watchdog_deleted_required_fields_fail_closed(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        path = self.write_watchdog_receipt(receipt_root, fixture)
        complete = json.loads(path.read_text())
        field_paths = (
            ("started_at_utc",),
            ("fixed_signature_grace_seconds",),
            ("signature_contract", "continuous_for_fixed_grace"),
            ("execution", "authorization_transport"),
            ("execution", "runner_returncode"),
            ("observations", "exact_hfnet_child"),
            ("observations", "child_discovered_at_utc"),
            ("terminal_contract", "receipt_publication"),
            ("pins", "runner_result_at_receipt"),
        )
        for field_path in field_paths:
            with self.subTest(field_path=field_path):
                tampered = copy.deepcopy(complete)
                owner = tampered
                for key in field_path[:-1]:
                    owner = owner[key]
                del owner[field_path[-1]]
                path.write_bytes(subject.canonical_json_bytes(tampered))
                with self.assertRaises(subject.ContractError):
                    self.validate_watchdog_fixture(fixture, receipt_root)

    def test_passive_watchdog_any_signal_or_monitoring_error_fails_closed(self) -> None:
        fixture = self.watchdog_fixture()
        receipt_root = self.root / "watchdog"
        path = self.write_watchdog_receipt(receipt_root, fixture)
        complete = json.loads(path.read_text())
        for field_path, replacement in (
            (("watchdog_action", "signal_attempt_count"), 1),
            (("watchdog_action", "signal_count"), 1),
            (("watchdog_action", "sigterm_sent"), True),
            (("observations", "monitoring_errors"), ["INJECTED"]),
            (("observations", "signature_evidence"), {"confirmed": True}),
        ):
            with self.subTest(field_path=field_path):
                tampered = copy.deepcopy(complete)
                tampered[field_path[0]][field_path[1]] = replacement
                path.write_bytes(subject.canonical_json_bytes(tampered))
                with self.assertRaises(subject.ContractError):
                    self.validate_watchdog_fixture(fixture, receipt_root)

    def published_adjudication_fixture(self) -> tuple[Path, Path, dict[str, object]]:
        case_id = "a07_10800_11200"
        spec = self.root / "published-case.json"
        spec.write_bytes(b"{}\n")
        receipt_root = self.root / "published-adjudication"
        receipt_root.mkdir()
        recomputed = {
            "schema_version": subject.ADJUDICATION_SCHEMA,
            "status": "PASS",
            "case_id": case_id,
            "raw_runability_receipt": {"path": "/raw", "size_bytes": 1, "sha256": "1" * 64},
            "prestart_receipt": {"path": "/pre", "size_bytes": 2, "sha256": "2" * 64},
            "zero_kf_watchdog_receipt": {
                "path": "/watchdog",
                "size_bytes": 3,
                "sha256": "3" * 64,
            },
            "accuracy_authority_supersession": {
                "path": "/authority",
                "size_bytes": 4,
                "sha256": "4" * 64,
            },
            "accuracy_computed": False,
        }
        published = {
            **recomputed,
            "adjudicated_at_utc": "2026-01-01T00:00:01+00:00",
            "roster_global_lock": {
                "path": str(self.root / "global.lock"),
                "pid": 123,
                "acquired_at_utc": "2026-01-01T00:00:00+00:00",
            },
        }
        (receipt_root / f"{case_id}.runability_adjudication.json").write_bytes(
            subject.canonical_json_bytes(published)
        )
        return spec, receipt_root, recomputed

    def test_published_adjudication_exact_recomputation_passes(self) -> None:
        spec, receipt_root, recomputed = self.published_adjudication_fixture()
        with mock.patch.object(subject, "RECEIPT_ROOT", receipt_root), mock.patch.object(
            subject.BASE, "validate_spec", return_value=({"case_id": "a07_10800_11200"}, {})
        ), mock.patch.object(
            subject.BASE, "global_lock_path", return_value=self.root / "global.lock"
        ), mock.patch.object(subject, "validate_post", return_value=recomputed):
            result = subject.validate_published_adjudication(spec)
        self.assertEqual(
            result["status"], "PASS_PUBLISHED_ADJUDICATION_EXACTLY_RECOMPUTED"
        )
        self.assertEqual(result["receipt_identity"]["path"], str(receipt_root / "a07_10800_11200.runability_adjudication.json"))

    def test_published_adjudication_projection_tamper_fails(self) -> None:
        spec, receipt_root, recomputed = self.published_adjudication_fixture()
        path = receipt_root / "a07_10800_11200.runability_adjudication.json"
        value = json.loads(path.read_text())
        value["accuracy_computed"] = True
        path.write_bytes(subject.canonical_json_bytes(value))
        with mock.patch.object(subject, "RECEIPT_ROOT", receipt_root), mock.patch.object(
            subject.BASE, "validate_spec", return_value=({"case_id": "a07_10800_11200"}, {})
        ), mock.patch.object(
            subject.BASE, "global_lock_path", return_value=self.root / "global.lock"
        ), mock.patch.object(subject, "validate_post", return_value=recomputed):
            with self.assertRaisesRegex(
                subject.ContractError, "PUBLISHED_ADJUDICATION_NOT_EXACT_RECOMPUTATION"
            ):
                subject.validate_published_adjudication(spec)

    def test_atomic_publication_is_no_replace(self) -> None:
        destination = self.root / "receipt.json"
        subject.atomic_publish_noreplace(destination, {"value": 1})
        with self.assertRaisesRegex(subject.ContractError, "EXCLUSIVE_PUBLICATION_EXISTS"):
            subject.atomic_publish_noreplace(destination, {"value": 2})
        self.assertEqual(json.loads(destination.read_text()), {"value": 1})


if __name__ == "__main__":
    unittest.main()
