#!/usr/bin/env python3
"""Prepare and audit the A09 4000..4400 HFNet cold-start input only.

The canonical raw AQUALOC tar members are copied byte-for-byte.  The existing
401-frame ROS bag is deliberately not used as the image source: it stores
decoded ``sensor_msgs/Image`` mono8 rasters and therefore no longer contains
the source PNG container, IDAT, or chunk-CRC bytes.  The bag remains pinned as
window-selection evidence.

This module reuses the sealed A06 materialization and independent-audit
primitives, the A06 archaeology clock shift, and the byte-pinned A06
archaeology configuration.  Publication is atomic and no-clobber.  It contains
no process launcher and never starts HFNet, ROS, VINS, a detector, or an
evaluator.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tarfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import zlib


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import audit_hfnet_v6_a06_0000_2460_exact_window_input_v1 as a06_audit
from scripts import materialize_hfnet_v6_a06_0000_2460_exact_window_v1 as a06


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-positive-a09-4000-4400-coldstart-materialization-v1"
AUDIT_SCHEMA_VERSION = (
    "aqua-fe-hfnet-positive-a09-4000-4400-coldstart-independent-audit-v1"
)

A06_ADAPTER_PATH = ROOT / "scripts/materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
A06_ADAPTER_SIZE = 16_321
A06_ADAPTER_SHA256 = "2ac7025c70a7aac48783b0ee37e9586aae43c00927a1183304a88ad05f796264"
A06_AUDITOR_PATH = ROOT / "scripts/audit_hfnet_v6_a06_0000_2460_exact_window_input_v1.py"
A06_AUDITOR_SIZE = 17_765
A06_AUDITOR_SHA256 = "b41412233b3c403d0ca8fb2841374a3c97484cce7bbe260bb4be8c780a46d3a2"

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
DEFAULT_SHORT_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo09_4000_4400.bag"
DEFAULT_CONFIG = (
    ROOT / "configs/published_baselines/"
    "hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a09_4000_4400_coldstart"
)

SHORT_BAG_SIZE = 98_167_227
SHORT_BAG_SHA256 = "ddc41e776b12bdf5f22a043a5862eba049d1c1494a2ab500ac2bf7893b5d9c54"
CONFIG_SIZE = 2_037
CONFIG_SHA256 = "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"

CONFIG_REQUIRED_TOKENS = (
    'Camera.type: "PinHole"',
    "Camera1.fx: 543.3327734182214",
    "Camera1.fy: 542.3987729825660",
    "Camera1.cx: 489.0253604224790",
    "Camera1.cy: 305.3872771200281",
    "Camera1.k1: -0.1255945656257394",
    "Camera1.k2: 0.053221287232781606",
    "Camera1.p1: 0.0000994070021080493",
    "Camera1.p2: 0.00009550660927242349",
    "Camera.width: 968",
    "Camera.height: 608",
    "Camera.fps: 20",
    "Camera.RGB: 1",
    "IMU.NoiseGyro: 0.003",
    "IMU.NoiseAcc: 0.05",
    "IMU.GyroWalk: 0.0001",
    "IMU.AccWalk: 0.0015",
    "IMU.Frequency: 200.0",
    'Extractor.type: "HFNetRT"',
    "Extractor.scaleFactor: 1.2",
    "Extractor.nLevels: 4",
    "Extractor.nFeatures: 675",
    "Extractor.threshold: 0.01",
    "loopClosing: 1",
)

FilePin = a06.FilePin
MaterializationContract = a06.MaterializationContract
ContractError = a06.ContractError
IMAGE_CSV_HEADER = a06.IMAGE_CSV_HEADER
CAMERA_OUTPUT_CSV_HEADER = a06.CAMERA_OUTPUT_CSV_HEADER
IMU_CSV_HEADER = a06.IMU_CSV_HEADER
core = a06.core


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=1_722_658_380,
        sha256="4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901",
    ),
    source_gzip_crc32="b2f3021d",
    source_gzip_isize=1_742_161_920,
    image_csv_member="raw_data/img_sequence_9.csv",
    image_csv_pin=FilePin(
        size_bytes=251_738,
        sha256="29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a",
        crc32="6ab5e1f7",
    ),
    imu_csv_member="raw_data/imu_sequence_9.csv",
    imu_csv_pin=FilePin(
        size_bytes=7_806_649,
        sha256="9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3",
        crc32="cc6033a9",
    ),
    image_member_prefix="raw_data/images_sequence_9/",
    source_camera_count=6_992,
    source_imu_count=69_861,
    camera_start_index=4_000,
    camera_end_index=4_400,
    camera_first_ns=1_542_888_946_038_630_384,
    camera_last_ns=1_542_888_966_034_698_672,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=39_967,
    imu_last_index=43_964,
    imu_first_raw_ns=1_542_888_945_983_034_352,
    imu_last_raw_ns=1_542_888_965_983_692_976,
    imu_first_output_ns=1_542_888_946_036_728_464,
    imu_second_output_ns=1_542_888_946_039_581_808,
    imu_penultimate_output_ns=1_542_888_966_032_163_568,
    imu_last_output_ns=1_542_888_966_037_387_088,
    expected_image_total_bytes=92_450_247,
    expected_source_image_inventory_sha256=(
        "2d9b9cfa043b69cab1b02fa236e7f5fa5f7af80450df226462b22c661f3656ce"
    ),
    expected_source_image_inventory_crc32="751aa11b",
    expected_renamed_image_inventory_sha256=(
        "a8a5b0411018e0b3bac1c57a2023afbee80ee59e73cf0876636879c35180564e"
    ),
    expected_renamed_image_inventory_crc32="49442874",
    times_pin=FilePin(
        size_bytes=8_020,
        sha256="f73f70dd4b5fe145665140dd38a0427229295661d215ce26958953867aa4fce9",
        crc32="e2460a7e",
    ),
    camera_csv_pin=FilePin(
        size_bytes=17_669,
        sha256="0bb8e8e82ed0ab120c3266cce559f7b46de469c447f4c87b7cbca88115a32784",
        crc32="0dec02c8",
    ),
    imu_output_pin=FilePin(
        size_bytes=447_436,
        sha256="b762654638307b994923c7ebc822e411cf5723853f0e430c6a43a535c5491c53",
        crc32="b9975f9f",
    ),
    expected_payload_sha256=(
        "552c3865562d8135037135971e4a24d7776492d608e2bd42b957de74e94f6c08"
    ),
    expected_payload_crc32="38ef5e97",
)


def _require_identity(path: Path, pin: FilePin, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    core.require_pin(observed, pin, label)
    return observed


def _require_provenance(short_bag: Path, config: Path) -> Dict[str, Any]:
    adapter = _require_identity(
        A06_ADAPTER_PATH,
        FilePin(A06_ADAPTER_SIZE, A06_ADAPTER_SHA256),
        "REUSED_A06_ADAPTER",
    )
    sealed_core = a06._require_core_pin()
    auditor = _require_identity(
        A06_AUDITOR_PATH,
        FilePin(A06_AUDITOR_SIZE, A06_AUDITOR_SHA256),
        "REUSED_A06_AUDITOR",
    )
    bag = _require_identity(
        short_bag,
        FilePin(SHORT_BAG_SIZE, SHORT_BAG_SHA256),
        "SHORT_BAG",
    )
    configuration = _require_identity(
        config,
        FilePin(CONFIG_SIZE, CONFIG_SHA256),
        "ARCHAEOLOGY_CONFIG",
    )
    config_text = config.read_text(encoding="utf-8")
    missing = [token for token in CONFIG_REQUIRED_TOKENS if token not in config_text]
    if missing:
        raise ContractError(f"ARCHAEOLOGY_CONFIG_SEMANTIC_DRIFT:{missing[0]}")
    return {
        "reused_a06_adapter": adapter,
        "reused_a06_sealed_core": sealed_core,
        "reused_a06_independent_auditor": auditor,
        "archaeology_config": {
            **configuration,
            "reuse_policy": "byte-identical A06 archaeology calibration and algorithm semantics",
            "imu_clock_policy": (
                "raw IMU timestamps shifted +53694112 ns because HFNet-SLAM has no td field"
            ),
        },
        "source_choice": {
            "selected": "canonical_raw_archive_png_members",
            "rejected_alternative": {
                **bag,
                "camera_topic": "/camera/image_raw",
                "camera_message_type": "sensor_msgs/Image",
                "camera_count": 401,
                "encoding": "mono8",
                "width": 968,
                "height": 608,
                "bytes_per_image": 588_544,
                "camera_header_ns_inclusive": [
                    1_542_888_946_038_630_384,
                    1_542_888_966_034_698_672,
                ],
                "canonical_png_container_bytes_available": False,
                "reason": (
                    "decoded raster messages preserve pixels but not source PNG signature, "
                    "chunks, IDAT bytes, or chunk CRCs"
                ),
            },
        },
    }


def _require_output_absent(output_root: Path) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")


def prepare_metadata(
    source_archive: Path,
    short_bag: Path,
    config: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    provenance = _require_provenance(short_bag, config)
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
    bracket = core.validate_imu_bracket(output_imu_payload, selected_camera, contract)
    return {
        **provenance,
        "source": source,
        "source_members": {"camera_csv": image_member, "imu_csv": imu_member},
        "selected_camera": selected_camera,
        "selected_imu": selected_imu,
        "times_payload": times_payload,
        "camera_csv_payload": camera_csv_payload,
        "imu_payload": output_imu_payload,
        "generated_identities": generated,
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
    histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "reused_sealed_implementation": {
            "a06_adapter": metadata["reused_a06_adapter"],
            "a06_core": metadata["reused_a06_sealed_core"],
            "a06_independent_auditor": metadata["reused_a06_independent_auditor"],
        },
        "configuration_authority": metadata["archaeology_config"],
        "source_choice": metadata["source_choice"],
        "source": {
            **metadata["source"],
            "members": metadata["source_members"],
            "gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "selection": {
            "dataset_family": "aqualoc_archaeology",
            "sequence_id": "A09",
            "window_id": "A09_4000_4400",
            "cold_start": True,
            "camera_indices_inclusive": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "camera_count": contract.camera_count,
            "camera_header_ns_inclusive": [
                contract.camera_first_ns,
                contract.camera_last_ns,
            ],
            "development_result_conditioned_selection": True,
            "held_out_confirmatory_claim_permitted": False,
            "imu_source_indices_inclusive_zero_based": [
                contract.imu_first_index,
                contract.imu_last_index,
            ],
            "imu_count": contract.imu_count,
            "imu_shift_ns": contract.imu_shift_ns,
            "imu_time_transform": "output_ns=raw_ns+53694112",
            "synthetic_or_extrapolated_imu_used": False,
        },
        "camera": {
            "copy_policy": "canonical tar member PNG bytes copied unchanged",
            "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png",
            "count": len(image_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
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
            "axis_transform": "none; AQUALOC Archaeology T_i_b is identity",
            "final_newline": False,
            "bracket_audit": metadata["imu_bracket"],
        },
        "payload_identity_excluding_manifest": payload_identity,
        "payload_file_count_excluding_manifest": len(image_rows) + 3,
        "reporting_boundary": (
            "development-only learned-active positive input preparation; "
            "no trajectory, accuracy, or comparison"
        ),
        "claims": {
            "runner_created": False,
            "start_claim_created": False,
            "hfnet_started": False,
            "ros_started": False,
            "vins_started": False,
            "detector_started": False,
            "evaluator_started": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
            "scientific_comparison_produced": False,
        },
    }


def materialize(
    source_archive: Path,
    short_bag: Path,
    config: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    _require_output_absent(output_root)
    metadata = prepare_metadata(source_archive, short_bag, config, contract)
    with core.atomic_directory(output_root) as staging:
        image_rows, source_rows = core.stream_selected_images(
            source_archive, metadata["selected_camera"], staging, contract
        )
        image_total = sum(int(row["size_bytes"]) for row in image_rows)
        if (
            contract.expected_image_total_bytes is not None
            and image_total != contract.expected_image_total_bytes
        ):
            raise ContractError(f"SELECTED_IMAGE_TOTAL_SIZE_MISMATCH:{image_total}")
        source_identity = core.aggregate_identities(source_rows)
        renamed_identity = core.aggregate_identities(image_rows)
        core.enforce_expected_aggregate(
            source_identity,
            contract.expected_source_image_inventory_sha256,
            contract.expected_source_image_inventory_crc32,
            "SOURCE_IMAGE_INVENTORY",
        )
        core.enforce_expected_aggregate(
            renamed_identity,
            contract.expected_renamed_image_inventory_sha256,
            contract.expected_renamed_image_inventory_crc32,
            "RENAMED_IMAGE_INVENTORY",
        )
        generated = metadata["generated_identities"]
        core.write_exclusive_bytes(staging / "cam0_times.txt", metadata["times_payload"])
        core.write_exclusive_bytes(
            staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"]
        )
        core.write_exclusive_bytes(staging / "mav0/imu0/data.csv", metadata["imu_payload"])
        payload_rows: List[Mapping[str, Any]] = list(image_rows)
        payload_rows.extend(
            [generated["cam0_times"], generated["cam0_data_csv"], generated["imu0_data_csv"]]
        )
        payload_identity = core.aggregate_identities(payload_rows)
        core.enforce_expected_aggregate(
            payload_identity,
            contract.expected_payload_sha256,
            contract.expected_payload_crc32,
            "PAYLOAD_IDENTITY",
        )
        manifest = build_manifest(
            metadata,
            image_rows,
            payload_identity,
            source_identity,
            renamed_identity,
            output_root,
            contract,
        )
        core.write_exclusive_bytes(
            staging / "materialization_manifest.json", core.canonical_json(manifest)
        )
        for directory in (
            staging / "mav0/cam0/data",
            staging / "mav0/cam0",
            staging / "mav0/imu0",
            staging / "mav0",
            staging,
        ):
            core.fsync_directory(directory)
    return manifest


def preflight_result(
    source_archive: Path,
    short_bag: Path,
    config: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    _require_output_absent(output_root)
    metadata = prepare_metadata(source_archive, short_bag, config, contract)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "source": metadata["source"],
        "source_choice": metadata["source_choice"],
        "configuration_authority": metadata["archaeology_config"],
        "camera_indices_inclusive": [contract.camera_start_index, contract.camera_end_index],
        "camera_count": contract.camera_count,
        "imu_count": contract.imu_count,
        "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "claims": {
            "output_created": False,
            "hfnet_started": False,
            "ros_started": False,
            "vins_started": False,
            "trajectory_produced": False,
        },
    }


def _parse_output_camera(
    root: Path, contract: MaterializationContract
) -> Tuple[List[int], List[Dict[str, Any]], Dict[str, int]]:
    times_payload = (root / "cam0_times.txt").read_bytes()
    if not times_payload.endswith(b"\n"):
        raise ContractError("AUDIT_CAM0_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in times_payload.decode("ascii").splitlines()]
    except ValueError as error:
        raise ContractError("AUDIT_CAM0_TIMES_INVALID") from error
    if (
        len(stamps) != contract.camera_count
        or stamps[0] != contract.camera_first_ns
        or stamps[-1] != contract.camera_last_ns
    ):
        raise ContractError("AUDIT_CAMERA_COUNT_OR_ENDPOINT_MISMATCH")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise ContractError("AUDIT_CAMERA_TIMES_NON_MONOTONIC")
    csv_lines = (root / "mav0/cam0/data.csv").read_text(encoding="ascii").splitlines()
    if not csv_lines or csv_lines[0] != CAMERA_OUTPUT_CSV_HEADER:
        raise ContractError("AUDIT_CAMERA_CSV_HEADER_MISMATCH")
    if csv_lines[1:] != [f"{stamp},{stamp}.png" for stamp in stamps]:
        raise ContractError("AUDIT_CAMERA_CSV_MAPPING_MISMATCH")
    rows: List[Dict[str, Any]] = []
    histogram: Dict[str, int] = {}
    for relative_index, stamp in enumerate(stamps):
        relative = f"mav0/cam0/data/{stamp}.png"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"AUDIT_IMAGE_MISSING_OR_NOT_REGULAR:{stamp}")
        payload = path.read_bytes()
        png = a06_audit.validate_png(payload)
        key = str(png["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
        rows.append(
            {
                **core.identity_bytes(relative, payload),
                "source_index": contract.camera_start_index + relative_index,
                "source_member": (
                    contract.image_member_prefix
                    + f"frame{contract.camera_start_index + relative_index:06d}.png"
                ),
                "camera_timestamp_ns": stamp,
            }
        )
    return stamps, rows, histogram


def _audit_source_stream(
    source_archive: Path,
    output_rows: Sequence[Mapping[str, Any]],
    contract: MaterializationContract,
) -> Dict[str, Any]:
    expected = {
        f"frame{int(row['source_index']):06d}.png": row for row in output_rows
    }
    csv_payloads: Dict[str, bytes] = {}
    csv_identities: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()
    try:
        with tarfile.open(str(source_archive), "r|gz") as tar:
            for member in tar:
                if member.name in (contract.image_csv_member, contract.imu_csv_member):
                    if member.name in csv_payloads:
                        raise ContractError(f"AUDIT_SOURCE_CSV_DUPLICATE:{member.name}")
                    if not member.isreg() or member.issym() or member.islnk():
                        raise ContractError(f"AUDIT_SOURCE_CSV_NOT_REGULAR:{member.name}")
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise ContractError(f"AUDIT_SOURCE_CSV_UNREADABLE:{member.name}")
                    payload = extracted.read()
                    csv_payloads[member.name] = payload
                    csv_identities[member.name] = core.identity_bytes(member.name, payload)
                    continue
                if not member.name.startswith(contract.image_member_prefix):
                    continue
                name = member.name[len(contract.image_member_prefix) :]
                output = expected.get(name)
                if output is None:
                    continue
                if name in seen or not member.isreg() or member.issym() or member.islnk():
                    raise ContractError(f"AUDIT_SOURCE_IMAGE_MEMBER_INVALID:{name}")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ContractError(f"AUDIT_SOURCE_IMAGE_UNREADABLE:{name}")
                payload = extracted.read()
                observed = core.identity_bytes(str(output["path"]), payload)
                for key in ("size_bytes", "sha256", "crc32"):
                    if observed[key] != output[key]:
                        raise ContractError(f"AUDIT_SOURCE_OUTPUT_BYTES_DIFFER:{name}")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise ContractError(
            f"AUDIT_SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}"
        ) from error
    if seen != set(expected):
        raise ContractError(f"AUDIT_SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    if set(csv_payloads) != {contract.image_csv_member, contract.imu_csv_member}:
        raise ContractError("AUDIT_SOURCE_CSV_SET_MISMATCH")
    core.require_pin(
        csv_identities[contract.image_csv_member], contract.image_csv_pin, "AUDIT_IMAGE_CSV"
    )
    core.require_pin(
        csv_identities[contract.imu_csv_member], contract.imu_csv_pin, "AUDIT_IMU_CSV"
    )
    return {
        "camera_csv_payload": csv_payloads[contract.image_csv_member],
        "imu_csv_payload": csv_payloads[contract.imu_csv_member],
        "member_identities": {
            "camera_csv": csv_identities[contract.image_csv_member],
            "imu_csv": csv_identities[contract.imu_csv_member],
        },
        "source_members_compared": len(seen),
        "all_output_png_bytes_identical_to_canonical_source_members": True,
        "source_gzip_stream_fully_consumed_and_crc_checked": True,
    }


def _audit_imu(payload: bytes, camera_stamps: Sequence[int], contract: MaterializationContract) -> Dict[str, Any]:
    if payload.endswith(b"\n"):
        raise ContractError("AUDIT_IMU_FINAL_NEWLINE_PRESENT")
    lines = payload.decode("utf-8").splitlines()
    if not lines or lines[0] != IMU_CSV_HEADER:
        raise ContractError("AUDIT_IMU_HEADER_MISMATCH")
    stamps: List[int] = []
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise ContractError(f"AUDIT_IMU_COLUMN_COUNT:{index}")
        try:
            stamps.append(int(fields[0]))
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"AUDIT_IMU_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in values):
            raise ContractError(f"AUDIT_IMU_NONFINITE:{index}")
    if len(stamps) != contract.imu_count:
        raise ContractError("AUDIT_IMU_COUNT_MISMATCH")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise ContractError("AUDIT_IMU_NON_MONOTONIC")
    endpoints = (stamps[0], stamps[1], stamps[-2], stamps[-1])
    expected = (
        contract.imu_first_output_ns,
        contract.imu_second_output_ns,
        contract.imu_penultimate_output_ns,
        contract.imu_last_output_ns,
    )
    if endpoints != expected:
        raise ContractError(f"AUDIT_IMU_ENDPOINT_MISMATCH:{endpoints}")
    if not (
        stamps[0] <= camera_stamps[0] < stamps[1]
        and stamps[-2] <= camera_stamps[-1] < stamps[-1]
    ):
        raise ContractError("AUDIT_IMU_CAMERA_READER_BRACKET_MISMATCH")
    return {
        "count": len(stamps),
        "strictly_monotonic": True,
        "endpoints_ns": list(endpoints),
        "reader_bracket_valid": True,
        "final_newline": False,
    }


def audit(
    root: Path,
    source_archive: Path,
    short_bag: Path,
    config: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("AUDIT_INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    provenance = _require_provenance(short_bag, config)
    source_identity = core.validate_source_archive(source_archive, contract)
    camera_stamps, image_rows, histogram = _parse_output_camera(root, contract)
    source_comparison = _audit_source_stream(source_archive, image_rows, contract)
    _, selected_camera = core.parse_camera_rows(
        source_comparison["camera_csv_payload"], contract
    )
    _, selected_imu = core.parse_imu_rows(
        source_comparison["imu_csv_payload"], selected_camera, contract
    )
    expected_generated_payloads = {
        "cam0_times.txt": core.camera_times_bytes(selected_camera),
        "mav0/cam0/data.csv": core.camera_csv_bytes(selected_camera),
        "mav0/imu0/data.csv": core.imu_csv_bytes(selected_imu, contract.imu_shift_ns),
    }
    generated_rows: List[Dict[str, Any]] = []
    pins = {
        "cam0_times.txt": contract.times_pin,
        "mav0/cam0/data.csv": contract.camera_csv_pin,
        "mav0/imu0/data.csv": contract.imu_output_pin,
    }
    for relative, expected_payload in expected_generated_payloads.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"AUDIT_GENERATED_MISSING:{relative}")
        payload = path.read_bytes()
        if payload != expected_payload:
            raise ContractError(f"AUDIT_GENERATED_SOURCE_DERIVATION_MISMATCH:{relative}")
        observed = core.identity_bytes(relative, payload)
        core.require_pin(observed, pins[relative], f"AUDIT_GENERATED:{relative}")
        generated_rows.append(observed)
    imu = _audit_imu(
        expected_generated_payloads["mav0/imu0/data.csv"], camera_stamps, contract
    )
    image_identity = core.aggregate_identities(image_rows)
    core.enforce_expected_aggregate(
        image_identity,
        contract.expected_renamed_image_inventory_sha256,
        contract.expected_renamed_image_inventory_crc32,
        "AUDIT_RENAMED_IMAGE_INVENTORY",
    )
    if (
        contract.expected_image_total_bytes is not None
        and sum(int(row["size_bytes"]) for row in image_rows)
        != contract.expected_image_total_bytes
    ):
        raise ContractError("AUDIT_IMAGE_TOTAL_BYTES_MISMATCH")
    payload_identity = core.aggregate_identities(list(image_rows) + generated_rows)
    core.enforce_expected_aggregate(
        payload_identity,
        contract.expected_payload_sha256,
        contract.expected_payload_crc32,
        "AUDIT_PAYLOAD_IDENTITY",
    )
    expected_paths = {str(row["path"]) for row in image_rows + generated_rows}
    expected_paths.add("materialization_manifest.json")
    observed_paths: Set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"AUDIT_OUTPUT_NONREGULAR:{path}")
        observed_paths.add(path.relative_to(root).as_posix())
    if observed_paths != expected_paths:
        raise ContractError("AUDIT_OUTPUT_FILE_SET_MISMATCH")
    manifest_path = root / "materialization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "PASS_PREPARATION_ONLY":
        raise ContractError("AUDIT_MANIFEST_STATUS_OR_SCHEMA_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != payload_identity:
        raise ContractError("AUDIT_MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise ContractError("AUDIT_MANIFEST_FORBIDDEN_CLAIM")
    selection = manifest.get("selection", {})
    if (
        selection.get("sequence_id") != "A09"
        or selection.get("camera_indices_inclusive")
        != [contract.camera_start_index, contract.camera_end_index]
        or selection.get("camera_count") != contract.camera_count
        or selection.get("cold_start") is not True
        or selection.get("synthetic_or_extrapolated_imu_used") is not False
    ):
        raise ContractError("AUDIT_MANIFEST_SELECTION_MISMATCH")
    manifest_files = manifest.get("camera", {}).get("files", [])
    if len(manifest_files) != len(image_rows):
        raise ContractError("AUDIT_MANIFEST_CAMERA_FILE_COUNT_MISMATCH")
    for expected_row, manifest_row in zip(image_rows, manifest_files):
        for key in (
            "path",
            "size_bytes",
            "sha256",
            "crc32",
            "source_index",
            "source_member",
            "camera_timestamp_ns",
        ):
            if manifest_row.get(key) != expected_row[key]:
                raise ContractError(f"AUDIT_MANIFEST_CAMERA_FILE_MISMATCH:{key}")
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "input_root": str(root.resolve()),
        "source": source_identity,
        "source_choice": provenance["source_choice"],
        "configuration_authority": provenance["archaeology_config"],
        "file_count_including_manifest": len(observed_paths),
        "payload_file_count_excluding_manifest": len(image_rows) + len(generated_rows),
        "camera": {
            "count": len(image_rows),
            "source_indices_inclusive": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "header_ns_inclusive": [camera_stamps[0], camera_stamps[-1]],
            "total_png_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "chunk_count_histogram": histogram,
            "inventory_identity": image_identity,
            "source_members": source_comparison["member_identities"],
            "source_members_compared": source_comparison["source_members_compared"],
            "all_output_png_bytes_identical_to_canonical_source_members": True,
            "source_gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "imu": imu,
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": core.identity_file(manifest_path, "materialization_manifest.json"),
        "reporting_boundary": (
            "development-only learned-active positive input preparation; "
            "no trajectory, accuracy, or comparison"
        ),
        "claims": {
            "runner_created": False,
            "start_claim_created": False,
            "hfnet_started": False,
            "ros_started": False,
            "vins_started": False,
            "detector_started": False,
            "evaluator_started": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
            "scientific_comparison_produced": False,
        },
    }


def _write_report_exclusive(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"NO_CLOBBER_REPORT_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    core.fsync_directory(path.parent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("preflight", "materialize", "audit", "materialize-and-audit"),
        default="preflight",
    )
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--short-bag", type=Path, default=DEFAULT_SHORT_BAG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--report",
        type=Path,
        help="optional no-clobber JSON receipt (normally a sibling of the immutable input tree)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.report is not None and (args.report.exists() or args.report.is_symlink()):
            raise ContractError(f"NO_CLOBBER_REPORT_EXISTS:{args.report}")
        if args.action == "preflight":
            result = preflight_result(
                args.source_archive, args.short_bag, args.config, args.output_root
            )
        elif args.action == "materialize":
            result = materialize(
                args.source_archive,
                args.short_bag,
                args.config,
                args.output_root,
            )
        elif args.action == "audit":
            result = audit(
                args.output_root, args.source_archive, args.short_bag, args.config
            )
        else:
            materialization = materialize(
                args.source_archive,
                args.short_bag,
                args.config,
                args.output_root,
            )
            independent_audit = audit(
                args.output_root, args.source_archive, args.short_bag, args.config
            )
            result = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "status": "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_PREPARATION_ONLY",
                "materialization": materialization,
                "independent_audit": independent_audit,
                "claims": {
                    "hfnet_started": False,
                    "ros_started": False,
                    "vins_started": False,
                    "trajectory_produced": False,
                },
            }
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {
                "hfnet_started": False,
                "ros_started": False,
                "vins_started": False,
                "trajectory_produced": False,
            },
        }
        return_code = 2
    payload = core.canonical_json(result)
    if args.report is not None and return_code == 0:
        _write_report_exclusive(args.report, payload)
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())

