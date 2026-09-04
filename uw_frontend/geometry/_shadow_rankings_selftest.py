"""Contract test for the five-arm shadow comparison.

Run: python3 -m uw_frontend.geometry._shadow_rankings_selftest

Core scenario (the paper's mechanism): two candidates lie in the SAME empty
far region (both far from KLT -> H ranks both high), plus one candidate that
fills a DIFFERENT empty region. H double-counts the redundant pair; QG, being
set-conditional, spreads its picks -> the H/QG top-n_t sets must differ (o<1).
"""

from __future__ import annotations

import sys

import numpy as np

from uw_frontend.geometry.marginal_support import MarginalSupportConfig, Track
from uw_frontend.geometry.shadow_rankings import compare_event

SHAPE = (640.0, 480.0)
RESULTS: list[tuple[str, bool, str]] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def _dense_base(n: int = 40, loc=(150.0, 150.0)) -> list[Track]:
    rng = np.random.default_rng(0)
    pts = rng.normal(loc=loc, scale=(30.0, 30.0), size=(n, 2))
    return [Track(1000 + i, float(x), float(y), 0.9, 0.0) for i, (x, y) in enumerate(pts)]


def _nearest_klt_distance(t: Track, base) -> float:
    return min(float(np.hypot(t.u - b.u, t.v - b.v)) for b in base)


def test_h_vs_qg_diverge_on_redundant_novelty() -> None:
    # base fills the top-left; the FARTHEST empty region is the bottom-right corner
    base = _dense_base(loc=(150.0, 150.0))
    # two mutually-close candidates in the farthest (bottom-right) corner
    a = Track(1, 620.0, 460.0, 0.9, 0.0)
    b = Track(2, 610.0, 455.0, 0.9, 0.0)
    # one candidate in the top-right: novel in u but closer to KLT than the pair
    c = Track(3, 620.0, 150.0, 0.9, 0.0)
    eligible = [a, b, c]
    h_scores = {t.track_id: _nearest_klt_distance(t, base) for t in eligible}
    cfg = MarginalSupportConfig(b_active=2, min_gain=0.0)
    cmp = compare_event(base, [], eligible, SHAPE, cfg, h_scores)

    _check("QG admits 2 (budget)", cmp.n_t == 2, f"n_t={cmp.n_t}")
    # H ranks purely by distance-to-KLT -> takes the two mutually-redundant corner points
    _check("H top-2 = the redundant pair", set(cmp.topn["h"]) == {1, 2}, f"h={cmp.topn['h']}")
    # QG conditions on the retained set -> drops the redundant twin, spreads to region c
    _check("QG top-2 spreads regions", 3 in cmp.topn["qg"], f"qg={cmp.topn['qg']}")
    _check("H/QG overlap < 1 (they differ)", cmp.overlap_vs_qg["h"] < 1.0,
           f"o_H={cmp.overlap_vs_qg['h']:.2f}")


def test_all_arms_present_and_matched() -> None:
    base = _dense_base()
    eligible = [Track(i, float(u), float(v), 0.5 + 0.1 * i, 0.0)
                for i, (u, v) in enumerate([(600, 40), (40, 40), (600, 440), (40, 440)])]
    h_scores = {t.track_id: _nearest_klt_distance(t, base) for t in eligible}
    cfg = MarginalSupportConfig(b_active=3, min_gain=0.0)
    cmp = compare_event(base, [], eligible, SHAPE, cfg, h_scores)
    _check("all five arms produce full orders",
           all(len(cmp.full_order[a]) == len(eligible) for a in ("r", "h", "q", "g", "qg")))
    _check("all top-n_t have size n_t",
           all(len(cmp.topn[a]) == cmp.n_t for a in ("r", "h", "q", "g", "qg")),
           f"n_t={cmp.n_t}")
    _check("QG overlaps itself = 1.0", abs(cmp.overlap_vs_qg["qg"] - 1.0) < 1e-9)


def test_q_arm_follows_reliability() -> None:
    base = _dense_base()
    # geometry roughly equal (all far corners), reliability differs
    eligible = [Track(1, 600.0, 40.0, 0.3, 0.0),
                Track(2, 40.0, 40.0, 0.95, 0.0),
                Track(3, 600.0, 440.0, 0.6, 0.0)]
    h_scores = {t.track_id: _nearest_klt_distance(t, base) for t in eligible}
    cfg = MarginalSupportConfig(b_active=1, min_gain=0.0)
    cmp = compare_event(base, [], eligible, SHAPE, cfg, h_scores)
    _check("Q top-1 = most reliable id", cmp.topn["q"][:1] == [2], f"q={cmp.topn['q']}")


def test_r_arm_is_grid_balanced() -> None:
    base = _dense_base()
    eligible = [
        Track(1, 20.0, 20.0, 0.5, 0.0),
        Track(2, 25.0, 25.0, 0.5, 0.0),
        Track(3, 320.0, 20.0, 0.5, 0.0),
        Track(4, 325.0, 25.0, 0.5, 0.0),
        Track(5, 620.0, 460.0, 0.5, 0.0),
        Track(6, 615.0, 455.0, 0.5, 0.0),
    ]
    h_scores = {track.track_id: _nearest_klt_distance(track, base) for track in eligible}
    cmp = compare_event(
        base,
        [],
        eligible,
        SHAPE,
        MarginalSupportConfig(b_active=3, min_gain=0.0),
        h_scores,
    )
    cells = {
        (min(2, int(next(t for t in eligible if t.track_id == track_id).u / SHAPE[0] * 3)),
         min(2, int(next(t for t in eligible if t.track_id == track_id).v / SHAPE[1] * 3)))
        for track_id in cmp.topn["r"]
    }
    _check("R top-3 spans three non-empty cells", len(cells) == 3, f"r={cmp.topn['r']}")


def main() -> int:
    for fn in [
        test_h_vs_qg_diverge_on_redundant_novelty,
        test_all_arms_present_and_matched,
        test_q_arm_follows_reliability,
        test_r_arm_is_grid_balanced,
    ]:
        fn()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{n_pass}/{len(RESULTS)} contracts passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
