"""Small synthetic interface checks, NOT trained-model or SLAM validation."""
import importlib.util
import struct
import unittest
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("adapter", Path(__file__).resolve().parents[1] / "learned_loop_candidates_v1.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class CandidateContractTests(unittest.TestCase):
    def test_history_excludes_nearby_self_and_future_before_topk(self):
        ids = np.array([0, 1, 2, 49, 50, 100, 101])
        rows = adapter.select_candidates(100, ids, np.array([.6, .7, .8, .9, 1., 1., 1.]), "L")
        self.assertEqual([r["candidate_id"] for r in rows], [49, 2, 1, 0])
        self.assertEqual([r["candidate_id"] for r in rows if r["selected_for_geometry"]], [0])

    def test_exact_exclusion_boundary(self):
        self.assertEqual(adapter.select_candidates(50, np.array([0]), np.array([1.]), "L"), [])
        self.assertEqual(len(adapter.select_candidates(51, np.array([0, 1]), np.array([.7, 1.]), "L")), 1)

    def test_native_classical_gate_and_single_verifier_budget(self):
        ids = np.array([0, 1, 2])
        rows = adapter.select_candidates(100, ids, np.array([.01, .02, .06]), "C")
        self.assertEqual([r["candidate_id"] for r in rows if r["selected_for_geometry"]], [1])
        rows = adapter.select_candidates(100, ids, np.array([.01, .015, .06]), "C")
        self.assertFalse(any(r["selected_for_geometry"] for r in rows))

    def test_ties_stable_and_no_geometry_claim(self):
        rows = adapter.select_candidates(100, np.array([3, 1, 0, 2, 4]), np.ones(5), "L")
        self.assertEqual([r["candidate_id"] for r in rows], [0, 1, 2, 3])
        self.assertTrue(all(r["geometry_status"] == "Not evaluated" and r["correctness"] == "Unknown" for r in rows))

    def test_invalid_scores_ids_rejected(self):
        for ids, scores in [(np.array([0, 0]), np.ones(2)), (np.array([0]), np.array([np.nan])), (np.array([-1]), np.ones(1))]:
            with self.assertRaises(ValueError):
                adapter.select_candidates(100, ids, scores, "L")

    def test_dictionary_mismatch_and_shape_rejected(self):
        for blob in (b"", struct.pack("<ii", 32, 1024) + bytes(32 * 1024 * 4), struct.pack("<ii", 32, 384) + bytes(32 * 384 * 4)):
            with self.assertRaises(ValueError):
                adapter.decode_vocabulary(blob)

    def test_preprocess_letterbox_and_rgb(self):
        bgr = np.zeros((120, 160, 3), dtype=np.uint8)
        bgr[:, :, 2] = 255
        out = adapter.preprocess_bgr(bgr)
        self.assertEqual(out.shape, (1, 3, 280, 448))
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out[0, 0, 100, 100]), (1 - .485) / .229, places=5)
        self.assertAlmostEqual(float(out[0, 0, 100, 0]), -.485 / .229, places=5)

    def test_vlad_normalization_and_degenerate_rejection(self):
        centers = np.zeros((32, 384), dtype=np.float32)
        centers[1:] = 20
        tokens = np.ones((640, 384), dtype=np.float32)
        desc = adapter.encode_vlad(tokens, centers)
        self.assertEqual(desc.shape, (12288,))
        self.assertAlmostEqual(float(np.linalg.norm(desc)), 1., places=5)
        self.assertTrue(np.all(desc[384:] == 0))
        with self.assertRaises(ValueError):
            adapter.encode_vlad(np.zeros_like(tokens), centers)


if __name__ == "__main__":
    unittest.main()
