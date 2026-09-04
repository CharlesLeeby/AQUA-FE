#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rosbag
import rospy


@dataclass
class ImageSample:
    stamp: float
    offset: float
    orb_count: int
    gftt_count: int
    lap_var: float
    contrast: float
    flow_count: int
    flow_median_px: float
    flow_p75_px: float


@dataclass
class ImuSample:
    stamp: float
    offset: float
    gyro_norm: float
    acc_norm: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan AFRL cave bag for VINS-friendly motion windows.")
    parser.add_argument("--bag", default="datasets/full_downloads/afrl_hf/ros1_bags/cave_gennie.bag")
    parser.add_argument("--image-topic", default="/slave1/image_raw/compressed")
    parser.add_argument("--imu-topic", default="/imu/imu")
    parser.add_argument("--window-s", type=float, default=20.0)
    parser.add_argument("--step-s", type=float, default=5.0)
    parser.add_argument("--image-stride", type=int, default=10, help="Process every Nth image.")
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--output-csv", default="logs/afrl_cave_v31/window_scan.csv")
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    image_samples, imu_samples, start_time, end_time = scan_bag(
        Path(args.bag),
        image_topic=args.image_topic,
        imu_topic=args.imu_topic,
        image_stride=max(1, int(args.image_stride)),
        max_width=max(64, int(args.max_width)),
    )
    windows = score_windows(
        image_samples,
        imu_samples,
        start_time=start_time,
        end_time=end_time,
        window_s=float(args.window_s),
        step_s=float(args.step_s),
    )
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "rank",
            "score",
            "start_offset_s",
            "end_offset_s",
            "image_samples",
            "median_flow_px",
            "p75_flow_px",
            "median_orb",
            "median_gftt",
            "median_lap_var",
            "median_contrast",
            "imu_samples",
            "gyro_rms",
            "gyro_p90",
            "acc_norm_std",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rank, row in enumerate(windows, start=1):
            writer.writerow({"rank": rank, **row})

    print(f"wrote {output_csv}")
    print("top windows:")
    for rank, row in enumerate(windows[: int(args.top_k)], start=1):
        print(
            f"{rank:02d} score={row['score']:.3f} "
            f"offset={row['start_offset_s']:.1f}-{row['end_offset_s']:.1f}s "
            f"flow_med={row['median_flow_px']:.2f}px flow_p75={row['p75_flow_px']:.2f}px "
            f"orb={row['median_orb']:.0f} gyro_rms={row['gyro_rms']:.4f} acc_std={row['acc_norm_std']:.4f}"
        )
    return 0


def scan_bag(
    bag_path: Path,
    *,
    image_topic: str,
    imu_topic: str,
    image_stride: int,
    max_width: int,
) -> tuple[list[ImageSample], list[ImuSample], float, float]:
    orb = cv2.ORB_create(nfeatures=1000)
    prev_gray: np.ndarray | None = None
    prev_points: np.ndarray | None = None
    image_samples: list[ImageSample] = []
    imu_samples: list[ImuSample] = []
    image_index = 0

    with rosbag.Bag(str(bag_path), "r") as bag:
        start_time = float(bag.get_start_time())
        end_time = float(bag.get_end_time())
        for topic, msg, stamp in bag.read_messages(topics=[image_topic, imu_topic]):
            msg_stamp = _message_stamp(msg, stamp)
            t_sec = float(msg_stamp.to_sec())
            offset = t_sec - start_time
            if topic == imu_topic:
                gyr = msg.angular_velocity
                acc = msg.linear_acceleration
                imu_samples.append(
                    ImuSample(
                        stamp=t_sec,
                        offset=offset,
                        gyro_norm=float(np.linalg.norm([gyr.x, gyr.y, gyr.z])),
                        acc_norm=float(np.linalg.norm([acc.x, acc.y, acc.z])),
                    )
                )
                continue

            if image_index % image_stride != 0:
                image_index += 1
                continue
            image_index += 1
            gray = _decode_gray(msg)
            if gray is None:
                continue
            gray = _resize_width(gray, max_width=max_width)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            contrast = float(gray.std())
            orb_count = len(orb.detect(gray, None))
            gftt = cv2.goodFeaturesToTrack(
                gray,
                maxCorners=600,
                qualityLevel=0.01,
                minDistance=8,
                blockSize=7,
            )
            gftt_count = 0 if gftt is None else int(len(gftt))
            flow_count = 0
            flow_median = 0.0
            flow_p75 = 0.0
            if prev_gray is not None and prev_points is not None and len(prev_points) >= 8:
                next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                    prev_gray,
                    gray,
                    prev_points,
                    None,
                    winSize=(21, 21),
                    maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
                )
                if next_points is not None and status is not None:
                    valid = status.reshape(-1).astype(bool)
                    if np.count_nonzero(valid) >= 8:
                        disp = np.linalg.norm(next_points[valid] - prev_points[valid], axis=1)
                        disp = disp[np.isfinite(disp)]
                        if disp.size:
                            flow_count = int(disp.size)
                            flow_median = float(np.median(disp))
                            flow_p75 = float(np.percentile(disp, 75))
            image_samples.append(
                ImageSample(
                    stamp=t_sec,
                    offset=offset,
                    orb_count=orb_count,
                    gftt_count=gftt_count,
                    lap_var=lap_var,
                    contrast=contrast,
                    flow_count=flow_count,
                    flow_median_px=flow_median,
                    flow_p75_px=flow_p75,
                )
            )
            prev_gray = gray
            prev_points = gftt.astype(np.float32) if gftt is not None and len(gftt) else None
    return image_samples, imu_samples, start_time, end_time


def score_windows(
    image_samples: list[ImageSample],
    imu_samples: list[ImuSample],
    *,
    start_time: float,
    end_time: float,
    window_s: float,
    step_s: float,
) -> list[dict[str, float]]:
    image_offsets = np.asarray([sample.offset for sample in image_samples], dtype=float)
    imu_offsets = np.asarray([sample.offset for sample in imu_samples], dtype=float)
    rows: list[dict[str, float]] = []
    duration = max(0.0, end_time - start_time)
    start = 0.0
    while start + window_s <= duration + 1e-6:
        end = start + window_s
        image_idx = np.flatnonzero((image_offsets >= start) & (image_offsets < end))
        imu_idx = np.flatnonzero((imu_offsets >= start) & (imu_offsets < end))
        if len(image_idx) < 5 or len(imu_idx) < 50:
            start += step_s
            continue
        img = [image_samples[int(i)] for i in image_idx]
        imu = [imu_samples[int(i)] for i in imu_idx]
        median_flow = _median([s.flow_median_px for s in img if s.flow_count >= 20])
        p75_flow = _median([s.flow_p75_px for s in img if s.flow_count >= 20])
        median_orb = _median([s.orb_count for s in img])
        median_gftt = _median([s.gftt_count for s in img])
        median_lap = _median([s.lap_var for s in img])
        median_contrast = _median([s.contrast for s in img])
        gyro = np.asarray([s.gyro_norm for s in imu], dtype=float)
        acc = np.asarray([s.acc_norm for s in imu], dtype=float)
        gyro_rms = float(np.sqrt(np.mean(gyro * gyro))) if gyro.size else 0.0
        gyro_p90 = float(np.percentile(gyro, 90)) if gyro.size else 0.0
        acc_std = float(np.std(acc)) if acc.size else 0.0
        score = (
            0.35 * _clip01(median_flow / 12.0)
            + 0.20 * _clip01(p75_flow / 20.0)
            + 0.15 * _clip01(median_orb / 250.0)
            + 0.15 * _clip01(gyro_rms / 0.12)
            + 0.15 * _clip01(acc_std / 0.20)
        )
        rows.append(
            {
                "score": score,
                "start_offset_s": start,
                "end_offset_s": end,
                "image_samples": float(len(image_idx)),
                "median_flow_px": median_flow,
                "p75_flow_px": p75_flow,
                "median_orb": median_orb,
                "median_gftt": median_gftt,
                "median_lap_var": median_lap,
                "median_contrast": median_contrast,
                "imu_samples": float(len(imu_idx)),
                "gyro_rms": gyro_rms,
                "gyro_p90": gyro_p90,
                "acc_norm_std": acc_std,
            }
        )
        start += step_s
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def _decode_gray(msg) -> np.ndarray | None:
    data = np.frombuffer(msg.data, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def _resize_width(image: np.ndarray, max_width: int) -> np.ndarray:
    height, width = image.shape[:2]
    if width <= max_width:
        return image
    scale = max_width / float(width)
    out_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (max_width, out_height), interpolation=cv2.INTER_AREA)


def _message_stamp(msg, fallback) -> rospy.Time:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and stamp.to_sec() > 0.0:
        return stamp
    return fallback


def _median(values: list[float] | list[int]) -> float:
    if not values:
        return 0.0
    return float(np.median(np.asarray(values, dtype=float)))


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


if __name__ == "__main__":
    raise SystemExit(main())
