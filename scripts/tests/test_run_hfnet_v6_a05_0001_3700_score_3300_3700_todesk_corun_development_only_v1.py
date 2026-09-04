#!/usr/bin/env python3
"""Process-free tests for the additive A05 ToDesk co-run overlay."""

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
    run_hfnet_v6_a05_0001_3700_score_3300_3700_todesk_corun_development_only_v1
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

    def test_frozen_controller_and_runner_freeze_identities(self) -> None:
        rows = (
            (
                subject.FORMAL_RUNNER,
                subject.FORMAL_RUNNER_SIZE,
                subject.FORMAL_RUNNER_SHA256,
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
        self.assertFalse(freeze["claims"]["attempt_prepared"])
        self.assertFalse(freeze["claims"]["hfnet_started"])

    def test_a09_success_precedent_proves_3072_floor_on_same_4gb_gpu(self) -> None:
        value = subject.validate_a09_success_precedent()
        self.assertEqual(value["gpu_total_mib"], 4096)
        self.assertEqual(value["minimum_free_mib"], 3072)
        self.assertEqual(value["observed_success_lock_free_mib"], 3204)

    def test_floor_cannot_be_lowered_to_unproven_corun_draft(self) -> None:
        self.assertEqual(subject.MIN_GPU_FREE_MIB, 3072)
        with self.assertRaisesRegex(
            subject.base.ContractError, "CORUN_GPU_FLOOR_NOT_FROZEN_3072_MIB"
        ):
            subject.resource_gate(2800)

    def test_todesk_and_ros_vins_are_allowed_when_safe_memory_remains(self) -> None:
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
            with mock.patch.object(subject.subprocess, "run", side_effect=responses) as run:
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertTrue(value["ready"])
        self.assertEqual(value["errors"], [])
        self.assertEqual(len(value["allowed_compute_applications"]), 2)
        self.assertTrue(value["cpu_ros_vins_processes_permitted"])
        self.assertEqual(run.call_count, 2)

    def test_current_low_memory_shape_fails_closed_before_any_hfnet_popen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            gpu_information = self._gpu_information(root)
            responses = [
                self._completed("4096, 3054, 1042\n"),
                self._completed("2001, python3, 1500\n2002, python3, 764\n"),
            ]
            with mock.patch.object(subject.subprocess, "run", side_effect=responses):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertFalse(value["ready"])
        self.assertIn(
            "GPU_FREE_MEMORY_BELOW_FORMAL_A09_SUCCESS_FLOOR", value["errors"]
        )
        self.assertEqual(value["gpu_platform"]["minimum_free_mib"], 3072)

    def test_competing_learned_compute_application_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            gpu_information = self._gpu_information(root)
            responses = [
                self._completed("4096, 700, 3300\n"),
                self._completed(
                    "42, mono_inertial_euroc_headless_v3, 600\n"
                ),
            ]
            with mock.patch.object(subject.subprocess, "run", side_effect=responses):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertFalse(value["ready"])
        self.assertIn(
            "FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_COMPUTE_APP_PRESENT",
            value["errors"],
        )

    def test_python_learned_job_is_found_by_proc_cmdline_but_vins_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc_root = Path(directory)
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
            conflicts = subject.scan_forbidden_processes(proc_root)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["pid"], 401)
        self.assertEqual(conflicts[0]["reason"], "LEARNED_BASELINE_PROCESS")

    def test_wrong_gpu_model_or_capacity_fails_even_with_enough_reported_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            gpu_information = self._gpu_information(root, "NVIDIA Mock GPU")
            responses = [
                self._completed("8192, 100, 8092\n"),
                self._completed(""),
            ]
            with mock.patch.object(subject.subprocess, "run", side_effect=responses):
                value = subject.resource_gate(
                    proc_root=proc_root, gpu_information=gpu_information
                )
        self.assertFalse(value["ready"])
        self.assertIn("GPU_MODEL_NOT_FROZEN_GTX1650", value["errors"])
        self.assertIn("GPU_TOTAL_MEMORY_NOT_FROZEN_4096_MIB", value["errors"])

    def test_only_resource_policy_and_namespace_are_overlaid(self) -> None:
        selection = subject._expected_selection()
        formal_selection = subject._FORMAL_EXPECTED_SELECTION()
        for key, value in formal_selection.items():
            self.assertEqual(selection[key], value)
        self.assertEqual(selection["execution_profile"], "TODESK_CORUN_DEVELOPMENT_ONLY")
        self.assertFalse(selection["resource_isolation"])
        self.assertEqual(subject.TIMEOUT_SECONDS, 600)
        self.assertEqual(subject.TIMEOUT_SECONDS, subject.formal.TIMEOUT_SECONDS)
        self.assertIs(subject.INPUT_ROOT, subject.formal.INPUT_ROOT)
        self.assertIs(subject.INPUT_MANIFEST, subject.formal.INPUT_MANIFEST)
        self.assertIs(subject.INPUT_AUDIT, subject.formal.INPUT_AUDIT)
        self.assertEqual(subject.INPUT_PAYLOAD_SHA256, subject.formal.INPUT_PAYLOAD_SHA256)
        self.assertNotEqual(subject.ATTEMPT, subject.formal.ATTEMPT)
        self.assertIs(subject._FORMAL_FINALIZE_RESULT, subject.formal._finalize_result_total)
        self.assertIs(subject._FORMAL_MINIMAL_FAILURE, subject.formal._minimal_terminal_failure)

    def test_claim_and_comparison_boundaries_forbid_accuracy_runtime_and_retry(self) -> None:
        comparison = subject._expected_comparison_boundary()
        self.assertTrue(comparison["runability_only"])
        self.assertFalse(comparison["accuracy_gate_open"])
        self.assertFalse(comparison["ranking_authorized"])
        self.assertFalse(comparison["runtime_or_realtime_claim_permitted"])
        self.assertFalse(subject.CLAIM_BOUNDARY["retry_permitted"])
        self.assertFalse(subject.CLAIM_BOUNDARY["accuracy_claim_authorized"])
        self.assertFalse(subject.CLAIM_BOUNDARY["runtime_or_realtime_claim_authorized"])
        self.assertFalse(subject.CLAIM_BOUNDARY["formal_paper_claim_authorized"])

    def test_terminal_decoration_does_not_turn_duration_into_runtime_evidence(self) -> None:
        value = subject._decorate_terminal(
            {
                "status": "PASS_DEVELOPMENT_RUNABILITY",
                "execution": {"duration_seconds": 123.0},
                "claim_boundary": {"development_only": True},
            }
        )
        self.assertEqual(value["execution"]["duration_seconds"], 123.0)
        self.assertFalse(
            value["claim_boundary"]["runtime_or_realtime_claim_authorized"]
        )
        self.assertFalse(
            value["resource_context"]["runtime_or_realtime_claim_permitted"]
        )

    def test_overlay_test_and_full_code_authority_are_frozen(self) -> None:
        self.assertTrue(subject.RUNNER_TEST_PIN_READY)
        authority = subject.validate_code_authority()
        self.assertEqual(
            authority["corun_overlay_test"]["sha256"], subject.RUNNER_TEST_SHA256
        )
        self.assertEqual(
            authority["frozen_a05_controller"]["sha256"],
            subject.FORMAL_RUNNER_SHA256,
        )

    def test_z_configure_overlay_is_binding_only_and_creates_no_attempt(self) -> None:
        existed_before = os.path.lexists(subject.ATTEMPT)
        subject.configure_overlay()
        existed_after = os.path.lexists(subject.ATTEMPT)
        self.assertEqual(existed_after, existed_before)
        self.assertIs(subject.formal.RUNNER, subject.RUNNER)
        self.assertEqual(subject.formal.ATTEMPT, subject.ATTEMPT)
        self.assertIs(subject.base.resource_gate, subject.resource_gate)
        self.assertIs(subject.formal.run_once, subject._FORMAL_RUN_ONCE)
        self.assertIs(
            subject.formal.warm_run_with_watchdog,
            subject._FORMAL_WARM_RUN_WITH_WATCHDOG,
        )
        self.assertEqual(subject.formal.TIMEOUT_SECONDS, 600)


if __name__ == "__main__":
    unittest.main()
