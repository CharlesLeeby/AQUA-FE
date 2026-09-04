"""Reliability-calibrated marginal geometric-support selection.

This is the paper's headline selector (ISJ plan section 6.2 / P03A). Given the
native KLT base set ``K_t^0``, the already-accepted-and-active lineage ``L_t``
and the new eligible candidates ``E_t`` at a decision event, it selects which
candidate lineages to admit by their *marginal* view-space conditioning gain
relative to the measurements already retained, each weighted by a conservative
conformal reliability ``q_i^-``.

The objective is a quality-weighted log-determinant on 3x3 normalized
image-plane vectors ``z_i = [1, 2u/W-1, 2v/H-1]``:

    A(S) = lambda_A * I + sum_{i in K^0 u L u S} w_i z_i z_i^T
    Delta(c | S) = logdet A(S u {c}) - logdet A(S)
                 = log(1 + w_c z_c^T A(S)^{-1} z_c)          (matrix determinant lemma)
    w_i = q_i^- * exp(-e_i / tau_e)

with ``e_i`` a pre-clipped normalized geometric residual. The log-det objective
is monotone submodular under PSD rank-one increments, so the cardinality-bounded
greedy has the standard ``1 - 1/e`` guarantee. This module is deliberately a
*pure* function of its inputs (no model fitting, no I/O) so it can be unit-tested
in isolation and produce a deterministic per-event hash.

NOTE: this is an image-plane view-space support surrogate, NOT a 6DoF FIM or
pose observability quantity (see plan 6.2 wording lock).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class MarginalSupportConfig:
    lambda_a: float = 1.0        # positive regularizer on A_0 (keeps it SPD)
    tau_e: float = 1.0           # residual temperature (dimensionless)
    e_max: float = 4.0           # clip cap for normalized residual e_i
    b_active: int = 8            # concurrent accepted-lineage cap
    total_feature_cap: int = 350  # total exported features, KLT base included
    min_gain: float = 1e-3       # greedy stop threshold on marginal gain
    weight_mode: str = "qg"      # qg | g | q | r  (ablation arms)
    random_seed: int = 20260730  # for the R (pseudorandom) control
    random_grid_rows: int = 3
    random_grid_cols: int = 3

    def __post_init__(self) -> None:
        if float(self.lambda_a) <= 0.0:
            raise ValueError("lambda_a must be > 0 to keep A_0 SPD")
        if float(self.tau_e) <= 0.0:
            raise ValueError("tau_e must be > 0")
        if float(self.e_max) <= 0.0:
            raise ValueError("e_max must be > 0")
        if int(self.b_active) < 0 or int(self.total_feature_cap) < 0:
            raise ValueError("b_active and total_feature_cap must be non-negative")
        if float(self.min_gain) < 0.0:
            raise ValueError("min_gain must be >= 0")
        if self.weight_mode not in {"qg", "g", "q", "r"}:
            raise ValueError(f"unsupported weight_mode: {self.weight_mode}")
        if int(self.random_grid_rows) <= 0 or int(self.random_grid_cols) <= 0:
            raise ValueError("random grid dimensions must be positive")


@dataclass(frozen=True)
class Track:
    """A single track at the decision event (base, active or candidate)."""

    track_id: int
    u: float
    v: float
    q_lower: float   # conservative conformal reliability q_i^-
    e: float = 0.0   # normalized geometric residual (pre-clip)


@dataclass(frozen=True)
class CandidateDecision:
    track_id: int
    selected: bool
    rank: int          # 1-based admission order; 0 if rejected
    gain: float
    weight: float
    q_lower: float
    e: float
    reason: str        # ACCEPTED | BELOW_MIN_GAIN | BUDGET_FULL | NO_SLOT


@dataclass
class SelectionResult:
    selected_ids: list[int]
    decisions: list[CandidateDecision]
    n_base: int
    n_active: int
    n_candidates: int
    b_slots: int
    frame_hash: str


def _z(u: float, v: float, w: float, h: float) -> np.ndarray:
    return np.array([1.0, 2.0 * float(u) / float(w) - 1.0, 2.0 * float(v) / float(h) - 1.0], dtype=np.float64)


def _weight(t: Track, cfg: MarginalSupportConfig) -> float:
    q = 1.0 if cfg.weight_mode == "g" else float(np.clip(t.q_lower, 0.0, 1.0))
    e = min(max(float(t.e), 0.0), float(cfg.e_max))
    return float(q * np.exp(-e / float(cfg.tau_e)))


def _build_a0(
    base: Sequence[Track],
    active: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
) -> np.ndarray:
    w_img, h_img = image_shape
    a0 = float(cfg.lambda_a) * np.eye(3, dtype=np.float64)
    for t in list(base) + list(active):
        z = _z(t.u, t.v, w_img, h_img)
        a0 += _weight(t, cfg) * np.outer(z, z)
    return a0


def _canonical_hash(
    base: Sequence[Track],
    active: Sequence[Track],
    candidates: Sequence[Track],
    decisions: Sequence[CandidateDecision],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
    *,
    base_export_count: int,
    b_slots: int,
    has_valid_base_model: bool,
    model_fit_hash: str,
    selector_model_hash: str,
    previous_frame_hash: str,
) -> str:
    width, height = image_shape
    payload = {
        "config": {
            "lambda_a": repr(float(cfg.lambda_a)),
            "tau_e": repr(float(cfg.tau_e)),
            "e_max": repr(float(cfg.e_max)),
            "b_active": int(cfg.b_active),
            "total_feature_cap": int(cfg.total_feature_cap),
            "min_gain": repr(float(cfg.min_gain)),
            "weight_mode": cfg.weight_mode,
            "random_seed": int(cfg.random_seed),
            "random_grid_rows": int(cfg.random_grid_rows),
            "random_grid_cols": int(cfg.random_grid_cols),
        },
        "image_shape": [_float_token(width), _float_token(height)],
        "base_export_count": int(base_export_count),
        "b_slots": int(b_slots),
        "has_valid_base_model": bool(has_valid_base_model),
        "model_fit_hash": str(model_fit_hash),
        "selector_model_hash": str(selector_model_hash),
        "previous_frame_hash": str(previous_frame_hash),
        "k0": [_track_hash_payload(track, width, height) for track in sorted(base, key=lambda item: item.track_id)],
        "active_l": [_track_hash_payload(track, width, height) for track in sorted(active, key=lambda item: item.track_id)],
        "eligible_e": [_track_hash_payload(track, width, height) for track in sorted(candidates, key=lambda item: item.track_id)],
        # ordered by admission rank then id for rejected: canonical, order-invariant
        "decisions": sorted(
            (
                [int(d.track_id), bool(d.selected), int(d.rank), repr(float(d.gain)), d.reason]
                for d in decisions
            ),
            key=lambda row: (0 if row[1] else 1, row[2], row[0]),
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def select_marginal_support(
    base: Sequence[Track],
    active: Sequence[Track],
    candidates: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
    *,
    base_export_count: int | None = None,
    has_valid_base_model: bool = True,
    model_fit_hash: str = "",
    selector_model_hash: str = "",
    previous_frame_hash: str = "",
) -> SelectionResult:
    """Select which candidate lineages to admit at one decision event.

    ``base`` = K_t^0 (native KLT), ``active`` = L_t (already-accepted active
    lineage), ``candidates`` = E_t (new eligible candidates). Returns a
    deterministic, tie-break-stable selection and per-candidate decision log.
    """

    w_img, h_img = image_shape
    if not math.isfinite(float(w_img)) or not math.isfinite(float(h_img)) or w_img <= 0 or h_img <= 0:
        raise ValueError("image_shape must be finite positive (width, height)")
    _validate_sets(base, active, candidates, image_shape, cfg)
    n_base = len(base)
    n_active = len(active)
    n_cand = len(candidates)

    base_export = n_base if base_export_count is None else int(base_export_count)
    if base_export < 0 or base_export > n_base:
        raise ValueError("base_export_count must be in [0, len(base)]")
    # New-admission slots obey both the concurrent lineage cap and the separate
    # total exported-feature cap. The base count is therefore never silently
    # excluded from the dose contract.
    b_slots = max(0, int(cfg.b_active) - n_active)
    b_slots = min(
        b_slots,
        max(0, int(cfg.total_feature_cap) - base_export - n_active),
    )

    decisions: dict[int, CandidateDecision] = {}
    selected: list[int] = []

    if not has_valid_base_model:
        result_decisions = [
            CandidateDecision(
                int(candidate.track_id),
                False,
                0,
                0.0,
                _weight(candidate, cfg),
                float(candidate.q_lower),
                float(candidate.e),
                "NO_VALID_BASE_MODEL",
            )
            for candidate in candidates
        ]
        frame_hash = _canonical_hash(
            base, active, candidates, result_decisions, image_shape, cfg,
            base_export_count=base_export,
            b_slots=0,
            has_valid_base_model=False,
            model_fit_hash=model_fit_hash,
            selector_model_hash=selector_model_hash,
            previous_frame_hash=previous_frame_hash,
        )
        return SelectionResult([], result_decisions, n_base, n_active, n_cand, 0, frame_hash)

    if cfg.weight_mode in {"q", "r"}:
        selected, decisions = _rank_select(candidates, cfg, b_slots, image_shape)
        result_decisions = [decisions[c.track_id] for c in candidates]
        return SelectionResult(selected, result_decisions, n_base, n_active, n_cand, b_slots,
                               _canonical_hash(
                                   base, active, candidates, result_decisions, image_shape, cfg,
                                   base_export_count=base_export,
                                   b_slots=b_slots,
                                   has_valid_base_model=True,
                                   model_fit_hash=model_fit_hash,
                                   selector_model_hash=selector_model_hash,
                                   previous_frame_hash=previous_frame_hash,
                               ))

    # qg / g : greedy submodular marginal-gain selection
    a_mat = _build_a0(base, active, image_shape, cfg)
    remaining = {c.track_id: c for c in candidates}
    rank = 0
    stop_reason = "BUDGET_FULL"

    while remaining and len(selected) < b_slots:
        scored = []
        for c in remaining.values():
            z = _z(c.u, c.v, w_img, h_img)
            w = _weight(c, cfg)
            # A(S)^{-1} z via linear solve (A SPD, no explicit inverse)
            solved = _solve_spd(a_mat, z)
            quad = float(z @ solved)
            gain = float(np.log1p(max(0.0, w * quad)))
            scored.append((gain, c.track_id, c, w))
        # deterministic: max gain, tie-break by ascending id
        scored.sort(key=lambda row: (-row[0], row[1]))
        best_gain, best_id, best_c, best_w = scored[0]
        if best_gain < float(cfg.min_gain):
            stop_reason = "BELOW_MIN_GAIN"
            break
        rank += 1
        z = _z(best_c.u, best_c.v, w_img, h_img)
        a_mat = a_mat + best_w * np.outer(z, z)
        selected.append(best_id)
        decisions[best_id] = CandidateDecision(
            best_id, True, rank, best_gain, best_w, float(best_c.q_lower), float(best_c.e), "ACCEPTED"
        )
        del remaining[best_id]

    # log rejected candidates
    for c in candidates:
        if c.track_id in decisions:
            continue
        z = _z(c.u, c.v, w_img, h_img)
        w = _weight(c, cfg)
        solved = _solve_spd(a_mat, z)
        gain = float(np.log1p(max(0.0, w * float(z @ solved))))
        reason = "NO_SLOT" if b_slots == 0 else stop_reason
        decisions[c.track_id] = CandidateDecision(
            c.track_id, False, 0, gain, w, float(c.q_lower), float(c.e), reason
        )

    result_decisions = [decisions[c.track_id] for c in candidates]
    return SelectionResult(
        selected, result_decisions, n_base, n_active, n_cand, b_slots,
        _canonical_hash(
            base, active, candidates, result_decisions, image_shape, cfg,
            base_export_count=base_export,
            b_slots=b_slots,
            has_valid_base_model=True,
            model_fit_hash=model_fit_hash,
            selector_model_hash=selector_model_hash,
            previous_frame_hash=previous_frame_hash,
        ),
    )


def _solve_spd(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    cholesky = np.linalg.cholesky(np.asarray(matrix, dtype=np.float64))
    return np.linalg.solve(cholesky.T, np.linalg.solve(cholesky, vector))


def _validate_sets(
    base: Sequence[Track],
    active: Sequence[Track],
    candidates: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
) -> None:
    width, height = image_shape
    groups = (("K0", base), ("L", active), ("E", candidates))
    all_ids: list[int] = []
    for label, tracks in groups:
        ids = [int(track.track_id) for track in tracks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate ID inside {label}")
        all_ids.extend(ids)
        for track in tracks:
            values = (track.u, track.v, track.q_lower, track.e)
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError(f"non-finite track evidence in {label}")
            if not (0.0 <= float(track.u) < width and 0.0 <= float(track.v) < height):
                raise ValueError(f"track outside image bounds in {label}")
            if not 0.0 <= float(track.q_lower) <= 1.0:
                raise ValueError(f"q_lower outside [0,1] in {label}")
            if not 0.0 <= float(track.e) <= float(cfg.e_max):
                raise ValueError(f"normalized residual outside [0,e_max] in {label}")
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("K0, L, and E IDs must be mutually disjoint")


def _track_hash_payload(track: Track, width: float, height: float) -> list[object]:
    return [
        int(track.track_id),
        _float_token(track.u),
        _float_token(track.v),
        [_float_token(1.0), _float_token(2.0 * track.u / width - 1.0), _float_token(2.0 * track.v / height - 1.0)],
        _float_token(track.q_lower),
        _float_token(track.e),
    ]


def _float_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def _rank_select(
    candidates: Sequence[Track],
    cfg: MarginalSupportConfig,
    b_slots: int,
    image_shape: tuple[float, float],
) -> tuple[list[int], dict[int, CandidateDecision]]:
    """Q (reliability-only) and R (pseudorandom) single-factor controls."""

    if cfg.weight_mode == "q":
        order = sorted(candidates, key=lambda c: (-float(c.q_lower), int(c.track_id)))
        keyfn = lambda c: float(c.q_lower)
    else:  # r : grid-balanced stable pseudorandom keyed by fixed seed
        order = stable_grid_random_order(candidates, image_shape, cfg)
        keyfn = lambda c: _random_key(cfg.random_seed, f"track:{int(c.track_id)}")

    selected: list[int] = []
    decisions: dict[int, CandidateDecision] = {}
    for rank, c in enumerate(order, start=1):
        if len(selected) < b_slots:
            selected.append(int(c.track_id))
            score = float(keyfn(c))
            decisions[c.track_id] = CandidateDecision(
                int(c.track_id), True, len(selected), score, score if cfg.weight_mode == "q" else 1.0,
                float(c.q_lower), float(c.e), "ACCEPTED",
            )
        else:
            score = float(keyfn(c))
            decisions[c.track_id] = CandidateDecision(
                int(c.track_id), False, 0, score, score if cfg.weight_mode == "q" else 1.0,
                float(c.q_lower), float(c.e), "NO_SLOT" if b_slots == 0 else "BUDGET_FULL",
            )
    return selected, decisions


def stable_grid_random_order(
    candidates: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
) -> list[Track]:
    """Round-robin non-empty cells; randomize cells/items with a stable seed."""

    width, height = image_shape
    rows = int(cfg.random_grid_rows)
    cols = int(cfg.random_grid_cols)
    cells: dict[tuple[int, int], list[Track]] = {}
    for candidate in candidates:
        row = min(rows - 1, max(0, int(float(candidate.v) / float(height) * rows)))
        col = min(cols - 1, max(0, int(float(candidate.u) / float(width) * cols)))
        cells.setdefault((row, col), []).append(candidate)
    for cell, tracks in cells.items():
        tracks.sort(
            key=lambda candidate: (
                _random_key(cfg.random_seed, f"cell:{cell[0]}:{cell[1]}:track:{candidate.track_id}"),
                int(candidate.track_id),
            )
        )
    cell_order = sorted(
        cells,
        key=lambda cell: (
            _random_key(cfg.random_seed, f"cell:{cell[0]}:{cell[1]}"),
            cell,
        ),
    )
    order: list[Track] = []
    depth = 0
    while True:
        appended = False
        for cell in cell_order:
            if depth < len(cells[cell]):
                order.append(cells[cell][depth])
                appended = True
        if not appended:
            break
        depth += 1
    return order


def _random_key(seed: int, value: str) -> float:
    digest = hashlib.sha256(f"{int(seed)}:{value}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)
