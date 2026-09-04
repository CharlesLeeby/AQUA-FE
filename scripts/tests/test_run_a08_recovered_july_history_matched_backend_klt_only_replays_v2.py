#!/usr/bin/env python3
"""Process-free contract tests for the A08 KLT-only backend diversion v2."""

from __future__ import annotations

import csv
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


RUNNER_PATH = Path(__file__).resolve().parents[1] / (
    "run_a08_recovered_july_history_matched_backend_klt_only_replays_v2.py"
)
SPEC = importlib.util.spec_from_file_location("a08_klt_only_backend_v2_tested", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def id_tuple(value: dict) -> tuple[int, str]:
    return value["size_bytes"], value["sha256"]


class SyntheticAuthority:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths = {
            key: root / key for key in RUNNER.EVIDENCE_PATHS
        }
        self.paths["xfeat_accepted_receipt"] = root / "xfeat_accepted_absent.json"

        write_bytes(self.paths["klt_receipt"], b"accepted-klt-receipt")
        self.klt_files = {
            "features_bag": root / "accepted_klt/features.bag",
            "frontend_metrics": root / "accepted_klt/frontend_metrics.csv",
            "camera_config": root / "accepted_klt/camera.yaml",
        }
        write_bytes(self.klt_files["features_bag"], b"accepted-klt-bag")
        write_bytes(self.klt_files["frontend_metrics"], b"accepted-klt-metrics")
        write_bytes(self.klt_files["camera_config"], b"accepted-camera")

        write_bytes(self.paths["xfeat_process_start_claim"], b"xfeat-claim")
        write_bytes(self.paths["xfeat_supervisor_log"], b"xfeat-log")
        failure = {
            "schema_version": "aqua-fe-a08-recovered-july-frontend-failure-v1",
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "qualified_status": "FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT",
            "stage": "xfeat",
            "error": "FEATURE_POINT_COUNT_RANGE",
            "vins_or_accuracy_executed": False,
            "popen_started": True,
            "process_start_claim": RUNNER.identity(
                self.paths["xfeat_process_start_claim"]
            ),
            "log": RUNNER.identity(self.paths["xfeat_supervisor_log"]),
        }
        write_bytes(
            self.paths["xfeat_failure_receipt"],
            (json.dumps(failure, sort_keys=True) + "\n").encode(),
        )

        write_bytes(self.paths["probe_features_bag"], b"probe-bag")
        self._write_probe(exported="352")
        write_bytes(self.paths["probe_camera_config"], b"probe-camera")
        write_bytes(
            self.paths["final_features_bag"],
            self.klt_files["features_bag"].read_bytes(),
        )
        write_bytes(
            self.paths["final_frontend_metrics"],
            self.klt_files["frontend_metrics"].read_bytes(),
        )
        write_bytes(
            self.paths["final_camera_config"],
            self.klt_files["camera_config"].read_bytes(),
        )
        write_bytes(self.paths["forensic_audit"], b"forensic-audit")
        self.probe_contract = dict(RUNNER.PROBE_CONTRACT, metrics_rows=4)
        self.refresh()

    def _write_probe(self, exported: str) -> None:
        fields = [
            "frame_index", "timestamp", "num_features", "exported_features",
            "exported_learned_features", "exported_xfeat_features",
            "export_source_histogram",
        ]
        rows = [
            {
                "frame_index": str(1 + 2 * index),
                "timestamp": f"t{index}",
                "num_features": "350",
                "exported_features": "350",
                "exported_learned_features": "0",
                "exported_xfeat_features": "0",
                "export_source_histogram": "klt:350",
            }
            for index in range(4)
        ]
        rows[3] = {
            "frame_index": "7",
            "timestamp": "1542884961.494887114",
            "num_features": "356",
            "exported_features": exported,
            "exported_learned_features": "2",
            "exported_xfeat_features": "2",
            "export_source_histogram": "gftt:11;klt:339;xfeat_confirmed:2",
        }
        path = self.paths["probe_frontend_metrics"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def refresh(self) -> None:
        ids = {
            label: RUNNER.identity(path)
            for label, path in self.paths.items()
            if label != "xfeat_accepted_receipt"
        }
        self.expected = {
            label: id_tuple(ids[label])
            for label in RUNNER.EVIDENCE_EXPECTED
            if label not in {
                "klt_features_bag", "klt_frontend_metrics", "klt_camera_config"
            }
        }
        self.klt_binding = {
            "stage": "klt",
            "receipt": ids["klt_receipt"],
            **{key: RUNNER.identity(path) for key, path in self.klt_files.items()},
        }
        self.expected.update({
            "klt_features_bag": id_tuple(self.klt_binding["features_bag"]),
            "klt_frontend_metrics": id_tuple(self.klt_binding["frontend_metrics"]),
            "klt_camera_config": id_tuple(self.klt_binding["camera_config"]),
        })
        assert set(self.expected) == set(RUNNER.EVIDENCE_EXPECTED)

    def validate(self) -> dict:
        return RUNNER.validate_terminal_diversion_evidence(
            self.klt_binding,
            evidence_paths=self.paths,
            expected=self.expected,
            probe_contract=self.probe_contract,
        )


class KltOnlyBackendV2Tests(unittest.TestCase):
    def test_fixed_order_namespaces_tokens_and_v2_receipt(self) -> None:
        self.assertEqual(
            RUNNER.ITEM_ORDER,
            ("KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"),
        )
        self.assertNotIn("XFEAT", " ".join(RUNNER.ITEM_ORDER))
        self.assertEqual(RUNNER.RECEIPT_NAME, "formal_run_receipt_v2.json")
        self.assertTrue(RUNNER.RECEIPT_SCHEMA.endswith("-v2"))
        self.assertIn("klt_only_replays_v2", str(RUNNER.BACKEND_ROOT))
        self.assertIn("klt_only_replays_v2", str(RUNNER.RUNTIME_ROOT))
        self.assertTrue(RUNNER.DEFAULT_LOCK.name.endswith("v2_execution_lock.json"))
        self.assertEqual(len(set(RUNNER.AUTHORIZATION_TOKENS.values())), 5)
        self.assertTrue(all("KLT_ONLY" in token for token in RUNNER.AUTHORIZATION_TOKENS.values()))

    def test_terminal_evidence_passes_and_exposes_exact_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticAuthority(Path(temporary))
            excluded = fixture.validate()
        exact = {
            key: excluded[key] for key in (
                "disposition", "accepted_receipt_present", "backend_launched_count",
                "learning_contribution_claim_permitted",
            )
        }
        self.assertEqual(exact, {
            "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
            "accepted_receipt_present": False,
            "backend_launched_count": 0,
            "learning_contribution_claim_permitted": False,
        })
        gate = excluded["method_native_probe"]["structural_gate"]
        self.assertEqual((gate["zero_based_row"], gate["exported_features"]), (3, "352"))
        self.assertEqual(gate["export_source_histogram"],
                         "gftt:11;klt:339;xfeat_confirmed:2")
        fallback = excluded["final_fallback"]
        self.assertFalse(fallback["accepted_frontend"])
        self.assertFalse(fallback["accepted_backend_input"])
        self.assertFalse(fallback["learned_contribution"])
        self.assertTrue(all(fallback["content_identity_equals_accepted_klt"].values()))

    def test_any_accepted_xfeat_receipt_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticAuthority(Path(temporary))
            write_bytes(fixture.paths["xfeat_accepted_receipt"], b"forbidden")
            with self.assertRaisesRegex(RUNNER.BackendProtocolError,
                                        "XFEAT_ACCEPTED_RECEIPT_FORBIDDEN"):
                fixture.validate()

    def test_failure_receipt_semantics_are_not_inferred_from_forensic_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticAuthority(Path(temporary))
            value = json.loads(fixture.paths["xfeat_failure_receipt"].read_text())
            value["qualified_status"] = "FAILED_BUT_RETRYABLE"
            write_bytes(
                fixture.paths["xfeat_failure_receipt"],
                (json.dumps(value, sort_keys=True) + "\n").encode(),
            )
            fixture.refresh()
            with self.assertRaisesRegex(RUNNER.BackendProtocolError,
                                        "XFEAT_FAILURE_SEMANTICS"):
                fixture.validate()

    def test_probe_row_and_histogram_are_read_from_frozen_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticAuthority(Path(temporary))
            fixture._write_probe(exported="350")
            fixture.refresh()
            with self.assertRaisesRegex(RUNNER.BackendProtocolError,
                                        "PROBE_VIOLATION_COUNT"):
                fixture.validate()

    def test_byte_identity_equality_is_mandatory_not_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticAuthority(Path(temporary))
            write_bytes(fixture.paths["final_features_bag"], b"different-fallback")
            fixture.refresh()
            with self.assertRaisesRegex(
                RUNNER.BackendProtocolError,
                "FINAL_FALLBACK_NOT_BYTE_IDENTICAL_TO_ACCEPTED_KLT",
            ):
                fixture.validate()

    def test_build_items_are_klt_only_single_thread_fresh_namespace_replays(self) -> None:
        accepted = {
            "features_bag": {"path": "/accepted/klt/features.bag", "size_bytes": 1,
                             "sha256": "a" * 64},
            "frontend_metrics": {"path": "/accepted/klt/metrics.csv", "size_bytes": 2,
                                 "sha256": "b" * 64},
            "camera_config": {"path": "/accepted/klt/camera.yaml", "size_bytes": 3,
                              "sha256": "c" * 64},
            "accepted_receipt": {"path": str(RUNNER.KLT_RECEIPT), "size_bytes": 4,
                                 "sha256": "d" * 64},
        }
        excluded = {
            "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
            "accepted_receipt_present": False,
            "backend_launched_count": 0,
            "learning_contribution_claim_permitted": False,
        }
        items = RUNNER.build_items(
            {"klt": accepted, "excluded_xfeat": excluded}, "net:[10]", "user:[20]"
        )
        self.assertEqual(list(items), list(RUNNER.ITEM_ORDER))
        for item_id, item in items.items():
            self.assertEqual((item["arm"], item["method"]), ("klt", "klt"))
            self.assertEqual(item["env"]["VINS_MULTIPLE_THREAD"], "0")
            self.assertEqual(item["env"]["OMP_NUM_THREADS"], "1")
            self.assertEqual(item["env"]["FORCE_RAW"], "0")
            self.assertEqual(item["env"]["FORCE_EXPORT"], "0")
            self.assertEqual(item["env"]["EXPORT_FEATURES"], "0")
            self.assertEqual(item["env"]["A08_STRICT_REPLAY_ONLY_GUARD"], "1")
            self.assertEqual(item["env"]["A08_KLT_ONLY_REPLAYS_V2"], "1")
            self.assertEqual(item["env"]["FEATURE_BAG_OVERRIDE"],
                             "/accepted/klt/features.bag")
            self.assertEqual(item["argv"][1:4], ["--user", "--map-root-user", "--net"])
            self.assertEqual(item["argv"][-2:], ["klt", "2"])
            serialized = json.dumps({"argv": item["argv"], "env": item["env"]})
            self.assertNotIn("hybrid_xfeat", serialized)
            self.assertNotIn("klt_safe_fallback", serialized)
            self.assertNotIn("probe_oldcontract", serialized)
            self.assertIn(item_id, item["output_dir"])

    def test_lock_core_binds_exact_excluded_authority_and_klt_receipt(self) -> None:
        accepted_receipt = {"path": "/accepted/receipt.json", "size_bytes": 1,
                            "sha256": "a" * 64}
        klt = {
            "features_bag": {"path": "/accepted/features.bag", "size_bytes": 1,
                             "sha256": "b" * 64},
            "frontend_metrics": {"path": "/accepted/metrics.csv", "size_bytes": 1,
                                 "sha256": "c" * 64},
            "camera_config": {"path": "/accepted/camera.yaml", "size_bytes": 1,
                              "sha256": "d" * 64},
            "accepted_receipt": accepted_receipt,
        }
        excluded = {
            "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
            "forensic_audit": {"path": "/forensic", "size_bytes": 1,
                               "sha256": "e" * 64},
            "terminal_failure_receipt": {"path": "/failure", "size_bytes": 1,
                                         "sha256": "f" * 64},
            "accepted_receipt_present": False,
            "backend_launched_count": 0,
            "learning_contribution_claim_permitted": False,
        }
        with mock.patch.object(
            RUNNER, "original_campaign_diversion_gate",
            return_value={"status": "PASS_ORIGINAL_UNTOUCHED"},
        ):
            core = RUNNER.contract_core(
                {"klt": klt, "excluded_xfeat": excluded},
                {"forensic": excluded["forensic_audit"]},
                "net:[1]", "user:[2]",
            )
        self.assertEqual(core["excluded_xfeat"], excluded)
        self.assertEqual(core["frontend_authority"]["klt"]["accepted_receipt"],
                         accepted_receipt)
        self.assertEqual(core["scientific_boundary"]["xfeat_accuracy"], "NA")
        self.assertFalse(core["scientific_boundary"][
            "this_campaign_klt_vs_learned_accuracy_comparison_permitted"
        ])
        self.assertTrue(core["scientific_boundary"][
            "separately_frozen_hfnet_vs_klt_evaluator_permitted"
        ])

    def test_original_campaign_lock_roots_and_each_item_must_remain_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            overlay = root / "overlay"
            patches = (
                mock.patch.object(RUNNER, "ORIGINAL_LOCK", root / "old.lock"),
                mock.patch.object(RUNNER, "ORIGINAL_BACKEND_ROOT", root / "old-output"),
                mock.patch.object(RUNNER, "ORIGINAL_RUNTIME_ROOT", root / "old-runtime"),
                mock.patch.object(RUNNER, "OVERLAY_RUN_ROOT", overlay),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                gate = RUNNER.original_campaign_diversion_gate()
                self.assertIn("ALL_TEN_ITEMS_UNSTARTED", gate["status"])
                touched = RUNNER._original_item_paths("XFEAT_R03")["workspace"]
                touched.parent.mkdir(parents=True)
                touched.mkdir()
                with self.assertRaisesRegex(RUNNER.BackendProtocolError,
                                            "ORIGINAL_5_PLUS_5_ITEM_TOUCHED"):
                    RUNNER.original_campaign_diversion_gate()

    def test_preflight_is_read_only_and_never_imports_process_safety(self) -> None:
        accepted = {
            "klt": {"accepted_receipt": {"path": "/klt", "size_bytes": 1,
                                           "sha256": "a" * 64}},
            "excluded_xfeat": {
                "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
                "accepted_receipt_present": False,
                "backend_launched_count": 0,
                "learning_contribution_claim_permitted": False,
            },
        }
        presence = {
            label: {"path": str(path), "state": (
                "ABSENT_AS_REQUIRED" if label == "xfeat_accepted_receipt"
                else "PRESENT_REGULAR"
            )}
            for label, path in RUNNER.EVIDENCE_PATHS.items()
        }
        with tempfile.TemporaryDirectory() as temporary:
            absent_lock = Path(temporary) / "lock.json"
            with mock.patch.object(RUNNER, "authority_presence", return_value=presence), \
                 mock.patch.object(RUNNER, "resolve_frontend_bindings", return_value=accepted), \
                 mock.patch.object(RUNNER, "original_campaign_diversion_gate",
                                   return_value={"status": "PASS"}), \
                 mock.patch.object(RUNNER, "require_campaign_unstarted"), \
                 mock.patch.object(RUNNER, "collect_static_identities", return_value={}), \
                 mock.patch.object(RUNNER, "contract_core", return_value={"candidate": True}), \
                 mock.patch.object(RUNNER, "current_namespace",
                                   side_effect=["net:[1]", "user:[2]"]), \
                 mock.patch.object(RUNNER.ENGINE, "safety_module",
                                   side_effect=AssertionError("process safety imported")), \
                 mock.patch.object(RUNNER.ENGINE.subprocess, "Popen",
                                   side_effect=AssertionError("process spawned")):
                result = RUNNER.preflight_readonly(absent_lock)
        self.assertEqual(result["status"], "READY_TO_BUILD_KLT_ONLY_V2_EXECUTION_LOCK")
        self.assertTrue(result["read_only"])
        self.assertFalse(absent_lock.exists())

    def test_wrong_item_token_fails_before_engine_or_process_control(self) -> None:
        with mock.patch.object(
            RUNNER.ENGINE, "execute_item", side_effect=AssertionError("engine reached")
        ):
            with self.assertRaisesRegex(RUNNER.BackendProtocolError, "AUTHORIZATION_TOKEN"):
                RUNNER.execute_item(Path("/absent/lock"), "KLT_R01", "wrong-token")

    def test_correct_item_token_still_fails_closed_without_lock_before_popen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            absent_lock = Path(temporary) / "absent-lock.json"
            with mock.patch.object(
                RUNNER, "resolve_frontend_bindings", return_value={
                    "klt": {}, "excluded_xfeat": {},
                },
            ), mock.patch.object(
                RUNNER.ENGINE, "safety_module",
                side_effect=AssertionError("process safety reached"),
            ), mock.patch.object(
                RUNNER.ENGINE.subprocess, "Popen",
                side_effect=AssertionError("process spawned"),
            ):
                with self.assertRaises((OSError, RUNNER.BackendProtocolError)):
                    RUNNER.execute_item(
                        absent_lock, "KLT_R01", RUNNER.AUTHORIZATION_TOKENS["KLT_R01"]
                    )
            self.assertFalse(absent_lock.exists())
            self.assertFalse(RUNNER.BACKEND_ROOT.exists())

    def test_top_level_prior_receipt_configures_and_delegates_deep_audit(self) -> None:
        lock_identity = {"path": "/lock", "size_bytes": 1, "sha256": "a" * 64}
        item = {"item_id": "KLT_R01"}
        sentinel = {"status": "PASS_BACKEND_REPLAY_ACCEPTED"}
        with mock.patch.object(RUNNER, "_configure_engine") as configure, \
             mock.patch.object(RUNNER.ENGINE, "prior_receipt", return_value=sentinel) as deep:
            observed = RUNNER.prior_receipt(lock_identity, item)
        configure.assert_called_once_with()
        deep.assert_called_once_with(lock_identity, item)
        self.assertIs(observed, sentinel)

    def test_integrity_fault_latch_is_irreversible_and_failure_has_no_replacement(self) -> None:
        group = {
            "leader_reaped": True,
            "process_group_empty": True,
            "owned_descendants_empty": True,
        }
        faults = RUNNER.ENGINE.finalized_integrity_fault_latch(
            ["EARLIER_FAULT"], {"status": "PASS"}, True, True, True,
            group, [], True,
        )
        self.assertEqual(faults, ["EARLIER_FAULT"])
        self.assertFalse(RUNNER.ENGINE.integrity_passes(
            faults, {"status": "PASS"}, True, True, True, group
        ))
        engine_source = inspect.getsource(RUNNER.ENGINE.execute_item)
        self.assertEqual(engine_source.count("subprocess.Popen("), 1)
        self.assertIn("FAILED_BACKEND_REPLAY_NO_REPLACEMENT", engine_source)
        self.assertIn('"replacement_permitted": False', engine_source)
        self.assertIn('"retry_count": 0', engine_source)

    def test_guard_and_protocol_state_the_fail_closed_scientific_boundary(self) -> None:
        guard = RUNNER.REPLAY_ONLY_GUARD.read_text(encoding="utf-8")
        protocol = RUNNER.PROTOCOL.read_text(encoding="utf-8")
        self.assertIn('"$METHOD" != "klt"', guard)
        self.assertIn("EXPECTED_BAG=", guard)
        self.assertIn("*hybrid_xfeat*|*probe*|*fallback*", guard)
        self.assertIn("exec /usr/bin/bash \"$BASE_GUARD\"", guard)
        self.assertNotIn("run_external_feature_frontend", guard)
        self.assertIn("formal_run_receipt_v2.json", protocol)
        self.assertIn("NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED", protocol)
        self.assertIn("separately frozen two-arm", protocol)
        self.assertIn("HFNet-versus-KLT", protocol)

    def test_static_authority_binds_engine_both_guards_and_forensic_note(self) -> None:
        paths = RUNNER.static_identity_paths()
        for key in (
            "runner", "protocol", "klt_only_replay_guard_v2",
            "base_backend_runner_v1", "base_backend_protocol_v1",
            "base_replay_only_guard_v1",
            "xfeat_terminal_forensic_audit_excluded_authority",
        ):
            self.assertIn(key, paths)
        self.assertEqual(
            paths["xfeat_terminal_forensic_audit_excluded_authority"],
            RUNNER.FORENSIC_AUDIT,
        )
        for label, expected in RUNNER.BASE_AUTHORITY_EXPECTED.items():
            self.assertEqual(id_tuple(RUNNER.identity(paths[label])), expected)


if __name__ == "__main__":
    unittest.main()
