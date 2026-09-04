from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import genpy
import rosbag
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud

from scripts.audit_p07_mp_frontend_export_v2 import (
    AuditViolation,
    allocation_row,
    learned_lineage_stats,
    parse_arbitration_summary,
    queue_row,
    validate_guard,
)
from scripts.build_p07_preoutcome_governance_v1 import M_ARM, P_ARM


FEATURE_TOPIC = "/feature_tracker/feature"


def feature_message(observations: list[tuple[int, int, int]], stamp: float) -> PointCloud:
    message = PointCloud()
    message.header.stamp = genpy.Time.from_sec(stamp)
    message.points = [Point32(float(index), 0.0, 1.0) for index, _ in enumerate(observations)]
    values = {
        "id": [float(item[0]) for item in observations],
        "source_code": [float(item[1]) for item in observations],
        "is_learned": [float(item[2]) for item in observations],
    }
    message.channels = [
        ChannelFloat32(name=name, values=channel_values)
        for name, channel_values in values.items()
    ]
    return message


def write_lineage_bag(path: Path, frames: list[list[tuple[int, int, int]]]) -> None:
    with rosbag.Bag(str(path), "w") as bag:
        for index, observations in enumerate(frames):
            stamp = genpy.Time.from_sec(float(index + 1))
            bag.write(FEATURE_TOPIC, feature_message(observations, float(index + 1)), stamp)


class P07MPFrontendExportV2Tests(unittest.TestCase):
    def test_queue_indices_are_exact_frozen_a02_m_then_p(self) -> None:
        m_row = queue_row(2)
        p_row = queue_row(3)
        self.assertEqual(m_row["arm"], M_ARM)
        self.assertEqual(p_row["arm"], P_ARM)
        self.assertEqual(m_row["window_id"], "aqualoc_archaeology:A02:0005")
        self.assertEqual(p_row["window_id"], m_row["window_id"])
        self.assertEqual(
            m_row["command_sha256"],
            "220c562dae36831d6cedd8272d7ad61c1dcb58928acdee0be453272780a5c1cc",
        )
        self.assertEqual(
            p_row["command_sha256"],
            "130dd140bd3c56ae59cb89beb315e7d74ba29544c09a937624801ff9ea03c034",
        )
        self.assertTrue(allocation_row(2)["run_id"].endswith("20260806T084500Z"))
        self.assertTrue(allocation_row(3)["run_id"].endswith("20260806T084500Z"))

    def test_summary_allows_duplicate_diagnostics_but_not_reserved_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arbitration_summary.txt"
            path.write_text(
                "dataset_family=aqualoc_archaeo\n"
                "profile=klt_safe_fallback\n"
                "probe_run=/tmp/probe\n"
                "final_run=/tmp/final\n"
                "feature_bag=/tmp/final/features.bag\n"
                "sf=first\n"
                "sf=second\n",
                encoding="utf-8",
            )
            summary, duplicates = parse_arbitration_summary(path)
            self.assertEqual(summary["profile"], "klt_safe_fallback")
            self.assertEqual(duplicates, {"sf": ["first", "second"]})
            path.write_text(path.read_text() + "profile=mirror_densecap\n", encoding="utf-8")
            with self.assertRaisesRegex(AuditViolation, "exactly one profile"):
                parse_arbitration_summary(path)

    def test_lineage_count_is_distinct_and_includes_klt_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "p.bag"
            write_lineage_bag(
                path,
                [
                    [(1, 1, 0), (100, 20, 1), (101, 20, 1)],
                    [(1, 1, 0), (100, 1, 0), (101, 20, 1)],
                ],
            )
            result = learned_lineage_stats(path)
            self.assertEqual(result["accepted_learned_born_lineage_count"], 2)
            self.assertEqual(result["learned_born_feature_ids"], [100, 101])
            self.assertEqual(result["learned_born_observations"], 4)

    def test_lineage_scan_fails_closed_on_late_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late.bag"
            write_lineage_bag(path, [[(100, 1, 0)], [(100, 20, 1)]])
            with self.assertRaisesRegex(AuditViolation, "learned provenance appears after"):
                learned_lineage_stats(path)

    def test_guard_validation_rejects_fallback_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
                        "action": "FALLBACK_CLASSICAL",
                        "contract_hash": "wrong",
                        "contract_pass": False,
                        "counts_as_proposed_result": False,
                        "result_label": "KLT_BACKEND_CONTRACT_FALLBACK",
                        "reasons": ["drift"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AuditViolation, "exact frozen PASS"):
                validate_guard(path, P_ARM)


if __name__ == "__main__":
    unittest.main()
