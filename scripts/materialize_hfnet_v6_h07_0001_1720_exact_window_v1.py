#!/usr/bin/env python3
"""Materialize the frozen H07 0001..1720 HFNet input, and nothing else.

The wrapper reuses the byte-validating H03 materialization primitives with a
separate H07 contract.  It atomically copies canonical PNG bytes, shifts IMU
timestamps by the calibrated Harbor offset, and never starts a scientific
process.  Source frame zero is deliberately excluded because it has no shifted
IMU predecessor and the official EuRoC entry would decrement first_imu to -1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_phase_f_h03_1800_3600_v1 as core


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-h07-0001-1720-input-materialization-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-h07-exact-window-selector-freeze-v1"

CORE_PATH = ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
CORE_SIZE = 38_774
CORE_SHA256 = "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d"

DEFAULT_SELECTOR_FREEZE = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_selector_freeze_v1.json"
SELECTOR_FREEZE_SIZE = 6_108
SELECTOR_FREEZE_SHA256 = "51430c83aa7b9870e1c1106f453cd527005c8adcd84990b544fecdea84294387"

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/aqualoc/samples/"
    "harbor_sequence_07_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_h07_exact_window_v1/"
    "aqualoc_harbor_h07_0001_1720"
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
        size_bytes=357_408_690,
        sha256="1ddcd260625ff6d69e1788c37f44cbc6a53495a7240475e46372ed9f2689961e",
    ),
    source_gzip_crc32="72f3d160",
    source_gzip_isize=361_728_000,
    image_csv_member="raw_data/harbor_img_sequence_07.csv",
    image_csv_pin=FilePin(
        size_bytes=81_422,
        sha256="fd44bcbb02f713454e7fee672eb6702cfa5f50d6797ac35251080d62a7750a90",
        crc32="abfdb882",
    ),
    imu_csv_member="raw_data/harbor_imu_sequence_07.csv",
    imu_csv_pin=FilePin(
        size_bytes=2_567_655,
        sha256="bcfd23d3cb643a64ac962c51f060ea4841eff5fb64677f5f4101d6be21b0ee74",
        crc32="9bd7f1d4",
    ),
    image_member_prefix="raw_data/harbor_images_sequence_07/",
    source_camera_count=2_261,
    source_imu_count=22_601,
    camera_start_index=1,
    camera_end_index=1_720,
    camera_first_ns=1_523_387_546_173_556_704,
    camera_last_ns=1_523_387_632_157_611_840,
    width=640,
    height=512,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=40_380_655,
    imu_first_index=4,
    imu_last_index=17_192,
    imu_first_raw_ns=1_523_387_546_131_621_952,
    imu_last_raw_ns=1_523_387_632_120_930_784,
    imu_first_output_ns=1_523_387_546_172_002_607,
    imu_second_output_ns=1_523_387_546_177_088_623,
    imu_penultimate_output_ns=1_523_387_632_156_272_303,
    imu_last_output_ns=1_523_387_632_161_311_439,
    expected_image_total_bytes=277_514_774,
    expected_source_image_inventory_sha256=(
        "ef94de2b061c3072cde56d6aa50faacd8b57f9fa3aee3dce03075a3fec002546"
    ),
    expected_source_image_inventory_crc32="a82e0ac8",
    expected_renamed_image_inventory_sha256=(
        "37ccac59d1a8a51820b2896d576522df403303e0f3191e8e1f87020de8d3d7d1"
    ),
    expected_renamed_image_inventory_crc32="3a307924",
    times_pin=FilePin(
        size_bytes=34_400,
        sha256="53b9b0590db89cec088a564098cc9445a9b9c8bd06cbbb47ceac6e055a46f3e2",
        crc32="8bbc4603",
    ),
    camera_csv_pin=FilePin(
        size_bytes=75_705,
        sha256="f2528507e8a44ce9d5d87e3267c2976fd195230cce23c03eae9270cd0dbf9567",
        crc32="7d81ccc4",
    ),
    imu_output_pin=FilePin(
        size_bytes=1_954_013,
        sha256="1aad764865eb6289f8202307b82081cc047a4fb37ff0c1beb34ad60b12db17f7",
        crc32="f21c7966",
    ),
    expected_payload_sha256=(
        "744300ce3ba1c295300af570df767ea731c887fe8110f97c67bef5810c0a2827"
    ),
    expected_payload_crc32="2a4e6ed3",
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
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise ContractError("SELECTOR_FREEZE_SCHEMA_MISMATCH")
    selection = value.get("selection", {})
    if selection.get("sequence_id") != "H07":
        raise ContractError("SELECTOR_SEQUENCE_MISMATCH")
    if selection.get("camera_indices_inclusive_for_feed") != [1, 1720]:
        raise ContractError("SELECTOR_FEED_RANGE_MISMATCH")
    if selection.get("score_camera_indices_inclusive") != [1660, 1720]:
        raise ContractError("SELECTOR_SCORE_RANGE_MISMATCH")
    sync = value.get("synchronization_boundary", {})
    if sync.get("camera0_has_shifted_imu_predecessor") is not False:
        raise ContractError("SELECTOR_CAMERA0_SYNC_RISK_MISSING")
    if sync.get("synthetic_or_extrapolated_imu_permitted") is not False:
        raise ContractError("SELECTOR_SYNTHETIC_IMU_NOT_FORBIDDEN")
    if value.get("selection", {}).get("development_result_conditioned_selection") is not True:
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_NOT_DISCLOSED")
    if any(item is not False for item in value.get("claims", {}).values()):
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
    generated = {
        "cam0_times": core.identity_bytes("cam0_times.txt", times_payload),
        "cam0_data_csv": core.identity_bytes("mav0/cam0/data.csv", camera_csv_payload),
        "imu0_data_csv": core.identity_bytes("mav0/imu0/data.csv", output_imu_payload),
    }
    core.require_pin(generated["cam0_times"], contract.times_pin, "CAM0_TIMES")
    core.require_pin(generated["cam0_data_csv"], contract.camera_csv_pin, "CAM0_DATA_CSV")
    core.require_pin(generated["imu0_data_csv"], contract.imu_output_pin, "IMU0_DATA_CSV")
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
        "generated_identities": generated,
        "imu_bracket": core.validate_imu_bracket(output_imu_payload, selected_camera, contract),
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
    histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
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
            "dataset_family": "aqualoc_harbor",
            "sequence_id": "H07",
            "camera_indices_inclusive": [1, 1720],
            "camera_count": contract.camera_count,
            "camera_header_ns_inclusive": [contract.camera_first_ns, contract.camera_last_ns],
            "preroll_source_indices_inclusive": [1, 1659],
            "score_camera_indices_inclusive": [1660, 1720],
            "score_relative_indices_inclusive": [1659, 1719],
            "score_camera_count": 61,
            "development_result_conditioned_selection": True,
            "source_frame_zero_excluded_before_run": True,
            "source_frame_zero_exclusion_reason": "no calibrated shifted-IMU predecessor; official first_imu-- would reach -1",
            "synthetic_or_extrapolated_imu_used": False,
            "imu_source_indices_inclusive_zero_based": [contract.imu_first_index, contract.imu_last_index],
            "imu_count": contract.imu_count,
            "imu_shift_ns": contract.imu_shift_ns,
            "imu_time_transform": "output_ns=raw_ns+40380655",
        },
        "camera": {
            "copy_policy": "canonical tar member PNG bytes copied unchanged",
            "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png",
            "count": len(image_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "640x512 8-bit grayscale non-interlaced PNG",
            "png_chunk_crc_all_valid": True,
            "png_idat_all_decompressed": True,
            "png_chunk_count_histogram": histogram,
            "source_member_inventory_identity": source_image_identity,
            "renamed_output_inventory_identity": renamed_image_identity,
            "files": list(image_rows),
        },
        "generated_files": metadata["generated_identities"],
        "imu": {
            "source_header": IMU_CSV_HEADER,
            "measurement_tokens_preserved": True,
            "axis_transform": "none; Harbor T_i_b is identity",
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
        image_rows, source_rows = core.stream_selected_images(
            source_archive, metadata["selected_camera"], staging, contract
        )
        image_total = sum(int(row["size_bytes"]) for row in image_rows)
        if contract.expected_image_total_bytes is not None and image_total != contract.expected_image_total_bytes:
            raise ContractError(f"SELECTED_IMAGE_TOTAL_SIZE_MISMATCH:{image_total}")
        source_identity = core.aggregate_identities(source_rows)
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
        "score_camera_indices_inclusive": [1660, 1720],
        "sync_boundary": {
            "source_frame_zero_excluded": True,
            "synthetic_or_extrapolated_imu_used": False,
            "reader_bracket": metadata["imu_bracket"],
        },
        "generated_identities": metadata["generated_identities"],
        "claims": {"output_created": False, "hfnet_started": False, "trajectory_produced": False},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    parser.add_argument("--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE)
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
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
