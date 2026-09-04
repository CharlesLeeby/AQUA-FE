#!/usr/bin/env python3
"""Synthetic, non-production tests for the fjord_2 .parts reclaim protocol."""

from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_p07_fjord2_parts_reclaim_lock_v1 as governance
import reclaim_p07_fjord2_parts_v1 as executor


class Fjord2PartsFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).absolute()
        self.payload = b"0123456789"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.size_patch = mock.patch.object(governance, "EXPECTED_SIZE", len(self.payload))
        self.sha_patch = mock.patch.object(governance, "EXPECTED_SHA256", self.digest)
        self.count_patch = mock.patch.object(governance, "EXPECTED_PART_COUNT", 3)
        self.size_patch.start()
        self.sha_patch.start()
        self.count_patch.start()
        self.addCleanup(self.size_patch.stop)
        self.addCleanup(self.sha_patch.stop)
        self.addCleanup(self.count_patch.stop)
        self.addCleanup(self.temporary.cleanup)
        self._create_fixture()
        self.quiescence_patch = mock.patch.object(
            governance,
            "inspect_quiescence",
            side_effect=lambda _root, _inventory: self.synthetic_quiescence(),
        )
        self.quiescence_patch.start()
        self.addCleanup(self.quiescence_patch.stop)

    def synthetic_quiescence(self) -> dict:
        identities = []
        for pid, comm in enumerate(sorted(governance.ALLOWED_INACCESSIBLE_COMMS), 100):
            identities.append(
                {
                    "pid": pid,
                    "starttime_ticks": 1000 + pid,
                    "ppid": 1,
                    "uid": os.geteuid(),
                    "comm": comm,
                    "comm_sha256": hashlib.sha256((comm + "\n").encode()).hexdigest(),
                    "cmdline_sha256": hashlib.sha256(f"cmd-{comm}".encode()).hexdigest(),
                    "cgroup_sha256": hashlib.sha256(f"cgroup-{comm}".encode()).hexdigest(),
                    "inaccessible_phases": ["fd-list"],
                }
            )
        return {
            "effective_uid": os.geteuid(),
            "same_user_processes_inspected": 3,
            "active_matches": [],
            "inspection_errors": [],
            "inaccessible_process_exceptions": identities,
            "boot_id_sha256": "b" * 64,
            "inaccessible_exception_policy": {
                "allowed_comms": sorted(governance.ALLOWED_INACCESSIBLE_COMMS),
                "identity_fields": list(governance.INACCESSIBLE_IDENTITY_FIELDS),
                "executor_requires_exact_frozen_tuple_set": True,
            },
            "lsof_exact_tree_exit_code": 1,
            "lsof_exact_tree_stdout_lines": [],
            "lsof_warnings": [],
        }

    def _write_csv(self, relative: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _create_fixture(self) -> None:
        storage = self.root / "storage"
        storage.mkdir()
        (self.root / "datasets").symlink_to(storage, target_is_directory=True)

        fjord = storage / "full_downloads/ntnu_hf/subset-fjord/fjord_2"
        part_root = fjord / ".parts/fjord_2.bag"
        part_root.mkdir(parents=True)
        self.parts = [
            ("part_00000_0_3", b"0123"),
            ("part_00001_4_7", b"4567"),
            ("part_00002_8_9", b"89"),
        ]
        for name, payload in self.parts:
            (part_root / name).write_bytes(payload)

        target_dir = self.root / "canonical"
        target_dir.mkdir()
        self.canonical_target = target_dir / "fjord_2.bag"
        self.canonical_target.write_bytes(self.payload)
        fjord.mkdir(parents=True, exist_ok=True)
        (fjord / "fjord_2.bag").symlink_to(self.canonical_target)

        canonical = governance.CANONICAL_REL.as_posix()
        self._write_csv(
            governance.CHECKSUM_REL,
            [
                "checksum_schema",
                "artifact_role",
                "dataset_family",
                "sequence",
                "path",
                "size_bytes",
                "algorithm",
                "digest",
                "digest_origin",
                "local_size_verified",
                "status",
            ],
            [
                {
                    "checksum_schema": "isj-input-reference-checksum-v1",
                    "artifact_role": "raw_input",
                    "dataset_family": "ntnu",
                    "sequence": "fjord_2",
                    "path": canonical,
                    "size_bytes": str(len(self.payload)),
                    "algorithm": "SHA-256",
                    "digest": self.digest,
                    "digest_origin": "official_HuggingFace_LFS_SHA256",
                    "local_size_verified": "true",
                    "status": "PASS",
                }
            ],
        )
        self._write_csv(
            governance.ELIGIBILITY_REL,
            [
                "manifest_schema",
                "dataset_family",
                "sequence",
                "raw_input_path",
                "raw_exists",
                "raw_size_bytes",
                "expected_raw_size_bytes",
                "raw_integrity",
            ],
            [
                {
                    "manifest_schema": "isj-data-eligibility-v1",
                    "dataset_family": "ntnu",
                    "sequence": "fjord_2",
                    "raw_input_path": canonical,
                    "raw_exists": "true",
                    "raw_size_bytes": str(len(self.payload)),
                    "expected_raw_size_bytes": str(len(self.payload)),
                    "raw_integrity": "SIZE_MATCH",
                }
            ],
        )
        self._write_csv(
            governance.REFERENCE_AUDIT_REL,
            [
                "audit_schema",
                "dataset_family",
                "sequence",
                "raw_input_path",
                "raw_exists",
                "raw_size_bytes",
                "raw_integrity",
            ],
            [
                {
                    "audit_schema": "isj-reference-audit-v1",
                    "dataset_family": "ntnu",
                    "sequence": "fjord_2",
                    "raw_input_path": canonical,
                    "raw_exists": "true",
                    "raw_size_bytes": str(len(self.payload)),
                    "raw_integrity": "SIZE_MATCH",
                }
            ],
        )

        for relative in governance.TOOL_RELS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic artifact: {relative.as_posix()}\n", encoding="utf-8")
        (self.root / governance.LOCK_REL.parent.parent).mkdir(parents=True, exist_ok=True)

    @property
    def candidate(self) -> Path:
        return self.root / governance.CANDIDATE_REL

    @property
    def part_root(self) -> Path:
        return self.root / governance.PART_ROOT_REL

    @property
    def lock_path(self) -> Path:
        return self.root / governance.LOCK_REL

    @property
    def intent_path(self) -> Path:
        return self.root / governance.INTENT_REL

    @property
    def receipt_path(self) -> Path:
        return self.root / governance.RECEIPT_REL

    def publish_lock(self) -> dict:
        lock = governance.build_lock(self.root)
        governance.write_formal_lock(self.root, lock)
        return lock


class TestFjord2PartsLock(Fjord2PartsFixture):
    def test_builder_is_read_only_without_explicit_write(self) -> None:
        lock = governance.build_lock(self.root)
        self.assertFalse(os.path.lexists(self.lock_path))
        self.assertEqual(lock["status"], governance.LOCK_STATUS)
        self.assertEqual(lock["frozen_state"]["inventory"]["part_count"], 3)
        self.assertEqual(lock["frozen_state"]["inventory"]["logical_bytes"], 10)
        self.assertEqual(
            lock["pre_freeze_dry_run_scanner_classification_incident"],
            governance.PREFREEZE_SCANNER_CLASSIFICATION_INCIDENT,
        )
        governance.verify_document_self_hash(lock)

    def test_atomic_lock_publish_is_no_clobber(self) -> None:
        lock = governance.build_lock(self.root)
        governance.write_formal_lock(self.root, lock)
        with self.assertRaises(governance.ReclaimViolation):
            governance.write_formal_lock(self.root, lock)

    def test_range_gap_is_rejected(self) -> None:
        old = self.part_root / "part_00001_4_7"
        old.rename(self.part_root / "part_00001_5_7")
        with self.assertRaisesRegex(governance.ReclaimViolation, "range discontinuity"):
            governance.build_lock(self.root)

    def test_extra_candidate_child_is_rejected(self) -> None:
        (self.candidate / "unexpected").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "unexpected children"):
            governance.build_lock(self.root)

    def test_symlink_part_is_rejected(self) -> None:
        part = self.part_root / "part_00002_8_9"
        part.unlink()
        part.symlink_to(self.canonical_target)
        with self.assertRaisesRegex(governance.ReclaimViolation, "not a direct regular file"):
            governance.build_lock(self.root)

    def test_evidence_reference_is_rejected(self) -> None:
        bad = self.root / governance.EVIDENCE_SCAN_REL / "bad_manifest.md"
        bad.write_text(governance.CANDIDATE_REL.as_posix(), encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "referenced by evidence"):
            governance.build_lock(self.root)

    def test_known_outcomes_are_classified_before_read(self) -> None:
        evidence = self.root / governance.EVIDENCE_SCAN_REL
        probe = governance.G0_ACCURACY_PROBE_DIRS[0]
        outcomes = {
            evidence / probe / "common_support_summary.json",
            evidence / probe / "common_support_metrics.csv",
            evidence / probe / "common_grid_audit.csv",
            evidence / probe / "evo_crosscheck.json",
            evidence / probe / "evo_crosscheck/full_evo_ape.log",
            evidence / probe / "evo_crosscheck/reference_segment_000.tum",
            evidence
            / Path("learned_specificity_20260803/analysis-output/analysis-report.md"),
        }
        for path in outcomes:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic outcome; must not be read", encoding="utf-8")
        original = Path.read_bytes

        def forbid_outcome_read(path: Path) -> bytes:
            if path in outcomes:
                raise AssertionError(f"outcome was read: {path}")
            return original(path)

        with mock.patch.object(Path, "read_bytes", new=forbid_outcome_read):
            lock = governance.build_lock(self.root)
        seen = set(
            lock["frozen_state"]["zero_reference_scan"]["excluded_outcome_files_seen"]
        )
        self.assertTrue(
            {path.relative_to(evidence).as_posix() for path in outcomes}.issubset(seen)
        )

    def test_governance_near_outcome_files_is_still_scanned(self) -> None:
        evidence = self.root / governance.EVIDENCE_SCAN_REL
        nearby = (
            evidence / governance.G0_ACCURACY_PROBE_DIRS[0] / "evaluator_attestation.json",
            evidence
            / governance.G0_EVO_RESULT_DIRS[0]
            / "evaluator_attestation.json",
            evidence
            / "ntnu_q_partition_20260805/analysis-output/lineage-audit.json",
        )
        for path in nearby:
            with self.subTest(path=path.as_posix()):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(governance.CANDIDATE_REL.as_posix(), encoding="utf-8")
                with self.assertRaisesRegex(governance.ReclaimViolation, "referenced by evidence"):
                    governance.build_lock(self.root)
                path.unlink()

    def test_unknown_extension_fails_before_read(self) -> None:
        unknown = self.root / governance.EVIDENCE_SCAN_REL / "synthetic.xml"
        unknown.write_text(governance.CANDIDATE_REL.as_posix(), encoding="utf-8")
        original = Path.read_bytes

        def forbid_unknown_read(path: Path) -> bytes:
            if path == unknown:
                raise AssertionError("unknown type was read")
            return original(path)

        with mock.patch.object(Path, "read_bytes", new=forbid_unknown_read):
            with self.assertRaisesRegex(governance.ReclaimViolation, "unclassified"):
                governance.build_lock(self.root)

    def test_generic_text_and_no_trajectory_manifest_are_scanned(self) -> None:
        evidence = self.root / governance.EVIDENCE_SCAN_REL
        for name in (
            "generic.json",
            "generic.log",
            "generic.csv",
            "generic.py",
            "suffixless_manifest",
            "no_trajectory_manifest.json",
        ):
            with self.subTest(name=name):
                bad = evidence / name
                bad.write_text(governance.CANDIDATE_REL.as_posix(), encoding="utf-8")
                with self.assertRaisesRegex(governance.ReclaimViolation, "referenced by evidence"):
                    governance.build_lock(self.root)
                bad.unlink()

    def test_other_capacity_recovery_lock_is_not_excluded(self) -> None:
        other = self.root / governance.CAPACITY_EVIDENCE_REL / "other_reclaim_lock.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text(governance.CANDIDATE_REL.as_posix(), encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "referenced by evidence"):
            governance.build_lock(self.root)

    def test_exact_part_basename_reference_is_rejected(self) -> None:
        bad = self.root / governance.EVIDENCE_SCAN_REL / "generic.json"
        bad.write_text(self.parts[1][0], encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "referenced by evidence"):
            governance.build_lock(self.root)

    def test_relevant_symlink_and_unreadable_file_fail_closed(self) -> None:
        evidence = self.root / governance.EVIDENCE_SCAN_REL
        target = self.root / "target.json"
        target.write_text("{}", encoding="utf-8")
        linked = evidence / "generic.json"
        linked.symlink_to(target)
        with self.assertRaisesRegex(governance.ReclaimViolation, "symlink"):
            governance.build_lock(self.root)
        linked.unlink()

        unreadable = evidence / "generic.log"
        unreadable.write_text("safe", encoding="utf-8")
        original = Path.read_bytes

        def synthetic_denial(path: Path) -> bytes:
            if path == unreadable:
                raise PermissionError("synthetic unreadable evidence")
            return original(path)

        with mock.patch.object(Path, "read_bytes", new=synthetic_denial):
            with self.assertRaisesRegex(governance.ReclaimViolation, "cannot scan"):
                governance.build_lock(self.root)

    def test_unallowlisted_accuracy_candidate_fails_without_reading(self) -> None:
        candidate = self.root / governance.EVIDENCE_SCAN_REL / "new/evo_crosscheck/result.log"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("must not be read", encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "new governance"):
            governance.build_lock(self.root)

    def test_exact_part_count_is_required(self) -> None:
        (self.part_root / self.parts[-1][0]).unlink()
        with self.assertRaisesRegex(governance.ReclaimViolation, "part-count mismatch"):
            governance.build_lock(self.root)

    def test_build_requires_all_formal_artifacts_absent(self) -> None:
        for relative in governance.FORMAL_RELS:
            with self.subTest(relative=relative.as_posix()):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("collision", encoding="utf-8")
                with self.assertRaisesRegex(governance.ReclaimViolation, "must all be absent"):
                    governance.build_lock(self.root)
                path.unlink()

    def test_rehashed_semantic_tampering_is_rejected(self) -> None:
        base = governance.build_lock(self.root)
        variants = []
        value = copy.deepcopy(base)
        value["scope"]["allowed_action"] = "delete anything"
        variants.append(("action", value))
        value = copy.deepcopy(base)
        value["outcome_boundary"] = "ACCURACY_ALLOWED"
        variants.append(("outcome", value))
        value = copy.deepcopy(base)
        value["frozen_state"]["inventory"]["part_count"] = 2
        variants.append(("count", value))
        value = copy.deepcopy(base)
        value["frozen_state"]["inventory"]["logical_bytes"] = 9
        variants.append(("bytes", value))
        value = copy.deepcopy(base)
        value["frozen_state"]["canonical_contract"]["official_sha256"] = "0" * 64
        variants.append(("checksum", value))
        value = copy.deepcopy(base)
        value["execution_contract"]["require_exact_lock_semantics"] = False
        variants.append(("requirement", value))
        value = copy.deepcopy(base)
        value["formal_paths"]["intent"] = "wrong.json"
        variants.append(("formal_path", value))
        value = copy.deepcopy(base)
        value["pre_freeze_dry_run_scanner_classification_incident"][
            "values_surfaced"
        ] = True
        variants.append(("incident", value))
        for label, tampered in variants:
            with self.subTest(label=label):
                tampered[governance.SELF_HASH_FIELD] = governance.document_self_hash(tampered)
                with self.assertRaises(governance.ReclaimViolation):
                    governance.validate_lock_semantics(self.root, tampered)

    def test_publication_race_never_unlinks_winner(self) -> None:
        relative = Path("papers/ieee_sensors_journal_experiments/p07/race.json")
        destination = self.root / relative

        def competing_link(_src: str, dst: str, **kwargs: object) -> None:
            fd = os.open(
                dst,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o444,
                dir_fd=int(kwargs["dst_dir_fd"]),
            )
            try:
                os.write(fd, b"winner")
                os.fsync(fd)
            finally:
                os.close(fd)
            raise FileExistsError("synthetic publication race")

        with mock.patch.object(governance.os, "link", side_effect=competing_link):
            with self.assertRaisesRegex(governance.ReclaimViolation, "publication race"):
                governance.atomic_no_clobber_json(self.root, relative, {"loser": True})
        self.assertEqual(destination.read_bytes(), b"winner")

    def test_parent_fsync_failure_preserves_published_destination(self) -> None:
        relative = Path("papers/ieee_sensors_journal_experiments/p07/fsync.json")
        destination = self.root / relative
        real_fsync = governance.os.fsync
        raised = False

        def fail_first_directory_fsync(fd: int) -> None:
            nonlocal raised
            if stat.S_ISDIR(os.fstat(fd).st_mode) and not raised:
                raised = True
                raise OSError("synthetic parent fsync failure")
            real_fsync(fd)

        with mock.patch.object(governance.os, "fsync", side_effect=fail_first_directory_fsync):
            with self.assertRaisesRegex(OSError, "synthetic parent fsync failure"):
                governance.atomic_no_clobber_json(self.root, relative, {"durable": True})
        self.assertTrue(destination.is_file())
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"durable": True})
        self.assertEqual(list(destination.parent.glob(f".{destination.name}.tmp.*")), [])

    def test_formal_parent_symlink_and_missing_ancestor_are_rejected(self) -> None:
        lock = governance.build_lock(self.root)
        external = self.root / "external"
        external.mkdir()
        formal_parent = self.root / governance.LOCK_REL.parent
        formal_parent.symlink_to(external, target_is_directory=True)
        with self.assertRaises(governance.ReclaimViolation):
            governance.write_formal_lock(self.root, lock)
        self.assertFalse((external / governance.LOCK_REL.name).exists())
        formal_parent.unlink()

        p07 = self.root / governance.LOCK_REL.parent.parent
        p07.rmdir()
        with self.assertRaises(FileNotFoundError):
            governance.write_formal_lock(self.root, lock)
        self.assertFalse(p07.exists())

    def test_formal_publication_lock_symlink_is_rejected(self) -> None:
        lock = governance.build_lock(self.root)
        formal_parent = self.root / governance.LOCK_REL.parent
        formal_parent.mkdir()
        external = self.root / "external-lock-target"
        external.write_text("unchanged", encoding="utf-8")
        (formal_parent / governance.FORMAL_ACTION_LOCK_NAME).symlink_to(external)
        with self.assertRaises(OSError):
            governance.write_formal_lock(self.root, lock)
        self.assertEqual(external.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse(self.lock_path.exists())

    def test_active_downloader_is_rejected(self) -> None:
        with mock.patch.object(
            governance,
            "inspect_quiescence",
            side_effect=governance.ReclaimViolation("synthetic active downloader"),
        ):
            with self.assertRaisesRegex(governance.ReclaimViolation, "active downloader"):
                governance.build_lock(self.root)

    def test_non_allowlisted_inaccessible_process_is_fatal(self) -> None:
        proc = self.root / "fake-proc/999"
        proc.mkdir(parents=True)
        fields = ["S", "1", *("0" for _ in range(17)), "1234"]
        (proc / "stat").write_text(f"999 (unknown) {' '.join(fields)}\n", encoding="utf-8")
        (proc / "comm").write_text("unknown\n", encoding="utf-8")
        (proc / "cmdline").write_bytes(b"unknown\0")
        (proc / "cgroup").write_text("0::/synthetic\n", encoding="utf-8")
        uid = os.geteuid()
        (proc / "status").write_text(
            f"Name:\tunknown\nPPid:\t1\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(governance.ReclaimViolation, "not allowlisted"):
            governance._proc_identity_exception(proc, 999, uid, ["fd-list"])


class TestFjord2PartsExecutor(Fjord2PartsFixture):
    def test_default_preflight_is_read_only(self) -> None:
        lock = self.publish_lock()
        result = executor.preflight(self.root)
        self.assertEqual(result["status"], "PASS_READ_ONLY_NO_MUTATION")
        self.assertEqual(result["lock_hash"], lock[governance.SELF_HASH_FIELD])
        self.assertTrue(self.candidate.is_dir())
        self.assertFalse(os.path.lexists(self.intent_path))
        self.assertFalse(os.path.lexists(self.receipt_path))

    def test_success_orders_intent_before_unlink_and_writes_pass_receipt(self) -> None:
        lock = self.publish_lock()
        observed_intent = []
        original = executor.unlink_part

        def checking_unlink(name: str, directory_fd: int) -> None:
            observed_intent.append(self.intent_path.is_file())
            original(name, directory_fd)

        with mock.patch.object(executor, "unlink_part", side_effect=checking_unlink):
            receipt = executor.execute(self.root)

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(observed_intent, [True, True, True])
        self.assertFalse(os.path.lexists(self.candidate))
        self.assertEqual(self.canonical_target.read_bytes(), self.payload)
        self.assertTrue(self.intent_path.is_file())
        self.assertTrue(self.receipt_path.is_file())
        on_disk = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["postcondition"]["exact_part_count_unlinked"], 3)
        self.assertEqual(on_disk["postcondition"]["exact_logical_bytes_unlinked"], 10)
        self.assertEqual(on_disk["lock_hash"], lock[governance.SELF_HASH_FIELD])
        governance.verify_document_self_hash(on_disk, "receipt_hash")

    def test_part_inode_drift_blocks_before_intent(self) -> None:
        self.publish_lock()
        part = self.part_root / self.parts[0][0]
        payload = part.read_bytes()
        part.unlink()
        part.write_bytes(payload)
        with self.assertRaisesRegex(governance.ReclaimViolation, "inventory"):
            executor.execute(self.root)
        self.assertFalse(os.path.lexists(self.intent_path))

    def test_frozen_tool_hash_drift_blocks_before_intent(self) -> None:
        self.publish_lock()
        tool = self.root / governance.TOOL_RELS[1]
        tool.write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "frozen tool hashes"):
            executor.execute(self.root)
        self.assertFalse(os.path.lexists(self.intent_path))

    def test_inaccessible_process_tuple_drift_or_addition_blocks(self) -> None:
        self.publish_lock()
        for mode in ("drift", "addition"):
            current = self.synthetic_quiescence()
            if mode == "drift":
                current["inaccessible_process_exceptions"][0]["starttime_ticks"] += 1
            else:
                extra = copy.deepcopy(current["inaccessible_process_exceptions"][0])
                extra["pid"] = 999
                extra["comm"] = "unexpected"
                current["inaccessible_process_exceptions"].append(extra)
            with self.subTest(mode=mode), mock.patch.object(
                governance, "inspect_quiescence", return_value=current
            ):
                with self.assertRaisesRegex(
                    governance.ReclaimViolation, "inaccessible-process exception tuples"
                ):
                    executor.preflight(self.root)

    def test_intent_reachability_is_rechecked_immediately_before_unlink(self) -> None:
        self.publish_lock()
        original = executor.revalidate_locked_state
        calls = 0

        def swap_after_second(root: Path, lock: dict) -> dict:
            nonlocal calls
            calls += 1
            result = original(root, lock)
            if calls == 2:
                self.intent_path.unlink()
                self.intent_path.write_text("swapped", encoding="utf-8")
            return result

        with mock.patch.object(
            executor, "revalidate_locked_state", side_effect=swap_after_second
        ):
            with self.assertRaises(governance.ReclaimViolation):
                executor.execute(self.root)
        self.assertTrue(self.candidate.is_dir())
        self.assertFalse(self.receipt_path.exists())

    def test_formal_parent_swap_during_intent_publication_blocks_unlink(self) -> None:
        self.publish_lock()
        original = governance._assert_publication_reachable
        formal_parent = self.root / governance.LOCK_REL.parent
        displaced = formal_parent.with_name("capacity_recovery_displaced")
        external = self.root / "replacement-capacity"
        external.mkdir()
        swapped = False

        def swap_then_check(
            root: Path, relative: Path, parent_fd: int, record: dict
        ) -> None:
            nonlocal swapped
            if relative == governance.INTENT_REL and not swapped:
                formal_parent.rename(displaced)
                formal_parent.symlink_to(external, target_is_directory=True)
                swapped = True
            original(root, relative, parent_fd, record)

        with mock.patch.object(
            governance, "_assert_publication_reachable", side_effect=swap_then_check
        ), mock.patch.object(executor, "unlink_part") as unlink_mock:
            with self.assertRaises(governance.ReclaimViolation):
                executor.execute(self.root)
        unlink_mock.assert_not_called()
        self.assertTrue(self.candidate.is_dir())

    def test_executor_action_lock_symlink_is_rejected(self) -> None:
        self.publish_lock()
        external = self.root / "external-action-target"
        external.write_text("unchanged", encoding="utf-8")
        action = self.lock_path.parent / executor.ACTION_LOCK_NAME
        action.symlink_to(external)
        with self.assertRaises(OSError):
            executor.execute(self.root)
        self.assertEqual(external.read_text(encoding="utf-8"), "unchanged")
        self.assertTrue(self.candidate.is_dir())
        self.assertFalse(self.intent_path.exists())

    def test_existing_intent_blocks_retry_before_inventory_validation(self) -> None:
        self.publish_lock()
        self.intent_path.write_text("synthetic collision\n", encoding="utf-8")
        part = self.part_root / self.parts[0][0]
        part.unlink()
        with self.assertRaisesRegex(governance.ReclaimViolation, "automatic retry"):
            executor.execute(self.root)

    def test_existing_receipt_blocks_execution(self) -> None:
        self.publish_lock()
        self.receipt_path.write_text("synthetic collision\n", encoding="utf-8")
        with self.assertRaisesRegex(governance.ReclaimViolation, "receipt already exists"):
            executor.execute(self.root)
        self.assertTrue(self.candidate.is_dir())

    def test_mid_delete_failure_leaves_intent_and_no_receipt(self) -> None:
        self.publish_lock()
        original = executor.unlink_part
        calls = 0

        def fail_second(name: str, directory_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic unlink failure")
            original(name, directory_fd)

        with mock.patch.object(executor, "unlink_part", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "synthetic unlink failure"):
                executor.execute(self.root)
        self.assertTrue(self.intent_path.is_file())
        self.assertFalse(os.path.lexists(self.receipt_path))
        with self.assertRaisesRegex(governance.ReclaimViolation, "automatic retry"):
            executor.execute(self.root)

    def test_canonical_target_drift_blocks_before_intent(self) -> None:
        self.publish_lock()
        self.canonical_target.write_bytes(b"changed-size")
        with self.assertRaisesRegex(governance.ReclaimViolation, "target size mismatch"):
            executor.execute(self.root)
        self.assertFalse(os.path.lexists(self.intent_path))

    def test_lock_self_hash_tamper_is_rejected(self) -> None:
        self.publish_lock()
        lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        lock["status"] = "TAMPERED"
        self.lock_path.unlink()
        self.lock_path.write_text(json.dumps(lock), encoding="utf-8")
        with self.assertRaises(governance.ReclaimViolation):
            executor.preflight(self.root)

    def test_cli_default_does_not_execute(self) -> None:
        self.publish_lock()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = executor.main(["--root", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertIn("PASS_READ_ONLY_NO_MUTATION", output.getvalue())
        self.assertTrue(self.candidate.is_dir())


if __name__ == "__main__":
    unittest.main()
