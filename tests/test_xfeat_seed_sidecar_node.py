from __future__ import annotations

import unittest

import cv2
import numpy as np
import rospy
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud

from uw_frontend.matchers.base import BaseMatcher, MatchResult
from uw_frontend.ros.causal_lineage_shadow_node import ShadowConfig, _median_speed
from uw_frontend.ros.xfeat_seed_sidecar_node import (
    LearnedSeedKltSidecar,
    SeedSidecarConfig,
)


class _SingleSeedMatcher(BaseMatcher):
    name = "xfeat"

    def __init__(self) -> None:
        self.calls = 0

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        self.calls += 1
        return MatchResult(
            points0=np.asarray([[80.0, 80.0]], dtype=np.float32),
            points1=np.asarray([[81.0, 80.0]], dtype=np.float32),
            confidences=np.asarray([1.0], dtype=np.float32),
            method=self.name,
        )


class _RetrySeedMatcher(_SingleSeedMatcher):
    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        self.calls += 1
        if self.calls == 1:
            return MatchResult(
                points0=np.empty((0, 2), dtype=np.float32),
                points1=np.empty((0, 2), dtype=np.float32),
                confidences=np.empty((0,), dtype=np.float32),
                method=self.name,
            )
        return MatchResult(
            points0=np.asarray([[80.0, 80.0]], dtype=np.float32),
            points1=np.asarray([[81.0, 80.0]], dtype=np.float32),
            confidences=np.asarray([1.0], dtype=np.float32),
            method=self.name,
        )


def _camera() -> dict:
    return {
        "model": "pinhole",
        "K": np.asarray([[100.0, 0.0, 64.0], [0.0, 100.0, 64.0], [0.0, 0.0, 1.0]]),
        "D": np.zeros((4,), dtype=np.float64),
    }


def _base_message(frame_index: int) -> PointCloud:
    msg = PointCloud()
    msg.header.stamp = rospy.Time.from_sec(100.0 + frame_index)
    msg.header.frame_id = "world"
    channel_names = [
        "id",
        "camera_id",
        "p_u",
        "p_v",
        "velocity_x",
        "velocity_y",
        "gx",
        "gy",
        "gz",
        "quality",
        "sigma",
        "source_code",
        "is_learned",
    ]
    msg.channels = [ChannelFloat32(name=name) for name in channel_names]
    points = [(10.0 + frame_index, 10.0), (12.0 + frame_index, 20.0), (18.0 + frame_index, 30.0)]
    for feature_id, (u, v) in enumerate(points):
        msg.points.append(Point32((u - 64.0) / 100.0, (v - 64.0) / 100.0, 1.0))
        values = [
            float(feature_id),
            0.0,
            u,
            v,
            0.01,
            0.0,
            0.0,
            0.0,
            0.0,
            0.9,
            1.0,
            0.0,
            0.0,
        ]
        for channel, value in zip(msg.channels, values):
            channel.values.append(float(value))
    return msg


def _half_velocity_base_message(frame_index: int) -> PointCloud:
    msg = _base_message(frame_index)
    p_u = next(channel for channel in msg.channels if channel.name == "p_u")
    for index, point in enumerate(msg.points):
        p_u.values[index] += float(frame_index)
        point.x += float(frame_index) / 100.0
    return msg


def _four_point_base_message(frame_index: int) -> PointCloud:
    msg = _base_message(frame_index)
    u, v = 25.0 + frame_index, 40.0
    msg.points.append(Point32((u - 64.0) / 100.0, (v - 64.0) / 100.0, 1.0))
    values = [3.0, 0.0, u, v, 0.01, 0.0, 0.0, 0.0, 0.0, 0.9, 1.0, 0.0, 0.0]
    for channel, value in zip(msg.channels, values):
        channel.values.append(float(value))
    return msg


def _zero_dominated_velocity_base_message(frame_index: int) -> PointCloud:
    msg = _base_message(frame_index)
    velocity_x = next(channel for channel in msg.channels if channel.name == "velocity_x")
    velocity_y = next(channel for channel in msg.channels if channel.name == "velocity_y")
    velocity_x.values = [0.0, 0.0, 0.01]
    velocity_y.values = [0.0, 0.0, 0.0]
    return msg


class LearnedSeedSidecarTest(unittest.TestCase):
    def test_nonzero_base_speed_mode_ignores_newborn_zero_placeholders(self) -> None:
        msg = _zero_dominated_velocity_base_message(0)
        self.assertEqual(_median_speed(msg), 0.0)
        self.assertAlmostEqual(_median_speed(msg, ignore_zeros=True), 0.01)

    def test_nonzero_base_speed_mode_allows_causal_motion_confirmation(self) -> None:
        rng = np.random.default_rng(3)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        core = LearnedSeedKltSidecar(
            matcher=_SingleSeedMatcher(),
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                max_active_seeds=2,
                seed_min_base_distance_px=20.0,
                ignore_zero_base_speeds=True,
            ),
            selector_config=ShadowConfig(ignore_zero_base_speeds=True),
        )

        merged_counts = []
        for frame_index in range(6):
            transform = np.float32(
                [[1.0, 0.0, float(frame_index)], [0.0, 1.0, 0.0]]
            )
            image = cv2.warpAffine(
                texture,
                transform,
                (texture.shape[1], texture.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            _sidecar, merged, _row = core.process(
                image,
                _zero_dominated_velocity_base_message(frame_index),
            )
            merged_counts.append(len(merged.points))

        self.assertEqual(merged_counts[:5], [3, 3, 3, 3, 3])
        self.assertEqual(merged_counts[5], 4)

    def test_seed_is_confirmed_causally_after_five_observations(self) -> None:
        rng = np.random.default_rng(4)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        matcher = _SingleSeedMatcher()
        core = LearnedSeedKltSidecar(
            matcher=matcher,
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                max_active_seeds=2,
                seed_min_base_distance_px=20.0,
                seed_min_active_distance_px=8.0,
                lk_fb_threshold=1.5,
                lk_min_ncc=0.35,
            ),
            selector_config=ShadowConfig(
                min_observations=5,
                rank_observations=5,
                min_distance_px=40.0,
                min_motion_ratio=0.6,
                max_motion_ratio=1.5,
                max_lineages=1,
            ),
        )

        merged_counts = []
        active_ids = []
        decisions = []
        for frame_index in range(6):
            transform = np.float32([[1.0, 0.0, float(frame_index)], [0.0, 1.0, 0.0]])
            image = cv2.warpAffine(
                texture,
                transform,
                (texture.shape[1], texture.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            sidecar, merged, decision = core.process(image, _base_message(frame_index))
            merged_counts.append(len(merged.points))
            decisions.append(decision)
            if sidecar.points:
                id_channel = next(channel for channel in sidecar.channels if channel.name == "id")
                active_ids.append(int(round(id_channel.values[0])))

        self.assertEqual(matcher.calls, 1)
        self.assertEqual(len(set(active_ids)), 1)
        self.assertEqual(merged_counts[:5], [3, 3, 3, 3, 3])
        self.assertEqual(merged_counts[5], 4)
        self.assertEqual(decisions[5]["selector_injected_observations"], 1)
        self.assertEqual(len(core.selector.selected_ids), 1)
        selected_id = next(iter(core.selector.selected_ids))
        self.assertAlmostEqual(core.selector.motion_ratios[selected_id], 1.0, places=1)

    def test_empty_match_does_not_consume_trigger_budget(self) -> None:
        rng = np.random.default_rng(7)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        matcher = _RetrySeedMatcher()
        core = LearnedSeedKltSidecar(
            matcher=matcher,
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                seed_min_base_distance_px=20.0,
            ),
            selector_config=ShadowConfig(),
        )
        rows = []
        for frame_index in range(3):
            transform = np.float32([[1.0, 0.0, float(frame_index)], [0.0, 1.0, 0.0]])
            image = cv2.warpAffine(texture, transform, (128, 128), borderMode=cv2.BORDER_REFLECT)
            _sidecar, _merged, row = core.process(image, _base_message(frame_index))
            rows.append(row)
        self.assertEqual(matcher.calls, 2)
        self.assertEqual(core.trigger_count, 1)
        self.assertEqual(rows[1]["added_seeds"], 0)
        self.assertIn("no_seed_retry", rows[1]["trigger_reason"])
        self.assertEqual(rows[2]["added_seeds"], 1)

    def test_motion_inconsistent_seed_is_removed_before_selection(self) -> None:
        rng = np.random.default_rng(11)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        core = LearnedSeedKltSidecar(
            matcher=_SingleSeedMatcher(),
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                max_active_seeds=2,
                seed_min_base_distance_px=20.0,
                motion_confirm_observations=5,
                min_motion_ratio=0.6,
                max_motion_ratio=1.5,
            ),
            selector_config=ShadowConfig(),
        )

        sidecar_counts = []
        merged_counts = []
        for frame_index in range(6):
            transform = np.float32([[1.0, 0.0, float(2 * frame_index)], [0.0, 1.0, 0.0]])
            image = cv2.warpAffine(
                texture,
                transform,
                (texture.shape[1], texture.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            sidecar, merged, _row = core.process(image, _base_message(frame_index))
            sidecar_counts.append(len(sidecar.points))
            merged_counts.append(len(merged.points))

        self.assertEqual(sidecar_counts, [0, 1, 1, 1, 1, 0])
        self.assertEqual(merged_counts, [3, 3, 3, 3, 3, 3])
        self.assertFalse(core.selector.selected_ids)

    def test_velocity_contract_scale_is_calibrated_from_base_tracks(self) -> None:
        rng = np.random.default_rng(13)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        core = LearnedSeedKltSidecar(
            matcher=_SingleSeedMatcher(),
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                max_active_seeds=2,
                seed_min_base_distance_px=20.0,
            ),
            selector_config=ShadowConfig(),
        )

        merged_counts = []
        for frame_index in range(6):
            transform = np.float32([[1.0, 0.0, float(2 * frame_index)], [0.0, 1.0, 0.0]])
            image = cv2.warpAffine(
                texture,
                transform,
                (texture.shape[1], texture.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            _sidecar, merged, _row = core.process(
                image,
                _half_velocity_base_message(frame_index),
            )
            merged_counts.append(len(merged.points))

        self.assertAlmostEqual(core.velocity_contract_scale, 0.5, places=2)
        self.assertEqual(merged_counts[:5], [3, 3, 3, 3, 3])
        self.assertEqual(merged_counts[5], 4)

    def test_geometry_inconsistent_seed_is_removed_before_selection(self) -> None:
        rng = np.random.default_rng(17)
        texture = rng.integers(0, 256, size=(128, 128), dtype=np.uint8)
        core = LearnedSeedKltSidecar(
            matcher=_SingleSeedMatcher(),
            camera=_camera(),
            config=SeedSidecarConfig(
                image_scale=1.0,
                preprocess="none",
                trigger_warmup_frames=0,
                trigger_cooldown_frames=100,
                max_triggers=1,
                force_periodic_trigger=True,
                seed_max_per_trigger=1,
                max_active_seeds=2,
                seed_min_base_distance_px=20.0,
                max_homography_residual_px=0.75,
            ),
            selector_config=ShadowConfig(),
        )

        sidecar_counts = []
        merged_counts = []
        for frame_index in range(6):
            transform = np.float32([[1.0, 0.0, 0.0], [0.0, 1.0, float(frame_index)]])
            image = cv2.warpAffine(
                texture,
                transform,
                (texture.shape[1], texture.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            sidecar, merged, _row = core.process(
                image,
                _four_point_base_message(frame_index),
            )
            sidecar_counts.append(len(sidecar.points))
            merged_counts.append(len(merged.points))

        self.assertEqual(sidecar_counts, [0, 1, 1, 1, 1, 0])
        self.assertEqual(merged_counts, [4, 4, 4, 4, 4, 4])
        self.assertFalse(core.selector.selected_ids)


if __name__ == "__main__":
    unittest.main()
