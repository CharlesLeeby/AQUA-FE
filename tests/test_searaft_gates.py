import unittest
import numpy as np
from searaft_screening_measurements import group_gate

class ScreeningGateTests(unittest.TestCase):
    def fixture(self):
        n=110
        return dict(b_failed=np.ones(n,bool),visible=np.arange(n)<100,truth=np.zeros((n,2)),
            C_points=np.tile([1.,0],(n,1)),S_points=np.tile([.1,0],(n,1)),
            C_common=np.arange(n)<40,S_common=np.arange(n)<20)

    def test_easy_subset_p95_cannot_pass_when_coverage_drops(self):
        data=self.fixture();g=group_gate(data,'fixture','large')
        self.assertLess(g['S_common_epe_p95'],.8*g['C_common_epe_p95'])
        self.assertFalse(g['B']);self.assertFalse(g['pass_group'])

    def test_more_acceptance_does_not_override_invisible_guard(self):
        data=self.fixture();data['S_common'][:70]=True;data['S_common'][100]=True
        g=group_gate(data,'fixture','large')
        self.assertTrue(g['A']);self.assertFalse(g['error_guards']);self.assertFalse(g['pass_group'])

if __name__=='__main__':unittest.main()
