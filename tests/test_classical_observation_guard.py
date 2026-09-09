import copy
import unittest

from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud

from uw_frontend.ros.classical_observation_guard import ClassicalObservationGuard, message_bytes


def cloud(count=350):
    msg = PointCloud()
    msg.header.frame_id = 'world'
    msg.points = [Point32(.1, .2, 1.) for _ in range(count)]
    msg.channels = [ChannelFloat32('id', list(map(float, range(count)))),
                    ChannelFloat32('camera_id', [0.] * count),
                    ChannelFloat32('quality', [.8] * count)]
    return msg


def remove(msg, index):
    del msg.points[index]
    for channel in msg.channels:
        del channel.values[index]


class GuardTests(unittest.TestCase):
    def test_identical_proposal(self):
        b = cloud()
        p = copy.deepcopy(b)
        o, reason = ClassicalObservationGuard().select(b, p)
        self.assertEqual(message_bytes(o), message_bytes(b))
        self.assertEqual(reason, 'preserved_baseline')

    def test_birth_omission_is_not_exempt(self):
        b, p = cloud(), cloud()
        remove(p, 349)
        o, reason = ClassicalObservationGuard().select(b, p)
        self.assertIs(o, b)
        self.assertEqual(reason, 'baseline_observation_deleted')

    def test_same_id_with_changed_quality_is_blocked(self):
        b, p = cloud(), cloud()
        p.channels[2].values[1] = .9
        self.assertEqual(ClassicalObservationGuard().select(b, p)[1], 'baseline_observation_modified')

    def test_same_id_wrong_camera_is_not_same_observation(self):
        b, p = cloud(), cloud()
        p.channels[1].values[1] = 1.
        self.assertEqual(ClassicalObservationGuard().select(b, p)[1], 'baseline_observation_deleted')

    def test_retained_order_is_protected(self):
        b, p = cloud(), cloud()
        for channel in p.channels:
            channel.values[0], channel.values[1] = channel.values[1], channel.values[0]
        self.assertEqual(ClassicalObservationGuard().select(b, p)[1], 'baseline_observation_reordered')

    def test_cap_and_invalid_baseline(self):
        self.assertEqual(ClassicalObservationGuard().select(cloud(), cloud(351))[1], 'feature_cap_exceeded')
        with self.assertRaises(ValueError):
            ClassicalObservationGuard().select(cloud(351), cloud(351))

    def test_genuine_additive_capacity_is_not_deleted(self):
        b, p = cloud(349), cloud()
        self.assertIs(ClassicalObservationGuard().select(b, p)[0], p)

    def test_latch_uses_past_fault_and_does_not_reactivate(self):
        guard = ClassicalObservationGuard()
        guard.select(cloud(), cloud(349))
        b, p = cloud(349), cloud()
        o, reason = guard.select(b, p)
        self.assertIs(o, b)
        self.assertTrue(reason.startswith('latched:'))

    def test_header_schema_duplicate_nonfinite(self):
        for kind in ('header', 'schema', 'duplicate', 'nan'):
            b, p = cloud(), cloud()
            if kind == 'header': p.header.seq = 1
            if kind == 'schema': p.channels[2].name = 'sigma'
            if kind == 'duplicate': p.channels[0].values[1] = 0.
            if kind == 'nan': p.points[1].x = float('nan')
            self.assertIs(ClassicalObservationGuard().select(b, p)[0], b)


if __name__ == '__main__':
    unittest.main()
