import copy
import unittest
import rospy
from geometry_msgs.msg import Point32
from sensor_msgs.msg import PointCloud,ChannelFloat32
from uw_frontend.ros.additive_budget_v1 import Publisher,assert_backbone,serialized


def baseline(t):
    m=PointCloud();m.header.stamp=rospy.Time(t,17);m.header.seq=19
    m.points=[Point32(.1,.2,1)]
    names=['id','camera_id','p_u','p_v','velocity_x','velocity_y','gx','gy','gz','quality','sigma','source_code','is_learned']
    m.channels=[ChannelFloat32(name=n,values=[v]) for n,v in zip(names,[9,0,20,30,.4,.5,0,0,0,.87,1.03,0,0])]
    return m


def record(t,ids):
    return dict(frame=t,stamp_ns=rospy.Time(t,17).to_nsec(),observations=[dict(source_id=i,point=[100+i,200],
                normalized=[i*.01,.2],quality=.85,source='xfeat',age=t+3) for i in ids])


class AdditiveContract(unittest.TestCase):
    def test_cap_causal_continuation_and_all_subset(self):
        six,all_=Publisher(6),Publisher()
        for t,ids in [(1,list(range(10))),(2,list(range(2,12))),(3,list(range(12)))]:
            b=baseline(t);a,s=six.publish(b,record(t,ids));_,full=all_.publish(b,record(t,ids))
            self.assertEqual(len(s),6);self.assertLessEqual(set(s),set(full));assert_backbone(b,a)
            if t==2:self.assertEqual(s[:4],[2,3,4,5])

    def test_missing_observation_breaks_identity_and_no_backfill(self):
        p=Publisher();p.publish(baseline(1),record(1,[0]));first=p.active[0][0]
        p.publish(baseline(2),record(2,[]));p.publish(baseline(3),record(3,[0]))
        self.assertNotEqual(first,p.active[0][0]);self.assertEqual(p.lengths[first],1)

    def test_no_cumulative_fifty_or_startup_horizon(self):
        p=Publisher(6)
        for t in range(1,42):p.publish(baseline(t),record(t,range(6)))
        self.assertEqual(sum(p.lengths.values()),246);self.assertEqual(len(p.lengths),6)

    def test_zero_and_corruption(self):
        b=baseline(1);out,_=Publisher().publish(b,record(1,[]))
        self.assertEqual(serialized(b),serialized(out))
        out.channels[4].values[0]=99
        with self.assertRaises(ValueError):assert_backbone(b,out)

    def test_duplicate_timestamp_identity_and_float32(self):
        p=Publisher();p.publish(baseline(1),record(1,[0]))
        with self.assertRaises(ValueError):p.publish(baseline(1),record(1,[0]))
        with self.assertRaises(ValueError):Publisher().publish(baseline(1),record(1,[0,0]))
        p=Publisher();p.next_id=2**24
        with self.assertRaises(ValueError):p.publish(baseline(1),record(1,[0]))


if __name__=='__main__':unittest.main()
