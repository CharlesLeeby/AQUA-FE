#!/usr/bin/env python3

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from scripts.run_p06_ros_screening import adapter_contract, run_sequence


class P06RosScreeningTest(unittest.TestCase):
    def test_ntnu_contract_disables_selection_and_vins(self) -> None:
        env, command, metrics, bags = adapter_contract(
            "ntnu",
            "fjord_6",
            "638",
            {"raw_input_path": "raw.bag"},
            Path("/tmp/p06/fjord_6"),
        )
        self.assertEqual(env["RUN_VINS"], "0")
        self.assertEqual(env["MEASUREMENT_SELECTION"], "0")
        self.assertEqual(command[-2:], ["klt", "1"])
        self.assertEqual(metrics.name, "frontend_metrics.csv")
        self.assertEqual([path.name for path in bags], ["features.bag"])

    def test_cemetery_camera_identity_is_frozen_to_left(self) -> None:
        env, command, _, bags = adapter_contract(
            "afrl",
            "cemetery",
            "434.82",
            {
                "raw_input_path": "raw.bag",
                "reference_path": "gt.txt",
                "calibration_paths": "camchain.yaml;imu.yaml",
            },
            Path("/tmp/p06/cemetery"),
        )
        self.assertEqual(env["CAMERA_KEY"], "cam0")
        self.assertEqual(env["SRC_IMAGE_TOPIC"], "/cam_fl/image_raw/compressed")
        self.assertEqual(env["AFRL_ADAPTER"], "isj-p06-afrl-direct-compressed-v1")
        self.assertIn("scripts/run_p06_afrl_direct_screening.py", command)
        self.assertEqual([path.name for path in bags], ["features.bag"])

    def test_afrl_replacement_uses_versioned_attempt_and_records_orchestrator(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as output, tempfile.TemporaryDirectory() as work:
            result = run_sequence(
                "cave_gennie",
                Path(output),
                Path(work),
                force=False,
                keep_work_bags=False,
                dry_run=True,
                attempt_id="attempt02",
            )
        self.assertEqual(result["attempt_id"], "attempt02")
        self.assertTrue(str(result["run_dir"]).endswith("/attempt02"))
        code_paths = {record["path"] for record in result["code"]}
        self.assertIn("scripts/run_p06_ros_screening.py", code_paths)
        self.assertIn("scripts/run_p06_afrl_direct_screening.py", code_paths)

    def test_attempt_id_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as work:
            with self.assertRaises(ValueError):
                run_sequence(
                    "cave_gennie",
                    Path(output),
                    Path(work),
                    force=False,
                    keep_work_bags=False,
                    dry_run=True,
                    attempt_id="../attempt02",
                )


if __name__ == "__main__":
    unittest.main()
