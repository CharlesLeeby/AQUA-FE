#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_p06_afrl_direct_screening import write_camera_config


class P06AfrlDirectScreeningTest(unittest.TestCase):
    def test_camera_config_preserves_full_resolution_intrinsics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "camera.yaml"
            write_camera_config(
                Path(
                    "datasets/full_downloads/afrl_hf/camera_imu_parameters/"
                    "camchain_cave_gennie.yaml"
                ),
                "cam0",
                output,
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("image_width: 1600", text)
            self.assertIn("image_height: 1200", text)
            self.assertIn("fx: 1156.5188534683703", text)
            self.assertIn("k1: -0.17473019446863114", text)


if __name__ == "__main__":
    unittest.main()
