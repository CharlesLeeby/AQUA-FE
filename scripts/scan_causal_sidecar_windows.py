#!/usr/bin/env python3
"""Find windows with multiple confirmed lineages and late seed observations."""

from __future__ import annotations

import argparse
import copy
import csv
import math
import re
from pathlib import Path

import rosbag

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "uw_frontend" / "ros"))
from causal_lineage_shadow_node import CausalLineageShadow, ShadowConfig  # noqa: E402


LEARNED_SOURCE_CODES = {10, 20, 30}
LEARNED_ID_MIN = 10_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Root containing sidecar.bag windows; repeat for datasets.",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--max-lineages", type=int, default=6)
    parser.add_argument("--min-observations", type=int, default=5)
    parser.add_argument("--min-distance-px", type=float, default=20.0)
    parser.add_argument("--late-frame", type=int, default=50)
    parser.add_argument("--ignore-zero-base-speeds", action="store_true")
    parser.add_argument("--rearm-absent-frames", type=int, default=0)
    parser.add_argument(
        "--window-regex",
        action="append",
        default=[],
        help=(
            "Only scan relative window paths matching this regular expression; "
            "repeat to include multiple dataset families."
        ),
    )
    return parser.parse_args()


def parse_roots(values: list[str]) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --root {value!r}; expected NAME=PATH")
        name, raw_path = value.split("=", 1)
        path = Path(raw_path).resolve()
        if not name or not path.is_dir():
            raise SystemExit(f"invalid root: {value!r}")
        roots.append((name, path))
    return roots


def feature_messages(path: Path, topic: str) -> list[object]:
    with rosbag.Bag(str(path), "r") as bag:
        return [msg for _topic, msg, _stamp in bag.read_messages(topics=[topic])]


def channel_values(msg: object, name: str, count: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            values = list(channel.values[:count])
            if len(values) < count:
                values.extend([default] * (count - len(values)))
            return values
    return [default] * count


def safe_int(value: float, default: int = -1) -> int:
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return default
        return int(round(numeric))
    except (TypeError, ValueError, OverflowError):
        return default


def strip_learned(msg: object) -> object:
    """Remove learned points when a historical full bag is used as the base."""
    output = copy.deepcopy(msg)
    count = len(output.points)
    ids = channel_values(output, "id", count, -1.0)
    sources = channel_values(output, "source_code", count, 0.0)
    learned = channel_values(output, "is_learned", count, 0.0)
    keep = [
        not (
            bool(round(learned[index]))
            or safe_int(sources[index], 0) in LEARNED_SOURCE_CODES
            or safe_int(ids[index]) >= LEARNED_ID_MIN
        )
        for index in range(count)
    ]
    output.points = [point for point, keep_value in zip(output.points, keep) if keep_value]
    for channel in output.channels:
        if len(channel.values) == len(keep):
            channel.values = [
                value for value, keep_value in zip(channel.values, keep) if keep_value
            ]
    return output


def locate_base(sidecar: Path) -> tuple[Path, bool] | None:
    candidate_roots = [sidecar.parent, sidecar.parent.parent]
    for window_root in candidate_roots:
        fresh = window_root / "fresh_klt" / "features.bag"
        if fresh.is_file():
            return fresh, False
        drop = window_root / "drop_whole_lineage.bag"
        if drop.is_file():
            return drop, False
        full = window_root / "full_merged.bag"
        if full.is_file():
            return full, True
    return None


def scan_case(
    family: str,
    window: str,
    sidecar: Path,
    *,
    max_lineages: int,
    min_observations: int,
    min_distance_px: float,
    late_frame: int,
    ignore_zero_base_speeds: bool,
    rearm_absent_frames: int,
) -> dict[str, object]:
    located = locate_base(sidecar)
    if located is None:
        raise RuntimeError("no base feature bag")
    base_path, strip_base = located
    base_messages = feature_messages(base_path, "/feature_tracker/feature")
    sidecar_messages = feature_messages(sidecar, "/feature_tracker/sidecar")
    if len(base_messages) != len(sidecar_messages):
        raise RuntimeError(
            f"frame count mismatch base={len(base_messages)} sidecar={len(sidecar_messages)}"
        )

    selector = CausalLineageShadow(
        ShadowConfig(
            max_lineages=max_lineages,
            min_observations=min_observations,
            min_distance_px=min_distance_px,
            ignore_zero_base_speeds=ignore_zero_base_speeds,
            rearm_absent_frames=rearm_absent_frames,
        )
    )
    injected_frames: list[int] = []
    injected_observations = 0
    late_injected_observations = 0
    activation_events = 0
    retirement_events = 0
    max_active_lineages = 0
    for frame_index, (base, sidecar_msg) in enumerate(zip(base_messages, sidecar_messages)):
        if strip_base:
            base = strip_learned(base)
        _merged, decision = selector.process(base, sidecar_msg)
        activation_events += len(
            [item for item in str(decision.get("activated_ids", "")).split(";") if item]
        )
        retirement_events += len(
            [item for item in str(decision.get("retired_ids", "")).split(";") if item]
        )
        active_ids = [
            item for item in str(decision.get("active_ids", "")).split(";") if item
        ]
        max_active_lineages = max(max_active_lineages, len(active_ids))
        count = int(decision["injected_observations"])
        if frame_index >= late_frame:
            late_injected_observations += count
        if count:
            injected_frames.append(frame_index)
            injected_observations += count

    eligible = [
        feature_id
        for feature_id, state in selector.lineages.items()
        if state.count >= selector.config.min_observations
    ]
    late_frames = [frame for frame in injected_frames if frame >= late_frame]
    selected = sorted(selector.selected_ids)
    return {
        "family": family,
        "window": window,
        "base_bag": str(base_path),
        "sidecar_bag": str(sidecar),
        "feature_frames": len(base_messages),
        "eligible_lineages": len(eligible),
        "selected_lineages": len(selected),
        "selected_ids": ";".join(str(item) for item in selected),
        "activation_events": activation_events,
        "retirement_events": retirement_events,
        "max_active_lineages": max_active_lineages,
        "injected_observations": injected_observations,
        "injected_frames": len(injected_frames),
        "first_injection_frame": injected_frames[0] if injected_frames else "",
        "last_injection_frame": injected_frames[-1] if injected_frames else "",
        "late_injection_frames": len(late_frames),
        "late_injection_observations": late_injected_observations,
    }


def main() -> int:
    args = parse_args()
    window_patterns = [re.compile(pattern) for pattern in args.window_regex]
    rows: list[dict[str, object]] = []
    for family, root in parse_roots(args.root):
        sidecars = sorted(root.rglob("sidecar.bag"))
        for sidecar in sidecars:
            window = sidecar.relative_to(root).parent.as_posix()
            if window_patterns and not any(
                pattern.search(window) for pattern in window_patterns
            ):
                continue
            try:
                rows.append(
                    scan_case(
                        family,
                        window,
                        sidecar,
                        max_lineages=args.max_lineages,
                        min_observations=args.min_observations,
                        min_distance_px=args.min_distance_px,
                        late_frame=args.late_frame,
                        ignore_zero_base_speeds=args.ignore_zero_base_speeds,
                        rearm_absent_frames=args.rearm_absent_frames,
                    )
                )
            except Exception as exc:
                print(f"warning: {sidecar}: {exc}")
    rows.sort(
        key=lambda row: (
            -int(row["late_injection_observations"] or 0),
            -int(row["selected_lineages"]),
            str(row["family"]),
            str(row["window"]),
        )
    )
    output = Path(args.output_csv).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise SystemExit("no windows with a usable base/sidecar pair")
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} windows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
