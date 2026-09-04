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
from scripts import build_p07_backend_formalization_incident_v1 as incident
from scripts import build_p07_backend_formalization_review_evidence_v1 as evidence
from scripts import p07_backend_replay_common_v1 as replay_common
from scripts.tests import test_p07_backend_formalization_adoption_v1 as adoption_fixture
from scripts.tests import test_p07_backend_formalization_incident_v1 as incident_fixture


class P07BackendFormalizationReviewEvidenceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = adoption_fixture.P07BackendFormalizationAdoptionV1Tests(
            "test_build_is_administrative_only_and_never_authorizes_execution"
        )
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        for relative in (
            *evidence.FUTURE_SOURCE_PATHS,
            *evidence.RUNTIME_CONTRACT_DOCUMENT_PATHS,
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((evidence.ROOT / relative).read_bytes())
        self.adoption_payload = self.base._build(acknowledged=True)
        self.base._publish(self.adoption_payload)
        self.adoption_record = self.base._record(adoption.OUTPUT_RELATIVE)
        precision = b"synthetic precision authority\n"
        precision_path = self.root / evidence.PRECISION_LOCK_RELATIVE
        precision_path.write_bytes(precision)
        self.precision_record = {
            "path": evidence.PRECISION_LOCK_RELATIVE,
            "sha256": hashlib.sha256(precision).hexdigest(),
            "size_bytes": len(precision),
        }
        self.epoch_hash = "9" * 64
        self.epoch_payload = {
            "parent_precision_correction_lock": dict(self.precision_record),
            evidence.epoch.SELF_HASH_FIELD: self.epoch_hash,
        }
        epoch_path = self.root / evidence.EPOCH_LOCK_RELATIVE
        epoch_path.write_bytes(adoption.json_bytes(self.epoch_payload))
        records = [self.base._record(path) for path in evidence.FUTURE_SOURCE_PATHS]
        self.source_hash = evidence._source_hash(records)
        global_identity = self.base.global_payload["reviewer_identity"]
        independent_identity = self.base.independent_payload["reviewer_identity"]
        self.expected_methods = evidence._test_method_inventory(self.root)
        self.receipts = [
            evidence._build_test_receipt_from_execution(
                receipt_role=evidence.RECEIPT_ROLES[0],
                reviewer_identity=global_identity,
                completed_at="2026-08-08T13:30:00+08:00",
                command_argv=evidence.FULL_STACK_ARGV,
                test_methods=self.expected_methods,
                return_code=0,
                stdout_sha256="a" * 64,
                stderr_sha256="b" * 64,
                source_artifacts_hash=self.source_hash,
                expected_test_methods=self.expected_methods,
            ),
            evidence._build_test_receipt_from_execution(
                receipt_role=evidence.RECEIPT_ROLES[1],
                reviewer_identity=independent_identity,
                completed_at="2026-08-08T13:40:00+08:00",
                command_argv=evidence.FULL_STACK_ARGV,
                test_methods=self.expected_methods,
                return_code=0,
                stdout_sha256="c" * 64,
                stderr_sha256="d" * 64,
                source_artifacts_hash=self.source_hash,
                expected_test_methods=self.expected_methods,
            ),
        ]

    def _authority_patches(self):
        binding = {
            "path": adoption.OUTPUT_RELATIVE,
            "sha256": self.adoption_record["sha256"],
            "size_bytes": self.adoption_record["size_bytes"],
            adoption.SELF_HASH_FIELD: self.adoption_payload[adoption.SELF_HASH_FIELD],
        }
        return mock.patch.multiple(
            adoption,
            load_and_validate_historical_adoption=mock.DEFAULT,
            adoption_authority_binding=mock.DEFAULT,
        ), binding

    def _build(self) -> dict[str, object]:
        patcher, binding = self._authority_patches()
        with patcher as patched:
            patched["load_and_validate_historical_adoption"].return_value = (
                self.adoption_payload,
                self.adoption_record,
            )
            patched["adoption_authority_binding"].return_value = binding
            with mock.patch.object(
                evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
            ):
                return evidence._build_evidence_lock_from_receipts(
                    root=self.root,
                    frozen_at="2026-08-08T13:50:00+08:00",
                    test_receipts=self.receipts,
                    ack_review_evidence_only=True,
                    ack_no_execution_authority=True,
                )

    def _validate(self, payload: dict[str, object], *, verify_files: bool = True) -> str:
        patcher, binding = self._authority_patches()
        with patcher as patched:
            patched["load_and_validate_historical_adoption"].return_value = (
                self.adoption_payload,
                self.adoption_record,
            )
            patched["adoption_authority_binding"].return_value = binding
            with mock.patch.object(
                evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
            ):
                return evidence.validate_evidence_lock(
                    payload, root=self.root, verify_files=verify_files
                )

    def test_evidence_lock_binds_adoption_reviews_sources_receipts_and_no_authority(self) -> None:
        payload = self._build()
        self.assertEqual(self._validate(payload), payload[evidence.SELF_HASH_FIELD])
        self.assertEqual(
            [item["receipt_role"] for item in payload["test_receipts"]],
            list(evidence.RECEIPT_ROLES),
        )
        self.assertTrue(all(value is False for value in payload["authorization"].values()))
        self.assertEqual(
            [
                item["path"]
                for item in payload["scientific_authorities"]["runtime_contract_documents"]
            ],
            list(evidence.RUNTIME_CONTRACT_DOCUMENT_PATHS),
        )

    def test_runtime_binding_closure_is_exactly_partitioned_into_sources_and_contracts(self) -> None:
        runtime_values = set(replay_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.values())
        runtime_scripts = {
            path for path in runtime_values if Path(path).suffix in {".py", ".sh"}
        }
        runtime_contracts = {
            path for path in runtime_values if Path(path).suffix == ".json"
        }
        self.assertEqual(runtime_values, runtime_scripts | runtime_contracts)
        self.assertLessEqual(runtime_scripts, set(evidence.FUTURE_SOURCE_PATHS))
        self.assertEqual(
            tuple(sorted(runtime_contracts)), evidence.RUNTIME_CONTRACT_DOCUMENT_PATHS
        )

    def test_missing_substituted_or_rehashed_authority_is_rejected(self) -> None:
        baseline = self._build()
        for mutation in (
            "missing",
            "adoption",
            "source",
            "contract",
            "receipt",
            "time",
        ):
            payload = copy.deepcopy(baseline)
            if mutation == "missing":
                payload.pop("external_review_manifest")
            elif mutation == "adoption":
                payload["formalization_adoption"][adoption.SELF_HASH_FIELD] = "f" * 64
            elif mutation == "source":
                payload["future_source_artifacts"][0]["sha256"] = "e" * 64
                payload["future_source_artifacts_hash"] = evidence._source_hash(
                    payload["future_source_artifacts"]
                )
                for receipt in payload["test_receipts"]:
                    receipt["source_artifacts_hash"] = payload["future_source_artifacts_hash"]
                    receipt["test_receipt_hash"] = evidence.test_receipt_hash(receipt)
            elif mutation == "contract":
                payload["scientific_authorities"]["runtime_contract_documents"][0][
                    "sha256"
                ] = "d" * 64
            elif mutation == "receipt":
                payload["test_receipts"][0]["tests_run"] += 1
                payload["test_receipts"][0]["test_receipt_hash"] = evidence.test_receipt_hash(
                    payload["test_receipts"][0]
                )
            else:
                payload["test_receipts"][1]["completed_at"] = "2026-08-08T13:20:00+08:00"
                payload["test_receipts"][1]["test_receipt_hash"] = evidence.test_receipt_hash(
                    payload["test_receipts"][1]
                )
            payload[evidence.SELF_HASH_FIELD] = evidence._hash(
                payload, evidence.SELF_HASH_FIELD
            )
            with self.subTest(mutation=mutation):
                with self.assertRaises(evidence.ReviewEvidenceError):
                    self._validate(payload, verify_files=True)

    def test_live_source_drift_is_rejected(self) -> None:
        payload = self._build()
        path = self.root / evidence.FUTURE_SOURCE_PATHS[-1]
        path.write_bytes(path.read_bytes() + b"# drift\n")
        with self.assertRaisesRegex(evidence.ReviewEvidenceError, "future source drift"):
            self._validate(payload)

    def test_publication_requires_dual_ack_and_is_no_clobber(self) -> None:
        payload = self._build()
        with self.assertRaises(evidence.ReviewEvidenceError):
            evidence.publish_evidence_lock(
                payload,
                root=self.root,
                ack_review_evidence_only=False,
                ack_no_execution_authority=True,
            )
        patcher, binding = self._authority_patches()
        with patcher as patched:
            patched["load_and_validate_historical_adoption"].return_value = (
                self.adoption_payload,
                self.adoption_record,
            )
            patched["adoption_authority_binding"].return_value = binding
            with mock.patch.object(
                evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
            ):
                evidence.publish_evidence_lock(
                    payload,
                    root=self.root,
                    ack_review_evidence_only=True,
                    ack_no_execution_authority=True,
                )
                before = (self.root / evidence.OUTPUT_RELATIVE).read_bytes()
                with self.assertRaises(FileExistsError):
                    evidence.publish_evidence_lock(
                        payload,
                        root=self.root,
                        ack_review_evidence_only=True,
                        ack_no_execution_authority=True,
                    )
        self.assertEqual((self.root / evidence.OUTPUT_RELATIVE).read_bytes(), before)
        self.assertEqual(
            adoption_fixture._preserved_rollbacks(
                self.root, evidence.OUTPUT_RELATIVE
            ),
            [],
        )

    def test_postlink_source_race_rolls_back_only_own_destination(self) -> None:
        payload = self._build()
        target = self.root / evidence.FUTURE_SOURCE_PATHS[-1]
        original = target.read_bytes()

        def drift() -> None:
            target.write_bytes(original + b"# raced\n")

        patcher, binding = self._authority_patches()
        with patcher as patched:
            patched["load_and_validate_historical_adoption"].return_value = (
                self.adoption_payload,
                self.adoption_record,
            )
            patched["adoption_authority_binding"].return_value = binding
            with mock.patch.object(
                evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
            ):
                with self.assertRaises(evidence.ReviewRollbackIncomplete) as raised:
                    evidence.publish_evidence_lock(
                        payload,
                        root=self.root,
                        ack_review_evidence_only=True,
                        ack_no_execution_authority=True,
                        _post_link_test_hook=drift,
                    )
        self.assertFalse((self.root / evidence.OUTPUT_RELATIVE).exists())
        preserved = adoption_fixture._preserved_rollbacks(
            self.root, evidence.OUTPUT_RELATIVE
        )
        self.assertEqual(preserved, [raised.exception.retained_path])
        self.assertEqual(preserved[0].read_bytes(), adoption.json_bytes(payload))
        opened, lexical = adoption_fixture._retained_identity_views(preserved[0])
        self.assertEqual(opened, lexical)
        self.assertEqual(raised.exception.retained_identity, lexical)
        self.assertEqual(lexical["nlink"], 1)

    def test_persistent_directory_fsync_failure_keeps_structured_rollback(self) -> None:
        payload = self._build()
        target = self.root / evidence.OUTPUT_RELATIVE
        partial_pattern = f".{target.name}.partial.*"

        def publish(*, pre_hook=None):
            patcher, binding = self._authority_patches()
            with patcher as patched:
                patched["load_and_validate_historical_adoption"].return_value = (
                    self.adoption_payload,
                    self.adoption_record,
                )
                patched["adoption_authority_binding"].return_value = binding
                with mock.patch.object(
                    evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
                ):
                    return evidence.publish_evidence_lock(
                        payload,
                        root=self.root,
                        ack_review_evidence_only=True,
                        ack_no_execution_authority=True,
                        _pre_link_test_hook=pre_hook,
                    )

        with mock.patch.object(
            evidence.formal_io,
            "_fsync_directory",
            side_effect=OSError(errno.EIO, "persistent directory fsync failure"),
        ):
            with self.assertRaises(evidence.ReviewRollbackIncomplete) as raised:
                publish()

        preserved = adoption_fixture._preserved_rollbacks(
            self.root, evidence.OUTPUT_RELATIVE
        )
        self.assertEqual(
            raised.exception.reason,
            "PRESERVED_ROLLBACK_DIRECTORY_FSYNC_FAILED",
        )
        self.assertEqual(preserved, [raised.exception.retained_path])
        self.assertEqual(preserved[0].read_bytes(), adoption.json_bytes(payload))
        opened, lexical = adoption_fixture._retained_identity_views(preserved[0])
        self.assertEqual(opened, lexical)
        self.assertEqual(raised.exception.retained_identity, lexical)
        self.assertEqual(lexical["nlink"], 1)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(partial_pattern)), [])
        preserved[0].unlink()

        def fail_before_link() -> None:
            raise evidence.ReviewEvidenceError("injected pre-link failure")

        with mock.patch.object(
            evidence.formal_io,
            "_fsync_directory",
            side_effect=OSError(errno.EIO, "persistent directory fsync failure"),
        ):
            with self.assertRaises(OSError) as cleanup_failure:
                publish(pre_hook=fail_before_link)
        self.assertEqual(cleanup_failure.exception.errno, errno.EIO)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(partial_pattern)), [])

    def test_postlink_unknown_review_winner_is_never_deleted(self) -> None:
        payload = self._build()
        target = self.root / evidence.FUTURE_SOURCE_PATHS[-1]
        original = target.read_bytes()
        canonical = self.root / evidence.OUTPUT_RELATIVE
        retained_own = canonical.with_name("test-retained-own-evidence.json")
        winner = b"unknown review winner must survive"

        def replace_destination() -> None:
            target.write_bytes(original + b"# raced\n")
            os.rename(canonical, retained_own)
            canonical.write_bytes(winner)

        patcher, binding = self._authority_patches()
        with patcher as patched:
            patched["load_and_validate_historical_adoption"].return_value = (
                self.adoption_payload,
                self.adoption_record,
            )
            patched["adoption_authority_binding"].return_value = binding
            with mock.patch.object(
                evidence.epoch, "validate_lock_payload", return_value=self.epoch_hash
            ):
                with self.assertRaisesRegex(
                    evidence.ReviewRollbackIncomplete,
                    "UNKNOWN_CANONICAL_WINNER_RETAINED",
                ) as raised:
                    evidence.publish_evidence_lock(
                        payload,
                        root=self.root,
                        ack_review_evidence_only=True,
                        ack_no_execution_authority=True,
                        _post_link_test_hook=replace_destination,
                    )
        self.assertEqual(raised.exception.retained_path, canonical.absolute())
        self.assertEqual(canonical.read_bytes(), winner)
        self.assertEqual(retained_own.read_bytes(), adoption.json_bytes(payload))

    def test_default_cli_is_read_only_blocked_without_receipts(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(evidence.ROOT / evidence.BUILDER_RELATIVE),
                "--root",
                str(self.root),
                "--frozen-at",
                "2026-08-08T13:50:00+08:00",
            ],
            cwd=evidence.ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn(b"READ_ONLY_BLOCKED", completed.stdout)
        self.assertFalse((self.root / evidence.OUTPUT_RELATIVE).exists())

    def test_real_incident_to_adoption_review_sequence_is_transactional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts = incident_fixture.IncidentFixture(root)
            incident_payload = incident.build_incident(
                root=root,
                observed_at=incident_fixture.OBSERVED_AT,
                require_output_absent=True,
            )
            incident.publish_incident(incident_payload, root=root)

            live = copy.deepcopy(self.base.live)
            source_records = live.get("source_artifacts")
            self.assertIsInstance(source_records, list)
            copy_paths = {
                *adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS,
                *[str(item["path"]) for item in source_records],
                "papers/ieee_sensors_journal_experiments/p07/split_role_audit_v1.csv",
            }
            for relative in sorted(copy_paths):
                candidate = self.base.root / relative
                source = candidate if candidate.is_file() else evidence.ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())

            def administrative_receipt(
                role: str,
                identity: dict[str, str],
                completed_at: str,
                source_hash: str,
            ) -> dict[str, object]:
                return adoption.build_administrative_test_receipt(
                    receipt_role=role,
                    completed_at=completed_at,
                    producer_identity=identity,
                    command_argv=adoption.ADMINISTRATIVE_TEST_ARGV,
                    test_methods=adoption.ADMINISTRATIVE_TEST_METHODS,
                    tests_run=len(adoption.ADMINISTRATIVE_TEST_METHODS),
                    return_code=0,
                    stdout_sha256="1" * 64,
                    stderr_sha256="2" * 64,
                    candidate_source_bindings_hash=source_hash,
                )

            external_identity = {
                "reviewer_id": "external-builder",
                "reviewer_instance": "external-builder-01",
                "reviewer_role": "EXTERNAL_MANIFEST_BUILDER",
            }
            global_identity = {
                "reviewer_id": "global-reviewer",
                "reviewer_instance": "global-reviewer-01",
                "reviewer_role": adoption.GLOBAL_REVIEWER_ROLE,
            }
            independent_identity = {
                "reviewer_id": "independent-reviewer",
                "reviewer_instance": "independent-reviewer-01",
                "reviewer_role": adoption.INDEPENDENT_REVIEWER_ROLE,
            }
            governance_records = [
                evidence._file_record(root, path, label="chain governance")
                for path in adoption.EXTERNAL_REVIEW_GOVERNANCE_PATHS
            ]
            governance_hash = evidence._source_hash(governance_records)
            external_receipt = administrative_receipt(
                "EXTERNAL_MANIFEST_PREFLIGHT",
                external_identity,
                "2099-08-08T04:05:00+00:00",
                governance_hash,
            )
            with mock.patch.object(
                adoption, "collect_live_rebuild_evidence", return_value=live
            ):
                manifest = evidence._build_external_manifest_from_receipt(
                    root=root,
                    frozen_at="2099-08-08T04:06:00+00:00",
                    administrative_test_receipt=external_receipt,
                )
                evidence.publish_external_manifest(
                    manifest,
                    root=root,
                    ack_external_review_manifest_only=True,
                    ack_no_execution_authority=True,
                )
                global_receipt = administrative_receipt(
                    "GLOBAL_STABILITY_ADMINISTRATIVE",
                    global_identity,
                    "2099-08-08T04:07:00+00:00",
                    str(live["source_bindings_hash"]),
                )
                global_review = evidence._build_global_review_from_receipt(
                    root=root,
                    reviewed_at="2099-08-08T04:08:00+00:00",
                    reviewer_identity=global_identity,
                    administrative_test_receipt=global_receipt,
                )
                evidence.publish_global_review(
                    global_review,
                    root=root,
                    ack_global_stability_review_only=True,
                    ack_no_execution_authority=True,
                )
                independent_receipt = administrative_receipt(
                    "INDEPENDENT_ADMINISTRATIVE_REPLAY",
                    independent_identity,
                    "2099-08-08T04:09:00+00:00",
                    str(live["source_bindings_hash"]),
                )
                independent_go = evidence._build_independent_go_from_receipt(
                    root=root,
                    reviewed_at="2099-08-08T04:10:00+00:00",
                    reviewer_identity=independent_identity,
                    administrative_test_receipt=independent_receipt,
                )
                evidence.publish_independent_go(
                    independent_go,
                    root=root,
                    ack_independent_adoption_review_only=True,
                    ack_no_execution_authority=True,
                )
                forged_downstream = root / evidence.OUTPUT_RELATIVE
                forged_downstream.write_bytes(b"forged downstream authority\n")
                with self.assertRaisesRegex(adoption.AdoptionError, "downstream"):
                    adoption.build_adoption(
                        root=root,
                        adopted_at="2099-08-08T04:11:00+00:00",
                        ack_administrative_adoption_only=True,
                        ack_no_execution_authority=True,
                    )
                forged_downstream.unlink()
                adopted = adoption.build_adoption(
                    root=root,
                    adopted_at="2099-08-08T04:11:00+00:00",
                    ack_administrative_adoption_only=True,
                    ack_no_execution_authority=True,
                )
                adoption.publish_adoption_no_clobber(
                    adopted,
                    root=root,
                    ack_administrative_adoption_only=True,
                    ack_no_execution_authority=True,
                )
                self.assertEqual(
                    adoption.validate_adoption_historical(adopted, root=root),
                    adopted[adoption.SELF_HASH_FIELD],
                )
            self.assertTrue(facts.path(adoption.OUTPUT_RELATIVE).is_file())


if __name__ == "__main__":
    unittest.main()
