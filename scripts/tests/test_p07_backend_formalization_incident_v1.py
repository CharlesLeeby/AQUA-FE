#!/usr/bin/env python3
"""Synthetic, outcome-free tests for the P07 formalization incident recorder."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import build_p07_backend_formalization_incident_v1 as incident


OBSERVED_AT = "2099-08-08T04:00:00+00:00"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def embedded_hash(payload: dict[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def render_csv(
    fields: list[str], rows: list[dict[str, str]], include_header: bool = True
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    if include_header:
        writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


class IncidentFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.p07 = root / "papers/ieee_sensors_journal_experiments/p07"
        self.p07.mkdir(parents=True)
        self.registry_path = root / incident.REGISTRY_RELATIVE
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_rows: list[dict[str, str]] = []
        self.allocation_rows: list[dict[str, str]] = []
        self.registry_suffix_rows: list[dict[str, str]] = []
        self._build()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def write_bytes(self, relative: str, content: bytes) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def write_json(self, relative: str, payload: dict[str, object]) -> None:
        self.write_bytes(relative, incident.json_bytes(payload))

    def record(self, relative: str) -> dict[str, object]:
        content = self.path(relative).read_bytes()
        return {
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }

    def hashed_json(
        self,
        relative: str,
        schema: str,
        status: str,
        field: str,
        extra: dict[str, object],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": schema,
            "status": status,
        }
        payload.update(extra)
        payload[field] = embedded_hash(payload, field)
        self.write_json(relative, payload)
        return payload

    def _build(self) -> None:
        registry_fields = [
            "run_id",
            "registry_event_id",
            "recorded_at",
            "stage",
            "backend_replay",
            "status",
            "run_dir",
        ]
        prefix_rows = [
            {
                "run_id": "preexisting_frontend_run",
                "registry_event_id": "preexisting_frontend_run_e00",
                "recorded_at": "2026-08-07T00:00:00+00:00",
                "stage": "P07_FRONTEND",
                "backend_replay": "",
                "status": "COMPLETED",
                "run_dir": "logs/preexisting_frontend_run",
            }
        ]
        prefix_content = render_csv(registry_fields, prefix_rows)
        prefix_record = {
            "path": incident.REGISTRY_RELATIVE,
            "sha256": hashlib.sha256(prefix_content).hexdigest(),
            "size_bytes": len(prefix_content),
        }

        queue_fields = [
            "schema_version",
            "queue_index",
            "run_id",
            "expected_run_dir",
            "expected_attempt_dir",
            "status",
            "outcome_boundary",
        ]
        for index in range(1, incident.EXPECTED_BACKEND_ROWS + 1):
            run_id = "synthetic_backend_{:03d}".format(index)
            self.queue_rows.append(
                {
                    "schema_version": incident.QUEUE_SCHEMA,
                    "queue_index": str(index),
                    "run_id": run_id,
                    "expected_run_dir": "logs/synthetic_backend_{:03d}".format(index),
                    "expected_attempt_dir": (
                        "papers/ieee_sensors_journal_experiments/p07/"
                        "backend_attempts/queue_{:03d}_attempt01".format(index)
                    ),
                    "status": "PLANNED",
                    "outcome_boundary": incident.OUTCOME_BOUNDARY,
                }
            )
        self.write_bytes(incident.QUEUE_RELATIVE, render_csv(queue_fields, self.queue_rows))

        queue_lock = self.hashed_json(
            incident.QUEUE_LOCK_RELATIVE,
            "isj-p07-backend-queue-lock-v1",
            "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK",
            "backend_queue_lock_hash",
            {
                "backend_replay_jobs": incident.EXPECTED_BACKEND_ROWS,
                "backend_replay_queue": self.record(incident.QUEUE_RELATIVE),
                "mutable_registry_prefix": prefix_record,
                "held_out_trajectory_outcome_read": False,
                "outcome_boundary": incident.OUTCOME_BOUNDARY,
            },
        )
        queue_lock_hash = str(queue_lock["backend_queue_lock_hash"])

        allocation_fields = [
            "schema_version",
            "queue_index",
            "run_id",
            "backend_replay",
            "status",
            "backend_queue_lock_hash",
        ]
        for index, queue_row in enumerate(self.queue_rows, start=1):
            self.allocation_rows.append(
                {
                    "schema_version": incident.ALLOCATION_SCHEMA,
                    "queue_index": str(index),
                    "run_id": queue_row["run_id"],
                    "backend_replay": "b{:02d}".format(((index - 1) % 3) + 1),
                    "status": "PLANNED",
                    "backend_queue_lock_hash": queue_lock_hash,
                }
            )
        self.write_bytes(
            incident.ALLOCATION_RELATIVE,
            render_csv(allocation_fields, self.allocation_rows),
        )

        validation = {
            "schema_version": "isj-p07-backend-queue-validation-v1",
            "status": "PASS",
            "backend_replay_jobs": incident.EXPECTED_BACKEND_ROWS,
            "backend_queue_lock_hash": queue_lock_hash,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": incident.OUTCOME_BOUNDARY,
        }
        self.write_json(incident.QUEUE_VALIDATION_RELATIVE, validation)

        for index, (queue_row, allocation_row) in enumerate(
            zip(self.queue_rows, self.allocation_rows), start=1
        ):
            run_id = queue_row["run_id"]
            self.registry_suffix_rows.append(
                {
                    "run_id": run_id,
                    "registry_event_id": "{}_e00".format(run_id),
                    "recorded_at": "2026-08-08T03:54:00+00:00",
                    "stage": "P07_BACKEND_REPLAY",
                    "backend_replay": allocation_row["backend_replay"],
                    "status": "PLANNED",
                    "run_dir": queue_row["expected_run_dir"],
                }
            )

        intended_hash = hashlib.sha256(
            canonical_json(self.registry_suffix_rows).encode("utf-8")
        ).hexdigest()
        intent = self.hashed_json(
            incident.REGISTRATION_INTENT_RELATIVE,
            "isj-p07-backend-registration-intent-v1",
            "FROZEN_BEFORE_CANONICAL_REGISTRY_APPEND",
            "registration_intent_hash",
            {
                "backend_queue_lock_hash": queue_lock_hash,
                "backend_queue": self.record(incident.QUEUE_RELATIVE),
                "backend_allocation": self.record(incident.ALLOCATION_RELATIVE),
                "backend_queue_lock": self.record(incident.QUEUE_LOCK_RELATIVE),
                "backend_queue_validation": self.record(
                    incident.QUEUE_VALIDATION_RELATIVE
                ),
                "registry_prefix": prefix_record,
                "intended_backend_runs": incident.EXPECTED_BACKEND_ROWS,
                "intended_registry_rows_sha256": intended_hash,
                "held_out_trajectory_outcome_read": False,
                "outcome_boundary": incident.OUTCOME_BOUNDARY,
            },
        )

        suffix_content = render_csv(
            registry_fields, self.registry_suffix_rows, include_header=False
        )
        full_registry = prefix_content + suffix_content
        self.registry_path.write_bytes(full_registry)

        report_extra: dict[str, object] = {
            "backend_queue_lock_hash": queue_lock_hash,
            "registration_intent": dict(
                self.record(incident.REGISTRATION_INTENT_RELATIVE),
                registration_intent_hash=intent["registration_intent_hash"],
            ),
            "registry_rows_appended_this_invocation": incident.EXPECTED_BACKEND_ROWS,
            "registry_rows_reconciled_existing": 0,
            "validation": {
                "intended_backend_runs": incident.EXPECTED_BACKEND_ROWS,
                "unique_untouched_planned_e00": incident.EXPECTED_BACKEND_ROWS,
                "pass": True,
            },
            "before_registry_sha256": prefix_record["sha256"],
            "after_registry_sha256": hashlib.sha256(full_registry).hexdigest(),
            "allocation_sha256": self.record(incident.ALLOCATION_RELATIVE)["sha256"],
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": incident.OUTCOME_BOUNDARY,
        }
        self.hashed_json(
            incident.REGISTRATION_RELATIVE,
            "isj-p07-backend-registration-v1",
            "PASS",
            "registration_report_hash",
            report_extra,
        )

        common_boundary = {
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        }
        for relative in incident.PRESENT_PATHS[:2]:
            self.hashed_json(
                relative,
                "isj-p07-backend-legacy-d-resolution-sidecar-v1",
                "PASS_NOT_APPLICABLE_LEGACY_LOCK_BOUND",
                "sidecar_hash",
                dict(common_boundary),
            )
        self.hashed_json(
            incident.PRESENT_PATHS[2],
            "isj-p07-backend-legacy-d-resolution-compatibility-lock-v1",
            "FROZEN_READY_FOR_BACKEND_QUEUE_INPUT",
            "compatibility_lock_hash",
            dict(common_boundary),
        )
        epoch_false = {
            "ape_artifact_read": False,
            "backend_queue_generated": False,
            "evaluation_plan_generated": False,
            "evaluator_executed": False,
            "real_trajectory_artifact_read": False,
            "result_artifact_read": False,
            "rpe_artifact_read": False,
            "vins_executed": False,
            "workspace_discovery_used": False,
        }
        self.hashed_json(
            incident.PRESENT_PATHS[3],
            "isj-p07-evaluator-epoch-ns-correction-lock-v1",
            "FROZEN_OUTCOME_BLIND_ADDITIVE_ROS_BAG_EPOCH_NS_CORRECTION",
            "epoch_ns_correction_lock_hash",
            {
                "outcome_blind_audit": epoch_false,
                "outcome_boundary": (
                    "SOURCE_AND_GOVERNANCE_ONLY_NO_REAL_TRAJECTORY_APE_RPE_RESULT_READ"
                ),
            },
        )


class BackendFormalizationIncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = IncidentFixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self) -> dict[str, object]:
        return incident.build_incident(
            root=self.root, observed_at=OBSERVED_AT, require_output_absent=True
        )

    def assert_no_incident_publication(self) -> None:
        self.assertFalse(self.fixture.path(incident.OUTPUT_RELATIVE).exists())
        self.assertEqual(
            list(self.fixture.p07.glob(".backend_formalization_incident_v1.json.partial.*")),
            [],
        )

    def test_exact_preview_and_live_validation(self) -> None:
        payload = self.build()
        self.assertEqual(payload["schema_version"], incident.SCHEMA)
        self.assertEqual(payload["status"], incident.STATUS)
        self.assertEqual(len(payload["present_artifacts"]), 10)
        self.assertEqual(
            payload["canonical_run_registry"]["exact_planned_e00_suffix"][
                "row_count"
            ],
            240,
        )
        self.assertEqual(
            payload["global_post_incident_output_absence"],
            [
                {"path": relative, "state": "ABSENT"}
                for relative in incident.GLOBAL_POST_INCIDENT_OUTPUT_PATHS
            ],
        )
        self.assertEqual(
            payload["execution_output_root_absence"],
            [
                {"path": relative, "path_state": "ABSENT"}
                for relative in incident.EXECUTION_OUTPUT_ROOT_PATHS
            ],
        )
        self.assertEqual(
            payload["replacement_output_absence"],
            [
                {"path": relative, "path_state": "ABSENT"}
                for relative in incident.REPLACEMENT_OUTPUT_PATHS
            ],
        )
        self.assertEqual(
            incident.validate_incident(payload, root=self.root, verify_live=True),
            payload[incident.SELF_HASH_FIELD],
        )
        self.assert_no_incident_publication()

    def test_payload_tamper_fails_even_with_rehashed_document(self) -> None:
        payload = self.build()
        tampered = copy.deepcopy(payload)
        tampered["creator_provenance"]["creator_command"] = "claimed-command"
        tampered[incident.SELF_HASH_FIELD] = incident.document_hash(tampered)
        with self.assertRaises(incident.IncidentError):
            incident.validate_incident(tampered, root=self.root, verify_live=True)

    def test_present_file_tamper_fails_live_validation(self) -> None:
        payload = self.build()
        target = self.fixture.path(incident.QUEUE_VALIDATION_RELATIVE)
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaises(incident.IncidentError):
            incident.validate_incident(payload, root=self.root, verify_live=True)

    def test_downstream_presence_fails_closed(self) -> None:
        target = self.fixture.path(incident.DOWNSTREAM_ABSENT_PATHS[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(incident.IncidentError):
            self.build()

    def test_post_incident_governance_presence_fails_closed(self) -> None:
        target = self.fixture.path(
            incident.POST_INCIDENT_GOVERNANCE_ABSENT_PATHS[0]
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(incident.IncidentError):
            self.build()

    def test_orphan_files_under_every_execution_output_root_fail_before_read(self) -> None:
        for relative in incident.EXECUTION_OUTPUT_ROOT_PATHS:
            with self.subTest(relative=relative):
                output_root = self.fixture.path(relative)
                forged = output_root / "orphan" / "forged.json"
                forged.parent.mkdir(parents=True)
                forged.write_text("{}\n", encoding="utf-8")
                with mock.patch.object(
                    incident,
                    "_direct_snapshot",
                    side_effect=AssertionError("incident sources must not be read"),
                ):
                    with self.assertRaises(incident.IncidentError):
                        self.build()
                forged.unlink()
                forged.parent.rmdir()
                output_root.rmdir()

    def test_replacement_index_and_output_root_presence_fail_before_read(self) -> None:
        replacement_index = self.fixture.path(
            incident.REPLACEMENT_ALLOCATION_INDEX_RELATIVE
        )
        replacement_index.write_text("forged\n", encoding="utf-8")
        with mock.patch.object(
            incident,
            "_direct_snapshot",
            side_effect=AssertionError("incident sources must not be read"),
        ):
            with self.assertRaises(incident.IncidentError):
                self.build()
        replacement_index.unlink()

        replacement_root = self.fixture.path(
            incident.REPLACEMENT_LOCK_ROOT_RELATIVE
        )
        forged = replacement_root / "orphan" / "forged.json"
        forged.parent.mkdir(parents=True)
        forged.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(
            incident,
            "_direct_snapshot",
            side_effect=AssertionError("incident sources must not be read"),
        ):
            with self.assertRaises(incident.IncidentError):
                self.build()

    def test_broken_symlink_at_every_output_root_or_leaf_fails_closed(self) -> None:
        absent_target = self.root / "deliberately-absent-output-target"
        for relative in (
            *incident.EXECUTION_OUTPUT_ROOT_PATHS,
            *incident.REPLACEMENT_OUTPUT_PATHS,
        ):
            with self.subTest(relative=relative):
                path = self.fixture.path(relative)
                path.symlink_to(absent_target, target_is_directory=True)
                with self.assertRaises(incident.IncidentError):
                    self.build()
                path.unlink()

    def test_symlinked_output_parent_chain_fails_closed_before_source_read(self) -> None:
        direct_p07 = self.fixture.p07
        relocated_p07 = direct_p07.with_name("p07-relocated")
        direct_p07.rename(relocated_p07)
        direct_p07.symlink_to(relocated_p07, target_is_directory=True)
        with mock.patch.object(
            incident,
            "_direct_snapshot",
            side_effect=AssertionError("incident sources must not be read"),
        ):
            with self.assertRaises(incident.IncidentError):
                self.build()

    def test_observation_time_must_not_precede_latest_ctime(self) -> None:
        with self.assertRaises(incident.IncidentError):
            incident.build_incident(
                root=self.root,
                observed_at="1970-01-01T00:00:00+00:00",
                require_output_absent=True,
            )

        payload = self.build()
        payload["observed_at"] = "1970-01-01T00:00:00+00:00"
        payload[incident.SELF_HASH_FIELD] = incident.document_hash(payload)
        with self.assertRaises(incident.IncidentError):
            incident.validate_incident(payload, root=self.root, verify_live=False)

    def test_registry_suffix_drift_fails_closed(self) -> None:
        content = self.fixture.registry_path.read_text(encoding="utf-8")
        self.fixture.registry_path.write_text(
            content.replace(",PLANNED,logs/synthetic_backend_240\n", ",RUNNING,logs/synthetic_backend_240\n"),
            encoding="utf-8",
        )
        with self.assertRaises(incident.IncidentError):
            self.build()

    def test_expected_attempt_directory_presence_fails_closed(self) -> None:
        attempt = self.fixture.path(self.fixture.queue_rows[0]["expected_attempt_dir"])
        attempt.mkdir(parents=True)
        with self.assertRaises(incident.IncidentError):
            self.build()

    def test_no_clobber_publication(self) -> None:
        payload = self.build()
        record = incident.publish_incident(payload, root=self.root)
        self.assertEqual(record["path"], incident.OUTPUT_RELATIVE)
        self.assertEqual(
            self.fixture.path(incident.OUTPUT_RELATIVE).read_bytes(),
            incident.json_bytes(payload),
        )
        with self.assertRaises(FileExistsError):
            incident.publish_incident(payload, root=self.root)

    def test_prelink_present_input_drift_leaves_no_incident(self) -> None:
        payload = self.build()
        target = self.fixture.path(incident.QUEUE_VALIDATION_RELATIVE)

        def drift() -> None:
            target.write_bytes(target.read_bytes() + b" ")

        with self.assertRaises(
            (incident.IncidentError, incident.formal_io.FormalIOError)
        ):
            incident.publish_incident(
                payload, root=self.root, _pre_link_test_hook=drift
            )
        self.assert_no_incident_publication()

    def test_prelink_future_output_drift_leaves_no_incident(self) -> None:
        payload = self.build()
        target = self.fixture.path(
            incident.POST_INCIDENT_GOVERNANCE_ABSENT_PATHS[0]
        )

        def drift() -> None:
            target.write_text("{}\n", encoding="utf-8")

        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(
                payload, root=self.root, _pre_link_test_hook=drift
            )
        self.assertTrue(target.exists())
        self.assert_no_incident_publication()

    def test_prelink_orphan_attempt_root_drift_leaves_no_incident(self) -> None:
        payload = self.build()
        orphan = (
            self.fixture.path(incident.EXECUTION_OUTPUT_ROOT_PATHS[0])
            / "unplanned_orphan_attempt"
            / "forged.json"
        )

        def drift() -> None:
            orphan.parent.mkdir(parents=True)
            orphan.write_text("{}\n", encoding="utf-8")

        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(
                payload, root=self.root, _pre_link_test_hook=drift
            )
        self.assertTrue(orphan.exists())
        self.assert_no_incident_publication()

    def test_postlink_present_input_drift_rolls_back_own_incident(self) -> None:
        payload = self.build()
        target = self.fixture.path(incident.QUEUE_VALIDATION_RELATIVE)

        def drift() -> None:
            target.write_bytes(target.read_bytes() + b" ")

        with self.assertRaises(
            (incident.IncidentError, incident.formal_io.FormalIOError)
        ):
            incident.publish_incident(
                payload, root=self.root, _post_link_test_hook=drift
            )
        self.assert_no_incident_publication()

    def test_postlink_future_output_drift_rolls_back_own_incident(self) -> None:
        payload = self.build()
        target = self.fixture.path(incident.DOWNSTREAM_ABSENT_PATHS[0])

        def drift() -> None:
            target.write_text("{}\n", encoding="utf-8")

        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(
                payload, root=self.root, _post_link_test_hook=drift
            )
        self.assertTrue(target.exists())
        self.assert_no_incident_publication()

    def test_postlink_g0_output_root_drift_rolls_back_own_incident(self) -> None:
        payload = self.build()
        forged = (
            self.fixture.path(incident.EXECUTION_OUTPUT_ROOT_PATHS[-1])
            / "unplanned_g0_result.json"
        )

        def drift() -> None:
            forged.parent.mkdir(parents=True)
            forged.write_text("{}\n", encoding="utf-8")

        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(
                payload, root=self.root, _post_link_test_hook=drift
            )
        self.assertTrue(forged.exists())
        self.assert_no_incident_publication()

    def test_postlink_competing_winner_is_never_unlinked(self) -> None:
        payload = self.build()
        destination = self.fixture.path(incident.OUTPUT_RELATIVE)
        winner = b"external-winner\n"

        def replace_with_winner() -> None:
            destination.unlink()
            destination.write_bytes(winner)

        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(
                payload,
                root=self.root,
                _post_link_test_hook=replace_with_winner,
            )
        self.assertEqual(destination.read_bytes(), winner)
        self.assertEqual(
            list(self.fixture.p07.glob(".backend_formalization_incident_v1.json.partial.*")),
            [],
        )

    def test_publisher_rejects_nonfresh_rehashed_payload(self) -> None:
        payload = self.build()
        payload["creator_provenance"]["creator_command"] = "claimed-command"
        payload[incident.SELF_HASH_FIELD] = incident.document_hash(payload)
        with self.assertRaises(incident.IncidentError):
            incident.publish_incident(payload, root=self.root)
        self.assert_no_incident_publication()

    def test_default_cli_is_read_only_preview(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = incident.main(
                ["--root", str(self.root), "--observed-at", OBSERVED_AT]
            )
        self.assertEqual(result, 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["status"], incident.STATUS)
        self.assertFalse(self.fixture.path(incident.OUTPUT_RELATIVE).exists())


if __name__ == "__main__":
    unittest.main()
