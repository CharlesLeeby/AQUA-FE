from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import genpy
import rosbag
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, Imu, PointCloud

from scripts.audit_quality_partition import audit_bags
from scripts.rewrite_quality_partition import rewrite_bag


def _feature_message() -> PointCloud:
    message = PointCloud()
    message.header.stamp = genpy.Time.from_sec(1.0)
    message.header.frame_id = "camera"
    message.points = [Point32(0.1, 0.2, 1.0), Point32(0.3, 0.4, 1.0)]
    values = {
        "id": [10.0, 11.0],
        "camera_id": [0.0, 0.0],
        "p_u": [100.0, 200.0],
        "p_v": [50.0, 60.0],
        "velocity_x": [0.0, 0.0],
        "velocity_y": [0.0, 0.0],
        "source_code": [1.0, 2.0],
        "quality": [0.8, 0.9],
        "sigma": [1.11803398875, 1.05409255339],
    }
    message.channels = [
        ChannelFloat32(name=name, values=channel_values)
        for name, channel_values in values.items()
    ]
    return message


def _write_input(path: Path) -> None:
    stamp = genpy.Time.from_sec(1.0)
    imu = Imu()
    imu.header.stamp = stamp
    imu.linear_acceleration.x = 1.25
    with rosbag.Bag(str(path), "w") as bag:
        bag.write("/imu", imu, stamp)
        bag.write("/feature_tracker/feature", _feature_message(), stamp)


class QualityPartitionTests(unittest.TestCase):
    def test_rewrite_and_audit_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            output = root / "output.bag"
            _write_input(source)
            stats = rewrite_bag(
                input_bag=source,
                output_bag=output,
                feature_topic="/feature_tracker/feature",
                source_codes={1},
                quality=1.0,
                min_quality=0.05,
            )
            self.assertEqual(stats["selected_observations"], 1)
            self.assertEqual(stats["raw_copied_messages"], 1)
            audit = audit_bags(
                input_bag=source,
                output_bag=output,
                feature_topic="/feature_tracker/feature",
                source_codes={1},
                quality=1.0,
                min_quality=0.05,
            )
            self.assertTrue(audit["contract_pass"])
            self.assertEqual(audit["changed_observations"], 1)

    def test_audit_rejects_an_unexpected_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            output = root / "output.bag"
            _write_input(source)
            rewrite_bag(
                input_bag=source,
                output_bag=output,
                feature_topic="/feature_tracker/feature",
                source_codes={2},
                quality=1.0,
                min_quality=0.05,
            )
            with self.assertRaises(ValueError):
                audit_bags(
                    input_bag=source,
                    output_bag=output,
                    feature_topic="/feature_tracker/feature",
                    source_codes={1},
                    quality=1.0,
                    min_quality=0.05,
                )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            output = root / "output.bag"
            _write_input(source)
            output.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                rewrite_bag(
                    input_bag=source,
                    output_bag=output,
                    feature_topic="/feature_tracker/feature",
                    source_codes={1},
                    quality=1.0,
                    min_quality=0.05,
                )


if __name__ == "__main__":
    unittest.main()
