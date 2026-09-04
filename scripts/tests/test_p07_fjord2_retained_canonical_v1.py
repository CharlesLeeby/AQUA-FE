#!/usr/bin/env python3
"""Synthetic tests for the additive fjord_2 retained-canonical attester."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import attest_p07_fjord2_retained_canonical_v1 as attester


class Fjord2RetainedCanonicalFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).absolute()
        self.payload = b"retained-canonical-test-payload"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self._create_fixture()

    def _write_json(self, relative: Path, document: dict) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _source_record(self, relative: Path) -> dict:
        path = self.root / relative
        record = attester.stat_record(path.lstat())
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return record

    def _symlink_contract(self, path: Path) -> dict:
        link_st = path.lstat()
        target = path.resolve(strict=True)
        return {
            "workspace_path": str(path),
            "link_text": os.readlink(str(path)),
            "link_lstat": attester.stat_record(link_st),
            "resolved_target": str(target),
            "target_lstat": attester.stat_record(target.lstat()),
        }

    def _create_fixture(self) -> None:
        self.dataset_target = self.root / "dataset-storage"
        self.dataset_target.mkdir()
        (self.root / attester.DATASETS_REL).symlink_to(
            self.dataset_target, target_is_directory=True
        )

        fjord = (
            self.dataset_target
            / "full_downloads/ntnu_hf/subset-fjord/fjord_2"
        )
        fjord.mkdir(parents=True)
        self.target_dir = self.root / "canonical-storage"
        self.target_dir.mkdir()
        self.canonical_target = self.target_dir / "fjord_2.bag"
        self.canonical_target.write_bytes(self.payload)
        self.canonical_link = fjord / "fjord_2.bag"
        self.canonical_link.symlink_to(self.canonical_target)

        for relative in attester.FROZEN_SOURCE_RELS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"synthetic frozen source: {relative.as_posix()}\n",
                encoding="utf-8",
            )

        frozen_sources = {
            relative.as_posix(): self._source_record(relative)
            for relative in attester.FROZEN_SOURCE_RELS
        }
        canonical_contract = {
            "canonical_relative_path": attester.CANONICAL_REL.as_posix(),
            # Preserve the lexical workspace path even though its datasets
            # parent is itself a symlink, matching the production lock.
            "canonical_symlink": self._symlink_contract(
                self.root / attester.CANONICAL_REL
            ),
            "datasets_mount": self._symlink_contract(
                self.root / attester.DATASETS_REL
            ),
            "expected_size_bytes": len(self.payload),
            "official_sha256": self.digest,
            "checksum_authority": "synthetic-checksum-authority.csv",
            "content_sha256_recomputed_for_reclaim": False,
        }
        inventory = {
            "part_count": attester.EXPECTED_PART_COUNT,
            "logical_bytes": len(self.payload),
            "inventory_hash": hashlib.sha256(b"synthetic inventory").hexdigest(),
        }
        lock = {
            "schema": attester.LOCK_SCHEMA,
            "status": attester.LOCK_STATUS,
            "workspace_root": str(self.root),
            "scope": {
                "candidate_relative_path": attester.CANDIDATE_REL.as_posix(),
                "allowed_action": "unlink exact frozen downloader part files and empty dirs only",
            },
            "frozen_state": {
                "canonical_contract": canonical_contract,
                "inventory": inventory,
                "frozen_artifacts": frozen_sources,
            },
            "outcome_boundary": attester.OUTCOME_BOUNDARY,
        }
        lock["reclaim_lock_hash"] = attester.document_self_hash(
            lock, "reclaim_lock_hash"
        )

        intent = {
            "schema": attester.INTENT_SCHEMA,
            "status": attester.INTENT_STATUS,
            "lock_hash": lock["reclaim_lock_hash"],
            "inventory_hash": inventory["inventory_hash"],
            "candidate_relative_path": attester.CANDIDATE_REL.as_posix(),
            "expected_part_count": attester.EXPECTED_PART_COUNT,
            "expected_logical_bytes": len(self.payload),
            "canonical_contract": canonical_contract,
            "outcome_boundary": attester.OUTCOME_BOUNDARY,
        }
        intent["intent_hash"] = attester.document_self_hash(intent, "intent_hash")

        receipt = {
            "schema": attester.RECEIPT_SCHEMA,
            "status": attester.RECEIPT_STATUS,
            "lock_hash": lock["reclaim_lock_hash"],
            "intent_hash": intent["intent_hash"],
            "postcondition": {
                "candidate_absent": True,
                "canonical_contract_unchanged": True,
                "checksum_bindings_unchanged": True,
                "frozen_artifacts_unchanged": True,
                "exact_part_count_unlinked": attester.EXPECTED_PART_COUNT,
                "exact_logical_bytes_unlinked": len(self.payload),
                "intent_hash": intent["intent_hash"],
            },
            "outcome_boundary": attester.OUTCOME_BOUNDARY,
        }
        receipt["receipt_hash"] = attester.document_self_hash(
            receipt, "receipt_hash"
        )

        self.lock = lock
        self.intent = intent
        self.receipt = receipt
        self.expected_formal_self_hashes = {
            "lock": lock["reclaim_lock_hash"],
            "intent": intent["intent_hash"],
            "receipt": receipt["receipt_hash"],
        }
        self.expected_source_sha256 = {
            relative: record["sha256"]
            for relative, record in frozen_sources.items()
        }
        self._write_json(attester.LOCK_REL, lock)
        self._write_json(attester.INTENT_REL, intent)
        self._write_json(attester.RECEIPT_REL, receipt)

    def build(self) -> dict:
        return attester.build_attestation(
            self.root,
            expected_size=len(self.payload),
            expected_sha256=self.digest,
            expected_part_count=attester.EXPECTED_PART_COUNT,
            expected_formal_self_hashes=self.expected_formal_self_hashes,
            expected_source_sha256=self.expected_source_sha256,
        )

    def preflight(self) -> dict:
        return attester.preflight(
            self.root,
            expected_size=len(self.payload),
            expected_sha256=self.digest,
            expected_part_count=attester.EXPECTED_PART_COUNT,
            expected_formal_self_hashes=self.expected_formal_self_hashes,
            expected_source_sha256=self.expected_source_sha256,
        )

    def write(self) -> dict:
        return attester.write_attestation(
            self.root,
            expected_size=len(self.payload),
            expected_sha256=self.digest,
            expected_part_count=attester.EXPECTED_PART_COUNT,
            expected_formal_self_hashes=self.expected_formal_self_hashes,
            expected_source_sha256=self.expected_source_sha256,
        )


class TestFjord2RetainedCanonical(Fjord2RetainedCanonicalFixture):
    def test_preflight_is_read_only_and_preserves_evidence_boundary(self) -> None:
        frozen_before = {
            relative: (self.root / relative).read_bytes()
            for relative in (
                attester.LOCK_REL,
                attester.INTENT_REL,
                attester.RECEIPT_REL,
                *attester.FROZEN_SOURCE_RELS,
            )
        }
        result = self.preflight()
        self.assertEqual(result["status"], "PASS_READ_ONLY_NO_MUTATION")
        self.assertFalse(result["output_written"])
        self.assertFalse(os.path.lexists(self.root / attester.OUTPUT_REL))
        proposal = result["proposed_attestation"]
        boundary = proposal["reclaim_evidence_boundary"]
        self.assertFalse(boundary["parts_combined_sha256"]["available"])
        self.assertIsNone(boundary["parts_combined_sha256"]["value"])
        self.assertFalse(boundary["receipt_proves_byte_identical_redundancy"])
        self.assertTrue(proposal["outcome_blinding"]["outcome_blind"])
        self.assertFalse(
            proposal["outcome_blinding"]["trajectory_artifacts_read"]
        )
        self.assertEqual(
            proposal["retained_canonical"]["sha256"], self.digest
        )
        attester.verify_document_self_hash(
            proposal, "attestation_hash", "synthetic proposal"
        )
        for relative, original in frozen_before.items():
            self.assertEqual((self.root / relative).read_bytes(), original)

    def test_same_size_canonical_content_drift_is_rejected(self) -> None:
        frozen_stat = self.canonical_target.lstat()
        replacement = b"X" * len(self.payload)
        self.assertNotEqual(hashlib.sha256(replacement).hexdigest(), self.digest)
        self.canonical_target.write_bytes(replacement)
        os.utime(
            self.canonical_target,
            ns=(frozen_stat.st_atime_ns, frozen_stat.st_mtime_ns),
        )
        self.assertEqual(
            attester.stat_record(self.canonical_target.lstat()),
            self.lock["frozen_state"]["canonical_contract"]["canonical_symlink"][
                "target_lstat"
            ],
        )
        result = self.preflight()
        self.assertEqual(
            result["status"],
            "FAIL_READ_ONLY_RETAINED_CANONICAL_DIGEST_MISMATCH",
        )
        self.assertFalse(result["assessment_passed"])
        proposal = result["proposed_attestation"]
        self.assertEqual(
            proposal["status"],
            attester.ATTESTATION_DIGEST_MISMATCH_STATUS,
        )
        self.assertFalse(proposal["assessment_passed"])
        self.assertFalse(proposal["retained_canonical"]["sha256_match"])
        self.assertTrue(proposal["integrity_incident"]["present"])
        self.assertFalse(proposal["integrity_incident"]["recovery_attempted"])
        self.assertEqual(
            proposal["retained_canonical"]["expected_sha256"], self.digest
        )
        self.assertNotEqual(
            proposal["retained_canonical"]["sha256"], self.digest
        )
        self.assertFalse(os.path.lexists(self.root / attester.OUTPUT_REL))

    def test_canonical_workspace_symlink_swap_is_rejected(self) -> None:
        alternate = self.target_dir / "alternate.bag"
        alternate.write_bytes(self.payload)
        self.canonical_link.unlink()
        self.canonical_link.symlink_to(alternate)
        with self.assertRaisesRegex(
            attester.AttestationViolation, "canonical symlink"
        ):
            self.build()

    def test_resolved_target_swap_during_hash_is_rejected(self) -> None:
        original_stream = attester._stream_sha256_fd
        target_inode = self.canonical_target.stat().st_ino
        swapped = {"done": False}

        def stream_then_swap(fd: int):
            result = original_stream(fd)
            if os.fstat(fd).st_ino == target_inode and not swapped["done"]:
                replacement = self.target_dir / "replacement.bag"
                replacement.write_bytes(self.payload)
                os.replace(replacement, self.canonical_target)
                swapped["done"] = True
            return result

        with mock.patch.object(
            attester, "_stream_sha256_fd", side_effect=stream_then_swap
        ):
            with self.assertRaisesRegex(
                attester.AttestationViolation,
                "canonical runtime (fstat before/after|path identity after hashing)",
            ):
                self.build()
        self.assertTrue(swapped["done"])

    def test_same_inode_rewrite_after_read_is_rejected_by_ctime(self) -> None:
        original_stream = attester._stream_sha256_fd
        target_inode = self.canonical_target.stat().st_ino
        frozen_stat = self.canonical_target.stat()
        mutated = {"done": False}

        def stream_then_rewrite_in_place(fd: int):
            result = original_stream(fd)
            if os.fstat(fd).st_ino == target_inode and not mutated["done"]:
                # Ensure the synthetic filesystem advances ctime even if its
                # timestamp granularity is coarser than this tiny hash read.
                time.sleep(0.01)
                self.canonical_target.write_bytes(b"Q" * len(self.payload))
                os.utime(
                    self.canonical_target,
                    ns=(frozen_stat.st_atime_ns, frozen_stat.st_mtime_ns),
                )
                mutated["done"] = True
            return result

        with mock.patch.object(
            attester, "_stream_sha256_fd", side_effect=stream_then_rewrite_in_place
        ):
            with self.assertRaisesRegex(
                attester.AttestationViolation,
                "canonical runtime fstat before/after",
            ):
                self.build()
        self.assertTrue(mutated["done"])

    def test_candidate_reappearance_is_rejected(self) -> None:
        candidate = self.root / attester.CANDIDATE_REL
        candidate.mkdir()
        with self.assertRaisesRegex(
            attester.AttestationViolation, "candidate reappeared"
        ):
            self.build()

    def test_formal_document_self_hash_drift_is_rejected(self) -> None:
        drifted = copy.deepcopy(self.receipt)
        drifted["postcondition"]["exact_part_count_unlinked"] += 1
        self._write_json(attester.RECEIPT_REL, drifted)
        with self.assertRaisesRegex(
            attester.AttestationViolation, "receipt self-hash mismatch"
        ):
            self.build()

    def test_recomputed_document_hash_cannot_replace_frozen_identity(self) -> None:
        drifted = copy.deepcopy(self.receipt)
        drifted["created_at_utc"] = "2099-01-01T00:00:00+00:00"
        drifted["receipt_hash"] = attester.document_self_hash(
            drifted, "receipt_hash"
        )
        self._write_json(attester.RECEIPT_REL, drifted)
        with self.assertRaisesRegex(
            attester.AttestationViolation, "frozen receipt identity"
        ):
            self.build()

    def test_frozen_source_hash_drift_is_rejected(self) -> None:
        relative = attester.FROZEN_SOURCE_RELS[0]
        path = self.root / relative
        before = path.lstat()
        original = path.read_bytes()
        drifted = bytes([original[0] ^ 1]) + original[1:]
        path.write_bytes(drifted)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(path.stat().st_size, len(original))
        with self.assertRaisesRegex(
            attester.AttestationViolation, "frozen source SHA-256"
        ):
            self.build()

    def test_atomic_hardlink_publication_is_no_clobber(self) -> None:
        frozen_stat = self.canonical_target.lstat()
        self.canonical_target.write_bytes(b"Z" * len(self.payload))
        os.utime(
            self.canonical_target,
            ns=(frozen_stat.st_atime_ns, frozen_stat.st_mtime_ns),
        )
        payload = self.write()
        output = self.root / attester.OUTPUT_REL
        self.assertTrue(output.is_file())
        self.assertEqual(output.stat().st_nlink, 1)
        self.assertEqual(
            payload["status"], attester.ATTESTATION_DIGEST_MISMATCH_STATUS
        )
        self.assertFalse(payload["assessment_passed"])
        self.assertTrue(payload["integrity_incident"]["present"])
        self.assertFalse(
            payload["integrity_incident"]["prior_lock_intent_receipt_modified"]
        )
        self.assertEqual(
            payload["retained_canonical"]["expected_sha256"], self.digest
        )
        self.assertNotEqual(
            payload["retained_canonical"]["sha256"], self.digest
        )
        observed = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(observed, payload)
        attester.verify_document_self_hash(
            observed, "attestation_hash", "published synthetic attestation"
        )
        temp_names = list(output.parent.glob(f".{output.name}.tmp.*"))
        self.assertEqual(temp_names, [])
        with self.assertRaisesRegex(
            attester.AttestationViolation, "no-clobber destination already exists"
        ):
            self.write()
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)

    def test_default_cli_mode_is_preflight_only(self) -> None:
        parsed = attester.parse_args(["--root", str(self.root)])
        self.assertFalse(parsed.write)
        self.assertFalse(parsed.preflight_only)
        explicit = attester.parse_args(
            ["--root", str(self.root), "--preflight-only"]
        )
        self.assertTrue(explicit.preflight_only)
        self.assertFalse(explicit.write)

    def test_default_cli_digest_mismatch_exits_failure_without_write(self) -> None:
        frozen_stat = self.canonical_target.lstat()
        self.canonical_target.write_bytes(b"M" * len(self.payload))
        os.utime(
            self.canonical_target,
            ns=(frozen_stat.st_atime_ns, frozen_stat.st_mtime_ns),
        )
        # CLI authority constants are production-bound; temporarily bind the
        # synthetic frozen chain exactly as the internal fixture helpers do.
        with mock.patch.object(
            attester,
            "EXPECTED_FORMAL_SELF_HASHES",
            self.expected_formal_self_hashes,
        ), mock.patch.object(
            attester,
            "EXPECTED_FROZEN_SOURCE_SHA256",
            self.expected_source_sha256,
        ), mock.patch.object(
            attester, "EXPECTED_SIZE", len(self.payload)
        ), mock.patch.object(
            attester, "EXPECTED_SHA256", self.digest
        ):
            # Function defaults are bound at definition time, so route main's
            # calls through wrappers carrying the synthetic authority.
            original_preflight = attester.preflight

            def synthetic_preflight(root: Path):
                return original_preflight(
                    root,
                    expected_size=len(self.payload),
                    expected_sha256=self.digest,
                    expected_part_count=attester.EXPECTED_PART_COUNT,
                    expected_formal_self_hashes=self.expected_formal_self_hashes,
                    expected_source_sha256=self.expected_source_sha256,
                )

            stdout = io.StringIO()
            with mock.patch.object(
                attester, "preflight", side_effect=synthetic_preflight
            ), contextlib.redirect_stdout(stdout):
                return_code = attester.main(["--root", str(self.root)])
        self.assertEqual(return_code, 1)
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            result["status"],
            "FAIL_READ_ONLY_RETAINED_CANONICAL_DIGEST_MISMATCH",
        )
        self.assertFalse(os.path.lexists(self.root / attester.OUTPUT_REL))


if __name__ == "__main__":
    unittest.main()
