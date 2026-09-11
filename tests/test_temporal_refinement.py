"""Contract and analytical tests; synthetic examples are NOT learning evidence."""
import copy
import unittest
import numpy as np
import torch
from uw_frontend.temporal_refinement import (
    PatchRefiner, paired_loss, extract_patch, correct_records,
    unproject_z, project_world, require_verified_supervision,
)
from scripts.train_temporal_refinement import consecutive_pairs


class TemporalRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_zero_initialization_bound_and_invalid_patch(self):
        torch.manual_seed(20260911)
        model = PatchRefiner()
        patches, history = torch.rand(4, 3, 31, 31), torch.randn(4, 4)
        valid = torch.ones(4, dtype=torch.bool)
        self.assertLess(sum(p.numel() for p in model.parameters()), 1000000)
        self.assertTrue(torch.equal(model(patches, history, valid), torch.zeros(4, 2)))
        with torch.no_grad():
            model.head.bias[:] = torch.tensor([20., -20.])
        patches[1, 0, 0, 0] = float('nan')
        valid[2] = False
        history[3, 0] = float('inf')
        out = model(patches, history, valid)
        self.assertTrue(torch.isfinite(out).all())
        self.assertTrue((out.abs() <= 2).all())
        self.assertTrue(torch.equal(out[1:], torch.zeros(3, 2)))

    def test_temporal_loss_penalizes_error_change_not_real_motion(self):
        truth = torch.tensor([[[1., 2.], [101., -202.]]])
        baseline = truth + torch.tensor([3., 4.])
        delta = torch.zeros_like(truth, requires_grad=True)
        _, _, temporal = paired_loss(delta, baseline, truth, .5)
        self.assertEqual(temporal.item(), 0.)
        baseline[:, 1, 0] += 2
        loss, _, temporal = paired_loss(delta, baseline, truth, .5)
        self.assertGreater(temporal.item(), 0.)
        loss.backward()
        self.assertTrue(torch.isfinite(delta.grad).all())

    def test_same_rows_metadata_and_public_velocity(self):
        rows = [dict(id=4, timestamp_ns=1000000000, uv=[10., 20.], normalized=[.1, .2],
                     velocity=[0., 0.], q=.8, sigma=1.2, age=1),
                dict(id=4, timestamp_ns=1500000000, uv=[20., 30.], normalized=[.2, .3],
                     velocity=[.2, .2], q=.8, sigma=1.2, age=2),
                dict(id=4, timestamp_ns=2000000000, uv=[30., 40.], normalized=[.3, .4],
                     velocity=[.2, .2], q=.8, sigma=1.2, age=3)]
        saved = copy.deepcopy(rows)
        normalize = lambda uv: uv / 100
        self.assertEqual(correct_records(rows, np.zeros((3, 2)), normalize), rows)
        output = correct_records(rows, [[0., 0.], [2., -2.], [0., 0.]], normalize)
        self.assertEqual(rows, saved)
        np.testing.assert_allclose(output[1]['normalized'], [.22, .28])
        np.testing.assert_allclose(output[1]['velocity'], [.24, .16])
        np.testing.assert_allclose(output[2]['velocity'], [.16, .24])
        for src, dst in zip(rows, output):
            self.assertEqual({k: v for k, v in src.items() if k not in ['uv', 'normalized', 'velocity']},
                             {k: v for k, v in dst.items() if k not in ['uv', 'normalized', 'velocity']})
        with self.assertRaises(ValueError):
            correct_records(rows, [[0, 0], [3, 0], [0, 0]], normalize)

    def test_patch_border_fallback_and_pixel_units(self):
        img = np.tile(np.arange(100, dtype=np.uint8), (80, 1))
        patch, reason = extract_patch(img, [30.5, 25.])
        self.assertEqual(reason, 'valid')
        self.assertAlmostEqual(patch[15, 15] * 255, 30.5, places=4)
        patch, reason = extract_patch(img, [2., 20.])
        self.assertEqual(reason, 'patch_out_of_bounds')
        self.assertEqual(float(patch.sum()), 0.)

    def test_analytical_world_projection_translation(self):
        K = np.array([[100., 0, 50.], [0, 100., 40.], [0, 0, 1.]])
        uv = np.array([[50., 40.], [60., 50.]])
        points = unproject_z(uv, [2., 4.], K)
        projected, depth = project_world(points, np.eye(4), K)
        np.testing.assert_allclose(projected, uv)
        np.testing.assert_allclose(depth, [2., 4.])
        pose = np.eye(4)
        pose[0, 3] = .1
        projected, _ = project_world(points, pose, K)
        np.testing.assert_allclose(projected, [[45., 40.], [57.5, 50.]])

    def test_unverified_depth_cannot_start_training(self):
        with self.assertRaisesRegex(ValueError, 'SUPERVISION_UNAVAILABLE'):
            require_verified_supervision({'metric_depth_encoding': 'Unknown'})

    def test_pairs_exclude_cross_id_scene_gaps_and_invalid(self):
        a = dict(sequence=np.array(['a', 'a', 'a', 'a', 'b', 'a', 'a']),
                 id=np.array([1, 1, 2, 1, 1, 1, 1]), frame=np.array([0, 1, 2, 3, 4, 4, 5]),
                 label_valid=np.array([1, 1, 1, 1, 1, 0, 1], bool))
        np.testing.assert_array_equal(consecutive_pairs(a), [[0, 1]])


if __name__ == '__main__':
    unittest.main()
