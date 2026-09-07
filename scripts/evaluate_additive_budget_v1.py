#!/usr/bin/env python3
"""Existing dual-scale evaluator with the existing exact ROS epoch adapter."""
import evaluate_vins_common_support_dual_scale as dual
from evaluate_vins_common_support_epoch_v2 import load_ros_reference

if __name__=='__main__':
    dual.base.load_ros_reference=load_ros_reference
    raise SystemExit(dual.main())
