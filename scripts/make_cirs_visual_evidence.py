from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np
import rosbag
from cv_bridge import CvBridge


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT_DIR = ROOT / "正反例窗口整理" / "可视化证据"
IMAGE_TOPIC = "/cirs/camera/image_mono"
FEATURE_TOPIC = "/feature_tracker/feature"


RUNS = {
    "s450": {
        "raw": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s450_d30_seedchain3_fullbackbone_cap20_export/raw_segment.bag",
        "features": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s450_d30_onlinegate_w8_framefresh5_cap20_export/features.bag",
        "metrics": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s450_d30_onlinegate_w8_framefresh5_cap20_export/frontend_metrics.csv",
        "ape_rpe": "53.708551 / 18.693785",
        "note": "strong counterexample",
    },
    "s750": {
        "raw": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s750_d30_seedchain3_fullbackbone_cap20_export/raw_segment.bag",
        "features": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s750_d30_onlinegate_w8_framefresh5_cap20_export/features.bag",
        "metrics": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s750_d30_onlinegate_w8_framefresh5_cap20_export/frontend_metrics.csv",
        "ape_rpe": "1.667670 / 0.316024",
        "note": "weak/borderline",
    },
    "s840": {
        "raw": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s840_d30_seedchain3_fullbackbone_cap20_export/raw_segment.bag",
        "features": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s840_d30_onlinegate_w8_framefresh5_cap20_export/features.bag",
        "metrics": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s840_d30_onlinegate_w8_framefresh5_cap20_export/frontend_metrics.csv",
        "ape_rpe": "3.532651 / 2.008013",
        "note": "fragmented tracks",
    },
    "s900": {
        "raw": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun22_cirs_s900_d30_xfeat_churn_v5_fullklt/raw_segment.bag",
        "features": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s900_d30_onlinegate_w8_framefresh5_cap20_export/features.bag",
        "metrics": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s900_d30_onlinegate_w8_framefresh5_cap20_export/frontend_metrics.csv",
        "ape_rpe": "0.997030 / 0.182378",
        "note": "online gate no longer positive",
    },
    "s960": {
        "raw": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun22_cirs_s960_d30_xfeat_churn_v5_fullklt/raw_segment.bag",
        "features": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s960_d30_onlinegate_w8_framefresh5_cap20_export/features.bag",
        "metrics": ROOT / "logs/cirs_caves_vins/external_hybrid_xfeat_every1_jun23_s960_d30_onlinegate_w8_framefresh5_cap20_export/frontend_metrics.csv",
        "ape_rpe": "1.703287 / 0.246472",
        "note": "early XFeat guarded",
    },
}


def read_raw_frames(path: Path) -> list[np.ndarray]:
    bridge = CvBridge()
    frames: list[np.ndarray] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, msg, _ in bag.read_messages(topics=[IMAGE_TOPIC]):
            gray = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
            frames.append(np.asarray(gray, dtype=np.uint8))
    return frames


def read_feature_frames(path: Path) -> list[dict[str, np.ndarray]]:
    frames: list[dict[str, np.ndarray]] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, msg, _ in bag.read_messages(topics=[FEATURE_TOPIC]):
            channels = {channel.name: np.asarray(channel.values) for channel in msg.channels}
            frames.append(channels)
    return frames


def read_metrics(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def metric(row: dict[str, str], key: str, default: str = "n/a") -> str:
    value = row.get(key, "")
    return value if value not in {"", "nan", "None"} else default


def source_count(hist: str, token: str) -> int:
    total = 0
    for part in str(hist or "").split(";"):
        if token in part.lower():
            try:
                total += int(float(part.rsplit(":", 1)[1]))
            except Exception:
                pass
    return total


def colorize(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def draw_text(img: np.ndarray, lines: list[str], *, y0: int = 22) -> None:
    for i, line in enumerate(lines):
        y = y0 + i * 20
        cv2.putText(img, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)


def draw_features(img: np.ndarray, features: dict[str, np.ndarray] | None) -> None:
    if not features:
        return
    pu = features.get("p_u")
    pv = features.get("p_v")
    src = features.get("source_code")
    if pu is None or pv is None or src is None:
        return
    for x, y, code in zip(pu, pv, src):
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        c = int(round(float(code)))
        if c == 20:
            color = (40, 40, 255)
            radius = 4
        elif c == 2:
            color = (255, 220, 40)
            radius = 2
        elif c == 1:
            color = (80, 255, 80)
            radius = 2
        else:
            color = (220, 220, 220)
            radius = 2
        cv2.circle(img, (int(round(float(x))), int(round(float(y)))), radius, color, -1, cv2.LINE_AA)


def annotated_frame(
    gray: np.ndarray,
    *,
    name: str,
    frame_index: int,
    metrics: dict[str, str] | None,
    features: dict[str, np.ndarray] | None,
    ape_rpe: str,
    note: str,
    overlay_features: bool,
) -> np.ndarray:
    img = colorize(gray)
    if overlay_features:
        draw_features(img, features)
    if metrics:
        hist = metrics.get("export_source_histogram", "")
        xfeat = source_count(hist, "xfeat")
        lines = [
            f"CIRS {name} d30 | frame {frame_index:03d} | {note}",
            f"APE/RPE {ape_rpe} | recovery={metric(metrics, 'recovery_reason')}",
            f"tracks={metric(metrics, 'classical_track_count')} age={metric(metrics, 'classical_median_age')} xfeat={xfeat}",
        ]
    else:
        lines = [f"CIRS {name} d30 | frame {frame_index:03d} | {note}", f"APE/RPE {ape_rpe}"]
    draw_text(img, lines)
    return img


def make_contact_sheet(name: str, cfg: dict[str, object]) -> Path:
    frames = read_raw_frames(cfg["raw"])  # type: ignore[arg-type]
    features = read_feature_frames(cfg["features"])  # type: ignore[arg-type]
    metrics = read_metrics(cfg["metrics"])  # type: ignore[arg-type]
    selected = np.linspace(0, len(frames) - 1, 12, dtype=int).tolist()
    thumbs: list[np.ndarray] = []
    for idx in selected:
        img = annotated_frame(
            frames[idx],
            name=name,
            frame_index=idx,
            metrics=metrics[idx] if idx < len(metrics) else None,
            features=features[idx] if idx < len(features) else None,
            ape_rpe=str(cfg["ape_rpe"]),
            note=str(cfg["note"]),
            overlay_features=True,
        )
        thumbs.append(cv2.resize(img, (320, 240), interpolation=cv2.INTER_AREA))
    rows = []
    for row in range(0, len(thumbs), 3):
        rows.append(np.hstack(thumbs[row : row + 3]))
    sheet = np.vstack(rows)
    out = OUT_DIR / f"cirs_{name}_contact_features.png"
    cv2.imwrite(str(out), sheet)
    return out


def make_video(name: str, cfg: dict[str, object]) -> Path:
    frames = read_raw_frames(cfg["raw"])  # type: ignore[arg-type]
    features = read_feature_frames(cfg["features"])  # type: ignore[arg-type]
    metrics = read_metrics(cfg["metrics"])  # type: ignore[arg-type]
    h, w = frames[0].shape[:2]
    out = OUT_DIR / f"cirs_{name}_feature_overlay.mp4"
    writer = cv2.VideoWriter(
        str(out),
        cv2.VideoWriter_fourcc(*"mp4v"),
        8.0,
        (w, h),
    )
    for idx, gray in enumerate(frames):
        img = annotated_frame(
            gray,
            name=name,
            frame_index=idx,
            metrics=metrics[idx] if idx < len(metrics) else None,
            features=features[idx] if idx < len(features) else None,
            ape_rpe=str(cfg["ape_rpe"]),
            note=str(cfg["note"]),
            overlay_features=True,
        )
        writer.write(img)
    writer.release()
    return out


def make_overview(paths: list[Path]) -> Path:
    sheets = [cv2.imread(str(path), cv2.IMREAD_COLOR) for path in paths]
    sheets = [sheet for sheet in sheets if sheet is not None]
    if not sheets:
        raise RuntimeError("no sheets generated")
    width = min(sheet.shape[1] for sheet in sheets)
    resized = []
    for sheet in sheets:
        scale = width / sheet.shape[1]
        resized.append(cv2.resize(sheet, (width, int(sheet.shape[0] * scale)), interpolation=cv2.INTER_AREA))
    overview = np.vstack(resized)
    out = OUT_DIR / "cirs_key_windows_overview.png"
    cv2.imwrite(str(out), overview)
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contact_paths: list[Path] = []
    video_paths: list[Path] = []
    for name, cfg in RUNS.items():
        missing = [key for key in ("raw", "features", "metrics") if not Path(cfg[key]).exists()]  # type: ignore[arg-type]
        if missing:
            print(f"skip {name}: missing {missing}")
            continue
        contact_paths.append(make_contact_sheet(name, cfg))
        video_paths.append(make_video(name, cfg))
    overview = make_overview(contact_paths)
    print("overview", overview)
    for path in contact_paths + video_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
