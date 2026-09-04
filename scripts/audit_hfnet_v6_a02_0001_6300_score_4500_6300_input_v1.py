#!/usr/bin/env python3
"""Independently audit the A02 source-1..6300 HFNet input tree.

This auditor does not import the A02 materializer.  It reuses only the sealed
A06 independent-audit primitives, then independently re-hashes and decodes all
6300 PNG files, verifies the exact camera and shifted-IMU reader brackets, and
streams the canonical A02 archive to prove byte preservation.  It starts no
scientific process.
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


ROOT = Path(__file__).resolve().parents[1]
REUSED_AUDITOR = ROOT / "scripts/audit_hfnet_v6_a06_0000_2460_exact_window_input_v1.py"
REUSED_AUDITOR_SIZE = 17_765
REUSED_AUDITOR_SHA256 = "b41412233b3c403d0ca8fb2841374a3c97484cce7bbe260bb4be8c780a46d3a2"


def _load(path: Path):
    specification = importlib.util.spec_from_file_location("hfnet_v6_a02_reused_a06_independent_auditor", str(path))
    if specification is None or specification.loader is None:
        raise RuntimeError("REUSED_A06_AUDITOR_IMPORT_FAILED")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


engine = _load(REUSED_AUDITOR)
AuditError = engine.AuditError

INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a02_full_history_v1/"
    "aqualoc_archaeology_a02_0001_6300"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
)
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a02_0001_6300_score_4500_6300_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_selector_freeze_v1.json"
IMAGE_PREFIX = "raw_data/images_sequence_2/"

SCHEMA_VERSION = "aqua-fe-hfnet-v6-a02-0001-6300-score-4500-6300-independent-input-audit-v1"
MATERIALIZATION_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-score-4500-6300-input-materialization-v1"
SOURCE_SIZE = 2_195_786_266
SOURCE_SHA256 = "8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69"
SELECTOR_SIZE = 3_320
SELECTOR_SHA256 = "54e1340a4fe655be30b971d89178e8c588b1b973a93e4287b6ed6dd39feb7505"
CONFIG_SIZE = 2_024
CONFIG_SHA256 = "b08c38d73347e4a506a43b3114b014a445d03df9fd76d01f75a1a9300de99b23"

SOURCE_CAMERA_FIRST = 1
SOURCE_CAMERA_LAST = 6_300
CAMERA_FIRST_NS = 1_542_828_791_787_420_320
CAMERA_LAST_NS = 1_542_829_106_687_510_592
CAMERA_COUNT = 6_300
SCORE_RELATIVE = [4_499, 6_299]
SCORE_SOURCE = [4_500, 6_300]
IMU_COUNT = 62_939
IMU_ENDPOINTS = (
    1_542_828_791_783_309_344,
    1_542_828_791_788_632_128,
    1_542_829_106_686_399_136,
    1_542_829_106_691_806_560,
)
EXPECTED_GENERATED = {
    "cam0_times.txt": (
        126_000,
        "0b117ff76aec9266260ffad4c075b6c669b8f816e7ab19f2f1bbf4d5b44d9d4d",
        "8cd30fea",
    ),
    "mav0/cam0/data.csv": (
        277_225,
        "ad9f7795cc7ca931ece0e8294dcfe3af87a266cc7d656de6b233e964e8164113",
        "796bb5d8",
    ),
    "mav0/imu0/data.csv": (
        7_100_776,
        "accf260a3bc99dc90c91db33e57be9fe720f702362bd4c3dca17252c2d15cc47",
        "93d98670",
    ),
}
EXPECTED_IMAGE_BYTES = 1_525_166_693
EXPECTED_IMAGE_INVENTORY_SHA256 = "1f06f9ddc43c8fdfd946719b389a1809d0194128c6ec5b963f13f9b27fa77ff0"
EXPECTED_IMAGE_INVENTORY_CRC32 = "76115d23"
EXPECTED_PAYLOAD_SHA256 = "86d2730e32d82b37cf6811c73dfe6b66368fb208877911d7ca7720686e358a58"
EXPECTED_PAYLOAD_CRC32 = "8481e897"


def _require_reused_auditor() -> Dict[str, Any]:
    return engine.require_identity(
        REUSED_AUDITOR,
        REUSED_AUDITOR_SIZE,
        REUSED_AUDITOR_SHA256,
        "REUSED_A06_INDEPENDENT_AUDITOR",
    )


def compare_to_source(source: Path, output_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    expected = {
        f"frame{source_index:06d}.png": output_rows[source_index - SOURCE_CAMERA_FIRST]
        for source_index in range(SOURCE_CAMERA_FIRST, SOURCE_CAMERA_LAST + 1)
    }
    seen: Set[str] = set()
    try:
        with tarfile.open(str(source), "r|gz") as tar:
            for member in tar:
                if not member.name.startswith(IMAGE_PREFIX):
                    continue
                name = member.name[len(IMAGE_PREFIX) :]
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
                expected_identity = (
                    output["size_bytes"],
                    output["sha256"],
                    output["crc32"],
                )
                if observed != expected_identity:
                    raise AuditError(f"SOURCE_OUTPUT_BYTES_DIFFER:{name}")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise AuditError(f"SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error
    if seen != set(expected):
        raise AuditError(f"SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    return {
        "source_members_compared": len(seen),
        "source_camera_indices_inclusive": [SOURCE_CAMERA_FIRST, SOURCE_CAMERA_LAST],
        "all_output_png_bytes_identical_to_canonical_source_members": True,
        "source_gzip_stream_fully_consumed_and_crc_checked": True,
    }


# Configure the reused independent primitives. No A02 materializer is imported.
for _name, _value in {
    "INPUT_ROOT": INPUT_ROOT,
    "SOURCE_ARCHIVE": SOURCE_ARCHIVE,
    "CONFIG": CONFIG,
    "SELECTOR": SELECTOR,
    "IMAGE_PREFIX": IMAGE_PREFIX,
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "SOURCE_SIZE": SOURCE_SIZE,
    "SOURCE_SHA256": SOURCE_SHA256,
    "SELECTOR_SIZE": SELECTOR_SIZE,
    "SELECTOR_SHA256": SELECTOR_SHA256,
    "CONFIG_SIZE": CONFIG_SIZE,
    "CONFIG_SHA256": CONFIG_SHA256,
    "CAMERA_FIRST_NS": CAMERA_FIRST_NS,
    "CAMERA_LAST_NS": CAMERA_LAST_NS,
    "CAMERA_COUNT": CAMERA_COUNT,
    "IMU_COUNT": IMU_COUNT,
    "IMU_ENDPOINTS": IMU_ENDPOINTS,
    "EXPECTED_GENERATED": EXPECTED_GENERATED,
    "EXPECTED_IMAGE_BYTES": EXPECTED_IMAGE_BYTES,
    "EXPECTED_IMAGE_INVENTORY_SHA256": EXPECTED_IMAGE_INVENTORY_SHA256,
    "EXPECTED_IMAGE_INVENTORY_CRC32": EXPECTED_IMAGE_INVENTORY_CRC32,
    "EXPECTED_PAYLOAD_SHA256": EXPECTED_PAYLOAD_SHA256,
    "EXPECTED_PAYLOAD_CRC32": EXPECTED_PAYLOAD_CRC32,
    "compare_to_source": compare_to_source,
}.items():
    setattr(engine, _name, _value)


def audit(root: Path, source: Path, config: Path, selector: Path) -> Dict[str, Any]:
    root, source, config, selector = map(Path, (root, source, config, selector))
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    reused = _require_reused_auditor()
    source_identity = engine.require_identity(source, SOURCE_SIZE, SOURCE_SHA256, "SOURCE")
    selector_identity = engine.require_identity(selector, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR")
    config_identity = engine.require_identity(config, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    stamps, image_rows, histogram = engine.parse_camera(root)
    generated_rows = engine.check_generated(root)
    imu = engine.parse_imu(root, stamps)
    image_identity = engine.aggregate(image_rows)
    if sum(int(row["size_bytes"]) for row in image_rows) != EXPECTED_IMAGE_BYTES:
        raise AuditError("IMAGE_TOTAL_BYTES_MISMATCH")
    if image_identity != {
        "sha256": EXPECTED_IMAGE_INVENTORY_SHA256,
        "crc32": EXPECTED_IMAGE_INVENTORY_CRC32,
    }:
        raise AuditError("IMAGE_INVENTORY_IDENTITY_MISMATCH")
    payload_identity = engine.aggregate(list(image_rows) + generated_rows)
    if payload_identity != {
        "sha256": EXPECTED_PAYLOAD_SHA256,
        "crc32": EXPECTED_PAYLOAD_CRC32,
    }:
        raise AuditError("PAYLOAD_IDENTITY_MISMATCH")
    expected_paths = {str(row["path"]) for row in image_rows + generated_rows}
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
    source_comparison = compare_to_source(source, image_rows)
    manifest_path = root / "materialization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS_PREPARATION_ONLY" or manifest.get("schema_version") != MATERIALIZATION_SCHEMA:
        raise AuditError("MANIFEST_STATUS_OR_SCHEMA_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != {
        "algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n",
        "sha256": EXPECTED_PAYLOAD_SHA256,
        "crc32": EXPECTED_PAYLOAD_CRC32,
    }:
        raise AuditError("MANIFEST_PAYLOAD_PIN_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise AuditError("MANIFEST_FORBIDDEN_CLAIM")
    selection = manifest.get("selection", {})
    if (
        selection.get("camera_indices_inclusive") != [1, 6300]
        or selection.get("score_source_camera_indices_inclusive") != SCORE_SOURCE
        or selection.get("score_relative_indices_inclusive") != SCORE_RELATIVE
        or selection.get("camera_zero_trimmed_for_missing_shifted_imu_predecessor") is not True
        or selection.get("synthetic_imu_samples_added") is not False
        or selection.get("development_result_conditioned_selection") is not True
    ):
        raise AuditError("MANIFEST_SELECTION_OR_TRIM_BOUNDARY_MISMATCH")
    selector_value = json.loads(selector.read_text(encoding="utf-8"))
    if selector_value.get("knowledge_boundary", {}).get("p07_artifacts_are_read_only_and_must_not_be_backfilled") is not True:
        raise AuditError("SELECTOR_P07_BOUNDARY_MISSING")
    config_text = config.read_text(encoding="utf-8")
    for required in (
        'Camera.type: "PinHole"',
        "Camera.width: 968",
        "Camera.height: 608",
        "IMU.NoiseGyro: 0.003",
        "IMU.NoiseAcc: 0.05",
        "IMU.GyroWalk: 0.0001",
        "IMU.AccWalk: 0.0015",
        "IMU.Frequency: 200.0",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    ):
        if required not in config_text:
            raise AuditError(f"CONFIG_REQUIRED_PIN_MISSING:{required}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "input_root": str(root.resolve()),
        "reused_independent_auditor": reused,
        "source": source_identity,
        "selector_freeze": selector_identity,
        "config": config_identity,
        "file_count_including_manifest": len(observed_paths),
        "payload_file_count_excluding_manifest": len(image_rows) + len(generated_rows),
        "camera": {
            "count": len(image_rows),
            "header_ns_inclusive": [stamps[0], stamps[-1]],
            "source_indices_inclusive": [SOURCE_CAMERA_FIRST, SOURCE_CAMERA_LAST],
            "score_source_camera_indices_inclusive": SCORE_SOURCE,
            "score_relative_indices_inclusive": SCORE_RELATIVE,
            "total_png_bytes": EXPECTED_IMAGE_BYTES,
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "chunk_count_histogram": histogram,
            "inventory_identity": image_identity,
            **source_comparison,
        },
        "imu": {
            **imu,
            "time_transform": "output_ns=raw_ns+53694112",
            "synthetic_samples_added": False,
            "source_zero_based_indices_inclusive": [2, 62940],
        },
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": engine.hash_file(manifest_path, "materialization_manifest.json"),
        "reporting_boundary": (
            "development-only full-history input preparation; old A02 and P07 evidence remain read-only; "
            "no trajectory, accuracy, or comparison"
        ),
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


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    parser.add_argument("--source-archive", type=Path, default=SOURCE_ARCHIVE)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--selector-freeze", type=Path, default=SELECTOR)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.input_root, args.source_archive, args.config, args.selector_freeze)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {"hfnet_started": False, "trajectory_produced": False},
        }
        return_code = 2
    payload = canonical_json(result)
    if args.report is not None:
        write_exclusive(args.report, payload)
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
