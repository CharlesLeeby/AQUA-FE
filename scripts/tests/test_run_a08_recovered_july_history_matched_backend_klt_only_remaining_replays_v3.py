#!/usr/bin/env python3
"""Process-free tests for the additive A08 KLT R02--R05 backend v3."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


RUNNER_PATH = Path(__file__).resolve().parents[1] / (
    "run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
SPEC = importlib.util.spec_from_file_location("a08_klt_remaining_v3_tested", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def accepted_bindings() -> dict:
    return {
        "klt": {
            "features_bag": {
                "path": "/accepted/klt/features.bag", "size_bytes": 11,
                "sha256": "a" * 64,
            },
            "frontend_metrics": {
                "path": "/accepted/klt/frontend_metrics.csv", "size_bytes": 12,
                "sha256": "b" * 64,
            },
            "camera_config": {
                "path": "/accepted/klt/camera.yaml", "size_bytes": 13,
                "sha256": "c" * 64,
            },
            "accepted_receipt": {
                "path": str(RUNNER.KLT_RECEIPT), "size_bytes": 14,
                "sha256": "d" * 64,
            },
        },
        "excluded_xfeat": {
            "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
            "accepted_receipt_present": False,
            "backend_launched_count": 0,
            "learning_contribution_claim_permitted": False,
        },
    }


def make_analysis_freeze(path: Path) -> dict:
    receipt = RUNNER.identity(
        RUNNER.V2.BACKEND_ROOT / "KLT_R01" / RUNNER.V2.RECEIPT_NAME
    )
    v2_lock = RUNNER.identity(RUNNER.V2_LOCK)
    value = {
        "schema_version": RUNNER.ANALYSIS_V3_DESIGN_FREEZE_SCHEMA,
        "status": RUNNER.ANALYSIS_V3_DESIGN_FREEZE_STATUS,
        "static_identities": {
            "backend_v3_protocol": RUNNER.identity(RUNNER.PROTOCOL),
            "backend_v3_runner": RUNNER.identity(RUNNER.RUNNER),
            "backend_v3_guard": RUNNER.identity(RUNNER.REPLAY_ONLY_GUARD),
            "backend_v3_process_free_tests": RUNNER.identity(RUNNER.PROCESS_FREE_TESTS),
            "v2_r01_terminal_receipt": receipt,
            "v2_execution_lock": v2_lock,
        },
        "prior_r01": {
            "disposition": RUNNER.PRIOR_R01_DISPOSITION,
            "failure_code": RUNNER.R01_INFRASTRUCTURE_FAILURE_CODE,
            "receipt": receipt,
            "v2_execution_lock": v2_lock,
            "v2_deep_terminal_evidence_audit": "PASS",
            "vio_empty": True,
            "ape_empty": True,
            "artifact_accepted": False,
            "rerun_or_replacement_permitted": False,
        },
        "design_contract": {
            "population_and_failure_rules": {
                "backend_item_order": [
                    "KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"
                ],
                "v3_backend_item_order": list(RUNNER.ITEM_ORDER),
                "klt_planned_count": 5,
                "maximum_valid_klt_count": 4,
                "r01_disposition": RUNNER.PRIOR_R01_DISPOSITION,
                "r01_counts_as_valid": False,
                "r01_rerun_or_replacement_permitted": False,
            },
        },
        "claim_boundary": {
            "backend_v3_execution_lock_built": False,
            "v3_backend_items_started": 0,
            "ape_or_rpe_computed": False,
            "ros_or_vins_started_for_v3": False,
        },
    }
    value["freeze_sha256"] = RUNNER.compact_sha256(value)
    write_json(path, value)
    return value


def guard_manifest(item: dict, owner: int = 424242) -> dict:
    expected = {
        "ground_truth": (
            item["env"]["GT_TXT"], int(item["env"]["A08_GT_SIZE_BYTES"]),
            item["env"]["A08_GT_SHA256"], 6,
        ),
        "raw_bag": (
            item["env"]["RAW_BAG"], int(item["env"]["A08_RAW_BAG_SIZE_BYTES"]),
            item["env"]["A08_RAW_BAG_SHA256"], 7,
        ),
        "raw_archive": (
            item["env"]["RAW_TAR"], int(item["env"]["A08_RAW_TAR_SIZE_BYTES"]),
            item["env"]["A08_RAW_TAR_SHA256"], 8,
        ),
        "feature_bag": (
            item["env"]["FEATURE_BAG_OVERRIDE"],
            int(item["env"]["A08_FEATURE_BAG_SIZE_BYTES"]),
            item["env"]["A08_FEATURE_BAG_SHA256"], 9,
        ),
        "frontend_metrics": (
            item["env"]["A08_FRONTEND_METRICS"],
            int(item["env"]["A08_FRONTEND_METRICS_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_METRICS_SHA256"], 10,
        ),
        "camera_config": (
            item["env"]["A08_FRONTEND_CAMERA_CONFIG"],
            int(item["env"]["A08_FRONTEND_CAMERA_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_CAMERA_SHA256"], 11,
        ),
    }
    return {
        "schema_version": "aqua-fe-a08-replay-only-stable-owner-fd-guard-v3",
        "status": "PASS_BEFORE_DELEGATED_BACKEND",
        "item_id": item["item_id"],
        "output_dir": item["output_dir"],
        "workspace_link": item["workspace_link"],
        "delegated_backend_shell": str(RUNNER.ENGINE.BACKEND_SHELL),
        "sealed_fd_owner_pid": owner,
        "prior_r01_disposition": RUNNER.PRIOR_R01_DISPOSITION,
        "history": {
            "dataset": "aqualoc_archaeo", "sequence": 8,
            "start_source_index": 0, "end_source_index": 4660,
            "every_n": 2, "method": "klt",
        },
        "policy": {
            "frontend_export_permitted": False,
            "raw_reconstruction_permitted": False,
            "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
            "delegated_data_environment_values_are_stable_owner_fd_paths": True,
            "all_delegated_data_paths_are_stable_owner_fd_paths": True,
            "child_self_fd_paths_forbidden": True,
            "owner_remains_alive_during_delegated_backend": True,
            "published_before_delegated_backend": True,
        },
        "bound_inputs": {
            label: {
                "accepted_path": row[0], "size_bytes": row[1], "sha256": row[2],
                "sealed_fd": row[3], "sealed_fd_owner_pid": owner,
                "sealed_path": f"/proc/{owner}/fd/{row[3]}",
                "device": 1, "inode": row[3],
                "stable_owner_path_verified_before_delegate": True,
            }
            for label, row in expected.items()
        },
    }


class RemainingBackendV3Tests(unittest.TestCase):
    def test_fixed_remaining_order_and_exact_r01_disposition(self) -> None:
        self.assertEqual(
            RUNNER.ITEM_ORDER, ("KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05")
        )
        self.assertEqual(
            RUNNER.PRIOR_R01_DISPOSITION,
            "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_"
            "NO_REPLAY_NO_REPLACEMENT",
        )
        self.assertNotIn("KLT_R01", RUNNER.ITEM_ORDER)
        self.assertEqual(len(set(RUNNER.AUTHORIZATION_TOKENS.values())), 4)
        self.assertEqual(RUNNER.RECEIPT_NAME, "formal_run_receipt_v3.json")

    def test_real_r01_is_deeply_bound_as_failure_not_accuracy(self) -> None:
        bindings = RUNNER.resolve_frontend_bindings()
        prior = RUNNER.prior_r01_authority(bindings)
        self.assertEqual(prior["disposition"], RUNNER.PRIOR_R01_DISPOSITION)
        self.assertEqual(
            (prior["v2_terminal_receipt"]["size_bytes"],
             prior["v2_terminal_receipt"]["sha256"]),
            RUNNER.R01_TERMINAL_EXPECTED["receipt"],
        )
        self.assertEqual(prior["v2_empty_vio"]["size_bytes"], 0)
        self.assertEqual(prior["v2_empty_ape"]["size_bytes"], 0)
        self.assertEqual(prior["failure_code"], RUNNER.R01_INFRASTRUCTURE_FAILURE_CODE)
        self.assertFalse(prior["failure_signature"]["artifact_accepted"])
        self.assertEqual(prior["execution_integrity"]["status"], "PASS")
        self.assertFalse(prior["rerun_permitted"])
        self.assertFalse(prior["replacement_permitted"])

    def test_r01_receipt_identity_is_not_inferred_from_log(self) -> None:
        wrong = dict(RUNNER.R01_TERMINAL_EXPECTED)
        wrong["receipt"] = (9999, "0" * 64)
        with mock.patch.object(RUNNER, "R01_TERMINAL_EXPECTED", wrong):
            with self.assertRaisesRegex(
                RUNNER.BackendProtocolError, "V2_R01_TERMINAL_RECEIPT_IDENTITY"
            ):
                RUNNER.prior_r01_authority(RUNNER.resolve_frontend_bindings())

    def test_preflight_waits_for_analysis_freeze_without_processes_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing_freeze = Path(temporary) / "missing-freeze.json"
            missing_lock = Path(temporary) / "missing-lock.json"
            with mock.patch.object(RUNNER, "ANALYSIS_V3_DESIGN_FREEZE", missing_freeze), \
                 mock.patch.object(
                     RUNNER.ENGINE.subprocess, "Popen",
                     side_effect=AssertionError("process spawned"),
                 ), mock.patch.object(
                     RUNNER.ENGINE, "safety_module",
                     side_effect=AssertionError("process safety imported"),
                 ):
                result = RUNNER.preflight_readonly(missing_lock)
            self.assertEqual(result["status"], "WAITING_ANALYSIS_V3_STATIC_DESIGN_FREEZE")
            self.assertFalse(result["backend_lock_build_permitted"])
            self.assertFalse(result["backend_item_launch_permitted"])
            self.assertFalse(missing_lock.exists())
            self.assertFalse(missing_freeze.exists())

    def test_analysis_freeze_binds_backend_r01_and_population(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze = Path(temporary) / "freeze.json"
            make_analysis_freeze(freeze)
            with mock.patch.object(RUNNER, "ANALYSIS_V3_DESIGN_FREEZE", freeze):
                binding = RUNNER.collect_analysis_v3_design_freeze_binding()
        self.assertEqual(binding["identity"]["path"], str(freeze.absolute()))
        self.assertEqual(binding["population_and_failure_rules"]["klt_planned_count"], 5)
        self.assertEqual(binding["prior_r01"]["disposition"], RUNNER.PRIOR_R01_DISPOSITION)

    def test_analysis_freeze_wrong_population_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze = Path(temporary) / "freeze.json"
            value = make_analysis_freeze(freeze)
            value["design_contract"]["population_and_failure_rules"][
                "maximum_valid_klt_count"
            ] = 5
            value.pop("freeze_sha256")
            value["freeze_sha256"] = RUNNER.compact_sha256(value)
            write_json(freeze, value)
            with mock.patch.object(RUNNER, "ANALYSIS_V3_DESIGN_FREEZE", freeze):
                with self.assertRaisesRegex(
                    RUNNER.BackendProtocolError, "ANALYSIS_V3_PLANNED_POPULATION"
                ):
                    RUNNER.collect_analysis_v3_design_freeze_binding()

    def test_analysis_freeze_wrong_backend_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze = Path(temporary) / "freeze.json"
            value = make_analysis_freeze(freeze)
            value["static_identities"]["backend_v3_guard"]["sha256"] = "0" * 64
            value.pop("freeze_sha256")
            value["freeze_sha256"] = RUNNER.compact_sha256(value)
            write_json(freeze, value)
            with mock.patch.object(RUNNER, "ANALYSIS_V3_DESIGN_FREEZE", freeze):
                with self.assertRaisesRegex(
                    RUNNER.BackendProtocolError, "ANALYSIS_V3_STATIC_BACKEND_BINDINGS"
                ):
                    RUNNER.collect_analysis_v3_design_freeze_binding()

    def test_items_use_new_roots_one_thread_and_stable_owner_guard(self) -> None:
        items = RUNNER.build_items(accepted_bindings(), "net:[10]", "user:[20]")
        self.assertEqual(list(items), list(RUNNER.ITEM_ORDER))
        for item_id, item in items.items():
            self.assertIn("remaining_replays_v3", item["output_dir"])
            self.assertIn("_v3", item["workspace_link"])
            self.assertEqual(item["env"]["VINS_MULTIPLE_THREAD"], "0")
            self.assertEqual(item["env"]["OMP_NUM_THREADS"], "1")
            self.assertEqual(item["env"]["FORCE_RAW"], "0")
            self.assertEqual(item["env"]["FORCE_EXPORT"], "0")
            self.assertEqual(item["env"]["EXPORT_FEATURES"], "0")
            self.assertEqual(item["env"]["A08_PRIOR_R01_DISPOSITION"],
                             RUNNER.PRIOR_R01_DISPOSITION)
            self.assertEqual(item["argv"][-2:], ["klt", "2"])
            self.assertIn(str(RUNNER.REPLAY_ONLY_GUARD), item["argv"])
            serialized = json.dumps(item)
            self.assertNotIn("hybrid_xfeat", serialized)
            self.assertNotIn("klt_safe_fallback", serialized)

    def test_guard_manifest_requires_one_stable_owner_for_all_six_inputs(self) -> None:
        item = RUNNER.build_items(
            accepted_bindings(), "net:[10]", "user:[20]"
        )["KLT_R02"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "guard.json"
            value = guard_manifest(item)
            write_json(path, value)
            audit = RUNNER.replay_guard_manifest_audit(path, item)
            self.assertEqual(audit["status"], "PASS")
            value["bound_inputs"]["feature_bag"]["sealed_path"] = "/proc/self/fd/9"
            write_json(path, value)
            failed = RUNNER.replay_guard_manifest_audit(path, item)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("bound_input:feature_bag", failed["failure_codes"])

    def test_replay_manifest_forbids_child_self_fd_and_binds_owner(self) -> None:
        item = RUNNER.build_items(
            accepted_bindings(), "net:[10]", "user:[20]"
        )["KLT_R02"]
        owner = 424242
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "replay_only_guard_manifest.json", guard_manifest(item, owner))
            values = {
                "play_bag": f"/proc/{owner}/fd/9",
                "raw_bag": f"/proc/{owner}/fd/7",
                "accepted_feature_bag": item["env"]["FEATURE_BAG_OVERRIDE"],
                "accepted_feature_bag_size_bytes": item["env"]["A08_FEATURE_BAG_SIZE_BYTES"],
                "accepted_feature_bag_sha256": item["env"]["A08_FEATURE_BAG_SHA256"],
                "sealed_play_bag": f"/proc/{owner}/fd/9",
                "sealed_fd_owner_pid": str(owner),
                "stable_owner_fd_guard": "1",
                "strict_replay_only_fd_guard": "1",
                "run_dir": item["workspace_link"],
            }
            replay = root / "replay_manifest.txt"
            replay.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
            self.assertEqual(RUNNER.replay_manifest_audit(replay, item)["status"], "PASS")
            values["play_bag"] = "/proc/self/fd/9"
            replay.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
            failed = RUNNER.replay_manifest_audit(replay, item)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("play_bag", failed["child_self_fd_value_keys"])

    def test_terminal_deep_audit_requires_owner_equal_sole_popen_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_json(
                output / "replay_only_guard_manifest.json",
                {"sealed_fd_owner_pid": 101},
            )
            item = {"item_id": "KLT_R02", "output_dir": str(output)}
            receipt = {
                "runtime": {"pid": 101},
                "artifact_contract": {
                    "semantic_checks": {
                        "replay_manifest": {
                            "sealed_fd_owner_pid": 101, "status": "PASS"
                        },
                    },
                },
            }
            with mock.patch.object(RUNNER, "_configure_engine"), \
                 mock.patch.object(RUNNER, "BASE_PRIOR_RECEIPT", return_value=receipt):
                self.assertIs(RUNNER.prior_receipt({}, item), receipt)
                receipt["runtime"]["pid"] = 102
                with self.assertRaisesRegex(
                    RUNNER.BackendProtocolError, "OWNER_NOT_SOLE_POPEN_PID"
                ):
                    RUNNER.prior_receipt({}, item)

    def test_wrong_item_token_fails_before_engine(self) -> None:
        with mock.patch.object(
            RUNNER.ENGINE, "execute_item", side_effect=AssertionError("engine reached")
        ):
            with self.assertRaisesRegex(RUNNER.BackendProtocolError, "AUTHORIZATION_TOKEN"):
                RUNNER.execute_item(Path("/missing"), "KLT_R02", "wrong")

    def test_guard_source_implements_stable_owner_not_exporter(self) -> None:
        source = RUNNER.REPLAY_ONLY_GUARD.read_text(encoding="utf-8")
        self.assertIn('export A08_SEALED_FD_OWNER_PID="$BASHPID"', source)
        self.assertIn('OWNER_PREFIX="/proc/${A08_SEALED_FD_OWNER_PID}/fd"', source)
        self.assertIn('owner_pid != os.getppid()', source)
        self.assertIn('export FEATURE_BAG_OVERRIDE="${OWNER_PREFIX}/9"', source)
        self.assertNotIn("run_external_feature_frontend", source)
        self.assertNotIn("export_vins_features", source)

    def test_protocol_and_static_paths_bind_additive_boundary(self) -> None:
        protocol = RUNNER.PROTOCOL.read_text(encoding="utf-8")
        self.assertIn(RUNNER.PRIOR_R01_DISPOSITION, protocol)
        self.assertIn("At most four valid KLT repeats", protocol)
        self.assertIn(RUNNER.ANALYSIS_V3_DESIGN_FREEZE.name, protocol)
        paths = RUNNER.static_identity_paths()
        for key in (
            "runner", "protocol", "stable_owner_replay_guard_v3",
            "process_free_tests", "v2_runner", "v2_protocol", "v2_guard",
            "v2_execution_lock", "rosbag_python_entry", "rosbag_python_dispatch",
            "rosbag_cpp_player",
        ):
            self.assertIn(key, paths)

    def test_execution_engine_retains_one_popen_no_retry_no_replacement(self) -> None:
        source = inspect.getsource(RUNNER.ENGINE.execute_item)
        self.assertEqual(source.count("subprocess.Popen("), 1)
        self.assertIn('"retry_count": 0', source)
        self.assertIn('"replacement_permitted": False', source)
        self.assertIn("FAILED_BACKEND_REPLAY_NO_REPLACEMENT", source)


if __name__ == "__main__":
    unittest.main()
