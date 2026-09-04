from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import allocate_p07_backend_replacement_v1 as allocator
from scripts import build_p07_backend_replacement_contract_v1 as contract
from scripts import build_p07_backend_replay_queue_v1 as queue_builder
from scripts import register_p07_backend_allocations_v1 as registration
from scripts import validate_p07_backend_replay_queue_v1 as queue_validator
from scripts.tests.test_p07_backend_replay_queue_v1 import HASHES, fixture_snapshot


def record(path: str, token: str = "a" * 64) -> dict[str, object]:
    return {"path": path, "sha256": token, "size_bytes": 123}


class P07BackendReplacementV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        outputs = queue_builder.build_outputs(
            fixture_snapshot(applicable_windows=0),
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
            include_code_records=False,
        )
        _fields, queue = queue_validator.parse_csv(
            outputs[queue_builder.BACKEND_QUEUE]
        )
        _fields, allocations = queue_validator.parse_csv(
            outputs[queue_builder.BACKEND_ALLOCATION]
        )
        self.base = queue[0]
        self.allocation = allocations[0]
        self.registry_fields, _rows = registration.read_csv_with_fields(
            registration.RUN_REGISTRY
        )
        self.base_registry = registration.build_registry_rows(
            [self.base],
            [self.allocation],
            registry_fields=self.registry_fields,
            split_roles={self.base["window_id"]: "FIXTURE_OUTCOME_BLIND"},
        )[0]

    def _terminal_chain(self) -> list[dict[str, str]]:
        e00 = dict(self.base_registry)
        e01 = dict(e00)
        e01.update(
            {
                "registry_event_id": f"{e00['run_id']}_e01",
                "supersedes_event_id": e00["registry_event_id"],
                "status": "RUNNING",
            }
        )
        e02 = dict(e01)
        e02.update(
            {
                "registry_event_id": f"{e00['run_id']}_e02",
                "supersedes_event_id": e01["registry_event_id"],
                "status": "FAILED",
                "infrastructure_failure": "true",
                "replay_evaluable": "false",
                "replay_hard_failure": "false",
                "algorithm_hard_failure": "false",
            }
        )
        return [e00, e01, e02]

    def _contract_payload(self) -> dict[str, object]:
        artifacts = [
            record(queue_builder.display_path(path), hashlib.sha256(str(path).encode()).hexdigest())
            for path in contract.required_artifact_paths()
        ]
        return contract.build_contract_payload(
            frozen_at="2026-08-08T00:01:00+08:00",
            artifacts=artifacts,
            formalization_adoption={
                "path": contract.adoption.OUTPUT_RELATIVE,
                "sha256": "1" * 64,
                "size_bytes": 1,
                contract.adoption.SELF_HASH_FIELD: "2" * 64,
            },
            formalization_review_evidence={
                "path": contract.review_evidence.OUTPUT_RELATIVE,
                "sha256": "3" * 64,
                "size_bytes": 1,
                contract.review_evidence.SELF_HASH_FIELD: "4" * 64,
            },
        )

    def _lock_payload(self) -> dict[str, object]:
        effective = allocator.build_effective_row(self.base, attempt_number=2)
        relative = allocator.lock_relative_path(int(self.base["queue_index"]), 2)
        registry = allocator.build_registry_row(
            self.base_registry,
            effective,
            allocated_at="2026-08-08T00:02:00+08:00",
            replacement_for=self.base["run_id"],
            replacement_lock_relative=relative,
            execution_lock_hash="b" * 64,
            replacement_contract_hash="c" * 64,
            registry_fields=self.registry_fields,
        )
        return allocator.build_replacement_lock_payload(
            allocated_at="2026-08-08T00:02:00+08:00",
            allocation_index=1,
            attempt_number=2,
            base_row=self.base,
            effective_row=effective,
            replacement_for=self.base["run_id"],
            replacement_lock_relative=relative,
            failure_evidence_record=record(
                f"{self.base['expected_attempt_dir']}/"
                "infrastructure_failure_evidence_v2.json",
                "d" * 64,
            ),
            failure_evidence_payload={
                "schema_version": allocator.INFRASTRUCTURE_EVIDENCE_SCHEMA,
                "status": "REPLACEMENT_ELIGIBLE",
                "failure_class": "INFRASTRUCTURE",
                "failure_code": "EXECUTION_ENVELOPE_FAILURE",
                "infrastructure_category": "FILE_NOT_FOUND",
                "failure_phase": "ADAPTER_RETURNED",
                "infrastructure_failure": True,
                "replacement_eligible": True,
                "algorithmic_slot_consumed": False,
                "slot_consumption_boundary_crossed": False,
                "trajectory_outcome_read": False,
                "evaluation_invoked": False,
                "audit_artifact_created": False,
            },
            infrastructure_evidence_bundle={
                "adapter_result": record("attempt/adapter_result.json", "1" * 64),
                "input_hash_manifest": record(
                    "attempt/input_hash_manifest.sha256", "2" * 64
                ),
                "failure_output_precommit": record(
                    "attempt/failure_output_precommit.sha256", "3" * 64
                ),
                "attempt_intent": record(
                    "attempt/attempt_intent_v1.json", "7" * 64
                ),
                "attempt_state_journal": record(
                    "attempt/attempt_state_v1.jsonl", "8" * 64
                ),
                "infrastructure_output_hash_manifest": record(
                    "attempt/infrastructure_output_hash_manifest.sha256", "4" * 64
                ),
            },
            source_registry_event=self._terminal_chain()[-1],
            registry_planned_event=registry,
            queue_record=record(
                "papers/ieee_sensors_journal_experiments/p07/"
                "backend_replay_queue_v1.csv",
                "5" * 64,
            ),
            allocation_record=record(
                "papers/ieee_sensors_journal_experiments/p07/"
                "backend_run_allocation_v1.csv",
                "6" * 64,
            ),
            base_allocation=self.allocation,
            allocation_index_prefix={
                "path": queue_builder.display_path(contract.INDEX_PATH),
                "sha256": hashlib.sha256(b"").hexdigest(),
                "size_bytes": 0,
            },
            execution_lock_record=record(
                "papers/ieee_sensors_journal_experiments/p07/"
                "backend_replay_execution_lock_v1.json",
                "e" * 64,
            ),
            execution_lock_hash="b" * 64,
            contract_record=record(
                "papers/ieee_sensors_journal_experiments/p07/"
                "backend_replacement_contract_v1.json",
                "f" * 64,
            ),
            replacement_contract_hash="c" * 64,
        )

    def test_contract_freezes_fail_closed_replacement_rules(self) -> None:
        payload = self._contract_payload()
        contract.validate_contract_payload(
            payload, root=queue_builder.ROOT, verify_artifacts=False
        )
        self.assertFalse(payload["trajectory_outcome_read_at_freeze"])
        self.assertEqual(
            payload["effective_row_policy"]["allowed_overrides"],
            ["run_id", "runner_tag", "expected_run_dir", "expected_attempt_dir"],
        )
        self.assertTrue(
            payload["replacement_lock_policy"]["single_use_via_untouched_planned_e00"]
        )
        self.assertIn(
            "SUPERVISOR_PROCESS_LOSS", payload["eligibility"]["allowed_failure_codes"]
        )
        self.assertFalse(
            payload["eligibility"]["phase_evidence_policy"]["PRE_ADAPTER"][
                "adapter_result_required"
            ]
        )
        self.assertTrue(
            payload["eligibility"]["phase_evidence_policy"]["ADAPTER_RUNNING"][
                "state_journal_required"
            ]
        )
        tampered = dict(payload)
        tampered["eligibility"] = {
            **payload["eligibility"],
            "algorithmic_slot_consumed": True,
        }
        tampered[contract.SELF_HASH_FIELD] = contract.contract_hash(tampered)
        with self.assertRaises(contract.ReplacementContractError):
            contract.validate_contract_payload(
                tampered, root=queue_builder.ROOT, verify_artifacts=False
            )
        for mutation in ("missing", "path", "hash"):
            changed = copy.deepcopy(payload)
            if mutation == "missing":
                changed.pop("formalization_adoption")
            elif mutation == "path":
                changed["formalization_adoption"]["path"] = "papers/evil.json"
            else:
                changed["formalization_adoption"][
                    contract.adoption.SELF_HASH_FIELD
                ] = "not-a-hash"
            changed[contract.SELF_HASH_FIELD] = contract.contract_hash(changed)
            with self.subTest(adoption_mutation=mutation):
                with self.assertRaises(contract.ReplacementContractError):
                    contract.validate_contract_payload(
                        changed,
                        root=queue_builder.ROOT,
                        verify_artifacts=False,
                    )

    def test_contract_publication_is_transactional_for_pre_and_postlink_drift(
        self,
    ) -> None:
        for mutation_call in (2, 3):
            with self.subTest(mutation_call=mutation_call), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source = root / "scripts/replacement_source.py"
                adoption_file = root / "papers/p07/adoption.json"
                evidence_file = root / "papers/p07/evidence.json"
                output = root / "papers/p07/replacement.json"
                for path, content in (
                    (source, b"source\n"),
                    (adoption_file, b"adoption\n"),
                    (evidence_file, b"evidence\n"),
                ):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                source_record = contract.g0_publisher.direct_file_record_rooted(
                    root, source, label="replacement source"
                )
                adoption_record = contract.g0_publisher.direct_file_record_rooted(
                    root, adoption_file, label="replacement adoption"
                )
                evidence_record = contract.g0_publisher.direct_file_record_rooted(
                    root, evidence_file, label="replacement evidence"
                )
                payload: dict[str, object] = {
                    "frozen_at": "2026-08-08T00:00:00+08:00",
                    "artifacts": [source_record],
                    "formalization_adoption": adoption_record,
                    "formalization_review_evidence": evidence_record,
                }
                calls = 0

                def rebuild(**_kwargs: object) -> dict[str, object]:
                    nonlocal calls
                    calls += 1
                    if calls == mutation_call:
                        source.write_bytes(b"drift\n")
                    return payload

                with mock.patch.object(queue_builder, "ROOT", root), mock.patch.object(
                    contract, "build_live_contract", side_effect=rebuild
                ):
                    with self.assertRaises(contract.ReplacementContractError):
                        contract.write_no_clobber(output, payload)
                self.assertFalse(output.exists())
                self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

    def test_contract_publication_preserves_existing_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "scripts/source.py"
            output = root / "papers/p07/replacement.json"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            source.write_bytes(b"source\n")
            output.write_bytes(b"independent winner\n")
            record = contract.g0_publisher.direct_file_record_rooted(
                root, source, label="replacement collision source"
            )
            payload = {
                "frozen_at": "2026-08-08T00:00:00+08:00",
                "artifacts": [record],
                "formalization_adoption": record,
                "formalization_review_evidence": record,
            }
            with mock.patch.object(queue_builder, "ROOT", root), mock.patch.object(
                contract, "build_live_contract", return_value=payload
            ):
                with self.assertRaises(FileExistsError):
                    contract.write_no_clobber(output, payload)
            self.assertEqual(output.read_bytes(), b"independent winner\n")

    def test_effective_row_changes_exactly_four_governance_fields(self) -> None:
        effective = allocator.build_effective_row(self.base, attempt_number=2)
        changed = {
            key for key in self.base if self.base[key] != effective[key]
        }
        self.assertEqual(changed, set(contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES))
        self.assertEqual(
            allocator.immutable_row_hash(self.base),
            allocator.immutable_row_hash(effective),
        )
        self.assertTrue(effective["runner_tag"].endswith("_attempt02"))
        self.assertTrue(effective["expected_run_dir"].endswith("_attempt02"))
        self.assertTrue(effective["expected_attempt_dir"].endswith("_attempt02"))

    def test_replacement_lock_binds_exact_job_and_rejects_scientific_tamper(self) -> None:
        payload = self._lock_payload()
        relative = allocator.lock_relative_path(int(self.base["queue_index"]), 2)
        allocator.validate_replacement_lock_payload(
            payload, expected_relative_path=relative
        )
        self.assertEqual(
            payload["job_argv"],
            allocator.exact_job_argv(int(self.base["queue_index"]), relative),
        )
        tampered = dict(payload)
        effective = dict(payload["effective_queue_row"])
        effective["window_start_s"] = "999"
        tampered["effective_queue_row"] = effective
        tampered["effective_queue_row_sha256"] = allocator.row_hash(effective)
        tampered[allocator.SELF_HASH_FIELD] = allocator.replacement_lock_hash(tampered)
        with self.assertRaisesRegex(
            allocator.ReplacementAllocationError, "scientific"
        ):
            allocator.validate_replacement_lock_payload(
                tampered, expected_relative_path=relative
            )

    def test_slot_requires_complete_latest_infrastructure_failure_chain(self) -> None:
        chain = self._terminal_chain()
        base_e00, terminal = allocator._validate_slot_unconsumed(
            self.base,
            failed_run_id=self.base["run_id"],
            index_rows=[],
            registry_rows=chain,
        )
        self.assertEqual(base_e00["registry_event_id"], self.base_registry["registry_event_id"])
        self.assertEqual(terminal["status"], "FAILED")

        consumed = [dict(row) for row in chain]
        consumed[-1]["infrastructure_failure"] = "false"
        consumed[-1]["replay_hard_failure"] = "true"
        with self.assertRaisesRegex(
            allocator.ReplacementAllocationError, "consumed"
        ):
            allocator._validate_slot_unconsumed(
                self.base,
                failed_run_id=self.base["run_id"],
                index_rows=[],
                registry_rows=consumed,
            )

        branch = dict(self.base_registry)
        branch["run_id"] = "unauthorized-branch"
        branch["registry_event_id"] = "unauthorized-branch_e00"
        with self.assertRaisesRegex(
            allocator.ReplacementAllocationError, "unknown or missing"
        ):
            allocator._validate_slot_unconsumed(
                self.base,
                failed_run_id=self.base["run_id"],
                index_rows=[],
                registry_rows=[*chain, branch],
            )

    def test_append_only_index_is_idempotent_and_collision_closed(self) -> None:
        payload = self._lock_payload()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replacement_index.csv"
            effective = payload["effective_queue_row"]
            row = {field: "" for field in allocator.INDEX_FIELDS}
            row.update(
                {
                    "schema_version": contract.INDEX_SCHEMA,
                    "allocation_index": "1",
                    "event_id": "p07_backend_replacement_a0001",
                    "previous_event_hash": "",
                    "event_hash": "",
                    "allocated_at": "2026-08-08T00:02:00+08:00",
                    "queue_index": self.base["queue_index"],
                    "algorithmic_slot": self.base["algorithmic_slot"],
                    "root_queue_run_id": self.base["run_id"],
                    "failed_run_id": self.base["run_id"],
                    "replacement_for": self.base["run_id"],
                    "run_id": effective["run_id"],
                    "attempt_number": "2",
                    "runner_tag": effective["runner_tag"],
                    "expected_run_dir": effective["expected_run_dir"],
                    "expected_attempt_dir": effective["expected_attempt_dir"],
                    "failure_evidence_path": payload["source_failure_evidence"]["path"],
                    "failure_evidence_sha256": "d" * 64,
                    "execution_lock_hash": "b" * 64,
                    "replacement_contract_hash": "c" * 64,
                    "replacement_lock_path": allocator.lock_relative_path(
                        int(self.base["queue_index"]), 2
                    ),
                    "replacement_lock_sha256": "e" * 64,
                    "status": allocator.INDEX_STATUS,
                    "outcome_boundary": allocator.OUTCOME_BOUNDARY,
                }
            )
            row["event_hash"] = allocator.index_event_hash(row)
            allocator.append_index_exact(path, row)
            allocator.append_index_exact(path, row)
            self.assertEqual(allocator.read_index(path), [row])
            collision = dict(row)
            collision["run_id"] = "different"
            with self.assertRaisesRegex(
                allocator.ReplacementAllocationError, "collision"
            ):
                allocator.append_index_exact(path, collision)

            external = Path(directory) / "external.csv"
            external.write_text("outside\n", encoding="utf-8")
            symlink = Path(directory) / "symlink-index.csv"
            symlink.symlink_to(external)
            with self.assertRaises(OSError):
                allocator.append_index_exact(symlink, row)
            self.assertEqual(external.read_text(encoding="utf-8"), "outside\n")


if __name__ == "__main__":
    unittest.main()
