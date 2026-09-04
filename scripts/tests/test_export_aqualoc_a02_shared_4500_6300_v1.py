#!/usr/bin/env python3
"""Synthetic tests for the A02 4500..6300 shared-input exporter."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cv2
import genpy
import numpy as np
import rosbag
from sensor_msgs.msg import Image, Imu

from scripts import export_aqualoc_a02_shared_4500_6300_v1 as adapter


def _time(ns: int) -> genpy.Time:
    return genpy.Time(ns // 1_000_000_000, ns % 1_000_000_000)


def _image(ns: int, value: int, width: int = 3, height: int = 2) -> Image:
    message = Image()
    message.header.stamp = _time(ns)
    message.width = width
    message.height = height
    message.encoding = "mono8"
    message.step = width
    message.data = bytes([value]) * (width * height)
    return message


def _imu(ns: int, value: float) -> Imu:
    message = Imu()
    message.header.stamp = _time(ns)
    message.angular_velocity.x = value
    message.angular_velocity.y = value + 1.0
    message.angular_velocity.z = value + 2.0
    message.linear_acceleration.x = value + 3.0
    message.linear_acceleration.y = value + 4.0
    message.linear_acceleration.z = value + 5.0
    return message


class SharedA02ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_production_contract_is_exact(self) -> None:
        self.assertEqual((adapter.GLOBAL_CAMERA_FIRST, adapter.GLOBAL_CAMERA_LAST), (4500, 6300))
        self.assertEqual(adapter.CAMERA_COUNT, 1801)
        self.assertEqual(adapter.PREROLL_GLOBAL_INDICES, (4500, 5399))
        self.assertEqual(adapter.SCORE_GLOBAL_INDICES, (5400, 6300))
        self.assertEqual(len(adapter.SCORE_REFERENCE_INDICES), 46)
        self.assertEqual((adapter.GLOBAL_IMU_FIRST, adapter.GLOBAL_IMU_LAST), (44954, 62940))
        self.assertEqual(adapter.IMU_COUNT, 17987)
        self.assertEqual(adapter.IMU_SHIFT_NS, 53_694_112)
        self.assertEqual(adapter.DEFAULT_PROVENANCE.name, "archaeo02_4500_6300.bag.manifest.json")
        self.assertEqual(adapter.RAW_TAR_SHA256, "8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69")

    def _provenance(self, bag: Path) -> dict[str, object]:
        return {
            "schema_version": "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1",
            "status": "PASS",
            "provenance": {
                "raw_tar": {
                    "path": "/canonical/raw.tar.gz",
                    "size": adapter.RAW_TAR_SIZE_BYTES,
                    "sha": adapter.RAW_TAR_SHA256,
                },
                "gt": {
                    "path": "/gt.txt",
                    "size": adapter.REFERENCE_SIZE_BYTES,
                    "sha": adapter.REFERENCE_SHA256,
                },
                "converter": {
                    "path": "/workspace/" + adapter.RAW_CONVERTER_RELATIVE,
                    "sha": adapter.RAW_CONVERTER_SHA256,
                },
                "argv": ["--start-image-index", "4500"],
            },
            "selection": {
                "camera_global_start_index": 4500,
                "camera_global_end_index_inclusive": 6300,
                "image_count_expected": 1801,
                "imu_margin_ns": 250_000_000,
                "imu_rule_closed_interval": True,
            },
            "semantics": {
                "header_stamp": "raw_csv_integer_ns",
                "record_stamp_equals_header": True,
                "no_time_shift": True,
                "image_encoding": "mono8",
                "gt_pose": "world_T_camera",
            },
            "output": {
                "path": str(bag),
                "size": bag.stat().st_size,
                "sha": hashlib.sha256(bag.read_bytes()).hexdigest(),
                "compression": "bz2",
                "topic_counts": {adapter.CAMERA_TOPIC: 1801, adapter.IMU_TOPIC: 18001},
            },
            "checks": {"camera_count": True, "endpoint": True, "no_clobber": True},
        }

    def test_provenance_binds_raw_converter_window_and_output(self) -> None:
        bag = self.root / "window.bag"
        bag.write_bytes(b"immutable derived window")
        provenance = self._provenance(bag)
        path = self.root / "window.bag.manifest.json"
        path.write_text(json.dumps(provenance), encoding="utf-8")
        identity = adapter.validate_provenance(path, bag)
        self.assertEqual(identity["output_topic_counts"][adapter.CAMERA_TOPIC], 1801)

        provenance["selection"]["camera_global_end_index_inclusive"] = 6299
        path.write_text(json.dumps(provenance), encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "CAMERA_RANGE"):
            adapter.validate_provenance(path, bag)

    def test_window_reader_selects_exact_shifted_imu_subsequence_from_margin(self) -> None:
        bag = self.root / "synthetic.bag"
        camera_ns = (1000, 1100, 1200)
        imu_ns = (800, 900, 1000, 1100, 1200, 1300)
        with rosbag.Bag(str(bag), "w", chunk_threshold=1024) as stream:
            for index, stamp in enumerate(camera_ns):
                stream.write(adapter.CAMERA_TOPIC, _image(stamp, index + 1), _time(stamp))
            for index, stamp in enumerate(imu_ns):
                stream.write(adapter.IMU_TOPIC, _imu(stamp, float(index)), _time(stamp))

        expected_counts = {adapter.CAMERA_TOPIC: 3, adapter.IMU_TOPIC: 6}
        patches = (
            mock.patch.object(adapter, "CAMERA_COUNT", 3),
            mock.patch.object(adapter, "CAMERA_WIDTH", 3),
            mock.patch.object(adapter, "CAMERA_HEIGHT", 2),
            mock.patch.object(adapter, "PREFIX_CAMERA_COUNT", 2),
            mock.patch.object(adapter, "GLOBAL_CAMERA_FIRST", 10),
            mock.patch.object(adapter, "IMU_COUNT", 4),
            mock.patch.object(adapter, "GLOBAL_IMU_FIRST", 20),
            mock.patch.object(adapter, "EXPECTED_FIRST_CAMERA_NS", 1000),
            mock.patch.object(adapter, "EXPECTED_BOUNDARY_CAMERA_NS", 1100),
            mock.patch.object(adapter, "EXPECTED_LAST_CAMERA_NS", 1200),
            mock.patch.object(adapter, "EXPECTED_FIRST_IMU_RAW_NS", 900),
            mock.patch.object(adapter, "EXPECTED_LAST_IMU_RAW_NS", 1200),
            mock.patch.object(adapter, "IMU_SHIFT_NS", 100),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            cameras, imus, audit = adapter.read_window_bag(bag, expected_counts)
        self.assertEqual([row.global_index for row in cameras], [10, 11, 12])
        self.assertEqual([row.raw_header_ns for row in imus], [900, 1000, 1100, 1200])
        self.assertEqual([row.output_header_ns for row in imus], [1000, 1100, 1200, 1300])
        self.assertEqual(audit[adapter.IMU_TOPIC]["message_count"], 6)

    def _synthetic_selection(self) -> adapter.Selection:
        cameras = []
        for relative, stamp in enumerate((100, 200, 300)):
            pixels = bytes([relative + 1]) * 4
            cameras.append(
                adapter.CameraSample(
                    relative,
                    10 + relative,
                    stamp,
                    stamp,
                    2,
                    2,
                    "mono8",
                    2,
                    pixels,
                    hashlib.sha256(pixels).hexdigest(),
                )
            )
        imus = tuple(
            adapter.ImuSample(i, 20 + i, 90 + 100 * i, 100 + 100 * i, 90 + 100 * i,
                              (1.0 + i, 2.0 + i, 3.0 + i),
                              (4.0 + i, 5.0 + i, 6.0 + i))
            for i in range(4)
        )
        references = (
            adapter.ReferencePose(11, 200, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
            adapter.ReferencePose(12, 300, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        )
        return adapter.Selection(tuple(cameras), imus, references, {
            adapter.CAMERA_TOPIC: {"message_type": adapter.CAMERA_TYPE, "message_count": 3},
            adapter.IMU_TOPIC: {"message_type": adapter.IMU_TYPE, "message_count": 4},
        })

    def _prefix(self, selection: adapter.Selection) -> tuple[Path, str]:
        root = self.root / "prefix"
        (root / "rgb").mkdir(parents=True)
        rows = []
        for sample in selection.cameras[:2]:
            source = np.frombuffer(sample.pixels, np.uint8).reshape(2, 2)
            ok, encoded = cv2.imencode(".png", source)
            self.assertTrue(ok)
            payload = bytes(encoded)
            relative = f"rgb/{sample.header_ns}.png"
            (root / relative).write_bytes(payload)
            rows.append({
                "source_index": sample.relative_index,
                "raw_header_ns": sample.header_ns,
                "source_pixel_sha256": sample.source_pixel_sha256,
                "relative_path": relative,
                "png_sha256": hashlib.sha256(payload).hexdigest(),
                "png_size_bytes": len(payload),
            })
        manifest = root / "conversion_manifest.json"
        manifest.write_text(json.dumps({"camera": {"images": rows}}), encoding="utf-8")
        return root, hashlib.sha256(manifest.read_bytes()).hexdigest()

    def test_shared_export_reuses_prefix_encodes_only_suffix_and_builds_hfnet_view(self) -> None:
        selection = self._synthetic_selection()
        prefix, prefix_hash = self._prefix(selection)
        bag = self.root / "window.bag"
        bag.write_bytes(b"bag")
        reference = self.root / "gt.txt"
        reference.write_text("synthetic reference", encoding="utf-8")
        output = self.root / "output"
        patches = (
            mock.patch.object(adapter, "CAMERA_COUNT", 3),
            mock.patch.object(adapter, "IMU_COUNT", 4),
            mock.patch.object(adapter, "PREFIX_CAMERA_COUNT", 2),
            mock.patch.object(adapter, "CAMERA_WIDTH", 2),
            mock.patch.object(adapter, "CAMERA_HEIGHT", 2),
            mock.patch.object(adapter, "SCORE_REFERENCE_INDICES", (11, 12)),
            mock.patch.object(adapter, "PREFIX_MANIFEST_SHA256", prefix_hash),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            with mock.patch.object(adapter, "encode_lossless_png", wraps=adapter.encode_lossless_png) as encode:
                manifest = adapter.write_artifact(
                    output, bag, {"sha256": "provenance"}, reference, prefix, selection
                )
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(encode.call_args.args[0].relative_index, 2)
        self.assertEqual(
            [row["materialization"] for row in manifest["camera"]["images"]],
            ["hardlink", "hardlink", "encoded_new_lossless"],
        )
        shared = sorted((output / "shared/cam0/data").glob("*.png"))
        hfnet = sorted((output / "hfnet/mav0/cam0/data").glob("*.png"))
        self.assertEqual(len(shared), 3)
        self.assertEqual([row.read_bytes() for row in shared], [row.read_bytes() for row in hfnet])
        self.assertEqual(len((output / "shared/reference_proxy.tum").read_text().splitlines()), 2)
        imu_csv = output / "hfnet/mav0/imu0/data.csv"
        self.assertEqual(len(imu_csv.read_bytes().splitlines()), 5)
        self.assertFalse(imu_csv.read_bytes().endswith(b"\n"))

    def test_link_failure_uses_verified_copy_and_existing_output_is_preserved(self) -> None:
        source = self.root / "source"
        target = self.root / "target"
        source.write_bytes(b"payload")
        with mock.patch.object(os, "link", side_effect=OSError("cross-device")):
            self.assertEqual(adapter._link_or_copy(source, target), "copy")
        self.assertEqual(target.read_bytes(), b"payload")

        output = self.root / "owned"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            with adapter.atomic_directory(output):
                pass
        self.assertEqual(marker.read_text(), "preserve")

    def test_frozen_reference_has_complete_score_grid(self) -> None:
        cameras = tuple(
            adapter.CameraSample(i, 4500 + i, 1_000_000_000 + i, 1_000_000_000 + i,
                                 0, 0, "mono8", 0, b"", "")
            for i in range(1801)
        )
        poses = adapter.load_references(adapter.DEFAULT_REFERENCE, cameras)
        self.assertEqual(len(poses), 46)
        self.assertEqual((poses[0].global_camera_index, poses[-1].global_camera_index), (5400, 6300))


if __name__ == "__main__":
    unittest.main()
