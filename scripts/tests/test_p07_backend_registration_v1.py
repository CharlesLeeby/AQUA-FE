from __future__ import annotations

import csv
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from scripts import build_p07_backend_replay_queue_v1 as builder
from scripts import register_p07_backend_allocations_v1 as registration
from scripts import validate_p07_backend_replay_queue_v1 as validator
from scripts.tests.test_p07_backend_replay_queue_v1 import HASHES, fixture_snapshot


class P07BackendRegistrationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        snapshot = fixture_snapshot(applicable_windows=1)
        outputs = builder.build_outputs(
            snapshot,
            allocated_at="2026-08-08T00:00:00+08:00",
            method_hashes=HASHES[:5],
            include_code_records=False,
        )
        _fields, self.queue = validator.parse_csv(outputs[builder.BACKEND_QUEUE])
        _fields, self.allocations = validator.parse_csv(
            outputs[builder.BACKEND_ALLOCATION]
        )
        self.registry_fields, _rows = registration.read_csv_with_fields(
            registration.RUN_REGISTRY
        )
        self.split_roles = {
            row["window_id"]: "FIXTURE_OUTCOME_BLIND"
            for row in snapshot.manifest_rows
        }
        self.intended = registration.build_registry_rows(
            self.queue,
            self.allocations,
            registry_fields=self.registry_fields,
            split_roles=self.split_roles,
        )

    def test_all_allocations_map_to_unique_untouched_planned_e00(self) -> None:
        self.assertEqual(len(self.intended), 243)
        self.assertEqual(len({row["run_id"] for row in self.intended}), 243)
        self.assertTrue(all(row["status"] == "PLANNED" for row in self.intended))
        self.assertTrue(
            all(row["registry_event_id"] == f"{row['run_id']}_e00" for row in self.intended)
        )
        report = registration.validate_registered(self.intended, self.intended)
        self.assertTrue(report["pass"])
        self.assertEqual(report["unique_untouched_planned_e00"], 243)

    def test_running_event_before_execution_lock_is_rejected(self) -> None:
        running = dict(self.intended[0])
        running["registry_event_id"] = f"{running['run_id']}_e01"
        running["supersedes_event_id"] = self.intended[0]["registry_event_id"]
        running["status"] = "RUNNING"
        report = registration.validate_registered(
            self.intended, [*self.intended, running]
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["unique_untouched_planned_e00"], 242)

    def test_append_is_idempotent_and_fails_closed_on_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=self.registry_fields).writeheader()
            subset = self.intended[:2]
            self.assertEqual(registration.append_missing(path, subset), 2)
            self.assertEqual(registration.append_missing(path, subset), 0)
            collision = dict(subset[0])
            collision["notes"] = "different"
            with self.assertRaisesRegex(ValueError, "collision"):
                registration.append_missing(path, [collision])

    def test_registration_intent_binds_exact_rows_and_rejects_tamper(self) -> None:
        expected_paths = {
            "backend_queue": builder.display_path(builder.BACKEND_QUEUE),
            "backend_allocation": builder.display_path(builder.BACKEND_ALLOCATION),
            "backend_queue_lock": builder.display_path(builder.BACKEND_QUEUE_LOCK),
            "backend_queue_validation": builder.display_path(
                builder.BACKEND_QUEUE_VALIDATION
            ),
            "split_role_audit": builder.display_path(
                builder.P07 / "split_role_audit_v1.csv"
            ),
        }
        fake_records = {
            name: {
                "path": expected_paths[name],
                "sha256": hashlib.sha256(name.encode()).hexdigest(),
                "size_bytes": len(name),
            }
            for name in (
                "backend_queue",
                "backend_allocation",
                "backend_queue_lock",
                "backend_queue_validation",
                "split_role_audit",
            )
        }
        registry_prefix = {
            "path": builder.display_path(registration.RUN_REGISTRY),
            "sha256": "b" * 64,
            "size_bytes": 123,
        }
        queue_lock = {
            "backend_queue_lock_hash": "a" * 64,
            "mutable_stream_prefix_snapshots": [registry_prefix],
        }
        intent = registration.build_registration_intent(
            queue_lock=queue_lock,
            intended=self.intended,
            registry_prefix=registry_prefix,
            allocated_at="2026-08-08T00:00:00+08:00",
            artifact_records=fake_records,
        )
        registration.validate_registration_intent(
            intent,
            intended=self.intended,
            queue_lock=queue_lock,
            expected_artifact_records=fake_records,
        )
        tampered = dict(intent)
        tampered["intended_backend_runs"] = len(self.intended) - 1
        tampered["registration_intent_hash"] = registration._document_hash(
            tampered, "registration_intent_hash"
        )
        with self.assertRaisesRegex(ValueError, "intent"):
            registration.validate_registration_intent(
                tampered,
                intended=self.intended,
                queue_lock=queue_lock,
                expected_artifact_records=fake_records,
            )
        expanded = dict(intent)
        expanded["unexpected_authority"] = True
        expanded["registration_intent_hash"] = registration._document_hash(
            expanded, "registration_intent_hash"
        )
        with self.assertRaisesRegex(ValueError, "intent"):
            registration.validate_registration_intent(
                expanded,
                intended=self.intended,
                queue_lock=queue_lock,
                expected_artifact_records=fake_records,
            )
        split_tampered = dict(intent)
        split_tampered["split_role_audit"] = {
            **intent["split_role_audit"],
            "sha256": "f" * 64,
        }
        split_tampered["registration_intent_hash"] = registration._document_hash(
            split_tampered, "registration_intent_hash"
        )
        with self.assertRaisesRegex(ValueError, "authority"):
            registration.validate_registration_intent(
                split_tampered,
                intended=self.intended,
                queue_lock=queue_lock,
                expected_artifact_records=fake_records,
            )

    def test_append_rejects_symlink_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external.csv"
            with external.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=self.registry_fields).writeheader()
            link = root / "registry.csv"
            link.symlink_to(external)
            with self.assertRaises(OSError):
                registration.append_missing(link, self.intended[:1])
            self.assertEqual(external.read_text().count("\n"), 1)

    def test_append_rejects_hardlink_and_symlink_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = root / "registry.csv"
            with direct.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=self.registry_fields).writeheader()
            hardlink = root / "registry-hardlink.csv"
            os.link(direct, hardlink)
            with self.assertRaisesRegex(ValueError, "direct regular file"):
                registration.append_missing(hardlink, self.intended[:1])
            self.assertEqual(direct.read_text().count("\n"), 1)

            outside = root / "outside"
            outside.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(outside, target_is_directory=True)
            linked_registry = linked_parent / "registry.csv"
            linked_registry.write_bytes(direct.read_bytes())
            with self.assertRaisesRegex(ValueError, "parent is unsafe"):
                registration.append_missing(linked_registry, self.intended[:1])
            self.assertEqual(linked_registry.read_text().count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
