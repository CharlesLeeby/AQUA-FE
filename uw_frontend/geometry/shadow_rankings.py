"""Five-arm shadow ranking comparison (ISJ plan 6.7 step 2/4/5).

At each decision event this compares the candidate ORDERINGS of five arms over
one shared eligible-candidate stream E_t (the selector-independent master
stream), *without* changing any actual export decision:

    R   pseudorandom control (fixed seed)
    H   legacy distance/grid heuristic  (key = -nearest_klt_distance, id)
    Q   reliability only                (key = -q_lower, id)
    G   geometric marginal gain, q_lower:=1
    QG  reliability-calibrated marginal geometric-support gain  (proposed)

It emits the admission-count-matched overlap ``o_t = |S_H n S_QG| / n_t`` and
per-arm top-n_t selections, where ``n_t = |S_QG,t|`` (the number QG admits).
This is the object the plan uses to decide whether QG selects *differently*
from H (o < 0.90) and whether the difference is directed toward better
candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from uw_frontend.geometry.marginal_support import (
    MarginalSupportConfig,
    Track,
    select_marginal_support,
    stable_grid_random_order,
)

ARMS = ("r", "h", "q", "g", "qg")


@dataclass
class EventComparison:
    n_t: int                                   # QG admission count (matched budget)
    full_order: dict[str, list[int]]           # arm -> full candidate ordering
    topn: dict[str, list[int]]                 # arm -> top-n_t selection
    overlap_vs_qg: dict[str, float]            # arm -> |S_arm n S_QG| / n_t
    rank_percentile: dict[str, dict[int, float]]  # arm -> {id: percentile in [0,1], 0=top}


def _greedy_full_order(
    base: Sequence[Track],
    active: Sequence[Track],
    eligible: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
    mode: str,
    base_export_count: int | None = None,
) -> list[int]:
    """Full admission ordering for qg/g by running greedy with an open budget."""
    open_cfg = replace(
        cfg,
        weight_mode=mode,
        b_active=len(active) + len(eligible),
        total_feature_cap=10 ** 9,
        min_gain=0.0,
    )
    res = select_marginal_support(
        base,
        active,
        eligible,
        image_shape,
        open_cfg,
        base_export_count=base_export_count,
    )
    ordered = [d.track_id for d in sorted(
        (d for d in res.decisions if d.selected), key=lambda d: d.rank)]
    # any candidate not admitted (shouldn't happen with open budget) appended by id
    leftover = [c.track_id for c in eligible if c.track_id not in ordered]
    return ordered + sorted(leftover)


def _heuristic_order(eligible: Sequence[Track], h_scores: dict[int, float]) -> list[int]:
    return [c.track_id for c in sorted(
        eligible, key=lambda c: (-float(h_scores.get(c.track_id, 0.0)), int(c.track_id)))]


def _reliability_order(eligible: Sequence[Track]) -> list[int]:
    return [c.track_id for c in sorted(
        eligible, key=lambda c: (-float(c.q_lower), int(c.track_id)))]


def _random_order(
    eligible: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
) -> list[int]:
    return [candidate.track_id for candidate in stable_grid_random_order(eligible, image_shape, cfg)]


def compare_event(
    base: Sequence[Track],
    active: Sequence[Track],
    eligible: Sequence[Track],
    image_shape: tuple[float, float],
    cfg: MarginalSupportConfig,
    h_scores: dict[int, float],
    *,
    base_export_count: int | None = None,
) -> EventComparison:
    """Compare all five arms at one decision event over the shared eligible stream."""

    # QG is the reference; its budgeted selection sets the matched count n_t
    qg_res = select_marginal_support(base, active, eligible, image_shape,
                                     replace(cfg, weight_mode="qg"),
                                     base_export_count=base_export_count)
    n_t = len(qg_res.selected_ids)

    full_order = {
        "qg": _greedy_full_order(base, active, eligible, image_shape, cfg, "qg", base_export_count),
        "g": _greedy_full_order(base, active, eligible, image_shape, cfg, "g", base_export_count),
        "q": _reliability_order(eligible),
        "h": _heuristic_order(eligible, h_scores),
        "r": _random_order(eligible, image_shape, cfg),
    }

    topn = {arm: order[:n_t] for arm, order in full_order.items()}
    qg_set = set(topn["qg"])
    overlap = {
        arm: (len(set(sel) & qg_set) / n_t if n_t > 0 else float("nan"))
        for arm, sel in topn.items()
    }

    n_cand = len(eligible)
    rank_percentile: dict[str, dict[int, float]] = {}
    for arm, order in full_order.items():
        denom = max(1, n_cand - 1)
        rank_percentile[arm] = {cid: (idx / denom) for idx, cid in enumerate(order)}

    return EventComparison(
        n_t=n_t,
        full_order=full_order,
        topn=topn,
        overlap_vs_qg=overlap,
        rank_percentile=rank_percentile,
    )
