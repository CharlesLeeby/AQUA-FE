import copy
import unittest

from scripts import run_p06_ros_screening_v3 as runner


class P06RosScreeningV3Test(unittest.TestCase):
    def test_afrl_calibration_is_replaced_per_sequence(self):
        correction = runner.load_correction()
        rows = [
            {
                "dataset_family": "afrl",
                "sequence": "bus_outside",
                "calibration_paths": (
                    "datasets/full_downloads/afrl_hf/camera_imu_parameters/"
                    "camchain_cave_gennie.yaml;"
                    "datasets/full_downloads/afrl_hf/camera_imu_parameters/imu.yaml"
                ),
            }
        ]
        updated = runner.apply_correction_to_rows(copy.deepcopy(rows), correction)
        self.assertIn("camchain_bus_outside.yaml", updated[0]["calibration_paths"])
        self.assertNotEqual(rows[0]["calibration_paths"], updated[0]["calibration_paths"])

    def test_unexpected_frozen_calibration_fails_closed(self):
        correction = runner.load_correction()
        rows = [
            {
                "dataset_family": "afrl",
                "sequence": "cemetery",
                "calibration_paths": "unexpected.yaml",
            }
        ]
        with self.assertRaises(ValueError):
            runner.apply_correction_to_rows(rows, correction)


if __name__ == "__main__":
    unittest.main()
