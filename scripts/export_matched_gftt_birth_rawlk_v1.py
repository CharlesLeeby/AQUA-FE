#!/usr/bin/env python3
"""Formal GFTT-birth arm for the shared matched raw-LK carrier v1."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import cv2
import numpy as np

from scripts import matched_birth_rawlk_core_v1 as matched


GFTT_MAX_CORNERS = 2048
GFTT_QUALITY_LEVEL = 0.01
GFTT_MIN_DISTANCE_PX = 1.0
GFTT_BLOCK_SIZE = 7
GFTT_USE_HARRIS = False
GFTT_HARRIS_K = 0.04
GFTT_SOURCE_CODE = 21


def _assert_frozen_gftt_definition() -> None:
    """Reject in-process mutation of the preregistered detector definition."""

    observed = {
        "max_corners": GFTT_MAX_CORNERS,
        "quality_level": GFTT_QUALITY_LEVEL,
        "min_distance_px": GFTT_MIN_DISTANCE_PX,
        "block_size": GFTT_BLOCK_SIZE,
        "use_harris": GFTT_USE_HARRIS,
        "harris_k": GFTT_HARRIS_K,
        "source_code": GFTT_SOURCE_CODE,
    }
    expected = {
        "max_corners": 2048,
        "quality_level": 0.01,
        "min_distance_px": 1.0,
        "block_size": 7,
        "use_harris": False,
        "harris_k": 0.04,
        "source_code": 21,
    }
    if observed != expected:
        raise RuntimeError(
            f"matched GFTT detector definition drift: {observed!r} != {expected!r}"
        )


class GFTTBirthDetector:
    """Detector-only Shi–Tomasi proposer; no LK, IDs, or spatial thinning."""

    def __init__(self) -> None:
        _assert_frozen_gftt_definition()
        # Detect reads only these literal instance values.  The module globals
        # are checked above for provenance but cannot silently steer a run.
        self._max_corners = 2048
        self._quality_level = 0.01
        self._min_distance_px = 1.0
        self._block_size = 7
        self._use_harris = False
        self._harris_k = 0.04
        self._detect_calls = 0
        self._candidate_total = 0
        self._input_shapes: set[tuple[int, int]] = set()

    def detect(self, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        _assert_frozen_gftt_definition()
        gray = np.asarray(gray, dtype=np.uint8)
        if gray.ndim != 2:
            raise ValueError("GFTT detector expects processed mono8")
        self._input_shapes.add((int(gray.shape[0]), int(gray.shape[1])))
        corners = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self._max_corners,
            qualityLevel=self._quality_level,
            minDistance=self._min_distance_px,
            mask=None,
            blockSize=self._block_size,
            useHarrisDetector=self._use_harris,
            k=self._harris_k,
        )
        self._detect_calls += 1
        if corners is None:
            points = np.empty((0, 2), dtype=np.float32)
            scores = np.empty((0,), dtype=np.float32)
            self._candidate_total += int(len(points))
            return points, scores
        points = np.asarray(corners, dtype=np.float32).reshape(-1, 2)
        response = cv2.cornerMinEigenVal(
            gray,
            blockSize=self._block_size,
            ksize=3,
            borderType=cv2.BORDER_DEFAULT,
        )
        height, width = gray.shape
        # OpenCV returns integral-pixel GFTT positions.  Fail closed if a future
        # implementation changes that API instead of silently inventing score
        # interpolation that would differ from the preregistered detector.
        rounded = np.rint(points).astype(np.int64)
        if not np.array_equal(points, rounded.astype(np.float32)):
            raise RuntimeError("GFTT returned non-integral candidate coordinates")
        if np.any(rounded[:, 0] < 0) or np.any(rounded[:, 0] >= width):
            raise RuntimeError("GFTT returned x coordinate outside image")
        if np.any(rounded[:, 1] < 0) or np.any(rounded[:, 1] >= height):
            raise RuntimeError("GFTT returned y coordinate outside image")
        scores = response[rounded[:, 1], rounded[:, 0]].astype(np.float32)
        self._candidate_total += int(len(points))
        return points, scores

    def artifact_metadata(self) -> dict[str, object]:
        _assert_frozen_gftt_definition()
        return {
            "identity": "opencv_GFTT_detector_only_matched_birth_v1",
            "api": {
                "call": "cv2.goodFeaturesToTrack",
                "score": "cv2.cornerMinEigenVal_at_returned_integral_pixel",
                "matcher_called": False,
                "descriptor_computation": False,
                "carrier_thinning_inside_detector": False,
            },
            "runtime": {
                "opencv_version": str(cv2.__version__),
                "numpy_version": str(np.__version__),
                "detect_calls": int(self._detect_calls),
                "candidate_total": int(self._candidate_total),
                "input_shapes": [
                    list(shape) for shape in sorted(self._input_shapes)
                ],
                "input_shapes_hw": [list(shape) for shape in sorted(self._input_shapes)],
            },
            "frozen_detector_parameters": {
                "max_corners": self._max_corners,
                "quality_level": self._quality_level,
                "min_distance_px": self._min_distance_px,
                "block_size": self._block_size,
                "use_harris": self._use_harris,
                "harris_k": self._harris_k,
            },
        }


GFTT_METHOD_SPEC = matched.MatchedMethodSpec(
    arm_id="GFTT_BIRTH_RAWLK_MATCHED_V1",
    detector_family="classical_gftt_shi_tomasi",
    detector_implementation_id="opencv_GFTT_detector_only_matched_birth_v1",
    detector_contract={
        "role": "birth_proposals_only",
        "input": "common_processed_mono8",
        "max_corners": GFTT_MAX_CORNERS,
        "quality_level": GFTT_QUALITY_LEVEL,
        "internal_min_distance_px": GFTT_MIN_DISTANCE_PX,
        "block_size": GFTT_BLOCK_SIZE,
        "use_harris_detector": GFTT_USE_HARRIS,
        "harris_k_api_argument_inert_when_non_harris": GFTT_HARRIS_K,
        "score": "cornerMinEigenVal_block7_ksize3_at_candidate_pixel",
        "output": ["points_xy_float32", "scores_float32"],
        "matcher": None,
        "descriptor": None,
        "shared_18px_admission_only": True,
    },
    source_code=GFTT_SOURCE_CODE,
    is_learned=0,
    detector_factory=GFTTBirthDetector,
    wrapper_source=Path(__file__).resolve(),
    detector_code_artifacts=(),
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--feature-topic", default=matched.FEATURE_TOPIC_DEFAULT)
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--diagnostics-csv", required=True)
    parser.add_argument("--legacy-manifest-json", required=True)
    parser.add_argument("--work-directory", required=True)
    parser.add_argument("--attempt-json", required=True)
    parser.add_argument("--max-published-frames", type=_positive_int, default=None)
    return parser


def export_bag(*args, **kwargs):
    return matched.export_bag(*args, method_spec=GFTT_METHOD_SPEC, **kwargs)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = matched.export_bag(
        args.source_feature_bag,
        args.raw_image_bag,
        args.camera_yaml,
        args.output_bag,
        image_topic=args.image_topic,
        feature_topic=args.feature_topic,
        manifest_json=args.manifest_json,
        diagnostics_csv=args.diagnostics_csv,
        legacy_manifest_json=args.legacy_manifest_json,
        work_directory=args.work_directory,
        attempt_json=args.attempt_json,
        max_published_frames=args.max_published_frames,
        method_spec=GFTT_METHOD_SPEC,
        _cli_production_factory_token=matched._CLI_PRODUCTION_FACTORY_TOKEN,
    )
    print(matched._canonical_bytes(matched.cli_summary(manifest)).decode().rstrip())
    return 0


if __name__ == "__main__":
    from scripts import export_matched_gftt_birth_rawlk_v1 as canonical

    raise SystemExit(canonical.main())
