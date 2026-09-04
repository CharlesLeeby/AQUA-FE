#!/usr/bin/env python3
"""Independently audit one prepared AQUALOC positive cold-start input.

The auditor does not call the materializer.  It re-hashes and decodes every
output PNG, checks exact generated-file and payload identities, validates the
camera/IMU reader brackets, streams the canonical archive to prove byte
preservation, and cross-checks A02/A07 against the frozen historical every2
feature bags.  It starts no scientific process.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile
from typing import Any, Dict, Mapping, Optional, Sequence, Set
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_aqualoc_old_positive_coldstart_roster_v1 as contract


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "scripts/audit_hfnet_v6_a06_0000_2460_exact_window_input_v1.py"
ENGINE_SIZE = 17_765
ENGINE_SHA256 = "b41412233b3c403d0ca8fb2841374a3c97484cce7bbe260bb4be8c780a46d3a2"
SCHEMA_VERSION = "aqua-fe-hfnet-v6-aqualoc-old-positive-coldstart-independent-input-audit-v1"
RUNNER_BINDING_SCHEMA = "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1"


def _load_engine(path: Path):
    spec = importlib.util.spec_from_file_location("hfnet_v6_aqualoc_coldstart_independent_engine", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("INDEPENDENT_ENGINE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engine = _load_engine(ENGINE_PATH)
AuditError = engine.AuditError
Profile = contract.Profile


def configure_engine(profile: Profile) -> None:
    engine.CAMERA_FIRST_NS = profile.camera_first_ns
    engine.CAMERA_LAST_NS = profile.camera_last_ns
    engine.CAMERA_COUNT = profile.camera_count
    engine.IMU_COUNT = profile.imu_last_index - profile.imu_first_index + 1
    engine.IMU_ENDPOINTS = tuple(int(value) for value in profile.imu_output_endpoints)
    engine.EXPECTED_GENERATED = {
        "cam0_times.txt": tuple(profile.times_pin),
        "mav0/cam0/data.csv": tuple(profile.camera_csv_pin),
        "mav0/imu0/data.csv": tuple(profile.imu_output_pin),
    }


def compare_to_source(
    profile: Profile, source: Path, output_rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    expected = {
        f"frame{source_index:06d}.png": output_rows[source_index - profile.start]
        for source_index in range(profile.start, profile.end + 1)
    }
    seen: Set[str] = set()
    try:
        with tarfile.open(str(source), "r|gz") as tar:
            for member in tar:
                if not member.name.startswith(profile.image_member_prefix):
                    continue
                name = member.name[len(profile.image_member_prefix) :]
                output = expected.get(name)
                if output is None:
                    continue
                if name in seen or not member.isreg() or member.issym() or member.islnk():
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_INVALID:{name}")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise AuditError(f"SOURCE_IMAGE_UNREADABLE:{name}")
                payload = extracted.read()
                observed = (
                    len(payload),
                    engine.hashlib.sha256(payload).hexdigest(),
                    f"{zlib.crc32(payload) & 0xffffffff:08x}",
                )
                wanted = (output["size_bytes"], output["sha256"], output["crc32"])
                if observed != wanted:
                    raise AuditError(f"SOURCE_OUTPUT_BYTES_DIFFER:{name}")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise AuditError(f"SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error
    if seen != set(expected):
        raise AuditError(f"SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    return {
        "source_members_compared": len(seen),
        "source_indices_inclusive": [profile.start, profile.end],
        "all_output_png_bytes_identical_to_canonical_source_members": True,
        "source_gzip_stream_fully_consumed_and_crc_checked": True,
    }


def crosscheck_legacy_window(profile: Profile, camera_stamps: Sequence[int]) -> Dict[str, Any]:
    if not all(
        value is not None
        for value in (
            profile.legacy_full_bag_path,
            profile.legacy_full_bag_size,
            profile.legacy_full_bag_sha256,
        )
    ):
        return {"status": "NOT_CONFIGURED_FOR_THIS_PROFILE", "same_window_claimed": False}
    legacy_stamps = list(camera_stamps)
    if profile.legacy_times_path is not None:
        times_path = Path(str(profile.legacy_times_path))
        times_identity: Mapping[str, Any] = engine.require_identity(
            times_path,
            int(profile.times_pin[0]),
            str(profile.times_pin[1]),
            "LEGACY_WINDOW_TIMES",
        )
        try:
            legacy_stamps = [int(line) for line in times_path.read_text(encoding="ascii").splitlines()]
        except ValueError as error:
            raise AuditError("LEGACY_WINDOW_TIMES_INVALID") from error
        if list(camera_stamps) != legacy_stamps:
            raise AuditError("LEGACY_WINDOW_CAMERA_HEADERS_DIFFER")
    else:
        times_identity = {
            "status": "NO_SEPARATE_FULL_HEADER_FILE; BAG_HEADERS_CROSSCHECKED_DIRECTLY"
        }
    bag_path = Path(str(profile.legacy_full_bag_path))
    bag_identity = engine.require_identity(
        bag_path,
        int(profile.legacy_full_bag_size),
        str(profile.legacy_full_bag_sha256),
        "LEGACY_FULL_FEATURE_BAG",
    )
    try:
        import rosbag  # type: ignore

        feature_stamps = []
        with rosbag.Bag(str(bag_path), "r") as bag:
            for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
                feature_stamps.append(int(message.header.stamp.to_nsec()))
    except Exception as error:
        raise AuditError(f"LEGACY_FULL_FEATURE_BAG_UNREADABLE:{type(error).__name__}") from error
    if feature_stamps != legacy_stamps[1::2]:
        raise AuditError("LEGACY_EVERY2_HEADERS_DIFFER_FROM_PREPARED_WINDOW")
    return {
        "status": "PASS_EXACT_HISTORICAL_WINDOW_CROSSCHECK",
        "legacy_exact_window_times": times_identity,
        "legacy_full_feature_bag": bag_identity,
        "source_camera_count": len(legacy_stamps),
        "source_camera_header_ns_inclusive": [legacy_stamps[0], legacy_stamps[-1]],
        "legacy_every2_feature_count": len(feature_stamps),
        "all_legacy_every2_headers_equal_source_relative_odd_indices": True,
        "same_window_claimed": True,
    }


def build_runner_binding(
    profile: Profile,
    root: Path,
    manifest_path: Path,
    config_identity: Mapping[str, Any],
    camera_stamps: Sequence[int],
    imu: Mapping[str, Any],
) -> Dict[str, Any]:
    if len(camera_stamps) != profile.camera_count:
        raise AuditError("RUNNER_BINDING_CAMERA_COUNT_MISMATCH")
    if imu.get("reader_bracket_valid") is not True:
        raise AuditError("RUNNER_BINDING_IMU_READER_BRACKET_INVALID")
    manifest_identity = engine.hash_file(manifest_path, str(manifest_path.resolve()))
    return {
        "schema_version": RUNNER_BINDING_SCHEMA,
        "case_id": profile.key,
        "input_root": str(root.resolve()),
        "input_manifest": {
            "path": str(manifest_path.resolve()),
            "size_bytes": manifest_identity["size_bytes"],
            "sha256": manifest_identity["sha256"],
        },
        "base_config": {
            "path": str(Path(str(config_identity["path"])).resolve()),
            "size_bytes": int(config_identity["size_bytes"]),
            "sha256": str(config_identity["sha256"]),
        },
        "camera_count": len(camera_stamps),
        "camera_header_ns_inclusive": [int(camera_stamps[0]), int(camera_stamps[-1])],
        "score_relative_indices_inclusive": [0, len(camera_stamps) - 1],
        "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
        "times_relative_path": "cam0_times.txt",
        "images_relative_path": "mav0/cam0/data",
        "image_extension": ".png",
        "imu_relative_path": "mav0/imu0/data.csv",
        "imu_reader_bracket_valid": True,
    }


def audit(
    profile: Profile,
    root: Path,
    source: Path,
    config_path: Path = contract.DEFAULT_CONFIG,
    roster_path: Path = contract.DEFAULT_ROSTER,
) -> Dict[str, Any]:
    root, source, config_path, roster_path = map(Path, (root, source, config_path, roster_path))
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    reused_engine = engine.require_identity(ENGINE_PATH, ENGINE_SIZE, ENGINE_SHA256, "INDEPENDENT_ENGINE")
    source_identity = engine.require_identity(source, profile.source_size, profile.source_sha256, "SOURCE")
    roster_identity = engine.require_identity(roster_path, contract.ROSTER_SIZE, contract.ROSTER_SHA256, "ROSTER")
    config_identity = engine.require_identity(config_path, contract.CONFIG_SIZE, contract.CONFIG_SHA256, "CONFIG")
    configure_engine(profile)
    stamps, image_rows, histogram = engine.parse_camera(root)
    generated_rows = engine.check_generated(root)
    imu = engine.parse_imu(root, stamps)
    image_identity = engine.aggregate(image_rows)
    expected_image_identity = {
        "sha256": profile.renamed_inventory_sha256,
        "crc32": profile.renamed_inventory_crc32,
    }
    if sum(int(row["size_bytes"]) for row in image_rows) != profile.image_total_bytes:
        raise AuditError("IMAGE_TOTAL_BYTES_MISMATCH")
    if image_identity != expected_image_identity:
        raise AuditError("IMAGE_INVENTORY_IDENTITY_MISMATCH")
    payload_identity = engine.aggregate(list(image_rows) + generated_rows)
    expected_payload_identity = {"sha256": profile.payload_sha256, "crc32": profile.payload_crc32}
    if payload_identity != expected_payload_identity:
        raise AuditError("PAYLOAD_IDENTITY_MISMATCH")
    expected_paths = {str(row["path"]) for row in list(image_rows) + generated_rows}
    expected_paths.add("materialization_manifest.json")
    observed_paths: Set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"OUTPUT_NONREGULAR:{path}")
        observed_paths.add(path.relative_to(root).as_posix())
    if observed_paths != expected_paths:
        raise AuditError("OUTPUT_FILE_SET_MISMATCH")
    source_comparison = compare_to_source(profile, source, image_rows)
    legacy_crosscheck = crosscheck_legacy_window(profile, stamps)
    manifest_path = root / "materialization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != contract.SCHEMA_VERSION or manifest.get("status") != "PASS_PREPARATION_ONLY" or manifest.get("profile") != profile.key:
        raise AuditError("MANIFEST_SCHEMA_STATUS_OR_PROFILE_MISMATCH")
    expected_manifest_payload = {
        "algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n",
        **expected_payload_identity,
    }
    if manifest.get("payload_identity_excluding_manifest") != expected_manifest_payload:
        raise AuditError("MANIFEST_PAYLOAD_PIN_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise AuditError("MANIFEST_FORBIDDEN_CLAIM")
    selection = manifest.get("selection", {})
    if (
        selection.get("camera_indices_inclusive") != [profile.start, profile.end]
        or selection.get("score_camera_indices_inclusive") != [profile.start, profile.end]
        or selection.get("score_relative_indices_inclusive") != [0, profile.camera_count - 1]
        or selection.get("history_policy") != "exact_window_cold_start"
        or selection.get("preroll_camera_count") != 0
        or selection.get("synthetic_imu_samples_added") is not False
    ):
        raise AuditError("MANIFEST_SELECTION_BOUNDARY_MISMATCH")
    runner_binding = build_runner_binding(
        profile, root, manifest_path, config_identity, stamps, imu
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "profile": profile.key,
        "input_root": str(root.resolve()),
        "reused_independent_engine": reused_engine,
        "source": source_identity,
        "roster": roster_identity,
        "config": config_identity,
        "file_count_including_manifest": len(observed_paths),
        "payload_file_count_excluding_manifest": len(image_rows) + len(generated_rows),
        "camera": {
            "count": len(image_rows),
            "header_ns_inclusive": [stamps[0], stamps[-1]],
            "source_indices_inclusive": [profile.start, profile.end],
            "total_png_bytes": profile.image_total_bytes,
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "chunk_count_histogram": histogram,
            "inventory_identity": image_identity,
            **source_comparison,
        },
        "imu": {**imu, "source_zero_based_indices_inclusive": [profile.imu_first_index, profile.imu_last_index], "time_transform": "output_ns=raw_ns+53694112", "synthetic_samples_added": False},
        "legacy_window_crosscheck": legacy_crosscheck,
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": engine.hash_file(manifest_path, "materialization_manifest.json"),
        "runner_binding": runner_binding,
        "reporting_boundary": "preparation-only same-window cold-start audit; no runability, trajectory, accuracy, or ranking",
        "claims": {"hfnet_started": False, "trajectory_produced": False, "accuracy_measured": False, "system_ranking_supported": False},
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(contract.PROFILES), required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--config", type=Path, default=contract.DEFAULT_CONFIG)
    parser.add_argument("--roster", type=Path, default=contract.DEFAULT_ROSTER)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        profile = contract.PROFILES[args.profile]
        result = audit(profile, args.input_root or profile.output_root, args.source_archive or profile.source_archive, args.config, args.roster)
        return_code = 0
    except Exception as error:
        result = {"schema_version": SCHEMA_VERSION, "status": "INTEGRITY_ERROR", "errors": [f"{type(error).__name__}:{error}"], "claims": {"hfnet_started": False, "trajectory_produced": False}}
        return_code = 2
    payload = contract.core.canonical_json(result)
    if args.report is not None:
        write_exclusive(args.report, payload)
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
