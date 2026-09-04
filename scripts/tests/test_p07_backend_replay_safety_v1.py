from __future__ import annotations

import csv
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_p07_backend_replay_v1 as auditor
from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as b0_bridge
from scripts import check_p07_backend_replay_input_v1 as checker
from scripts import p07_backend_replay_common_v1 as common
from scripts import run_p07_backend_replay_adapter_v1 as adapter
from scripts import run_p07_backend_replay_job_v1 as job


def write_canonical_json(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(common.formal_io.json_bytes(payload))


class P07BackendReplaySafetyV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.g0_authority_patch = mock.patch.object(
            common.g0_governance,
            "validate_execution_authority_binding",
            side_effect=lambda payload, **_kwargs: payload[
                "g0_execution_authority_hash"
            ],
        )
        self.g0_authority_patch.start()
        def validate_fixture_adoption(value, **_kwargs):
            if not isinstance(value, dict):
                raise b0_bridge.adoption.AdoptionError(
                    "fixture adoption binding missing"
                )
            return dict(value)

        self.adoption_authority_patch = mock.patch.object(
            b0_bridge.adoption,
            "validate_adoption_authority_binding",
            side_effect=validate_fixture_adoption,
        )
        self.adoption_authority_patch.start()
        self.review_evidence_authority_patch = mock.patch.object(
            b0_bridge.review_evidence,
            "validate_review_evidence_authority_binding",
            side_effect=lambda value, **_kwargs: dict(value),
        )
        self.review_evidence_authority_patch.start()
        self.lock_fd = os.open(
            self.root / "fixture-backend.lock", os.O_RDWR | os.O_CREAT, 0o600
        )
        self.bag = self.root / "logs/frontend/source/features.bag"
        self.bag.parent.mkdir(parents=True)
        self.bag.write_bytes(b"fixture frozen feature bag\n")
        self.attestation = self.bag.with_name("features.bag.quality-contract.json")
        self.audit = self.root / "papers/ieee_sensors_journal_experiments/p07/source_audit.json"
        self.audit.parent.mkdir(parents=True)
        self._write_native_attestation(self.attestation)
        self._write_frontend_audit(self.audit, common.B1_ARM)
        self.row = self._row(common.B1_ARM)

        manifest = (
            self.root
            / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
        )
        raw = self.root / "datasets/full_downloads/ntnu_hf/fjord_6.bag"
        reference = self.root / "datasets/full_downloads/ntnu_hf/fjord_6.tum"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(b"raw fixture")
        reference.write_text("reference fixture\n", encoding="utf-8")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "dataset_family,sequence,raw_input_path,reference_path\n"
            f"ntnu,fjord_6,{raw.relative_to(self.root)},{reference.relative_to(self.root)}\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.g0_authority_patch.stop()
        self.adoption_authority_patch.stop()
        self.review_evidence_authority_patch.stop()
        os.close(self.lock_fd)
        self.tempdir.cleanup()

    def _write_native_attestation(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": "aqua-fe-nativeq-bag-attestation-v1",
                    "contract_pass": True,
                    "backend_contract_hash": checker.NATIVEQ_CONTRACT_HASH,
                    "feature_bag": str(self.bag),
                    "feature_bag_sha256": common.sha256(self.bag),
                }
            ),
            encoding="utf-8",
        )

    def _write_frontend_audit(self, path: Path, arm: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": "isj-p07-frontend-export-audit-v4",
                    "status": "PASS",
                    "window_id": "ntnu:fjord_6:fixture",
                    "arm": arm,
                    "held_out_trajectory_outcome_read": False,
                    "forbidden_outcome_artifacts": [],
                    "feature_bag": {
                        "path": str(self.bag),
                        "sha256": common.sha256(self.bag),
                    },
                    "attestation": {
                        "path": str(self.attestation),
                        "sha256": common.sha256(self.attestation),
                    },
                }
            ),
            encoding="utf-8",
        )

    def _row(self, arm: str, *, queue_index: int = 1) -> dict[str, str]:
        mode = common.EXPECTED_RUNNER_MODE[arm]
        method = common.EXPECTED_RUNNER_METHOD[arm]
        tag = f"fixture_{arm.split('_', 1)[0].lower()}_b01"
        argv = [
            "python3",
            "scripts/run_p07_backend_replay_job_v1.py",
            "--queue-index",
            str(queue_index),
            "--execution-lock",
            "papers/ieee_sensors_journal_experiments/p07/backend_replay_execution_lock_v1.json",
        ]
        argv_json = json.dumps(argv, separators=(",", ":"), ensure_ascii=True)
        feature_values = arm != common.B0_ARM
        source_run_id = (
            "fixture-frontend-source"
            if feature_values
            else "B0_NATIVE_DATA:ntnu:fjord_6:fixture"
        )
        source_kind = (
            "CANONICAL_FRONTEND_COMPLETED"
            if feature_values
            else "B0_NATIVE_DATA_IDENTITY_V1"
        )
        source_provenance = {
            "kind": source_kind,
            "source_run_id": source_run_id,
            "window_id": "ntnu:fjord_6:fixture",
            "held_out_trajectory_outcome_read": False,
        }
        return {
            "schema_version": common.QUEUE_SCHEMA,
            "queue_index": str(queue_index),
            "assignment_rank": "1",
            "pattern_id": "0",
            "arm_order_position": "1",
            "replay_index": "1",
            "algorithmic_slot": "b01",
            "run_id": f"fixture-run-{queue_index}",
            "window_id": "ntnu:fjord_6:fixture",
            "dataset_family": "ntnu",
            "data_domain": "fixture",
            "sequence": "fjord_6",
            "window_start_s": "10",
            "window_end_s": "20",
            "runner_start": "10",
            "runner_end_or_duration": "10",
            "runner_unit": "second",
            "runner_mode": mode,
            "runner_method": method,
            "runner_every_n": "2",
            "runner_tag": tag,
            "texture_stratum": "low",
            "selection_tier": "ABSOLUTE_LOW",
            "arm": arm,
            "arm_role": "fixture",
            "applicability": "REQUIRED",
            "source_frontend_queue_index": "1" if feature_values else "",
            "source_d_slot_index": "",
            "source_run_id": source_run_id,
            "source_provenance_kind": source_kind,
            "source_provenance_hash": common.sha256_bytes(
                json.dumps(
                    source_provenance,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ),
            "feature_bag": str(self.bag.relative_to(self.root)) if feature_values else "",
            "feature_bag_sha256": common.sha256(self.bag) if feature_values else "",
            "attestation_path": (
                str(self.attestation.relative_to(self.root)) if feature_values else ""
            ),
            "attestation_sha256": (
                common.sha256(self.attestation) if feature_values else ""
            ),
            "input_audit_path": str(self.audit.relative_to(self.root)) if feature_values else "",
            "input_audit_sha256": common.sha256(self.audit) if feature_values else "",
            "replay_argv_json": argv_json,
            "replay_argv_sha256": common.sha256_bytes(argv_json.encode("utf-8")),
            "expected_run_dir": f"logs/ntnu_vins/{mode}_{method}_every2_{tag}",
            "expected_attempt_dir": (
                "papers/ieee_sensors_journal_experiments/p07/backend_attempts/fixture"
                f"_{queue_index}"
            ),
            "evaluator_profile_id": "fixture",
            "estimated_output_bytes": "1024",
            "status": "PLANNED",
            "method_lock_hash": "a" * 64,
            "environment_manifest_sha256": "b" * 64,
            "evaluator_protocol_sha256": "c" * 64,
            "evaluator_implementation_sha256": "d" * 64,
            "failure_taxonomy_sha256": "e" * 64,
            "capacity_policy": "REMAINING_ESTIMATE_X1P2_PLUS_2GIB_RESERVE",
            "outcome_boundary": "BACKEND_QUEUE_FROZEN_BEFORE_P07_TRAJECTORY_OUTCOME",
        }

    def _write_execution_lock_fixture(
        self,
    ) -> tuple[Path, Path, Path, Path, dict[str, object]]:
        queue = self.root / "papers/p07/backend_replay_queue_v1.csv"
        allocation = self.root / "papers/p07/backend_run_allocation_v1.csv"
        registry = self.root / "papers/run_registry.csv"
        execution_lock = self.root / "papers/p07/backend_replay_execution_lock_v1.json"
        queue.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("run_id,status\n", encoding="utf-8")
        with queue.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerow(self.row)
        allocation_row = {
            "schema_version": common.ALLOCATION_SCHEMA,
            **{
                key: self.row[key]
                for key in (
                    "queue_index",
                    "run_id",
                    "window_id",
                    "dataset_family",
                    "sequence",
                    "arm",
                    "replay_index",
                    "algorithmic_slot",
                    "feature_bag",
                    "feature_bag_sha256",
                    "attestation_path",
                    "attestation_sha256",
                    "expected_run_dir",
                    "expected_attempt_dir",
                    "method_lock_hash",
                    "source_run_id",
                    "source_provenance_kind",
                    "source_provenance_hash",
                )
            },
            "status": "PLANNED",
        }
        with allocation.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(allocation_row))
            writer.writeheader()
            writer.writerow(allocation_row)
        entrypoint = self.root / "scripts/run_p07_backend_replay_job_v1.py"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("# fixture job\n", encoding="utf-8")
        record = {
            "path": entrypoint.relative_to(self.root).as_posix(),
            "sha256": common.sha256(entrypoint),
            "size_bytes": entrypoint.stat().st_size,
        }
        critical_paths = [
            "scripts/run_p07_backend_replay_only_v1.sh",
            "scripts/prepare_p07_backend_replay_config_v1.py",
            "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
            "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
            "papers/ieee_sensors_journal_experiments/reference_audit.csv",
            "papers/ieee_sensors_journal_experiments/p07/backend_replacement_contract_v1.json",
            "scripts/build_p07_backend_replacement_contract_v1.py",
            "scripts/allocate_p07_backend_replacement_v1.py",
            common.FORMALIZATION_ADOPTION_PATH,
            common.FORMALIZATION_REVIEW_EVIDENCE_PATH,
            *(
                path
                for path in common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.values()
                if path != record["path"]
            ),
        ]
        artifact_records = [record]
        for relative in dict.fromkeys(critical_paths):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                prefix = "# " if path.suffix == ".py" else ""
                path.write_text(f"{prefix}fixture {relative}\n", encoding="utf-8")
            artifact_records.append(
                {
                    "path": relative,
                    "sha256": common.sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        replacement_record = next(
            item
            for item in artifact_records
            if item["path"].endswith("backend_replacement_contract_v1.json")
        )
        artifact_by_path = {
            str(item["path"]): item for item in artifact_records
        }
        runtime_bindings = {
            role: artifact_by_path[path]
            for role, path in common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.items()
        }
        g0_lock_path = self.root / "papers/p07/g0_evaluation_lock_v1.json"
        g0_lock_path.write_text("{}\n", encoding="utf-8")
        g0_lock_record = {
            "path": g0_lock_path.relative_to(self.root).as_posix(),
            "sha256": common.sha256(g0_lock_path),
            "size_bytes": g0_lock_path.stat().st_size,
        }
        artifact_records.append(g0_lock_record)
        g0_authority = {
            "schema_version": common.g0_governance.EXECUTION_AUTHORITY_SCHEMA,
            "status": common.g0_governance.EXECUTION_AUTHORITY_STATUS,
            "evaluation_lock": {
                **g0_lock_record,
                "evaluation_lock_hash": "d" * 64,
            },
            "g0_execution_authority_hash": "e" * 64,
        }
        prefix = {
            "path": registry.relative_to(self.root).as_posix(),
            "sha256": common.sha256(registry),
            "size_bytes": registry.stat().st_size,
        }
        source_provenance = {
            "kind": self.row["source_provenance_kind"],
            "source_run_id": self.row["source_run_id"],
            "window_id": self.row["window_id"],
            "held_out_trajectory_outcome_read": False,
        }
        queue_lock_payload = {
            "schema_version": common.QUEUE_LOCK_SCHEMA,
            "status": common.QUEUE_LOCK_STATUS,
            "artifacts": [record],
            "mutable_registry_prefix": prefix,
            "source_evidence": [
                {
                    "window_id": self.row["window_id"],
                    "arm": self.row["arm"],
                    "feature_bag": self.row["feature_bag"],
                    "feature_bag_sha256": self.row["feature_bag_sha256"],
                    "attestation_path": self.row["attestation_path"],
                    "attestation_sha256": self.row["attestation_sha256"],
                    "input_audit_path": self.row["input_audit_path"],
                    "input_audit_sha256": self.row["input_audit_sha256"],
                    "source_run_id": self.row["source_run_id"],
                    "source_provenance_kind": self.row[
                        "source_provenance_kind"
                    ],
                    "source_provenance_hash": self.row[
                        "source_provenance_hash"
                    ],
                    "source_provenance": source_provenance,
                }
            ],
        }
        queue_lock_payload["backend_queue_lock_hash"] = common.canonical_json_hash(
            queue_lock_payload, "backend_queue_lock_hash"
        )
        queue_lock_path = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07/"
            "backend_queue_lock_v1.json"
        )
        queue_lock_path.parent.mkdir(parents=True, exist_ok=True)
        write_canonical_json(queue_lock_path, queue_lock_payload)
        artifact_records.append(
            {
                "path": queue_lock_path.relative_to(self.root).as_posix(),
                "sha256": common.sha256(queue_lock_path),
                "size_bytes": queue_lock_path.stat().st_size,
            }
        )
        raw = self.root / "datasets/full_downloads/ntnu_hf/fjord_6.bag"
        reference = self.root / "datasets/full_downloads/ntnu_hf/fjord_6.tum"
        identity_entries = []
        for path, kind in ((raw, "raw"), (reference, "reference")):
            identity = common.capture_canonical_input_identity(
                self.root,
                path.relative_to(self.root).as_posix(),
                expected_sha256=common.sha256(path),
                verify_sha256=True,
            )
            identity.update(
                {
                    "kinds": [kind],
                    "datasets": ["ntnu:fjord_6"],
                    "sha256_verified_at_freeze": True,
                }
            )
            identity_entries.append(identity)
        identity_manifests = [
            next(item for item in artifact_records if item["path"] == relative)
            for relative in (
                "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
                "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
                "papers/ieee_sensors_journal_experiments/reference_audit.csv",
            )
        ]
        data_identity = {
            "schema_version": common.DATA_IDENTITY_SCHEMA,
            "status": common.DATA_IDENTITY_STATUS,
            "manifest_records": identity_manifests,
            "dataset_bindings": [
                {
                    "dataset_family": "ntnu",
                    "sequence": "fjord_6",
                    "raw_input_path": raw.relative_to(self.root).as_posix(),
                    "reference_path": reference.relative_to(self.root).as_posix(),
                    "calibration_paths": [],
                }
            ],
            "entries": identity_entries,
            "verification": {
                "full_sha256_once_at_execution_lock_freeze": True,
                "stat_identity_before_each_replay": True,
                "manifest_files_rehashed_before_each_replay": True,
                "symlink_chain_before_each_replay": True,
                "trajectory_values_interpreted": False,
            },
        }
        data_identity[common.DATA_IDENTITY_SELF_HASH] = common.canonical_json_hash(
            data_identity, common.DATA_IDENTITY_SELF_HASH
        )
        def write_b0_authority(
            relative: str,
            payload: dict[str, object],
            self_hash_field: str,
        ) -> dict[str, object]:
            payload[self_hash_field] = common.canonical_json_hash(
                payload, self_hash_field
            )
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            write_canonical_json(path, payload)
            artifact = {
                "path": relative,
                "sha256": common.sha256(path),
                "size_bytes": path.stat().st_size,
            }
            artifact_records.append(artifact)
            return artifact

        b0_plan = {
            "schema_version": "isj-p07-backend-b0-materialization-lock-v1",
            "status": "FROZEN_READY_FOR_EXPLICIT_B0_MATERIALIZATION",
        }
        b0_plan_record = write_b0_authority(
            common.B0_MATERIALIZATION_LOCK_PATH,
            b0_plan,
            "materialization_lock_hash",
        )
        b0_intent = {
            "schema_version": "isj-p07-backend-b0-materialization-intent-v1",
            "status": "FROZEN_BEFORE_FIRST_B0_TARGET_MUTATION",
            "materialization_lock_hash": b0_plan["materialization_lock_hash"],
        }
        b0_intent_record = write_b0_authority(
            common.B0_MATERIALIZATION_INTENT_PATH,
            b0_intent,
            "materialization_intent_hash",
        )
        b0_receipt = {
            "schema_version": "isj-p07-backend-b0-materialization-receipt-v1",
            "status": "PASS_ALL_B0_INPUTS_EXACT_AND_OUTCOME_BLIND",
            "materialization_lock": b0_plan_record,
            "materialization_lock_hash": b0_plan["materialization_lock_hash"],
            "materialization_intent": b0_intent_record,
            "materialization_intent_hash": b0_intent[
                "materialization_intent_hash"
            ],
        }
        b0_receipt_record = write_b0_authority(
            common.B0_MATERIALIZATION_RECEIPT_PATH,
            b0_receipt,
            "materialization_receipt_hash",
        )
        b0_play_inputs = {
            "schema_version": common.B0_PLAY_INPUTS_SCHEMA,
            "status": common.B0_PLAY_INPUTS_STATUS,
            "materialization_lock_hash": b0_plan["materialization_lock_hash"],
            "materialization_intent_hash": b0_intent[
                "materialization_intent_hash"
            ],
            "materialization_receipt_hash": b0_receipt[
                "materialization_receipt_hash"
            ],
            "materialization_receipt": b0_receipt_record,
            "entries": [],
            "queue_bindings": [],
            "policy": {
                "all_b0_queue_rows_bound": True,
                "full_sha256_before_and_after_each_replay": True,
                "path_link_target_identity_before_and_after_each_replay": True,
                "preparation_must_not_create_or_replace_play_input": True,
                "derived_inputs_materialized_before_execution_lock": True,
                "trajectory_values_interpreted": False,
            },
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": common.B0_OUTCOME_BOUNDARY,
        }
        b0_play_inputs[common.B0_PLAY_INPUTS_SELF_HASH] = common.canonical_json_hash(
            b0_play_inputs, common.B0_PLAY_INPUTS_SELF_HASH
        )
        b0_final_path = self.root / common.B0_PLAY_INPUTS_PATH
        b0_final_path.parent.mkdir(parents=True, exist_ok=True)
        write_canonical_json(b0_final_path, b0_play_inputs)
        artifact_records.append(
            {
                "path": common.B0_PLAY_INPUTS_PATH,
                "sha256": common.sha256(b0_final_path),
                "size_bytes": b0_final_path.stat().st_size,
            }
        )
        adoption_binding = {
            "path": common.FORMALIZATION_ADOPTION_PATH,
            "sha256": next(
                item["sha256"]
                for item in artifact_records
                if item["path"] == common.FORMALIZATION_ADOPTION_PATH
            ),
            "size_bytes": next(
                item["size_bytes"]
                for item in artifact_records
                if item["path"] == common.FORMALIZATION_ADOPTION_PATH
            ),
            b0_bridge.adoption.SELF_HASH_FIELD: "a" * 64,
        }
        evidence_record = next(
            item
            for item in artifact_records
            if item["path"] == common.FORMALIZATION_REVIEW_EVIDENCE_PATH
        )
        review_evidence_binding = {
            **evidence_record,
            b0_bridge.review_evidence.SELF_HASH_FIELD: "9" * 64,
        }
        replacement_payload = {
            "schema_version": "isj-p07-backend-replacement-contract-v1",
            "status": "FROZEN_READY_FOR_INFRASTRUCTURE_REPLACEMENT_ALLOCATION",
            "formalization_adoption": adoption_binding,
            "formalization_review_evidence": review_evidence_binding,
        }
        replacement_payload["replacement_contract_hash"] = (
            common.canonical_json_hash(
                replacement_payload, "replacement_contract_hash"
            )
        )
        replacement_path = self.root / str(replacement_record["path"])
        write_canonical_json(replacement_path, replacement_payload)
        replacement_record.update(
            {
                "sha256": common.sha256(replacement_path),
                "size_bytes": replacement_path.stat().st_size,
            }
        )
        bridge_sources = [
            {"path": relative, "sha256": "b" * 64, "size_bytes": 1}
            for relative in b0_bridge.REQUIRED_SOURCE_PATHS
        ]
        b0_prelock = b0_bridge.build_prelock_payload(
            frozen_at="2026-08-08T00:00:00+08:00",
            adoption_binding=adoption_binding,
            review_evidence_binding=review_evidence_binding,
            plan_record=b0_plan_record,
            plan_hash=str(b0_plan["materialization_lock_hash"]),
            source_artifacts=bridge_sources,
        )
        b0_prelock_path = self.root / common.B0_ADOPTION_PRELOCK_PATH
        b0_prelock_path.parent.mkdir(parents=True, exist_ok=True)
        write_canonical_json(b0_prelock_path, b0_prelock)
        b0_prelock_record = {
            "path": common.B0_ADOPTION_PRELOCK_PATH,
            "sha256": common.sha256(b0_prelock_path),
            "size_bytes": b0_prelock_path.stat().st_size,
        }
        artifact_records.append(b0_prelock_record)
        action_started_at = "2026-08-08T00:00:10+08:00"
        action_completed_at = "2026-08-08T00:00:20+08:00"
        action_closed_at = "2026-08-08T00:01:00+08:00"
        wrapper_argv = b0_bridge.canonical_wrapper_argv(
            action_started_at=action_started_at,
            completed_at=action_completed_at,
            closed_at=action_closed_at,
            timeout_s=60,
        )
        b0_action = b0_bridge.build_action_intent_payload(
            recorded_at=action_started_at,
            completed_at=action_completed_at,
            closed_at=action_closed_at,
            timeout_s=60,
            adoption_binding=adoption_binding,
            review_evidence_binding=review_evidence_binding,
            prelock_record=b0_prelock_record,
            prelock_hash=str(b0_prelock[b0_bridge.PRELOCK_HASH]),
            plan_record=b0_plan_record,
            plan_hash=str(b0_plan["materialization_lock_hash"]),
            wrapper_argv=wrapper_argv,
            plan_sources=[],
            source_artifacts=bridge_sources,
            cache_namespace_pre_state=b0_prelock["cache_namespace_pre_state"],
            formal_output_pre_state=b0_prelock["formal_output_pre_state"],
            process_quiescence=b0_prelock["process_quiescence"],
        )
        b0_action_path = self.root / common.B0_ADOPTION_ACTION_INTENT_PATH
        write_canonical_json(b0_action_path, b0_action)
        b0_action_record = {
            "path": common.B0_ADOPTION_ACTION_INTENT_PATH,
            "sha256": common.sha256(b0_action_path),
            "size_bytes": b0_action_path.stat().st_size,
        }
        artifact_records.append(b0_action_record)
        b0_final_record = next(
            item for item in artifact_records if item["path"] == common.B0_PLAY_INPUTS_PATH
        )
        b0_closeout = b0_bridge.build_closeout_payload(
            closed_at="2026-08-08T00:01:00+08:00",
            adoption_binding=adoption_binding,
            review_evidence_binding=review_evidence_binding,
            prelock_record=b0_prelock_record,
            prelock_hash=str(b0_prelock[b0_bridge.PRELOCK_HASH]),
            plan_record=b0_plan_record,
            plan_hash=str(b0_plan["materialization_lock_hash"]),
            intent_record=b0_intent_record,
            intent_hash=str(b0_intent["materialization_intent_hash"]),
            receipt_record=b0_receipt_record,
            receipt_hash=str(b0_receipt["materialization_receipt_hash"]),
            final_record=b0_final_record,
            final_hash=str(b0_play_inputs[common.B0_PLAY_INPUTS_SELF_HASH]),
            action_intent_record=b0_action_record,
            action_intent_hash=str(b0_action[b0_bridge.ACTION_INTENT_HASH]),
        )
        b0_closeout_path = self.root / common.B0_ADOPTION_CLOSEOUT_PATH
        write_canonical_json(b0_closeout_path, b0_closeout)
        b0_closeout_record = {
            "path": common.B0_ADOPTION_CLOSEOUT_PATH,
            "sha256": common.sha256(b0_closeout_path),
            "size_bytes": b0_closeout_path.stat().st_size,
        }
        artifact_records.append(b0_closeout_record)
        payload: dict[str, object] = {
            "schema_version": common.EXECUTION_LOCK_SCHEMA,
            "status": common.EXECUTION_LOCK_STATUS,
            "frozen_at": "2026-08-08T00:02:00+08:00",
            "queue_sha256": common.sha256(queue),
            "allocation_sha256": common.sha256(allocation),
            "queue_lock_sha256": common.sha256(queue_lock_path),
            "validation_sha256": "7" * 64,
            "registration_sha256": "8" * 64,
            "queue_items": 1,
            "formalization_adoption": adoption_binding,
            "formalization_review_evidence": review_evidence_binding,
            "b0_formalization_adoption": {
                "pre_materialization_lock": {
                    **b0_prelock_record,
                    b0_bridge.PRELOCK_HASH: b0_prelock[
                        b0_bridge.PRELOCK_HASH
                    ],
                },
                "materialization_action_intent": {
                    **b0_action_record,
                    b0_bridge.ACTION_INTENT_HASH: b0_action[
                        b0_bridge.ACTION_INTENT_HASH
                    ],
                },
                "post_materialization_closeout": {
                    **b0_closeout_record,
                    b0_bridge.CLOSEOUT_HASH: b0_closeout[
                        b0_bridge.CLOSEOUT_HASH
                    ],
                },
            },
            "backend_queue_lock_hash": queue_lock_payload[
                "backend_queue_lock_hash"
            ],
            "execution_order": [
                {
                    "queue_index": 1,
                    "run_id": self.row["run_id"],
                    "window_id": self.row["window_id"],
                    "arm": self.row["arm"],
                    "replay_index": 1,
                    "algorithmic_slot": "b01",
                    "feature_bag_sha256": self.row["feature_bag_sha256"],
                    "attestation_sha256": self.row["attestation_sha256"],
                    "input_audit_sha256": self.row["input_audit_sha256"],
                    "source_run_id": self.row["source_run_id"],
                    "source_provenance_kind": self.row[
                        "source_provenance_kind"
                    ],
                    "source_provenance_hash": self.row[
                        "source_provenance_hash"
                    ],
                    "expected_run_dir": self.row["expected_run_dir"],
                    "expected_attempt_dir": self.row["expected_attempt_dir"],
                }
            ],
            "allowed_entrypoint": record,
            "executor": record,
            "adapter": runtime_bindings["adapter"],
            "auditor": runtime_bindings["auditor"],
            "runtime_implementation_bindings": runtime_bindings,
            "external_runtime_bindings": {
                role: {
                    "path": str(path),
                    "sha256": common.sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for role, path in common.EXTERNAL_RUNTIME_BINDING_PATHS.items()
            },
            "global_flock_path": str(common.DEFAULT_GLOBAL_FLOCK),
            "serialization": {
                "one_ros_vins_rosbag_group_at_a_time": True,
                "queue_order_mandatory": True,
                "three_replays_per_arm_are_consecutive": True,
            },
            "adapter_policy": {
                "allowed_vins_workspace": str(common.VINS_ORIGIN),
                "forbidden_workspace": str(common.FORBIDDEN_VINS_WORKSPACE),
                "required_environment": {
                    "preparation": {
                        "RUN_VINS": "0",
                        "FORCE_EXPORT": "0",
                        "EXPORT_FEATURES": "0",
                        "RUN_EVALUATION": "0",
                    },
                    "replay_only": {"VINS_MULTIPLE_THREAD": "0"},
                    "formal_ros": dict(common.FROZEN_ROS_ENVIRONMENT),
                    "ros_executables": dict(common.FROZEN_ROS_EXECUTABLES),
                },
                "replay_only_runner": "scripts/run_p07_backend_replay_only_v1.sh",
                "replay_only_config_helper": (
                    "scripts/prepare_p07_backend_replay_config_v1.py"
                ),
                "job_is_only_entrypoint": True,
                "adapter_direct_cli_forbidden": True,
                "b0_external_feature_bag_forbidden": True,
                "feature_arms_require_readonly_fd_override": True,
                "feature_arms_require_sealed_memfd_copy": True,
                "controller_job_and_transitive_modules_require_sealed_memfd": True,
                "unknown_scripts_import_workspace_fallback_forbidden": True,
                "b0_play_input_requires_sealed_memfd_copy": True,
                "attestation_and_input_audit_require_sealed_memfd_copy": True,
                "vins_and_camera_configs_require_sealed_memfd_consumption": True,
                "vins_binary_and_project_libraries_require_sealed_memfd": True,
                "vins_pid_exe_and_maps_identity_check_required": True,
                "aqualoc_afrl_dynamic_cache_conversion_forbidden": True,
                "formal_setup_path_source_forbidden": True,
                "minimal_ros_environment_is_job_constructed": True,
                "ros_cli_absolute_paths_required": True,
                "preparation_runners_run_vins_zero_only": True,
                "replay_only_runner_is_only_ros_replay_path": True,
                "evaluation_during_replay_forbidden": True,
                "ape_rpe_during_replay_forbidden": True,
                "data_identity_check_before_launch_required": True,
                "shell_export_wrapper_forbidden": True,
                "frontend_export_wrapper_forbidden": True,
                "input_sha256_before_and_after_required": True,
                "attestation_sha256_before_and_after_required": True,
                "delete_or_replace_input_forbidden": True,
                "target_no_clobber": True,
            },
            "data_identity_policy": {
                "data_eligibility_manifest": (
                    "papers/ieee_sensors_journal_experiments/"
                    "data_eligibility_manifest.csv"
                ),
                "dataset_checksum_manifest": (
                    "papers/ieee_sensors_journal_experiments/"
                    "dataset_checksum_manifest.txt"
                ),
                "reference_audit": (
                    "papers/ieee_sensors_journal_experiments/reference_audit.csv"
                ),
                "unique_family_sequence_row_required": True,
                "raw_input_identity_and_checksum_required": True,
                "reference_identity_and_checksum_required": True,
                "calibration_identity_and_checksum_required": True,
                "check_before_each_replay": True,
                "trajectory_values_read_by_identity_check": False,
            },
            "infrastructure_replacement": {
                "schema_version": "isj-p07-backend-replacement-contract-v1",
                "status": (
                    "FROZEN_READY_FOR_INFRASTRUCTURE_REPLACEMENT_ALLOCATION"
                ),
                "contract": replacement_record,
                "replacement_contract_hash": replacement_payload[
                    "replacement_contract_hash"
                ],
                "formalization_adoption": adoption_binding,
                "formalization_review_evidence": review_evidence_binding,
                "replacement_lock_schema": (
                    "isj-p07-backend-infrastructure-replacement-lock-v1"
                ),
                "replacement_lock_status": (
                    "FROZEN_PLANNED_INFRASTRUCTURE_REPLACEMENT"
                ),
                "replacement_lock_directory": (
                    "papers/ieee_sensors_journal_experiments/p07/"
                    "backend_replacements"
                ),
                "allocation_index_schema": (
                    "isj-p07-backend-replacement-allocation-v1"
                ),
                "allocation_index_path": (
                    "papers/ieee_sensors_journal_experiments/p07/"
                    "backend_replacement_allocation_v1.csv"
                ),
                "allowed_effective_row_overrides": [
                    "run_id",
                    "runner_tag",
                    "expected_run_dir",
                    "expected_attempt_dir",
                ],
                "replacement_job_flag": "--replacement-lock",
                "new_unique_planned_e00_required": True,
                "replacement_for_immediately_failed_run_id": True,
                "algorithmic_slot_preserved": True,
            },
            "capacity_gate": {
                "policy": "REMAINING_ESTIMATE_X1P2_PLUS_2GIB_RESERVE",
                "margin_numerator": 6,
                "margin_denominator": 5,
                "reserve_bytes": 2 * 1024**3,
                "minimum_governance_free_bytes": 512 * 1024**2,
                "estimated_total_output_bytes": 1024,
                "required_output_free_bytes": 2 * 1024**3 + 1229,
                "observed_output_free_bytes_at_freeze": 10**12,
                "observed_governance_free_bytes_at_freeze": 10**12,
                "output_filesystem_path": "logs",
                "governance_filesystem_path": (
                    "papers/ieee_sensors_journal_experiments/p07"
                ),
                "recompute_before_each_job": True,
                "insufficient_action": "WAITING",
            },
            "artifacts": artifact_records,
            "mutable_registry_prefix": prefix,
            "data_identity_snapshot": data_identity,
            "b0_play_inputs": b0_play_inputs,
            common.g0_governance.EXECUTION_LOCK_BINDING_KEY: g0_authority,
            "method_lock_hash": self.row["method_lock_hash"],
            "trajectory_outcome_read_at_freeze": False,
            "outcome_boundary": common.EXECUTION_OUTCOME_BOUNDARY,
        }
        payload["execution_lock_hash"] = common.canonical_json_hash(
            payload, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, payload)
        return queue, allocation, registry, execution_lock, payload

    def test_native_feature_input_is_cross_hash_bound(self) -> None:
        report = checker.check_row_inputs(self.row, root=self.root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["feature_bag"]["sha256"], common.sha256(self.bag))
        self.assertFalse(report["checks"]["trajectory_outcome_read"])

    def test_bag_or_attestation_drift_fails_closed(self) -> None:
        self.bag.write_bytes(b"mutated\n")
        with self.assertRaisesRegex(common.BackendReplayViolation, "feature bag SHA"):
            checker.check_row_inputs(self.row, root=self.root)

        self.bag.write_bytes(b"fixture frozen feature bag\n")
        self.attestation.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(common.BackendReplayViolation, "attestation SHA"):
            checker.check_row_inputs(self.row, root=self.root)

    def test_d_requires_exact_whole_lineage_drop_audit(self) -> None:
        row = self._row(common.D_ARM)
        row["input_audit_sha256"] = common.sha256(self.audit)
        with self.assertRaisesRegex(common.BackendReplayViolation, "exact-drop"):
            checker.check_row_inputs(row, root=self.root)

        exact = {
            "schema_version": "aqua-fe-whole-lineage-exact-drop-audit-v1",
            "contract_pass": True,
            "decision": "PASS_EXACT_WHOLE_LINEAGE_DROP",
            "forbidden_outcomes_accessed": [],
            "inputs": {
                "drop_bag": str(self.bag),
                "drop_bag_sha256": common.sha256(self.bag),
            },
            "checks": {
                "drop_feature_payload_equals_filtered_proposed_payload_byte_for_byte": True,
                "learned_births_and_all_lineage_continuations_absent_from_drop": True,
                "message_count_order_topic_type_md5_record_timestamp_exact": True,
                "non_dropped_observation_order_fields_channels_exact": True,
                "nonfeature_serialized_bytes_exact": True,
            },
        }
        self.audit.write_text(json.dumps(exact), encoding="utf-8")
        row["input_audit_sha256"] = common.sha256(self.audit)
        self.assertEqual(checker.check_row_inputs(row, root=self.root)["status"], "PASS")

    def test_b0_forbids_reused_feature_inputs(self) -> None:
        row = self._row(common.B0_ARM)
        self.assertFalse(checker.check_row_inputs(row, root=self.root)["feature_bag_reuse"])
        row["feature_bag"] = str(self.bag)
        with self.assertRaisesRegex(common.BackendReplayViolation, "B0 must not bind"):
            checker.check_row_inputs(row, root=self.root)

    def test_formal_argv_rejects_adapter_or_export_wrapper(self) -> None:
        for script in (
            "scripts/run_p07_backend_replay_adapter_v1.py",
            "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
        ):
            row = dict(self.row)
            argv = ["python3", script, "--queue-index", "1"]
            raw = json.dumps(argv, separators=(",", ":"))
            row["replay_argv_json"] = raw
            row["replay_argv_sha256"] = common.sha256_bytes(raw.encode())
            with self.assertRaises(common.BackendReplayViolation):
                common.validate_queue_row(row)

        row = dict(self.row)
        argv = json.loads(row["replay_argv_json"])
        argv.append("--preflight-only")
        raw = json.dumps(argv, separators=(",", ":"))
        row["replay_argv_json"] = raw
        row["replay_argv_sha256"] = common.sha256_bytes(raw.encode())
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "exact governed job invocation"
        ):
            common.validate_queue_row(row)

    def test_execution_lock_binds_each_queue_item_and_registry_prefix(self) -> None:
        queue, allocation, registry, execution_lock, payload = (
            self._write_execution_lock_fixture()
        )
        common.validate_execution_lock(
            self.root,
            execution_lock,
            queue_path=queue,
            allocation_path=allocation,
        )

        for role, relative in common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.items():
            weakened = json.loads(json.dumps(payload))
            weakened["runtime_implementation_bindings"].pop(role)
            weakened["artifacts"] = [
                item
                for item in weakened["artifacts"]
                if item.get("path") != relative
            ]
            weakened["execution_lock_hash"] = common.canonical_json_hash(
                weakened, "execution_lock_hash"
            )
            write_canonical_json(execution_lock, weakened)
            with self.assertRaisesRegex(
                common.BackendReplayViolation,
                "runtime implementation",
            ):
                common.validate_execution_lock(
                    self.root,
                    execution_lock,
                    queue_path=queue,
                    allocation_path=allocation,
                )

        substituted = json.loads(json.dumps(payload))
        substituted["runtime_implementation_bindings"]["serial_controller"] = (
            substituted["runtime_implementation_bindings"]["common"]
        )
        substituted["execution_lock_hash"] = common.canonical_json_hash(
            substituted, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, substituted)
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "runtime implementation"
        ):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

        write_canonical_json(execution_lock, payload)

        with registry.open("a", encoding="utf-8") as handle:
            handle.write("fixture,PLANNED\n")
        common.validate_execution_lock(
            self.root,
            execution_lock,
            queue_path=queue,
            allocation_path=allocation,
        )

        bad_order = json.loads(json.dumps(payload))
        bad_order["execution_order"][0]["run_id"] = "substituted-run"
        bad_order["execution_lock_hash"] = common.canonical_json_hash(
            bad_order, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, bad_order)
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "order/item bindings"
        ):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

        payload["execution_lock_hash"] = common.canonical_json_hash(
            payload, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, payload)
        content = registry.read_bytes()
        registry.write_bytes(b"X" + content[1:])
        with self.assertRaisesRegex(common.BackendReplayViolation, "prefix drift"):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

    def test_execution_lock_rejects_vins_runtime_role_substitution(self) -> None:
        queue, allocation, _registry, execution_lock, payload = (
            self._write_execution_lock_fixture()
        )
        attacked = json.loads(json.dumps(payload))
        attacked["external_runtime_bindings"]["vins_binary"] = attacked[
            "external_runtime_bindings"
        ]["vins_shared_library"]
        attacked["execution_lock_hash"] = common.canonical_json_hash(
            attacked, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, attacked)
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "external runtime path"
        ):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

    def test_execution_lock_rejects_missing_or_rehashed_adoption_bridge(self) -> None:
        queue, allocation, _registry, execution_lock, payload = (
            self._write_execution_lock_fixture()
        )
        mutations = []
        missing = json.loads(json.dumps(payload))
        missing.pop("formalization_adoption")
        mutations.append(missing)
        missing_bridge = json.loads(json.dumps(payload))
        missing_bridge["b0_formalization_adoption"].pop(
            "post_materialization_closeout"
        )
        mutations.append(missing_bridge)
        substituted = json.loads(json.dumps(payload))
        substituted["b0_formalization_adoption"][
            "post_materialization_closeout"
        ]["sha256"] = "f" * 64
        mutations.append(substituted)
        for attacked in mutations:
            attacked["execution_lock_hash"] = common.canonical_json_hash(
                attacked, "execution_lock_hash"
            )
            write_canonical_json(execution_lock, attacked)
            with self.subTest(keys=sorted(attacked)):
                with self.assertRaisesRegex(
                    common.BackendReplayViolation,
                    "adoption|B0|execution lock keys/schema",
                ):
                    common.validate_execution_lock(
                        self.root,
                        execution_lock,
                        queue_path=queue,
                        allocation_path=allocation,
                    )

    def test_execution_lock_rejects_rehashed_schema_and_canonical_json_attacks(
        self,
    ) -> None:
        queue, allocation, _registry, execution_lock, payload = (
            self._write_execution_lock_fixture()
        )

        semantic_mutations: list[dict[str, object]] = []
        missing_top = json.loads(json.dumps(payload))
        missing_top.pop("frozen_at")
        semantic_mutations.append(missing_top)
        extra_top = json.loads(json.dumps(payload))
        extra_top["unreviewed_extension"] = True
        semantic_mutations.append(extra_top)
        outcome_read = json.loads(json.dumps(payload))
        outcome_read["trajectory_outcome_read_at_freeze"] = True
        semantic_mutations.append(outcome_read)
        missing_observation = json.loads(json.dumps(payload))
        missing_observation["capacity_gate"].pop(
            "observed_output_free_bytes_at_freeze"
        )
        semantic_mutations.append(missing_observation)
        non_integer_observation = json.loads(json.dumps(payload))
        non_integer_observation["capacity_gate"][
            "observed_governance_free_bytes_at_freeze"
        ] = True
        semantic_mutations.append(non_integer_observation)
        insufficient_observation = json.loads(json.dumps(payload))
        insufficient_observation["capacity_gate"][
            "observed_output_free_bytes_at_freeze"
        ] = 1
        semantic_mutations.append(insufficient_observation)

        for attacked in semantic_mutations:
            attacked["execution_lock_hash"] = common.canonical_json_hash(
                attacked, "execution_lock_hash"
            )
            write_canonical_json(execution_lock, attacked)
            with self.subTest(mutation=sorted(attacked)):
                with self.assertRaises(common.BackendReplayViolation):
                    common.validate_execution_lock(
                        self.root,
                        execution_lock,
                        queue_path=queue,
                        allocation_path=allocation,
                    )

        write_canonical_json(execution_lock, payload)
        canonical = execution_lock.read_text(encoding="utf-8")
        duplicate = canonical[:-2] + ',\n  "status": "' + common.EXECUTION_LOCK_STATUS + '"\n}\n'
        execution_lock.write_text(duplicate, encoding="utf-8")
        with self.assertRaisesRegex(common.BackendReplayViolation, "duplicate"):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

        execution_lock.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(common.BackendReplayViolation, "not canonical"):
            common.validate_execution_lock(
                self.root,
                execution_lock,
                queue_path=queue,
                allocation_path=allocation,
            )

    def test_readonly_fd_path_does_not_expose_deletable_source_path(self) -> None:
        with common.ReadOnlyFeatureBag(self.bag, common.sha256(self.bag)) as lease:
            self.assertIsNotNone(lease.fd)
            code = (
                "import os,sys; data=open(sys.argv[1],'rb').read(); "
                "\ntry: os.unlink(sys.argv[1]); ok=False"
                "\nexcept OSError: ok=True"
                "\ntry: f=open(sys.argv[1],'wb'); f.write(b'BAD'); f.close(); wok=False"
                "\nexcept OSError: wok=True"
                "\nprint(len(data), int(ok), int(wok))"
            )
            completed = subprocess.run(
                ["python3", "-c", code, lease.proc_path],
                pass_fds=(lease.fd,),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertTrue(completed.stdout.strip().endswith("1 1"))
            subprocess.run(
                ["bash", "-c", 'test -r "$1"', "p07-sealed-fd", lease.proc_path],
                pass_fds=(lease.fd,),
                check=True,
            )
            lease.verify_unchanged()
        self.assertTrue(self.bag.is_file())
        self.assertEqual(self.bag.read_bytes(), b"fixture frozen feature bag\n")

    def test_readonly_lease_detects_in_place_mutation(self) -> None:
        with common.ReadOnlyFeatureBag(self.bag, common.sha256(self.bag)) as lease:
            self.bag.write_bytes(b"changed during replay\n")
            with self.assertRaisesRegex(common.BackendReplayViolation, "changed"):
                lease.verify_unchanged()

    def test_global_flock_rejects_concurrent_owner(self) -> None:
        lock_path = self.root / "backend.lock"
        with common.global_execution_lock(lock_path) as lock_fd:
            common.validate_inherited_lock(lock_fd, lock_path)
            with self.assertRaises(common.LockBusy):
                with common.global_execution_lock(lock_path):
                    self.fail("second backend owner unexpectedly acquired flock")

        target = self.root / "lock-target"
        target.write_text("must remain unchanged\n", encoding="utf-8")
        symlink = self.root / "symlink.lock"
        symlink.symlink_to(target)
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "cannot safely open"
        ):
            with common.global_execution_lock(symlink):
                self.fail("symlinked global lock unexpectedly opened")
        self.assertEqual(target.read_text(encoding="utf-8"), "must remain unchanged\n")

    def test_adapter_separates_preparation_from_replay_only_runner(self) -> None:
        prepare_argv = adapter.build_prepare_argv(self.row, root=self.root)
        self.assertEqual(Path(prepare_argv[1]).name, "run_ntnu_vins_eval.sh")
        self.assertNotIn("guarded", " ".join(prepare_argv))
        replay_argv = adapter.build_backend_argv(
            self.row, root=self.root, play_bag="/proc/self/fd/9"
        )
        self.assertEqual(Path(replay_argv[1]).name, "run_p07_backend_replay_only_v1.sh")
        self.assertNotIn("vins_eval", " ".join(replay_argv))
        attempt = common.output_path(
            self.root, self.row["expected_attempt_dir"], label="attempt"
        )
        with mock.patch.dict(
            os.environ,
            {
                "FORCE_EXPORT": "1",
                "EXPORT_FEATURES": "1",
                "RUN_VINS": "0",
                "AQUAFE_DRY_RUN": "1",
                "VINS_OUTPUT": "/tmp/unsafe-output",
                "LD_PRELOAD": "/tmp/unsafe-library.so",
            },
            clear=False,
        ):
            environment = adapter.safe_environment(
                self.row,
                root=self.root,
                attempt_dir=attempt,
                feature_bag_fd_path="/proc/self/fd/9",
            )
        self.assertEqual(environment["FORCE_EXPORT"], "0")
        self.assertEqual(environment["EXPORT_FEATURES"], "0")
        self.assertEqual(environment["RUN_VINS"], "0")
        self.assertEqual(environment["RUN_EVALUATION"], "0")
        self.assertEqual(environment["BACKEND_REPLAY_ONLY"], "1")
        self.assertEqual(environment["FEATURE_BAG_OVERRIDE"], "/proc/self/fd/9")
        self.assertNotIn("AQUAFE_DRY_RUN", environment)
        self.assertNotIn("VINS_OUTPUT", environment)
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertNotIn("PYTHONPATH", environment)

    def test_aqualoc_cache_missing_fails_before_converter_and_procfd_is_forced(self) -> None:
        row = {
            **self.row,
            "dataset_family": "aqualoc_harbor",
            "sequence": "H07",
            "runner_start": "10",
            "runner_end_or_duration": "20",
            "runner_unit": "frame",
            "expected_run_dir": (
                f"logs/aqualoc_real_vins/external_klt_every2_{self.row['runner_tag']}"
            ),
        }
        cache = (
            self.root / "datasets/aqualoc/rosbags/harbor07_10_20.bag"
        )
        with self.assertRaisesRegex(
            adapter.AdapterViolation, "pre-materialized.*missing"
        ):
            adapter.prematerialized_preparation_bag(row, root=self.root)
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"pre-materialized cache\n")
        self.assertEqual(
            adapter.prematerialized_preparation_bag(row, root=self.root), cache
        )
        attempt = common.output_path(
            self.root, row["expected_attempt_dir"], label="attempt"
        )
        with mock.patch.object(
            adapter,
            "_manifest_row",
            return_value={
                "raw_input_path": "datasets/raw.tar",
                "reference_path": "datasets/reference.txt",
            },
        ):
            with mock.patch.object(
                adapter, "_manifest_input", return_value="/fixture/input"
            ):
                environment = adapter.safe_environment(
                    row,
                    root=self.root,
                    attempt_dir=attempt,
                    feature_bag_fd_path="/proc/self/fd/7",
                    preparation_bag_fd_path="/proc/self/fd/8",
                )
        self.assertEqual(environment["RAW_BAG"], "/proc/self/fd/8")
        runner_text = (
            common.ROOT / "scripts/run_aqualoc_real_vins_eval.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('RAW_BAG="${RAW_BAG:-', runner_text)
        self.assertIn('if [[ ! -f "$RAW_BAG" ]]', runner_text)
        self.assertLess(
            runner_text.index("formal backend requires a pre-materialized"),
            runner_text.index("uw_frontend.datasets.aqualoc_raw_to_rosbag"),
        )
        archaeology_text = (
            common.ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"
        ).read_text(encoding="utf-8")
        self.assertLess(
            archaeology_text.index("formal backend requires a pre-materialized"),
            archaeology_text.index("uw_frontend.datasets.aqualoc_raw_to_rosbag"),
        )
        afrl_text = (
            common.ROOT / "scripts/run_afrl_cave_vins_eval.sh"
        ).read_text(encoding="utf-8")
        self.assertLess(
            afrl_text.index("formal backend requires an existing sealed AFRL"),
            afrl_text.index("uw_frontend.datasets.afrl_cave_to_rosbag"),
        )

    def test_ros_port_conflict_fails_before_launch(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            port = int(listener.getsockname()[1])
            with self.assertRaisesRegex(adapter.AdapterViolation, "unavailable"):
                adapter.assert_ros_port_available(port)
        finally:
            listener.close()
        adapter.assert_ros_port_available(port)

    def test_capacity_waiting_creates_no_attempt_directory(self) -> None:
        attempt = common.output_path(
            self.root, self.row["expected_attempt_dir"], label="attempt"
        )
        report = {
            "run_dir_collision": False,
            "attempt_dir_collision": False,
            "capacity": {"output_pass": False, "governance_pass": True},
        }
        with mock.patch.object(
            job,
            "preflight",
            return_value=(report, self.row, {"backend_replay": "b01"}, {}),
        ):
            with self.assertRaises(common.CapacityWaiting):
                job.execute(
                    1,
                    root=self.root,
                    queue_path=self.root / "queue.csv",
                    allocation_path=self.root / "allocation.csv",
                    execution_lock_path=self.root / "lock.json",
                    registry_path=self.root / "registry.csv",
                    lock_fd=self.lock_fd,
                    timeout_s=1,
                )
        self.assertFalse(attempt.exists())

    def test_algorithmic_hard_failure_is_registered_failed_but_consumes_slot(self) -> None:
        queue = self.root / "queue.csv"
        allocation = self.root / "allocation.csv"
        execution_lock = self.root / "lock.json"
        for path in (queue, allocation, execution_lock):
            path.write_text("fixture\n", encoding="utf-8")
        registry = self.root / "registry.csv"
        fields = [
            "run_id",
            "registry_event_id",
            "recorded_at",
            "supersedes_event_id",
            "stage",
            "dataset_family",
            "sequence",
            "arm",
            "backend_replay",
            "status",
            "replay_evaluable",
            "replay_hard_failure",
            "algorithm_hard_failure",
            "run_dir",
            "command_file",
            "input_hash_manifest",
            "output_hash_manifest",
            "infrastructure_failure",
            "notes",
        ]
        initial = {field: "" for field in fields}
        initial.update(
            {
                "run_id": self.row["run_id"],
                "registry_event_id": f"{self.row['run_id']}_e00",
                "stage": "P07_BACKEND_REPLAY",
                "dataset_family": self.row["dataset_family"],
                "sequence": self.row["sequence"],
                "arm": self.row["arm"],
                "backend_replay": "b01",
                "status": "PLANNED",
                "replay_evaluable": "false",
            }
        )
        with registry.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(initial)
        report = {
            "run_dir_collision": False,
            "attempt_dir_collision": False,
            "capacity": {"output_pass": True, "governance_pass": True},
            "data_identity": {"data_identity_snapshot_hash": "f" * 64},
            "b0_play_input": None,
        }
        hard_audit = {
            "schema_version": auditor.SCHEMA_VERSION,
            "status": "PASS",
            "queue_index": 1,
            "run_id": self.row["run_id"],
            "window_id": self.row["window_id"],
            "arm": self.row["arm"],
            "terminal": True,
            "failure_code": "TIMEOUT",
            "replay_hard_failure": True,
            "numeric_evaluation_candidate": False,
            "g0_evaluation_pending": False,
            "checks": {
                "job_only_governed_adapter": True,
                "job_authority_manifest_valid": True,
                "data_identity_manifest_link_target_revalidated": True,
                "durable_attempt_intent_and_state_chain_valid": True,
                "expected_run_no_clobber": True,
                "trajectory_values_read": False,
                "ape_rpe_values_read": False,
            },
            "outcome_boundary": (
                "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
            ),
        }
        with mock.patch.object(
            job,
            "preflight",
            return_value=(
                report,
                self.row,
                {"backend_replay": "b01"},
                {
                    "execution_lock_hash": "f" * 64,
                    common.g0_governance.EXECUTION_LOCK_BINDING_KEY: {
                        "g0_execution_authority_hash": "e" * 64,
                        "evaluation_lock": {"evaluation_lock_hash": "d" * 64},
                    },
                },
            ),
        ):
            with mock.patch.object(
                common,
                "validate_sealed_runtime_context",
                return_value=mock.Mock(),
            ):
                with mock.patch.object(
                    adapter,
                    "execute_replay",
                    return_value={
                        "status": "TERMINAL_PROCESS_FAILURE",
                        "returncode": 124,
                        "timed_out": True,
                        "replay_started": True,
                    },
                ):
                    with mock.patch.object(
                        auditor, "build_audit", return_value=hard_audit
                    ):
                        result = job.execute(
                            1,
                            root=self.root,
                            queue_path=queue,
                            allocation_path=allocation,
                            execution_lock_path=execution_lock,
                            registry_path=registry,
                            lock_fd=self.lock_fd,
                            timeout_s=1,
                        )
        self.assertEqual(result["status"], "FAILED")
        chain = job.registry_chain(registry, self.row["run_id"])
        self.assertEqual(chain[-1]["status"], "FAILED")
        self.assertEqual(chain[-1]["replay_hard_failure"], "true")
        self.assertEqual(chain[-1]["infrastructure_failure"], "false")
        self.assertTrue(chain[-1]["output_hash_manifest"])

        successor_queue = self.root / "successor_queue.csv"
        with successor_queue.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerows(
                [
                    self.row,
                    {
                        **self.row,
                        "queue_index": "2",
                        "run_id": "successor",
                    },
                ]
            )
        job._require_predecessors_complete(
            [1, 2],
            2,
            queue_path=successor_queue,
            registry_path=registry,
            root=self.root,
        )

        chain[-1]["infrastructure_failure"] = "true"
        with registry.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(chain)
        with self.assertRaisesRegex(job.JobViolation, "blocked by predecessor"):
            job._require_predecessors_complete(
                [1, 2],
                2,
                queue_path=successor_queue,
                registry_path=registry,
                root=self.root,
            )

    def test_pre_replay_infrastructure_failure_is_replacement_eligible_and_bound(self) -> None:
        queue = self.root / "queue.csv"
        allocation = self.root / "allocation.csv"
        execution_lock = self.root / "lock.json"
        for path in (queue, allocation, execution_lock):
            path.write_text("fixture\n", encoding="utf-8")
        registry = self.root / "registry.csv"
        fields = [
            "run_id",
            "registry_event_id",
            "recorded_at",
            "supersedes_event_id",
            "stage",
            "dataset_family",
            "sequence",
            "arm",
            "backend_replay",
            "status",
            "replay_evaluable",
            "replay_hard_failure",
            "algorithm_hard_failure",
            "run_dir",
            "command_file",
            "input_hash_manifest",
            "output_hash_manifest",
            "infrastructure_failure",
            "notes",
        ]
        initial = {field: "" for field in fields}
        initial.update(
            {
                "run_id": self.row["run_id"],
                "registry_event_id": f"{self.row['run_id']}_e00",
                "stage": "P07_BACKEND_REPLAY",
                "dataset_family": self.row["dataset_family"],
                "sequence": self.row["sequence"],
                "arm": self.row["arm"],
                "backend_replay": "b01",
                "status": "PLANNED",
                "replay_evaluable": "false",
            }
        )
        with registry.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(initial)
        report = {
            "run_dir_collision": False,
            "attempt_dir_collision": False,
            "capacity": {"output_pass": True, "governance_pass": True},
            "data_identity": {"data_identity_snapshot_hash": "f" * 64},
            "b0_play_input": None,
        }

        def fail_before_replay(*_args: object, **kwargs: object) -> dict[str, object]:
            result = {
                "schema_version": adapter.SCHEMA_VERSION,
                "status": "FAIL_GOVERNANCE",
                "returncode": None,
                "timed_out": False,
                "replay_started": False,
                "error_type": "FileNotFoundError",
                "error": "missing frozen raw input",
            }
            attempt_dir = Path(str(kwargs["attempt_dir"]))
            (attempt_dir / "adapter_result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            return result

        with mock.patch.object(
            job,
            "preflight",
            return_value=(
                report,
                self.row,
                {"backend_replay": "b01"},
                {
                    "execution_lock_hash": "f" * 64,
                    common.g0_governance.EXECUTION_LOCK_BINDING_KEY: {
                        "g0_execution_authority_hash": "e" * 64,
                        "evaluation_lock": {"evaluation_lock_hash": "d" * 64},
                    },
                },
            ),
        ):
            with mock.patch.object(
                common,
                "validate_sealed_runtime_context",
                return_value=mock.Mock(),
            ):
                with mock.patch.object(
                    adapter, "execute_replay", side_effect=fail_before_replay
                ):
                    with self.assertRaisesRegex(job.JobViolation, "adapter failed"):
                        job.execute(
                            1,
                            root=self.root,
                            queue_path=queue,
                            allocation_path=allocation,
                            execution_lock_path=execution_lock,
                            registry_path=registry,
                            lock_fd=self.lock_fd,
                            timeout_s=1,
                        )
        attempt = common.output_path(
            self.root, self.row["expected_attempt_dir"], label="attempt"
        )
        evidence = json.loads(
            (attempt / "infrastructure_failure_evidence_v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["status"], "REPLACEMENT_ELIGIBLE")
        self.assertEqual(evidence["failure_phase"], "ADAPTER_RETURNED")
        self.assertFalse(evidence["slot_consumption_boundary_crossed"])
        self.assertFalse(evidence["trajectory_outcome_read"])
        self.assertFalse(evidence["evaluation_invoked"])
        self.assertEqual(evidence["infrastructure_category"], "FILE_NOT_FOUND")
        self.assertIsNotNone(evidence["adapter_result"])
        self.assertIsNotNone(evidence["input_hash_manifest"])
        self.assertIsNotNone(evidence["failure_output_precommit"])
        terminal = job.registry_chain(registry, self.row["run_id"])[-1]
        self.assertEqual(terminal["status"], "FAILED")
        self.assertEqual(terminal["infrastructure_failure"], "true")
        final_manifest = common.workspace_path(
            self.root, terminal["output_hash_manifest"], label="infra manifest"
        )
        text = final_manifest.read_text(encoding="utf-8")
        self.assertIn("infrastructure_failure_evidence_v2.json", text)
        self.assertIn("failure_output_precommit.sha256", text)

    def test_durable_intent_orphan_reconcile_closes_pre_adapter_without_rerun(self) -> None:
        queue, allocation, registry, execution_lock, payload = (
            self._write_execution_lock_fixture()
        )
        fields = [
            "run_id",
            "registry_event_id",
            "recorded_at",
            "supersedes_event_id",
            "stage",
            "dataset_family",
            "sequence",
            "arm",
            "backend_replay",
            "status",
            "replay_evaluable",
            "replay_hard_failure",
            "algorithm_hard_failure",
            "run_dir",
            "command_file",
            "input_hash_manifest",
            "output_hash_manifest",
            "infrastructure_failure",
            "notes",
        ]
        initial = {field: "" for field in fields}
        initial.update(
            {
                "run_id": self.row["run_id"],
                "registry_event_id": f"{self.row['run_id']}_e00",
                "stage": "P07_BACKEND_REPLAY",
                "dataset_family": self.row["dataset_family"],
                "sequence": self.row["sequence"],
                "arm": self.row["arm"],
                "backend_replay": self.row["algorithmic_slot"],
                "status": "PLANNED",
                "replay_evaluable": "false",
            }
        )
        with registry.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(initial)
        payload["mutable_registry_prefix"] = {
            "path": registry.relative_to(self.root).as_posix(),
            "sha256": common.sha256(registry),
            "size_bytes": registry.stat().st_size,
        }
        queue_lock_path = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07/"
            "backend_queue_lock_v1.json"
        )
        queue_lock_payload = json.loads(queue_lock_path.read_text(encoding="utf-8"))
        queue_lock_payload["mutable_registry_prefix"] = dict(
            payload["mutable_registry_prefix"]
        )
        queue_lock_payload["backend_queue_lock_hash"] = common.canonical_json_hash(
            queue_lock_payload, "backend_queue_lock_hash"
        )
        write_canonical_json(queue_lock_path, queue_lock_payload)
        queue_lock_record = next(
            item
            for item in payload["artifacts"]
            if item["path"].endswith("backend_queue_lock_v1.json")
        )
        queue_lock_record["sha256"] = common.sha256(queue_lock_path)
        queue_lock_record["size_bytes"] = queue_lock_path.stat().st_size
        payload["backend_queue_lock_hash"] = queue_lock_payload[
            "backend_queue_lock_hash"
        ]
        payload["execution_lock_hash"] = common.canonical_json_hash(
            payload, "execution_lock_hash"
        )
        write_canonical_json(execution_lock, payload)
        data_report = common.revalidate_data_identity_snapshot(
            self.root, payload["data_identity_snapshot"], phase="JOB_PREFLIGHT"
        )
        intent = job.build_attempt_intent(
            self.row,
            root=self.root,
            execution_lock_path=execution_lock,
            execution_lock=payload,
            registry_path=registry,
            replacement=None,
            data_identity_report=data_report,
            b0_play_input_report=None,
        )
        intent["creator_process"] = {
            "pid": 99999999,
            "starttime_ticks": 1,
            "cmdline_sha256": "0" * 64,
        }
        intent["attempt_intent_hash"] = job.attempt_intent_hash(intent)
        intent_path = job.attempt_intent_path(self.root, self.row)
        common.write_json_exclusive(intent_path, intent)

        with mock.patch.object(
            common,
            "validate_sealed_runtime_context",
            return_value=mock.Mock(),
        ):
            result = job.reconcile_orphan(
                1,
                root=self.root,
                queue_path=queue,
                allocation_path=allocation,
                execution_lock_path=execution_lock,
                registry_path=registry,
            )
        self.assertEqual(result["status"], "FAILED_CLOSED_RECONCILED")
        self.assertTrue(result["replacement_eligible"])
        self.assertFalse(result["algorithmic_slot_consumed"])
        terminal = job.registry_chain(registry, self.row["run_id"])[-1]
        self.assertEqual(terminal["status"], "FAILED")
        self.assertEqual(terminal["infrastructure_failure"], "true")
        attempt = common.output_path(
            self.root, self.row["expected_attempt_dir"], label="attempt"
        )
        evidence = json.loads(
            (attempt / "infrastructure_failure_evidence_v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsNone(evidence["adapter_result"])
        self.assertTrue(evidence["pre_adapter_without_result_proven"])
        self.assertEqual(
            evidence["infrastructure_category"], "SUPERVISOR_PROCESS_LOSS"
        )
        self.assertFalse(evidence["trajectory_outcome_read"])

        with mock.patch.object(
            common,
            "validate_sealed_runtime_context",
            return_value=mock.Mock(),
        ):
            resumed = job.reconcile_orphan(
                1,
                root=self.root,
                queue_path=queue,
                allocation_path=allocation,
                execution_lock_path=execution_lock,
                registry_path=registry,
            )
        self.assertEqual(resumed, result)
        self.assertEqual(len(job.registry_chain(registry, self.row["run_id"])), 2)

        command_path = attempt / "command.json"
        command_path.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(
            common,
            "validate_sealed_runtime_context",
            return_value=mock.Mock(),
        ):
            with self.assertRaisesRegex(job.JobViolation, "JSON bytes differ"):
                job.reconcile_orphan(
                    1,
                    root=self.root,
                    queue_path=queue,
                    allocation_path=allocation,
                    execution_lock_path=execution_lock,
                    registry_path=registry,
                )

    def test_auditor_rejects_input_immutability_failure(self) -> None:
        attempt = common.output_path(
            self.root, self.row["expected_attempt_dir"], label="attempt"
        )
        attempt.mkdir(parents=True)
        (attempt / "command.log").write_bytes(b"fixture\n")
        (attempt / "input_check.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "queue_index": 1,
                    "run_id": self.row["run_id"],
                    "arm": self.row["arm"],
                }
            ),
            encoding="utf-8",
        )
        (attempt / "job_authority_v1.json").write_text(
            json.dumps(
                {
                    "schema_version": adapter.JOB_AUTHORITY_SCHEMA_VERSION,
                    "queue_index": 1,
                    "run_id": self.row["run_id"],
                    "row_sha256": adapter._row_sha256(self.row),
                    "outcome_boundary": (
                        "JOB_AUTHORITY_ONLY_NO_TRAJECTORY_OR_EVALUATION_OUTCOME"
                    ),
                }
            ),
            encoding="utf-8",
        )
        prepare_argv = adapter.build_prepare_argv(self.row, root=self.root)
        config_argv = adapter.build_config_argv(self.row, root=self.root)
        argv = adapter.build_backend_argv(
            self.row, root=self.root, play_bag="/proc/self/fd/9"
        )
        (attempt / "adapter_command.json").write_text(
            json.dumps(
                {
                    "schema_version": adapter.COMMAND_SCHEMA_VERSION,
                    "queue_index": 1,
                    "run_id": self.row["run_id"],
                    "arm": self.row["arm"],
                    "preparation_argv": prepare_argv,
                    "preparation_argv_sha256": adapter._argv_sha256(prepare_argv),
                    "config_argv": config_argv,
                    "config_argv_sha256": adapter._argv_sha256(config_argv),
                    "replay_argv": argv,
                    "replay_argv_sha256": adapter._argv_sha256(argv),
                    "argv": argv,
                    "argv_sha256": adapter._argv_sha256(argv),
                    "vins_workspace": str(common.VINS_ORIGIN),
                    "run_vins": True,
                    "preparation_run_vins": False,
                    "replay_only_runner": True,
                    "evaluation_invoked": False,
                    "force_export": False,
                    "export_features": False,
                    "feature_bag_path_disclosed_to_runner": False,
                    "feature_bag_transport": "sealed_memfd_byte_exact_copy",
                }
            ),
            encoding="utf-8",
        )
        (attempt / "adapter_result.json").write_text(
            json.dumps(
                {
                    "schema_version": adapter.SCHEMA_VERSION,
                    "status": "FAIL_INPUT_IMMUTABILITY",
                    "queue_index": 1,
                    "run_id": self.row["run_id"],
                    "arm": self.row["arm"],
                    "input_feature_bag_unchanged": False,
                    "export_wrapper_invoked": False,
                    "trajectory_metrics_read_by_adapter": False,
                    "evaluation_invoked": False,
                    "ape_rpe_artifacts_created": False,
                    "direct_eval_runner_used_for_replay": False,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(auditor.AuditViolation, "governance envelope"):
            auditor.build_audit(
                self.row,
                root=self.root,
                attempt_dir=attempt,
                command_log=attempt / "command.log",
            )

    def test_b0_auditor_requires_exact_origin_identity_pass(self) -> None:
        attempt = self.root / "papers/p07/b0-attempt"
        decision_dir = attempt / "b0_contract_decisions"
        decision_dir.mkdir(parents=True)
        decision = decision_dir / "identity.json"
        payload = {
            "schema_version": "aqua-fe-b0-vins-origin-identity-decision-v1",
            "contract_pass": True,
            "action": "ALLOW_B0_NATIVE",
            "result_label": "B0_NATIVE_VINS_ORIGIN_V1",
            "counts_as_b0": True,
            "contract_hash": checker.NATIVEQ_CONTRACT_HASH,
            "vins_workspace": str(common.VINS_ORIGIN),
            "backend_root": str(common.VINS_ORIGIN / "src/VINS-Fusion-master"),
            "binary": str(common.VINS_ORIGIN / "devel/lib/vins/vins_node"),
            "reasons": [],
            "outcome_boundary": (
                "EXECUTION_IDENTITY_ONLY_NO_FRONTEND_OR_TRAJECTORY_OUTCOME"
            ),
        }
        decision.write_text(json.dumps(payload), encoding="utf-8")
        record = auditor._b0_identity_record(attempt, root=self.root)
        self.assertEqual(record["sha256"], common.sha256(decision))

        payload["contract_pass"] = False
        payload["action"] = "REJECT_B0_NATIVE"
        payload["reasons"] = ["fixture rejection"]
        decision.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(auditor.AuditViolation, "not an exact PASS"):
            auditor._b0_identity_record(attempt, root=self.root)

    def test_feature_auditor_requires_exact_consumer_guard_pass(self) -> None:
        decision = {
            "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
            "contract_pass": True,
            "action": "ALLOW_LEARNED",
            "counts_as_proposed_result": True,
            "contract_hash": checker.NATIVEQ_CONTRACT_HASH,
            "backend_root": str(common.VINS_ORIGIN / "src/VINS-Fusion-master"),
            "binary": str(common.VINS_ORIGIN / "devel/lib/vins/vins_node"),
            "feature_bag": "/proc/self/fd/17",
            "bag_attestation": str(self.attestation),
            "reasons": [],
        }
        auditor._validate_consumer_decision(self.row, decision, root=self.root)
        decision["action"] = "FALLBACK_CLASSICAL"
        with self.assertRaisesRegex(auditor.AuditViolation, "not an exact PASS"):
            auditor._validate_consumer_decision(self.row, decision, root=self.root)

    def test_direct_adapter_cli_is_forbidden(self) -> None:
        completed = subprocess.run(
            ["python3", "scripts/run_p07_backend_replay_adapter_v1.py"],
            cwd=common.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 64)
        self.assertIn("DIRECT_CLI_FORBIDDEN", completed.stderr)

    def test_formal_job_cli_rejects_registry_or_timeout_override(self) -> None:
        arguments = {
            "root": common.ROOT,
            "queue_path": common.DEFAULT_QUEUE,
            "allocation_path": common.DEFAULT_ALLOCATION,
            "execution_lock_path": common.DEFAULT_EXECUTION_LOCK,
            "registry_path": common.DEFAULT_REGISTRY,
            "timeout_s": job.FROZEN_TIMEOUT_S,
        }
        job.validate_formal_cli_contract(**arguments)
        changed = dict(arguments)
        changed["registry_path"] = self.root / "fake_registry.csv"
        with self.assertRaisesRegex(job.JobViolation, "path override forbidden"):
            job.validate_formal_cli_contract(**changed)
        changed = dict(arguments)
        changed["timeout_s"] = job.FROZEN_TIMEOUT_S + 1
        with self.assertRaisesRegex(job.JobViolation, "timeout override forbidden"):
            job.validate_formal_cli_contract(**changed)


if __name__ == "__main__":
    unittest.main()
