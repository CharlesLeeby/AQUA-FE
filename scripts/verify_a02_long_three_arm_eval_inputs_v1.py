#!/usr/bin/env python3
"""Seal or re-check the exact inputs to the A02 long-window three-arm G0.

This verifier runs no SLAM and computes no accuracy metric.  It fail-closes on
identity, pose, reference, bridge, or HFNet-v4 provenance drift and publishes
one no-clobber JSON receipt.  ``check`` recomputes the complete deterministic
record and requires byte-equivalent evidence before the evaluator may start.
"""

from __future__ import annotations

import argparse
import ast
import base64
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import evaluate_vins_common_support as evaluator
from scripts import export_aqualoc_a02_shared_4500_6300_v1 as shared_exporter


SCHEMA = "aqua-fe-a02-long-three-arm-pre-eval-verification-v1"
STATUS = "PASS_THREE_ARM_EVAL_INPUTS_SEALED"

DEFAULT_SHARED_ROOT = Path("/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1")
DEFAULT_WINDOW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
DEFAULT_WINDOW_MANIFEST = Path(str(DEFAULT_WINDOW_BAG) + ".manifest.json")
DEFAULT_B1_NATIVE_BAG = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_native_r1/features.bag"
DEFAULT_B1_NATIVE_CAMERA = DEFAULT_B1_NATIVE_BAG.parent / "aqualoc_archaeo02_pinhole.yaml"
DEFAULT_B1_GUARD_DECISION_DIR = ROOT / "logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1"
DEFAULT_B1_BACKEND_CONTRACT = ROOT / "papers/ieee_sensors_journal_experiments/backend_quality_contract_b1_current_exporter_v3.json"
DEFAULT_B1_BASE_BACKEND_CONTRACT = ROOT / "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
DEFAULT_B1_TRANSITION_PROOF = ROOT / "papers/ieee_sensors_journal_experiments/b1_klt_exporter_7ed_to_567_transition_proof_v2.json"
DEFAULT_B1_ELIGIBILITY_MANIFEST = ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
DEFAULT_B1_CONSTQ_BAG = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/features.bag"
DEFAULT_B1_QUALITY_AUDIT = DEFAULT_B1_CONSTQ_BAG.parent / "quality_partition_audit.json"
DEFAULT_XFEAT_BAG = ROOT / "logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_r1/features.bag"
DEFAULT_XFEAT_MANIFEST = DEFAULT_XFEAT_BAG.parent / "export_manifest.json"
DEFAULT_XFEAT_AUDIT = DEFAULT_XFEAT_BAG.parent / "audit.json"
DEFAULT_B1 = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_r1/vins_output/vio.csv"
DEFAULT_XFEAT = ROOT / "logs/aqualoc_archaeo_vins/external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1/vins_output/vio.csv"
DEFAULT_B1_LOG = DEFAULT_B1.parents[1] / "vins.log"
DEFAULT_XFEAT_LOG = DEFAULT_XFEAT.parents[1] / "vins.log"
DEFAULT_HFNET = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv"
DEFAULT_HFNET_RUN_DIR = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/runs/aqualoc_a02_4500_6300_headless_r1"
DEFAULT_HFNET_SOURCE = DEFAULT_HFNET_RUN_DIR / "trajectory.txt"
DEFAULT_BRIDGE_MANIFEST = Path(str(DEFAULT_HFNET) + ".manifest.json")
DEFAULT_V4_RESULT = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json"
DEFAULT_V4_CONTRACT = ROOT / "papers/hfnet_slam_a02_long1801_headless_run_contract_v4.json"
DEFAULT_V4_CONTRACT_SNAPSHOT = DEFAULT_V4_RESULT.parent / "frozen_contract.snapshot.json"
DEFAULT_EVAL_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
DEFAULT_EVALUATOR = ROOT / "scripts/evaluate_vins_common_support.py"
DEFAULT_CORE = ROOT / "scripts/trajectory_eval_core.py"
DEFAULT_OUTPUT = ROOT / "papers/a02_4500_6300_three_arm_pre_eval_verification_v1.json"
DEFAULT_EVAL_DIR = ROOT / "papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_vs_hfnet_r1"
DEFAULT_POST_EVAL_OUTPUT = DEFAULT_EVAL_DIR / "strict_gate_receipt.json"
DEFAULT_FREEZE = ROOT / "papers/a02_4500_6300_post_stop_long_window_comparison_freeze_v1.json"

EVALUATOR_SHA256 = "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"
CORE_SHA256 = "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"
CONFIG_SHA256 = "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"
RUNNER_SHA256 = "c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc"
VINS_BINARY_SHA256 = "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"
B1_V3_RUNNER_SHA256 = "1525a5f4ff18e6c562ab75ca17539b5748f0d9617e9c331ca4720672cd651d7e"
B1_V4_EXECUTION_REPAIR_SHA256 = "0e2735985cc8041ddeb8b9a8cea4c9264844f3c49c5f7349929e6819eb54167f"
B1_V4_EXECUTION_REPAIR_TESTS_SHA256 = "7d1192518e8ee7dec0d96725bae44efb136729674eb7c82b848c659514dcea55"
B1_LEGACY_RUNNER_SHA256 = "6c112ebdb916becf615b0772c4474a119bf774a17b4f85391ceb88d46d0505d1"
B1_BACKEND_CONTRACT_SHA256 = "24995595906c0ea2e121ac91e7acbfd1f9d2e583a7011e6953073e9e1134f177"
B1_BASE_BACKEND_CONTRACT_SHA256 = "14abab7ca7ad0f48af8856372b3cf97470d405c1e20081cdb4247f3c87b64957"
B1_CONTRACT_CHECKER_SHA256 = "32130de7016ad326281080825e74a9baab214cce1f98379f603e07b29c87d87e"
B1_V2_COMMON_CHECKER_SHA256 = "aa7f0b53049b99ed9dcbc1c511a709f9cc0e492514ac4662c31ca803672f57b6"
B1_LEGACY_CONTRACT_CHECKER_SHA256 = "8dafcb3e40278210e4fb545c5e19e347b69898cd45e5af3ec7736ceb682bad15"
B1_NATIVEQ_CHECKER_CORE_SHA256 = "37c61326e38d17e2a950fff66c9bd062bed8eab015385da36474c3bb558d3f4f"
B1_CONTRACT_BUILDER_SHA256 = "5701538678248de97711756264ff9cf5dfb64ff120cfe90f9b2c6376e354a50a"
B1_V2_CONTRACT_BUILDER_SHA256 = "cabda6889b1bd4e82607b541104577aa05c42030b20224d36270876b8477be50"
B1_LEGACY_CONTRACT_BUILDER_SHA256 = "0c5bbdf3fd1f0948a94df346d29dc8b26ee66666c51287b933db5e7e79a0decc"
B1_TRANSITION_PROVER_SHA256 = "5541d9e211490c5eb0d0ec39c57e5233597514e30729a9cff1f285382118f50b"
B1_TRANSITION_PROOF_SHA256 = "9a149489e1defa790a9ff7a5ec107a75f9c15a506723fea081315c68eaf1dd2a"
B1_V3_TESTS_SHA256 = "c38740e508e687fa176b7f970e8f1c966ffb941c598f2c2cd1c0c0fd052a9af5"
B1_ELIGIBILITY_MANIFEST_SHA256 = "510c276c33217706eef11ea53e58de4b37318828f8a6dc793dea9262f0a0a0f5"
B1_FRONTEND_EXPORTER_SHA256 = "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"
B1_BACKEND_CONTRACT_PAYLOAD_HASH = "7b6b653b51f0d3cc559962d18c4f3fdef7592b501123bb46bd40c822519f84a0"
B1_BASE_BACKEND_CONTRACT_PAYLOAD_HASH = "39eaea6d26e6f5a881ef2b17b898cbda75c7aba8087ce447fe897e2fe0bdfce0"
B1_BACKEND_CONTRACT_EXPORTER_SHA256 = "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"
QUALITY_REWRITER_SHA256 = "1cbf679994ad2897cdadd5e94cbf3653822ae980a7c1fabb47c7f2f400157f2d"
QUALITY_AUDITOR_SHA256 = "9ba78f3fa3ae9ea87109bed10b58233afef85d003f5ae996404eabee0f765c0b"
XFEAT_EXPORTER_SHA256 = "d7b6a698b784e0cee1c432308eb6f7546251503f0b47f4eeed9651b8fe401aba"
XFEAT_AUDITOR_SHA256 = "89998cacb929b00de08eb93cc21e36e7b64434a59acb3fc1b332f16822608935"
XFEAT_CARRIER_BASE_SHA256 = "2419fddc561c3a5bb2742aa033c62aa24d7361806a975c09c7e25ecf5995a34c"
XFEAT_AUDIT_BASE_SHA256 = "f8a6abecb6c2253d8721befaccf1e49eb6e68013b6d1376cff8dbd71f579f1d1"
XFEAT_QUALITY_REFERENCE_SOURCE_SHA256 = "e0b4a885cb8ecd2909b8abefc0fbc17098c9596df44091d5a3398df56583b89e"
XFEAT_AUDIT_PYTHON = Path("/tmp/aqua-fe-opencv-usac-v1/bin/python")
XFEAT_AUDIT_BASE_INTERPRETER = Path("/usr/bin/python3.8")
XFEAT_AUDIT_CV2_CORE = Path("/tmp/aqua-fe-opencv-usac-v1/lib/python3.8/site-packages/cv2/cv2.abi3.so")
XFEAT_AUDIT_BASE_INTERPRETER_SHA256 = "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06"
XFEAT_AUDIT_CV2_CORE_SHA256 = "72c7fe9b389ecd9549b6e9cdca35ee11940de15d13d46722b8412865cafabc78"
XFEAT_AUDIT_BASE_INTERPRETER_SIZE = 5_490_456
XFEAT_AUDIT_CV2_CORE_SIZE = 65_651_673
XFEAT_AUDIT_NUMPY = Path("/usr/lib/python3/dist-packages/numpy/__init__.py")
XFEAT_AUDIT_NUMPY_SHA256 = "e9ba95ebf3add32b201e50e1d2685aa28c21a3ce5ce460b9384b7266b49c77d5"
XFEAT_AUDIT_NUMPY_SIZE = 7_110
XFEAT_EXPORT_RUNTIME_FILES = {
    "/home/ma/.local/lib/python3.8/site-packages/torch/__init__.py": (
        78_481,
        "fe825c99bf91627cc438ab1967e413f4efef8599de835fb71af926c15b07a223",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py": (
        16_174,
        "edd18feff93348beb02f392959e80b9fda1875a842d7f9760847f32386fdfd48",
    ),
    "/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so": (
        6_970_496,
        "00f302d1efe76049187e2e2c7a05262e883394f82316490e2f28adb807ac1833",
    ),
    "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py": (
        1_800,
        "a65e884f18df0e88ff7403b53d77ad9ac59bd24734d880e301f7afe68fec4a81",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/_C.cpython-38-x86_64-linux-gnu.so": (
        37_489,
        "cbf6861cb2e89e098e1cc88c38fa3e565b70cdf471042b0bde14a351df26acf1",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch_python.so": (
        23_371_696,
        "ff832d1a405158eaae1241f17d4fef0ec143c42e3f129c9f7a934a617c773bdf",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libshm.so": (
        35_280,
        "46e21dd56dc8093909ebe0d7c01c1609b7957ffc269a137590b4e78bb40a9d98",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch.so": (
        7_192,
        "d85f826501ff97723aa4671328929a43e456dcda589e0be33f7bab5e9b882b37",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libtorch_cpu.so": (
        471_835_833,
        "ea615ec43ee633af935a073f6937f25555f4f68484935472ead52f80f6c801e2",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libc10.so": (
        1_167_384,
        "4804bd9f2524b593a71eecaeb5b09d82594ca98408574a93fcf70e92d3f28966",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/torch/lib/libgomp-a34b3233.so.1": (
        168_721,
        "570455c2902d6cc2a7f367703c06dac07495dd7f8a1ed2c8fc4cea628c881b13",
    ),
}
EVALUATION_RUNTIME_FILES = {
    "/opt/ros/noetic/lib/python3/dist-packages/rospy/__init__.py": (
        4_636,
        "9e5c4e111abae5c45266c74c2ed83ff045d00b29d4c514d31c09b250460c9159",
    ),
    "/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/msg/__init__.py": (
        848,
        "d19edf818de477fe4555552190ee083ce4967320d3b0ce63a6e79b0eceff0cb2",
    ),
    "/opt/ros/noetic/lib/python3/dist-packages/nav_msgs/msg/__init__.py": (
        351,
        "83cb4a545c959030c156611321bdadc8de74d09519beaf08b0c7e190191821cf",
    ),
    "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/__init__.py": (
        762,
        "c34aa9962d67d308caafc5cf61acf0515c9ba4826f6de2dbfee3b50ca8a9128f",
    ),
    "/opt/ros/noetic/lib/python3/dist-packages/std_msgs/msg/__init__.py": (
        855,
        "d51bf5761f4b02c5d4ba24325c02eb9962d49cfafbaf98f60eaaffe12b52b9f2",
    ),
    "/home/ma/.evo/settings.json": (
        1_850,
        "62a54e1c4b15fdbae6d36ea2c875b99c1f1a70a8d874d6b905b282ae0bd4d3bd",
    ),
    "/home/ma/.evo/assets_version": (
        7,
        "4be46314bd7bb15822fda619849fea4d28b993d5bb6631352605819b9819a4e6",
    ),
    "/home/ma/.local/bin/evo_ape": (
        213,
        "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15",
    ),
    "/home/ma/.local/bin/evo_rpe": (
        213,
        "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/evo/__init__.py": (
        583,
        "ea1a753dbb2d53e58f5b3c7c1691fbcac02295cd22be8fe0831092fe7e009010",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/evo-1.31.1.dist-info/RECORD": (
        5_951,
        "a720ae5d78b1cf5d0c5b3ed81b8deb2adc41cb686ccffd773a42a1553823cbde",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/core/_multiarray_umath.cpython-38-x86_64-linux-gnu.so": (
        6_311_424,
        "190fed599b26cf689e22f198faf97d632f1d19b8aa75fdf5ca7fb96d37d97e37",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/linalg.py": (
        89_351,
        "304a00b1bbd5f933e3920264c93f7a21a46e4091a05fc714248492b54e78d1c9",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/_umath_linalg.cpython-38-x86_64-linux-gnu.so": (
        230_272,
        "77d989daf30e91b14b657f0a125377d1c5bf49d7d950522baefdce9a7a93f927",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/lapack_lite.cpython-38-x86_64-linux-gnu.so": (
        29_992,
        "793234784255abc82b21e594a61906664219da405b0f73bf613da7b36e70c776",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy/lib/function_base.py": (
        185_141,
        "e2c03da3ca2ee0f918b8759df35a621db422f36dc6c017eef0f769188c8d452e",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libopenblas64_p-r0-15028c96.3.21.so": (
        32_955_056,
        "554bde1d8a0c71d8dc21ae74de05c44da4fff5dbc6791a819f6acf5adfe90bd9",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libgfortran-040039e1.so.5.0.0": (
        2_686_064,
        "47ab3b68295b0a3ce8990a448de7fab11abddbc160f8895972ca9aa712cf86d0",
    ),
    "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/libquadmath-96973f99.so.0.0.0": (
        247_608,
        "97cda85ddb5163e2da6e1edb4e1d6b557833a99a40eda079ae37e5039465b65d",
    ),
}
VINS_ENV_RECORDER_SHA256 = "577e17acb5e8df1a4a6d8d5b6ed531103adb984a5c7cb1cc8523f95d6e695ad3"
VINS_SIM_EVALUATOR_SHA256 = "ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33"
HFNET_V4_TESTS_SHA256 = "7963f86ebb8e7cd80ea699391c7061be11317ad251dfbbf256332afcfd11d397"
SHARED_EXPORTER_SHA256 = "c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f"
MATERIALIZER_SHA256 = "7d5ca32fea25945fcce454b948c55bc9d883b8dca3f5bf481611ced0395cd7a3"
RAW_CONVERTER_SHA256 = "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec"
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_CORE_LIBRARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")
VINS_CAMERA_MODELS_LIBRARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so")
LDD = Path("/usr/bin/ldd")
VINS_CORE_LIBRARY_SHA256 = "c1080aefdfd0eb3f011d491041c773649917a77923b97e24503bd90136bab467"
VINS_CAMERA_MODELS_LIBRARY_SHA256 = "6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d"
LDD_SHA256 = "d089c1054925b1f1dc9b574c2e7fabf3a495a1ce2ef946cd66d507daf09b7b8f"
VINS_CORE_LIBRARY_SIZE = 165_207_064
VINS_CAMERA_MODELS_LIBRARY_SIZE = 2_970_640
RUNNER = ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"
SHARED_SCHEMA = "aqua-fe-a02-shared-4500-6300-v1"
SHARED_STATUS = "EXPORTED_SHARED_INPUT_ONLY_NO_SLAM_STARTED"
V4_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-result-v4"
V4_STATUS = "PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE"
BRIDGE_SCHEMA = "aqua-fe-hfnet-world-body-to-vins-csv-bridge-v1"
BRIDGE_SHA256 = "5b14003204da7724f5a750bd0f6538575517aae7e21202c9b468a2716a84d2a1"
V4_CONTRACT_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-contract-v4"
V4_PROFILE_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-profile-v4"
V4_ROLE = "POST_STOP_EXPLORATORY_PUBLISHED_BASELINE_LONG_WINDOW_NOT_CONFIRMATORY"
QUALITY_AUDIT_SCHEMA = "aqua-fe-quality-partition-audit-v1"
XFEAT_MANIFEST_SCHEMA = "xfeat-lk-carrier-export-v1"
XFEAT_AUDIT_SCHEMA = "aqua-fe-xfeat-lk-carrier-audit-v1"
B1_GUARD_DECISION_SCHEMA = "aqua-fe-b1-klt-nativeq-current-exporter-guard-decision-v3"
POST_EVAL_SCHEMA = "aqua-fe-a02-long-three-arm-post-eval-verification-v1"
POST_EVAL_STATUS = "PASS_STRICT_COMMON_SUPPORT_APE_RPE_GRID45"
VINS_PROCESS_RECEIPT_SCHEMA = "aqua-fe-a02-vins-arm-process-receipt-v1"
SCORE_FIRST_NS = 1_542_829_061_692_686_528
SCORE_LAST_NS = 1_542_829_106_687_510_592
EXPECTED_REFERENCE_ROWS = 46
EXPECTED_UNIFORM_GRID_POINTS = 45
EXPECTED_STATIC_IDENTITY_COUNT = 131
EXPECTED_WORKING_DIRECTORY = str(ROOT)
EXPECTED_WINDOW_CONTRACT = {
    "camera_feed_count": 1_801,
    "camera_feed_global_indices_inclusive": [4_500, 6_300],
    "canonical_margin_imu_count": 18_084,
    "canonical_margin_imu_endpoints_ns": [
        1_542_829_016_456_083_680,
        1_542_829_106_933_121_504,
    ],
    "frame_5400_feed_count": 1,
    "hfnet_inner_imu_count": 17_987,
    "preroll_global_indices_inclusive": [4_500, 5_399],
    "score_global_indices_inclusive": [5_400, 6_300],
    "score_timestamp_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
}
EXPECTED_NORMALIZED_VINS_CONFIG_SHA256 = "45eb12852b8eff6b14dbfdb8f366fa64eebf7ca5dbf838d791f011dd84a4d084"
FREEZE_SCHEMA = "aqua-fe-a02-4500-6300-post-stop-long-window-comparison-freeze-v1"
FREEZE_STATUS = "FROZEN_NO_EXPERIMENT_STARTED_STATIC_GATE_REQUIRED"
ARM_LABELS = ("B1_CONSTQ", "XFEATBIRTH_RAWLK", "HFNET_WHOLE_SYSTEM")
EXPECTED_RESERVED_PATHS = (
    str(DEFAULT_WINDOW_BAG),
    str(DEFAULT_WINDOW_MANIFEST),
    str(DEFAULT_SHARED_ROOT),
    str(DEFAULT_B1_GUARD_DECISION_DIR),
    str(DEFAULT_B1_NATIVE_BAG.parent),
    str(DEFAULT_B1_CONSTQ_BAG.parent),
    str(DEFAULT_B1_QUALITY_AUDIT),
    str(DEFAULT_XFEAT_BAG.parent),
    str(DEFAULT_B1.parents[1]),
    str(DEFAULT_XFEAT.parents[1]),
    str(DEFAULT_V4_CONTRACT),
    str(DEFAULT_HFNET_RUN_DIR),
    str(DEFAULT_V4_RESULT.parent),
    str(DEFAULT_HFNET),
    str(DEFAULT_BRIDGE_MANIFEST),
    str(DEFAULT_OUTPUT),
    str(DEFAULT_EVAL_DIR),
    str(DEFAULT_POST_EVAL_OUTPUT),
)
INITIALIZATION_PATTERN = re.compile(rb"\binitialization[ \t]+finish!", re.IGNORECASE)
LOG_PATTERNS = {
    "linear_solver_failure": re.compile(rb"\blinear[ \t]+solver[ \t]+failure\b", re.IGNORECASE),
    "failure_detection": re.compile(rb"\bfailure[ \t]+detection!", re.IGNORECASE),
    "system_reboot": re.compile(rb"\bsystem[ \t]+reboot!", re.IGNORECASE),
    "external_restart": re.compile(rb"\brestart[ \t]+the[ \t]+estimator!", re.IGNORECASE),
}
B1_PYTHON_RUNTIME_CLOSURE = {
    "uw_frontend/__init__.py": (75, "44c8ccc9ab0cd7e8637b0dd005f183fb7b250a539c8b22ea6d26889a394f0934"),
    "uw_frontend/datasets/__init__.py": (60, "3e51607ce52c41b4cdba7cdc4b09e9cf3aff20c2e90b028971ab950cb8010477"),
    "uw_frontend/datasets/image_sequence.py": (4844, "2ba225a52a7caab9e92eb6b06c3ae7ff9a0030b96ea78e6f20f4228e97337384"),
    "uw_frontend/evaluation/__init__.py": (50, "b95c4d2adf475a333bb42261ad54ee79656fe5aaecb351c4ecec31c18f5dea9b"),
    "uw_frontend/evaluation/frontend_metrics.py": (17993, "dae3258f04316c387bbbee5b0870132f7bac4fb3261b6069f690f06e07b9baf8"),
    "uw_frontend/evaluation/measurement_selection.py": (46894, "83230a42744be60e010ee4870011375fdd432a562843388c7adacd030dc298d3"),
    "uw_frontend/evaluation/run_frontend_eval.py": (33121, "c299038feb926e37bada04d0f150e57d45bed2f4d91bad8fb6a0c4ab2b22e6d2"),
    "uw_frontend/geometry/__init__.py": (39, "f51eef8fcc512e338b3c5fd4f1e77f1dcb19dc09ab68eaab9289c968d56de882"),
    "uw_frontend/geometry/dl_vins_magsac.py": (4232, "d3c70b0c1f83f589380db82172b448ade485c101ed10102744f8a8d32487e128"),
    "uw_frontend/geometry/grid.py": (1155, "c1e6be4bfaee6cc1cac222c2dc5ba8f3e941702c60074f8473f663cf706de6eb"),
    "uw_frontend/geometry/mode.py": (5833, "402b5dc3eaecfb450a889502760cd591d02ff9c0e770edb522d1c777634c7a69"),
    "uw_frontend/geometry/validation.py": (2954, "4e2080bf786bf59b13af87ea7ee56b70b5f03892160ccd0a75aa9968d1781bb2"),
    "uw_frontend/matchers/__init__.py": (82, "ad377bf38dfe58a58b8db275c70c1f5b9372ab6329d0591bc88ff5425f949c13"),
    "uw_frontend/matchers/base.py": (741, "ad1baae7dc56188ae9d4a117de5efe0ae032a1b2749a4de38474c43d960876fa"),
    "uw_frontend/matchers/classical_gftt.py": (3799, "ec846d33ef8cc6ccb8e69fb30d87214c660807f94e9ca3b19aed6c944316604f"),
    "uw_frontend/matchers/lightglue_adapter.py": (6384, "9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a"),
    "uw_frontend/matchers/loftr_adapter.py": (5600, "105cf63af51b6d4f8554a76939f88509d30fd85abc1b804ef18f2fd78edaebc2"),
    "uw_frontend/matchers/xfeat_adapter.py": (5558, "919b6b365548f2439b13eb01a24bd3e476de543dfcfa28b77baa09a7692fe345"),
    "uw_frontend/quality/__init__.py": (42, "940c342bc9918992c9e53190993d1bff4f04970d3d0a9536d99f069a1b4a85fd"),
    "uw_frontend/quality/feature_confidence.py": (6691, "2ba770c1be212ec587c64ae0a35b3abc1dd58458f2e6eda572444859faf82864"),
    "uw_frontend/quality/image_quality.py": (13301, "e0b4a885cb8ecd2909b8abefc0fbc17098c9596df44091d5a3398df56583b89e"),
    "uw_frontend/quality/reliability_features.py": (4064, "f5f3d770af0655e7d68dbec9fdf043d6b772dd7b11b0f43ebc821515978cd8a4"),
    "uw_frontend/ros/__init__.py": (59, "63e8c6c8109779dde006b8e6067ae7dabb9520342bd069a210615ba1a2c774d1"),
    "uw_frontend/ros/export_vins_features.py": (437542, "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"),
    "uw_frontend/scheduler/__init__.py": (44, "c7ddade87b1a990451e559aa16a24892309a95cee6f5b976bc7e93e719279a90"),
    "uw_frontend/scheduler/hybrid_scheduler.py": (6956, "71e8ee6f95b47e6fbbfc8d25c96affea2abca217c91c47f75e0d13750ab3279b"),
    "uw_frontend/tracking/__init__.py": (34, "74c60ba0b8a4cceec88519da9c269dce3b796812e900a0cdf10110488c2a696a"),
    "uw_frontend/tracking/hybrid_tracker.py": (220766, "7772772f1baf0966a4b1096ac1cd3122d71edbe18031756de409443e7c5ea2ae"),
    "uw_frontend/tracking/klt_tracker.py": (12306, "e60957bc0b45a11ef24824fa95ef9093dbbd7ba5998bc82bb91641c831f1fb5b"),
    "uw_frontend/tracking/matcher_recovery.py": (30796, "3d65f84f0d81a85ec7ce97daa44b9885ed8726f4df4c330b76fa390a9eb46e70"),
    "uw_frontend/tracking/orb_tracker.py": (10987, "c8490ab98348a6e57b2b250df7faf52cc527206449e9a90778001c84d7e363b2"),
    "uw_frontend/tracking/pairwise_matcher_tracker.py": (17147, "c2796382afdf79f4ab6c06615390749a6a91e5d8b7cf1f239209ea51e47500c6"),
    "uw_frontend/tracking/track_state.py": (1181, "c6a5f23209f830088a33cf2afd733c3520d7da88e14a0f10c01e8d54ce384802"),
}
B1_YAML_EXTENDS_CLOSURE = {
    "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml": (1493, "6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3"),
    "uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml": (1478, "2a61f1c57a77df4ed6bf2d85c080c7e6bd754a2ff47171e526e0643a3d617a25"),
    "uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml": (1964, "4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce"),
    "uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml": (2121, "d5927fb412de869cfe9dd6275dfb81a566fc33e4149160bafc0e8fa933b27eed"),
    "uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml": (5453, "236e5173611731ffefd3acdd3b9f69429633dac16ae66429690d609fab0dd5d7"),
    "uw_frontend/configs/backend_strict_frontend.yaml": (9082, "908351d3d9547b98f917ffd059efdc7b279ee7f9199887688cda48e178a4855a"),
}
HFNET_PYTHON_RUNTIME_CLOSURE = {
    "scripts/export_aqualoc_a02_shared_4500_6300_v1.py": (36414, "c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f"),
    "scripts/export_aqualoc_to_hfnet_euroc_full_v2.py": (14829, "b13f56b69fd88799d4885c044c75bd41aa4331e688c22edaa2301c523ef42013"),
    "scripts/export_aqualoc_to_hfnet_euroc_v1.py": (32173, "7bc4fcdae60172b00c630ae35fba1515b8969cf1a403a33a2cdbc2847cb1b9b0"),
    "scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py": (52355, "165589aae498225d825b7a2e43586607475704fdbf98cba484a16346ffb245c4"),
    "scripts/run_hfnet_slam_a02_full901_headless_v3.py": (20668, "b5ad8731f7d50ed2dd5eb0e435f95ed2db9e854474c6d559ab6d21bcec4675a2"),
    "scripts/run_hfnet_slam_a02_long1801_headless_v4.py": (42063, "3cbf73588be58da7cd550b2deba42e0082968924bb9ed756684181720a38f41f"),
}
XFEAT_OFFICIAL_CLOSURE = {
    "external_tools/accelerated_features/modules/xfeat.py": (13472, "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7"),
    "external_tools/accelerated_features/modules/model.py": (4542, "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964"),
    "external_tools/accelerated_features/modules/interpolator.py": (1175, "d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da"),
    "external_tools/accelerated_features/weights/xfeat.pt": (6247949, "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b"),
    "external_tools/accelerated_features/LICENSE": (11357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
}


class VerificationError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_regular(path: Path, label: str) -> tuple[bytes, dict[str, object]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            payload = stream.read()
            metadata = os.fstat(stream.fileno())
    except OSError as error:
        raise VerificationError(f"{label}_NOT_REGULAR_NONSYMLINK:{error}") from error
    if not os.path.isfile(path) or path.is_symlink():
        raise VerificationError(f"{label}_NOT_REGULAR_NONSYMLINK")
    return payload, {
        "path": str(path.expanduser().resolve(strict=True)),
        "size_bytes": int(metadata.st_size),
        "sha256": sha256_bytes(payload),
    }


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def load_canonical_json(path: Path, label: str) -> tuple[dict[str, object], dict[str, object]]:
    payload, identity = read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{label}_INVALID_JSON") from error
    if not isinstance(value, dict) or payload != canonical_json(value):
        raise VerificationError(f"{label}_NOT_CANONICAL_OBJECT")
    return value, identity


def load_json_object(path: Path, label: str) -> tuple[dict[str, object], dict[str, object]]:
    payload, identity = read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{label}_INVALID_JSON") from error
    if not isinstance(value, dict):
        raise VerificationError(f"{label}_NOT_OBJECT")
    return value, identity


def require_file_identity(record: object, observed: Mapping[str, object], label: str) -> None:
    if not isinstance(record, Mapping):
        raise VerificationError(f"{label}_IDENTITY_NOT_OBJECT")
    required = {
        "path": observed["path"],
        "size_bytes": observed["size_bytes"],
        "sha256": observed["sha256"],
    }
    if any(record.get(key) != value for key, value in required.items()):
        raise VerificationError(f"{label}_IDENTITY_MISMATCH")


def exact_identity(path: Path, expected: str, label: str) -> dict[str, object]:
    _, identity = read_regular(path, label)
    if identity["sha256"] != expected:
        raise VerificationError(f"{label}_FROZEN_SHA256_MISMATCH")
    return identity


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def exact_closure_identities(
    expected: Mapping[str, tuple[int, str]], label: str
) -> dict[str, object]:
    result: dict[str, object] = {}
    for relative, (expected_size, expected_sha256) in sorted(expected.items()):
        path = ROOT / relative
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise VerificationError(f"{label}_MISSING:{relative}:{error}") from error
        if resolved != path.absolute() or path.is_symlink():
            raise VerificationError(f"{label}_SYMLINK_OR_PATH_ESCAPE:{relative}")
        identity = exact_identity(path, expected_sha256, f"{label}_{relative}")
        if identity["size_bytes"] != expected_size:
            raise VerificationError(f"{label}_SIZE_MISMATCH:{relative}")
        result[relative] = identity
    return result


def resolve_b1_python_runtime_closure() -> set[str]:
    package_root = ROOT / "uw_frontend"

    def module_path(name: str) -> Path | None:
        stem = ROOT.joinpath(*name.split("."))
        candidates = [stem.with_suffix(".py"), stem / "__init__.py"]
        existing = [candidate for candidate in candidates if candidate.is_file()]
        if len(existing) > 1:
            raise VerificationError(f"B1_PYTHON_IMPORT_DUPLICATE_MODULE:{name}")
        if not existing:
            return None
        candidate = existing[0]
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise VerificationError(f"B1_PYTHON_IMPORT_UNRESOLVED:{name}:{error}") from error
        if resolved != candidate.absolute() or not path_is_within(resolved, package_root):
            raise VerificationError(f"B1_PYTHON_IMPORT_SYMLINK_OR_PATH_ESCAPE:{name}")
        return candidate

    def module_name(path: Path) -> str:
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    entry = ROOT / "uw_frontend/ros/export_vins_features.py"
    pending = [entry]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        parent = path.parent
        while parent == package_root or package_root in parent.parents:
            initializer = parent / "__init__.py"
            if initializer.is_file() and initializer not in seen:
                pending.append(initializer)
            if parent == package_root:
                break
            parent = parent.parent
        payload, _ = read_regular(path, "B1_PYTHON_RUNTIME_SOURCE")
        try:
            tree = ast.parse(payload.decode("utf-8"), filename=str(path))
        except (UnicodeError, SyntaxError) as error:
            raise VerificationError(f"B1_PYTHON_IMPORT_PARSE_FAILED:{path}:{error}") from error
        current = module_name(path)
        current_package = current if path.name == "__init__.py" else current.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("uw_frontend"):
                        dependency = module_path(alias.name)
                        if dependency is None:
                            raise VerificationError(f"B1_PYTHON_IMPORT_UNRESOLVED:{alias.name}")
                        pending.append(dependency)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package_parts = current_package.split(".") if current_package else []
                    remove = node.level - 1
                    if remove > len(package_parts):
                        raise VerificationError("B1_PYTHON_RELATIVE_IMPORT_PATH_ESCAPE")
                    base = ".".join(package_parts[: len(package_parts) - remove])
                    imported_module = ".".join(
                        part for part in (base, node.module or "") if part
                    )
                else:
                    imported_module = node.module or ""
                if not imported_module.startswith("uw_frontend"):
                    continue
                dependency = module_path(imported_module)
                if dependency is None:
                    raise VerificationError(f"B1_PYTHON_IMPORT_UNRESOLVED:{imported_module}")
                pending.append(dependency)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    possible_submodule = f"{imported_module}.{alias.name}"
                    dependency = module_path(possible_submodule)
                    if dependency is not None:
                        pending.append(dependency)
    observed = {str(path.relative_to(ROOT)) for path in seen}
    expected = set(B1_PYTHON_RUNTIME_CLOSURE)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise VerificationError(
            f"B1_PYTHON_IMPORT_CLOSURE_SET_MISMATCH:MISSING={missing}:EXTRA={extra}"
        )
    return observed


def resolve_b1_yaml_extends_closure() -> set[str]:
    config_root = ROOT / "uw_frontend/configs"
    current = ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
    seen: set[Path] = set()
    while True:
        current = Path(os.path.abspath(os.path.normpath(str(current))))
        if current in seen:
            raise VerificationError(f"B1_YAML_EXTENDS_CYCLE:{current}")
        try:
            resolved = current.resolve(strict=True)
        except OSError as error:
            raise VerificationError(f"B1_YAML_EXTENDS_MISSING:{current}:{error}") from error
        if resolved != current or not path_is_within(resolved, config_root):
            raise VerificationError(f"B1_YAML_EXTENDS_SYMLINK_OR_PATH_ESCAPE:{current}")
        seen.add(current)
        payload, _ = read_regular(current, "B1_YAML_EXTENDS_SOURCE")
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeError as error:
            raise VerificationError(f"B1_YAML_EXTENDS_NOT_UTF8:{current}") from error
        extends_lines = [line for line in lines if re.match(r"^[ \t]*extends[ \t]*:", line)]
        if len(extends_lines) > 1:
            raise VerificationError(f"B1_YAML_EXTENDS_DUPLICATE:{current}")
        if not extends_lines:
            break
        match = re.fullmatch(r"extends:[ \t]+([A-Za-z0-9_./-]+)[ \t]*", extends_lines[0])
        if match is None:
            raise VerificationError(f"B1_YAML_EXTENDS_UNRESOLVED_SYNTAX:{current}")
        current = current.parent / match.group(1)
    observed = {str(path.relative_to(ROOT)) for path in seen}
    expected = set(B1_YAML_EXTENDS_CLOSURE)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise VerificationError(
            f"B1_YAML_EXTENDS_CLOSURE_SET_MISMATCH:MISSING={missing}:EXTRA={extra}"
        )
    return observed


def validate_b1_runtime_closures() -> dict[str, object]:
    python_set = resolve_b1_python_runtime_closure()
    yaml_set = resolve_b1_yaml_extends_closure()
    return {
        "schema_version": "aqua-fe-b1-python-local-import-and-yaml-extends-closure-v1",
        "python_runtime_file_count": len(python_set),
        "python_runtime_files": exact_closure_identities(
            B1_PYTHON_RUNTIME_CLOSURE, "B1_PYTHON_RUNTIME_CLOSURE"
        ),
        "yaml_extends_file_count": len(yaml_set),
        "yaml_extends_files": exact_closure_identities(
            B1_YAML_EXTENDS_CLOSURE, "B1_YAML_EXTENDS_CLOSURE"
        ),
    }


def validate_hfnet_python_runtime_closure() -> dict[str, object]:
    def module_path(name: str) -> Path | None:
        stem = ROOT.joinpath(*name.split("."))
        candidates = [stem.with_suffix(".py"), stem / "__init__.py"]
        existing = [candidate for candidate in candidates if candidate.is_file()]
        if len(existing) > 1:
            raise VerificationError(f"HFNET_PYTHON_IMPORT_DUPLICATE_MODULE:{name}")
        if not existing:
            return None
        candidate = existing[0]
        resolved = candidate.resolve(strict=True)
        if resolved != candidate.absolute() or not path_is_within(resolved, ROOT / "scripts"):
            raise VerificationError(f"HFNET_PYTHON_IMPORT_SYMLINK_OR_PATH_ESCAPE:{name}")
        return candidate

    pending = [ROOT / "scripts/run_hfnet_slam_a02_long1801_headless_v4.py"]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        payload, _ = read_regular(path, "HFNET_PYTHON_RUNTIME_SOURCE")
        try:
            tree = ast.parse(payload.decode("utf-8"), filename=str(path))
        except (UnicodeError, SyntaxError) as error:
            raise VerificationError(f"HFNET_PYTHON_IMPORT_PARSE_FAILED:{path}:{error}") from error
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module]
                names.extend(
                    f"{module}.{alias.name}" for alias in node.names if alias.name != "*"
                )
            for name in names:
                if not name.startswith("scripts"):
                    continue
                dependency = module_path(name)
                if dependency is not None:
                    pending.append(dependency)
                elif name.count(".") == 1:
                    raise VerificationError(f"HFNET_PYTHON_IMPORT_UNRESOLVED:{name}")
    observed = {str(path.relative_to(ROOT)) for path in seen}
    expected = set(HFNET_PYTHON_RUNTIME_CLOSURE)
    if observed != expected:
        raise VerificationError(
            "HFNET_PYTHON_IMPORT_CLOSURE_SET_MISMATCH:"
            f"MISSING={sorted(expected - observed)}:EXTRA={sorted(observed - expected)}"
        )
    return {
        "schema_version": "aqua-fe-hfnet-python-local-import-closure-v1",
        "runtime_file_count": len(observed),
        "runtime_files": exact_closure_identities(
            HFNET_PYTHON_RUNTIME_CLOSURE, "HFNET_PYTHON_RUNTIME_CLOSURE"
        ),
    }


def validate_xfeat_audit_runtime() -> dict[str, object]:
    try:
        resolved_interpreter = XFEAT_AUDIT_PYTHON.resolve(strict=True)
    except OSError as error:
        raise VerificationError(f"XFEAT_AUDIT_VENV_PYTHON_MISSING:{error}") from error
    if resolved_interpreter != XFEAT_AUDIT_BASE_INTERPRETER:
        raise VerificationError("XFEAT_AUDIT_VENV_PYTHON_RESOLUTION_MISMATCH")
    interpreter = exact_identity(
        XFEAT_AUDIT_BASE_INTERPRETER,
        XFEAT_AUDIT_BASE_INTERPRETER_SHA256,
        "XFEAT_AUDIT_BASE_INTERPRETER",
    )
    core = exact_identity(
        XFEAT_AUDIT_CV2_CORE,
        XFEAT_AUDIT_CV2_CORE_SHA256,
        "XFEAT_AUDIT_CV2_CORE",
    )
    numpy_identity = exact_identity(
        XFEAT_AUDIT_NUMPY,
        XFEAT_AUDIT_NUMPY_SHA256,
        "XFEAT_AUDIT_NUMPY",
    )
    if interpreter["size_bytes"] != XFEAT_AUDIT_BASE_INTERPRETER_SIZE:
        raise VerificationError("XFEAT_AUDIT_BASE_INTERPRETER_SIZE_MISMATCH")
    if core["size_bytes"] != XFEAT_AUDIT_CV2_CORE_SIZE:
        raise VerificationError("XFEAT_AUDIT_CV2_CORE_SIZE_MISMATCH")
    if numpy_identity["size_bytes"] != XFEAT_AUDIT_NUMPY_SIZE:
        raise VerificationError("XFEAT_AUDIT_NUMPY_SIZE_MISMATCH")
    probe_source = (
        "import cv2,json,numpy,pathlib,rosbag; "
        "core=(pathlib.Path(tuple(cv2.__path__)[0])/'cv2.abi3.so').resolve(); "
        "print(json.dumps({'version':cv2.__version__,'core':str(core),"
        "'rosbag':str(pathlib.Path(rosbag.__file__).resolve()),"
        "'numpy_version':numpy.__version__,"
        "'numpy_file':str(pathlib.Path(numpy.__file__).resolve())},sort_keys=True))"
    )
    audit_env = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": "/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
        "PYTHONPATH": "/opt/ros/noetic/lib/python3/dist-packages",
    }
    try:
        completed = subprocess.run(
            [str(XFEAT_AUDIT_PYTHON), "-c", probe_source],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
            env=audit_env,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError(f"XFEAT_AUDIT_RUNTIME_PROBE_FAILED:{error}") from error
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VerificationError("XFEAT_AUDIT_RUNTIME_PROBE_NOT_JSON") from error
    if (
        completed.returncode != 0
        or probe
        != {
            "version": "4.10.0",
            "core": str(XFEAT_AUDIT_CV2_CORE),
            "rosbag": "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
            "numpy_version": "1.17.4",
            "numpy_file": str(XFEAT_AUDIT_NUMPY),
        }
    ):
        raise VerificationError("XFEAT_AUDIT_RUNTIME_PROBE_IDENTITY_MISMATCH")
    return {
        "status": "PASS",
        "venv_python": str(XFEAT_AUDIT_PYTHON),
        "resolved_interpreter": interpreter,
        "cv2_version": "4.10.0",
        "cv2_core": core,
        "numpy_version": "1.17.4",
        "numpy_module": numpy_identity,
        "rosbag_module": "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
        "sealed_environment": audit_env,
    }


def validate_xfeat_export_runtime() -> dict[str, object]:
    identities: dict[str, object] = {}
    for raw_path, (expected_size, expected_sha256) in sorted(
        XFEAT_EXPORT_RUNTIME_FILES.items()
    ):
        identity = exact_identity(
            Path(raw_path), expected_sha256, f"XFEAT_EXPORT_RUNTIME_{raw_path}"
        )
        if identity["size_bytes"] != expected_size:
            raise VerificationError(f"XFEAT_EXPORT_RUNTIME_SIZE_MISMATCH:{raw_path}")
        identities[raw_path] = identity
    export_env = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": "/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
        "CUDA_VISIBLE_DEVICES": "0",
        "PYTHONPATH": (
            f"{ROOT}:/home/ma/.local/lib/python3.8/site-packages:"
            "/opt/ros/noetic/lib/python3/dist-packages"
        ),
    }
    probe_source = (
        "import cv2,json,numpy,pathlib,rosbag,torch; "
        "print(json.dumps({'torch_version':torch.__version__,"
        "'torch_cuda':torch.version.cuda,'cuda_available':torch.cuda.is_available(),"
        "'torch_file':str(pathlib.Path(torch.__file__).resolve()),"
        "'torch_c_file':str(pathlib.Path(torch._C.__file__).resolve()),"
        "'torch_num_threads':torch.get_num_threads(),"
        "'torch_num_interop_threads':torch.get_num_interop_threads(),"
        "'torch_mkldnn_enabled':torch.backends.mkldnn.enabled,"
        "'torch_deterministic_algorithms':torch.are_deterministic_algorithms_enabled(),"
        "'torch_cudnn_deterministic':torch.backends.cudnn.deterministic,"
        "'torch_cudnn_benchmark':torch.backends.cudnn.benchmark,"
        "'numpy_version':numpy.__version__,"
        "'numpy_file':str(pathlib.Path(numpy.__file__).resolve()),"
        "'cv2_version':cv2.__version__,'cv2_file':str(pathlib.Path(cv2.__file__).resolve()),"
        "'rosbag_file':str(pathlib.Path(rosbag.__file__).resolve())},sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(XFEAT_AUDIT_BASE_INTERPRETER), "-c", probe_source],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
            env=export_env,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError(f"XFEAT_EXPORT_RUNTIME_PROBE_FAILED:{error}") from error
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VerificationError("XFEAT_EXPORT_RUNTIME_PROBE_NOT_JSON") from error
    expected_probe = {
        "torch_version": "2.2.2+cpu",
        "torch_cuda": None,
        "cuda_available": False,
        "torch_file": "/home/ma/.local/lib/python3.8/site-packages/torch/__init__.py",
        "torch_c_file": "/home/ma/.local/lib/python3.8/site-packages/torch/_C.cpython-38-x86_64-linux-gnu.so",
        "torch_num_threads": 6,
        "torch_num_interop_threads": 12,
        "torch_mkldnn_enabled": True,
        "torch_deterministic_algorithms": False,
        "torch_cudnn_deterministic": False,
        "torch_cudnn_benchmark": False,
        "numpy_version": "1.24.4",
        "numpy_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py",
        "cv2_version": "4.2.0",
        "cv2_file": "/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so",
        "rosbag_file": "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
    }
    if completed.returncode != 0 or probe != expected_probe:
        raise VerificationError("XFEAT_EXPORT_RUNTIME_PROBE_IDENTITY_MISMATCH")
    return {
        "status": "PASS_FROZEN_CPU_RUNTIME",
        "files": identities,
        "probe": probe,
        "sealed_environment": export_env,
        "external_timeout_policy": "NO_SHORT_TIMEOUT_EXPECT_10_TO_15_MINUTES_CPU",
    }


def sealed_evaluation_environment() -> dict[str, str]:
    return {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": "/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
        "PYTHONPATH": (
            f"{ROOT}:/home/ma/.local/lib/python3.8/site-packages:"
            "/opt/ros/noetic/lib/python3/dist-packages"
        ),
    }


def sealed_evaluation_python_prefix() -> str:
    assignments = " ".join(
        f"{key}={value}" for key, value in sealed_evaluation_environment().items()
    )
    return (
        "test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && "
        f"/usr/bin/env -i {assignments} /usr/bin/python3.8 -B"
    )


def validate_evaluation_runtime() -> dict[str, object]:
    pycache_prefix = Path(sealed_evaluation_environment()["PYTHONPYCACHEPREFIX"])
    if pycache_prefix.exists() or pycache_prefix.is_symlink():
        raise VerificationError("EVALUATION_RUNTIME_RESERVED_PYCACHE_PREFIX_NOT_ABSENT")
    identities: dict[str, object] = {}
    for raw_path, (expected_size, expected_sha256) in sorted(
        EVALUATION_RUNTIME_FILES.items()
    ):
        identity = exact_identity(
            Path(raw_path), expected_sha256, f"EVALUATION_RUNTIME_{raw_path}"
        )
        if identity["size_bytes"] != expected_size:
            raise VerificationError(f"EVALUATION_RUNTIME_SIZE_MISMATCH:{raw_path}")
        identities[raw_path] = identity

    record_path = Path(
        "/home/ma/.local/lib/python3.8/site-packages/evo-1.31.1.dist-info/RECORD"
    )
    record_payload, _ = read_regular(record_path, "EVO_DISTRIBUTION_RECORD")
    try:
        rows = list(csv.reader(record_payload.decode("utf-8").splitlines()))
    except (UnicodeError, csv.Error) as error:
        raise VerificationError(f"EVO_DISTRIBUTION_RECORD_INVALID:{error}") from error
    site_root = Path("/home/ma/.local/lib/python3.8/site-packages")
    hashed_rows = 0
    for index, row in enumerate(rows):
        if len(row) != 3:
            raise VerificationError(f"EVO_DISTRIBUTION_RECORD_ROW_{index}_SHAPE")
        relative, digest_record, size_record = row
        if not digest_record:
            continue
        if not digest_record.startswith("sha256=") or not size_record.isdigit():
            raise VerificationError(f"EVO_DISTRIBUTION_RECORD_ROW_{index}_HASH_OR_SIZE")
        path = (site_root / relative).resolve(strict=True)
        if not path_is_within(path, Path("/home/ma/.local")):
            raise VerificationError(f"EVO_DISTRIBUTION_RECORD_ROW_{index}_PATH_ESCAPE")
        payload, identity = read_regular(path, f"EVO_DISTRIBUTION_FILE_{index}")
        encoded = digest_record.split("=", 1)[1]
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        expected_digest = base64.urlsafe_b64decode(encoded + padding).hex()
        if (
            identity["sha256"] != expected_digest
            or identity["size_bytes"] != int(size_record)
            or len(payload) != int(size_record)
        ):
            raise VerificationError(f"EVO_DISTRIBUTION_RECORD_ROW_{index}_DRIFT")
        hashed_rows += 1
    if len(rows) != 91 or hashed_rows != 52:
        raise VerificationError("EVO_DISTRIBUTION_RECORD_CARDINALITY_MISMATCH")

    probe_source = (
        "import cv2,evo,geometry_msgs.msg,json,nav_msgs.msg,numpy,pathlib,rosbag,rospy,sensor_msgs.msg,shutil,std_msgs.msg; "
        "import numpy.core._multiarray_umath as multiarray; "
        "import numpy.linalg._umath_linalg as umath_linalg; "
        "import numpy.linalg.lapack_lite as lapack_lite; "
        "import numpy.lib.function_base as function_base; "
        "from evo import main_ape,main_rpe; from evo.tools import settings; "
        "a=numpy.array([[1.,2.,3.],[4.,5.,6.],[7.,8.,10.]],dtype=numpy.float64); "
        "print(json.dumps({'evo_version':evo.__version__,"
        "'evo_file':str(pathlib.Path(evo.__file__).resolve()),"
        "'numpy_version':numpy.__version__,"
        "'numpy_file':str(pathlib.Path(numpy.__file__).resolve()),"
        "'multiarray_file':str(pathlib.Path(multiarray.__file__).resolve()),"
        "'linalg_file':str(pathlib.Path(numpy.linalg.linalg.__file__).resolve()),"
        "'umath_linalg_file':str(pathlib.Path(umath_linalg.__file__).resolve()),"
        "'lapack_lite_file':str(pathlib.Path(lapack_lite.__file__).resolve()),"
        "'function_base_file':str(pathlib.Path(function_base.__file__).resolve()),"
        "'svd_hex':[float(x).hex() for x in numpy.linalg.svd(a,compute_uv=False)],"
        "'float64_eps_hex':float(numpy.finfo(numpy.float64).eps).hex(),"
        "'longdouble_bits':numpy.finfo(numpy.longdouble).bits,"
        "'longdouble_nmant':numpy.finfo(numpy.longdouble).nmant,"
        "'evo_ape':shutil.which('evo_ape'),'evo_rpe':shutil.which('evo_rpe'),"
        "'main_ape_file':str(pathlib.Path(main_ape.__file__).resolve()),"
        "'main_rpe_file':str(pathlib.Path(main_rpe.__file__).resolve()),"
        "'settings_path':str(pathlib.Path(settings.DEFAULT_PATH).resolve()),"
        "'assets_version_path':str(pathlib.Path(settings.USER_ASSETS_VERSION_PATH).resolve()),"
        "'cv2_file':str(pathlib.Path(cv2.__file__).resolve()),"
        "'rosbag_file':str(pathlib.Path(rosbag.__file__).resolve()),"
        "'rospy_file':str(pathlib.Path(rospy.__file__).resolve()),"
        "'geometry_msgs_file':str(pathlib.Path(geometry_msgs.msg.__file__).resolve()),"
        "'nav_msgs_file':str(pathlib.Path(nav_msgs.msg.__file__).resolve()),"
        "'sensor_msgs_file':str(pathlib.Path(sensor_msgs.msg.__file__).resolve()),"
        "'std_msgs_file':str(pathlib.Path(std_msgs.msg.__file__).resolve())},sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(XFEAT_AUDIT_BASE_INTERPRETER), "-B", "-c", probe_source],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
            env=sealed_evaluation_environment(),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError(f"EVALUATION_RUNTIME_PROBE_FAILED:{error}") from error
    expected_probe = {
        "evo_version": "v1.31.1",
        "evo_file": "/home/ma/.local/lib/python3.8/site-packages/evo/__init__.py",
        "numpy_version": "1.24.4",
        "numpy_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py",
        "multiarray_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/core/_multiarray_umath.cpython-38-x86_64-linux-gnu.so",
        "linalg_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/linalg.py",
        "umath_linalg_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/_umath_linalg.cpython-38-x86_64-linux-gnu.so",
        "lapack_lite_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/lapack_lite.cpython-38-x86_64-linux-gnu.so",
        "function_base_file": "/home/ma/.local/lib/python3.8/site-packages/numpy/lib/function_base.py",
        "svd_hex": [
            "0x1.16999f048dfbbp+4",
            "0x1.c0152602e522bp-1",
            "0x1.932ec12f0363cp-3",
        ],
        "float64_eps_hex": "0x1.0000000000000p-52",
        "longdouble_bits": 128,
        "longdouble_nmant": 63,
        "evo_ape": "/home/ma/.local/bin/evo_ape",
        "evo_rpe": "/home/ma/.local/bin/evo_rpe",
        "main_ape_file": "/home/ma/.local/lib/python3.8/site-packages/evo/main_ape.py",
        "main_rpe_file": "/home/ma/.local/lib/python3.8/site-packages/evo/main_rpe.py",
        "settings_path": "/home/ma/.evo/settings.json",
        "assets_version_path": "/home/ma/.evo/assets_version",
        "cv2_file": "/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so",
        "rosbag_file": "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
        "rospy_file": "/opt/ros/noetic/lib/python3/dist-packages/rospy/__init__.py",
        "geometry_msgs_file": "/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/msg/__init__.py",
        "nav_msgs_file": "/opt/ros/noetic/lib/python3/dist-packages/nav_msgs/msg/__init__.py",
        "sensor_msgs_file": "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/__init__.py",
        "std_msgs_file": "/opt/ros/noetic/lib/python3/dist-packages/std_msgs/msg/__init__.py",
    }
    try:
        observed_probe = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VerificationError("EVALUATION_RUNTIME_PROBE_NOT_JSON") from error
    if completed.returncode != 0 or observed_probe != expected_probe:
        raise VerificationError("EVALUATION_RUNTIME_PROBE_IDENTITY_MISMATCH")
    return {
        "status": "PASS_FROZEN_NUMPY1244_EVO1311",
        "files": identities,
        "evo_record_rows": len(rows),
        "evo_record_hashed_rows": hashed_rows,
        "probe": observed_probe,
        "sealed_environment": sealed_evaluation_environment(),
    }


def validate_xfeat_official_closure() -> dict[str, object]:
    identities: dict[str, object] = {}
    for relative, (expected_size, expected_sha256) in sorted(XFEAT_OFFICIAL_CLOSURE.items()):
        path = ROOT / relative
        identity = exact_identity(path, expected_sha256, f"XFEAT_OFFICIAL_CLOSURE_{relative}")
        if identity["size_bytes"] != expected_size:
            raise VerificationError(f"XFEAT_OFFICIAL_CLOSURE_SIZE_MISMATCH:{relative}")
        identities[relative] = identity
    return {
        "status": "PASS",
        "upstream_commit": "e92685f57f8318b18725c5c8c0bd28c7fe188d9a",
        "file_count": len(identities),
        "files": identities,
    }


def constq_quality_gate_command() -> str:
    return (
        f"{sealed_evaluation_python_prefix()} -c 'import json,pathlib; "
        f'p=pathlib.Path("{DEFAULT_B1_QUALITY_AUDIT}"); '
        "d=json.loads(p.read_text()); "
        'ok=(d.get("schema_version")=="aqua-fe-quality-partition-audit-v1" '
        'and d.get("contract_pass") is True and d.get("feature_frames")==900 '
        'and d.get("selected_observations")==315000 '
        'and d.get("untouched_observations")==0 and d.get("quality")==1.0 '
        'and d.get("sigma")==1.0 '
        'and d.get("total_messages")==d.get("raw_equal_nonfeature_messages",-1)+d.get("feature_frames",-2)); '
        "raise SystemExit(0 if ok else 2)'"
    )


def xfeat_audit_gate_command() -> str:
    return (
        f"{sealed_evaluation_python_prefix()} -c 'import json,pathlib; "
        f'p=pathlib.Path("{DEFAULT_XFEAT_AUDIT}"); '
        "d=json.loads(p.read_text()); i=d.get(\"input\",{}); m=d.get(\"method\",{}); "
        'ok=(d.get("schema_version")=="aqua-fe-xfeat-lk-carrier-audit-v1" '
        'and d.get("status")=="PASS" and d.get("pass") is True '
        f'and i.get("candidate_bag")=="{DEFAULT_XFEAT_BAG.resolve(strict=False)}" '
        'and m.get("method_id")=="xfeat_detector_raw_frame_lk_carrier_v1" '
        'and m.get("expected_source_code")==20 and m.get("expected_observations_per_frame")==350); '
        "raise SystemExit(0 if ok else 2)'"
    )


def expected_xfeat_export_command() -> str:
    invocation = (
        "test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && "
        "/usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash "
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 "
        "PYTHONDONTWRITEBYTECODE=1 "
        "PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 "
        "CUDA_VISIBLE_DEVICES=0 "
        f"PYTHONPATH={ROOT}:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages "
        "/usr/bin/python3.8 scripts/export_xfeat_lk_carrier_v1.py "
        f"--source-feature-bag {DEFAULT_B1_CONSTQ_BAG} "
        f"--raw-image-bag {DEFAULT_WINDOW_BAG} "
        f"--camera-yaml {DEFAULT_B1_NATIVE_CAMERA} "
        f"--output-bag {DEFAULT_XFEAT_BAG} "
        "--image-topic /camera/image_raw --feature-topic /feature_tracker/feature "
        f"--manifest-json {DEFAULT_XFEAT_MANIFEST}"
    )
    output_dir = DEFAULT_XFEAT_BAG.parent
    return (
        "xfeat_export_rc=125; "
        f"if {constq_quality_gate_command()}; then "
        f"if [ ! -e {output_dir} ]; then xfeat_export_rc=0; "
        f"/usr/bin/mkdir {output_dir} && {invocation} || xfeat_export_rc=$?; "
        "else xfeat_export_rc=73; fi; fi; "
        "printf 'XFEAT_EXPORT_RC=%s\\n' \"$xfeat_export_rc\""
    )


def expected_xfeat_audit_command() -> str:
    invocation = (
        "test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && "
        "/usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash "
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 "
        "PYTHONDONTWRITEBYTECODE=1 "
        "PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 "
        "PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages "
        f"{XFEAT_AUDIT_PYTHON} scripts/audit_xfeat_lk_carrier_v1.py "
        f"--reference-bag {DEFAULT_B1_CONSTQ_BAG} "
        f"--candidate-bag {DEFAULT_XFEAT_BAG} "
        f"--camera-yaml {DEFAULT_B1_NATIVE_CAMERA} "
        "--feature-topic /feature_tracker/feature "
        f"--output-json {DEFAULT_XFEAT_AUDIT}"
    )
    return (
        "xfeat_audit_rc=125; "
        f"if [ -f {DEFAULT_XFEAT_BAG} ] && [ -f {DEFAULT_XFEAT_MANIFEST} ] "
        f"&& [ ! -e {DEFAULT_XFEAT_AUDIT} ]; then xfeat_audit_rc=0; "
        f"{invocation} || xfeat_audit_rc=$?; fi; "
        "printf 'XFEAT_AUDIT_RC=%s\\n' \"$xfeat_audit_rc\""
    )


def expected_vins_replay_command(
    *, rc_variable: str, rc_label: str, feature_bag: Path, port: int, tag: str
) -> str:
    raw_root = ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    assignments = (
        "HOME=/home/ma",
        "USER=ma",
        "LOGNAME=ma",
        "SHELL=/bin/bash",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "ROS_DISTRO=noetic",
        f"ROS_MASTER_URI=http://localhost:{port}",
        "PYTHONNOUSERSITE=1",
        "PYTHONHASHSEED=0",
        "CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel",
        "CATKIN_SETUP_UTIL_ARGS='--local --extend'",
        f"ROOT={ROOT}",
        "VINS_WS=/home/ma/SLAM/VINS-Fusion-origin",
        f"AQUALOC_ROOT={raw_root}",
        f"RAW_TAR={raw_root / 'archaeo_sequence_2_raw_data.tar.gz'}",
        "RAW_ROOT=raw_data",
        f"GT_TXT={raw_root / 'archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt'}",
        f"RAW_BAG={DEFAULT_WINDOW_BAG}",
        f"FEATURE_BAG_OVERRIDE={feature_bag}",
        f"FRONTEND_CONFIG={ROOT / 'uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml'}",
        "BACKEND_REPLAY_ONLY=0",
        "RUN_VINS=1",
        "FORCE_RAW=0",
        "FORCE_EXPORT=0",
        "EXPORT_FEATURES=0",
        "VINS_MULTIPLE_THREAD=0",
        "VINS_TD=-0.053694112369382575",
        "VINS_ESTIMATE_TD=0",
        "VINS_MAX_SOLVER_TIME=0.04",
        "VINS_MAX_NUM_ITERATIONS=8",
        "AQUALOC_BODY_T_CAM0_MODE=imu_cam",
        "PLAY_RATE=1.0",
        "POST_PLAY_SLEEP=8",
        "ROSBAG_PLAY_DELAY=3",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS=0",
        "ROSBAG_PLAY_TOPICS=",
        "WAIT_FOR_VINS_SUBSCRIBERS=0",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT=20",
        f"PORT={port}",
        f"TAG={tag}",
    )
    invocation = " ".join(
        (
            "/usr/bin/env",
            "-i",
            *assignments,
            "/bin/bash",
            "--noprofile",
            "--norc",
            str(ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"),
            "external",
            "2",
            "4500",
            "6300",
            "klt",
            "2",
        )
    )
    arm = "B1_CONSTQ" if rc_variable == "b1_vins_rc" else "XFEATBIRTH_RAWLK"
    receipt_variable = "b1_receipt_rc" if rc_variable == "b1_vins_rc" else "xfeat_receipt_rc"
    dependency_gate = (
        constq_quality_gate_command()
        if arm == "B1_CONSTQ"
        else xfeat_audit_gate_command()
    )
    run_dir = DEFAULT_B1.parents[1] if arm == "B1_CONSTQ" else DEFAULT_XFEAT.parents[1]
    return (
        f"{rc_variable}=125; if {dependency_gate}; then "
        f"if [ ! -e {run_dir} ]; then {rc_variable}=0; {invocation} || {rc_variable}=$?; "
        f"else {rc_variable}=73; fi; fi; "
        f"{receipt_variable}=0; {sealed_evaluation_python_prefix()} scripts/verify_a02_long_three_arm_eval_inputs_v1.py "
        f"--action seal-arm-rc --arm {arm} --return-code \"${rc_variable}\" || {receipt_variable}=$?; "
        f"printf '{rc_label}=%s\\n' \"${rc_variable}\"; "
        f"printf '{arm}_RECEIPT_RC=%s\\n' \"${receipt_variable}\""
    )


def expected_hfnet_bridge_command() -> str:
    result = DEFAULT_V4_RESULT.resolve(strict=False)
    trajectory = DEFAULT_HFNET_SOURCE.resolve(strict=False)
    output = DEFAULT_HFNET.resolve(strict=False)
    result_gate = (
        f"{sealed_evaluation_python_prefix()} -c 'import json,pathlib; "
        f'p=pathlib.Path("{result}"); '
        "d=json.loads(p.read_text()); "
        'ok=(d.get("schema_version")=="aqua-fe-hfnet-slam-a02-long1801-headless-result-v4" '
        'and d.get("status")=="PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE" '
        'and d.get("return_code")==0 and d.get("evaluable") is True); '
        "raise SystemExit(0 if ok else 2)'"
    )
    bridge = (
        f"{sealed_evaluation_python_prefix()} scripts/bridge_hfnet_world_body_to_vins_csv_v1.py --action convert "
        f"--input {trajectory} --output {output} --run-result-json {result}"
    )
    return (
        "hfnet_bridge_rc=2; "
        f"if {result_gate}; then hfnet_bridge_rc=0; {bridge} || hfnet_bridge_rc=$?; fi; "
        "printf 'HFNET_BRIDGE_RC=%s\\n' \"$hfnet_bridge_rc\""
    )


def expected_evaluator_command() -> str:
    return (
        f"{sealed_evaluation_python_prefix()} scripts/evaluate_vins_common_support.py "
        f"--reference-tum {DEFAULT_SHARED_ROOT / 'shared/reference_proxy.tum'} "
        f"--arm B1_CONSTQ={DEFAULT_B1} "
        f"--arm XFEATBIRTH_RAWLK={DEFAULT_XFEAT} "
        f"--arm HFNET_WHOLE_SYSTEM={DEFAULT_HFNET} "
        f"--arm-config B1_CONSTQ={DEFAULT_EVAL_CONFIG} "
        f"--arm-config XFEATBIRTH_RAWLK={DEFAULT_EVAL_CONFIG} "
        f"--arm-config HFNET_WHOLE_SYSTEM={DEFAULT_EVAL_CONFIG} "
        "--nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 "
        "--evaluation-rate-hz 1 --max-reference-gap-s 2.5 "
        "--max-estimate-gap-s 0.25 --window-start-s 1542829061.692686528 "
        "--window-end-s 1542829106.687510592 --rpe-delta-s 1 "
        "--min-ape-poses 30 --min-ape-span-s 10 --min-common-coverage 0.70 "
        "--min-rpe-pairs 10 --contrast-name A02_4500_6300_POST_STOP_B1_XFEAT_HFNET "
        f"--output-dir {DEFAULT_EVAL_DIR} --run-evo"
    )


def exclusive_eval_dir_claim_command() -> str:
    return (
        f"/usr/bin/mkdir -p {DEFAULT_EVAL_DIR.parent} && "
        f"/usr/bin/mkdir {DEFAULT_EVAL_DIR}"
    )


def expected_final_gate_command() -> str:
    verifier = (
        f"{sealed_evaluation_python_prefix()} "
        "scripts/verify_a02_long_three_arm_eval_inputs_v1.py"
    )
    return (
        f"pre_seal_rc=0; {verifier} --action seal || pre_seal_rc=$?; "
        "pre_check_rc=2; if [ -e /home/ma/AQUA-FE_WS/papers/a02_4500_6300_three_arm_pre_eval_verification_v1.json ]; then "
        f"pre_check_rc=0; {verifier} --action check || pre_check_rc=$?; fi; "
        "if [ \"$pre_seal_rc\" -eq 0 ] && [ \"$pre_check_rc\" -eq 0 ]; then "
        f"eval_dir_claim_rc=0; {exclusive_eval_dir_claim_command()} || eval_dir_claim_rc=$?; "
        "if [ \"$eval_dir_claim_rc\" -eq 0 ]; then "
        f"eval_rc=0; {expected_evaluator_command()} || eval_rc=$?; "
        "if [ \"$eval_rc\" -eq 0 ]; then "
        f"post_seal_rc=0; {verifier} --action seal-evaluation || post_seal_rc=$?; "
        f"post_check_rc=2; if [ -e {DEFAULT_POST_EVAL_OUTPUT} ]; then "
        f"post_check_rc=0; {verifier} --action check-evaluation || post_check_rc=$?; fi; "
        "if [ \"$post_seal_rc\" -eq 0 ] && [ \"$post_check_rc\" -eq 0 ]; then "
        "echo THREE_ARM_G0_STRICT_PASS; exit 0; "
        "else echo THREE_ARM_G0_POST_GATE_FAILED_NO_RANKING; exit 2; fi; "
        "else echo THREE_ARM_G0_EVALUATOR_FAILED_NO_RANKING; exit 2; fi; "
        "else echo THREE_ARM_G0_EVAL_DIR_CLAIM_FAILED_NO_EVALUATOR; exit 2; fi; "
        "else echo THREE_ARM_G0_SKIPPED_REPORT_USABILITY_WITHOUT_RANKING; exit 2; fi"
    )


def authoritative_commands() -> list[str]:
    project_python = sealed_evaluation_python_prefix()
    static_gate = (
        f"{project_python} scripts/verify_a02_long_three_arm_eval_inputs_v1.py "
        "--action check-static || exit $?"
    )
    start_gate = (
        f"{project_python} scripts/verify_a02_long_three_arm_eval_inputs_v1.py "
        "--action check-start || exit $?"
    )
    decision_dir = Path(
        "/mnt/data/AQUA-FE_WS/logs/backend_contract_decisions/b1/"
        "litcmp_a02_4500_6300_preroll_b1_native_r1"
    )
    b1_native_run_dir = DEFAULT_B1_NATIVE_BAG.parent
    b1_native = (
        "b1_native_rc=0; /usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma "
        "SHELL=/bin/bash PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "LANG=C.UTF-8 LC_ALL=C.UTF-8 "
        f"AQUAFE_B1_V4_DECISION_DIR={decision_dir} RUN_VINS=0 FORCE_RAW=0 "
        "FORCE_EXPORT=0 TAG=litcmp_a02_4500_6300_preroll_b1_native_r1 "
        "/bin/bash --noprofile --norc "
        "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh "
        "aqualoc_archaeology A02 4500 6300 2 || b1_native_rc=$?; "
        "printf 'B1_NATIVE_EXPORT_RC=%s\\n' \"$b1_native_rc\""
    )
    constq_dir = DEFAULT_B1_CONSTQ_BAG.parent
    constq_rewrite = (
        "constq_rewrite_rc=125; "
        f"if [ -f {DEFAULT_B1_NATIVE_BAG} ] && [ ! -e {constq_dir} ]; then "
        f"constq_rewrite_rc=0; /usr/bin/mkdir {constq_dir} && "
        f"{project_python} scripts/agent_qi_calibration_rewrite_bag.py "
        f"--input-bag {DEFAULT_B1_NATIVE_BAG} --output-bag {DEFAULT_B1_CONSTQ_BAG} "
        "--schedule constq --feature-topic /feature_tracker/feature "
        f"--stats-csv {constq_dir / 'constq_stats.csv'} || constq_rewrite_rc=$?; fi; "
        "printf 'CONSTQ_REWRITE_RC=%s\\n' \"$constq_rewrite_rc\""
    )
    constq_audit = (
        "constq_audit_rc=125; "
        f"if [ -f {DEFAULT_B1_NATIVE_BAG} ] && [ -f {DEFAULT_B1_CONSTQ_BAG} ] "
        f"&& [ ! -e {DEFAULT_B1_QUALITY_AUDIT} ]; then constq_audit_rc=0; "
        f"{project_python} scripts/audit_quality_partition.py "
        f"--input-bag {DEFAULT_B1_NATIVE_BAG} --output-bag {DEFAULT_B1_CONSTQ_BAG} "
        f"--audit-json {DEFAULT_B1_QUALITY_AUDIT} --feature-topic /feature_tracker/feature "
        "--source-code 1 --quality 1 --min-quality 0.05 || constq_audit_rc=$?; fi; "
        "printf 'CONSTQ_AUDIT_RC=%s\\n' \"$constq_audit_rc\""
    )
    constq_gate = (
        f"constq_gate_rc=0; {constq_quality_gate_command()} || constq_gate_rc=$?; "
        "printf 'CONSTQ_CONTRACT_GATE_RC=%s\\n' \"$constq_gate_rc\""
    )
    b1_vins = expected_vins_replay_command(
        rc_variable="b1_vins_rc",
        rc_label="B1_CONSTQ_VINS_RC",
        feature_bag=DEFAULT_B1_CONSTQ_BAG,
        port=11531,
        tag="litcmp_a02_4500_6300_preroll_b1_constq_vins_r1",
    )
    xfeat_vins = expected_vins_replay_command(
        rc_variable="xfeat_vins_rc",
        rc_label="XFEATBIRTH_RAWLK_VINS_RC",
        feature_bag=DEFAULT_XFEAT_BAG,
        port=11532,
        tag="litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1",
    )
    hfnet_preflight = (
        f"hfnet_preflight_rc=0; {project_python} scripts/run_hfnet_slam_a02_long1801_headless_v4.py "
        "--action preflight || hfnet_preflight_rc=$?; "
        "printf 'HFNET_PREFLIGHT_RC=%s\\n' \"$hfnet_preflight_rc\""
    )
    hfnet_freeze = (
        f"hfnet_freeze_rc=0; {project_python} scripts/run_hfnet_slam_a02_long1801_headless_v4.py "
        "--action freeze || hfnet_freeze_rc=$?; "
        "printf 'HFNET_FREEZE_RC=%s\\n' \"$hfnet_freeze_rc\""
    )
    hfnet_run = (
        f"hfnet_run_rc=0; {project_python} scripts/run_hfnet_slam_a02_long1801_headless_v4.py "
        "--action run || hfnet_run_rc=$?; "
        "printf 'HFNET_WHOLE_SYSTEM_RC=%s\\n' \"$hfnet_run_rc\""
    )
    return [
        start_gate,
        f"{project_python} scripts/materialize_aqualoc_a02_4500_6300_window_v1.py --action preflight || exit $?",
        f"{project_python} scripts/materialize_aqualoc_a02_4500_6300_window_v1.py --action export || exit $?",
        f"{project_python} scripts/export_aqualoc_a02_shared_4500_6300_v1.py --action preflight || exit $?",
        f"{project_python} scripts/export_aqualoc_a02_shared_4500_6300_v1.py --action export --output {DEFAULT_SHARED_ROOT} || exit $?",
        f"test ! -e {decision_dir} || exit 73",
        f"test ! -e {b1_native_run_dir} || exit 73",
        static_gate,
        b1_native,
        f"{project_python} scripts/verify_a02_long_three_arm_eval_inputs_v1.py --action check-b1-decision || exit 42",
        constq_rewrite,
        constq_audit,
        constq_gate,
        static_gate,
        expected_xfeat_export_command(),
        static_gate,
        expected_xfeat_audit_command(),
        static_gate,
        b1_vins,
        xfeat_vins,
        static_gate,
        hfnet_preflight,
        hfnet_freeze,
        hfnet_run,
        expected_hfnet_bridge_command(),
        f"test ! -e {DEFAULT_OUTPUT} || exit 73",
        f"test ! -e {DEFAULT_EVAL_DIR} || exit 73",
        expected_final_gate_command(),
    ]


def validate_frozen_command_protocol(freeze: Mapping[str, object]) -> dict[str, object]:
    commands = freeze.get("commands")
    expected = authoritative_commands()
    if not isinstance(commands, list) or len(commands) != len(expected) or not all(
        isinstance(command, str) and "\n" not in command for command in commands
    ):
        raise VerificationError("STATIC_COMMAND_PROTOCOL_SHAPE_MISMATCH")
    if any("set -e" in command or "set -o errexit" in command for command in commands):
        raise VerificationError("STATIC_COMMAND_PROTOCOL_EXTERNAL_ERREXIT_DEPENDENCY")
    if commands != expected:
        mismatch = next(
            index
            for index, (observed, wanted) in enumerate(zip(commands, expected))
            if observed != wanted
        )
        raise VerificationError(f"STATIC_COMMAND_PROTOCOL_EXACT_MISMATCH_AT_{mismatch}")
    if any("evaluate_vins_common_support.py" in command for command in commands[:-1]):
        raise VerificationError("STATIC_COMMAND_PROTOCOL_EVALUATOR_OUTSIDE_FINAL_NESTED_GATE")
    return {
        "status": "PASS_EXACT_EXPLICIT_RC_NO_EXTERNAL_ERREXIT_ENV_I_AND_NESTED_G0",
        "command_count": len(commands),
        "vins_environment_isolation": "env_i_exact_allowlist",
        "xfeat_export_environment_isolation": "env_i_cpu_runtime_exact_allowlist",
        "xfeat_audit_environment_isolation": "env_i_rosbag_cv2_runtime_exact_allowlist",
        "static_point_of_use_gate_indices": [0, 7, 13, 15, 17, 20],
        "strict_b1_decision_global_gate_index": 9,
        "scientific_failure_capture_indices": [8, 10, 11, 12, 14, 16, 18, 19, 21, 22, 23, 24],
        "final_gate_single_command": True,
    }


def validate_frozen_window_contract(freeze: Mapping[str, object]) -> dict[str, object]:
    if freeze.get("window") != EXPECTED_WINDOW_CONTRACT:
        raise VerificationError("STATIC_WINDOW_CONTRACT_EXACT_MISMATCH")
    return {
        "status": "PASS_EXACT_INTEGER_WINDOW_CONTRACT",
        "window": EXPECTED_WINDOW_CONTRACT,
    }


def validate_vins_dynamic_linkage(binary: Path) -> dict[str, object]:
    ldd_identity = exact_identity(LDD, LDD_SHA256, "LDD_RESOLVER")
    try:
        result = subprocess.run(
            [str(LDD), str(binary)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError(f"VINS_LDD_EXECUTION_FAILED:{error}") from error
    if result.returncode != 0:
        raise VerificationError(f"VINS_LDD_RETURN_CODE_{result.returncode}")
    resolved: dict[str, Path] = {}
    pattern = re.compile(r"^[ \t]*(libvins_lib[.]so|libcamera_models[.]so)[ \t]+=>[ \t]+([^ \t]+)[ \t]+[(]")
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        soname, raw_path = match.groups()
        if soname in resolved:
            raise VerificationError(f"VINS_LDD_DUPLICATE_{soname}")
        resolved[soname] = Path(raw_path)
    expected = {
        "libvins_lib.so": (
            VINS_CORE_LIBRARY,
            VINS_CORE_LIBRARY_SHA256,
            VINS_CORE_LIBRARY_SIZE,
        ),
        "libcamera_models.so": (
            VINS_CAMERA_MODELS_LIBRARY,
            VINS_CAMERA_MODELS_LIBRARY_SHA256,
            VINS_CAMERA_MODELS_LIBRARY_SIZE,
        ),
    }
    if set(resolved) != set(expected):
        raise VerificationError("VINS_LDD_REQUIRED_LIBRARY_SET_MISMATCH")
    identities: dict[str, object] = {}
    for soname, (expected_path, expected_sha256, expected_size) in expected.items():
        observed_path = resolved[soname]
        if observed_path != expected_path:
            raise VerificationError(f"VINS_LDD_{soname}_PATH_MISMATCH")
        library_identity = exact_identity(
            observed_path, expected_sha256, f"VINS_LDD_{soname}"
        )
        if library_identity["size_bytes"] != expected_size:
            raise VerificationError(f"VINS_LDD_{soname}_SIZE_MISMATCH")
        identities[soname] = library_identity
    return {
        "status": "PASS",
        "resolver": ldd_identity,
        "binary": str(binary.expanduser().absolute()),
        "resolved_libraries": identities,
    }


def validate_b1_v4_ros_environment() -> dict[str, object]:
    source_probe = (
        "set -euo pipefail; source /opt/ros/noetic/setup.bash; "
        "source /home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash; "
        "printf '%s\\n' \"$CMAKE_PREFIX_PATH\" \"$ROS_PACKAGE_PATH\" "
        "\"$LD_LIBRARY_PATH\" \"$PYTHONPATH\"; rospack find vins"
    )
    environment = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "ROS_DISTRO": "noetic",
        "ROS_MASTER_URI": "http://localhost:11341",
        "CMAKE_PREFIX_PATH": "/home/ma/SLAM/VINS-Fusion-origin/devel",
        "CATKIN_SETUP_UTIL_ARGS": "--local --extend",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": "/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
    }
    try:
        completed = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", source_probe],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError(f"B1_V4_ROS_ENVIRONMENT_PROBE_FAILED:{error}") from error
    expected_lines = [
        "/opt/ros/noetic:/home/ma/SLAM/VINS-Fusion-origin/devel",
        "/opt/ros/noetic/share:/home/ma/SLAM/VINS-Fusion-origin/src",
        "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
        "/opt/ros/noetic/lib/python3/dist-packages",
        "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator",
    ]
    if completed.returncode != 0 or completed.stdout.splitlines() != expected_lines:
        raise VerificationError("B1_V4_ROS_ENVIRONMENT_PROBE_IDENTITY_MISMATCH")
    return {
        "status": "PASS_NOETIC_ORIGIN_ONLY_UNDER_NOUNSET",
        "initial_environment": environment,
        "post_source_lines": expected_lines,
    }


def validate_static_freeze(freeze_path: Path) -> dict[str, object]:
    freeze, freeze_identity = load_canonical_json(freeze_path, "LONG_WINDOW_FREEZE")
    identities = freeze.get("identities")
    if (
        freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("status") != FREEZE_STATUS
        or freeze.get("working_directory") != EXPECTED_WORKING_DIRECTORY
        or not isinstance(identities, Mapping)
        or len(identities) != EXPECTED_STATIC_IDENTITY_COUNT
    ):
        raise VerificationError("STATIC_FREEZE_SCHEMA_STATUS_OR_IDENTITY_COUNT_MISMATCH")
    command_protocol = validate_frozen_command_protocol(freeze)
    window_contract = validate_frozen_window_contract(freeze)
    required = {
        str(ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py"): B1_CONTRACT_CHECKER_SHA256,
        str(ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py"): B1_V2_COMMON_CHECKER_SHA256,
        str(ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v3.py"): B1_CONTRACT_BUILDER_SHA256,
        str(ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v2.py"): B1_V2_CONTRACT_BUILDER_SHA256,
        str(ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh"): B1_V3_RUNNER_SHA256,
        str(ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh"): B1_V4_EXECUTION_REPAIR_SHA256,
        str(ROOT / "scripts/tests/test_a02_b1_guarded_execution_repair_v4.py"): B1_V4_EXECUTION_REPAIR_TESTS_SHA256,
        str(DEFAULT_B1_BACKEND_CONTRACT): B1_BACKEND_CONTRACT_SHA256,
        str(DEFAULT_B1_TRANSITION_PROOF): B1_TRANSITION_PROOF_SHA256,
        str(ROOT / "scripts/prove_b1_klt_exporter_transition_v2.py"): B1_TRANSITION_PROVER_SHA256,
        str(ROOT / "uw_frontend/ros/export_vins_features.py"): B1_FRONTEND_EXPORTER_SHA256,
        str(ROOT / "uw_frontend/quality/image_quality.py"): XFEAT_QUALITY_REFERENCE_SOURCE_SHA256,
        str(XFEAT_AUDIT_BASE_INTERPRETER): XFEAT_AUDIT_BASE_INTERPRETER_SHA256,
        str(XFEAT_AUDIT_CV2_CORE): XFEAT_AUDIT_CV2_CORE_SHA256,
        str(XFEAT_AUDIT_NUMPY): XFEAT_AUDIT_NUMPY_SHA256,
        str(ROOT / "scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py"): HFNET_PYTHON_RUNTIME_CLOSURE["scripts/run_hfnet_slam_a02_full901_diagnostic_v2.py"][1],
        str(ROOT / "scripts/tests/test_run_hfnet_slam_a02_long1801_headless_v4.py"): HFNET_V4_TESTS_SHA256,
        str(ROOT / "scripts/export_aqualoc_to_hfnet_euroc_full_v2.py"): HFNET_PYTHON_RUNTIME_CLOSURE["scripts/export_aqualoc_to_hfnet_euroc_full_v2.py"][1],
        str(ROOT / "scripts/export_aqualoc_to_hfnet_euroc_v1.py"): HFNET_PYTHON_RUNTIME_CLOSURE["scripts/export_aqualoc_to_hfnet_euroc_v1.py"][1],
        str(VINS_CORE_LIBRARY): VINS_CORE_LIBRARY_SHA256,
        str(VINS_CAMERA_MODELS_LIBRARY): VINS_CAMERA_MODELS_LIBRARY_SHA256,
        str(LDD): LDD_SHA256,
    }
    for raw_path, (_size, expected) in XFEAT_EXPORT_RUNTIME_FILES.items():
        required[raw_path] = expected
    for raw_path, (_size, expected) in EVALUATION_RUNTIME_FILES.items():
        required[raw_path] = expected
    for path, expected in required.items():
        if identities.get(path) != expected:
            raise VerificationError(f"STATIC_FREEZE_REQUIRED_IDENTITY_MISMATCH:{path}")
    for closure in (
        B1_PYTHON_RUNTIME_CLOSURE,
        B1_YAML_EXTENDS_CLOSURE,
        HFNET_PYTHON_RUNTIME_CLOSURE,
        XFEAT_OFFICIAL_CLOSURE,
    ):
        for relative, (_size, expected) in closure.items():
            path = str(ROOT / relative)
            if identities.get(path) != expected:
                raise VerificationError(f"STATIC_FREEZE_CLOSURE_IDENTITY_MISMATCH:{path}")
    checked: dict[str, object] = {}
    for raw_path, expected in identities.items():
        if (
            not isinstance(raw_path, str)
            or not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        ):
            raise VerificationError("STATIC_FREEZE_IDENTITY_ENTRY_INVALID")
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        checked[raw_path] = exact_identity(path, expected, "STATIC_FROZEN_ARTIFACT")
    linkage = validate_vins_dynamic_linkage(VINS_BINARY)
    b1_v4_ros_environment = validate_b1_v4_ros_environment()
    b1_runtime_closures = validate_b1_runtime_closures()
    hfnet_runtime_closure = validate_hfnet_python_runtime_closure()
    xfeat_audit_runtime = validate_xfeat_audit_runtime()
    xfeat_export_runtime = validate_xfeat_export_runtime()
    evaluation_runtime = validate_evaluation_runtime()
    xfeat_official_closure = validate_xfeat_official_closure()

    from scripts import check_b1_klt_nativeq_current_exporter_contract_v3 as guard_v3

    prior_path = os.environ.get("PATH")
    os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    try:
        guard = guard_v3.evaluate_contract(DEFAULT_B1_BACKEND_CONTRACT)
    finally:
        if prior_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = prior_path
    if (
        guard.get("schema_version") != B1_GUARD_DECISION_SCHEMA
        or guard.get("status") != "PASS"
        or guard.get("contract_pass") is not True
        or guard.get("action") != "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3"
        or guard.get("contract_hash") != B1_BACKEND_CONTRACT_PAYLOAD_HASH
        or guard.get("contract_file_sha256") != B1_BACKEND_CONTRACT_SHA256
        or guard.get("reasons") != []
    ):
        raise VerificationError("STATIC_B1_V3_GUARD_CONTRACT_NOT_PASS")
    return {
        "status": "PASS_STATIC_IDENTITY_AND_B1_V3_CONTRACT",
        "freeze": freeze_identity,
        "identity_count": len(checked),
        "working_directory": EXPECTED_WORKING_DIRECTORY,
        "vins_dynamic_linkage": linkage,
        "b1_v4_ros_environment": b1_v4_ros_environment,
        "b1_v3_contract_hash": B1_BACKEND_CONTRACT_PAYLOAD_HASH,
        "command_protocol": command_protocol,
        "window_contract": window_contract,
        "b1_runtime_closures": b1_runtime_closures,
        "hfnet_runtime_closure": hfnet_runtime_closure,
        "xfeat_audit_runtime": xfeat_audit_runtime,
        "xfeat_export_runtime": xfeat_export_runtime,
        "evaluation_runtime": evaluation_runtime,
        "xfeat_official_closure": xfeat_official_closure,
    }


def validate_start_freeze(freeze_path: Path) -> dict[str, object]:
    static = validate_static_freeze(freeze_path)
    freeze, freeze_identity = load_canonical_json(freeze_path, "LONG_WINDOW_START_FREEZE")
    reserved = freeze.get("reserved_paths_absent_at_freeze")
    if reserved != list(EXPECTED_RESERVED_PATHS):
        raise VerificationError("START_RESERVED_PATH_SET_OR_ORDER_MISMATCH")
    present = [
        raw_path
        for raw_path in EXPECTED_RESERVED_PATHS
        if Path(raw_path).exists() or Path(raw_path).is_symlink()
    ]
    if present:
        raise VerificationError(f"START_RESERVED_PATH_NOT_ABSENT:{present}")
    return {
        "status": "PASS_STATIC_AND_EXACT_18_RESERVED_PATHS_ABSENT",
        "freeze": freeze_identity,
        "reserved_path_count": len(EXPECTED_RESERVED_PATHS),
        "static": static,
    }


def backend_contract_payload_hash(contract: Mapping[str, object]) -> str:
    normalized = {
        key: value
        for key, value in contract.items()
        if key not in {"contract_hash", "generated_at_utc"}
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def validate_b1_guard_governance(
    *,
    decision_dir: Path,
    contract_path: Path,
    eligibility_manifest: Path,
    raw_tar_claim: Mapping[str, object],
    gt_claim: Mapping[str, object],
    frontend_exporter_identity: Mapping[str, object],
    vins_binary_identity: Mapping[str, object],
    vins_dynamic_linkage: Mapping[str, object],
) -> dict[str, object]:
    """Bind the one guarded B1 decision and the manifest row used by its wrapper."""

    if decision_dir.is_symlink() or not decision_dir.is_dir():
        raise VerificationError("B1_GUARD_DECISION_DIR_NOT_REAL_DIRECTORY")
    entries = sorted(decision_dir.iterdir(), key=lambda path: path.name)
    if len(entries) != 1:
        raise VerificationError(f"B1_GUARD_DECISION_FILE_COUNT_{len(entries)}")
    decision_path = entries[0]
    if decision_path.name != "b1_current_exporter_v3_decision.json":
        raise VerificationError("B1_GUARD_DECISION_FILENAME_MISMATCH")
    decision, decision_identity = load_canonical_json(
        decision_path, "B1_GUARD_DECISION"
    )

    contract, contract_identity = load_canonical_json(
        contract_path, "B1_BACKEND_QUALITY_CONTRACT"
    )
    records = contract.get("records")
    exporter_record = records.get("current_exporter") if isinstance(records, Mapping) else None
    proof_record = records.get("transition_proof") if isinstance(records, Mapping) else None
    base_record = records.get("base_contract_v1") if isinstance(records, Mapping) else None
    binary_record = records.get("vins_node") if isinstance(records, Mapping) else None
    manifest_record = records.get("data_eligibility_manifest") if isinstance(records, Mapping) else None
    _, base_contract_identity = read_regular(
        DEFAULT_B1_BASE_BACKEND_CONTRACT, "B1_BASE_BACKEND_QUALITY_CONTRACT"
    )
    _, transition_proof_identity = read_regular(
        DEFAULT_B1_TRANSITION_PROOF, "B1_EXPORTER_TRANSITION_PROOF"
    )
    if (
        contract.get("schema_version")
        != "aqua-fe-b1-klt-nativeq-current-exporter-contract-v3"
        or contract.get("status")
        != "FROZEN_POST_STOP_B1_CURRENT_EXPORTER_CONTRACT_V3"
        or contract.get("contract_hash") != B1_BACKEND_CONTRACT_PAYLOAD_HASH
        or backend_contract_payload_hash(contract) != B1_BACKEND_CONTRACT_PAYLOAD_HASH
        or contract.get("base_contract_hash")
        != B1_BASE_BACKEND_CONTRACT_PAYLOAD_HASH
        or not isinstance(exporter_record, Mapping)
        or exporter_record.get("sha256") != B1_BACKEND_CONTRACT_EXPORTER_SHA256
        or not isinstance(proof_record, Mapping)
        or not isinstance(base_record, Mapping)
        or not isinstance(binary_record, Mapping)
        or not isinstance(manifest_record, Mapping)
    ):
        raise VerificationError("B1_BACKEND_QUALITY_CONTRACT_CONTENT_MISMATCH")
    require_file_identity(
        exporter_record, frontend_exporter_identity, "B1_V2_CONTRACT_EXPORTER"
    )
    require_file_identity(
        proof_record, transition_proof_identity, "B1_V2_CONTRACT_TRANSITION_PROOF"
    )
    require_file_identity(
        base_record, base_contract_identity, "B1_V2_CONTRACT_BASE_CONTRACT"
    )
    require_file_identity(
        binary_record, vins_binary_identity, "B1_V2_CONTRACT_VINS_BINARY"
    )
    if decision.get("vins_ldd_core") != vins_dynamic_linkage.get(
        "resolved_libraries"
    ) or contract.get("vins_ldd_core") != vins_dynamic_linkage.get(
        "resolved_libraries"
    ):
        raise VerificationError("B1_V2_VINS_LDD_CORE_BINDING_MISMATCH")

    expected_contract_path = str(contract_path.expanduser().absolute())
    expected_decision_keys = {
        "action",
        "algorithm_settings",
        "backend_binary",
        "base_contract_hash",
        "contract_file_sha256",
        "contract_hash",
        "contract_pass",
        "contract_path",
        "counts_as_b1",
        "counts_as_proposed_result",
        "exporter",
        "outcome_boundary",
        "reasons",
        "result_label",
        "schema_version",
        "status",
        "transition_proof",
        "vins_ldd_core",
    }
    if (
        set(decision) != expected_decision_keys
        or decision.get("schema_version") != B1_GUARD_DECISION_SCHEMA
        or decision.get("status") != "PASS"
        or decision.get("contract_pass") is not True
        or decision.get("action") != "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3"
        or decision.get("result_label") != "B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3"
        or decision.get("counts_as_b1") is not True
        or decision.get("counts_as_proposed_result") is not False
        or decision.get("outcome_boundary")
        != "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME"
        or decision.get("contract_path") != expected_contract_path
        or decision.get("contract_file_sha256") != B1_BACKEND_CONTRACT_SHA256
        or decision.get("contract_hash") != B1_BACKEND_CONTRACT_PAYLOAD_HASH
        or decision.get("base_contract_hash")
        != B1_BASE_BACKEND_CONTRACT_PAYLOAD_HASH
        or decision.get("exporter") != exporter_record
        or decision.get("transition_proof") != proof_record
        or decision.get("backend_binary") != binary_record
        or decision.get("algorithm_settings") != contract.get("algorithm_settings")
        or decision.get("reasons") != []
    ):
        raise VerificationError("B1_GUARD_DECISION_CONTRACT_MISMATCH")

    manifest_payload, manifest_identity = read_regular(
        eligibility_manifest, "B1_DATA_ELIGIBILITY_MANIFEST"
    )
    require_file_identity(
        manifest_record, manifest_identity, "B1_V2_CONTRACT_ELIGIBILITY_MANIFEST"
    )
    try:
        manifest_text = manifest_payload.decode("utf-8")
        rows = list(csv.DictReader(manifest_text.splitlines()))
    except (UnicodeError, csv.Error) as error:
        raise VerificationError("B1_DATA_ELIGIBILITY_MANIFEST_INVALID") from error
    matches = [
        row
        for row in rows
        if row.get("dataset_family") == "aqualoc_archaeology"
        and row.get("sequence") == "A02"
    ]
    if len(matches) != 1:
        raise VerificationError(f"B1_A02_ELIGIBILITY_ROW_COUNT_{len(matches)}")
    row = matches[0]
    expected_raw_path = str((ROOT / str(row.get("raw_input_path", ""))).resolve(strict=False))
    expected_gt_path = str((ROOT / str(row.get("reference_path", ""))).resolve(strict=False))
    if (
        row.get("manifest_schema") != "isj-data-eligibility-v1"
        or row.get("eligibility") != "ELIGIBLE_WITH_REFERENCE_CAVEAT"
        or raw_tar_claim.get("path") != expected_raw_path
        or gt_claim.get("path") != expected_gt_path
    ):
        raise VerificationError("B1_A02_ELIGIBILITY_ROW_SOURCE_BINDING_MISMATCH")
    return {
        "status": "PASS",
        "decision_directory": str(decision_dir.expanduser().resolve(strict=False)),
        "decision": decision_identity,
        "backend_contract": contract_identity,
        "backend_contract_payload_hash": B1_BACKEND_CONTRACT_PAYLOAD_HASH,
        "base_backend_contract": base_contract_identity,
        "transition_proof": transition_proof_identity,
        "eligibility_manifest": manifest_identity,
        "eligibility_row": {
            "dataset_family": "aqualoc_archaeology",
            "sequence": "A02",
            "eligibility": "ELIGIBLE_WITH_REFERENCE_CAVEAT",
            "raw_input_path": expected_raw_path,
            "reference_path": expected_gt_path,
        },
        "frontend_exporter": dict(frontend_exporter_identity),
    }


def validate_b1_decision_after_wrapper(args: argparse.Namespace) -> dict[str, object]:
    static = validate_static_freeze(args.freeze)
    source_chain = validate_shared_source_chain(
        args.shared_root, args.window_bag, args.window_manifest
    )
    linkage = validate_vins_dynamic_linkage(VINS_BINARY)
    governance = validate_b1_guard_governance(
        decision_dir=args.b1_guard_decision_dir,
        contract_path=args.b1_backend_contract,
        eligibility_manifest=args.b1_eligibility_manifest,
        raw_tar_claim=source_chain["canonical_raw_tar_claim"],
        gt_claim=source_chain["canonical_gt_claim"],
        frontend_exporter_identity=exact_identity(
            ROOT / "uw_frontend/ros/export_vins_features.py",
            B1_FRONTEND_EXPORTER_SHA256,
            "B1_DECISION_GATE_FRONTEND_EXPORTER",
        ),
        vins_binary_identity=exact_identity(
            VINS_BINARY, VINS_BINARY_SHA256, "B1_DECISION_GATE_VINS_BINARY"
        ),
        vins_dynamic_linkage=linkage,
    )
    return {
        "status": "PASS_STRICT_B1_V3_DECISION_AFTER_V4_WRAPPER",
        "static_identity_gate": static,
        "shared_source_chain": source_chain,
        "guard_governance": governance,
    }


def validate_shared_source_chain(
    shared_root: Path, window_bag: Path, window_manifest: Path
) -> dict[str, object]:
    shared, shared_identity = load_canonical_json(
        shared_root / "conversion_manifest.json", "SHARED_MANIFEST_SOURCE_CHAIN"
    )
    try:
        provenance = shared_exporter.validate_provenance(window_manifest, window_bag)
    except Exception as error:
        raise VerificationError(f"CANONICAL_WINDOW_PROVENANCE_INVALID:{error}") from error
    source = shared.get("source")
    if not isinstance(source, dict):
        raise VerificationError("SHARED_SOURCE_NOT_OBJECT")
    if source.get("provenance") != provenance:
        raise VerificationError("SHARED_SOURCE_PROVENANCE_NOT_CURRENT_CANONICAL_WINDOW")
    if source.get("derived_window_bag") != provenance.get("derived_window_bag"):
        raise VerificationError("SHARED_DERIVED_WINDOW_IDENTITY_MISMATCH")
    producer = provenance.get("producer_record")
    if not isinstance(producer, dict):
        raise VerificationError("CANONICAL_WINDOW_PRODUCER_RECORD_MISSING")
    output = producer.get("output")
    producer_provenance = producer.get("provenance")
    if not isinstance(output, dict) or not isinstance(producer_provenance, dict):
        raise VerificationError("CANONICAL_WINDOW_OUTPUT_OR_PROVENANCE_RECORD_MISSING")
    for key in ("raw_tar", "gt", "converter"):
        if not isinstance(producer_provenance.get(key), dict):
            raise VerificationError(f"CANONICAL_WINDOW_{key.upper()}_CLAIM_MISSING")
    return {
        "shared_manifest_identity": shared_identity,
        "canonical_window_bag_identity": provenance["derived_window_bag"],
        "canonical_window_manifest_identity": {
            "path": provenance["path"],
            "size_bytes": provenance["size_bytes"],
            "sha256": provenance["sha256"],
        },
        "canonical_raw_tar_claim": producer_provenance["raw_tar"],
        "canonical_gt_claim": producer_provenance["gt"],
        "canonical_converter_claim": producer_provenance["converter"],
        "canonical_output_topic_counts": provenance["output_topic_counts"],
    }


def validate_quality_chain(
    native_bag: Path, constq_bag: Path, audit_path: Path
) -> dict[str, object]:
    _, native_identity = read_regular(native_bag, "B1_NATIVE_FEATURE_BAG")
    _, constq_identity = read_regular(constq_bag, "B1_CONSTQ_FEATURE_BAG")
    audit, audit_identity = load_canonical_json(audit_path, "B1_CONSTQ_QUALITY_AUDIT")
    if (
        audit.get("schema_version") != QUALITY_AUDIT_SCHEMA
        or audit.get("contract_pass") is not True
        or audit.get("input_bag") != str(native_bag.expanduser().absolute())
        or audit.get("output_bag") != str(constq_bag.expanduser().absolute())
        or audit.get("input_sha256") != native_identity["sha256"]
        or audit.get("output_sha256") != constq_identity["sha256"]
        or audit.get("feature_topic") != "/feature_tracker/feature"
        or audit.get("source_codes") != [1]
        or audit.get("quality") != 1.0
        or audit.get("sigma") != 1.0
        or audit.get("feature_frames") != 900
        or audit.get("selected_observations") != 315000
        or audit.get("untouched_observations") != 0
    ):
        raise VerificationError("B1_CONSTQ_QUALITY_AUDIT_CONTRACT_MISMATCH")
    if audit.get("total_messages") != audit.get("raw_equal_nonfeature_messages", -1) + audit.get("feature_frames", -2):
        raise VerificationError("B1_CONSTQ_MESSAGE_ACCOUNTING_MISMATCH")
    return {
        "status": "PASS",
        "native_feature_bag": native_identity,
        "constq_feature_bag": constq_identity,
        "quality_audit": audit_identity,
        "audited_contract": {
            "feature_frames": 900,
            "selected_observations": 315000,
            "untouched_observations": 0,
            "quality": 1.0,
            "sigma": 1.0,
            "nonquality_nonfeature_and_order_equality": True,
        },
    }


def validate_xfeat_chain(
    *,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    output_bag: Path,
    manifest_path: Path,
    audit_path: Path,
) -> dict[str, object]:
    identities = {}
    for label, path in (
        ("source_feature_bag", source_bag),
        ("raw_image_bag", raw_bag),
        ("camera_yaml", camera_yaml),
        ("output_bag", output_bag),
    ):
        _, identities[label] = read_regular(path, f"XFEAT_{label.upper()}")
    manifest, manifest_identity = load_canonical_json(manifest_path, "XFEAT_EXPORT_MANIFEST")
    inputs = manifest.get("inputs")
    prefix = manifest.get("prefix")
    metrics = manifest.get("metrics")
    algorithm = manifest.get("algorithm")
    code_artifacts = manifest.get("code_artifacts")
    exporter_artifact = code_artifacts.get("exporter") if isinstance(code_artifacts, dict) else None
    carrier_artifact = code_artifacts.get("carrier_base") if isinstance(code_artifacts, dict) else None
    quality_artifact = code_artifacts.get("quality_reference_source") if isinstance(code_artifacts, dict) else None
    detector_artifact = code_artifacts.get("detector") if isinstance(code_artifacts, dict) else None
    detector_runtime = detector_artifact.get("runtime") if isinstance(detector_artifact, dict) else None
    detector_closure = detector_artifact.get("closure") if isinstance(detector_artifact, dict) else None
    detector_repository = detector_artifact.get("repository") if isinstance(detector_artifact, dict) else None
    detector_license = detector_artifact.get("license") if isinstance(detector_artifact, dict) else None
    official_closure = validate_xfeat_official_closure()
    official_files = official_closure["files"]
    detector_expected = {
        "xfeat.py": official_files["external_tools/accelerated_features/modules/xfeat.py"],
        "model.py": official_files["external_tools/accelerated_features/modules/model.py"],
        "interpolator.py": official_files["external_tools/accelerated_features/modules/interpolator.py"],
        "xfeat.pt": official_files["external_tools/accelerated_features/weights/xfeat.pt"],
    }
    expected_imported_paths = {
        "modules.xfeat": str((ROOT / "external_tools/accelerated_features/modules/xfeat.py").resolve()),
        "modules.model": str((ROOT / "external_tools/accelerated_features/modules/model.py").resolve()),
        "modules.interpolator": str((ROOT / "external_tools/accelerated_features/modules/interpolator.py").resolve()),
    }
    quality_identity = exact_identity(
        ROOT / "uw_frontend/quality/image_quality.py",
        XFEAT_QUALITY_REFERENCE_SOURCE_SHA256,
        "XFEAT_QUALITY_REFERENCE_SOURCE",
    )
    if (
        manifest.get("schema_version") != XFEAT_MANIFEST_SCHEMA
        or manifest.get("status") != "FULL"
        or manifest.get("formal_eligible") is not True
        or not isinstance(inputs, dict)
        or not isinstance(prefix, dict)
        or not isinstance(metrics, dict)
        or not isinstance(algorithm, dict)
        or not isinstance(exporter_artifact, dict)
        or not isinstance(carrier_artifact, dict)
        or not isinstance(quality_artifact, dict)
        or not isinstance(detector_runtime, dict)
        or not isinstance(detector_closure, dict)
        or not isinstance(detector_repository, dict)
        or not isinstance(detector_license, dict)
        or manifest.get("detector_origin") != "cli_production_factory"
        or prefix.get("requested_max_published_frames") is not None
        or prefix.get("source_total_published_frames") != 900
        or prefix.get("selected_published_frames") != 900
        or metrics.get("published_frames") != 900
        or metrics.get("observations") != 315000
        or metrics.get("observations_per_frame_min") != 350
        or metrics.get("observations_per_frame_max") != 350
        or algorithm.get("name") != "xfeat_detector_raw_frame_lk_carrier_v1"
        or exporter_artifact.get("sha256") != XFEAT_EXPORTER_SHA256
        or carrier_artifact.get("sha256") != XFEAT_CARRIER_BASE_SHA256
        or detector_artifact.get("identity") != "official_verlab_XFeat_sparse_detectAndCompute_proposals_only"
        or detector_closure != detector_expected
        or detector_repository.get("commit") != "e92685f57f8318b18725c5c8c0bd28c7fe188d9a"
        or detector_license.get("spdx") != "Apache-2.0"
        or detector_license.get("file") != official_files["external_tools/accelerated_features/LICENSE"]
        or detector_runtime.get("device") != "cpu"
        or detector_runtime.get("torch_version") != "2.2.2+cpu"
        or detector_runtime.get("opencv_version") != "4.2.0"
        or detector_runtime.get("numpy_version") != "1.24.4"
        or detector_runtime.get("imported_module_paths") != expected_imported_paths
        or detector_runtime.get("detect_calls") != 900
        or detector_runtime.get("gray_input_shapes_hw") != [[608, 968]]
        or detector_runtime.get("rgb_tensor_input_shapes_bchw") != [[1, 3, 608, 968]]
        or inputs.get("feature_topic") != "/feature_tracker/feature"
        or inputs.get("image_topic") != "/camera/image_raw"
    ):
        raise VerificationError("XFEAT_EXPORT_MANIFEST_CONTRACT_MISMATCH")
    for key in ("source_feature_bag", "raw_image_bag", "camera_yaml"):
        require_file_identity(inputs.get(key), identities[key], f"XFEAT_MANIFEST_{key}")
    require_file_identity(manifest.get("output_bag"), identities["output_bag"], "XFEAT_MANIFEST_OUTPUT")
    require_file_identity(
        quality_artifact,
        quality_identity,
        "XFEAT_MANIFEST_QUALITY_REFERENCE_SOURCE",
    )
    static_artifacts = {
        "xfeat_source": "external_tools/accelerated_features/modules/xfeat.py",
        "xfeat_model_source": "external_tools/accelerated_features/modules/model.py",
        "xfeat_interpolator_source": "external_tools/accelerated_features/modules/interpolator.py",
        "xfeat_weight": "external_tools/accelerated_features/weights/xfeat.pt",
        "xfeat_license": "external_tools/accelerated_features/LICENSE",
    }
    for artifact_label, relative in static_artifacts.items():
        expected = dict(official_files[relative])
        expected["path"] = str((ROOT / relative).resolve())
        if code_artifacts.get(artifact_label) != expected:
            raise VerificationError(f"XFEAT_MANIFEST_STATIC_ARTIFACT_MISMATCH:{artifact_label}")

    audit, audit_identity = load_json_object(audit_path, "XFEAT_INDEPENDENT_AUDIT")
    audit_input = audit.get("input")
    method = audit.get("method")
    audit_artifact = audit.get("audit_artifact")
    audit_entrypoint = audit_artifact.get("entrypoint") if isinstance(audit_artifact, dict) else None
    audit_base = audit_artifact.get("audit_base") if isinstance(audit_artifact, dict) else None
    if (
        audit.get("schema_version") != XFEAT_AUDIT_SCHEMA
        or audit.get("status") != "PASS"
        or audit.get("pass") is not True
        or not isinstance(audit_input, dict)
        or not isinstance(method, dict)
        or not isinstance(audit_entrypoint, dict)
        or not isinstance(audit_base, dict)
        or audit_input.get("reference_bag") != identities["source_feature_bag"]["path"]
        or audit_input.get("candidate_bag") != identities["output_bag"]["path"]
        or audit_input.get("camera_yaml") != identities["camera_yaml"]["path"]
        or audit_input.get("feature_topic") != "/feature_tracker/feature"
        or audit_input.get("allow_candidate_prefix") is not False
        or method.get("method_id") != "xfeat_detector_raw_frame_lk_carrier_v1"
        or method.get("expected_source_code") != 20
        or method.get("expected_observations_per_frame") != 350
        or audit_entrypoint.get("sha256") != XFEAT_AUDITOR_SHA256
        or audit_base.get("sha256") != XFEAT_AUDIT_BASE_SHA256
    ):
        raise VerificationError("XFEAT_INDEPENDENT_AUDIT_CONTRACT_MISMATCH")
    return {
        "status": "PASS",
        "source_feature_bag": identities["source_feature_bag"],
        "raw_window_bag": identities["raw_image_bag"],
        "camera_yaml": identities["camera_yaml"],
        "xfeat_feature_bag": identities["output_bag"],
        "export_manifest": manifest_identity,
        "independent_audit": audit_identity,
        "quality_reference_source": quality_identity,
        "official_xfeat_closure": official_closure,
        "detector_runtime_contract": {
            "device": "cpu",
            "torch_version": "2.2.2+cpu",
            "opencv_version": "4.2.0",
            "numpy_version": "1.24.4",
            "detect_calls": 900,
        },
    }


def validate_reference(shared_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    manifest_path = shared_root / "conversion_manifest.json"
    manifest, manifest_identity = load_canonical_json(manifest_path, "SHARED_MANIFEST")
    if manifest.get("schema_version") != SHARED_SCHEMA or manifest.get("status") != SHARED_STATUS:
        raise VerificationError("SHARED_MANIFEST_SCHEMA_OR_STATUS_MISMATCH")
    window = manifest.get("window")
    views = manifest.get("views")
    reference_record = manifest.get("reference")
    if not isinstance(window, dict) or window.get("score_reference_count") != EXPECTED_REFERENCE_ROWS:
        raise VerificationError("SHARED_REFERENCE_COUNT_CONTRACT_MISMATCH")
    expected_indices = list(range(5400, 6301, 20))
    if window.get("score_reference_global_indices") != expected_indices:
        raise VerificationError("SHARED_REFERENCE_INDEX_CONTRACT_MISMATCH")
    if not isinstance(views, dict) or views.get("reference_tum") != "shared/reference_proxy.tum":
        raise VerificationError("SHARED_REFERENCE_VIEW_MISMATCH")
    if not isinstance(reference_record, dict) or reference_record.get("target_rows") != EXPECTED_REFERENCE_ROWS or reference_record.get("pose_convention") != "world_T_camera":
        raise VerificationError("SHARED_REFERENCE_RECORD_MISMATCH")
    mapping = reference_record.get("mapping")
    if not isinstance(mapping, list) or len(mapping) != EXPECTED_REFERENCE_ROWS:
        raise VerificationError("SHARED_REFERENCE_MAPPING_MISMATCH")

    reference_path = shared_root / "shared/reference_proxy.tum"
    payload, reference_identity = read_regular(reference_path, "REFERENCE_TUM")
    source_record = reference_record.get("identity")
    if not isinstance(source_record, dict) or not isinstance(source_record.get("path"), str):
        raise VerificationError("SHARED_REFERENCE_SOURCE_IDENTITY_MISSING")
    source_path = Path(source_record["path"])
    source_payload, source_identity = read_regular(source_path, "REFERENCE_PROXY_SOURCE")
    require_file_identity(source_record, source_identity, "REFERENCE_PROXY_SOURCE")
    target_poses: dict[int, tuple[tuple[float, float, float], tuple[float, float, float, float]]] = {}
    try:
        source_lines = source_payload.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise VerificationError("REFERENCE_PROXY_SOURCE_NOT_UTF8") from error
    wanted = set(expected_indices)
    for line_number, source_line in enumerate(source_lines, 1):
        fields = source_line.split()
        if len(fields) != 8:
            raise VerificationError(f"REFERENCE_PROXY_SOURCE_ROW_{line_number}_SHAPE_MISMATCH")
        try:
            index_value = float(fields[0])
            values = tuple(float(value) for value in fields[1:])
        except ValueError as error:
            raise VerificationError(f"REFERENCE_PROXY_SOURCE_ROW_{line_number}_NONNUMERIC") from error
        if not index_value.is_integer() or not all(math.isfinite(value) for value in values):
            raise VerificationError(f"REFERENCE_PROXY_SOURCE_ROW_{line_number}_INVALID")
        global_index = int(index_value)
        if global_index in wanted:
            if global_index in target_poses:
                raise VerificationError("REFERENCE_PROXY_SOURCE_DUPLICATE_TARGET")
            target_poses[global_index] = (values[0:3], values[3:7])  # type: ignore[assignment]
    if set(target_poses) != wanted:
        raise VerificationError("REFERENCE_PROXY_SOURCE_TARGETS_INCOMPLETE")
    expected_poses = []
    for global_index, raw_mapping in zip(expected_indices, mapping):
        if (
            not isinstance(raw_mapping, dict)
            or raw_mapping.get("global_camera_index") != global_index
            or not isinstance(raw_mapping.get("header_ns"), int)
        ):
            raise VerificationError("SHARED_REFERENCE_MAPPING_MISMATCH")
        position, quaternion = target_poses[global_index]
        expected_poses.append(
            shared_exporter.ReferencePose(
                global_camera_index=global_index,
                header_ns=int(raw_mapping.get("header_ns")),
                position_xyz=position,
                quaternion_xyzw=quaternion,
            )
        )
    if payload != shared_exporter.reference_tum_bytes(tuple(expected_poses)):
        raise VerificationError("REFERENCE_TUM_NOT_EXACT_DERIVATION_OF_FROZEN_PROXY")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise VerificationError("REFERENCE_TUM_NOT_ASCII") from error
    if len(lines) != EXPECTED_REFERENCE_ROWS or any(not line for line in lines):
        raise VerificationError("REFERENCE_TUM_ROW_COUNT_MISMATCH")
    observed_ns: list[int] = []
    for index, (line, raw_mapping) in enumerate(zip(lines, mapping)):
        fields = line.split()
        if len(fields) != 8 or not isinstance(raw_mapping, dict):
            raise VerificationError(f"REFERENCE_ROW_{index}_SHAPE_MISMATCH")
        try:
            stamp = Decimal(fields[0]) * Decimal(1_000_000_000)
            pose = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise VerificationError(f"REFERENCE_ROW_{index}_NONNUMERIC") from error
        if stamp != stamp.to_integral_value() or not all(math.isfinite(value) for value in pose):
            raise VerificationError(f"REFERENCE_ROW_{index}_INVALID")
        stamp_ns = int(stamp)
        if raw_mapping.get("global_camera_index") != expected_indices[index] or raw_mapping.get("header_ns") != stamp_ns:
            raise VerificationError(f"REFERENCE_ROW_{index}_MAPPING_MISMATCH")
        norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if not 0.99 <= norm <= 1.01:
            raise VerificationError(f"REFERENCE_ROW_{index}_QUATERNION_INVALID")
        observed_ns.append(stamp_ns)
    if observed_ns[0] != SCORE_FIRST_NS or observed_ns[-1] != SCORE_LAST_NS or any(right <= left for left, right in zip(observed_ns, observed_ns[1:])):
        raise VerificationError("REFERENCE_TIMESTAMP_CONTRACT_MISMATCH")
    return reference_identity, manifest_identity


def bridge_semantics_contract() -> dict[str, object]:
    return {
        "input_columns": ["timestamp_ns", "tx", "ty", "tz", "qx", "qy", "qz", "qw"],
        "input_pose": "world_T_body",
        "output_columns": ["timestamp_ns", "tx", "ty", "tz", "qw", "qx", "qy", "qz"],
        "output_pose": "world_T_body",
        "timestamp_numeric_value_changed": False,
        "timestamp_scale_or_offset_applied": False,
        "pose_transform_inverse_or_normalisation_applied": False,
        "pose_numeric_tokens_preserved_byte_for_byte_modulo_delimiter_and_quaternion_column_order": True,
        "timestamp_text_canonicalised_from_exact_integral_decimal_to_integer": True,
        "source_bytes_equal_v4_passed_trajectory_identity": True,
    }


def independently_rebuild_bridge_payload(source_payload: bytes) -> tuple[bytes, int]:
    try:
        lines = source_payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise VerificationError("HFNET_BRIDGE_SOURCE_NOT_ASCII") from error
    if not lines or any(not line.strip() for line in lines):
        raise VerificationError("HFNET_BRIDGE_SOURCE_EMPTY_OR_BLANK_ROW")
    rows: list[str] = []
    previous_stamp: int | None = None
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            raise VerificationError(f"HFNET_BRIDGE_SOURCE_ROW_{index}_FIELD_COUNT")
        try:
            stamp_decimal = Decimal(fields[0])
            pose = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise VerificationError(f"HFNET_BRIDGE_SOURCE_ROW_{index}_NONNUMERIC") from error
        if (
            not stamp_decimal.is_finite()
            or stamp_decimal != stamp_decimal.to_integral_value()
            or not all(math.isfinite(value) for value in pose)
        ):
            raise VerificationError(f"HFNET_BRIDGE_SOURCE_ROW_{index}_INVALID")
        stamp = int(stamp_decimal)
        if previous_stamp is not None and stamp <= previous_stamp:
            raise VerificationError("HFNET_BRIDGE_SOURCE_TIMESTAMPS_NOT_STRICT")
        previous_stamp = stamp
        quaternion_norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if not 0.99 <= quaternion_norm <= 1.01:
            raise VerificationError(f"HFNET_BRIDGE_SOURCE_ROW_{index}_QUATERNION_INVALID")
        rows.append(",".join((str(stamp), fields[1], fields[2], fields[3], fields[7], fields[4], fields[5], fields[6])))
    return ("\n".join(rows) + "\n").encode("ascii"), len(rows)


def validate_v4_contract_snapshot_and_profile(result: Mapping[str, object]) -> tuple[dict[str, object], dict[str, object], str]:
    contract, contract_identity = load_canonical_json(DEFAULT_V4_CONTRACT, "HFNET_V4_CONTRACT")
    snapshot_payload, snapshot_identity = read_regular(DEFAULT_V4_CONTRACT_SNAPSHOT, "HFNET_V4_CONTRACT_SNAPSHOT")
    if snapshot_payload != canonical_json(contract):
        raise VerificationError("HFNET_V4_CONTRACT_SNAPSHOT_NOT_BYTE_EXACT")
    profile = contract.get("frozen_profile")
    execution_policy = contract.get("execution_policy")
    paths = contract.get("paths")
    if (
        contract.get("schema_version") != V4_CONTRACT_SCHEMA
        or contract.get("scientific_role") != V4_ROLE
        or not isinstance(profile, dict)
        or profile.get("schema_version") != V4_PROFILE_SCHEMA
        or not isinstance(execution_policy, dict)
        or execution_policy.get("maximum_process_starts") != 1
        or execution_policy.get("retry") is not False
        or execution_policy.get("viewer") is not False
        or execution_policy.get("official_algorithm_or_source_modification") is not False
        or not isinstance(paths, dict)
    ):
        raise VerificationError("HFNET_V4_CONTRACT_PROTOCOL_MISMATCH")
    expected_paths = {
        "contract": str(DEFAULT_V4_CONTRACT.resolve(strict=False)),
        "evidence": str(DEFAULT_V4_RESULT.parent.resolve(strict=False)),
        "result": str(DEFAULT_HFNET_RUN_DIR.resolve(strict=False)),
        "raw_trajectory": str(DEFAULT_HFNET_SOURCE.resolve(strict=False)),
        "raw_keyframes": str((DEFAULT_HFNET_RUN_DIR / "trajectory_keyframe.txt").resolve(strict=False)),
        "reserved_vins_csv_bridge_output": str(DEFAULT_HFNET.resolve(strict=False)),
        "reserved_vins_csv_bridge_manifest": str(DEFAULT_BRIDGE_MANIFEST.resolve(strict=False)),
    }
    if paths != expected_paths:
        raise VerificationError("HFNET_V4_CONTRACT_PATHS_MISMATCH")
    profile_sha256 = sha256_bytes(canonical_json(profile))
    if contract.get("frozen_profile_sha256") != profile_sha256:
        raise VerificationError("HFNET_V4_CONTRACT_PROFILE_HASH_MISMATCH")
    immutables = result.get("immutables")
    if not isinstance(immutables, dict) or immutables.get("profile_sha256") != profile_sha256:
        raise VerificationError("HFNET_V4_RESULT_PROFILE_HASH_MISMATCH")
    official = profile.get("official")
    support = official.get("support_identities") if isinstance(official, dict) else None
    if not isinstance(support, dict):
        raise VerificationError("HFNET_V4_PROFILE_SUPPORT_IDENTITIES_MISSING")
    expected_support = {
        "v4_runner": exact_identity(ROOT / "scripts/run_hfnet_slam_a02_long1801_headless_v4.py", HFNET_PYTHON_RUNTIME_CLOSURE["scripts/run_hfnet_slam_a02_long1801_headless_v4.py"][1], "HFNET_V4_PROFILE_RUNNER"),
        "v3_runner": exact_identity(ROOT / "scripts/run_hfnet_slam_a02_full901_headless_v3.py", HFNET_PYTHON_RUNTIME_CLOSURE["scripts/run_hfnet_slam_a02_full901_headless_v3.py"][1], "HFNET_V4_PROFILE_V3_RUNNER"),
        "shared_exporter": exact_identity(ROOT / "scripts/export_aqualoc_a02_shared_4500_6300_v1.py", SHARED_EXPORTER_SHA256, "HFNET_V4_PROFILE_SHARED_EXPORTER"),
        "world_body_bridge": exact_identity(ROOT / "scripts/bridge_hfnet_world_body_to_vins_csv_v1.py", BRIDGE_SHA256, "HFNET_V4_PROFILE_BRIDGE"),
        "evaluation_config": exact_identity(DEFAULT_EVAL_CONFIG, CONFIG_SHA256, "HFNET_V4_PROFILE_EVAL_CONFIG"),
    }
    if support != expected_support:
        raise VerificationError("HFNET_V4_PROFILE_SUPPORT_IDENTITIES_MISMATCH")
    return contract_identity, snapshot_identity, profile_sha256


def validate_bridge_chain(hfnet_csv: Path, bridge_manifest_path: Path, run_result_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    hfnet_csv = hfnet_csv.resolve(strict=False)
    bridge_manifest_path = bridge_manifest_path.resolve(strict=False)
    run_result_path = run_result_path.resolve(strict=False)
    output_payload, output_identity = read_regular(hfnet_csv, "HFNET_BRIDGE_OUTPUT")
    bridge, bridge_identity = load_canonical_json(bridge_manifest_path, "HFNET_BRIDGE_MANIFEST")
    result, result_identity = load_canonical_json(run_result_path, "HFNET_V4_RESULT")
    if bridge.get("schema_version") != BRIDGE_SCHEMA or bridge.get("status") != "PASS":
        raise VerificationError("HFNET_BRIDGE_SCHEMA_OR_STATUS_MISMATCH")
    if bridge.get("output") != output_identity:
        raise VerificationError("HFNET_BRIDGE_OUTPUT_IDENTITY_MISMATCH")
    producer = exact_identity(
        ROOT / "scripts/bridge_hfnet_world_body_to_vins_csv_v1.py",
        BRIDGE_SHA256,
        "HFNET_BRIDGE_PRODUCER",
    )
    if bridge.get("producer") != producer or bridge.get("semantics") != bridge_semantics_contract():
        raise VerificationError("HFNET_BRIDGE_PRODUCER_OR_SEMANTICS_MISMATCH")
    if result.get("schema_version") != V4_SCHEMA or result.get("status") != V4_STATUS or result.get("return_code") != 0 or result.get("evaluable") is not True:
        raise VerificationError("HFNET_V4_RESULT_NOT_PASS")
    execution = result.get("execution")
    gate = result.get("gate")
    trajectory = gate.get("trajectory") if isinstance(gate, dict) else None
    keyframes = gate.get("keyframe_trajectory") if isinstance(gate, dict) else None
    if not isinstance(execution, dict) or execution.get("command_started") is not True or execution.get("process_start_count") != 1 or execution.get("raw_returncode") != 0 or execution.get("timed_out") is not False:
        raise VerificationError("HFNET_V4_EXECUTION_GATE_MISMATCH")
    if not isinstance(trajectory, dict) or trajectory.get("gate_pass") is not True or not isinstance(trajectory.get("identity"), dict):
        raise VerificationError("HFNET_V4_TRAJECTORY_GATE_MISMATCH")
    if not isinstance(keyframes, dict) or keyframes.get("gate_pass") is not True or not isinstance(keyframes.get("identity"), dict):
        raise VerificationError("HFNET_V4_KEYFRAME_GATE_MISMATCH")
    if bridge.get("source") != trajectory["identity"]:
        raise VerificationError("HFNET_BRIDGE_SOURCE_NOT_V4_GATED_TRAJECTORY")
    source_path = Path(str(trajectory["identity"].get("path")))
    if source_path != DEFAULT_HFNET_SOURCE.resolve(strict=False):
        raise VerificationError("HFNET_V4_TRAJECTORY_PATH_MISMATCH")
    source_payload, source_identity = read_regular(source_path, "HFNET_V4_RAW_TRAJECTORY")
    if source_identity != trajectory["identity"]:
        raise VerificationError("HFNET_V4_TRAJECTORY_CURRENT_IDENTITY_MISMATCH")
    rebuilt_payload, rebuilt_rows = independently_rebuild_bridge_payload(source_payload)
    if output_payload != rebuilt_payload or bridge.get("row_count") != rebuilt_rows:
        raise VerificationError("HFNET_BRIDGE_OUTPUT_NOT_INDEPENDENT_EXACT_REBUILD")
    bridge_result = bridge.get("v4_run_result")
    if not isinstance(bridge_result, dict) or bridge_result.get("identity") != result_identity or bridge_result.get("trajectory_source_identity_match") is not True:
        raise VerificationError("HFNET_BRIDGE_RUN_RESULT_BINDING_MISMATCH")
    if not output_payload:
        raise VerificationError("HFNET_BRIDGE_OUTPUT_EMPTY")
    contract_identity, snapshot_identity, profile_sha256 = validate_v4_contract_snapshot_and_profile(result)
    if bridge_result.get("v4_profile_sha256") != profile_sha256:
        raise VerificationError("HFNET_BRIDGE_PROFILE_HASH_BINDING_MISMATCH")
    return output_identity, bridge_identity, result_identity, contract_identity, snapshot_identity


def validate_arm(path: Path, label: str) -> dict[str, object]:
    payload, identity = read_regular(path, f"ARM_{label}")
    if not payload.strip():
        raise VerificationError(f"ARM_{label}_TRAJECTORY_EMPTY")
    try:
        body = evaluator.load_vins_body_csv(path)
        if body.quaternions_xyzw is None:
            raise VerificationError(f"ARM_{label}_ORIENTATION_MISSING")
        evaluator.validate_estimate_samples(body.stamps, body.positions, body.quaternions_xyzw)
    except (OSError, ValueError) as error:
        raise VerificationError(f"ARM_{label}_POSE_VALIDATION_FAILED:{error}") from error
    score_first = Decimal(SCORE_FIRST_NS) / Decimal(1_000_000_000)
    score_last = Decimal(SCORE_LAST_NS) / Decimal(1_000_000_000)
    score_count = sum(1 for value in body.stamps if Decimal(str(value)) >= score_first and Decimal(str(value)) <= score_last)
    if len(body.stamps) < 30 or score_count < 30:
        raise VerificationError(f"ARM_{label}_INSUFFICIENT_SCORE_SUPPORT")
    _, post_identity = read_regular(path, f"ARM_{label}_POST_VALIDATION")
    if post_identity != identity:
        raise VerificationError(f"ARM_{label}_TRAJECTORY_CHANGED_DURING_VALIDATION")
    return {
        **identity,
        "pose_rows": int(len(body.stamps)),
        "score_pose_rows": int(score_count),
        "pose_convention": "world_T_body",
        "raw_row_order_validated_without_sort_filter_or_deduplication": True,
        "finite_pose_data": True,
        "strictly_increasing_timestamps": True,
    }


def validate_vins_raw_csv_schema(path: Path, label: str) -> dict[str, object]:
    payload, identity = read_regular(path, f"ARM_{label}_RAW_VINS_CSV")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise VerificationError(f"ARM_{label}_RAW_VINS_CSV_NOT_ASCII") from error
    if not lines or any(not line for line in lines):
        raise VerificationError(f"ARM_{label}_RAW_VINS_CSV_EMPTY_OR_BLANK_ROW")
    previous_ns: int | None = None
    for line_number, row in enumerate(csv.reader(lines), 1):
        if len(row) != 12 or row[-1] != "":
            raise VerificationError(
                f"ARM_{label}_RAW_VINS_CSV_ROW_{line_number}_NOT_11_NUMERIC_PLUS_EMPTY"
            )
        if not row[0].isdigit():
            raise VerificationError(
                f"ARM_{label}_RAW_VINS_CSV_ROW_{line_number}_TIMESTAMP_NOT_UINT_NS"
            )
        try:
            values = [Decimal(value) for value in row[:11]]
        except InvalidOperation as error:
            raise VerificationError(
                f"ARM_{label}_RAW_VINS_CSV_ROW_{line_number}_NONNUMERIC"
            ) from error
        if not all(value.is_finite() for value in values):
            raise VerificationError(
                f"ARM_{label}_RAW_VINS_CSV_ROW_{line_number}_NONFINITE"
            )
        stamp_ns = int(row[0])
        if previous_ns is not None and stamp_ns <= previous_ns:
            raise VerificationError(
                f"ARM_{label}_RAW_VINS_CSV_ROW_{line_number}_NOT_STRICTLY_INCREASING"
            )
        previous_ns = stamp_ns
    return {
        **identity,
        "row_count": len(lines),
        "writer_schema": "11_numeric_fields_plus_terminal_empty_field",
        "all_numeric_fields_finite": True,
        "integer_nanosecond_timestamps_strictly_increasing_in_raw_file_order": True,
    }


def validate_vins_log(path: Path, label: str) -> dict[str, object]:
    payload, identity = read_regular(path, f"ARM_{label}_VINS_LOG")
    if not payload:
        raise VerificationError(f"ARM_{label}_VINS_LOG_EMPTY")
    initialization_matches = list(INITIALIZATION_PATTERN.finditer(payload))
    initialization_count = len(initialization_matches)
    if initialization_count != 1:
        raise VerificationError(
            f"ARM_{label}_INITIALIZATION_SUCCESS_COUNT_{initialization_count}_NOT_ONE"
        )
    initialization_offset = initialization_matches[0].start()
    post_initialization = payload[initialization_matches[0].end() :]
    total_counts = {name: len(pattern.findall(payload)) for name, pattern in LOG_PATTERNS.items()}
    post_counts = {
        name: len(pattern.findall(post_initialization)) for name, pattern in LOG_PATTERNS.items()
    }
    post_solver_failures = post_counts["linear_solver_failure"]
    post_restart_markers = sum(
        post_counts[name]
        for name in ("failure_detection", "system_reboot", "external_restart")
    )
    if post_solver_failures:
        raise VerificationError(
            f"ARM_{label}_POST_INITIALIZATION_LINEAR_SOLVER_FAILURES_{post_solver_failures}"
        )
    if post_restart_markers:
        raise VerificationError(
            f"ARM_{label}_POST_INITIALIZATION_RESTART_MARKERS_{post_restart_markers}"
        )
    _, post_identity = read_regular(path, f"ARM_{label}_VINS_LOG_POST_VALIDATION")
    if post_identity != identity:
        raise VerificationError(f"ARM_{label}_VINS_LOG_CHANGED_DURING_VALIDATION")
    return {
        **identity,
        "initialization_success_pattern": INITIALIZATION_PATTERN.pattern.decode("ascii"),
        "initialization_success_count": initialization_count,
        "initialization_marker_byte_offset": initialization_offset,
        "marker_counts_total": total_counts,
        "marker_counts_after_initialization": post_counts,
        "pre_initialization_linear_solver_failure_count": total_counts["linear_solver_failure"] - post_counts["linear_solver_failure"],
        "post_initialization_linear_solver_failure_count": post_solver_failures,
        "post_initialization_restart_marker_count": post_restart_markers,
    }


def parse_unique_key_value_lines(payload: bytes, label: str) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise VerificationError(f"{label}_NOT_UTF8") from error
    result: dict[str, str] = {}
    for line in lines:
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key or key in result:
            raise VerificationError(f"{label}_DUPLICATE_OR_EMPTY_KEY")
        result[key] = value
    return result


def require_unique_yaml_scalar(text: str, key: str, expected: str, label: str) -> None:
    prefix = key + ":"
    matches = [line[len(prefix) :].strip().strip('"') for line in text.splitlines() if line.startswith(prefix)]
    if matches != [expected]:
        raise VerificationError(f"{label}_YAML_{key}_MISMATCH")


def vins_process_receipt_contract(label: str) -> dict[str, object]:
    contracts = {
        "B1_CONSTQ": {
            "run_dir": DEFAULT_B1.parents[1],
            "feature_bag": DEFAULT_B1_CONSTQ_BAG,
            "port": 11531,
            "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1",
        },
        "XFEATBIRTH_RAWLK": {
            "run_dir": DEFAULT_XFEAT.parents[1],
            "feature_bag": DEFAULT_XFEAT_BAG,
            "port": 11532,
            "tag": "litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_r1",
        },
    }
    try:
        return contracts[label]
    except KeyError as error:
        raise VerificationError(f"VINS_PROCESS_RECEIPT_UNKNOWN_ARM:{label}") from error


def build_vins_process_receipt(label: str, return_code: int) -> dict[str, object]:
    if isinstance(return_code, bool) or return_code < 0 or return_code > 255:
        raise VerificationError("VINS_PROCESS_RECEIPT_RETURN_CODE_OUT_OF_RANGE")
    contract = vins_process_receipt_contract(label)
    return {
        "schema_version": VINS_PROCESS_RECEIPT_SCHEMA,
        "status": "PASS_PROCESS_RC0" if return_code == 0 else "FAIL_PROCESS_NONZERO",
        "arm": label,
        "return_code": return_code,
        "attempt_count": 1,
        "no_retry": True,
        "run_dir": str(Path(contract["run_dir"]).absolute()),
        "feature_bag": str(Path(contract["feature_bag"]).absolute()),
        "port": contract["port"],
        "tag": contract["tag"],
        "runner": {"path": str(RUNNER), "sha256": RUNNER_SHA256},
    }


def validate_vins_process_receipt(run_dir: Path, label: str) -> dict[str, object]:
    path = run_dir / "process_rc_receipt.json"
    receipt, receipt_identity = load_canonical_json(
        path, f"ARM_{label}_PROCESS_RC_RECEIPT"
    )
    expected = build_vins_process_receipt(label, 0)
    if receipt != expected:
        raise VerificationError(f"ARM_{label}_PROCESS_RC_RECEIPT_NOT_EXACT_RC0")
    return receipt_identity


def validate_vins_replay_provenance(
    *,
    trajectory_path: Path,
    expected_feature_bag: Mapping[str, object],
    expected_camera_config: Mapping[str, object],
    raw_window_bag: Path,
    eval_config: Path,
    port: int,
    label: str,
) -> dict[str, object]:
    run_dir = trajectory_path.parents[1]
    process_receipt_identity = validate_vins_process_receipt(run_dir, label)
    default_feature_path = (
        DEFAULT_B1_CONSTQ_BAG if label == "B1_CONSTQ" else DEFAULT_XFEAT_BAG
    )
    recorded_feature_path = Path(str(expected_feature_bag["path"]))
    expected_feature_path = (
        default_feature_path
        if recorded_feature_path == default_feature_path.resolve(strict=False)
        else recorded_feature_path
    )
    _, current_feature_identity = read_regular(
        expected_feature_path, f"ARM_{label}_FEATURE_BAG"
    )
    if current_feature_identity != dict(expected_feature_bag):
        raise VerificationError(f"ARM_{label}_FEATURE_BAG_CHANGED_AFTER_AUDIT")

    replay_path = run_dir / "replay_manifest.txt"
    replay_payload, replay_identity = read_regular(replay_path, f"ARM_{label}_REPLAY_MANIFEST")
    replay = parse_unique_key_value_lines(replay_payload, f"ARM_{label}_REPLAY_MANIFEST")
    expected_replay = {
        "run_dir": str(run_dir.absolute()),
        "raw_bag": str(raw_window_bag.absolute()),
        "play_bag": str(expected_feature_path.absolute()),
        "vins_csv": str(trajectory_path.absolute()),
    }
    if replay != expected_replay:
        raise VerificationError(f"ARM_{label}_REPLAY_MANIFEST_BINDING_MISMATCH")

    config_path = run_dir / "vins_aqualoc_archaeo_external.yaml"
    config_payload, config_identity = read_regular(config_path, f"ARM_{label}_VINS_CONFIG")
    try:
        config_text = config_payload.decode("ascii")
    except UnicodeError as error:
        raise VerificationError(f"ARM_{label}_VINS_CONFIG_NOT_ASCII") from error
    for key, expected in (
        ("multiple_thread", "0"),
        ("imu_topic", "/rtimulib_node/imu"),
        ("image0_topic", "/unused/image"),
        ("output_path", str((run_dir / "vins_output").absolute())),
        ("cam0_calib", "aqualoc_archaeo02_pinhole.yaml"),
        ("estimate_extrinsic", "0"),
        ("max_cnt", "150"),
        ("freq", "10"),
        ("max_solver_time", "0.04"),
        ("max_num_iterations", "8"),
        ("loop_closure", "0"),
        ("td", "-0.053694112369382575"),
        ("estimate_td", "0"),
    ):
        require_unique_yaml_scalar(config_text, key, expected, f"ARM_{label}")
    try:
        replay_transform = evaluator.load_body_t_sensor(config_path)
        frozen_transform = evaluator.load_body_t_sensor(eval_config)
    except (OSError, ValueError) as error:
        raise VerificationError(f"ARM_{label}_BODY_T_CAM0_PARSE_FAILED:{error}") from error
    if not np.allclose(replay_transform, frozen_transform, rtol=0.0, atol=5e-8):
        raise VerificationError(f"ARM_{label}_BODY_T_CAM0_NOT_UNIFIED_CONFIG")
    normalized_config = config_text.replace(
        str((run_dir / "vins_output").absolute()), "<FROZEN_RUN_OUTPUT>"
    ).encode("ascii")
    normalized_config_sha256 = sha256_bytes(normalized_config)
    if normalized_config_sha256 != EXPECTED_NORMALIZED_VINS_CONFIG_SHA256:
        raise VerificationError(f"ARM_{label}_FULL_NORMALIZED_VINS_CONFIG_MISMATCH")

    camera_path = run_dir / "aqualoc_archaeo02_pinhole.yaml"
    _, camera_identity = read_regular(camera_path, f"ARM_{label}_CAMERA_CONFIG")
    if any(
        camera_identity.get(key) != expected_camera_config.get(key)
        for key in ("size_bytes", "sha256")
    ):
        raise VerificationError(f"ARM_{label}_CAMERA_CONFIG_NOT_EXACT_B1_FROZEN_CAMERA")
    env_path = run_dir / "vins_env_manifest.txt"
    env_payload, env_identity = read_regular(env_path, f"ARM_{label}_VINS_ENV")
    env = parse_unique_key_value_lines(env_payload, f"ARM_{label}_VINS_ENV")
    raw_root = ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    receipt_contract = vins_process_receipt_contract(label)
    expected_env = {
        "pwd": str(ROOT),
        "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "ROS_MASTER_URI": f"http://localhost:{port}",
        "ROS_DISTRO": "noetic",
        "CMAKE_PREFIX_PATH": "/opt/ros/noetic:/home/ma/SLAM/VINS-Fusion-origin/devel",
        "ROS_PACKAGE_PATH": "/opt/ros/noetic/share:/home/ma/SLAM/VINS-Fusion-origin/src",
        "LD_LIBRARY_PATH": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
        "PYTHONPATH": "/opt/ros/noetic/lib/python3/dist-packages",
        "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "CATKIN_SETUP_UTIL_ARGS": "--local --extend",
        "ROOT": str(ROOT),
        "AQUALOC_ROOT": str(raw_root),
        "RAW_TAR": str(raw_root / "archaeo_sequence_2_raw_data.tar.gz"),
        "RAW_ROOT": "raw_data",
        "GT_TXT": str(raw_root / "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"),
        "RAW_BAG": str(raw_window_bag.absolute()),
        "FEATURE_BAG_OVERRIDE": str(expected_feature_path.absolute()),
        "FRONTEND_CONFIG": str(ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
        "BACKEND_REPLAY_ONLY": "0",
        "RUN_VINS": "1",
        "FORCE_RAW": "0",
        "FORCE_EXPORT": "0",
        "EXPORT_FEATURES": "0",
        "VINS_MULTIPLE_THREAD": "0",
        "VINS_TD": "-0.053694112369382575",
        "VINS_ESTIMATE_TD": "0",
        "VINS_MAX_SOLVER_TIME": "0.04",
        "VINS_MAX_NUM_ITERATIONS": "8",
        "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
        "PLAY_RATE": "1.0",
        "POST_PLAY_SLEEP": "8",
        "ROSBAG_PLAY_DELAY": "3",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
        "ROSBAG_PLAY_TOPICS": "",
        "WAIT_FOR_VINS_SUBSCRIBERS": "0",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
        "PORT": str(port),
        "TAG": str(receipt_contract["tag"]),
        "vins_binary": str(VINS_BINARY),
        "rospack_find_vins": "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator",
    }
    expected_env_keys = set(expected_env) | {
        "timestamp_utc", "hostname", "vins_binary_stat", "vins_binary_md5"
    }
    if set(env) != expected_env_keys or any(env.get(key) != value for key, value in expected_env.items()):
        raise VerificationError(f"ARM_{label}_VINS_ENV_BINDING_MISMATCH")
    actual_md5 = hashlib.md5(VINS_BINARY.read_bytes()).hexdigest()
    expected_md5_line = f"{actual_md5}  {VINS_BINARY}"
    if env.get("vins_binary_md5") != expected_md5_line:
        raise VerificationError(f"ARM_{label}_VINS_ENV_BINARY_MD5_MISMATCH")
    return {
        "feature_bag": current_feature_identity,
        "process_rc_receipt": process_receipt_identity,
        "replay_manifest": replay_identity,
        "vins_config": config_identity,
        "normalized_vins_config_sha256": normalized_config_sha256,
        "camera_config": camera_identity,
        "environment_manifest": env_identity,
        "ros_master_port": port,
        "runner_identity": exact_identity(RUNNER, RUNNER_SHA256, f"ARM_{label}_RUNNER"),
        "vins_binary_identity": exact_identity(VINS_BINARY, VINS_BINARY_SHA256, f"ARM_{label}_VINS_BINARY"),
    }


def validate_vins_arm(
    path: Path,
    log_path: Path,
    label: str,
    *,
    expected_feature_bag: Mapping[str, object],
    expected_camera_config: Mapping[str, object],
    raw_window_bag: Path,
    eval_config: Path,
    port: int,
) -> dict[str, object]:
    raw_schema = validate_vins_raw_csv_schema(path, label)
    trajectory = validate_arm(path, label)
    for key in ("path", "size_bytes", "sha256"):
        if raw_schema[key] != trajectory[key]:
            raise VerificationError(f"ARM_{label}_TRAJECTORY_CHANGED_BETWEEN_RAW_AND_POSE_VALIDATION")
    return {
        "status": "PASS",
        "raw_vins_csv_schema": raw_schema,
        "trajectory": trajectory,
        "vins_log": validate_vins_log(log_path, label),
        "replay_provenance": validate_vins_replay_provenance(
            trajectory_path=path,
            expected_feature_bag=expected_feature_bag,
            expected_camera_config=expected_camera_config,
            raw_window_bag=raw_window_bag,
            eval_config=eval_config,
            port=port,
            label=label,
        ),
    }


def capture_arm(validation) -> dict[str, object]:
    try:
        return validation()
    except (VerificationError, OSError, ValueError) as error:
        return {"status": "FAIL", "reasons": [str(error)]}


def build_record(args: argparse.Namespace) -> dict[str, object]:
    static_freeze_gate = validate_static_freeze(args.freeze)
    frozen = {
        "static_freeze_gate": static_freeze_gate,
        "evaluation_config": exact_identity(args.eval_config, CONFIG_SHA256, "EVALUATION_CONFIG"),
        "evaluator": exact_identity(args.evaluator, EVALUATOR_SHA256, "EVALUATOR"),
        "trajectory_eval_core": exact_identity(args.core, CORE_SHA256, "TRAJECTORY_EVAL_CORE"),
        "aqualoc_vins_runner": exact_identity(RUNNER, RUNNER_SHA256, "AQUALOC_VINS_RUNNER"),
        "vins_binary": exact_identity(VINS_BINARY, VINS_BINARY_SHA256, "VINS_BINARY"),
        "vins_dynamic_linkage": validate_vins_dynamic_linkage(VINS_BINARY),
        "b1_guarded_runner_v3": exact_identity(ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh", B1_V3_RUNNER_SHA256, "B1_GUARDED_RUNNER_V3"),
        "b1_execution_repair_v4": exact_identity(ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh", B1_V4_EXECUTION_REPAIR_SHA256, "B1_EXECUTION_REPAIR_V4"),
        "b1_execution_repair_v4_tests": exact_identity(ROOT / "scripts/tests/test_a02_b1_guarded_execution_repair_v4.py", B1_V4_EXECUTION_REPAIR_TESTS_SHA256, "B1_EXECUTION_REPAIR_V4_TESTS"),
        "b1_legacy_guarded_runner": exact_identity(ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh", B1_LEGACY_RUNNER_SHA256, "B1_LEGACY_GUARDED_RUNNER"),
        "b1_backend_quality_contract": exact_identity(args.b1_backend_contract, B1_BACKEND_CONTRACT_SHA256, "B1_BACKEND_QUALITY_CONTRACT"),
        "b1_base_backend_quality_contract": exact_identity(DEFAULT_B1_BASE_BACKEND_CONTRACT, B1_BASE_BACKEND_CONTRACT_SHA256, "B1_BASE_BACKEND_QUALITY_CONTRACT"),
        "b1_contract_checker_v3": exact_identity(ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py", B1_CONTRACT_CHECKER_SHA256, "B1_CONTRACT_CHECKER_V3"),
        "b1_v2_common_checker_runtime_dependency": exact_identity(ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py", B1_V2_COMMON_CHECKER_SHA256, "B1_V2_COMMON_CHECKER_RUNTIME_DEPENDENCY"),
        "b1_legacy_contract_checker": exact_identity(ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py", B1_LEGACY_CONTRACT_CHECKER_SHA256, "B1_LEGACY_CONTRACT_CHECKER"),
        "b1_nativeq_checker_core": exact_identity(ROOT / "scripts/check_nativeq_backend_contract.py", B1_NATIVEQ_CHECKER_CORE_SHA256, "B1_NATIVEQ_CHECKER_CORE"),
        "b1_contract_hash_builder_v3": exact_identity(ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v3.py", B1_CONTRACT_BUILDER_SHA256, "B1_CONTRACT_HASH_BUILDER_V3"),
        "b1_v2_contract_builder_indirect_dependency": exact_identity(ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v2.py", B1_V2_CONTRACT_BUILDER_SHA256, "B1_V2_CONTRACT_BUILDER_INDIRECT_DEPENDENCY"),
        "b1_legacy_contract_hash_builder": exact_identity(ROOT / "scripts/build_nativeq_backend_contract.py", B1_LEGACY_CONTRACT_BUILDER_SHA256, "B1_LEGACY_CONTRACT_HASH_BUILDER"),
        "b1_exporter_transition_prover": exact_identity(ROOT / "scripts/prove_b1_klt_exporter_transition_v2.py", B1_TRANSITION_PROVER_SHA256, "B1_EXPORTER_TRANSITION_PROVER"),
        "b1_exporter_transition_proof": exact_identity(DEFAULT_B1_TRANSITION_PROOF, B1_TRANSITION_PROOF_SHA256, "B1_EXPORTER_TRANSITION_PROOF"),
        "b1_v3_synthetic_tests": exact_identity(ROOT / "scripts/tests/test_b1_klt_nativeq_current_exporter_contract_v3.py", B1_V3_TESTS_SHA256, "B1_V3_SYNTHETIC_TESTS"),
        "b1_data_eligibility_manifest": exact_identity(args.b1_eligibility_manifest, B1_ELIGIBILITY_MANIFEST_SHA256, "B1_DATA_ELIGIBILITY_MANIFEST"),
        "b1_frontend_exporter": exact_identity(ROOT / "uw_frontend/ros/export_vins_features.py", B1_FRONTEND_EXPORTER_SHA256, "B1_FRONTEND_EXPORTER"),
        "quality_rewriter": exact_identity(ROOT / "scripts/agent_qi_calibration_rewrite_bag.py", QUALITY_REWRITER_SHA256, "QUALITY_REWRITER"),
        "quality_auditor": exact_identity(ROOT / "scripts/audit_quality_partition.py", QUALITY_AUDITOR_SHA256, "QUALITY_AUDITOR"),
        "xfeat_exporter": exact_identity(ROOT / "scripts/export_xfeat_lk_carrier_v1.py", XFEAT_EXPORTER_SHA256, "XFEAT_EXPORTER"),
        "xfeat_auditor": exact_identity(ROOT / "scripts/audit_xfeat_lk_carrier_v1.py", XFEAT_AUDITOR_SHA256, "XFEAT_AUDITOR"),
        "xfeat_carrier_base": exact_identity(ROOT / "scripts/export_superpoint_lk_carrier_v1.py", XFEAT_CARRIER_BASE_SHA256, "XFEAT_CARRIER_BASE"),
        "xfeat_audit_base": exact_identity(ROOT / "scripts/audit_superpoint_lk_carrier_v1.py", XFEAT_AUDIT_BASE_SHA256, "XFEAT_AUDIT_BASE"),
        "xfeat_quality_reference_source": exact_identity(ROOT / "uw_frontend/quality/image_quality.py", XFEAT_QUALITY_REFERENCE_SOURCE_SHA256, "XFEAT_QUALITY_REFERENCE_SOURCE"),
        "vins_environment_recorder": exact_identity(ROOT / "scripts/record_vins_env.sh", VINS_ENV_RECORDER_SHA256, "VINS_ENV_RECORDER"),
        "vins_runner_internal_evaluator": exact_identity(ROOT / "scripts/evaluate_vins_sim_ape.py", VINS_SIM_EVALUATOR_SHA256, "VINS_SIM_EVALUATOR"),
        "shared_exporter": exact_identity(ROOT / "scripts/export_aqualoc_a02_shared_4500_6300_v1.py", SHARED_EXPORTER_SHA256, "SHARED_EXPORTER"),
        "window_materializer": exact_identity(ROOT / "scripts/materialize_aqualoc_a02_4500_6300_window_v1.py", MATERIALIZER_SHA256, "WINDOW_MATERIALIZER"),
        "canonical_raw_converter": exact_identity(ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py", RAW_CONVERTER_SHA256, "CANONICAL_RAW_CONVERTER"),
        "b1_runtime_closures": validate_b1_runtime_closures(),
        "xfeat_audit_runtime": validate_xfeat_audit_runtime(),
        "xfeat_export_runtime": validate_xfeat_export_runtime(),
        "xfeat_official_closure": validate_xfeat_official_closure(),
        "hfnet_python_runtime_closure": validate_hfnet_python_runtime_closure(),
        "hfnet_v4_synthetic_tests": exact_identity(ROOT / "scripts/tests/test_run_hfnet_slam_a02_long1801_headless_v4.py", HFNET_V4_TESTS_SHA256, "HFNET_V4_SYNTHETIC_TESTS"),
        "hfnet_bridge": exact_identity(ROOT / "scripts/bridge_hfnet_world_body_to_vins_csv_v1.py", BRIDGE_SHA256, "HFNET_BRIDGE"),
    }
    reference, shared_manifest = validate_reference(args.shared_root)
    shared_source_chain = validate_shared_source_chain(
        args.shared_root, args.window_bag, args.window_manifest
    )
    if shared_source_chain["shared_manifest_identity"] != shared_manifest:
        raise VerificationError("SHARED_MANIFEST_IDENTITY_CHANGED_DURING_VALIDATION")
    b1_guard_governance = validate_b1_guard_governance(
        decision_dir=args.b1_guard_decision_dir,
        contract_path=args.b1_backend_contract,
        eligibility_manifest=args.b1_eligibility_manifest,
        raw_tar_claim=shared_source_chain["canonical_raw_tar_claim"],
        gt_claim=shared_source_chain["canonical_gt_claim"],
        frontend_exporter_identity=frozen["b1_frontend_exporter"],
        vins_binary_identity=frozen["vins_binary"],
        vins_dynamic_linkage=frozen["vins_dynamic_linkage"],
    )
    quality_chain = capture_arm(
        lambda: validate_quality_chain(
            args.b1_native_bag, args.b1_constq_bag, args.b1_quality_audit
        )
    )
    xfeat_chain = capture_arm(
        lambda: validate_xfeat_chain(
            source_bag=args.b1_constq_bag,
            raw_bag=args.window_bag,
            camera_yaml=args.b1_native_camera,
            output_bag=args.xfeat_bag,
            manifest_path=args.xfeat_manifest,
            audit_path=args.xfeat_audit,
        )
    )

    def validate_b1() -> dict[str, object]:
        if quality_chain.get("status") != "PASS":
            raise VerificationError("B1_CONSTQ_INPUT_LINEAGE_NOT_PASS")
        _, native_camera_identity = read_regular(
            args.b1_native_camera, "B1_NATIVE_FROZEN_CAMERA"
        )
        result = validate_vins_arm(
            args.b1,
            args.b1_log,
            "B1_CONSTQ",
            expected_feature_bag=quality_chain["constq_feature_bag"],
            expected_camera_config=native_camera_identity,
            raw_window_bag=args.window_bag,
            eval_config=args.eval_config,
            port=11531,
        )
        result["input_lineage"] = quality_chain
        result["guard_governance"] = b1_guard_governance
        return result

    def validate_xfeat() -> dict[str, object]:
        if xfeat_chain.get("status") != "PASS":
            raise VerificationError("XFEAT_INPUT_LINEAGE_NOT_PASS")
        result = validate_vins_arm(
            args.xfeat,
            args.xfeat_log,
            "XFEATBIRTH_RAWLK",
            expected_feature_bag=xfeat_chain["xfeat_feature_bag"],
            expected_camera_config=xfeat_chain["camera_yaml"],
            raw_window_bag=args.window_bag,
            eval_config=args.eval_config,
            port=11532,
        )
        result["input_lineage"] = xfeat_chain
        return result

    arms = {
        "B1_CONSTQ": capture_arm(validate_b1),
        "XFEATBIRTH_RAWLK": capture_arm(validate_xfeat),
    }
    if all(arms[label].get("status") == "PASS" for label in ("B1_CONSTQ", "XFEATBIRTH_RAWLK")):
        b1_normalized = arms["B1_CONSTQ"]["replay_provenance"]["normalized_vins_config_sha256"]
        xfeat_normalized = arms["XFEATBIRTH_RAWLK"]["replay_provenance"]["normalized_vins_config_sha256"]
        if b1_normalized != xfeat_normalized:
            for label in ("B1_CONSTQ", "XFEATBIRTH_RAWLK"):
                arms[label] = {
                    "status": "FAIL",
                    "reasons": ["NORMALIZED_VINS_CONFIGS_DIFFER_BETWEEN_COMPONENT_ARMS"],
                    "failed_observation": arms[label],
                }
    hfnet_provenance: dict[str, object] = {}

    def validate_hfnet_arm() -> dict[str, object]:
        hfnet, bridge_manifest, run_result, v4_contract, v4_contract_snapshot = validate_bridge_chain(
            args.hfnet, args.bridge_manifest, args.v4_run_result
        )
        hfnet_provenance.update(
            {
                "bridge_manifest_identity": bridge_manifest,
                "v4_run_result_identity": run_result,
                "v4_contract_identity": v4_contract,
                "v4_contract_snapshot_identity": v4_contract_snapshot,
                "v4_status_required": V4_STATUS,
            }
        )
        return {
            "status": "PASS",
            "trajectory": validate_arm(args.hfnet, "HFNET_WHOLE_SYSTEM"),
            "bridge_output_identity": hfnet,
        }

    arms["HFNET_WHOLE_SYSTEM"] = capture_arm(validate_hfnet_arm)
    all_arms_pass = all(arms[label].get("status") == "PASS" for label in ARM_LABELS)
    return {
        "schema_version": SCHEMA,
        "status": STATUS if all_arms_pass else "FAIL_ONE_OR_MORE_SCIENTIFIC_ARMS",
        "scientific_role": "POST_STOP_EXPLORATORY_THREE_ARM_INPUT_BINDING_NOT_AN_ACCURACY_RESULT",
        "frozen_tools": frozen,
        "evaluation_arm_config_sha256_by_arm": {label: CONFIG_SHA256 for label in ARM_LABELS},
        "reference": {
            "identity": reference,
            "shared_manifest_identity": shared_manifest,
            "shared_and_canonical_source_chain": shared_source_chain,
            "row_count": EXPECTED_REFERENCE_ROWS,
            "uniform_grid_points_expected": EXPECTED_UNIFORM_GRID_POINTS,
            "independent_ground_truth": False,
        },
        "arms": arms,
        "hfnet_provenance": hfnet_provenance,
        "evaluation_contract": {
            "reference_mode": "reference_tum_46_rows",
            "window_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
            "ape_valid_and_rpe_valid_required": True,
            "all_three_legal_trajectories_required_for_ranking": True,
            "all_three_legal_trajectories_observed": all_arms_pass,
            "three_arm_evaluation_eligible": all_arms_pass,
            "arm_scientific_failure_does_not_suppress_other_mandatory_arms": True,
        },
    }


def frozen_evaluation_protocol(expected_reference: Path) -> dict[str, object]:
    return {
        "contrast_name": "A02_4500_6300_POST_STOP_B1_XFEAT_HFNET",
        "reference": str(expected_reference.absolute()),
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "window_start_s": float(np.longdouble("1542829061.692686528")),
        "window_end_s": float(np.longdouble("1542829106.687510592")),
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "reference_time_offset_s": 0.0,
        "arm_time_offsets_s": {label: 0.0 for label in ARM_LABELS},
    }


def recompute_frozen_common_support_summary(args: argparse.Namespace) -> dict[str, object]:
    reference_path = args.shared_root / "shared/reference_proxy.tum"
    reference_series = evaluator.load_tum_reference(reference_path)
    reference_stamps, _, _, _ = evaluator.prepare_reference_samples(
        reference_series.stamps,
        reference_series.positions,
        reference_series.quaternions_xyzw,
    )
    window_start = np.longdouble("1542829061.692686528")
    window_end = np.longdouble("1542829106.687510592")
    grid = evaluator.make_uniform_grid(window_start, window_end, 1.0)
    reference = evaluator.resample_trajectory(
        reference_series.stamps,
        reference_series.positions,
        grid,
        2.5,
        reference_series.quaternions_xyzw,
        sample_kind="reference",
    )
    paths = {
        "B1_CONSTQ": args.b1,
        "XFEATBIRTH_RAWLK": args.xfeat,
        "HFNET_WHOLE_SYSTEM": args.hfnet,
    }
    arms = {}
    legacy_reuse = {}
    transform = evaluator.load_body_t_sensor(args.eval_config)
    for label in ARM_LABELS:
        body = evaluator.load_vins_body_csv(paths[label])
        if body.quaternions_xyzw is None:
            raise VerificationError(f"POST_EVAL_{label}_ORIENTATION_MISSING")
        evaluator.validate_estimate_samples(
            body.stamps, body.positions, body.quaternions_xyzw
        )
        legacy_reuse[label] = evaluator.legacy_nearest_reuse_stats(
            body.stamps, reference_stamps
        )
        sensor_positions, sensor_quaternions = evaluator.transform_body_poses_to_sensor(
            body.positions, body.quaternions_xyzw, transform
        )
        arms[label] = evaluator.resample_trajectory(
            body.stamps,
            sensor_positions,
            grid,
            0.25,
            sensor_quaternions,
            sample_kind="estimate",
        )
    evaluation = evaluator.evaluate_common_translation(
        reference,
        arms,
        window_start_s=window_start,
        window_end_s=window_end,
        max_segment_gap_s=2.5,
        rpe_delta_s=1.0,
        min_ape_poses=30,
        min_ape_span_s=10.0,
        min_common_coverage=0.70,
        min_rpe_pairs=10,
    )
    summary = evaluator.clean_json_value(
        evaluator.serializable_summary(
            evaluation,
            reference,
            arms,
            frozen_evaluation_protocol(reference_path),
            legacy_reuse,
        )
    )
    if not isinstance(summary, dict):
        raise VerificationError("RECOMPUTED_COMMON_SUPPORT_SUMMARY_NOT_OBJECT")
    return summary


def validate_evaluation_summary(
    path: Path,
    expected_reference: Path,
    args: argparse.Namespace | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    summary, identity = load_canonical_json(path, "COMMON_SUPPORT_SUMMARY")
    support = summary.get("support")
    protocol = summary.get("protocol")
    arms = summary.get("arms")
    if not isinstance(support, dict) or not isinstance(protocol, dict) or not isinstance(arms, dict):
        raise VerificationError("COMMON_SUPPORT_SUMMARY_SHAPE_MISMATCH")
    if set(arms) != set(ARM_LABELS):
        raise VerificationError("COMMON_SUPPORT_SUMMARY_ARM_SET_MISMATCH")
    if (
        support.get("ape_valid") is not True
        or support.get("rpe_valid") is not True
        or support.get("grid_count") != EXPECTED_UNIFORM_GRID_POINTS
    ):
        raise VerificationError("COMMON_SUPPORT_STRICT_APE_RPE_GRID45_GATE_FAILED")
    if protocol != frozen_evaluation_protocol(expected_reference):
        raise VerificationError("COMMON_SUPPORT_FROZEN_PROTOCOL_MISMATCH")
    for label in ARM_LABELS:
        metrics = arms.get(label)
        if not isinstance(metrics, dict):
            raise VerificationError(f"COMMON_SUPPORT_{label}_METRICS_MISSING")
        for key in ("ape_rmse_m", "rpe_rmse_m"):
            value = metrics.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise VerificationError(f"COMMON_SUPPORT_{label}_{key}_INVALID")
    if args is not None and summary != recompute_frozen_common_support_summary(args):
        raise VerificationError("COMMON_SUPPORT_SUMMARY_NOT_RECOMPUTED_FROM_SEALED_INPUTS")
    return identity, {
        "ape_valid": True,
        "rpe_valid": True,
        "grid_count": EXPECTED_UNIFORM_GRID_POINTS,
        "arm_labels": list(ARM_LABELS),
    }


def build_post_eval_record(args: argparse.Namespace) -> dict[str, object]:
    current_pre_record = build_record(args)
    if current_pre_record.get("status") != STATUS:
        raise VerificationError("CURRENT_PRE_EVAL_INPUTS_NOT_ALL_PASS")
    pre_payload, pre_identity = read_regular(args.evidence, "PRE_EVAL_EVIDENCE_FOR_POST_GATE")
    if pre_payload != canonical_json(current_pre_record):
        raise VerificationError("PRE_EVAL_EVIDENCE_OR_CURRENT_INPUTS_MISMATCH_AT_POST_GATE")
    summary_path = args.eval_dir / "common_support_summary.json"
    summary_failure: str | None = None
    try:
        summary_identity, gates = validate_evaluation_summary(
            summary_path,
            args.shared_root / "shared/reference_proxy.tum",
            args,
        )
    except VerificationError as error:
        _, summary_identity = read_regular(summary_path, "FAILED_COMMON_SUPPORT_SUMMARY")
        gates = {
            "ape_valid": False,
            "rpe_valid": False,
            "grid_count": None,
            "arm_labels": list(ARM_LABELS),
        }
        summary_failure = str(error)
    arm_config_hashes = current_pre_record.get("evaluation_arm_config_sha256_by_arm")
    expected_hashes = {label: CONFIG_SHA256 for label in ARM_LABELS}
    if arm_config_hashes != expected_hashes:
        raise VerificationError("POST_GATE_UNIFIED_CONFIG_BINDING_MISMATCH")
    passed = summary_failure is None
    return {
        "schema_version": POST_EVAL_SCHEMA,
        "status": POST_EVAL_STATUS if passed else "FAIL_STRICT_COMMON_SUPPORT_GATE",
        "scientific_role": "POST_STOP_EXPLORATORY_STRICT_COMMON_SUPPORT_GATE_NOT_CONFIRMATORY",
        "pre_eval_evidence_identity": pre_identity,
        "common_support_summary_identity": summary_identity,
        "strict_gates": gates,
        "failure_reasons": [] if passed else [summary_failure],
        "evaluation_arm_config_sha256_by_arm": expected_hashes,
        "evaluator_identity": current_pre_record["frozen_tools"]["evaluator"],
        "trajectory_eval_core_identity": current_pre_record["frozen_tools"]["trajectory_eval_core"],
        "reference_identity": current_pre_record["reference"]["identity"],
        "arm_trajectory_identities": {
            label: current_pre_record["arms"][label]["trajectory"]
            for label in ARM_LABELS
        },
        "ranking_eligible": passed,
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=("check-start", "check-static", "check-b1-decision", "seal-arm-rc", "seal", "check", "seal-evaluation", "check-evaluation"),
        required=True,
    )
    value.add_argument("--arm", choices=("B1_CONSTQ", "XFEATBIRTH_RAWLK"))
    value.add_argument("--return-code", type=int)
    value.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    value.add_argument("--shared-root", type=Path, default=DEFAULT_SHARED_ROOT)
    value.add_argument("--window-bag", type=Path, default=DEFAULT_WINDOW_BAG)
    value.add_argument("--window-manifest", type=Path, default=DEFAULT_WINDOW_MANIFEST)
    value.add_argument("--b1-native-bag", type=Path, default=DEFAULT_B1_NATIVE_BAG)
    value.add_argument("--b1-native-camera", type=Path, default=DEFAULT_B1_NATIVE_CAMERA)
    value.add_argument("--b1-guard-decision-dir", type=Path, default=DEFAULT_B1_GUARD_DECISION_DIR)
    value.add_argument("--b1-backend-contract", type=Path, default=DEFAULT_B1_BACKEND_CONTRACT)
    value.add_argument("--b1-eligibility-manifest", type=Path, default=DEFAULT_B1_ELIGIBILITY_MANIFEST)
    value.add_argument("--b1-constq-bag", type=Path, default=DEFAULT_B1_CONSTQ_BAG)
    value.add_argument("--b1-quality-audit", type=Path, default=DEFAULT_B1_QUALITY_AUDIT)
    value.add_argument("--xfeat-bag", type=Path, default=DEFAULT_XFEAT_BAG)
    value.add_argument("--xfeat-manifest", type=Path, default=DEFAULT_XFEAT_MANIFEST)
    value.add_argument("--xfeat-audit", type=Path, default=DEFAULT_XFEAT_AUDIT)
    value.add_argument("--b1", type=Path, default=DEFAULT_B1)
    value.add_argument("--xfeat", type=Path, default=DEFAULT_XFEAT)
    value.add_argument("--b1-log", type=Path, default=DEFAULT_B1_LOG)
    value.add_argument("--xfeat-log", type=Path, default=DEFAULT_XFEAT_LOG)
    value.add_argument("--hfnet", type=Path, default=DEFAULT_HFNET)
    value.add_argument("--bridge-manifest", type=Path, default=DEFAULT_BRIDGE_MANIFEST)
    value.add_argument("--v4-run-result", type=Path, default=DEFAULT_V4_RESULT)
    value.add_argument("--eval-config", type=Path, default=DEFAULT_EVAL_CONFIG)
    value.add_argument("--evaluator", type=Path, default=DEFAULT_EVALUATOR)
    value.add_argument("--core", type=Path, default=DEFAULT_CORE)
    value.add_argument("--evidence", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    value.add_argument("--post-eval-evidence", type=Path, default=DEFAULT_POST_EVAL_OUTPUT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "check-start":
            record = validate_start_freeze(args.freeze)
            print(json.dumps(record, sort_keys=True))
            return 0
        if args.action == "check-static":
            record = validate_static_freeze(args.freeze)
            print(json.dumps(record, sort_keys=True))
            return 0
        if args.action == "check-b1-decision":
            record = validate_b1_decision_after_wrapper(args)
            print(json.dumps(record, sort_keys=True))
            return 0
        if args.action == "seal-arm-rc":
            if args.arm is None or args.return_code is None:
                raise VerificationError("SEAL_ARM_RC_REQUIRES_ARM_AND_RETURN_CODE")
            contract = vins_process_receipt_contract(args.arm)
            receipt_path = Path(contract["run_dir"]) / "process_rc_receipt.json"
            if receipt_path.exists() or receipt_path.is_symlink():
                raise VerificationError("VINS_PROCESS_RECEIPT_ALREADY_EXISTS")
            payload = canonical_json(build_vins_process_receipt(args.arm, args.return_code))
            write_exclusive(receipt_path, payload)
            print(json.dumps({"status": "SEALED_ARM_PROCESS_RC", "evidence": str(receipt_path), "evidence_sha256": sha256_bytes(payload)}, sort_keys=True))
            return 0
        post_evaluation = args.action in {"seal-evaluation", "check-evaluation"}
        record = build_post_eval_record(args) if post_evaluation else build_record(args)
        payload = canonical_json(record)
        evidence = args.post_eval_evidence if post_evaluation else args.evidence
        sealing = args.action in {"seal", "seal-evaluation"}
        if sealing:
            if evidence.exists() or evidence.is_symlink():
                raise VerificationError("EVIDENCE_ALREADY_EXISTS")
            write_exclusive(evidence, payload)
            status = "SEALED"
        else:
            existing, _ = read_regular(evidence, "SEALED_EVIDENCE")
            if existing != payload:
                raise VerificationError("SEALED_EVIDENCE_OR_CURRENT_INPUTS_MISMATCH")
            status = "CHECK_PASS"
        print(json.dumps({"status": status, "evidence": str(evidence), "evidence_sha256": sha256_bytes(payload)}, sort_keys=True))
        required_status = POST_EVAL_STATUS if post_evaluation else STATUS
        return 0 if record["status"] == required_status else 2
    except (VerificationError, OSError, ValueError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
