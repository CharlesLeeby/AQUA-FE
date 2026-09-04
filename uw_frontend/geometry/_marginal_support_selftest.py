"""Synthetic contract tests for the marginal-support selector (ISJ plan 6.7 step 3).

Run: python3 -m uw_frontend.geometry._marginal_support_selftest
Empirical-validation style (no pytest): prints PASS/FAIL per contract, exits 1 on any failure.
"""

from __future__ import annotations

import sys
import hashlib

import numpy as np

from uw_frontend.geometry.marginal_support import (
    MarginalSupportConfig,
    Track,
    select_marginal_support,
)

SHAPE = (640.0, 480.0)
RESULTS: list[tuple[str, bool, str]] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def _dense_base(n: int = 40) -> list[Track]:
    """A dense cluster of KLT base tracks in the left-center region."""
    rng = np.random.default_rng(0)
    pts = rng.normal(loc=(160.0, 240.0), scale=(18.0, 18.0), size=(n, 2))
    return [Track(1000 + i, float(x), float(y), 0.9, 0.0) for i, (x, y) in enumerate(pts)]


def test_redundant_vs_new_region() -> None:
    base = _dense_base()
    redundant = Track(1, 160.0, 240.0, 0.9, 0.0)     # inside the base cluster
    new_region = Track(2, 600.0, 40.0, 0.9, 0.0)      # empty far corner
    cfg = MarginalSupportConfig(b_active=8, min_gain=0.0)
    res = select_marginal_support(base, [], [redundant, new_region], SHAPE, cfg)
    gain = {d.track_id: d.gain for d in res.decisions}
    ok = gain[2] > gain[1]
    _check("new-region gain > redundant gain", ok, f"new={gain[2]:.5f} redundant={gain[1]:.5f}")
    # and the new-region candidate must be admitted first
    _check("new-region admitted rank 1", res.selected_ids[0] == 2, f"selected={res.selected_ids}")


def test_low_reliability_downweights() -> None:
    base = _dense_base()
    hi = Track(1, 600.0, 40.0, 0.9, 0.0)
    lo = Track(2, 600.0, 40.0, 0.3, 0.0)   # same position, lower q_lower
    cfg = MarginalSupportConfig(b_active=8, min_gain=0.0)
    res_hi = select_marginal_support(base, [], [hi], SHAPE, cfg)
    res_lo = select_marginal_support(base, [], [lo], SHAPE, cfg)
    g_hi = res_hi.decisions[0].gain
    g_lo = res_lo.decisions[0].gain
    _check("higher q_lower -> higher gain", g_hi > g_lo, f"q0.9={g_hi:.5f} q0.3={g_lo:.5f}")


def test_residual_downweights() -> None:
    base = _dense_base()
    clean = Track(1, 600.0, 40.0, 0.9, 0.0)
    noisy = Track(2, 600.0, 40.0, 0.9, 3.0)   # same pos/q, large normalized residual
    cfg = MarginalSupportConfig(b_active=8, min_gain=0.0, tau_e=1.0)
    g_clean = select_marginal_support(base, [], [clean], SHAPE, cfg).decisions[0].gain
    g_noisy = select_marginal_support(base, [], [noisy], SHAPE, cfg).decisions[0].gain
    _check("higher residual -> lower gain", g_clean > g_noisy, f"e0={g_clean:.5f} e3={g_noisy:.5f}")


def test_resolution_scale_invariance() -> None:
    base = _dense_base()
    cands = [Track(1, 160.0, 240.0, 0.9, 0.0), Track(2, 600.0, 40.0, 0.9, 0.0),
             Track(3, 320.0, 300.0, 0.7, 0.5)]
    cfg = MarginalSupportConfig(b_active=8, min_gain=0.0)
    res1 = select_marginal_support(base, [], cands, SHAPE, cfg)
    # scale image and every coordinate by 2x -> identical normalized z -> identical selection
    base2 = [Track(t.track_id, t.u * 2, t.v * 2, t.q_lower, t.e) for t in base]
    cands2 = [Track(t.track_id, t.u * 2, t.v * 2, t.q_lower, t.e) for t in cands]
    res2 = select_marginal_support(base2, [], cands2, (1280.0, 960.0), cfg)
    _check("scale-invariant selection order", res1.selected_ids == res2.selected_ids,
           f"{res1.selected_ids} vs {res2.selected_ids}")
    _check("image-shape-sensitive frame hash", res1.frame_hash != res2.frame_hash)


def test_deterministic_and_order_invariant() -> None:
    base = _dense_base()
    cands = [Track(i, float(u), float(v), 0.8, 0.0)
             for i, (u, v) in enumerate([(600, 40), (40, 40), (600, 440), (40, 440), (320, 240)])]
    cfg = MarginalSupportConfig(b_active=3, min_gain=0.0)
    res_a = select_marginal_support(base, [], cands, SHAPE, cfg)
    res_b = select_marginal_support(base, [], list(reversed(cands)), SHAPE, cfg)
    _check("input-order-invariant selection", res_a.selected_ids == res_b.selected_ids,
           f"{res_a.selected_ids} vs {res_b.selected_ids}")
    _check("input-order-invariant hash", res_a.frame_hash == res_b.frame_hash)


def test_budget_and_min_gain_stops() -> None:
    base = _dense_base()
    cands = [Track(i, float(u), float(v), 0.8, 0.0)
             for i, (u, v) in enumerate([(600, 40), (40, 40), (600, 440), (40, 440), (320, 240)])]
    # budget cap
    cfg_b = MarginalSupportConfig(b_active=2, min_gain=0.0)
    res_b = select_marginal_support(base, [], cands, SHAPE, cfg_b)
    _check("respects b_active budget", len(res_b.selected_ids) == 2, f"selected={res_b.selected_ids}")
    # active lineage consumes slots
    active = [Track(9000, 300.0, 200.0, 0.8, 0.0)]
    res_a = select_marginal_support(base, active, cands, SHAPE, MarginalSupportConfig(b_active=2, min_gain=0.0))
    _check("active lineage consumes slots (b_slots=1)", res_a.b_slots == 1, f"b_slots={res_a.b_slots}")
    # high min_gain rejects everything
    res_m = select_marginal_support(base, [], cands, SHAPE, MarginalSupportConfig(b_active=5, min_gain=10.0))
    _check("high min_gain admits nothing", res_m.selected_ids == [],
           f"selected={res_m.selected_ids}")


def test_g_and_q_modes_run() -> None:
    base = _dense_base()
    cands = [Track(1, 600.0, 40.0, 0.3, 0.0), Track(2, 160.0, 240.0, 0.95, 0.0)]
    g = select_marginal_support(base, [], cands, SHAPE, MarginalSupportConfig(weight_mode="g", b_active=1, min_gain=0.0))
    q = select_marginal_support(base, [], cands, SHAPE, MarginalSupportConfig(weight_mode="q", b_active=1, min_gain=0.0))
    # G ignores q_lower -> picks the geometrically novel far corner (id 1)
    _check("G-mode picks geometric novelty", g.selected_ids == [1], f"g={g.selected_ids}")
    # Q ignores geometry -> picks highest reliability (id 2)
    _check("Q-mode picks reliability", q.selected_ids == [2], f"q={q.selected_ids}")


def test_contract_edges_and_hash_inputs() -> None:
    base = _dense_base()
    candidates = [Track(1, 600.0, 40.0, 0.8, 0.0), Track(2, 40.0, 440.0, 0.8, 0.0)]
    capped = select_marginal_support(
        base,
        [],
        candidates,
        SHAPE,
        MarginalSupportConfig(b_active=8, total_feature_cap=len(base) + 1, min_gain=0.0),
    )
    _check("total feature cap includes K0 base", len(capped.selected_ids) == 1, f"selected={capped.selected_ids}")

    no_model = select_marginal_support(
        base,
        [],
        candidates,
        SHAPE,
        MarginalSupportConfig(b_active=8, min_gain=0.0),
        has_valid_base_model=False,
    )
    _check(
        "NO_VALID_BASE_MODEL rejects every candidate",
        not no_model.selected_ids and all(d.reason == "NO_VALID_BASE_MODEL" for d in no_model.decisions),
    )

    try:
        select_marginal_support(
            base,
            [],
            [Track(base[0].track_id, 600.0, 40.0, 0.8, 0.0)],
            SHAPE,
            MarginalSupportConfig(),
        )
    except ValueError as exc:
        duplicate_rejected = "mutually disjoint" in str(exc)
    else:
        duplicate_rejected = False
    _check("K0/L/E duplicate IDs rejected", duplicate_rejected)

    cfg = MarginalSupportConfig(b_active=1, min_gain=0.0)
    hash_a = select_marginal_support(
        base, [], candidates, SHAPE, cfg, model_fit_hash=hashlib.sha256(b"fit-a").hexdigest()
    ).frame_hash
    hash_b = select_marginal_support(
        base, [], candidates, SHAPE, cfg, model_fit_hash=hashlib.sha256(b"fit-b").hexdigest()
    ).frame_hash
    _check("frame hash includes model-fit identity", hash_a != hash_b)


def main() -> int:
    for fn in [
        test_redundant_vs_new_region,
        test_low_reliability_downweights,
        test_residual_downweights,
        test_resolution_scale_invariance,
        test_deterministic_and_order_invariant,
        test_budget_and_min_gain_stops,
        test_g_and_q_modes_run,
        test_contract_edges_and_hash_inputs,
    ]:
        fn()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{n_pass}/{len(RESULTS)} contracts passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
