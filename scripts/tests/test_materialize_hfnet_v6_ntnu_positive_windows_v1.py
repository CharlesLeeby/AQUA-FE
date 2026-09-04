#!/usr/bin/env python3
"""Process-free synthetic ROS-bag tests for the NTNU HFNet input layer."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import rosbag
import rospy
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import String

from scripts import audit_hfnet_v6_ntnu_positive_windows_input_v1 as auditor
from scripts import materialize_hfnet_v6_ntnu_positive_windows_v1 as adapter


def stamp(seconds: float) -> rospy.Time:
    return rospy.Time.from_sec(seconds)


def image_message(header_seconds: float, value: int) -> Image:
    message = Image()
    message.header.stamp = stamp(header_seconds)
    message.header.frame_id = "cam0_sensor_frame"
    message.height = 540
    message.width = 720
    message.encoding = "mono8"
    message.is_bigendian = 0
    message.step = 720
    message.data = bytes([value]) * (720 * 540)
    return message


def imu_message(header_seconds: float, index: int) -> Imu:
    message = Imu()
    message.header.stamp = stamp(header_seconds)
    message.header.frame_id = "imu_sensor_frame"
    message.angular_velocity.x = index * 1e-5
    message.angular_velocity.y = -index * 2e-5
    message.angular_velocity.z = index * 3e-5
    message.linear_acceleration.x = 0.1
    message.linear_acceleration.y = -0.2
    message.linear_acceleration.z = 9.81
    return message


class NTNUPositiveMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "synthetic.bag"
        events = [(1000.0, "/origin", String(data="exact bag origin"))]
        # IMU record time is 5 ms later than its Header.stamp, matching the
        # two-clock structure that the production selector must preserve.
        index = 0
        current = 1001.40
        while current <= 1003.50 + 1e-12:
            events.append((current, adapter.IMU_TOPIC, imu_message(current - 0.005, index)))
            current += 0.005
            index += 1
        # The first selected camera has a header before T0+2 s; the last
        # excluded camera has a header before T0+3 s.  Correct selection is
        # therefore provably by record time, not by Header.stamp.
        events.extend(
            [
                (1001.95, adapter.CAMERA_TOPIC, image_message(1001.90, 1)),
                (1002.01, adapter.CAMERA_TOPIC, image_message(1001.96, 2)),
                (1002.50, adapter.CAMERA_TOPIC, image_message(1002.45, 3)),
                (1002.90, adapter.CAMERA_TOPIC, image_message(1002.85, 4)),
                (1003.01, adapter.CAMERA_TOPIC, image_message(1002.96, 5)),
            ]
        )
        with rosbag.Bag(str(self.source), "w", chunk_threshold=1024) as bag:
            for record_seconds, topic, message in sorted(events, key=lambda item: item[0]):
                bag.write(topic, message, stamp(record_seconds))
        self.output = self.root / "prepared"
        self.spec = adapter.WindowSpec(
            window_id="synthetic_s2_d1",
            sequence_id="synthetic",
            source_bag=self.source,
            source_size_bytes=self.source.stat().st_size,
            official_xet_cas_key="synthetic-not-a-content-hash",
            local_full_file_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            start_offset_ns=2_000_000_000,
            end_offset_ns=3_000_000_000,
            output_root=self.output,
        )
        scan = adapter.scan_window(self.spec, retain_camera_messages=False)
        summary = adapter.scan_summary(scan)
        self.assertEqual(summary["camera"]["count"], 3)
        self.assertLess(summary["camera"]["header_ns_inclusive"][0], 1_002_000_000_000)
        self.frozen = {
            "source_bag_first_record_ns": summary["source_bag_first_record_ns"],
            "absolute_record_bounds_ns_closed": summary["requested_record_bounds_ns_closed"],
            "camera": {
                key: summary["camera"][key]
                for key in (
                    "count",
                    "record_ns_inclusive",
                    "header_ns_inclusive",
                    "header_minus_record_ns_range",
                )
            },
            "imu": {
                key: summary["imu"][key]
                for key in (
                    "count",
                    "record_ns_inclusive",
                    "raw_header_ns_inclusive",
                    "shifted_header_ns_inclusive",
                )
            },
        }

    def materialize(self):
        return adapter.materialize_one(
            self.spec,
            self.frozen,
            selector_identity={"sha256": "synthetic-selector"},
            config_identity={"sha256": "synthetic-config"},
            reused_code={"status": "synthetic-test"},
        )

    def test_exact_window_materialization_is_atomic_and_process_free(self) -> None:
        manifest = self.materialize()
        self.assertEqual(manifest["status"], "PASS_EXACT_WINDOW_PREPARATION_ONLY")
        self.assertTrue(all(value is False for value in manifest["claims"].values()))
        stamps = [int(line) for line in (self.output / "cam0_times.txt").read_text().splitlines()]
        self.assertEqual(len(stamps), 3)
        self.assertEqual(len(list((self.output / "mav0/cam0/data").glob("*.png"))), 3)
        self.assertTrue((self.output / "mav0/imu0/data.csv").is_file())
        self.assertTrue((self.output / "materialization_manifest.json").is_file())

    def test_independent_auditor_replays_source_selection(self) -> None:
        self.materialize()
        audit_spec = auditor.AuditSpec(
            window_id=self.spec.window_id,
            sequence_id=self.spec.sequence_id,
            source_bag=self.source,
            source_size_bytes=self.source.stat().st_size,
            source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            start_offset_ns=self.spec.start_offset_ns,
            end_offset_ns=self.spec.end_offset_ns,
            output_root=self.output,
        )
        result = auditor.audit_one(
            audit_spec,
            self.frozen,
            camera_schema=adapter.CAMERA_SCHEMA,
            verify_source_sha256=True,
        )
        self.assertEqual(result["status"], "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT")
        self.assertTrue(result["camera"]["all_png_pixels_byte_identical_to_selected_source_messages"])
        self.assertTrue(all(value is False for value in result["claims"].values()))
        binding = result["runner_binding"]
        manifest_path = (self.output / "materialization_manifest.json").resolve()
        config_path = adapter.DEFAULT_CONFIG.resolve()
        self.assertEqual(
            binding["schema_version"],
            "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1",
        )
        self.assertEqual(binding["case_id"], self.spec.window_id)
        self.assertEqual(binding["input_root"], str(self.output.resolve()))
        self.assertEqual(binding["input_manifest"]["path"], str(manifest_path))
        self.assertEqual(binding["input_manifest"]["size_bytes"], manifest_path.stat().st_size)
        self.assertEqual(
            binding["input_manifest"]["sha256"],
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(binding["base_config"]["path"], str(config_path))
        self.assertEqual(binding["base_config"]["size_bytes"], config_path.stat().st_size)
        self.assertEqual(
            binding["base_config"]["sha256"],
            hashlib.sha256(config_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(binding["camera_count"], 3)
        self.assertEqual(
            binding["camera_header_ns_inclusive"],
            self.frozen["camera"]["header_ns_inclusive"],
        )
        self.assertEqual(binding["score_relative_indices_inclusive"], [0, 2])
        self.assertEqual(
            binding["history"],
            "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
        )
        self.assertEqual(binding["times_relative_path"], "cam0_times.txt")
        self.assertEqual(binding["images_relative_path"], "mav0/cam0/data")
        self.assertEqual(binding["image_extension"], ".png")
        self.assertEqual(binding["imu_relative_path"], "mav0/imu0/data.csv")
        self.assertIs(binding["imu_reader_bracket_valid"], True)
        self.assertEqual(
            binding,
            {
                "schema_version": "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1",
                "case_id": self.spec.window_id,
                "input_root": str(self.output.resolve()),
                "input_manifest": {
                    "path": str(manifest_path),
                    "size_bytes": manifest_path.stat().st_size,
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                },
                "base_config": {
                    "path": str(config_path),
                    "size_bytes": config_path.stat().st_size,
                    "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                },
                "camera_count": 3,
                "camera_header_ns_inclusive": self.frozen["camera"][
                    "header_ns_inclusive"
                ],
                "score_relative_indices_inclusive": [0, 2],
                "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
                "times_relative_path": "cam0_times.txt",
                "images_relative_path": "mav0/cam0/data",
                "image_extension": ".png",
                "imu_relative_path": "mav0/imu0/data.csv",
                "imu_reader_bracket_valid": True,
            },
        )

    def test_no_clobber_preserves_existing_owner(self) -> None:
        self.output.mkdir()
        marker = self.output / "owner"
        marker.write_text("preserve", encoding="ascii")
        with self.assertRaisesRegex(adapter.ContractError, "NO_CLOBBER"):
            self.materialize()
        self.assertEqual(marker.read_text(encoding="ascii"), "preserve")

    def test_natural_history_is_preflight_only(self) -> None:
        result = adapter.preflight_one(
            self.spec,
            self.frozen,
            selector_identity={},
            config_identity={},
            reused_code={},
            mode="natural-history",
        )
        self.assertEqual(
            result["status"],
            "PREFLIGHT_SECONDARY_NATURAL_HISTORY_UNFROZEN_NOT_MATERIALIZABLE",
        )
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(adapter.ContractError, "SEPARATE_SELECTOR_FREEZE"):
            adapter.materialize_one(
                self.spec,
                self.frozen,
                selector_identity={},
                config_identity={},
                reused_code={},
                mode="natural-history",
            )

    def test_materialization_rehashes_complete_source_before_staging(self) -> None:
        bad = replace(self.spec, local_full_file_sha256="0" * 64)
        with self.assertRaisesRegex(adapter.ContractError, "FULL_FILE_SHA256_MISMATCH"):
            adapter.materialize_one(
                bad,
                self.frozen,
                selector_identity={},
                config_identity={},
                reused_code={},
            )
        self.assertFalse(self.output.exists())

    def test_config_uses_inverse_t_imu_cam_and_shared_model_path(self) -> None:
        text = adapter.DEFAULT_CONFIG.read_text(encoding="utf-8")
        self.assertIn("0.048394787222036377", text)
        self.assertIn("-0.0097706618631980095", text)
        self.assertNotIn("-0.04828147993677678", text)
        self.assertIn(
            'Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"',
            text,
        )

    def test_production_selector_freezes_local_hashes_and_mclab2_header_boundary(self) -> None:
        selector, identity = adapter.validate_selector()
        self.assertEqual(identity["sha256"], adapter.SELECTOR_SHA256)
        source = selector["windows"]["mclab2_s110_d10"]["source_bag"]
        self.assertEqual(
            source["local_full_file_sha256"],
            "c81bddcae78e0cc5bfd773a5364a64d1e89726a6bce34bf4e4d314c85157834f",
        )
        self.assertNotEqual(source["local_full_file_sha256"], source["official_xet_cas_key"])
        self.assertEqual(
            selector["windows"]["mclab2_s110_d10"]["camera"]["header_ns_inclusive"],
            [1725640076078123169, 1725640086028023053],
        )


if __name__ == "__main__":
    unittest.main()
