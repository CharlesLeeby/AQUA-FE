from __future__ import annotations

import sys
import unittest
from pathlib import Path

import rospy
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "uw_frontend" / "ros"))

from causal_lineage_shadow_node import CausalLineageShadow, ShadowConfig


def point_cloud(feature_id: int | None, pixel_u: float = 0.0) -> PointCloud:
    msg = PointCloud()
    msg.header.stamp = rospy.Time.from_sec(1.0)
    if feature_id is None:
        return msg
    msg.points = [Point32(0.0, 0.0, 1.0)]
    values = {
        "id": float(feature_id),
        "source_code": 20.0,
        "is_learned": 1.0,
        "p_u": pixel_u,
        "p_v": 0.0,
        "velocity_x": 1.0,
        "velocity_y": 0.0,
    }
    msg.channels = [
        ChannelFloat32(name=name, values=[value]) for name, value in values.items()
    ]
    return msg


def base_cloud() -> PointCloud:
    msg = point_cloud(1, 0.0)
    for channel in msg.channels:
        if channel.name == "source_code" or channel.name == "is_learned":
            channel.values[0] = 0.0
    return msg


class CausalLineageRearmTest(unittest.TestCase):
    def config(self, rearm_absent_frames: int) -> ShadowConfig:
        return ShadowConfig(
            min_observations=1,
            rank_observations=1,
            min_distance_px=5.0,
            min_motion_ratio=0.5,
            max_motion_ratio=1.5,
            max_lineages=1,
            rearm_absent_frames=rearm_absent_frames,
        )

    def test_default_cap_remains_cumulative(self) -> None:
        selector = CausalLineageShadow(self.config(0))
        selector.process(base_cloud(), point_cloud(101, 100.0))
        selector.process(base_cloud(), point_cloud(None))
        _merged, decision = selector.process(base_cloud(), point_cloud(102, 120.0))
        self.assertEqual(decision["injected_observations"], 0)
        self.assertEqual(decision["selected_ids"], "101")

    def test_absent_lineage_releases_active_slot(self) -> None:
        selector = CausalLineageShadow(self.config(2))
        selector.process(base_cloud(), point_cloud(101, 100.0))
        selector.process(base_cloud(), point_cloud(None))
        _merged, decision = selector.process(base_cloud(), point_cloud(102, 120.0))
        self.assertEqual(decision["retired_ids"], "101")
        self.assertEqual(decision["active_ids"], "102")
        self.assertEqual(decision["injected_observations"], 1)
        self.assertEqual(decision["selected_ids"], "101;102")


if __name__ == "__main__":
    unittest.main()
