from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from uw_frontend.datasets.image_sequence import ImageSequence
from uw_frontend.quality.image_quality import score_image_quality


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan an image sequence for underwater degradation candidates.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--image-prefix", default=None)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=None)
    parser.add_argument("--quality-threshold", type=float, default=0.45)
    parser.add_argument("--texture-threshold", type=float, default=0.45)
    parser.add_argument("--blur-threshold", type=float, default=0.45)
    parser.add_argument("--degradation-threshold", type=float, default=0.55)
    parser.add_argument("--flat-region-threshold", type=float, default=0.90)
    parser.add_argument("--illumination-threshold", type=float, default=0.48)
    parser.add_argument("--backscatter-threshold", type=float, default=0.43)
    parser.add_argument("--grid-texture-threshold", type=float, default=0.10)
    args = parser.parse_args()

    sequence = ImageSequence(
        args.input,
        image_prefix=args.image_prefix,
        every_n=args.every_n,
        max_frames=args.max_frames,
        start_index=args.start_index,
        end_index=args.end_index,
    )
    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "frame_index",
            "frame_name",
            "mean_intensity",
            "contrast",
            "gradient_mean",
            "laplacian_var",
            "underexposed_ratio",
            "overexposed_ratio",
            "illumination_nonuniformity",
            "local_contrast",
            "flat_region_ratio",
            "texture_score",
            "blur_score",
            "exposure_score",
            "contrast_score",
            "illumination_score",
            "backscatter_score",
            "highlight_shadow_score",
            "grid_texture_score",
            "underwater_score",
            "degradation_score",
            "image_quality",
            "is_degraded",
            "degradation_reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for frame in sequence:
            q = score_image_quality(frame.image)
            reasons = []
            if q.global_score < args.quality_threshold:
                reasons.append("low_quality")
            if q.texture_score < args.texture_threshold:
                reasons.append("low_texture")
            if q.blur_score < args.blur_threshold:
                reasons.append("blur")
            if q.underexposed_ratio + q.overexposed_ratio > 0.08:
                reasons.append("bad_exposure")
            if q.degradation_score > args.degradation_threshold:
                reasons.append("underwater_degradation")
            if q.flat_region_ratio > args.flat_region_threshold:
                reasons.append("flat_regions")
            if q.illumination_nonuniformity > args.illumination_threshold:
                reasons.append("illumination_nonuniformity")
            if q.backscatter_score < args.backscatter_threshold:
                reasons.append("backscatter_or_low_contrast")
            if q.grid_texture_score < args.grid_texture_threshold:
                reasons.append("low_grid_texture")
            row = {
                "frame_index": frame.index,
                "frame_name": frame.name,
                "mean_intensity": q.mean_intensity,
                "contrast": q.contrast,
                "gradient_mean": q.gradient_mean,
                "laplacian_var": q.laplacian_var,
                "underexposed_ratio": q.underexposed_ratio,
                "overexposed_ratio": q.overexposed_ratio,
                "illumination_nonuniformity": q.illumination_nonuniformity,
                "local_contrast": q.local_contrast,
                "flat_region_ratio": q.flat_region_ratio,
                "texture_score": q.texture_score,
                "blur_score": q.blur_score,
                "exposure_score": q.exposure_score,
                "contrast_score": q.contrast_score,
                "illumination_score": q.illumination_score,
                "backscatter_score": q.backscatter_score,
                "highlight_shadow_score": q.highlight_shadow_score,
                "grid_texture_score": q.grid_texture_score,
                "underwater_score": q.underwater_score,
                "degradation_score": q.degradation_score,
                "image_quality": q.global_score,
                "is_degraded": bool(reasons),
                "degradation_reason": "+".join(reasons) if reasons else "healthy",
            }
            writer.writerow(row)
            rows.append(row)

    _print_summary(rows, out)
    return 0


def _print_summary(rows: list[dict], out: Path) -> None:
    if not rows:
        print(f"wrote empty scan {out}")
        return
    qualities = np.asarray([row["image_quality"] for row in rows], dtype=np.float32)
    textures = np.asarray([row["texture_score"] for row in rows], dtype=np.float32)
    degradations = np.asarray([row["degradation_score"] for row in rows], dtype=np.float32)
    flat_regions = np.asarray([row["flat_region_ratio"] for row in rows], dtype=np.float32)
    degraded = [row for row in rows if row["is_degraded"]]
    print(f"wrote {out}")
    print(f"frames: {len(rows)}")
    print(f"degraded: {len(degraded)} ({len(degraded) / len(rows):.1%})")
    print(f"image_quality median/min: {float(np.median(qualities)):.3f}/{float(np.min(qualities)):.3f}")
    print(f"texture_score median/min: {float(np.median(textures)):.3f}/{float(np.min(textures)):.3f}")
    print(f"degradation median/max: {float(np.median(degradations)):.3f}/{float(np.max(degradations)):.3f}")
    print(f"flat_region median/max: {float(np.median(flat_regions)):.3f}/{float(np.max(flat_regions)):.3f}")
    if degraded:
        print("first degraded frames:")
        for row in degraded[:10]:
            print(f"  {row['frame_index']:6d} {row['image_quality']:.3f} {row['texture_score']:.3f} {row['degradation_reason']} {row['frame_name']}")


if __name__ == "__main__":
    raise SystemExit(main())
