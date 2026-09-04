from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from uw_frontend.matchers.base import Availability, BaseMatcher, MatchResult


class SuperPointLightGlueMatcher(BaseMatcher):
    name = "superpoint_lightglue"
    _EXPECTED_WEIGHT_SIZES = {
        "superpoint_v1.pth": 5206086,
        "superpoint_lightglue_v0-1_arxiv.pth": 47500279,
    }

    def __init__(
        self,
        repo_path: str | Path = "external_tools/LightGlue",
        max_keypoints: int = 2048,
        resize: int | None = 1024,
        filter_threshold: float = 0.1,
        depth_confidence: float = 0.95,
        width_confidence: float = 0.99,
        cache_sparse_features: bool = False,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.max_keypoints = max_keypoints
        self.resize = resize
        self.filter_threshold = filter_threshold
        self.depth_confidence = depth_confidence
        self.width_confidence = width_confidence
        self.cache_sparse_features = bool(cache_sparse_features)
        self._torch = None
        self._extractor = None
        self._matcher = None
        self._cached_sparse_image: np.ndarray | None = None
        self._cached_sparse_output = None

    def reset(self) -> None:
        self._cached_sparse_image = None
        self._cached_sparse_output = None

    @classmethod
    def availability(cls) -> Availability:
        try:
            import torch  # noqa: F401
        except Exception as exc:
            return Availability(False, f"missing torch: {exc}")
        try:
            import kornia  # noqa: F401
        except Exception as exc:
            return Availability(False, f"missing kornia: {exc}")
        try:
            import torchvision  # noqa: F401
        except Exception as exc:
            return Availability(False, f"missing torchvision: {exc}")
        repo_file = Path("external_tools/LightGlue/lightglue/lightglue.py")
        if not repo_file.exists():
            return Availability(False, f"missing LightGlue repo file: {repo_file}")
        incomplete = cls._incomplete_weight()
        if incomplete is not None:
            return Availability(False, incomplete)
        return Availability(True)

    @classmethod
    def is_available(cls) -> bool:
        return cls.availability().available

    def _load(self) -> None:
        if self._matcher is not None:
            return
        try:
            import torch
        except Exception as exc:
            raise RuntimeError("SuperPoint+LightGlue requires torch; install torch before using this matcher.") from exc
        repo_str = str(self.repo_path.resolve())
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)
        from lightglue import LightGlue, SuperPoint

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._torch = torch
        self._extractor = SuperPoint(max_num_keypoints=self.max_keypoints).eval().to(device)
        self._matcher = LightGlue(
            features="superpoint",
            filter_threshold=self.filter_threshold,
            depth_confidence=self.depth_confidence,
            width_confidence=self.width_confidence,
        ).eval().to(device)

    @classmethod
    def _incomplete_weight(cls) -> str | None:
        checkpoint_dir = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
        for name, expected_size in cls._EXPECTED_WEIGHT_SIZES.items():
            path = checkpoint_dir / name
            if path.exists() and path.stat().st_size != expected_size:
                return f"incomplete cached weight: {path} has {path.stat().st_size} bytes, expected {expected_size}"
        return None

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        self._load()
        assert self._torch is not None and self._extractor is not None and self._matcher is not None
        device = next(self._matcher.parameters()).device
        with self._torch.no_grad():
            if (
                self.cache_sparse_features
                and self._cached_sparse_image is not None
                and self._cached_sparse_output is not None
                and _images_byte_equal(image0, self._cached_sparse_image)
            ):
                feats0 = self._cached_sparse_output
            else:
                tensor0 = _image_to_tensor(self._torch, image0).to(device)
                feats0 = self._extractor.extract(tensor0, resize=self.resize)
            tensor1 = _image_to_tensor(self._torch, image1).to(device)
            feats1 = self._extractor.extract(tensor1, resize=self.resize)
            if self.cache_sparse_features:
                self._cached_sparse_image = np.asarray(image1).copy()
                self._cached_sparse_output = feats1
            matches01 = self._matcher({"image0": feats0, "image1": feats1})
        from lightglue.utils import rbd

        feats0, feats1, matches01 = [rbd(x) for x in [feats0, feats1, matches01]]
        matches = matches01["matches"].detach().cpu().numpy()
        if len(matches) == 0:
            return MatchResult(
                points0=np.empty((0, 2), dtype=np.float32),
                points1=np.empty((0, 2), dtype=np.float32),
                confidences=np.empty((0,), dtype=np.float32),
                method=self.name,
            )
        points0 = feats0["keypoints"][matches[:, 0]].detach().cpu().numpy()
        points1 = feats1["keypoints"][matches[:, 1]].detach().cpu().numpy()
        scores = matches01.get("scores", None)
        if scores is None:
            confidences = np.ones((len(points0),), dtype=np.float32)
        else:
            confidences = scores.detach().cpu().numpy().astype(np.float32)
        return MatchResult(points0=points0, points1=points1, confidences=confidences, method=self.name)


def _image_to_tensor(torch, image: np.ndarray):
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    image = image.astype(np.float32) / 255.0
    return torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)


def _images_byte_equal(image0: np.ndarray, image1: np.ndarray) -> bool:
    array0 = np.asarray(image0)
    array1 = np.asarray(image1)
    return (
        array0.shape == array1.shape
        and array0.dtype == array1.dtype
        and array0.tobytes(order="C") == array1.tobytes(order="C")
    )
