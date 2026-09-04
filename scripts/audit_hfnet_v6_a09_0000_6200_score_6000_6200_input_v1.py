#!/usr/bin/env python3
"""Independently audit the frozen A09 HFNet input and write one receipt.

This auditor imports no materializer. It reuses only pinned, process-free
independent-audit primitives, hashes and decodes every prepared PNG, streams
the pinned canonical A09 archive through EOF, proves source frames 0..6200
were copied byte-for-byte, independently rebuilds the camera and shifted-IMU
files, checks every camera bracket, and closes the output tree. It never
starts HFNet, ROS, VINS, a detector, or an evaluator.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any, Dict, Mapping, Optional, Sequence


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import (
    audit_hfnet_v6_a08_0000_4660_score_4500_4660_input_v1 as bridge,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a09_0000_6200_score_6000_6200_warmstart"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
SELECTOR = (
    ROOT
    / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_"
    "selector_freeze_v1.json"
)
CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
)
DEFAULT_REPORT = Path(str(INPUT_ROOT) + ".independent_audit_v1.json")

SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "independent-input-audit-v1"
)
MATERIALIZATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "input-materialization-v1"
)
SELECTOR_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "selector-freeze-v1"
)

A08_AUDITOR = (
    ROOT / "scripts/audit_hfnet_v6_a08_0000_4660_score_4500_4660_input_v1.py"
)
A08_AUDITOR_SIZE = 14_409
A08_AUDITOR_SHA256 = (
    "684cf14d7d38b186548837a518caff3782939ae0a452a68ec4f09048da3c7d75"
)

SOURCE_SIZE = 1_722_658_380
SOURCE_SHA256 = (
    "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901"
)
SOURCE_GZIP_CRC32 = "b2f3021d"
SOURCE_GZIP_ISIZE = 1_742_161_920
SELECTOR_SIZE = 4_673
SELECTOR_SHA256 = (
    "2d9bea353a09dfc806cd9764de86d19aa759ee6e640696e33380dc2d9a120883"
)
CONFIG_SIZE = 2_037
CONFIG_SHA256 = (
    "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"
)

IMAGE_CSV_MEMBER = "raw_data/img_sequence_9.csv"
IMAGE_CSV_SIZE = 251_738
IMAGE_CSV_SHA256 = (
    "29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a"
)
IMAGE_CSV_CRC32 = "6ab5e1f7"
IMU_CSV_MEMBER = "raw_data/imu_sequence_9.csv"
IMU_CSV_SIZE = 7_806_649
IMU_CSV_SHA256 = (
    "9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3"
)
IMU_CSV_CRC32 = "cc6033a9"
IMAGE_PREFIX = "raw_data/images_sequence_9/"

SOURCE_CAMERA_COUNT = 6_992
SOURCE_CAMERA_FIRST = 0
SOURCE_CAMERA_LAST = 6_200
CAMERA_COUNT = 6_201
CAMERA_FIRST_NS = 1_542_888_746_071_008_208
CAMERA_LAST_NS = 1_542_889_056_019_958_896
SCORE_SOURCE = [6_000, 6_200]
SCORE_RELATIVE = [6_000, 6_200]

SOURCE_IMU_COUNT = 69_861
IMU_FIRST_INDEX = 5
IMU_LAST_INDEX = 61_947
IMU_COUNT = 61_943
IMU_SHIFT_NS = 53_694_112
IMU_FIRST_RAW_NS = 1_542_888_746_014_492_144
IMU_LAST_RAW_NS = 1_542_889_055_968_943_952
IMU_ENDPOINTS = (
    1_542_888_746_068_186_256,
    1_542_888_746_073_476_784,
    1_542_889_056_017_423_152,
    1_542_889_056_022_638_064,
)

EXPECTED_GENERATED = {
    "cam0_times.txt": (
        124_020,
        "c552e3038595940518ec64e3e8c3a1e0918fb3bdb61c61df33dfd38953b19f3d",
        "5056b9e7",
    ),
    "mav0/cam0/data.csv": (
        272_869,
        "95f24b5a55ecf1707488db9bce74312978efc4135a34f2c9b17c46cc780a531c",
        "974b684e",
    ),
    "mav0/imu0/data.csv": (
        6_915_052,
        "b4aa90d41eab066cf7b7132378f0b7c8735a47ada45342cd7083c0cc1e6dbc57",
        "c2bab267",
    ),
}

REPORTING_BOUNDARY = (
    "development-only A09 natural-history input preparation; historical "
    "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
    "trajectory, accuracy, or ranking"
)
BASE_REPORTING_BOUNDARY = (
    "development-only A05 natural-history input preparation; historical "
    "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
    "trajectory, accuracy, or ranking"
)


core = bridge.core
AuditError = core.AuditError
canonical_json = core.canonical_json
identity_file = core.identity_file
load_json_unique = core.load_json_unique
validate_imu_brackets = core.validate_imu_brackets
require_tree_closure = core.require_tree_closure
write_exclusive = core.write_exclusive

_base_parse_source_camera = bridge._base_parse_source_camera
_base_parse_source_imu = bridge._base_parse_source_imu
_base_validate_manifest = bridge._base_validate_manifest
_base_audit = bridge._base_audit


def parse_source_camera(
    payload: bytes,
    source_count: int = SOURCE_CAMERA_COUNT,
    first: int = SOURCE_CAMERA_FIRST,
    last: int = SOURCE_CAMERA_LAST,
) -> Any:
    """Call the reused parser with every A09 authority explicit."""

    return _base_parse_source_camera(payload, source_count, first, last)


def parse_source_imu(
    payload: bytes,
    selected_camera: Sequence[Any],
    source_count: int = SOURCE_IMU_COUNT,
    first_index: int = IMU_FIRST_INDEX,
    last_index: int = IMU_LAST_INDEX,
    shift_ns: int = IMU_SHIFT_NS,
) -> Any:
    """Call the reused parser with every A09 authority explicit."""

    return _base_parse_source_imu(
        payload,
        selected_camera,
        source_count,
        first_index,
        last_index,
        shift_ns,
    )


def _require_reused_auditor_pins() -> Dict[str, Any]:
    observed = core.identity_file(
        A08_AUDITOR, str(A08_AUDITOR.resolve()), "A08_AUDITOR"
    )
    if (
        observed["size_bytes"] != A08_AUDITOR_SIZE
        or observed["sha256"] != A08_AUDITOR_SHA256
    ):
        raise AuditError("REUSED_A08_AUDITOR_IDENTITY_MISMATCH")
    base = bridge._require_base_auditor_pin()
    return {"a08_auditor_bridge": observed, "a05_base_auditor": base}


def expected_selector_selection() -> Dict[str, Any]:
    return {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A09",
        "camera_indices_inclusive_for_feed": [0, 6200],
        "camera_count_for_feed": 6201,
        "camera_zero_included": True,
        "camera_zero_inclusion_reason": (
            "After the frozen +53694112 ns IMU-to-camera clock shift, source "
            "camera 0 has both a shifted IMU predecessor and successor and is "
            "therefore a legal feed frame."
        ),
        "preroll_camera_indices_inclusive": [0, 5999],
        "score_camera_indices_inclusive": [6000, 6200],
        "score_camera_count": 201,
        "score_history_policy": (
            "Feed frames 0..6200 continuously without estimator reset and "
            "score only source frames 6000..6200."
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
        "FROZEN_BEFORE_A09_MATERIALIZATION_AND_HFNET_PROCESS_START"
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
        "sequence_id": "A09",
        "camera_indices_inclusive": [0, 6200],
        "camera_count": 6201,
        "camera_header_ns_inclusive": [CAMERA_FIRST_NS, CAMERA_LAST_NS],
        "camera_zero_retained_with_shifted_imu_bracket": True,
        "first_legal_camera_source_index": 0,
        "preroll_source_camera_indices_inclusive": [0, 5999],
        "preroll_relative_indices_inclusive": [0, 5999],
        "score_source_camera_indices_inclusive": SCORE_SOURCE,
        "score_relative_indices_inclusive": SCORE_RELATIVE,
        "score_camera_count": 201,
        "warm_start": True,
        "cold_start": False,
        "development_result_conditioned_selection": True,
        "imu_source_indices_inclusive_zero_based": [5, 61947],
        "imu_count": IMU_COUNT,
        "imu_shift_ns": IMU_SHIFT_NS,
        "synthetic_imu_samples_added": False,
    }


def validate_manifest_selection(value: Any) -> None:
    if value != expected_manifest_selection():
        raise AuditError("MANIFEST_SELECTION_MISMATCH")


def validate_manifest(
    manifest: Mapping[str, Any], *args: Any, **kwargs: Any
) -> None:
    if manifest.get("reporting_boundary") != REPORTING_BOUNDARY:
        raise AuditError("MANIFEST_REPORTING_BOUNDARY_MISMATCH")
    surrogate = dict(manifest)
    surrogate["reporting_boundary"] = BASE_REPORTING_BOUNDARY
    _base_validate_manifest(surrogate, *args, **kwargs)


_CORE_BINDINGS = {
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
}


def _bind_core() -> None:
    for name, value in _CORE_BINDINGS.items():
        setattr(core, name, value)


_bind_core()


def audit(
    root: Path = INPUT_ROOT,
    source: Path = SOURCE_ARCHIVE,
    selector: Path = SELECTOR,
    config: Path = CONFIG,
) -> Dict[str, Any]:
    _bind_core()
    reused = _require_reused_auditor_pins()
    result = _base_audit(root, source, selector, config)
    result["auditor"] = core.identity_file(
        Path(__file__).resolve(), str(Path(__file__).resolve()), "AUDITOR"
    )
    result["reused_auditors"] = reused
    result["camera"]["preroll_source_indices_inclusive"] = [0, 5999]
    result["reporting_boundary"] = (
        "development-only A09 natural-history input preparation; no HFNet "
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
