import unittest
import numpy as np
from uw_frontend.tracking.correspondence_evidence import check_correspondence_evidence, sample_patches


class EvidenceNumerics(unittest.TestCase):
    def setUp(self):
        rng = np.random.RandomState(20260910)
        self.image = rng.uniform(30, 160, (40, 40))
        self.points = np.array([[17.25, 19.625]])

    def test_identity_and_photometric_scaling(self):
        # Low contrast remains above the fixed one-gray-level floor.
        for gain, bias in [(1., 0.), (1.4, 8.), (.15, 90.)]:
            r = check_correspondence_evidence(self.image, self.image*gain+bias, self.points, self.points)
            self.assertTrue(r['evidence_accepted'][0])
            self.assertAlmostEqual(r['ncc'][0], 1., places=12)

    def test_constant_and_low_variance_unresolved(self):
        for image in [np.full((40, 40), 100.), self.image*.001+100]:
            r = check_correspondence_evidence(image, image, self.points, self.points)
            self.assertFalse(r['evidence_accepted'][0])
            self.assertFalse(r['valid_patch'][0])
            self.assertEqual(r['reason'][0], 'UNRESOLVED_LOW_VARIANCE')
            self.assertTrue(np.isnan(r['ncc'][0]))

    def test_border_is_exact_without_rounding_or_padding(self):
        p = np.array([[5., 5.], [4.999, 5.], [34., 34.], [34.001, 34.]])
        r = check_correspondence_evidence(self.image, self.image, p, p)
        np.testing.assert_array_equal(r['evidence_accepted'], [True, False, True, False])

    def test_bilinear_sampling_matches_scalar_reference(self):
        patch, valid = sample_patches(self.image, self.points)
        self.assertTrue(valid[0])
        for row, col in [(0, 0), (5, 5), (7, 9), (10, 10)]:
            x, y = self.points[0]+[col-5, row-5]
            ix, iy = int(np.floor(x)), int(np.floor(y))
            a, b = x-ix, y-iy
            expected = ((1-a)*(1-b)*self.image[iy, ix]+a*(1-b)*self.image[iy, ix+1]
                        +(1-a)*b*self.image[iy+1, ix]+a*b*self.image[iy+1, ix+1])
            self.assertAlmostEqual(patch[0, row, col], expected, places=12)
        self.assertNotAlmostEqual(patch[0, 5, 5], self.image[20, 17])

    def test_nonfinite_and_wrong_match(self):
        bad = self.image.copy();bad[19, 17] = np.nan
        r = check_correspondence_evidence(self.image, bad, self.points, self.points)
        self.assertEqual(r['reason'][0], 'UNRESOLVED_NONFINITE_PATCH')
        r = check_correspondence_evidence(self.image, self.image, self.points, [[np.nan, 10.]])
        self.assertEqual(r['reason'][0], 'UNRESOLVED_NONFINITE_COORDINATE')
        r = check_correspondence_evidence(self.image, 200-self.image, self.points, self.points)
        self.assertEqual(r['reason'][0], 'NCC_BELOW_THRESHOLD')
        self.assertAlmostEqual(r['ncc'][0], -1.)


if __name__ == '__main__':
    unittest.main()
