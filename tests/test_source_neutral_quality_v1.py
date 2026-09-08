import copy
import sys
import unittest
from pathlib import Path

import numpy as np
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from convert_source_neutral_quality_v1 import mapping, tracks_from_records, assert_only_quality_changed


class SourceNeutralTest(unittest.TestCase):
    def test_generic_mapping_preserves_real_source(self):
        original, neutral = mapping()
        records = [dict(source_id=i, point=[20., 30.], age=age, fb=fb, ncc=ncc, raw_quality=q)
                   for i, (age, fb, ncc, q) in enumerate([(3, .9, .65, .1), (8, 0, 1, 1), (20, .2, .9, .8)])]
        tracks = tracks_from_records(records)
        oldq = original(tracks, mode='vins_safe', floor=.8, alpha=.65)
        neutralq = neutral(tracks, mode='vins_safe', floor=.8, alpha=.65)
        self.assertEqual(tracks.sources, ['xfeat_confirmed'] * 3)
        self.assertTrue(np.all(neutralq >= .8) and np.any(neutralq != oldq))
        # The existing generic fallback is source independent, while real labels stay intact.
        generic = copy.deepcopy(tracks)
        generic.sources = ['unclassified_observation'] * 3
        np.testing.assert_array_equal(neutralq, original(generic, mode='vins_safe', floor=.8, alpha=.65))

    def test_input_contract_rejects_backbone_and_geometry_changes(self):
        msg = PointCloud(points=[Point32(0, 0, 1), Point32(.1, .2, 1)], channels=[
            ChannelFloat32('id', [1, 10000000]), ChannelFloat32('quality', [.7, .92]),
            ChannelFloat32('sigma', [1.2, 1.04]), ChannelFloat32('source_code', [0, 4])])
        changed = copy.deepcopy(msg)
        changed.channels[1].values[1] = .8
        assert_only_quality_changed(msg, changed)
        changed.channels[1].values[0] = .8
        with self.assertRaises(AssertionError):
            assert_only_quality_changed(msg, changed)
        changed = copy.deepcopy(msg)
        changed.points[1].x = .3
        with self.assertRaises(AssertionError):
            assert_only_quality_changed(msg, changed)


if __name__ == '__main__':
    unittest.main()
