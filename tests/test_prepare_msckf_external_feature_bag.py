from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import rospy
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_msckf_external_feature_bag.py"
SPEC = importlib.util.spec_from_file_location("prepare_msckf_feature_bag", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def make_message(*, id_first: bool = False) -> PointCloud:
    msg = PointCloud()
    msg.header.stamp = rospy.Time.from_sec(12.25)
    msg.points = [
        Point32(x=-0.25, y=0.10, z=1.0),
        Point32(x=0.30, y=-0.20, z=1.0),
    ]
    channels = [
        ChannelFloat32(name="p_u", values=[100.5, 500.25]),
        ChannelFloat32(name="p_v", values=[200.0, 300.75]),
        ChannelFloat32(name="id", values=[7.0, 1_000_002.0]),
        ChannelFloat32(name="quality", values=[0.8, 0.9]),
    ]
    if id_first:
        channels.insert(0, channels.pop(2))
    msg.channels = channels
    return msg


class PrepareMsckfExternalFeatureBagTest(unittest.TestCase):
    def test_maps_pixels_and_keeps_ids_without_mutating_input(self) -> None:
        original = make_message()
        output, audit = MODULE.adapt_feature_message(
            original, image_width=968, image_height=608
        )

        self.assertEqual(output.channels[0].name, "id")
        self.assertEqual(list(output.channels[0].values), [7.0, 1_000_002.0])
        self.assertEqual(
            [(point.x, point.y, point.z) for point in output.points],
            [(100.5, 200.0, 1.0), (500.25, 300.75, 1.0)],
        )
        self.assertEqual(
            [(point.x, point.y) for point in original.points],
            [(-0.25, 0.10), (0.30, -0.20)],
        )
        self.assertEqual(audit["count"], 2)
        self.assertEqual(audit["min_id"], 7)
        self.assertEqual(audit["max_id"], 1_000_002)
        self.assertNotEqual(
            audit["source_normalized_sha256"], audit["msckf_contract_sha256"]
        )

    def test_already_first_id_channel_is_stable(self) -> None:
        output, _ = MODULE.adapt_feature_message(
            make_message(id_first=True), image_width=968, image_height=608
        )
        self.assertEqual(
            [channel.name for channel in output.channels],
            ["id", "p_u", "p_v", "quality"],
        )

    def test_rejects_missing_or_misaligned_channels(self) -> None:
        missing = make_message()
        missing.channels = [
            channel for channel in missing.channels if channel.name != "p_v"
        ]
        with self.assertRaisesRegex(ValueError, "missing required"):
            MODULE.adapt_feature_message(
                missing, image_width=968, image_height=608
            )

        misaligned = make_message()
        misaligned.channels[0].values.pop()
        with self.assertRaisesRegex(ValueError, "values for 2 points"):
            MODULE.adapt_feature_message(
                misaligned, image_width=968, image_height=608
            )

    def test_rejects_unsafe_id_and_out_of_bounds_pixel(self) -> None:
        unsafe_id = make_message()
        next(
            channel for channel in unsafe_id.channels if channel.name == "id"
        ).values[0] = float(1 << 24)
        with self.assertRaisesRegex(ValueError, "cannot be represented exactly"):
            MODULE.adapt_feature_message(
                unsafe_id, image_width=968, image_height=608
            )

        out_of_bounds = make_message()
        next(
            channel for channel in out_of_bounds.channels if channel.name == "p_u"
        ).values[0] = 968.0
        with self.assertRaisesRegex(ValueError, "outside 968x608"):
            MODULE.adapt_feature_message(
                out_of_bounds, image_width=968, image_height=608
            )


if __name__ == "__main__":
    unittest.main()
