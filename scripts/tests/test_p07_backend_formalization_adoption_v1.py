from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_p07_backend_formalization_adoption_v1 as adoption


def _preserved_rollbacks(root: Path, relative: str) -> list[Path]:
    target = root / relative
    prefix = f".{target.name}.aqua-fe-preserved-rollback-"
    return sorted(path for path in target.parent.iterdir() if path.name.startswith(prefix))


def _retained_identity_views(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    descriptor = -1
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        opened = adoption._rollback_identity(os.fstat(descriptor))
        lexical = adoption._rollback_identity(
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        )
        return opened, lexical
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


class P07BackendFormalizationAdoptionV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.p07 = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07"
        )
        self.p07.mkdir(parents=True)
        for relative in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((adoption.ROOT / relative).read_bytes())
        (self.p07 / "split_role_audit_v1.csv").write_text(
            "window_id,corrected_split_role\nsynthetic,held_out\n",
            encoding="utf-8",
        )
        self.source_records = []
        for name, content in (("a.py", b"a\n"), ("b.py", b"bb\n"), ("c.py", b"ccc\n")):
            relative = f"scripts/{name}"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            self.source_records.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
        self.incident_hash = "1" * 64
        self.live = {
            "legacy_d": {
                "byte_exact": True,
                "paths": [
                    "papers/ieee_sensors_journal_experiments/p07/backend_a01_0018_legacy_d_sidecar_v1.json",
                    "papers/ieee_sensors_journal_experiments/p07/backend_a02_0005_legacy_d_sidecar_v1.json",
                    "papers/ieee_sensors_journal_experiments/p07/backend_legacy_d_resolution_compatibility_lock_v1.json",
                ],
                "compatibility_lock_hash": "3" * 64,
            },
            "epoch_ns": {
                "byte_exact": True,
                "path": (
                    "papers/ieee_sensors_journal_experiments/p07/"
                    "evaluator_epoch_ns_correction_lock_v1.json"
                ),
                "epoch_ns_correction_lock_hash": "4" * 64,
            },
            "backend_queue_bundle": {
                "byte_exact": True,
                "paths": [
                    "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv",
                    "papers/ieee_sensors_journal_experiments/p07/backend_run_allocation_v1.csv",
                    "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json",
                ],
                "backend_queue_lock_hash": "5" * 64,
                "backend_replay_jobs": 240,
            },
            "queue_validation": {
                "byte_exact": True,
                "path": (
                    "papers/ieee_sensors_journal_experiments/p07/"
                    "backend_queue_validation_v1.json"
                ),
                "status": "PASS",
            },
            "registration": {
                "byte_exact": True,
                "registry_prefix": {
                    "path": "papers/ieee_sensors_journal_experiments/run_registry.csv",
                    "sha256": "6" * 64,
                    "size_bytes": 10,
                },
                "registry_suffix_rows": 240,
                "registry_suffix_sha256": "7" * 64,
                "intended_registry_rows_sha256": "8" * 64,
                "first_registry_event_id": "first_e00",
                "last_registry_event_id": "last_e00",
                "current_registry": {
                    "path": "papers/ieee_sensors_journal_experiments/run_registry.csv",
                    "sha256": "9" * 64,
                    "size_bytes": 20,
                },
                "planned_e00_exact": True,
                "backend_output_paths_present": 0,
            },
            "all_ten_files_byte_exact": True,
            "source_artifact_count": 3,
            "source_bindings_hash": "2" * 64,
            "source_artifacts": self.source_records,
            "held_out_trajectory_outcome_read": False,
            "vins_executed": False,
        }
        self.live["source_bindings_hash"] = hashlib.sha256(
            adoption.canonical_json(self.live["source_artifacts"]).encode("utf-8")
        ).hexdigest()
        incident_artifacts = []
        for index, relative in enumerate(adoption.incident.PRESENT_PATHS, start=1):
            content = f"synthetic-adopted-formal-{index}\n".encode("utf-8")
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            incident_artifacts.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
        self.incident_payload = {
            "schema_version": adoption.incident.SCHEMA,
            "status": adoption.incident.STATUS,
            "observed_at": "2026-08-08T12:30:00+08:00",
            "present_artifacts": incident_artifacts,
            adoption.incident.SELF_HASH_FIELD: self.incident_hash,
        }
        self._write_json(adoption.incident.OUTPUT_RELATIVE, self.incident_payload)
        incident_record = self._record(adoption.incident.OUTPUT_RELATIVE)
        self.incident_reference = adoption._reference(
            incident_record,
            self.incident_hash,
            adoption.incident.SELF_HASH_FIELD,
        )
        self.external_manifest_payload = {
            "schema_version": adoption.EXTERNAL_REVIEW_MANIFEST_SCHEMA,
            "status": adoption.EXTERNAL_REVIEW_MANIFEST_STATUS,
            "frozen_at": "2026-08-08T12:45:00+08:00",
            "incident": self.incident_reference,
            "governance_artifacts": [
                self._record(relative)
                for relative in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS
            ],
            "review_protocol": (
                "TWO_DISTINCT_REVIEWERS_GLOBAL_THEN_INDEPENDENT_BEFORE_ADOPTION"
            ),
            "review_scope": "PREOUTCOME_BYTE_EXACT_ADMINISTRATIVE_ADOPTION_ONLY",
            "reviewer_role_requirements": {
                "required_roles": [
                    adoption.GLOBAL_REVIEWER_ROLE,
                    adoption.INDEPENDENT_REVIEWER_ROLE,
                ],
                "distinct_reviewer_identities_required": True,
                "independent_review_must_bind_global_review": True,
            },
            "administrative_test_receipt": adoption.build_administrative_test_receipt(
                receipt_role="EXTERNAL_MANIFEST_PREFLIGHT",
                completed_at="2026-08-08T12:44:00+08:00",
                producer_identity={
                    "reviewer_id": "external-manifest-builder",
                    "reviewer_instance": "external-manifest-instance-01",
                    "reviewer_role": "EXTERNAL_MANIFEST_BUILDER",
                },
                command_argv=adoption.ADMINISTRATIVE_TEST_ARGV,
                test_methods=adoption.ADMINISTRATIVE_TEST_METHODS,
                tests_run=len(adoption.ADMINISTRATIVE_TEST_METHODS),
                return_code=0,
                stdout_sha256="a" * 64,
                stderr_sha256="b" * 64,
                candidate_source_bindings_hash=hashlib.sha256(
                    adoption.canonical_json(
                        [
                            self._record(relative)
                            for relative in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS
                        ]
                    ).encode("utf-8")
                ).hexdigest(),
            ),
            "publication_acknowledgements": {
                "external_review_manifest_only": True,
                "no_execution_authority": True,
            },
            "execution_authorized": False,
            "vins_executed": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": adoption.OUTCOME_BOUNDARY,
        }
        self.external_manifest_payload[
            adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
        ] = adoption.document_hash(
            self.external_manifest_payload,
            adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        )
        self._write_json(
            adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
            self.external_manifest_payload,
        )
        manifest_record = self._record(adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE)
        self.manifest_reference = adoption._reference(
            manifest_record,
            str(
                self.external_manifest_payload[
                    adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
                ]
            ),
            adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        )
        self.global_payload = {
            "schema_version": adoption.GLOBAL_STABLE_SCHEMA,
            "status": adoption.GLOBAL_STABLE_STATUS,
            "reviewed_at": "2026-08-08T13:00:00+08:00",
            "reviewer_identity": {
                "reviewer_id": "global-reviewer",
                "reviewer_instance": "global-instance-01",
                "reviewer_role": adoption.GLOBAL_REVIEWER_ROLE,
            },
            "independence_attestation": dict(
                adoption.GLOBAL_INDEPENDENCE_ATTESTATION
            ),
            "incident": self.incident_reference,
            "external_review_manifest": self.manifest_reference,
            "candidate_source_bindings_hash": self.live["source_bindings_hash"],
            "tests_status": "PASS",
            "administrative_test_receipt": adoption.build_administrative_test_receipt(
                receipt_role="GLOBAL_STABILITY_ADMINISTRATIVE",
                completed_at="2026-08-08T12:59:00+08:00",
                producer_identity={
                    "reviewer_id": "global-reviewer",
                    "reviewer_instance": "global-instance-01",
                    "reviewer_role": adoption.GLOBAL_REVIEWER_ROLE,
                },
                command_argv=adoption.ADMINISTRATIVE_TEST_ARGV,
                test_methods=adoption.ADMINISTRATIVE_TEST_METHODS,
                tests_run=len(adoption.ADMINISTRATIVE_TEST_METHODS),
                return_code=0,
                stdout_sha256="c" * 64,
                stderr_sha256="d" * 64,
                candidate_source_bindings_hash=self.live["source_bindings_hash"],
            ),
            "publication_acknowledgements": {
                "global_stability_review_only": True,
                "no_execution_authority": True,
            },
            "formal_write_performed": False,
            "vins_executed": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": adoption.OUTCOME_BOUNDARY,
        }
        self.global_payload[adoption.GLOBAL_STABLE_HASH_FIELD] = adoption.document_hash(
            self.global_payload, adoption.GLOBAL_STABLE_HASH_FIELD
        )
        self._write_json(adoption.GLOBAL_STABLE_REVIEW_RELATIVE, self.global_payload)
        global_record = self._record(adoption.GLOBAL_STABLE_REVIEW_RELATIVE)
        global_reference = adoption._reference(
            global_record,
            str(self.global_payload[adoption.GLOBAL_STABLE_HASH_FIELD]),
            adoption.GLOBAL_STABLE_HASH_FIELD,
        )
        self.independent_payload = {
            "schema_version": adoption.INDEPENDENT_GO_SCHEMA,
            "status": adoption.INDEPENDENT_GO_STATUS,
            "reviewed_at": "2026-08-08T13:10:00+08:00",
            "reviewer_identity": {
                "reviewer_id": "independent-reviewer",
                "reviewer_instance": "independent-instance-01",
                "reviewer_role": adoption.INDEPENDENT_REVIEWER_ROLE,
            },
            "independence_attestation": {
                "global_reviewer_id": "global-reviewer",
                "global_reviewer_instance": "global-instance-01",
                "independent_reviewer_is_global_reviewer": False,
                "incident_creator_is_reviewer": False,
                "review_performed_without_outcome_access": True,
                "execution_authority_requested": False,
            },
            "incident": self.incident_reference,
            "external_review_manifest": self.manifest_reference,
            "global_stable_review": global_reference,
            "candidate_source_bindings_hash": self.live["source_bindings_hash"],
            "administrative_test_receipt": adoption.build_administrative_test_receipt(
                receipt_role="INDEPENDENT_ADMINISTRATIVE_REPLAY",
                completed_at="2026-08-08T13:09:00+08:00",
                producer_identity={
                    "reviewer_id": "independent-reviewer",
                    "reviewer_instance": "independent-instance-01",
                    "reviewer_role": adoption.INDEPENDENT_REVIEWER_ROLE,
                },
                command_argv=adoption.ADMINISTRATIVE_TEST_ARGV,
                test_methods=adoption.ADMINISTRATIVE_TEST_METHODS,
                tests_run=len(adoption.ADMINISTRATIVE_TEST_METHODS),
                return_code=0,
                stdout_sha256="e" * 64,
                stderr_sha256="f" * 64,
                candidate_source_bindings_hash=self.live["source_bindings_hash"],
            ),
            "publication_acknowledgements": {
                "independent_adoption_review_only": True,
                "no_execution_authority": True,
            },
            "adoption_scope": "ADMINISTRATIVE_ADOPTION_ONLY_NO_EXECUTION",
            "execution_authorized": False,
            "vins_executed": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": adoption.OUTCOME_BOUNDARY,
        }
        self.independent_payload[adoption.INDEPENDENT_GO_HASH_FIELD] = (
            adoption.document_hash(
                self.independent_payload, adoption.INDEPENDENT_GO_HASH_FIELD
            )
        )
        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, self.independent_payload)

    def _write_json(self, relative: str, payload: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(adoption.json_bytes(payload))

    def _record(self, relative: str) -> dict[str, object]:
        content = (self.root / relative).read_bytes()
        return {
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }

    def _build(
        self,
        *,
        adopted_at: str = "2026-08-08T13:20:00+08:00",
        acknowledged: bool = False,
    ) -> dict[str, object]:
        with mock.patch.object(
            adoption.incident,
            "validate_incident",
            return_value=self.incident_hash,
        ):
            with mock.patch.object(
                adoption,
                "collect_live_rebuild_evidence",
                return_value=copy.deepcopy(self.live),
            ):
                return adoption.build_adoption(
                    root=self.root,
                    adopted_at=adopted_at,
                    ack_administrative_adoption_only=acknowledged,
                    ack_no_execution_authority=acknowledged,
                )

    def _publish(
        self,
        payload: dict[str, object],
        *,
        ack_administrative_adoption_only: bool = True,
        ack_no_execution_authority: bool = True,
        pre_hook=None,
        post_hook=None,
    ) -> dict[str, object]:
        with mock.patch.object(
            adoption.incident,
            "validate_incident",
            return_value=self.incident_hash,
        ):
            with mock.patch.object(
                adoption,
                "collect_live_rebuild_evidence",
                return_value=copy.deepcopy(self.live),
            ):
                return adoption.publish_adoption_no_clobber(
                    payload,
                    root=self.root,
                    ack_administrative_adoption_only=(
                        ack_administrative_adoption_only
                    ),
                    ack_no_execution_authority=ack_no_execution_authority,
                    _pre_link_test_hook=pre_hook,
                    _post_link_test_hook=post_hook,
                )

    def test_build_is_administrative_only_and_never_authorizes_execution(self) -> None:
        payload = self._build()
        self.assertEqual(payload["status"], adoption.STATUS)
        self.assertTrue(payload["live_rebuild"]["all_ten_files_byte_exact"])
        self.assertEqual(
            payload[adoption.SELF_HASH_FIELD],
            adoption.document_hash(payload, adoption.SELF_HASH_FIELD),
        )
        self.assertTrue(
            all(
                value is False
                for key, value in payload["authorization"].items()
                if key.endswith("_authorized")
            )
        )
        adoption.validate_adoption(payload, root=self.root, verify_live=False)
        self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())

    def test_duplicate_key_and_noncanonical_review_json_fail_closed(self) -> None:
        canonical = adoption.json_bytes(self.independent_payload).decode("utf-8")
        duplicate = canonical.replace(
            '  "execution_authorized": false,',
            '  "execution_authorized": true,\n  "execution_authorized": false,',
        )
        (self.root / adoption.INDEPENDENT_GO_RELATIVE).write_text(
            duplicate, encoding="utf-8"
        )
        with self.assertRaisesRegex(adoption.AdoptionError, "invalid independent"):
            self._build()

        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, self.independent_payload)
        path = self.root / adoption.INDEPENDENT_GO_RELATIVE
        path.write_bytes(path.read_bytes() + b" \n")
        with self.assertRaisesRegex(adoption.AdoptionError, "not canonical"):
            self._build()

    def test_reviewer_identity_independence_and_timestamp_order_fail_closed(self) -> None:
        same = copy.deepcopy(self.independent_payload)
        same["reviewer_identity"] = copy.deepcopy(
            self.global_payload["reviewer_identity"]
        )
        same["reviewer_identity"]["reviewer_role"] = (
            adoption.INDEPENDENT_REVIEWER_ROLE
        )
        same["independence_attestation"]["independent_reviewer_is_global_reviewer"] = True
        same[adoption.INDEPENDENT_GO_HASH_FIELD] = adoption.document_hash(
            same, adoption.INDEPENDENT_GO_HASH_FIELD
        )
        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, same)
        with self.assertRaisesRegex(adoption.AdoptionError, "reviewer attestation"):
            self._build()

        early = copy.deepcopy(self.independent_payload)
        early["reviewed_at"] = "2026-08-08T12:59:59+08:00"
        early[adoption.INDEPENDENT_GO_HASH_FIELD] = adoption.document_hash(
            early, adoption.INDEPENDENT_GO_HASH_FIELD
        )
        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, early)
        with self.assertRaisesRegex(
            adoption.AdoptionError, "receipt mismatch|timestamp order"
        ):
            self._build()

        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, self.independent_payload)
        with self.assertRaisesRegex(adoption.AdoptionError, "timestamp order"):
            self._build(adopted_at="2026-08-08T13:05:00+08:00")

    def test_missing_or_tampered_reviews_fail_closed(self) -> None:
        (self.root / adoption.INDEPENDENT_GO_RELATIVE).unlink()
        with self.assertRaises(adoption.AdoptionError):
            self._build()

        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, self.independent_payload)
        tampered = dict(self.global_payload)
        tampered["tests_status"] = "REVISE"
        tampered[adoption.GLOBAL_STABLE_HASH_FIELD] = adoption.document_hash(
            tampered, adoption.GLOBAL_STABLE_HASH_FIELD
        )
        self._write_json(adoption.GLOBAL_STABLE_REVIEW_RELATIVE, tampered)
        with self.assertRaisesRegex(adoption.AdoptionError, "global-stable"):
            self._build()

    def test_external_manifest_scope_and_bound_code_drift_fail_closed(self) -> None:
        tampered = copy.deepcopy(self.external_manifest_payload)
        tampered["review_scope"] = "EXECUTION_REVIEW"
        tampered[adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD] = (
            adoption.document_hash(
                tampered, adoption.EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
            )
        )
        self._write_json(adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE, tampered)
        with self.assertRaisesRegex(adoption.AdoptionError, "manifest semantic"):
            self._build()

        self._write_json(
            adoption.EXTERNAL_REVIEW_MANIFEST_RELATIVE,
            self.external_manifest_payload,
        )
        governed = self.root / adoption.INCIDENT_TEST_RELATIVE
        original = governed.read_bytes()
        governed.write_bytes(original + b"# drift\n")
        with self.assertRaisesRegex(adoption.AdoptionError, "governance artifact drift"):
            self._build()
        governed.write_bytes(original)

    def test_independent_go_cannot_authorize_execution_even_when_rehashed(self) -> None:
        tampered = dict(self.independent_payload)
        tampered["execution_authorized"] = True
        tampered[adoption.INDEPENDENT_GO_HASH_FIELD] = adoption.document_hash(
            tampered, adoption.INDEPENDENT_GO_HASH_FIELD
        )
        self._write_json(adoption.INDEPENDENT_GO_RELATIVE, tampered)
        with self.assertRaisesRegex(adoption.AdoptionError, "independent"):
            self._build()

    def test_adoption_scope_or_authority_tamper_is_rejected_after_rehash(self) -> None:
        payload = self._build()
        for mutation in ("scope", "authority", "extra"):
            changed = copy.deepcopy(payload)
            if mutation == "scope":
                changed["adoption_scope"] = "EXECUTION_ALLOWED"
            elif mutation == "authority":
                changed["authorization"]["vins_authorized"] = True
            else:
                changed["unexpected"] = True
            changed[adoption.SELF_HASH_FIELD] = adoption.document_hash(
                changed, adoption.SELF_HASH_FIELD
            )
            with self.subTest(mutation=mutation):
                with self.assertRaises(adoption.AdoptionError):
                    adoption.validate_adoption(
                        changed, root=self.root, verify_live=False
                    )

    def test_downstream_formal_presence_blocks_adoption(self) -> None:
        blocked = adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]
        path = self.root / blocked
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("collision", encoding="utf-8")
        with self.assertRaisesRegex(adoption.AdoptionError, "downstream formal"):
            self._build()

    def test_no_clobber_publication_retains_first_adoption(self) -> None:
        payload = self._build(acknowledged=True)
        self._publish(payload)
        before = (self.root / adoption.OUTPUT_RELATIVE).read_bytes()
        with self.assertRaises(FileExistsError):
            self._publish(payload)
        self.assertEqual((self.root / adoption.OUTPUT_RELATIVE).read_bytes(), before)
        self.assertEqual(_preserved_rollbacks(self.root, adoption.OUTPUT_RELATIVE), [])

    def test_library_publish_api_cannot_bypass_dual_ack(self) -> None:
        acknowledged = self._build(acknowledged=True)
        for administrative, no_execution in ((False, True), (True, False)):
            with self.subTest(
                administrative=administrative, no_execution=no_execution
            ):
                with self.assertRaisesRegex(adoption.AdoptionError, "requires both"):
                    self._publish(
                        acknowledged,
                        ack_administrative_adoption_only=administrative,
                        ack_no_execution_authority=no_execution,
                    )
                self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())
        unacknowledged = self._build(acknowledged=False)
        with self.assertRaisesRegex(adoption.AdoptionError, "payload does not record"):
            self._publish(unacknowledged)
        self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())

    def test_prelink_review_and_downstream_drift_leave_no_adoption(self) -> None:
        for mutation in ("input", "review", "downstream"):
            payload = self._build(acknowledged=True)

            def mutate() -> None:
                if mutation == "input":
                    path = self.root / "scripts/a.py"
                    path.write_bytes(path.read_bytes() + b"drift")
                elif mutation == "review":
                    path = self.root / adoption.GLOBAL_STABLE_REVIEW_RELATIVE
                    path.write_bytes(path.read_bytes() + b" ")
                else:
                    path = self.root / adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("race\n", encoding="utf-8")

            with self.subTest(mutation=mutation):
                with self.assertRaises(Exception):
                    self._publish(payload, pre_hook=mutate)
                self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())
            if mutation == "input":
                (self.root / "scripts/a.py").write_bytes(b"a\n")
            elif mutation == "review":
                self._write_json(
                    adoption.GLOBAL_STABLE_REVIEW_RELATIVE, self.global_payload
                )
            else:
                (self.root / adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]).unlink()

    def test_postlink_drift_rolls_back_only_new_adoption(self) -> None:
        for mutation in ("input", "downstream"):
            payload = self._build(acknowledged=True)

            def mutate() -> None:
                if mutation == "input":
                    path = self.root / adoption.INDEPENDENT_GO_RELATIVE
                    path.write_bytes(path.read_bytes() + b" ")
                else:
                    path = self.root / adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("post-link-race\n", encoding="utf-8")

            with self.subTest(mutation=mutation):
                with self.assertRaises(adoption.RollbackIncomplete) as raised:
                    self._publish(payload, post_hook=mutate)
                self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())
                preserved = _preserved_rollbacks(
                    self.root, adoption.OUTPUT_RELATIVE
                )
                self.assertEqual(preserved, [raised.exception.retained_path])
                self.assertEqual(preserved[0].read_bytes(), adoption.json_bytes(payload))
                opened, lexical = _retained_identity_views(preserved[0])
                self.assertEqual(opened, lexical)
                self.assertEqual(raised.exception.retained_identity, lexical)
                self.assertEqual(lexical["nlink"], 1)
            if mutation == "input":
                self._write_json(
                    adoption.INDEPENDENT_GO_RELATIVE, self.independent_payload
                )
            else:
                (self.root / adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]).unlink()
            with self.assertRaisesRegex(
                adoption.RollbackIncomplete,
                "PRESERVED_ROLLBACK_REQUIRES_SEPARATE_GOVERNANCE",
            ):
                self._publish(payload)
            preserved[0].unlink()

    def test_persistent_directory_fsync_failure_keeps_structured_rollback(self) -> None:
        payload = self._build(acknowledged=True)
        target = self.root / adoption.OUTPUT_RELATIVE
        partial_pattern = f".{target.name}.partial.*"

        with mock.patch.object(
            adoption.formal_io,
            "_fsync_directory",
            side_effect=OSError(errno.EIO, "persistent directory fsync failure"),
        ):
            with self.assertRaises(adoption.RollbackIncomplete) as raised:
                self._publish(payload)

        preserved = _preserved_rollbacks(self.root, adoption.OUTPUT_RELATIVE)
        self.assertEqual(
            raised.exception.reason,
            "PRESERVED_ROLLBACK_DIRECTORY_FSYNC_FAILED",
        )
        self.assertEqual(preserved, [raised.exception.retained_path])
        self.assertEqual(preserved[0].read_bytes(), adoption.json_bytes(payload))
        opened, lexical = _retained_identity_views(preserved[0])
        self.assertEqual(opened, lexical)
        self.assertEqual(raised.exception.retained_identity, lexical)
        self.assertEqual(lexical["nlink"], 1)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(partial_pattern)), [])
        preserved[0].unlink()

        def fail_before_link() -> None:
            raise adoption.AdoptionError("injected pre-link failure")

        with mock.patch.object(
            adoption.formal_io,
            "_fsync_directory",
            side_effect=OSError(errno.EIO, "persistent directory fsync failure"),
        ):
            with self.assertRaises(OSError) as cleanup_failure:
                self._publish(payload, pre_hook=fail_before_link)
        self.assertEqual(cleanup_failure.exception.errno, errno.EIO)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(partial_pattern)), [])

    def test_postlink_unknown_winner_is_never_deleted(self) -> None:
        payload = self._build(acknowledged=True)
        canonical = self.root / adoption.OUTPUT_RELATIVE
        retained_own = canonical.with_name("test-retained-own-adoption.json")
        winner = b"unknown winner must survive"
        source = self.root / adoption.INDEPENDENT_GO_RELATIVE

        def replace_destination() -> None:
            source.write_bytes(source.read_bytes() + b" ")
            os.rename(canonical, retained_own)
            canonical.write_bytes(winner)

        with self.assertRaisesRegex(
            adoption.RollbackIncomplete, "UNKNOWN_CANONICAL_WINNER_RETAINED"
        ) as raised:
            self._publish(payload, post_hook=replace_destination)
        self.assertEqual(raised.exception.retained_path, canonical.absolute())
        self.assertEqual(canonical.read_bytes(), winner)
        self.assertEqual(retained_own.read_bytes(), adoption.json_bytes(payload))
        self.assertEqual(_preserved_rollbacks(self.root, adoption.OUTPUT_RELATIVE), [])

    def test_rollback_rename_race_preserves_unknown_without_deletion(self) -> None:
        payload = self._build(acknowledged=True)
        canonical = self.root / adoption.OUTPUT_RELATIVE
        retained_own = canonical.with_name("test-race-retained-own-adoption.json")
        winner = b"unknown rename-race winner must survive"
        source = self.root / adoption.INDEPENDENT_GO_RELATIVE
        real_rename = adoption._rename_noreplace_at
        swapped = []

        def drift() -> None:
            source.write_bytes(source.read_bytes() + b" ")

        def swap_then_rename(parent_fd, source_name, destination_name):
            if source_name == canonical.name and not swapped:
                os.rename(canonical, retained_own)
                canonical.write_bytes(winner)
                swapped.append(True)
            return real_rename(parent_fd, source_name, destination_name)

        with mock.patch.object(
            adoption, "_rename_noreplace_at", new=swap_then_rename
        ):
            with self.assertRaisesRegex(
                adoption.RollbackIncomplete, "UNKNOWN_MOVED_INODE_PRESERVED"
            ) as raised:
                self._publish(payload, post_hook=drift)
        self.assertFalse(canonical.exists())
        self.assertEqual(retained_own.read_bytes(), adoption.json_bytes(payload))
        self.assertEqual(raised.exception.retained_path.read_bytes(), winner)
        self.assertEqual(
            _preserved_rollbacks(self.root, adoption.OUTPUT_RELATIVE),
            [raised.exception.retained_path],
        )

    def test_rollback_destination_collision_is_retained_and_retried(self) -> None:
        payload = self._build(acknowledged=True)
        canonical = self.root / adoption.OUTPUT_RELATIVE
        collision_token = "a" * 32
        retained_token = "b" * 32
        collision = canonical.with_name(
            f".{canonical.name}.aqua-fe-preserved-rollback-"
            f"{os.getpid()}-{collision_token}"
        )
        collision_bytes = b"unknown collision must survive"
        source = self.root / adoption.INDEPENDENT_GO_RELATIVE

        def drift_and_collide() -> None:
            source.write_bytes(source.read_bytes() + b" ")
            collision.write_bytes(collision_bytes)

        rollback_tokens = iter((collision_token, retained_token))

        def token_hex(size: int) -> str:
            if size == 12:
                return "t" * 24
            self.assertEqual(size, 16)
            return next(rollback_tokens)

        with mock.patch.object(adoption.secrets, "token_hex", side_effect=token_hex):
            with self.assertRaisesRegex(
                adoption.RollbackIncomplete,
                "OWN_PUBLICATION_PRESERVED_NO_AUTOMATIC_RECLAIM",
            ) as raised:
                self._publish(payload, post_hook=drift_and_collide)
        self.assertFalse(canonical.exists())
        self.assertEqual(collision.read_bytes(), collision_bytes)
        self.assertNotEqual(collision, raised.exception.retained_path)
        self.assertEqual(
            raised.exception.retained_path.read_bytes(), adoption.json_bytes(payload)
        )

    def test_historical_validation_allows_later_downstream_but_not_byte_drift(self) -> None:
        payload = self._build(acknowledged=True)
        self._publish(payload)
        downstream = self.root / adoption.incident.DOWNSTREAM_ABSENT_PATHS[0]
        downstream.parent.mkdir(parents=True, exist_ok=True)
        downstream.write_text("later-valid-formal\n", encoding="utf-8")
        with mock.patch.object(
            adoption.incident,
            "validate_incident",
            return_value=self.incident_hash,
        ):
            self.assertEqual(
                adoption.validate_adoption_historical(payload, root=self.root),
                payload[adoption.SELF_HASH_FIELD],
            )
            loaded, loaded_record = adoption.load_and_validate_historical_adoption(
                root=self.root
            )
            self.assertEqual(loaded, payload)
            self.assertEqual(loaded_record["path"], adoption.OUTPUT_RELATIVE)
            binding = adoption.adoption_authority_binding(root=self.root)
            self.assertEqual(
                adoption.validate_adoption_authority_binding(
                    binding, root=self.root
                ),
                binding,
            )
            bad_binding = dict(binding)
            bad_binding["sha256"] = "0" * 64
            with self.assertRaisesRegex(adoption.AdoptionError, "binding live"):
                adoption.validate_adoption_authority_binding(
                    bad_binding, root=self.root
                )
        with mock.patch.object(
            adoption.incident,
            "validate_incident",
            return_value=self.incident_hash,
        ):
            with mock.patch.object(
                adoption,
                "collect_live_rebuild_evidence",
                return_value=copy.deepcopy(self.live),
            ):
                with self.assertRaisesRegex(adoption.AdoptionError, "downstream formal"):
                    adoption.validate_adoption_live_pre_adoption(
                        payload, root=self.root
                    )
        adopted_path = self.root / adoption.incident.PRESENT_PATHS[0]
        adopted_path.write_bytes(adopted_path.read_bytes() + b"drift")
        with mock.patch.object(
            adoption.incident,
            "validate_incident",
            return_value=self.incident_hash,
        ):
            with self.assertRaisesRegex(adoption.AdoptionError, "byte drift"):
                adoption.validate_adoption_historical(payload, root=self.root)

    def test_write_requires_both_scope_acknowledgements_before_any_build(self) -> None:
        command = [
            sys.executable,
            "scripts/build_p07_backend_formalization_adoption_v1.py",
            "--root",
            str(self.root),
            "--adopted-at",
            "2026-08-08T13:20:00+08:00",
            "--write",
        ]
        completed = subprocess.run(
            command,
            cwd=adoption.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("requires both", completed.stderr)
        self.assertFalse((self.root / adoption.OUTPUT_RELATIVE).exists())

    def test_default_cli_reports_blocked_without_incident_and_writes_nothing(self) -> None:
        empty = self.root / "empty-workspace"
        empty.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/build_p07_backend_formalization_adoption_v1.py",
                "--root",
                str(empty),
                "--adopted-at",
                "2026-08-08T13:20:00+08:00",
            ],
            cwd=adoption.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        status = json.loads(completed.stdout)
        self.assertEqual(status["mode"], "READ_ONLY_BLOCKED")
        self.assertFalse(status["backend_replay_authorized"])
        self.assertFalse((empty / adoption.OUTPUT_RELATIVE).exists())


class P07BackendFormalizationAdoptionProductionReadOnlyTests(unittest.TestCase):
    def test_existing_unplanned_batch_rebuilds_byte_exact_without_writing(self) -> None:
        ten = [adoption.ROOT / path for path in adoption.incident.PRESENT_PATHS]
        if not all(path.is_file() for path in ten):
            self.skipTest("unplanned production batch is not present")
        output = adoption.ROOT / adoption.OUTPUT_RELATIVE
        before_exists = output.exists()
        p07 = adoption.ROOT / "papers/ieee_sensors_journal_experiments/p07"
        before_mode = p07.stat().st_mode
        live = adoption.collect_live_rebuild_evidence(root=adoption.ROOT)
        self.assertTrue(live["all_ten_files_byte_exact"])
        self.assertEqual(live["registration"]["registry_suffix_rows"], 240)
        self.assertTrue(live["registration"]["planned_e00_exact"])
        self.assertEqual(live["registration"]["backend_output_paths_present"], 0)
        self.assertEqual(output.exists(), before_exists)
        self.assertEqual(p07.stat().st_mode, before_mode)


if __name__ == "__main__":
    unittest.main()
