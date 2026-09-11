"""Small lifecycle/priority checks; fake measurements only, no model load."""
import unittest
from unittest.mock import patch
import numpy as np
from uw_frontend.tracking.klt_tracker import KltConfig,KltTracker
from uw_frontend.tracking.track_state import TrackSet
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.searaft_system_recovery import SeaRaftSystemTracker

class RecoveryTest(unittest.TestCase):
    def test_only_remaining_ids_and_no_revival(self):
        im=np.random.RandomState(5).randint(0,256,(80,80),dtype=np.uint8)
        old=np.array([[20,20],[35,35],[50,50]],np.float32)
        ordinary=TrackSet(ids=np.array([10]),prev_points=old[:1].copy(),points=old[:1].copy(),ages=np.array([3]),fb_errors=np.zeros(1),ncc_scores=np.ones(1),local_texture=np.ones(1),qualities=np.ones(1),sources=['klt'])
        def ordinary_step(tr,*args):
            tr.points,tr.ids,tr.ages=ordinary.points.copy(),ordinary.ids.copy(),ordinary.ages.copy()
            return ordinary
        seen=[]
        def predict(a,b,p):
            seen.append(p.copy());return dict(points=p.copy(),fb_error=np.zeros(len(p)))
        for arm in ['C','R']:
            tr=SeaRaftSystemTracker(arm,KltConfig(),predict)
            tr.points=old.copy();tr.ids=np.array([10,11,12]);tr.ages=np.array([2,2,2]);tr.raw_previous=tr.raw_current=im
            tr.frame_stats={}
            with patch.object(KltTracker,'_track_existing',ordinary_step),patch('uw_frontend.tracking.searaft_system_recovery.strong_lk',return_value=(old[1:].copy(),np.array([0.,2.]),0.)):
                result=tr._track_existing(im,im,score_image_quality(im))
            self.assertEqual(result.ids.tolist(),[10,11] if arm=='C' else [10,11,12])
            np.testing.assert_array_equal(result.points[:2],old[:2])
        np.testing.assert_array_equal(seen[0],old[2:])
        tr.frame_index=3
        with self.assertRaises(ValueError):tr.process_raw(im,im,score_image_quality(im),5,5)

if __name__=='__main__':unittest.main()
