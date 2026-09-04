#!/usr/bin/env python3
"""Process-free tests for the additive A09 ToDesk co-run overlay."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts import (
    run_hfnet_v6_a09_0000_6200_score_6000_6200_todesk_corun_development_only_v1
    as subject,
)


class CorunOverlayTest(unittest.TestCase):
    def _gpu_information(self, root: Path, model: str = "NVIDIA GeForce GTX 1650") -> Path:
        path = root / "information"
        path.write_text(
            f"Model:\t\t {model}\nBus Location:\t 0000:26:00.0\n",
            encoding="utf-8",
        )
        return path

    def _proc_entry(
        self,
        root: Path,
        pid: int,
        executable: str,
        arguments: list[str],
    ) -> None:
        entry = root / str(pid)
        entry.mkdir()
        os.symlink(executable, entry / "exe")
        (entry / "cmdline").write_bytes(
            b"\0".join(item.encode("utf-8") for item in arguments) + b"\0"
        )

    @staticmethod
    def _completed(stdout: str, returncode: int = 0) -> SimpleNamespace:
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    @staticmethod
    def _resource_subprocess():
        return subject.proven_resource.proven_resource.subprocess

    def test_formal_runner_test_and_freeze_exact_identities(self) -> None:
        rows = (
            (
                subject.FORMAL_RUNNER,
                subject.FORMAL_RUNNER_SIZE,
                subject.FORMAL_RUNNER_SHA256,
            ),
            (
                subject.FORMAL_RUNNER_TEST,
                subject.FORMAL_RUNNER_TEST_SIZE,
                subject.FORMAL_RUNNER_TEST_SHA256,
            ),
            (
                subject.FORMAL_RUNNER_FREEZE,
                subject.FORMAL_RUNNER_FREEZE_SIZE,
                subject.FORMAL_RUNNER_FREEZE_SHA256,
            ),
        )
        for path, expected_size, expected_hash in rows:
            self.assertEqual(path.stat().st_size, expected_size)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
        freeze = json.loads(subject.FORMAL_RUNNER_FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(freeze["controller"]["sha256"], subject.FORMAL_RUNNER_SHA256)
        self.assertEqual(
            freeze["controller_tests"]["sha256"], subject.FORMAL_RUNNER_TEST_SHA256
        )
        self.assertFalse(freeze["claims"]["attempt_prepared"])
        self.assertFalse(freeze["claims"]["hfnet_started"])

    def test_frozen_a08_resource_helper_and_a09_precedent(self) -> None:
        rows = (
            (
                subject.RESOURCE_HELPER,
                subject.RESOURCE_HELPER_SIZE,
                subject.RESOURCE_HELPER_SHA256,
            ),
            (
                subject.RESOURCE_HELPER_TEST,
                subject.RESOURCE_HELPER_TEST_SIZE,
                subject.RESOURCE_HELPER_TEST_SHA256,
            ),
            (
                subject.RESOURCE_HELPER_FREEZE,
                subject.RESOURCE_HELPER_FREEZE_SIZE,
                subject.RESOURCE_HELPER_FREEZE_SHA256,
            ),
        )
        for path, expected_size, expected_hash in rows:
            self.assertEqual(path.stat().st_size, expected_size)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
        freeze = json.loads(subject.RESOURCE_HELPER_FREEZE.read_text(encoding="utf-8"))
        self.assertTrue(freeze["claims"]["overlay_implemented_and_frozen"])
        self.assertFalse(freeze["claims"]["attempt_prepared"])
        value = subject.validate_a09_success_precedent()
        self.assertEqual(value["gpu_total_mib"], 4096)
        self.assertEqual(value["minimum_free_mib"], 3072)
        self.assertEqual(value["observed_success_lock_free_mib"], 3204)

    def test_namespace_token_indices_and_timeout_are_a09_specific(self) -> None:
        self.assertIs(subject.INPUT_ROOT, subject.formal.INPUT_ROOT)
        self.assertIs(subject.INPUT_MANIFEST, subject.formal.INPUT_MANIFEST)
        self.assertIs(subject.INPUT_AUDIT, subject.formal.INPUT_AUDIT)
        self.assertEqual(subject.TIMEOUT_SECONDS, 900)
        self.assertEqual(subject.formal.FEED_SOURCE_FIRST, 0)
        self.assertEqual(subject.formal.FEED_SOURCE_LAST, 6200)
        self.assertEqual(subject.formal.FEED_LOCAL_FIRST, 0)
        self.assertEqual(subject.formal.FEED_LOCAL_LAST, 6200)
        self.assertEqual(subject.formal.SCORE_SOURCE_FIRST, 6000)
        self.assertEqual(subject.formal.SCORE_SOURCE_LAST, 6200)
        self.assertEqual(subject.formal.SCORE_COUNT, 201)
        self.assertNotEqual(subject.ATTEMPT, subject.formal.ATTEMPT)
        self.assertIn("/corun/old_frozen_positive_windows/", str(subject.ATTEMPT))
        self.assertTrue(str(subject.ATTEMPT).endswith("/attempt_001"))
        self.assertEqual(
            subject.AUTHORIZATION_TOKEN,
            "HFNET_V6_A09_0000_6200_SCORE_6000_6200_TODESK_CORUN_"
            "DEVELOPMENT_ONLY_ATTEMPT_001_START_EXACTLY_ONCE",
        )
        self.assertEqual(
            subject.paths()["score_trajectory"].name,
            "trajectory_score_source_6000_6200.txt",
        )

    def test_todesk_ros_and_vins_are_allowed_when_memory_floor_holds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            self._proc_entry(proc_root, 101, "/opt/todesk/bin/ToDesk", ["ToDesk"])
            self._proc_entry(proc_root, 102, "/opt/ros/noetic/bin/roscore", ["roscore"])
            self._proc_entry(proc_root, 103, "/tmp/vins_node", ["vins_node"])
            gpu_information = self._gpu_information(root)
            responses = [
                self._completed("4096, 900, 3196\n"),
                self._completed("101, ToDesk, 220\n103, vins_node, 48\n"),
            ]
            with mock.patch.object(
                self._resource_subprocess(), "run", side_effect=responses
            ):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertTrue(value["ready"])
        self.assertEqual(value["errors"], [])
        self.assertEqual(len(value["allowed_compute_applications"]), 2)
        self.assertTrue(value["cpu_ros_vins_processes_permitted"])

    def test_low_memory_fails_even_under_user_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            gpu_information = self._gpu_information(root)
            responses = [
                self._completed("4096, 3054, 1042\n"),
                self._completed("2001, python3, 1500\n"),
            ]
            with mock.patch.object(
                self._resource_subprocess(), "run", side_effect=responses
            ):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertFalse(value["ready"])
        self.assertIn(
            "GPU_FREE_MEMORY_BELOW_FORMAL_A09_SUCCESS_FLOOR", value["errors"]
        )
        with self.assertRaisesRegex(
            subject.base.ContractError, "CORUN_GPU_FLOOR_NOT_FROZEN_3072_MIB"
        ):
            subject.resource_gate(2800)

    def test_competing_learned_compute_and_cmdline_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            self._proc_entry(
                proc_root,
                401,
                "/usr/bin/python3",
                ["python3", "/tmp/run_xfeat_frontend.py"],
            )
            self._proc_entry(
                proc_root,
                402,
                "/usr/bin/python3",
                ["python3", "/tmp/run_vins_replay.py"],
            )
            gpu_information = self._gpu_information(root)
            responses = [
                self._completed("4096, 700, 3300\n"),
                self._completed("42, mono_inertial_euroc_headless_v3, 600\n"),
            ]
            with mock.patch.object(
                self._resource_subprocess(), "run", side_effect=responses
            ):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
            conflicts = subject.scan_forbidden_processes(proc_root)
        self.assertFalse(value["ready"])
        self.assertIn(
            "FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_COMPUTE_APP_PRESENT",
            value["errors"],
        )
        self.assertIn(
            "FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_PROCESS_PRESENT", value["errors"]
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["pid"], 401)
        self.assertEqual(conflicts[0]["reason"], "LEARNED_BASELINE_PROCESS")

    def test_wrong_gpu_model_or_capacity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            gpu_information = self._gpu_information(root, "NVIDIA Mock GPU")
            responses = [self._completed("8192, 100, 8092\n"), self._completed("")]
            with mock.patch.object(
                self._resource_subprocess(), "run", side_effect=responses
            ):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertFalse(value["ready"])
        self.assertIn("GPU_MODEL_NOT_FROZEN_GTX1650", value["errors"])
        self.assertIn("GPU_TOTAL_MEMORY_NOT_FROZEN_4096_MIB", value["errors"])

    def test_policy_and_comparison_boundary_do_not_open_claims(self) -> None:
        policy = subject.RESOURCE_POLICY
        self.assertFalse(policy["resource_isolation"])
        self.assertTrue(policy["todesk_corun"])
        self.assertEqual(policy["minimum_prestart_free_gpu_mib"], 3072)
        self.assertFalse(policy["competing_hfnet_orb_or_learned_baseline_process_permitted"])
        boundary = subject._expected_comparison_boundary()
        self.assertTrue(boundary["runability_only"])
        self.assertFalse(boundary["accuracy_gate_open"])
        self.assertFalse(boundary["runtime_or_realtime_claim_permitted"])
        self.assertTrue(boundary["formal_resource_contract_relaxed_for_todesk_or_unrelated_ros"])
        self.assertFalse(boundary["resource_isolation"])
        self.assertEqual(boundary["timeout_seconds"], 900)
        self.assertFalse(subject.CLAIM_BOUNDARY["retry_permitted"])
        self.assertFalse(subject.CLAIM_BOUNDARY["formal_paper_claim_authorized"])

    def test_prepared_manifest_injection_and_validation_are_exact(self) -> None:
        prepared: dict[str, object] = {"launch": {}}
        with mock.patch.object(subject, "_install_overlay_profile"), mock.patch.object(
            subject, "_FORMAL_PROFILE_ATOMIC_JSON"
        ) as publisher:
            subject.profile_atomic_json(subject.paths()["prepared"], prepared)
        self.assertEqual(prepared["claim_boundary"], subject.CLAIM_BOUNDARY)
        self.assertEqual(prepared["resource_policy"], subject.RESOURCE_POLICY)
        self.assertEqual(prepared["launch"]["minimum_prestart_free_gpu_mib"], 3072)
        publisher.assert_called_once_with(
            subject.paths()["prepared"], prepared, exclusive=False
        )
        with mock.patch.object(subject, "_FORMAL_VALIDATE_PREPARED_LAUNCH"):
            subject._validate_prepared_launch(prepared)
            drift = dict(prepared)
            drift["resource_policy"] = dict(subject.RESOURCE_POLICY)
            drift["resource_policy"]["minimum_prestart_free_gpu_mib"] = 2800
            with self.assertRaisesRegex(
                subject.base.ContractError,
                "A09_CORUN_PREPARED_RESOURCE_CONTRACT_MISMATCH",
            ):
                subject._validate_prepared_launch(drift)

    def test_installer_rebinds_gate_and_finalizers_after_formal_install(self) -> None:
        def strict_gate() -> dict[str, object]:
            return {"ready": False}

        def restore_strict() -> None:
            subject.base.resource_gate = strict_gate

        strict_finalize = lambda value: dict(value)  # noqa: E731
        strict_failure = lambda value, error: dict(value)  # noqa: E731
        with mock.patch.object(subject, "_FORMAL_INSTALL", side_effect=restore_strict), mock.patch.object(
            subject.base, "resource_gate", strict_gate
        ), mock.patch.object(
            subject.formal.hardened, "_finalize_result_total", strict_finalize
        ), mock.patch.object(
            subject.formal.hardened, "_minimal_terminal_failure", strict_failure
        ):
            subject._install_overlay_profile()
            self.assertIs(subject.base.resource_gate, subject.resource_gate)
            self.assertIs(
                subject.formal.hardened._finalize_result_total,
                subject._finalize_result_total,
            )
            self.assertIs(
                subject.formal.hardened._minimal_terminal_failure,
                subject._minimal_terminal_failure,
            )

    def test_check_uses_real_installer_and_rebinds_gate_last(self) -> None:
        def strict_gate() -> dict[str, object]:
            return {"ready": False}

        def restore_strict() -> None:
            subject.base.resource_gate = strict_gate

        def fake_hardened_check() -> dict[str, object]:
            self.assertIs(subject.base.resource_gate, subject.resource_gate)
            return {"ready": True, "errors": []}

        with mock.patch.object(
            subject, "_FORMAL_INSTALL", side_effect=restore_strict
        ), mock.patch.object(
            subject.base, "resource_gate", strict_gate
        ), mock.patch.object(
            subject.formal, "_HARDENED_CHECK", side_effect=fake_hardened_check
        ):
            value = subject.check()
        self.assertTrue(value["ready"])
        self.assertEqual(value["schema_version"], subject.CHECK_SCHEMA)
        self.assertEqual(value["resource_policy"], subject.RESOURCE_POLICY)

    def test_terminal_decoration_forbids_accuracy_and_runtime_claims(self) -> None:
        value = subject._decorate_terminal(
            {
                "status": "PASS_DEVELOPMENT_RUNABILITY",
                "execution": {"duration_seconds": 456.0},
                "claim_boundary": {"development_only": True},
            }
        )
        self.assertEqual(value["execution"]["duration_seconds"], 456.0)
        self.assertFalse(value["claim_boundary"]["accuracy_claim_authorized"])
        self.assertFalse(value["claim_boundary"]["runtime_or_realtime_claim_authorized"])
        self.assertFalse(value["resource_context"]["runtime_or_realtime_claim_permitted"])

    def test_full_code_authority_includes_formal_helper_and_overlay_test(self) -> None:
        self.assertTrue(subject.RUNNER_TEST_PIN_READY)
        authority = subject.validate_code_authority()
        self.assertEqual(
            authority["frozen_a09_controller"]["sha256"],
            subject.FORMAL_RUNNER_SHA256,
        )
        self.assertEqual(
            authority["frozen_a09_controller_test"]["sha256"],
            subject.FORMAL_RUNNER_TEST_SHA256,
        )
        self.assertEqual(
            authority["proven_corun_resource_helper"]["sha256"],
            subject.RESOURCE_HELPER_SHA256,
        )
        self.assertEqual(
            authority["corun_overlay_test"]["sha256"], subject.RUNNER_TEST_SHA256
        )

    def test_overlay_has_no_popen_or_retry_path_and_parent_has_one_popen(self) -> None:
        overlay_source = subject.RUNNER.read_text(encoding="utf-8")
        formal_source = subject.FORMAL_RUNNER.read_text(encoding="utf-8")
        hardened_source = subject.formal.HARDENED_A05_RUNNER.read_text(encoding="utf-8")
        self.assertEqual(overlay_source.count("base.subprocess.Popen("), 0)
        self.assertEqual(formal_source.count("base.subprocess.Popen("), 0)
        self.assertEqual(hardened_source.count("base.subprocess.Popen("), 1)
        self.assertIs(subject._FORMAL_RUN_ONCE, subject.formal.run_once)
        self.assertIs(
            subject._FORMAL_WARM_RUN_WITH_WATCHDOG,
            subject.formal.warm_run_with_watchdog,
        )
        self.assertNotIn("for retry", overlay_source.lower())
        self.assertFalse(subject.CLAIM_BOUNDARY["retry_permitted"])

    def test_y_prior_a08_overlay_contamination_is_replaced_by_a09_overlay(self) -> None:
        self.assertTrue(subject.formal._STRICT_PROFILE_CAPTURE_READY)
        subject.proven_resource.configure_overlay()
        self.assertIs(subject.base.resource_gate, subject.proven_resource.resource_gate)
        subject.configure_overlay()
        subject._install_overlay_profile()
        self.assertIs(subject.base.resource_gate, subject.resource_gate)
        self.assertIs(
            subject.formal.hardened._finalize_result_total,
            subject._finalize_result_total,
        )
        self.assertIs(
            subject.formal.hardened._minimal_terminal_failure,
            subject._minimal_terminal_failure,
        )
        self.assertFalse(os.path.lexists(subject.ATTEMPT))

    def test_z_configure_overlay_is_binding_only_and_creates_no_attempt(self) -> None:
        existed_before = os.path.lexists(subject.ATTEMPT)
        subject.configure_overlay()
        existed_after = os.path.lexists(subject.ATTEMPT)
        self.assertEqual(existed_after, existed_before)
        self.assertIs(subject.formal.RUNNER, subject.RUNNER)
        self.assertEqual(subject.formal.ATTEMPT, subject.ATTEMPT)
        self.assertIs(subject.formal.paths, subject.paths)
        self.assertIs(subject.formal.check, subject.check)
        self.assertIs(
            subject.formal._install_hardened_profile, subject._install_overlay_profile
        )
        self.assertIs(subject.base.resource_gate, subject.resource_gate)
        self.assertIs(subject.formal.run_once, subject._FORMAL_RUN_ONCE)
        self.assertEqual(subject.formal.TIMEOUT_SECONDS, 900)


if __name__ == "__main__":
    unittest.main()
