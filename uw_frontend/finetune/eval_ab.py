"""A/B matching-quality comparison: stock XFeat vs. underwater-adapted XFeat.

Runs both matchers on consecutive frame pairs of a sequence and reports, per
variant, the mean number of matches and the geometric consistency of those
matches (fundamental- and homography-RANSAC inlier ratios, symmetric epipolar
error). This is the honest frontend-level evidence: same frames, same matcher
class, only the weights differ.

Example:
    python3 -m uw_frontend.finetune.eval_ab \
        --seq datasets/afrl/samples/cemetery_fl_every5_800 \
        --stock external_tools/accelerated_features/weights/xfeat.pt \
        --uw external_tools/accelerated_features/weights/xfeat_uw.pt \
        --max-pairs 150 --every-n 2
"""

from __future__ import annotations

import argparse

import cv2
import numpy as np

from uw_frontend.datasets.image_sequence import ImageSequence
from uw_frontend.matchers.xfeat_adapter import XFeatMatcher


def _symmetric_epipolar_error(F, p0, p1) -> float:
    if F is None or len(p0) == 0:
        return float("nan")
    p0h = np.hstack([p0, np.ones((len(p0), 1))])
    p1h = np.hstack([p1, np.ones((len(p1), 1))])
    Fp0 = (F @ p0h.T).T           # epipolar lines in image1
    Ftp1 = (F.T @ p1h.T).T        # epipolar lines in image0
    num = (np.sum(p1h * Fp0, axis=1)) ** 2
    d = 1.0 / (Fp0[:, 0] ** 2 + Fp0[:, 1] ** 2 + 1e-12) + 1.0 / (Ftp1[:, 0] ** 2 + Ftp1[:, 1] ** 2 + 1e-12)
    return float(np.sqrt(np.mean(num * d)))


def _pair_stats(matcher: XFeatMatcher, img0, img1) -> dict:
    r = matcher.match(img0, img1)
    p0, p1 = r.points0, r.points1
    out = {"matches": len(p0), "f_inlier": float("nan"), "h_inlier": float("nan"), "epi": float("nan")}
    if len(p0) >= 8:
        F, maskF = cv2.findFundamentalMat(p0, p1, cv2.FM_RANSAC, 1.0, 0.999)
        if maskF is not None:
            m = maskF.ravel().astype(bool)
            out["f_inlier"] = float(m.mean())
            out["epi"] = _symmetric_epipolar_error(F, p0[m], p1[m])
        H, maskH = cv2.findHomography(p0, p1, cv2.RANSAC, 3.0)
        if maskH is not None:
            out["h_inlier"] = float(maskH.ravel().mean())
    return out


def _run_variant(name: str, weights: str, frames: list, top_k: int, adapter: str | None = None) -> dict:
    matcher = XFeatMatcher(weights=weights, top_k=top_k, adapter_weights=adapter)
    rows = [_pair_stats(matcher, frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    agg = {}
    for k in ("matches", "f_inlier", "h_inlier", "epi"):
        vals = np.array([r[k] for r in rows], dtype=np.float64)
        agg[k] = float(np.nanmean(vals))
    agg["n_pairs"] = len(rows)
    print(f"[{name}] pairs={agg['n_pairs']} matches={agg['matches']:.1f} "
          f"F-inlier={agg['f_inlier']:.3f} H-inlier={agg['h_inlier']:.3f} epi={agg['epi']:.3f}px")
    return agg


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A/B: stock vs underwater-adapted XFeat matching quality.")
    p.add_argument("--seq", required=True, help="Sequence directory / archive.")
    # Paths are relative to the XFeat repo_path (external_tools/accelerated_features).
    p.add_argument("--stock", default="weights/xfeat.pt")
    p.add_argument("--uw", default="weights/xfeat_uw.pt")
    p.add_argument("--max-pairs", type=int, default=150)
    p.add_argument("--every-n", type=int, default=2)
    p.add_argument("--top-k", type=int, default=4096)
    p.add_argument("--uw-adapter", default=None, help="Optional UWAdapter weights applied to the uw variant.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    seq = ImageSequence(args.seq, every_n=args.every_n, max_frames=args.max_pairs + 1)
    frames = [f.image for f in seq]
    print(f"loaded {len(frames)} frames from {args.seq}")
    if len(frames) < 2:
        raise SystemExit("need >=2 frames")

    stock = _run_variant("stock", args.stock, frames, args.top_k)
    uw = _run_variant("uw   ", args.uw, frames, args.top_k, adapter=args.uw_adapter)

    print("\n=== A/B (uw vs stock) ===")
    def delta(k, higher_better=True, pct=True):
        a, b = uw[k], stock[k]
        d = a - b
        rel = 100.0 * d / b if b not in (0, 0.0) and not np.isnan(b) else float("nan")
        arrow = "↑" if (d > 0) == higher_better else "↓"
        return f"{k:9s}: stock={b:.3f}  uw={a:.3f}  Δ={d:+.3f} ({rel:+.1f}%) {arrow}"
    print(delta("matches"))
    print(delta("f_inlier"))
    print(delta("h_inlier"))
    print(delta("epi", higher_better=False))


if __name__ == "__main__":
    main()
