#!/usr/bin/env python3
"""Prepare and independently audit the A09 natural-history HFNet input.

Canonical AQUALOC A09 frames 0..4400 are fed continuously without an
estimator reset.  Frames 0..3999 are history only; any later runner must score
only frames 4000..4400.  Raw archive PNG members are copied byte-for-byte and
IMU timestamps receive the frozen archaeology +53694112 ns clock shift.

Publication reserves the final target with a no-clobber ``mkdirat`` and writes
``materialization_manifest.json`` exclusively as the last commit marker.  The
independent audit re-derives every generated file from the pinned source CSVs,
compares every output PNG with its canonical tar member, and requires exact
file and directory closure.  This module contains no process launcher and
never starts HFNet, ROS, VINS, a detector, or an evaluator.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_positive_a09_4000_4400_coldstart_v1 as base


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = (
    "aqua-fe-hfnet-positive-a09-0000-4400-score-4000-4400-"
    "warmstart-materialization-v1"
)
AUDIT_SCHEMA_VERSION = (
    "aqua-fe-hfnet-positive-a09-0000-4400-score-4000-4400-"
    "warmstart-independent-audit-v1"
)
SELECTOR_SCHEMA_VERSION = "aqua-fe-hfnet-v6-a09-warmstart-selector-freeze-v1"

BASE_ADAPTER_PATH = ROOT / "scripts/materialize_hfnet_positive_a09_4000_4400_coldstart_v1.py"
BASE_ADAPTER_SIZE = 37_453
BASE_ADAPTER_SHA256 = "002711916b5892fb093bb2ee49e507b59fcb4a90f21106ae2ff17c9288a30376"

DEFAULT_SELECTOR_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_"
    "warmstart_selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 5_743
SELECTOR_FREEZE_SHA256 = "bfec892d6f58f751c12302e93dfbdcd1132d326dad2506066d4fe8e2e87fd51c"

DEFAULT_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_"
    "warmstart_runability_rescue_protocol_v1.md"
)
PROTOCOL_SIZE = 10_944
PROTOCOL_SHA256 = "090e3458e7a281dd694c6d31582e729ec93a3a2927521cc7783e338e66f6fb12"

DEFAULT_PAYLOAD_PIN_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_"
    "warmstart_payload_pin_derivation_freeze_v1.json"
)
PAYLOAD_PIN_FREEZE_SIZE = 11_763
PAYLOAD_PIN_FREEZE_SHA256 = (
    "e4c64167c70e326237e7835a8b41140ed1c9a8a55eb9b9490b72f73b3de0e857"
)
PAYLOAD_PIN_FREEZE_SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a09-warmstart-payload-pin-read-only-derivation-freeze-v1"
)

DEFAULT_SOURCE_ARCHIVE = base.DEFAULT_SOURCE_ARCHIVE
DEFAULT_SHORT_BAG = base.DEFAULT_SHORT_BAG
DEFAULT_CONFIG = base.DEFAULT_CONFIG
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a09_0000_4400_score_4000_4400_warmstart"
)
DEFAULT_AUDIT_REPORT = Path(str(DEFAULT_OUTPUT_ROOT) + ".audit.json")

FEED_START_INDEX = 0
FEED_END_INDEX = 4_400
SCORE_START_INDEX = 4_000
SCORE_END_INDEX = 4_400
SCORE_FIRST_NS = 1_542_888_946_038_630_384
SCORE_LAST_NS = 1_542_888_966_034_698_672
PREROLL_LAST_NS = 1_542_888_945_988_866_768
IMU_SECOND_RAW_NS = 1_542_888_746_019_782_672
IMU_PENULTIMATE_RAW_NS = 1_542_888_965_978_469_456

FilePin = base.FilePin
MaterializationContract = base.MaterializationContract
ContractError = base.ContractError
IMAGE_CSV_HEADER = base.IMAGE_CSV_HEADER
CAMERA_OUTPUT_CSV_HEADER = base.CAMERA_OUTPUT_CSV_HEADER
IMU_CSV_HEADER = base.IMU_CSV_HEADER
core = base.core


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
    camera_start_index=FEED_START_INDEX,
    camera_end_index=FEED_END_INDEX,
    camera_first_ns=1_542_888_746_071_008_208,
    camera_last_ns=1_542_888_966_034_698_672,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=5,
    imu_last_index=43_964,
    imu_first_raw_ns=1_542_888_746_014_492_144,
    imu_last_raw_ns=1_542_888_965_983_692_976,
    imu_first_output_ns=1_542_888_746_068_186_256,
    imu_second_output_ns=1_542_888_746_073_476_784,
    imu_penultimate_output_ns=1_542_888_966_032_163_568,
    imu_last_output_ns=1_542_888_966_037_387_088,
    expected_image_total_bytes=1_125_883_992,
    expected_source_image_inventory_sha256=(
        "b8f0a21731558e1694c09c23c05ce259fbd1dba83b3bf55bfebea88448a5d148"
    ),
    expected_source_image_inventory_crc32="415c8b51",
    expected_renamed_image_inventory_sha256=(
        "d065372862769e802a3236d297f14cdd8e8ec25fd6607beb3c25c6c6d10f594f"
    ),
    expected_renamed_image_inventory_crc32="9526b009",
    times_pin=FilePin(
        size_bytes=88_020,
        sha256="c8b9bb58e1692ae570cfc855e2069bda734110c2866004093c8eefa4293f16a8",
        crc32="6aff1e64",
    ),
    camera_csv_pin=FilePin(
        size_bytes=193_669,
        sha256="bec600ec64aefbff6679bb482059b6c581934083c2476af052cf9d51f4973a42",
        crc32="b6616fa8",
    ),
    imu_output_pin=FilePin(
        size_bytes=4_911_770,
        sha256="2281ea603ae9d47d21914423212b930e99d4066edd3bcdccd5758b911d0cd4d8",
        crc32="ff36467b",
    ),
    expected_payload_sha256=(
        "845bc56b0de8df58f0dedde3d22e7a6019ba3b02fa4edc7b6ceec395fdee5f52"
    ),
    expected_payload_crc32="79183172",
)


def _require_identity(path: Path, pin: FilePin, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    core.require_pin(observed, pin, label)
    return observed


def validate_selector(path: Path) -> Dict[str, Any]:
    observed = _require_identity(
        path,
        FilePin(SELECTOR_FREEZE_SIZE, SELECTOR_FREEZE_SHA256),
        "SELECTOR_FREEZE",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA_VERSION:
        raise ContractError("SELECTOR_FREEZE_SCHEMA_MISMATCH")
    selection = value.get("selection", {})
    required = {
        "sequence_id": "A09",
        "camera_indices_inclusive_for_feed": [FEED_START_INDEX, FEED_END_INDEX],
        "camera_count_for_feed": FEED_END_INDEX - FEED_START_INDEX + 1,
        "camera_header_ns_inclusive_for_feed": [
            PRODUCTION_CONTRACT.camera_first_ns,
            PRODUCTION_CONTRACT.camera_last_ns,
        ],
        "preroll_camera_indices_half_open": [FEED_START_INDEX, SCORE_START_INDEX],
        "preroll_camera_count": SCORE_START_INDEX - FEED_START_INDEX,
        "preroll_last_camera_header_ns": PREROLL_LAST_NS,
        "score_camera_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
        "score_camera_count": SCORE_END_INDEX - SCORE_START_INDEX + 1,
        "score_camera_header_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
        "warm_start": True,
    }
    for key, expected in required.items():
        if selection.get(key) != expected:
            raise ContractError(f"SELECTOR_FREEZE_SELECTION_MISMATCH:{key}")
    boundary = value.get("knowledge_boundary", {})
    if boundary.get("development_result_conditioned_selection") is not True:
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_NOT_DISCLOSED")
    if boundary.get("held_out_confirmatory_claim_permitted") is not False:
        raise ContractError("SELECTOR_HELD_OUT_BOUNDARY_INVALID")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    materialization_gate = value.get("materialization_gate", {})
    if materialization_gate.get("production_materialization_permitted") is not False:
        raise ContractError("SELECTOR_MATERIALIZATION_AUTHORITY_BOUNDARY_INVALID")
    return observed


def _require_semantic_mapping(
    observed: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    for key, expected_value in expected.items():
        if observed.get(key) != expected_value:
            raise ContractError(f"{label}_MISMATCH:{key}")


def validate_payload_pin_freeze(
    path: Path,
    selector_freeze: Path,
    protocol: Path,
    selector_identity: Optional[Mapping[str, Any]] = None,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    """Bind the read-only derivation and match every target pin to contract."""

    observed = _require_identity(
        path,
        FilePin(PAYLOAD_PIN_FREEZE_SIZE, PAYLOAD_PIN_FREEZE_SHA256),
        "PAYLOAD_PIN_DERIVATION_FREEZE",
    )
    selector_observed = (
        dict(selector_identity)
        if selector_identity is not None
        else validate_selector(selector_freeze)
    )
    protocol_observed = _require_identity(
        protocol,
        FilePin(PROTOCOL_SIZE, PROTOCOL_SHA256),
        "RUNABILITY_PROTOCOL",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != PAYLOAD_PIN_FREEZE_SCHEMA_VERSION:
        raise ContractError("PAYLOAD_PIN_FREEZE_SCHEMA_MISMATCH")
    if value.get("status") != "PASS_READ_ONLY_DERIVATION_NO_CANONICAL_OUTPUT_WRITTEN":
        raise ContractError("PAYLOAD_PIN_FREEZE_STATUS_MISMATCH")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("PAYLOAD_PIN_FREEZE_FORBIDDEN_CLAIM")
    authority = value.get("authority_boundary", {})
    if (
        authority.get("materialization_authority_created") is not False
        or authority.get("process_launch_authority_created") is not False
    ):
        raise ContractError("PAYLOAD_PIN_FREEZE_AUTHORITY_BOUNDARY_INVALID")

    design_inputs = value.get("frozen_design_inputs", {})
    _require_semantic_mapping(
        design_inputs.get("selector", {}),
        {
            "path": str(selector_freeze.resolve()),
            "size_bytes": selector_observed["size_bytes"],
            "sha256": selector_observed["sha256"],
        },
        "PAYLOAD_PIN_FREEZE_SELECTOR_BINDING",
    )
    _require_semantic_mapping(
        design_inputs.get("protocol", {}),
        {
            "path": str(protocol.resolve()),
            "size_bytes": protocol_observed["size_bytes"],
            "sha256": protocol_observed["sha256"],
        },
        "PAYLOAD_PIN_FREEZE_PROTOCOL_BINDING",
    )

    source_pins = value.get("source_pins", {})
    _require_semantic_mapping(
        source_pins.get("archive", {}),
        {
            "path": str(contract.source_archive.resolve()),
            "size_bytes": contract.source_pin.size_bytes,
            "sha256": contract.source_pin.sha256,
            "gzip_footer_crc32": contract.source_gzip_crc32,
            "gzip_footer_isize_mod_2_32": contract.source_gzip_isize,
        },
        "PAYLOAD_PIN_FREEZE_SOURCE_ARCHIVE",
    )
    _require_semantic_mapping(
        source_pins.get("camera_csv_member", {}),
        {
            "path": contract.image_csv_member,
            "size_bytes": contract.image_csv_pin.size_bytes,
            "sha256": contract.image_csv_pin.sha256,
            "crc32": contract.image_csv_pin.crc32,
            "source_row_count": contract.source_camera_count,
        },
        "PAYLOAD_PIN_FREEZE_CAMERA_CSV",
    )
    _require_semantic_mapping(
        source_pins.get("imu_csv_member", {}),
        {
            "path": contract.imu_csv_member,
            "size_bytes": contract.imu_csv_pin.size_bytes,
            "sha256": contract.imu_csv_pin.sha256,
            "crc32": contract.imu_csv_pin.crc32,
            "source_row_count": contract.source_imu_count,
        },
        "PAYLOAD_PIN_FREEZE_IMU_CSV",
    )
    if source_pins.get("image_member_prefix") != contract.image_member_prefix:
        raise ContractError("PAYLOAD_PIN_FREEZE_IMAGE_PREFIX_MISMATCH")

    selection = value.get("selection_and_sync", {})
    _require_semantic_mapping(
        selection.get("camera", {}),
        {
            "feed_count": contract.camera_count,
            "feed_indices_inclusive": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "feed_timestamp_ns_inclusive": [
                contract.camera_first_ns,
                contract.camera_last_ns,
            ],
            "prefix_last_index": SCORE_START_INDEX - 1,
            "prefix_last_timestamp_ns": PREROLL_LAST_NS,
            "score_count": SCORE_END_INDEX - SCORE_START_INDEX + 1,
            "score_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
            "score_timestamp_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
            "strictly_increasing": True,
        },
        "PAYLOAD_PIN_FREEZE_CAMERA_SELECTION",
    )
    _require_semantic_mapping(
        selection.get("imu", {}),
        {
            "output_shift_ns": contract.imu_shift_ns,
            "raw_indices_inclusive_zero_based_excluding_header": [
                contract.imu_first_index,
                contract.imu_last_index,
            ],
            "selected_count": contract.imu_count,
            "raw_boundary_ns_first_second_penultimate_last": [
                contract.imu_first_raw_ns,
                IMU_SECOND_RAW_NS,
                IMU_PENULTIMATE_RAW_NS,
                contract.imu_last_raw_ns,
            ],
            "shifted_boundary_ns_first_second_penultimate_last": [
                contract.imu_first_output_ns,
                contract.imu_second_output_ns,
                contract.imu_penultimate_output_ns,
                contract.imu_last_output_ns,
            ],
            "first_camera_bracket_output_ns": [
                contract.imu_first_output_ns,
                contract.camera_first_ns,
                contract.imu_second_output_ns,
            ],
            "last_camera_bracket_output_ns": [
                contract.imu_penultimate_output_ns,
                contract.camera_last_ns,
                contract.imu_last_output_ns,
            ],
            "strict_camera_endpoint_brackets": True,
            "strictly_increasing": True,
            "synthetic_interpolated_or_extrapolated_rows_used": False,
        },
        "PAYLOAD_PIN_FREEZE_IMU_SELECTION",
    )

    target = value.get("target_payload_pins", {})
    selected_pngs = target.get("selected_canonical_pngs", {})
    _require_semantic_mapping(
        selected_pngs,
        {
            "file_count": contract.camera_count,
            "total_size_bytes": contract.expected_image_total_bytes,
            "canonical_member_bytes_preserved": True,
        },
        "PAYLOAD_PIN_FREEZE_SELECTED_PNGS",
    )
    _require_semantic_mapping(
        selected_pngs.get("source_member_inventory", {}),
        {
            "sha256": contract.expected_source_image_inventory_sha256,
            "crc32": contract.expected_source_image_inventory_crc32,
        },
        "PAYLOAD_PIN_FREEZE_SOURCE_IMAGE_INVENTORY",
    )
    _require_semantic_mapping(
        selected_pngs.get("renamed_output_inventory", {}),
        {
            "sha256": contract.expected_renamed_image_inventory_sha256,
            "crc32": contract.expected_renamed_image_inventory_crc32,
        },
        "PAYLOAD_PIN_FREEZE_RENAMED_IMAGE_INVENTORY",
    )
    generated = target.get("generated_files", {})
    generated_expected = {
        "cam0_times.txt": contract.times_pin,
        "mav0/cam0/data.csv": contract.camera_csv_pin,
        "mav0/imu0/data.csv": contract.imu_output_pin,
    }
    for relative, pin in generated_expected.items():
        _require_semantic_mapping(
            generated.get(relative, {}),
            {
                "size_bytes": pin.size_bytes,
                "sha256": pin.sha256,
                "crc32": pin.crc32,
            },
            f"PAYLOAD_PIN_FREEZE_GENERATED:{relative}",
        )
    payload = target.get("payload_excluding_manifest", {})
    _require_semantic_mapping(
        payload,
        {
            "algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n",
            "file_count": contract.camera_count + 3,
            "file_count_breakdown": {
                "generated_files": 3,
                "selected_png_files": contract.camera_count,
            },
            "total_size_bytes": (
                int(contract.expected_image_total_bytes or 0)
                + int(contract.times_pin.size_bytes or 0)
                + int(contract.camera_csv_pin.size_bytes or 0)
                + int(contract.imu_output_pin.size_bytes or 0)
            ),
            "sha256": contract.expected_payload_sha256,
            "crc32": contract.expected_payload_crc32,
        },
        "PAYLOAD_PIN_FREEZE_PAYLOAD",
    )

    derivation = value.get("derivation", {})
    core_observed = core.identity_file(
        Path(core.__file__), str(Path(core.__file__).resolve())
    )
    _require_semantic_mapping(
        derivation.get("core_identity", {}),
        {
            "path": core_observed["path"],
            "size_bytes": core_observed["size_bytes"],
            "sha256": core_observed["sha256"],
            "crc32": core_observed["crc32"],
        },
        "PAYLOAD_PIN_FREEZE_CORE_BINDING",
    )
    if derivation.get("no_write_functions_invoked") is not True:
        raise ContractError("PAYLOAD_PIN_FREEZE_READ_ONLY_DERIVATION_MISMATCH")
    canonical_state = derivation.get("canonical_output_state", {})
    required_absence = {
        "canonical_input_root_absent_after": True,
        "audit_receipt_absent_after": True,
        "attempt_namespace_absent_after": True,
        "canonical_output_file_count_written": 0,
    }
    _require_semantic_mapping(
        canonical_state,
        required_absence,
        "PAYLOAD_PIN_FREEZE_CANONICAL_OUTPUT_STATE",
    )
    cold_reproduction = value.get("cold_subset_exact_reproduction", {})
    _require_semantic_mapping(
        cold_reproduction.get("comparison", {}),
        {
            "all_frozen_pins_reproduced_exactly": True,
            "mismatch_count": 0,
            "mismatches": [],
        },
        "PAYLOAD_PIN_FREEZE_COLD_REPRODUCTION",
    )
    _require_semantic_mapping(
        cold_reproduction.get("reference_artifacts", {}).get(
            "materializer_contract", {}
        ),
        {
            "path": str(BASE_ADAPTER_PATH.resolve()),
            "size_bytes": BASE_ADAPTER_SIZE,
            "sha256": BASE_ADAPTER_SHA256,
        },
        "PAYLOAD_PIN_FREEZE_COLD_ADAPTER_BINDING",
    )
    return {
        "payload_pin_derivation_freeze": {
            **observed,
            "semantic_validation": "PASS_ALL_TARGET_PINS_MATCH_PRODUCTION_CONTRACT",
            "materialization_authority_created": False,
            "process_launch_authority_created": False,
        },
        "runability_protocol": protocol_observed,
    }


def _require_provenance(
    selector_freeze: Path, short_bag: Path, config: Path
) -> Dict[str, Any]:
    reused_base = _require_identity(
        BASE_ADAPTER_PATH,
        FilePin(BASE_ADAPTER_SIZE, BASE_ADAPTER_SHA256),
        "REUSED_A09_COLDSTART_ADAPTER",
    )
    selector = validate_selector(selector_freeze)
    pin_derivation = validate_payload_pin_freeze(
        DEFAULT_PAYLOAD_PIN_FREEZE,
        selector_freeze,
        DEFAULT_PROTOCOL,
        selector,
    )
    inherited = base._require_provenance(short_bag, config)
    return {
        **inherited,
        "reused_a09_coldstart_adapter": reused_base,
        "selector_freeze": selector,
        **pin_derivation,
    }


def _require_output_absent(output_root: Path) -> None:
    if os.path.lexists(os.fspath(output_root)):
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")


def _expected_directories(paths: Set[str]) -> Set[str]:
    directories: Set[str] = set()
    for relative in paths:
        parent = Path(relative).parent
        while parent != Path("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


class ManifestCommittedReservation:
    """An atomically reserved target whose manifest is the commit marker."""

    def __init__(
        self,
        path: Path,
        parent_fd: int,
        root_fd: int,
        root_identity: tuple,
    ) -> None:
        self.path = path
        self.parent_fd = parent_fd
        self.root_fd = root_fd
        self.root_identity = root_identity
        self.committed = False

    def require_root_identity(self) -> None:
        observed = os.stat(
            self.path.name, dir_fd=self.parent_fd, follow_symlinks=False
        )
        held = os.fstat(self.root_fd)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or not stat.S_ISDIR(held.st_mode)
            or (observed.st_dev, observed.st_ino) != self.root_identity
            or (held.st_dev, held.st_ino) != self.root_identity
        ):
            raise ContractError("RESERVED_TARGET_IDENTITY_DRIFT")

    def _validate_payload_tree(self, expected_paths: Set[str]) -> None:
        self.require_root_identity()
        observed_paths: Set[str] = set()
        observed_directories: Set[str] = set()
        for path in self.path.rglob("*"):
            relative = path.relative_to(self.path).as_posix()
            if path.is_symlink():
                raise ContractError(f"PRECOMMIT_OUTPUT_SYMLINK:{path}")
            observed = path.lstat()
            if stat.S_ISDIR(observed.st_mode):
                observed_directories.add(relative)
            elif stat.S_ISREG(observed.st_mode):
                observed_paths.add(relative)
            else:
                raise ContractError(f"PRECOMMIT_OUTPUT_NONREGULAR:{path}")
        if observed_paths != expected_paths:
            raise ContractError("PRECOMMIT_PAYLOAD_FILE_SET_MISMATCH")
        if observed_directories != _expected_directories(expected_paths):
            raise ContractError("PRECOMMIT_PAYLOAD_DIRECTORY_SET_MISMATCH")

    def commit_manifest(self, payload: bytes, expected_paths: Set[str]) -> None:
        if self.committed:
            raise ContractError("MANIFEST_ALREADY_COMMITTED")
        if "materialization_manifest.json" in expected_paths:
            raise ContractError("COMMIT_MARKER_MUST_NOT_BE_PAYLOAD")
        self._validate_payload_tree(expected_paths)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(
            "materialization_manifest.json",
            flags,
            0o444,
            dir_fd=self.root_fd,
        )
        try:
            view = memoryview(payload)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise ContractError("COMMIT_MARKER_SHORT_WRITE")
                written += count
            os.fsync(descriptor)
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or observed.st_size != len(payload):
                raise ContractError("COMMIT_MARKER_IDENTITY_MISMATCH")
        finally:
            os.close(descriptor)
        self.require_root_identity()
        os.fsync(self.root_fd)
        os.fsync(self.parent_fd)
        self.committed = True


@contextmanager
def manifest_committed_directory(target: Path):
    """Atomically reserve target; publish only by writing the manifest last."""

    target = Path(os.path.abspath(os.path.expanduser(os.fspath(target))))
    if not target.name or target.name in (".", ".."):
        raise ContractError("RESERVED_TARGET_NAME_INVALID")
    _require_output_absent(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        parent_fd = os.open(os.fspath(target.parent), flags)
    except OSError as error:
        raise ContractError("RESERVED_TARGET_PARENT_UNSAFE") from error
    root_fd: Optional[int] = None
    reservation: Optional[ManifestCommittedReservation] = None
    try:
        parent_held = os.fstat(parent_fd)
        parent_path = os.stat(target.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_path.st_mode)
            or (parent_held.st_dev, parent_held.st_ino)
            != (parent_path.st_dev, parent_path.st_ino)
        ):
            raise ContractError("RESERVED_TARGET_PARENT_IDENTITY_DRIFT")
        try:
            os.mkdir(target.name, 0o700, dir_fd=parent_fd)
        except FileExistsError as error:
            raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{target}") from error
        observed = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(observed.st_mode) or observed.st_uid != os.getuid():
            raise ContractError("RESERVED_TARGET_UNSAFE")
        root_identity = (observed.st_dev, observed.st_ino)
        root_fd = os.open(target.name, flags, dir_fd=parent_fd)
        held = os.fstat(root_fd)
        if (held.st_dev, held.st_ino) != root_identity:
            raise ContractError("RESERVED_TARGET_OPEN_IDENTITY_DRIFT")
        reservation = ManifestCommittedReservation(
            target, parent_fd, root_fd, root_identity
        )
        yield reservation
        if not reservation.committed:
            raise ContractError("MANIFEST_COMMIT_REQUIRED")
    finally:
        try:
            if reservation is not None and not reservation.committed:
                try:
                    reservation.require_root_identity()
                except (FileNotFoundError, ContractError):
                    pass
                else:
                    shutil.rmtree(target)
                    os.fsync(parent_fd)
        finally:
            if root_fd is not None:
                os.close(root_fd)
            os.close(parent_fd)


def prepare_metadata(
    selector_freeze: Path,
    source_archive: Path,
    short_bag: Path,
    config: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    provenance = _require_provenance(selector_freeze, short_bag, config)
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
        "cam0_data_csv": core.identity_bytes(
            "mav0/cam0/data.csv", camera_csv_payload
        ),
        "imu0_data_csv": core.identity_bytes(
            "mav0/imu0/data.csv", output_imu_payload
        ),
    }
    core.require_pin(generated["cam0_times"], contract.times_pin, "CAM0_TIMES")
    core.require_pin(
        generated["cam0_data_csv"], contract.camera_csv_pin, "CAM0_DATA_CSV"
    )
    core.require_pin(
        generated["imu0_data_csv"], contract.imu_output_pin, "IMU0_DATA_CSV"
    )
    bracket = core.validate_imu_bracket(
        output_imu_payload, selected_camera, contract
    )
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
            "a09_coldstart_adapter": metadata["reused_a09_coldstart_adapter"],
            "a06_adapter": metadata["reused_a06_adapter"],
            "a06_core": metadata["reused_a06_sealed_core"],
            "a06_independent_auditor": metadata[
                "reused_a06_independent_auditor"
            ],
        },
        "selector_freeze": metadata["selector_freeze"],
        "payload_pin_derivation_freeze": metadata[
            "payload_pin_derivation_freeze"
        ],
        "runability_protocol": metadata["runability_protocol"],
        "authority_boundary": {
            "selector_production_materialization_permitted": False,
            "materializer_implementation_is_not_materialization_authority": True,
            "separate_exact_canonical_write_authority_required": True,
            "process_launch_authority_created": False,
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
            "warm_start": True,
            "cold_start": False,
            "camera_indices_inclusive_for_feed": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "camera_count_for_feed": contract.camera_count,
            "camera_header_ns_inclusive_for_feed": [
                contract.camera_first_ns,
                contract.camera_last_ns,
            ],
            "preroll_camera_indices_half_open": [
                contract.camera_start_index,
                SCORE_START_INDEX,
            ],
            "preroll_camera_count": SCORE_START_INDEX - contract.camera_start_index,
            "preroll_last_camera_header_ns": PREROLL_LAST_NS,
            "score_camera_indices_inclusive": [
                SCORE_START_INDEX,
                SCORE_END_INDEX,
            ],
            "score_camera_count": SCORE_END_INDEX - SCORE_START_INDEX + 1,
            "score_camera_header_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
            "initialization_and_preroll_excluded_from_score": True,
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
        "publication": {
            "method": "mkdirat target reservation plus manifest O_EXCL last",
            "target_reservation": "atomic no-clobber mkdir relative to held parent fd",
            "commit_marker": "materialization_manifest.json",
            "commit_marker_written_exclusive_last": True,
            "tree_without_commit_marker_is_uncommitted": True,
            "runner_requires_independent_audit_receipt": True,
            "filesystem_mode_bits_not_used_as_authority": True,
            "exact_file_and_directory_closure_required": True,
        },
        "reporting_boundary": (
            "development-only warm-start input preparation; frames 0..3999 are "
            "history only and frames 4000..4400 are the sole score window; no "
            "trajectory, accuracy, or scientific comparison"
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
    selector_freeze: Path,
    source_archive: Path,
    short_bag: Path,
    config: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    _require_output_absent(output_root)
    metadata = prepare_metadata(
        selector_freeze, source_archive, short_bag, config, contract
    )
    with manifest_committed_directory(output_root) as reservation:
        staging = reservation.path
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
        core.write_exclusive_bytes(
            staging / "cam0_times.txt", metadata["times_payload"]
        )
        core.write_exclusive_bytes(
            staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"]
        )
        core.write_exclusive_bytes(
            staging / "mav0/imu0/data.csv", metadata["imu_payload"]
        )
        payload_rows: List[Mapping[str, Any]] = list(image_rows)
        payload_rows.extend(
            [
                generated["cam0_times"],
                generated["cam0_data_csv"],
                generated["imu0_data_csv"],
            ]
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
        for directory in (
            staging / "mav0/cam0/data",
            staging / "mav0/cam0",
            staging / "mav0/imu0",
            staging / "mav0",
            staging,
        ):
            core.fsync_directory(directory)
        expected_payload_paths = {str(row["path"]) for row in payload_rows}
        reservation.commit_manifest(
            core.canonical_json(manifest), expected_payload_paths
        )
    return manifest


def preflight_result(
    selector_freeze: Path,
    source_archive: Path,
    short_bag: Path,
    config: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    _require_output_absent(output_root)
    metadata = prepare_metadata(
        selector_freeze, source_archive, short_bag, config, contract
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "selector_freeze": metadata["selector_freeze"],
        "payload_pin_derivation_freeze": metadata[
            "payload_pin_derivation_freeze"
        ],
        "runability_protocol": metadata["runability_protocol"],
        "authority_boundary": {
            "selector_production_materialization_permitted": False,
            "materializer_implementation_is_not_materialization_authority": True,
            "separate_exact_canonical_write_authority_required": True,
            "process_launch_authority_created": False,
        },
        "source": metadata["source"],
        "source_choice": metadata["source_choice"],
        "configuration_authority": metadata["archaeology_config"],
        "camera_indices_inclusive_for_feed": [
            contract.camera_start_index,
            contract.camera_end_index,
        ],
        "camera_count_for_feed": contract.camera_count,
        "preroll_camera_indices_half_open": [
            contract.camera_start_index,
            SCORE_START_INDEX,
        ],
        "score_camera_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
        "score_camera_count": SCORE_END_INDEX - SCORE_START_INDEX + 1,
        "imu_count": contract.imu_count,
        "publication": {
            "method": "mkdirat target reservation plus manifest O_EXCL last",
            "target_currently_absent": True,
            "tree_without_commit_marker_is_uncommitted": True,
            "runner_requires_independent_audit_receipt": True,
            "exact_file_and_directory_closure_required": True,
        },
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


def _audit_exact_tree(root: Path, expected_paths: Set[str]) -> Dict[str, Set[str]]:
    observed_paths: Set[str] = set()
    observed_directories: Set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ContractError(f"AUDIT_OUTPUT_SYMLINK:{path}")
        observed = path.lstat()
        if stat.S_ISDIR(observed.st_mode):
            observed_directories.add(relative)
        elif stat.S_ISREG(observed.st_mode):
            observed_paths.add(relative)
        else:
            raise ContractError(f"AUDIT_OUTPUT_NONREGULAR:{path}")
    if observed_paths != expected_paths:
        raise ContractError("AUDIT_OUTPUT_FILE_SET_MISMATCH")
    expected_directories = _expected_directories(expected_paths)
    if observed_directories != expected_directories:
        raise ContractError("AUDIT_OUTPUT_DIRECTORY_SET_MISMATCH")
    return {"files": observed_paths, "directories": observed_directories}


def audit(
    root: Path,
    selector_freeze: Path,
    source_archive: Path,
    short_bag: Path,
    config: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("AUDIT_INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    manifest_path = root / "materialization_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ContractError("AUDIT_COMMIT_MARKER_MISSING_OR_NOT_REGULAR")
    provenance = _require_provenance(selector_freeze, short_bag, config)
    source_identity = core.validate_source_archive(source_archive, contract)

    # These A09 cold-adapter audit primitives are pinned above.  They parse the
    # output independently, stream the canonical tar again to compare every
    # selected PNG byte-for-byte, and return the source CSV payloads rather
    # than trusting the materialization manifest.
    camera_stamps, image_rows, histogram = base._parse_output_camera(root, contract)
    source_comparison = base._audit_source_stream(
        source_archive, image_rows, contract
    )
    _, selected_camera = core.parse_camera_rows(
        source_comparison["camera_csv_payload"], contract
    )
    _, selected_imu = core.parse_imu_rows(
        source_comparison["imu_csv_payload"], selected_camera, contract
    )
    expected_generated = {
        "cam0_times.txt": core.camera_times_bytes(selected_camera),
        "mav0/cam0/data.csv": core.camera_csv_bytes(selected_camera),
        "mav0/imu0/data.csv": core.imu_csv_bytes(
            selected_imu, contract.imu_shift_ns
        ),
    }
    pins = {
        "cam0_times.txt": contract.times_pin,
        "mav0/cam0/data.csv": contract.camera_csv_pin,
        "mav0/imu0/data.csv": contract.imu_output_pin,
    }
    generated_rows: List[Dict[str, Any]] = []
    for relative, expected_payload in expected_generated.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"AUDIT_GENERATED_MISSING:{relative}")
        payload = path.read_bytes()
        if payload != expected_payload:
            raise ContractError(
                f"AUDIT_GENERATED_SOURCE_DERIVATION_MISMATCH:{relative}"
            )
        observed = core.identity_bytes(relative, payload)
        core.require_pin(observed, pins[relative], f"AUDIT_GENERATED:{relative}")
        generated_rows.append(observed)
    imu = base._audit_imu(
        expected_generated["mav0/imu0/data.csv"], camera_stamps, contract
    )
    image_identity = core.aggregate_identities(image_rows)
    core.enforce_expected_aggregate(
        image_identity,
        contract.expected_renamed_image_inventory_sha256,
        contract.expected_renamed_image_inventory_crc32,
        "AUDIT_RENAMED_IMAGE_INVENTORY",
    )
    image_total = sum(int(row["size_bytes"]) for row in image_rows)
    if (
        contract.expected_image_total_bytes is not None
        and image_total != contract.expected_image_total_bytes
    ):
        raise ContractError("AUDIT_IMAGE_TOTAL_BYTES_MISMATCH")
    payload_identity = core.aggregate_identities(image_rows + generated_rows)
    core.enforce_expected_aggregate(
        payload_identity,
        contract.expected_payload_sha256,
        contract.expected_payload_crc32,
        "AUDIT_PAYLOAD_IDENTITY",
    )
    expected_paths = {str(row["path"]) for row in image_rows + generated_rows}
    expected_paths.add("materialization_manifest.json")
    tree = _audit_exact_tree(root, expected_paths)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "PASS_PREPARATION_ONLY"
    ):
        raise ContractError("AUDIT_MANIFEST_STATUS_OR_SCHEMA_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != payload_identity:
        raise ContractError("AUDIT_MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if (
        manifest.get("selector_freeze") != provenance["selector_freeze"]
        or manifest.get("payload_pin_derivation_freeze")
        != provenance["payload_pin_derivation_freeze"]
        or manifest.get("runability_protocol")
        != provenance["runability_protocol"]
    ):
        raise ContractError("AUDIT_MANIFEST_FROZEN_PROVENANCE_MISMATCH")
    authority_boundary = manifest.get("authority_boundary", {})
    required_authority_boundary = {
        "selector_production_materialization_permitted": False,
        "materializer_implementation_is_not_materialization_authority": True,
        "separate_exact_canonical_write_authority_required": True,
        "process_launch_authority_created": False,
    }
    _require_semantic_mapping(
        authority_boundary,
        required_authority_boundary,
        "AUDIT_MANIFEST_AUTHORITY_BOUNDARY",
    )
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise ContractError("AUDIT_MANIFEST_FORBIDDEN_CLAIM")
    publication = manifest.get("publication", {})
    required_publication = {
        "method": "mkdirat target reservation plus manifest O_EXCL last",
        "commit_marker": "materialization_manifest.json",
        "commit_marker_written_exclusive_last": True,
        "tree_without_commit_marker_is_uncommitted": True,
        "runner_requires_independent_audit_receipt": True,
        "exact_file_and_directory_closure_required": True,
    }
    for key, expected in required_publication.items():
        if publication.get(key) != expected:
            raise ContractError(f"AUDIT_MANIFEST_PUBLICATION_MISMATCH:{key}")
    selection = manifest.get("selection", {})
    expected_selection = {
        "sequence_id": "A09",
        "warm_start": True,
        "cold_start": False,
        "camera_indices_inclusive_for_feed": [
            contract.camera_start_index,
            contract.camera_end_index,
        ],
        "camera_count_for_feed": contract.camera_count,
        "preroll_camera_indices_half_open": [
            contract.camera_start_index,
            SCORE_START_INDEX,
        ],
        "preroll_camera_count": SCORE_START_INDEX - contract.camera_start_index,
        "score_camera_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
        "score_camera_count": SCORE_END_INDEX - SCORE_START_INDEX + 1,
        "synthetic_or_extrapolated_imu_used": False,
    }
    for key, expected in expected_selection.items():
        if selection.get(key) != expected:
            raise ContractError(f"AUDIT_MANIFEST_SELECTION_MISMATCH:{key}")
    if selection.get("initialization_and_preroll_excluded_from_score") is not True:
        raise ContractError("AUDIT_MANIFEST_SCORE_BOUNDARY_MISMATCH")
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
                raise ContractError(
                    f"AUDIT_MANIFEST_CAMERA_FILE_MISMATCH:{key}"
                )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "input_root": str(root.resolve()),
        "source": source_identity,
        "selector_freeze": provenance["selector_freeze"],
        "payload_pin_derivation_freeze": provenance[
            "payload_pin_derivation_freeze"
        ],
        "runability_protocol": provenance["runability_protocol"],
        "authority_boundary": required_authority_boundary,
        "source_choice": provenance["source_choice"],
        "configuration_authority": provenance["archaeology_config"],
        "file_count_including_manifest": len(tree["files"]),
        "directory_count_excluding_root": len(tree["directories"]),
        "payload_file_count_excluding_manifest": len(image_rows)
        + len(generated_rows),
        "camera": {
            "count": len(image_rows),
            "source_indices_inclusive": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "header_ns_inclusive": [camera_stamps[0], camera_stamps[-1]],
            "total_png_bytes": image_total,
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "chunk_count_histogram": histogram,
            "inventory_identity": image_identity,
            "source_members": source_comparison["member_identities"],
            "source_members_compared": source_comparison[
                "source_members_compared"
            ],
            "all_output_png_bytes_identical_to_canonical_source_members": True,
            "source_gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "score_boundary": {
            "preroll_camera_indices_half_open": [
                contract.camera_start_index,
                SCORE_START_INDEX,
            ],
            "score_camera_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
            "initialization_and_preroll_excluded_from_score": True,
        },
        "imu": imu,
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": core.identity_file(
            manifest_path, "materialization_manifest.json"
        ),
        "publication": {
            "materialization_commit_marker_valid": True,
            "target_was_reserved_by_no_clobber_mkdirat": True,
            "independent_source_rederivation_passed": True,
            "exact_file_and_directory_closure_passed": True,
            "independent_audit_receipt_required_before_runner": True,
            "this_result_is_the_receipt_payload": True,
        },
        "reporting_boundary": (
            "development-only warm-start input preparation; no HFNet process, "
            "trajectory, accuracy, or comparison"
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
    if os.path.lexists(os.fspath(path)):
        raise ContractError(f"NO_CLOBBER_REPORT_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444
    )
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
    parser.add_argument(
        "--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE
    )
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--short-bag", type=Path, default=DEFAULT_SHORT_BAG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--report",
        type=Path,
        help="optional no-clobber JSON receipt outside the immutable input tree",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.report is not None and os.path.lexists(os.fspath(args.report)):
            raise ContractError(f"NO_CLOBBER_REPORT_EXISTS:{args.report}")
        if args.action == "preflight":
            result = preflight_result(
                args.selector_freeze,
                args.source_archive,
                args.short_bag,
                args.config,
                args.output_root,
            )
        elif args.action == "materialize":
            result = materialize(
                args.selector_freeze,
                args.source_archive,
                args.short_bag,
                args.config,
                args.output_root,
            )
        elif args.action == "audit":
            result = audit(
                args.output_root,
                args.selector_freeze,
                args.source_archive,
                args.short_bag,
                args.config,
            )
        else:
            materialization = materialize(
                args.selector_freeze,
                args.source_archive,
                args.short_bag,
                args.config,
                args.output_root,
            )
            independent_audit = audit(
                args.output_root,
                args.selector_freeze,
                args.source_archive,
                args.short_bag,
                args.config,
            )
            result = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "status": (
                    "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_"
                    "PREPARATION_ONLY"
                ),
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
