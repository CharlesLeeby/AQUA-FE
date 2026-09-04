#!/usr/bin/env python3
"""Run P06 AFRL KLT screening directly from the compressed source bag.

This adapter deliberately produces the same image pixels consumed by the
legacy AFRL wrapper while avoiding its full-resolution, uncompressed short
bag.  It is screening-only: no VINS process or trajectory evaluator is run.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-bag", required=True)
    parser.add_argument("--camchain", required=True)
    parser.add_argument("--camera-key", default="cam0")
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw_bag = Path(args.raw_bag)
    camchain = Path(args.camchain)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if not raw_bag.is_file():
        raise FileNotFoundError(raw_bag)
    if not camchain.is_file():
        raise FileNotFoundError(camchain)

    camera_config = work_dir / "afrl_p06_camera.yaml"
    feature_bag = work_dir / "features.bag"
    metrics = work_dir / "frontend_metrics.csv"
    write_camera_config(camchain, args.camera_key, camera_config)

    command = [
        "python3",
        "-m",
        "uw_frontend.ros.export_vins_features",
        "--bag",
        str(raw_bag),
        "--image-topic",
        args.image_topic,
        "--camera-config",
        str(camera_config),
        "--output-bag",
        str(feature_bag),
        "--config",
        str(CONFIG),
        "--method",
        "klt",
        "--semidense-fallback-method",
        "none",
        "--start-offset",
        f"{args.start_offset:.17g}",
        "--duration",
        f"{args.duration:.17g}",
        "--every-n",
        "1",
        "--frame-offset",
        "0",
        "--export-max-features",
        "350",
        "--export-min-age",
        "0",
        "--preprocess",
        "adaptive_clahe",
        "--timestamp-source",
        "header",
        "--max-header-stamp-delta",
        "0.25",
        "--invalid-header-policy",
        "skip",
        "--metrics-csv",
        str(metrics),
        "--backend-quality-mode",
        "default",
        "--backend-quality-alpha",
        "0.65",
        "--backend-learned-quality-scale",
        "1.0",
        "--backend-sp-lg-quality-scale",
        "1.0",
        "--backend-xfeat-quality-scale",
        "1.0",
        "--backend-loftr-quality-scale",
        "1.0",
        "--mirror-measurement-selection-policy",
        "baseline",
    ]
    if args.max_frames is not None:
        command.extend(["--max-frames", str(args.max_frames)])

    (work_dir / "direct_command.txt").write_text(
        shlex.join(command) + "\n", encoding="utf-8"
    )
    if args.dry_run:
        print(shlex.join(command))
        return 0

    feature_bag.unlink(missing_ok=True)
    metrics.unlink(missing_ok=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode != 0:
        return completed.returncode
    if not metrics.is_file() or metrics.stat().st_size == 0:
        raise RuntimeError("direct AFRL screening produced no metrics")
    print(f"P06_AFRL_DIRECT_PASS rows={sum(1 for _ in metrics.open()) - 1}")
    return 0


def write_camera_config(camchain_path: Path, camera_key: str, output: Path) -> None:
    data = yaml.safe_load(camchain_path.read_text(encoding="utf-8"))
    camera = data[camera_key]
    if camera.get("camera_model") != "pinhole":
        raise ValueError(f"unsupported AFRL camera model: {camera.get('camera_model')}")
    width, height = [int(value) for value in camera["resolution"]]
    fx, fy, cx, cy = [float(value) for value in camera["intrinsics"]]
    k1, k2, p1, p2 = [float(value) for value in camera["distortion_coeffs"][:4]]
    output.write_text(
        "%YAML:1.0\n"
        "---\n"
        "model_type: PINHOLE\n"
        f"camera_name: afrl_p06_{camera_key}\n"
        f"image_width: {width}\n"
        f"image_height: {height}\n"
        "distortion_parameters:\n"
        f"   k1: {k1:.17g}\n"
        f"   k2: {k2:.17g}\n"
        f"   p1: {p1:.17g}\n"
        f"   p2: {p2:.17g}\n"
        "projection_parameters:\n"
        f"   fx: {fx:.17g}\n"
        f"   fy: {fy:.17g}\n"
        f"   cx: {cx:.17g}\n"
        f"   cy: {cy:.17g}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
