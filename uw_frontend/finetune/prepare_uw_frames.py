"""Collect underwater frames from dataset sources into a flat dir for fine-tuning.

The XFeat augmentor (:mod:`modules.dataset.augmentation`) reads a flat directory
of ``.jpg`` / ``.png`` images and applies self-supervised homography warps. This
script samples frames from one or more sources -- image directories, tar/zip
archives, or rosbag-exported folders -- subsamples them, optionally caps the
resolution, and writes them as JPEGs into a single output directory.

Color is preserved where available (the underwater degradation augmentation uses
per-channel attenuation); grayscale sources are written as 3-channel.

Example:
    python3 -m uw_frontend.finetune.prepare_uw_frames \
        --source datasets/afrl/FL --source datasets/aqualoc/archaeo06 \
        --every-n 5 --max-per-source 800 --resize-max 1024 \
        --out-dir /workspace/uw_frames
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from uw_frontend.datasets.image_sequence import IMAGE_EXTENSIONS, ImageSequence


def _iter_dir_images(path: Path):
    files = sorted(p for p in path.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
    for p in files:
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)  # BGR, 3-channel
        if img is not None:
            yield p.name, img


def _resize_cap(img, resize_max: int):
    if resize_max <= 0:
        return img
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= resize_max:
        return img
    s = resize_max / m
    return cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)


def _collect_source(source: Path, every_n: int, max_per_source: int, resize_max: int, out_dir: Path, tag: str) -> int:
    written = 0
    if source.is_dir():
        gen = _iter_dir_images(source)
        for idx, (name, img) in enumerate(gen):
            if idx % every_n != 0:
                continue
            img = _resize_cap(img, resize_max)
            cv2.imwrite(str(out_dir / f"{tag}_{written:06d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            written += 1
            if max_per_source and written >= max_per_source:
                break
    else:
        # tar/zip/rosbag-exported or single image -> grayscale via ImageSequence.
        seq = ImageSequence(source, every_n=every_n, max_frames=max_per_source or None)
        for frame in seq:
            img = frame.image
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img = _resize_cap(img, resize_max)
            cv2.imwrite(str(out_dir / f"{tag}_{written:06d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            written += 1
            if max_per_source and written >= max_per_source:
                break
    return written


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect underwater frames into a flat dir for fine-tuning.")
    p.add_argument("--source", action="append", required=True, help="Dataset source (dir/tar/zip). Repeatable.")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--every-n", type=int, default=5, help="Keep 1 in every N frames per source.")
    p.add_argument("--max-per-source", type=int, default=1000, help="Cap frames written per source (0 = no cap).")
    p.add_argument("--resize-max", type=int, default=1024, help="Cap the longer image side (0 = keep original).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for src in args.source:
        source = Path(src)
        tag = source.name.replace(" ", "_") or "src"
        if not source.exists():
            print(f"[skip] missing source: {source}")
            continue
        n = _collect_source(source, args.every_n, args.max_per_source, args.resize_max, out_dir, tag)
        print(f"[src] {source} -> {n} frames")
        total += n

    print(f"[done] wrote {total} frames to {out_dir}")


if __name__ == "__main__":
    main()
