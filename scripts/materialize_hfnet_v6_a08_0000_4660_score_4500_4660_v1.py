#!/usr/bin/env python3
"""Materialize the frozen A08 natural-history HFNet input, and nothing else.

The feed contains canonical AQUALOC archaeology source cameras 0..4660.
Cameras 0..4499 are history only and 4500..4660 are the sole score window.
Publication is atomic and no-clobber; this module starts no process.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, Optional, Sequence


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_a05_0001_3700_score_3300_3700_v1 as bridge


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a08-0000-4660-score-4500-4660-"
    "input-materialization-v1"
)
SELECTOR_SCHEMA = (
    "aqua-fe-hfnet-v6-a08-0000-4660-score-4500-4660-"
    "selector-freeze-v1"
)

A05_BRIDGE_PATH = (
    ROOT / "scripts/materialize_hfnet_v6_a05_0001_3700_score_3300_3700_v1.py"
)
A05_BRIDGE_SIZE = 12_729
A05_BRIDGE_SHA256 = (
    "ed9a9483216b9f4331cd70ec427c9215b7b0a2af222d5c18c3dbeffa39a69b3c"
)
A06_ADAPTER_PATH = (
    ROOT / "scripts/materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
)
A06_ADAPTER_SIZE = 16_321
A06_ADAPTER_SHA256 = (
    "2ac7025c70a7aac48783b0ee37e9586aae43c00927a1183304a88ad05f796264"
)

DEFAULT_SELECTOR_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a08_0000_4660_score_4500_4660_"
    "selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 4_960
SELECTOR_FREEZE_SHA256 = (
    "2cc49bb2311c87338a06f266e8557e5ac68fadad044d57f4b6bea09de7522ed7"
)

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a08_0000_4660_score_4500_4660_warmstart"
)

adapter = bridge.adapter
core = bridge.core
FilePin = core.FilePin
MaterializationContract = core.MaterializationContract
ContractError = core.ContractError


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=2_316_571_070,
        sha256=(
            "b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153"
        ),
    ),
    source_gzip_crc32="3ebe1f0c",
    source_gzip_isize=2_343_168_000,
    image_csv_member="raw_data/img_sequence_8.csv",
    image_csv_pin=FilePin(
        size_bytes=338_102,
        sha256=(
            "1137d5b60e618c5febfb62f6f89f0d261af206e2256d5bfac2bea6f0cbafe689"
        ),
        crc32="179269f8",
    ),
    imu_csv_member="raw_data/imu_sequence_8.csv",
    imu_csv_pin=FilePin(
        size_bytes=10_495_986,
        sha256=(
            "be4ce25d04d2a50b51474a072a14071f77e450dd78aff51e5ba8378f556c3643"
        ),
        crc32="6b630122",
    ),
    image_member_prefix="raw_data/images_sequence_8/",
    source_camera_count=9_391,
    source_imu_count=93_837,
    camera_start_index=0,
    camera_end_index=4_660,
    camera_first_ns=1_542_884_961_144_554_192,
    camera_last_ns=1_542_885_194_106_222_672,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=12,
    imu_last_index=46_570,
    imu_first_raw_ns=1_542_884_961_090_347_600,
    imu_last_raw_ns=1_542_885_194_055_132_080,
    imu_first_output_ns=1_542_884_961_144_041_712,
    imu_second_output_ns=1_542_884_961_146_933_296,
    imu_penultimate_output_ns=1_542_885_194_103_702_576,
    imu_last_output_ns=1_542_885_194_108_826_192,
    expected_image_total_bytes=None,
    expected_source_image_inventory_sha256=None,
    expected_source_image_inventory_crc32=None,
    expected_renamed_image_inventory_sha256=None,
    expected_renamed_image_inventory_crc32=None,
    times_pin=FilePin(
        size_bytes=93_220,
        sha256=(
            "0ce637bc6e9e74a300dee7b40eb18e84962106fb7fc867d5d0eae83bf47f7662"
        ),
        crc32="2d2d0119",
    ),
    camera_csv_pin=FilePin(
        size_bytes=205_109,
        sha256=(
            "43203c2d25a3d806397648558006bd8a21fdc7aa7f908b0099f44d5251c0c361"
        ),
        crc32="9d90eca7",
    ),
    imu_output_pin=FilePin(
        size_bytes=5_211_752,
        sha256=(
            "98b7ca7feab3913edce8803f131e29a2861b2883a8578882cc19eb858c919262"
        ),
        crc32="87378882",
    ),
    # Image and payload aggregates are derived during this additive
    # preparation, then independently recomputed by the separate auditor.
    expected_payload_sha256=None,
    expected_payload_crc32=None,
)


def _require_reused_code_pins() -> Dict[str, Any]:
    observed_bridge = core.identity_file(
        A05_BRIDGE_PATH, str(A05_BRIDGE_PATH.resolve())
    )
    if (
        observed_bridge["size_bytes"] != A05_BRIDGE_SIZE
        or observed_bridge["sha256"] != A05_BRIDGE_SHA256
    ):
        raise ContractError("REUSED_A05_BRIDGE_IDENTITY_MISMATCH")
    observed_adapter = core.identity_file(
        A06_ADAPTER_PATH, str(A06_ADAPTER_PATH.resolve())
    )
    if (
        observed_adapter["size_bytes"] != A06_ADAPTER_SIZE
        or observed_adapter["sha256"] != A06_ADAPTER_SHA256
    ):
        raise ContractError("REUSED_A06_ADAPTER_IDENTITY_MISMATCH")
    return {
        "a05_materializer_bridge": observed_bridge,
        "a06_adapter": observed_adapter,
    }


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
        "FROZEN_BEFORE_A08_MATERIALIZATION_AND_HFNET_PROCESS_START"
    ):
        raise ContractError("SELECTOR_STATUS_MISMATCH")
    selection = value.get("selection", {})
    required = {
        "sequence_id": "A08",
        "camera_indices_inclusive_for_feed": [0, 4660],
        "camera_count_for_feed": 4661,
        "camera_zero_included": True,
        "preroll_camera_indices_inclusive": [0, 4499],
        "score_camera_indices_inclusive": [4500, 4660],
        "score_camera_count": 161,
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
        "sequence_id": "A08",
        "camera_indices_inclusive": [0, 4660],
        "camera_count": 4661,
        "camera_header_ns_inclusive": [
            contract.camera_first_ns,
            contract.camera_last_ns,
        ],
        "camera_zero_retained_with_shifted_imu_bracket": True,
        "first_legal_camera_source_index": 0,
        "preroll_source_camera_indices_inclusive": [0, 4499],
        "preroll_relative_indices_inclusive": [0, 4499],
        "score_source_camera_indices_inclusive": [4500, 4660],
        "score_relative_indices_inclusive": [4500, 4660],
        "score_camera_count": 161,
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
        "development-only A08 natural-history input preparation; historical "
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
        "camera_source_indices_inclusive": [0, 4660],
        "camera_count": 4661,
        "score_source_camera_indices_inclusive": [4500, 4660],
        "score_relative_indices_inclusive": [4500, 4660],
        "score_camera_count": 161,
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


# Reused A06 functions resolve these names from their defining module.
for _name, _value in {
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
}.items():
    setattr(adapter, _name, _value)

materialize = adapter.materialize


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
