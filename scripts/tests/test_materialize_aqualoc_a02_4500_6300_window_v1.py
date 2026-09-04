from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts import export_aqualoc_a02_shared_4500_6300_v1 as SHARED


SCRIPT = Path(__file__).resolve().parents[1] / "materialize_aqualoc_a02_4500_6300_window_v1.py"
SPEC = importlib.util.spec_from_file_location("a02_window", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MaterializeA02WindowTests(unittest.TestCase):
    def test_converter_command_freezes_inclusive_window_and_topics(self) -> None:
        output = Path("/tmp/unique-a02-window.bag")
        command = MODULE.converter_command(output)
        self.assertEqual(command[command.index("--start-index") + 1], "4500")
        self.assertEqual(command[command.index("--end-index") + 1], "6300")
        self.assertEqual(command[command.index("--imu-margin-s") + 1], "0.25")
        self.assertEqual(command[command.index("--image-topic") + 1], MODULE.CAMERA_TOPIC)
        self.assertEqual(command[command.index("--imu-topic") + 1], MODULE.IMU_TOPIC)
        self.assertEqual(command[command.index("--gt-topic") + 1], MODULE.GT_TOPIC)

    def test_expected_counts_and_boundaries_are_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_TOPIC_COUNTS, {
            "/camera/image_raw": 1801,
            "/rtimulib_node/imu": 18084,
            "/aqualoc/colmap_gt": 91,
        })
        self.assertEqual(MODULE.EXPECTED_IMU_FIRST_NS, 1542829016456083680)
        self.assertEqual(MODULE.EXPECTED_IMU_LAST_NS, 1542829106933121504)
        self.assertEqual(MODULE.HFNET_INNER_IMU_COUNT, 17987)
        self.assertEqual(MODULE.EXPECTED_CAMERA_NS[900], 1542829061692686528)
        self.assertLess(MODULE.EXPECTED_CAMERA_NS[0], MODULE.EXPECTED_CAMERA_NS[900])
        self.assertLess(MODULE.EXPECTED_CAMERA_NS[900], MODULE.EXPECTED_CAMERA_NS[1800])

    def test_manifest_shape_matches_shared_consumer_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "window.bag"
            output.write_bytes(b"sealed-test-bag")
            audit = {
                "topic_counts": dict(MODULE.EXPECTED_TOPIC_COUNTS),
                "topic_first_header_ns": {},
                "topic_last_header_ns": {},
            }
            identities = {
                "raw_tar": {"path": "raw", "size_bytes": MODULE.RAW_TAR_SIZE, "sha256": MODULE.RAW_TAR_SHA256},
                "gt": {"path": "gt", "size_bytes": MODULE.GT_SIZE, "sha256": MODULE.GT_SHA256},
                "converter": {"path": "uw_frontend/datasets/aqualoc_raw_to_rosbag.py", "size_bytes": 1, "sha256": MODULE.CONVERTER_SHA256},
            }
            value = MODULE.build_manifest(output, output, ["python3", "-m", "converter"], audit, identities)
            encoded = json.dumps(value, allow_nan=False)
            self.assertIn(MODULE.SCHEMA_VERSION, encoded)
            self.assertEqual(value["status"], "PASS")
            self.assertEqual(value["selection"]["camera_global_end_index_inclusive"], 6300)
            self.assertEqual(value["selection"]["downstream_hfnet_inner_imu"]["count"], 17987)
            self.assertEqual(value["output"]["topic_counts"][MODULE.CAMERA_TOPIC], 1801)
            self.assertEqual(value["semantics"]["header_stamp"], "raw_csv_integer_ns")
            self.assertTrue(value["semantics"]["no_time_shift"])
            self.assertEqual(value["semantics"]["gt_pose"], "world_T_camera")
            self.assertTrue(all(value["checks"].values()))
            manifest_path = Path(directory) / "window.bag.manifest.json"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            shared_identity = SHARED.validate_provenance(manifest_path, output)
            self.assertEqual(shared_identity["output_topic_counts"][MODULE.IMU_TOPIC], 18084)

    def test_exclusive_writer_refuses_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            MODULE.write_exclusive(path, b"first")
            with self.assertRaises(FileExistsError):
                MODULE.write_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")

    def test_manifest_publish_failure_rolls_back_formal_bag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial_bag = root / ".window.bag.partial"
            partial_manifest = root / ".window.bag.manifest.json.partial"
            output_bag = root / "window.bag"
            output_manifest = root / "window.bag.manifest.json"
            partial_bag.write_bytes(b"bag")
            partial_manifest.write_bytes(b"manifest")
            calls = 0

            def fail_second_link(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected manifest publication failure")
                os.link(source, destination)

            with self.assertRaisesRegex(OSError, "injected manifest"):
                MODULE.publish_pair_no_clobber(
                    partial_bag,
                    partial_manifest,
                    output_bag,
                    output_manifest,
                    link=fail_second_link,
                )
            self.assertFalse(output_bag.exists())
            self.assertFalse(output_manifest.exists())
            self.assertTrue(partial_bag.exists())
            self.assertTrue(partial_manifest.exists())


if __name__ == "__main__":
    unittest.main()
