#!/usr/bin/python3.8
"""Process-free contract tests for additive A08 backend v5.

The suite may read and reconstruct frozen evidence but never starts ROS, VINS,
or a formal replay. Its only child process is ``bash -n`` for guard syntax.
"""

import ast
import copy
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
    "remaining_replays_v5.py"
)
ANALYSIS_RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v5.py"


def load_module(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class BackendV5ProcessFreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(RUNNER, "a08_backend_v5_process_free_tests")
        cls.bindings = cls.module.resolve_frontend_bindings()
        cls.prior = cls.module.prior_r03_authority(cls.bindings)

    def test_01_import_is_inert_and_campaign_is_unstarted(self):
        self.assertFalse(self.module.DEFAULT_LOCK.exists())
        self.assertFalse(self.module.BACKEND_ROOT.exists())
        self.assertFalse(self.module.RUNTIME_ROOT.exists())
        for item_id in self.module.ITEM_ORDER:
            workspace = (
                self.module.OVERLAY_RUN_ROOT
                / self.module.arm_spec(item_id)["run_leaf"]
            )
            self.assertFalse(workspace.exists())

    def test_02_only_r04_r05_are_executable(self):
        self.assertEqual(self.module.ITEM_ORDER, ("KLT_R04", "KLT_R05"))
        self.assertEqual(set(self.module.AUTHORIZATION_TOKENS), set(self.module.ITEM_ORDER))
        for consumed in ("KLT_R01", "KLT_R02", "KLT_R03"):
            self.assertNotIn(consumed, self.module.AUTHORIZATION_TOKENS)

    def test_03_all_consumed_dispositions_and_failures_are_exact(self):
        self.assertEqual(
            self.module.PRIOR_R01_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT",
        )
        self.assertEqual(
            self.module.R01_FAILURE_CODE,
            "ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9",
        )
        self.assertEqual(
            self.module.PRIOR_R02_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT",
        )
        self.assertEqual(
            self.module.R02_FAILURE_CODE,
            "OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS",
        )
        self.assertEqual(
            self.module.PRIOR_R03_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_RUNTIME_ENV_AUDIT_CONTRACT_MISMATCH_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT",
        )
        self.assertEqual(
            self.module.R03_FAILURE_CODE,
            "LOCKED_ITEM_ENV_OMITTED_OVERLAY_ROS_HOSTNAME_LOCALHOST_LIFECYCLE_AUDIT_MISMATCH",
        )

    def test_04_r03_is_exact_complete_but_permanently_unaccepted_evidence(self):
        prior = self.prior
        self.assertEqual(prior["v4_base_artifact_audit"], "PASS")
        self.assertEqual(prior["v4_artifact_receipt_reconstruction"], "PASS")
        self.assertEqual(prior["v4_base_prior_failure_code"],
                         "PRIOR_EXECUTION_INTEGRITY:KLT_R03")
        self.assertEqual(prior["v4_strict_prior_failure_code"],
                         "PRIOR_EXECUTION_INTEGRITY:KLT_R03")
        self.assertTrue(prior["complete_artifacts"])
        self.assertEqual(len(prior["complete_artifact_identities"]), 14)
        self.assertEqual(prior["trajectory_rows"], 2319)
        self.assertTrue(prior["replay_completed"])
        self.assertFalse(prior["trajectory_admitted"])
        self.assertFalse(prior["artifact_accepted"])
        self.assertFalse(prior["rerun_or_replacement_permitted"])
        self.assertEqual(prior["artifact_integrity_issues"],
                         ["VINS_LIFECYCLE_MANIFEST_CONTRACT"])

    def test_05_r03_proves_ros_hostname_is_the_only_selected_env_delta(self):
        prior = self.prior
        self.assertFalse(prior["locked_item_ros_hostname_present"])
        self.assertEqual(prior["observed_overlay_ros_hostname"], "localhost")
        self.assertEqual(prior["runtime_lifecycle_ros_hostname"], "localhost")
        self.assertTrue(prior["all_other_selected_scientific_environment_equal"])
        self.assertEqual(prior["only_permitted_v5_environment_addition"],
                         {"ROS_HOSTNAME": "localhost"})

    def test_06_old_v4_r04_r05_and_new_v5_locations_are_untouched(self):
        old = self.prior["v4_remaining_items"]
        self.assertEqual(old["status"], "PASS_V4_R04_R05_ALL_UNSTARTED")
        for paths in old["items"].values():
            for value in paths.values():
                self.assertFalse(Path(value).exists())
        self.module.require_campaign_unstarted()

    def test_07_preflight_waits_for_analysis_freeze_without_process(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                mock.patch.object(
                    self.module, "prior_r03_authority", return_value=self.prior
                ):
            result = self.module.preflight_readonly()
        self.assertEqual(result["status"], "WAITING_ANALYSIS_V5_STATIC_DESIGN_FREEZE")
        self.assertFalse(result["backend_lock_build_permitted"])
        self.assertFalse(result["backend_item_launch_permitted"])

    def test_08_noncanonical_paths_are_rejected_before_authority_or_process(self):
        bad = Path("/tmp/not-the-a08-backend-v5-lock.json")
        with mock.patch.object(
            self.module, "resolve_frontend_bindings", side_effect=AssertionError("late")
        ):
            result = self.module.preflight_readonly(bad)
        self.assertEqual(result["status"], "BLOCKED_PREFLIGHT")
        self.assertIn("NONCANONICAL_V5_LOCK_PATH", result["error"])
        with self.assertRaisesRegex(RuntimeError, "NONCANONICAL_V5_LOCK_PATH"):
            self.module.build_lock(bad, self.module.BUILD_LOCK_TOKEN)
        with self.assertRaisesRegex(RuntimeError, "NONCANONICAL_V5_LOCK_PATH"):
            self.module.execute_item(
                bad, "KLT_R04", self.module.AUTHORIZATION_TOKENS["KLT_R04"]
            )

    def test_09_locked_selected_environment_has_exactly_one_added_key(self):
        for item_id in self.module.ITEM_ORDER:
            old = self.module.V4.item_environment(item_id, self.bindings)
            new = self.module.item_environment(item_id, self.bindings)
            old_selected = {
                key: old[key] for key in self.module.SCIENTIFIC_ENV_KEYS if key in old
            }
            new_selected = {
                key: new[key] for key in self.module.SCIENTIFIC_ENV_KEYS if key in new
            }
            self.assertNotIn("ROS_HOSTNAME", old_selected)
            self.assertEqual(new_selected, {**old_selected, "ROS_HOSTNAME": "localhost"})
            self.assertEqual(new["VINS_MULTIPLE_THREAD"], "0")
            self.assertEqual(new["VINS_NODE_BIN"], str(self.module.LIFECYCLE_WRAPPER))
            self.assertEqual(new["A08_REAL_VINS_NODE_BIN"], str(self.module.REAL_VINS))

    def test_10_items_bind_r04_r05_roots_and_all_lifecycle_manifests(self):
        items = self.module.build_items(self.bindings, "net:[1]", "user:[2]")
        self.assertEqual(list(items), ["KLT_R04", "KLT_R05"])
        for item_id, item in items.items():
            self.assertEqual(item["method"], "klt")
            self.assertIn("remaining_replays_v5", item["output_dir"])
            self.assertTrue(item["workspace_link"].endswith(
                self.module.arm_spec(item_id)["run_leaf"]
            ))
            self.assertEqual(item["scientific_boundary"]["maximum_valid_repeat_count"], 2)
            outputs = set(item["expected_outputs"])
            self.assertTrue({
                "vins_lifecycle_start_manifest_v4.json",
                "vins_lifecycle_terminal_manifest_v4.json",
                "overlay_signal_mask_manifest_v4.json",
            }.issubset(outputs))

    def test_11_static_paths_bind_v5_and_reused_frozen_helpers(self):
        paths = self.module.static_identity_paths()
        for key in (
            "runner", "protocol", "stable_owner_replay_guard_v5",
            "process_free_tests", "v4_runner", "v4_protocol", "v4_guard",
            "v4_lifecycle_wrapper", "v4_signal_mask_launcher",
            "v4_process_free_tests", "v4_execution_lock",
            "analysis_v4_design_freeze", "python38", "real_vins_binary",
        ):
            self.assertIn(key, paths)
        values = self.module.collect_static_identities()
        self.assertEqual(values["v4_lifecycle_wrapper"],
                         self.module.identity(self.module.LIFECYCLE_WRAPPER))
        self.assertEqual(values["v4_signal_mask_launcher"],
                         self.module.identity(self.module.SIGNAL_MASK_LAUNCHER))

    def test_12_corrected_nested_two_shell_lineage_accepts_frozen_r03(self):
        lock, _ = self.module.v4_lock_authority(self.bindings)
        item = lock["items"]["KLT_R03"]
        receipt, _ = self.module.stable_json(
            self.module.V4.BACKEND_ROOT / "KLT_R03" / self.module.V4.RECEIPT_NAME
        )
        audit = self.module.nested_runtime_lineage_audit(receipt, item, lock)
        self.assertEqual(audit["status"], "PASS", audit)
        self.assertTrue(audit["checks"]["nested_not_direct"])
        self.assertFalse(audit["direct_child_claim"])
        shell = audit["shell_authority"]
        self.assertTrue(shell["nested_shell_process_chain_required"])
        self.assertFalse(shell["direct_launcher_to_wrapper_claim_permitted"])
        self.assertIn("ROS_HOSTNAME=localhost", shell["inner_line_925"])
        tampered = copy.deepcopy(receipt)
        tampered["runtime"]["pid"] += 1
        rejected = self.module.nested_runtime_lineage_audit(tampered, item, lock)
        self.assertEqual(rejected["status"], "FAIL")
        self.assertIn("guard_owner_runtime", rejected["failure_codes"])
        self.assertIn("mask_owner_runtime", rejected["failure_codes"])

    def test_13_guard_is_v5_bound_delegates_once_and_never_exports_frontend(self):
        source = self.module.REPLAY_ONLY_GUARD.read_text()
        self.assertIn("backend_klt_only_remaining_replays_v5", source)
        self.assertIn("A08_KLT_ONLY_REMAINING_REPLAYS_V5", source)
        self.assertIn('"$A08_PYTHON38_PATH" "$A08_SIGNAL_MASK_LAUNCHER_PATH"', source)
        self.assertNotIn('/usr/bin/bash "$A08_OVERLAY_BACKEND_SHELL"', source)
        self.assertIn('"frontend_export_permitted": False', source)
        self.assertIn('"raw_reconstruction_permitted": False', source)
        self.assertNotIn("run_xfeat", source.lower())

    def test_14_protocol_declares_exact_population_amendment_and_no_retry(self):
        source = self.module.PROTOCOL.read_text()
        for value in (
            "KLT_R04", "KLT_R05", "maximum possible number of valid KLT repeats is two",
            self.module.PRIOR_R03_DISPOSITION, self.module.R03_FAILURE_CODE,
            "ROS_HOSTNAME=localhost", "two-shell chain", "Automatic retries are zero",
            "Replacement repeats are forbidden", "coordinate-wise median",
        ):
            self.assertIn(value, source)

    def test_15_analysis_freeze_cross_contract_accepts_live_candidate_payload(self):
        analysis = load_module(ANALYSIS_RUNNER, "a08_analysis_v5_for_backend_test")
        payload = analysis.build_design_freeze_payload(
            "2026-08-28T00:00:00+00:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design-freeze-v5.json"
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            with mock.patch.object(self.module, "ANALYSIS_V5_DESIGN_FREEZE", path), \
                    mock.patch.object(
                        self.module, "prior_r03_authority", return_value=self.prior
                    ):
                observed = self.module.collect_analysis_v5_design_freeze_binding()
            for section in (
                "sealed_support", "klt_frontend", "excluded_xfeat", "evo_authority"
            ):
                tampered = copy.deepcopy(payload)
                tampered[section]["tampered"] = True
                unsigned = dict(tampered); unsigned.pop("freeze_sha256", None)
                tampered["freeze_sha256"] = self.module.compact_sha256(unsigned)
                path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
                with mock.patch.object(
                    self.module, "ANALYSIS_V5_DESIGN_FREEZE", path
                ), self.assertRaises(RuntimeError):
                    self.module.collect_analysis_v5_design_freeze_binding()
            tampered = copy.deepcopy(payload)
            tampered["static_identities"]["primary_evaluator"]["sha256"] = "0" * 64
            unsigned = dict(tampered); unsigned.pop("freeze_sha256", None)
            tampered["freeze_sha256"] = self.module.compact_sha256(unsigned)
            path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
            with mock.patch.object(
                self.module, "ANALYSIS_V5_DESIGN_FREEZE", path
            ), self.assertRaises(RuntimeError):
                self.module.collect_analysis_v5_design_freeze_binding()
        self.assertEqual(observed["status"], self.module.ANALYSIS_V5_DESIGN_FREEZE_STATUS)
        self.assertEqual(observed["prior_r03"]["trajectory_admitted"], False)
        self.assertEqual(observed["v5_environment_amendment"][
            "only_permitted_scientific_environment_addition"
        ], {"ROS_HOSTNAME": "localhost"})

    def test_16_contract_core_retains_five_planned_and_at_most_two_valid(self):
        fake_freeze = {"identity": {"path": "synthetic"}}
        with mock.patch.object(
            self.module, "collect_analysis_v5_design_freeze_binding",
            return_value=fake_freeze,
        ):
            core = self.module.contract_core(
                self.bindings, self.module.collect_static_identities(),
                "net:[1]", "user:[2]",
            )
        self.assertEqual(core["item_order"], ["KLT_R04", "KLT_R05"])
        self.assertEqual(core["policy"]["original_declared_repeat_count"], 5)
        self.assertEqual(core["policy"]["v5_executable_repeat_count"], 2)
        self.assertEqual(core["policy"]["maximum_valid_repeat_count"], 2)
        self.assertEqual(core["policy"]["automatic_retry_count"], 0)
        self.assertFalse(core["policy"]["replacement_repeat_permitted"])
        self.assertEqual(core["scientific_environment_amendment"][
            "only_permitted_addition"
        ], {"ROS_HOSTNAME": "localhost"})

    def test_17_source_and_guard_syntax_are_valid_without_experiment_process(self):
        ast.parse(self.module.RUNNER.read_text())
        ast.parse(self.module.LIFECYCLE_WRAPPER.read_text())
        ast.parse(self.module.SIGNAL_MASK_LAUNCHER.read_text())
        result = subprocess.run(
            ["/usr/bin/bash", "-n", str(self.module.REPLAY_ONLY_GUARD)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_18_no_consumed_item_authorization_and_single_supervisor_launch_policy(self):
        source = self.module.RUNNER.read_text()
        for consumed in ("R01_EXACTLY_ONCE", "R02_EXACTLY_ONCE", "R03_EXACTLY_ONCE"):
            self.assertNotIn(consumed, source)
        self.assertIn('"single_supervisor_popen_per_item": True', source)
        self.assertIn('"automatic_retry_count": 0', source)
        self.assertIn('"maximum_valid_repeat_count": 2', source)

    def test_19_guard_audit_rejects_each_restored_inherited_gate_tamper(self):
        item = self.module.build_items(
            self.bindings, "net:[1]", "user:[2]"
        )["KLT_R04"]
        frozen_guard, _ = self.module.stable_json(
            self.module.V4.BACKEND_ROOT / "KLT_R03"
            / "replay_only_guard_manifest.json"
        )
        valid = copy.deepcopy(frozen_guard)
        valid.update({
            "schema_version": "aqua-fe-a08-replay-only-stable-owner-fd-guard-v5",
            "item_id": "KLT_R04", "output_dir": item["output_dir"],
            "workspace_link": item["workspace_link"],
            "prior_dispositions": {
                "KLT_R01": self.module.PRIOR_R01_DISPOSITION,
                "KLT_R02": self.module.PRIOR_R02_DISPOSITION,
                "KLT_R03": self.module.PRIOR_R03_DISPOSITION,
            },
            "runtime_environment_contract": {
                "locked_ros_hostname": "localhost",
                "frozen_overlay_export_line": "export ROS_HOSTNAME=localhost",
                "only_scientific_environment_addition_from_v4": {
                    "ROS_HOSTNAME": "localhost"
                },
            },
        })
        valid["vins_lifecycle"]["start_manifest"] = item["env"][
            "A08_VINS_LIFECYCLE_START_MANIFEST"
        ]
        valid["vins_lifecycle"]["terminal_manifest"] = item["env"][
            "A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"
        ]
        valid["signal_mask_launcher"]["manifest"] = item["env"][
            "A08_SIGNAL_MASK_MANIFEST"
        ]
        mutations = {
            "delegated_shell": lambda value: value.__setitem__(
                "delegated_backend_shell", "/tampered"
            ),
            "history": lambda value: value["history"].__setitem__("sequence", 99),
            "policy": lambda value: value["policy"].__setitem__(
                "frontend_export_permitted", True
            ),
            "runtime_environment": lambda value: value[
                "runtime_environment_contract"
            ].__setitem__("locked_ros_hostname", "tampered"),
            "lifecycle_policy": lambda value: value["vins_lifecycle"].__setitem__(
                "real_child_launch_count", 2
            ),
            "launcher_python": lambda value: value["signal_mask_launcher"][
                "python38"
            ].__setitem__("path", "/tampered"),
            "launcher_bash": lambda value: value["signal_mask_launcher"][
                "delegated_bash"
            ].__setitem__("path", "/tampered"),
            "launcher_overlay": lambda value: value["signal_mask_launcher"][
                "frozen_overlay_shell"
            ].__setitem__("path", "/tampered"),
            "launcher_policy": lambda value: value["signal_mask_launcher"].__setitem__(
                "unblocked_before_overlay_exec", [2, 15]
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guard.json"
            path.write_text(json.dumps(valid, indent=2, sort_keys=True) + "\n")
            accepted = self.module.replay_guard_manifest_audit(path, item)
            self.assertEqual(accepted["status"], "PASS", accepted)
            for expected_failure, mutate in mutations.items():
                tampered = copy.deepcopy(valid)
                mutate(tampered)
                path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
                rejected = self.module.replay_guard_manifest_audit(path, item)
                self.assertEqual(rejected["status"], "FAIL", rejected)
                self.assertIn(expected_failure, rejected["failure_codes"])

    def test_20_engine_callbacks_and_klt_receipt_authority_are_executable(self):
        self.module._configure_engine()
        self.assertEqual(
            self.module.ENGINE.KLT_RECEIPT, self.module.V4.V3.KLT_RECEIPT
        )
        self.assertIs(
            self.module.ENGINE.replay_guard_manifest_audit,
            self.module.replay_guard_manifest_audit,
        )
        self.assertIs(self.module.ENGINE.prior_receipt, self.module.prior_receipt)
        sentinel = (0, {"status": "PROCESS_FREE_CALLBACK_SPY"})
        with mock.patch.object(
            self.module.ENGINE, "execute_item", return_value=sentinel
        ) as execute:
            observed = self.module.execute_item(
                self.module.DEFAULT_LOCK, "KLT_R05",
                self.module.AUTHORIZATION_TOKENS["KLT_R05"],
            )
        self.assertEqual(observed, sentinel)
        execute.assert_called_once_with(
            self.module.DEFAULT_LOCK, "KLT_R05",
            self.module.AUTHORIZATION_TOKENS["KLT_R05"],
        )

    def test_21_r05_sequence_accepts_terminal_failure_but_blocks_integrity_failure(self):
        self.module._configure_engine()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = {
                "item_order": ["KLT_R04", "KLT_R05"],
                "items": {
                    item: {
                        "item_id": item,
                        "output_dir": str(root / "output" / item),
                        "workspace_link": str(root / "workspace" / item),
                    }
                    for item in ("KLT_R04", "KLT_R05")
                },
            }
            terminal_failure = {
                "status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
                "execution_integrity": {"status": "PASS"},
            }
            with mock.patch.object(
                self.module.ENGINE, "RUNTIME_ROOT", root / "runtime"
            ), mock.patch.object(
                self.module.ENGINE, "prior_receipt", return_value=terminal_failure
            ) as prior:
                self.module.ENGINE.enforce_sequence(lock, {"path": "lock"}, "KLT_R05")
            prior.assert_called_once_with(
                {"path": "lock"}, lock["items"]["KLT_R04"]
            )
            with mock.patch.object(
                self.module.ENGINE, "RUNTIME_ROOT", root / "runtime"
            ), mock.patch.object(
                self.module.ENGINE, "prior_receipt",
                side_effect=self.module.BackendProtocolError(
                    "PRIOR_EXECUTION_INTEGRITY:KLT_R04"
                ),
            ), self.assertRaisesRegex(
                RuntimeError, "PRIOR_EXECUTION_INTEGRITY:KLT_R04"
            ):
                self.module.ENGINE.enforce_sequence(
                    lock, {"path": "lock"}, "KLT_R05"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
