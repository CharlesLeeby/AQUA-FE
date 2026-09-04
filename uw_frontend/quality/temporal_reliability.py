"""Source-neutral temporal reliability and conformal q_lower for P03/P03B."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from uw_frontend.geometry.master_candidate_stream import TrackEvidence
from uw_frontend.quality.conformal_calibrator import conformal_quantile


FEATURE_NAMES = (
    "age_norm_30",
    "ncc_score",
    "fb_score_tau_1px",
    "survival_ratio",
    "prior_residual_median_score",
    "prior_residual_p95_score",
)
SOURCE_GROUPS = frozenset({"klt", "learned", "classical"})


@dataclass(frozen=True)
class TemporalSnapshot:
    sequence_id: str
    lineage_id: int
    source_group: str
    geometry_stratum: str
    frame_index: int
    evidence: TrackEvidence
    klt_valid: bool
    geometry_correct: bool
    decision_eligible: bool = True


@dataclass(frozen=True)
class CalibrationRow:
    sequence_id: str
    lineage_id: int
    source_group: str
    geometry_stratum: str
    decision_frame: int
    label_end_frame: int
    split: str
    features: tuple[float, ...]
    label: int


@dataclass(frozen=True)
class PooledReliabilityModel:
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float
    horizon_frames: int
    alpha: float
    conformal_quantile: float
    model_hash: str
    train_sequences: tuple[str, ...] = ()
    calibration_sequences: tuple[str, ...] = ()
    row_identity_hash: str = ""

    @classmethod
    def from_json(cls, path: str | Path) -> "PooledReliabilityModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            feature_names=tuple(data["feature_names"]),
            mean=tuple(float(value) for value in data["mean"]),
            scale=tuple(float(value) for value in data["scale"]),
            weights=tuple(float(value) for value in data["weights"]),
            bias=float(data["bias"]),
            horizon_frames=int(data["horizon_frames"]),
            alpha=float(data["alpha"]),
            conformal_quantile=float(data["conformal_quantile"]),
            model_hash=str(data["model_hash"]),
            train_sequences=tuple(str(value) for value in data.get("train_sequences", [])),
            calibration_sequences=tuple(str(value) for value in data.get("calibration_sequences", [])),
            row_identity_hash=str(data.get("row_identity_hash", "")),
        )

    def to_json(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.as_dict(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def p_hat(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        array = np.asarray(features, dtype=np.float64)
        if array.size == 0:
            return np.empty((0,), dtype=np.float64)
        array = array.reshape(-1, len(self.feature_names))
        normalized = (array - np.asarray(self.mean)) / np.asarray(self.scale)
        logits = normalized @ np.asarray(self.weights) + float(self.bias)
        return 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))

    def q_lower(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        return np.clip(self.p_hat(features) - float(self.conformal_quantile), 0.0, 1.0)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "isj-temporal-reliability-model-v1",
            "feature_names": list(self.feature_names),
            "mean": list(self.mean),
            "scale": list(self.scale),
            "weights": list(self.weights),
            "bias": self.bias,
            "horizon_frames": self.horizon_frames,
            "alpha": self.alpha,
            "conformal_quantile": self.conformal_quantile,
            "model_hash": self.model_hash,
            "train_sequences": list(self.train_sequences),
            "calibration_sequences": list(self.calibration_sequences),
            "row_identity_hash": self.row_identity_hash,
        }


def selector_features(evidence: TrackEvidence) -> tuple[float, ...]:
    """Build features without source, confidence, base_quality, or current e."""

    age = max(0, int(evidence.age))
    survival = max(0, int(evidence.survival_count))
    prior = np.asarray(evidence.residual_history, dtype=np.float64)
    prior = prior[np.isfinite(prior)]
    if len(prior):
        median_score = math.exp(-max(0.0, float(np.median(prior))))
        p95_score = math.exp(-max(0.0, float(np.quantile(prior, 0.95, method="linear"))))
    else:
        median_score = 0.0
        p95_score = 0.0
    return (
        min(1.0, age / 30.0),
        min(1.0, max(0.0, (float(evidence.ncc) + 1.0) * 0.5)),
        math.exp(-max(0.0, float(evidence.fb_error))),
        min(1.0, survival / max(1.0, float(age))),
        median_score,
        p95_score,
    )


def build_calibration_rows(
    snapshots: Sequence[TemporalSnapshot],
    *,
    sequence_splits: Mapping[str, str],
    sequence_end_frames: Mapping[str, int] | None = None,
    horizon_frames: int = 5,
) -> list[CalibrationRow]:
    if int(horizon_frames) <= 0:
        raise ValueError("horizon_frames must be positive")
    if set(sequence_splits.values()) - {"train", "calibration"}:
        raise ValueError("split values must be train or calibration")
    sequence_max: dict[str, int] = {}
    grouped: dict[tuple[str, int], dict[int, TemporalSnapshot]] = {}
    lineage_source: dict[tuple[str, int], str] = {}
    for snapshot in snapshots:
        if snapshot.source_group not in SOURCE_GROUPS:
            raise ValueError(f"unsupported source group: {snapshot.source_group}")
        if snapshot.sequence_id not in sequence_splits:
            raise ValueError(f"sequence lacks a frozen split: {snapshot.sequence_id}")
        key = (snapshot.sequence_id, int(snapshot.lineage_id))
        if key in lineage_source and lineage_source[key] != snapshot.source_group:
            raise ValueError("lineage source changed")
        lineage_source[key] = snapshot.source_group
        frames = grouped.setdefault(key, {})
        if snapshot.frame_index in frames:
            raise ValueError("duplicate lineage x frame snapshot")
        frames[int(snapshot.frame_index)] = snapshot
        sequence_max[snapshot.sequence_id] = max(
            sequence_max.get(snapshot.sequence_id, -1), int(snapshot.frame_index)
        )
    for sequence_id, end_frame in (sequence_end_frames or {}).items():
        if sequence_id not in sequence_splits:
            raise ValueError(f"sequence end lacks a frozen split: {sequence_id}")
        sequence_max[sequence_id] = max(sequence_max.get(sequence_id, -1), int(end_frame))

    rows: list[CalibrationRow] = []
    for (sequence_id, lineage_id), frames in sorted(grouped.items()):
        for frame, snapshot in sorted(frames.items()):
            if not snapshot.decision_eligible:
                continue
            label_end = frame + int(horizon_frames)
            if label_end > sequence_max[sequence_id]:
                continue
            future = [frames.get(index) for index in range(frame + 1, label_end + 1)]
            label = int(
                all(
                    item is not None and item.klt_valid and item.geometry_correct
                    for item in future
                )
            )
            rows.append(
                CalibrationRow(
                    sequence_id=sequence_id,
                    lineage_id=lineage_id,
                    source_group=snapshot.source_group,
                    geometry_stratum=snapshot.geometry_stratum,
                    decision_frame=frame,
                    label_end_frame=label_end,
                    split=sequence_splits[sequence_id],
                    features=selector_features(snapshot.evidence),
                    label=label,
                )
            )
    audit_calibration_rows(rows)
    return rows


def audit_calibration_rows(rows: Sequence[CalibrationRow]) -> None:
    if not rows:
        raise ValueError("calibration rows are empty")
    sequence_split: dict[str, str] = {}
    lineage_split: dict[tuple[str, int], str] = {}
    identities: set[tuple[str, int, int]] = set()
    for row in rows:
        if row.split not in {"train", "calibration"}:
            raise ValueError("row has an invalid split")
        if len(row.features) != len(FEATURE_NAMES):
            raise ValueError("row feature width mismatch")
        if any(not math.isfinite(float(value)) for value in row.features):
            raise ValueError("row contains non-finite features")
        if row.label not in {0, 1}:
            raise ValueError("row label is not binary")
        if row.source_group not in SOURCE_GROUPS:
            raise ValueError("row source group is invalid")
        identity = (row.sequence_id, row.lineage_id, row.decision_frame)
        if identity in identities:
            raise ValueError("duplicate track-lineage x decision-time row")
        identities.add(identity)
        previous = sequence_split.setdefault(row.sequence_id, row.split)
        if previous != row.split:
            raise ValueError("sequence appears in multiple splits")
        lineage_key = (row.sequence_id, row.lineage_id)
        previous = lineage_split.setdefault(lineage_key, row.split)
        if previous != row.split:
            raise ValueError("lineage appears in multiple splits")
    train_sequences = {row.sequence_id for row in rows if row.split == "train"}
    calibration_sequences = {row.sequence_id for row in rows if row.split == "calibration"}
    if train_sequences & calibration_sequences:
        raise ValueError("train/calibration sequences overlap")


def fit_pooled_reliability(
    rows: Sequence[CalibrationRow],
    *,
    horizon_frames: int = 5,
    alpha: float = 0.10,
    epochs: int = 800,
    learning_rate: float = 0.05,
    l2: float = 0.01,
    require_source_groups: bool = True,
) -> PooledReliabilityModel:
    audit_calibration_rows(rows)
    if require_source_groups and {row.source_group for row in rows} != SOURCE_GROUPS:
        raise ValueError("KLT, learned, and classical calibration rows are all required")
    train = [row for row in rows if row.split == "train"]
    calibration = [row for row in rows if row.split == "calibration"]
    if not train or not calibration:
        raise ValueError("both train and calibration rows are required")
    train_y = np.asarray([row.label for row in train], dtype=np.float64)
    if len(np.unique(train_y)) != 2:
        raise ValueError("training rows need both label classes")
    train_x = np.asarray([row.features for row in train], dtype=np.float64)
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    normalized = (train_x - mean) / scale
    weights = np.zeros((len(FEATURE_NAMES),), dtype=np.float64)
    positive_rate = float(np.clip(train_y.mean(), 1e-6, 1.0 - 1e-6))
    bias = math.log(positive_rate / (1.0 - positive_rate))
    for _ in range(int(epochs)):
        logits = normalized @ weights + bias
        prediction = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
        error = prediction - train_y
        weights -= float(learning_rate) * (
            normalized.T @ error / len(train_y) + float(l2) * weights
        )
        bias -= float(learning_rate) * float(error.mean())

    calibration_x = np.asarray([row.features for row in calibration], dtype=np.float64)
    calibration_y = np.asarray([row.label for row in calibration], dtype=np.float64)
    calibration_prediction = 1.0 / (
        1.0
        + np.exp(
            -np.clip((calibration_x - mean) / scale @ weights + bias, -40.0, 40.0)
        )
    )
    quantile = conformal_quantile(
        np.abs(calibration_y - calibration_prediction), float(alpha)
    )
    payload = {
        "feature_names": list(FEATURE_NAMES),
        "mean": [_float_token(value) for value in mean],
        "scale": [_float_token(value) for value in scale],
        "weights": [_float_token(value) for value in weights],
        "bias": _float_token(bias),
        "horizon_frames": int(horizon_frames),
        "alpha": _float_token(alpha),
        "conformal_quantile": _float_token(quantile),
        "train_sequences": sorted({row.sequence_id for row in train}),
        "calibration_sequences": sorted({row.sequence_id for row in calibration}),
        "row_identity_hash": _row_identity_hash(rows),
    }
    model_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return PooledReliabilityModel(
        feature_names=FEATURE_NAMES,
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
        horizon_frames=int(horizon_frames),
        alpha=float(alpha),
        conformal_quantile=float(quantile),
        model_hash=model_hash,
        train_sequences=tuple(sorted({row.sequence_id for row in train})),
        calibration_sequences=tuple(sorted({row.sequence_id for row in calibration})),
        row_identity_hash=str(payload["row_identity_hash"]),
    )


def calibration_audit(
    model: PooledReliabilityModel,
    rows: Sequence[CalibrationRow],
    *,
    ece_bins: int = 10,
) -> list[dict[str, object]]:
    calibration = [row for row in rows if row.split == "calibration"]
    if not calibration:
        raise ValueError("calibration audit requires calibration rows")
    groups: list[tuple[str, list[CalibrationRow]]] = [("overall", calibration)]
    for source in sorted({row.source_group for row in calibration}):
        groups.append((f"source:{source}", [row for row in calibration if row.source_group == source]))
    for geometry in sorted({row.geometry_stratum for row in calibration}):
        groups.append((f"geometry:{geometry}", [row for row in calibration if row.geometry_stratum == geometry]))
    output = []
    for name, group in groups:
        features = np.asarray([row.features for row in group], dtype=np.float64)
        labels = np.asarray([row.label for row in group], dtype=np.float64)
        prediction = model.p_hat(features)
        covered = np.abs(labels - prediction) <= model.conformal_quantile
        output.append(
            {
                "group": name,
                "rows": len(group),
                "coverage": float(np.mean(covered)),
                "ece": _ece(labels, prediction, ece_bins),
                "positive_rate": float(np.mean(labels)),
            }
        )
    return output


def write_calibration_rows(path: str | Path, rows: Sequence[CalibrationRow]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "sequence_id", "lineage_id", "source_group", "geometry_stratum",
        "decision_frame", "label_end_frame", "split", *FEATURE_NAMES, "label",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            record = {
                "sequence_id": row.sequence_id,
                "lineage_id": row.lineage_id,
                "source_group": row.source_group,
                "geometry_stratum": row.geometry_stratum,
                "decision_frame": row.decision_frame,
                "label_end_frame": row.label_end_frame,
                "split": row.split,
                "label": row.label,
            }
            record.update(dict(zip(FEATURE_NAMES, row.features)))
            writer.writerow(record)


def _ece(labels: np.ndarray, prediction: np.ndarray, bins: int) -> float:
    total = len(labels)
    value = 0.0
    for index in range(int(bins)):
        low = index / bins
        high = (index + 1) / bins
        mask = (prediction >= low) & (
            prediction <= high if index == bins - 1 else prediction < high
        )
        if np.any(mask):
            value += float(np.count_nonzero(mask)) / total * abs(
                float(np.mean(prediction[mask])) - float(np.mean(labels[mask]))
            )
    return float(value)


def _row_identity_hash(rows: Sequence[CalibrationRow]) -> str:
    identities = sorted(
        (row.sequence_id, row.lineage_id, row.decision_frame, row.label_end_frame, row.split, row.label)
        for row in rows
    )
    return hashlib.sha256(
        json.dumps(identities, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _float_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


__all__ = [
    "CalibrationRow",
    "FEATURE_NAMES",
    "PooledReliabilityModel",
    "SOURCE_GROUPS",
    "TemporalSnapshot",
    "audit_calibration_rows",
    "build_calibration_rows",
    "calibration_audit",
    "fit_pooled_reliability",
    "selector_features",
    "write_calibration_rows",
]
