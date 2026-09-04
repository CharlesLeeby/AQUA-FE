#!/usr/bin/env python3
"""Materialize the frozen A09 natural-history HFNet input, and nothing else.

The feed contains canonical AQUALOC archaeology source cameras 0..6200.
Cameras 0..5999 are history only and 6000..6200 are the sole score window.
Publication is atomic and no-clobber; this module starts no process.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, Optional, Sequence


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_a08_0000_4660_score_4500_4660_v1 as bridge


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "input-materialization-v1"
)
SELECTOR_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "selector-freeze-v1"
)

A08_BRIDGE_PATH = (
    ROOT / "scripts/materialize_hfnet_v6_a08_0000_4660_score_4500_4660_v1.py"
)
A08_BRIDGE_SIZE = 13_342
A08_BRIDGE_SHA256 = (
    "67043bfb2e9f57d0b2f83a5471d9f8f365f3222753d766cd1e5df9eca4d6826d"
)

DEFAULT_SELECTOR_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_"
    "selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 4_673
SELECTOR_FREEZE_SHA256 = (
    "2d9bea353a09dfc806cd9764de86d19aa759ee6e640696e33380dc2d9a120883"
)

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a09_0000_6200_score_6000_6200_warmstart"
)

adapter = bridge.adapter
core = bridge.core
FilePin = core.FilePin
MaterializationContract = core.MaterializationContract
ContractError = core.ContractError


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=1_722_658_380,
        sha256=(
            "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901"
        ),
    ),
    source_gzip_crc32="b2f3021d",
    source_gzip_isize=1_742_161_920,
    image_csv_member="raw_data/img_sequence_9.csv",
    image_csv_pin=FilePin(
        size_bytes=251_738,
        sha256=(
            "29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a"
        ),
        crc32="6ab5e1f7",
    ),
    imu_csv_member="raw_data/imu_sequence_9.csv",
    imu_csv_pin=FilePin(
        size_bytes=7_806_649,
        sha256=(
            "9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3"
        ),
        crc32="cc6033a9",
    ),
    image_member_prefix="raw_data/images_sequence_9/",
    source_camera_count=6_992,
    source_imu_count=69_861,
    camera_start_index=0,
    camera_end_index=6_200,
    camera_first_ns=1_542_888_746_071_008_208,
    camera_last_ns=1_542_889_056_019_958_896,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=5,
    imu_last_index=61_947,
    imu_first_raw_ns=1_542_888_746_014_492_144,
    imu_last_raw_ns=1_542_889_055_968_943_952,
    imu_first_output_ns=1_542_888_746_068_186_256,
    imu_second_output_ns=1_542_888_746_073_476_784,
    imu_penultimate_output_ns=1_542_889_056_017_423_152,
    imu_last_output_ns=1_542_889_056_022_638_064,
    expected_image_total_bytes=1_523_345_291,
    expected_source_image_inventory_sha256=(
        "f6a010a370a1f96d4180d6caaa31bae201993c7c3bb7d728a73ec752adb808d9"
    ),
    expected_source_image_inventory_crc32="87d0105f",
    expected_renamed_image_inventory_sha256=(
        "77dd65cc8f258e081ee127506bec78a00dfda7077262fd012178d3c68449fafd"
    ),
    expected_renamed_image_inventory_crc32="52749daf",
    times_pin=FilePin(
        size_bytes=124_020,
        sha256=(
            "c552e3038595940518ec64e3e8c3a1e0918fb3bdb61c61df33dfd38953b19f3d"
        ),
        crc32="5056b9e7",
    ),
    camera_csv_pin=FilePin(
        size_bytes=272_869,
        sha256=(
            "95f24b5a55ecf1707488db9bce74312978efc4135a34f2c9b17c46cc780a531c"
        ),
        crc32="974b684e",
    ),
    imu_output_pin=FilePin(
        size_bytes=6_915_052,
        sha256=(
            "b4aa90d41eab066cf7b7132378f0b7c8735a47ada45342cd7083c0cc1e6dbc57"
        ),
        crc32="c2bab267",
    ),
    expected_payload_sha256=(
        "a186160594fe6e0fc46ed2e363d6171e22a5ee8abd549467635a4f3833151c1c"
    ),
    expected_payload_crc32="6ea95711",
)


def _require_reused_code_pins() -> Dict[str, Any]:
    observed = core.identity_file(
        A08_BRIDGE_PATH, str(A08_BRIDGE_PATH.resolve())
    )
    if (
        observed["size_bytes"] != A08_BRIDGE_SIZE
        or observed["sha256"] != A08_BRIDGE_SHA256
    ):
        raise ContractError("REUSED_A08_BRIDGE_IDENTITY_MISMATCH")
    inherited = bridge._require_reused_code_pins()
    return {"a08_materializer_bridge": observed, **inherited}


def validate_selector(path: Path) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("SELECTOR_FREEZE_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    if observed["size_bytes"] != SELECTOR_FREEZE_SIZE:
        raise ContractError("SELECTOR_FREEZE_SIZE_MISMATCH")
    if observed["sha256"] != SELECTOR_FREEZE_SHA256:
        raise ContractError("SELECTOR_FREEZE_SHA256_MISMATCH")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise ContractError("SELECTOR_SCHEMA_MISMATCH")
    if value.get("status") != (
        "FROZEN_BEFORE_A09_MATERIALIZATION_AND_HFNET_PROCESS_START"
    ):
        raise ContractError("SELECTOR_STATUS_MISMATCH")
    selection = value.get("selection", {})
    required = {
        "sequence_id": "A09",
        "camera_indices_inclusive_for_feed": [0, 6200],
        "camera_count_for_feed": 6201,
        "camera_zero_included": True,
        "preroll_camera_indices_inclusive": [0, 5999],
        "score_camera_indices_inclusive": [6000, 6200],
        "score_camera_count": 201,
        "warm_start": True,
        "cold_start": False,
        "synthetic_or_extrapolated_imu_permitted": False,
    }
    for key, expected in required.items():
        if selection.get(key) != expected:
            raise ContractError(f"SELECTOR_SELECTION_MISMATCH:{key}")
    boundary = value.get("knowledge_boundary", {})
    if boundary.get("window_is_outcome_selected") is not True:
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_MISSING")
    if boundary.get(
        "accuracy_requires_new_history_matched_controls_and_common_support"
    ) is not True:
        raise ContractError("SELECTOR_ACCURACY_BOUNDARY_MISSING")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


_base_prepare_metadata = bridge._base_prepare_metadata
_base_build_manifest = bridge._base_build_manifest


def prepare_metadata(
    selector_freeze: Path,
    source_archive: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    _bind_adapter()
    metadata = _base_prepare_metadata(selector_freeze, source_archive, contract)
    metadata["reused_code"] = _require_reused_code_pins()
    return metadata


def build_manifest(
    metadata: Mapping[str, Any],
    image_rows: Sequence[Mapping[str, Any]],
    payload_identity: Mapping[str, Any],
    source_image_identity: Mapping[str, Any],
    renamed_image_identity: Mapping[str, Any],
    output_root: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    value = _base_build_manifest(
        metadata,
        image_rows,
        payload_identity,
        source_image_identity,
        renamed_image_identity,
        output_root,
        contract,
    )
    value["reused_a06_adapter"] = metadata["reused_code"]["a06_adapter"]
    value["selection"] = {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A09",
        "camera_indices_inclusive": [0, 6200],
        "camera_count": 6201,
        "camera_header_ns_inclusive": [
            contract.camera_first_ns,
            contract.camera_last_ns,
        ],
        "camera_zero_retained_with_shifted_imu_bracket": True,
        "first_legal_camera_source_index": 0,
        "preroll_source_camera_indices_inclusive": [0, 5999],
        "preroll_relative_indices_inclusive": [0, 5999],
        "score_source_camera_indices_inclusive": [6000, 6200],
        "score_relative_indices_inclusive": [6000, 6200],
        "score_camera_count": 201,
        "warm_start": True,
        "cold_start": False,
        "development_result_conditioned_selection": True,
        "imu_source_indices_inclusive_zero_based": [
            contract.imu_first_index,
            contract.imu_last_index,
        ],
        "imu_count": contract.imu_count,
        "imu_shift_ns": contract.imu_shift_ns,
        "synthetic_imu_samples_added": False,
    }
    value["reporting_boundary"] = (
        "development-only A09 natural-history input preparation; historical "
        "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
        "trajectory, accuracy, or ranking"
    )
    return value


def preflight_result(
    selector_freeze: Path,
    source_archive: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")
    metadata = prepare_metadata(selector_freeze, source_archive, contract)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "selector_freeze": metadata["selector"],
        "reused_code": metadata["reused_code"],
        "source": metadata["source"],
        "output_root": str(output_root.resolve(strict=False)),
        "camera_source_indices_inclusive": [0, 6200],
        "camera_count": 6201,
        "score_source_camera_indices_inclusive": [6000, 6200],
        "score_relative_indices_inclusive": [6000, 6200],
        "score_camera_count": 201,
        "imu_count": contract.imu_count,
        "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "claims": {
            "output_created": False,
            "hfnet_started": False,
            "trajectory_produced": False,
            "accuracy_evaluated": False,
        },
    }


# The reused A06 functions resolve these names from their defining module.
_ADAPTER_BINDINGS = {
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "SELECTOR_SCHEMA": SELECTOR_SCHEMA,
    "DEFAULT_SELECTOR_FREEZE": DEFAULT_SELECTOR_FREEZE,
    "SELECTOR_FREEZE_SIZE": SELECTOR_FREEZE_SIZE,
    "SELECTOR_FREEZE_SHA256": SELECTOR_FREEZE_SHA256,
    "DEFAULT_SOURCE_ARCHIVE": DEFAULT_SOURCE_ARCHIVE,
    "DEFAULT_OUTPUT_ROOT": DEFAULT_OUTPUT_ROOT,
    "PRODUCTION_CONTRACT": PRODUCTION_CONTRACT,
    "validate_selector": validate_selector,
    "prepare_metadata": prepare_metadata,
    "build_manifest": build_manifest,
    "preflight_result": preflight_result,
}


def _bind_adapter() -> None:
    for name, value in _ADAPTER_BINDINGS.items():
        setattr(adapter, name, value)


_base_materialize = adapter.materialize
_bind_adapter()


def materialize(
    selector_freeze: Path,
    source_archive: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    _bind_adapter()
    return _base_materialize(
        selector_freeze, source_archive, output_root, contract
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action", choices=("preflight", "materialize"), default="preflight"
    )
    value.add_argument(
        "--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE
    )
    value.add_argument(
        "--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE
    )
    value.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "materialize":
            result = materialize(
                args.selector_freeze,
                args.source_archive,
                args.output_root,
                PRODUCTION_CONTRACT,
            )
        else:
            result = preflight_result(
                args.selector_freeze,
                args.source_archive,
                args.output_root,
                PRODUCTION_CONTRACT,
            )
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {
                "hfnet_started": False,
                "trajectory_produced": False,
                "accuracy_evaluated": False,
            },
        }
        return_code = 2
    sys.stdout.buffer.write(core.canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
