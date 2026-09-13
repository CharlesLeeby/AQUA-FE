#!/usr/bin/env python3
"""Frozen v1 candidate-only adapter; never emits a relative pose or loop edge.

Encoder/model loading and the native VINS verifier bridge are NOT implemented
here. CLI input is a provenance-tagged cache of real keyframe descriptors.
Preprocessing/VLAD follow the pinned DL-VINS reference in the protocol, without
copying its ROS2/TensorRT deployment. There is no vocabulary fitting operation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import struct
from pathlib import Path

import numpy as np

VOCAB_SHA256 = "695985ec145406609d5c8d122092198886c4d89463c316e6a3b1606aee34143d"
PREPROCESS_ID = "dl-vits14-final-norm-patch-280x448-letterbox-imagenet-k32-v1"
FIELDS = ["sequence_id", "repeat", "arm", "query_id", "query_time_s",
          "candidate_id", "candidate_time_s", "rank", "score", "score_gate",
          "selected_for_geometry", "geometry_status", "correctness"]


def decode_vocabulary(blob: bytes) -> np.ndarray:
    if len(blob) != 8 + 32 * 384 * 4 or struct.unpack("<ii", blob[:8]) != (32, 384):
        raise ValueError("Expected exactly K=32, D=384 float32 vocabulary")
    if hashlib.sha256(blob).hexdigest() != VOCAB_SHA256:
        raise ValueError("Not the preregistered vocabulary")
    centers = np.frombuffer(blob, dtype="<f4", offset=8).reshape(32, 384)
    if not np.isfinite(centers).all():
        raise ValueError("Nonfinite vocabulary")
    return centers.copy()


def preprocess_bgr(image: np.ndarray) -> np.ndarray:
    import cv2
    if image.dtype != np.uint8 or image.ndim not in (2, 3) or min(image.shape[:2]) < 1:
        raise ValueError("Expected nonempty uint8 grayscale or BGR image")
    if image.ndim == 3 and image.shape[2] != 3:
        raise ValueError("Expected three BGR channels")
    h, w = image.shape[:2]
    scale = min(448 / w, 280 / h)
    nw, nh = int(w * scale), int(h * scale)
    if min(nw, nh) < 1:
        raise ValueError("Degenerate letterbox dimensions")
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB if image.ndim == 2 else cv2.COLOR_BGR2RGB)
    padded = np.zeros((280, 448, 3), dtype=np.uint8)
    x, y = (448 - nw) // 2, (280 - nh) // 2
    padded[y:y + nh, x:x + nw] = rgb
    data = padded.astype(np.float32) / 255.0
    data = (data - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
    return np.ascontiguousarray(data.transpose(2, 0, 1)[None])


def encode_vlad(tokens: np.ndarray, centers: np.ndarray) -> np.ndarray:
    tokens, centers = np.asarray(tokens, dtype=np.float32), np.asarray(centers, dtype=np.float32)
    if tokens.shape != (640, 384) or centers.shape != (32, 384):
        raise ValueError("Expected 640x384 final patch tokens and 32x384 centers")
    if not np.isfinite(tokens).all() or not np.isfinite(centers).all():
        raise ValueError("Nonfinite token/center")
    # Per-token differences avoid a large tokens x clusters x dimensions tensor.
    sums = np.zeros_like(centers)
    for token in tokens:
        residuals = token[None] - centers
        c = int(np.argmin(np.sum(residuals * residuals, axis=1)))
        sums[c] += residuals[c]
    sums /= np.maximum(np.linalg.norm(sums, axis=1, keepdims=True), 1e-12)
    result = (np.sign(sums) * np.sqrt(np.abs(sums))).reshape(-1)
    norm = np.linalg.norm(result)
    if not np.isfinite(norm) or norm < 1e-12:
        raise ValueError("Degenerate VLAD; not a valid cosine descriptor")
    return result / norm


def select_candidates(query_id: int, ids: np.ndarray, scores: np.ndarray, arm: str) -> list[dict]:
    """Apply shared history BEFORE top-4; caller must supply all eligible scores.

    For C these are native DBoW scores, not dense learned descriptors. A truncated
    native top-4 list containing its last-entry exception is not a valid input.
    """
    ids, scores = np.asarray(ids), np.asarray(scores)
    if arm not in ("C", "L") or ids.ndim != 1 or ids.shape != scores.shape:
        raise ValueError("Invalid arm/score vectors")
    if not np.issubdtype(ids.dtype, np.integer) or len(set(ids.tolist())) != len(ids) or np.any(ids < 0):
        raise ValueError("Candidate IDs must be unique nonnegative integers")
    if not np.isfinite(scores).all():
        raise ValueError("Nonfinite score")
    mask = ids < query_id - 50
    ids, scores = ids[mask], scores[mask]
    order = np.lexsort((ids, -scores))[:4]
    ranked = [(int(ids[i]), float(scores[i])) for i in order]
    if arm == "C":
        gate = len(ranked) > 1 and ranked[0][1] > .05 and any(s > .015 for _, s in ranked[1:])
        eligible = [i for i, s in ranked if gate and s > .015]
    else:
        eligible = [i for i, s in ranked if s >= .60]
        gate = bool(eligible)
    selected = min(eligible) if eligible else None
    return [dict(candidate_id=i, rank=r + 1, score=s, score_gate=int(gate),
                 selected_for_geometry=int(i == selected),
                 geometry_status="Not evaluated", correctness="Unknown")
            for r, (i, s) in enumerate(ranked)]


def load_cache(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        if str(data["vocabulary_sha256"].item()) != VOCAB_SHA256 or str(data["preprocess"].item()) != PREPROCESS_ID:
            raise ValueError("Descriptor configuration identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", str(data["model_sha256"].item())):
            raise ValueError("Missing actual encoder weight hash")
        ids, times, descriptors = data["ids"].copy(), data["timestamps"].copy(), data["descriptors"].copy()
        image_hashes = data["image_sha256"].tolist()
    n = len(ids)
    if not np.issubdtype(ids.dtype, np.integer) or not np.array_equal(ids, np.arange(n)):
        raise ValueError("Cache IDs must match the contiguous archived keyframe roster")
    if times.shape != (n,) or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
        raise ValueError("Keyframe header times must be finite and strictly increasing")
    if n == 0 or descriptors.shape != (n, 12288) or not np.isfinite(descriptors).all():
        raise ValueError("Invalid descriptor matrix")
    if not np.allclose(np.linalg.norm(descriptors, axis=1), 1., atol=1e-4):
        raise ValueError("Descriptors must already be unit length; no silent repair")
    if len(image_hashes) != n or any(not re.fullmatch(r"[0-9a-f]{64}", str(x)) for x in image_hashes):
        raise ValueError("Missing keyframe image identity")
    return ids, times, descriptors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ids, times, descriptors = load_cache(args.cache)
    # 'x' prevents accidental replacement of an existing experiment result.
    with args.output.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for q in range(len(ids)):
            history = ids[:max(0, q - 50)]
            scores = descriptors[history] @ descriptors[q]
            for row in select_candidates(q, history, scores, "L"):
                row.update(sequence_id=args.sequence, repeat=args.repeat, arm="L", query_id=q,
                           query_time_s=times[q], candidate_time_s=times[row["candidate_id"]])
                writer.writerow(row)


if __name__ == "__main__":
    main()
