#!/usr/bin/env python3
"""Fail-closed, one-shot A09 AQUA-FE-only v2 supervisor.

This runner never creates the KLT input.  It consumes a separately accepted
full-history KLT export, runs the frozen causal stock-XFeat sidecar exactly
once, audits the complete learned-feature contract, and publishes the result
only after a directory-commit and post-commit rehash.

The run is development-only.  An ambient desktop/ToDesk process is allowed by
the user's explicit waiver, so this runner makes no runtime or throughput
claim.  It still owns and drains every process that it starts.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import io
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence


sys.dont_write_bytecode = True


ROOT = Path("/home/ma/AQUA-FE_WS")
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
FRONTENDS = EXP_ROOT / "frontends"
RAW_DIR = EXP_ROOT / "raw"
RAW_BAG = RAW_DIR / "archaeo09_0000_4400.bag"
RAW_RECEIPT = RAW_DIR / "raw_materialization_receipt_v1.json"
RAW_ADDENDUM = RAW_DIR / "raw_materialization_canonicalization_addendum_v1.json"
RAW_FREEZE = ROOT / "papers/a09_samehistory_warmstart_v1_raw_materialization_freeze.json"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
GROUND_TRUTH = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_groundtruth_files/"
    "new_archaeo_colmap_traj_sequence_09.txt"
)

KLT_DIR = FRONTENDS / "klt_export"
KLT_TAG = "systemfair_a09_warmstart_v1_feed0000_4400_klt_export"
KLT_WORKSPACE = ROOT / f"logs/aqualoc_archaeo_vins/external_klt_every2_{KLT_TAG}"
KLT_STRENGTH_ADDENDUM = (
    ROOT / "papers/a09_samehistory_warmstart_v1_klt_execution_strength_addendum.json"
)
KLT_STRENGTH_IDENTITY_KEY = "klt_execution_strength_addendum"
KLT_STRENGTH_BUILDER = (
    ROOT / "scripts/build_a09_samehistory_warmstart_v1_klt_execution_addendum.py"
)
KLT_STRENGTH_BUILDER_IDENTITY_KEY = "klt_execution_strength_addendum_builder"
AQUA_DIR = FRONTENDS / "aquafe_finalonline"
AQUA_STAGE = FRONTENDS / ".aquafe_finalonline.stage_v2"
AQUA_FAILURE = FRONTENDS / "aquafe_finalonline_failed_v2"
GLOBAL_FLOCK = EXP_ROOT / ".frontend_supervisor.flock"

DEFAULT_LOCK = ROOT / "papers/a09_samehistory_warmstart_v2_aquafe_execution_lock.json"
PROTOCOL = ROOT / "papers/a09_samehistory_warmstart_v2_aquafe_protocol.md"
BUILDER = ROOT / "scripts/build_a09_samehistory_warmstart_v2_aquafe_lock.py"
A10_HELPER = ROOT / "scripts/run_samehistory_system_a10_finalonline_v3_recovery.py"

CLAIM_NAME = "process_start_claim_v2.json"
RECEIPT_NAME = "formal_run_receipt_v2.json"
LOG_NAME = "supervisor_process.log"
FAILURE_RECEIPT_NAME = "failure_receipt_v2.json"
SCHEMA = "aqua-fe-a09-samehistory-warmstart-aquafe-supervisor-v2"
LOCK_SCHEMA = "aqua-fe-a09-samehistory-warmstart-aquafe-lock-v2"

LOCK_EXECUTION_POLICY = {
    "single_popen": True,
    "retry_count": 0,
    "durable_claim_before_popen": True,
    "complete_effective_environment_allowlist": True,
    "start_new_session": True,
    "process_group_and_owned_descendants_must_be_empty": True,
    "canonical_symlink_must_bind_exact_stage_inode": True,
    "directory_commit_then_postcommit_rehash": True,
    "ambient_desktop_allowed_by_user_development_waiver": True,
    "runtime_or_throughput_claim_permitted": False,
}
LOCK_CLAIM_BOUNDARY = {
    "frontend_artifact_only": True,
    "vins_or_slam_executed": False,
    "trajectory_or_accuracy_result_available": False,
    "formal_paper_accuracy_evidence_permitted": False,
}
LOCK_TOP_LEVEL_KEYS = {
    "schema_version", "status", "created_at_utc", "stage", "argv",
    "argv_sha256", "effective_environment", "effective_environment_sha256",
    "identities", "config_chain", "dependency_acceptance",
    "execution_policy", "claim_boundary",
}
KLT_ADDENDUM_LIMITATIONS = {
    "old_receipt_waited_session_leader_only": True,
    "old_receipt_process_group_claim_is_not_strong_proof": True,
    "cannot_retroactively_prove_descendants_empty_at_leader_exit": True,
    "old_receipt_environment_records_overrides_only": True,
    "full_effective_environment_not_proven": True,
    "old_claim_was_plain_write_not_durable_or_exclusive": True,
    "exactly_once_execution_not_proven": True,
    "addendum_is_posthoc_evidence_only": True,
    "runtime_or_paper_performance_claim_permitted": False,
}
KLT_POSTHOC_EXPECTED_PGID = 1_508_785
KLT_POSTHOC_EXPECTED_IDENTIFIERS = [
    {"pid": 1_508_785, "role": "group_leader"},
    {"pid": 1_508_829, "role": "science_child"},
    {"pid": 1_508_316, "role": "supervisor"},
]
KLT_POSTHOC_EXPECTED_MARKERS = [
    "run_a09_samehistory_warmstart_v1_frontends.py run-klt",
    "run_paper_sidecar_profiles.sh aqualoc_archaeo_loftr_mirror_klt 9 0 4400",
    "run_aqualoc_archaeo_vins_eval.sh external 9 0 4400 klt 2",
    "uw_frontend.ros.export_vins_features --bag "
    "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/raw/"
    "archaeo09_0000_4400.bag",
]
KLT_POSTHOC_IDENTIFIER_PROVENANCE = (
    "EXTERNAL_ORCHESTRATOR_LIVE_PROC_OBSERVATION_DURING_EXECUTION_"
    "NOT_BOUND_BY_ORIGINAL_V1_RECEIPT"
)
KLT_POSTHOC_DESCENDANT_INTERPRETATION = (
    "No original-PGID member, observed PID, or known A09 KLT command marker "
    "was present at this post-hoc snapshot; this is not a contemporaneous "
    "proof of descendant emptiness when the leader exited."
)
KLT_ADDENDUM_TOP_LEVEL_KEYS = {
    "schema_version", "status", "observed_at_utc", "auditor_identity",
    "bindings", "path_state", "posthoc_process_tree",
    "postcommit_external_rehash", "limitations", "claim_boundary",
}
KLT_ADDENDUM_CLAIM_BOUNDARY = {
    "frontend_artifact_only": True,
    "vins_or_slam_executed": False,
    "trajectory_or_accuracy_result_available": False,
    "runtime_or_throughput_claim_permitted": False,
    "formal_paper_accuracy_evidence_permitted": False,
}

XFEAT_NODE = ROOT / "uw_frontend/ros/xfeat_seed_sidecar_node.py"
SELECTOR_NODE = ROOT / "uw_frontend/ros/causal_lineage_shadow_node.py"
CONFIG_TOP = ROOT / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml"
CAMERA_CONFIG = KLT_DIR / "aqualoc_archaeo09_pinhole.yaml"
BASE_BAG = KLT_DIR / "features.bag"

FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"
CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"

CHANNELS = (
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y",
    "gx", "gy", "gz", "quality", "sigma", "source_code", "is_learned",
)
STATS_COLUMNS = (
    "frame_index", "stamp", "base_tracks", "base_grid_coverage",
    "base_dropout_ratio", "base_long_track_ratio", "image_degradation",
    "image_flat_region_ratio", "image_grid_texture", "triggered",
    "trigger_reason", "trigger_count", "match_count", "added_seeds",
    "tracked_before", "tracked_after", "active_seeds", "max_seed_age",
    "velocity_contract_scale", "match_ms", "processing_ms",
    "selector_frame_index", "selector_stamp", "selector_discovered_ids",
    "selector_evaluated_ids", "selector_activated_ids",
    "selector_retired_ids", "selector_active_ids", "selector_selected_ids",
    "selector_injected_observations", "image_match_delta_s",
)
STATS_HEADER_SHA256 = "f9ea50d9fb582d076bd22278d02111d021f73b1ebe346c5aadaaeaed2ca9fb36"
KLT_HEADER_SHA256 = "7afdc87e9515a88a83e4c7560042b3013f9dce303f77da2f40e6c6fcab846e83"
CAMERA_YAML_SHA256 = "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5"
POINTCLOUD_MD5 = "d8e9c3f5afbdd8a130fd1d2763945fca"

CAMERA_COUNT = 4_401
FEATURE_COUNT = 2_200
PREFIX_FEATURE_COUNT = 2_000
SCORE_FEATURE_COUNT = 200
IMU_COUNT = 44_025
GT_COUNT = 213
FEATURE_FIRST_NS = 1_542_888_746_121_190_768
SCORE_FEATURE_FIRST_NS = 1_542_888_946_088_258_928
FEATURE_LAST_NS = 1_542_888_965_985_217_392


class AquaV2Error(RuntimeError):
    """A fail-closed contract violation."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AquaV2Error(code)


def compact_sha(value: Any) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def no_symlink_components(path: Path, *, missing_leaf_ok: bool = False) -> None:
    path = path.absolute()
    current = Path(path.parts[0])
    for index, part in enumerate(path.parts[1:], start=1):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if missing_leaf_ok and index == len(path.parts) - 1:
                return
            raise AquaV2Error(f"MISSING_PATH_COMPONENT:{current}")
        require(not stat.S_ISLNK(mode), f"SYMLINK_PATH_COMPONENT:{current}")


def snapshot_file(path: Path) -> dict[str, Any]:
    """Hash a regular file without loading a multi-GB bag into memory."""
    path = path.absolute()
    no_symlink_components(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AquaV2Error(f"OPEN_REGULAR_FAILED:{path}:{error.errno}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"NOT_REGULAR_FILE:{path}")
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(
            all(getattr(before, name) == getattr(after, name) for name in fields),
            f"FILE_CHANGED_WHILE_HASHING:{path}",
        )
        return {
            "path": str(path), "size_bytes": int(before.st_size),
            "sha256": digest.hexdigest(), "device": int(before.st_dev),
            "inode": int(before.st_ino), "mtime_ns": int(before.st_mtime_ns),
            "ctime_ns": int(before.st_ctime_ns),
        }
    finally:
        os.close(descriptor)


def public_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("path", "size_bytes", "sha256")}


def content_identity(value: Mapping[str, Any]) -> tuple[int, str]:
    return int(value["size_bytes"]), str(value["sha256"])


def postcommit_fingerprint(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        value[key]
        for key in ("size_bytes", "sha256", "device", "inode", "mtime_ns", "ctime_ns")
    )


def require_expected(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    actual = snapshot_file(path)
    require(content_identity(actual) == expected, f"IDENTITY_DRIFT:{path}")
    return actual


# These are accidental-drift authorities, not a recursive OS-package SBOM.
# Every local science source that can change this child and the A10-equivalent
# package entry points are pinned.  All external-tools paths use their real
# /mnt spelling so snapshot_file never traverses the workspace symlink.
STATIC_EXPECTED: dict[str, tuple[Path, int, str]] = {
    "python3_8": (Path("/usr/bin/python3.8"), 5_490_456, "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06"),
    "a10_supervisor_helper": (A10_HELPER, 212_018, "925d0d46c130538e629c7b50c1c53c8f6df3962708ef3e0d92beea2518c336c1"),
    "xfeat_sidecar_node": (XFEAT_NODE, 41_561, "9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7"),
    "causal_selector": (SELECTOR_NODE, 16_891, "8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727"),
    "uw_frontend_init": (ROOT / "uw_frontend/__init__.py", 75, "44c8ccc9ab0cd7e8637b0dd005f183fb7b250a539c8b22ea6d26889a394f0934"),
    "datasets_init": (ROOT / "uw_frontend/datasets/__init__.py", 60, "3e51607ce52c41b4cdba7cdc4b09e9cf3aff20c2e90b028971ab950cb8010477"),
    "image_sequence": (ROOT / "uw_frontend/datasets/image_sequence.py", 4_844, "2ba225a52a7caab9e92eb6b06c3ae7ff9a0030b96ea78e6f20f4228e97337384"),
    "evaluation_init": (ROOT / "uw_frontend/evaluation/__init__.py", 50, "b95c4d2adf475a333bb42261ad54ee79656fe5aaecb351c4ecec31c18f5dea9b"),
    "frontend_metrics": (ROOT / "uw_frontend/evaluation/frontend_metrics.py", 17_993, "dae3258f04316c387bbbee5b0870132f7bac4fb3261b6069f690f06e07b9baf8"),
    "measurement_selection": (ROOT / "uw_frontend/evaluation/measurement_selection.py", 46_894, "83230a42744be60e010ee4870011375fdd432a562843388c7adacd030dc298d3"),
    "frontend_config_loader": (ROOT / "uw_frontend/evaluation/run_frontend_eval.py", 33_121, "c299038feb926e37bada04d0f150e57d45bed2f4d91bad8fb6a0c4ab2b22e6d2"),
    "finetune_init": (ROOT / "uw_frontend/finetune/__init__.py", 395, "349d8612c0c145c7821749b7e0d7996fced37cbc2581e2eab3b9a073722e2bf4"),
    "uw_adapter": (ROOT / "uw_frontend/finetune/uw_adapter.py", 3_700, "e2d963679a350c8a78d12931337a0efaf2da6954fbaf75a39fb2f0e70fc64f71"),
    "geometry_init": (ROOT / "uw_frontend/geometry/__init__.py", 39, "f51eef8fcc512e338b3c5fd4f1e77f1dcb19dc09ab68eaab9289c968d56de882"),
    "geometry_dl_vins_magsac": (ROOT / "uw_frontend/geometry/dl_vins_magsac.py", 4_232, "d3c70b0c1f83f589380db82172b448ade485c101ed10102744f8a8d32487e128"),
    "geometry_grid": (ROOT / "uw_frontend/geometry/grid.py", 1_155, "c1e6be4bfaee6cc1cac222c2dc5ba8f3e941702c60074f8473f663cf706de6eb"),
    "geometry_mode": (ROOT / "uw_frontend/geometry/mode.py", 5_833, "402b5dc3eaecfb450a889502760cd591d02ff9c0e770edb522d1c777634c7a69"),
    "geometry_validation": (ROOT / "uw_frontend/geometry/validation.py", 2_954, "4e2080bf786bf59b13af87ea7ee56b70b5f03892160ccd0a75aa9968d1781bb2"),
    "matchers_init": (ROOT / "uw_frontend/matchers/__init__.py", 82, "ad377bf38dfe58a58b8db275c70c1f5b9372ab6329d0591bc88ff5425f949c13"),
    "matcher_base": (ROOT / "uw_frontend/matchers/base.py", 741, "ad1baae7dc56188ae9d4a117de5efe0ae032a1b2749a4de38474c43d960876fa"),
    "classical_gftt_matcher": (ROOT / "uw_frontend/matchers/classical_gftt.py", 3_799, "ec846d33ef8cc6ccb8e69fb30d87214c660807f94e9ca3b19aed6c944316604f"),
    "lightglue_adapter": (ROOT / "uw_frontend/matchers/lightglue_adapter.py", 6_384, "9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a"),
    "loftr_adapter": (ROOT / "uw_frontend/matchers/loftr_adapter.py", 5_600, "105cf63af51b6d4f8554a76939f88509d30fd85abc1b804ef18f2fd78edaebc2"),
    "xfeat_adapter": (ROOT / "uw_frontend/matchers/xfeat_adapter.py", 7_014, "8090ad7246b7acba62183577d108f62b41c87fe04f52c66f5d897315481e91ee"),
    "quality_init": (ROOT / "uw_frontend/quality/__init__.py", 42, "940c342bc9918992c9e53190993d1bff4f04970d3d0a9536d99f069a1b4a85fd"),
    "feature_confidence": (ROOT / "uw_frontend/quality/feature_confidence.py", 6_691, "2ba770c1be212ec587c64ae0a35b3abc1dd58458f2e6eda572444859faf82864"),
    "image_quality": (ROOT / "uw_frontend/quality/image_quality.py", 13_301, "e0b4a885cb8ecd2909b8abefc0fbc17098c9596df44091d5a3398df56583b89e"),
    "reliability_features": (ROOT / "uw_frontend/quality/reliability_features.py", 4_064, "f5f3d770af0655e7d68dbec9fdf043d6b772dd7b11b0f43ebc821515978cd8a4"),
    "ros_init": (ROOT / "uw_frontend/ros/__init__.py", 59, "63e8c6c8109779dde006b8e6067ae7dabb9520342bd069a210615ba1a2c774d1"),
    "vins_pointcloud_exporter": (ROOT / "uw_frontend/ros/export_vins_features.py", 437_542, "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"),
    "scheduler_init": (ROOT / "uw_frontend/scheduler/__init__.py", 44, "c7ddade87b1a990451e559aa16a24892309a95cee6f5b976bc7e93e719279a90"),
    "hybrid_scheduler": (ROOT / "uw_frontend/scheduler/hybrid_scheduler.py", 6_956, "71e8ee6f95b47e6fbbfc8d25c96affea2abca217c91c47f75e0d13750ab3279b"),
    "tracking_init": (ROOT / "uw_frontend/tracking/__init__.py", 34, "74c60ba0b8a4cceec88519da9c269dce3b796812e900a0cdf10110488c2a696a"),
    "hybrid_tracker": (ROOT / "uw_frontend/tracking/hybrid_tracker.py", 220_766, "7772772f1baf0966a4b1096ac1cd3122d71edbe18031756de409443e7c5ea2ae"),
    "klt_patch_helper": (ROOT / "uw_frontend/tracking/klt_tracker.py", 12_306, "e60957bc0b45a11ef24824fa95ef9093dbbd7ba5998bc82bb91641c831f1fb5b"),
    "matcher_recovery": (ROOT / "uw_frontend/tracking/matcher_recovery.py", 30_796, "3d65f84f0d81a85ec7ce97daa44b9885ed8726f4df4c330b76fa390a9eb46e70"),
    "orb_tracker": (ROOT / "uw_frontend/tracking/orb_tracker.py", 10_987, "c8490ab98348a6e57b2b250df7faf52cc527206449e9a90778001c84d7e363b2"),
    "pairwise_matcher_tracker": (ROOT / "uw_frontend/tracking/pairwise_matcher_tracker.py", 17_147, "c2796382afdf79f4ab6c06615390749a6a91e5d8b7cf1f239209ea51e47500c6"),
    "track_state": (ROOT / "uw_frontend/tracking/track_state.py", 1_181, "c6a5f23209f830088a33cf2afd733c3520d7da88e14a0f10c01e8d54ce384802"),
    "config_top": (CONFIG_TOP, 778, "369120917878b55564d6d993670328738e5436beae92bee25e99dd86c3eb66a6"),
    "config_seedchain": (ROOT / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml", 886, "c98df8dcf6a58261798d06433f52a8bf02bf39968a52fe85475284f845229d38"),
    "config_churn": (ROOT / "uw_frontend/configs/experiments/cirs_identity_churn_xfeat_probe.yaml", 1_466, "9e16c2b2377d95d2a855b05733a2bc37d77defc1ed101ea8ba88afc8e7c1db91"),
    "config_active": (ROOT / "uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml", 1_478, "2a61f1c57a77df4ed6bf2d85c080c7e6bd754a2ff47171e526e0643a3d617a25"),
    "config_paper_safe": (ROOT / "uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml", 1_964, "4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce"),
    "config_loftr_extreme": (ROOT / "uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml", 2_121, "d5927fb412de869cfe9dd6275dfb81a566fc33e4149160bafc0e8fa933b27eed"),
    "config_three_layer": (ROOT / "uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml", 5_453, "236e5173611731ffefd3acdd3b9f69429633dac16ae66429690d609fab0dd5d7"),
    "config_backend_strict": (ROOT / "uw_frontend/configs/backend_strict_frontend.yaml", 9_082, "908351d3d9547b98f917ffd059efdc7b279ee7f9199887688cda48e178a4855a"),
    "xfeat_modules_init": (Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/__init__.py"), 140, "e19469abdce05280ae3adb40cdea9cfe7d50dcb8a3619cc98382a4a46236c386"),
    "xfeat_stock_module": (Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/xfeat.py"), 13_472, "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7"),
    "xfeat_stock_model": (Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/model.py"), 4_542, "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964"),
    "xfeat_interpolator": (Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/interpolator.py"), 1_175, "d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da"),
    "xfeat_weights": (Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/weights/xfeat.pt"), 6_247_949, "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b"),
    "opencv_python_binary": (Path("/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so"), 6_970_496, "00f302d1efe76049187e2e2c7a05262e883394f82316490e2f28adb807ac1833"),
    "numpy_python_entry": (Path("/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py"), 16_174, "edd18feff93348beb02f392959e80b9fda1875a842d7f9760847f32386fdfd48"),
    "torch_python_entry": (Path("/home/ma/.local/lib/python3.8/site-packages/torch/__init__.py"), 78_481, "fe825c99bf91627cc438ab1967e413f4efef8599de835fb71af926c15b07a223"),
    "rosbag_python_entry": (Path("/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py"), 1_800, "a65e884f18df0e88ff7403b53d77ad9ac59bd24734d880e301f7afe68fec4a81"),
    "pyyaml_python_entry": (Path("/usr/lib/python3/dist-packages/yaml/__init__.py"), 13_170, "5c550d6ca4e0e1a7c07740444e3190d66290f7bfe0e636c4d42d16a0a73be1d7"),
    "cv_bridge_init": (Path("/opt/ros/noetic/lib/python3/dist-packages/cv_bridge/__init__.py"), 244, "a9e514401a9f32b58a535bd7964fc19d77519ab47bec76ceef8f5fb7db70390e"),
    "cv_bridge_core": (Path("/opt/ros/noetic/lib/python3/dist-packages/cv_bridge/core.py"), 11_830, "f39332d4013334759f2734ed0017a84728185a8bf366f5a3c958c4f98042d9d5"),
    "cv_bridge_boost": (Path("/opt/ros/noetic/lib/python3/dist-packages/cv_bridge/boost/cv_bridge_boost.so"), 98_352, "a89310abeaa33112a9f145f5f0d5a6f9ffe70c1d21f1e3b76f66417496d8c632"),
    "cv_bridge_library": (Path("/opt/ros/noetic/lib/libcv_bridge.so"), 167_416, "d68e8bfdaa8adec589f540a838bf604d2211088bb275c8fbf87e08e084967db6"),
    "pointcloud_message": (Path("/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_PointCloud.py"), 12_155, "ab1d8018476ccdf630506cbf12d35065be36ec4269ea97f12abdde52b2f50b0d"),
    "channel_message": (Path("/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_ChannelFloat32.py"), 6_061, "911f546066708c69609b88f5aae2be7042890d9a29dbff9ad7560dc31b72a610"),
    "raw_bag": (RAW_BAG, 1_187_038_470, "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97"),
    "raw_receipt": (RAW_RECEIPT, 7_199, "b6f0ec00f04d5c62514b96b3ce591bc561221227ea05163793fc68d8c4d3cf91"),
    "raw_addendum": (RAW_ADDENDUM, 2_717, "86e82d58dbd85f39907144aa1098352b97282c143fef5259cacd2974c4ca0956"),
    "raw_freeze": (RAW_FREEZE, 2_422, "d72dcef75052194a8e48a8e14da5233412345b66a60b7c53e93e4650779cfa57"),
    "source_archive": (SOURCE_ARCHIVE, 1_722_658_380, "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901"),
    "ground_truth": (GROUND_TRUTH, 45_197, "b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17"),
}

CONFIG_CHAIN: tuple[tuple[Path, str | None], ...] = (
    (CONFIG_TOP, "cirs_xfeat_seedchain_klt_probe.yaml"),
    (ROOT / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml", "cirs_identity_churn_xfeat_probe.yaml"),
    (ROOT / "uw_frontend/configs/experiments/cirs_identity_churn_xfeat_probe.yaml", "low_texture_active_xfeat_sidecar.yaml"),
    (ROOT / "uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml", "paper_vins_safe_learned_sidecar.yaml"),
    (ROOT / "uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml", "loftr_extreme_only_frontend.yaml"),
    (ROOT / "uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml", "three_layer_source_aware_frontend.yaml"),
    (ROOT / "uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml", "../backend_strict_frontend.yaml"),
    (ROOT / "uw_frontend/configs/backend_strict_frontend.yaml", None),
)
MERGED_CONFIG_SHA256 = "9ecd1329953d4b95ab38297e173cfed880616050469b81d547ab1094efc8aa69"
EFFECTIVE_XFEAT_SHA256 = "7ddbc0d1e640f92433d9f080343ab8987f1f3a7fbbfb12283ab969c700b8e107"
EFFECTIVE_XFEAT = {
    "repo_path": "external_tools/accelerated_features",
    "top_k": 2_048,
    "semi_dense": False,
    "min_cossim": 0.82,
}
EXTERNAL_TOOLS_LINK = ROOT / "external_tools"
EXTERNAL_TOOLS_TARGET = "/mnt/data/AQUA-FE_WS/external_tools"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = json.loads(json.dumps(value))
    return result


def verify_external_tools_link() -> dict[str, Any]:
    info = EXTERNAL_TOOLS_LINK.lstat()
    require(stat.S_ISLNK(info.st_mode), "EXTERNAL_TOOLS_NOT_SYMLINK")
    target = os.readlink(EXTERNAL_TOOLS_LINK)
    require(target == EXTERNAL_TOOLS_TARGET, f"EXTERNAL_TOOLS_TARGET:{target}")
    resolved = EXTERNAL_TOOLS_LINK.resolve(strict=True)
    require(resolved == Path(EXTERNAL_TOOLS_TARGET), f"EXTERNAL_TOOLS_RESOLVE:{resolved}")
    return {
        "path": str(EXTERNAL_TOOLS_LINK), "target": target,
        "target_string_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        "device": int(info.st_dev), "inode": int(info.st_ino),
        "mtime_ns": int(info.st_mtime_ns), "ctime_ns": int(info.st_ctime_ns),
    }


def verify_config_chain() -> dict[str, Any]:
    # PyYAML is imported only after its entry point was identity-checked by the
    # caller.  The chain is interpreted independently rather than trusting an
    # unobserved recursive include.
    import yaml  # type: ignore

    parsed: list[dict[str, Any]] = []
    for index, (path, expected_extends) in enumerate(CONFIG_CHAIN):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        require(isinstance(value, dict), f"CONFIG_ROOT_NOT_OBJECT:{path}")
        actual_extends = value.get("extends")
        require(actual_extends == expected_extends, f"CONFIG_EXTENDS_DRIFT:{path}")
        if expected_extends is not None:
            resolved = (path.parent / expected_extends).resolve(strict=True)
            require(resolved == CONFIG_CHAIN[index + 1][0], f"CONFIG_EXTENDS_RESOLVE:{path}")
        local = dict(value)
        local.pop("extends", None)
        parsed.append(local)
    merged: dict[str, Any] = {}
    for local in reversed(parsed):
        merged = _deep_merge(merged, local)
    require(compact_sha(merged) == MERGED_CONFIG_SHA256, "MERGED_CONFIG_SHA_DRIFT")
    require(merged.get("xfeat") == EFFECTIVE_XFEAT, "EFFECTIVE_XFEAT_DRIFT")
    require(compact_sha(merged["xfeat"]) == EFFECTIVE_XFEAT_SHA256, "EFFECTIVE_XFEAT_SHA_DRIFT")
    repo = (ROOT / str(merged["xfeat"]["repo_path"])).resolve(strict=True)
    require(
        repo == Path("/mnt/data/AQUA-FE_WS/external_tools/accelerated_features"),
        f"XFEAT_REPO_RESOLUTION:{repo}",
    )
    weights = (repo / "weights/xfeat.pt").resolve(strict=True)
    require(
        weights == STATIC_EXPECTED["xfeat_weights"][0],
        f"XFEAT_WEIGHTS_RESOLUTION:{weights}",
    )
    return {
        "ordered_paths": [str(path) for path, _ in CONFIG_CHAIN],
        "merged_config_sha256": compact_sha(merged),
        "effective_xfeat": merged["xfeat"],
        "effective_xfeat_sha256": compact_sha(merged["xfeat"]),
        "resolved_repo": str(repo), "resolved_weights": str(weights),
    }


def static_authority_snapshots() -> dict[str, Any]:
    result: dict[str, Any] = {}
    # Validate the parser entry before importing yaml in verify_config_chain.
    for key, (path, size, digest) in STATIC_EXPECTED.items():
        result[key] = require_expected(path, (size, digest))
    result["external_tools_link"] = verify_external_tools_link()
    result["config_chain"] = verify_config_chain()
    return result


_A10_MODULE: Any | None = None


def a10_helper() -> Any:
    global _A10_MODULE
    if _A10_MODULE is not None:
        return _A10_MODULE
    require_expected(
        A10_HELPER,
        (STATIC_EXPECTED["a10_supervisor_helper"][1], STATIC_EXPECTED["a10_supervisor_helper"][2]),
    )
    name = "_a09_pinned_a10_v3_supervisor_helper"
    spec = importlib.util.spec_from_file_location(name, A10_HELPER)
    require(spec is not None and spec.loader is not None, "A10_HELPER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(snapshot_file(A10_HELPER)["sha256"] == STATIC_EXPECTED["a10_supervisor_helper"][2], "A10_HELPER_CHANGED_DURING_IMPORT")
    require(
        Path(str(module.__file__)).absolute() == A10_HELPER,
        "A10_HELPER_MODULE_PATH",
    )
    for function_name in (
        "atomic_publish", "canonical_json", "fsync_dir", "blocked_signals",
        "interruption_handlers", "enable_subreaper", "direct_child_identities",
        "process_identity", "drain_owned_processes", "validate_rosbag_topic_equal",
    ):
        require(callable(getattr(module, function_name, None)), f"A10_HELPER_API:{function_name}")
    _A10_MODULE = module
    return module


def build_argv() -> list[str]:
    return [
        "/usr/bin/python3.8", "-m", "uw_frontend.ros.xfeat_seed_sidecar_node", "bag",
        "--config", str(CONFIG_TOP),
        "--camera-config", str(CAMERA_CONFIG),
        "--image-bag", str(RAW_BAG),
        "--base-bag", str(BASE_BAG),
        "--output-bag", str(AQUA_DIR / "full_merged.bag"),
        "--sidecar-bag", str(AQUA_DIR / "sidecar.bag"),
        "--stats-csv", str(AQUA_DIR / "stats.csv"),
        "--image-topic", CAMERA_TOPIC,
        "--base-topic", FEATURE_TOPIC,
        "--sidecar-topic", SIDECAR_TOPIC,
        "--image-scale", "0.5", "--preprocess", "adaptive_clahe",
        "--trigger-warmup-frames", "0", "--trigger-cooldown-frames", "0",
        "--max-triggers", "3", "--trigger-degradation-min", "0.18",
        "--trigger-flat-region-min", "0.10", "--trigger-grid-texture-max", "0.90",
        "--trigger-base-tracks-max", "300", "--trigger-base-grid-max", "0.80",
        "--trigger-dropout-min", "0.18", "--trigger-long-track-ratio-max", "0.45",
        "--seed-max-per-trigger", "50", "--max-active-seeds", "72",
        "--seed-min-base-distance-px", "8", "--seed-min-active-distance-px", "10",
        "--seed-max-per-cell", "2", "--lk-fb-threshold", "1.20",
        "--lk-min-ncc", "0.42", "--min-observations", "10",
        "--rank-observations", "5", "--min-distance-px", "40",
        "--min-motion-ratio", "0.6", "--max-motion-ratio", "1.5",
        "--max-homography-residual-px", "0.75", "--max-lineages", "1",
        "--remap-id-base", "10000000", "--match-tolerance", "0.02",
    ]


def effective_environment() -> dict[str, str]:
    # This is a complete allowlist.  Ambient os.environ is never merged in.
    runtime = AQUA_DIR / "runtime_v2"
    result = {
        "CMAKE_PREFIX_PATH": "/home/ma/dave_ws/devel:/home/ma/uuv_ws/devel:/opt/ros/noetic",
        "HOME": "/home/ma", "LANG": "zh_CN.UTF-8", "LANGUAGE": "zh_CN:zh",
        "LD_LIBRARY_PATH": "/home/ma/dave_ws/devel/lib:/home/ma/uuv_ws/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
        "LOGNAME": "ma",
        "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PKG_CONFIG_PATH": "/home/ma/dave_ws/devel/lib/pkgconfig:/home/ma/uuv_ws/devel/lib/pkgconfig:/opt/ros/noetic/lib/pkgconfig:/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig",
        "PWD": str(ROOT),
        "PYTHONPATH": "/home/ma/dave_ws/devel/lib/python3/dist-packages:/home/ma/uuv_ws/devel/lib/python3/dist-packages:/opt/ros/noetic/lib/python3/dist-packages",
        "ROS_DISTRO": "noetic", "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
        "ROS_HOME": str(runtime / "ros_home"),
        "ROS_LOG_DIR": str(runtime / "ros_log"),
        "ROS_MASTER_URI": "http://localhost:11311",
        "ROS_PACKAGE_PATH": "/home/ma/dave_ws/src:/home/ma/uuv_ws/src:/opt/ros/noetic/share",
        "ROS_PYTHON_VERSION": "3", "ROS_ROOT": "/opt/ros/noetic/share/ros",
        "ROS_VERSION": "1", "USER": "ma",
        "CUDA_CACHE_DISABLE": "1", "CUDA_CACHE_PATH": str(runtime / "cuda_cache"),
        "MPLCONFIGDIR": str(runtime / "mpl_config"),
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0", "TMPDIR": str(runtime / "tmp"),
        "TORCH_HOME": str(runtime / "torch_home"),
        "XDG_CACHE_HOME": str(runtime / "xdg_cache"),
    }
    require(set(result) == set(result.keys()), "EFFECTIVE_ENV_DUPLICATE")
    return result


def symlink_guard(expected_stage_identity: tuple[int, int]) -> dict[str, Any]:
    stage_info = AQUA_STAGE.lstat()
    require(stat.S_ISDIR(stage_info.st_mode), "AQUA_STAGE_NOT_DIRECTORY")
    require(
        (int(stage_info.st_dev), int(stage_info.st_ino)) == expected_stage_identity,
        "AQUA_STAGE_INODE_CHANGED",
    )
    link_info = AQUA_DIR.lstat()
    require(stat.S_ISLNK(link_info.st_mode), "AQUA_CANONICAL_NOT_SYMLINK_DURING_STAGE")
    target = os.readlink(AQUA_DIR)
    require(target == str(AQUA_STAGE), f"AQUA_CANONICAL_TARGET:{target}")
    target_info = AQUA_DIR.stat()
    require(
        (int(target_info.st_dev), int(target_info.st_ino)) == expected_stage_identity,
        "AQUA_CANONICAL_TARGET_INODE_CHANGED",
    )
    return {
        "canonical": str(AQUA_DIR), "target": target,
        "link_device": int(link_info.st_dev), "link_inode": int(link_info.st_ino),
        "stage_device": expected_stage_identity[0], "stage_inode": expected_stage_identity[1],
    }


def committed_directory_guard(expected_stage_identity: tuple[int, int]) -> dict[str, Any]:
    require(AQUA_DIR.exists() and not AQUA_DIR.is_symlink(), "AQUA_COMMIT_NOT_REAL_DIRECTORY")
    info = AQUA_DIR.lstat()
    require(stat.S_ISDIR(info.st_mode), "AQUA_COMMIT_NOT_DIRECTORY")
    require(
        (int(info.st_dev), int(info.st_ino)) == expected_stage_identity,
        "AQUA_COMMIT_INODE_CHANGED",
    )
    require(not AQUA_STAGE.exists() and not AQUA_STAGE.is_symlink(), "AQUA_STAGE_SURVIVED_COMMIT")
    return {
        "path": str(AQUA_DIR), "device": int(info.st_dev), "inode": int(info.st_ino),
        "is_symlink": False,
    }


def exact_integer(value: Any, code: str) -> int:
    require(not isinstance(value, bool), f"INTEGER_BOOL:{code}")
    text = str(value)
    require(re.fullmatch(r"(?:0|[1-9][0-9]*)", text) is not None, f"INTEGER_GRAMMAR:{code}:{text!r}")
    return int(text)


def finite_number(value: Any, code: str) -> float:
    text = str(value)
    require(text == text.strip() and text != "", f"FLOAT_GRAMMAR:{code}:{text!r}")
    try:
        result = float(text)
    except ValueError as error:
        raise AquaV2Error(f"FLOAT_PARSE:{code}:{text!r}") from error
    require(math.isfinite(result), f"FLOAT_NONFINITE:{code}:{text!r}")
    return result


def ros_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "ROS_STAMP_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "ROS_STAMP_RANGE")
    return int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs)


def serialized_digest_update(digest: Any, message: Any, record_stamp: Any) -> None:
    payload = io.BytesIO()
    message.serialize(payload)
    data = payload.getvalue()
    digest.update(ros_ns(record_stamp).to_bytes(8, "big", signed=False))
    digest.update(len(data).to_bytes(8, "big", signed=False))
    digest.update(data)


def rosbag_module() -> Any:
    path = "/opt/ros/noetic/lib/python3/dist-packages"
    if path not in sys.path:
        sys.path.insert(0, path)
    import rosbag  # type: ignore
    return rosbag


def channel_map(message: Any) -> dict[str, Sequence[float]]:
    names = [str(channel.name) for channel in message.channels]
    require(tuple(names) == CHANNELS, f"POINTCLOUD_CHANNEL_ORDER:{names}")
    require(len(set(names)) == len(names), "POINTCLOUD_DUPLICATE_CHANNEL")
    result = {str(channel.name): channel.values for channel in message.channels}
    require(
        all(len(values) == len(message.points) for values in result.values()),
        "POINTCLOUD_CHANNEL_LENGTH",
    )
    return result


def integral_float(value: Any, code: str) -> int:
    number = finite_number(value, code)
    rounded = round(number)
    require(abs(number - rounded) <= 1e-6, f"POINTCLOUD_NONINTEGRAL:{code}:{number}")
    return int(rounded)


def validate_pointcloud(
    message: Any, record_stamp: Any, *, kind: str, camera: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require(getattr(message, "_type", None) == "sensor_msgs/PointCloud", f"POINTCLOUD_TYPE:{kind}")
    require(getattr(message, "_md5sum", None) == POINTCLOUD_MD5, f"POINTCLOUD_MD5:{kind}")
    require(message.header.frame_id == "world" and int(message.header.seq) == 0, f"POINTCLOUD_HEADER:{kind}")
    require(ros_ns(message.header.stamp) == ros_ns(record_stamp), f"POINTCLOUD_RECORD_STAMP:{kind}")
    count = len(message.points)
    if kind == "base":
        require(count == 350, "BASE_POINT_COUNT")
    elif kind == "sidecar":
        require(0 <= count <= 72, "SIDECAR_POINT_COUNT")
    elif kind == "merged":
        require(350 <= count <= 351, "MERGED_POINT_COUNT")
    else:
        raise AquaV2Error(f"POINTCLOUD_KIND:{kind}")
    channels = channel_map(message)
    for point in message.points:
        require(
            all(math.isfinite(float(value)) for value in (point.x, point.y, point.z)),
            f"POINT_NONFINITE:{kind}",
        )
        require(float(point.z) == 1.0, f"POINT_Z:{kind}")
    for name, values in channels.items():
        require(all(math.isfinite(float(value)) for value in values), f"CHANNEL_NONFINITE:{kind}:{name}")
    ids = [integral_float(value, f"{kind}:id") for value in channels["id"]]
    camera_ids = [integral_float(value, f"{kind}:camera") for value in channels["camera_id"]]
    sources = [integral_float(value, f"{kind}:source") for value in channels["source_code"]]
    learned = [integral_float(value, f"{kind}:learned") for value in channels["is_learned"]]
    require(len(ids) == len(set(ids)), f"POINTCLOUD_ID_DUPLICATE:{kind}")
    require(all(value == 0 for value in camera_ids), f"POINTCLOUD_CAMERA_ID:{kind}")
    for name in ("gx", "gy", "gz"):
        require(all(float(value) == 0.0 for value in channels[name]), f"POINTCLOUD_CONSTANT:{kind}:{name}")
    require(all(0.0 <= float(value) < 968.0 for value in channels["p_u"]), f"POINTCLOUD_PU:{kind}")
    require(all(0.0 <= float(value) < 608.0 for value in channels["p_v"]), f"POINTCLOUD_PV:{kind}")
    require(all(0.0 <= float(value) <= 1.0 for value in channels["quality"]), f"POINTCLOUD_QUALITY:{kind}")
    for quality, sigma_value in zip(channels["quality"], channels["sigma"]):
        expected = 1.0 / math.sqrt(max(0.05, float(quality)))
        require(abs(float(sigma_value) - expected) <= 2e-6, f"POINTCLOUD_SIGMA:{kind}")
    if kind == "base":
        require(all(0 <= value < 10_000_000 for value in ids), "BASE_ID_RANGE")
        require(all(value in {1, 2} for value in sources), "BASE_SOURCE")
        require(all(value == 0 for value in learned), "BASE_LEARNED")
    elif kind == "sidecar":
        require(all(1_000_000 <= value < 10_000_000 for value in ids), "SIDECAR_ID_RANGE")
        require(all(value == 20 for value in sources), "SIDECAR_SOURCE")
        require(all(value == 1 for value in learned), "SIDECAR_LEARNED")
    else:
        for feature_id, source, flag in zip(ids, sources, learned):
            if source in {1, 2}:
                require(0 <= feature_id < 10_000_000 and flag == 0, "MERGED_CLASSICAL_CONTRACT")
            elif source == 20:
                require(feature_id >= 10_000_000 and flag == 1, "MERGED_LEARNED_CONTRACT")
            else:
                raise AquaV2Error(f"MERGED_SOURCE:{source}")
    if kind == "sidecar" and camera is not None and count:
        # Recompute the pinhole+distortion normalization independently through
        # the pinned OpenCV API.  This catches a learned point/channel mismatch.
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        pixels = np.asarray(
            list(zip(channels["p_u"], channels["p_v"])), dtype=np.float64,
        ).reshape(-1, 1, 2)
        expected_xy = cv2.undistortPoints(pixels, camera["K"], camera["D"]).reshape(-1, 2)
        actual_xy = np.asarray([(point.x, point.y) for point in message.points], dtype=np.float64)
        require(float(np.max(np.abs(expected_xy - actual_xy))) <= 1e-6, "SIDECAR_NORMALIZED_XY")
    return {"channels": channels, "ids": ids, "sources": sources, "learned": learned}


def parse_selector_ids(raw: str, column: str, row_index: int) -> list[int]:
    if raw == "":
        return []
    fields = raw.split(";")
    require(
        all(re.fullmatch(r"(?:0|[1-9][0-9]*)", value) for value in fields),
        f"SELECTOR_ID_GRAMMAR:{row_index}:{column}:{raw!r}",
    )
    values = [int(value) for value in fields]
    require(values == sorted(set(values)), f"SELECTOR_ID_CANONICAL:{row_index}:{column}")
    require(all(1_000_000 <= value < 10_000_000 for value in values), f"SELECTOR_ID_RANGE:{row_index}:{column}")
    return values


TRIGGER_TOKEN_ORDER = (
    "degradation", "flat_regions", "low_grid_texture", "latched_optical",
    "low_base_tracks", "identity_churn", "low_base_grid", "forced_periodic",
    "seed_loss_rearm", "no_seed_retry",
)
TRIGGER_SINGLETONS = {
    "no_previous_image", "warmup_optical_latched", "warmup", "trigger_budget",
    "cooldown", "low_base_grid_only", "healthy",
}
TRIGGER_ALLOWED = set(TRIGGER_TOKEN_ORDER) | TRIGGER_SINGLETONS
EFFECTIVE_FORBIDDEN_TRIGGER_TOKENS = {
    "warmup_optical_latched", "warmup", "cooldown", "latched_optical",
    "forced_periodic", "seed_loss_rearm",
}


def validate_trigger_reason(raw: str, row_index: int) -> list[str]:
    require(raw != "", f"TRIGGER_REASON_EMPTY:{row_index}")
    tokens = raw.split("+")
    require(all(token in TRIGGER_ALLOWED for token in tokens), f"TRIGGER_TOKEN:{row_index}:{raw}")
    require(len(tokens) == len(set(tokens)), f"TRIGGER_TOKEN_DUPLICATE:{row_index}")
    if set(tokens) & TRIGGER_SINGLETONS:
        require(len(tokens) == 1, f"TRIGGER_SINGLETON_COMBINATION:{row_index}:{raw}")
    non_singleton = [token for token in tokens if token not in TRIGGER_SINGLETONS]
    expected_order = [token for token in TRIGGER_TOKEN_ORDER if token in non_singleton]
    require(non_singleton == expected_order, f"TRIGGER_TOKEN_ORDER:{row_index}:{raw}")
    require(not (set(tokens) & EFFECTIVE_FORBIDDEN_TRIGGER_TOKENS), f"TRIGGER_UNREACHABLE:{row_index}:{raw}")
    return tokens


def expected_trigger_reason(row: Mapping[str, str], row_index: int, previous_trigger_count: int) -> tuple[int, str]:
    if row_index == 0:
        return 0, "no_previous_image"
    if previous_trigger_count >= 3:
        return 0, "trigger_budget"
    reasons: list[str] = []
    if finite_number(row["image_degradation"], "image_degradation") >= 0.18:
        reasons.append("degradation")
    if finite_number(row["image_flat_region_ratio"], "image_flat") >= 0.10:
        reasons.append("flat_regions")
    if finite_number(row["image_grid_texture"], "image_grid_texture") <= 0.90:
        reasons.append("low_grid_texture")
    if exact_integer(row["base_tracks"], "base_tracks") <= 300:
        reasons.append("low_base_tracks")
    if (
        finite_number(row["base_dropout_ratio"], "dropout") >= 0.18
        and finite_number(row["base_long_track_ratio"], "long_track") <= 0.45
    ):
        reasons.append("identity_churn")
    grid = finite_number(row["base_grid_coverage"], "grid")
    if reasons and grid <= 0.80:
        reasons.append("low_base_grid")
    if not reasons and grid <= 0.80:
        return 0, "low_base_grid_only"
    triggered = int(bool(reasons))
    reason = "+".join(reasons) if reasons else "healthy"
    if triggered and exact_integer(row["added_seeds"], "added_seeds") == 0:
        reason += "+no_seed_retry"
    return triggered, reason


def load_camera_contract(path: Path) -> dict[str, Any]:
    require_expected(path, (357, CAMERA_YAML_SHA256))
    # Parse the frozen small OpenCV YAML without relying on the producer's
    # loader.  Only the exact pinned values are accepted.
    text = path.read_text(encoding="utf-8")
    expected = {
        "fx": 543.3327734182214, "fy": 542.398772982566,
        "cx": 489.02536042247897, "cy": 305.38727712002805,
        "k1": -0.1255945656257394, "k2": 0.053221287232781606,
        "p1": 9.94070021080493e-05, "p2": 9.550660927242349e-05,
    }
    for key, value in expected.items():
        require(re.search(rf"(?:^|\s){re.escape(key)}:\s*{re.escape(str(value))}(?:\s|$)", text, re.MULTILINE) is not None, f"CAMERA_VALUE:{key}")
    import numpy as np  # type: ignore
    return {
        "K": np.asarray(
            [[expected["fx"], 0.0, expected["cx"]], [0.0, expected["fy"], expected["cy"]], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        ),
        "D": np.asarray([expected["k1"], expected["k2"], expected["p1"], expected["p2"]], dtype=np.float64),
    }


def _header_sha(path: Path) -> str:
    with path.open("rb") as stream:
        first = stream.readline().rstrip(b"\r\n")
    return hashlib.sha256(first).hexdigest()


def audit_aqua_artifacts(
    *, base_path: Path, merged_path: Path, sidecar_path: Path, stats_path: Path,
    camera_path: Path, image_bag_path: Path, expected_features: int, expected_imu: int,
    expected_gt: int, expected_first_ns: int, expected_last_ns: int,
    prefix_features: int,
) -> dict[str, Any]:
    rosbag = rosbag_module()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from cv_bridge import CvBridge  # type: ignore
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    from uw_frontend.quality.image_quality import score_image_quality

    bridge = CvBridge()
    camera = load_camera_contract(camera_path)
    for path in (base_path, merged_path, sidecar_path, stats_path, image_bag_path):
        require(path.is_file() and not path.is_symlink(), f"AQUA_OUTPUT_NOT_REGULAR:{path}")
    require(_header_sha(stats_path) == STATS_HEADER_SHA256, "STATS_HEADER_SHA")
    with stats_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == STATS_COLUMNS, "STATS_HEADER_COLUMNS")
        rows = list(reader)
    require(len(rows) == expected_features, f"STATS_ROW_COUNT:{len(rows)}")
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), "STATS_ROW_WIDTH")

    with rosbag.Bag(str(base_path), "r") as bag:
        base_topics = bag.get_type_and_topic_info().topics
        require(
            {name: int(info.message_count) for name, info in base_topics.items()}
            == {FEATURE_TOPIC: expected_features, IMU_TOPIC: expected_imu, GT_TOPIC: expected_gt},
            "BASE_TOPIC_COUNTS",
        )
    with rosbag.Bag(str(merged_path), "r") as bag:
        merged_topics = bag.get_type_and_topic_info().topics
        require(
            {name: int(info.message_count) for name, info in merged_topics.items()}
            == {FEATURE_TOPIC: expected_features, IMU_TOPIC: expected_imu, GT_TOPIC: expected_gt},
            "MERGED_TOPIC_COUNTS",
        )
    with rosbag.Bag(str(sidecar_path), "r") as bag:
        side_topics = bag.get_type_and_topic_info().topics
        require(
            {name: int(info.message_count) for name, info in side_topics.items()}
            == {SIDECAR_TOPIC: expected_features},
            "SIDECAR_TOPIC_COUNTS",
        )

    a10 = a10_helper()
    imu_equal = a10.validate_rosbag_topic_equal(merged_path, base_path, IMU_TOPIC, expected_imu)
    gt_equal = a10.validate_rosbag_topic_equal(merged_path, base_path, GT_TOPIC, expected_gt)

    selector_evaluated: set[int] = set()
    selector_selected: set[int] = set()
    selector_lineages: dict[int, dict[str, Any]] = {}
    previous_side_ids: set[int] = set()
    reconstructed_seed_ages: dict[int, int] = {}
    next_raw_id = 1_000_000
    previous_base_ids: set[int] = set()
    base_id_ages: dict[int, int] = {}
    remap: dict[int, int] = {}
    bindings: list[dict[str, Any]] = []
    sidecar_total = 0
    injected_total = 0
    affected_frames = 0
    prefix_injected = 0
    trigger_total = 0
    seed_total = 0
    previous_active = 0
    previous_trigger_count = 0
    first_stamp: int | None = None
    last_stamp: int | None = None

    sentinel = object()
    with rosbag.Bag(str(base_path), "r") as base_bag, \
            rosbag.Bag(str(merged_path), "r") as merged_bag, \
            rosbag.Bag(str(sidecar_path), "r") as sidecar_bag, \
            rosbag.Bag(str(image_bag_path), "r") as image_bag:
        base_iter = base_bag.read_messages(topics=[FEATURE_TOPIC])
        merged_iter = merged_bag.read_messages(topics=[FEATURE_TOPIC])
        side_iter = sidecar_bag.read_messages(topics=[SIDECAR_TOPIC])
        image_iter = image_bag.read_messages(topics=[CAMERA_TOPIC])
        image_item: Any = next(image_iter, sentinel)
        combined = itertools.zip_longest(base_iter, merged_iter, side_iter, rows, fillvalue=sentinel)
        for index, items in enumerate(combined):
            base_item, merged_item, side_item, row = items
            require(all(item is not sentinel for item in items), f"AQUA_LENGTH_MISMATCH:{index}")
            base_topic, base, base_record = base_item
            merged_topic, merged, merged_record = merged_item
            side_topic, sidecar, side_record = side_item
            require(base_topic == merged_topic == FEATURE_TOPIC and side_topic == SIDECAR_TOPIC, f"AQUA_TOPIC:{index}")
            stamp = ros_ns(base.header.stamp)
            require(
                base.header == merged.header == sidecar.header
                and ros_ns(base_record) == ros_ns(merged_record) == ros_ns(side_record) == stamp,
                f"AQUA_HEADER_BINDING:{index}",
            )
            if first_stamp is None:
                first_stamp = stamp
            require(last_stamp is None or stamp > last_stamp, f"AQUA_TIMELINE:{index}")
            last_stamp = stamp

            base_seconds = float(base.header.stamp.to_sec())
            while image_item is not sentinel:
                _image_topic, candidate_image, candidate_record = image_item
                candidate_seconds = (
                    float(candidate_image.header.stamp.to_sec())
                    if hasattr(candidate_image, "header")
                    and candidate_image.header.stamp.to_sec() > 0.0
                    else float(candidate_record.to_sec())
                )
                if candidate_seconds < base_seconds - 0.02:
                    image_item = next(image_iter, sentinel)
                    continue
                break
            require(image_item is not sentinel, f"AQUA_IMAGE_EXHAUSTED:{index}")
            image_topic, image_message, image_record = image_item
            require(image_topic == CAMERA_TOPIC, f"AQUA_IMAGE_TOPIC:{index}")
            image_seconds = (
                float(image_message.header.stamp.to_sec())
                if hasattr(image_message, "header") and image_message.header.stamp.to_sec() > 0.0
                else float(image_record.to_sec())
            )
            image_delta = abs(base_seconds - image_seconds)
            require(image_delta <= 0.02, f"AQUA_IMAGE_BINDING:{index}:{image_delta}")
            raw_gray = np.asarray(
                bridge.compressed_imgmsg_to_cv2(image_message, desired_encoding="mono8")
                if getattr(image_message, "_type", "") == "sensor_msgs/CompressedImage"
                else bridge.imgmsg_to_cv2(image_message, desired_encoding="mono8"),
                dtype=np.uint8,
            )
            raw_height, raw_width = raw_gray.shape[:2]
            processed = cv2.resize(
                raw_gray,
                (max(8, int(round(raw_width * 0.5))), max(8, int(round(raw_height * 0.5)))),
                interpolation=cv2.INTER_AREA,
            )
            pre_quality = score_image_quality(processed)
            if (
                pre_quality.contrast_score < 0.72
                or pre_quality.grid_texture_score < 0.58
                or pre_quality.illumination_nonuniformity > 0.18
                or pre_quality.degradation_score > 0.42
            ):
                processed = cv2.createCLAHE(
                    clipLimit=2.0, tileGridSize=(8, 8),
                ).apply(processed)
            image_quality = score_image_quality(processed)
            image_item = next(image_iter, sentinel)
            base_contract = validate_pointcloud(base, base_record, kind="base")
            merged_contract = validate_pointcloud(merged, merged_record, kind="merged")
            side_contract = validate_pointcloud(sidecar, side_record, kind="sidecar", camera=camera)
            base_channels = base_contract["channels"]
            merged_channels = merged_contract["channels"]
            side_channels = side_contract["channels"]
            require(len(merged.points) - len(base.points) in {0, 1}, f"AQUA_EXTENSION_COUNT:{index}")
            require(list(base.points) == list(merged.points[: len(base.points)]), f"AQUA_BASE_POINT_PREFIX:{index}")
            for name in CHANNELS:
                require(
                    tuple(base_channels[name]) == tuple(merged_channels[name][: len(base.points)]),
                    f"AQUA_BASE_CHANNEL_PREFIX:{index}:{name}",
                )

            require(exact_integer(row["frame_index"], "frame_index") == index, f"STATS_FRAME:{index}")
            require(exact_integer(row["selector_frame_index"], "selector_frame_index") == index, f"STATS_SELECTOR_FRAME:{index}")
            exact_stamp = str(float(base.header.stamp.to_sec()))
            require(row["stamp"] == row["selector_stamp"] == exact_stamp, f"STATS_STAMP_SPELLING:{index}:{row['stamp']!r}:{exact_stamp!r}")
            require(row["base_tracks"] == "350", f"STATS_BASE_TRACKS:{index}")
            current_base_ids = set(base_contract["ids"])
            expected_dropout = (
                1.0 - len(current_base_ids & previous_base_ids) / max(1, len(previous_base_ids))
                if previous_base_ids else 0.0
            )
            base_id_ages = {
                feature_id: base_id_ages.get(feature_id, 0) + 1
                for feature_id in current_base_ids
            }
            expected_long_ratio = (
                sum(age >= 5 for age in base_id_ages.values())
                / max(1, len(current_base_ids))
            )
            occupied_cells = {
                (
                    min(5, max(0, int(float(v) / max(1, raw_height) * 6))),
                    min(5, max(0, int(float(u) / max(1, raw_width) * 6))),
                )
                for u, v in zip(base_channels["p_u"], base_channels["p_v"])
            }
            expected_grid = len(occupied_cells) / 36.0
            require(len(current_base_ids) == 350, f"BASE_HEALTH_TRACK_COUNT:{index}")
            numeric_ranges = {
                "base_grid_coverage": (0.0, 1.0), "base_dropout_ratio": (0.0, 1.0),
                "base_long_track_ratio": (0.0, 1.0), "image_degradation": (0.0, 1.0),
                "image_flat_region_ratio": (0.0, 1.0), "image_grid_texture": (0.0, 1.0),
                "velocity_contract_scale": (0.2, 2.0), "image_match_delta_s": (0.0, 0.02),
            }
            for name, (low, high) in numeric_ranges.items():
                value = finite_number(row[name], f"{index}:{name}")
                require(low <= value <= high, f"STATS_RANGE:{index}:{name}:{value}")
            independently_recomputed = {
                "base_grid_coverage": expected_grid,
                "base_dropout_ratio": expected_dropout,
                "base_long_track_ratio": expected_long_ratio,
                "image_degradation": float(image_quality.degradation_score),
                "image_flat_region_ratio": float(image_quality.flat_region_ratio),
                "image_grid_texture": float(image_quality.grid_texture_score),
                "image_match_delta_s": image_delta,
            }
            for name, expected_value in independently_recomputed.items():
                require(
                    finite_number(row[name], f"{index}:{name}:recomputed") == expected_value,
                    f"STATS_RECOMPUTED:{index}:{name}",
                )
            previous_base_ids = current_base_ids
            for name in ("match_ms", "processing_ms"):
                require(finite_number(row[name], f"{index}:{name}") >= 0.0, f"STATS_NEGATIVE:{index}:{name}")
            integer_limits = {
                "triggered": (0, 1), "trigger_count": (0, 3), "match_count": (0, 2_048),
                "added_seeds": (0, 50), "tracked_before": (0, 72),
                "tracked_after": (0, 72), "active_seeds": (0, 72),
                "max_seed_age": (0, expected_features), "selector_injected_observations": (0, 1),
            }
            parsed_ints: dict[str, int] = {}
            for name, (low, high) in integer_limits.items():
                value = exact_integer(row[name], f"{index}:{name}")
                require(value >= low and (high is None or value <= high), f"STATS_INTEGER_RANGE:{index}:{name}:{value}")
                parsed_ints[name] = value
            validate_trigger_reason(row["trigger_reason"], index)
            expected_trigger, expected_reason = expected_trigger_reason(row, index, previous_trigger_count)
            require(parsed_ints["triggered"] == expected_trigger, f"TRIGGER_DECISION:{index}")
            require(row["trigger_reason"] == expected_reason, f"TRIGGER_REASON_DECISION:{index}:{row['trigger_reason']}:{expected_reason}")
            if not parsed_ints["triggered"]:
                require(parsed_ints["match_count"] == parsed_ints["added_seeds"] == 0, f"TRIGGER_FALSE_ACTION:{index}")
            require(
                parsed_ints["match_count"] >= parsed_ints["added_seeds"],
                f"MATCH_SEED_ACCOUNTING:{index}",
            )
            if parsed_ints["added_seeds"]:
                require(parsed_ints["triggered"] == 1, f"SEEDS_WITHOUT_TRIGGER:{index}")
            expected_trigger_count = previous_trigger_count + int(parsed_ints["triggered"] == 1 and parsed_ints["added_seeds"] > 0)
            require(parsed_ints["trigger_count"] == expected_trigger_count, f"TRIGGER_COUNT_TRANSITION:{index}")
            require(parsed_ints["tracked_before"] == (0 if index == 0 else previous_active), f"TRACKED_BEFORE_TRANSITION:{index}")
            require(
                parsed_ints["active_seeds"] == parsed_ints["tracked_after"] + parsed_ints["added_seeds"],
                f"ACTIVE_SEED_ACCOUNTING:{index}",
            )
            require(len(sidecar.points) == parsed_ints["active_seeds"], f"SIDECAR_ACTIVE_COUNT:{index}")

            selector_columns = {
                name: parse_selector_ids(row[name], name, index)
                for name in (
                    "selector_discovered_ids", "selector_evaluated_ids",
                    "selector_activated_ids", "selector_retired_ids",
                    "selector_active_ids", "selector_selected_ids",
                )
            }
            side_ids = list(side_contract["ids"])
            require(side_ids == sorted(side_ids), f"SIDECAR_ID_ORDER:{index}")
            discovered = selector_columns["selector_discovered_ids"]
            evaluated = selector_columns["selector_evaluated_ids"]
            activated = selector_columns["selector_activated_ids"]
            retired = selector_columns["selector_retired_ids"]
            active = selector_columns["selector_active_ids"]
            selected = selector_columns["selector_selected_ids"]
            expected_discovered: list[int] = []
            for raw_id in side_ids:
                if raw_id not in selector_lineages:
                    selector_lineages[raw_id] = {
                        "count": 0, "distances": [], "motion_ratios": [],
                        "score": None, "motion_ratio": None,
                    }
                    expected_discovered.append(raw_id)
            require(discovered == expected_discovered, f"SELECTOR_DISCOVERED_BINDING:{index}")
            require(len(discovered) == parsed_ints["added_seeds"], f"SELECTOR_DISCOVERED_SEED_COUNT:{index}")
            current_side_ids = set(side_ids)
            require(
                current_side_ids - set(discovered) <= previous_side_ids,
                f"SIDECAR_LINEAGE_REVIVAL:{index}",
            )
            require(
                parsed_ints["tracked_after"] == len(current_side_ids & previous_side_ids),
                f"TRACKED_AFTER_ID_BINDING:{index}",
            )
            expected_new_ids = list(range(next_raw_id, next_raw_id + parsed_ints["added_seeds"]))
            require(discovered == expected_new_ids, f"SIDECAR_NEW_ID_SEQUENCE:{index}")
            next_raw_id += parsed_ints["added_seeds"]
            reconstructed_seed_ages = {
                raw_id: reconstructed_seed_ages[raw_id] + 1
                if raw_id in previous_side_ids else 1
                for raw_id in current_side_ids
            }
            require(
                parsed_ints["max_seed_age"]
                == max(reconstructed_seed_ages.values(), default=0),
                f"MAX_SEED_AGE_BINDING:{index}",
            )

            base_pixels = list(zip(base_channels["p_u"], base_channels["p_v"]))
            base_speeds = [
                math.hypot(float(vx), float(vy))
                for vx, vy in zip(base_channels["velocity_x"], base_channels["velocity_y"])
            ]
            base_speed = float(statistics.median(base_speeds)) if base_speeds else None
            for raw_id, u, v, vx, vy in zip(
                side_ids, side_channels["p_u"], side_channels["p_v"],
                side_channels["velocity_x"], side_channels["velocity_y"],
            ):
                state = selector_lineages[raw_id]
                state["count"] += 1
                if len(state["distances"]) < 5:
                    state["distances"].append(min(
                        math.hypot(float(u) - float(bu), float(v) - float(bv))
                        for bu, bv in base_pixels
                    ))
                if len(state["motion_ratios"]) < 5 and base_speed is not None and base_speed > 1e-9:
                    state["motion_ratios"].append(
                        math.hypot(float(vx), float(vy)) / base_speed
                    )

            expected_evaluated: list[int] = []
            novelty_ready: list[int] = []
            motion_ok: dict[int, bool] = {}
            for raw_id in sorted(set(side_ids)):
                if raw_id in selector_evaluated:
                    continue
                state = selector_lineages[raw_id]
                if (
                    state["count"] < 10
                    or len(state["distances"]) < 5
                    or len(state["motion_ratios"]) < 5
                ):
                    continue
                score = float(statistics.median(state["distances"][:5]))
                ratio = float(statistics.median(state["motion_ratios"][:5]))
                state["score"] = score
                state["motion_ratio"] = ratio
                expected_evaluated.append(raw_id)
                motion_ok[raw_id] = 0.6 <= ratio <= 1.5
                if score >= 40.0:
                    novelty_ready.append(raw_id)
            require(evaluated == expected_evaluated, f"SELECTOR_EVALUATED_DECISION:{index}")
            remaining = max(0, 1 - len(selector_selected))
            ranked = sorted(
                novelty_ready,
                key=lambda raw_id: (-float(selector_lineages[raw_id]["score"]), raw_id),
            )
            expected_activated = [
                raw_id for raw_id in ranked[:remaining] if motion_ok[raw_id]
            ]
            require(activated == expected_activated, f"SELECTOR_ACTIVATED_DECISION:{index}")
            require(retired == [], f"SELECTOR_RETIRED_WITH_REARM_ZERO:{index}")
            require(
                set(selected) == selector_selected | set(expected_activated),
                f"SELECTOR_SELECTED_TRANSITION:{index}",
            )
            require(active == selected and len(selected) <= 1, f"SELECTOR_ACTIVE_SELECTED:{index}")
            expected_injected = sum(value in set(selected) for value in side_ids)
            require(parsed_ints["selector_injected_observations"] == expected_injected, f"SELECTOR_INJECTION_COUNT:{index}")
            added = len(merged.points) - len(base.points)
            require(added == expected_injected, f"THREE_WAY_ACTION_BINDING:{index}")

            if added:
                raw_selected = next(value for value in side_ids if value in set(selected))
                side_index = side_ids.index(raw_selected)
                learned_index = len(merged.points) - 1
                mapped = integral_float(merged_channels["id"][learned_index], "merged_remap")
                expected_mapped = remap.setdefault(raw_selected, 10_000_000 + len(remap))
                require(mapped == expected_mapped == 10_000_000, f"REMAP_STABILITY:{index}:{mapped}")
                require(merged.points[learned_index] == sidecar.points[side_index], f"LEARNED_SUFFIX_POINT:{index}")
                for name in CHANNELS:
                    if name == "id":
                        continue
                    require(
                        float(merged_channels[name][learned_index]) == float(side_channels[name][side_index]),
                        f"LEARNED_SUFFIX_CHANNEL:{index}:{name}",
                    )
                affected_frames += 1
                injected_total += 1
                if index < prefix_features:
                    prefix_injected += 1
            sidecar_total += len(sidecar.points)
            trigger_total += parsed_ints["triggered"]
            seed_total += parsed_ints["added_seeds"]
            bindings.append({"frame_index": index, "stamp": exact_stamp, "injected_observations": added})
            selector_evaluated.update(evaluated)
            selector_selected = set(selected)
            previous_side_ids = current_side_ids
            previous_active = parsed_ints["active_seeds"]
            previous_trigger_count = parsed_ints["trigger_count"]

    require(first_stamp == expected_first_ns and last_stamp == expected_last_ns, "AQUA_FEATURE_ENDPOINTS")
    require(len(bindings) == expected_features, "AQUA_FEATURE_COUNT")
    require(expected_features - prefix_features == SCORE_FEATURE_COUNT if expected_features == FEATURE_COUNT else True, "AQUA_SCORE_PARTITION")
    return {
        "status": "PASS_STRICT_AQUAFE_ARTIFACT_AUDIT",
        "feature_messages": len(bindings), "first_stamp_ns": first_stamp,
        "last_stamp_ns": last_stamp, "sidecar_messages": len(bindings),
        "sidecar_total_points": sidecar_total,
        "action_binding_sha256": compact_sha(bindings),
        "learned_action": {
            "full_observations": injected_total,
            "full_affected_frames": affected_frames,
            "prefix_observations": prefix_injected,
            "score_observations": injected_total - prefix_injected,
            "remapped_lineage_ids": sorted(remap.values()),
            "selector_raw_ids": sorted(remap),
            "triggered_frames": trigger_total, "added_seeds": seed_total,
        },
        "copied_streams": {"imu": imu_equal, "ground_truth": gt_equal},
        "stats_rows": len(rows), "stats_columns": len(STATS_COLUMNS),
        "stats_header_sha256": _header_sha(stats_path),
    }


def audit_raw_and_klt() -> dict[str, Any]:
    """Independently validate the accepted KLT dependency before XFeat."""
    rosbag = rosbag_module()
    require(KLT_DIR.is_dir() and not KLT_DIR.is_symlink(), "KLT_ACCEPTED_DIR_MISSING")
    require_expected(CAMERA_CONFIG, (357, CAMERA_YAML_SHA256))
    cameras: list[int] = []
    raw_counts = {CAMERA_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    with rosbag.Bag(str(RAW_BAG), "r") as bag:
        for topic, message, record in bag.read_messages(topics=list(raw_counts)):
            require(hasattr(message, "header"), f"RAW_HEADER_MISSING:{topic}")
            require(ros_ns(message.header.stamp) == ros_ns(record), f"RAW_HEADER_RECORD:{topic}")
            raw_counts[topic] += 1
            if topic == CAMERA_TOPIC:
                cameras.append(ros_ns(record))
    require(raw_counts == {CAMERA_TOPIC: CAMERA_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT}, "RAW_COUNTS")
    require(all(right > left for left, right in zip(cameras, cameras[1:])), "RAW_CAMERA_TIMELINE")
    expected_stamps = cameras[1:4400:2]
    require(
        len(expected_stamps) == FEATURE_COUNT
        and expected_stamps[0] == FEATURE_FIRST_NS
        and expected_stamps[PREFIX_FEATURE_COUNT] == SCORE_FEATURE_FIRST_NS
        and expected_stamps[-1] == FEATURE_LAST_NS,
        "RAW_FEATURE_BINDING",
    )
    feature_stamps: list[int] = []
    with rosbag.Bag(str(BASE_BAG), "r") as bag:
        info = bag.get_type_and_topic_info().topics
        require(
            {name: int(value.message_count) for name, value in info.items()}
            == {FEATURE_TOPIC: FEATURE_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT},
            "KLT_TOPIC_COUNTS",
        )
        for _topic, message, record in bag.read_messages(topics=[FEATURE_TOPIC]):
            validate_pointcloud(message, record, kind="base")
            feature_stamps.append(ros_ns(record))
    require(feature_stamps == expected_stamps, "KLT_RAW_ODD_FRAME_BINDING")
    a10 = a10_helper()
    imu_equal = a10.validate_rosbag_topic_equal(BASE_BAG, RAW_BAG, IMU_TOPIC, IMU_COUNT)
    gt_equal = a10.validate_rosbag_topic_equal(BASE_BAG, RAW_BAG, GT_TOPIC, GT_COUNT)
    metrics = KLT_DIR / "frontend_metrics.csv"
    require(metrics.is_file() and not metrics.is_symlink(), "KLT_METRICS_MISSING")
    require(_header_sha(metrics) == KLT_HEADER_SHA256, "KLT_METRICS_HEADER")
    with metrics.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and len(reader.fieldnames) == 141, "KLT_METRICS_COLUMNS")
        rows = list(reader)
    require(len(rows) == FEATURE_COUNT, "KLT_METRICS_ROWS")
    zero_columns = (
        "learned_candidate_count", "learned_confirmed_count",
        "learned_confirmed_xfeat_count", "exported_learned_features",
        "exported_xfeat_features", "exported_loftr_features",
        "exported_sp_lg_features", "source_provenance_learned_count",
        "source_provenance_xfeat_count",
    )
    for index, (row, stamp) in enumerate(zip(rows, feature_stamps)):
        seconds, nanoseconds = divmod(stamp, 1_000_000_000)
        expected_csv_stamp = f"{seconds + nanoseconds / 1_000_000_000.0:.9f}"
        require(int(row["frame_index"]) == 1 + 2 * index, f"KLT_METRICS_FRAME:{index}")
        require(int(row["selected_feature_index"]) == index, f"KLT_METRICS_SELECTED:{index}")
        require(row["timestamp"] == expected_csv_stamp, f"KLT_METRICS_STAMP:{index}")
        require(row["num_features"] == row["exported_features"] == row["classical_track_count"] == "350", f"KLT_METRICS_COUNT:{index}")
        require(all(float(row[name]) == 0.0 for name in zero_columns), f"KLT_METRICS_LEARNED:{index}")
    return {
        "status": "PASS_KLT_DEPENDENCY_ARTIFACT_AUDIT",
        "raw_counts": raw_counts, "feature_messages": len(feature_stamps),
        "first_stamp_ns": feature_stamps[0], "last_stamp_ns": feature_stamps[-1],
        "score_first_stamp_ns": feature_stamps[PREFIX_FEATURE_COUNT],
        "imu_equal": imu_equal, "ground_truth_equal": gt_equal,
        "metrics_rows": len(rows), "metrics_columns": len(reader.fieldnames or []),
    }


KLT_LOCK_FILES = {
    "klt_features": BASE_BAG,
    "klt_metrics": KLT_DIR / "frontend_metrics.csv",
    "klt_camera": CAMERA_CONFIG,
    "klt_claim": KLT_DIR / "process_start_claim_v1.json",
    "klt_receipt": KLT_DIR / "formal_run_receipt_v1.json",
    "klt_log": KLT_DIR / "supervisor_process.log",
}


def verify_klt_strength_addendum() -> dict[str, Any]:
    addendum, snapshot = load_json_regular(KLT_STRENGTH_ADDENDUM)
    require(
        set(addendum) == KLT_ADDENDUM_TOP_LEVEL_KEYS,
        f"KLT_ADDENDUM_TOP_LEVEL_KEYS:{sorted(set(addendum)^KLT_ADDENDUM_TOP_LEVEL_KEYS)}",
    )
    require(
        addendum.get("schema_version")
        == "aqua-fe-a09-samehistory-warmstart-klt-execution-strength-addendum-v1",
        "KLT_ADDENDUM_SCHEMA",
    )
    require(
        addendum.get("status") == "PASS_POSTHOC_KLT_EXECUTION_STRENGTH_AUDIT",
        "KLT_ADDENDUM_STATUS",
    )
    observed_at = addendum.get("observed_at_utc")
    require(isinstance(observed_at, str), "KLT_ADDENDUM_OBSERVED_AT")
    try:
        observed_time = datetime.fromisoformat(observed_at)
    except ValueError as error:
        raise AquaV2Error("KLT_ADDENDUM_OBSERVED_AT_GRAMMAR") from error
    require(
        observed_time.utcoffset() == timezone.utc.utcoffset(observed_time),
        "KLT_ADDENDUM_OBSERVED_AT_NOT_UTC",
    )
    require(addendum.get("limitations") == KLT_ADDENDUM_LIMITATIONS, "KLT_ADDENDUM_LIMITATIONS")
    require(
        addendum.get("claim_boundary") == KLT_ADDENDUM_CLAIM_BOUNDARY,
        "KLT_ADDENDUM_CLAIM_BOUNDARY",
    )
    auditor = public_identity(snapshot_file(KLT_STRENGTH_BUILDER))
    require(addendum.get("auditor_identity") == auditor, "KLT_ADDENDUM_AUDITOR_IDENTITY")
    process_tree = addendum.get("posthoc_process_tree")
    require(isinstance(process_tree, dict), "KLT_ADDENDUM_PROCESS_TREE")
    require(
        set(process_tree) == {
            "status", "evidence_scope", "observed_process_group_id",
            "observed_process_identifiers", "process_group_empty",
            "owned_descendants_empty", "owned_descendants_interpretation",
            "observed_process_markers", "identifier_provenance",
            "identifier_provenance_is_original_receipt_bound",
            "matching_processes",
        },
        "KLT_ADDENDUM_PROCESS_TREE_KEYS",
    )
    require(
        process_tree.get("observed_process_group_id") == KLT_POSTHOC_EXPECTED_PGID
        and process_tree.get("observed_process_identifiers")
        == KLT_POSTHOC_EXPECTED_IDENTIFIERS,
        "KLT_ADDENDUM_PROCESS_IDENTIFIERS",
    )
    require(
        process_tree.get("observed_process_markers") == KLT_POSTHOC_EXPECTED_MARKERS
        and process_tree.get("identifier_provenance")
        == KLT_POSTHOC_IDENTIFIER_PROVENANCE
        and process_tree.get("identifier_provenance_is_original_receipt_bound")
        is False
        and process_tree.get("matching_processes") == []
        and process_tree.get("owned_descendants_interpretation")
        == KLT_POSTHOC_DESCENDANT_INTERPRETATION,
        "KLT_ADDENDUM_PROCESS_MARKERS",
    )
    require(
        process_tree.get("status") == "PASS_POSTHOC_EMPTY_SNAPSHOT"
        and process_tree.get("process_group_empty") is True
        and process_tree.get("owned_descendants_empty") is True
        and process_tree.get("evidence_scope")
        == "POSTHOC_SNAPSHOT_NOT_CONTINUOUS_OWNERSHIP_PROOF",
        "KLT_ADDENDUM_PROCESS_TREE_STRENGTH",
    )

    canonical_info = KLT_DIR.lstat()
    require(stat.S_ISDIR(canonical_info.st_mode), "KLT_ADDENDUM_CANONICAL_NOT_REAL_DIR")
    workspace_info = KLT_WORKSPACE.lstat()
    require(stat.S_ISLNK(workspace_info.st_mode), "KLT_ADDENDUM_WORKSPACE_NOT_SYMLINK")
    workspace_target = os.readlink(KLT_WORKSPACE)
    require(workspace_target == str(KLT_DIR), f"KLT_ADDENDUM_WORKSPACE_TARGET:{workspace_target}")
    workspace_target_info = KLT_WORKSPACE.stat()
    require(
        (int(workspace_target_info.st_dev), int(workspace_target_info.st_ino))
        == (int(canonical_info.st_dev), int(canonical_info.st_ino)),
        "KLT_ADDENDUM_WORKSPACE_INODE",
    )
    path_state = addendum.get("path_state")
    require(isinstance(path_state, dict), "KLT_ADDENDUM_PATH_STATE")
    require(path_state.get("canonical") == {
        "path": str(KLT_DIR), "is_real_directory": True,
        "device": int(canonical_info.st_dev), "inode": int(canonical_info.st_ino),
    }, "KLT_ADDENDUM_CANONICAL_BINDING")
    require(path_state.get("workspace") == {
        "path": str(KLT_WORKSPACE), "is_symlink": True, "target": str(KLT_DIR),
        "resolves_canonical_inode": True,
    }, "KLT_ADDENDUM_WORKSPACE_BINDING")

    bindings = addendum.get("bindings")
    require(isinstance(bindings, dict), "KLT_ADDENDUM_BINDINGS")
    require(set(bindings) == set(KLT_LOCK_FILES), "KLT_ADDENDUM_BINDING_KEYS")
    current: dict[str, dict[str, Any]] = {}
    for key, path in KLT_LOCK_FILES.items():
        actual = snapshot_file(path)
        public = public_identity(actual)
        require(bindings.get(key) == public, f"KLT_ADDENDUM_FILE_BINDING:{key}")
        current[key] = public
    rehash = addendum.get("postcommit_external_rehash")
    require(
        isinstance(rehash, dict)
        and rehash.get("canonical_is_real_directory") is True
        and rehash.get("workspace_resolves_canonical_inode") is True
        and rehash.get("all_six_rehashed_after_commit") is True
        and rehash.get("receipt_output_binding_equal") is True
        and rehash.get("bindings_sha256") == compact_sha(current),
        "KLT_ADDENDUM_POSTCOMMIT_REHASH",
    )
    return {
        "status": "PASS_KLT_EXECUTION_STRENGTH_ADDENDUM",
        "addendum": snapshot,
        "limitations": KLT_ADDENDUM_LIMITATIONS,
        "posthoc_process_tree": process_tree,
        "bindings_sha256": compact_sha(current),
    }


def load_json_regular(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    snap = snapshot_file(path)
    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"JSON_DUPLICATE_KEY:{path}:{key}")
            result[key] = value
        return result

    def finite_json_float(raw: str) -> float:
        value = float(raw)
        require(math.isfinite(value), f"JSON_NONFINITE_FLOAT:{path}:{raw}")
        return value

    def reject_json_constant(raw: str) -> Any:
        raise AquaV2Error(f"JSON_NONSTANDARD_CONSTANT:{path}:{raw}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=object_without_duplicates,
            parse_float=finite_json_float,
            parse_constant=reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AquaV2Error(f"JSON_PARSE:{path}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT:{path}")
    require(snapshot_file(path) == snap, f"JSON_CHANGED_DURING_PARSE:{path}")
    return value, snap


def verify_klt_receipt() -> dict[str, Any]:
    receipt, receipt_snapshot = load_json_regular(KLT_LOCK_FILES["klt_receipt"])
    require(receipt.get("schema_version") == "aqua-fe-a09-samehistory-warmstart-frontend-receipt-v1", "KLT_RECEIPT_SCHEMA")
    require(receipt.get("status") == "PASS_FRONTEND_STAGE_ACCEPTED" and receipt.get("stage") == "klt", "KLT_RECEIPT_STATUS")
    require(receipt.get("terminal_process", {}).get("return_code") == 0, "KLT_RECEIPT_RC")
    require(receipt.get("terminal_process", {}).get("single_popen") is True, "KLT_RECEIPT_POPEN")
    require(receipt.get("artifact_audit", {}).get("status") == "PASS_KLT_FRONTEND_AUDIT", "KLT_RECEIPT_AUDIT")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict), "KLT_RECEIPT_OUTPUTS")
    for name in ("features.bag", "frontend_metrics.csv", "aqualoc_archaeo09_pinhole.yaml", "supervisor_process.log"):
        actual = snapshot_file(KLT_DIR / name)
        recorded = outputs.get(name)
        require(
            isinstance(recorded, dict)
            and recorded.get("size_bytes") == actual["size_bytes"]
            and recorded.get("sha256") == actual["sha256"],
            f"KLT_RECEIPT_OUTPUT_BINDING:{name}",
        )
    return {"receipt": receipt_snapshot, "status": "PASS_KLT_RECEIPT_BINDING"}


def verify_lock(lock_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    require(lock_path.absolute() == DEFAULT_LOCK, f"NONCANONICAL_LOCK_PATH:{lock_path}")
    lock, lock_snapshot = load_json_regular(lock_path)
    require(set(lock) == LOCK_TOP_LEVEL_KEYS, f"LOCK_TOP_LEVEL_KEYS:{sorted(set(lock)^LOCK_TOP_LEVEL_KEYS)}")
    require(lock.get("schema_version") == LOCK_SCHEMA, "LOCK_SCHEMA")
    require(lock.get("status") == "FROZEN_BEFORE_AQUAFE_POPEN", "LOCK_STATUS")
    require(lock.get("stage") == "aquafe", "LOCK_STAGE")
    created_at = lock.get("created_at_utc")
    require(
        isinstance(created_at, str)
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00", created_at)
        is not None,
        "LOCK_CREATED_AT_GRAMMAR",
    )
    require(lock.get("argv") == build_argv(), "LOCK_ARGV")
    require(lock.get("argv_sha256") == compact_sha(build_argv()), "LOCK_ARGV_SHA")
    env = effective_environment()
    require(lock.get("effective_environment") == env, "LOCK_ENV")
    require(lock.get("effective_environment_sha256") == compact_sha(env), "LOCK_ENV_SHA")
    require(lock.get("execution_policy") == LOCK_EXECUTION_POLICY, "LOCK_EXECUTION_POLICY")
    require(lock.get("claim_boundary") == LOCK_CLAIM_BOUNDARY, "LOCK_CLAIM_BOUNDARY")
    dependency = lock.get("dependency_acceptance")
    require(
        isinstance(dependency, dict)
        and set(dependency) == {
            "klt_receipt", "klt_execution_strength_addendum", "klt_artifact_audit",
        },
        "LOCK_DEPENDENCY_ACCEPTANCE_KEYS",
    )
    require(
        dependency["klt_receipt"].get("status") == "PASS_KLT_RECEIPT_BINDING"
        and dependency["klt_execution_strength_addendum"].get("status")
        == "PASS_KLT_EXECUTION_STRENGTH_ADDENDUM"
        and dependency["klt_artifact_audit"].get("status")
        == "PASS_KLT_DEPENDENCY_ARTIFACT_AUDIT",
        "LOCK_DEPENDENCY_ACCEPTANCE_STATUS",
    )
    identities = lock.get("identities")
    require(isinstance(identities, dict), "LOCK_IDENTITIES")
    expected_keys = set(STATIC_EXPECTED) | set(KLT_LOCK_FILES) | {
        "runner", "builder", "protocol", KLT_STRENGTH_IDENTITY_KEY,
        KLT_STRENGTH_BUILDER_IDENTITY_KEY,
    }
    require(set(identities) == expected_keys, f"LOCK_IDENTITY_KEYS:{sorted(set(identities)^expected_keys)}")
    for key, (path, size, digest) in STATIC_EXPECTED.items():
        claim = identities.get(key)
        require(
            claim == {"path": str(path), "size_bytes": size, "sha256": digest},
            f"LOCK_STATIC_IDENTITY:{key}",
        )
        require_expected(path, (size, digest))
    fixed_paths = {
        "runner": Path(__file__).absolute(), "builder": BUILDER,
        "protocol": PROTOCOL,
        KLT_STRENGTH_IDENTITY_KEY: KLT_STRENGTH_ADDENDUM,
        KLT_STRENGTH_BUILDER_IDENTITY_KEY: KLT_STRENGTH_BUILDER,
        **KLT_LOCK_FILES,
    }
    for key, path in fixed_paths.items():
        claim = identities.get(key)
        require(isinstance(claim, dict) and claim.get("path") == str(path), f"LOCK_PATH:{key}")
        actual = snapshot_file(path)
        require(
            claim.get("size_bytes") == actual["size_bytes"]
            and claim.get("sha256") == actual["sha256"],
            f"LOCK_DYNAMIC_IDENTITY:{key}",
        )
    require(lock.get("config_chain") == {
        "ordered_paths": [str(path) for path, _ in CONFIG_CHAIN],
        "merged_config_sha256": MERGED_CONFIG_SHA256,
        "effective_xfeat": EFFECTIVE_XFEAT,
        "effective_xfeat_sha256": EFFECTIVE_XFEAT_SHA256,
        "external_tools_link": {"path": str(EXTERNAL_TOOLS_LINK), "target": EXTERNAL_TOOLS_TARGET},
    }, "LOCK_CONFIG_CHAIN")
    return lock, lock_snapshot


def all_input_snapshots(lock: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    identities = lock["identities"]
    for key, claim in identities.items():
        path = Path(claim["path"])
        actual = snapshot_file(path)
        require(
            actual["size_bytes"] == claim["size_bytes"]
            and actual["sha256"] == claim["sha256"],
            f"INPUT_IDENTITY:{key}",
        )
        result[key] = actual
    result["execution_lock"] = snapshot_file(DEFAULT_LOCK)
    result["external_tools_link"] = verify_external_tools_link()
    result["config_chain"] = verify_config_chain()
    return result


def compare_input_snapshots(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    require(set(before) == set(after), "INPUT_SET_CHANGED")
    for key in before:
        if key in {"external_tools_link", "config_chain"}:
            require(before[key] == after[key], f"INPUT_SPECIAL_CHANGED:{key}")
        else:
            require(postcommit_fingerprint(before[key]) == postcommit_fingerprint(after[key]), f"INPUT_CHANGED:{key}")


@contextmanager
def global_mutex() -> Iterator[dict[str, Any]]:
    GLOBAL_FLOCK.parent.mkdir(parents=True, exist_ok=True)
    no_symlink_components(GLOBAL_FLOCK.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(GLOBAL_FLOCK, flags, 0o644)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode), "GLOBAL_FLOCK_NOT_REGULAR")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AquaV2Error("ANOTHER_FRONTEND_SUPERVISOR_HOLDS_FLOCK") from error
        yield {"path": str(GLOBAL_FLOCK), "device": int(info.st_dev), "inode": int(info.st_ino)}
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def fsync_regular(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), f"FSYNC_NOT_REGULAR:{path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_runtime_directories() -> None:
    runtime = AQUA_STAGE / "runtime_v2"
    for path in (
        runtime, runtime / "ros_home", runtime / "ros_log", runtime / "tmp",
        runtime / "cuda_cache", runtime / "mpl_config", runtime / "torch_home",
        runtime / "xdg_cache",
    ):
        path.mkdir(mode=0o700)


def remove_empty_runtime_directories() -> None:
    runtime = AQUA_STAGE / "runtime_v2"
    for path in (
        runtime / "xdg_cache", runtime / "torch_home", runtime / "mpl_config",
        runtime / "cuda_cache", runtime / "tmp", runtime / "ros_log",
        runtime / "ros_home", runtime,
    ):
        require(path.is_dir() and not path.is_symlink(), f"RUNTIME_DIR_MISSING:{path}")
        require(not any(path.iterdir()), f"RUNTIME_DIR_NOT_EMPTY:{path}")
        path.rmdir()


def output_tree_exact(base: Path, *, receipt_allowed: bool = False) -> list[str]:
    allowed = {"full_merged.bag", "sidecar.bag", "stats.csv", CLAIM_NAME, LOG_NAME}
    if receipt_allowed:
        allowed.add(RECEIPT_NAME)
    entries = sorted(path.name for path in base.iterdir())
    require(set(entries) == allowed, f"OUTPUT_TREE:{entries}:{sorted(allowed)}")
    require(all((base / name).is_file() and not (base / name).is_symlink() for name in entries), "OUTPUT_TREE_NONREGULAR")
    return entries


def expected_output_snapshots(base: Path) -> dict[str, Any]:
    return {
        name: snapshot_file(base / name)
        for name in ("full_merged.bag", "sidecar.bag", "stats.csv", CLAIM_NAME, LOG_NAME)
    }


def drain_process(
    process: subprocess.Popen[bytes], baseline_children: set[tuple[int, int]],
    timeout_seconds: int, pending_signals: Sequence[int],
) -> tuple[dict[str, Any], str | None]:
    helper = a10_helper()
    leader = helper.process_identity(process.pid)
    if leader is None:
        leader = (process.pid, -1)
    raw_return_code: int | None = None
    timed_out = False
    error_text: str | None = None
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if pending_signals:
                raise AquaV2Error(
                    "TERMINATION_SIGNALS:" + ",".join(signal.Signals(value).name for value in pending_signals)
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                raw_return_code = process.wait(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException as error:
        error_text = f"{type(error).__name__}:{error}"
    with helper.blocked_signals():
        audit = helper.drain_owned_processes(
            process, process.pid, leader, baseline_children,
            normal_exit=(raw_return_code == 0 and not timed_out and error_text is None),
        )
    raw_return_code = process.returncode
    if audit.get("term_group_sent") and raw_return_code == 0:
        error_text = (error_text + ";" if error_text else "") + "NORMAL_RC_LEFT_OWNED_PROCESS"
    for key, code in (
        ("leader_reaped", "LEADER_NOT_REAPED"),
        ("process_group_empty", "PROCESS_GROUP_NOT_EMPTY"),
        ("owned_descendants_empty", "OWNED_DESCENDANTS_NOT_EMPTY"),
    ):
        if audit.get(key) is not True:
            error_text = (error_text + ";" if error_text else "") + code
    return {
        "popen_invocation_count": 1, "child_started": True,
        "pid": process.pid, "pgid": process.pid,
        "leader_identity": {"pid": leader[0], "start_ticks": leader[1]},
        "raw_return_code": raw_return_code, "timed_out": timed_out,
        "timeout_seconds": timeout_seconds, "process_group": audit,
    }, error_text


def raise_pending_signals(pending_signals: Sequence[int]) -> None:
    if pending_signals:
        names = ",".join(signal.Signals(value).name for value in pending_signals)
        raise AquaV2Error(f"TERMINATION_SIGNALS:{names}")


A10_FIXTURE = {
    "execution_lock": (ROOT / "papers/samehistory_system_comparison_a10_finalonline_v3_recovery_execution_lock.json", 144_118, "b9cf114cc8fa183fc1127b1d7987e20bdabeed60a46f3ed17b178e3a8fa1352d"),
    "claim": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/aquafe_finalonline/process_start_claim.json"), 102_562, "eb5fba04ca55a5ed507fdaaf485d645a3cf8dbf850d87588d92842b216ca98dc"),
    "receipt": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/aquafe_finalonline/formal_run_receipt_v3.json"), 98_125, "f17287d343c721a2fa9f7906de6e1c4c27a440704f3f2eec02ada70f398d93fa"),
    "stats": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/aquafe_finalonline/stats.csv"), 350_112, "cfecc933567e0e62503532f0077ca19a64304994ba57c683a6e6bd0c3bc04da5"),
    "sidecar": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/aquafe_finalonline/sidecar.bag"), 575_687, "82e773c5dd0a4a4b451e5a7d9e3803cc18193ad87c7686a777cdced3fbb09497"),
    "merged": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/aquafe_finalonline/full_merged.bag"), 42_580_404, "7b739e0c717ae41c11b07e364e48331d4a34c7786082cdd98bf53e8f58e03754"),
    "base": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/klt_input_adoption/features.bag"), 42_576_500, "34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f"),
    "camera": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/frontends/klt_input_adoption/aqualoc_archaeo10_pinhole.yaml"), 357, CAMERA_YAML_SHA256),
    "raw": (Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/archaeo10_0000_2800.bag"), 765_976_943, "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e"),
}

A10_FIXTURE_AUTHORITY_KEYS = (
    "a10_supervisor_helper", "opencv_python_binary", "numpy_python_entry",
    "rosbag_python_entry", "pointcloud_message", "channel_message",
    "cv_bridge_init", "cv_bridge_core", "cv_bridge_boost", "cv_bridge_library",
    "uw_frontend_init", "quality_init", "image_quality",
)


def a10_fixture_authority_snapshots() -> dict[str, Any]:
    return {
        key: require_expected(
            STATIC_EXPECTED[key][0],
            (STATIC_EXPECTED[key][1], STATIC_EXPECTED[key][2]),
        )
        for key in A10_FIXTURE_AUTHORITY_KEYS
    }


def selftest_a10_fixture() -> dict[str, Any]:
    identities = {
        key: require_expected(path, (size, digest))
        for key, (path, size, digest) in A10_FIXTURE.items()
    }
    receipt, _ = load_json_regular(A10_FIXTURE["receipt"][0])
    terminal = receipt.get("terminal_process", {})
    group = terminal.get("process_group", {})
    execution = receipt.get("execution_integrity", {})
    artifact = receipt.get("artifact_contract", {})
    require(receipt.get("schema_version") == "aqua-fe-a10-samehistory-finalonline-supervisor-v3", "A10_FIXTURE_RECEIPT_SCHEMA")
    require(receipt.get("item_id") == "aquafe_build", "A10_FIXTURE_ITEM")
    require(receipt.get("launch_allowance_consumed") is True, "A10_FIXTURE_ALLOWANCE")
    require(terminal.get("status") == "TERMINAL_PROCESS_RC0" and terminal.get("popen_invocation_count") == 1, "A10_FIXTURE_TERMINAL")
    require(all(group.get(key) is True for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")), "A10_FIXTURE_GROUP")
    require(execution.get("status") == "PASS" and artifact.get("status") == "PASS", "A10_FIXTURE_ACCEPTANCE")
    require(receipt.get("overall_disposition") == "ACCEPTED", "A10_FIXTURE_DISPOSITION")
    recorded_outputs = artifact.get("outputs", {})
    for key in ("stats", "sidecar", "merged"):
        path = A10_FIXTURE[key][0]
        require(recorded_outputs.get(str(path), {}).get("sha256") == identities[key]["sha256"], f"A10_FIXTURE_OUTPUT_BINDING:{key}")
    audit = audit_aqua_artifacts(
        base_path=A10_FIXTURE["base"][0], merged_path=A10_FIXTURE["merged"][0],
        sidecar_path=A10_FIXTURE["sidecar"][0], stats_path=A10_FIXTURE["stats"][0],
        camera_path=A10_FIXTURE["camera"][0], image_bag_path=A10_FIXTURE["raw"][0],
        expected_features=1_400,
        expected_imu=28_064, expected_gt=139,
        expected_first_ns=1_542_888_796_113_753_648,
        expected_last_ns=1_542_888_935_990_218_544,
        prefix_features=1_200,
    )
    require(audit["sidecar_total_points"] == 2_993, "A10_FIXTURE_SIDECAR_SUMMARY")
    require(audit["learned_action"]["full_observations"] == 61, "A10_FIXTURE_ACTION_SUMMARY")
    return {
        "status": "PASS_KNOWN_LAWFUL_A10_FIXTURE",
        "fixture_is_not_a09_outcome_oracle": True,
        "identities": {key: public_identity(value) for key, value in identities.items()},
        "artifact_audit": audit,
    }


def static_selftest() -> dict[str, Any]:
    # Pure tests deliberately do not inspect A09 KLT paths.
    require(str(float(1_542_888_746 + 121_190_768 / 1e9)) == "1542888746.1211908", "STATIC_STAMP_FIRST")
    require(parse_selector_ids("1000000;1000002", "test", 0) == [1_000_000, 1_000_002], "STATIC_SELECTOR_PARSE")
    try:
        parse_selector_ids("01000000", "test", 0)
    except AquaV2Error:
        pass
    else:
        raise AquaV2Error("STATIC_SELECTOR_NEGATIVE_TEST")
    try:
        validate_trigger_reason("healthy+degradation", 0)
    except AquaV2Error:
        pass
    else:
        raise AquaV2Error("STATIC_TRIGGER_NEGATIVE_TEST")
    argv = build_argv()
    env = effective_environment()
    require(argv.count("--max-lineages") == 1 and argv[argv.index("--max-lineages") + 1] == "1", "STATIC_ARGV_LINEAGES")
    require("CUDA_VISIBLE_DEVICES" not in env and "PYTHONHASHSEED" in env, "STATIC_ENV")
    return {
        "status": "PASS_STATIC_SELFTEST_NO_A09_KLT_READ",
        "argv_sha256": compact_sha(argv),
        "effective_environment_sha256": compact_sha(env),
        "config_chain_paths": [str(path) for path, _ in CONFIG_CHAIN],
    }


def preflight(lock_path: Path, *, include_a10_fixture: bool = True) -> dict[str, Any]:
    require(shutil.disk_usage(EXP_ROOT).free >= 5_000_000_000, "INSUFFICIENT_MNT_DATA_SPACE")
    require(not AQUA_DIR.exists() and not AQUA_DIR.is_symlink(), "AQUA_CANONICAL_EXISTS")
    require(not AQUA_STAGE.exists() and not AQUA_STAGE.is_symlink(), "AQUA_STAGE_EXISTS")
    require(not AQUA_FAILURE.exists() and not AQUA_FAILURE.is_symlink(), "AQUA_FAILURE_EXISTS")
    lock, lock_snapshot = verify_lock(lock_path)
    authority = static_authority_snapshots()
    inputs = all_input_snapshots(lock)
    require(
        postcommit_fingerprint(lock_snapshot)
        == postcommit_fingerprint(inputs["execution_lock"]),
        "LOCK_CHANGED_BETWEEN_VERIFY_AND_INPUT_SNAPSHOT",
    )
    receipt = verify_klt_receipt()
    strength_addendum = verify_klt_strength_addendum()
    klt_audit = audit_raw_and_klt()
    fixture = selftest_a10_fixture() if include_a10_fixture else {"status": "SKIPPED_BY_EXPLICIT_PREFLIGHT_FLAG"}
    return {
        "status": "READY_AQUAFE_V2_SINGLE_POPEN",
        "lock": lock, "lock_snapshot": lock_snapshot,
        "authority": authority, "inputs": inputs,
        "klt_receipt": receipt, "klt_strength_addendum": strength_addendum,
        "klt_audit": klt_audit,
        "a10_lawful_fixture": fixture,
        "argv": build_argv(), "effective_environment": effective_environment(),
        "free_bytes": shutil.disk_usage(EXP_ROOT).free,
    }


def safe_failure_transition(error: BaseException, stage_identity: tuple[int, int] | None) -> None:
    helper = a10_helper()
    # Never unlink a foreign or retargeted canonical path.
    if stage_identity is not None and AQUA_STAGE.is_dir() and not AQUA_STAGE.is_symlink():
        try:
            stage_info = AQUA_STAGE.lstat()
            if (
                not stat.S_ISDIR(stage_info.st_mode)
                or (int(stage_info.st_dev), int(stage_info.st_ino)) != stage_identity
            ):
                return
        except OSError:
            return
        failure = {
            "schema_version": SCHEMA, "status": "FAILED_NO_AUTOMATIC_RETRY",
            "recorded_at_utc": now_utc(), "error_type": type(error).__name__,
            "error": str(error), "launch_allowance_consumed": (AQUA_STAGE / CLAIM_NAME).exists(),
        }
        try:
            if not (AQUA_STAGE / FAILURE_RECEIPT_NAME).exists():
                helper.atomic_publish(AQUA_STAGE / FAILURE_RECEIPT_NAME, failure)
        except BaseException:
            pass
        try:
            try:
                canonical_info = AQUA_DIR.lstat()
            except FileNotFoundError:
                canonical_info = None
            if canonical_info is not None:
                if not stat.S_ISLNK(canonical_info.st_mode):
                    return
                symlink_guard(stage_identity)
                AQUA_DIR.unlink()
                helper.fsync_dir(FRONTENDS)
            if not AQUA_FAILURE.exists() and not AQUA_FAILURE.is_symlink():
                AQUA_STAGE.rename(AQUA_FAILURE)
                helper.fsync_dir(FRONTENDS)
        except OSError:
            return
    elif stage_identity is not None and AQUA_DIR.is_dir() and not AQUA_DIR.is_symlink():
        try:
            committed_directory_guard(stage_identity)
            failure = {
                "schema_version": SCHEMA, "status": "FAILED_NO_AUTOMATIC_RETRY",
                "recorded_at_utc": now_utc(), "error_type": type(error).__name__,
                "error": str(error), "launch_allowance_consumed": (
                    AQUA_DIR / CLAIM_NAME
                ).exists(),
                "failure_after_directory_commit": True,
                "prior_pass_receipt_present": (AQUA_DIR / RECEIPT_NAME).exists(),
            }
            if not (AQUA_DIR / FAILURE_RECEIPT_NAME).exists():
                helper.atomic_publish(AQUA_DIR / FAILURE_RECEIPT_NAME, failure)
            if not AQUA_FAILURE.exists() and not AQUA_FAILURE.is_symlink():
                AQUA_DIR.rename(AQUA_FAILURE)
                helper.fsync_dir(FRONTENDS)
        except BaseException:
            return


def execute(
    lock_path: Path, *, include_a10_fixture: bool = True,
    pending_signals: Sequence[int] = (),
) -> dict[str, Any]:
    helper = a10_helper()
    FRONTENDS.mkdir(parents=True, exist_ok=True)
    with global_mutex() as mutex:
        raise_pending_signals(pending_signals)
        ready = preflight(lock_path, include_a10_fixture=include_a10_fixture)
        raise_pending_signals(pending_signals)
        AQUA_STAGE.mkdir(mode=0o755)
        helper.fsync_dir(FRONTENDS)
        stage_info = AQUA_STAGE.lstat()
        stage_identity = (int(stage_info.st_dev), int(stage_info.st_ino))
        prepare_runtime_directories()
        AQUA_DIR.symlink_to(AQUA_STAGE, target_is_directory=True)
        helper.fsync_dir(FRONTENDS)
        symlink_initial = symlink_guard(stage_identity)
        started = now_utc()
        claim = {
            "schema_version": SCHEMA, "status": "CLAIMED_BEFORE_SINGLE_POPEN",
            "stage": "aquafe", "started_at_utc": started,
            "launch_allowance_consumed": True,
            "popen_invocation_count_at_claim": 0, "retry_count": 0,
            "no_automatic_retry": True, "global_mutex": mutex,
            "execution_lock": public_identity(ready["lock_snapshot"]),
            "argv": ready["argv"], "argv_sha256": compact_sha(ready["argv"]),
            "effective_environment": ready["effective_environment"],
            "effective_environment_sha256": compact_sha(ready["effective_environment"]),
            "inputs": {key: public_identity(value) for key, value in ready["inputs"].items() if isinstance(value, dict) and "sha256" in value},
            "symlink_invariant": symlink_initial,
            "ambient_desktop_allowed_by_user_development_waiver": True,
            "no_runtime_benchmark_claim": True,
        }
        claim_path = AQUA_STAGE / CLAIM_NAME
        stage_claim_publication = helper.atomic_publish(
            claim_path, claim, propagate_interruption_after_commit=True,
        )
        require(
            stage_claim_publication in {"PUBLISHED", "PUBLISHED_POSTLINK_RECOVERED"},
            f"CLAIM_PUBLICATION:{stage_claim_publication}",
        )
        claim_snapshot = snapshot_file(claim_path)
        require(helper.canonical_json(claim) == claim_path.read_bytes(), "CLAIM_BYTES")
        raise_pending_signals(pending_signals)
        symlink_guard(stage_identity)
        inputs_after_claim = all_input_snapshots(ready["lock"])
        compare_input_snapshots(ready["inputs"], inputs_after_claim)

        helper.enable_subreaper()
        timeout_seconds = 3_600
        runtime: dict[str, Any] | None = None
        process_error: str | None = None
        process: subprocess.Popen[bytes] | None = None
        baseline_children: set[tuple[int, int]] = set()
        wall_started = time.monotonic()
        try:
            raise_pending_signals(pending_signals)
            symlink_guard(stage_identity)
            inputs_before_popen = all_input_snapshots(ready["lock"])
            compare_input_snapshots(ready["inputs"], inputs_before_popen)
            raise_pending_signals(pending_signals)
            log_path = AQUA_STAGE / LOG_NAME
            with log_path.open("xb") as log_stream:
                with helper.blocked_signals():
                    baseline_children = set(helper.direct_child_identities(os.getpid()))
                    process = subprocess.Popen(
                        ready["argv"], cwd=str(ROOT), env=ready["effective_environment"],
                        stdout=log_stream, stderr=subprocess.STDOUT,
                        start_new_session=True, close_fds=True,
                    )
                runtime, process_error = drain_process(
                    process, baseline_children, timeout_seconds, pending_signals,
                )
        except BaseException as error:
            process_error = f"{type(error).__name__}:{error}"
            if process is not None and runtime is None:
                runtime, drain_error = drain_process(
                    process, baseline_children, timeout_seconds, (),
                )
                if drain_error:
                    process_error += ";" + drain_error
        if runtime is None:
            runtime = {
                "popen_invocation_count": 0, "child_started": False,
                "raw_return_code": None, "timed_out": False,
                "timeout_seconds": timeout_seconds,
                "process_group": {"leader_reaped": True, "process_group_empty": True, "owned_descendants_empty": True},
            }
        require(runtime.get("popen_invocation_count") == 1, "POPEN_COUNT")
        require(runtime.get("raw_return_code") == 0 and runtime.get("timed_out") is False, f"CHILD_TERMINAL:{runtime}")
        require(process_error is None, f"PROCESS_INTEGRITY:{process_error}")
        group = runtime["process_group"]
        require(all(group.get(key) is True for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")), "PROCESS_TREE_NOT_EMPTY")
        raise_pending_signals(pending_signals)
        symlink_guard(stage_identity)
        remove_empty_runtime_directories()
        output_tree_exact(AQUA_STAGE)
        artifact_audit = audit_aqua_artifacts(
            base_path=BASE_BAG, merged_path=AQUA_STAGE / "full_merged.bag",
            sidecar_path=AQUA_STAGE / "sidecar.bag", stats_path=AQUA_STAGE / "stats.csv",
            camera_path=CAMERA_CONFIG, image_bag_path=RAW_BAG,
            expected_features=FEATURE_COUNT,
            expected_imu=IMU_COUNT, expected_gt=GT_COUNT,
            expected_first_ns=FEATURE_FIRST_NS, expected_last_ns=FEATURE_LAST_NS,
            prefix_features=PREFIX_FEATURE_COUNT,
        )
        raise_pending_signals(pending_signals)
        symlink_guard(stage_identity)
        inputs_after_audit = all_input_snapshots(ready["lock"])
        compare_input_snapshots(ready["inputs"], inputs_after_audit)
        for name in ("full_merged.bag", "sidecar.bag", "stats.csv", LOG_NAME):
            path = AQUA_STAGE / name
            os.chmod(path, 0o444)
            fsync_regular(path)
        helper.fsync_dir(AQUA_STAGE)
        outputs_precommit = expected_output_snapshots(AQUA_STAGE)
        symlink_before_commit = symlink_guard(stage_identity)

        with helper.blocked_signals():
            symlink_guard(stage_identity)
            AQUA_DIR.unlink()
            AQUA_STAGE.rename(AQUA_DIR)
            helper.fsync_dir(FRONTENDS)
        raise_pending_signals(pending_signals)
        committed = committed_directory_guard(stage_identity)
        output_tree_exact(AQUA_DIR)
        outputs_postcommit = expected_output_snapshots(AQUA_DIR)
        for name in outputs_precommit:
            require(
                postcommit_fingerprint(outputs_precommit[name])
                == postcommit_fingerprint(outputs_postcommit[name]),
                f"POSTCOMMIT_REHASH:{name}",
            )
        inputs_postcommit = all_input_snapshots(ready["lock"])
        compare_input_snapshots(ready["inputs"], inputs_postcommit)
        ended = now_utc()
        receipt = {
            "schema_version": SCHEMA, "status": "PASS_AQUAFE_V2_ACCEPTED",
            "stage": "aquafe", "started_at_utc": started, "ended_at_utc": ended,
            "wall_time_seconds": time.monotonic() - wall_started,
            "launch_allowance_consumed": True, "no_automatic_retry": True,
            "execution_lock": public_identity(ready["lock_snapshot"]),
            "claim": public_identity(claim_snapshot),
            "terminal_process": runtime,
            "execution_integrity": {
                "status": "PASS", "effective_environment": ready["effective_environment"],
                "effective_environment_sha256": compact_sha(ready["effective_environment"]),
                "process_group_empty": True, "owned_descendants_empty": True,
                "authority_before_after_equal": True,
                "ambient_desktop_allowed_by_user_development_waiver": True,
                "no_runtime_benchmark_claim": True,
            },
            "artifact_audit": artifact_audit,
            "outputs_precommit": {key: public_identity(value) for key, value in outputs_precommit.items()},
            "outputs_postcommit": {key: public_identity(value) for key, value in outputs_postcommit.items()},
            "commit_invariant": {
                "symlink_before_commit": symlink_before_commit,
                "committed_directory": committed,
                "postcommit_rehash_equal": True,
            },
            "dependency_audit": {
                "klt_artifact": ready["klt_audit"],
                "klt_execution_strength": ready["klt_strength_addendum"],
            },
            "known_lawful_fixture": ready["a10_lawful_fixture"],
            "claim_boundary": {
                "frontend_artifact_only": True, "vins_or_slam_executed": False,
                "trajectory_or_accuracy_result_available": False,
                "formal_paper_accuracy_evidence_permitted": False,
            },
        }
        receipt_path = AQUA_DIR / RECEIPT_NAME
        publication = helper.atomic_publish(receipt_path, receipt)
        require(
            publication in {"PUBLISHED", "PUBLISHED_POSTLINK_RECOVERED"},
            f"RECEIPT_PUBLICATION:{publication}",
        )
        receipt_snapshot = snapshot_file(receipt_path)
        output_tree_exact(AQUA_DIR, receipt_allowed=True)
        committed_directory_guard(stage_identity)
        # One final read-only science-output rehash after receipt publication.
        outputs_final = expected_output_snapshots(AQUA_DIR)
        for name in outputs_postcommit:
            require(
                postcommit_fingerprint(outputs_postcommit[name])
                == postcommit_fingerprint(outputs_final[name]),
                f"FINAL_REHASH:{name}",
            )
        return {
            "status": receipt["status"], "output_dir": str(AQUA_DIR),
            "receipt": public_identity(receipt_snapshot),
            "artifact_audit": artifact_audit,
            "postcommit_rehash_equal": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("static-selftest", "selftest-a10-fixture", "preflight", "run", "audit-existing"),
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--skip-a10-fixture", action="store_true",
        help="Skip only the known-lawful positive fixture; never weakens the A09 artifact audit.",
    )
    args = parser.parse_args()
    try:
        if args.command == "static-selftest":
            result = static_selftest()
        elif args.command == "selftest-a10-fixture":
            a10_fixture_authority_snapshots()
            result = selftest_a10_fixture()
        elif args.command == "preflight":
            with global_mutex():
                result = preflight(args.lock, include_a10_fixture=not args.skip_a10_fixture)
            # Avoid dumping all raw/KLT metadata on normal preflight stdout.
            result = {
                "status": result["status"],
                "lock": public_identity(result["lock_snapshot"]),
                "klt_audit": result["klt_audit"],
                "klt_strength_addendum": result["klt_strength_addendum"]["status"],
                "a10_lawful_fixture": result["a10_lawful_fixture"]["status"],
                "argv_sha256": compact_sha(result["argv"]),
                "effective_environment_sha256": compact_sha(result["effective_environment"]),
                "free_bytes": result["free_bytes"],
            }
        elif args.command == "run":
            helper = a10_helper()
            with helper.interruption_handlers() as pending_signals:
                result = execute(
                    args.lock, include_a10_fixture=not args.skip_a10_fixture,
                    pending_signals=pending_signals,
                )
        else:
            require(AQUA_DIR.is_dir() and not AQUA_DIR.is_symlink(), "AQUA_ACCEPTED_DIR_MISSING")
            result = audit_aqua_artifacts(
                base_path=BASE_BAG, merged_path=AQUA_DIR / "full_merged.bag",
                sidecar_path=AQUA_DIR / "sidecar.bag", stats_path=AQUA_DIR / "stats.csv",
                camera_path=CAMERA_CONFIG, image_bag_path=RAW_BAG,
                expected_features=FEATURE_COUNT,
                expected_imu=IMU_COUNT, expected_gt=GT_COUNT,
                expected_first_ns=FEATURE_FIRST_NS, expected_last_ns=FEATURE_LAST_NS,
                prefix_features=PREFIX_FEATURE_COUNT,
            )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as error:
        if args.command == "run":
            stage_identity: tuple[int, int] | None = None
            try:
                info = AQUA_STAGE.lstat() if AQUA_STAGE.exists() else AQUA_DIR.lstat()
                if stat.S_ISDIR(info.st_mode):
                    stage_identity = (int(info.st_dev), int(info.st_ino))
            except OSError:
                pass
            safe_failure_transition(error, stage_identity)
        print(f"AQUAFE_V2_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
