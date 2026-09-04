#!/usr/bin/env python3
"""Independently audit the frozen A08 HFNet input and write one receipt.

This auditor imports no materializer.  It reuses only the pinned, process-free
A05 independent-audit primitives, hashes and decodes every prepared PNG,
streams the pinned canonical A08 archive through EOF, proves source frames
0..4660 were copied byte-for-byte, independently rebuilds the camera and
shifted-IMU files, checks every camera bracket, and closes the output tree.
It never starts HFNet, ROS, VINS, a detector, or an evaluator.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any, Dict, Mapping, Optional, Sequence


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import (
    audit_hfnet_v6_a05_0001_3700_score_3300_3700_input_v1 as core,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a08_0000_4660_score_4500_4660_warmstart"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz"
)
SELECTOR = (
    ROOT
    / "papers/hfnet_v6_a08_0000_4660_score_4500_4660_"
    "selector_freeze_v1.json"
)
CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
)
DEFAULT_REPORT = Path(str(INPUT_ROOT) + ".independent_audit_v1.json")

SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a08-0000-4660-score-4500-4660-"
    "independent-input-audit-v1"
)
MATERIALIZATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a08-0000-4660-score-4500-4660-"
    "input-materialization-v1"
)
SELECTOR_SCHEMA = (
    "aqua-fe-hfnet-v6-a08-0000-4660-score-4500-4660-"
    "selector-freeze-v1"
)

BASE_AUDITOR = (
    ROOT / "scripts/audit_hfnet_v6_a05_0001_3700_score_3300_3700_input_v1.py"
)
BASE_AUDITOR_SIZE = 46_363
BASE_AUDITOR_SHA256 = (
    "eefa9799b2066d199821c07e034f6db5147108e09b4dc83e0a5277154f0e33eb"
)

SOURCE_SIZE = 2_316_571_070
SOURCE_SHA256 = (
    "b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153"
)
SOURCE_GZIP_CRC32 = "3ebe1f0c"
SOURCE_GZIP_ISIZE = 2_343_168_000
SELECTOR_SIZE = 4_960
SELECTOR_SHA256 = (
    "2cc49bb2311c87338a06f266e8557e5ac68fadad044d57f4b6bea09de7522ed7"
)
CONFIG_SIZE = 2_037
CONFIG_SHA256 = (
    "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"
)

IMAGE_CSV_MEMBER = "raw_data/img_sequence_8.csv"
IMAGE_CSV_SIZE = 338_102
IMAGE_CSV_SHA256 = (
    "1137d5b60e618c5febfb62f6f89f0d261af206e2256d5bfac2bea6f0cbafe689"
)
IMAGE_CSV_CRC32 = "179269f8"
IMU_CSV_MEMBER = "raw_data/imu_sequence_8.csv"
IMU_CSV_SIZE = 10_495_986
IMU_CSV_SHA256 = (
    "be4ce25d04d2a50b51474a072a14071f77e450dd78aff51e5ba8378f556c3643"
)
IMU_CSV_CRC32 = "6b630122"
IMAGE_PREFIX = "raw_data/images_sequence_8/"

SOURCE_CAMERA_COUNT = 9_391
SOURCE_CAMERA_FIRST = 0
SOURCE_CAMERA_LAST = 4_660
CAMERA_COUNT = 4_661
CAMERA_FIRST_NS = 1_542_884_961_144_554_192
CAMERA_LAST_NS = 1_542_885_194_106_222_672
SCORE_SOURCE = [4_500, 4_660]
SCORE_RELATIVE = [4_500, 4_660]

SOURCE_IMU_COUNT = 93_837
IMU_FIRST_INDEX = 12
IMU_LAST_INDEX = 46_570
IMU_COUNT = 46_559
IMU_SHIFT_NS = 53_694_112
IMU_FIRST_RAW_NS = 1_542_884_961_090_347_600
IMU_LAST_RAW_NS = 1_542_885_194_055_132_080
IMU_ENDPOINTS = (
    1_542_884_961_144_041_712,
    1_542_884_961_146_933_296,
    1_542_885_194_103_702_576,
    1_542_885_194_108_826_192,
)

EXPECTED_GENERATED = {
    "cam0_times.txt": (
        93_220,
        "0ce637bc6e9e74a300dee7b40eb18e84962106fb7fc867d5d0eae83bf47f7662",
        "2d2d0119",
    ),
    "mav0/cam0/data.csv": (
        205_109,
        "43203c2d25a3d806397648558006bd8a21fdc7aa7f908b0099f44d5251c0c361",
        "9d90eca7",
    ),
    "mav0/imu0/data.csv": (
        5_211_752,
        "98b7ca7feab3913edce8803f131e29a2861b2883a8578882cc19eb858c919262",
        "87378882",
    ),
}

REPORTING_BOUNDARY = (
    "development-only A08 natural-history input preparation; historical "
    "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
    "trajectory, accuracy, or ranking"
)
BASE_REPORTING_BOUNDARY = (
    "development-only A05 natural-history input preparation; historical "
    "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
    "trajectory, accuracy, or ranking"
)


AuditError = core.AuditError
canonical_json = core.canonical_json
identity_file = core.identity_file
load_json_unique = core.load_json_unique
validate_imu_brackets = core.validate_imu_brackets
require_tree_closure = core.require_tree_closure
write_exclusive = core.write_exclusive

_base_parse_source_camera = core.parse_source_camera
_base_parse_source_imu = core.parse_source_imu


def parse_source_camera(
    payload: bytes,
    source_count: int = SOURCE_CAMERA_COUNT,
    first: int = SOURCE_CAMERA_FIRST,
    last: int = SOURCE_CAMERA_LAST,
) -> Any:
    """Call the reused parser with A08 authorities passed explicitly.

    The reused function's original default arguments were bound at A05 module
    definition time, so relying on those defaults would be an unsafe adapter
    leak even though its module globals are rebound below.
    """

    return _base_parse_source_camera(payload, source_count, first, last)


def parse_source_imu(
    payload: bytes,
    selected_camera: Sequence[Any],
    source_count: int = SOURCE_IMU_COUNT,
    first_index: int = IMU_FIRST_INDEX,
    last_index: int = IMU_LAST_INDEX,
    shift_ns: int = IMU_SHIFT_NS,
) -> Any:
    """Call the reused parser with every A08 authority passed explicitly."""

    return _base_parse_source_imu(
        payload,
        selected_camera,
        source_count,
        first_index,
        last_index,
        shift_ns,
    )


def _require_base_auditor_pin() -> Dict[str, Any]:
    observed = core.identity_file(
        BASE_AUDITOR, str(BASE_AUDITOR.resolve()), "BASE_AUDITOR"
    )
    if (
        observed["size_bytes"] != BASE_AUDITOR_SIZE
        or observed["sha256"] != BASE_AUDITOR_SHA256
    ):
        raise AuditError("REUSED_BASE_AUDITOR_IDENTITY_MISMATCH")
    return observed


def expected_selector_selection() -> Dict[str, Any]:
    return {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A08",
        "camera_indices_inclusive_for_feed": [0, 4660],
        "camera_count_for_feed": 4661,
        "camera_zero_included": True,
        "camera_zero_inclusion_reason": (
            "After the frozen +53694112 ns IMU-to-camera clock shift, source "
            "camera 0 has both a shifted IMU predecessor and successor and is "
            "therefore a legal feed frame."
        ),
        "preroll_camera_indices_inclusive": [0, 4499],
        "score_camera_indices_inclusive": [4500, 4660],
        "score_camera_count": 161,
        "score_history_policy": (
            "Feed frames 0..4660 continuously without estimator reset and "
            "score only source frames 4500..4660."
        ),
        "warm_start": True,
        "cold_start": False,
        "synthetic_or_extrapolated_imu_permitted": False,
    }


def validate_selector(payload: bytes) -> Dict[str, Any]:
    value = core.load_json_unique(payload, "SELECTOR")
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise AuditError("SELECTOR_SCHEMA_MISMATCH")
    if value.get("status") != (
        "FROZEN_BEFORE_A08_MATERIALIZATION_AND_HFNET_PROCESS_START"
    ):
        raise AuditError("SELECTOR_STATUS_MISMATCH")
    if value.get("selection") != expected_selector_selection():
        raise AuditError("SELECTOR_SELECTION_MISMATCH")
    boundary = value.get("knowledge_boundary", {})
    if (
        boundary.get("window_is_outcome_selected") is not True
        or boundary.get(
            "accuracy_requires_new_history_matched_controls_and_common_support"
        )
        is not True
        or boundary.get(
            "natural_history_hfnet_must_not_be_ranked_against_cold_crop_metrics"
        )
        is not True
    ):
        raise AuditError("SELECTOR_KNOWLEDGE_BOUNDARY_MISMATCH")
    if value.get("claims") != {
        "accuracy_evaluated": False,
        "confirmatory_evidence": False,
        "hfnet_runability_passed": False,
        "hfnet_started": False,
        "input_materialized": False,
        "superiority_supported": False,
        "system_ranking_supported": False,
        "trajectory_produced": False,
    }:
        raise AuditError("SELECTOR_CLAIMS_MISMATCH")
    return value


def expected_manifest_selection() -> Dict[str, Any]:
    return {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A08",
        "camera_indices_inclusive": [0, 4660],
        "camera_count": 4661,
        "camera_header_ns_inclusive": [CAMERA_FIRST_NS, CAMERA_LAST_NS],
        "camera_zero_retained_with_shifted_imu_bracket": True,
        "first_legal_camera_source_index": 0,
        "preroll_source_camera_indices_inclusive": [0, 4499],
        "preroll_relative_indices_inclusive": [0, 4499],
        "score_source_camera_indices_inclusive": SCORE_SOURCE,
        "score_relative_indices_inclusive": SCORE_RELATIVE,
        "score_camera_count": 161,
        "warm_start": True,
        "cold_start": False,
        "development_result_conditioned_selection": True,
        "imu_source_indices_inclusive_zero_based": [12, 46570],
        "imu_count": IMU_COUNT,
        "imu_shift_ns": IMU_SHIFT_NS,
        "synthetic_imu_samples_added": False,
    }


def validate_manifest_selection(value: Any) -> None:
    if value != expected_manifest_selection():
        raise AuditError("MANIFEST_SELECTION_MISMATCH")


_base_validate_manifest = core.validate_manifest
_base_audit = core.audit


def validate_manifest(
    manifest: Mapping[str, Any], *args: Any, **kwargs: Any
) -> None:
    if manifest.get("reporting_boundary") != REPORTING_BOUNDARY:
        raise AuditError("MANIFEST_REPORTING_BOUNDARY_MISMATCH")
    surrogate = dict(manifest)
    surrogate["reporting_boundary"] = BASE_REPORTING_BOUNDARY
    _base_validate_manifest(surrogate, *args, **kwargs)


# The reused independent-audit primitives resolve dataset constants and
# validators from their defining module.  Bind all A08-specific authorities.
for _name, _value in {
    "INPUT_ROOT": INPUT_ROOT,
    "SOURCE_ARCHIVE": SOURCE_ARCHIVE,
    "SELECTOR": SELECTOR,
    "CONFIG": CONFIG,
    "DEFAULT_REPORT": DEFAULT_REPORT,
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "MATERIALIZATION_SCHEMA": MATERIALIZATION_SCHEMA,
    "SELECTOR_SCHEMA": SELECTOR_SCHEMA,
    "SOURCE_SIZE": SOURCE_SIZE,
    "SOURCE_SHA256": SOURCE_SHA256,
    "SOURCE_GZIP_CRC32": SOURCE_GZIP_CRC32,
    "SOURCE_GZIP_ISIZE": SOURCE_GZIP_ISIZE,
    "SELECTOR_SIZE": SELECTOR_SIZE,
    "SELECTOR_SHA256": SELECTOR_SHA256,
    "CONFIG_SIZE": CONFIG_SIZE,
    "CONFIG_SHA256": CONFIG_SHA256,
    "IMAGE_CSV_MEMBER": IMAGE_CSV_MEMBER,
    "IMAGE_CSV_SIZE": IMAGE_CSV_SIZE,
    "IMAGE_CSV_SHA256": IMAGE_CSV_SHA256,
    "IMAGE_CSV_CRC32": IMAGE_CSV_CRC32,
    "IMU_CSV_MEMBER": IMU_CSV_MEMBER,
    "IMU_CSV_SIZE": IMU_CSV_SIZE,
    "IMU_CSV_SHA256": IMU_CSV_SHA256,
    "IMU_CSV_CRC32": IMU_CSV_CRC32,
    "IMAGE_PREFIX": IMAGE_PREFIX,
    "SOURCE_CAMERA_COUNT": SOURCE_CAMERA_COUNT,
    "SOURCE_CAMERA_FIRST": SOURCE_CAMERA_FIRST,
    "SOURCE_CAMERA_LAST": SOURCE_CAMERA_LAST,
    "CAMERA_COUNT": CAMERA_COUNT,
    "CAMERA_FIRST_NS": CAMERA_FIRST_NS,
    "CAMERA_LAST_NS": CAMERA_LAST_NS,
    "SCORE_SOURCE": SCORE_SOURCE,
    "SCORE_RELATIVE": SCORE_RELATIVE,
    "SOURCE_IMU_COUNT": SOURCE_IMU_COUNT,
    "IMU_FIRST_INDEX": IMU_FIRST_INDEX,
    "IMU_LAST_INDEX": IMU_LAST_INDEX,
    "IMU_COUNT": IMU_COUNT,
    "IMU_SHIFT_NS": IMU_SHIFT_NS,
    "IMU_FIRST_RAW_NS": IMU_FIRST_RAW_NS,
    "IMU_LAST_RAW_NS": IMU_LAST_RAW_NS,
    "IMU_ENDPOINTS": IMU_ENDPOINTS,
    "EXPECTED_GENERATED": EXPECTED_GENERATED,
    "parse_source_camera": parse_source_camera,
    "parse_source_imu": parse_source_imu,
    "validate_selector": validate_selector,
    "expected_manifest_selection": expected_manifest_selection,
    "validate_manifest_selection": validate_manifest_selection,
    "validate_manifest": validate_manifest,
}.items():
    setattr(core, _name, _value)


def audit(
    root: Path = INPUT_ROOT,
    source: Path = SOURCE_ARCHIVE,
    selector: Path = SELECTOR,
    config: Path = CONFIG,
) -> Dict[str, Any]:
    _require_base_auditor_pin()
    result = _base_audit(root, source, selector, config)
    result["auditor"] = core.identity_file(
        Path(__file__).resolve(), str(Path(__file__).resolve()), "AUDITOR"
    )
    result["camera"]["preroll_source_indices_inclusive"] = [0, 4499]
    result["reporting_boundary"] = (
        "development-only A08 natural-history input preparation; no HFNet "
        "process, trajectory, runability result, accuracy, or ranking"
    )
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    value.add_argument("--source-archive", type=Path, default=SOURCE_ARCHIVE)
    value.add_argument("--selector-freeze", type=Path, default=SELECTOR)
    value.add_argument("--config", type=Path, default=CONFIG)
    value.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if os.path.lexists(os.fspath(args.report)):
            raise AuditError(f"NO_CLOBBER_REPORT_EXISTS:{args.report}")
        result = audit(
            args.input_root,
            args.source_archive,
            args.selector_freeze,
            args.config,
        )
        payload = canonical_json(result)
        write_exclusive(args.report, payload)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {
                "hfnet_started": False,
                "trajectory_produced": False,
                "accuracy_measured": False,
            },
        }
        payload = canonical_json(result)
        return_code = 2
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
