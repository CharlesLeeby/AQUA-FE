#!/usr/bin/env python3
"""Regression tests for the post-A05 accuracy supersession builder."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import copy
import contextlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_hfnet_v6_samehistory_positive_accuracy_supersession_v2.py"


def load_module():
    name = "_test_accuracy_supersession_builder_v2"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = load_module()


def lock_evidence(path: Path | None = None) -> dict[str, object]:
    return {
        "path": str(path or B.GLOBAL_SERIAL_LOCK),
        "pid": 12345,
        "acquired_at_utc": "2026-08-28T19:00:00Z",
        "mode": "EXCLUSIVE_NONBLOCKING_FLOCK",
        "scope": "DOUBLE_BUILD_COMPARE_THROUGH_HARDLINK_PUBLICATION_OR_DRY_RUN_OUTPUT",
    }


class BuilderContractTests(unittest.TestCase):
    def test_default_cli_is_dry_run(self) -> None:
        arguments = B.parse_args([])
        self.assertFalse(arguments.publish)
        self.assertIsNone(arguments.authorization_token)

    def test_real_document_is_post_a05_pre_remaining_nine(self) -> None:
        before = B.file_identity(B.BASE_SEAL, "base_before", B.BASE_SEAL_EXPECTED)
        first = B.build_document(lock_evidence())
        second = B.build_document(lock_evidence())
        B.validate_document(first)
        self.assertEqual(first, second)
        self.assertEqual(first["remaining_cases"], list(B.REMAINING_CASES))
        self.assertNotIn(B.A05, first["remaining_cases"])
        self.assertEqual(
            first["a05_terminal_boundary"]["status"],
            "TERMINAL_FAIL_ACCURACY_NA_NO_RETRY",
        )
        self.assertFalse(first["a05_terminal_boundary"]["accuracy_numeric_authorized"])
        self.assertEqual(
            first["zero_kf_watchdog_contract"]["accuracy_promotable_status"],
            "PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL",
        )
        self.assertFalse(
            first["zero_kf_watchdog_contract"][
                "zero_kf_or_supervision_error_promotable"
            ]
        )
        self.assertEqual(
            first["analysis_code_identities"]["cache_contract_adjudicator"],
            B.file_identity(
                B.CACHE_ADJUDICATOR,
                "validator",
                B.CACHE_ADJUDICATOR_EXPECTED,
            ),
        )
        self.assertEqual(
            first["authorities"]["zero_kf_watchdog_protocol"],
            B.file_identity(
                B.ZERO_KF_WATCHDOG_PROTOCOL,
                "watchdog_protocol",
                B.ZERO_KF_WATCHDOG_PROTOCOL_EXPECTED,
            ),
        )
        self.assertEqual(
            before,
            B.file_identity(B.BASE_SEAL, "base_after", B.BASE_SEAL_EXPECTED),
        )

    def test_no_plaintext_tokens_in_document(self) -> None:
        payload = B.canonical_json_bytes(B.build_document(lock_evidence()))
        for token in (
            B.PUBLISH_TOKEN,
            "FREEZE_HFNET_V6_SAMEHISTORY_ACCURACY_LOCK_V2",
            "RUN_FROZEN_HFNET_V6_SAMEHISTORY_ACCURACY_V2",
        ):
            self.assertNotIn(token.encode("ascii"), payload)

    def test_publish_is_hardlink_no_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "delta.json"
            payload = B.canonical_json_bytes({"status": "fixture"})
            identity = B.publish_noreplace(destination, payload)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(identity["path"], str(destination))
            with self.assertRaisesRegex(B.BuildError, "publish_destination"):
                B.publish_noreplace(destination, b"replacement")
            self.assertEqual(destination.read_bytes(), payload)

    def test_global_lock_is_nonblocking_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".gpu_serial.lock"
            path.write_bytes(b"")
            with mock.patch.object(B, "GLOBAL_SERIAL_LOCK", path):
                with B.global_serial_lock() as evidence:
                    self.assertEqual(evidence["path"], str(path))
                    with self.assertRaisesRegex(B.BuildError, "GLOBAL_SERIAL_LOCK_BUSY"):
                        with B.global_serial_lock():
                            self.fail("nested lock unexpectedly acquired")

    def test_document_rejects_bad_lock_evidence(self) -> None:
        bad = lock_evidence()
        bad["pid"] = True
        with self.assertRaisesRegex(B.BuildError, "RUNTIME_GLOBAL_SERIAL_LOCK_EVIDENCE"):
            B.build_document(bad)
        document = B.build_document(lock_evidence())
        document["publication_contract"]["global_serial_lock_contract"][
            "held_through_double_build_and_publication"
        ] = False
        with self.assertRaisesRegex(B.BuildError, "GLOBAL_SERIAL_LOCK_CONTRACT"):
            B.validate_document(document)

    def test_dry_run_main_does_not_publish(self) -> None:
        class Stdout:
            def __init__(self) -> None:
                self.buffer = io.BytesIO()

        stdout = Stdout()
        with mock.patch.object(sys, "stdout", stdout):
            result = B.main([])
        self.assertEqual(result, 0)
        value = json.loads(stdout.buffer.getvalue())
        self.assertEqual(value["status"], B.STATUS)
        self.assertFalse(B.PUBLICATION_PATH.exists())

    def test_main_rejects_double_build_drift_under_one_lock(self) -> None:
        evidence = lock_evidence()
        first = B.build_document(evidence)
        second = copy.deepcopy(first)
        second["reporting_boundary"] += " drift"
        output = io.StringIO()
        with mock.patch.object(
            B, "global_serial_lock", return_value=contextlib.nullcontext(evidence)
        ), mock.patch.object(B, "build_document", side_effect=(first, second)), mock.patch.object(
            sys, "stdout", output
        ):
            result = B.main([])
        self.assertEqual(result, 2)
        self.assertIn("DOUBLE_BUILD_TOCTOU_DRIFT", output.getvalue())


if __name__ == "__main__":
    unittest.main()
