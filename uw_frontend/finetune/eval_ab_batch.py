"""Batch A/B evaluation across many sequences -> CSV + paper-grade markdown.

Runs stock vs. a fine-tuned XFeat variant over a list of sequences, aggregates
matching-quality metrics per sequence, and writes both a machine-readable CSV
and a markdown table grouped by difficulty (stock F-inlier tier) with headline
statistics (mean delta, win rate). Reproducible evidence for the low-texture
claim.

Example:
    python3 -m uw_frontend.finetune.eval_ab_batch \
        --glob 'datasets/prepared_new/uvvid_window_scan_may24/uvvid_underwater_caves_*' \
        --glob 'datasets/prepared_new/uvvid_window_scan_may24/uvvid_pipeline_*' \
        --uw weights/xfeat_uw_expanded.pt --tag round2_expanded \
        --max-pairs 18 --out-dir logs/xfeat_uw_finetune
"""

from __future__ import annotations

import argparse
import csv
import glob as globmod
from datetime import datetime
from pathlib import Path

import numpy as np

from uw_frontend.datasets.image_sequence import ImageSequence
from uw_frontend.finetune.eval_ab import _run_variant


def _tier(stock_f: float) -> str:
    if stock_f < 0.16:
        return "hard (<0.16)"
    if stock_f < 0.25:
        return "medium (0.16-0.25)"
    return "easy (>=0.25)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch stock-vs-uw XFeat A/B across sequences.")
    p.add_argument("--glob", action="append", required=True, help="Glob of sequence dirs. Repeatable.")
    p.add_argument("--uw", default="weights/xfeat_uw_expanded.pt")
    p.add_argument("--stock", default="weights/xfeat.pt")
    p.add_argument("--uw-adapter", default=None)
    p.add_argument("--tag", default="uw", help="Label for this variant in outputs.")
    p.add_argument("--max-pairs", type=int, default=18)
    p.add_argument("--every-n", type=int, default=2)
    p.add_argument("--top-k", type=int, default=2048)
    p.add_argument("--out-dir", default="logs/xfeat_uw_finetune")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    seqs = sorted({s for g in args.glob for s in globmod.glob(g)})
    if not seqs:
        raise SystemExit("no sequences matched")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for seq in seqs:
        frames = [f.image for f in ImageSequence(seq, every_n=args.every_n, max_frames=args.max_pairs + 1)]
        if len(frames) < 2:
            continue
        st = _run_variant("stock", args.stock, frames, args.top_k)
        uw = _run_variant(args.tag, args.uw, frames, args.top_k, adapter=args.uw_adapter)
        rows.append({
            "sequence": Path(seq).name,
            "n_pairs": st["n_pairs"],
            "stock_matches": st["matches"], "uw_matches": uw["matches"],
            "stock_f_inlier": st["f_inlier"], "uw_f_inlier": uw["f_inlier"],
            "stock_h_inlier": st["h_inlier"], "uw_h_inlier": uw["h_inlier"],
            "stock_epi": st["epi"], "uw_epi": uw["epi"],
            "d_f_inlier": uw["f_inlier"] - st["f_inlier"],
            "d_f_inlier_pct": 100.0 * (uw["f_inlier"] - st["f_inlier"]) / st["f_inlier"] if st["f_inlier"] else float("nan"),
            "tier": _tier(st["f_inlier"]),
        })

    rows.sort(key=lambda r: r["stock_f_inlier"])  # by difficulty

    csv_path = out_dir / f"ab_{args.tag}.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    d = np.array([r["d_f_inlier"] for r in rows])
    dpct = np.array([r["d_f_inlier_pct"] for r in rows])
    win = int(np.sum(d > 0))
    md = [
        f"# XFeat underwater fine-tune A/B — `{args.tag}` vs stock",
        f"\n_Generated {datetime.now():%Y-%m-%d %H:%M} · uw=`{args.uw}`"
        + (f" · adapter=`{args.uw_adapter}`" if args.uw_adapter else "")
        + f" · {args.max_pairs} pairs/seq, every-{args.every_n}, top_k={args.top_k}_\n",
        f"**Headline:** {win}/{len(rows)} sequences improve F-inlier "
        f"(win rate {100*win/len(rows):.0f}%); mean ΔF-inlier = {d.mean():+.3f} "
        f"({np.nanmean(dpct):+.1f}% rel).\n",
        "| sequence | n | tier | stock F | uw F | ΔF | ΔF% | stock H | uw H | stock epi | uw epi |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['sequence']} | {r['n_pairs']} | {r['tier']} | "
            f"{r['stock_f_inlier']:.3f} | {r['uw_f_inlier']:.3f} | {r['d_f_inlier']:+.3f} | {r['d_f_inlier_pct']:+.1f}% | "
            f"{r['stock_h_inlier']:.3f} | {r['uw_h_inlier']:.3f} | {r['stock_epi']:.3f} | {r['uw_epi']:.3f} |"
        )
    # Per-tier aggregate.
    md.append("\n**By difficulty tier (mean ΔF-inlier):**\n")
    md.append("| tier | n | mean stock F | mean ΔF | mean ΔF% |")
    md.append("|---|---|---|---|---|")
    for tier in ["hard (<0.16)", "medium (0.16-0.25)", "easy (>=0.25)"]:
        tr = [r for r in rows if r["tier"] == tier]
        if not tr:
            continue
        md.append(f"| {tier} | {len(tr)} | {np.mean([r['stock_f_inlier'] for r in tr]):.3f} | "
                  f"{np.mean([r['d_f_inlier'] for r in tr]):+.3f} | "
                  f"{np.nanmean([r['d_f_inlier_pct'] for r in tr]):+.1f}% |")

    md_path = out_dir / f"ab_{args.tag}.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[done] {len(rows)} sequences -> {csv_path} , {md_path}")
    print(f"[headline] win {win}/{len(rows)}, mean ΔF={d.mean():+.3f} ({np.nanmean(dpct):+.1f}%)")


if __name__ == "__main__":
    main()
