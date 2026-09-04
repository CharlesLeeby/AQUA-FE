#!/usr/bin/env python3
"""Contract tests for the additive A08 ROS-bootstrap correction."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "run_a08_recovered_july_natural_history_frontends_attempt002_v1.py"
)
SPEC = importlib.util.spec_from_file_location("a08_frontend_attempt002", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class Attempt002ContractTest(unittest.TestCase):
    def test_attempt001_runner_and_terminal_evidence_are_immutable(self) -> None:
        for path, expected in RUNNER.ATTEMPT1_IDENTITIES.items():
            value = RUNNER.BASE.require_identity(path, expected)
            self.assertEqual((value["size_bytes"], value["sha256"]), expected)
        self.assertTrue(RUNNER.ATTEMPT1_RUN.is_dir())
        self.assertEqual(list(RUNNER.ATTEMPT1_RUN.iterdir()), [])

    def test_only_two_ros_bootstrap_values_are_added(self) -> None:
        before = RUNNER.ORIGINAL_ENVIRONMENT_UPDATES()
        after = RUNNER.environment_updates()
        observed = {
            key: (before.get(key), after.get(key))
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        }
        self.assertEqual(
            observed,
            {
                "ROS_DISTRO": (None, "noetic"),
                "ROS_MASTER_URI": (None, "http://localhost:11311"),
            },
        )

    def test_algorithm_command_is_unchanged_and_namespace_is_additive(self) -> None:
        command, environment = RUNNER.BASE.command_for("klt")
        attempt001 = json.loads(
            (RUNNER.BASE.FRONTEND_ROOT / "klt_process_start_claim_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(command, attempt001["command"])
        self.assertNotEqual(environment["TAG"], attempt001["environment"]["TAG"])
        self.assertIn("attempt002_rosseed", environment["TAG"])
        self.assertNotEqual(
            RUNNER.BASE.KLT_RECEIPT,
            RUNNER.BASE.FRONTEND_ROOT / "klt_export_receipt_v1.json",
        )

    def test_claim_context_proves_the_exact_permitted_delta(self) -> None:
        _, environment = RUNNER.BASE.command_for("klt")
        context = RUNNER.infrastructure_context("klt", environment)
        self.assertEqual(context["campaign_supervisor_launch_count_including_attempt002"], 2)
        self.assertEqual(context["attempt001_data_processing_exporter_invocation_count"], 0)
        self.assertEqual(context["algorithmic_export_attempt_index"], 1)
        self.assertEqual(context["automatic_retry_count"], 0)
        self.assertTrue(context["algorithm_command_unchanged"])
        self.assertEqual(
            set(context["observed_environment_delta"]),
            {"ROS_DISTRO", "ROS_MASTER_URI", "TAG"},
        )

    def test_set_u_source_chain_and_exact_hook_order_pass(self) -> None:
        value = RUNNER.strict_source_chain_fingerprint()
        self.assertTrue(value["set_euo_pipefail_verified"])
        self.assertTrue(value["bootstrap_reference_equivalence"]["equivalent_after_source"])
        self.assertEqual(len(value["exact_sourced_closure_files"]), 23)
        self.assertEqual(len(value["pinned_setup_superset_files"]), 39)
        self.assertEqual(value["hook_source_rounds"], 2)
        self.assertEqual(
            value["generated_setup_snapshots"]["ros_noetic"]["hook_paths_in_order"],
            RUNNER.EXPECTED_HOOK_PATHS,
        )
        self.assertEqual(
            value["generated_setup_snapshots"]["vins_devel_after_ros"]["hook_paths_in_order"],
            RUNNER.EXPECTED_HOOK_PATHS,
        )

    def test_fixed_inputs_add_both_runners_amendment_and_failure(self) -> None:
        value = RUNNER.fixed_inputs()
        for path in (*RUNNER.ATTEMPT1_IDENTITIES, SCRIPT.resolve()):
            self.assertIn(str(path), value)


if __name__ == "__main__":
    unittest.main()
