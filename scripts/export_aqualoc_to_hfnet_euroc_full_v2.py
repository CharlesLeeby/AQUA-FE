#!/usr/bin/env python3
"""Materialize the frozen A02 full window for the HFNet-SLAM diagnostic track.

This is a post-STOP, high-level data adapter.  It deliberately lives beside,
and does not replace or modify, ``export_aqualoc_to_hfnet_euroc_v1.py`` or
the sealed 200-frame result.  The only changes to the source data are the
already-audited EuRoC directory layout, lossless PNG serialization, and the
Kalibr clock conversion required by an upstream reader with no ``td`` field.

The script never starts HFNet-SLAM.  ``preflight`` is read-only; ``export``
uses a new no-clobber directory and an atomic rename.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from scripts import export_aqualoc_to_hfnet_euroc_v1 as base


ADAPTER_VERSION = "aqualoc-hfnet-euroc-full-v2"
ARTIFACT_SCOPE = "A02_CAMERA_INDICES_0_900_FULL_POST_STOP_DIAGNOSTIC"
SCIENTIFIC_ROLE = "POST_STOP_DIAGNOSTIC_NOT_REPLACEMENT_FOR_PREFIX_R1_STOP"
BASE_ADAPTER_SHA256 = (
    "7bc4fcdae60172b00c630ae35fba1515b8969cf1a403a33a2cdbc2847cb1b9b0"
)

WORKSPACE_DEFAULT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = base.SOURCE_RELATIVE
HFNET_ROOT_DEFAULT = base.HFNET_ROOT_DEFAULT

A02_FULL_CONTRACT = base.PrefixContract(
    image_topic=base.CAMERA_TOPIC,
    imu_topic=base.IMU_TOPIC,
    expected_image_type=base.CAMERA_MESSAGE_TYPE,
    expected_imu_type=base.IMU_MESSAGE_TYPE,
    expected_total_images=901,
    expected_total_imus=9_091,
    image_first_index=0,
    image_last_index=900,
    imu_first_index=38,
    imu_last_index=9_031,
    width=968,
    height=608,
    encoding="mono8",
    imu_shift_ns=base.IMU_OUTPUT_SHIFT_NS,
    expected_first_image_stamp_ns=1_542_829_016_700_435_392,
    expected_last_image_stamp_ns=1_542_829_061_692_686_528,
    expected_first_imu_raw_stamp_ns=1_542_829_016_645_312_000,
    expected_last_imu_raw_stamp_ns=1_542_829_061_641_706_560,
)

STATUS_PREFLIGHT_READY = "PREFLIGHT_READY"
STATUS_EXPORTED = "EXPORTED"
STATUS_INTEGRITY_ERROR = "INTEGRITY_ERROR"
RC_READY = 0
RC_INTEGRITY_ERROR = 2

ContractError = base.ContractError


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_base_adapter_identity() -> dict[str, Any]:
    path = Path(base.__file__).resolve()
    observed = _sha256(path) if path.is_file() else None
    if observed != BASE_ADAPTER_SHA256:
        raise ContractError("BASE_ADAPTER_IDENTITY_MISMATCH")
    return {
        "path": str(path),
        "sha256": observed,
        "size_bytes": path.stat().st_size,
    }


def prepare(
    source_bag: Path,
    hfnet_root: Path,
    *,
    contract: base.PrefixContract = A02_FULL_CONTRACT,
    expected_size: int = base.SOURCE_SIZE_BYTES,
    expected_sha256: str = base.SOURCE_SHA256,
) -> tuple[str, dict[str, Any], base.SourceSelection, dict[str, Any]]:
    base_identity = validate_base_adapter_identity()
    source_hash, upstream = base.validate_static_identity(
        source_bag, expected_size, expected_sha256, hfnet_root
    )
    selection = base.read_source_selection(source_bag, contract)
    return source_hash, upstream, selection, base_identity


def preflight_result(
    source_bag: Path,
    source_hash: str,
    upstream: Mapping[str, Any],
    selection: base.SourceSelection,
    contract: base.PrefixContract,
    base_identity: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "artifact_scope": ARTIFACT_SCOPE,
        "base_adapter": dict(base_identity),
        "claims": {
            "full_output_created": False,
            "hfnet_source_modified": False,
            "hfnet_started": False,
            "prefix_r1_result_replaced": False,
            "trajectory_produced": False,
        },
        "contract": {
            **asdict(contract),
            "image_time_transform": "none; raw ROS header ns",
            "imu_time_transform": "output_ns=raw_header_ns+53694112",
            "kalibr_timeshift_cam_imu_s": base.KALIBR_TIMESHIFT_CAM_IMU_S,
        },
        "scientific_role": SCIENTIFIC_ROLE,
        "selection": {
            "camera_count": len(selection.cameras),
            "camera_header_ns_inclusive": [
                selection.cameras[0].header_ns,
                selection.cameras[-1].header_ns,
            ],
            "camera_indices_inclusive": [
                selection.cameras[0].source_index,
                selection.cameras[-1].source_index,
            ],
            "imu_brackets_camera": True,
            "imu_count": len(selection.imus),
            "imu_output_header_ns_inclusive": [
                selection.imus[0].output_header_ns,
                selection.imus[-1].output_header_ns,
            ],
            "imu_raw_header_ns_inclusive": [
                selection.imus[0].raw_header_ns,
                selection.imus[-1].raw_header_ns,
            ],
            "imu_indices_inclusive": [
                selection.imus[0].source_index,
                selection.imus[-1].source_index,
            ],
        },
        "source": {
            "bag": str(source_bag),
            "sha256": source_hash,
            "size_bytes": source_bag.stat().st_size,
            "topics": selection.topic_audit,
        },
        "status": STATUS_PREFLIGHT_READY,
        "upstream": dict(upstream),
    }


def write_artifact(
    output_sequence_root: Path,
    source_bag: Path,
    source_hash: str,
    selection: base.SourceSelection,
    contract: base.PrefixContract,
    upstream: Mapping[str, Any],
    base_identity: Mapping[str, Any],
) -> dict[str, Any]:
    with base.atomic_directory(output_sequence_root) as staging:
        image_directory = staging / "mav0/cam0/data"
        image_directory.mkdir(parents=True)
        image_rows: list[dict[str, Any]] = []
        aggregate_rows: list[tuple[str, str]] = []
        for sample in selection.cameras:
            filename = f"{sample.header_ns}.png"
            relative = f"mav0/cam0/data/{filename}"
            encoded = base.encode_lossless_png(sample)
            path = image_directory / filename
            path.write_bytes(encoded)
            output_hash = hashlib.sha256(encoded).hexdigest()
            image_rows.append(
                {
                    "filename": filename,
                    "pixel_identity_verified": True,
                    "png_sha256": output_hash,
                    "raw_header_ns": sample.header_ns,
                    "source_index": sample.source_index,
                    "source_pixel_sha256": sample.pixel_sha256,
                }
            )
            aggregate_rows.append((relative, output_hash))

        times_payload = base.camera_times_bytes(selection.cameras)
        times_path = staging / "cam0_times.txt"
        times_path.write_bytes(times_payload)
        times_hash = hashlib.sha256(times_payload).hexdigest()
        aggregate_rows.append(("cam0_times.txt", times_hash))

        csv_payload = base.imu_csv_bytes(selection.imus)
        imu_path = staging / "mav0/imu0/data.csv"
        imu_path.parent.mkdir(parents=True)
        imu_path.write_bytes(csv_payload)
        csv_hash = hashlib.sha256(csv_payload).hexdigest()
        aggregate_rows.append(("mav0/imu0/data.csv", csv_hash))

        duration = (
            selection.imus[-1].output_header_ns
            - selection.imus[0].output_header_ns
        ) / 1e9
        rate = (len(selection.imus) - 1) / duration
        manifest: dict[str, Any] = {
            "adapter_version": ADAPTER_VERSION,
            "artifact_scope": ARTIFACT_SCOPE,
            "base_adapter": dict(base_identity),
            "camera": {
                "count": len(selection.cameras),
                "first_raw_header_ns": selection.cameras[0].header_ns,
                "images": image_rows,
                "last_raw_header_ns": selection.cameras[-1].header_ns,
                "schema": {
                    "encoding": contract.encoding,
                    "height": contract.height,
                    "step": contract.width,
                    "width": contract.width,
                },
                "source_indices_inclusive": [
                    selection.cameras[0].source_index,
                    selection.cameras[-1].source_index,
                ],
                "strictly_monotonic": True,
                "times_file": {
                    "final_newline": True,
                    "line_count": len(selection.cameras),
                    "path": "cam0_times.txt",
                    "sha256": times_hash,
                },
            },
            "claims": {
                "full_a02_window_exported": True,
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "prefix_r1_result_replaced": False,
                "trajectory_produced": False,
            },
            "contract": {
                **asdict(contract),
                "hfnet_invocation_paths": {
                    "images": "<this artifact>/mav0/cam0/data/<timestamp>.png",
                    "imu": "<this artifact>/mav0/imu0/data.csv",
                    "sequence_root": "<this artifact>",
                    "times_file": "<this artifact>/cam0_times.txt",
                },
                "image_time_transform": "none; raw ROS header ns",
                "imu_time_transform": "output_ns=raw_header_ns+53694112",
                "kalibr_timeshift_cam_imu_s": base.KALIBR_TIMESHIFT_CAM_IMU_S,
            },
            "imu": {
                "brackets_camera_full_window": True,
                "count": len(selection.imus),
                "csv": {
                    "data_row_count": len(selection.imus),
                    "final_newline": False,
                    "header": base.CSV_HEADER,
                    "path": "mav0/imu0/data.csv",
                    "sha256": csv_hash,
                },
                "first_output_header_ns": selection.imus[0].output_header_ns,
                "first_raw_header_ns": selection.imus[0].raw_header_ns,
                "last_output_header_ns": selection.imus[-1].output_header_ns,
                "last_raw_header_ns": selection.imus[-1].raw_header_ns,
                "observed_rate_hz": rate,
                "source_indices_inclusive": [
                    selection.imus[0].source_index,
                    selection.imus[-1].source_index,
                ],
            },
            "payload_tree_sha256_excluding_manifest": base._aggregate_rows(
                sorted(aggregate_rows)
            ),
            "scientific_role": SCIENTIFIC_ROLE,
            "source": {
                "bag": str(source_bag),
                "resolved_bag": str(source_bag.resolve()),
                "sha256": source_hash,
                "size_bytes": source_bag.stat().st_size,
                "topics": selection.topic_audit,
            },
            "status": STATUS_EXPORTED,
            "upstream": dict(upstream),
        }
        (staging / "conversion_manifest.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
    return manifest


def _write_report_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("preflight", "export"), default="preflight"
    )
    parser.add_argument(
        "--source-bag", type=Path, default=WORKSPACE_DEFAULT / SOURCE_RELATIVE
    )
    parser.add_argument("--hfnet-root", type=Path, default=HFNET_ROOT_DEFAULT)
    parser.add_argument("--output-sequence-root", type=Path)
    parser.add_argument("--report-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_hash, upstream, selection, base_identity = prepare(
            args.source_bag, args.hfnet_root
        )
        if args.action == "preflight":
            result = preflight_result(
                args.source_bag,
                source_hash,
                upstream,
                selection,
                A02_FULL_CONTRACT,
                base_identity,
            )
        else:
            if args.output_sequence_root is None:
                raise ContractError("OUTPUT_SEQUENCE_ROOT_REQUIRED")
            result = write_artifact(
                args.output_sequence_root,
                args.source_bag,
                source_hash,
                selection,
                A02_FULL_CONTRACT,
                upstream,
                base_identity,
            )
        rc = RC_READY
    except ContractError as error:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "claims": {
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "prefix_r1_result_replaced": False,
                "trajectory_produced": False,
            },
            "errors": [str(error)],
            "status": STATUS_INTEGRITY_ERROR,
        }
        rc = RC_INTEGRITY_ERROR
    except Exception as error:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "claims": {
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "prefix_r1_result_replaced": False,
                "trajectory_produced": False,
            },
            "errors": [f"UNEXPECTED_{type(error).__name__}:{error}"],
            "status": STATUS_INTEGRITY_ERROR,
        }
        rc = RC_INTEGRITY_ERROR
    payload = canonical_json(result)
    sys.stdout.write(payload)
    if args.report_json:
        _write_report_atomic(args.report_json, payload)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
