#!/usr/bin/env python3
"""Exploratory transfer scan for the External-KLT dynamic rescue gate.

This script does not rewrite a feature bag.  It replays the External-KLT
overlap/mature-track state machine over frozen AQUA-FE KLT feature bags and
asks whether already-recorded, FB/NCC-qualified XFeat sidecars were available
while the state machine was active.  The result is an opportunity/selection
diagnostic, not a trajectory result.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
CONFIRMATORY_LEDGER = (
    ROOT / "papers/frontend_same_backend_confirmatory_v3/frontend_runability.csv"
)


@dataclass(frozen=True)
class Case:
    window: str
    cohort: str
    known_outcome: str
    klt_bag: Path
    xfeat_metrics: Path


@dataclass(frozen=True)
class GateConfig:
    name: str
    enable_after_frame: int | None
    enable_after_sec: float | None
    enter_overlap_ratio: float = 80.0 / 180.0
    enter_mature_ratio: float = 40.0 / 180.0
    enter_frames: int = 3
    exit_overlap_ratio: float = 120.0 / 180.0
    exit_mature_ratio: float = 80.0 / 180.0
    exit_frames: int = 10
    min_rescue_frames: int = 20


class TrackAger:
    """Exact normalized counterpart of the External-KLT TrackAger."""

    def __init__(self) -> None:
        self.ages: dict[int, int] = {}
        self.previous_ids: set[int] = set()

    def update(self, ids: list[int]) -> tuple[dict[int, int], int, bool]:
        current = set(ids)
        overlap = len(current & self.previous_ids) if self.previous_ids else 0
        reset = (
            len(current) >= 20
            and len(self.previous_ids) >= 20
            and overlap / float(min(len(current), len(self.previous_ids))) < 0.05
        )
        if reset:
            self.ages.clear()
            overlap = 0
        self.ages = {
            feature_id: self.ages.get(feature_id, 0) + 1
            for feature_id in current
        }
        self.previous_ids = current
        return dict(self.ages), overlap, reset


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def feature_ids(message) -> list[int]:
    for name in ("id", "feature_id"):
        for channel in message.channels:
            if channel.name == name:
                if len(channel.values) != len(message.points):
                    raise ValueError(f"{name} length mismatch")
                return [int(round(float(value))) for value in channel.values]
    raise ValueError("feature message has no id/feature_id channel")


def discover_cases() -> list[Case]:
    ledger = read_csv(CONFIRMATORY_LEDGER)
    indexed = {(row["run_slug"], row["arm"]): row for row in ledger}
    cases: list[Case] = []
    for window in sorted({row["run_slug"] for row in ledger}):
        klt = indexed[(window, "klt")]
        xfeat = indexed[(window, "xfeat_v3")]
        cases.append(
            Case(
                window=window,
                cohort="confirmatory_v3_frontend",
                known_outcome="UNREAD_OR_NOT_USED",
                klt_bag=Path(klt["feature_bag_path"]),
                xfeat_metrics=Path(xfeat["frontend_metrics_path"]),
            )
        )

    development = [
        Case(
            "a09_6000_6800",
            "known_outcome_development",
            "POSITIVE_RETAINED",
            Path(
                "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
                "external_klt_every2_fsbcv1_a09_6000_6800_klt_r1/features.bag"
            ),
            ROOT
            / "artifacts/frontend_persistence_churn_guard_v3/shadow_root/logs/"
            "aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcgv3_"
            "a09_6000_6800/frontend_metrics.csv",
        ),
        Case(
            "a06_s045_d045",
            "known_outcome_development",
            "POSITIVE_RETAINED",
            ROOT
            / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/"
            "logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_"
            "a06_s045_d045_klt_frontend/features.bag",
            ROOT
            / "artifacts/frontend_persistence_churn_guard_v3/shadow_root/logs/"
            "aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcgv3_"
            "a06_s045_d045/frontend_metrics.csv",
        ),
        Case(
            "a06_s000_d045",
            "known_outcome_development",
            "HARMFUL_REPLACEMENT_BLOCKED_BY_V3",
            ROOT
            / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/"
            "logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_"
            "a06_s000_d045_klt_frontend/features.bag",
            ROOT
            / "artifacts/frontend_persistence_churn_guard_v3/shadow_root/logs/"
            "aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcgv3_"
            "a06_s000_d045/frontend_metrics.csv",
        ),
        Case(
            "h07_s000_d050",
            "known_outcome_development",
            "NO_HARM_ANCHOR",
            ROOT
            / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/"
            "logs/aqualoc_real_vins/external_klt_every2_fsbcsupp_"
            "h07_s000_d050_klt_frontend/features.bag",
            ROOT
            / "artifacts/frontend_persistence_churn_guard_v3/shadow_root/logs/"
            "aqualoc_real_vins/external_hybrid_xfeat_every2_pcgv3_"
            "h07_s000_d050/frontend_metrics.csv",
        ),
    ]
    return cases + development


def numeric(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in (None, "") else 0.0


def evaluate_gate(
    frames: list[dict[str, float | int | bool]], config: GateConfig
) -> dict[str, int | float | str]:
    rescue = False
    enter_count = 0
    exit_count = 0
    rescue_age = 0
    rescue_episodes = 0
    active_frames = 0
    candidate_active_frames = 0
    candidate_active_observations = 0
    first_candidate_frame: int | None = None
    last_candidate_frame: int | None = None

    for frame in frames:
        enabled = not bool(frame["reset"])
        if config.enable_after_frame is not None:
            enabled = enabled and int(frame["frame_index"]) > config.enable_after_frame
        if config.enable_after_sec is not None:
            enabled = enabled and float(frame["rel_sec"]) >= config.enable_after_sec
        enter_bad = (
            float(frame["overlap_ratio"]) < config.enter_overlap_ratio
            and float(frame["mature_ratio"]) < config.enter_mature_ratio
        )
        exit_good = (
            float(frame["overlap_ratio"]) >= config.exit_overlap_ratio
            and float(frame["mature_ratio"]) >= config.exit_mature_ratio
        )
        if not rescue:
            enter_count = enter_count + 1 if enabled and enter_bad else 0
            if enter_count >= config.enter_frames:
                rescue = True
                rescue_episodes += 1
                rescue_age = 0
                exit_count = 0
        else:
            rescue_age += 1
            exit_count = exit_count + 1 if exit_good else 0
            if rescue_age >= config.min_rescue_frames and exit_count >= config.exit_frames:
                rescue = False
                enter_count = 0
                exit_count = 0

        if not rescue:
            continue
        active_frames += 1
        candidate_count = int(frame["candidate_count"])
        if candidate_count <= 0:
            continue
        candidate_active_frames += 1
        candidate_active_observations += candidate_count
        frame_index = int(frame["frame_index"])
        if first_candidate_frame is None:
            first_candidate_frame = frame_index
        last_candidate_frame = frame_index

    return {
        f"{config.name}_rescue_episodes": rescue_episodes,
        f"{config.name}_active_frames": active_frames,
        f"{config.name}_candidate_active_frames": candidate_active_frames,
        f"{config.name}_candidate_active_observations": candidate_active_observations,
        f"{config.name}_first_candidate_frame": (
            "" if first_candidate_frame is None else first_candidate_frame
        ),
        f"{config.name}_last_candidate_frame": (
            "" if last_candidate_frame is None else last_candidate_frame
        ),
    }


def evaluate_case(case: Case, configs: Iterable[GateConfig]) -> dict[str, object]:
    for path in (case.klt_bag, case.xfeat_metrics):
        if not path.is_file():
            raise FileNotFoundError(path)
    metrics = read_csv(case.xfeat_metrics)
    ager = TrackAger()
    frames: list[dict[str, float | int | bool]] = []
    first_stamp: float | None = None
    with rosbag.Bag(str(case.klt_bag), "r") as bag:
        messages = bag.read_messages(topics=["/feature_tracker/feature"])
        for frame_index, ((_, message, _), metric) in enumerate(zip(messages, metrics)):
            stamp = float(message.header.stamp.to_sec())
            if first_stamp is None:
                first_stamp = stamp
            ids = feature_ids(message)
            ages, overlap, reset = ager.update(ids)
            denominator = max(1, len(ids))
            frames.append(
                {
                    "frame_index": frame_index,
                    "rel_sec": stamp - first_stamp,
                    "reset": reset,
                    "overlap_ratio": overlap / denominator,
                    "mature_ratio": sum(age >= 4 for age in ages.values())
                    / denominator,
                    "candidate_count": int(numeric(metric, "pre_gate_sidecar_basic_ok")),
                }
            )
    if len(frames) != len(metrics):
        raise ValueError(
            f"frame/metrics mismatch for {case.window}: {len(frames)} != {len(metrics)}"
        )
    output: dict[str, object] = {
        "window": case.window,
        "cohort": case.cohort,
        "known_outcome": case.known_outcome,
        "feature_frames": len(frames),
        "candidate_frames": sum(int(frame["candidate_count"]) > 0 for frame in frames),
        "candidate_observations": sum(int(frame["candidate_count"]) for frame in frames),
        "current_v3_exported_xfeat_observations": int(
            sum(numeric(row, "exported_xfeat_features") for row in metrics)
        ),
        "klt_bag": str(case.klt_bag),
        "xfeat_metrics": str(case.xfeat_metrics),
    }
    for config in configs:
        output.update(evaluate_gate(frames, config))
    return output


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "papers/external_klt_dynamic_gate_quick_probe_v1/opportunity_scan.csv",
    )
    args = parser.parse_args()
    configs = (
        GateConfig("early5", enable_after_frame=4, enable_after_sec=None),
        GateConfig("faithful30s", enable_after_frame=None, enable_after_sec=30.0),
    )
    rows = [evaluate_case(case, configs) for case in discover_cases()]
    write_csv(args.output, rows)
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
