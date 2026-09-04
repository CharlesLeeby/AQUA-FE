from __future__ import annotations

import errno
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import materialize_a08_history_matched_controls_v1_raw as module


class MaterializeA08HistoryMatchedRawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = module.derive_contract()

    def test_frozen_contract_and_support(self) -> None:
        contract = self.contract
        self.assertEqual(contract["selected_camera_count"], 4661)
        self.assertEqual(contract["selected_imu_count"], 46631)
        self.assertEqual(contract["selected_gt_count"], 226)
        self.assertEqual(contract["selected_camera_first_ns"], module.START_NS)
        self.assertEqual(contract["selected_camera_last_ns"], module.END_NS)
        self.assertEqual(len(contract["support_gt_indices"]), 32)
        self.assertNotIn(4400, contract["support_gt_indices"])
        self.assertNotIn(4640, contract["support_gt_indices"])

    def test_converter_command_is_full_history_raw_time(self) -> None:
        command = module.converter_command(Path("/tmp/a08.bag"))
        self.assertIn("--start-index", command)
        self.assertEqual(command[command.index("--start-index") + 1], "0")
        self.assertEqual(command[command.index("--end-index") + 1], "4660")
        self.assertEqual(command[command.index("--imu-margin-s") + 1], "0.25")
        self.assertNotIn("53694112", " ".join(command))

    def test_exact_ns_rejects_invalid_ros_stamp(self) -> None:
        stamp = types.SimpleNamespace(secs=1, nsecs=2)
        self.assertEqual(module.exact_ns(stamp), 1_000_000_002)
        with self.assertRaisesRegex(module.MaterializationError, "ROS_STAMP_RANGE"):
            module.exact_ns(types.SimpleNamespace(secs=1, nsecs=1_000_000_000))

    def test_exclusive_claim_cannot_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claim.json"
            module.write_json_exclusive(path, {"attempt": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["attempt"], 1)
            with self.assertRaises(FileExistsError):
                module.write_json_exclusive(path, {"attempt": 2})

    def test_atomic_directory_publish_cannot_replace_competing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "ours").write_text("ours", encoding="utf-8")
            (destination / "theirs").write_text("theirs", encoding="utf-8")
            with self.assertRaisesRegex(
                module.MaterializationError, "DESTINATION_ALREADY_EXISTS_AT_PUBLISH"
            ):
                module.rename_noreplace(source, destination)
            self.assertEqual((destination / "theirs").read_text(encoding="utf-8"), "theirs")
            self.assertTrue((source / "ours").is_file())

    def test_publication_ancestor_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            link = root / "link"
            real.mkdir()
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(
                module.MaterializationError, "OUTPUT_ANCESTOR_SYMLINK"
            ):
                module.require_no_symlink_ancestors(link / "raw")

    def test_limited_filesystem_fallback_publishes_receipt_last_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "bag").write_text("payload", encoding="utf-8")
            receipt_name = "receipt.json"
            (source / receipt_name).write_text("{}\n", encoding="utf-8")
            with patch.object(
                module,
                "rename_noreplace",
                side_effect=OSError(errno.EINVAL, "unsupported flag"),
            ):
                module.publish_directory_noreplace(source, destination, receipt_name)
            self.assertFalse(source.exists())
            self.assertEqual((destination / "bag").read_text(encoding="utf-8"), "payload")
            self.assertEqual((destination / receipt_name).read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
