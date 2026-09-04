#!/usr/bin/env python3
"""Additive figures-only correction for the sealed Stage-5 MH01 GT bundle.

This renderer reads the already sealed associated-pairs and RPE-pairs CSVs.
It does not align poses, recompute APE/RPE, modify the sealed attempt, or start
ROS/model processes.  Its only scientific outputs are corrected vector SVGs.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import html
import json
import math
import os
from pathlib import Path
import signal
import stat
import sys
import traceback
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


sys.dont_write_bytecode = True

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve()
TEST_SOURCE = WORKSPACE / "scripts/tests/test_render_supervins_v1_official_euroc_mh01_gt_visualization_correction_v1.py"
TEST_RECEIPT = WORKSPACE / "papers/supervins_v1_official_euroc_mh01_gt_visualization_correction_test_receipt_v1.json"

SEALED_ATTEMPT = WORKSPACE / "experiments/published_supervins_v1_official_euroc_mh01_gt_evaluation_20260821_r1/attempt_001"
ASSOCIATED_CSV = SEALED_ATTEMPT / "analysis-output/associated-pairs.csv"
RPE_CSV = SEALED_ATTEMPT / "analysis-output/rpe-pairs-1s.csv"
SEALED_MANIFEST = SEALED_ATTEMPT / "analysis-output/artifact-manifest.json"
SEALED_RESULT = SEALED_ATTEMPT / "run_result.json"
ORIGINAL_FIGURE_1 = SEALED_ATTEMPT / "analysis-output/figures/figure-01-trajectory-overlay.svg"
ORIGINAL_FIGURE_2 = SEALED_ATTEMPT / "analysis-output/figures/figure-02-error-over-time.svg"

EVIDENCE_ROOT = WORKSPACE / "experiments/published_supervins_v1_official_euroc_mh01_gt_evaluation_visualization_correction_20260821_v1"
SOURCE_DIR = EVIDENCE_ROOT / "source"
FIGURES_DIR = EVIDENCE_ROOT / "figures"
SOURCE_COPY = SOURCE_DIR / SOURCE.name
TEST_COPY = SOURCE_DIR / TEST_SOURCE.name
TEST_RECEIPT_COPY = SOURCE_DIR / TEST_RECEIPT.name
FIGURE_1 = FIGURES_DIR / "figure-01-trajectory-overlay-corrected-v1.svg"
FIGURE_2 = FIGURES_DIR / "figure-02-error-over-time-corrected-v1.svg"
MANIFEST = EVIDENCE_ROOT / "artifact-manifest.json"
RUN_RECEIPT = EVIDENCE_ROOT / "visualization-correction-receipt.json"
FAILURE_RECEIPT = EVIDENCE_ROOT / "visualization-correction-failure-receipt.json"

COMMAND = ["/usr/bin/python3", "-B", str(SOURCE), "--action", "run"]

EXPECTED_INPUTS: Dict[Path, Dict[str, Any]] = {
    ASSOCIATED_CSV: {
        "sha256": "958649077a8ccd2b73fe2c58392af1980b011bb895a53b95ad00b585820283f1",
        "size_bytes": 614772,
    },
    RPE_CSV: {
        "sha256": "71b4f357d33d1cd7a4b6f70b87b467fc5faa95c39e71a7cd3c566d8d84548e57",
        "size_bytes": 200989,
    },
    SEALED_MANIFEST: {
        "sha256": "df79dc4543be692b2ed9f040b80039cd96dbbb37c34389fddc431b2859f769bb",
        "size_bytes": 2164,
    },
    SEALED_RESULT: {
        "sha256": "72e5c40bb0b3212b37db3deed0ed0a7c0f557458e6277143329c93e55ca83918",
        "size_bytes": 33695,
    },
    ORIGINAL_FIGURE_1: {
        "sha256": "eca48d727db213a3b1cfcac9bad4e0fc294592eba3afc395e4bc62401608c15e",
        "size_bytes": 156761,
    },
    ORIGINAL_FIGURE_2: {
        "sha256": "bee8454ea2762d07d6bb230d95338749b22d87b9fda8861e5d9ea78e59b46f88",
        "size_bytes": 54607,
    },
}

ASSOCIATED_HEADER = [
    "estimate_row_index", "camera_row_index", "estimate_timestamp_text",
    "display_timestamp_ns", "source_camera_timestamp_ns", "gt_row_index",
    "timestamp_text_minus_source_ns", "gt_x_m", "gt_y_m", "gt_z_m",
    "estimate_x_m", "estimate_y_m", "estimate_z_m", "se3_aligned_x_m",
    "se3_aligned_y_m", "se3_aligned_z_m", "se3_ape_m",
    "sim3_aligned_x_m", "sim3_aligned_y_m", "sim3_aligned_z_m",
    "sim3_ape_m",
]
RPE_HEADER = [
    "left_estimate_row_index", "right_estimate_row_index",
    "left_camera_row_index", "right_camera_row_index",
    "left_source_timestamp_ns", "right_source_timestamp_ns", "delta_ns",
    "se3_rpe_m", "sim3_rpe_m",
]

PENDING_SIGNAL: Optional[int] = None
NAMESPACE_OWNED = False
TERMINAL_COMMITTED = False


class ControlledSignal(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path, include_seal: bool = False) -> Dict[str, Any]:
    info = path.stat()
    identity: Dict[str, Any] = {
        "sha256": sha256_file(path),
        "size_bytes": info.st_size,
    }
    if include_seal:
        identity.update({
            "mode": "0{:o}".format(stat.S_IMODE(info.st_mode)),
            "nlink": info.st_nlink,
        })
    return identity


def compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, indent=2, sort_keys=True, ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_tree_digest(entries: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        {
            "path": path,
            "sha256": spec["sha256"],
            "size_bytes": int(spec["size_bytes"]),
        }
        for path, spec in sorted(entries.items())
    ]
    return hashlib.sha256(compact_json_bytes(rows)).hexdigest()


def add_canonical_self_hash(value: Mapping[str, Any], field: str) -> Dict[str, Any]:
    if field in value:
        raise ValueError("self-hash field already exists")
    output = dict(value)
    output[field] = hashlib.sha256(compact_json_bytes(value)).hexdigest()
    return output


def verify_canonical_self_hash(value: Mapping[str, Any], field: str) -> bool:
    if field not in value or not isinstance(value[field], str):
        return False
    base = dict(value)
    declared = base.pop(field)
    return hashlib.sha256(compact_json_bytes(base)).hexdigest() == declared


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def mkdir_exclusive(path: Path, mode: int = 0o755) -> None:
    os.mkdir(str(path), mode)
    fsync_directory(path.parent)


def write_bytes_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> Dict[str, Any]:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    return file_identity(path, include_seal=True)


def write_json_exclusive(path: Path, value: Any) -> Dict[str, Any]:
    return write_bytes_exclusive(path, pretty_json_bytes(value))


def _signal_handler(signum: int, _frame: Any) -> None:
    global PENDING_SIGNAL
    if PENDING_SIGNAL is None:
        PENDING_SIGNAL = signum


def install_signal_handlers() -> Dict[int, Any]:
    previous: Dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_handler)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def raise_if_pending() -> None:
    if PENDING_SIGNAL is not None:
        raise ControlledSignal("caught signal {}".format(PENDING_SIGNAL))


def inspect_expected_inputs() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    failures: List[str] = []
    for path, expected in sorted(EXPECTED_INPUTS.items(), key=lambda item: str(item[0])):
        try:
            observed = file_identity(path, include_seal=True)
            ok = (
                observed["sha256"] == expected["sha256"]
                and observed["size_bytes"] == expected["size_bytes"]
                and observed["mode"] == "0444"
                and observed["nlink"] == 1
            )
        except Exception as exc:
            observed = {"error": "{}: {}".format(type(exc).__name__, exc)}
            ok = False
        checks[str(path)] = {"expected": expected, "observed": observed, "ok": ok}
        if not ok:
            failures.append(str(path))
    return {"ok": not failures, "failures": failures, "checks": checks}


def finite_float(text: str, label: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("{} is non-finite".format(label))
    return value


def read_associated_rows(path: Path = ASSOCIATED_CSV) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ASSOCIATED_HEADER:
            raise ValueError("associated-pairs header differs from sealed schema")
        for index, row in enumerate(reader):
            record: Dict[str, Any] = {
                "estimate_row_index": int(row["estimate_row_index"]),
                "camera_row_index": int(row["camera_row_index"]),
                "source_camera_timestamp_ns": int(row["source_camera_timestamp_ns"]),
            }
            for name in (
                "gt_x_m", "gt_y_m", "gt_z_m",
                "se3_aligned_x_m", "se3_aligned_y_m", "se3_aligned_z_m",
                "sim3_aligned_x_m", "sim3_aligned_y_m", "sim3_aligned_z_m",
                "se3_ape_m",
            ):
                record[name] = finite_float(row[name], "row {} {}".format(index, name))
            if record["se3_ape_m"] < 0.0:
                raise ValueError("sealed APE display column is negative")
            if record["estimate_row_index"] != index:
                raise ValueError("associated estimate indices are not contiguous")
            if record["camera_row_index"] != 63 + 2 * index:
                raise ValueError("associated camera indices differ from sealed contract")
            if output and record["source_camera_timestamp_ns"] <= output[-1]["source_camera_timestamp_ns"]:
                raise ValueError("associated timestamps are not strictly increasing")
            output.append(record)
    if len(output) != 1799:
        raise ValueError("associated-pairs row count is not 1799")
    return output


def read_rpe_rows(path: Path = RPE_CSV) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != RPE_HEADER:
            raise ValueError("RPE-pairs header differs from sealed schema")
        for index, row in enumerate(reader):
            record = {
                "left_estimate_row_index": int(row["left_estimate_row_index"]),
                "right_estimate_row_index": int(row["right_estimate_row_index"]),
                "left_camera_row_index": int(row["left_camera_row_index"]),
                "right_camera_row_index": int(row["right_camera_row_index"]),
                "left_source_timestamp_ns": int(row["left_source_timestamp_ns"]),
                "right_source_timestamp_ns": int(row["right_source_timestamp_ns"]),
                "delta_ns": int(row["delta_ns"]),
                "se3_rpe_m": finite_float(row["se3_rpe_m"], "RPE row {}".format(index)),
            }
            if record["se3_rpe_m"] < 0.0:
                raise ValueError("sealed RPE display column is negative")
            if record["left_estimate_row_index"] != index or record["right_estimate_row_index"] != index + 10:
                raise ValueError("RPE estimate indices differ from sealed contract")
            if record["right_camera_row_index"] - record["left_camera_row_index"] != 20:
                raise ValueError("RPE camera index delta differs from sealed contract")
            if record["delta_ns"] != 1_000_000_000:
                raise ValueError("RPE time delta differs from sealed contract")
            output.append(record)
    if len(output) != 1789:
        raise ValueError("RPE-pairs row count is not 1789")
    return output


def tick_text(value: float) -> str:
    if abs(value) < 5e-14:
        return "0"
    return "{:.4g}".format(value)


def map_point(
    xvalue: float, yvalue: float, domain: Mapping[str, float],
    x0: float, y0: float, width: float, height: float,
) -> Tuple[float, float]:
    px = x0 + (xvalue - domain["xmin"]) / (domain["xmax"] - domain["xmin"]) * width
    py = y0 + height - (yvalue - domain["ymin"]) / (domain["ymax"] - domain["ymin"]) * height
    return px, py


def panel_svg(
    series: Sequence[Tuple[Sequence[float], Sequence[float], str, str, str]],
    domain: Mapping[str, float], x0: float, y0: float, width: float,
    height: float, xlabel: str, ylabel: str, label: str,
) -> str:
    parts = [
        '<rect x="{:.2f}" y="{:.2f}" width="{:.2f}" height="{:.2f}" fill="white" stroke="#555" stroke-width="1"/>'.format(x0, y0, width, height),
        '<text x="{:.2f}" y="{:.2f}" font-size="17" font-weight="bold">{}</text>'.format(x0 + 8, y0 + 23, html.escape(label)),
    ]
    for tick in range(5):
        alpha = tick / 4.0
        px = x0 + alpha * width
        py = y0 + height - alpha * height
        xv = domain["xmin"] + alpha * (domain["xmax"] - domain["xmin"])
        yv = domain["ymin"] + alpha * (domain["ymax"] - domain["ymin"])
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{0:.2f}" y2="{2:.2f}" stroke="#e1e1e1"/>'.format(px, y0, y0 + height))
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{2:.2f}" y2="{1:.2f}" stroke="#e1e1e1"/>'.format(py, x0, x0 + width))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="11" text-anchor="middle">{}</text>'.format(px, y0 + height + 19, tick_text(xv)))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="11" text-anchor="end">{}</text>'.format(x0 - 7, py + 4, tick_text(yv)))
    for xvalues, yvalues, colour, name, dash in series:
        points = " ".join(
            "{:.2f},{:.2f}".format(*map_point(float(xvalue), float(yvalue), domain, x0, y0, width, height))
            for xvalue, yvalue in zip(xvalues, yvalues)
        )
        dash_attr = ' stroke-dasharray="{}"'.format(dash) if dash else ""
        parts.append('<polyline fill="none" stroke="{}" stroke-width="1.8"{} vector-effect="non-scaling-stroke" points="{}"/>'.format(colour, dash_attr, points))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="13" text-anchor="middle">{}</text>'.format(x0 + width / 2.0, y0 + height + 44, html.escape(xlabel)))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="13" text-anchor="middle" transform="rotate(-90 {:.2f} {:.2f})">{}</text>'.format(x0 - 58, y0 + height / 2.0, x0 - 58, y0 + height / 2.0, html.escape(ylabel)))
    legend_x = x0 + width - 177
    legend_y = y0 + 17
    parts.append('<rect x="{:.2f}" y="{:.2f}" width="171" height="62" fill="white" fill-opacity="0.9"/>'.format(legend_x - 5, legend_y - 12))
    for index, (_x, _y, colour, name, dash) in enumerate(series):
        yy = legend_y + index * 19
        dash_attr = ' stroke-dasharray="{}"'.format(dash) if dash else ""
        parts.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" stroke-width="2"{} />'.format(legend_x, yy, legend_x + 27, yy, colour, dash_attr))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10.5">{}</text>'.format(legend_x + 33, yy + 4, html.escape(name)))
    return "\n".join(parts)


def trajectory_svg(rows: Sequence[Mapping[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    series_xyz = {
        "gt": ([float(row["gt_x_m"]) for row in rows], [float(row["gt_y_m"]) for row in rows], [float(row["gt_z_m"]) for row in rows]),
        "se3": ([float(row["se3_aligned_x_m"]) for row in rows], [float(row["se3_aligned_y_m"]) for row in rows], [float(row["se3_aligned_z_m"]) for row in rows]),
        "sim3": ([float(row["sim3_aligned_x_m"]) for row in rows], [float(row["sim3_aligned_y_m"]) for row in rows], [float(row["sim3_aligned_z_m"]) for row in rows]),
    }
    all_x = [value for xyz in series_xyz.values() for value in xyz[0]]
    all_y = [value for xyz in series_xyz.values() for value in xyz[1]]
    all_z = [value for xyz in series_xyz.values() for value in xyz[2]]
    raw = {
        "xmin": min(all_x), "xmax": max(all_x),
        "ymin": min(all_y), "ymax": max(all_y),
        "zmin": min(all_z), "zmax": max(all_z),
    }
    largest_span = max(raw["xmax"] - raw["xmin"], raw["ymax"] - raw["ymin"], raw["zmax"] - raw["zmin"])
    if not math.isfinite(largest_span) or largest_span <= 0.0:
        raise ValueError("trajectory plotting span is invalid")
    common_extent_m = largest_span * 1.12

    def centered_domain(xmin: float, xmax: float, ymin: float, ymax: float) -> Dict[str, float]:
        xcenter = 0.5 * (xmin + xmax)
        ycenter = 0.5 * (ymin + ymax)
        return {
            "xmin": xcenter - common_extent_m / 2.0,
            "xmax": xcenter + common_extent_m / 2.0,
            "ymin": ycenter - common_extent_m / 2.0,
            "ymax": ycenter + common_extent_m / 2.0,
        }

    xy_domain = centered_domain(raw["xmin"], raw["xmax"], raw["ymin"], raw["ymax"])
    xz_domain = centered_domain(raw["xmin"], raw["xmax"], raw["zmin"], raw["zmax"])
    width = 440.0
    height = 440.0
    metres_per_pixel = common_extent_m / width
    audit = {
        "plot_width_px": width,
        "plot_height_px": height,
        "shared_extent_m": common_extent_m,
        "shared_metres_per_pixel": metres_per_pixel,
        "xy_domain": xy_domain,
        "xz_domain": xz_domain,
        "xy_x_metres_per_pixel": (xy_domain["xmax"] - xy_domain["xmin"]) / width,
        "xy_y_metres_per_pixel": (xy_domain["ymax"] - xy_domain["ymin"]) / height,
        "xz_x_metres_per_pixel": (xz_domain["xmax"] - xz_domain["xmin"]) / width,
        "xz_z_metres_per_pixel": (xz_domain["ymax"] - xz_domain["ymin"]) / height,
    }
    audit["equal_metric_aspect_all_axes"] = max(
        abs(audit[key] - metres_per_pixel)
        for key in (
            "xy_x_metres_per_pixel", "xy_y_metres_per_pixel",
            "xz_x_metres_per_pixel", "xz_z_metres_per_pixel",
        )
    ) <= 1e-15
    if not audit["equal_metric_aspect_all_axes"]:
        raise ValueError("trajectory panels do not have equal metric aspect")
    drawing_series_xy = [
        (series_xyz["gt"][0], series_xyz["gt"][1], "#000000", "Official GT", ""),
        (series_xyz["se3"][0], series_xyz["se3"][1], "#0072B2", "SE(3) aligned", ""),
        (series_xyz["sim3"][0], series_xyz["sim3"][1], "#E69F00", "Sim(3) diagnostic", "7 4"),
    ]
    drawing_series_xz = [
        (series_xyz["gt"][0], series_xyz["gt"][2], "#000000", "Official GT", ""),
        (series_xyz["se3"][0], series_xyz["se3"][2], "#0072B2", "SE(3) aligned", ""),
        (series_xyz["sim3"][0], series_xyz["sim3"][2], "#E69F00", "Sim(3) diagnostic", "7 4"),
    ]
    metadata = html.escape(json.dumps(audit, sort_keys=True, separators=(",", ":")), quote=False)
    body = "\n".join([
        panel_svg(drawing_series_xy, xy_domain, 100, 70, width, height, "x (m)", "y (m)", "(a) XY trajectory"),
        panel_svg(drawing_series_xz, xz_domain, 700, 70, width, height, "x (m)", "z (m)", "(b) XZ trajectory"),
    ])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="590" viewBox="0 0 1240 590" '
        'font-family="Arial, Helvetica, sans-serif">\n'
        '<title>Corrected MH01 trajectory overlay</title>\n'
        '<desc>XY and XZ panels share identical metres per pixel on both axes. Sim3 is diagnostic only.</desc>\n'
        '<metadata id="metric-aspect-audit">{}</metadata>\n'
        '<rect width="100%" height="100%" fill="white"/>\n{}\n</svg>\n'
    ).format(metadata, body)
    return svg, audit


def error_svg(
    associated_rows: Sequence[Mapping[str, Any]],
    rpe_rows: Sequence[Mapping[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    first_ns = int(associated_rows[0]["source_camera_timestamp_ns"])
    ape_time = [(int(row["source_camera_timestamp_ns"]) - first_ns) / 1e9 for row in associated_rows]
    ape = [float(row["se3_ape_m"]) for row in associated_rows]
    rpe_time = [(int(row["right_source_timestamp_ns"]) - first_ns) / 1e9 for row in rpe_rows]
    rpe = [float(row["se3_rpe_m"]) for row in rpe_rows]
    if min(ape_time + rpe_time) < 0.0 or min(ape + rpe) < 0.0:
        raise ValueError("negative display time or error is forbidden")

    def nonnegative_domain(xvalues: Sequence[float], yvalues: Sequence[float]) -> Dict[str, float]:
        xmax = max(xvalues) * 1.02
        ymax = max(yvalues) * 1.08
        return {
            "xmin": 0.0,
            "xmax": xmax if xmax > 0.0 else 1.0,
            "ymin": 0.0,
            "ymax": ymax if ymax > 0.0 else 1.0,
        }

    ape_domain = nonnegative_domain(ape_time, ape)
    rpe_domain = nonnegative_domain(rpe_time, rpe)
    audit = {
        "ape_domain": ape_domain,
        "rpe_domain": rpe_domain,
        "ape_source_min_s": min(ape_time),
        "rpe_source_min_s": min(rpe_time),
        "ape_source_error_min_m": min(ape),
        "rpe_source_error_min_m": min(rpe),
        "all_axis_lower_bounds_exact_zero": (
            ape_domain["xmin"] == 0.0 and ape_domain["ymin"] == 0.0
            and rpe_domain["xmin"] == 0.0 and rpe_domain["ymin"] == 0.0
        ),
    }
    if not audit["all_axis_lower_bounds_exact_zero"]:
        raise ValueError("error panels do not start at zero")
    body = "\n".join([
        panel_svg([(ape_time, ape, "#D55E00", "SE(3) translation APE", "")], ape_domain, 100, 70, 440, 400, "source time since first match (s)", "error (m)", "(a) APE over time"),
        panel_svg([(rpe_time, rpe, "#0072B2", "SE(3) 1 s translation RPE", "")], rpe_domain, 700, 70, 440, 400, "pair end time since first match (s)", "error (m)", "(b) RPE over time"),
    ])
    metadata = html.escape(json.dumps(audit, sort_keys=True, separators=(",", ":")), quote=False)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="550" viewBox="0 0 1240 550" '
        'font-family="Arial, Helvetica, sans-serif">\n'
        '<title>Corrected MH01 error traces</title>\n'
        '<desc>Both time and error axes begin at exactly zero. Values are read from the sealed CSVs.</desc>\n'
        '<metadata id="nonnegative-axis-audit">{}</metadata>\n'
        '<rect width="100%" height="100%" fill="white"/>\n{}\n</svg>\n'
    ).format(metadata, body)
    return svg, audit


def exact_output_paths() -> List[str]:
    return sorted([
        str(SOURCE_COPY.relative_to(EVIDENCE_ROOT)),
        str(TEST_COPY.relative_to(EVIDENCE_ROOT)),
        str(TEST_RECEIPT_COPY.relative_to(EVIDENCE_ROOT)),
        str(FIGURE_1.relative_to(EVIDENCE_ROOT)),
        str(FIGURE_2.relative_to(EVIDENCE_ROOT)),
        str(MANIFEST.relative_to(EVIDENCE_ROOT)),
        str(RUN_RECEIPT.relative_to(EVIDENCE_ROOT)),
    ])


def audit_completed_root() -> Dict[str, Any]:
    actual = sorted(str(path.relative_to(EVIDENCE_ROOT)) for path in EVIDENCE_ROOT.rglob("*") if path.is_file())
    checks: Dict[str, Any] = {}
    for relative in actual:
        path = EVIDENCE_ROOT / relative
        checks[relative] = file_identity(path, include_seal=True)
    return {
        "exact_file_set": actual == exact_output_paths(),
        "expected_file_set": exact_output_paths(),
        "actual_file_set": actual,
        "all_files_mode_0444_nlink1": all(
            value["mode"] == "0444" and value["nlink"] == 1
            for value in checks.values()
        ),
        "files": checks,
    }


def run_once() -> int:
    global NAMESPACE_OWNED, TERMINAL_COMMITTED
    if EVIDENCE_ROOT.exists():
        print(json.dumps({"status": "NO_GO", "reason": "fresh correction root already exists"}, sort_keys=True))
        return 2
    input_pre = inspect_expected_inputs()
    if not input_pre["ok"]:
        print(json.dumps({"status": "NO_GO", "input_failures": input_pre["failures"]}, sort_keys=True))
        return 2
    for path in (SOURCE, TEST_SOURCE, TEST_RECEIPT):
        info = file_identity(path, include_seal=True)
        if info["mode"] != "0444" or info["nlink"] != 1:
            print(json.dumps({"status": "NO_GO", "unsealed_source_or_test": str(path), "identity": info}, sort_keys=True))
            return 2

    previous_handlers = install_signal_handlers()
    started_at = now_iso()
    try:
        mkdir_exclusive(EVIDENCE_ROOT)
        NAMESPACE_OWNED = True
        mkdir_exclusive(SOURCE_DIR)
        mkdir_exclusive(FIGURES_DIR)
        raise_if_pending()

        source_identity = write_bytes_exclusive(SOURCE_COPY, SOURCE.read_bytes())
        test_identity = write_bytes_exclusive(TEST_COPY, TEST_SOURCE.read_bytes())
        test_receipt_identity = write_bytes_exclusive(TEST_RECEIPT_COPY, TEST_RECEIPT.read_bytes())
        associated_rows = read_associated_rows()
        rpe_rows = read_rpe_rows()
        raise_if_pending()

        trajectory_text, trajectory_audit = trajectory_svg(associated_rows)
        error_text, error_audit = error_svg(associated_rows, rpe_rows)
        figure_1_identity = write_bytes_exclusive(FIGURE_1, trajectory_text.encode("utf-8"))
        figure_2_identity = write_bytes_exclusive(FIGURE_2, error_text.encode("utf-8"))
        raise_if_pending()

        input_post = inspect_expected_inputs()
        if not input_post["ok"] or input_post != input_pre:
            raise ValueError("sealed input identities changed during render")

        manifest_entries = {
            str(SOURCE_COPY.relative_to(EVIDENCE_ROOT)): source_identity,
            str(TEST_COPY.relative_to(EVIDENCE_ROOT)): test_identity,
            str(TEST_RECEIPT_COPY.relative_to(EVIDENCE_ROOT)): test_receipt_identity,
            str(FIGURE_1.relative_to(EVIDENCE_ROOT)): figure_1_identity,
            str(FIGURE_2.relative_to(EVIDENCE_ROOT)): figure_2_identity,
        }
        manifest_base = {
            "schema_version": "aqua-fe-supervins-mh01-gt-visualization-correction-manifest-v1",
            "created_at": now_iso(),
            "status": "FIGURES_ONLY_ADDITIVE_CORRECTION",
            "scope": "Corrected figures, renderer source, tests, and test receipt. The terminal render receipt is intentionally created after and anchors this manifest.",
            "supersedes_figures_only": {
                str(ORIGINAL_FIGURE_1): EXPECTED_INPUTS[ORIGINAL_FIGURE_1],
                str(ORIGINAL_FIGURE_2): EXPECTED_INPUTS[ORIGINAL_FIGURE_2],
            },
            "does_not_supersede": [
                str(SEALED_RESULT), str(SEALED_MANIFEST),
                str(ASSOCIATED_CSV), str(RPE_CSV),
            ],
            "entry_count": len(manifest_entries),
            "entries": dict(sorted(manifest_entries.items())),
            "bundle_content_tree_algorithm": "SHA-256 over compact canonical sorted [{path,sha256,size_bytes}]",
            "bundle_content_tree_sha256": canonical_tree_digest(manifest_entries),
            "manifest_self_hash_algorithm": "SHA-256 over compact canonical JSON of this object with manifest_self_hash_sha256 omitted",
        }
        manifest = add_canonical_self_hash(manifest_base, "manifest_self_hash_sha256")
        if not verify_canonical_self_hash(manifest, "manifest_self_hash_sha256"):
            raise ValueError("manifest self-hash verification failed before write")
        manifest_identity = write_json_exclusive(MANIFEST, manifest)

        existing_before_receipt = sorted(
            str(path.relative_to(EVIDENCE_ROOT))
            for path in EVIDENCE_ROOT.rglob("*") if path.is_file()
        )
        expected_before_receipt = sorted(
            relative for relative in exact_output_paths()
            if relative != str(RUN_RECEIPT.relative_to(EVIDENCE_ROOT))
        )
        preterminal_seals = {
            relative: file_identity(EVIDENCE_ROOT / relative, include_seal=True)
            for relative in existing_before_receipt
        }
        preterminal_exact = existing_before_receipt == expected_before_receipt
        preterminal_sealed = all(
            identity["mode"] == "0444" and identity["nlink"] == 1
            for identity in preterminal_seals.values()
        )
        if not preterminal_exact or not preterminal_sealed:
            raise ValueError("preterminal exact-file-set or seal audit failed")
        receipt_base = {
            "schema_version": "aqua-fe-supervins-mh01-gt-visualization-correction-receipt-v1",
            "status": "PASS_ADDITIVE_FIGURES_ONLY_CORRECTION",
            "return_code": 0,
            "started_at": started_at,
            "completed_at": now_iso(),
            "controller_command": COMMAND,
            "fresh_root_created_once": True,
            "retry_authorized": False,
            "source": file_identity(SOURCE, include_seal=True),
            "tests": file_identity(TEST_SOURCE, include_seal=True),
            "test_receipt": file_identity(TEST_RECEIPT, include_seal=True),
            "sealed_input_pre": input_pre,
            "sealed_input_post": input_post,
            "sealed_inputs_unchanged": input_pre == input_post,
            "input_rows": {"associated_pairs": len(associated_rows), "rpe_pairs_1s": len(rpe_rows)},
            "figure_audit": {
                "trajectory": trajectory_audit,
                "error": error_audit,
            },
            "generated_before_manifest": manifest_entries,
            "artifact_manifest": manifest_identity,
            "artifact_manifest_self_hash_verified": verify_canonical_self_hash(manifest, "manifest_self_hash_sha256"),
            "existing_files_before_terminal_receipt": existing_before_receipt,
            "preterminal_exact_file_set_verified": preterminal_exact,
            "preterminal_all_files_mode_0444_nlink1": preterminal_sealed,
            "preterminal_file_seals": preterminal_seals,
            "expected_exact_file_set_after_terminal_receipt": exact_output_paths(),
            "terminal_receipt_written_last": True,
            "supersedes_figures_only": True,
            "superseded_figure_identities": {
                str(ORIGINAL_FIGURE_1): EXPECTED_INPUTS[ORIGINAL_FIGURE_1],
                str(ORIGINAL_FIGURE_2): EXPECTED_INPUTS[ORIGINAL_FIGURE_2],
            },
            "sealed_attempt_or_metrics_superseded": False,
            "scientific_boundary": {
                "existing_csv_coordinates_and_error_columns_read": True,
                "pose_alignment_recomputed": False,
                "ape_or_rpe_recomputed": False,
                "metrics_json_modified": False,
                "sealed_attempt_modified": False,
                "ros_or_model_started": False,
                "scientific_claim_changed": False,
            },
            "receipt_self_hash_algorithm": "SHA-256 over compact canonical JSON of this object with receipt_self_hash_sha256 omitted",
        }
        receipt = add_canonical_self_hash(receipt_base, "receipt_self_hash_sha256")
        if not verify_canonical_self_hash(receipt, "receipt_self_hash_sha256"):
            raise ValueError("receipt self-hash verification failed before write")
        receipt_identity = write_json_exclusive(RUN_RECEIPT, receipt)
        TERMINAL_COMMITTED = True
        try:
            print(json.dumps({
                "status": receipt["status"],
                "return_code": 0,
                "root": str(EVIDENCE_ROOT),
                "receipt": receipt_identity,
                "manifest": manifest_identity,
            }, sort_keys=True))
        except OSError:
            pass
        return 0
    except BaseException as exc:
        if TERMINAL_COMMITTED:
            return 0
        if NAMESPACE_OWNED and EVIDENCE_ROOT.exists() and not RUN_RECEIPT.exists() and not FAILURE_RECEIPT.exists():
            failure_base = {
                "schema_version": "aqua-fe-supervins-mh01-gt-visualization-correction-failure-v1",
                "status": "FAIL_ADDITIVE_FIGURES_ONLY_CORRECTION",
                "return_code": 1,
                "started_at": started_at,
                "failed_at": now_iso(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "retry_authorized": False,
                "failure_self_hash_algorithm": "SHA-256 over compact canonical JSON of this object with failure_self_hash_sha256 omitted",
            }
            try:
                write_json_exclusive(
                    FAILURE_RECEIPT,
                    add_canonical_self_hash(failure_base, "failure_self_hash_sha256"),
                )
            except Exception:
                pass
        print(json.dumps({"status": "FAIL", "error": "{}: {}".format(type(exc).__name__, exc)}, sort_keys=True))
        return 1
    finally:
        restore_signal_handlers(previous_handlers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    args = parser.parse_args()
    if args.action == "preflight":
        audit = inspect_expected_inputs()
        ready = audit["ok"] and not EVIDENCE_ROOT.exists() and TEST_SOURCE.exists() and TEST_RECEIPT.exists()
        print(json.dumps({
            "status": "GO_FIGURES_ONLY_CORRECTION" if ready else "NO_GO",
            "ready": ready,
            "fresh_root_absent": not EVIDENCE_ROOT.exists(),
            "input_audit": audit,
            "scientific_boundary": {
                "alignment_or_metric_recomputation_run": False,
                "sealed_attempt_modified": False,
            },
        }, sort_keys=True))
        return 0 if ready else 2
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
