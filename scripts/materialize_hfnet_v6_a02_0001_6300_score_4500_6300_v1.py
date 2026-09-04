#!/usr/bin/env python3
"""Materialize the frozen A02 full-history HFNet input, and nothing else.

The feed contains canonical source cameras 1..6300.  Source camera 0 is
excluded because the shifted IMU stream has no predecessor for it; camera 1
is the first camera satisfying the author's reader bracket on both ends.  The
scientific score window remains source cameras 4500..6300 inclusive.

This preparation-only wrapper reuses the independently tested A06 adapter and
the sealed H03 streaming primitives.  It never starts HFNet, ROS, VINS, a
detector, or an evaluator and publishes its output atomically without clobber.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_a06_0000_2460_exact_window_v1 as adapter


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-a02-0001-6300-score-4500-6300-input-materialization-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-a02-full-history-selector-freeze-v1"

A06_ADAPTER_PATH = ROOT / "scripts/materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
A06_ADAPTER_SIZE = 16_321
A06_ADAPTER_SHA256 = "2ac7025c70a7aac48783b0ee37e9586aae43c00927a1183304a88ad05f796264"

DEFAULT_SELECTOR_FREEZE = (
    ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 3_320
SELECTOR_FREEZE_SHA256 = "54e1340a4fe655be30b971d89178e8c588b1b973a93e4287b6ed6dd39feb7505"

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a02_full_history_v1/"
    "aqualoc_archaeology_a02_0001_6300"
)

core = adapter.core
FilePin = core.FilePin
MaterializationContract = core.MaterializationContract
ContractError = core.ContractError


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=2_195_786_266,
        sha256="8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69",
    ),
    source_gzip_crc32="daa06f87",
    source_gzip_isize=2_223_994_880,
    image_csv_member="raw_data/img_sequence_2.csv",
    image_csv_pin=FilePin(
        size_bytes=323_558,
        sha256="a1781919532af0e1c7babe2a2676fd7cf7c112a7f4070da8ed868757eb67f05c",
        crc32="2aa8333e",
    ),
    imu_csv_member="raw_data/imu_sequence_2.csv",
    imu_csv_pin=FilePin(
        size_bytes=10_119_433,
        sha256="068db1d6eabba9b19bb3df4a922e5ff22b3f8120c6255896450a6d7adf34393c",
        crc32="6e3c8e19",
    ),
    image_member_prefix="raw_data/images_sequence_2/",
    source_camera_count=8_987,
    source_imu_count=89_795,
    camera_start_index=1,
    camera_end_index=6_300,
    camera_first_ns=1_542_828_791_787_420_320,
    camera_last_ns=1_542_829_106_687_510_592,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=2,
    imu_last_index=62_940,
    imu_first_raw_ns=1_542_828_791_729_615_232,
    imu_last_raw_ns=1_542_829_106_638_112_448,
    imu_first_output_ns=1_542_828_791_783_309_344,
    imu_second_output_ns=1_542_828_791_788_632_128,
    imu_penultimate_output_ns=1_542_829_106_686_399_136,
    imu_last_output_ns=1_542_829_106_691_806_560,
    expected_image_total_bytes=1_525_166_693,
    expected_source_image_inventory_sha256=(
        "b7d041a0fd0ce312d231b5f8bf2ff7fd4c74a31ce108758c8f8ccfb17cdc471d"
    ),
    expected_source_image_inventory_crc32="74c90c25",
    expected_renamed_image_inventory_sha256=(
        "1f06f9ddc43c8fdfd946719b389a1809d0194128c6ec5b963f13f9b27fa77ff0"
    ),
    expected_renamed_image_inventory_crc32="76115d23",
    times_pin=FilePin(
        size_bytes=126_000,
        sha256="0b117ff76aec9266260ffad4c075b6c669b8f816e7ab19f2f1bbf4d5b44d9d4d",
        crc32="8cd30fea",
    ),
    camera_csv_pin=FilePin(
        size_bytes=277_225,
        sha256="ad9f7795cc7ca931ece0e8294dcfe3af87a266cc7d656de6b233e964e8164113",
        crc32="796bb5d8",
    ),
    imu_output_pin=FilePin(
        size_bytes=7_100_776,
        sha256="accf260a3bc99dc90c91db33e57be9fe720f702362bd4c3dca17252c2d15cc47",
        crc32="93d98670",
    ),
    expected_payload_sha256=(
        "86d2730e32d82b37cf6811c73dfe6b66368fb208877911d7ca7720686e358a58"
    ),
    expected_payload_crc32="8481e897",
)


def _require_a06_adapter_pin() -> Dict[str, Any]:
    observed = core.identity_file(A06_ADAPTER_PATH, str(A06_ADAPTER_PATH.resolve()))
    if observed["size_bytes"] != A06_ADAPTER_SIZE or observed["sha256"] != A06_ADAPTER_SHA256:
        raise ContractError("REUSED_A06_ADAPTER_IDENTITY_MISMATCH")
    return observed


def validate_selector(path: Path) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("SELECTOR_FREEZE_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    if observed["size_bytes"] != SELECTOR_FREEZE_SIZE:
        raise ContractError("SELECTOR_FREEZE_SIZE_MISMATCH")
    if observed["sha256"] != SELECTOR_FREEZE_SHA256:
        raise ContractError("SELECTOR_FREEZE_SHA256_MISMATCH")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA or value.get("status") != "FROZEN_PREPARATION_ONLY_NO_PROCESS_START":
        raise ContractError("SELECTOR_SCHEMA_OR_STATUS_MISMATCH")
    selection = value.get("selection", {})
    if selection.get("sequence_id") != "A02":
        raise ContractError("SELECTOR_SEQUENCE_MISMATCH")
    if selection.get("camera_indices_inclusive_for_feed") != [1, 6300]:
        raise ContractError("SELECTOR_FEED_RANGE_MISMATCH")
    if selection.get("score_camera_indices_inclusive") != [4500, 6300]:
        raise ContractError("SELECTOR_SCORE_RANGE_MISMATCH")
    if selection.get("camera_count_for_feed") != 6300 or selection.get("score_camera_count") != 1801:
        raise ContractError("SELECTOR_COUNT_MISMATCH")
    boundary = value.get("knowledge_boundary", {})
    if boundary.get("development_result_conditioned_selection") is not True:
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_NOT_DISCLOSED")
    if boundary.get("p07_artifacts_are_read_only_and_must_not_be_backfilled") is not True:
        raise ContractError("SELECTOR_P07_BOUNDARY_MISSING")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


_base_prepare_metadata = adapter.prepare_metadata
_base_build_manifest = adapter.build_manifest


def prepare_metadata(
    selector_freeze: Path,
    source_archive: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    metadata = _base_prepare_metadata(selector_freeze, source_archive, contract)
    metadata["reused_a06_adapter"] = _require_a06_adapter_pin()
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
    value["reused_a06_adapter"] = metadata["reused_a06_adapter"]
    value["selection"] = {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A02",
        "camera_indices_inclusive": [1, 6300],
        "camera_count": 6300,
        "camera_header_ns_inclusive": [
            contract.camera_first_ns,
            contract.camera_last_ns,
        ],
        "camera_zero_trimmed_for_missing_shifted_imu_predecessor": True,
        "first_legal_camera_source_index": 1,
        "preroll_source_camera_indices_inclusive": [1, 4499],
        "preroll_relative_indices_inclusive": [0, 4498],
        "score_source_camera_indices_inclusive": [4500, 6300],
        "score_relative_indices_inclusive": [4499, 6299],
        "score_camera_count": 1801,
        "development_result_conditioned_selection": True,
        "imu_source_indices_inclusive_zero_based": [
            contract.imu_first_index,
            contract.imu_last_index,
        ],
        "imu_count": contract.imu_count,
        "imu_shift_ns": contract.imu_shift_ns,
        "imu_time_transform": "output_ns=raw_ns+53694112",
        "synthetic_imu_samples_added": False,
    }
    value["reporting_boundary"] = (
        "development-only full-history preparation; legacy A02/P07 artifacts remain read-only; "
        "no trajectory, accuracy, or comparison"
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
        "reused_a06_adapter": metadata["reused_a06_adapter"],
        "source": metadata["source"],
        "output_root": str(output_root.resolve(strict=False)),
        "camera_count": contract.camera_count,
        "camera_source_indices_inclusive": [1, 6300],
        "score_source_camera_indices_inclusive": [4500, 6300],
        "score_relative_indices_inclusive": [4499, 6299],
        "imu_count": contract.imu_count,
        "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "claims": {
            "output_created": False,
            "hfnet_started": False,
            "trajectory_produced": False,
        },
    }


# Configure the reused A06 implementation. Its functions retain adapter-module
# globals, so all assignments are explicit and fail closed.
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
    value.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    value.add_argument("--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE)
    value.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    value.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "materialize":
            result = materialize(args.selector_freeze, args.source_archive, args.output_root, PRODUCTION_CONTRACT)
        else:
            result = preflight_result(args.selector_freeze, args.source_archive, args.output_root, PRODUCTION_CONTRACT)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {"hfnet_started": False, "trajectory_produced": False},
        }
        return_code = 2
    sys.stdout.buffer.write(core.canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
