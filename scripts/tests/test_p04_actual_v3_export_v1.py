from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import genpy
import rosbag
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, Imu, PointCloud

from scripts.audit_p04_actual_v3_export_v1 import AuditViolation, audit_attempt


def _feature(stamp: float) -> PointCloud:
    message = PointCloud()
    message.header.stamp = genpy.Time.from_sec(stamp)
    message.points = [Point32(0.1, 0.2, 1.0)]
    values = {
        "id": [1.0],
        "source_code": [1.0],
        "is_learned": [0.0],
        "quality": [0.9],
        "sigma": [1.0540925],
    }
    message.channels = [
        ChannelFloat32(name=name, values=channel) for name, channel in values.items()
    ]
    return message


def _make_run(path: Path, frames: int = 450) -> None:
    path.mkdir()
    with rosbag.Bag(str(path / "features.bag"), "w") as bag:
        for index in range(frames):
            stamp = genpy.Time.from_sec(1.0 + index * 0.1)
            bag.write("/imu", Imu(), stamp)
            bag.write("/feature_tracker/feature", _feature(stamp.to_sec()), stamp)
    fields = (
        "learned_candidate_count",
        "learned_confirmed_count",
        "exported_xfeat_features",
    )
    with (path / "frontend_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for _ in range(frames):
            writer.writerow(
                {
                    "learned_candidate_count": 1,
                    "learned_confirmed_count": 1,
                    "exported_xfeat_features": 0,
                }
            )


def _summary(probe: Path, final: Path) -> str:
    return "\n".join(
        (
            "dataset_family=aqualoc_archaeo",
            "profile=klt_safe_fallback",
            "seedchain_profile=lineage_early_seed_scan",
            "final_effective_seedchain_profile=klt",
            "probe_xfeat_total=0",
            "probe_xfeat_frames=0",
            "oldcontract_signature=0",
            "oldcontract_fail_reasons=min_strength",
            f"probe_run={probe}",
            f"final_run={final}",
        )
    ) + "\n"


class ActualV3ExportAuditTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        probe = root / "probe"
        final = root / "final"
        _make_run(probe)
        _make_run(final)
        (final / "arbitration_summary.txt").write_text(
            _summary(probe, final), encoding="utf-8"
        )
        guard = root / "guard.json"
        guard.write_text(
            json.dumps(
                {
                    "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
                    "contract_pass": True,
                    "action": "ALLOW_LEARNED",
                    "contract_hash": "fixture",
                    "reasons": [],
                }
            ),
            encoding="utf-8",
        )
        return probe, final, guard

    def test_zero_action_byte_identity_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe, final, guard = self._fixture(Path(directory))
            result = audit_attempt(
                probe_run=probe, final_run=final, guard_decision=guard
            )
            self.assertTrue(result["contract_pass"])
            self.assertEqual(
                result["decision"], "PASS_ACTUAL_V3_ZERO_ACTION_KLT_FALLBACK"
            )

    def test_changed_final_bag_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe, final, guard = self._fixture(Path(directory))
            with rosbag.Bag(str(final / "features.bag"), "a") as bag:
                stamp = genpy.Time.from_sec(100.0)
                bag.write("/imu", Imu(), stamp)
            with self.assertRaisesRegex(AuditViolation, "not byte-identical"):
                audit_attempt(probe_run=probe, final_run=final, guard_decision=guard)

    def test_failed_guard_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe, final, guard = self._fixture(Path(directory))
            value = json.loads(guard.read_text(encoding="utf-8"))
            value["contract_pass"] = False
            guard.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(AuditViolation, "guard did not pass"):
                audit_attempt(probe_run=probe, final_run=final, guard_decision=guard)


if __name__ == "__main__":
    unittest.main()
