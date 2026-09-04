#!/usr/bin/env python3
"""Prepare and independently audit the A10 HFNet warm-start input only.

Canonical AQUALOC A10 frames 0..2800 are fed without a backend reset.  Frames
0..2399 are history only; any later runner must score only frames 2400..2800.
Raw archive PNG members are copied byte-for-byte and IMU timestamps receive the
frozen archaeology +53694112 ns clock shift.  Publication is atomic and
no-clobber.  This module has no process launcher and never starts HFNet, ROS,
VINS, a detector, or an evaluator.
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
from scripts import materialize_hfnet_positive_a10_2400_2800_coldstart_v1 as base


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = (
    "aqua-fe-hfnet-positive-a10-0000-2800-score-2400-2800-"
    "warmstart-materialization-v1"
)
AUDIT_SCHEMA_VERSION = (
    "aqua-fe-hfnet-positive-a10-0000-2800-score-2400-2800-"
    "warmstart-independent-audit-v1"
)
SELECTOR_SCHEMA_VERSION = "aqua-fe-hfnet-v6-a10-warmstart-selector-freeze-v1"

BASE_ADAPTER_PATH = (
    ROOT / "scripts/materialize_hfnet_positive_a10_2400_2800_coldstart_v1.py"
)
BASE_ADAPTER_SIZE = 37_461
BASE_ADAPTER_SHA256 = "3565a6bdb8c6e437c60f465023be6f1d0a390b768de7953b303522b02f6074a0"

DEFAULT_SELECTOR_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a10_0000_2800_score_2400_2800_"
    "warmstart_selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 2_872
SELECTOR_FREEZE_SHA256 = "8ec2f5454f9db9f179c1125f41718a710b35ee85e721e7f696d5d284458fd078"

DEFAULT_SOURCE_ARCHIVE = base.DEFAULT_SOURCE_ARCHIVE
DEFAULT_SHORT_BAG = base.DEFAULT_SHORT_BAG
DEFAULT_CONFIG = base.DEFAULT_CONFIG
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a10_0000_2800_score_2400_2800_warmstart"
)
DEFAULT_AUDIT_REPORT = Path(str(DEFAULT_OUTPUT_ROOT) + ".audit.json")

FEED_START_INDEX = 0
FEED_END_INDEX = 2_800
SCORE_START_INDEX = 2_400
SCORE_END_INDEX = 2_800
SCORE_FIRST_NS = 1_542_888_916_043_622_160
SCORE_LAST_NS = 1_542_888_936_039_921_424

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
        size_bytes=3_761_302_356,
        sha256="e8bde74e147236c15fe70d0385c618a75b2fc6e18e6f369dc12e355b49faceee",
    ),
    source_gzip_crc32="f35c87a1",
    source_gzip_isize=3_798_589_440,
    image_csv_member="raw_data/img_sequence_10.csv",
    image_csv_pin=FilePin(
        size_bytes=514_574,
        sha256="7d34396a421e508a5c13f227cf6d60974ba2e6b9114fa7d26d0bc28583a3be8a",
        crc32="70604988",
    ),
    imu_csv_member="raw_data/imu_sequence_10.csv",
    imu_csv_pin=FilePin(
        size_bytes=15_978_793,
        sha256="c9c667f8d89c89f04536d7c341a15f2878ededfaba61e85e949c9accdbffa6c4",
        crc32="39ba0a0a",
    ),
    image_member_prefix="raw_data/images_sequence_10/",
    source_camera_count=14_293,
    source_imu_count=142_828,
    camera_start_index=FEED_START_INDEX,
    camera_end_index=FEED_END_INDEX,
    camera_first_ns=1_542_888_796_062_978_800,
    camera_last_ns=1_542_888_936_039_921_424,
    width=968,
    height=608,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=53_694_112,
    imu_first_index=28,
    imu_last_index=28_003,
    imu_first_raw_ns=1_542_888_796_004_612_880,
    imu_last_raw_ns=1_542_888_935_988_415_664,
    imu_first_output_ns=1_542_888_796_058_306_992,
    imu_second_output_ns=1_542_888_796_063_392_976,
    imu_penultimate_output_ns=1_542_888_936_037_078_064,
    imu_last_output_ns=1_542_888_936_042_109_776,
    expected_image_total_bytes=728_611_326,
    expected_source_image_inventory_sha256=(
        "f91bc5744f604fef888a52e23a2837118a70b71e564add3561208defdfdac827"
    ),
    expected_source_image_inventory_crc32="9c8ad642",
    expected_renamed_image_inventory_sha256=(
        "67f81ab424076f31cbaab8c70a2ee72c7b9686ecf9dfc532a4f9a9c35994f418"
    ),
    expected_renamed_image_inventory_crc32="e55cdc5a",
    times_pin=FilePin(
        size_bytes=56_020,
        sha256="94f7ea8c9cfdfc0af8e5e89efdc19f3c878dd7aaef459a4e97120bedb8048572",
        crc32="5df12785",
    ),
    camera_csv_pin=FilePin(
        size_bytes=123_269,
        sha256="3165952817d400b8039a5f2ac956d1b121c50dd49097136dfcddd52334045704",
        crc32="2368a331",
    ),
    imu_output_pin=FilePin(
        size_bytes=3_124_993,
        sha256="c56d304b4619e6bd45ab9ea53f2094c0586c1a159aaa9823e5d2cf9a261b31ed",
        crc32="fed45218",
    ),
    expected_payload_sha256=(
        "2213e27475bf379bc65d9873f242075489faffbb12d52ae8ad03a2611d8839d8"
    ),
    expected_payload_crc32="67de0168",
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
        "sequence_id": "A10",
        "camera_indices_inclusive_for_feed": [FEED_START_INDEX, FEED_END_INDEX],
        "preroll_camera_indices_half_open": [FEED_START_INDEX, SCORE_START_INDEX],
        "score_camera_indices_inclusive": [SCORE_START_INDEX, SCORE_END_INDEX],
        "warm_start": True,
    }
    for key, expected in required.items():
        if selection.get(key) != expected:
            raise ContractError(f"SELECTOR_FREEZE_SELECTION_MISMATCH:{key}")
    if (
        value.get("knowledge_boundary", {}).get(
            "development_result_conditioned_selection"
        )
        is not True
    ):
        raise ContractError("SELECTOR_DEVELOPMENT_EXPOSURE_NOT_DISCLOSED")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


def _require_provenance(
    selector_freeze: Path, short_bag: Path, config: Path
) -> Dict[str, Any]:
    reused_base = _require_identity(
        BASE_ADAPTER_PATH,
        FilePin(BASE_ADAPTER_SIZE, BASE_ADAPTER_SHA256),
        "REUSED_A10_COLDSTART_ADAPTER",
    )
    selector = validate_selector(selector_freeze)
    inherited = base._require_provenance(short_bag, config)
    return {
        **inherited,
        "reused_a10_coldstart_adapter": reused_base,
        "selector_freeze": selector,
    }


def _require_output_absent(output_root: Path) -> None:
    if os.path.lexists(os.fspath(output_root)):
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")


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
        for path in self.path.rglob("*"):
            if path.is_symlink():
                raise ContractError(f"PRECOMMIT_OUTPUT_SYMLINK:{path}")
            observed = path.lstat()
            if stat.S_ISDIR(observed.st_mode):
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise ContractError(f"PRECOMMIT_OUTPUT_NONREGULAR:{path}")
            observed_paths.add(path.relative_to(self.path).as_posix())
        if observed_paths != expected_paths:
            raise ContractError("PRECOMMIT_PAYLOAD_FILE_SET_MISMATCH")

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
    """Atomically reserve target; commit only when the manifest is written last."""

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
            "a10_coldstart_adapter": metadata["reused_a10_coldstart_adapter"],
            "a06_adapter": metadata["reused_a06_adapter"],
            "a06_core": metadata["reused_a06_sealed_core"],
            "a06_independent_auditor": metadata[
                "reused_a06_independent_auditor"
            ],
        },
        "selector_freeze": metadata["selector_freeze"],
        "configuration_authority": metadata["archaeology_config"],
        "source_choice": metadata["source_choice"],
        "source": {
            **metadata["source"],
            "members": metadata["source_members"],
            "gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "selection": {
            "dataset_family": "aqualoc_archaeology",
            "sequence_id": "A10",
            "window_id": "A10_2400_2800",
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
        },
        "reporting_boundary": (
            "development-only warm-start input preparation; frames 0..2399 are "
            "history only and frames 2400..2800 are the sole score window; no "
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
    observed_paths: Set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ContractError(f"AUDIT_OUTPUT_SYMLINK:{path}")
        observed_stat = path.lstat()
        if stat.S_ISDIR(observed_stat.st_mode):
            continue
        if not stat.S_ISREG(observed_stat.st_mode):
            raise ContractError(f"AUDIT_OUTPUT_NONREGULAR:{path}")
        observed_paths.add(path.relative_to(root).as_posix())
    if observed_paths != expected_paths:
        raise ContractError("AUDIT_OUTPUT_FILE_SET_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "PASS_PREPARATION_ONLY"
    ):
        raise ContractError("AUDIT_MANIFEST_STATUS_OR_SCHEMA_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != payload_identity:
        raise ContractError("AUDIT_MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise ContractError("AUDIT_MANIFEST_FORBIDDEN_CLAIM")
    publication = manifest.get("publication", {})
    if (
        publication.get("method")
        != "mkdirat target reservation plus manifest O_EXCL last"
        or publication.get("commit_marker") != "materialization_manifest.json"
        or publication.get("commit_marker_written_exclusive_last") is not True
        or publication.get("tree_without_commit_marker_is_uncommitted") is not True
        or publication.get("runner_requires_independent_audit_receipt") is not True
    ):
        raise ContractError("AUDIT_MANIFEST_PUBLICATION_MISMATCH")
    selection = manifest.get("selection", {})
    expected_selection = {
        "sequence_id": "A10",
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
        "source_choice": provenance["source_choice"],
        "configuration_authority": provenance["archaeology_config"],
        "file_count_including_manifest": len(observed_paths),
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
        if args.report is not None and (
            args.report.exists() or args.report.is_symlink()
        ):
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
