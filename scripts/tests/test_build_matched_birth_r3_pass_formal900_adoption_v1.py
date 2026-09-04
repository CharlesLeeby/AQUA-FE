from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


from scripts import build_matched_birth_r3_pass_formal900_adoption_v1 as adoption


class MatchedBirthR3FormalAdoptionTests(unittest.TestCase):
    def test_live_r3_pass_gate_is_exact_and_sanitized(self) -> None:
        record = adoption.build_record()
        self.assertEqual(record["schema_version"], adoption.SCHEMA_VERSION)
        self.assertEqual(record["status"], adoption.STATUS)
        source = record["source_namespace"]
        self.assertEqual(source["tree_entry_count"], 24)
        self.assertEqual(source["directory_count"], 5)
        self.assertEqual(source["regular_file_count"], 19)
        self.assertEqual(len(source["exact_tree_inventory"]), 24)
        self.assertEqual(
            set(record["pass_qualification"]["required_gate_names"]),
            adoption.EXPECTED_GATE_NAMES,
        )
        self.assertIs(record["pass_qualification"]["every_gate_pass"], True)
        encoded = adoption._canonical_bytes(record)
        for forbidden in (
            b'"metrics"', b'"observations"', b'"detector_candidates"',
            b'"births"', b'"unique_ids"',
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertNotIn("manifest_template", record)
        self.assertNotIn("payload", record)
        self.assertEqual(
            record["target"]["root"], str(adoption.R4_ROOT)
        )
        execution = record["builder_execution_contract"]
        self.assertEqual(execution["working_directory"], str(adoption.WORKSPACE_ROOT))
        self.assertEqual(execution["environment"], adoption.launcher.FROZEN_ENVIRONMENT)
        self.assertEqual(
            execution["runtime_sha256"],
            adoption.probe_audit.core._canonical_sha256(execution["runtime"]),
        )
        self.assertFalse(adoption.R4_ROOT.exists())

    def test_snapshot_holds_exact_five_directories_and_nineteen_files(self) -> None:
        snapshot = adoption._snapshot_r3()
        try:
            self.assertEqual(len(snapshot["directories"]), 5)
            self.assertEqual(len(snapshot["files"]), 19)
            self.assertEqual(len(snapshot["inventory"]), 24)
            self.assertEqual(
                sum(row["kind"] == "directory" for row in snapshot["inventory"]),
                5,
            )
            self.assertEqual(
                sum(row["kind"] == "regular" for row in snapshot["inventory"]),
                19,
            )
            adoption._finish_snapshot(snapshot)
        finally:
            adoption._close_snapshot(snapshot)

    def test_commit_identity_and_all_gate_drift_fail_closed(self) -> None:
        expected = copy.deepcopy(adoption.EXPECTED_R3_COMMIT_IDENTITIES)
        expected["freeze"]["sha256"] = "0" * 64
        with mock.patch.object(adoption, "EXPECTED_R3_COMMIT_IDENTITIES", expected):
            with self.assertRaisesRegex(adoption.AdoptionError, "commit identities"):
                adoption.build_record()

        expected_gates = set(adoption.EXPECTED_GATE_NAMES) | {"unknown_gate"}
        with mock.patch.object(adoption, "EXPECTED_GATE_NAMES", frozenset(expected_gates)):
            with self.assertRaisesRegex(adoption.AdoptionError, "gates"):
                adoption.build_record()

    def test_seal_pass_mode_claim_and_process_drift_fail_closed(self) -> None:
        original = adoption._decode_json
        cases = (
            ("pass", lambda value: value.__setitem__("pass", False), "PASS"),
            (
                "claim",
                lambda value: value["claim_boundary"].__setitem__(
                    "whole_slam_superiority", True
                ),
                "claim boundary",
            ),
            (
                "gate",
                lambda value: value["gates"]["manifest_pair"].__setitem__(
                    "pass", False
                ),
                "contract gate",
            ),
        )
        seal_name = "probe16_post_run_pair_seal.json"
        for label, mutate, message in cases:
            def changed(path, payload, *, label, _mutate=mutate):
                value = original(path, payload, label=label)
                if path.name == seal_name:
                    value = copy.deepcopy(value)
                    _mutate(value)
                return value

            with self.subTest(label=label), mock.patch.object(
                adoption, "_decode_json", side_effect=changed
            ):
                with self.assertRaisesRegex(adoption.AdoptionError, message):
                    adoption.build_record()

        def bad_process(path, payload, *, label):
            value = original(path, payload, label=label)
            if path.name == "launcher_rc_receipt.json":
                value = copy.deepcopy(value)
                value["producer_process"]["producer_return_code"] = 9
            return value

        with mock.patch.object(adoption, "_decode_json", side_effect=bad_process):
            with self.assertRaisesRegex(adoption.AdoptionError, "producer_return_code"):
                adoption.build_record()

    def test_canonical_json_codec_and_type_equality_are_fail_closed(self) -> None:
        path = adoption.R3_ROOT / "probe16_freeze.json"
        payload = path.read_bytes()
        parsed = adoption._decode_json(path, payload, label="freeze")
        self.assertEqual(parsed["status"], "FROZEN")
        with self.assertRaisesRegex(adoption.AdoptionError, "canonical codec"):
            adoption._decode_json(path, b" " + payload, label="freeze")
        with self.assertRaisesRegex(adoption.AdoptionError, "mismatch"):
            adoption._strict_equal(True, 1, label="type")

    def test_r4_or_pycache_presence_blocks_before_snapshot(self) -> None:
        real_lexists = os.path.lexists

        def r4_present(value):
            if os.fspath(value) == os.fspath(adoption.R4_ROOT):
                return True
            return real_lexists(value)

        with mock.patch("os.path.lexists", side_effect=r4_present), mock.patch.object(
            adoption, "_snapshot_r3"
        ) as snapshot:
            with self.assertRaisesRegex(adoption.AdoptionError, "r4 target"):
                adoption.build_record()
            snapshot.assert_not_called()

        def pycache_present(value):
            if os.fspath(value) == os.fspath(adoption.PY_CACHE_PREFIX):
                return True
            return real_lexists(value)

        with mock.patch("os.path.lexists", side_effect=pycache_present), mock.patch.object(
            adoption, "_snapshot_r3"
        ) as snapshot:
            with self.assertRaisesRegex(adoption.AdoptionError, "pycache"):
                adoption.build_record()
            snapshot.assert_not_called()

    def test_write_once_is_canonical_0444_o_excl_and_not_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "adoption.json"
            record = {"schema_version": "test", "status": "PASS"}
            with mock.patch.object(adoption, "DEFAULT_OUTPUT", target):
                identity = adoption.write_once(target, record)
                self.assertEqual(target.read_bytes(), adoption._canonical_bytes(record))
                observed = os.lstat(target)
                self.assertTrue(stat.S_ISREG(observed.st_mode))
                self.assertEqual(stat.S_IMODE(observed.st_mode), 0o444)
                self.assertEqual(observed.st_nlink, 1)
                self.assertEqual(identity["path"], str(target))
                with self.assertRaisesRegex(adoption.AdoptionError, "consumed"):
                    adoption.write_once(target, record)

    def test_finish_snapshot_failure_is_never_ignored(self) -> None:
        with mock.patch.object(
            adoption, "_finish_snapshot",
            side_effect=adoption.AdoptionError("final held drift"),
        ):
            with self.assertRaisesRegex(adoption.AdoptionError, "final held drift"):
                adoption.build_record()

    def test_open_file_read_failure_closes_uncommitted_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leaf = root / "leaf.json"
            leaf.write_bytes(b"{}\n")
            parent_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            descriptors = {}
            payloads = {}
            before = set(os.listdir("/proc/self/fd"))
            try:
                with mock.patch.object(
                    adoption, "_read_fd",
                    side_effect=adoption.AdoptionError("synthetic held read failure"),
                ):
                    with self.assertRaisesRegex(
                        adoption.AdoptionError, "synthetic held read failure"
                    ):
                        adoption._open_file(
                            leaf,
                            name=leaf.name,
                            parent_fd=parent_fd,
                            descriptors=descriptors,
                            payloads=payloads,
                        )
                self.assertEqual(descriptors, {})
                self.assertEqual(payloads, {})
                self.assertEqual(set(os.listdir("/proc/self/fd")), before)
            finally:
                os.close(parent_fd)

    def test_r3_device_identity_is_code_authoritative(self) -> None:
        with mock.patch.object(
            adoption, "EXPECTED_R3_DEVICE_ID", adoption.EXPECTED_R3_DEVICE_ID + 1
        ):
            with self.assertRaisesRegex(adoption.AdoptionError, "device identity"):
                adoption.build_record()


if __name__ == "__main__":
    unittest.main()
