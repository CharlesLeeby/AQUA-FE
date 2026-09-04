from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MethodSpec:
    label: str
    csv_path: Path
    viz_dir: Path


def parse_method_spec(raw: str) -> MethodSpec:
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("method spec must be label:csv_path:viz_dir")
    return MethodSpec(parts[0], Path(parts[1]), Path(parts[2]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create side-by-side frontend visualization montages.")
    parser.add_argument("--method", action="append", type=parse_method_spec, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frames", nargs="*", type=int, default=None)
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--header-height", type=int, default=82)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = {spec.label: _read_metrics(spec.csv_path) for spec in args.method}
    frames = args.frames if args.frames else _common_frames(args.method)
    if not frames:
        raise RuntimeError("No common visualization frames found.")

    for frame_index in frames:
        panels = []
        for spec in args.method:
            image_path = spec.viz_dir / f"frame_{frame_index:06d}.jpg"
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            image = _resize_width(image, args.image_width)
            header = _make_header(spec.label, metrics[spec.label].get(frame_index, {}), image.shape[1], args.header_height)
            panels.append(np.vstack([header, image]))
        if not panels:
            continue
        target_h = max(panel.shape[0] for panel in panels)
        panels = [_pad_height(panel, target_h) for panel in panels]
        montage = np.hstack(panels)
        out_path = output_dir / f"compare_{frame_index:06d}.jpg"
        cv2.imwrite(str(out_path), montage)
        print(out_path)
    return 0


def _read_metrics(path: Path) -> dict[int, dict]:
    df = pd.read_csv(path)
    if "frame_index" not in df:
        return {}
    return {int(row["frame_index"]): row.to_dict() for _, row in df.iterrows()}


def _common_frames(specs: list[MethodSpec]) -> list[int]:
    common: set[int] | None = None
    for spec in specs:
        frames = {
            int(path.stem.split("_")[-1])
            for path in spec.viz_dir.glob("frame_*.jpg")
            if path.stem.split("_")[-1].isdigit()
        }
        common = frames if common is None else common & frames
    return sorted(common or [])


def _make_header(label: str, row: dict, width: int, height: int) -> np.ndarray:
    header = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(header, (0, 0), (width - 1, height - 1), (190, 190, 190), 1)
    title = label
    line1 = (
        f"N={_fmt(row.get('num_features'), 0)}  cov={_fmt(row.get('grid_coverage'), 2)}  "
        f"age={_fmt(row.get('median_track_age'), 1)}  q={_fmt(row.get('median_quality'), 2)}"
    )
    line2 = (
        f"F-in={_fmt(row.get('fundamental_inlier_ratio'), 2)}  "
        f"epi={_fmt(row.get('median_epipolar_error'), 2)}  "
        f"LK={_fmt(row.get('lk_recovery_tracks'), 0)}  "
        f"X={_fmt(row.get('xfeat_recovery_tracks'), 0)}  "
        f"SP={_fmt(row.get('superpoint_lightglue_recovery_tracks'), 0)}  "
        f"L={_fmt(row.get('loftr_recovery_tracks'), 0)}"
    )
    _put_text(header, title, (12, 24), 0.62, (25, 25, 25), 2)
    _put_text(header, line1, (12, 49), 0.48, (45, 45, 45), 1)
    _put_text(header, line2, (12, 72), 0.48, (45, 45, 45), 1)
    return header


def _put_text(image: np.ndarray, text: str, org: tuple[int, int], scale: float, color: tuple[int, int, int], thickness: int) -> None:
    cv2.putText(image, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _fmt(value: object, decimals: int) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nan"
    if np.isnan(number):
        return "nan"
    if decimals == 0:
        return str(int(round(number)))
    return f"{number:.{decimals}f}"


def _resize_width(image: np.ndarray, width: int) -> np.ndarray:
    if image.shape[1] == width:
        return image
    scale = width / float(image.shape[1])
    height = max(1, int(round(image.shape[0] * scale)))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def _pad_height(image: np.ndarray, height: int) -> np.ndarray:
    if image.shape[0] == height:
        return image
    pad = np.full((height - image.shape[0], image.shape[1], 3), 245, dtype=np.uint8)
    return np.vstack([image, pad])


if __name__ == "__main__":
    raise SystemExit(main())
