import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_loop_system_v1 import common_gate, errors_with_evo, proper_alignment


class EvaluationContract(unittest.TestCase):
    def setUp(self):
        self.t = np.arange(40.)
        self.p = np.column_stack((np.cos(self.t / 9), np.sin(self.t / 9), self.t / 7))
        self.q = Rotation.from_euler("z", self.t / 15).as_quat()

    def test_fixed_scale_does_not_hide_scale_error(self):
        fixed, _ = errors_with_evo(self.t, self.p, self.q, 3 * self.p, self.q)
        sim, _ = errors_with_evo(self.t, self.p, self.q, 3 * self.p, self.q, True)
        self.assertEqual(fixed["scale"], 1.)
        self.assertGreater(fixed["ape_rmse"], .1)
        self.assertAlmostEqual(sim["scale"], 1 / 3)
        self.assertLess(sim["ape_rmse"], 1e-10)
        self.assertLess(sim["rpe_1s_translation_rmse"], 1e-10)

    def test_proper_se3_and_orientation_invariance(self):
        r = Rotation.from_euler("xyz", [.2, -.3, 1.1]).as_matrix()
        source = (self.p - [4., 2., 7.]) @ r
        q = Rotation.from_matrix(r.T @ Rotation.from_quat(self.q).as_matrix()).as_quat()
        result, _ = errors_with_evo(self.t, self.p, self.q, source, q)
        self.assertLess(result["ape_rmse"], 1e-10)
        self.assertLess(result["rpe_1s_rotation_rmse_deg"], 1e-8)
        self.assertAlmostEqual(result["alignment_rotation_det"], 1.)

    def test_no_gap_bridge_for_one_second_rpe(self):
        mask = np.ones(40, bool)
        mask[20] = False
        result, _ = errors_with_evo(self.t[mask], self.p[mask], self.q[mask], self.p[mask], self.q[mask])
        self.assertEqual(result["rpe_pairs"], 37)

    def test_all_arms_and_full_reference_denominator(self):
        ref = np.ones(100, bool)
        valid = np.arange(100) < 69
        _, result = common_gate(np.arange(100), ref, {"B": ref, "C": ref, "L": valid})
        self.assertEqual(result["support_gate"], "FAIL")
        self.assertEqual(result["common_reference_coverage"], .69)
        valid[69] = True
        _, result = common_gate(np.arange(100), ref, {"B": ref, "C": ref, "L": valid})
        self.assertEqual(result["support_gate"], "PASS")

    def test_reflection_is_not_allowed(self):
        reflected = self.p.copy()
        reflected[:, 0] *= -1
        r, _, _ = proper_alignment(reflected, self.p)
        self.assertAlmostEqual(np.linalg.det(r), 1.)

    def test_collinear_alignment_is_rejected(self):
        positions = np.column_stack((self.t, self.t * 0, self.t * 0))
        with self.assertRaises(ValueError):
            proper_alignment(positions, positions)


if __name__ == "__main__":
    unittest.main()
