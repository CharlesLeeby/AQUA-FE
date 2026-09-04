#!/usr/bin/env python3
"""Validate QG on real geometry in a candidate-surplus regime (GT-free).

Motivation: the frozen novelty+motion gate starves the matured pool to 3-8
candidates, so H and QG rarely differ (see qg-selector-supply-bottleneck memory).
But the GENERATOR yields ~80 distinct candidates/window and ~24 survive >=5
frames. This probe exposes that survival>=k surplus pool and, at a matched
budget b, compares the five arms by two GT-free measurement-set quality metrics
the paper uses:

  - distinct grid cells occupied by the selected candidates (spatial spread)
  - mean provisional reliability of the selected candidates

Reliability here is a PROVISIONAL survival proxy (q ~ how long the track has
lived so far), monotone with the survival label the conformal calibrator is
trained on. This is a mechanism probe, NOT a confirmatory result, and it does
not change any export.
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

import rosbag

from uw_frontend.ros.causal_lineage_shadow_node import _channel_values, _pixels, _safe_int
from uw_frontend.geometry.marginal_support import MarginalSupportConfig, Track
from uw_frontend.geometry.shadow_rankings import ARMS, compare_event

FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"


def _messages(path: Path, topic: str):
    with rosbag.Bag(str(path)) as bag:
        return [m for _t, m, _ts in bag.read_messages(topics=[topic])]


def _base_pixels(full_msg):
    n = len(full_msg.points)
    il = _channel_values(full_msg, "is_learned", n, 0.0)
    p_u = _channel_values(full_msg, "p_u", n, float("nan"))
    p_v = _channel_values(full_msg, "p_v", n, float("nan"))
    return [(float(p_u[i]), float(p_v[i])) for i in range(n)
            if int(round(float(il[i]))) == 0 and p_u[i] == p_u[i] and p_v[i] == p_v[i]]


def _seeds(sidecar):
    n = len(sidecar.points)
    ids = _channel_values(sidecar, "id", n, -1.0)
    il = _channel_values(sidecar, "is_learned", n, 0.0)
    sc = _channel_values(sidecar, "source_code", n, 0.0)
    p_u = _channel_values(sidecar, "p_u", n, float("nan"))
    p_v = _channel_values(sidecar, "p_v", n, float("nan"))
    out = {}
    for i in range(n):
        fid = _safe_int(ids[i], -1)
        if (int(round(float(il[i]))) or int(round(float(sc[i]))) == 20) and p_u[i] == p_u[i]:
            out.setdefault(fid, (float(p_u[i]), float(p_v[i])))
    return out


def _cell(u, v, shape, g):
    return (min(g - 1, int(u / shape[0] * g)), min(g - 1, int(v / shape[1] * g)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", required=True)
    ap.add_argument("--sidecar", required=True)
    ap.add_argument("--survival", type=int, default=5, help="min frames alive to enter surplus pool")
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--grid", type=int, default=8)
    ap.add_argument("--surplus-margin", type=int, default=2, help="require pool >= budget+margin")
    args = ap.parse_args()

    full = _messages(Path(args.full), FEATURE_TOPIC)
    side = _messages(Path(args.sidecar), SIDECAR_TOPIC)
    nf = min(len(full), len(side))

    umax = vmax = 1.0
    for m in side + full:
        n = len(m.points)
        for u in _channel_values(m, "p_u", n, 0.0): umax = max(umax, float(u))
        for v in _channel_values(m, "p_v", n, 0.0): vmax = max(vmax, float(v))
    shape = (umax + 1.0, vmax + 1.0)

    life = defaultdict(int)
    cfg = MarginalSupportConfig(weight_mode="qg", b_active=args.budget, min_gain=0.0)

    cells = {a: [] for a in ARMS}
    relia = {a: [] for a in ARMS}
    overlaps = []
    scored_frames = 0

    for f in range(nf):
        present = _seeds(side[f])
        for fid in present:
            life[fid] += 1
        pool_ids = [fid for fid in present if life[fid] >= args.survival]
        if len(pool_ids) < args.budget + args.surplus_margin:
            continue
        scored_frames += 1

        base_px = _base_pixels(full[f])
        base_tracks = [Track(10 ** 7 + i, u, v, 1.0, 0.0) for i, (u, v) in enumerate(base_px)]

        def q_of(fid):  # provisional survival-proxy reliability
            return max(0.1, min(0.95, life[fid] / 15.0))

        def near_klt(u, v):
            return min((((u - bu) ** 2 + (v - bv) ** 2) ** 0.5 for bu, bv in base_px), default=0.0)

        eligible = [Track(fid, present[fid][0], present[fid][1], q_of(fid), 0.0) for fid in pool_ids]
        h_scores = {fid: near_klt(*present[fid]) for fid in pool_ids}

        cmp = compare_event(base_tracks, [], eligible, shape, cfg, h_scores)
        overlaps.append(cmp.overlap_vs_qg["h"])
        pos = {fid: present[fid] for fid in pool_ids}
        for arm in ARMS:
            sel = cmp.topn[arm]
            occ = {_cell(*pos[fid], shape, args.grid) for fid in sel}
            cells[arm].append(len(occ))
            relia[arm].append(statistics.mean(q_of(fid) for fid in sel) if sel else 0.0)

    print(f"window: {Path(args.full).parent.name}")
    print(f"frames={nf} image={shape[0]:.0f}x{shape[1]:.0f} survival>={args.survival} "
          f"budget={args.budget} grid={args.grid}x{args.grid}")
    print(f"surplus decision frames scored (pool>={args.budget + args.surplus_margin}): {scored_frames}")
    if not scored_frames:
        print("no surplus frames -> relax --survival or lower --budget")
        return 0
    print(f"\n{'arm':>4} | {'mean distinct cells':>20} | {'mean selected reliability':>26}")
    print("-" * 60)
    for arm in ("r", "h", "q", "g", "qg"):
        print(f"{arm:>4} | {statistics.mean(cells[arm]):>20.3f} | {statistics.mean(relia[arm]):>26.3f}")
    print(f"\nmean H-vs-QG top-{args.budget} overlap: {statistics.mean(overlaps):.3f} "
          f"(1.0=identical, <1=QG selects differently)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
