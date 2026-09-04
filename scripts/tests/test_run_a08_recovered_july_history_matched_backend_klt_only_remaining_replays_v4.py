#!/usr/bin/python3.8
"""Process-free contract tests for additive A08 backend v4."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)


def load_runner():
    specification = importlib.util.spec_from_file_location("a08_backend_v4_tests", RUNNER)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class BackendV4ProcessFreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runner()
        cls.bindings = cls.module.resolve_frontend_bindings()
        cls.prior_r02 = cls.module.prior_r02_authority(cls.bindings)

    def test_01_import_is_inert_and_v4_authorities_are_absent(self):
        self.assertFalse(self.module.DEFAULT_LOCK.exists())
        self.assertFalse(self.module.BACKEND_ROOT.exists())
        self.assertFalse(self.module.RUNTIME_ROOT.exists())

    def test_02_only_r03_r05_are_executable(self):
        self.assertEqual(self.module.ITEM_ORDER, ("KLT_R03", "KLT_R04", "KLT_R05"))
        self.assertEqual(set(self.module.AUTHORIZATION_TOKENS), set(self.module.ITEM_ORDER))
        self.assertNotIn("KLT_R01", self.module.AUTHORIZATION_TOKENS)
        self.assertNotIn("KLT_R02", self.module.AUTHORIZATION_TOKENS)

    def test_03_consumed_dispositions_are_exact(self):
        self.assertEqual(
            self.module.PRIOR_R01_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT",
        )
        self.assertEqual(
            self.module.PRIOR_R02_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT",
        )
        self.assertEqual(
            self.module.R02_FAILURE_CODE,
            "OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS",
        )

    def test_04_r02_base_and_strict_audits_are_bound(self):
        prior = self.prior_r02
        self.assertEqual(prior["base_deep_terminal_evidence_audit"], "PASS")
        self.assertEqual(
            prior["v3_strict_deep_terminal_evidence_audit"],
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        )
        self.assertEqual(prior["v3_strict_deep_failure_code"],
                         "PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:KLT_R02")
        self.assertEqual(prior["artifact_contract_status"], "FAIL")
        self.assertTrue(prior["complete_artifacts"])
        self.assertEqual(len(prior["complete_artifact_identities"]), 11)

    def test_05_r02_complete_replay_is_not_admitted(self):
        prior = self.prior_r02
        self.assertTrue(prior["replay_completed"])
        self.assertTrue(prior["trajectory_complete"])
        self.assertFalse(prior["trajectory_admitted"])
        self.assertFalse(prior["artifact_accepted"])
        self.assertFalse(prior["rerun_or_replacement_permitted"])
        self.assertEqual(prior["v3_remaining_items"]["status"],
                         "PASS_V3_R03_R05_ALL_UNSTARTED")

    def test_06_preflight_waits_for_analysis_freeze_without_process(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            result = self.module.preflight_readonly()
        self.assertEqual(result["status"], "WAITING_ANALYSIS_V4_STATIC_DESIGN_FREEZE")
        self.assertFalse(result["backend_lock_build_permitted"])
        self.assertFalse(result["backend_item_launch_permitted"])

    def test_07_noncanonical_preflight_is_rejected_before_authority_work(self):
        with mock.patch.object(
            self.module, "resolve_frontend_bindings", side_effect=AssertionError("late work")
        ):
            result = self.module.preflight_readonly(Path("/tmp/not-the-v4-lock.json"))
        self.assertEqual(result["status"], "BLOCKED_PREFLIGHT")
        self.assertIn("NONCANONICAL_V4_LOCK_PATH", result["error"])

    def test_08_noncanonical_build_and_execute_are_rejected(self):
        bad = Path("/tmp/not-the-v4-lock.json")
        with self.assertRaisesRegex(RuntimeError, "NONCANONICAL_V4_LOCK_PATH"):
            self.module.build_lock(bad, self.module.BUILD_LOCK_TOKEN)
        with self.assertRaisesRegex(RuntimeError, "NONCANONICAL_V4_LOCK_PATH"):
            self.module.execute_item(
                bad, "KLT_R03", self.module.AUTHORIZATION_TOKENS["KLT_R03"]
            )

    def test_09_item_environment_binds_two_layer_signal_repair(self):
        env = self.module.item_environment("KLT_R03", self.bindings)
        self.assertEqual(env["VINS_NODE_BIN"], str(self.module.LIFECYCLE_WRAPPER))
        self.assertEqual(env["A08_REAL_VINS_NODE_BIN"], str(self.module.REAL_VINS))
        self.assertEqual(env["A08_SIGNAL_MASK_LAUNCHER_PATH"],
                         str(self.module.SIGNAL_MASK_LAUNCHER))
        self.assertEqual(env["A08_UNBLOCKED_OVERLAY_EXEC_V4"], "1")
        self.assertEqual(env["VINS_MULTIPLE_THREAD"], "0")
        self.assertEqual(env["A08_XFEAT_BACKEND_LAUNCHED_COUNT"], "0")
        self.assertEqual(env["A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED"], "0")

    def test_10_items_add_all_three_boundary_manifests(self):
        items = self.module.build_items(self.bindings, "net:[1]", "user:[2]")
        self.assertEqual(list(items), list(self.module.ITEM_ORDER))
        for item in items.values():
            outputs = set(item["expected_outputs"])
            self.assertIn("vins_lifecycle_start_manifest_v4.json", outputs)
            self.assertIn("vins_lifecycle_terminal_manifest_v4.json", outputs)
            self.assertIn("overlay_signal_mask_manifest_v4.json", outputs)
            self.assertEqual(item["scientific_boundary"]["maximum_valid_repeat_count"], 3)

    def test_11_static_paths_bind_interpreter_real_vins_and_helpers(self):
        paths = self.module.static_identity_paths()
        for key in (
            "python38", "real_vins_binary", "vins_lifecycle_wrapper_v4",
            "signal_mask_launcher_v4", "stable_owner_replay_guard_v4",
        ):
            self.assertIn(key, paths)
        self.assertEqual(paths["python38"], Path("/usr/bin/python3.8"))

    def test_12_wrapper_has_fixed_interpreter_one_popen_and_bounded_escalation(self):
        path = self.module.LIFECYCLE_WRAPPER
        source = path.read_text()
        self.assertTrue(source.startswith("#!/usr/bin/python3.8\n"))
        tree = ast.parse(source)
        popens = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "Popen"]
        self.assertEqual(len(popens), 1)
        self.assertIn("SIGINT_GRACE_SECONDS = 1.0", source)
        self.assertIn("SIGTERM_GRACE_SECONDS = 0.5", source)
        self.assertIn("SIGKILL_REAP_TIMEOUT_SECONDS = 2.0", source)
        self.assertIn("real_child_popen_count\": 1", source)
        self.assertIn("automatic_restart_count\": 0", source)

    def test_13_launcher_has_fixed_interpreter_unblock_then_single_execve(self):
        source = self.module.SIGNAL_MASK_LAUNCHER.read_text()
        self.assertTrue(source.startswith("#!/usr/bin/python3.8\n"))
        tree = ast.parse(source)
        execves = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "execve"]
        popens = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "Popen"]
        self.assertEqual(len(execves), 1)
        self.assertEqual(popens, [])
        self.assertLess(source.index("SIG_UNBLOCK"), source.index("os.execve"))
        self.assertIn("STABLE_OWNER_PARENT", source)

    def test_14_guard_delegates_through_launcher_and_never_exports(self):
        source = self.module.REPLAY_ONLY_GUARD.read_text()
        self.assertIn('"$A08_PYTHON38_PATH" "$A08_SIGNAL_MASK_LAUNCHER_PATH"', source)
        self.assertNotIn('/usr/bin/bash "$A08_OVERLAY_BACKEND_SHELL"', source)
        self.assertIn('"frontend_export_permitted": False', source)
        self.assertIn('"raw_reconstruction_permitted": False', source)
        self.assertNotIn("run_xfeat", source.lower())

    def test_15_protocol_declares_planned_five_maximum_valid_three(self):
        source = self.module.PROTOCOL.read_text()
        self.assertIn("KLT_R03, KLT_R04, KLT_R05", source)
        self.assertIn("maximum possible valid KLT count is\nthree", source)
        self.assertIn(self.module.PRIOR_R02_DISPOSITION, source)
        self.assertIn("3.5 seconds", source)

    def test_16_analysis_freeze_contract_accepts_exact_synthetic_payload(self):
        prior = self.prior_r02
        static = {
            "backend_v4_protocol": self.module.identity(self.module.PROTOCOL),
            "backend_v4_runner": self.module.identity(self.module.RUNNER),
            "backend_v4_guard": self.module.identity(self.module.REPLAY_ONLY_GUARD),
            "backend_v4_lifecycle_wrapper": self.module.identity(self.module.LIFECYCLE_WRAPPER),
            "backend_v4_signal_mask_launcher": self.module.identity(self.module.SIGNAL_MASK_LAUNCHER),
            "backend_v4_process_free_tests": self.module.identity(self.module.PROCESS_FREE_TESTS),
            "backend_v4_python38": self.module.identity(self.module.PYTHON38),
            "backend_v4_vins_node": self.module.identity(self.module.REAL_VINS),
            "analysis_v3_design_freeze": self.module.identity(self.module.ANALYSIS_V3_DESIGN_FREEZE),
            "backend_v3_execution_lock": self.module.identity(self.module.V3_LOCK),
            "v3_r02_terminal_receipt": prior["v3_terminal_receipt"],
        }
        prior_freeze = {
            "disposition": prior["disposition"], "failure_code": prior["failure_code"],
            "receipt": prior["v3_terminal_receipt"],
            "v3_execution_lock": prior["v3_execution_lock"],
            **{key: prior[key] for key in (
                "base_deep_terminal_evidence_audit",
                "v3_strict_deep_terminal_evidence_audit", "v3_strict_deep_failure_code",
                "receipt_status", "execution_integrity", "runtime_timed_out",
                "raw_return_code", "artifact_contract_status", "artifact_issue",
                "replay_manifest_semantic_status", "replay_manifest_missing_keys",
                "evidence_tree_integrity", "complete_artifacts",
                "complete_artifact_identities", "trajectory_complete",
                "trajectory_admitted", "replay_completed", "post_result_cleanup_failed",
                "rerun_or_replacement_permitted",
            )},
        }
        value = {
            "schema_version": self.module.ANALYSIS_V4_DESIGN_FREEZE_SCHEMA,
            "status": self.module.ANALYSIS_V4_DESIGN_FREEZE_STATUS,
            "static_identities": static, "prior_r02": prior_freeze,
            "design_contract": {"population_and_failure_rules": {
                "backend_item_order": ["KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"],
                "v4_backend_item_order": list(self.module.ITEM_ORDER),
                "klt_planned_count": 5, "maximum_valid_klt_count": 3,
                "r01_counts_as_valid": False, "r02_counts_as_valid": False,
                "r01_rerun_or_replacement_permitted": False,
                "r02_rerun_or_replacement_permitted": False,
            }},
            "claim_boundary": {
                "backend_v4_execution_lock_built": False, "v4_backend_items_started": 0,
                "ape_or_rpe_computed_for_v4": False, "ros_or_vins_started_for_v4": False,
            },
        }
        value["freeze_sha256"] = self.module.compact_sha256(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freeze.json"
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            with mock.patch.object(self.module, "ANALYSIS_V4_DESIGN_FREEZE", path):
                observed = self.module.collect_analysis_v4_design_freeze_binding()
        self.assertEqual(observed["status"], self.module.ANALYSIS_V4_DESIGN_FREEZE_STATUS)

    def test_17_shell_and_python_sources_are_syntax_valid_without_process_launch(self):
        ast.parse(self.module.RUNNER.read_text())
        ast.parse(self.module.LIFECYCLE_WRAPPER.read_text())
        ast.parse(self.module.SIGNAL_MASK_LAUNCHER.read_text())
        # bash -n is the only child process in this test suite and starts no experiment.
        result = subprocess.run(
            ["/usr/bin/bash", "-n", str(self.module.REPLAY_ONLY_GUARD)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_18_runner_never_authorizes_r01_or_r02_string_tokens(self):
        source = self.module.RUNNER.read_text()
        self.assertNotIn("V4_RUN_KLT_R01_EXACTLY_ONCE", source)
        self.assertNotIn("V4_RUN_KLT_R02_EXACTLY_ONCE", source)
        self.assertIn("maximum_valid_repeat_count\": 3", source)

    def test_19_shutdown_stage_state_machine_rejects_tampering(self):
        valid = [
            {"signal": "SIGINT", "sent": True, "grace_seconds": 1.0,
             "child_return_code_after_grace": None},
            {"signal": "SIGTERM", "sent": True, "grace_seconds": 0.5,
             "child_return_code_after_grace": None},
            {"signal": "SIGKILL", "sent": True, "reap_timeout_seconds": 2.0,
             "child_return_code_after_wait": -9},
        ]
        self.assertEqual(self.module.shutdown_stage_audit(valid, -9)["status"], "PASS")
        for stages, code in (
            ([], -9),
            ([{"signal": "BOGUS", "sent": True}], -9),
            ([{**valid[0], "grace_seconds": 99.0}], -2),
            (valid, 0),
        ):
            self.assertEqual(
                self.module.shutdown_stage_audit(stages, code)["status"], "FAIL"
            )
        self.assertEqual(
            self.module.wrapper_signal_sequence_audit([15])["status"], "PASS"
        )
        for tampered in ([], [2], [15, 15], [15, 2]):
            self.assertEqual(
                self.module.wrapper_signal_sequence_audit(tampered)["status"], "FAIL"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
