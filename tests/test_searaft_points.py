import unittest
import numpy as np
import torch
from uw_frontend.matchers.searaft_points import bilinear,restore_flow,common_mask

class CoordinateTests(unittest.TestCase):
    def test_resize_restores_each_component_at_odd_asymmetric_dimensions(self):
        flow=torch.ones(1,2,25,40)
        flow[:,1]*=3
        full=restore_flow(flow,(51,83))
        np.testing.assert_allclose(full[0,0].numpy(),83/40,rtol=1e-6)
        np.testing.assert_allclose(full[0,1].numpy(),3*51/25,rtol=1e-6)

    def test_bilinear_and_backward_at_forward_endpoint(self):
        y,x=np.mgrid[:50,:60]
        field=np.stack((x+2*y,3*x-y),axis=-1).astype(float)
        p=np.array([[20.25,20.75]])
        np.testing.assert_allclose(bilinear(field,p),[[61.75,40.]])
        f=np.stack((x*.1,np.zeros_like(x)),axis=-1)
        b=np.stack((-x/11.,np.zeros_like(x)),axis=-1)
        flow=bilinear(f,p);end=p+flow
        fb=np.linalg.norm(flow+bilinear(b,end),axis=1)
        self.assertLess(fb[0],1e-12)
        self.assertGreater(np.linalg.norm(flow+bilinear(b,p)),.1)
        self.assertTrue(common_mask(p,end,fb,(50,60))[0])

    def test_outside_is_missing_and_border_is_not_clamped_valid(self):
        out=bilinear(np.ones((20,30,2)),np.array([[-1,10],[30,10],[5.5,7]]))
        self.assertTrue(np.isnan(out[:2]).all())
        self.assertFalse(common_mask(np.array([[10,10]]),np.array([[25,10]]),np.array([0.]),(20,30))[0])

if __name__=='__main__':
    unittest.main()
