from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import reclaim_p07_raw_cache_v1 as reclaim


class P07RawCacheReclamationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.raw = self.root / "datasets/aqualoc/rosbags/harbor01_0_10.bag"
        self.source = self.root / "datasets/full_downloads/aqualoc/harbor_sequence_01_raw_data.tar.gz"
        self.raw.parent.mkdir(parents=True)
        self.source.parent.mkdir(parents=True)
        self.raw.write_bytes(b"derived-window-cache\n")
        self.source.write_bytes(b"immutable-source-archive\n")

        bundle = self.root / "papers/ieee_sensors_journal_experiments"
        p07 = bundle / "p07"
        attempts = p07 / "frontend_attempts"
        attempts.mkdir(parents=True)
        self.queue_rows = []
        self.allocation_rows = []
        self.registry_rows = []
        arms = [reclaim.ARM_B1, reclaim.ARM_M, reclaim.ARM_P]
        for queue_index, arm in zip((7, 8, 9), arms):
            tag = f"fixture_{queue_index}"
            run_id = f"fixture-run-{queue_index}"
            attempt = attempts / f"queue_{queue_index:03d}_{tag}"
            attempt.mkdir()
            (attempt / "command.log").write_text(
                f"run_dir=/tmp/fixture-{queue_index}\n"
                + ("images=21 imu=42 gt=3\n" if queue_index == 7 else "")
                + f"raw_bag={self.raw}\n"
                + f"raw_bag={self.raw}\n",
                encoding="utf-8",
            )
            (attempt / "audit_v3.json").write_text(
                json.dumps(
                    {
                        "schema_version": "isj-p07-frontend-export-audit-v3",
                        "status": "PASS",
                        "window_id": "aqualoc_harbor:H01:0001",
                        "queue_index": queue_index,
                        "run_id": run_id,
                        "arm": arm,
                        "held_out_trajectory_outcome_read": False,
                        "forbidden_outcome_artifacts": [],
                    }
                ),
                encoding="utf-8",
            )
            self.queue_rows.append(
                {
                    "queue_index": str(queue_index),
                    "window_id": "aqualoc_harbor:H01:0001",
                    "arm": arm,
                    "tag": tag,
                }
            )
            self.allocation_rows.append(
                {
                    "queue_index": str(queue_index),
                    "window_id": "aqualoc_harbor:H01:0001",
                    "run_id": run_id,
                    "dataset_family": "aqualoc_harbor",
                    "sequence": "H01",
                    "window_start": "0",
                    "window_end": "10",
                }
            )
            self.registry_rows.append(
                {
                    "run_id": run_id,
                    "registry_event_id": f"{run_id}_e00",
                    "supersedes_event_id": "",
                    "status": "COMPLETED",
                    "protocol_version": "fixture",
                    "method_profile": arm,
                    "stage": "P07_FRONTEND_EXPORT",
                    "dataset_family": "aqualoc_harbor",
                    "sequence": "H01",
                    "window_start": "0",
                    "window_end": "10",
                    "arm": arm,
                    "frontend_seed": "0",
                    "backend_replay": "b00",
                }
            )

        self._write_csv(
            p07 / "frontend_export_queue_v1.csv",
            self.queue_rows,
        )
        self._write_csv(
            p07 / "frontend_run_allocation_v1.csv",
            self.allocation_rows,
        )
        self._write_csv(bundle / "run_registry.csv", self.registry_rows)
        self._write_csv(
            bundle / "dataset_manifest_v4.csv",
            [
                {
                    "window_id": "aqualoc_harbor:H01:0001",
                    "dataset_family": "aqualoc_harbor",
                    "sequence": "H01",
                    "window_start_s": "0",
                    "window_end_s": "10",
                }
            ],
        )
        self._write_csv(
            bundle / "data_eligibility_manifest.csv",
            [
                {
                    "dataset_family": "aqualoc_harbor",
                    "sequence": "H01",
                    "raw_input_path": reclaim.display_path(self.root, self.source),
                    "raw_exists": "true",
                }
            ],
        )
        d_evidence = p07 / "d_resolutions/h01_0001.json"
        d_evidence.parent.mkdir()
        d_evidence.write_text(
            json.dumps(
                {
                    "window_id": "aqualoc_harbor:H01:0001",
                    "status": "PASS_NOT_APPLICABLE",
                    "held_out_trajectory_outcome_read": False,
                }
            ),
            encoding="utf-8",
        )
        self._write_csv(
            bundle / "arm_applicability.csv",
            [
                {
                    "dataset_family": "aqualoc_harbor",
                    "sequence": "H01",
                    "window_start": "0",
                    "window_end": "10",
                    "proposed_arm": reclaim.ARM_P,
                    "drop_arm": "D_legacy_exact_lineage_drop_v3",
                    "resolution": "NOT_APPLICABLE",
                    "evidence_path": reclaim.display_path(self.root, d_evidence),
                }
            ],
        )
        checksum_path = bundle / "dataset_checksum_manifest.txt"
        checksum_path.write_text(
            f"{hashlib.sha256(self.source.read_bytes()).hexdigest()}  {reclaim.display_path(self.root, self.source)}\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0])
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_default_is_read_only_dry_run(self) -> None:
        report = reclaim.run(self.root)
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(
            report["candidates"][0]["command_log_counts"],
            {"gt": 3, "images": 21, "imu": 42},
        )
        evidence = set(report["candidates"][0]["evidence_paths"])
        self.assertIn("papers/ieee_sensors_journal_experiments/run_registry.csv", evidence)
        self.assertIn("papers/ieee_sensors_journal_experiments/arm_applicability.csv", evidence)
        self.assertIn(
            "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
            evidence,
        )
        self.assertEqual(sum(path.endswith("audit_v3.json") for path in evidence), 3)
        self.assertTrue(self.raw.is_file())
        self.assertFalse((self.root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation").exists())

    def test_execute_receipt_precedes_unlink_and_ledger_is_self_contained(self) -> None:
        report = reclaim.run(self.root, execute=True)
        self.assertEqual(report["mode"], "EXECUTE")
        self.assertFalse(self.raw.exists())
        reclaim_dir = self.root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
        receipts = [path for path in reclaim_dir.glob("receipt-*.json")]
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "AUTHORIZED_BEFORE_UNLINK")
        ledger = self.root / "papers/ieee_sensors_journal_experiments/execution_ledger.jsonl"
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "RAW_CACHE_RECLAIMED")
        self.assertTrue(events[0]["self_contained"])
        self.assertEqual(events[0]["raw_cache_sha256"], receipt["raw_cache_sha256"])

    def test_hash_manifest_reference_blocks_candidate(self) -> None:
        manifest = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_007_fixture_7/output_hash_manifest.sha256"
        )
        manifest.write_text(
            f"{hashlib.sha256(self.raw.read_bytes()).hexdigest()}  {reclaim.display_path(self.root, self.raw)}\n",
            encoding="utf-8",
        )
        report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertTrue(any("hash manifest" in reason for reason in report["rejected"][0]["reasons"]))
        self.assertTrue(self.raw.exists())

    def test_nonterminal_arm_blocks_candidate(self) -> None:
        registry = self.root / "papers/ieee_sensors_journal_experiments/run_registry.csv"
        rows = list(csv.DictReader(registry.read_text(encoding="utf-8").splitlines()))
        rows[0]["status"] = "RUNNING"
        self._write_csv(registry, [dict(row) for row in rows])
        report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertIn("COMPLETED", report["rejected"][0]["reasons"][0])
        self.assertTrue(self.raw.exists())

    def test_outside_cache_path_is_rejected(self) -> None:
        outside = self.root / "outside.bag"
        outside.write_bytes(b"outside")
        log = self.root / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_007_fixture_7/command.log"
        log.write_text(f"raw_bag={outside}\n", encoding="utf-8")
        report = reclaim.run(self.root)
        self.assertTrue(
            any(
                "outside" in reason
                for item in report["rejected"]
                for reason in item["reasons"]
            )
        )
        self.assertTrue(outside.exists())

    def test_early_queue_binding_is_never_reclaimable(self) -> None:
        early = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_001_early"
        )
        early.mkdir()
        (early / "command.log").write_text(f"raw_bag={self.raw}\n", encoding="utf-8")
        report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertTrue(
            any(
                "q1-6" in reason
                for item in report["rejected"]
                for reason in item["reasons"]
            )
        )
        self.assertTrue(self.raw.exists())

    def test_malformed_ledger_blocks_before_receipt_or_unlink(self) -> None:
        ledger = self.root / "papers/ieee_sensors_journal_experiments/execution_ledger.jsonl"
        ledger.write_text("not-json\n", encoding="utf-8")
        report = reclaim.run(self.root, execute=True)
        self.assertTrue(self.raw.exists())
        self.assertEqual(report["executed"], [])
        self.assertIn("invalid execution ledger", report["execution_errors"][0]["reason"])
        reclaim_dir = self.root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
        self.assertEqual(list(reclaim_dir.glob("receipt-*.json")), [])

    def test_receipt_is_fsynced_before_unlink_attempt_and_failure_is_not_ledgered(self) -> None:
        real_unlink = reclaim.os.unlink

        def fail_target(path: str | bytes) -> None:
            if Path(path) == self.raw:
                reclaim_dir = (
                    self.root
                    / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
                )
                self.assertEqual(len(list(reclaim_dir.glob("receipt-*.json"))), 1)
                raise OSError("fixture unlink failure")
            real_unlink(path)

        with mock.patch.object(reclaim.os, "unlink", side_effect=fail_target):
            report = reclaim.run(self.root, execute=True)
        self.assertTrue(self.raw.exists())
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("fixture unlink failure", report["execution_errors"][0]["reason"])
        ledger = self.root / "papers/ieee_sensors_journal_experiments/execution_ledger.jsonl"
        self.assertEqual(ledger.read_bytes(), b"")

    def test_incomplete_triplet_is_rejected(self) -> None:
        log = (
            self.root
            / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_009_fixture_9/command.log"
        )
        log.write_text("run_dir=/tmp/fixture-9\n", encoding="utf-8")
        report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertTrue(
            any(
                "exactly one three-arm triplet" in reason
                for item in report["rejected"]
                for reason in item["reasons"]
            )
        )
        self.assertTrue(self.raw.exists())

    def test_future_allocation_for_same_cache_blocks_reclamation(self) -> None:
        bundle = self.root / "papers/ieee_sensors_journal_experiments"
        self.queue_rows.append(
            {
                "queue_index": "10",
                "window_id": "aqualoc_harbor:H01:future",
                "arm": reclaim.ARM_B1,
                "tag": "future",
            }
        )
        self.allocation_rows.append(
            {
                "queue_index": "10",
                "window_id": "aqualoc_harbor:H01:future",
                "run_id": "future-run",
                "dataset_family": "aqualoc_harbor",
                "sequence": "H01",
                "window_start": "0",
                "window_end": "10",
            }
        )
        self._write_csv(bundle / "p07/frontend_export_queue_v1.csv", self.queue_rows)
        self._write_csv(bundle / "p07/frontend_run_allocation_v1.csv", self.allocation_rows)
        report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertTrue(
            any(
                "future allocation" in reason
                for item in report["rejected"]
                for reason in item["reasons"]
            )
        )
        self.assertTrue(self.raw.exists())

    def test_active_process_reference_is_rejected(self) -> None:
        with mock.patch.object(
            reclaim,
            "_active_processes_for_path",
            return_value=[{"pid": 4242, "evidence": ["open_file_descriptor"], "command": "producer"}],
        ):
            report = reclaim.run(self.root)
        self.assertEqual(report["candidates"], [])
        self.assertIn("active process", report["rejected"][0]["reasons"][0])
        self.assertTrue(self.raw.exists())

    def test_hash_change_between_scan_and_execute_is_fail_closed(self) -> None:
        candidates, rejections = reclaim.discover_candidates(self.root)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(rejections, [])
        self.raw.write_bytes(b"changed-after-scan\n")
        with self.assertRaises(reclaim.ReclamationError):
            reclaim._execute_candidate(self.root, candidates[0], {})
        self.assertTrue(self.raw.exists())
        reclaim_dir = self.root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
        self.assertFalse(list(reclaim_dir.glob("receipt-*.json")))

    def test_receipt_name_collision_never_clobbers_existing_receipt(self) -> None:
        candidates, _rejections = reclaim.discover_candidates(self.root)
        candidate = candidates[0]
        reclaim_dir = self.root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
        receipt = reclaim_dir / f"receipt-{candidate.sha256[:16]}-deadbeefdeadbeef.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("sentinel\n", encoding="utf-8")
        with mock.patch.object(reclaim.secrets, "token_hex", return_value="deadbeefdeadbeef"):
            report = reclaim.run(self.root, execute=True)
        self.assertTrue(self.raw.exists())
        self.assertEqual(report["executed"], [])
        self.assertIn("existing reclamation receipt", report["execution_errors"][0]["reason"])
        self.assertEqual(receipt.read_text(encoding="utf-8"), "sentinel\n")


if __name__ == "__main__":
    unittest.main()
