#!/usr/bin/env python3
"""Build the confirmatory-v3 frontend ledger without changing experiment state."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

import rosbag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_confirmatory_v3 as runner


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_same_backend_confirmatory_v3"

FIELDS = [
    "order",
    "window_id",
    "run_slug",
    "family",
    "sequence",
    "stratum",
    "arm",
    "method",
    "cell_status",
    "expected_feature_messages",
    "feature_messages",
    "frontend_coverage",
    "max_features",
    "frontend_integrity_pass",
    "image_messages",
    "imu_messages",
    "proxy_messages",
    "exported_xfeat_observations",
    "exported_splg_observations",
    "persistence_replaced_gftt_observations",
    "dropped_classical_for_cap_observations",
    "kept_sidecar_observations",
    "churn_guard_decision",
    "churn_guard_decision_frame",
    "feature_bag_path",
    "feature_bag_sha256",
    "frontend_metrics_path",
    "frontend_metrics_sha256",
    "prepared_input_path",
    "prepared_input_sha256",
    "all_three_bags_byte_identical",
    "pairwise_byte_identity",
    "failure_class",
    "notes",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def numeric_total(rows: list[dict[str, str]], field: str) -> int:
    return int(sum(float(row.get(field) or 0) for row in rows))


def audit_feature_bag(path: Path) -> dict[str, object]:
    topic_counts: dict[str, int] = {}
    feature_stamps: list[int] = []
    nonempty = 0
    maximum = 0
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages():
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if topic == "/feature_tracker/feature":
                feature_stamps.append(int(stamp.to_nsec()))
                points = len(message.points)
                nonempty += int(points > 0)
                maximum = max(maximum, points)
    return {
        "feature_messages": len(feature_stamps),
        "nonempty_feature_messages": nonempty,
        "max_features": maximum,
        "unique_feature_stamps": len(set(feature_stamps)),
        "strictly_increasing_feature_stamps": all(
            left < right for left, right in zip(feature_stamps, feature_stamps[1:])
        ),
        "first_feature_ns": feature_stamps[0] if feature_stamps else None,
        "last_feature_ns": feature_stamps[-1] if feature_stamps else None,
        "topic_counts": topic_counts,
    }


def metric_summary(path: Path) -> dict[str, object]:
    rows = read_csv(path)
    decisions = [
        row
        for row in rows
        if row.get("final_mirror_persistence_churn_guard_decision") not in (None, "")
    ]
    decision = decisions[-1] if decisions else {}
    return {
        "rows": len(rows),
        "exported_xfeat_observations": numeric_total(rows, "exported_xfeat_features"),
        "exported_splg_observations": numeric_total(rows, "exported_sp_lg_features"),
        "persistence_replaced_gftt_observations": numeric_total(
            rows, "final_mirror_persistence_replaced_gftt"
        ),
        "dropped_classical_for_cap_observations": numeric_total(
            rows, "final_mirror_dropped_classical_for_cap"
        ),
        "kept_sidecar_observations": numeric_total(
            rows, "final_mirror_kept_sidecars"
        ),
        "churn_guard_decision": decision.get(
            "final_mirror_persistence_churn_guard_decision", ""
        ),
        "churn_guard_decision_frame": decision.get(
            "final_mirror_persistence_churn_guard_decision_frame", ""
        ),
    }


def topic_count(counts: dict[str, int], alternatives: tuple[str, ...]) -> int:
    return sum(counts.get(topic, 0) for topic in alternatives)


def main() -> int:
    runner.verify_lock()
    runner.prepare_shadow()
    windows = runner.load_windows()
    arms = runner.load_arms()
    cells: dict[tuple[str, str], dict[str, object]] = {}

    for window in windows:
        for arm_id, arm in arms.items():
            _, _, run_dir, prepared = runner.command_for(window, arm)
            receipt_path = run_dir / "confirmatory_frontend_receipt.json"
            failed_path = run_dir / "failed_receipt.json"
            feature_bag = run_dir / "features.bag"
            metrics_path = run_dir / "frontend_metrics.csv"
            cell: dict[str, object] = {
                "status": "NOT_RUN",
                "run_dir": run_dir,
                "prepared": prepared,
            }
            if failed_path.is_file():
                cell.update(
                    {
                        "status": "FAILED",
                        "failure_class": "frontend_process_failure",
                        "notes": failed_path.read_text(encoding="utf-8").strip(),
                    }
                )
            elif receipt_path.is_file() and feature_bag.is_file() and metrics_path.is_file():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                bag = audit_feature_bag(feature_bag)
                metric = metric_summary(metrics_path)
                expected = int(receipt["expected_feature_messages"])
                coverage = bag["feature_messages"] / expected if expected else 0.0
                integrity = (
                    bag["feature_messages"] > 0
                    and coverage >= 0.70
                    and bag["feature_messages"] == bag["unique_feature_stamps"]
                    and bag["strictly_increasing_feature_stamps"]
                    and bag["max_features"] <= 350
                    and sha256(feature_bag) == receipt["feature_bag_sha256"]
                    and sha256(metrics_path) == receipt["frontend_metrics_sha256"]
                )
                cell.update(
                    {
                        "status": "PASS" if integrity else "FAIL_INTEGRITY",
                        "receipt": receipt,
                        "bag": bag,
                        "metric": metric,
                        "expected": expected,
                        "coverage": coverage,
                        "integrity": integrity,
                        "feature_bag_sha256": sha256(feature_bag),
                        "metrics_sha256": sha256(metrics_path),
                        "failure_class": "" if integrity else "frontend_integrity",
                        "notes": "",
                    }
                )
            elif run_dir.exists():
                cell.update(
                    {
                        "status": "RUNNING_OR_PARTIAL",
                        "failure_class": "incomplete_cell",
                        "notes": "run directory exists without a complete receipt",
                    }
                )
            cells[(window["run_slug"], arm_id)] = cell

    rows: list[dict[str, str]] = []
    for window in windows:
        window_cells = {
            arm_id: cells[(window["run_slug"], arm_id)] for arm_id in arms
        }
        completed_hashes = {
            arm_id: str(cell.get("feature_bag_sha256", ""))
            for arm_id, cell in window_cells.items()
            if cell["status"] in ("PASS", "FAIL_INTEGRITY")
        }
        all_three_complete = len(completed_hashes) == len(arms)
        all_identical = all_three_complete and len(set(completed_hashes.values())) == 1
        identity_pairs: list[str] = []
        arm_ids = list(arms)
        for index, left in enumerate(arm_ids):
            for right in arm_ids[index + 1 :]:
                if (
                    left in completed_hashes
                    and right in completed_hashes
                    and completed_hashes[left] == completed_hashes[right]
                ):
                    identity_pairs.append(f"{left}={right}")

        for arm_id, arm in arms.items():
            cell = window_cells[arm_id]
            receipt = cell.get("receipt", {})
            bag = cell.get("bag", {})
            metric = cell.get("metric", {})
            counts = bag.get("topic_counts", {})
            run_dir = Path(cell["run_dir"])
            prepared = Path(cell["prepared"])
            prepared_hash = receipt.get("prepared_input_sha256", "")
            if not prepared_hash and prepared.is_file():
                prepared_hash = sha256(prepared)
            row = {field: "" for field in FIELDS}
            row.update(
                {
                    "order": window["order"],
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "family": window["family"],
                    "sequence": window["sequence"],
                    "stratum": window["stratum"],
                    "arm": arm_id,
                    "method": arm["method"],
                    "cell_status": str(cell["status"]),
                    "expected_feature_messages": str(cell.get("expected", "")),
                    "feature_messages": str(bag.get("feature_messages", "")),
                    "frontend_coverage": (
                        f"{float(cell['coverage']):.9f}" if "coverage" in cell else ""
                    ),
                    "max_features": str(bag.get("max_features", "")),
                    "frontend_integrity_pass": (
                        str(bool(cell.get("integrity"))).lower()
                        if "integrity" in cell
                        else ""
                    ),
                    "image_messages": str(
                        topic_count(
                            counts,
                            (
                                "/aqualoc/image_raw",
                                "/camera/image_raw",
                                "/camera/left/image_raw",
                            ),
                        )
                    ) if counts else "",
                    "imu_messages": str(
                        topic_count(counts, ("/rtimulib_node/imu", "/imu/imu"))
                    ) if counts else "",
                    "proxy_messages": str(
                        topic_count(counts, ("/aqualoc/colmap_gt", "/afrl/colmap_gt"))
                    ) if counts else "",
                    "exported_xfeat_observations": str(
                        metric.get("exported_xfeat_observations", "")
                    ),
                    "exported_splg_observations": str(
                        metric.get("exported_splg_observations", "")
                    ),
                    "persistence_replaced_gftt_observations": str(
                        metric.get("persistence_replaced_gftt_observations", "")
                    ),
                    "dropped_classical_for_cap_observations": str(
                        metric.get("dropped_classical_for_cap_observations", "")
                    ),
                    "kept_sidecar_observations": str(
                        metric.get("kept_sidecar_observations", "")
                    ),
                    "churn_guard_decision": str(metric.get("churn_guard_decision", "")),
                    "churn_guard_decision_frame": str(
                        metric.get("churn_guard_decision_frame", "")
                    ),
                    "feature_bag_path": str(receipt.get("feature_bag", run_dir / "features.bag")),
                    "feature_bag_sha256": str(cell.get("feature_bag_sha256", "")),
                    "frontend_metrics_path": str(
                        receipt.get("frontend_metrics", run_dir / "frontend_metrics.csv")
                    ),
                    "frontend_metrics_sha256": str(cell.get("metrics_sha256", "")),
                    "prepared_input_path": str(prepared),
                    "prepared_input_sha256": str(prepared_hash),
                    "all_three_bags_byte_identical": (
                        str(all_identical).lower() if all_three_complete else ""
                    ),
                    "pairwise_byte_identity": "|".join(identity_pairs),
                    "failure_class": str(cell.get("failure_class", "")),
                    "notes": str(cell.get("notes", "")),
                }
            )
            rows.append(row)

    output = PAPER / "frontend_runability.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    status_counts: dict[str, int] = {}
    for cell in cells.values():
        status = str(cell["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"wrote {output}: rows={len(rows)} status={status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
