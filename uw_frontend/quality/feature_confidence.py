from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def quality_to_sigma(
    qualities: np.ndarray,
    sigma_base: float = 1.0,
    eps: float = 1e-3,
    max_sigma: float = 10.0,
) -> np.ndarray:
    """Map feature confidence q_i in [0, 1] to a visual residual sigma."""

    q = np.asarray(qualities, dtype=np.float32)
    sigma = float(sigma_base) / np.sqrt(np.clip(q, 0.0, 1.0) + float(eps))
    return np.clip(sigma, float(sigma_base), float(max_sigma)).astype(np.float32)


@dataclass
class ReliabilityCalibrator:
    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float
    blend: float = 1.0
    source_models: dict[str, dict[str, np.ndarray | float]] | None = None

    @classmethod
    def from_json(cls, path: str | Path) -> "ReliabilityCalibrator":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        source_models = None
        if "source_models" in data:
            source_models = {}
            for source, model in data["source_models"].items():
                source_models[source] = {
                    "mean": np.asarray(model["mean"], dtype=np.float32),
                    "scale": np.asarray(model["scale"], dtype=np.float32),
                    "weights": np.asarray(model["weights"], dtype=np.float32),
                    "bias": float(model["bias"]),
                    "blend": float(model.get("blend", data.get("blend", 1.0))),
                }
        return cls(
            feature_names=list(data["feature_names"]),
            mean=np.asarray(data["mean"], dtype=np.float32),
            scale=np.asarray(data["scale"], dtype=np.float32),
            weights=np.asarray(data["weights"], dtype=np.float32),
            bias=float(data["bias"]),
            blend=float(data.get("blend", 1.0)),
            source_models=source_models,
        )

    def predict(
        self,
        features: np.ndarray,
        base_quality: np.ndarray | None = None,
        sources: list[str] | np.ndarray | None = None,
    ) -> np.ndarray:
        x = np.asarray(features, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        source_keys = self._source_keys(x, sources)
        if self.source_models:
            base_arr = np.asarray(base_quality, dtype=np.float32).reshape(-1) if base_quality is not None else None
            probs = self._predict_global(x, base_quality)
            for source, model in self.source_models.items():
                mask = source_keys == source
                if not np.any(mask):
                    continue
                probs[mask] = self._predict_with_model(x[mask], base_arr[mask] if base_arr is not None else None, model)
            return np.clip(probs, 0.01, 1.0).astype(np.float32)
        return self._predict_global(x, base_quality)

    def _predict_global(self, x: np.ndarray, base_quality: np.ndarray | None) -> np.ndarray:
        scale = np.where(self.scale > 1e-6, self.scale, 1.0)
        z = (x - self.mean.reshape(1, -1)) / scale.reshape(1, -1)
        logits = z @ self.weights.reshape(-1, 1) + self.bias
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits.reshape(-1), -30.0, 30.0)))
        if base_quality is not None and self.blend < 1.0:
            base = np.asarray(base_quality, dtype=np.float32).reshape(-1)
            probs = self.blend * probs + (1.0 - self.blend) * np.clip(base, 0.0, 1.0)
        return np.clip(probs, 0.01, 1.0).astype(np.float32)

    def _predict_with_model(
        self,
        x: np.ndarray,
        base_quality: np.ndarray | None,
        model: dict[str, np.ndarray | float],
    ) -> np.ndarray:
        mean = np.asarray(model["mean"], dtype=np.float32)
        scale = np.asarray(model["scale"], dtype=np.float32)
        scale = np.where(scale > 1e-6, scale, 1.0)
        weights = np.asarray(model["weights"], dtype=np.float32)
        bias = float(model["bias"])
        blend = float(model.get("blend", self.blend))
        z = (x - mean.reshape(1, -1)) / scale.reshape(1, -1)
        logits = z @ weights.reshape(-1, 1) + bias
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits.reshape(-1), -30.0, 30.0)))
        if base_quality is not None and blend < 1.0:
            base = np.asarray(base_quality, dtype=np.float32).reshape(-1)
            probs = blend * probs + (1.0 - blend) * np.clip(base, 0.0, 1.0)
        return np.clip(probs, 0.01, 1.0).astype(np.float32)

    def _source_keys(self, x: np.ndarray, sources: list[str] | np.ndarray | None = None) -> np.ndarray:
        if sources is not None:
            source_arr = np.asarray(sources, dtype=object).reshape(-1)
            if len(source_arr) != len(x):
                raise ValueError("sources must have the same length as features")
            available = set(self.source_models.keys()) if self.source_models else set()
            keys = np.full((len(source_arr),), "other", dtype=object)
            for idx, source in enumerate(source_arr):
                keys[idx] = _source_key_from_name(str(source), available)
            return keys
        index = {name: idx for idx, name in enumerate(self.feature_names)}
        keys = np.full((len(x),), "other", dtype=object)
        if "source_klt" in index:
            keys[x[:, index["source_klt"]] > 0.5] = "klt"
        if "source_gftt" in index:
            keys[x[:, index["source_gftt"]] > 0.5] = "gftt"
        if "source_lk_recovery" in index:
            keys[x[:, index["source_lk_recovery"]] > 0.5] = "lk_recovery"
        if "source_homography_recovery" in index:
            keys[x[:, index["source_homography_recovery"]] > 0.5] = "homography_recovery"
        if "source_orb_recovery" in index:
            keys[x[:, index["source_orb_recovery"]] > 0.5] = "orb_recovery"
        if "source_learned_recovery" in index:
            keys[x[:, index["source_learned_recovery"]] > 0.5] = "learned_recovery"
        if "source_learned_init" in index:
            keys[x[:, index["source_learned_init"]] > 0.5] = "learned_init"
        return keys


def _source_key_from_name(source: str, available: set[str] | None = None) -> str:
    available = available or set()
    if source in available:
        return source
    coarse = _coarse_source_key(source)
    if coarse in available:
        return coarse
    return coarse


def _coarse_source_key(source: str) -> str:
    if source in {"klt", "gftt", "lk_recovery", "homography_recovery", "orb_recovery"}:
        return source
    if source.endswith("_recovery"):
        return "learned_recovery"
    if source.endswith("_init"):
        return "learned_init"
    return "other"
