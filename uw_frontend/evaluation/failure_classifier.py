"""Frozen replay-failure classification for the ISJ experiment program.

The classifier is deliberately independent of ROS and VINS execution.  It
turns process state, trajectory samples, queue accounting, and a VINS log into
one replay decision, then applies the preregistered three-replay reducer at the
``window x arm`` level.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml


@dataclass(frozen=True)
class FailureThresholds:
    initialization_deadline_s: float = 10.0
    output_segment_max_gap_s: float = 1.0
    hard_failure_coverage_below: float = 0.50
    sustained_queue_drop_rate_above: float = 0.01
    sustained_backlog_growth_s_at_least: float = 5.0
    planned_algorithmic_replays: int = 3
    minimum_evaluable_replays: int = 2


@dataclass(frozen=True)
class ReplayEvidence:
    process_exit_code: int
    timed_out: bool
    window_start_s: float
    window_end_s: float
    trajectory_timestamps_s: Sequence[float]
    trajectory_rows_finite: Sequence[bool] | None = None
    log_text: str = ""
    input_message_count: int | None = None
    processed_message_count: int | None = None
    observable_backlog_growth_s: float = 0.0
    infrastructure_evidence: Sequence[str] = ()


@dataclass(frozen=True)
class ReplayDecision:
    valid_pose_count: int
    first_valid_pose_offset_s: float | None
    full_window_coverage: float
    process_crash: bool
    timed_out: bool
    empty_trajectory: bool
    nonfinite_trajectory: bool
    nonmonotonic_trajectory: bool
    initialization_failure: bool
    replay_hard_failure: bool
    replay_evaluable: bool
    algorithm_hard_failure: bool
    infrastructure_failure: bool
    solver_risk: bool
    solver_risk_signatures: tuple[str, ...]
    queue_drop_rate: float | None
    sustained_queue_drop: bool
    hard_failure_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WindowArmDecision:
    planned_replays: int
    evaluable_replays: int
    window_arm_hard_failure: bool
    any_repeat_hard_failure: bool
    window_arm_solver_risk: bool
    median_metrics: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FailureTaxonomy:
    def __init__(
        self,
        thresholds: FailureThresholds,
        solver_risk_patterns: Mapping[str, Sequence[str]],
    ) -> None:
        self.thresholds = thresholds
        self.solver_risk_patterns = {
            str(name): tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns)
            for name, patterns in solver_risk_patterns.items()
        }

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FailureTaxonomy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        threshold_data = data.get("thresholds", {})
        thresholds = FailureThresholds(
            initialization_deadline_s=float(threshold_data["initialization_deadline_s"]),
            output_segment_max_gap_s=float(threshold_data["output_segment_max_gap_s"]),
            hard_failure_coverage_below=float(threshold_data["hard_failure_coverage_below"]),
            sustained_queue_drop_rate_above=float(threshold_data["sustained_queue_drop_rate_above"]),
            sustained_backlog_growth_s_at_least=float(
                threshold_data["sustained_backlog_growth_s_at_least"]
            ),
            planned_algorithmic_replays=int(threshold_data["planned_algorithmic_replays"]),
            minimum_evaluable_replays=int(threshold_data["minimum_evaluable_replays"]),
        )
        patterns = data.get("solver_risk_signatures", {})
        if not isinstance(patterns, dict) or not patterns:
            raise ValueError("solver_risk_signatures must be a non-empty mapping")
        return cls(thresholds, patterns)

    def classify(self, evidence: ReplayEvidence) -> ReplayDecision:
        start = float(evidence.window_start_s)
        end = float(evidence.window_end_s)
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("window_end_s must be finite and greater than window_start_s")

        timestamps = [float(value) for value in evidence.trajectory_timestamps_s]
        row_finite = (
            [bool(value) for value in evidence.trajectory_rows_finite]
            if evidence.trajectory_rows_finite is not None
            else [math.isfinite(value) for value in timestamps]
        )
        if len(row_finite) != len(timestamps):
            raise ValueError("trajectory_rows_finite must match trajectory_timestamps_s")

        nonfinite = any(
            (not finite) or (not math.isfinite(timestamp))
            for timestamp, finite in zip(timestamps, row_finite)
        )
        finite_times = [
            timestamp
            for timestamp, finite in zip(timestamps, row_finite)
            if finite and math.isfinite(timestamp) and start <= timestamp <= end
        ]
        nonmonotonic = any(right <= left for left, right in zip(finite_times, finite_times[1:]))
        valid_times = finite_times if not nonmonotonic else []
        empty = len(timestamps) == 0 or len(finite_times) == 0
        coverage = _segment_coverage(
            valid_times,
            start,
            end,
            max_gap_s=self.thresholds.output_segment_max_gap_s,
        )
        first_offset = valid_times[0] - start if valid_times else None
        initialization_failure = (
            first_offset is None
            or first_offset > self.thresholds.initialization_deadline_s
        )
        process_crash = int(evidence.process_exit_code) != 0
        infrastructure_failure = bool(evidence.infrastructure_evidence)

        hard_reasons: list[str] = []
        for condition, reason in (
            (process_crash, "NONZERO_EXIT"),
            (bool(evidence.timed_out), "TIMEOUT"),
            (empty, "EMPTY_TRAJECTORY"),
            (nonfinite, "NONFINITE_TRAJECTORY"),
            (nonmonotonic, "NONMONOTONIC_TRAJECTORY"),
            (initialization_failure, "INITIALIZATION_FAILURE"),
            (coverage < self.thresholds.hard_failure_coverage_below, "COVERAGE_BELOW_0P50"),
        ):
            if condition and reason not in hard_reasons:
                hard_reasons.append(reason)
        replay_hard_failure = bool(hard_reasons)

        signature_names = tuple(
            name
            for name, patterns in sorted(self.solver_risk_patterns.items())
            if any(pattern.search(evidence.log_text or "") for pattern in patterns)
        )
        queue_drop_rate = _queue_drop_rate(
            evidence.input_message_count,
            evidence.processed_message_count,
        )
        sustained_queue_drop = (
            queue_drop_rate is not None
            and queue_drop_rate > self.thresholds.sustained_queue_drop_rate_above
        ) or (
            float(evidence.observable_backlog_growth_s)
            >= self.thresholds.sustained_backlog_growth_s_at_least
        )

        return ReplayDecision(
            valid_pose_count=len(valid_times),
            first_valid_pose_offset_s=first_offset,
            full_window_coverage=coverage,
            process_crash=process_crash,
            timed_out=bool(evidence.timed_out),
            empty_trajectory=empty,
            nonfinite_trajectory=nonfinite,
            nonmonotonic_trajectory=nonmonotonic,
            initialization_failure=initialization_failure,
            replay_hard_failure=replay_hard_failure,
            replay_evaluable=not replay_hard_failure,
            algorithm_hard_failure=replay_hard_failure and not infrastructure_failure,
            infrastructure_failure=infrastructure_failure,
            solver_risk=bool(signature_names),
            solver_risk_signatures=signature_names,
            queue_drop_rate=queue_drop_rate,
            sustained_queue_drop=sustained_queue_drop,
            hard_failure_reasons=tuple(hard_reasons),
        )

    def reduce_window_arm(
        self,
        decisions: Sequence[ReplayDecision],
        metrics: Sequence[Mapping[str, float]] | None = None,
    ) -> WindowArmDecision:
        planned = self.thresholds.planned_algorithmic_replays
        if len(decisions) != planned:
            raise ValueError(f"expected exactly {planned} algorithmic replays")
        if any(decision.infrastructure_failure for decision in decisions):
            raise ValueError(
                "infrastructure attempts must be replaced before the three algorithmic replays are reduced"
            )
        if metrics is not None and len(metrics) != planned:
            raise ValueError("metrics must match decisions")

        evaluable_indices = [
            index for index, decision in enumerate(decisions) if decision.replay_evaluable
        ]
        median_metrics: dict[str, float] = {}
        if metrics is not None and evaluable_indices:
            names = sorted(set.intersection(*(set(metrics[index]) for index in evaluable_indices)))
            for name in names:
                values = [float(metrics[index][name]) for index in evaluable_indices]
                finite = [value for value in values if math.isfinite(value)]
                if len(finite) == len(values):
                    median_metrics[name] = float(statistics.median(finite))

        evaluable_count = len(evaluable_indices)
        return WindowArmDecision(
            planned_replays=planned,
            evaluable_replays=evaluable_count,
            window_arm_hard_failure=(
                evaluable_count < self.thresholds.minimum_evaluable_replays
            ),
            any_repeat_hard_failure=any(
                decision.replay_hard_failure for decision in decisions
            ),
            window_arm_solver_risk=any(decision.solver_risk for decision in decisions),
            median_metrics=median_metrics,
        )


def read_trajectory_rows(path: str | Path) -> tuple[list[float], list[bool]]:
    """Read whitespace/comma trajectory rows; first field is timestamp."""

    timestamps: list[float] = []
    finite_rows: list[bool] = []
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.replace(",", " ").split()
            try:
                values = [float(field) for field in fields]
            except ValueError:
                timestamps.append(float("nan"))
                finite_rows.append(False)
                continue
            timestamps.append(values[0] if values else float("nan"))
            finite_rows.append(bool(values) and all(math.isfinite(value) for value in values))
    return timestamps, finite_rows


def _segment_coverage(
    timestamps: Sequence[float],
    window_start_s: float,
    window_end_s: float,
    *,
    max_gap_s: float,
) -> float:
    if len(timestamps) < 2:
        return 0.0
    duration = window_end_s - window_start_s
    covered = sum(
        right - left
        for left, right in zip(timestamps, timestamps[1:])
        if 0.0 < right - left <= max_gap_s
    )
    return min(1.0, max(0.0, covered / duration))


def _queue_drop_rate(input_count: int | None, processed_count: int | None) -> float | None:
    if input_count is None or processed_count is None:
        return None
    if int(input_count) < 0 or int(processed_count) < 0:
        raise ValueError("message counts must be non-negative")
    if int(processed_count) > int(input_count):
        raise ValueError("processed_message_count cannot exceed input_message_count")
    if int(input_count) == 0:
        return 0.0 if int(processed_count) == 0 else None
    return (int(input_count) - int(processed_count)) / float(input_count)

