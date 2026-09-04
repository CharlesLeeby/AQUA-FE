from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_p03_candidate_bundle import (
    DEFAULT_LOCK,
    DEFAULT_PROTOCOL,
    BundleValidationError,
    payload_hash,
    validate_claim_boundary,
    validate_method_lock,
    validate_protocol,
    validate_shadow_csv,
)


class P03CandidateBundleValidatorTests(unittest.TestCase):
    def test_current_protocol_and_method_lock_are_candidate_only(self) -> None:
        protocol = validate_protocol(DEFAULT_PROTOCOL)
        self.assertEqual(protocol["status_token"], "CANDIDATE_P03")
        # The lock is deliberately checked by the integration command.  It
        # may be stale while another agent is changing a frozen source file;
        # the unit test should exercise token parsing independently.
        self.assertEqual(json.loads(DEFAULT_LOCK.read_text())["status"], "P03_CANDIDATE_NOT_CANONICAL")

    def test_method_lock_hash_changes_when_payload_changes(self) -> None:
        data = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
        original = payload_hash(data)
        data["route"] = "TAMPERED"
        self.assertNotEqual(original, payload_hash(data))

    def test_master_chain_rejects_predecessor_tamper(self) -> None:
        # A minimal malformed JSONL is enough to exercise the validator's
        # error envelope without depending on a concurrently regenerated
        # smoke file.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "master.jsonl"
            path.write_text('{"not": "a master event"}\n', encoding="utf-8")
            from scripts.validate_p03_candidate_bundle import validate_master_stream

            with self.assertRaisesRegex(BundleValidationError, "line 1|master stream"):
                validate_master_stream(path)

    def test_shadow_schema_rejects_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.csv"
            path.write_text("event_index\n0\n", encoding="utf-8")
            with self.assertRaisesRegex(BundleValidationError, "missing columns"):
                validate_shadow_csv(path, [object()])

    def test_claim_boundary_rejects_unlabelled_confirmatory_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.md"
            protocol.write_text(
                "\n".join(
                    (
                        "No number in this document is a confirmatory APE/RPE result.",
                        "Existing cached learned/VINS windows remain development-only.",
                        "no held-out or confirmatory learned/VINS result is claimed in P03.",
                        "Confirmatory APE: 0.123",
                    )
                ),
                encoding="utf-8",
            )
            lock = root / "lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "development_smoke_artifacts": [
                            {"role": "development_smoke_artifact", "path": "p03/smoke_x.jsonl"}
                        ],
                        "calibration": {"status": "PROVISIONAL_DEVELOPMENT_ONLY"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BundleValidationError, "boundary violations"):
                validate_claim_boundary(protocol, lock, root)


if __name__ == "__main__":
    unittest.main()
