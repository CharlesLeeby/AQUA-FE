from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
import rosbag


def main() -> int:
    parser = argparse.ArgumentParser(description="Export compressed ROS bag images to a directory.")
    parser.add_argument("--bag", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=500)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg")
    parser.add_argument("--jpeg-quality", type=int, default=90)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamps_path = out_dir / "timestamps.csv"
    every_n = max(1, int(args.every_n))
    emitted = 0
    seen = 0
    with rosbag.Bag(args.bag, "r") as bag, timestamps_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame_index", "timestamp", "filename"])
        writer.writeheader()
        for _, msg, stamp in bag.read_messages(topics=[args.topic]):
            raw_index = seen
            seen += 1
            if raw_index < args.start_index:
                continue
            if (raw_index - args.start_index) % every_n != 0:
                continue
            image = _decode_image(msg)
            if image is None:
                continue
            filename = f"frame_{raw_index:06d}.{args.format}"
            output_path = out_dir / filename
            if args.format == "jpg":
                cv2.imwrite(str(output_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)])
            else:
                cv2.imwrite(str(output_path), image)
            writer.writerow(
                {
                    "frame_index": raw_index,
                    "timestamp": float(stamp.to_sec()),
                    "filename": filename,
                }
            )
            emitted += 1
            if emitted >= args.max_frames:
                break
    print(f"wrote {emitted} frames to {out_dir}")
    return 0


def _decode_image(msg) -> np.ndarray | None:
    if hasattr(msg, "format") and hasattr(msg, "data"):
        data = np.frombuffer(msg.data, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if not all(hasattr(msg, attr) for attr in ("height", "width", "encoding", "data")):
        return None
    height = int(msg.height)
    width = int(msg.width)
    encoding = str(msg.encoding).lower()
    data = np.frombuffer(msg.data, dtype=np.uint8)
    if encoding in {"mono8", "8uc1"}:
        expected = height * width
        if data.size < expected:
            return None
        return data[:expected].reshape(height, width).copy()
    if encoding in {"bgr8", "rgb8"}:
        expected = height * width * 3
        if data.size < expected:
            return None
        image = data[:expected].reshape(height, width, 3)
        if encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image
    return None


if __name__ == "__main__":
    raise SystemExit(main())
