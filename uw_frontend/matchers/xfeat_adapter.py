from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from uw_frontend.matchers.base import Availability, BaseMatcher, MatchResult


class XFeatMatcher(BaseMatcher):
    name = "xfeat"

    def __init__(
        self,
        repo_path: str | Path = "external_tools/accelerated_features",
        top_k: int = 4096,
        semi_dense: bool = False,
        min_cossim: float = 0.82,
        confidence_mode: str = "ones",
        cache_sparse_features: bool = False,
        weights: str | Path = "weights/xfeat.pt",
        adapter_weights: str | Path | None = None,
        adapter_type: str = "residual",
    ) -> None:
        self.adapter_type = adapter_type
        self.repo_path = Path(repo_path)
        # Weights path: absolute, or relative to repo_path (e.g. the underwater
        # domain-adapted "weights/xfeat_uw.pt" produced by uw_frontend.finetune).
        weights_path = Path(weights)
        self.weights = weights_path if weights_path.is_absolute() else self.repo_path / weights_path
        # Optional UWAdapter enhancement front-end (uw_adapter.pt).
        if adapter_weights is not None:
            ap = Path(adapter_weights)
            self.adapter_weights = ap if ap.is_absolute() else self.repo_path / ap
        else:
            self.adapter_weights = None
        self._adapter = None
        self.top_k = top_k
        self.semi_dense = semi_dense
        self.min_cossim = min_cossim
        if confidence_mode not in {"ones", "cosine"}:
            raise ValueError("confidence_mode must be 'ones' or 'cosine'")
        if semi_dense and confidence_mode == "cosine":
            raise ValueError("cosine confidence is only available for sparse XFeat")
        self.confidence_mode = confidence_mode
        self.cache_sparse_features = bool(cache_sparse_features)
        self._torch = None
        self._model = None
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
        repo_file = Path("external_tools/accelerated_features/modules/xfeat.py")
        if not repo_file.exists():
            return Availability(False, f"missing XFeat repo file: {repo_file}")
        weights = Path("external_tools/accelerated_features/weights/xfeat.pt")
        if not weights.exists():
            return Availability(False, f"missing XFeat weights: {weights}")
        return Availability(True)

    @classmethod
    def is_available(cls) -> bool:
        return cls.availability().available

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
        except Exception as exc:
            raise RuntimeError("XFeat requires torch; install torch before using this matcher.") from exc
        repo_str = str(self.repo_path.resolve())
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)
        from modules.xfeat import XFeat

        self._torch = torch
        self._model = XFeat(weights=str(self.weights.resolve()))

        if self.adapter_weights is not None:
            from uw_frontend.finetune.uw_adapter import UWAdapter, UWPhysAdapter

            adapter = UWPhysAdapter() if self.adapter_type == "phys" else UWAdapter()
            adapter.load_state_dict(torch.load(str(self.adapter_weights.resolve()), map_location="cpu"))
            adapter.eval()
            self._adapter = adapter.to(self._model.dev)

    def _prep(self, image: np.ndarray):
        """Image -> model-ready tensor, applying the UWAdapter front-end if loaded."""
        tensor = _image_to_tensor(self._torch, image)
        if self._adapter is not None:
            gray = tensor.mean(1, keepdim=True).to(self._model.dev)
            enhanced = self._adapter(gray)
            tensor = enhanced.repeat(1, 3, 1, 1)
        return tensor

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        self._load()
        assert self._torch is not None and self._model is not None
        with self._torch.no_grad():
            if self.semi_dense:
                tensor0 = self._prep(image0)
                tensor1 = self._prep(image1)
                points0, points1 = self._model.match_xfeat_star(tensor0, tensor1, top_k=self.top_k)
                confidences = np.ones((len(points0),), dtype=np.float32)
            elif self.confidence_mode == "cosine":
                if (
                    self.cache_sparse_features
                    and self._cached_sparse_image is not None
                    and self._cached_sparse_output is not None
                    and np.array_equal(image0, self._cached_sparse_image)
                ):
                    output0 = self._cached_sparse_output
                else:
                    tensor0 = self._prep(image0)
                    output0 = self._model.detectAndCompute(tensor0, top_k=self.top_k)[0]
                tensor1 = self._prep(image1)
                output1 = self._model.detectAndCompute(tensor1, top_k=self.top_k)[0]
                if self.cache_sparse_features:
                    self._cached_sparse_image = np.asarray(image1).copy()
                    self._cached_sparse_output = output1
                indices0, indices1 = self._model.match(
                    output0["descriptors"],
                    output1["descriptors"],
                    min_cossim=self.min_cossim,
                )
                points0 = output0["keypoints"][indices0].detach().cpu().numpy()
                points1 = output1["keypoints"][indices1].detach().cpu().numpy()
                confidences = (
                    output0["descriptors"][indices0]
                    * output1["descriptors"][indices1]
                ).sum(dim=-1).clamp(0.0, 1.0).detach().cpu().numpy().astype(np.float32)
            else:
                tensor0 = self._prep(image0)
                tensor1 = self._prep(image1)
                points0, points1 = self._model.match_xfeat(
                    tensor0,
                    tensor1,
                    top_k=self.top_k,
                    min_cossim=self.min_cossim,
                )
                confidences = np.ones((len(points0),), dtype=np.float32)
        return MatchResult(
            points0=np.asarray(points0, dtype=np.float32),
            points1=np.asarray(points1, dtype=np.float32),
            confidences=confidences,
            method=self.name,
        )


def _image_to_tensor(torch, image: np.ndarray):
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    image = image.astype(np.float32) / 255.0
    tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)
    return tensor
