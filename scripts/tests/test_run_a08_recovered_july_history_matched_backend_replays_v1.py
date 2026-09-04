#!/usr/bin/env python3
"""Process-free contract tests for the A08 ten-item backend supervisor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.dont_write_bytecode = True
SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "run_a08_recovered_july_history_matched_backend_replays_v1.py"
)
SPEC = importlib.util.spec_from_file_location("a08_backend_replays_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def file_identity(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path.absolute()),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def synthetic_item(root: Path, item_id: str) -> dict[str, object]:
    spec = M.arm_spec(item_id)
    env = {
        "GT_TXT": str(root / "inputs/ground_truth.txt"),
        "A08_GT_SIZE_BYTES": "11", "A08_GT_SHA256": "1" * 64,
        "RAW_BAG": str(root / "inputs/raw.bag"),
        "A08_RAW_BAG_SIZE_BYTES": "12", "A08_RAW_BAG_SHA256": "2" * 64,
        "RAW_TAR": str(root / "inputs/raw.tar.gz"),
        "A08_RAW_TAR_SIZE_BYTES": "13", "A08_RAW_TAR_SHA256": "3" * 64,
        "FEATURE_BAG_OVERRIDE": str(root / f"inputs/{spec['arm']}.bag"),
        "A08_FEATURE_BAG_SIZE_BYTES": "14", "A08_FEATURE_BAG_SHA256": "4" * 64,
        "A08_FRONTEND_METRICS": str(root / f"inputs/{spec['arm']}_metrics.csv"),
        "A08_FRONTEND_METRICS_SIZE_BYTES": "15",
        "A08_FRONTEND_METRICS_SHA256": "5" * 64,
        "A08_FRONTEND_CAMERA_CONFIG": str(root / "inputs/camera.yaml"),
        "A08_FRONTEND_CAMERA_SIZE_BYTES": "16",
        "A08_FRONTEND_CAMERA_SHA256": "6" * 64,
    }
    return {
        "item_id": item_id,
        "method": spec["method"],
        "output_dir": str(root / "outputs" / item_id),
        "workspace_link": str(root / "workspace" / item_id),
        "host_network_namespace": "net:[10]",
        "host_user_namespace": "user:[20]",
        "inner_backend_argv_sha256": "c" * 64,
        "expected_outputs": list(M.EXPECTED_OUTPUTS),
        "env": env,
        "argv": ["/fixture/backend", item_id],
        "command_sha256": "d" * 64,
        "input_binding": {
            "fixture_arm": spec["arm"],
            "frontend_metrics": {
                "path": env["A08_FRONTEND_METRICS"],
                "size_bytes": int(env["A08_FRONTEND_METRICS_SIZE_BYTES"]),
                "sha256": env["A08_FRONTEND_METRICS_SHA256"],
            },
            "camera_config": {
                "path": env["A08_FRONTEND_CAMERA_CONFIG"],
                "size_bytes": int(env["A08_FRONTEND_CAMERA_SIZE_BYTES"]),
                "sha256": env["A08_FRONTEND_CAMERA_SHA256"],
            },
            "history_contract": {
                "feature_first_ns": 1_000_000_000,
                "feature_last_ns": 31_000_000_000,
            },
        },
    }


def valid_namespace_manifest(item: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "aqua-fe-a10-samehistory-backend-netns-v4",
        "status": "PASS",
        "isolation_scope": "NETWORK_NAMESPACE_LOOPBACK_ONLY",
        "machine_exclusive_cpu_scheduling": False,
        "uid_inside": 0,
        "gid_inside": 0,
        "self_network_namespace": "net:[11]",
        "host_network_namespace": item["host_network_namespace"],
        "self_user_namespace": "user:[21]",
        "host_user_namespace": item["host_user_namespace"],
        "interfaces": ["lo"],
        "initial_tcp_listeners": [],
        "formal_bind_address": "127.0.0.1",
        "formal_bind_port": 11981,
        "backend_argv_sha256": item["inner_backend_argv_sha256"],
    }


def valid_guard_manifest(item: dict[str, object]) -> dict[str, object]:
    env = item["env"]
    assert isinstance(env, dict)
    specifications = {
        "ground_truth": ("GT_TXT", "A08_GT_SIZE_BYTES", "A08_GT_SHA256", 6),
        "raw_bag": ("RAW_BAG", "A08_RAW_BAG_SIZE_BYTES", "A08_RAW_BAG_SHA256", 7),
        "raw_archive": ("RAW_TAR", "A08_RAW_TAR_SIZE_BYTES", "A08_RAW_TAR_SHA256", 8),
        "feature_bag": (
            "FEATURE_BAG_OVERRIDE", "A08_FEATURE_BAG_SIZE_BYTES",
            "A08_FEATURE_BAG_SHA256", 9,
        ),
        "frontend_metrics": (
            "A08_FRONTEND_METRICS", "A08_FRONTEND_METRICS_SIZE_BYTES",
            "A08_FRONTEND_METRICS_SHA256", 10,
        ),
        "camera_config": (
            "A08_FRONTEND_CAMERA_CONFIG", "A08_FRONTEND_CAMERA_SIZE_BYTES",
            "A08_FRONTEND_CAMERA_SHA256", 11,
        ),
    }
    bound_inputs = {}
    for label, (path_key, size_key, sha_key, descriptor) in specifications.items():
        bound_inputs[label] = {
            "accepted_path": env[path_key],
            "size_bytes": int(env[size_key]),
            "sha256": env[sha_key],
            "sealed_fd": descriptor,
            "sealed_path": f"/proc/self/fd/{descriptor}",
            "device": 1,
            "inode": descriptor,
        }
    return {
        "schema_version": "aqua-fe-a08-replay-only-fd-guard-v1",
        "status": "PASS_BEFORE_DELEGATED_BACKEND",
        "item_id": item["item_id"],
        "history": {
            "dataset": "aqualoc_archaeo", "sequence": 8,
            "start_source_index": 0, "end_source_index": 4660,
            "every_n": 2, "method": item["method"],
        },
        "output_dir": item["output_dir"],
        "workspace_link": item["workspace_link"],
        "delegated_backend_shell": str(M.BACKEND_SHELL),
        "policy": {
            "frontend_export_permitted": False,
            "raw_reconstruction_permitted": False,
            "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
            "delegated_data_environment_values_are_inherited_fds": True,
            "all_delegated_data_paths_are_inherited_fds": True,
            "published_before_delegated_backend": True,
        },
        "bound_inputs": bound_inputs,
    }


def make_receipts(root: Path) -> tuple[dict[str, Path], Path, dict[str, dict[str, object]]]:
    run_root = root / "overlay/logs/aqualoc_archaeo_vins"
    receipt_root = root / "frontends_v1"
    output_identities: dict[str, dict[str, object]] = {}
    receipts: dict[str, Path] = {}
    feature_stamps = list(range(1_000_000, 1_000_000 + 2_330))
    copied_streams = {M.IMU_TOPIC: "a" * 64, M.GT_TOPIC: "b" * 64}
    raw_contract = {
        "counts": {M.CAMERA_TOPIC: 4_661, M.IMU_TOPIC: 46_631, M.GT_TOPIC: 226},
        "feature_stamps": feature_stamps,
        "copied_stream_sha256": copied_streams,
    }
    for stage in ("klt", "xfeat"):
        run_dir = run_root / f"external_{stage}_every2_fixture"
        bag = run_dir / "features.bag"
        metrics = run_dir / "frontend_metrics.csv"
        camera = run_dir / "aqualoc_archaeo08_pinhole.yaml"
        write_bytes(bag, (stage + "-bag").encode("ascii"))
        write_bytes(metrics, ("frame,value\n0," + stage + "\n").encode("ascii"))
        write_bytes(camera, b"%YAML:1.0\nshared-camera\n")
        outputs = {
            "features_bag": file_identity(bag),
            "frontend_metrics": file_identity(metrics),
            "camera_config": file_identity(camera),
        }
        output_identities[stage] = outputs
        final_audit = {
            "status": f"PASS_{stage.upper()}_EXPORT_AUDIT",
            "run_dir": str(run_dir.absolute()),
            "topic_counts": {
                M.FEATURE_TOPIC: 2_330, M.IMU_TOPIC: 46_631, M.GT_TOPIC: 226,
            },
            "feature_messages": 2_330,
            "feature_first_ns": feature_stamps[0],
            "feature_last_ns": feature_stamps[-1],
            "copied_stream_sha256": copied_streams,
            "outputs": outputs,
        }
        artifact = final_audit if stage == "klt" else {
            "status": "PASS_XFEAT_METHOD_NATIVE_PROBE_AND_FINAL_EXPORT_AUDIT",
            "probe": {"status": "IGNORED_BY_BACKEND_BINDING"},
            "final": final_audit,
        }
        input_claims = {
            str(M.RAW_BAG): {
                "path": str(M.RAW_BAG), "size_bytes": M.RAW_BAG_EXPECTED[0],
                "sha256": M.RAW_BAG_EXPECTED[1],
            },
            str(M.SOURCE_ARCHIVE): {
                "path": str(M.SOURCE_ARCHIVE), "size_bytes": M.SOURCE_ARCHIVE_EXPECTED[0],
                "sha256": M.SOURCE_ARCHIVE_EXPECTED[1],
            },
            str(M.FRONTEND_RECEIPT_GROUND_TRUTH_PATH): {
                "path": str(M.FRONTEND_RECEIPT_GROUND_TRUTH_PATH),
                "size_bytes": M.GROUND_TRUTH_EXPECTED[0],
                "sha256": M.GROUND_TRUTH_EXPECTED[1],
            },
        }
        if stage == "xfeat":
            input_claims[str(receipts["klt"].absolute())] = file_identity(receipts["klt"])
        receipt = {
            "schema_version": M.FRONTEND_RECEIPT_SCHEMA,
            "status": "PASS_FRONTEND_EXPORT_ACCEPTED",
            "stage": stage,
            "terminal_process": (
                {
                    "original_single_supervisor_popen": True,
                    "additional_exporter_popen_count": 0,
                    "automatic_retry_count": 0,
                    "return_code_observed_by_original_supervisor": False,
                    "successful_shell_completion_sentinel_observed": True,
                    "success_inferred_under_set_euo_pipefail": True,
                }
                if stage == "klt"
                else {
                    "single_supervisor_popen": True,
                    "automatic_retry_count": 0,
                    "return_code": 0,
                }
            ),
            "claim_boundary": {
                "export_only": True,
                "vins_or_slam_executed": False,
            },
            "inputs_before": input_claims,
            "inputs_after": input_claims,
            "raw_contract": raw_contract,
            "artifact_audit": artifact,
        }
        if stage == "klt":
            receipt["supervisor_continuation_recovery"] = {
                "classification": "SAME_EXPORTER_ARTIFACT_AUDIT_AFTER_TOOL_WALL_TIMEOUT",
                "exporter_restarted": False,
                "exporter_invocation_count": 1,
                "additional_exporter_popen_count": 0,
                "audit_only": True,
                "no_vins_or_accuracy": True,
            }
        receipt_path = receipt_root / f"{stage}_attempt002_export_receipt_v1.json"
        write_bytes(
            receipt_path,
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        receipts[stage] = receipt_path
    return receipts, run_root, output_identities


class A08BackendReplayContractTests(unittest.TestCase):
    def test_exact_interleaved_population(self) -> None:
        self.assertEqual(
            M.ITEM_ORDER,
            (
                "KLT_R01", "XFEAT_R01", "KLT_R02", "XFEAT_R02",
                "KLT_R03", "XFEAT_R03", "KLT_R04", "XFEAT_R04",
                "KLT_R05", "XFEAT_R05",
            ),
        )
        self.assertEqual(len(M.ITEM_ORDER), 10)

    def test_missing_receipt_preflight_is_read_only_and_does_not_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = {
                "klt": root / "missing-klt.json",
                "xfeat": root / "missing-xfeat.json",
            }
            with mock.patch.object(
                M, "collect_static_identities", side_effect=AssertionError("must not hash")
            ), mock.patch.object(
                M.subprocess, "Popen", side_effect=AssertionError("must not spawn")
            ):
                result = M.preflight_readonly(
                    root / "absent-lock.json", receipts, root / "run-root"
                )
            self.assertEqual(
                result["status"], "WAITING_FOR_BOTH_ACCEPTED_FRONTEND_RECEIPTS"
            )
            self.assertFalse(result["dynamic_artifacts_opened"])
            self.assertFalse(result["static_hashing_performed"])
            self.assertEqual(list(root.iterdir()), [])

    def test_accepted_receipts_late_bind_exact_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts, run_root, identities = make_receipts(Path(temporary))
            bindings = M.resolve_frontend_bindings(receipts, run_root)
            self.assertEqual(bindings["klt"]["features_bag"], identities["klt"]["features_bag"])
            self.assertEqual(bindings["xfeat"]["features_bag"], identities["xfeat"]["features_bag"])
            self.assertEqual(bindings["xfeat"]["audit_status"], "PASS_XFEAT_EXPORT_AUDIT")
            self.assertNotEqual(
                bindings["klt"]["features_bag"]["path"],
                bindings["xfeat"]["features_bag"]["path"],
            )

    def test_unaccepted_receipt_and_output_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts, run_root, _ = make_receipts(root)
            value = json.loads(receipts["klt"].read_text(encoding="utf-8"))
            value["status"] = "FAILED"
            receipts["klt"].write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(M.BackendProtocolError, "FRONTEND_RECEIPT_STATUS"):
                M.resolve_frontend_bindings(receipts, run_root)

            receipts, run_root, _ = make_receipts(root / "second")
            bag = Path(
                json.loads(receipts["xfeat"].read_text(encoding="utf-8"))["artifact_audit"]
                ["final"]["outputs"]["features_bag"]["path"]
            )
            bag.write_bytes(b"changed-after-receipt")
            with self.assertRaisesRegex(M.BackendProtocolError, "IDENTITY_DRIFT"):
                M.resolve_frontend_bindings(receipts, run_root)

    def test_history_binding_requires_xfeat_to_name_accepted_klt_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts, run_root, _ = make_receipts(Path(temporary))
            value = json.loads(receipts["xfeat"].read_text(encoding="utf-8"))
            klt_key = str(receipts["klt"].absolute())
            value["inputs_before"][klt_key]["sha256"] = "f" * 64
            value["inputs_after"][klt_key]["sha256"] = "f" * 64
            receipts["xfeat"].write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                M.BackendProtocolError,
                "XFEAT_HISTORY_DOES_NOT_BIND_ACCEPTED_KLT_RECEIPT",
            ):
                M.resolve_frontend_bindings(receipts, run_root)

    def test_ten_items_share_arm_bags_and_force_single_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts, run_root, _ = make_receipts(Path(temporary))
            bindings = M.resolve_frontend_bindings(receipts, run_root)
            items = M.build_items(bindings, "net:[123]", "user:[456]")
        self.assertEqual(tuple(items), M.ITEM_ORDER)
        klt_bags = set()
        xfeat_bags = set()
        tags = set()
        ros_homes = set()
        for item_id, item in items.items():
            environment = item["env"]
            self.assertEqual(environment["VINS_MULTIPLE_THREAD"], "0")
            self.assertEqual(environment["PORT"], "11981")
            self.assertEqual(environment["FORCE_EXPORT"], "0")
            self.assertEqual(environment["EXPORT_FEATURES"], "0")
            self.assertEqual(environment["BACKEND_REPLAY_ONLY"], "0")
            self.assertEqual(environment["RUN_VINS"], "1")
            self.assertEqual(environment["A08_STRICT_REPLAY_ONLY_GUARD"], "1")
            self.assertEqual(item["argv"][:4], [
                "/usr/bin/unshare", "--user", "--map-root-user", "--net"
            ])
            self.assertIn("--formal-port", item["argv"])
            self.assertIn("11981", item["argv"])
            self.assertIn("--host-network-namespace", item["argv"])
            self.assertIn("net:[123]", item["argv"])
            self.assertIn("user:[456]", item["argv"])
            self.assertIn(str(M.REPLAY_ONLY_GUARD), item["argv"])
            self.assertNotIn(str(M.BACKEND_SHELL), item["argv"])
            tags.add(environment["TAG"])
            ros_homes.add(environment["ROS_HOME"])
            (klt_bags if item_id.startswith("KLT") else xfeat_bags).add(
                environment["FEATURE_BAG_OVERRIDE"]
            )
        self.assertEqual(len(klt_bags), 1)
        self.assertEqual(len(xfeat_bags), 1)
        self.assertEqual(len(tags), 10)
        self.assertEqual(len(ros_homes), 10)

    def test_replay_guard_seals_inputs_and_contains_no_exporter_invocation(self) -> None:
        text = M.REPLAY_ONLY_GUARD.read_text(encoding="utf-8")
        self.assertIn("exec 9<\"$ACCEPTED_FEATURE_BAG\"", text)
        self.assertIn("export FEATURE_BAG_OVERRIDE=/proc/self/fd/9", text)
        self.assertIn("export A08_FRONTEND_METRICS=/proc/self/fd/10", text)
        self.assertIn("replay_only_guard_manifest.json", text)
        self.assertIn("os.O_EXCL", text)
        self.assertIn("os.fsync", text)
        self.assertIn("BACKEND_RETURN_CODE", text)
        self.assertIn("strict_replay_only_fd_guard=1", text)
        self.assertNotIn("export_vins_features", text)

    def test_lock_payload_freezes_policy_and_dynamic_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts, run_root, _ = make_receipts(Path(temporary))
            bindings = M.resolve_frontend_bindings(receipts, run_root)
            payload = M.build_lock_payload(
                bindings,
                {"fixture": {"path": "/fixture", "size_bytes": 1, "sha256": "0" * 64}},
                "net:[1]", "user:[2]", "2026-08-28T00:00:00+00:00",
            )
        digest = payload.pop("contract_sha256")
        self.assertEqual(digest, M.compact_sha256(payload))
        self.assertEqual(payload["item_order"], list(M.ITEM_ORDER))
        self.assertFalse(payload["policy"]["replacement_repeat_permitted"])
        self.assertTrue(payload["policy"]["terminal_result_failure_does_not_block_later_items"])
        self.assertTrue(payload["policy"]["execution_integrity_failure_blocks_later_items"])

    def test_static_lock_authority_includes_catkin_setup_closure(self) -> None:
        paths = M.static_identity_paths()
        self.assertEqual(
            paths["vins_setup_sh"],
            Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.sh"),
        )
        self.assertEqual(paths["ros_setup_util"], Path("/opt/ros/noetic/_setup_util.py"))
        self.assertTrue(any(key.startswith("catkin_profile_3_") for key in paths))

    def test_failed_repeat_with_passed_integrity_allows_next_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_identity = {"path": str(root / "lock"), "size_bytes": 1, "sha256": "1" * 64}
            items = {
                item_id: synthetic_item(root, item_id) for item_id in M.ITEM_ORDER
            }
            lock = {"item_order": list(M.ITEM_ORDER), "items": items}
            prior_output = Path(items["KLT_R01"]["output_dir"])
            prior_output.mkdir(parents=True)
            prior_claim_path = prior_output / M.CLAIM_NAME
            claim_value = {
                "schema_version":
                    "aqua-fe-a08-recovered-july-backend-process-start-claim-v1",
                "status": "CLAIMED_ALLOWANCE_CONSUMED_NO_RETRY_NO_REPLACEMENT",
                "item_id": "KLT_R01",
                "execution_lock": lock_identity,
                "command_sha256": items["KLT_R01"]["command_sha256"],
                "argv": items["KLT_R01"]["argv"],
                "effective_environment": items["KLT_R01"]["env"],
                "input_binding": items["KLT_R01"]["input_binding"],
                "popen_invocation_count_at_claim": 0,
                "automatic_retry_count": 0,
                "replacement_permitted": False,
            }
            claim_payload = json.dumps(claim_value) + "\n"
            prior_claim_path.write_text(claim_payload, encoding="utf-8")
            prior_log_path = prior_output / M.LOG_NAME
            prior_log_path.write_text("fixture child log\n", encoding="utf-8")
            namespace_path = prior_output / "network_namespace_manifest.json"
            namespace_path.write_text(
                json.dumps(valid_namespace_manifest(items["KLT_R01"])), encoding="utf-8"
            )
            guard_path = prior_output / "replay_only_guard_manifest.json"
            guard_path.write_text(
                json.dumps(valid_guard_manifest(items["KLT_R01"])), encoding="utf-8"
            )
            prior_receipt = {
                "schema_version": M.RECEIPT_SCHEMA,
                "status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
                "item_id": "KLT_R01",
                "execution_lock": lock_identity,
                "launch_allowance_consumed": True,
                "retry_count": 0,
                "replacement_permitted": False,
                "execution_integrity": {
                    "status": "PASS", "irreversible_fault_latch_clear": True,
                    "authority_post": {"status": "PASS", "lock": lock_identity},
                    "claim_stable": True,
                    "workspace_binding_stable": True,
                    "owned_processes_drained": True,
                    "artifact_integrity_issues": [],
                },
                "integrity_fault_latch": [],
                "runtime": {
                    "popen_invocation_count": 1,
                    "child_started": True,
                    "process_group": {
                        "leader_reaped": True,
                        "process_group_empty": True,
                        "owned_descendants_empty": True,
                    },
                },
                "claim": file_identity(prior_claim_path),
                "process_log": file_identity(prior_log_path),
                "artifact_contract": {
                    "status": "FAIL", "outputs": {
                        "network_namespace_manifest.json": file_identity(namespace_path),
                        "replay_only_guard_manifest.json": file_identity(guard_path),
                    },
                    "evidence_tree_integrity": True, "integrity_issues": [],
                },
            }
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            workspace = Path(items["KLT_R01"]["workspace_link"])
            workspace.parent.mkdir(parents=True)
            workspace.symlink_to(prior_output)
            with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                M.enforce_sequence(lock, lock_identity, "XFEAT_R01")
            saved_process_log = prior_receipt["process_log"]
            prior_receipt["process_log"] = None
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            with self.assertRaisesRegex(M.BackendProtocolError, "PRIOR_PROCESS_LOG"):
                with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                    M.enforce_sequence(lock, lock_identity, "XFEAT_R01")
            prior_receipt["process_log"] = saved_process_log
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            saved_guard = prior_receipt["artifact_contract"]["outputs"].pop(
                "replay_only_guard_manifest.json"
            )
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            with self.assertRaisesRegex(M.BackendProtocolError, "PRIOR_BOUNDARY_MANIFESTS"):
                with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                    M.enforce_sequence(lock, lock_identity, "XFEAT_R01")
            prior_receipt["artifact_contract"]["outputs"][
                "replay_only_guard_manifest.json"
            ] = saved_guard
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            prior_claim_path.write_text('{"changed":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(M.BackendProtocolError, "IDENTITY_DRIFT"):
                with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                    M.enforce_sequence(lock, lock_identity, "XFEAT_R01")
            prior_claim_path.write_text(claim_payload, encoding="utf-8")
            workspace.unlink()
            workspace.symlink_to(root / "wrong-output")
            with self.assertRaisesRegex(M.BackendProtocolError, "PRIOR_WORKSPACE_BINDING"):
                with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                    M.enforce_sequence(lock, lock_identity, "XFEAT_R01")
            workspace.unlink()
            workspace.symlink_to(prior_output)
            prior_receipt["execution_integrity"]["status"] = "FAIL"
            (prior_output / M.RECEIPT_NAME).write_text(
                json.dumps(prior_receipt), encoding="utf-8"
            )
            with self.assertRaisesRegex(M.BackendProtocolError, "PRIOR_EXECUTION_INTEGRITY"):
                with mock.patch.object(M, "RUNTIME_ROOT", root / "runtime"):
                    M.enforce_sequence(lock, lock_identity, "XFEAT_R01")

    def test_read_only_audit_makes_no_files_and_spawns_no_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backends = root / "backends"
            overlay_runs = root / "overlay-runs"
            receipts = {"klt": root / "klt.json", "xfeat": root / "xfeat.json"}
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with mock.patch.object(M, "BACKEND_ROOT", backends), mock.patch.object(
                M, "OVERLAY_RUN_ROOT", overlay_runs
            ), mock.patch.object(
                M.subprocess, "Popen", side_effect=AssertionError("must not spawn")
            ), mock.patch.object(
                M, "RUNTIME_ROOT", root / "runtime"
            ):
                result = M.audit_readonly(root / "lock.json", receipts)
            after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            self.assertEqual(before, after)
            self.assertEqual(result["status"], "READ_ONLY_AUDIT")
            self.assertIsNone(result["next_item_if_lock_and_authorization_pass"])
            self.assertEqual(
                result["next_item_block_reason"],
                "LOCK_AUTHORITY:NOT_CHECKED_LOCK_ABSENT",
            )

    def test_lock_build_cleanliness_rejects_dirty_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backends = root / "backends"
            overlay_runs = root / "overlay-runs"
            runtime = root / "runtime"
            with mock.patch.object(M, "BACKEND_ROOT", backends), mock.patch.object(
                M, "OVERLAY_RUN_ROOT", overlay_runs
            ), mock.patch.object(M, "RUNTIME_ROOT", runtime):
                M.require_campaign_unstarted()
                workspace = overlay_runs / M.arm_spec("KLT_R01")["run_leaf"]
                workspace.parent.mkdir(parents=True)
                workspace.symlink_to(root / "absent-target")
                self.assertEqual(
                    M.inspect_item_readonly("KLT_R01")["state"], "DIRTY_WORKSPACE"
                )
                workspace.unlink()
                (runtime / "KLT_R01").mkdir(parents=True)
                self.assertEqual(M.inspect_item_readonly("KLT_R01")["state"], "DIRTY_RUNTIME")
                with self.assertRaisesRegex(M.BackendProtocolError, "CAMPAIGN_ALREADY_TOUCHED"):
                    M.require_campaign_unstarted()

    def test_run_item_fails_closed_without_lock_before_safety_or_popen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing_lock = Path(temporary) / "missing-lock.json"
            with mock.patch.object(M, "resolve_frontend_bindings", return_value={}), mock.patch.object(
                M, "safety_module", side_effect=AssertionError("must not load execution safety")
            ), mock.patch.object(
                M.subprocess, "Popen", side_effect=AssertionError("must not spawn")
            ):
                with self.assertRaises(M.BackendProtocolError):
                    M.execute_item(
                        missing_lock, "KLT_R01", M.AUTHORIZATION_TOKENS["KLT_R01"]
                    )

    def test_pre_popen_integrity_fault_is_irreversible(self) -> None:
        clean_group = {
            "leader_reaped": True,
            "process_group_empty": True,
            "owned_descendants_empty": True,
        }
        self.assertTrue(M.integrity_passes([], {"status": "PASS"}, True, True, True, clean_group))
        self.assertFalse(
            M.integrity_passes(
                ["AUTHORITY_FAILED_BEFORE_POPEN"],
                {"status": "PASS"}, True, True, True, clean_group,
            )
        )
        latch = M.finalized_integrity_fault_latch(
            [], {"status": "PASS"}, True, True, True, clean_group,
            ["MISSING_BOUNDARY_MANIFEST:replay_only_guard_manifest.json"], True,
        )
        self.assertEqual(
            latch,
            [
                "ARTIFACT_INTEGRITY:"
                "MISSING_BOUNDARY_MANIFEST:replay_only_guard_manifest.json"
            ],
        )
        self.assertFalse(M.integrity_passes(
            latch, {"status": "PASS"}, True, True, True, clean_group
        ))

    def test_missing_supervisor_log_is_an_execution_integrity_fault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = synthetic_item(root, "KLT_R01")
            output = Path(item["output_dir"])
            output.mkdir(parents=True)
            (output / "network_namespace_manifest.json").write_text(
                json.dumps(valid_namespace_manifest(item)), encoding="utf-8"
            )
            (output / "replay_only_guard_manifest.json").write_text(
                json.dumps(valid_guard_manifest(item)), encoding="utf-8"
            )
            audit = M.artifact_audit(item)
            self.assertIn(
                "SUPERVISOR_PROCESS_LOG_CONTRACT", audit["integrity_issues"]
            )

    def test_trajectory_convention_and_strict_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "vio.csv"
            path.write_text(
                "1542885161111831216,0,0,0,1,0,0,0,0,0,0,\n"
                "1542885161211831216,1,0,0,1,0,0,0,0,0,0,\n",
                encoding="utf-8",
            )
            audit = M.trajectory_audit(path)
            self.assertEqual(audit["convention"], "world_T_body")
            self.assertEqual(audit["timestamp_unit"], "nanoseconds")
            self.assertEqual(audit["rows"], 2)
            self.assertAlmostEqual(audit["duration_s"], 0.1)
            path.write_text("1542885161111831216,0,0\n", encoding="utf-8")
            with self.assertRaisesRegex(M.BackendProtocolError, "VIO_FIELD_COUNT"):
                M.trajectory_audit(path)

    def test_backend_usability_rejects_failed_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ape.txt"
            values = {
                "matched": 100, "rpe_pairs": 90, "output_poses": 100,
                "output_duration_s": 20, "expected_duration_s": 30,
                "output_coverage_ratio": 0.8, "max_output_gap_s": 0.1,
                "init_success": 0, "log_linear_solver_failures": 0,
                "log_failure_mentions": 0, "log_restart_mentions": 0,
            }
            path.write_text(
                "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
                encoding="utf-8",
            )
            audit = M.ape_usability_audit(path)
            self.assertEqual(audit["status"], "FAIL")
            self.assertEqual(audit["failure_codes"], ["init_success"])
            values["init_success"] = 1
            values["output_coverage_ratio"] = 0.69
            path.write_text(
                "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "minimum_output_coverage_ratio",
                M.ape_usability_audit(path)["failure_codes"],
            )

    def test_namespace_manifest_semantics_bind_port_namespaces_and_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "network_namespace_manifest.json"
            item = {
                "host_network_namespace": "net:[10]",
                "host_user_namespace": "user:[20]",
                "inner_backend_argv_sha256": "c" * 64,
            }
            manifest = {
                "schema_version": "aqua-fe-a10-samehistory-backend-netns-v4",
                "status": "PASS",
                "isolation_scope": "NETWORK_NAMESPACE_LOOPBACK_ONLY",
                "machine_exclusive_cpu_scheduling": False,
                "uid_inside": 0,
                "gid_inside": 0,
                "self_network_namespace": "net:[11]",
                "host_network_namespace": "net:[10]",
                "self_user_namespace": "user:[21]",
                "host_user_namespace": "user:[20]",
                "interfaces": ["lo"],
                "initial_tcp_listeners": [],
                "formal_bind_address": "127.0.0.1",
                "formal_bind_port": 11981,
                "backend_argv_sha256": "c" * 64,
            }
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(M.namespace_manifest_audit(path, item)["status"], "PASS")
            manifest["formal_bind_port"] = 11982
            path.write_text(json.dumps(manifest), encoding="utf-8")
            audit = M.namespace_manifest_audit(path, item)
            self.assertEqual(audit["status"], "FAIL")
            self.assertIn("formal_bind", audit["failure_codes"])

    def test_replay_guard_manifest_semantics_bind_every_fd_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = synthetic_item(root, "XFEAT_R03")
            path = root / "replay_only_guard_manifest.json"
            manifest = valid_guard_manifest(item)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(M.replay_guard_manifest_audit(path, item)["status"], "PASS")
            manifest["bound_inputs"]["feature_bag"]["sealed_fd"] = 7
            path.write_text(json.dumps(manifest), encoding="utf-8")
            audit = M.replay_guard_manifest_audit(path, item)
            self.assertEqual(audit["status"], "FAIL")
            self.assertIn("bound_input:feature_bag", audit["failure_codes"])

    def test_incomplete_replay_manifest_is_result_failure_not_lineage_fault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = synthetic_item(root, "KLT_R02")
            path = root / "replay_manifest.txt"
            path.write_text("play_bag=/proc/self/fd/9\n", encoding="utf-8")
            incomplete = M.replay_manifest_audit(path, item)
            self.assertEqual(incomplete["status"], "FAIL")
            self.assertFalse(incomplete["explicit_lineage_conflict"])
            path.write_text("play_bag=/wrong.bag\n", encoding="utf-8")
            conflict = M.replay_manifest_audit(path, item)
            self.assertEqual(conflict["status"], "FAIL")
            self.assertTrue(conflict["explicit_lineage_conflict"])

    def test_protocol_defers_lock_and_forbids_replacement(self) -> None:
        text = M.PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("KLT_R01, XFEAT_R01", text)
        self.assertIn("VINS_MULTIPLE_THREAD=0", text)
        self.assertIn("no retry, replacement repeat", text)
        self.assertIn("world_T_body", text)


if __name__ == "__main__":
    unittest.main()
