#!/usr/bin/env python3
"""Audit preregistered churn-guard v3 bags against frozen KLT/v1 inputs."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np

from analyze_persistence_singlechain_frontend_v2 import CASES, load


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNTIME = ROOT / "artifacts/frontend_persistence_churn_guard_v3"
PAPER = ROOT / "papers/frontend_persistence_churn_guard_v3"
TAG = "pcgv3"
EXPECTED_SOURCE = {
    "a06_s000_d045": "klt",
    "a09_6000_6800": "v1",
    "a06_s045_d045": "v1",
    "h07_s000_d050": "klt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, str(default)) or default))
    except ValueError:
        return default


def real(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "nan") or "nan")
    except ValueError:
        return float("nan")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    validation: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    victims: list[dict[str, object]] = []
    for case in CASES:
        run_dir = RUNTIME / "shadow_root/logs" / case.family / (
            f"external_hybrid_xfeat_every2_{TAG}_{case.window}"
        )
        bag = run_dir / "features.bag"
        metrics_path = run_dir / "frontend_metrics.csv"
        for path in (bag, metrics_path, case.klt_bag, case.v1_bag):
            if not path.is_file():
                raise FileNotFoundError(path)
        candidate = load(bag)
        klt = load(case.klt_bag)
        with metrics_path.open(newline="", encoding="utf-8") as stream:
            metrics = list(csv.DictReader(stream))
        expected_path = case.klt_bag if EXPECTED_SOURCE[case.window] == "klt" else case.v1_bag
        candidate_hash = sha256(bag)
        expected_hash = sha256(expected_path)
        exact_expected = candidate_hash == expected_hash
        exact_klt = candidate_hash == sha256(case.klt_bag)
        exact_v1 = candidate_hash == sha256(case.v1_bag)

        learned_count = 0
        learned_after_horizon = 0
        max_features = 0
        missing_sources: list[int] = []
        for frame, (baseline, output) in enumerate(zip(klt, candidate)):
            max_features = max(max_features, len(output["ids"]))
            learned_count += int(np.count_nonzero(output["learned"]))
            if frame > 4:
                learned_after_horizon += int(np.count_nonzero(output["learned"]))
            output_classical = {
                int(value) for value in output["ids"][~output["learned"]]
            }
            for idx, track_id in enumerate(baseline["ids"]):
                if int(track_id) not in output_classical:
                    source = int(baseline["sources"][idx])
                    missing_sources.append(source)
                    victims.append(
                        {
                            "window": case.window,
                            "selected_feature_index": frame,
                            "track_id": int(track_id),
                            "source_code_at_birth": source,
                            "p_u": float(baseline["u"][idx]),
                            "p_v": float(baseline["v"][idx]),
                        }
                    )

        decided = [
            row for row in metrics
            if integer(row, "final_mirror_persistence_churn_guard_decision", -1) >= 0
        ]
        decision_values = {
            integer(row, "final_mirror_persistence_churn_guard_decision", -1)
            for row in decided
        }
        decision_frame_values = {
            integer(row, "final_mirror_persistence_churn_guard_decision_frame", -1)
            for row in decided
        }
        first_decision = decided[0] if decided else {}
        decision = integer(first_decision, "final_mirror_persistence_churn_guard_decision", -1)
        decision_frame = integer(
            first_decision,
            "final_mirror_persistence_churn_guard_decision_frame",
            -1,
        )
        births = integer(first_decision, "final_mirror_persistence_churn_guard_gftt_births")
        denominator = integer(
            first_decision,
            "final_mirror_persistence_churn_guard_denominator",
        )
        ratio = real(first_decision, "final_mirror_persistence_churn_guard_ratio")
        expected_decision = {
            "a06_s000_d045": 0,
            "a09_6000_6800": 1,
            "a06_s045_d045": 1,
            "h07_s000_d050": -1,
        }[case.window]
        expected_decision_ok = decision == expected_decision
        if expected_decision < 0:
            expected_decision_ok = not decided
        guard_active_rows = sum(
            integer(row, "final_mirror_persistence_churn_guard_active")
            for row in metrics
        )
        timestamps_equal = (
            len(candidate) == len(klt)
            and [row["stamp"] for row in candidate] == [row["stamp"] for row in klt]
        )
        valid = bool(
            len(candidate) == case.frames
            and len(klt) == case.frames
            and timestamps_equal
            and max_features <= 350
            and learned_after_horizon == 0
            and all(source == 2 for source in missing_sources)
            and exact_expected
            and expected_decision_ok
            and guard_active_rows == case.frames
            and len(decision_values) <= 1
            and len(decision_frame_values) <= 1
        )
        decisions.append(
            {
                "window": case.window,
                "latched_decision": "ARM_V1" if decision == 1 else (
                    "CLOSE_TO_KLT" if decision == 0 else "NO_ELIGIBLE_EVENT"
                ),
                "selected_feature_index": decision_frame,
                "gftt_births": births,
                "denominator": denominator,
                "gftt_birth_reserve_ratio": ratio,
                "threshold": 0.10,
                "expected_source": EXPECTED_SOURCE[case.window],
                "byte_identical_expected": exact_expected,
            }
        )
        validation.append(
            {
                "window": case.window,
                "status": "PASS" if valid else "FAIL",
                "feature_frames": len(candidate),
                "expected_frames": case.frames,
                "timestamps_equal_klt": timestamps_equal,
                "max_features": max_features,
                "published_xfeat_observations": learned_count,
                "learned_after_frame_4": learned_after_horizon,
                "all_victims_gftt": all(source == 2 for source in missing_sources),
                "expected_source": EXPECTED_SOURCE[case.window],
                "byte_identical_expected": exact_expected,
                "byte_identical_klt": exact_klt,
                "byte_identical_v1": exact_v1,
                "feature_bag_sha256": candidate_hash,
                "expected_bag_sha256": expected_hash,
            }
        )
    PAPER.mkdir(parents=True, exist_ok=True)
    write_csv(PAPER / "frontend_validation.csv", validation)
    write_csv(PAPER / "churn_guard_decisions.csv", decisions)
    write_csv(PAPER / "replacement_victims.csv", victims)
    return 0 if all(row["status"] == "PASS" for row in validation) else 1


if __name__ == "__main__":
    raise SystemExit(main())
