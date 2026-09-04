#!/usr/bin/env python3
"""Frozen constants for the additive A02 HFNet result-informed extension.

This module contains no producer and starts no process.  It keeps the
4500..7200 experiment namespace and scientific caveats identical across the
materializer, shared exporter, and HFNet supervisor.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
ROLE = "POST-FAILURE_RESULT-INFORMED_EXPLORATORY_INITIALIZATION_CONTINUATION"

FEED_FIRST = 4_500
FEED_LAST = 7_200
FEED_COUNT = 2_701
PRIOR_FEED_LAST = 6_300
PRIOR_PREFIX_COUNT = 1_801
NEW_CAMERA_COUNT = 900
SCORE_FIRST = 6_300
SCORE_LAST = 7_200
SCORE_REFERENCE_INDICES = tuple(range(SCORE_FIRST, SCORE_LAST + 1, 20))
SCORE_REFERENCE_COUNT = 46
SCORE_EVALUATION_GRID_COUNT = 45

CAMERA_FIRST_NS = 1_542_829_016_700_435_392
CAMERA_PRIOR_LAST_NS = 1_542_829_106_687_510_592
CAMERA_LAST_NS = 1_542_829_151_677_182_656
SCORE_SPAN_NS = CAMERA_LAST_NS - CAMERA_PRIOR_LAST_NS

CANONICAL_MARGIN_IMU_COUNT = 27_076
CANONICAL_MARGIN_IMU_GLOBAL_FIRST = 44_916
CANONICAL_MARGIN_IMU_GLOBAL_LAST = 71_991
CANONICAL_MARGIN_IMU_FIRST_NS = 1_542_829_016_456_083_680
CANONICAL_MARGIN_IMU_LAST_NS = 1_542_829_151_925_575_072

IMU_SHIFT_NS = 53_694_112
HFNET_INNER_IMU_COUNT = 26_978
HFNET_INNER_IMU_GLOBAL_FIRST = 44_954
HFNET_INNER_IMU_GLOBAL_LAST = 71_931
HFNET_INNER_IMU_FIRST_RAW_NS = 1_542_829_016_645_312_000
HFNET_INNER_IMU_LAST_RAW_NS = 1_542_829_151_625_420_640

RAW_TAR = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_sequence_2_raw_data.tar.gz"
)
GT_PATH = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
)
CONVERTER = ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
OLD_WINDOW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
OLD_WINDOW_MANIFEST = Path(str(OLD_WINDOW_BAG) + ".manifest.json")
OLD_SHARED_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/"
    "a02_4500_6300_shared_r1"
)
OLD_HFNET_CONTRACT = ROOT / "papers/hfnet_slam_a02_long1801_headless_run_contract_v4.json"
OLD_HFNET_RESULT = ROOT / (
    "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/"
    "drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json"
)

NEW_WINDOW_BAG = ROOT / (
    "datasets/aqualoc/rosbags/"
    "archaeo02_4500_7200_hfnet_result_informed_v1.bag"
)
NEW_WINDOW_MANIFEST = Path(str(NEW_WINDOW_BAG) + ".manifest.json")
NEW_WINDOW_ATTEMPT = Path(str(NEW_WINDOW_BAG) + ".attempt.json")
NEW_SHARED_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/"
    "a02_4500_7200_result_informed_hfnet_r1"
)
NEW_SHARED_ATTEMPT = NEW_SHARED_ROOT.with_name(NEW_SHARED_ROOT.name + ".attempt.json")
NEW_RESULT = ROOT / (
    "logs/published_hfnet_slam_v5/result_informed_a02_4500_7200/"
    "runs/aqualoc_a02_4500_7200_headless_r1"
)
NEW_EVIDENCE = ROOT / (
    "logs/published_hfnet_slam_v5/result_informed_a02_4500_7200/"
    "drivers/aqualoc_a02_4500_7200_headless_r1"
)
NEW_RUN_CONTRACT = ROOT / (
    "papers/hfnet_slam_a02_4500_7200_result_informed_run_contract_v5.json"
)
NEW_BRIDGE_OUTPUT = ROOT / (
    "logs/published_hfnet_slam_v5/result_informed_a02_4500_7200/"
    "bridges/aqualoc_a02_6300_7200_hfnet_world_T_body_v1.csv"
)
STATIC_FREEZE = ROOT / (
    "papers/a02_4500_7200_hfnet_result_informed_extension_freeze_v1.json"
)

SEALED_PYTHON = "/usr/bin/python3.8"
SEALED_PYCACHE_PREFIX = "/tmp/aqua-fe-a02-hfnet-extension-empty-pycache-v1"
REQUIRED_ENVIRONMENT = {
    "HOME": "/home/ma",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LOGNAME": "ma",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "PATH": "/home/ma/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "PYTHONPATH": "/home/ma/AQUA-FE_WS:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages",
    "PYTHONPYCACHEPREFIX": SEALED_PYCACHE_PREFIX,
    "SHELL": "/bin/bash",
    "USER": "ma",
}

RAW_TAR_SIZE = 2_195_786_266
RAW_TAR_SHA256 = "8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69"
GT_SIZE = 64_318
GT_SHA256 = "1122b753372545966026df10f1899e751cdaa3359a6938be251cd8e22b6e4379"
CONVERTER_SHA256 = "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec"
OLD_WINDOW_BAG_SIZE = 449_056_538
OLD_WINDOW_BAG_SHA256 = "eebd45439e76c461e58a2a1d6321f3fcb82dbcf57ea4093929548c9620e63a83"
OLD_WINDOW_MANIFEST_SIZE = 4_502
OLD_WINDOW_MANIFEST_SHA256 = "41667ae9fd00dc6baf261cb2c519642b0ff9c2123ba154421780bc41bcf4de8e"
OLD_SHARED_MANIFEST_SIZE = 682_952
OLD_SHARED_MANIFEST_SHA256 = "f2931e451e9542a3801209e88fd47519b881d6713ac829c9871a1f9366bc9d93"
OLD_HFNET_CONTRACT_SIZE = 61_550
OLD_HFNET_CONTRACT_SHA256 = "f084994e70480d71c939fe60827aa5380a89d1434d6876058b89e26871632c8e"
OLD_HFNET_RESULT_SIZE = 4_966
OLD_HFNET_RESULT_SHA256 = "b7c911ca364a9d9233fa9b7cf0c6f245b83e89b129882628075fd8e759c6cb73"


class ExtensionError(RuntimeError):
    pass


def authoritative_commands() -> list[dict[str, object]]:
    rows: Sequence[tuple[str, Sequence[str], bool, bool]] = (
        (
            "synthetic_tests_only",
            (
                SEALED_PYTHON,
                "-B",
                "-m",
                "unittest",
                "scripts.tests.test_a02_hfnet_result_informed_extension_v1",
            ),
            True,
            False,
        ),
        ("source_window_preflight", (SEALED_PYTHON, "-B", "scripts/materialize_aqualoc_a02_4500_7200_result_informed_v1.py", "--action", "preflight"), False, False),
        ("source_window_export_once", (SEALED_PYTHON, "-B", "scripts/materialize_aqualoc_a02_4500_7200_result_informed_v1.py", "--action", "export"), False, False),
        ("shared_input_preflight", (SEALED_PYTHON, "-B", "scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py", "--action", "preflight"), False, False),
        ("shared_input_export_once", (SEALED_PYTHON, "-B", "scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py", "--action", "export"), False, False),
        ("shared_input_post_export_audit", (SEALED_PYTHON, "-B", "scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py", "--action", "audit"), False, False),
        ("hfnet_preflight", (SEALED_PYTHON, "-B", "scripts/run_hfnet_slam_a02_4500_7200_result_informed_headless_v5.py", "--action", "preflight"), False, False),
        ("hfnet_dynamic_contract_freeze", (SEALED_PYTHON, "-B", "scripts/run_hfnet_slam_a02_4500_7200_result_informed_headless_v5.py", "--action", "freeze"), False, False),
        ("hfnet_one_shot_run", (SEALED_PYTHON, "-B", "scripts/run_hfnet_slam_a02_4500_7200_result_informed_headless_v5.py", "--action", "run"), False, True),
    )
    return [
        {
            "action": action,
            "argv": list(argv),
            "executed_during_implementation": executed,
            "may_start_slam": may_start_slam,
            "ordinal": ordinal,
        }
        for ordinal, (action, argv, executed, may_start_slam) in enumerate(rows)
    ]


def audit_sealed_invocation_environment() -> None:
    if dict(os.environ) != REQUIRED_ENVIRONMENT:
        raise ExtensionError("INVOCATION_ENVIRONMENT_NOT_EXACTLY_SEALED")
    if Path.cwd().resolve(strict=True) != ROOT:
        raise ExtensionError("INVOCATION_CWD_MISMATCH")
    prefix = Path(SEALED_PYCACHE_PREFIX)
    if prefix.exists() or prefix.is_symlink():
        raise ExtensionError("PYTHONPYCACHEPREFIX_MUST_BE_ABSENT")


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, *, size: int | None = None, sha256: str | None = None, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ExtensionError(f"{label}_MISSING_OR_NOT_REGULAR")
    resolved = path.resolve(strict=True)
    observed = {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }
    if size is not None and observed["size_bytes"] != size:
        raise ExtensionError(f"{label}_SIZE_MISMATCH")
    if sha256 is not None and observed["sha256"] != sha256:
        raise ExtensionError(f"{label}_SHA256_MISMATCH")
    return observed


def expected_static_source_identities() -> Mapping[str, dict[str, object]]:
    return {
        "raw_tar": identity(RAW_TAR, size=RAW_TAR_SIZE, sha256=RAW_TAR_SHA256, label="RAW_TAR"),
        "ground_truth": identity(GT_PATH, size=GT_SIZE, sha256=GT_SHA256, label="GROUND_TRUTH"),
        "converter": identity(CONVERTER, sha256=CONVERTER_SHA256, label="CONVERTER"),
        "prior_window_bag": identity(OLD_WINDOW_BAG, size=OLD_WINDOW_BAG_SIZE, sha256=OLD_WINDOW_BAG_SHA256, label="PRIOR_WINDOW_BAG"),
        "prior_window_manifest": identity(OLD_WINDOW_MANIFEST, size=OLD_WINDOW_MANIFEST_SIZE, sha256=OLD_WINDOW_MANIFEST_SHA256, label="PRIOR_WINDOW_MANIFEST"),
        "prior_shared_manifest": identity(OLD_SHARED_ROOT / "conversion_manifest.json", size=OLD_SHARED_MANIFEST_SIZE, sha256=OLD_SHARED_MANIFEST_SHA256, label="PRIOR_SHARED_MANIFEST"),
        "prior_hfnet_contract": identity(OLD_HFNET_CONTRACT, size=OLD_HFNET_CONTRACT_SIZE, sha256=OLD_HFNET_CONTRACT_SHA256, label="PRIOR_HFNET_CONTRACT"),
        "prior_hfnet_unusable_result": identity(OLD_HFNET_RESULT, size=OLD_HFNET_RESULT_SIZE, sha256=OLD_HFNET_RESULT_SHA256, label="PRIOR_HFNET_RESULT"),
    }


def reserved_paths() -> tuple[Path, ...]:
    return (
        NEW_WINDOW_BAG,
        NEW_WINDOW_MANIFEST,
        NEW_WINDOW_ATTEMPT,
        NEW_SHARED_ROOT,
        NEW_SHARED_ATTEMPT,
        NEW_RESULT,
        NEW_EVIDENCE,
        NEW_RUN_CONTRACT,
        NEW_BRIDGE_OUTPUT,
        Path(str(NEW_BRIDGE_OUTPUT) + ".manifest.json"),
    )
