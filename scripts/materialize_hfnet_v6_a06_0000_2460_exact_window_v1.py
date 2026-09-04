#!/usr/bin/env python3
"""Prepare the frozen A06 HFNet-SLAM exact-window input, and nothing else.

This deliberately small wrapper reuses the already tested H03 Phase-F
materialization primitives.  It supplies a separately frozen A06 contract and
dataset-specific manifest, publishes atomically, and never starts HFNet, ROS,
VINS, a detector, a trajectory evaluator, or any other scientific process.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_phase_f_h03_1800_3600_v1 as core


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-a06-0000-2460-input-materialization-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-a06-exact-window-selector-freeze-v1"

CORE_PATH = ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
CORE_SIZE = 38_774
CORE_SHA256 = "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d"

DEFAULT_SELECTOR_FREEZE = (
    ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 8_273
SELECTOR_FREEZE_SHA256 = "1d0937320c087cb73911db7a5c55d8cde40d0bf0c800c4cf42aba68342b72b15"

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_6_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
    "aqualoc_archaeology_a06_0000_2460"
)

FilePin = core.FilePin
MaterializationContract = core.MaterializationContract
ContractError = core.ContractError
IMAGE_CSV_HEADER = core.IMAGE_CSV_HEADER
CAMERA_OUTPUT_CSV_HEADER = core.CAMERA_OUTPUT_CSV_HEADER
IMU_CSV_HEADER = core.IMU_CSV_HEADER


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=758_010_849,
        sha256="02795e92984321d61cbf7ee5555cf2b4ee344e2263bb7dcf37ffd94cb2472bd9",
    ),
    source_gzip_crc32="48e175ef",
    source_gzip_isize=768_358_400,
    image_csv_member="raw_data/img_sequence_6.csv",
    image_csv_pin=FilePin(
        size_bytes=121_886,
        sha256="4cb417cc2ad306f921c37edb0ec19c8117fd295d0d0aa099620a303e8d2af134",
        crc32="6f9a4e6e",
    ),
    imu_csv_member="raw_data/imu_sequence_6.csv",
    imu_csv_pin=FilePin(
        size_bytes=3_784_801,
        sha256="c78de2f43971b00721c95b74f99c4ad6cbad4d131d9ace2c73c0d7a118125ca7",
        crc32="e418b047",
    ),
    image_member_prefix="raw_data/images_sequence_6/",
    source_camera_count=3_385,
    source_imu_count=33_833,
    camera_start_index=0,
    camera_end_index=2_460,
    camera_first_ns=1_542_883_311_780_022_336,
    camera_last_ns=1_542_883_434_765_650_624,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=8,
    imu_last_index=24_588,
    imu_first_raw_ns=1_542_883_311_724_266_784,
    imu_last_raw_ns=1_542_883_434_713_537_344,
    imu_first_output_ns=1_542_883_311_777_960_896,
    imu_second_output_ns=1_542_883_311_783_094_496,
    imu_penultimate_output_ns=1_542_883_434_762_137_952,
    imu_last_output_ns=1_542_883_434_767_231_456,
    expected_image_total_bytes=544_207_164,
    expected_source_image_inventory_sha256=(
        "5db91b0aaece01781f6f65b70f7bca082cb70569176914ab7bc7ed8adb354159"
    ),
    expected_source_image_inventory_crc32="a7f6362d",
    expected_renamed_image_inventory_sha256=(
        "1dee6b53ef749584f218316701f40fbddbcf4be3fd17e24cae1f1f3a12073193"
    ),
    expected_renamed_image_inventory_crc32="03c2d990",
    times_pin=FilePin(
        size_bytes=49_220,
        sha256="7b81913749fe5b296aae4280531e6e26cda3349791e7331befdb72eb6de7f861",
        crc32="ab59a657",
    ),
    camera_csv_pin=FilePin(
        size_bytes=108_309,
        sha256="91ccea67a551f15090e6136dd754fa6cae00eeece798b3b025c0c1209928eb23",
        crc32="f5fd3504",
    ),
    imu_output_pin=FilePin(
        size_bytes=2_749_671,
        sha256="2e5d9a78192d86d6de55a46f9c29a1f639536e114702b5f9b0480c070d0a9388",
        crc32="40a84fd6",
    ),
    expected_payload_sha256=(
        "a03a119b98ec4c3a862905692325133310acae6d268cabaf7369262803b36673"
    ),
    expected_payload_crc32="489e46af",
)


def _require_core_pin() -> Dict[str, Any]:
    observed = core.identity_file(CORE_PATH, str(CORE_PATH.resolve()))
    if observed["size_bytes"] != CORE_SIZE or observed["sha256"] != CORE_SHA256:
        raise ContractError("REUSED_CORE_IDENTITY_MISMATCH")
    return observed


def validate_selector(path: Path) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("SELECTOR_FREEZE_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    if observed["size_bytes"] != SELECTOR_FREEZE_SIZE:
        raise ContractError("SELECTOR_FREEZE_SIZE_MISMATCH")
    if observed["sha256"] != SELECTOR_FREEZE_SHA256:
        raise ContractError("SELECTOR_FREEZE_SHA256_MISMATCH")
    value = __import__("json").loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise ContractError("SELECTOR_FREEZE_SCHEMA_MISMATCH")
    selection = value.get("selection", {})
    if selection.get("sequence_id") != "A06":
        raise ContractError("SELECTOR_SEQUENCE_MISMATCH")
    if selection.get("camera_indices_inclusive_for_feed") != [0, 2460]:
        raise ContractError("SELECTOR_FEED_RANGE_MISMATCH")
    if selection.get("score_camera_indices_inclusive") != [2210, 2460]:
        raise ContractError("SELECTOR_SCORE_RANGE_MISMATCH")
    boundary = value.get("knowledge_boundary", {})
    if boundary.get("development_result_conditioned_selection") is not True:
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_NOT_DISCLOSED")
    claims = value.get("claims", {})
    if any(value is not False for value in claims.values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


def prepare_metadata(
    selector_freeze: Path,
    source_archive: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    reused_core = _require_core_pin()
    selector = validate_selector(selector_freeze)
    source = core.validate_source_archive(source_archive, contract)
    image_payload, image_member = core.read_pinned_member(
        source_archive, contract.image_csv_member, contract.image_csv_pin, "IMAGE_CSV"
    )
    imu_payload, imu_member = core.read_pinned_member(
        source_archive, contract.imu_csv_member, contract.imu_csv_pin, "IMU_CSV"
    )
    _, selected_camera = core.parse_camera_rows(image_payload, contract)
    _, selected_imu = core.parse_imu_rows(imu_payload, selected_camera, contract)
    times_payload = core.camera_times_bytes(selected_camera)
    camera_csv_payload = core.camera_csv_bytes(selected_camera)
    output_imu_payload = core.imu_csv_bytes(selected_imu, contract.imu_shift_ns)
    times_identity = core.identity_bytes("cam0_times.txt", times_payload)
    camera_csv_identity = core.identity_bytes("mav0/cam0/data.csv", camera_csv_payload)
    imu_identity = core.identity_bytes("mav0/imu0/data.csv", output_imu_payload)
    core.require_pin(times_identity, contract.times_pin, "CAM0_TIMES")
    core.require_pin(camera_csv_identity, contract.camera_csv_pin, "CAM0_DATA_CSV")
    core.require_pin(imu_identity, contract.imu_output_pin, "IMU0_DATA_CSV")
    bracket = core.validate_imu_bracket(output_imu_payload, selected_camera, contract)
    return {
        "reused_core": reused_core,
        "selector": selector,
        "source": source,
        "source_members": {"camera_csv": image_member, "imu_csv": imu_member},
        "selected_camera": selected_camera,
        "selected_imu": selected_imu,
        "times_payload": times_payload,
        "camera_csv_payload": camera_csv_payload,
        "imu_payload": output_imu_payload,
        "generated_identities": {
            "cam0_times": times_identity,
            "cam0_data_csv": camera_csv_identity,
            "imu0_data_csv": imu_identity,
        },
        "imu_bracket": bracket,
    }


def build_manifest(
    metadata: Mapping[str, Any],
    image_rows: Sequence[Mapping[str, Any]],
    payload_identity: Mapping[str, Any],
    source_image_identity: Mapping[str, Any],
    renamed_image_identity: Mapping[str, Any],
    output_root: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    chunk_histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        chunk_histogram[key] = chunk_histogram.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "reused_sealed_core": metadata["reused_core"],
        "selector_freeze": metadata["selector"],
        "source": {
            **metadata["source"],
            "members": metadata["source_members"],
            "gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "selection": {
            "dataset_family": "aqualoc_archaeology",
            "sequence_id": "A06",
            "camera_indices_inclusive": [0, 2460],
            "camera_count": contract.camera_count,
            "camera_header_ns_inclusive": [contract.camera_first_ns, contract.camera_last_ns],
            "preroll_camera_indices_half_open": [0, 2210],
            "score_camera_indices_inclusive": [2210, 2460],
            "score_camera_count": 251,
            "development_result_conditioned_selection": True,
            "imu_source_indices_inclusive_zero_based": [contract.imu_first_index, contract.imu_last_index],
            "imu_count": contract.imu_count,
            "imu_shift_ns": contract.imu_shift_ns,
            "imu_time_transform": "output_ns=raw_ns+53694112",
        },
        "camera": {
            "copy_policy": "canonical tar member PNG bytes copied unchanged",
            "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png",
            "count": len(image_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "png_chunk_crc_all_valid": True,
            "png_idat_all_decompressed": True,
            "png_chunk_count_histogram": chunk_histogram,
            "source_member_inventory_identity": source_image_identity,
            "renamed_output_inventory_identity": renamed_image_identity,
            "files": list(image_rows),
        },
        "generated_files": metadata["generated_identities"],
        "imu": {
            "source_header": IMU_CSV_HEADER,
            "measurement_tokens_preserved": True,
            "axis_transform": "none; A06 Archaeology T_i_b is identity",
            "final_newline": False,
            "bracket_audit": metadata["imu_bracket"],
        },
        "payload_identity_excluding_manifest": payload_identity,
        "payload_file_count_excluding_manifest": len(image_rows) + 3,
        "reporting_boundary": "development-only preparation; no trajectory, accuracy, or comparison",
        "claims": {
            "runner_created": False,
            "start_claim_created": False,
            "hfnet_started": False,
            "vins_started": False,
            "detector_started": False,
            "evaluator_started": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
            "scientific_comparison_produced": False,
        },
    }


def materialize(
    selector_freeze: Path,
    source_archive: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    metadata = prepare_metadata(selector_freeze, source_archive, contract)
    with core.atomic_directory(output_root) as staging:
        image_rows, source_image_rows = core.stream_selected_images(
            source_archive, metadata["selected_camera"], staging, contract
        )
        image_total = sum(int(row["size_bytes"]) for row in image_rows)
        if contract.expected_image_total_bytes is not None and image_total != contract.expected_image_total_bytes:
            raise ContractError(f"SELECTED_IMAGE_TOTAL_SIZE_MISMATCH:{image_total}")
        source_identity = core.aggregate_identities(source_image_rows)
        renamed_identity = core.aggregate_identities(image_rows)
        core.enforce_expected_aggregate(source_identity, contract.expected_source_image_inventory_sha256, contract.expected_source_image_inventory_crc32, "SOURCE_IMAGE_INVENTORY")
        core.enforce_expected_aggregate(renamed_identity, contract.expected_renamed_image_inventory_sha256, contract.expected_renamed_image_inventory_crc32, "RENAMED_IMAGE_INVENTORY")
        generated = metadata["generated_identities"]
        core.write_exclusive_bytes(staging / "cam0_times.txt", metadata["times_payload"])
        core.write_exclusive_bytes(staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"])
        core.write_exclusive_bytes(staging / "mav0/imu0/data.csv", metadata["imu_payload"])
        payload_rows: List[Mapping[str, Any]] = list(image_rows)
        payload_rows.extend([generated["cam0_times"], generated["cam0_data_csv"], generated["imu0_data_csv"]])
        payload_identity = core.aggregate_identities(payload_rows)
        core.enforce_expected_aggregate(payload_identity, contract.expected_payload_sha256, contract.expected_payload_crc32, "PAYLOAD_IDENTITY")
        manifest = build_manifest(metadata, image_rows, payload_identity, source_identity, renamed_identity, output_root, contract)
        core.write_exclusive_bytes(staging / "materialization_manifest.json", core.canonical_json(manifest))
        for directory in (staging / "mav0/cam0/data", staging / "mav0/cam0", staging / "mav0/imu0", staging / "mav0", staging):
            core.fsync_directory(directory)
    return manifest


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
        "source": metadata["source"],
        "output_root": str(output_root.resolve(strict=False)),
        "camera_count": contract.camera_count,
        "imu_count": contract.imu_count,
        "score_camera_indices_inclusive": [2210, 2460],
        "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "claims": {"output_created": False, "hfnet_started": False, "trajectory_produced": False},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    parser.add_argument("--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE)
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = materialize(args.selector_freeze, args.source_archive, args.output_root) if args.action == "materialize" else preflight_result(args.selector_freeze, args.source_archive, args.output_root)
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
