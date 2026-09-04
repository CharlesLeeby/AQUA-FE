from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from uw_frontend.matchers.base import Availability, BaseMatcher, MatchResult


class LoFTRMatcher(BaseMatcher):
    name = "loftr"
    _EXPECTED_WEIGHT_SIZES = {
        "loftr_outdoor.ckpt": 46341978,
    }

    def __init__(
        self,
        weights_path: str | Path | None = None,
        pretrained: str = "outdoor",
        max_dim: int = 640,
        min_confidence: float = 0.2,
        max_matches: int = 1500,
    ) -> None:
        self.weights_path = Path(weights_path) if weights_path else None
        self.pretrained = pretrained
        self.max_dim = max_dim
        self.min_confidence = min_confidence
        self.max_matches = max_matches
        self._torch = None
        self._matcher = None
        self._device = "cpu"

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
            from kornia.feature import LoFTR  # noqa: F401
        except Exception as exc:
            return Availability(False, f"kornia LoFTR unavailable: {exc}")
        incomplete = cls._incomplete_weight()
        if incomplete is not None:
            return Availability(False, incomplete)
        return Availability(True)

    @classmethod
    def is_available(cls) -> bool:
        return cls.availability().available

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        self._load()
        assert self._torch is not None and self._matcher is not None
        img0, scale0 = _prepare_gray(image0, self.max_dim)
        img1, scale1 = _prepare_gray(image1, self.max_dim)
        tensor0 = _image_to_tensor(self._torch, img0).to(self._device)
        tensor1 = _image_to_tensor(self._torch, img1).to(self._device)
        batch = {"image0": tensor0, "image1": tensor1}
        with self._torch.no_grad():
            output = self._matcher(batch)

        points0 = output["keypoints0"].detach().cpu().numpy().astype(np.float32)
        points1 = output["keypoints1"].detach().cpu().numpy().astype(np.float32)
        confidences = output.get("confidence")
        if confidences is None:
            confidences_np = np.ones((len(points0),), dtype=np.float32)
        else:
            confidences_np = confidences.detach().cpu().numpy().astype(np.float32)
        if len(confidences_np):
            valid = confidences_np >= self.min_confidence
            points0 = points0[valid]
            points1 = points1[valid]
            confidences_np = confidences_np[valid]
        if len(confidences_np) > self.max_matches:
            order = np.argsort(-confidences_np)[: self.max_matches]
            points0 = points0[order]
            points1 = points1[order]
            confidences_np = confidences_np[order]
        points0[:, 0] /= scale0[0]
        points0[:, 1] /= scale0[1]
        points1[:, 0] /= scale1[0]
        points1[:, 1] /= scale1[1]
        return MatchResult(
            points0=points0,
            points1=points1,
            confidences=confidences_np,
            method=self.name,
        )

    def _load(self) -> None:
        if self._matcher is not None:
            return
        try:
            import torch
            from kornia.feature import LoFTR
        except Exception as exc:
            raise RuntimeError("LoFTR requires torch and kornia.") from exc
        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.weights_path:
            matcher = LoFTR(pretrained=None)
            state = torch.load(str(self.weights_path), map_location=self._device)
            matcher.load_state_dict(state.get("state_dict", state), strict=False)
        else:
            matcher = LoFTR(pretrained=self.pretrained)
        self._matcher = matcher.eval().to(self._device)

    @classmethod
    def _incomplete_weight(cls) -> str | None:
        checkpoint_dir = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
        for name, expected_size in cls._EXPECTED_WEIGHT_SIZES.items():
            path = checkpoint_dir / name
            if path.exists() and path.stat().st_size != expected_size:
                return f"incomplete cached weight: {path} has {path.stat().st_size} bytes, expected {expected_size}"
        partials = sorted(checkpoint_dir.glob("loftr_*.partial"))
        if partials:
            return f"incomplete cached weight: {partials[0]} has {partials[0].stat().st_size} bytes"
        return None


def _prepare_gray(image: np.ndarray, max_dim: int) -> tuple[np.ndarray, tuple[float, float]]:
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = image.astype(np.uint8, copy=False)
    h, w = gray.shape[:2]
    if max_dim <= 0 or max(h, w) <= max_dim:
        return gray, (1.0, 1.0)
    scale = float(max_dim) / float(max(h, w))
    new_w = max(8, int(round(w * scale)))
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, (new_w // 8) * 8)
    new_h = max(8, (new_h // 8) * 8)
    resized = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, (new_w / float(w), new_h / float(h))


def _image_to_tensor(torch, image: np.ndarray):
    tensor = torch.from_numpy(image.astype(np.float32) / 255.0)
    return tensor.unsqueeze(0).unsqueeze(0)
