from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import genpy
import rosbag
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, Imu, PointCloud

from scripts.audit_whole_lineage_exact_drop_v1 import (
    AuditViolation,
    audit_bags,
    write_json_no_clobber,
)


FEATURE_TOPIC = "/feature_tracker/feature"


def _observation(
    feature_id: int,
    *,
    source_code: int,
    learned: int,
    p_u: float,
    quality: float = 0.9,
) -> dict:
    return {
        "id": float(feature_id),
        "camera_id": 0.0,
        "p_u": float(p_u),
        "p_v": float(p_u + 5.0),
        "quality": float(quality),
        "source_code": float(source_code),
        "is_learned": float(learned),
    }


def _feature_message(observations: list, stamp_s: float) -> PointCloud:
    message = PointCloud()
    message.header.stamp = genpy.Time.from_sec(stamp_s)
    message.header.frame_id = "world"
    message.points = [
        Point32(item["p_u"] / 100.0, item["p_v"] / 100.0, 1.0)
        for item in observations
    ]
    names = (
        "id",
        "camera_id",
        "p_u",
        "p_v",
        "quality",
        "source_code",
        "is_learned",
    )
    message.channels = [
        ChannelFloat32(name=name, values=[item[name] for item in observations])
        for name in names
    ]
    return message


def _imu(stamp_s: float, value: float) -> Imu:
    message = Imu()
    message.header.stamp = genpy.Time.from_sec(stamp_s)
    message.linear_acceleration.x = float(value)
    return message


def _write_bag(
    path: Path,
    frames: list,
    *,
    imu_values=(1.25, 2.5),
) -> None:
    with rosbag.Bag(str(path), "w") as bag:
        stamp = genpy.Time.from_sec(1.0)
        bag.write("/imu", _imu(1.0, imu_values[0]), stamp)
        stamp = genpy.Time.from_sec(2.0)
        bag.write(FEATURE_TOPIC, _feature_message(frames[0], 2.0), stamp)
        stamp = genpy.Time.from_sec(3.0)
        bag.write("/imu", _imu(3.0, imu_values[1]), stamp)
        stamp = genpy.Time.from_sec(4.0)
        bag.write(FEATURE_TOPIC, _feature_message(frames[1], 4.0), stamp)


def _proposed_frames() -> list:
    return [
        [
            _observation(1, source_code=1, learned=0, p_u=10.0),
            _observation(100, source_code=20, learned=1, p_u=50.0, quality=0.8),
        ],
        [
            _observation(1, source_code=1, learned=0, p_u=11.0),
            # The learned-born ID is now represented as an ordinary KLT observation.
            _observation(100, source_code=1, learned=0, p_u=51.0, quality=0.81),
            _observation(2, source_code=2, learned=0, p_u=70.0),
        ],
    ]


def _exact_drop_frames() -> list:
    proposed = _proposed_frames()
    return [
        [proposed[0][0]],
        [proposed[1][0], proposed[1][2]],
    ]


class WholeLineageExactDropV1Tests(unittest.TestCase):
    def test_passes_and_counts_seed_plus_klt_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposed = root / "p.bag"
            drop = root / "d.bag"
            _write_bag(proposed, _proposed_frames())
            _write_bag(drop, _exact_drop_frames())

            result = audit_bags(proposed_bag=proposed, drop_bag=drop)

            self.assertTrue(result["contract_pass"])
            self.assertEqual(result["summary"]["learned_lineages"], 1)
            self.assertEqual(result["summary"]["dropped_observations"], 2)
            self.assertEqual(result["summary"]["klt_source_code_1_continuation_observations"], 1)
            self.assertEqual(result["summary"]["nonfeature_messages"], 2)
            self.assertEqual(
                result["digests"]["expected_drop_feature_sequence_sha256"],
                result["digests"]["actual_drop_feature_sequence_sha256"],
            )

    def test_rejects_seed_only_drop_that_leaves_klt_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposed = root / "p.bag"
            drop = root / "d_seed_only.bag"
            frames = _exact_drop_frames()
            frames[1].insert(1, _proposed_frames()[1][1])
            _write_bag(proposed, _proposed_frames())
            _write_bag(drop, frames)

            with self.assertRaisesRegex(AuditViolation, "point fields/order differ"):
                audit_bags(proposed_bag=proposed, drop_bag=drop)

    def test_rejects_change_to_a_kept_observation_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposed = root / "p.bag"
            drop = root / "d_changed.bag"
            frames = _exact_drop_frames()
            frames[1][0] = dict(frames[1][0], quality=0.5)
            _write_bag(proposed, _proposed_frames())
            _write_bag(drop, frames)

            with self.assertRaisesRegex(AuditViolation, "channel 'quality' values differ"):
                audit_bags(proposed_bag=proposed, drop_bag=drop)

    def test_rejects_nonfeature_serialized_byte_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposed = root / "p.bag"
            drop = root / "d_changed_imu.bag"
            _write_bag(proposed, _proposed_frames())
            _write_bag(drop, _exact_drop_frames(), imu_values=(9.0, 2.5))

            with self.assertRaisesRegex(AuditViolation, "non-feature serialized payload differs"):
                audit_bags(proposed_bag=proposed, drop_bag=drop)

    def test_rejects_late_learned_marker_for_preexisting_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposed = root / "p_late_marker.bag"
            drop = root / "d.bag"
            frames = [
                [_observation(100, source_code=1, learned=0, p_u=50.0)],
                [_observation(100, source_code=20, learned=1, p_u=51.0)],
            ]
            _write_bag(proposed, frames)
            _write_bag(drop, [[], []])

            with self.assertRaisesRegex(AuditViolation, "learned provenance appears after"):
                audit_bags(proposed_bag=proposed, drop_bag=drop)

    def test_report_writer_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            write_json_no_clobber(path, {"contract_pass": True})
            with self.assertRaises(FileExistsError):
                write_json_no_clobber(path, {"contract_pass": False})


if __name__ == "__main__":
    unittest.main()
