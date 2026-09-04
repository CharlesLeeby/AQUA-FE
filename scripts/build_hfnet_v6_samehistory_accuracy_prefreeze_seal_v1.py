#!/usr/bin/env python3
"""Build the outcome-blind HFNet-v6 accuracy prestart seal.

The ordinary explicit operation is read-only ``dry-run``.  ``publish`` requires an
explicit authorization token and writes one canonical JSON file with
temp-O_EXCL, file fsync, hard-link no-replace, and directory fsync.  It never
opens an HFNet result, log, or trajectory: all such paths must be absent.

This seal binds the prospective analysis grid, the already prepared ten-case
roster, the historical July-17 learned-plus-KLT/KLT inputs, proxy references,
and the complete evo runtime identity before any HFNet process starts.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Dict, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
RUNNER_SERIAL_LOCK = RUNTIME_ROOT / ".gpu_serial.lock"
PUBLICATION_PATH = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
)
FUTURE_ACCURACY_ROOT = RUNTIME_ROOT / "_accuracy_analysis_v1"
FUTURE_EXECUTION_LOCK_ROOT = RUNTIME_ROOT / "_accuracy_execution_locks_v1"
PUBLISH_AUTHORIZATION_TOKEN = "PUBLISH_OUTCOME_BLIND_ACCURACY_PREFREEZE_SEAL_V1"

SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-samehistory-positive-accuracy-prefreeze-seal-v1"
)
STATUS = "SEALED_OUTCOME_BLIND_BEFORE_ANY_HFNET_START"

PREFREEZE = ROOT / "papers/hfnet_v6_samehistory_positive_accuracy_analysis_grid_prefreeze_v1.md"
PARENT_PROTOCOL = ROOT / "papers/hfnet_v6_samehistory_old_positive_roster_protocol_v1.md"
SUPERSESSION_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_prestart_parser_supersession_v2.md"
)
HISTORICAL_REPORT = (
    ROOT
    / "papers/frozen_frontend_eval_20260714/"
    "positive_regression_report_20260717.md"
)
A08_REPEAT_MANIFEST = (
    ROOT
    / "papers/frozen_frontend_eval_20260714/"
    "a08_4500_4660_repeat_results_20260717.csv"
)
ROSTER_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
ROSTER_LOCK = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
    "a1df6b5e08cc9230/roster_lock.json"
)
ROSTER_BUILD_RECEIPT = ROSTER_LOCK.parent / "build_receipt.json"
RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"

EXPECTED_POINTER_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-roster-publication-pointer-v1"
)
EXPECTED_ROSTER_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-roster-lock-v2"
EXPECTED_CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v2"
EXPECTED_PREPARED_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-prepared-v2"

EXPECTED_AUTHORITIES: Mapping[str, Tuple[Path, int, str]] = {
    "analysis_grid_prefreeze": (
        PREFREEZE,
        16833,
        "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d",
    ),
    "parent_protocol": (
        PARENT_PROTOCOL,
        6196,
        "a5f9db42e9b35e470fe1fa680e1d2682dd59e52a064fe805da95de829e4ef541",
    ),
    "prestart_parser_supersession_protocol": (
        SUPERSESSION_PROTOCOL,
        4653,
        "cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7",
    ),
    "historical_positive_report": (
        HISTORICAL_REPORT,
        4433,
        "4ddb11404c64f44537b9d142f97a4d13d744b0db3f18e1f8b857787503024ade",
    ),
    "whole_roster_pointer": (
        ROSTER_POINTER,
        5296,
        "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
    ),
    "roster_lock": (
        ROSTER_LOCK,
        3132,
        "a1df6b5e08cc923087e563caddf017eac344d111ddc3b2db801949a620245289",
    ),
    "roster_build_receipt": (
        ROSTER_BUILD_RECEIPT,
        5379,
        "946f272063bfc55dc11296fcdbc09197419bd506818959bced8a836140fe8017",
    ),
    "prepared_runner": (
        RUNNER,
        7639,
        "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
    ),
}

ANALYSIS_EVALUATOR = (
    ROOT
    / "scripts/evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1.py"
)
FORMAL_ACCURACY_CONTROLLER = (
    ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v1.py"
)

# These identities are deliberately fail-closed until both implementations
# have completed review.  Publication is impossible while either size/hash is
# ``None``.  The canonical paths are already fixed so a later identity update
# cannot silently substitute a different implementation.
EXPECTED_ANALYSIS_CODE_IDENTITIES: Mapping[
    str, Tuple[Path, int | None, str | None]
] = {
    "roster_evaluator_core": (
        ANALYSIS_EVALUATOR,
        109889,
        "91b0245a4f8cd76b95f3fa2a18bcf67fe1ce9bfe7324d996ca23fb37baedeca5",
    ),
    "formal_accuracy_controller": (
        FORMAL_ACCURACY_CONTROLLER,
        120822,
        "4208597556c62b1023ce564d2ac8065558622193863b942d8a88f6f40b0ff887",
    ),
}

CASE_ORDER: Tuple[str, ...] = (
    "a05_3300_3700",
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
)

EXPECTED_PREPARED_MANIFESTS: Mapping[str, Tuple[int, str]] = {
    "a05_3300_3700": (
        12457,
        "aa24be0a28216dcc0ddbf42d445171ba4a266c66950150179db5f400ffcf8e26",
    ),
    "a07_10800_11200": (
        12493,
        "37b83a33fe7de41840aaa755d5dc8b620f9ccac25d2b7fe440ab218fd03f0433",
    ),
    "a08_4500_4660": (
        12457,
        "4a51677efb9847d8d7da1c38618bd17a46456b342d5ee755efb00961d483ab7e",
    ),
    "a09_6000_6200": (
        12457,
        "acbe74bd8860d60fd2f9544741f0550f07309587979e9e455828a4c6aa279628",
    ),
    "fjord1_s83_d10": (
        12550,
        "2f1735cf84e17d47736ec19a4f1b1306c705ea8c9e8ffb6d3857ee49ea9aebf1",
    ),
    "mclab1_s60_d15": (
        12552,
        "5685ceb62aee423adffdbd841ed9680222c39c4d77987030eeb6ffa416e2ff72",
    ),
    "cirs_s575_d30": (
        12373,
        "e6c4ee20c36dc7cb7cf635db69bc841dcce8904b9ff92317e0c7551f1bd4b1e9",
    ),
    "cirs_s900_d30": (
        12373,
        "3ad88677a431928e9c81e9d78bd3a0e63f7564a5bf9aed715ebe2a8f5b50feca",
    ),
    "a02_7600_8000": (
        12457,
        "e6c936e716668c3b0fefff70286fcd221d1cfe56740ad044bebc73557c6337fb",
    ),
    "mclab2_s110_d10": (
        12568,
        "7ac863487757ad92e61d3da299d71730cd15d0befc0706af154cb2f787de742b",
    ),
}

CONDITIONAL_CASES = frozenset(
    {
        "a05_3300_3700",
        "a07_10800_11200",
        "mclab1_s60_d15",
        "cirs_s575_d30",
        "cirs_s900_d30",
        "a02_7600_8000",
    }
)

STRUCTURAL_NA_REASONS: Mapping[str, Tuple[str, ...]] = {
    "a08_4500_4660": ("COMMON_SPAN_LT_10S",),
    "a09_6000_6200": ("COMMON_SPAN_LT_10S",),
    "fjord1_s83_d10": ("COMMON_SPAN_LT_10S",),
    "mclab2_s110_d10": (
        "COMMON_SPAN_LT_10S",
        "COMMON_COVERAGE_LT_0_70",
    ),
}

# Dataset, frozen grid count, reference gap, estimate gap, native anchors.
CASE_POLICY: Mapping[str, Tuple[str, int, int, int, int]] = {
    "a05_3300_3700": ("AQUALOC_ARCHAEOLOGY", 200, 2_500_000_000, 250_000_000, 21),
    "a07_10800_11200": ("AQUALOC_ARCHAEOLOGY", 200, 2_500_000_000, 250_000_000, 21),
    "a08_4500_4660": ("AQUALOC_ARCHAEOLOGY", 80, 2_500_000_000, 250_000_000, 0),
    "a09_6000_6200": ("AQUALOC_ARCHAEOLOGY", 100, 2_500_000_000, 250_000_000, 0),
    "fjord1_s83_d10": ("NTNU", 100, 50_000_000, 250_000_000, 0),
    "mclab1_s60_d15": ("NTNU", 150, 50_000_000, 250_000_000, 0),
    "cirs_s575_d30": ("CIRS", 299, 250_000_000, 500_000_000, 0),
    "cirs_s900_d30": ("CIRS", 299, 250_000_000, 500_000_000, 0),
    "a02_7600_8000": ("AQUALOC_ARCHAEOLOGY", 200, 2_500_000_000, 250_000_000, 21),
    "mclab2_s110_d10": ("NTNU", 100, 50_000_000, 250_000_000, 0),
}


def _vio(run_directory: str) -> Path:
    return Path(run_directory) / "vins_output/vio.csv"


HISTORICAL_TRAJECTORIES: Mapping[str, Mapping[str, Path]] = {
    "a05_3300_3700": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_a05_3300_3700_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_jul17positive_replay_a05_3300_3700_klt"
        ),
    },
    "a07_10800_11200": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_a07_10800_11200_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_jul17positive_replay_a07_10800_11200_klt"
        ),
    },
    "a09_6000_6200": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_a09_6000_6200_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_jul17positive_replay_a09_6000_6200_klt"
        ),
    },
    "fjord1_s83_d10": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_fjord1_s83_d10_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_klt_every2_jul17positive_replay_fjord1_s83_d10_klt"
        ),
    },
    "mclab1_s60_d15": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_mclab1_s60_d15_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_klt_every2_jul17positive_replay_mclab1_s60_d15_klt"
        ),
    },
    "cirs_s575_d30": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_hybrid_xfeat_every1_jul17positive_replay_cirs_s575_d30_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_klt_every1_jul17positive_replay_cirs_s575_d30_klt"
        ),
    },
    "cirs_s900_d30": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_hybrid_xfeat_every1_jul17positive_replay_cirs_s900_d30_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_klt_every1_jul17positive_replay_cirs_s900_d30_klt"
        ),
    },
    "a02_7600_8000": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_a02_7600_8000_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_jul17positive_replay_a02_7600_8000_klt"
        ),
    },
    "mclab2_s110_d10": {
        "learned_plus_klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_mclab2_s110_d10_full"
        ),
        "klt": _vio(
            "/home/ma/AQUA-FE_WS/logs/ntnu_vins/"
            "external_klt_every2_jul17positive_replay_mclab2_s110_d10_klt"
        ),
    },
}


def _a08_candidates(prefix: str) -> Tuple[Path, ...]:
    if prefix == "learned_plus_klt":
        base = (
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul17positive_replay_a08_4500_4660"
        )
        suffix = "full"
    elif prefix == "klt":
        base = (
            "/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_jul17positive_replay_a08_4500_4660"
        )
        suffix = "klt"
    else:  # pragma: no cover - internal table construction only.
        raise ValueError(prefix)
    return tuple(
        _vio(f"{base}{'' if repeat == 1 else '_r' + str(repeat)}_{suffix}")
        for repeat in range(1, 6)
    )


A08_CANDIDATES = {
    "learned_plus_klt": _a08_candidates("learned_plus_klt"),
    "klt": _a08_candidates("klt"),
}

REFERENCE_INPUTS: Mapping[str, Mapping[str, Any]] = {
    "a05_3300_3700": {
        "path": ROOT / "datasets/aqualoc/rosbags/archaeo05_3300_3700.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/aqualoc/colmap_gt",
        "role": "NON_INDEPENDENT_COLMAP_PROXY_REFERENCE",
    },
    "a07_10800_11200": {
        "path": ROOT / "datasets/aqualoc/rosbags/archaeo07_10800_11200.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/aqualoc/colmap_gt",
        "role": "NON_INDEPENDENT_COLMAP_PROXY_REFERENCE",
    },
    "a08_4500_4660": {
        "path": ROOT / "datasets/aqualoc/rosbags/archaeo08_4500_4660.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/aqualoc/colmap_gt",
        "role": "NON_INDEPENDENT_COLMAP_PROXY_REFERENCE",
    },
    "a09_6000_6200": {
        "path": ROOT / "datasets/aqualoc/rosbags/archaeo09_6000_6200.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/aqualoc/colmap_gt",
        "role": "NON_INDEPENDENT_COLMAP_PROXY_REFERENCE",
    },
    "fjord1_s83_d10": {
        "path": Path(
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/ntnu_hf/"
            "subset-fjord/fjord_1/fjord_1_baseline.tum"
        ),
        "format": "TUM",
        "topic": None,
        "role": "NON_INDEPENDENT_REAQROVIO_PROXY_REFERENCE",
    },
    "mclab1_s60_d15": {
        "path": Path(
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/ntnu_hf/"
            "subset-mclab/mclab_1/mclab_1_baseline.tum"
        ),
        "format": "TUM",
        "topic": None,
        "role": "NON_INDEPENDENT_REAQROVIO_PROXY_REFERENCE",
    },
    "cirs_s575_d30": {
        "path": ROOT
        / "logs/cirs_caves_vins/"
        "external_hybrid_xfeat_every1_jul14frozen3way_cirs_s575_d30_full/"
        "raw_segment.bag",
        "equivalent_july17_path": ROOT
        / "logs/cirs_caves_vins/"
        "external_hybrid_xfeat_every1_jul17positive_replay_cirs_s575_d30_full/"
        "raw_segment.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/cirs/odometry_gt",
        "role": "NON_INDEPENDENT_DATASET_ODOMETRY_PROXY_REFERENCE",
    },
    "cirs_s900_d30": {
        "path": ROOT
        / "logs/cirs_caves_vins/"
        "external_hybrid_xfeat_every1_jul14frozen3way_cirs_s900_d30_full/"
        "raw_segment.bag",
        "equivalent_july17_path": ROOT
        / "logs/cirs_caves_vins/"
        "external_hybrid_xfeat_every1_jul17positive_replay_cirs_s900_d30_full/"
        "raw_segment.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/cirs/odometry_gt",
        "role": "NON_INDEPENDENT_DATASET_ODOMETRY_PROXY_REFERENCE",
    },
    "a02_7600_8000": {
        "path": ROOT / "datasets/aqualoc/rosbags/archaeo02_7600_8000.bag",
        "format": "ROSBAG_ODOMETRY",
        "topic": "/aqualoc/colmap_gt",
        "role": "NON_INDEPENDENT_COLMAP_PROXY_REFERENCE",
    },
    "mclab2_s110_d10": {
        "path": Path(
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/ntnu_hf/"
            "subset-mclab/mclab_2/mclab_2_baseline.tum"
        ),
        "format": "TUM",
        "topic": None,
        "role": "NON_INDEPENDENT_REAQROVIO_PROXY_REFERENCE",
    },
}

EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")
PYTHON38 = Path("/usr/bin/python3.8")
SITE_PACKAGES = Path("/home/ma/.local/lib/python3.8/site-packages")
EVO_PACKAGE = SITE_PACKAGES / "evo"
EVO_DIST_INFO = SITE_PACKAGES / "evo-1.31.1.dist-info"
EVO_RECORD = EVO_DIST_INFO / "RECORD"
NUMPY_RECORD = SITE_PACKAGES / "numpy-1.24.4.dist-info/RECORD"
SCIPY_RECORD = SITE_PACKAGES / "scipy-1.10.1.dist-info/RECORD"

EXPECTED_RUNTIME_IDENTITIES: Mapping[str, Tuple[Path, int | None, str]] = {
    "evo_ape": (
        EVO_APE,
        213,
        "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15",
    ),
    "evo_rpe": (
        EVO_RPE,
        213,
        "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1",
    ),
    "python3_8": (
        PYTHON38,
        5_490_456,
        "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
    ),
    "evo_record": (
        EVO_RECORD,
        None,
        "a720ae5d78b1cf5d0c5b3ed81b8deb2adc41cb686ccffd773a42a1553823cbde",
    ),
    "numpy_record": (
        NUMPY_RECORD,
        None,
        "6c7ce7bb7cd520b75be0d504637fe57020dd50aef3503d9941b2cbc20473676a",
    ),
    "scipy_record": (
        SCIPY_RECORD,
        None,
        "ff024ed0ab4a9407c96c290ad8db1453153fa4cdddcdb99e6a637a2c6916d004",
    ),
}

EVO_TREE_FILE_COUNT = 45
EVO_TREE_TOTAL_BYTES = 473_395
EVO_TREE_SHA256 = "adab14dc969a68572af4c4e1966010df89b3f7dfb50f7dad441221075f410a4d"
EVO_TREE_ALGORITHM = (
    "sha256_of_sorted_site_relative_path_NUL_decimal_size_NUL_"
    "lowercase_file_sha256_LF"
)

GRID_STEP_NS = 100_000_000
RPE_DELTA_NS = 1_000_000_000
HFNET_BRIDGE_MAX_DELTA_NS = 256

AQUALOC_CALIBRATION = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_calibration_files/"
    "archaeo_imu_camera_calib.yaml"
)
AQUALOC_IMU_T_CAMERA = (
    (-0.999372214240385, -0.034374888513960, -0.008575805730306, -0.019289625059918),
    (0.009015607185122, -0.012659747009765, -0.999879217522163, -0.175142540090067),
    (0.034262169098800, -0.999328823683828, 0.012961709892746, -0.026795196070038),
    (0.0, 0.0, 0.0, 1.0),
)
CIRS_VEHICLE_T_IMU = (
    (2.220446049250313e-16, -1.0, -1.224646799147353e-16, 0.1),
    (-1.0, -2.220446049250313e-16, -2.465190328815662e-32, 0.0),
    (0.0, 1.224646799147353e-16, -1.0, -0.16),
    (0.0, 0.0, 0.0, 1.0),
)
CIRS_IMU_T_VEHICLE = (
    (2.220446049250313e-16, -1.0, 0.0, -2.220446049250313e-17),
    (-1.0, -2.220446049250313e-16, 1.224646799147353e-16, 0.10000000000000002),
    (-1.224646799147353e-16, -2.465190328815662e-32, -1.0, -0.16),
    (0.0, 0.0, 0.0, 1.0),
)
CIRS_FRAME_EVIDENCE_SHA256 = {
    "materializer": "c11432ffe2b08620f0368e5d2c37f2c4d2105d39f246abbeddba2be4a0fd784a",
    "independent_auditor": "0bb42548755506a55e4d2555a8af13a726876173e7fa16ce2c381e4efca9979a",
    "hfnet_config": "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204",
    "raw_full_dataset_bag": "6fb0309f56329c79f7b4a04be4993451975c8419d94302b980bf179f84251d3d",
    "camera_tf_bag_forbidden_as_body": "04db46c710232fcab1b461cc69ba86df9ff4236abd508f3578bbb554920df8fe",
}


class BuildError(RuntimeError):
    """The prestart evidence is not exactly the prospective frozen state."""


class PublicationIndeterminate(BuildError):
    """The canonical link exists but publication durability is uncertain."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _regular_file_metadata(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(str(path))
    except FileNotFoundError as error:
        raise BuildError(f"REQUIRED_FILE_MISSING:{path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BuildError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return metadata


def file_identity(path: Path) -> Dict[str, Any]:
    """Hash one final-component non-symlink regular file with race checks."""

    path = Path(path)
    before = _regular_file_metadata(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise BuildError(f"FILE_OPEN_FAILED:{path}:{error}") from error
    digest = hashlib.sha256()
    try:
        opened_before = os.fstat(descriptor)
        if not stat.S_ISREG(opened_before.st_mode):
            raise BuildError(f"OPENED_FILE_NOT_REGULAR:{path}")
        while True:
            block = os.read(descriptor, 4 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = _regular_file_metadata(path)
    signatures = {
        (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
        )
        for value in (before, opened_before, opened_after, after)
    }
    if len(signatures) != 1:
        raise BuildError(f"FILE_CHANGED_DURING_HASH:{path}")
    return {
        "path": str(path.resolve(strict=True)),
        "size_bytes": opened_after.st_size,
        "sha256": digest.hexdigest(),
    }


def strict_identity(path: Path, size: int | None, sha256: str, label: str) -> Dict[str, Any]:
    observed = file_identity(path)
    if size is not None and observed["size_bytes"] != size:
        raise BuildError(f"IDENTITY_SIZE_MISMATCH:{label}")
    if observed["sha256"] != sha256:
        raise BuildError(f"IDENTITY_SHA256_MISMATCH:{label}")
    return observed


def analysis_code_identities() -> Dict[str, Dict[str, Any]]:
    """Bind both future numeric entry points, or fail before any seal exists."""

    expected_paths = {
        "roster_evaluator_core": ANALYSIS_EVALUATOR,
        "formal_accuracy_controller": FORMAL_ACCURACY_CONTROLLER,
    }
    if set(EXPECTED_ANALYSIS_CODE_IDENTITIES) != set(expected_paths):
        raise BuildError("ANALYSIS_CODE_IDENTITY_LABEL_SET_MISMATCH")
    identities: Dict[str, Dict[str, Any]] = {}
    for label, expected_path in expected_paths.items():
        path, size, digest = EXPECTED_ANALYSIS_CODE_IDENTITIES[label]
        if path != expected_path:
            raise BuildError(f"ANALYSIS_CODE_NONCANONICAL_PATH:{label}")
        if (
            size is None
            or size <= 0
            or digest is None
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BuildError(f"ANALYSIS_CODE_IDENTITY_NOT_FROZEN:{label}")
        identities[label] = strict_identity(path, size, digest, label)
    return identities


def read_json_with_identity(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    identity = file_identity(path)
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise BuildError(f"JSON_READ_FAILED:{path}:{error}") from error
    if len(payload) != identity["size_bytes"] or sha256_bytes(payload) != identity["sha256"]:
        raise BuildError(f"JSON_CHANGED_AFTER_IDENTITY:{path}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BuildError(f"JSON_INVALID:{path}:{error}") from error
    if not isinstance(value, dict):
        raise BuildError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value, identity


def _absent(path: Path) -> bool:
    try:
        os.lstat(str(path))
    except FileNotFoundError:
        return True
    return False


def require_absent(path: Path, label: str) -> str:
    if not path.is_absolute():
        raise BuildError(f"ABSENCE_PATH_NOT_ABSOLUTE:{label}:{path}")
    if not _absent(path):
        raise BuildError(f"OUTCOME_OR_DESTINATION_ALREADY_EXISTS:{label}:{path}")
    return str(path)


def require_plain_directory(path: Path, label: str, *, empty: bool = False) -> str:
    try:
        metadata = os.lstat(str(path))
    except FileNotFoundError as error:
        raise BuildError(f"REQUIRED_DIRECTORY_MISSING:{label}:{path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise BuildError(f"NOT_PLAIN_DIRECTORY:{label}:{path}")
    if empty:
        try:
            with os.scandir(str(path)) as entries:
                if next(entries, None) is not None:
                    raise BuildError(f"DIRECTORY_NOT_EMPTY:{label}:{path}")
        except OSError as error:
            raise BuildError(f"DIRECTORY_SCAN_FAILED:{label}:{path}:{error}") from error
    return str(path)


def _parse_score_headers(path: Path) -> Tuple[Sequence[int], Dict[str, Any]]:
    identity = file_identity(path)
    payload = path.read_bytes()
    if len(payload) != identity["size_bytes"] or sha256_bytes(payload) != identity["sha256"]:
        raise BuildError(f"SCORE_HEADERS_CHANGED_AFTER_IDENTITY:{path}")
    try:
        lines = payload.decode("ascii").splitlines()
        stamps = [int(line) for line in lines if line.strip()]
    except (UnicodeError, ValueError) as error:
        raise BuildError(f"SCORE_HEADERS_INVALID:{path}") from error
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise BuildError(f"SCORE_HEADERS_NOT_STRICTLY_INCREASING:{path}")
    canonical = "".join(f"{stamp}\n" for stamp in stamps).encode("ascii")
    if canonical != payload:
        raise BuildError(f"SCORE_HEADERS_NOT_CANONICAL_ASCII_LF:{path}")
    return stamps, identity


def grid_contract(stamps: Sequence[int], expected_count: int) -> Dict[str, Any]:
    start, last = stamps[0], stamps[-1]
    grid = list(range(start, last + 1, GRID_STEP_NS))
    if len(grid) != expected_count:
        raise BuildError(
            f"GRID_COUNT_MISMATCH:{len(grid)}:{expected_count}:{start}:{last}"
        )
    payload = "".join(f"{stamp}\n" for stamp in grid).encode("ascii")
    return {
        "anchor_first_score_camera_header_ns": start,
        "last_score_camera_header_ns": last,
        "step_ns": GRID_STEP_NS,
        "rate_hz": 10,
        "count": len(grid),
        "ordered_integer_ns_lf_sha256": sha256_bytes(payload),
        "construction": "g_k=first_score_camera_header_ns+k*100000000_ns;g_k<=last",
    }


def matrix_binding(matrix: Sequence[Sequence[float]]) -> Dict[str, Any]:
    rows = [list(row) for row in matrix]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise BuildError("STATIC_MATRIX_NOT_4X4")
    if any(not isinstance(value, (int, float)) for row in rows for value in row):
        raise BuildError("STATIC_MATRIX_NONNUMERIC")
    return {
        "matrix": rows,
        "matrix_sha256": sha256_bytes(canonical_json(rows)),
    }


def _matmul4(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> Sequence[Sequence[float]]:
    return [
        [
            sum(float(left[row][inner]) * float(right[inner][column]) for inner in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


def _max_identity_error(matrix: Sequence[Sequence[float]]) -> float:
    return max(
        abs(float(matrix[row][column]) - (1.0 if row == column else 0.0))
        for row in range(4)
        for column in range(4)
    )


def frame_contract() -> Dict[str, Any]:
    vehicle_imu_error = _max_identity_error(
        _matmul4(CIRS_VEHICLE_T_IMU, CIRS_IMU_T_VEHICLE)
    )
    imu_vehicle_error = _max_identity_error(
        _matmul4(CIRS_IMU_T_VEHICLE, CIRS_VEHICLE_T_IMU)
    )
    if max(vehicle_imu_error, imu_vehicle_error) > 1e-15:
        raise BuildError("CIRS_FROZEN_TRANSFORMS_NOT_TWO_SIDED_INVERSES")
    return {
        "serialized_pose_conventions": {
            "hfnet": "world_T_IMU_OR_BODY;quaternion_qx_qy_qz_qw",
            "historical_vins": "world_T_IMU_OR_BODY;quaternion_qw_qx_qy_qz",
            "quaternion_conversion": "LOSSLESS_PERMUTATION_ONLY",
        },
        "mandatory_operation_order": [
            "PARSE_NATIVE_world_T_source",
            "RESAMPLE_SOURCE_ON_INTEGER_NS_GRID_POSITION_LINEAR_ROTATION_SHORTEST_SLERP",
            "RIGHT_COMPOSE_FROZEN_source_T_target",
            "FIT_AND_APPLY_ARM_SPECIFIC_PROPER_FIXED_SCALE_LEFT_SE3",
            "CALCULATE_ERROR_ON_ALREADY_ACCEPTED_JOINT_POPULATION",
        ],
        "lever_arm_composition_before_translation_interpolation_forbidden": True,
        "AQUALOC_ARCHAEOLOGY": {
            "common_target_frame": "aqualoc_camera",
            "reference_pose": "world_T_camera",
            "estimate_pose_before_resampling": "world_T_IMU",
            "reference_static_transform": "IDENTITY",
            "estimate_static_transform": "IMU_T_camera",
            "estimate_uses_inverse_transform": False,
            "imu_T_camera": matrix_binding(AQUALOC_IMU_T_CAMERA),
            "matrix_elementwise_max_abs_tolerance": 1e-12,
            "calibration_authority": strict_identity(
                AQUALOC_CALIBRATION,
                938,
                "e3aad241432b6619395564224fc39cb64931f17ac9446129c47a1ddf6c7a3ebc",
                "aqualoc_imu_camera_calibration",
            ),
        },
        "NTNU": {
            "common_target_frame": "ntnu_imu_body",
            "reference_pose": "world_T_IMU_OR_BODY",
            "estimate_pose": "world_T_IMU_OR_BODY",
            "all_static_bridges": "IDENTITY",
            "old_world_T_cam0_or_body_T_cam0_contracts_superseded": True,
            "superseded_old_document_sha256": {
                "reference_audit_csv": "3f4ba3963542e8b8b735ca315b7b6883b9c3ec6d6fe310584fbddc9d56f53a20",
                "data_eligibility_manifest_csv": "510c276c33217706eef11ea53e58de4b37318828f8a6dc793dea9262f0a0a0f5",
                "evaluator_protocol_v1_md": "d3ae583ca799ef423054a5b9ece8b53e0000a8d3bbb1ea8c50121f7a60a40816",
            },
        },
        "CIRS": {
            "common_target_frame": "cirs_published_vehicle_body",
            "reference_pose": "world_T_vehicle",
            "estimate_pose_before_resampling": "world_T_MTi_IMU",
            "reference_static_transform": "IDENTITY",
            "estimate_static_transform": "IMU_T_vehicle",
            "vehicle_T_imu": matrix_binding(CIRS_VEHICLE_T_IMU),
            "imu_T_vehicle": matrix_binding(CIRS_IMU_T_VEHICLE),
            "two_sided_inverse_verified": True,
            "two_sided_inverse_max_abs_error": max(vehicle_imu_error, imu_vehicle_error),
            "matrix_elementwise_max_abs_tolerance": 1e-15,
            "calibration_representation": "FULL_PRECISION_ORIGINAL_TF_PRIMARY",
            "canonical_zero_snapping": "DISPLAY_ONLY_NOT_NUMERIC",
            "original_quaternion_sealed": True,
            "published_common_vehicle_body_verified": True,
            "historical_online_camera_extrinsic_ignored_for_body_bridge": True,
            "camera_transform_used_as_body_transform": False,
            "camera_transform_as_body_transform_forbidden": True,
            "evidence_sha256": dict(CIRS_FRAME_EVIDENCE_SHA256),
        },
        "future_execution_lock_must_identity_pin_and_test_exact_contract": True,
    }


def _future_hfnet_paths(case_id: str, attempt_root: Path) -> Dict[str, str]:
    permanent = RUNTIME_ROOT / "_case_claims"
    paths = {
        "preparation_incident": attempt_root / "preparation_incident.json",
        "attempt_process_start_claim": attempt_root / "process_start_claim.json",
        "permanent_start_once_reservation": permanent / f"{case_id}.start_once",
        "permanent_process_start_claim": permanent / f"{case_id}.process_start_claim.json",
        "terminal_runability_result": attempt_root / "run_result.json",
        "stdout_log": attempt_root / "headless.stdout.log",
        "stderr_log": attempt_root / "headless.stderr.log",
        "trajectory": attempt_root / "result/trajectory.txt",
        "keyframe_trajectory": attempt_root / "result/trajectory_keyframe.txt",
    }
    return {
        label: require_absent(path, f"{case_id}:{label}")
        for label, path in paths.items()
    }


def _future_accuracy_paths(case_id: str) -> Dict[str, Any]:
    case_root = FUTURE_ACCURACY_ROOT / case_id
    paths = {
        "execution_lock": FUTURE_EXECUTION_LOCK_ROOT / f"{case_id}.json",
        "hfnet_timestamp_bridge_receipt": (
            FUTURE_EXECUTION_LOCK_ROOT
            / f"{case_id}.hfnet_timestamp_bridge_receipt.json"
        ),
        "output_dir": case_root / "attempt_001",
        "process_claim": FUTURE_ACCURACY_ROOT / "_claims" / f"{case_id}.start_once",
        "terminal_receipt": case_root / "terminal_receipt.json",
    }
    return {
        **{
            label: require_absent(path, f"{case_id}:accuracy:{label}")
            for label, path in paths.items()
        },
        "retry_permitted": False,
        "replacement_output_permitted": False,
        "maximum_claims": 1,
    }


def _historical_sources(case_id: str, accuracy_admitted: bool) -> Dict[str, Any]:
    reference_row = REFERENCE_INPUTS[case_id]
    canonical_reference = file_identity(Path(reference_row["path"]))
    reference: Dict[str, Any] = {
        "trajectory_or_container": canonical_reference,
        "format": reference_row["format"],
        "topic": reference_row["topic"],
        "role": reference_row["role"],
        "external_ground_truth": False,
        "authorized_as_future_metric_input": accuracy_admitted,
    }
    equivalent = reference_row.get("equivalent_july17_path")
    if equivalent is not None:
        equivalent_identity = file_identity(Path(equivalent))
        if (
            equivalent_identity["size_bytes"] != canonical_reference["size_bytes"]
            or equivalent_identity["sha256"] != canonical_reference["sha256"]
        ):
            raise BuildError(f"CIRS_REFERENCE_REPLAY_NOT_BYTE_IDENTICAL:{case_id}")
        reference["july17_replay_byte_equivalent"] = equivalent_identity
        reference["canonical_choice"] = "JUL14_RAW_SEGMENT_BYTE_IDENTICAL_TO_JUL17"

    if case_id == "a08_4500_4660":
        repeat_manifest = strict_identity(
            A08_REPEAT_MANIFEST,
            2394,
            "f6a807900e08955748695edc9a5c88a8b640dee240bc72b49d2e7029b223d2eb",
            "a08_repeat_manifest",
        )
        learned = {
            "role": "HISTORICAL_JUL17_LEARNED_PLUS_KLT_VINS_TRAJECTORY_SET",
            "trajectory_candidates": [
                {"repeat": index, "identity": file_identity(path)}
                for index, path in enumerate(A08_CANDIDATES["learned_plus_klt"], 1)
            ],
            "repeat_manifest": repeat_manifest,
            "single_trajectory_selection": "NOT_APPLICABLE_STRUCTURAL_NA",
            "authorized_as_future_metric_input": False,
        }
        klt = {
            "role": "HISTORICAL_JUL17_PURE_KLT_VINS_TRAJECTORY_SET",
            "trajectory_candidates": [
                {"repeat": index, "identity": file_identity(path)}
                for index, path in enumerate(A08_CANDIDATES["klt"], 1)
            ],
            "repeat_manifest": repeat_manifest,
            "single_trajectory_selection": "NOT_APPLICABLE_STRUCTURAL_NA",
            "authorized_as_future_metric_input": False,
        }
    else:
        selected = HISTORICAL_TRAJECTORIES[case_id]
        learned = {
            "trajectory": file_identity(selected["learned_plus_klt"]),
            "role": "HISTORICAL_JUL17_LEARNED_PLUS_KLT_VINS_TRAJECTORY",
            "single_trajectory_selection": (
                "FROZEN_ROSTER_INPUT"
                if accuracy_admitted
                else "UPPER_BOUND_AUDIT_ONLY_STRUCTURAL_NA"
            ),
            "authorized_as_future_metric_input": accuracy_admitted,
        }
        klt = {
            "trajectory": file_identity(selected["klt"]),
            "role": "HISTORICAL_JUL17_PURE_KLT_VINS_TRAJECTORY",
            "single_trajectory_selection": (
                "FROZEN_ROSTER_INPUT"
                if accuracy_admitted
                else "UPPER_BOUND_AUDIT_ONLY_STRUCTURAL_NA"
            ),
            "authorized_as_future_metric_input": accuracy_admitted,
        }
    return {
        "reference": reference,
        "learned_plus_klt": learned,
        "klt": klt,
        "contents_parsed_for_accuracy_or_ranking": False,
        "identity_hashing_only": True,
    }


def evo_tree_identity() -> Dict[str, Any]:
    files = []
    for root in (EVO_PACKAGE, EVO_DIST_INFO):
        if root.is_symlink() or not root.is_dir():
            raise BuildError(f"EVO_TREE_ROOT_INVALID:{root}")
        for path in root.rglob("*"):
            relative = path.relative_to(SITE_PACKAGES)
            if "__pycache__" in relative.parts:
                continue
            metadata = os.lstat(str(path))
            if stat.S_ISLNK(metadata.st_mode):
                raise BuildError(f"EVO_TREE_SYMLINK:{path}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise BuildError(f"EVO_TREE_SPECIAL_FILE:{path}")
            files.append(path)
    files.sort(key=lambda path: path.relative_to(SITE_PACKAGES).as_posix())
    digest = hashlib.sha256()
    total = 0
    for path in files:
        observed = file_identity(path)
        relative = path.relative_to(SITE_PACKAGES).as_posix()
        digest.update(
            (
                f"{relative}\0{observed['size_bytes']}\0"
                f"{observed['sha256']}\n"
            ).encode("ascii")
        )
        total += int(observed["size_bytes"])
    result = {
        "site_packages_root": str(SITE_PACKAGES),
        "included_roots": ["evo", "evo-1.31.1.dist-info"],
        "excluded_path_component": "__pycache__",
        "regular_nonsymlink_files_only": True,
        "file_count": len(files),
        "total_bytes": total,
        "tree_sha256": digest.hexdigest(),
        "digest_algorithm": EVO_TREE_ALGORITHM,
        "record_included": True,
    }
    expected = {
        "file_count": EVO_TREE_FILE_COUNT,
        "total_bytes": EVO_TREE_TOTAL_BYTES,
        "tree_sha256": EVO_TREE_SHA256,
    }
    if any(result[key] != value for key, value in expected.items()):
        raise BuildError(f"EVO_IMPLEMENTATION_TREE_DRIFT:{result}")
    return result


def evo_verification_contract() -> Dict[str, Any]:
    """Return the complete, outcome-independent evo cross-check protocol."""

    return {
        "input_pose_source": "RAW_RESAMPLED_COMMON_TARGET_FULL_POSES",
        "real_resampled_orientations_required": True,
        "identity_quaternion_substitution_forbidden": True,
        "timestamps": {
            "serialization": "RELATIVE_ZERO_SECONDS_FROM_AUTHORITATIVE_INTEGER_NS",
            "fitted_or_searched_offset_ns": 0,
            "association_tolerance_seconds": "1e-9",
        },
        "ape": {
            "population": "ONE_ALL_ACCEPTED_COMMON_POSE_TUM_PAIR",
            "argv_template": [
                str(EVO_APE),
                "tum",
                "{REFERENCE_ALL_COMMON_TUM}",
                "{ESTIMATE_ALL_COMMON_TUM}",
                "-a",
                "-r",
                "trans_part",
                "--t_max_diff",
                "1e-9",
                "--t_offset",
                "0",
            ],
            "scale_flag_forbidden": "-s",
            "alignment": "EVO_PROPER_GLOBAL_SE3_FIXED_SCALE_ONE",
        },
        "rpe": {
            "population": "EXACT_ONE_SECOND_PAIRS_WITHIN_EACH_CONTIGUOUS_ACCEPTED_SEGMENT",
            "run_granularity": "ONE_EVO_PROCESS_PER_CONTIGUOUS_ACCEPTED_SEGMENT",
            "argv_template": [
                str(EVO_RPE),
                "tum",
                "{REFERENCE_SEGMENT_TUM}",
                "{ESTIMATE_SEGMENT_TUM}",
                "-r",
                "trans_part",
                "-d",
                "10",
                "-u",
                "f",
                "--all_pairs",
                "--pairs_from_reference",
                "--t_max_diff",
                "1e-9",
                "--t_offset",
                "0",
            ],
            "alignment_flag_forbidden": "-a",
            "scale_flag_forbidden": "-s",
            "global_left_alignment_invariance_relied_upon": True,
            "combine_segments": (
                "SUM_SQUARED_TRANSLATION_ERRORS_DIVIDED_BY_SUM_EXACT_PAIR_COUNTS"
            ),
            "unweighted_mean_of_segment_rmse_forbidden": True,
        },
        "primary_evo_population_equivalence": {
            "common_pose_population": "COUNT_AND_ORDERED_INTEGER_NS_LIST_SHA256",
            "exact_one_second_pair_population": (
                "COUNT_AND_ORDERED_INTEGER_NS_PAIR_LIST_SHA256"
            ),
            "same_populations_required": True,
        },
        "evidence_to_identity_freeze": [
            "EXACT_ARGV",
            "RETURN_STATUS",
            "STDOUT",
            "STDERR",
            "GENERATED_TUM_FILES",
            "CONTIGUOUS_SEGMENT_MEMBERSHIP",
            "PARSED_PER_SEGMENT_PAIR_COUNTS",
        ],
        "caller_supplied_scalar_rmse_forbidden": True,
        "caller_supplied_population_dictionary_forbidden": True,
        "maximum_absolute_primary_evo_ape_or_rpe_rmse_disagreement_m": 1e-5,
        "larger_disagreement_closes_case_without_ranking": True,
        "primary_metric_status_before_crosscheck": "EVO_CROSSCHECK_PENDING",
        "accuracy_or_ranking_authorized_before_crosscheck": False,
    }


def _evo_environment() -> Dict[str, Any]:
    identities = {
        label: strict_identity(path, size, digest, label)
        for label, (path, size, digest) in EXPECTED_RUNTIME_IDENTITIES.items()
    }
    return {
        "evo_version": "v1.31.1",
        "evo_ape": identities["evo_ape"],
        "evo_rpe": identities["evo_rpe"],
        "python_executable": identities["python3_8"],
        "evo_distribution_record": identities["evo_record"],
        "evo_implementation_tree": evo_tree_identity(),
        "numpy": {
            "version": "1.24.4",
            "distribution_record": identities["numpy_record"],
        },
        "scipy": {
            "version": "1.10.1",
            "distribution_record": identities["scipy_record"],
        },
        "verification_contract": evo_verification_contract(),
    }


def future_controller_contract() -> Dict[str, Any]:
    """Freeze the authorization boundary for the later exactly-once runner."""

    return {
        "canonical_prestart_seal_path": str(PUBLICATION_PATH),
        "caller_selected_prestart_seal_path_permitted": False,
        "seal_supplied_self_identity_is_sufficient_authorization": False,
        "independent_full_seal_contract_validation_required": True,
        "sealed_code_identities_verified_for_running_processes": [
            "roster_evaluator_core",
            "formal_accuracy_controller",
        ],
        "matching_identity_pinned_execution_lock_required": True,
        "identity_field_shape_or_sequential_lstat_is_execution_authorization": False,
        "freeze_lock": {
            "stage": "AFTER_HFNET_TERMINAL_PASS_BEFORE_SUPPORT_OR_METRICS",
            "canonical_execution_lock_pattern": str(
                FUTURE_EXECUTION_LOCK_ROOT / "{case_id}.json"
            ),
            "canonical_bridge_receipt_pattern": str(
                FUTURE_EXECUTION_LOCK_ROOT
                / "{case_id}.hfnet_timestamp_bridge_receipt.json"
            ),
            "support_computation_permitted": False,
            "ape_or_rpe_computation_permitted": False,
            "identity_freeze_only": True,
            "write_once_no_clobber": True,
            "input_toctou_recheck_required": True,
            "identity_bindings_required": [
                "WHOLE_PRESTART_SEAL",
                "RUNNING_CONTROLLER",
                "RUNNING_EVALUATOR",
                "HFNET_TERMINAL_RUNABILITY_PASS_RECEIPT",
                "HFNET_TRAJECTORY",
                "SCORE_CAMERA_HEADERS",
                "LEARNED_PLUS_KLT_TRAJECTORY_OR_STRUCTURAL_NA_REPEAT_SET",
                "KLT_TRAJECTORY_OR_STRUCTURAL_NA_REPEAT_SET",
                "REFERENCE_TRAJECTORY_OR_CONTAINER_AND_TOPIC",
                "HFNET_TIMESTAMP_BRIDGE_RECEIPT",
                "FRAME_CONTRACT",
                "EVO_ENVIRONMENT",
                "CANONICAL_FUTURE_DESTINATIONS",
            ],
        },
        "pre_open_and_pre_publication_identity_reverification_required_for": [
            "WHOLE_PRESTART_SEAL",
            "EXECUTION_LOCK",
            "RUNNING_CONTROLLER_AND_EVALUATOR",
            "RUNABILITY_RECEIPT",
            "HFNET_TRAJECTORY",
            "HISTORICAL_TRAJECTORIES",
            "REFERENCE",
            "FRAME_CONTRACT",
            "HFNET_TIMESTAMP_BRIDGE",
            "EVO_ENVIRONMENT",
        ],
        "atomic_exactly_once_claim_required": True,
        "canonicalize_all_destination_paths_before_distinctness_check": True,
        "maximum_attempts_per_case": 1,
        "retry_permitted": False,
        "terminal_receipt_always_required": True,
        "fuse_publication": (
            "TEMP_O_EXCL_FILE_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC_NO_RENAME"
        ),
    }


def _load_roster_authorities() -> Tuple[Dict[str, Any], Dict[str, Any], Mapping[str, Any]]:
    pointer, pointer_identity = read_json_with_identity(ROSTER_POINTER)
    expected_pointer = strict_identity(
        ROSTER_POINTER,
        EXPECTED_AUTHORITIES["whole_roster_pointer"][1],
        EXPECTED_AUTHORITIES["whole_roster_pointer"][2],
        "whole_roster_pointer",
    )
    if pointer_identity != expected_pointer:
        raise BuildError("POINTER_IDENTITY_TOCTOU")
    roster, roster_identity = read_json_with_identity(ROSTER_LOCK)
    expected_roster = strict_identity(
        ROSTER_LOCK,
        EXPECTED_AUTHORITIES["roster_lock"][1],
        EXPECTED_AUTHORITIES["roster_lock"][2],
        "roster_lock",
    )
    if roster_identity != expected_roster:
        raise BuildError("ROSTER_IDENTITY_TOCTOU")
    if (
        pointer.get("schema_version") != EXPECTED_POINTER_SCHEMA
        or pointer.get("status") != "FROZEN_READY_FOR_EXECUTION"
    ):
        raise BuildError("POINTER_STATUS_INVALID")
    if (
        roster.get("schema_version") != EXPECTED_ROSTER_SCHEMA
        or roster.get("status") != "FROZEN_READY_FOR_EXECUTION"
    ):
        raise BuildError("ROSTER_STATUS_INVALID")
    pointer_claims = pointer.get("claims")
    if (
        not isinstance(pointer_claims, dict)
        or not pointer_claims
        or any(value is not False for value in pointer_claims.values())
    ):
        raise BuildError("POINTER_CLAIMS_NOT_ALL_FALSE")
    execution = roster.get("execution_contract")
    if (
        not isinstance(execution, dict)
        or execution.get("maximum_attempts_per_case") != 1
        or execution.get("retry_permitted") is not False
        or execution.get("accuracy_evaluated_by_runner") is not False
    ):
        raise BuildError("ROSTER_EXECUTION_CONTRACT_INVALID")
    pointer_cases = pointer.get("cases")
    roster_cases = roster.get("cases")
    if not isinstance(pointer_cases, list) or not isinstance(roster_cases, list):
        raise BuildError("ROSTER_CASES_NOT_LIST")
    if [row.get("case_id") for row in pointer_cases] != list(CASE_ORDER):
        raise BuildError("POINTER_CASE_ORDER_MISMATCH")
    if [row.get("case_id") for row in roster_cases] != list(CASE_ORDER):
        raise BuildError("ROSTER_CASE_ORDER_MISMATCH")
    if pointer.get("roster_lock") != roster_identity:
        raise BuildError("POINTER_ROSTER_IDENTITY_MISMATCH")
    expected_receipt = strict_identity(
        ROSTER_BUILD_RECEIPT,
        EXPECTED_AUTHORITIES["roster_build_receipt"][1],
        EXPECTED_AUTHORITIES["roster_build_receipt"][2],
        "roster_build_receipt",
    )
    if (
        pointer.get("bundle_root") != str(ROSTER_LOCK.parent)
        or pointer.get("build_receipt") != expected_receipt
    ):
        raise BuildError("POINTER_BUNDLE_OR_RECEIPT_IDENTITY_MISMATCH")
    return pointer, roster, {row["case_id"]: row for row in pointer_cases}


def _build_case(
    case_id: str,
    pointer_case: Mapping[str, Any],
    roster: Mapping[str, Any],
) -> Dict[str, Any]:
    spec_path = Path(pointer_case["spec"]["path"])
    spec, spec_identity = read_json_with_identity(spec_path)
    if spec_identity != pointer_case.get("spec"):
        raise BuildError(f"CASE_SPEC_IDENTITY_MISMATCH:{case_id}")
    if (
        spec.get("schema_version") != EXPECTED_CASE_SCHEMA
        or spec.get("case_id") != case_id
        or spec.get("retry_permitted") is not False
    ):
        raise BuildError(f"CASE_SPEC_CONTRACT_MISMATCH:{case_id}")
    attempt_root = Path(spec.get("attempt_root", ""))
    if not attempt_root.is_absolute() or attempt_root != RUNTIME_ROOT / case_id / "attempt_001":
        raise BuildError(f"CASE_ATTEMPT_ROOT_MISMATCH:{case_id}")
    require_plain_directory(attempt_root, f"{case_id}:prepared_attempt_root")
    require_plain_directory(
        attempt_root / "result", f"{case_id}:prepared_result_directory", empty=True
    )
    prepared_path = attempt_root / "prepared_manifest.json"
    prepared, prepared_identity = read_json_with_identity(prepared_path)
    prepared_size, prepared_sha256 = EXPECTED_PREPARED_MANIFESTS[case_id]
    if prepared_identity != {
        "path": str(prepared_path.resolve(strict=True)),
        "size_bytes": prepared_size,
        "sha256": prepared_sha256,
    }:
        raise BuildError(f"PREPARED_MANIFEST_IDENTITY_MISMATCH:{case_id}")
    if (
        prepared.get("schema_version") != EXPECTED_PREPARED_SCHEMA
        or prepared.get("status") != "PREPARED_NOT_STARTED"
        or prepared.get("case_id") != case_id
        or prepared.get("case_spec") != spec_identity
        or prepared.get("runner")
        != strict_identity(
            RUNNER,
            EXPECTED_AUTHORITIES["prepared_runner"][1],
            EXPECTED_AUTHORITIES["prepared_runner"][2],
            "prepared_runner",
        )
    ):
        raise BuildError(f"PREPARED_MANIFEST_CONTRACT_MISMATCH:{case_id}")
    boundary = prepared.get("scientific_boundary")
    if (
        not isinstance(boundary, dict)
        or boundary.get("accuracy_evaluated") is not False
        or boundary.get("retry_permitted") is not False
    ):
        raise BuildError(f"PREPARED_BOUNDARY_NOT_PRISTINE:{case_id}")
    dependencies = prepared.get("frozen_dependencies")
    if not isinstance(dependencies, dict):
        raise BuildError(f"PREPARED_DEPENDENCIES_MISSING:{case_id}")
    prepared_pointer = dependencies.get("publication_pointer")
    prepared_roster = dependencies.get("roster_lock")
    expected_pointer_core = {
        "path": str(ROSTER_POINTER.resolve(strict=True)),
        "size_bytes": EXPECTED_AUTHORITIES["whole_roster_pointer"][1],
        "sha256": EXPECTED_AUTHORITIES["whole_roster_pointer"][2],
    }
    expected_roster_core = {
        "path": str(ROSTER_LOCK.resolve(strict=True)),
        "size_bytes": EXPECTED_AUTHORITIES["roster_lock"][1],
        "sha256": EXPECTED_AUTHORITIES["roster_lock"][2],
    }
    if (
        not isinstance(prepared_pointer, dict)
        or any(prepared_pointer.get(key) != value for key, value in expected_pointer_core.items())
        or prepared_pointer.get("schema_version") != EXPECTED_POINTER_SCHEMA
        or prepared_pointer.get("status") != "FROZEN_READY_FOR_EXECUTION"
        or prepared_pointer.get("bundle_root") != str(ROSTER_LOCK.parent)
        or prepared_pointer.get("build_receipt")
        != {
            "path": str(ROSTER_BUILD_RECEIPT.resolve(strict=True)),
            "size_bytes": EXPECTED_AUTHORITIES["roster_build_receipt"][1],
            "sha256": EXPECTED_AUTHORITIES["roster_build_receipt"][2],
        }
        or prepared_pointer.get("selected_case_spec") != spec_identity
        or prepared_pointer.get("selected_case_core_spec_sha256")
        != pointer_case.get("core_spec_sha256")
        or not isinstance(prepared_roster, dict)
        or any(prepared_roster.get(key) != value for key, value in expected_roster_core.items())
        or prepared_roster.get("schema_version") != EXPECTED_ROSTER_SCHEMA
        or prepared_roster.get("status") != "FROZEN_READY_FOR_EXECUTION"
        or prepared_roster.get("case_core_spec_sha256")
        != pointer_case.get("core_spec_sha256")
    ):
        raise BuildError(f"PREPARED_V2_AUTHORITY_BINDING_MISMATCH:{case_id}")
    policy_dataset, grid_count, reference_gap, estimate_gap, native_anchors = CASE_POLICY[
        case_id
    ]
    times_path = Path(spec["input_root"]) / str(spec["times_relative_path"])
    stamps, times_identity = _parse_score_headers(times_path)
    if (
        len(stamps) != spec.get("camera_count")
        or [stamps[0], stamps[-1]] != spec.get("camera_header_ns_inclusive")
    ):
        raise BuildError(f"SCORE_HEADERS_SPEC_MISMATCH:{case_id}")
    score_payload = "".join(f"{stamp}\n" for stamp in stamps).encode("ascii")
    admitted = case_id in CONDITIONAL_CASES
    structural = list(STRUCTURAL_NA_REASONS.get(case_id, ()))
    roster_row = next(row for row in roster["cases"] if row["case_id"] == case_id)
    if roster_row.get("core_spec_sha256") != pointer_case.get("core_spec_sha256"):
        raise BuildError(f"ROSTER_CORE_SPEC_MISMATCH:{case_id}")
    return {
        "case_id": case_id,
        "dataset": policy_dataset,
        "accuracy_admission": (
            "CONDITIONAL_ON_FUTURE_HFNET_RUNABILITY_PASS_AND_FOURWAY_GATE"
            if admitted
            else "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND"
        ),
        "structural_na_reasons": structural,
        "case_spec": spec_identity,
        "case_core_spec_sha256": pointer_case["core_spec_sha256"],
        "prepared_manifest": prepared_identity,
        "score_camera_headers": {
            "identity": times_identity,
            "count": len(stamps),
            "first_last_ns_inclusive": [stamps[0], stamps[-1]],
            "ordered_integer_ns_ascii_lf_sha256": sha256_bytes(score_payload),
            "digest_serialization": "decimal_integer_ns_plus_LF_per_header",
        },
        "analysis_grid": {
            **grid_contract(stamps, grid_count),
            "reference_max_two_sided_gap_ns": reference_gap,
            "each_estimate_max_two_sided_gap_ns": estimate_gap,
        },
        "historical_sources": _historical_sources(case_id, admitted),
        "native_reference_sensitivity": {
            "required": native_anchors > 0,
            "expected_native_anchor_count": native_anchors or None,
            "descriptive_only": True if native_anchors else None,
            "run_only_after_primary_gate": True if native_anchors else None,
            "can_reopen_primary_gate": False,
        },
        "future_hfnet_outputs_observed_absent": _future_hfnet_paths(
            case_id, attempt_root
        ),
        "future_accuracy_publication": _future_accuracy_paths(case_id),
        "claims": {
            "hfnet_started": False,
            "hfnet_result_observed": False,
            "hfnet_log_observed": False,
            "hfnet_trajectory_observed": False,
            "accuracy_execution_lock_frozen": False,
            "hfnet_timestamp_bridge_receipt_frozen": False,
            "common_support_computed": False,
            "accuracy_analysis_started": False,
            "accuracy_measured": False,
            "ranking_authorized": False,
        },
    }


def analysis_contract() -> Dict[str, Any]:
    return {
        "source_order": ["reference", "hfnet", "learned_plus_klt", "klt"],
        "joint_mask": (
            "valid_reference AND valid_HFNet AND valid_learned_plus_KLT AND valid_KLT"
        ),
        "support_before_coordinate_loading_or_alignment": True,
        "timestamp_unit": "integer_nanoseconds",
        "all_fitted_or_searched_offsets_ns": 0,
        "nearest_association": False,
        "timestamp_snapping": False,
        "extrapolation": False,
        "interpolation": {
            "translation": "LINEAR_TWO_SIDED_BRACKET_ONLY",
            "rotation": "SHORTEST_ARC_SLERP_TWO_SIDED_BRACKET_ONLY",
            "sample_reuse_for_missing_bracket": False,
        },
        "hfnet_epoch_double_serialization_bridge": {
            "maximum_absolute_delta_ns": HFNET_BRIDGE_MAX_DELTA_NS,
            "mapping": "BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT",
            "strictly_monotonic": True,
            "source_header_reuse": False,
            "ambiguous_or_missing_mapping_closes_case": True,
            "post_bridge_tolerance_ns": 0,
        },
        "coverage_denominator": "COMPLETE_SCORE_GRID",
        "invalid_grid_point_breaks_segment": True,
        "rpe_definition": (
            "NORM_TRANSLATION_OF_(T_REF_I_INV_T_REF_J)_INV_"
            "(T_EST_I_INV_T_EST_J)_FROM_FULL_POSES"
        ),
        "aligned_global_position_delta_vector_rpe_forbidden": True,
        "rpe_delta_ns": RPE_DELTA_NS,
        "rpe_grid_steps": 10,
        "rpe_never_crosses_segment_break": True,
        "gates": {
            "hfnet_runability_receipt_status": "PASS",
            "minimum_common_grid_poses": 30,
            "minimum_common_span_ns": 10_000_000_000,
            "minimum_complete_score_grid_coverage": 0.70,
            "minimum_exact_one_second_rpe_pairs": 10,
            "all_gates_apply_to_same_joint_mask": True,
            "closed_gate_accuracy": "NA_WITHOUT_HIDDEN_NUMERIC_METRICS",
        },
        "alignment": {
            "independent_per_system": True,
            "proper_se3": True,
            "fixed_scale": 1.0,
            "det_rotation_positive_and_approximately_one": True,
            "sim3_primary_forbidden": True,
        },
        "frame_transform_execution_lock_required_before_metrics": True,
        "frame_contract": frame_contract(),
    }


def future_accuracy_namespace_contract() -> Dict[str, Any]:
    return {
        "root": str(FUTURE_ACCURACY_ROOT),
        "execution_lock_root": str(FUTURE_EXECUTION_LOCK_ROOT),
        "case_execution_lock_pattern": str(
            FUTURE_EXECUTION_LOCK_ROOT / "{case_id}.json"
        ),
        "case_hfnet_timestamp_bridge_receipt_pattern": str(
            FUTURE_EXECUTION_LOCK_ROOT
            / "{case_id}.hfnet_timestamp_bridge_receipt.json"
        ),
        "case_output_pattern": str(FUTURE_ACCURACY_ROOT / "{case_id}/attempt_001"),
        "case_claim_pattern": str(
            FUTURE_ACCURACY_ROOT / "_claims/{case_id}.start_once"
        ),
        "case_terminal_receipt_pattern": str(
            FUTURE_ACCURACY_ROOT / "{case_id}/terminal_receipt.json"
        ),
        "maximum_attempts_per_case": 1,
        "retry_permitted": False,
        "replacement_output_permitted": False,
        "freeze_lock_stage": "AFTER_HFNET_TERMINAL_PASS_BEFORE_SUPPORT_OR_METRICS",
        "freeze_lock_may_compute_support_or_ape_or_rpe": False,
        "fuse_publication": (
            "TEMP_O_EXCL_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC_NO_RENAME"
        ),
    }


def future_accuracy_execution_lock_namespace_contract() -> Dict[str, Any]:
    return {
        "root": str(FUTURE_EXECUTION_LOCK_ROOT),
        "case_lock_pattern": str(FUTURE_EXECUTION_LOCK_ROOT / "{case_id}.json"),
        "case_bridge_receipt_pattern": str(
            FUTURE_EXECUTION_LOCK_ROOT
            / "{case_id}.hfnet_timestamp_bridge_receipt.json"
        ),
        "publication_stage": "AFTER_HFNET_TERMINAL_PASS_BEFORE_SUPPORT_OR_METRICS",
        "support_or_metric_computation_permitted": False,
        "retry_permitted": False,
        "replacement_permitted": False,
    }


def publication_contract() -> Dict[str, Any]:
    return {
        "canonical_path": str(PUBLICATION_PATH),
        "write_once_no_clobber": True,
        "temporary_creation": "O_CREAT|O_EXCL",
        "temporary_file_fsync": True,
        "commit": "HARDLINK_NOREPLACE",
        "parent_directory_fsync": True,
        "rename_used": False,
        "runner_serial_lock_held_during_publish": str(RUNNER_SERIAL_LOCK),
    }


def execution_authority_adjudication() -> Dict[str, Any]:
    return {
        "active_execution_generation": "V2_PRESTART_PARSER_SUPERSESSION",
        "active_runtime_root": str(RUNTIME_ROOT),
        "active_pointer": str(ROSTER_POINTER),
        "active_runner": str(RUNNER),
        "supersession_protocol": str(SUPERSESSION_PROTOCOL),
        "analysis_grid_scientific_design_retained": True,
        "v1_execution_authorities_accepted": False,
        "v1_prepared_attempts": "RETIRED_PRESTART_PARSER_INCOMPATIBLE",
        "v1_attempts_may_be_run_edited_deleted_or_used_for_accuracy": False,
    }


def build_document() -> Dict[str, Any]:
    require_absent(PUBLICATION_PATH, "canonical_prefreeze_seal")
    require_absent(FUTURE_ACCURACY_ROOT, "future_accuracy_root")
    require_absent(FUTURE_EXECUTION_LOCK_ROOT, "future_execution_lock_root")
    if set(CASE_POLICY) != set(CASE_ORDER):
        raise BuildError("CASE_POLICY_SET_MISMATCH")
    if set(EXPECTED_PREPARED_MANIFESTS) != set(CASE_ORDER):
        raise BuildError("EXPECTED_PREPARED_MANIFEST_SET_MISMATCH")
    if CONDITIONAL_CASES | set(STRUCTURAL_NA_REASONS) != set(CASE_ORDER):
        raise BuildError("CASE_ADMISSION_PARTITION_MISMATCH")
    if CONDITIONAL_CASES & set(STRUCTURAL_NA_REASONS):
        raise BuildError("CASE_ADMISSION_PARTITION_OVERLAP")

    authorities = {
        label: strict_identity(path, size, digest, label)
        for label, (path, size, digest) in EXPECTED_AUTHORITIES.items()
    }
    analysis_code = analysis_code_identities()
    pointer, roster, pointer_cases = _load_roster_authorities()
    cases = [
        _build_case(case_id, pointer_cases[case_id], roster)
        for case_id in CASE_ORDER
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "reporting_boundary": (
            "outcome-blind design and input identity seal only; no HFNet result "
            "opened and no accuracy calculated"
        ),
        "authorities": authorities,
        "execution_authority_adjudication": execution_authority_adjudication(),
        "analysis_code_identities": analysis_code,
        "case_count": 10,
        "case_order": list(CASE_ORDER),
        "cases": cases,
        "analysis_contract": analysis_contract(),
        "evo_environment": _evo_environment(),
        "future_accuracy_controller_contract": future_controller_contract(),
        "future_accuracy_namespace": future_accuracy_namespace_contract(),
        "future_accuracy_execution_lock_namespace": (
            future_accuracy_execution_lock_namespace_contract()
        ),
        "outcome_firewall": {
            "hfnet_result_log_or_trajectory_files_opened": False,
            "accuracy_execution_lock_or_bridge_receipt_observed": False,
            "historical_trajectory_contents_parsed_for_metrics": False,
            "historical_files_read_for_identity_hashing_only": True,
            "ape_or_rpe_computed": False,
            "winner_or_ranking_computed": False,
            "all_ten_attempts_prepared_not_started": True,
        },
        "claims": {
            "hfnet_started": False,
            "hfnet_result_observed": False,
            "hfnet_log_observed": False,
            "hfnet_trajectory_observed": False,
            "accuracy_execution_lock_frozen": False,
            "hfnet_timestamp_bridge_receipt_frozen": False,
            "common_support_computed": False,
            "accuracy_analysis_started": False,
            "accuracy_measured": False,
            "winner_or_ranking_authorized": False,
            "retry_authorized": False,
        },
        "publication_contract": publication_contract(),
    }


def validate_document(document: Mapping[str, Any]) -> None:
    require_absent(PUBLICATION_PATH, "canonical_prefreeze_seal")
    require_absent(FUTURE_ACCURACY_ROOT, "future_accuracy_root")
    require_absent(FUTURE_EXECUTION_LOCK_ROOT, "future_execution_lock_root")
    if document.get("schema_version") != SCHEMA_VERSION or document.get("status") != STATUS:
        raise BuildError("DOCUMENT_SCHEMA_OR_STATUS")
    expected_authorities = {
        label: strict_identity(path, size, digest, label)
        for label, (path, size, digest) in EXPECTED_AUTHORITIES.items()
    }
    if document.get("authorities") != expected_authorities:
        raise BuildError("DOCUMENT_AUTHORITIES")
    if document.get("execution_authority_adjudication") != execution_authority_adjudication():
        raise BuildError("DOCUMENT_EXECUTION_AUTHORITY_ADJUDICATION")
    if document.get("analysis_code_identities") != analysis_code_identities():
        raise BuildError("DOCUMENT_ANALYSIS_CODE_IDENTITIES")
    if document.get("case_count") != 10 or document.get("case_order") != list(CASE_ORDER):
        raise BuildError("DOCUMENT_CASE_ORDER")
    cases = document.get("cases")
    if not isinstance(cases, list) or [row.get("case_id") for row in cases] != list(CASE_ORDER):
        raise BuildError("DOCUMENT_CASES")
    for row in cases:
        case_id = row["case_id"]
        admitted = case_id in CONDITIONAL_CASES
        dataset, grid_count, reference_gap, estimate_gap, _ = CASE_POLICY[case_id]
        expected_admission = (
            "CONDITIONAL_ON_FUTURE_HFNET_RUNABILITY_PASS_AND_FOURWAY_GATE"
            if admitted
            else "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND"
        )
        if row.get("accuracy_admission") != expected_admission:
            raise BuildError(f"DOCUMENT_ADMISSION:{case_id}")
        if row.get("structural_na_reasons") != list(
            STRUCTURAL_NA_REASONS.get(case_id, ())
        ):
            raise BuildError(f"DOCUMENT_STRUCTURAL_NA:{case_id}")
        if row.get("dataset") != dataset:
            raise BuildError(f"DOCUMENT_DATASET:{case_id}")
        grid = row.get("analysis_grid")
        if not isinstance(grid, dict) or (
            grid.get("count"),
            grid.get("step_ns"),
            grid.get("reference_max_two_sided_gap_ns"),
            grid.get("each_estimate_max_two_sided_gap_ns"),
        ) != (grid_count, GRID_STEP_NS, reference_gap, estimate_gap):
            raise BuildError(f"DOCUMENT_GRID_OR_GAPS:{case_id}")
        if row.get("claims") != {
            "hfnet_started": False,
            "hfnet_result_observed": False,
            "hfnet_log_observed": False,
            "hfnet_trajectory_observed": False,
            "accuracy_execution_lock_frozen": False,
            "hfnet_timestamp_bridge_receipt_frozen": False,
            "common_support_computed": False,
            "accuracy_analysis_started": False,
            "accuracy_measured": False,
            "ranking_authorized": False,
        }:
            raise BuildError(f"DOCUMENT_CASE_CLAIMS:{case_id}")
        expected_hfnet_absences = _future_hfnet_paths(
            case_id, RUNTIME_ROOT / case_id / "attempt_001"
        )
        if row.get("future_hfnet_outputs_observed_absent") != expected_hfnet_absences:
            raise BuildError(f"DOCUMENT_FUTURE_HFNET_PATHS:{case_id}")
        future = row.get("future_accuracy_publication")
        expected_accuracy = _future_accuracy_paths(case_id)
        if not isinstance(future, dict) or future != expected_accuracy:
            raise BuildError(f"DOCUMENT_FUTURE_ACCURACY:{case_id}")
    claims = document.get("claims")
    if not isinstance(claims, dict) or not claims or any(value is not False for value in claims.values()):
        raise BuildError("DOCUMENT_CLAIMS_NOT_ALL_FALSE")
    if document.get("outcome_firewall") != {
        "hfnet_result_log_or_trajectory_files_opened": False,
        "accuracy_execution_lock_or_bridge_receipt_observed": False,
        "historical_trajectory_contents_parsed_for_metrics": False,
        "historical_files_read_for_identity_hashing_only": True,
        "ape_or_rpe_computed": False,
        "winner_or_ranking_computed": False,
        "all_ten_attempts_prepared_not_started": True,
    }:
        raise BuildError("DOCUMENT_OUTCOME_FIREWALL")
    evo = document.get("evo_environment")
    if not isinstance(evo, dict) or evo != _evo_environment():
        raise BuildError("DOCUMENT_EVO_ENVIRONMENT")
    contract = document.get("analysis_contract")
    if not isinstance(contract, dict) or contract != analysis_contract():
        raise BuildError("DOCUMENT_ANALYSIS_CONTRACT")
    if document.get("future_accuracy_controller_contract") != future_controller_contract():
        raise BuildError("DOCUMENT_FUTURE_CONTROLLER_CONTRACT")
    if document.get("future_accuracy_namespace") != future_accuracy_namespace_contract():
        raise BuildError("DOCUMENT_FUTURE_ACCURACY_NAMESPACE")
    if (
        document.get("future_accuracy_execution_lock_namespace")
        != future_accuracy_execution_lock_namespace_contract()
    ):
        raise BuildError("DOCUMENT_FUTURE_EXECUTION_LOCK_NAMESPACE")
    if document.get("publication_contract") != publication_contract():
        raise BuildError("DOCUMENT_PUBLICATION_CONTRACT")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_file_noreplace(path: Path, payload: bytes) -> Dict[str, Any]:
    """Commit complete bytes on fuseblk without rename or replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.publish-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    linked = False
    committed_identity: Dict[str, Any] | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            os.fchmod(stream.fileno(), 0o444)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(str(temporary), str(path))
        except FileExistsError as error:
            raise BuildError(f"OUTPUT_ALREADY_EXISTS:{path}") from error
        linked = True
        try:
            committed_identity = file_identity(path)
            if (
                committed_identity["size_bytes"] != len(payload)
                or committed_identity["sha256"] != sha256_bytes(payload)
            ):
                raise BuildError("LINKED_OUTPUT_PAYLOAD_IDENTITY_MISMATCH")
            fsync_directory(path.parent)
            temporary.unlink()
            fsync_directory(path.parent)
        except (BuildError, OSError) as error:
            raise PublicationIndeterminate(
                f"OUTPUT_LINKED_DURABILITY_OR_CLEANUP_UNCONFIRMED:{path}:{error}"
            ) from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            if linked:
                raise PublicationIndeterminate(
                    f"OUTPUT_LINKED_TEMP_CLEANUP_UNCONFIRMED:{path}:{error}"
                ) from error
    if committed_identity is None:  # pragma: no cover - defensive invariant.
        raise BuildError("OUTPUT_COMMIT_IDENTITY_MISSING")
    return committed_identity


class RunnerSerialLock:
    def __init__(self, path: Path):
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> "RunnerSerialLock":
        metadata = _regular_file_metadata(self.path)
        if metadata.st_size != 0:
            raise BuildError("RUNNER_SERIAL_LOCK_FILE_NOT_EMPTY")
        self.descriptor = os.open(
            str(self.path),
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_size != metadata.st_size
        ):
            os.close(self.descriptor)
            self.descriptor = None
            raise BuildError("RUNNER_SERIAL_LOCK_CHANGED_DURING_OPEN")
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self.descriptor)
            self.descriptor = None
            raise BuildError(f"RUNNER_SERIAL_LOCK_BUSY:{error}") from error
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.descriptor is not None:
            try:
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self.descriptor)
                self.descriptor = None


def dry_run_document() -> Dict[str, Any]:
    with RunnerSerialLock(RUNNER_SERIAL_LOCK):
        first = build_document()
        validate_document(first)
        second = build_document()
        validate_document(second)
        if canonical_json(first) != canonical_json(second):
            raise BuildError("DRY_RUN_TOCTOU_OR_NONDETERMINISM")
        return first


def publish(authorization_token: str) -> Dict[str, Any]:
    if authorization_token != PUBLISH_AUTHORIZATION_TOKEN:
        raise BuildError("PUBLISH_AUTHORIZATION_TOKEN_MISMATCH")
    if PUBLICATION_PATH.resolve(strict=False) != Path(
        "/mnt/data/AQUA-FE_WS/locks/"
        "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
    ).resolve(strict=False):  # pragma: no cover - immutable constant guard.
        raise BuildError("NONCANONICAL_PUBLICATION_PATH")
    with RunnerSerialLock(RUNNER_SERIAL_LOCK):
        first = build_document()
        validate_document(first)
        second = build_document()
        validate_document(second)
        first_bytes = canonical_json(first)
        if first_bytes != canonical_json(second):
            raise BuildError("PUBLISH_TOCTOU_OR_NONDETERMINISM")
        return publish_file_noreplace(PUBLICATION_PATH, first_bytes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("dry-run", help="validate and print the seal without writing")
    publish_parser = subparsers.add_parser(
        "publish", help="write the one canonical seal exactly once"
    )
    publish_parser.add_argument("--authorization-token", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "dry-run":
            result = dry_run_document()
        else:
            result = publish(arguments.authorization_token)
    except PublicationIndeterminate as error:
        print(
            json.dumps(
                {
                    "status": "PUBLICATION_INDETERMINATE_DO_NOT_RETRY",
                    "error": f"{type(error).__name__}:{error}",
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    except (BuildError, KeyError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_NO_OUTPUT_COMMITTED",
                    "error": f"{type(error).__name__}:{error}",
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    sys.stdout.buffer.write(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
