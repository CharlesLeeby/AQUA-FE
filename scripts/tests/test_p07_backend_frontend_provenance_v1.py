from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import p07_backend_frontend_provenance_v1 as provenance


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def event(run_id: str, index: int, status: str, output: str = "") -> dict[str, str]:
    return {
        "run_id": run_id,
        "registry_event_id": f"{run_id}_e{index:02d}",
        "supersedes_event_id": "" if index == 0 else f"{run_id}_e{index-1:02d}",
        "stage": "P07_FRONTEND_EXPORT",
        "status": status,
        "output_hash_manifest": output,
    }


class P07BackendFrontendProvenanceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _audit(
        self, relative: str, *, queue_index: int, run_id: str, window: str, arm: str
    ) -> Path:
        path = self.root / relative
        write_json(
            path,
            {
                "schema_version": "isj-p07-frontend-export-audit-v4",
                "status": "PASS",
                "queue_index": queue_index,
                "run_id": run_id,
                "window_id": window,
                "arm": arm,
                "held_out_trajectory_outcome_read": False,
                "forbidden_outcome_artifacts": [],
            },
        )
        return path

    def test_canonical_completed_source_is_hashable(self) -> None:
        run_id = "canonical-run"
        manifest = self.root / "papers/output.sha256"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("fixture\n", encoding="utf-8")
        rows = [
            event(run_id, 0, "PLANNED"),
            event(run_id, 1, "RUNNING"),
            event(run_id, 2, "COMPLETED", "papers/output.sha256"),
        ]
        queue = {"queue_index": "7", "window_id": "fixture:w", "arm": "M"}
        audit = self._audit(
            "papers/audit.json",
            queue_index=7,
            run_id=run_id,
            window="fixture:w",
            arm="M",
        )
        payload = provenance.resolve_frontend_provenance(
            queue,
            {"run_id": run_id},
            rows,
            root=self.root,
            canonical_audit_path=audit,
        )
        self.assertEqual(payload["kind"], provenance.CANONICAL)
        self.assertEqual(len(provenance.provenance_hash(payload)), 64)

    def test_allowlisted_auditor_only_correction_is_explicit_and_bound(self) -> None:
        run_id = "auditor-correction-run"
        output = self.root / "papers/corrected-output.sha256"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("fixture\n", encoding="utf-8")
        chain = [
            event(run_id, 0, "PLANNED"),
            event(run_id, 1, "RUNNING"),
            event(run_id, 2, "FAILED"),
            event(run_id, 3, "COMPLETED", "papers/corrected-output.sha256"),
        ]
        queue = {"queue_index": "1", "window_id": "fixture:w", "arm": "B1"}
        audit = self._audit(
            "papers/corrected-audit.json",
            queue_index=1,
            run_id=run_id,
            window="fixture:w",
            arm="B1",
        )
        correction_lock: dict[str, object] = {
            "schema_version": "isj-p07-b1-auditor-correction-lock-v2",
            "status": "FROZEN_POST_ATTEMPT_PRE_REAUDIT",
            "queue_index": 1,
            "run_id": run_id,
            "held_out_trajectory_outcome_read": False,
        }
        correction_lock["correction_lock_hash"] = provenance.document_hash(
            correction_lock, "correction_lock_hash"
        )
        correction_lock_path = self.root / "papers/correction-lock.json"
        write_json(correction_lock_path, correction_lock)
        closeout = {
            "schema_version": "isj-p07-b1-smoke-audit-correction-closeout-v2",
            "status": "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE",
            "queue_index": 1,
            "run_id": run_id,
            "physical_frontend_rerun": False,
            "held_out_trajectory_outcome_read": False,
            "superseded_registry_event": chain[-2]["registry_event_id"],
            "completion_registry_event": chain[-1]["registry_event_id"],
            "correction_lock": provenance.file_record(self.root, correction_lock_path),
            "audit": provenance.file_record(self.root, audit),
            "output_hash_manifest": provenance.file_record(self.root, output),
        }
        write_json(
            self.root / provenance.AUDITOR_CORRECTIONS[1]["closeout"], closeout
        )
        payload = provenance.resolve_frontend_provenance(
            queue,
            {"run_id": run_id},
            chain,
            root=self.root,
            canonical_audit_path=audit,
        )
        self.assertEqual(payload["kind"], provenance.AUDITOR_CORRECTION)
        self.assertFalse(payload["physical_frontend_rerun"])
        self.assertEqual(len(payload["governance_records"]), 2)

        queue["queue_index"] = "7"
        audit_payload = json.loads(audit.read_text(encoding="utf-8"))
        audit_payload["queue_index"] = 7
        write_json(audit, audit_payload)
        with self.assertRaisesRegex(provenance.ProvenanceError, "unallowlisted"):
            provenance.resolve_frontend_provenance(
                queue,
                {"run_id": run_id},
                chain,
                root=self.root,
                canonical_audit_path=audit,
            )

    def _q55_fixture(self) -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
        original = "q55-original"
        replacement = "q55-replacement"
        output = self.root / "papers/q55-output.sha256"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("fixture\n", encoding="utf-8")
        original_chain = [
            event(original, 0, "PLANNED"),
            event(original, 1, "RUNNING"),
            event(original, 2, "FAILED"),
        ]
        replacement_chain = [
            event(replacement, 0, "PLANNED"),
            event(replacement, 1, "RUNNING"),
            event(replacement, 2, "COMPLETED", "papers/q55-output.sha256"),
        ]
        queue = {
            "queue_index": "55",
            "window_id": "aqualoc_archaeology:A04:0002",
            "arm": "P_legacy_nativeq_xfeat_seedchain_v3",
        }
        audit_path = self._audit(
            provenance.Q55_AUDIT,
            queue_index=55,
            run_id=replacement,
            window=queue["window_id"],
            arm=queue["arm"],
        )
        audit_record = provenance.file_record(self.root, audit_path)
        output_record = provenance.file_record(self.root, output)
        lock: dict[str, object] = {
            "schema_version": "isj-p07-a04-layout-replacement-lock-v1",
            "status": "FROZEN_READY_FOR_Q55_A04_LAYOUT_ATTEMPT02_RECOVERY",
            "original_queue_index": 55,
            "original_run_id": original,
            "replacement_run_id": replacement,
            "trajectory_outcome_read": False,
            "vins_execution_allowed": False,
        }
        lock["replacement_lock_hash"] = provenance.document_hash(
            lock, "replacement_lock_hash"
        )
        write_json(self.root / provenance.Q55_LOCK, lock)
        write_json(
            self.root / provenance.Q55_REGISTRATION,
            {
                "schema_version": "isj-p07-frontend-layout-replacement-registration-v1",
                "status": "ALLOCATED",
                "original_run_id": original,
                "replacement_run_id": replacement,
                "replacement_lock_hash": lock["replacement_lock_hash"],
                "trajectory_outcome_read": False,
            },
        )
        closeout: dict[str, object] = {
            "schema_version": "isj-p07-frontend-layout-replacement-closeout-v1",
            "status": "PASS",
            "original_queue_index": 55,
            "original_run_id": original,
            "replacement_run_id": replacement,
            "replacement_lock_hash": lock["replacement_lock_hash"],
            "effective_slot_status": "COMPLETED",
            "physical_frontend_rerun": True,
            "trajectory_outcome_read": False,
            "original_final_registry_event": original_chain[-1],
            "completion_registry_event": replacement_chain[-1],
            "replacement_audit": audit_record,
            "replacement_output_manifest": output_record,
        }
        closeout["closeout_hash"] = provenance.document_hash(closeout, "closeout_hash")
        write_json(self.root / provenance.Q55_CLOSEOUT, closeout)
        return queue, {"run_id": original}, [*original_chain, *replacement_chain]

    def test_q55_uses_effective_replacement_and_rejects_closeout_tamper(self) -> None:
        queue, allocation, rows = self._q55_fixture()
        payload = provenance.resolve_frontend_provenance(
            queue,
            allocation,
            rows,
            root=self.root,
            canonical_audit_path=self.root / "unused",
        )
        self.assertEqual(payload["kind"], provenance.Q55_REPLACEMENT)
        self.assertEqual(payload["source_run_id"], "q55-replacement")
        closeout_path = self.root / provenance.Q55_CLOSEOUT
        closeout = json.loads(closeout_path.read_text())
        closeout["physical_frontend_rerun"] = False
        write_json(closeout_path, closeout)
        with self.assertRaises(provenance.ProvenanceError):
            provenance.resolve_frontend_provenance(
                queue,
                allocation,
                rows,
                root=self.root,
                canonical_audit_path=self.root / "unused",
            )

    def test_provenance_json_rejects_leaf_symlink_and_hardlink(self) -> None:
        outside = self.root / "outside.json"
        write_json(outside, {"status": "PASS"})
        linked = self.root / "papers/linked.json"
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(outside)
        with self.assertRaises(provenance.ProvenanceError):
            provenance._json_path(self.root, linked, label="synthetic provenance")
        linked.unlink()
        os.link(outside, linked)
        with self.assertRaises(provenance.ProvenanceError):
            provenance._json_path(self.root, linked, label="synthetic provenance")

    def test_q58_requires_exact_no_rerun_closeout(self) -> None:
        run_id = "q58-run"
        queue = {
            "queue_index": "58",
            "window_id": "aqualoc_archaeology:A07:0001",
            "arm": "M_xfeat_pairwise_nativeq_v1",
        }
        output = self.root / "papers/q58-output.sha256"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("fixture\n", encoding="utf-8")
        chain = [
            event(run_id, 0, "PLANNED"),
            event(run_id, 1, "RUNNING"),
            event(run_id, 2, "COMPLETED", "papers/q58-output.sha256"),
        ]
        audit = self._audit(
            "papers/q58-audit.json",
            queue_index=58,
            run_id=run_id,
            window=queue["window_id"],
            arm=queue["arm"],
        )
        audit_record = provenance.file_record(self.root, audit)
        output_record = provenance.file_record(self.root, output)
        lock: dict[str, object] = {
            "schema_version": "isj-p07-q58-orphan-closeout-lock-v1",
            "status": "FROZEN_POST_PHYSICAL_COMMAND_PRE_ATTESTATION_AUDIT",
            "queue_index": 58,
            "run_id": run_id,
            "physical_frontend_rerun": False,
            "trajectory_outcome_read": False,
            "held_out_trajectory_outcome_read": False,
        }
        lock["closeout_lock_hash"] = provenance.document_hash(lock, "closeout_lock_hash")
        write_json(self.root / provenance.Q58_LOCK, lock)
        closeout: dict[str, object] = {
            "schema_version": "isj-p07-q58-orphan-execution-closeout-v1",
            "status": "PASS_COMPLETED_FROM_PRESERVED_ORPHANED_EXECUTION",
            "queue_index": 58,
            "run_id": run_id,
            "orphan_closeout_lock_hash": lock["closeout_lock_hash"],
            "physical_frontend_rerun": False,
            "trajectory_outcome_read": False,
            "held_out_trajectory_outcome_read": False,
            "completion_registry_event": chain[-1],
            "audit": audit_record,
            "output_hash_manifest": output_record,
        }
        closeout["closeout_hash"] = provenance.document_hash(closeout, "closeout_hash")
        write_json(self.root / provenance.Q58_CLOSEOUT, closeout)
        payload = provenance.resolve_frontend_provenance(
            queue,
            {"run_id": run_id},
            chain,
            root=self.root,
            canonical_audit_path=audit,
        )
        self.assertEqual(payload["kind"], provenance.Q58_ORPHAN)
        closeout["physical_frontend_rerun"] = True
        closeout["closeout_hash"] = provenance.document_hash(closeout, "closeout_hash")
        write_json(self.root / provenance.Q58_CLOSEOUT, closeout)
        with self.assertRaises(provenance.ProvenanceError):
            provenance.resolve_frontend_provenance(
                queue,
                {"run_id": run_id},
                chain,
                root=self.root,
                canonical_audit_path=audit,
            )


if __name__ == "__main__":
    unittest.main()
