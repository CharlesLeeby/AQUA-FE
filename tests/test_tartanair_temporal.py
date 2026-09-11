import unittest
import numpy as np
from scripts.train_temporal_refinement import PatchTriplets
from uw_frontend.datasets.tartanair_temporal import anchor_world,visible_world,sample,K,NED_FROM_OPTICAL


class TartanAirTemporalTests(unittest.TestCase):
    def test_compact_patches_equal_explicit_triplets(self):
        bank=np.arange(5*31*31,dtype=np.float32).reshape(5,31,31)/10000
        indices=np.array([[0,0,0],[0,0,1],[0,1,2],[3,3,3],[3,3,4]])
        compact=PatchTriplets(bank,indices)
        explicit=np.stack([bank[r] for r in indices])
        np.testing.assert_array_equal(compact[:],explicit)
        np.testing.assert_array_equal(compact[[4,0,2]],explicit[[4,0,2]])

    def test_birth_point_does_not_move_when_klt_drifts(self):
        depth=np.full((480,640),4.,np.float32)
        pose=np.eye(4)
        birth=np.array([[320.,240.]])
        world,reason=anchor_world(birth,depth,pose)
        self.assertEqual(reason[0],'valid')
        moved=np.eye(4);moved[0,3]=.1
        truth,reason=visible_world(world,depth,moved)
        np.testing.assert_allclose(truth,[[312.,240.]])
        drifted_klt=np.array([[314.,239.]])
        self.assertGreater(np.linalg.norm(drifted_klt-truth),2.)
        np.testing.assert_allclose(world,[[0.,0.,4.]])
        self.assertEqual(reason[0],'valid')

    def test_visibility_and_depth_edge_reasons(self):
        depth=np.full((480,640),4.,np.float32);pose=np.eye(4)
        world,_=anchor_world(np.array([[320.,240.]]),depth,pose)
        _,reason=visible_world(world,np.full_like(depth,2.),pose)
        self.assertEqual(reason[0],'occluded_or_depth_mismatch')
        depth[240,320]=2.
        _,reason=anchor_world(np.array([[320.,240.]]),depth,pose)
        self.assertEqual(reason[0],'depth_discontinuity')
        _,reason=anchor_world(np.array([[0.,240.]]),depth,pose)
        self.assertEqual(reason[0],'out_of_view')

    def test_optical_to_ned_and_mask_codes(self):
        np.testing.assert_array_equal(NED_FROM_OPTICAL @ [2,3,4],[4,2,3])
        mask=np.zeros((480,640),np.uint8);mask[30,20]=100
        values=sample(mask,np.array([[20,30],[21,30],[-1,30]]),True,border=255)
        np.testing.assert_array_equal(values,[100,0,255])


if __name__=='__main__':
    unittest.main()
