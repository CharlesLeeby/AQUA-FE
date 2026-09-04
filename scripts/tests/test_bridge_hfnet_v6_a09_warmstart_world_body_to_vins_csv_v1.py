#!/usr/bin/env python3
"""Static and temporary-directory tests for the sealed A09 HFNet bridge."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import bridge_hfnet_v6_a09_warmstart_world_body_to_vins_csv_v1 as bridge


class A09BridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_sealed_audit_is_read_only_and_exact(self) -> None:
        before = {
            name: bridge.read_regular(Path(pin.path))[1]
            for name, pin in bridge.SEALED_PINS.items()
        }
        record = bridge.audit_record(bridge.prepare_evidence())
        after = {
            name: bridge.read_regular(Path(pin.path))[1]
            for name, pin in bridge.SEALED_PINS.items()
        }
        self.assertEqual(before, after)
        self.assertEqual(record["status"], "AUDIT_PASS_NO_WRITE")
        self.assertEqual(record["row_count"], 401)
        self.assertEqual(
            record["lossless_bridge"]["sha256"],
            bridge.EXPECTED_BRIDGE_CONTENT["sha256"],
        )
        self.assertEqual(
            record["source_stamp_canonicalization"]["sha256"],
            bridge.EXPECTED_CANONICAL_CONTENT["sha256"],
        )
        self.assertEqual(
            record["source_stamp_canonicalization"]
            ["complete_sealed_minus_source_delta_histogram_ns"],
            {str(key): value for key, value in bridge.EXPECTED_DELTA_HISTOGRAM_NS.items()},
        )

    def test_two_stage_temporary_publication_and_canonical_receipts(self) -> None:
        first = self.root / "bridge.csv"
        first_receipt = self.root / "bridge.receipt.json"
        second = self.root / "canonical.csv"
        second_receipt = self.root / "canonical.receipt.json"

        first_result = bridge.bridge_stage(first, first_receipt)
        second_result = bridge.canonicalize_stage(
            first,
            first_receipt,
            second,
            second_receipt,
        )
        self.assertEqual(
            first_result["output"]["sha256"],
            bridge.EXPECTED_BRIDGE_CONTENT["sha256"],
        )
        self.assertEqual(
            second_result["output"]["sha256"],
            bridge.EXPECTED_CANONICAL_CONTENT["sha256"],
        )
        for receipt_path in (first_receipt, second_receipt):
            payload = receipt_path.read_bytes()
            value = json.loads(payload.decode("utf-8"))
            self.assertEqual(payload, bridge.canonical_json(value))
            self.assertFalse(value["claim_boundary"]["accuracy_evaluated"])
            self.assertFalse(value["claim_boundary"]["hfnet_ros_vins_execution_surface"])

        first_rows = [line.split(",") for line in first.read_text(encoding="ascii").splitlines()]
        second_rows = [line.split(",") for line in second.read_text(encoding="ascii").splitlines()]
        self.assertEqual(len(first_rows), 401)
        self.assertEqual(
            [row[1:] for row in first_rows],
            [row[1:] for row in second_rows],
        )
        prepared = bridge.prepare_evidence()
        self.assertEqual(
            [int(row[0]) for row in second_rows],
            list(prepared.score_source_times_ns),
        )

    def test_strict_path_allowlist_rejects_byte_identical_source_copy(self) -> None:
        copied = self.root / "copied_score.txt"
        copied.write_bytes(Path(bridge.SEALED_PINS["score_source"].path).read_bytes())
        paths = dict(bridge.DEFAULT_AUTHORITY_PATHS)
        paths["score_source"] = copied
        with self.assertRaisesRegex(
            bridge.BridgeError, "AUTHORITY_PATH_NOT_ALLOWLISTED:score_source"
        ):
            bridge.prepare_evidence(paths)

    def test_terminal_claim_mutation_is_semantically_rejected(self) -> None:
        path = Path(bridge.SEALED_PINS["terminal_freeze"].path)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["claim_boundary"]["accuracy_evaluated"] = True
        with self.assertRaisesRegex(bridge.BridgeError, "TERMINAL_CLAIM_BOUNDARY"):
            bridge.validate_terminal_freeze_value(value, bridge.SEALED_PINS)

    def test_fractional_timestamp_bad_quaternion_and_blank_are_rejected(self) -> None:
        with self.assertRaisesRegex(bridge.BridgeError, "TIMESTAMP_NOT_INTEGER_NS"):
            bridge.parse_score_source(b"1.5 0 0 0 0 0 0 1\n")
        with self.assertRaisesRegex(bridge.BridgeError, "QUATERNION_NORM"):
            bridge.parse_score_source(b"1 0 0 0 0 0 0 2\n")
        with self.assertRaisesRegex(bridge.BridgeError, "BLANK_ROW"):
            bridge.parse_score_source(b"1 0 0 0 0 0 0 1\n\n")

    def test_existing_output_or_receipt_is_never_adopted(self) -> None:
        output = self.root / "owned.csv"
        receipt = self.root / "owned.receipt.json"
        output.write_bytes(b"preexisting owner")
        with self.assertRaisesRegex(bridge.BridgeError, "OUTPUT_ALREADY_EXISTS"):
            bridge.bridge_stage(output, receipt)
        self.assertEqual(output.read_bytes(), b"preexisting owner")
        self.assertFalse(receipt.exists())

        second_output = self.root / "new.csv"
        second_receipt = self.root / "preexisting.receipt.json"
        second_receipt.write_bytes(b"receipt owner")
        with self.assertRaisesRegex(bridge.BridgeError, "RECEIPT_ALREADY_EXISTS"):
            bridge.bridge_stage(second_output, second_receipt)
        self.assertFalse(second_output.exists())
        self.assertEqual(second_receipt.read_bytes(), b"receipt owner")

    def test_dangling_symlink_target_is_rejected(self) -> None:
        output = self.root / "dangling.csv"
        receipt = self.root / "dangling.receipt.json"
        output.symlink_to(self.root / "missing-target")
        with self.assertRaisesRegex(bridge.BridgeError, "OUTPUT_ALREADY_EXISTS"):
            bridge.bridge_stage(output, receipt)
        self.assertTrue(output.is_symlink())
        self.assertFalse(receipt.exists())

    def test_receipt_link_failure_rolls_back_only_owned_output(self) -> None:
        output = self.root / "transaction.bin"
        receipt = self.root / "transaction.receipt.json"
        original_link = bridge.os.link
        calls = []

        def fail_second_link(source, target, **kwargs):
            calls.append((source, target))
            if len(calls) == 2:
                raise FileExistsError("synthetic receipt race")
            return original_link(source, target, **kwargs)

        with patch.object(bridge.os, "link", side_effect=fail_second_link):
            with self.assertRaisesRegex(bridge.BridgeError, "RECEIPT_RACE_ALREADY_EXISTS"):
                bridge.publish_output_and_receipt(
                    output,
                    b"science bytes",
                    receipt,
                    bridge.canonical_json({"status": "synthetic"}),
                )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_tampered_stage1_receipt_blocks_canonicalization(self) -> None:
        first = self.root / "bridge.csv"
        first_receipt = self.root / "bridge.receipt.json"
        bridge.bridge_stage(first, first_receipt)
        first_receipt.chmod(0o600)
        value = json.loads(first_receipt.read_text(encoding="utf-8"))
        value["claim_boundary"]["accuracy_evaluated"] = True
        first_receipt.write_bytes(bridge.canonical_json(value))
        with self.assertRaisesRegex(
            bridge.BridgeError, "UPSTREAM_BRIDGE_RECEIPT_CONTRACT"
        ):
            bridge.canonicalize_stage(
                first,
                first_receipt,
                self.root / "canonical.csv",
                self.root / "canonical.receipt.json",
            )

    def test_no_process_ros_hfnet_or_evaluator_execution_surface(self) -> None:
        source = bridge.TOOL_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        dangerous_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in {"Popen", "run", "call", "system", "execv", "execve", "spawnv"}:
                    dangerous_calls.append(name)
        self.assertTrue({"subprocess", "rosbag", "rospy"}.isdisjoint(imported))
        self.assertEqual(dangerous_calls, [])
        self.assertNotIn("evaluate_vins_common_support", source)


if __name__ == "__main__":
    unittest.main()
