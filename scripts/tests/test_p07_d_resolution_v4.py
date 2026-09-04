from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_p07_d_resolution_lock_v4 as builder
from scripts import resolve_p07_d_applicability_v4 as resolver


class P07DResolutionV4ReplacementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.command = (
            "RUN_VINS=0 FORCE_EXPORT=1 "
            "TAG_BASE=isj_p07_aqualoc_archaeology_a04_0002_p_attempt02 "
            "bash scripts/run_isj_nativeq_contract_guarded_v4.sh "
            "aqualoc_archaeo 4 1800 2700 hybrid_xfeat 2"
        )
        self.command_hash = hashlib.sha256(self.command.encode("utf-8")).hexdigest()
        self.original_run_id = "q55-original"
        self.replacement_run_id = "q55-replacement"
        self.p_row = {
            "queue_index": "55",
            "window_id": resolver.SPECIAL_WINDOW_ID,
            "dataset_family": "aqualoc_archaeology",
            "sequence": "A04",
            "arm": resolver.governance.P_ARM,
            "tag": "isj_p07_aqualoc_archaeology_a04_0002_p_attempt01",
        }
        self.allocation = {
            "queue_index": "55",
            "run_id": self.original_run_id,
            "window_id": resolver.SPECIAL_WINDOW_ID,
            "dataset_family": "aqualoc_archaeology",
            "sequence": "A04",
            "window_start": "1800",
            "window_end": "2700",
            "arm": resolver.governance.P_ARM,
        }
        self.original_chain = [
            self._event(self.original_run_id, 0, "PLANNED"),
            self._event(self.original_run_id, 1, "RUNNING"),
            self._event(self.original_run_id, 2, "FAILED"),
        ]
        self.replacement_chain = [
            self._event(self.replacement_run_id, 0, "PLANNED"),
            self._event(self.replacement_run_id, 1, "RUNNING"),
            self._event(self.replacement_run_id, 2, "COMPLETED"),
        ]
        for event in self.replacement_chain:
            event["replacement_for"] = self.original_run_id
        self.audit_path = self.root / "evidence/replacement_audit_v4.json"
        self.audit_path.parent.mkdir(parents=True)
        self.audit = {
            "schema_version": resolver.REPLACEMENT_AUDIT_SCHEMA,
            "status": "PASS",
            "queue_index": 55,
            "run_id": self.replacement_run_id,
            "window_id": resolver.SPECIAL_WINDOW_ID,
            "dataset_family": "aqualoc_archaeology",
            "arm": resolver.governance.P_ARM,
            "command_sha256": self.command_hash,
            "learned_lineages": {
                "accepted_learned_born_lineage_count": 0,
            },
            "feature_bag": {"path": "logs/replacement/features.bag", "sha256": "0" * 64},
            "outcome_boundary": resolver.OUTCOME_BOUNDARY,
            "held_out_trajectory_outcome_read": False,
        }
        self._write_json(self.audit_path, self.audit)

        self.policy_path = self.root / "policy/frozen.txt"
        self.policy_path.parent.mkdir(parents=True)
        self.policy_path.write_text("frozen\n", encoding="utf-8")
        self.stream_path = self.root / "streams/registry.csv"
        self.stream_path.parent.mkdir(parents=True)
        self.stream_path.write_text("prefix\nappended\n", encoding="utf-8")
        prefix = b"prefix\n"
        self.lock_path = self.root / "evidence/recovery_lock_v1.json"
        self.lock = {
            "schema_version": resolver.RECOVERY_LOCK_SCHEMA,
            "status": resolver.RECOVERY_LOCK_STATUS,
            "original_queue_index": 55,
            "original_run_id": self.original_run_id,
            "replacement_run_id": self.replacement_run_id,
            "replacement_tag": resolver.REPLACEMENT_TAG,
            "replacement": {
                "run_id": self.replacement_run_id,
                "tag": resolver.REPLACEMENT_TAG,
                "command": self.command,
                "command_sha256": self.command_hash,
                "effective_queue_row": {
                    **self.p_row,
                    "tag": resolver.REPLACEMENT_TAG,
                    "command": self.command,
                    "command_sha256": self.command_hash,
                },
                "effective_allocation_row": {
                    **self.allocation,
                    "run_id": self.replacement_run_id,
                    "tag": resolver.REPLACEMENT_TAG,
                    "command_sha256": self.command_hash,
                },
            },
            "original": {
                "queue_row": self.p_row,
                "allocation_row": self.allocation,
                "registry_failure_chain": self.original_chain,
            },
            "artifacts": [self._file_record(self.policy_path)],
            "mutable_stream_prefix_snapshots": [
                {
                    "path": self.stream_path.relative_to(self.root).as_posix(),
                    "sha256": hashlib.sha256(prefix).hexdigest(),
                    "size_bytes": len(prefix),
                }
            ],
        }
        self.lock["replacement_lock_hash"] = resolver.document_hash(
            self.lock, "replacement_lock_hash"
        )
        self._write_json(self.lock_path, self.lock)

        self.closeout_path = self.root / "closeout.json"
        self.closeout = {
            "schema_version": resolver.CLOSEOUT_SCHEMA,
            "status": "PASS",
            "original_queue_index": 55,
            "original_run_id": self.original_run_id,
            "original_final_registry_event": self.original_chain[-1],
            "replacement_run_id": self.replacement_run_id,
            "replacement_tag": resolver.REPLACEMENT_TAG,
            "replacement_command": self.command,
            "replacement_command_sha256": self.command_hash,
            "replacement_audit": {
                "path": self.audit_path.relative_to(self.root).as_posix(),
                "sha256": resolver.sha256(self.audit_path),
                "schema_version": resolver.REPLACEMENT_AUDIT_SCHEMA,
                "status": "PASS",
            },
            "completion_registry_event": self.replacement_chain[-1],
            "effective_slot_status": "COMPLETED",
            "physical_frontend_rerun": True,
            "replacement_for": {
                "original_queue_index": 55,
                "original_run_id": self.original_run_id,
                "original_failed_registry_event_id": self.original_chain[-1][
                    "registry_event_id"
                ],
                "reason_code": resolver.REPLACEMENT_REASON,
            },
            "lock_path": self.lock_path.relative_to(self.root).as_posix(),
            "replacement_lock_hash": self.lock["replacement_lock_hash"],
            "outcome_boundary": resolver.OUTCOME_BOUNDARY,
            "trajectory_outcome_read": False,
        }
        self._write_closeout()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _event(run_id: str, number: int, status: str) -> dict[str, str]:
        return {
            "run_id": run_id,
            "registry_event_id": f"{run_id}_e{number:02d}",
            "supersedes_event_id": "" if number == 0 else f"{run_id}_e{number - 1:02d}",
            "status": status,
            "dataset_family": "aqualoc_archaeology",
            "sequence": "A04",
            "window_start": "1800",
            "window_end": "2700",
            "arm": resolver.governance.P_ARM,
        }

    def _file_record(self, path: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": resolver.sha256(path),
            "size_bytes": path.stat().st_size,
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def _write_closeout(self) -> None:
        self.closeout.pop("closeout_hash", None)
        self.closeout["closeout_hash"] = resolver.document_hash(
            self.closeout, "closeout_hash"
        )
        self._write_json(self.closeout_path, self.closeout)

    def _chain(self, run_id: str) -> list[dict[str, str]]:
        if run_id == self.original_run_id:
            return self.original_chain
        if run_id == self.replacement_run_id:
            return self.replacement_chain
        return []

    def _validation_context(self):
        return mock.patch.multiple(
            resolver,
            WORKSPACE_ROOT=self.root,
            REPLACEMENT_CLOSEOUT=self.closeout_path,
        )

    def _load(self) -> dict[str, object]:
        with self._validation_context(), mock.patch.object(
            resolver.frontend_audit, "allocation_row", return_value=self.allocation
        ), mock.patch.object(resolver.registry, "registry_chain", side_effect=self._chain):
            return resolver.load_replacement_evidence(self.p_row)

    def test_valid_replacement_maps_effective_p_to_replacement_completed_event(self) -> None:
        evidence = self._load()
        self.assertEqual(evidence["replacement_run_id"], self.replacement_run_id)
        self.assertEqual(
            evidence["replacement_registry_event"], self.replacement_chain[-1]
        )
        with self._validation_context(), mock.patch.object(
            resolver.frontend_audit, "allocation_row", return_value=self.allocation
        ), mock.patch.object(
            resolver.registry, "registry_chain", side_effect=self._chain
        ), mock.patch.object(
            resolver, "_canonical_p_audit_path", side_effect=resolver.ResolutionViolation("missing")
        ):
            latest = resolver.latest_registry_rows([self.p_row])
        self.assertEqual(
            latest[resolver.governance.P_ARM]["run_id"], self.replacement_run_id
        )

    def test_recovery_lock_tamper_is_rejected(self) -> None:
        self.lock["replacement_tag"] = "tampered"
        self._write_json(self.lock_path, self.lock)
        with self.assertRaisesRegex(resolver.ResolutionViolation, "self-hash"):
            self._load()

    def test_wrong_original_mapping_is_rejected_even_with_valid_closeout_hash(self) -> None:
        self.closeout["original_queue_index"] = 54
        self._write_closeout()
        with self.assertRaisesRegex(resolver.ResolutionViolation, "identity"):
            self._load()

    def test_noncompleted_replacement_chain_is_rejected(self) -> None:
        self.replacement_chain[-1] = self._event(
            self.replacement_run_id, 2, "FAILED"
        )
        self.replacement_chain[-1]["replacement_for"] = self.original_run_id
        self.closeout["completion_registry_event"] = self.replacement_chain[-1]
        self._write_closeout()
        with self.assertRaisesRegex(resolver.ResolutionViolation, "not terminal COMPLETED"):
            self._load()

    def test_replacement_audit_sha_mismatch_is_rejected(self) -> None:
        self.closeout["replacement_audit"]["sha256"] = "f" * 64
        self._write_closeout()
        with self.assertRaisesRegex(resolver.ResolutionViolation, "audit record or SHA-256"):
            self._load()

    def test_closeout_tamper_is_rejected(self) -> None:
        self.closeout["physical_frontend_rerun"] = False
        self._write_json(self.closeout_path, self.closeout)
        with self.assertRaisesRegex(resolver.ResolutionViolation, "closeout self-hash"):
            self._load()

    def test_nonreplacement_window_uses_ordinary_v3_audit(self) -> None:
        path = self.root / "ordinary_audit_v3.json"
        payload = {
            "schema_version": "isj-p07-frontend-export-audit-v3",
            "status": "PASS",
            "window_id": "aqualoc_harbor:H04:0003",
            "dataset_family": "aqualoc_harbor",
            "arm": resolver.governance.P_ARM,
            "learned_lineages": {"accepted_learned_born_lineage_count": 0},
            "held_out_trajectory_outcome_read": False,
        }
        self._write_json(path, payload)
        row = {
            "queue_index": "52",
            "window_id": payload["window_id"],
            "arm": resolver.governance.P_ARM,
        }
        with mock.patch.object(resolver, "_canonical_p_audit_path", return_value=path), mock.patch.object(
            resolver, "load_replacement_evidence", side_effect=AssertionError("unused")
        ):
            observed_path, observed = resolver.load_p_audit(payload["window_id"], row)
        self.assertEqual(observed_path, path)
        self.assertEqual(observed["schema_version"], payload["schema_version"])


class P07DResolutionV4LockBuilderTests(unittest.TestCase):
    def test_builder_hash_binds_replacement_and_v2_v3_parent_contracts(self) -> None:
        p_row = {
            "queue_index": "55",
            "window_id": resolver.SPECIAL_WINDOW_ID,
            "arm": resolver.governance.P_ARM,
        }
        paths = {
            "closeout_path": Path("/tmp/closeout.json"),
            "audit_path": Path("/tmp/audit.json"),
            "recovery_lock_path": Path("/tmp/recovery_lock.json"),
        }
        evidence = {
            **paths,
            "closeout": {"physical_frontend_rerun": True},
            "original_run_id": "original",
            "replacement_run_id": "replacement",
            "replacement_tag": resolver.REPLACEMENT_TAG,
        }
        base = {
            "schema_version": "isj-p07-d-resolution-lock-v2",
            "artifacts": [],
            "parent_p": {"run_id": "replacement"},
            "decision": "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1",
        }

        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "sha256": "a" * 64, "size_bytes": 1}

        with mock.patch.object(builder.v2_builder, "build_lock", return_value=base), mock.patch.object(
            builder.resolver, "queue_rows", return_value=[p_row]
        ), mock.patch.object(
            builder, "_replacement_evidence_if_used", return_value=evidence
        ), mock.patch.object(builder.v2_builder, "file_record", side_effect=record):
            payload = builder.build_lock(resolver.SPECIAL_WINDOW_ID)

        self.assertEqual(payload["schema_version"], "isj-p07-d-resolution-lock-v4")
        self.assertEqual(payload["parent_p"]["run_id"], "replacement")
        self.assertTrue(payload["layout_replacement_compatibility"]["applied"])
        self.assertEqual(
            payload["resolution_lock_hash"], resolver.resolution_lock_hash(payload)
        )
        artifact_paths = {record["path"] for record in payload["artifacts"]}
        self.assertIn(str(paths["closeout_path"]), artifact_paths)
        self.assertIn(str(paths["audit_path"]), artifact_paths)
        self.assertIn("/home/ma/AQUA-FE_WS/scripts/resolve_p07_d_applicability_v2.py", artifact_paths)
        self.assertIn("/home/ma/AQUA-FE_WS/scripts/resolve_p07_d_applicability_v3.py", artifact_paths)
        self.assertIn("/home/ma/AQUA-FE_WS/scripts/resolve_p07_d_applicability_v4.py", artifact_paths)


if __name__ == "__main__":
    unittest.main()
