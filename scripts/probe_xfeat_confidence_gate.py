#!/usr/bin/env python3
"""Probe: is XFeat keypoint detection score a useful gate signal for births?

Design question behind the "learned-informed gate" idea: the XFeat-birth arm
uses XFeat as a DETECTOR (detectAndCompute -> keypoints), then raw LK carries
them. Each XFeat keypoint has a network confidence `score`. If high-score
keypoints survive/track longer under LK than low-score ones, then gating births
by XFeat score is a useful, learned-informed component. If not, the gate is
useless and we drop it.

GT-free, no VINS, no governance machinery. ~1 window, a few hundred frames.
"""

from __future__ import annotations

import argparse
import sys
import statistics as st

import cv2
import numpy as np
import rosbag
from cv_bridge import CvBridge

sys.path.insert(0, "external_tools/accelerated_features")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-bag", required=True)
    ap.add_argument("--image-topic", default="/camera/image_raw")
    ap.add_argument("--top-k", type=int, default=512)
    ap.add_argument("--track-frames", type=int, default=40, help="max frames to LK-track each birth")
    ap.add_argument("--fb-threshold", type=float, default=1.0)
    ap.add_argument("--reseed-every", type=int, default=30, help="detect a fresh XFeat batch every N frames")
    args = ap.parse_args()

    import torch
    from modules.xfeat import XFeat
    model = XFeat(weights="external_tools/accelerated_features/weights/xfeat.pt")
    bridge = CvBridge()

    # load a window of frames
    frames = []
    with rosbag.Bag(args.raw_bag) as b:
        for _t, m, _ts in b.read_messages(topics=[args.image_topic]):
            frames.append(bridge.imgmsg_to_cv2(m, "mono8"))
            if len(frames) >= 250:
                break
    if len(frames) < 20:
        print("too few frames")
        return 1

    lk = dict(winSize=(21, 21), maxLevel=3,
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    def detect(gray):
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB).astype(np.float32)
        t = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
        with torch.no_grad():
            out = model.detectAndCompute(t, top_k=args.top_k)[0]
        kp = out["keypoints"].cpu().numpy().astype(np.float32)
        sc = out["scores"].cpu().numpy().astype(np.float32)
        return kp, sc

    records = []  # (score, survival_frames)
    seed_idxs = list(range(0, len(frames) - 5, args.reseed_every))
    for s0 in seed_idxs:
        kp, sc = detect(frames[s0])
        pts = kp.reshape(-1, 1, 2).copy()
        alive = np.ones(len(pts), bool)
        survival = np.zeros(len(pts), int)
        prev = frames[s0]
        for step in range(1, min(args.track_frames, len(frames) - s0)):
            cur = frames[s0 + step]
            nxt, s_fwd, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, **lk)
            bak, _, _ = cv2.calcOpticalFlowPyrLK(cur, prev, nxt, None, **lk)
            fb = np.linalg.norm((pts - bak).reshape(-1, 2), axis=1)
            ok = (s_fwd.reshape(-1) == 1) & (fb < args.fb_threshold)
            h, w = cur.shape[:2]
            xy = nxt.reshape(-1, 2)
            inb = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
            newly_alive = alive & ok & inb
            survival[alive & ~newly_alive] = step  # died this step
            alive = newly_alive
            pts = nxt
            prev = cur
        survival[alive] = min(args.track_frames, len(frames) - s0)  # survived to end
        for i in range(len(kp)):
            records.append((float(sc[i]), int(survival[i])))

    scores = np.array([r[0] for r in records])
    surv = np.array([r[1] for r in records])
    med = float(np.median(scores))
    hi = surv[scores >= med]
    lo = surv[scores < med]
    # Pearson correlation
    corr = float(np.corrcoef(scores, surv)[0, 1]) if len(records) > 2 else float("nan")

    print(f"window frames={len(frames)}  seed batches={len(seed_idxs)}  births tracked={len(records)}")
    print(f"XFeat score: min={scores.min():.3f} median={med:.3f} max={scores.max():.3f}")
    print(f"\n生存帧数(LK 存活):")
    print(f"  高分点(score>=median): n={len(hi)} median生存={np.median(hi):.1f} mean={hi.mean():.1f} >=10帧={100*np.mean(hi>=10):.0f}%")
    print(f"  低分点(score< median): n={len(lo)} median生存={np.median(lo):.1f} mean={lo.mean():.1f} >=10帧={100*np.mean(lo>=10):.0f}%")
    print(f"\ncorr(score, survival) = {corr:.3f}")
    ratio = (np.median(hi) + 1e-9) / (np.median(lo) + 1e-9)
    print(f"高分/低分 median 生存比 = {ratio:.2f}x")
    print("\n判读: 高分点显著更长命(比值>1.3 或 corr>0.15) => XFeat score 是有用的 births 门控信号")
    print("      无差别(比值~1, corr~0) => 门控无用,drop 这个旋钮")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
