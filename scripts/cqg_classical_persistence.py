#!/usr/bin/env python3
"""C-QG level-1 (frontend-only): can CLASSICAL seeds form persistent anchors?

The learned-seed value hypothesis is "XFeat finds persistent trackable points in
the gaps that Shi-Tomasi/KLT deprioritizes". This probe tests the classical
counterpart on the SAME raw imagery: run KLT (goodFeaturesToTrack + LK, refilled
to a cap like VINS) AND, at trigger frames, detect EXTRA Shi-Tomasi corners in
the gaps (>=8px from the KLT set, the same rule the learned sidecar uses), then
LK-track those "classical seeds" as persistent lineages. Measure how many
classical seeds survive >=10 frames vs the learned seeds on the same window.

If classical seeds persist like learned -> learned is not necessary (persistent
anchors are the value, source-agnostic). If classical seeds die like churny KLT
-> learned detection IS providing something Shi-Tomasi cannot.  No VINS needed.
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import defaultdict

import cv2
import numpy as np
import rosbag
from cv_bridge import CvBridge


def _ch(msg, name):
    for c in msg.channels:
        if c.name == name:
            return list(c.values)
    return [0.0] * len(msg.points)


def learned_lifetimes(sidecar_bag):
    life = defaultdict(int)
    with rosbag.Bag(sidecar_bag) as b:
        for _t, m, _ts in b.read_messages(topics=["/feature_tracker/sidecar"]):
            ids, il, sc = _ch(m, "id"), _ch(m, "is_learned"), _ch(m, "source_code")
            seen = set()
            for i in range(len(m.points)):
                fid = int(round(ids[i]))
                if (int(round(il[i])) or int(round(sc[i])) == 20) and fid not in seen:
                    seen.add(fid)
                    life[fid] += 1
    return list(life.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="raw image bag with /camera/image_raw")
    ap.add_argument("--sidecar", required=True, help="learned sidecar bag for comparison")
    ap.add_argument("--image-topic", default="/camera/image_raw")
    ap.add_argument("--max-klt", type=int, default=350)
    ap.add_argument("--min-dist", type=int, default=10)
    ap.add_argument("--trigger-every", type=int, default=10)
    ap.add_argument("--seeds-per-trigger", type=int, default=8)
    ap.add_argument("--gap-px", type=float, default=8.0)
    args = ap.parse_args()

    bridge = CvBridge()
    lk = dict(winSize=(21, 21), maxLevel=3,
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    prev = None
    klt = None                              # Nx1x2 KLT base points
    seeds = {}                              # seed_id -> (x,y)
    seed_life = defaultdict(int)            # seed_id -> frames survived
    next_seed_id = 0
    frame = 0

    with rosbag.Bag(args.raw) as b:
        for _t, msg, _ts in b.read_messages(topics=[args.image_topic]):
            img = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
            H, W = img.shape[:2]

            if prev is None:
                klt = cv2.goodFeaturesToTrack(img, args.max_klt, 0.01, args.min_dist)
            else:
                # --- track KLT base with forward-backward check ---
                nxt, stt, _ = cv2.calcOpticalFlowPyrLK(prev, img, klt, None, **lk)
                back, _, _ = cv2.calcOpticalFlowPyrLK(img, prev, nxt, None, **lk)
                fb = np.linalg.norm((klt - back).reshape(-1, 2), axis=1)
                good = (stt.reshape(-1) == 1) & (fb < 1.0)
                klt = nxt[good].reshape(-1, 1, 2)

                # --- track classical seeds ---
                if seeds:
                    sid = list(seeds)
                    pts = np.array([seeds[i] for i in sid], np.float32).reshape(-1, 1, 2)
                    snx, sst, _ = cv2.calcOpticalFlowPyrLK(prev, img, pts, None, **lk)
                    sbk, _, _ = cv2.calcOpticalFlowPyrLK(img, prev, snx, None, **lk)
                    sfb = np.linalg.norm((pts - sbk).reshape(-1, 2), axis=1)
                    seeds = {}
                    for k, i in enumerate(sid):
                        x, y = snx[k].reshape(2)
                        if sst[k] == 1 and sfb[k] < 1.0 and 0 <= x < W and 0 <= y < H:
                            seeds[i] = (float(x), float(y))
                            seed_life[i] += 1
                # refill KLT base to cap (mimic VINS churn)
                have = len(klt) if klt is not None else 0
                if have < args.max_klt:
                    mask = np.full((H, W), 255, np.uint8)
                    for p in (klt.reshape(-1, 2) if klt is not None else []):
                        cv2.circle(mask, (int(p[0]), int(p[1])), args.min_dist, 0, -1)
                    add = cv2.goodFeaturesToTrack(img, args.max_klt - have, 0.01, args.min_dist, mask=mask)
                    if add is not None:
                        klt = np.vstack([klt, add]) if klt is not None else add

            # --- trigger: detect classical seeds in the gaps (>=gap_px from KLT) ---
            if frame % args.trigger_every == 0:
                mask = np.full((H, W), 255, np.uint8)
                for p in (klt.reshape(-1, 2) if klt is not None else []):
                    cv2.circle(mask, (int(p[0]), int(p[1])), int(args.gap_px), 0, -1)
                for (x, y) in seeds.values():
                    cv2.circle(mask, (int(x), int(y)), int(args.gap_px), 0, -1)
                cand = cv2.goodFeaturesToTrack(img, args.seeds_per_trigger, 0.01, args.min_dist, mask=mask)
                if cand is not None:
                    for p in cand.reshape(-1, 2):
                        seeds[next_seed_id] = (float(p[0]), float(p[1]))
                        seed_life[next_seed_id] += 1
                        next_seed_id += 1

            prev = img
            frame += 1

    cls = list(seed_life.values())
    lrn = learned_lifetimes(args.sidecar)

    def s(x):
        return (f"n={len(x):3d} median={st.median(x):4.1f} mean={st.mean(x):4.1f} "
                f"max={max(x):3d} >=10帧={sum(1 for v in x if v>=10)} "
                f"(={sum(1 for v in x if v>=10)/len(x)*100:.0f}%)") if x else "n=0"
    print(f"frames={frame} image={W}x{H}")
    print(f"classical seeds (Shi-Tomasi in gaps, LK-tracked): {s(cls)}")
    print(f"learned  seeds (XFeat, from sidecar)            : {s(lrn)}")
    if cls and lrn:
        cp = sum(1 for v in cls if v >= 10) / len(cls) * 100
        lp = sum(1 for v in lrn if v >= 10) / len(lrn) * 100
        print(f"\n持久锚点(>=10帧)占比: 经典={cp:.0f}%  learned={lp:.0f}%")
        print("→ 经典 >= learned  ⇒  learned 非必需(持久锚点 source-agnostic)"
              if cp >= lp * 0.8 else
              "→ 经典 << learned  ⇒  learned 检测提供了 Shi-Tomasi 给不了的持久点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
