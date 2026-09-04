#!/usr/bin/env python3
"""Export a detector-only SuperPoint + raw-frame LK comparison feature bag.

This standalone exporter is additive: it does not call LightGlue matching and
does not modify the project tracker, matcher, exporter, or VINS backend.  It
uses the frozen B1 KLT carrier and replaces only GFTT replenishment with
detector-only SuperPoint births.

The reference feature bag supplies only the publication contract (feature
topic, headers, record stamps, and the non-feature stream).  Its feature IDs,
pixels, matches, and channels are never used.  Raw frame 0 initializes tracks;
all raw frames are preprocessed, tracked, and replenished; raw frames 1, 3, ...
are published and must join the reference schedule exactly.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass, field
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import secrets
import struct
import sys
import time
from typing import Callable, Mapping, Sequence

# Absolute-path CLI execution adds only ``scripts/`` to sys.path.  Bootstrap
# the repository root before importing the in-tree ``uw_frontend`` package;
# callers must not need to inject the workspace through PYTHONPATH.
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import cv2
from geometry_msgs.msg import Point32
import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32, PointCloud
import yaml

from uw_frontend.quality.image_quality import score_image_quality


FEATURE_TOPIC_DEFAULT = "/feature_tracker/feature"
SUPERPOINT_REPO = WORKSPACE_ROOT / "external_tools" / "LightGlue"
SUPERPOINT_SOURCE = SUPERPOINT_REPO / "lightglue" / "superpoint.py"
SUPERPOINT_UTILS_SOURCE = SUPERPOINT_REPO / "lightglue" / "utils.py"
KLT_REFERENCE_SOURCE = WORKSPACE_ROOT / "uw_frontend" / "tracking" / "klt_tracker.py"
QUALITY_REFERENCE_SOURCE = (
    WORKSPACE_ROOT / "uw_frontend" / "quality" / "image_quality.py"
)
SUPERPOINT_WEIGHT = (
    Path.home() / ".cache" / "torch" / "hub" / "checkpoints" / "superpoint_v1.pth"
)
SUPERPOINT_WEIGHT_SIZE = 5_206_086
SUPERPOINT_WEIGHT_SHA256 = (
    "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e"
)

# Frozen method-level contract.  Code 10 is the repository's formal
# SuperPoint/LightGlue/learned source enum; continuations retain their learned
# birth provenance even though LK alone carries their persistent identity.
SUPERPOINT_LK_SOURCE_CODE = 10
SUPERPOINT_MAX_KEYPOINTS = 2048
SUPERPOINT_RESIZE = 1024
FEATURE_CAP = 350
MIN_DISTANCE_PX = 18.0
BORDER_PX = 8
PUBLISHED_EVERY_N = 2
PUBLISHED_FRAME_OFFSET = 1
LK_WIN_SIZE = (21, 21)
LK_MAX_LEVEL = 3
LK_CRITERIA_COUNT = 30
LK_CRITERIA_EPS = 0.01
LK_MIN_EIG_THRESHOLD = 1e-4
LK_FB_MAX_PX = 1.0
NCC_MIN = 0.65
NCC_PATCH_RADIUS = 5
PREPROCESS_MODE = "adaptive_clahe"

CHANNEL_NAMES = (
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
)

# Formal eligibility is provenance, not a detector-supplied claim.  These
# module-private sentinels let the two production CLIs attest that they created
# their frozen detector factory.  Ordinary Python API calls cannot become
# formal merely by returning a persuasive artifact_metadata() identity.
_CLI_PRODUCTION_FACTORY_TOKEN = object()
_WRAPPED_CLI_PRODUCTION_FACTORY_TOKEN = object()
_WRAPPED_PYTHON_FACTORY_TOKEN = object()


@dataclass(frozen=True)
class ScheduleFrame:
    header: object
    header_stamp_ns: int
    record_stamp_ns: int


@dataclass(frozen=True)
class RawFrame:
    header_stamp_ns: int
    image: np.ndarray


@dataclass(frozen=True)
class PublishedFrame:
    ids: np.ndarray
    pixels: np.ndarray
    ages: np.ndarray


@dataclass
class CarrierState:
    points: np.ndarray
    ids: np.ndarray
    ages: np.ndarray
    next_id: int

    @classmethod
    def empty(cls) -> "CarrierState":
        return cls(
            points=np.empty((0, 2), dtype=np.float32),
            ids=np.empty((0,), dtype=np.int64),
            ages=np.empty((0,), dtype=np.int32),
            next_id=0,
        )


@dataclass(frozen=True)
class TrackResult:
    points: np.ndarray
    valid: np.ndarray
    fb_errors: np.ndarray
    ncc_scores: np.ndarray


@dataclass(frozen=True)
class RawStepDiagnostics:
    raw_index: int
    header_stamp_ns: int
    published: bool
    adaptive_clahe_applied: bool
    tracked_before: int
    tracked_after: int
    dropped: int
    detector_candidates: int
    births: int
    output_tracks: int
    fb_median_px: float
    fb_p95_px: float
    ncc_median: float


@dataclass(frozen=True)
class CarrierRun:
    published_frames: list[PublishedFrame]
    raw_diagnostics: list[RawStepDiagnostics]


@dataclass(frozen=True)
class DetectorMethodSpec:
    """Detector-specific identity layered over the frozen LK carrier.

    The carrier, preprocessing, publication schedule, and feature schema stay
    shared.  A method spec controls only the learned birth proposal source and
    the provenance fields needed to distinguish formal comparison arms.
    """

    algorithm_name: str
    detector_key: str
    detector_contract: Mapping[str, object]
    source_code: int
    max_candidates: int
    manifest_schema_version: str
    detector_factory: Callable[[], object]
    entrypoint_source: Path
    static_code_artifacts: tuple[tuple[str, Path], ...]
    production_detector_identity: str

    def validate(self) -> None:
        if not self.algorithm_name or not self.detector_key:
            raise ValueError("method spec algorithm_name/detector_key must be nonempty")
        if not isinstance(self.source_code, int) or isinstance(self.source_code, bool):
            raise ValueError("method spec source_code must be an integer")
        if self.max_candidates <= 0:
            raise ValueError("method spec max_candidates must be positive")
        if not self.manifest_schema_version:
            raise ValueError("method spec manifest_schema_version must be nonempty")
        if not callable(self.detector_factory):
            raise ValueError("method spec detector_factory must be callable")
        labels = [str(label) for label, _path in self.static_code_artifacts]
        if any(not label for label in labels) or len(labels) != len(set(labels)):
            raise ValueError("method spec artifact labels must be unique and nonempty")


@dataclass
class ExportRuntimeProfiler:
    """Optional manifest profiler used by comparison wrappers, never by default."""

    required_stages: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    started_at: float = field(default_factory=time.perf_counter)
    samples_ms: dict[str, list[float]] = field(default_factory=dict)

    def measure(self, stage: str, function: Callable, *args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.samples_ms.setdefault(str(stage), []).append(elapsed_ms)

    @staticmethod
    def _distribution(samples_ms: Sequence[float]) -> dict[str, object]:
        values = np.asarray(samples_ms, dtype=np.float64).reshape(-1)
        if len(values) == 0:
            return {
                "count": 0,
                "median_ms": None,
                "p90_ms": None,
                "total_ms": 0.0,
            }
        return {
            "count": int(len(values)),
            "median_ms": float(np.median(values)),
            "p90_ms": float(np.percentile(values, 90)),
            "total_ms": float(np.sum(values)),
        }

    def snapshot(self) -> dict[str, object]:
        names = sorted(set(self.required_stages) | set(self.samples_ms))
        return {
            "clock": "time.perf_counter",
            "component_profiler": True,
            "profiled_wall_ms": (time.perf_counter() - self.started_at) * 1000.0,
            "stages": {
                name: self._distribution(self.samples_ms.get(name, ()))
                for name in names
            },
            "scope": (
                "wrapper entry through candidate validation and artifact collection; "
                "bag_io includes schedule/raw reads, nonfeature digests, candidate "
                "write, schedule verification, output-bag hashing, and whole-file "
                "SHA256 reads of the source and raw bags; excludes manifest "
                "serialization and final renames"
            ),
            "notes": list(self.notes),
        }


def _message_bytes(message) -> bytes:
    buffer = io.BytesIO()
    message.serialize(buffer)
    return buffer.getvalue()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_metadata(path: Path, *, reported_path: Path | None = None) -> dict[str, object]:
    path = Path(path)
    return {
        "path": str(reported_path if reported_path is not None else path),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
    }


def _canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _percentile(values: np.ndarray, percentile: float) -> float:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return float("nan")
    return float(np.percentile(values, percentile))


def _algorithm_contract(
    method_spec: DetectorMethodSpec | None = None,
) -> dict[str, object]:
    if method_spec is None:
        method_spec = SUPERPOINT_METHOD_SPEC
    method_spec.validate()
    contract = {
        "name": method_spec.algorithm_name,
        "method_family": "learned_detector_births_plus_lk_persistent_ids",
        "preprocess": {
            "mode": PREPROCESS_MODE,
            "quality_gate_source": "raw",
            "clahe_clip_limit": 2.0,
            "clahe_tile_grid": [8, 8],
            "gate": {
                "contrast_score_lt": 0.72,
                "grid_texture_score_lt": 0.58,
                "illumination_nonuniformity_gt": 0.18,
                "degradation_score_gt": 0.42,
                "logic": "any",
            },
        },
        "carrier": {
            "process_skipped_frames": True,
            "published_every_n": PUBLISHED_EVERY_N,
            "published_frame_offset": PUBLISHED_FRAME_OFFSET,
            "feature_cap": FEATURE_CAP,
            "survivor_order": "age_desc_then_id_asc",
            "birth_min_distance_px": MIN_DISTANCE_PX,
            "border_px": BORDER_PX,
            "id_policy": "fresh_monotonic_no_reuse_no_revival",
            "lk_win_size": list(LK_WIN_SIZE),
            "lk_max_level": LK_MAX_LEVEL,
            "lk_criteria_count": LK_CRITERIA_COUNT,
            "lk_criteria_eps": LK_CRITERIA_EPS,
            "lk_min_eig_threshold": LK_MIN_EIG_THRESHOLD,
            "forward_backward_max_px": LK_FB_MAX_PX,
            "ncc_min": NCC_MIN,
            "ncc_patch_radius": NCC_PATCH_RADIUS,
        },
        "publication": {
            "schedule": "reference_feature_header_and_record_stamp_exact",
            "source_feature_observations_reused": False,
            "normalized": (
                "camera_model_dispatch_from_yaml:"
                "pinhole=cv2.undistortPoints,"
                "kannala_brandt=cv2.fisheye.undistortPoints"
            ),
            "supported_camera_models": ["PINHOLE", "KANNALA_BRANDT"],
            "velocity": "adjacent_published_normalized_delta_over_header_dt",
            "birth_velocity": 0.0,
            "quality": 1.0,
            "sigma": 1.0,
            "source_code": method_spec.source_code,
            "is_learned": 1,
        },
    }
    contract[method_spec.detector_key] = copy.deepcopy(
        dict(method_spec.detector_contract)
    )
    return contract


def adaptive_clahe(
    gray: np.ndarray,
    *,
    quality_scorer: Callable[[np.ndarray], object] = score_image_quality,
    clahe_factory: Callable[..., object] = cv2.createCLAHE,
) -> tuple[np.ndarray, bool]:
    """Mirror ``export_vins_features._preprocess_gray(..., adaptive_clahe)``."""

    gray = np.asarray(gray, dtype=np.uint8)
    if gray.ndim != 2:
        raise ValueError("adaptive_clahe expects a grayscale image")
    quality = quality_scorer(gray)
    should_enhance = (
        float(quality.contrast_score) < 0.72
        or float(quality.grid_texture_score) < 0.58
        or float(quality.illumination_nonuniformity) > 0.18
        or float(quality.degradation_score) > 0.42
    )
    if not should_enhance:
        return gray, False
    enhanced = clahe_factory(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return np.asarray(enhanced, dtype=np.uint8), True


class SuperPointDetector:
    """Lazy, detector-only adapter for the vendored LightGlue SuperPoint model."""

    def __init__(self) -> None:
        self._torch = None
        self._extractor = None
        self._device = None

    def _validate_weight(self) -> None:
        if not SUPERPOINT_WEIGHT.is_file():
            raise FileNotFoundError(
                "frozen SuperPoint weight is missing; refusing an implicit download: "
                f"{SUPERPOINT_WEIGHT}"
            )
        if SUPERPOINT_WEIGHT.stat().st_size != SUPERPOINT_WEIGHT_SIZE:
            raise RuntimeError(
                "SuperPoint weight size mismatch: "
                f"{SUPERPOINT_WEIGHT.stat().st_size} != {SUPERPOINT_WEIGHT_SIZE}"
            )
        digest = _sha256_file(SUPERPOINT_WEIGHT)
        if digest != SUPERPOINT_WEIGHT_SHA256:
            raise RuntimeError(
                f"SuperPoint weight SHA256 mismatch: {digest} != {SUPERPOINT_WEIGHT_SHA256}"
            )

    def _load(self) -> None:
        if self._extractor is not None:
            return
        self._validate_weight()
        if not SUPERPOINT_SOURCE.is_file():
            raise FileNotFoundError(f"missing vendored SuperPoint source: {SUPERPOINT_SOURCE}")
        repo = str(SUPERPOINT_REPO.resolve())
        if repo not in sys.path:
            sys.path.insert(0, repo)
        torch = importlib.import_module("torch")
        lightglue = importlib.import_module("lightglue")
        # Deliberately access only SuperPoint.  No matcher is instantiated.
        extractor = lightglue.SuperPoint(
            max_num_keypoints=SUPERPOINT_MAX_KEYPOINTS
        ).eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._torch = torch
        self._extractor = extractor.to(device)
        self._device = device

    def detect(self, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self._load()
        assert self._torch is not None and self._extractor is not None
        gray = np.asarray(gray, dtype=np.uint8)
        if gray.ndim != 2:
            raise ValueError("SuperPoint detector expects a grayscale image")
        tensor = self._torch.from_numpy(
            gray.astype(np.float32) / np.float32(255.0)
        )[None, None].to(self._device)
        with self._torch.no_grad():
            features = self._extractor.extract(tensor, resize=SUPERPOINT_RESIZE)
        points = features["keypoints"][0].detach().cpu().numpy().astype(np.float32)
        scores = (
            features["keypoint_scores"][0]
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        return _validated_candidates(points, scores)

    def artifact_metadata(self) -> dict[str, object]:
        self._load()
        return {
            "identity": "LightGlue_repository_SuperPoint_detector_only",
            "weight": _file_metadata(SUPERPOINT_WEIGHT),
            "source": _file_metadata(SUPERPOINT_SOURCE),
            "coordinate_mapping_source": _file_metadata(SUPERPOINT_UTILS_SOURCE),
            "runtime": {
                "device": str(self._device),
                "torch_version": str(getattr(self._torch, "__version__", "unknown")),
                "opencv_version": str(cv2.__version__),
                "numpy_version": str(np.__version__),
            },
        }


SUPERPOINT_METHOD_SPEC = DetectorMethodSpec(
    algorithm_name="superpoint_detector_raw_frame_lk_carrier_v1",
    detector_key="superpoint",
    detector_contract={
        "detector_only": True,
        "matcher": None,
        "max_keypoints": SUPERPOINT_MAX_KEYPOINTS,
        "resize": SUPERPOINT_RESIZE,
        "score_order": "descending_stable_input_index_tiebreak",
    },
    source_code=SUPERPOINT_LK_SOURCE_CODE,
    max_candidates=SUPERPOINT_MAX_KEYPOINTS,
    manifest_schema_version="superpoint-lk-carrier-export-v1",
    detector_factory=SuperPointDetector,
    entrypoint_source=Path(__file__).resolve(),
    static_code_artifacts=(
        ("superpoint_source", SUPERPOINT_SOURCE),
        ("superpoint_coordinate_mapping_source", SUPERPOINT_UTILS_SOURCE),
    ),
    production_detector_identity="LightGlue_repository_SuperPoint_detector_only",
)


def _validated_candidates(
    points: np.ndarray,
    scores: np.ndarray,
    max_candidates: int = SUPERPOINT_MAX_KEYPOINTS,
) -> tuple[np.ndarray, np.ndarray]:
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    points = np.asarray(points, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    if points.size == 0:
        points = np.empty((0, 2), dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError(f"detector points must have shape (N,2), got {points.shape}")
    if len(points) != len(scores):
        raise ValueError(
            f"detector point/score count mismatch: {len(points)} != {len(scores)}"
        )
    if len(points) > max_candidates:
        raise ValueError(
            f"detector exceeded method max_candidates={max_candidates}"
        )
    if not np.all(np.isfinite(points)) or not np.all(np.isfinite(scores)):
        raise ValueError("detector returned non-finite points or scores")
    return points, scores


def _patch_ncc(
    previous: np.ndarray,
    current: np.ndarray,
    previous_points: np.ndarray,
    current_points: np.ndarray,
    radius: int = NCC_PATCH_RADIUS,
) -> np.ndarray:
    scores = np.zeros((len(previous_points),), dtype=np.float32)
    height, width = previous.shape[:2]
    for index, ((x0, y0), (x1, y1)) in enumerate(
        zip(previous_points, current_points)
    ):
        ix0, iy0 = int(round(float(x0))), int(round(float(y0)))
        ix1, iy1 = int(round(float(x1))), int(round(float(y1)))
        if (
            ix0 - radius < 0
            or iy0 - radius < 0
            or ix0 + radius + 1 > width
            or iy0 + radius + 1 > height
            or ix1 - radius < 0
            or iy1 - radius < 0
            or ix1 + radius + 1 > width
            or iy1 + radius + 1 > height
        ):
            continue
        patch0 = previous[
            iy0 - radius : iy0 + radius + 1,
            ix0 - radius : ix0 + radius + 1,
        ].astype(np.float32)
        patch1 = current[
            iy1 - radius : iy1 + radius + 1,
            ix1 - radius : ix1 + radius + 1,
        ].astype(np.float32)
        patch0 -= np.mean(patch0)
        patch1 -= np.mean(patch1)
        denominator = float(np.linalg.norm(patch0) * np.linalg.norm(patch1))
        if denominator > 1e-6:
            scores[index] = float(
                np.clip(np.sum(patch0 * patch1) / denominator, -1.0, 1.0)
            )
    return scores


def _in_border(points: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape[:2]
    return (
        (points[:, 0] >= BORDER_PX)
        & (points[:, 0] < width - BORDER_PX)
        & (points[:, 1] >= BORDER_PX)
        & (points[:, 1] < height - BORDER_PX)
    )


def track_points_lk(
    previous: np.ndarray,
    current: np.ndarray,
    points: np.ndarray,
    *,
    flow: Callable = cv2.calcOpticalFlowPyrLK,
    ncc_function: Callable = _patch_ncc,
) -> TrackResult:
    """Track one raw-frame step with the exact frozen B1 LK/NCC gates."""

    points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    count = len(points)
    if count == 0:
        return TrackResult(
            points=np.empty((0, 2), dtype=np.float32),
            valid=np.empty((0,), dtype=bool),
            fb_errors=np.empty((0,), dtype=np.float32),
            ncc_scores=np.empty((0,), dtype=np.float32),
        )
    previous_cv = points.reshape(-1, 1, 2)
    parameters = {
        "winSize": LK_WIN_SIZE,
        "maxLevel": LK_MAX_LEVEL,
        "criteria": (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            LK_CRITERIA_COUNT,
            LK_CRITERIA_EPS,
        ),
        "minEigThreshold": LK_MIN_EIG_THRESHOLD,
    }
    forward, forward_status, _ = flow(
        previous, current, previous_cv, None, **parameters
    )
    if forward is None or forward_status is None:
        return TrackResult(
            points=np.full((count, 2), np.nan, dtype=np.float32),
            valid=np.zeros((count,), dtype=bool),
            fb_errors=np.full((count,), np.inf, dtype=np.float32),
            ncc_scores=np.full((count,), -1.0, dtype=np.float32),
        )
    forward = np.asarray(forward, dtype=np.float32).reshape(-1, 2)
    forward_status = np.asarray(forward_status).reshape(-1)
    if len(forward) != count or len(forward_status) != count:
        raise ValueError("LK forward result length changed")
    backward, backward_status, _ = flow(
        current, previous, forward.reshape(-1, 1, 2), None, **parameters
    )
    if backward is None or backward_status is None:
        backward = np.full((count, 2), np.nan, dtype=np.float32)
        backward_status = np.zeros((count,), dtype=np.uint8)
    else:
        backward = np.asarray(backward, dtype=np.float32).reshape(-1, 2)
        backward_status = np.asarray(backward_status).reshape(-1)
        if len(backward) != count or len(backward_status) != count:
            raise ValueError("LK backward result length changed")
    fb_errors = np.linalg.norm(backward - points, axis=1).astype(np.float32)
    ncc = np.asarray(
        ncc_function(previous, current, points, forward, NCC_PATCH_RADIUS),
        dtype=np.float32,
    ).reshape(-1)
    if len(ncc) != count:
        raise ValueError("NCC result length changed")
    finite = (
        np.all(np.isfinite(forward), axis=1)
        & np.all(np.isfinite(backward), axis=1)
        & np.isfinite(fb_errors)
        & np.isfinite(ncc)
    )
    valid = (
        (forward_status > 0)
        & (backward_status > 0)
        & finite
        & (fb_errors <= LK_FB_MAX_PX)
        & (ncc >= NCC_MIN)
        & _in_border(forward, current.shape)
    )
    return TrackResult(forward, valid.astype(bool), fb_errors, ncc)


def _sort_survivors(state: CarrierState) -> None:
    if len(state.ids) <= 1:
        return
    order = np.lexsort((state.ids, -state.ages.astype(np.int64)))
    state.points = state.points[order].astype(np.float32)
    state.ids = state.ids[order].astype(np.int64)
    state.ages = state.ages[order].astype(np.int32)


def advance_state(
    state: CarrierState,
    previous: np.ndarray,
    current: np.ndarray,
    *,
    tracker: Callable[[np.ndarray, np.ndarray, np.ndarray], TrackResult] = track_points_lk,
) -> TrackResult:
    result = tracker(previous, current, state.points.copy())
    valid = np.asarray(result.valid, dtype=bool).reshape(-1)
    points = np.asarray(result.points, dtype=np.float32).reshape(-1, 2)
    if len(valid) != len(state.ids) or len(points) != len(state.ids):
        raise ValueError("tracker result does not match carrier state")
    state.points = points[valid].astype(np.float32)
    state.ids = state.ids[valid].astype(np.int64)
    state.ages = (state.ages[valid] + 1).astype(np.int32)
    _sort_survivors(state)
    return result


def select_births(
    candidates: np.ndarray,
    scores: np.ndarray,
    occupied: np.ndarray,
    image_shape: tuple[int, int],
    slots: int,
    max_candidates: int = SUPERPOINT_MAX_KEYPOINTS,
) -> np.ndarray:
    """Select score-ordered, border-safe, 18 px separated detector births."""

    candidates, scores = _validated_candidates(
        candidates, scores, max_candidates=max_candidates
    )
    occupied = np.asarray(occupied, dtype=np.float32).reshape(-1, 2)
    if not np.all(np.isfinite(occupied)):
        raise ValueError("occupied track coordinates must be finite")
    if slots <= 0 or len(candidates) == 0:
        return np.empty((0, 2), dtype=np.float32)
    height, width = image_shape[:2]
    # Stable input-index tie break is explicit and independent of NumPy sort kind.
    order = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))
    selected: list[np.ndarray] = []
    min_distance_squared = MIN_DISTANCE_PX * MIN_DISTANCE_PX
    for index in order:
        point = candidates[index]
        x, y = float(point[0]), float(point[1])
        if not (
            x >= BORDER_PX
            and x < width - BORDER_PX
            and y >= BORDER_PX
            and y < height - BORDER_PX
        ):
            continue
        if len(occupied):
            distance_squared = np.sum((occupied - point) ** 2, axis=1)
            if bool(np.any(distance_squared < min_distance_squared)):
                continue
        if selected:
            selected_array = np.asarray(selected, dtype=np.float32)
            distance_squared = np.sum((selected_array - point) ** 2, axis=1)
            if bool(np.any(distance_squared < min_distance_squared)):
                continue
        selected.append(point.copy())
        if len(selected) >= slots:
            break
    if not selected:
        return np.empty((0, 2), dtype=np.float32)
    return np.asarray(selected, dtype=np.float32).reshape(-1, 2)


def replenish_state(
    state: CarrierState,
    image: np.ndarray,
    detector,
    *,
    max_candidates: int = SUPERPOINT_MAX_KEYPOINTS,
) -> tuple[int, int]:
    if len(state.ids) > FEATURE_CAP:
        raise ValueError(f"carrier state exceeds feature cap {FEATURE_CAP}")
    slots = FEATURE_CAP - len(state.ids)
    if slots <= 0:
        return 0, 0
    candidates, scores = detector.detect(image)
    candidates, scores = _validated_candidates(
        candidates, scores, max_candidates=max_candidates
    )
    births = select_births(
        candidates,
        scores,
        state.points,
        image.shape,
        slots,
        max_candidates=max_candidates,
    )
    count = len(births)
    if count:
        new_ids = np.arange(state.next_id, state.next_id + count, dtype=np.int64)
        state.next_id += count
        state.points = np.vstack((state.points, births)).astype(np.float32)
        state.ids = np.concatenate((state.ids, new_ids)).astype(np.int64)
        state.ages = np.concatenate(
            (state.ages, np.ones((count,), dtype=np.int32))
        )
        _sort_survivors(state)
    return len(candidates), count


def _schedule_raw_indices(
    schedule: Sequence[ScheduleFrame], raw_frames: Sequence[RawFrame]
) -> np.ndarray:
    if not schedule:
        raise ValueError("publication schedule must not be empty")
    if not raw_frames:
        raise ValueError("raw frames must not be empty")
    raw_stamps = np.asarray([frame.header_stamp_ns for frame in raw_frames], dtype=np.int64)
    if np.any(np.diff(raw_stamps) <= 0):
        raise ValueError("raw image header stamps must be strictly increasing")
    index_by_stamp = {int(value): index for index, value in enumerate(raw_stamps)}
    indices = []
    for frame in schedule:
        if frame.header_stamp_ns not in index_by_stamp:
            raise ValueError(
                "reference feature header stamp has no exact raw-image join: "
                f"{frame.header_stamp_ns}"
            )
        indices.append(index_by_stamp[frame.header_stamp_ns])
    result = np.asarray(indices, dtype=np.int64)
    if result[0] != PUBLISHED_FRAME_OFFSET:
        raise ValueError(
            "superpoint-LK v1 requires raw frame 0 initialization and first "
            f"publication at raw index {PUBLISHED_FRAME_OFFSET}; got {result[0]}"
        )
    if len(result) > 1 and not np.all(np.diff(result) == PUBLISHED_EVERY_N):
        raise ValueError(
            "reference schedule is not exact raw frames 1,3,...; observed raw "
            f"strides={np.unique(np.diff(result)).tolist()}"
        )
    expected = np.arange(
        PUBLISHED_FRAME_OFFSET,
        PUBLISHED_FRAME_OFFSET + PUBLISHED_EVERY_N * len(result),
        PUBLISHED_EVERY_N,
        dtype=np.int64,
    )
    if not np.array_equal(result, expected):
        raise ValueError("reference publication schedule does not match every2/offset1")
    if int(result[-1]) != len(raw_frames) - 1:
        raise ValueError("raw-frame slice must end at the last reference publication")
    return result


def run_carrier(
    schedule: Sequence[ScheduleFrame],
    raw_frames: Sequence[RawFrame],
    detector,
    *,
    tracker: Callable[[np.ndarray, np.ndarray, np.ndarray], TrackResult] = track_points_lk,
    preprocess: Callable[[np.ndarray], tuple[np.ndarray, bool]] = adaptive_clahe,
    max_candidates: int = SUPERPOINT_MAX_KEYPOINTS,
) -> CarrierRun:
    publish_indices = _schedule_raw_indices(schedule, raw_frames)
    schedule_by_raw = {
        int(raw_index): schedule_index
        for schedule_index, raw_index in enumerate(publish_indices)
    }
    state = CarrierState.empty()
    published: list[PublishedFrame] = []
    diagnostics: list[RawStepDiagnostics] = []
    previous_processed = None
    for raw_index, raw_frame in enumerate(raw_frames):
        processed, enhanced = preprocess(raw_frame.image)
        processed = np.asarray(processed, dtype=np.uint8)
        if processed.ndim != 2 or processed.shape != raw_frame.image.shape:
            raise ValueError("preprocessing must preserve the grayscale image shape")
        tracked_before = len(state.ids)
        tracked_after = tracked_before
        fb = np.empty((0,), dtype=np.float32)
        ncc = np.empty((0,), dtype=np.float32)
        if previous_processed is not None:
            track_result = advance_state(
                state,
                previous_processed,
                processed,
                tracker=tracker,
            )
            tracked_after = len(state.ids)
            valid = np.asarray(track_result.valid, dtype=bool)
            fb = np.asarray(track_result.fb_errors, dtype=np.float32)[valid]
            ncc = np.asarray(track_result.ncc_scores, dtype=np.float32)[valid]
        candidate_count, births = replenish_state(
            state,
            processed,
            detector,
            max_candidates=max_candidates,
        )
        is_published = raw_index in schedule_by_raw
        if is_published:
            if len(np.unique(state.ids)) != len(state.ids):
                raise AssertionError("carrier produced duplicate IDs")
            published.append(
                PublishedFrame(
                    ids=state.ids.copy(),
                    pixels=state.points.copy(),
                    ages=state.ages.copy(),
                )
            )
        diagnostics.append(
            RawStepDiagnostics(
                raw_index=raw_index,
                header_stamp_ns=raw_frame.header_stamp_ns,
                published=is_published,
                adaptive_clahe_applied=bool(enhanced),
                tracked_before=tracked_before,
                tracked_after=tracked_after,
                dropped=tracked_before - tracked_after,
                detector_candidates=candidate_count,
                births=births,
                output_tracks=len(state.ids),
                fb_median_px=_percentile(fb, 50.0),
                fb_p95_px=_percentile(fb, 95.0),
                ncc_median=_percentile(ncc, 50.0),
            )
        )
        previous_processed = processed.copy()
    if len(published) != len(schedule):
        raise AssertionError(
            f"published {len(published)} frames for {len(schedule)} schedule entries"
        )
    return CarrierRun(published, diagnostics)


def _mono8_image(message) -> np.ndarray:
    encoding = str(getattr(message, "encoding", "")).lower()
    if encoding not in {"mono8", "8uc1"}:
        raise ValueError(
            "superpoint-LK v1 requires mono8/8UC1 raw images, got "
            f"encoding={encoding!r}"
        )
    height = int(message.height)
    width = int(message.width)
    step = int(message.step)
    if height <= 0 or width <= 0 or step < width:
        raise ValueError(f"invalid raw image geometry: {width}x{height}, step={step}")
    raw = np.frombuffer(message.data, dtype=np.uint8)
    required = height * step
    if raw.size < required:
        raise ValueError(f"truncated image payload: {raw.size} < {required}")
    return raw[:required].reshape(height, step)[:, :width].copy()


def read_source_schedule(
    source_bag: Path,
    feature_topic: str,
    max_published_frames: int | None,
) -> tuple[list[ScheduleFrame], int]:
    if max_published_frames is not None and max_published_frames <= 0:
        raise ValueError("max_published_frames must be a positive integer")
    all_frames: list[ScheduleFrame] = []
    with rosbag.Bag(str(source_bag), "r") as bag:
        for _topic, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            if getattr(message, "_type", "") != "sensor_msgs/PointCloud":
                raise ValueError(
                    f"feature topic must contain sensor_msgs/PointCloud, got "
                    f"{getattr(message, '_type', '')!r}"
                )
            header_stamp_ns = int(message.header.stamp.to_nsec())
            record_stamp_ns = int(record_stamp.to_nsec())
            if header_stamp_ns <= 0 or record_stamp_ns <= 0:
                raise ValueError("feature header and record stamps must be positive")
            all_frames.append(
                ScheduleFrame(
                    header=copy.deepcopy(message.header),
                    header_stamp_ns=header_stamp_ns,
                    record_stamp_ns=record_stamp_ns,
                )
            )
    if not all_frames:
        raise ValueError(f"no reference feature messages found on {feature_topic}")
    header_stamps = np.asarray(
        [frame.header_stamp_ns for frame in all_frames], dtype=np.int64
    )
    record_stamps = np.asarray(
        [frame.record_stamp_ns for frame in all_frames], dtype=np.int64
    )
    if np.any(np.diff(header_stamps) <= 0):
        raise ValueError("reference feature header stamps must be strictly increasing")
    if np.any(np.diff(record_stamps) <= 0):
        raise ValueError("reference feature record stamps must be strictly increasing")
    selected = (
        all_frames
        if max_published_frames is None
        else all_frames[:max_published_frames]
    )
    return selected, len(all_frames)


def read_raw_frames(
    raw_bag: Path,
    image_topic: str,
    first_published_stamp_ns: int,
    last_published_stamp_ns: int,
) -> list[RawFrame]:
    previous: RawFrame | None = None
    selected: list[RawFrame] = []
    last_seen_stamp = None
    with rosbag.Bag(str(raw_bag), "r") as bag:
        for _topic, message, _record_stamp in bag.read_messages(topics=[image_topic]):
            header_stamp_ns = int(message.header.stamp.to_nsec())
            if header_stamp_ns <= 0:
                raise ValueError("raw image header stamps must be positive")
            if last_seen_stamp is not None and header_stamp_ns <= last_seen_stamp:
                raise ValueError("raw image header stamps must be strictly increasing")
            last_seen_stamp = header_stamp_ns
            frame = RawFrame(header_stamp_ns, _mono8_image(message))
            if header_stamp_ns < first_published_stamp_ns:
                previous = frame
                continue
            if header_stamp_ns > last_published_stamp_ns:
                break
            if not selected:
                if previous is None:
                    raise ValueError(
                        "reference first publication has no preceding raw frame for "
                        "offset=1 initialization"
                    )
                selected.append(previous)
            selected.append(frame)
    if not selected:
        raise ValueError(f"no raw images found on {image_topic} for reference schedule")
    if selected[-1].header_stamp_ns != last_published_stamp_ns:
        raise ValueError("last reference publication has no exact raw-image join")
    return selected


def load_camera_model(camera_yaml: Path) -> tuple[np.ndarray, np.ndarray, str]:
    text = "\n".join(
        line
        for line in camera_yaml.read_text(encoding="utf-8").splitlines()
        if not line.startswith("%YAML:")
    )
    data = yaml.safe_load(text) or {}
    if "cam0" in data:
        data = data["cam0"]
    model = str(data.get("model_type", data.get("distortion_model", "PINHOLE"))).upper()
    projection = data.get("projection_parameters", {})
    if model in {"KANNALA_BRANDT", "EQUIDISTANT", "FISHEYE"}:
        try:
            fx, fy, cx, cy = (
                float(projection["mu"]),
                float(projection["mv"]),
                float(projection["u0"]),
                float(projection["v0"]),
            )
            distortion_values = [
                float(projection[name]) for name in ("k2", "k3", "k4", "k5")
            ]
        except KeyError as exc:
            raise ValueError(f"missing Kannala-Brandt parameter: {exc}") from exc
        camera_model = "kannala_brandt"
    elif model in {"PINHOLE", "PLUMB_BOB"}:
        camera_model = "pinhole"
    else:
        raise ValueError(f"unsupported camera model {model!r}")
    if camera_model == "kannala_brandt":
        if not all(np.isfinite([fx, fy, cx, cy])) or fx <= 0.0 or fy <= 0.0:
            raise ValueError("camera intrinsics must be finite with positive mu/mv")
        if not np.all(np.isfinite(distortion_values)):
            raise ValueError("Kannala-Brandt coefficients must be finite")
        camera_matrix = np.asarray(
            [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        return (
            camera_matrix,
            np.asarray(distortion_values, dtype=np.float64),
            camera_model,
        )
    if projection:
        try:
            fx, fy, cx, cy = (
                float(projection["fx"]),
                float(projection["fy"]),
                float(projection["cx"]),
                float(projection["cy"]),
            )
        except KeyError as exc:
            raise ValueError(f"missing pinhole projection parameter: {exc}") from exc
    else:
        intrinsics = data.get("intrinsics")
        if not isinstance(intrinsics, (list, tuple)) or len(intrinsics) != 4:
            raise ValueError("camera YAML lacks projection_parameters or 4 intrinsics")
        fx, fy, cx, cy = [float(value) for value in intrinsics]
    if not all(np.isfinite([fx, fy, cx, cy])) or fx <= 0.0 or fy <= 0.0:
        raise ValueError("camera intrinsics must be finite with positive fx/fy")
    distortion = data.get("distortion_parameters", {})
    if distortion:
        distortion_values = [
            float(distortion.get("k1", 0.0)),
            float(distortion.get("k2", 0.0)),
            float(distortion.get("p1", 0.0)),
            float(distortion.get("p2", 0.0)),
        ]
    else:
        distortion_values = data.get(
            "distortion_coeffs",
            data.get("distortion_coefficients", data.get("D", [0.0] * 4)),
        )
        if not isinstance(distortion_values, (list, tuple)) or len(distortion_values) < 4:
            raise ValueError("camera distortion vector must contain at least four values")
        distortion_values = [float(value) for value in distortion_values[:4]]
    if not np.all(np.isfinite(distortion_values)):
        raise ValueError("camera distortion coefficients must be finite")
    camera_matrix = np.asarray(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return camera_matrix, np.asarray(distortion_values, dtype=np.float64), camera_model


def load_pinhole_camera(camera_yaml: Path) -> tuple[np.ndarray, np.ndarray]:
    """Backward-compatible strict pinhole loader for callers outside this CLI."""

    camera_matrix, distortion, model = load_camera_model(camera_yaml)
    if model != "pinhole":
        raise ValueError(f"expected pinhole camera, got {model!r}")
    return camera_matrix, distortion


def normalized_frames(
    frames: Sequence[PublishedFrame],
    camera_matrix: np.ndarray,
    distortion: np.ndarray,
    camera_model: str = "pinhole",
) -> list[np.ndarray]:
    normalized = []
    for frame in frames:
        if len(frame.pixels) == 0:
            normalized.append(np.empty((0, 2), dtype=np.float32))
            continue
        pixels = np.asarray(frame.pixels, dtype=np.float32).reshape(-1, 1, 2)
        if camera_model == "pinhole":
            points = cv2.undistortPoints(
                pixels,
                camera_matrix,
                distortion,
            ).reshape(-1, 2)
        elif camera_model == "kannala_brandt":
            points = cv2.fisheye.undistortPoints(
                pixels,
                camera_matrix,
                distortion,
            ).reshape(-1, 2)
        else:
            raise ValueError(f"unsupported camera normalization model {camera_model!r}")
        if not np.all(np.isfinite(points)):
            raise ValueError("camera normalization produced non-finite coordinates")
        normalized.append(points.astype(np.float32))
    return normalized


def velocity_frames(
    schedule: Sequence[ScheduleFrame],
    frames: Sequence[PublishedFrame],
    normalized: Sequence[np.ndarray],
) -> list[np.ndarray]:
    if not (len(schedule) == len(frames) == len(normalized)):
        raise ValueError("schedule/frame/normalized lengths differ")
    velocities: list[np.ndarray] = []
    for index, frame in enumerate(frames):
        velocity = np.zeros_like(normalized[index], dtype=np.float32)
        if index:
            dt = (
                schedule[index].header_stamp_ns
                - schedule[index - 1].header_stamp_ns
            ) * 1e-9
            if not np.isfinite(dt) or dt <= 0.0:
                raise ValueError(f"non-positive published-frame dt at frame {index}: {dt}")
            previous_by_id = {
                int(feature_id): previous_index
                for previous_index, feature_id in enumerate(frames[index - 1].ids)
            }
            for current_index, feature_id in enumerate(frame.ids):
                previous_index = previous_by_id.get(int(feature_id))
                if previous_index is not None:
                    velocity[current_index] = (
                        normalized[index][current_index]
                        - normalized[index - 1][previous_index]
                    ) / float(dt)
        velocities.append(velocity)
    return velocities


def build_feature_message(
    schedule_frame: ScheduleFrame,
    frame: PublishedFrame,
    normalized: np.ndarray,
    velocities: np.ndarray,
    source_code: int = SUPERPOINT_LK_SOURCE_CODE,
) -> PointCloud:
    count = len(frame.ids)
    if not (
        frame.pixels.shape == (count, 2)
        and normalized.shape == (count, 2)
        and velocities.shape == (count, 2)
    ):
        raise ValueError("published feature arrays have inconsistent shapes")
    if count > FEATURE_CAP or len(np.unique(frame.ids)) != count:
        raise ValueError("published feature IDs violate uniqueness or cap")
    message = PointCloud()
    message.header = copy.deepcopy(schedule_frame.header)
    if int(message.header.stamp.to_nsec()) != schedule_frame.header_stamp_ns:
        raise ValueError("schedule header object/stamp mismatch")
    message.channels = [ChannelFloat32(name=name) for name in CHANNEL_NAMES]
    for index in range(count):
        message.points.append(
            Point32(
                float(normalized[index, 0]),
                float(normalized[index, 1]),
                1.0,
            )
        )
        values = (
            float(int(frame.ids[index])),
            0.0,
            float(frame.pixels[index, 0]),
            float(frame.pixels[index, 1]),
            float(velocities[index, 0]),
            float(velocities[index, 1]),
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            float(source_code),
            1.0,
        )
        for channel, value in zip(message.channels, values):
            channel.values.append(value)
    return message


def _nonfeature_digest(
    path: Path,
    feature_topic: str,
    cutoff_record_stamp_ns: int | None,
) -> dict[str, object]:
    global_digest = hashlib.sha256()
    topic_state: dict[str, dict[str, object]] = {}
    message_count = 0
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages():
            record_stamp_ns = int(stamp.to_nsec())
            if (
                cutoff_record_stamp_ns is not None
                and record_stamp_ns > cutoff_record_stamp_ns
            ):
                break
            if topic == feature_topic:
                continue
            raw = _message_bytes(message)
            prefix = topic.encode("utf-8") + b"\0" + struct.pack(
                "<qQ", record_stamp_ns, len(raw)
            )
            global_digest.update(prefix)
            global_digest.update(raw)
            state = topic_state.setdefault(
                topic, {"count": 0, "digest": hashlib.sha256()}
            )
            state["digest"].update(prefix)
            state["digest"].update(raw)
            state["count"] = int(state["count"]) + 1
            message_count += 1
    return {
        "message_count": message_count,
        "ordered_sha256": global_digest.hexdigest(),
        "topics": {
            topic: {
                "count": int(state["count"]),
                "sha256": state["digest"].hexdigest(),
            }
            for topic, state in sorted(topic_state.items())
        },
    }


def _write_candidate_bag(
    source_bag: Path,
    temporary_bag: Path,
    feature_topic: str,
    schedule: Sequence[ScheduleFrame],
    messages: Sequence[PointCloud],
    prefix_mode: bool,
) -> None:
    feature_index = 0
    cutoff = schedule[-1].record_stamp_ns if prefix_mode else None
    with rosbag.Bag(str(source_bag), "r") as source, rosbag.Bag(
        str(temporary_bag), "w"
    ) as output:
        for topic, message, record_stamp, connection_header in source.read_messages(
            return_connection_header=True
        ):
            record_stamp_ns = int(record_stamp.to_nsec())
            if cutoff is not None and record_stamp_ns > cutoff:
                break
            if topic == feature_topic:
                if feature_index >= len(schedule):
                    if prefix_mode:
                        continue
                    raise ValueError("reference bag contains unexpected extra feature frames")
                expected = schedule[feature_index]
                if (
                    int(message.header.stamp.to_nsec()) != expected.header_stamp_ns
                    or record_stamp_ns != expected.record_stamp_ns
                ):
                    raise ValueError(
                        f"reference feature schedule changed at frame {feature_index}"
                    )
                message = messages[feature_index]
                feature_index += 1
            output.write(
                topic,
                message,
                record_stamp,
                connection_header=connection_header,
            )
    if feature_index != len(schedule):
        raise ValueError(
            f"wrote {feature_index} feature frames, expected {len(schedule)}"
        )


def _verify_output_schedule(
    path: Path, feature_topic: str, schedule: Sequence[ScheduleFrame]
) -> None:
    observed = []
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            observed.append(
                (
                    int(message.header.stamp.to_nsec()),
                    int(record_stamp.to_nsec()),
                    int(message.header.seq),
                    str(message.header.frame_id),
                )
            )
    expected = [
        (
            frame.header_stamp_ns,
            frame.record_stamp_ns,
            int(frame.header.seq),
            str(frame.header.frame_id),
        )
        for frame in schedule
    ]
    if observed != expected:
        raise RuntimeError("candidate feature header/record schedule is not reference-exact")


def _reserve_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    os.close(descriptor)


def _temporary_path(final_path: Path) -> Path:
    return final_path.with_name(
        f".{final_path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )


def _detector_artifacts(
    detector, method_spec: DetectorMethodSpec = SUPERPOINT_METHOD_SPEC
) -> dict[str, object]:
    metadata = getattr(detector, "artifact_metadata", None)
    if callable(metadata):
        result = metadata()
        if not isinstance(result, dict):
            raise ValueError("detector artifact_metadata() must return a dict")
        return result
    return {
        "identity": f"injected_detector:{type(detector).__module__}.{type(detector).__name__}",
        "note": (
            "dependency-injected detector; production CLI identity is "
            f"{method_spec.production_detector_identity}"
        ),
    }


def _code_artifacts(
    method_spec: DetectorMethodSpec,
    detector,
) -> dict[str, object]:
    method_spec.validate()
    protected_labels = {
        "exporter",
        "carrier_base",
        "klt_reference_source",
        "quality_reference_source",
        "detector",
    }
    labels = {label for label, _path in method_spec.static_code_artifacts}
    overlap = protected_labels & labels
    if overlap:
        raise ValueError(
            f"method spec uses reserved artifact labels: {sorted(overlap)}"
        )
    entrypoint = Path(method_spec.entrypoint_source).resolve()
    carrier_base = Path(__file__).resolve()
    result: dict[str, object] = {
        "exporter": _file_metadata(entrypoint),
    }
    if entrypoint != carrier_base:
        result["carrier_base"] = _file_metadata(carrier_base)
    for label, path in method_spec.static_code_artifacts:
        result[str(label)] = _file_metadata(Path(path).resolve())
    result.update(
        {
            "klt_reference_source": _file_metadata(KLT_REFERENCE_SOURCE),
            "quality_reference_source": _file_metadata(QUALITY_REFERENCE_SOURCE),
            "detector": _detector_artifacts(detector, method_spec),
        }
    )
    return result


def _detector_origin(
    detector_was_supplied: bool,
    *,
    cli_production_factory_token: object | None,
    wrapped_factory_token: object | None,
) -> str:
    if (
        not detector_was_supplied
        and cli_production_factory_token is _CLI_PRODUCTION_FACTORY_TOKEN
        and wrapped_factory_token is None
    ):
        return "cli_production_factory"
    if (
        detector_was_supplied
        and cli_production_factory_token is None
        and wrapped_factory_token is _WRAPPED_CLI_PRODUCTION_FACTORY_TOKEN
    ):
        return "cli_production_factory"
    if (
        detector_was_supplied
        and cli_production_factory_token is None
        and wrapped_factory_token is _WRAPPED_PYTHON_FACTORY_TOKEN
    ):
        return "python_api_production_factory"
    if cli_production_factory_token is not None or wrapped_factory_token is not None:
        raise ValueError("invalid internal detector provenance token combination")
    return (
        "python_api_injected_detector"
        if detector_was_supplied
        else "python_api_production_factory"
    )


def _formal_eligibility(
    *,
    prefix_mode: bool,
    detector_origin: str,
) -> tuple[bool, str]:
    if prefix_mode:
        return False, "explicit_prefix_is_nonformal"
    if detector_origin == "cli_production_factory":
        return True, "full_export_from_frozen_cli_production_factory"
    if detector_origin == "python_api_injected_detector":
        return False, "python_api_injected_detector_is_nonformal"
    if detector_origin == "python_api_production_factory":
        return False, "only_cli_production_factory_full_exports_are_formal"
    raise AssertionError(f"unknown detector origin {detector_origin!r}")


def export_bag(
    source_feature_bag: str | Path,
    raw_image_bag: str | Path,
    camera_yaml: str | Path,
    output_bag: str | Path,
    *,
    image_topic: str,
    feature_topic: str = FEATURE_TOPIC_DEFAULT,
    max_published_frames: int | None = None,
    manifest_json: str | Path | None = None,
    detector=None,
    tracker: Callable[[np.ndarray, np.ndarray, np.ndarray], TrackResult] = track_points_lk,
    preprocess: Callable[[np.ndarray], tuple[np.ndarray, bool]] = adaptive_clahe,
    method_spec: DetectorMethodSpec = SUPERPOINT_METHOD_SPEC,
    runtime_profiler: ExportRuntimeProfiler | None = None,
    _cli_production_factory_token: object | None = None,
    _wrapped_factory_token: object | None = None,
) -> dict[str, object]:
    method_spec.validate()
    detector_was_supplied = detector is not None
    detector_origin = _detector_origin(
        detector_was_supplied,
        cli_production_factory_token=_cli_production_factory_token,
        wrapped_factory_token=_wrapped_factory_token,
    )
    source_feature_bag = Path(source_feature_bag).resolve()
    raw_image_bag = Path(raw_image_bag).resolve()
    camera_yaml = Path(camera_yaml).resolve()
    output_bag = Path(output_bag).resolve()
    manifest_path = (
        Path(manifest_json).resolve()
        if manifest_json is not None
        else output_bag.with_name(output_bag.name + ".manifest.json")
    )
    if max_published_frames is not None and max_published_frames <= 0:
        raise ValueError("max_published_frames must be a positive integer")
    for path, label in (
        (source_feature_bag, "source feature bag"),
        (raw_image_bag, "raw image bag"),
        (camera_yaml, "camera YAML"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    protected = {source_feature_bag, raw_image_bag, camera_yaml}
    if output_bag in protected:
        raise ValueError("output bag must not alias an input")
    if manifest_path in protected or manifest_path == output_bag:
        raise ValueError("manifest path must not alias an input or output bag")

    reserved_output = False
    reserved_manifest = False
    temporary_bag = _temporary_path(output_bag)
    temporary_manifest = _temporary_path(manifest_path)
    try:
        _reserve_file(output_bag)
        reserved_output = True
        try:
            _reserve_file(manifest_path)
            reserved_manifest = True
        except BaseException:
            output_bag.unlink(missing_ok=True)
            reserved_output = False
            raise

        prefix_mode = max_published_frames is not None
        run_mode = "PREFIX_NONFORMAL" if prefix_mode else "FULL"
        formal_eligible, formal_eligibility_reason = _formal_eligibility(
            prefix_mode=prefix_mode,
            detector_origin=detector_origin,
        )
        if runtime_profiler is None:
            schedule, source_total_frames = read_source_schedule(
                source_feature_bag,
                feature_topic,
                max_published_frames,
            )
            raw_frames = read_raw_frames(
                raw_image_bag,
                image_topic,
                schedule[0].header_stamp_ns,
                schedule[-1].header_stamp_ns,
            )
        else:
            schedule, source_total_frames = runtime_profiler.measure(
                "bag_io",
                read_source_schedule,
                source_feature_bag,
                feature_topic,
                max_published_frames,
            )
            raw_frames = runtime_profiler.measure(
                "bag_io",
                read_raw_frames,
                raw_image_bag,
                image_topic,
                schedule[0].header_stamp_ns,
                schedule[-1].header_stamp_ns,
            )
        if detector is None:
            detector = method_spec.detector_factory()
        carrier = run_carrier(
            schedule,
            raw_frames,
            detector,
            tracker=tracker,
            preprocess=preprocess,
            max_candidates=method_spec.max_candidates,
        )
        camera_matrix, distortion, camera_model = load_camera_model(camera_yaml)
        normalized = normalized_frames(
            carrier.published_frames,
            camera_matrix,
            distortion,
            camera_model,
        )
        velocities = velocity_frames(
            schedule,
            carrier.published_frames,
            normalized,
        )
        feature_messages = [
            build_feature_message(
                schedule[index],
                frame,
                normalized[index],
                velocities[index],
                source_code=method_spec.source_code,
            )
            for index, frame in enumerate(carrier.published_frames)
        ]
        cutoff = schedule[-1].record_stamp_ns if prefix_mode else None
        if runtime_profiler is None:
            before_digest = _nonfeature_digest(
                source_feature_bag,
                feature_topic,
                cutoff,
            )
            _write_candidate_bag(
                source_feature_bag,
                temporary_bag,
                feature_topic,
                schedule,
                feature_messages,
                prefix_mode,
            )
            _verify_output_schedule(temporary_bag, feature_topic, schedule)
            after_digest = _nonfeature_digest(temporary_bag, feature_topic, cutoff)
        else:
            before_digest = runtime_profiler.measure(
                "bag_io",
                _nonfeature_digest,
                source_feature_bag,
                feature_topic,
                cutoff,
            )
            runtime_profiler.measure(
                "bag_io",
                _write_candidate_bag,
                source_feature_bag,
                temporary_bag,
                feature_topic,
                schedule,
                feature_messages,
                prefix_mode,
            )
            runtime_profiler.measure(
                "bag_io",
                _verify_output_schedule,
                temporary_bag,
                feature_topic,
                schedule,
            )
            after_digest = runtime_profiler.measure(
                "bag_io",
                _nonfeature_digest,
                temporary_bag,
                feature_topic,
                cutoff,
            )
        if before_digest != after_digest:
            raise RuntimeError(
                "non-feature ordered record stamps or serialized payloads changed"
            )

        contract = _algorithm_contract(method_spec)
        frame_observations = [len(frame.ids) for frame in carrier.published_frames]
        observed_ids: set[int] = set()
        published_births = 0
        published_continuations = 0
        for frame in carrier.published_frames:
            for feature_id in frame.ids:
                if int(feature_id) in observed_ids:
                    published_continuations += 1
                else:
                    observed_ids.add(int(feature_id))
                    published_births += 1
        metrics = {
            "raw_frames_processed": len(raw_frames),
            "published_frames": len(schedule),
            "observations": int(sum(frame_observations)),
            "observations_per_frame_min": int(min(frame_observations)),
            "observations_per_frame_median": float(np.median(frame_observations)),
            "observations_per_frame_max": int(max(frame_observations)),
            "unique_ids": len(observed_ids),
            "published_first_occurrences": published_births,
            "published_continuations": published_continuations,
            "raw_births": int(sum(row.births for row in carrier.raw_diagnostics)),
            "raw_drops": int(sum(row.dropped for row in carrier.raw_diagnostics)),
            "adaptive_clahe_frames": int(
                sum(row.adaptive_clahe_applied for row in carrier.raw_diagnostics)
            ),
            "detector_candidates": int(
                sum(row.detector_candidates for row in carrier.raw_diagnostics)
            ),
        }
        if runtime_profiler is None:
            output_metadata = _file_metadata(
                temporary_bag,
                reported_path=output_bag,
            )
        else:
            output_metadata = runtime_profiler.measure(
                "bag_io",
                _file_metadata,
                temporary_bag,
                reported_path=output_bag,
            )
        if runtime_profiler is None:
            source_feature_metadata = _file_metadata(source_feature_bag)
            raw_image_metadata = _file_metadata(raw_image_bag)
        else:
            source_feature_metadata = runtime_profiler.measure(
                "bag_io", _file_metadata, source_feature_bag
            )
            raw_image_metadata = runtime_profiler.measure(
                "bag_io", _file_metadata, raw_image_bag
            )
        code_artifacts = _code_artifacts(method_spec, detector)
        manifest_payload = {
                "schema_version": method_spec.manifest_schema_version,
                "status": run_mode,
                "formal_eligible": formal_eligible,
                "formal_eligibility_reason": formal_eligibility_reason,
                "detector_origin": detector_origin,
                "prefix": {
                    "requested_max_published_frames": max_published_frames,
                    "source_total_published_frames": source_total_frames,
                    "selected_published_frames": len(schedule),
                    "cutoff_feature_record_stamp_ns": cutoff,
                },
                "inputs": {
                    "source_feature_bag": source_feature_metadata,
                    "raw_image_bag": raw_image_metadata,
                    "camera_yaml": _file_metadata(camera_yaml),
                    "camera_normalization_model": camera_model,
                    "feature_topic": feature_topic,
                    "image_topic": image_topic,
                },
                "algorithm": contract,
                "algorithm_config_sha256": _canonical_json_sha256(contract),
                "code_artifacts": code_artifacts,
                "output_bag": output_metadata,
                "nonfeature_stream_before": before_digest,
                "nonfeature_stream_after": after_digest,
                "metrics": metrics,
                "raw_frame_diagnostics": [
                    asdict(row) for row in carrier.raw_diagnostics
                ],
            }
        if runtime_profiler is not None:
            manifest_payload["runtime_profile"] = runtime_profiler.snapshot()
        manifest = _json_safe(manifest_payload)
        with temporary_manifest.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_bag, output_bag)
        os.replace(temporary_manifest, manifest_path)
        reserved_output = False
        reserved_manifest = False
        return manifest
    except BaseException:
        temporary_bag.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        if reserved_output:
            output_bag.unlink(missing_ok=True)
        if reserved_manifest:
            manifest_path.unlink(missing_ok=True)
        raise


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC_DEFAULT)
    parser.add_argument(
        "--max-published-frames",
        type=_positive_int,
        default=None,
        help=(
            "Explicit diagnostic prefix. Any use marks the manifest "
            "PREFIX_NONFORMAL, even when it selects the full source length."
        ),
    )
    parser.add_argument(
        "--manifest-json",
        default=None,
        help="Default: OUTPUT_BAG.manifest.json (also strict no-clobber).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = export_bag(
        args.source_feature_bag,
        args.raw_image_bag,
        args.camera_yaml,
        args.output_bag,
        image_topic=args.image_topic,
        feature_topic=args.feature_topic,
        max_published_frames=args.max_published_frames,
        manifest_json=args.manifest_json,
        _cli_production_factory_token=_CLI_PRODUCTION_FACTORY_TOKEN,
    )
    summary = {
        "status": manifest["status"],
        "formal_eligible": manifest["formal_eligible"],
        "output_bag": manifest["output_bag"],
        "metrics": manifest["metrics"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
