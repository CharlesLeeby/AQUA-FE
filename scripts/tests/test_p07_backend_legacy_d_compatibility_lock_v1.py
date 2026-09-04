from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_p07_backend_legacy_d_compatibility_lock_v1 as builder
from scripts import p07_backend_frontend_provenance_v1 as provenance


class P07BackendLegacyDCompatibilityLockV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.sanctioned_patch = mock.patch.dict(
            provenance.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS, {}, clear=True
        )
        self.sanctioned_patch.start()
        self.fields = [
            "protocol_version",
            "method_profile",
            "dataset_family",
            "sequence",
            "window_start",
            "window_end",
            "proposed_arm",
            "accepted_lineage_count",
            "applicability_rule",
            "resolution_time",
            "drop_arm",
            "classical_arm",
            "resolution",
            "evidence_path",
            "resolver_hash",
        ]
        self.rows: list[dict[str, str]] = []
        applicability = (
            self.root
            / "papers/ieee_sensors_journal_experiments/arm_applicability.csv"
        )
        applicability.parent.mkdir(parents=True, exist_ok=True)
        with applicability.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(
                handle, fieldnames=self.fields, lineterminator="\n"
            ).writeheader()
        registry = (
            self.root
            / "papers/ieee_sensors_journal_experiments/run_registry.csv"
        )
        registry.write_text("run_id,status\n", encoding="utf-8")
        for case in builder.CASES:
            self._case(case)
        with applicability.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fields, lineterminator="\n")
            writer.writerows(self.rows)

    def tearDown(self) -> None:
        self.sanctioned_patch.stop()
        self.tempdir.cleanup()

    def _record(self, path: Path) -> dict[str, object]:
        return provenance.file_record(self.root, path)

    def _case(self, case: builder.LegacyCase) -> None:
        expected_paths = builder.LEGACY_ARTIFACT_PATHS[case.label]
        for relative in expected_paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(f"fixture:{relative}\n".encode())
        p_bag = self.root / next(
            relative
            for relative in expected_paths
            if relative.endswith("features.bag") and "_p_attempt" in relative
        )
        b1_bag = self.root / next(
            relative
            for relative in expected_paths
            if relative.endswith("features.bag") and "_b1_attempt" in relative
        )
        audit = self.root / next(
            relative
            for relative in expected_paths
            if "/frontend_attempts/" in relative
            and "/audit_v" in relative
            and "_p_attempt" in relative
        )
        p_bag.write_bytes(b"identical\n")
        b1_bag.write_bytes(b"identical\n")
        audit.write_text("{}\n", encoding="utf-8")
        bag_hash = hashlib.sha256(p_bag.read_bytes()).hexdigest()
        artifacts = [self._record(self.root / relative) for relative in expected_paths]
        prefixes = []
        for relative in sorted(builder.LEGACY_PREFIX_PATHS):
            path = self.root / relative
            content = path.read_bytes()
            prefixes.append(
                {
                    "binding": "PRE_RESOLUTION_APPEND_ONLY_PREFIX_SNAPSHOT",
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
        lock: dict[str, object] = {
            "schema_version": case.lock_schema,
            "status": "FROZEN_READY_TO_APPEND_NOT_APPLICABLE",
            "window_id": case.window_id,
            "slot_index": case.slot_index,
            "held_out_trajectory_outcome_read": False,
            "artifacts": artifacts,
            "mutable_stream_prefix_snapshots": prefixes,
        }
        lock["resolution_lock_hash"] = builder.document_hash(
            lock, "resolution_lock_hash"
        )
        lock_path = self.root / case.lock_relative
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        row = {
            "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
            "method_profile": "P_legacy_nativeq_xfeat_seedchain_v3",
            "dataset_family": "aqualoc_archaeology",
            "sequence": case.sequence,
            "window_start": case.start,
            "window_end": case.end,
            "proposed_arm": "P_legacy_nativeq_xfeat_seedchain_v3",
            "accepted_lineage_count": "0",
            "applicability_rule": "accepted_learned_born_lineage_count>0",
            "resolution_time": "2026-08-08T00:00:00+08:00",
            "drop_arm": "D_legacy_exact_lineage_drop_v3",
            "classical_arm": "",
            "resolution": "NOT_APPLICABLE",
            "evidence_path": self._record(audit)["path"],
            "resolver_hash": str(lock["resolution_lock_hash"]),
        }
        self.rows.append(row)
        rendered = builder._render_row(self.fields, row)
        terminal = {
            "schema_version": case.terminal_schema,
            "status": "PASS_NOT_APPLICABLE",
            "window_id": case.window_id,
            "slot_index": case.slot_index,
            "parent_p_run_id": f"run-{case.label}",
            "accepted_learned_born_lineage_count": 0,
            "resolution": "NOT_APPLICABLE",
            "d_bag_created": False,
            "d_replay_slots_created": 0,
            "evidence": {
                "accepted_learned_born_lineage_count": 0,
                "active": False,
                "zero_action_identity": "PASS_BYTE_IDENTICAL_TO_B1",
                "p_feature_bag": self._record(p_bag)["path"],
                "p_feature_bag_sha256": bag_hash,
                "b1_feature_bag": self._record(b1_bag)["path"],
                "b1_feature_bag_sha256": bag_hash,
                "audit": self._record(audit)["path"],
                "audit_sha256": self._record(audit)["sha256"],
            },
            "resolution_lock_hash": lock["resolution_lock_hash"],
            "canonical_stream": {
                "appended_row_sha256": hashlib.sha256(rendered).hexdigest()
            },
            "held_out_trajectory_outcome_read": False,
        }
        terminal_path = self.root / case.terminal_relative
        terminal_path.parent.mkdir(parents=True, exist_ok=True)
        terminal_path.write_text(json.dumps(terminal), encoding="utf-8")

    def test_builds_two_sidecars_and_commit_lock_without_writing(self) -> None:
        outputs = builder.build_outputs(
            root=self.root,
            frozen_at="2026-08-08T00:00:00+08:00",
            include_code_records=False,
        )
        self.assertEqual(len(outputs), 3)
        lock_path = self.root / builder.OUTPUT.relative_to(builder.ROOT)
        lock = json.loads(outputs[lock_path])
        self.assertEqual(lock["status"], builder.LOCK_STATUS)
        self.assertEqual(
            lock["compatibility_lock_hash"],
            builder.document_hash(lock, "compatibility_lock_hash"),
        )
        self.assertFalse(lock_path.exists())

        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        validated = builder.validate_live_bundle(root=self.root)
        self.assertEqual(validated["compatibility_lock_hash"], lock["compatibility_lock_hash"])

    def test_lineage_or_identity_tamper_fails_closed(self) -> None:
        terminal = self.root / builder.CASES[0].terminal_relative
        payload = json.loads(terminal.read_text())
        payload["accepted_learned_born_lineage_count"] = 1
        terminal.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(builder.LegacyDCompatibilityError):
            builder.build_outputs(
                root=self.root,
                frozen_at="2026-08-08T00:00:00+08:00",
                include_code_records=False,
            )

    def test_lock_self_hash_tamper_fails_closed(self) -> None:
        lock_path = self.root / builder.CASES[1].lock_relative
        payload = json.loads(lock_path.read_text())
        payload["status"] = "TAMPERED"
        lock_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(builder.LegacyDCompatibilityError):
            builder.build_outputs(
                root=self.root,
                frozen_at="2026-08-08T00:00:00+08:00",
                include_code_records=False,
            )

    def test_rehashed_empty_artifacts_or_prefixes_fail_closed(self) -> None:
        for field in ("artifacts", "mutable_stream_prefix_snapshots"):
            lock_path = self.root / builder.CASES[0].lock_relative
            original = lock_path.read_bytes()
            payload = json.loads(original)
            payload[field] = []
            payload["resolution_lock_hash"] = builder.document_hash(
                payload, "resolution_lock_hash"
            )
            lock_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                builder.LegacyDCompatibilityError,
                "exact artifact set|exact mutable-prefix set",
            ):
                builder.build_outputs(
                    root=self.root,
                    frozen_at="2026-08-08T00:00:00+08:00",
                    include_code_records=False,
                )
            lock_path.write_bytes(original)

    def test_legacy_inputs_reject_leaf_symlink_and_hardlink(self) -> None:
        lock_path = self.root / builder.CASES[0].lock_relative
        original = lock_path.read_bytes()
        outside = self.root / "outside-lock.json"
        outside.write_bytes(original)
        lock_path.unlink()
        lock_path.symlink_to(outside)
        with self.assertRaises(builder.LegacyDCompatibilityError):
            builder.build_outputs(
                root=self.root,
                frozen_at="2026-08-08T00:00:00+08:00",
                include_code_records=False,
            )

        lock_path.unlink()
        lock_path.write_bytes(original)
        hardlink = self.root / "lock-hardlink.json"
        os.link(lock_path, hardlink)
        with self.assertRaises(builder.LegacyDCompatibilityError):
            builder.build_outputs(
                root=self.root,
                frozen_at="2026-08-08T00:00:00+08:00",
                include_code_records=False,
            )


if __name__ == "__main__":
    unittest.main()
