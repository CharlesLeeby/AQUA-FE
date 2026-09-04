from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_p07_frontend_export_v3 as frontend_audit
from scripts import build_p07_q58_orphan_replacement_lock_v1 as builder
from scripts import run_p07_mp_frontend_export_job_v2 as canonical_registry
from scripts import run_p07_q58_orphan_replacement_v1 as runtime


class P07Q58OrphanReplacementV1Tests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        queue = frontend_audit.queue_row(58)
        allocation = frontend_audit.allocation_row(58)
        chain = canonical_registry.registry_chain(allocation["run_id"])
        frozen = builder.validate_original_running_chain(chain, allocation["run_id"])
        return builder.build_payload(
            frozen_at="2026-08-08T04:00:00+08:00",
            original_queue=queue,
            original_allocation=allocation,
            original_chain=frozen,
            artifacts=[],
            stream_snapshots=[],
            orphan_attempt_artifacts=[],
            orphan_run_artifacts=[],
            raw_cache={
                "path": builder.display_path(builder.RAW_BAG),
                "sha256": "a" * 64,
                "size_bytes": 123,
                "device": 1,
                "inode": 2,
                "topic_counts": builder.EXPECTED_RAW_TOPIC_COUNTS,
                "rosbag_metadata_only": True,
                "trajectory_payload_read": False,
            },
            quiescence={
                "observed_at": "2026-08-08T04:00:00+08:00",
                "matching_processes": [],
                "signal_or_process_mutation_performed": False,
            },
        )

    def _write_registry(self, path: Path, rows: list[dict[str, str]]) -> None:
        fields, _rows = runtime.read_registry(runtime.RUN_REGISTRY)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_scientific_command_change_is_identity_only(self) -> None:
        payload = self._payload()
        original = payload["original"]["queue_row"]
        effective = payload["replacement"]["effective_queue_row"]
        builder.assert_tag_only_command_diff(original, effective)
        self.assertEqual(effective["tag"], builder.REPLACEMENT_TAG)
        self.assertIn("RUN_VINS=0", effective["command"])
        self.assertNotIn(builder.ORIGINAL_TAG, effective["command"])
        self.assertEqual(
            payload["replacement"]["scientific_command_change_scope"],
            ["TAG", "output_identity"],
        )
        self.assertFalse(payload["replacement"]["scientific_parameters_changed"])

    def test_lock_rejects_hash_and_scientific_tamper(self) -> None:
        payload = self._payload()
        runtime.validate_lock_payload(payload, verify_artifacts=False)

        bad_hash = dict(payload)
        bad_hash["replacement_tag"] = "tampered"
        with self.assertRaisesRegex(runtime.OrphanReplacementRuntimeError, "hash"):
            runtime.validate_lock_payload(bad_hash, verify_artifacts=False)

        scientific = json.loads(json.dumps(payload))
        effective = scientific["replacement"]["effective_queue_row"]
        effective["command"] += " --unfrozen-flag"
        effective["command_sha256"] = hashlib.sha256(
            effective["command"].encode()
        ).hexdigest()
        scientific["replacement"]["command"] = effective["command"]
        scientific["replacement"]["command_sha256"] = effective["command_sha256"]
        scientific[builder.SELF_HASH_FIELD] = builder.document_hash(scientific)
        with self.assertRaisesRegex(runtime.OrphanReplacementRuntimeError, "scientific"):
            runtime.validate_lock_payload(scientific, verify_artifacts=False)

    def test_original_chain_must_remain_exact_e01_running_before_freeze(self) -> None:
        payload = self._payload()
        chain = [dict(row) for row in payload["original"]["registry_running_chain"]]
        chain[-1]["status"] = "COMPLETED"
        with self.assertRaisesRegex(builder.OrphanReplacementLockError, "RUNNING"):
            builder.validate_original_running_chain(chain, payload["original_run_id"])

    def test_fake_proc_scan_detects_exact_orphan_mutator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            pid = proc / "424242"
            pid.mkdir()
            pid.joinpath("cmdline").write_bytes(
                b"python3\0-m\0uw_frontend.ros.export_vins_features\0"
                + builder.ORIGINAL_TAG.encode()
                + b"\0"
            )
            pid.joinpath("status").write_text(
                "Name:\tpython3\nState:\tR (running)\nPPid:\t1783\n",
                encoding="utf-8",
            )
            pid.joinpath("stat").write_text(
                "424242 (python3) R " + " ".join(str(i) for i in range(1, 20)),
                encoding="utf-8",
            )
            matches = builder.matching_mutator_processes(proc)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["pid"], 424242)
        self.assertIn(builder.ORIGINAL_TAG, matches[0]["cmdline"])

    def test_classification_appends_only_exact_infrastructure_e02_and_reconciles(self) -> None:
        payload = self._payload()
        original = [dict(row) for row in payload["original"]["registry_running_chain"]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "run_registry.csv"
            classification_path = root / "classification.json"
            self._write_registry(registry_path, original)
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(builder, "CLASSIFICATION", classification_path):
                    with mock.patch.object(
                        builder, "matching_mutator_processes", return_value=[]
                    ):
                        with mock.patch.object(
                            runtime, "validate_raw_cache", return_value={"status": "PASS"}
                        ):
                            first = runtime.classify_original(payload)
                            second = runtime.classify_original(payload)
            chain = runtime.registry_chain(registry_path, payload["original_run_id"])
        self.assertEqual([row["status"] for row in chain], ["PLANNED", "RUNNING", "FAILED"])
        self.assertEqual(chain[-1]["infrastructure_failure"], "true")
        self.assertEqual(chain[-1]["output_hash_manifest"], "")
        self.assertEqual(first, second)
        self.assertFalse(first["unattested_child_output_promoted"])

    def test_classification_rejects_nonexact_existing_e02(self) -> None:
        payload = self._payload()
        original = [dict(row) for row in payload["original"]["registry_running_chain"]]
        bad = runtime.build_original_failure_event(
            payload, recorded_at="2026-08-08T04:01:00+08:00"
        )
        bad["infrastructure_failure"] = "false"
        with tempfile.TemporaryDirectory() as directory:
            registry_path = Path(directory) / "run_registry.csv"
            self._write_registry(registry_path, [*original, bad])
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(
                    builder, "matching_mutator_processes", return_value=[]
                ):
                    with mock.patch.object(
                        runtime, "validate_raw_cache", return_value={"status": "PASS"}
                    ):
                        with self.assertRaisesRegex(
                            runtime.OrphanReplacementRuntimeError, "not exact"
                        ):
                            runtime.classify_original(payload)

    def test_register_repairs_exact_e00_sidecar_gap_without_touching_original(self) -> None:
        payload = self._payload()
        original = [dict(row) for row in payload["original"]["registry_running_chain"]]
        failure = runtime.build_original_failure_event(
            payload, recorded_at="2026-08-08T04:01:00+08:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "run_registry.csv"
            classification_path = root / "classification.json"
            registration_path = root / "registration.json"
            ledger_path = root / "ledger.jsonl"
            self._write_registry(registry_path, [*original, failure])
            classification = {
                "schema_version": runtime.CLASSIFICATION_SCHEMA,
                "status": "PASS_INFRASTRUCTURE_FAILED",
                "original_run_id": payload["original_run_id"],
                "classification_event": failure,
                "reason_code": builder.REASON_CODE,
                "replacement_lock_hash": payload[builder.SELF_HASH_FIELD],
                "outcome_boundary": builder.OUTCOME_BOUNDARY,
                "trajectory_outcome_read": False,
                "unattested_child_output_promoted": False,
            }
            classification_path.write_text(json.dumps(classification), encoding="utf-8")
            e00 = runtime.build_replacement_e00(
                payload, recorded_at="2026-08-08T04:02:00+08:00"
            )
            runtime._append_registry_row(registry_path, e00, expect_absent=True)
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(builder, "CLASSIFICATION", classification_path):
                    with mock.patch.object(builder, "REGISTRATION", registration_path):
                        with mock.patch.object(builder, "LEDGER", ledger_path):
                            report = runtime.register(payload)
            original_after = runtime.registry_chain(registry_path, payload["original_run_id"])
            replacement = runtime.registry_chain(
                registry_path, payload["replacement_run_id"]
            )
        self.assertEqual(original_after, [*original, failure])
        self.assertEqual(replacement, [e00])
        self.assertEqual(report["status"], "ALLOCATED")

    def test_preexecution_failure_closes_replacement_as_infrastructure(self) -> None:
        payload = self._payload()
        original = [dict(row) for row in payload["original"]["registry_running_chain"]]
        failure = runtime.build_original_failure_event(
            payload, recorded_at="2026-08-08T04:01:00+08:00"
        )
        e00 = runtime.build_replacement_e00(
            payload, recorded_at="2026-08-08T04:02:00+08:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "run_registry.csv"
            attempt = root / "attempt"
            attempt.mkdir()
            ledger = root / "ledger.jsonl"
            self._write_registry(registry_path, [*original, failure, e00])
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(builder, "ATTEMPT_DIR", attempt):
                    with mock.patch.object(builder, "LEDGER", ledger):
                        runtime._close_preexecution_failure(
                            payload,
                            phase="SYNTHETIC_WRITE",
                            error=RuntimeError("synthetic"),
                        )
            replacement = runtime.registry_chain(
                registry_path, payload["replacement_run_id"]
            )
        self.assertEqual(
            [row["status"] for row in replacement],
            ["PLANNED", "RUNNING", "FAILED"],
        )
        self.assertEqual(replacement[-1]["infrastructure_failure"], "true")
        self.assertIn("SYNTHETIC_WRITE", replacement[-1]["notes"])

    def test_combined_predecessor_adapter_skips_only_effective_55_and_58(self) -> None:
        payload = self._payload()
        observed: list[int] = []
        with mock.patch.object(runtime, "load_closeout", return_value={"status": "PASS"}):
            with mock.patch.object(runtime, "_load_q55_dependency", return_value={}):
                with mock.patch.object(
                    runtime, "_canonical_completed", side_effect=lambda index: observed.append(index)
                ):
                    with mock.patch.object(
                        runtime.queue_v4, "window_is_terminal_complete", return_value=True
                    ):
                        runtime.replacement_aware_ensure_predecessors(
                            59,
                            {"execution_order": [54, 55, 56, 57, 58, 59, 60]},
                            payload,
                        )
        self.assertEqual(observed, [54, 56, 57])

    def test_effective_allocation_overlay_changes_only_q58(self) -> None:
        payload = self._payload()
        canonical_59 = frontend_audit.allocation_row(59)
        with runtime.effective_allocation_overlay(payload):
            observed_58 = runtime.audit_v3.allocation_row(58)
            observed_59 = runtime.audit_v3.allocation_row(59)
        self.assertEqual(
            observed_58["run_id"], payload["replacement"]["effective_allocation_row"]["run_id"]
        )
        self.assertEqual(observed_59, canonical_59)

    def test_resumed_manifest_binds_recovery_correction_and_d_evidence(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = (
                "lock",
                "classification",
                "registration",
                "closeout",
                "q55_lock",
                "q55_closeout",
                "path_correction",
                "a04_d_lock",
                "a04_d_evidence",
            )
            paths = {name: root / f"{name}.json" for name in names}
            for path in paths.values():
                path.write_text('{"status":"PASS"}\n', encoding="utf-8")
            output = root / "input_hash_manifest.sha256"
            patches = (
                mock.patch.object(runtime, "LOCK_PATH", paths["lock"]),
                mock.patch.object(builder, "CLASSIFICATION", paths["classification"]),
                mock.patch.object(builder, "REGISTRATION", paths["registration"]),
                mock.patch.object(builder, "CLOSEOUT", paths["closeout"]),
                mock.patch.object(builder, "Q55_LOCK", paths["q55_lock"]),
                mock.patch.object(builder, "Q55_CLOSEOUT", paths["q55_closeout"]),
                mock.patch.object(
                    builder, "A04_PATH_CORRECTION_LOCK", paths["path_correction"]
                ),
                mock.patch.object(builder, "A04_D_LOCK", paths["a04_d_lock"]),
                mock.patch.object(builder, "A04_D_EVIDENCE", paths["a04_d_evidence"]),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
                with runtime.replacement_aware_execution_evidence_overlay(payload, 59):
                    runtime.base_job.write_hash_manifest(output, [])
            text = output.read_text(encoding="utf-8")
        for path in paths.values():
            self.assertIn(str(path), text)

    def test_atomic_json_refuses_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runtime.atomic_json(path, {"status": "PASS"})
            self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
