from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description="Export frames from a video file to an image directory.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=500)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg")
    parser.add_argument("--jpeg-quality", type=int, default=90)
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    timestamps_path = output_dir / "timestamps.csv"
    every_n = max(1, int(args.every_n))
    emitted = 0
    raw_index = -1
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    with timestamps_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame_index", "timestamp", "filename"])
        writer.writeheader()
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            raw_index += 1
            if raw_index < args.start_index:
                continue
            if (raw_index - args.start_index) % every_n != 0:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            filename = f"frame_{raw_index:06d}.{args.format}"
            output_path = output_dir / filename
            if args.format == "jpg":
                cv2.imwrite(str(output_path), gray, [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)])
            else:
                cv2.imwrite(str(output_path), gray)
            timestamp = raw_index / fps if fps > 0.0 else float(raw_index)
            writer.writerow({"frame_index": raw_index, "timestamp": timestamp, "filename": filename})
            emitted += 1
            if emitted >= args.max_frames:
                break
    capture.release()
    print(f"wrote {emitted} frames to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
