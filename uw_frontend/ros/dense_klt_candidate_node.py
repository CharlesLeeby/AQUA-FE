#!/usr/bin/env python3
"""Publish the AQUA-FE 350-track KLT stream as an online candidate pool."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np
from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage, Image, PointCloud

from uw_frontend.evaluation.run_frontend_eval import load_config
from uw_frontend.quality.image_quality import ImageQuality
from uw_frontend.ros.export_vins_features import (
    _image_msg_to_gray,
    _load_pinhole_camera,
    _preprocess_gray,
    _tracks_to_vins_pointcloud,
)
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker


# The merger never sends candidate q_i to the backend: admitted tracks inherit
# the base PointCloud schema, and the validated candidate export uses q_i=1.
# Computing the full underwater image-quality vector costs about 0.22 s/frame
# at 1280x720, so the online candidate path deliberately supplies a neutral
# quality object.  KLT locations, FB/NCC checks, and identities are unchanged.
NEUTRAL_IMAGE_QUALITY = ImageQuality(*([1.0] * 20))


class DenseKltCandidatePublisher:
    def __init__(
        self,
        *,
        tracker: KltTracker,
        camera: dict,
        preprocess: str,
        constant_quality: bool,
    ) -> None:
        self.tracker = tracker
        self.camera = camera
        self.preprocess = preprocess
        self.constant_quality = constant_quality
        self.bridge = CvBridge()
        self.previous_stamp: float | None = None
        self.frame_index = 0
        self.lock = threading.Lock()

    def process(self, msg) -> tuple[PointCloud, dict[str, object]]:
        started = time.perf_counter()
        with self.lock:
            stamp = float(msg.header.stamp.to_sec())
            if self.previous_stamp is not None and (
                stamp <= self.previous_stamp or stamp - self.previous_stamp > 1.0
            ):
                self.tracker.reset()
                self.previous_stamp = None
            dt = (
                None
                if self.previous_stamp is None
                else max(1e-6, stamp - self.previous_stamp)
            )
            raw_gray = _image_msg_to_gray(self.bridge, msg)
            gray = _preprocess_gray(raw_gray, self.preprocess)
            tracks, diagnostics = self.tracker.process(gray, NEUTRAL_IMAGE_QUALITY)
            output = _tracks_to_vins_pointcloud(
                tracks,
                msg.header.stamp,
                self.camera,
                dt,
                constant_quality=self.constant_quality,
            )
            decision = {
                "frame_index": self.frame_index,
                "stamp": f"{stamp:.9f}",
                "tracks": len(tracks),
                "mature_tracks": int(np.count_nonzero(tracks.ages >= 4)),
                "added": diagnostics.added_features,
                "dropped": diagnostics.dropped_features,
                "median_fb": diagnostics.median_fb_error,
                "median_ncc": diagnostics.median_ncc,
                "processing_ms": (time.perf_counter() - started) * 1000.0,
            }
            self.previous_stamp = stamp
            self.frame_index += 1
            return output, decision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-topic", default="/cam0/image_raw")
    parser.add_argument("--output-topic", default="/feature_tracker/candidate")
    parser.add_argument("--decision-topic", default="/aqua_fe/dense_klt_candidate")
    parser.add_argument("--camera-config", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("uw_frontend/configs/klt_frontend.yaml"),
    )
    parser.add_argument(
        "--preprocess",
        choices=("none", "equalize", "clahe", "adaptive_clahe"),
        default="clahe",
    )
    parser.add_argument("--compressed", action="store_true")
    parser.add_argument(
        "--variable-quality",
        dest="constant_quality",
        action="store_false",
        help="Export reliability q_i instead of the validated constant q_i=1 candidate stream.",
    )
    parser.set_defaults(constant_quality=True)
    return parser


def main() -> int:
    import rospy
    from std_msgs.msg import String

    args = build_parser().parse_args()
    cfg = load_config(args.config)
    klt_config = KltConfig(**cfg.get("klt", {}))
    klt_config.compute_track_metadata = False
    klt_config.vectorized_ncc = True
    processor = DenseKltCandidatePublisher(
        tracker=KltTracker(klt_config),
        camera=_load_pinhole_camera(args.camera_config),
        preprocess=args.preprocess,
        constant_quality=args.constant_quality,
    )
    rospy.init_node("dense_klt_candidate")
    publisher = rospy.Publisher(args.output_topic, PointCloud, queue_size=10)
    decision_publisher = rospy.Publisher(args.decision_topic, String, queue_size=10)

    def callback(msg) -> None:
        output, decision = processor.process(msg)
        publisher.publish(output)
        decision_publisher.publish(
            String(data=json.dumps(decision, separators=(",", ":"), allow_nan=True))
        )

    image_type = CompressedImage if args.compressed else Image
    rospy.Subscriber(
        args.image_topic,
        image_type,
        callback,
        queue_size=10,
        buff_size=64 * 1024 * 1024,
    )
    rospy.spin()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
