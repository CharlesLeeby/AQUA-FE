#!/usr/bin/env python3
"""Export an official-XFeat proposal + raw-frame LK comparison feature bag.

This additive comparison arm imports the local official VerLab XFeat checkout
without modifying it.  A preprocessed grayscale frame that needs carrier
replenishment is converted to an RGB float tensor and passed once to
``XFeat.detectAndCompute(..., top_k=2048)``.  Only its original-image keypoints
and native scores become birth proposals for the frozen carrier in
``export_superpoint_lk_carrier_v1``.  The official call does compute 64-D
descriptors internally; this adapter discards them and never calls a descriptor
matcher.  Existing tracker, exporter, and VINS code is not modified.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Sequence

import cv2
import numpy as np


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import export_superpoint_lk_carrier_v1 as carrier


XFEAT_REPO = WORKSPACE_ROOT / "external_tools" / "accelerated_features"
XFEAT_SOURCE = XFEAT_REPO / "modules" / "xfeat.py"
XFEAT_MODEL_SOURCE = XFEAT_REPO / "modules" / "model.py"
XFEAT_INTERPOLATOR_SOURCE = XFEAT_REPO / "modules" / "interpolator.py"
XFEAT_WEIGHT = XFEAT_REPO / "weights" / "xfeat.pt"
XFEAT_LICENSE = XFEAT_REPO / "LICENSE"

XFEAT_EXPECTED_COMMIT = "e92685f57f8318b18725c5c8c0bd28c7fe188d9a"
XFEAT_TOP_K = 2048
XFEAT_DETECTION_THRESHOLD = 0.05
XFEAT_LK_SOURCE_CODE = 20
_CLI_PRODUCTION_FACTORY_TOKEN = object()

XFEAT_CLOSURE = {
    "xfeat.py": {
        "path": XFEAT_SOURCE,
        "size_bytes": 13_472,
        "sha256": "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7",
    },
    "model.py": {
        "path": XFEAT_MODEL_SOURCE,
        "size_bytes": 4_542,
        "sha256": "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964",
    },
    "interpolator.py": {
        "path": XFEAT_INTERPOLATOR_SOURCE,
        "size_bytes": 1_175,
        "sha256": "d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da",
    },
    "xfeat.pt": {
        "path": XFEAT_WEIGHT,
        "size_bytes": 6_247_949,
        "sha256": "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b",
    },
    "LICENSE": {
        "path": XFEAT_LICENSE,
        "size_bytes": 11_357,
        "sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    },
}


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(XFEAT_REPO), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "cannot identify local XFeat repository: "
            f"git {' '.join(arguments)}: {completed.stderr.strip()}"
        )
    return completed.stdout.rstrip("\n")


def _mode_only_worktree_proof(
    status_porcelain_z: str,
) -> tuple[bool, list[dict[str, object]]]:
    entries = [entry for entry in status_porcelain_z.split("\0") if entry]
    proofs: list[dict[str, object]] = []
    if not entries:
        return False, proofs
    for entry in entries:
        proof: dict[str, object] = {"status_entry": entry}
        proofs.append(proof)
        if not entry.startswith(" M "):
            proof["proved_mode_only"] = False
            proof["reason"] = "not_a_simple_unstaged_worktree_modification"
            continue
        relative_path = entry[3:]
        proof["path"] = relative_path
        index_record = _git_output("ls-files", "-s", "--", relative_path)
        parts = index_record.split(maxsplit=3)
        if len(parts) != 4 or parts[2] != "0":
            proof["proved_mode_only"] = False
            proof["reason"] = "missing_or_nonstage0_index_entry"
            continue
        index_mode, index_blob = parts[0], parts[1]
        working_path = XFEAT_REPO / relative_path
        if index_mode not in {"100644", "100755"} or not working_path.is_file():
            proof["proved_mode_only"] = False
            proof["reason"] = "unsupported_index_mode_or_missing_regular_file"
            continue
        working_mode = "100755" if working_path.stat().st_mode & 0o111 else "100644"
        working_blob = _git_output(
            "hash-object", "--no-filters", "--", relative_path
        ).strip()
        bytes_equal = bool(working_blob == index_blob)
        mode_changed = bool(working_mode != index_mode)
        proof.update(
            {
                "index_mode": index_mode,
                "working_mode": working_mode,
                "index_blob": index_blob,
                "working_blob": working_blob,
                "bytes_equal_to_index": bytes_equal,
                "mode_changed": mode_changed,
                "proved_mode_only": bool(bytes_equal and mode_changed),
                "reason": (
                    "working_bytes_equal_index_and_git_mode_changed"
                    if bytes_equal and mode_changed
                    else "working_bytes_changed_or_git_mode_not_changed"
                ),
            }
        )
    return bool(proofs and all(row["proved_mode_only"] for row in proofs)), proofs


def _repository_metadata() -> dict[str, object]:
    commit = _git_output("rev-parse", "HEAD").strip()
    if commit != XFEAT_EXPECTED_COMMIT:
        raise RuntimeError(
            f"XFeat commit mismatch: {commit} != {XFEAT_EXPECTED_COMMIT}"
        )
    status_lines = tuple(
        line
        for line in _git_output(
            "status", "--porcelain=v1", "--untracked-files=all"
        ).splitlines()
        if line
    )
    status_porcelain_z = _git_output(
        "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    dirty = bool(status_porcelain_z)
    unstaged_summary = tuple(
        line
        for line in _git_output("diff", "--summary").splitlines()
        if line
    )
    staged_summary = tuple(
        line
        for line in _git_output("diff", "--cached", "--summary").splitlines()
        if line
    )
    mode_bits_only, dirty_path_proofs = _mode_only_worktree_proof(
        status_porcelain_z
    )
    dirty_classification = (
        "clean"
        if not dirty
        else "mode_bits_only"
        if mode_bits_only
        else "content_or_index_or_untracked_changes"
    )
    caveat = (
        "Dirty worktree (mode bits only): closure bytes match the pinned SHA256 "
        "values, but the commit alone does not describe filesystem modes."
        if mode_bits_only
        else "Dirty worktree: the commit alone is not a complete runtime identity; "
        "the recorded closure file sizes and SHA256 values are authoritative."
        if dirty
        else "Clean worktree at the recorded commit."
    )
    return {
        "path": str(XFEAT_REPO),
        "upstream": "https://github.com/verlab/accelerated_features",
        "commit": commit,
        "dirty": dirty,
        "dirty_classification": dirty_classification,
        "status_porcelain_v1": list(status_lines),
        "dirty_path_content_and_mode_proofs": dirty_path_proofs,
        "unstaged_summary": list(unstaged_summary),
        "staged_summary": list(staged_summary),
        "content_identity_caveat": caveat,
        "license_spdx": "Apache-2.0",
    }


def _validate_runtime_closure() -> dict[str, dict[str, object]]:
    observed: dict[str, dict[str, object]] = {}
    for label, expected in XFEAT_CLOSURE.items():
        path = Path(expected["path"])
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen XFeat closure artifact: {path}")
        metadata = carrier._file_metadata(path)
        expected_size = int(expected["size_bytes"])
        expected_sha256 = str(expected["sha256"])
        if metadata["size_bytes"] != expected_size:
            raise RuntimeError(
                f"XFeat closure size mismatch for {label}: "
                f"{metadata['size_bytes']} != {expected_size}"
            )
        if metadata["sha256"] != expected_sha256:
            raise RuntimeError(
                f"XFeat closure SHA256 mismatch for {label}: "
                f"{metadata['sha256']} != {expected_sha256}"
            )
        observed[label] = metadata
    return observed


def _timing_distribution(samples_ms: Sequence[float]) -> dict[str, object]:
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


class XFeatDetector:
    """Proposal-only adapter around official sparse ``detectAndCompute``."""

    def __init__(self) -> None:
        self._torch = None
        self._model = None
        self._device: str | None = None
        self._closure_metadata: dict[str, dict[str, object]] | None = None
        self._repository_metadata: dict[str, object] | None = None
        self._imported_module_paths: dict[str, str] = {}
        self._detect_calls = 0
        self._gray_input_shapes: set[tuple[int, int]] = set()
        self._tensor_input_shapes: set[tuple[int, int, int, int]] = set()
        self._warmup_detect_ms: list[float] = []
        self._steady_detect_ms: list[float] = []

    def _load(self) -> None:
        if self._model is not None:
            return
        closure = _validate_runtime_closure()
        repository = _repository_metadata()
        repo = str(XFEAT_REPO.resolve())
        if repo not in sys.path:
            sys.path.insert(0, repo)
        torch = importlib.import_module("torch")
        xfeat_module = importlib.import_module("modules.xfeat")
        imported_modules = {
            "modules.xfeat": (xfeat_module, XFEAT_SOURCE),
            "modules.model": (
                importlib.import_module("modules.model"),
                XFEAT_MODEL_SOURCE,
            ),
            "modules.interpolator": (
                importlib.import_module("modules.interpolator"),
                XFEAT_INTERPOLATOR_SOURCE,
            ),
        }
        imported_paths: dict[str, str] = {}
        for name, (module, expected_path) in imported_modules.items():
            module_path = Path(getattr(module, "__file__", "")).resolve()
            if module_path != expected_path.resolve():
                raise RuntimeError(
                    f"import namespace pollution for {name}: {module_path} != "
                    f"{expected_path.resolve()}"
                )
            imported_paths[name] = str(module_path)
        model = xfeat_module.XFeat(
            weights=str(XFEAT_WEIGHT.resolve()),
            top_k=XFEAT_TOP_K,
            detection_threshold=XFEAT_DETECTION_THRESHOLD,
        )
        self._torch = torch
        self._model = model
        self._device = str(getattr(model, "dev", "unknown"))
        self._closure_metadata = closure
        self._repository_metadata = repository
        self._imported_module_paths = imported_paths

    def _synchronize_if_cuda(self) -> None:
        if self._torch is None or not str(self._device).startswith("cuda"):
            return
        cuda = getattr(self._torch, "cuda", None)
        synchronize = getattr(cuda, "synchronize", None)
        if callable(synchronize):
            synchronize()

    def detect(self, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self._load()
        assert self._torch is not None and self._model is not None
        gray = np.asarray(gray, dtype=np.uint8)
        if gray.ndim != 2:
            raise ValueError("XFeat detector expects a grayscale image")
        self._gray_input_shapes.add((int(gray.shape[0]), int(gray.shape[1])))
        self._synchronize_if_cuda()
        started = time.perf_counter()
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        tensor = self._torch.from_numpy(
            rgb.astype(np.float32) / np.float32(255.0)
        ).permute(2, 0, 1).unsqueeze(0)
        self._tensor_input_shapes.add(tuple(int(value) for value in tensor.shape))
        # The official API computes sparse 64-D descriptors as part of this
        # call.  We intentionally consume only proposals and scores below.
        output = self._model.detectAndCompute(tensor, top_k=XFEAT_TOP_K)[0]
        self._synchronize_if_cuda()
        points = output["keypoints"].detach().cpu().numpy().astype(
            np.float32, copy=False
        )
        scores = output["scores"].detach().cpu().numpy().astype(
            np.float32, copy=False
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if self._detect_calls == 0:
            self._warmup_detect_ms.append(elapsed_ms)
        else:
            self._steady_detect_ms.append(elapsed_ms)
        self._detect_calls += 1
        return carrier._validated_candidates(
            points,
            scores,
            max_candidates=XFEAT_TOP_K,
        )

    def artifact_metadata(self) -> dict[str, object]:
        self._load()
        assert self._torch is not None
        assert self._closure_metadata is not None
        assert self._repository_metadata is not None
        all_detect_ms = self._warmup_detect_ms + self._steady_detect_ms
        return {
            "identity": "official_verlab_XFeat_sparse_detectAndCompute_proposals_only",
            "repository": dict(self._repository_metadata),
            "license": {
                "spdx": "Apache-2.0",
                "file": dict(self._closure_metadata["LICENSE"]),
            },
            "closure": {
                label: dict(metadata)
                for label, metadata in self._closure_metadata.items()
                if label != "LICENSE"
            },
            "api": {
                "call": "XFeat.detectAndCompute(tensor, top_k=2048)[0]",
                "top_k": XFEAT_TOP_K,
                "detection_threshold": XFEAT_DETECTION_THRESHOLD,
                "carrier_consumes": ["keypoints", "scores"],
                "keypoint_coordinates": "official_original_image_coordinates_unmodified",
                "score_values": "official_native_sparse_scores_unmodified",
                "input_adaptation": (
                    "frozen literature input is mono/255; this wrapper repeats mono "
                    "into RGB after /255 for the official PyTorch B,C,H,W path. "
                    "XFeatModel.forward averages channels to one, so the repeated "
                    "channels recover the same normalized mono values"
                ),
                "matcher_called": False,
                "descriptor_computation": (
                    "official detectAndCompute computes 64-D descriptors internally; "
                    "the adapter discards them and does not use them for LK or matching"
                ),
            },
            "runtime": {
                "device": str(self._device),
                "torch_version": str(getattr(self._torch, "__version__", "unknown")),
                "opencv_version": str(cv2.__version__),
                "numpy_version": str(np.__version__),
                "imported_module_paths": dict(self._imported_module_paths),
                "detect_calls": int(self._detect_calls),
                "gray_input_shapes_hw": [
                    list(shape) for shape in sorted(self._gray_input_shapes)
                ],
                "rgb_tensor_input_shapes_bchw": [
                    list(shape) for shape in sorted(self._tensor_input_shapes)
                ],
                "timing_clock": "time.perf_counter",
                "cuda_timing_sync": "synchronize_before_and_after_when_cuda",
                "warmup_policy": "first_detect_call_separate",
                "detect_ms_scope": (
                    "gray-to-repeated-RGB tensor conversion, official "
                    "detectAndCompute call, CUDA synchronization when applicable, "
                    "and keypoint/score transfer; lazy model loading is excluded"
                ),
                "detect_ms": {
                    "warmup": _timing_distribution(self._warmup_detect_ms),
                    "steady_state": _timing_distribution(self._steady_detect_ms),
                    "all": _timing_distribution(all_detect_ms),
                },
            },
        }


XFEAT_METHOD_SPEC = carrier.DetectorMethodSpec(
    algorithm_name="xfeat_detector_raw_frame_lk_carrier_v1",
    detector_key="xfeat",
    detector_contract={
        "carrier_role": "birth_proposals_only",
        "official_api": "XFeat.detectAndCompute",
        "top_k": XFEAT_TOP_K,
        "detection_threshold": XFEAT_DETECTION_THRESHOLD,
        "literature_frozen_input": "single_channel_mono_divided_by_255",
        "wrapper_input": "mono8_repeated_to_rgb_float32_tensor_after_divide_by_255",
        "official_tensor_path_compatibility": (
            "official detectAndCompute accepts B,C,H,W tensors; XFeatModel.forward "
            "averages channels before its one-channel backbone, so repeated RGB is "
            "numerically mono/255 after that official averaging step"
        ),
        "internal_size_mapping": (
            "official preprocess_tensor bilinearly resizes H,W down to floor multiples "
            "of 32; official detectAndCompute multiplies keypoints by original/floored "
            "width,height ratios before returning original-image coordinates"
        ),
        "keypoints": "official_original_image_coordinates_unmodified",
        "scores": "official_native_sparse_scores_unmodified",
        "score_order": "descending_stable_input_index_tiebreak_for_carrier_births",
        "pairwise_matcher": None,
        "matcher_called": False,
        "descriptor_computation_skipped": False,
        "descriptor_policy": (
            "official detectAndCompute computes 64-D descriptors; adapter discards "
            "them and never supplies descriptors to LK or a matcher"
        ),
    },
    source_code=XFEAT_LK_SOURCE_CODE,
    max_candidates=XFEAT_TOP_K,
    manifest_schema_version="xfeat-lk-carrier-export-v1",
    detector_factory=XFeatDetector,
    entrypoint_source=Path(__file__).resolve(),
    static_code_artifacts=(
        ("xfeat_source", XFEAT_SOURCE),
        ("xfeat_model_source", XFEAT_MODEL_SOURCE),
        ("xfeat_interpolator_source", XFEAT_INTERPOLATOR_SOURCE),
        ("xfeat_weight", XFEAT_WEIGHT),
        ("xfeat_license", XFEAT_LICENSE),
    ),
    production_detector_identity=(
        "official_verlab_XFeat_sparse_detectAndCompute_proposals_only"
    ),
)


class _ProfiledDetector:
    def __init__(
        self, detector, runtime_profiler: carrier.ExportRuntimeProfiler
    ) -> None:
        self._detector = detector
        self._runtime_profiler = runtime_profiler

    def detect(self, image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self._runtime_profiler.measure(
            "detect", self._detector.detect, image
        )

    def __getattr__(self, name: str):
        return getattr(self._detector, name)


def export_bag(
    source_feature_bag: str | Path,
    raw_image_bag: str | Path,
    camera_yaml: str | Path,
    output_bag: str | Path,
    *,
    image_topic: str,
    feature_topic: str = carrier.FEATURE_TOPIC_DEFAULT,
    max_published_frames: int | None = None,
    manifest_json: str | Path | None = None,
    detector=None,
    tracker: Callable[[np.ndarray, np.ndarray, np.ndarray], carrier.TrackResult] = (
        carrier.track_points_lk
    ),
    preprocess: Callable[[np.ndarray], tuple[np.ndarray, bool]] = carrier.adaptive_clahe,
    _cli_production_factory_token: object | None = None,
) -> dict[str, object]:
    if (
        _cli_production_factory_token is not None
        and _cli_production_factory_token is not _CLI_PRODUCTION_FACTORY_TOKEN
    ):
        raise ValueError("invalid internal XFeat CLI provenance token")
    detector_was_supplied = detector is not None
    cli_factory = (
        _cli_production_factory_token is _CLI_PRODUCTION_FACTORY_TOKEN
        and not detector_was_supplied
    )
    runtime_profiler = carrier.ExportRuntimeProfiler(
        required_stages=("preprocess", "detect", "lk", "bag_io"),
        notes=(
            "preprocess times the configured image preprocessing callable per raw frame",
            "detect times the full detector adapter; its first sample includes lazy "
            "model loading, while code_artifacts.detector.runtime.detect_ms excludes "
            "loading and separates first-inference warmup",
            "lk times the frozen carrier tracker callable for raw-frame transitions",
            "bag_io is the aggregate of heterogeneous bag/file operations named in "
            "scope, including whole-file source/raw hashes; its median and p90 are "
            "operation-sample summaries and must not be interpreted as per-frame I/O",
        ),
    )
    detector = XFeatDetector() if detector is None else detector
    profiled_detector = _ProfiledDetector(detector, runtime_profiler)

    def profiled_tracker(
        previous: np.ndarray,
        current: np.ndarray,
        points: np.ndarray,
    ) -> carrier.TrackResult:
        return runtime_profiler.measure(
            "lk", tracker, previous, current, points
        )

    def profiled_preprocess(image: np.ndarray) -> tuple[np.ndarray, bool]:
        return runtime_profiler.measure("preprocess", preprocess, image)

    return carrier.export_bag(
        source_feature_bag,
        raw_image_bag,
        camera_yaml,
        output_bag,
        image_topic=image_topic,
        feature_topic=feature_topic,
        max_published_frames=max_published_frames,
        manifest_json=manifest_json,
        detector=profiled_detector,
        tracker=profiled_tracker,
        preprocess=profiled_preprocess,
        method_spec=XFEAT_METHOD_SPEC,
        runtime_profiler=runtime_profiler,
        _wrapped_factory_token=(
            carrier._WRAPPED_CLI_PRODUCTION_FACTORY_TOKEN
            if cli_factory
            else carrier._WRAPPED_PYTHON_FACTORY_TOKEN
            if not detector_was_supplied
            else None
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--feature-topic", default=carrier.FEATURE_TOPIC_DEFAULT)
    parser.add_argument(
        "--max-published-frames",
        type=carrier._positive_int,
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
        "runtime_profile": manifest["runtime_profile"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
