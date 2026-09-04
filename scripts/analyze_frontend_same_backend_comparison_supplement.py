#!/usr/bin/env python3
"""Audit stage-2 feature bags and update the preregistered runability ledger."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import sys

import rosbag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_comparison_supplement as runner


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER_ROOT = ROOT / "papers/frontend_same_backend_comparison_supplement"
FIELDNAMES = [
    "window_id", "role", "arm", "method", "candidate_status",
    "scheduled_feature_epochs", "nonempty_feature_epochs", "frontend_coverage",
    "frontend_runable", "feature_bag_path", "feature_bag_sha256",
    "all_three_bags_byte_identical", "exclusion_status",
    "repeat1_init", "repeat1_pose_count", "repeat1_span_s", "repeat1_coverage",
    "repeat2_init", "repeat2_pose_count", "repeat2_span_s", "repeat2_coverage",
    "repeat3_init", "repeat3_pose_count", "repeat3_span_s", "repeat3_coverage",
    "arm_window_pass", "failure_class", "notes",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_bag(path: Path, scheduled: int) -> dict[str, object]:
    counts: dict[str, int] = {}
    feature_messages = 0
    nonempty = 0
    maximum = 0
    unique_feature_stamps: set[tuple[int, int]] = set()
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _ in bag.read_messages():
            counts[topic] = counts.get(topic, 0) + 1
            if topic == "/feature_tracker/feature":
                feature_messages += 1
                count = len(message.points)
                nonempty += int(count > 0)
                maximum = max(maximum, count)
                stamp = message.header.stamp
                unique_feature_stamps.add((int(stamp.secs), int(stamp.nsecs)))
    coverage = nonempty / scheduled if scheduled else 0.0
    pass_flag = (
        coverage >= 0.70
        and feature_messages == scheduled
        and len(unique_feature_stamps) == feature_messages
        and maximum <= 350
        and counts.get("/rtimulib_node/imu", counts.get("/imu/imu", 0)) > 0
        and counts.get("/aqualoc/colmap_gt", counts.get("/afrl/colmap_gt", 0)) > 0
    )
    return {
        "feature_messages": feature_messages,
        "nonempty": nonempty,
        "maximum": maximum,
        "coverage": coverage,
        "counts": counts,
        "pass": pass_flag,
        "sha256": sha256(path),
    }


def main() -> int:
    runner.verify_frozen()
    candidates = list(csv.DictReader((PAPER_ROOT / "candidate_windows.csv").open(newline="", encoding="utf-8")))
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        window_id = candidate["window_id"]
        eligible = candidate["eligibility"] == "ELIGIBLE"
        arm_audits: dict[str, dict[str, object]] = {}
        paths: dict[str, Path] = {}
        if eligible:
            scheduled = int(candidate["image_count_input"]) // 2
            for arm in runner.ARMS:
                _, _, run_dir = runner.command_for(candidate, arm)
                path = run_dir / "features.bag"
                paths[arm] = path
                receipt = run_dir / "supplement_frontend_receipt.json"
                if path.is_file() and receipt.is_file():
                    arm_audits[arm] = audit_bag(path, scheduled)

        all_present = eligible and len(arm_audits) == len(runner.ARMS)
        all_frontend_pass = all_present and all(bool(value["pass"]) for value in arm_audits.values())
        hashes = [str(value["sha256"]) for value in arm_audits.values()]
        all_identical = all_present and len(set(hashes)) == 1
        identity_groups: list[str] = []
        if all_present:
            arm_names = list(runner.ARMS)
            for i, left in enumerate(arm_names):
                for right in arm_names[i + 1:]:
                    if arm_audits[left]["sha256"] == arm_audits[right]["sha256"]:
                        identity_groups.append(f"{left}={right}")

        for arm, (method, _) in runner.ARMS.items():
            row = {field: "" for field in FIELDNAMES}
            row.update(
                {
                    "window_id": window_id,
                    "role": candidate["role"],
                    "arm": arm,
                    "method": method,
                    "arm_window_pass": "NOT_RUN",
                }
            )
            if not eligible:
                row.update(
                    {
                        "candidate_status": "NOT_ELIGIBLE_METADATA",
                        "exclusion_status": candidate["eligibility"],
                        "failure_class": "metadata_proxy_support",
                        "notes": candidate["eligibility_reason"],
                    }
                )
            elif arm not in arm_audits:
                row.update(
                    {
                        "candidate_status": "FRONTEND_INCOMPLETE",
                        "scheduled_feature_epochs": str(int(candidate["image_count_input"]) // 2),
                        "frontend_runable": "FAIL",
                        "exclusion_status": "NOT_EVALUATED",
                        "failure_class": "configuration_or_infrastructure",
                        "notes": f"missing feature bag or receipt: {paths.get(arm, '')}",
                    }
                )
            else:
                audit = arm_audits[arm]
                row.update(
                    {
                        "candidate_status": "FRONTEND_PASS" if all_frontend_pass else "FRONTEND_FAIL",
                        "scheduled_feature_epochs": str(int(candidate["image_count_input"]) // 2),
                        "nonempty_feature_epochs": str(audit["nonempty"]),
                        "frontend_coverage": f"{float(audit['coverage']):.9f}",
                        "frontend_runable": "PASS" if audit["pass"] else "FAIL",
                        "feature_bag_path": str(paths[arm].resolve()),
                        "feature_bag_sha256": str(audit["sha256"]),
                        "all_three_bags_byte_identical": "true" if all_identical else "false",
                        "exclusion_status": "EXCLUDED_IDENTICAL_FEATURE_BAGS" if all_identical else "INCLUDED",
                        "failure_class": "" if audit["pass"] else "frontend_coverage_or_integrity",
                        "notes": ";".join(
                            [
                                f"feature_messages={audit['feature_messages']}",
                                f"max_features={audit['maximum']}",
                                f"topic_counts={audit['counts']}",
                                f"pairwise_byte_identity={'|'.join(identity_groups) if identity_groups else 'none'}",
                            ]
                        ),
                    }
                )
            rows.append(row)

    output = PAPER_ROOT / "runability.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {output}: rows={len(rows)}")
    print(
        f"frontend-complete windows={sum(1 for c in candidates if any(r['window_id']==c['window_id'] and r['candidate_status']=='FRONTEND_PASS' for r in rows))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
