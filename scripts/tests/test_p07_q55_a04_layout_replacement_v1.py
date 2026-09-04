from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_p07_frontend_export_v3 as frontend_audit
from scripts import build_p07_q55_a04_layout_replacement_lock_v1 as builder
from scripts import run_p07_mp_frontend_export_job_v2 as canonical_registry
from scripts import run_p07_q55_a04_layout_replacement_v1 as runtime


class P07Q55A04LayoutReplacementV1Tests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        queue = frontend_audit.queue_row(55)
        allocation = frontend_audit.allocation_row(55)
        chain = canonical_registry.registry_chain(allocation["run_id"])
        return builder.build_payload(
            frozen_at="2026-08-08T01:00:00+08:00",
            original_queue=queue,
            original_allocation=allocation,
            original_chain=builder.validate_original_failure_chain(
                chain, allocation["run_id"]
            ),
            artifacts=[],
            stream_snapshots=[],
            archive_layout={
                "archive_layout": "MEMBERS_AT_ARCHIVE_ROOT",
                "raw_root_argv": "",
                "archive_image_rows": 13385,
                "window_image_rows": 901,
            },
        )

    def _write_registry(
        self, path: Path, rows: list[dict[str, str]]
    ) -> list[str]:
        fields, _canonical = runtime.read_registry(runtime.RUN_REGISTRY)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return fields

    def test_scientific_command_diff_is_tag_only(self) -> None:
        payload = self._payload()
        original = payload["original"]["queue_row"]
        effective = payload["replacement"]["effective_queue_row"]
        builder.assert_tag_only_command_diff(original, effective)
        self.assertEqual(effective["tag"], builder.REPLACEMENT_TAG)
        self.assertEqual(
            payload["replacement"]["scientific_command_change_scope"], ["TAG_BASE"]
        )
        self.assertFalse(payload["replacement"]["scientific_parameters_changed"])
        allocation = payload["replacement"]["effective_allocation_row"]
        self.assertIn("#replacement.effective_queue_row", allocation["command_source"])

    def test_lock_rejects_self_hash_and_scientific_tamper(self) -> None:
        payload = self._payload()
        runtime.validate_lock_payload(payload, verify_artifacts=False)

        bad_hash = dict(payload)
        bad_hash["replacement_tag"] = "tampered"
        with self.assertRaisesRegex(runtime.ReplacementRuntimeError, "hash"):
            runtime.validate_lock_payload(bad_hash, verify_artifacts=False)

        scientific = json.loads(json.dumps(payload))
        effective = scientific["replacement"]["effective_queue_row"]
        effective["command"] += " --unfrozen-scientific-flag"
        effective["command_sha256"] = hashlib.sha256(
            effective["command"].encode()
        ).hexdigest()
        scientific["replacement"]["command"] = effective["command"]
        scientific["replacement"]["command_sha256"] = effective["command_sha256"]
        scientific[builder.SELF_HASH_FIELD] = builder.document_hash(scientific)
        with self.assertRaisesRegex(runtime.ReplacementRuntimeError, "scientific"):
            runtime.validate_lock_payload(scientific, verify_artifacts=False)

    def test_wrong_failure_chain_is_rejected(self) -> None:
        payload = self._payload()
        chain = [dict(row) for row in payload["original"]["registry_failure_chain"]]
        chain[-1]["status"] = "COMPLETED"
        with self.assertRaisesRegex(builder.ReplacementLockError, "FAILED"):
            builder.validate_original_failure_chain(
                chain, payload["original_run_id"]
            )

    def _archive(self, path: Path, *, root_layout: bool) -> None:
        prefix = "" if root_layout else "raw_data/"
        rows = "".join(f"{index},frame{index:06d}.png\n" for index in range(13385))
        with tarfile.open(path, "w:gz") as archive:
            def add(name: str, content: bytes = b"") -> None:
                info = tarfile.TarInfo(prefix + name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

            add("img_sequence_4.csv", rows.encode())
            add("imu_sequence_4.csv", b"0,0,0,0,0,0,0\n")
            directory = tarfile.TarInfo(prefix + "images_sequence_4")
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            for index in range(1800, 2701):
                add(f"images_sequence_4/frame{index:06d}.png")

    def test_archive_root_layout_and_wrong_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            correct = root / "correct.tar.gz"
            wrong = root / "wrong.tar.gz"
            self._archive(correct, root_layout=True)
            self._archive(wrong, root_layout=False)
            report = builder.validate_archive_layout(correct)
            self.assertEqual(report["archive_image_rows"], 13385)
            self.assertEqual(report["window_image_rows"], 901)
            with self.assertRaisesRegex(builder.ReplacementLockError, "missing"):
                builder.validate_archive_layout(wrong)

    def test_atomic_json_refuses_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runtime.atomic_json(path, {"status": "PASS"})
            self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")

    def test_registry_replacement_chain_preserves_original_failed(self) -> None:
        payload = self._payload()
        original_chain = [
            dict(row) for row in payload["original"]["registry_failure_chain"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            registry_path = Path(directory) / "run_registry.csv"
            self._write_registry(registry_path, original_chain)
            e00 = runtime.build_replacement_e00(
                payload, recorded_at="2026-08-08T01:01:00+08:00"
            )
            runtime._append_registry_row(registry_path, e00, expect_absent=True)
            e01 = runtime.append_transition(
                registry_path,
                payload["replacement_run_id"],
                expected_status="PLANNED",
                status="RUNNING",
                updates={"notes": e00["notes"] + "; started"},
                recorded_at="2026-08-08T01:02:00+08:00",
            )
            e02 = runtime.append_transition(
                registry_path,
                payload["replacement_run_id"],
                expected_status="RUNNING",
                status="COMPLETED",
                updates={"notes": e01["notes"] + "; completed"},
                recorded_at="2026-08-08T01:03:00+08:00",
            )
            self.assertEqual(
                [row["status"] for row in runtime.registry_chain(
                    registry_path, payload["original_run_id"]
                )],
                ["PLANNED", "RUNNING", "FAILED"],
            )
            replacement = runtime.registry_chain(
                registry_path, payload["replacement_run_id"]
            )
            self.assertEqual(
                [row["status"] for row in replacement],
                ["PLANNED", "RUNNING", "COMPLETED"],
            )
            self.assertTrue(
                all(row["replacement_for"] == payload["original_run_id"] for row in replacement)
            )
            self.assertEqual(e02["registry_event_id"], payload["replacement_run_id"] + "_e02")

    def test_register_repairs_only_exact_e00_sidecar_crash_window(self) -> None:
        payload = self._payload()
        original_chain = [
            dict(row) for row in payload["original"]["registry_failure_chain"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "run_registry.csv"
            registration_path = root / "registration.json"
            ledger_path = root / "ledger.jsonl"
            self._write_registry(registry_path, original_chain)
            e00 = runtime.build_replacement_e00(
                payload, recorded_at="2026-08-08T01:01:00+08:00"
            )
            runtime._append_registry_row(registry_path, e00, expect_absent=True)
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(builder, "REGISTRATION", registration_path):
                    with mock.patch.object(builder, "LEDGER", ledger_path):
                        report = runtime.register(payload)
            self.assertEqual(report["registry_event"], e00)
            self.assertTrue(registration_path.is_file())
            self.assertEqual(
                len(runtime.registry_chain(registry_path, payload["replacement_run_id"])),
                1,
            )
            self.assertEqual(len(runtime.ledger_events(ledger_path, payload["replacement_run_id"])), 1)
            with mock.patch.object(builder, "LEDGER", ledger_path):
                repeated = runtime.append_ledger(
                    ledger_path,
                    payload,
                    event_type="ALLOCATED",
                    status="PLANNED",
                    registry_event=e00,
                )
            self.assertEqual(repeated, report["ledger_event"])
            self.assertEqual(len(runtime.ledger_events(ledger_path, payload["replacement_run_id"])), 1)

    def test_preexecution_failure_becomes_terminal_infrastructure_failure(self) -> None:
        payload = self._payload()
        original_chain = [
            dict(row) for row in payload["original"]["registry_failure_chain"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "run_registry.csv"
            ledger_path = root / "ledger.jsonl"
            self._write_registry(registry_path, original_chain)
            e00 = runtime.build_replacement_e00(
                payload, recorded_at="2026-08-08T01:01:00+08:00"
            )
            runtime._append_registry_row(registry_path, e00, expect_absent=True)
            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(builder, "LEDGER", ledger_path):
                    runtime._close_preexecution_failure(
                        payload,
                        phase="GUARD_PREFLIGHT",
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
            self.assertIn("GUARD_PREFLIGHT", replacement[-1]["notes"])

    def test_closeout_ledger_crash_reconcile_finds_earlier_exact_event(self) -> None:
        payload = self._payload()
        e00 = runtime.build_replacement_e00(
            payload, recorded_at="2026-08-08T01:01:00+08:00"
        )
        e01 = dict(e00)
        e01.update(
            {
                "registry_event_id": payload["replacement_run_id"] + "_e01",
                "supersedes_event_id": e00["registry_event_id"],
                "status": "RUNNING",
            }
        )
        e02 = dict(e01)
        e02.update(
            {
                "registry_event_id": payload["replacement_run_id"] + "_e02",
                "supersedes_event_id": e01["registry_event_id"],
                "status": "COMPLETED",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            for event_type, status, event in (
                ("ALLOCATED", "PLANNED", e00),
                ("EXECUTION_STARTED", "RUNNING", e01),
                ("EXECUTION_COMPLETED", "COMPLETED", e02),
                ("EFFECTIVE_SLOT_CLOSEOUT", "COMPLETED", e02),
            ):
                runtime.append_ledger(
                    ledger,
                    payload,
                    event_type=event_type,
                    status=status,
                    registry_event=event,
                )
            reconciled = runtime.append_ledger(
                ledger,
                payload,
                event_type="EXECUTION_COMPLETED",
                status="COMPLETED",
                registry_event=e02,
            )
            events = runtime.ledger_events(ledger, payload["replacement_run_id"])
        self.assertEqual(reconciled["ledger_event_id"], payload["replacement_run_id"] + "_l02")
        self.assertEqual(len(events), 4)

    def test_closeout_document_marks_effective_slot_without_rewriting_original(self) -> None:
        payload = self._payload()
        original = dict(payload["original"]["registry_failure_chain"][-1])
        replacement = runtime.build_replacement_e00(
            payload, recorded_at="2026-08-08T01:01:00+08:00"
        )
        replacement.update(
            {
                "registry_event_id": payload["replacement_run_id"] + "_e02",
                "supersedes_event_id": payload["replacement_run_id"] + "_e01",
                "status": "COMPLETED",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "audit_v4.json"
            output_manifest_path = root / "output_hash_manifest.sha256"
            materialization_path = root / "raw_materialization_v1.json"
            audit = {"schema_version": "isj-p07-frontend-export-audit-v4", "status": "PASS"}
            materialization = {
                "schema_version": "isj-p07-a04-raw-materialization-v1",
                "status": "PASS",
                "raw_bag": {"sha256": "a" * 64},
            }
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            output_manifest_path.write_text("a" * 64 + "  evidence\n", encoding="utf-8")
            materialization_path.write_text(json.dumps(materialization), encoding="utf-8")
            with mock.patch.object(runtime, "MATERIALIZATION_REPORT", materialization_path):
                report = runtime.build_closeout_document(
                    payload,
                    original_final_event=original,
                    replacement_completion_event=replacement,
                    audit_path=audit_path,
                    audit=audit,
                    output_manifest_path=output_manifest_path,
                    materialization=materialization,
                    ledger_event={"status": "COMPLETED"},
                    recorded_at="2026-08-08T01:04:00+08:00",
                )
        self.assertEqual(report["original_final_registry_event"]["status"], "FAILED")
        self.assertEqual(report["completion_registry_event"]["status"], "COMPLETED")
        self.assertEqual(report["effective_slot_status"], "COMPLETED")
        self.assertEqual(report["closeout_hash"], runtime.closeout_hash(report))
        self.assertTrue(report["physical_frontend_rerun"])

    def test_replacement_aware_predecessor_skips_only_q55(self) -> None:
        payload = self._payload()
        q54_allocation = frontend_audit.allocation_row(54)
        q54_chain = canonical_registry.registry_chain(q54_allocation["run_id"])
        original_chain = [
            dict(row) for row in payload["original"]["registry_failure_chain"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            registry_path = Path(directory) / "run_registry.csv"
            self._write_registry(registry_path, [*q54_chain, *original_chain])
            execution_lock = {"execution_order": [54, 55, 56]}

            def allocation(index: int) -> dict[str, str]:
                if index == 54:
                    return q54_allocation
                raise AssertionError(f"q55 canonical allocation must not be queried: {index}")

            with mock.patch.object(runtime, "RUN_REGISTRY", registry_path):
                with mock.patch.object(
                    runtime, "load_closeout", return_value={"status": "PASS"}
                ):
                    with mock.patch.object(
                        runtime.audit_v3, "allocation_row", side_effect=allocation
                    ):
                        runtime.replacement_aware_ensure_predecessors(
                            56, execution_lock, payload
                        )

    def test_resumed_input_manifest_binds_replacement_dependency_evidence(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "lock.json"
            closeout = root / "closeout.json"
            registration = root / "registration.json"
            output = root / "input_hash_manifest.sha256"
            for path in (lock, closeout, registration):
                path.write_text('{"status":"PASS"}\n', encoding="utf-8")
            with mock.patch.object(runtime, "LOCK_PATH", lock):
                with mock.patch.object(builder, "CLOSEOUT", closeout):
                    with mock.patch.object(builder, "REGISTRATION", registration):
                        with runtime.replacement_aware_execution_evidence_overlay(payload, 56):
                            runtime.base_job.write_hash_manifest(output, [])
            text = output.read_text(encoding="utf-8")
            self.assertIn(str(lock), text)
            self.assertIn(str(closeout), text)
            self.assertIn(str(registration), text)
            self.assertIn("run_p07_q55_a04_layout_replacement_v1.py", text)

    def test_a04_d_evidence_lookup_uses_real_append_only_header_mapping(self) -> None:
        manifest = runtime.audit_v3.manifest_row(builder.WINDOW_ID)
        source = runtime.governance.BUNDLE / "arm_applicability.csv"
        fields, rows = runtime.read_registry(source)
        matched = runtime.d_resolver_v2.matching_applicability_rows(rows, manifest)
        self.assertEqual(len(matched), 1)
        terminal = dict(matched[0])
        terminal["resolution"] = "NOT_APPLICABLE"
        terminal["evidence_path"] = "d_evidence.json"
        terminal["resolver_hash"] = "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            p07 = root / "p07"
            (p07 / "d_resolution_locks").mkdir(parents=True)
            bundle.mkdir()
            applicability = bundle / "arm_applicability.csv"
            with applicability.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerow(terminal)
            evidence = root / "d_evidence.json"
            resolution_lock = (
                p07 / "d_resolution_locks/aqualoc_archaeology_a04_0002_v4.json"
            )
            evidence.write_text('{"status":"PASS_NOT_APPLICABLE"}\n', encoding="utf-8")
            resolution_lock.write_text('{"status":"FROZEN_READY_TO_RESOLVE_D"}\n', encoding="utf-8")
            with mock.patch.object(runtime.governance, "BUNDLE", bundle):
                with mock.patch.object(builder, "ROOT", root):
                    with mock.patch.object(builder, "P07", p07):
                        with mock.patch.object(
                            runtime.queue_v4,
                            "window_is_terminal_complete",
                            return_value=True,
                        ):
                            with mock.patch.object(
                                runtime.d_resolver_v4,
                                "load_resolution_lock",
                                return_value={"resolution_lock_hash": "b" * 64},
                            ):
                                observed = runtime.a04_terminal_d_evidence_files()
            self.assertEqual(observed, [evidence, resolution_lock])

    def test_materialization_evidence_remains_valid_after_governed_raw_deletion(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "raw_materialization_v1.json"
            deleted_raw = root / "deleted_raw_cache.bag"
            report = {
                "schema_version": "isj-p07-a04-raw-materialization-v1",
                "status": "PASS",
                "replacement_run_id": payload["replacement_run_id"],
                "replacement_lock_hash": payload[builder.SELF_HASH_FIELD],
                "expected_topic_counts": builder.EXPECTED_TOPIC_COUNTS,
                "raw_bag": {
                    "path": str(deleted_raw),
                    "sha256": "a" * 64,
                    "size_bytes": 123,
                    "device": 1,
                    "inode": 2,
                    "topic_counts": builder.EXPECTED_TOPIC_COUNTS,
                    "topic_stamp_ranges_ns": {},
                },
                "trajectory_outcome_read": False,
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with mock.patch.object(runtime, "MATERIALIZATION_REPORT", report_path):
                with mock.patch.object(builder, "RAW_BAG", deleted_raw):
                    observed = runtime.materialization_record(payload, require_raw=False)
                    with self.assertRaises(runtime.ReplacementRuntimeError):
                        runtime.materialization_record(payload, require_raw=True)
            self.assertEqual(observed["raw_bag"]["sha256"], "a" * 64)

    def test_reclaim_sidecar_collision_fails_before_any_scan_or_unlink(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as directory:
            collision = Path(directory) / "raw_reclaim_closeout.json"
            collision.write_text('{"status":"EXISTING"}\n', encoding="utf-8")
            with mock.patch.object(builder, "RECLAIM_CLOSEOUT", collision):
                with mock.patch.object(runtime, "load_closeout") as load:
                    with mock.patch.object(runtime.raw_reclaim, "run") as run:
                        with self.assertRaises(FileExistsError):
                            runtime.reclaim(payload)
            load.assert_not_called()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
