#!/usr/bin/env python3
"""Process-free tests for the A10 0..2800 warm-start preparation."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import zlib

from scripts import (
    materialize_hfnet_positive_a10_0000_2800_score_2400_2800_warmstart_v1
    as adapter,
)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png(value: int) -> bytes:
    header = struct.pack(">IIBBBBB", 968, 608, 8, 0, 0, 0, 0)
    scanlines = (b"\x00" + bytes([value]) * 968) * 608
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


def _add(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))


class A10WarmstartMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.tar.gz"
        self.selector = self.root / "selector.json"
        self.short_bag = self.root / "window.bag"
        self.config = self.root / "config.yaml"
        self.selector.write_text("{}\n", encoding="utf-8")
        self.short_bag.write_bytes(b"selection-only")
        self.config.write_text("synthetic\n", encoding="utf-8")
        camera_stamps = [1000, 2000, 3000, 4000]
        imu_stamps = [800, 950, 1050, 1800, 1950, 2050, 2800, 2950]
        camera = (
            adapter.IMAGE_CSV_HEADER
            + "\n"
            + "\n".join(
                f"{stamp},frame{index:06d}.png"
                for index, stamp in enumerate(camera_stamps)
            )
            + "\n"
        ).encode()
        imu = (
            adapter.IMU_CSV_HEADER
            + "\n"
            + "\n".join(f"{stamp},1,2,3,4,5,6" for stamp in imu_stamps)
            + "\n"
        ).encode()
        self.images = [_png(index + 1) for index in range(4)]
        with tarfile.open(self.source, "w:gz") as tar:
            _add(tar, "raw_data/camera.csv", camera)
            for index, payload in enumerate(self.images):
                _add(tar, f"raw_data/images/frame{index:06d}.png", payload)
            _add(tar, "raw_data/imu.csv", imu)
        source = self.source.read_bytes()

        def pin(payload: bytes) -> adapter.FilePin:
            return adapter.FilePin(
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                f"{zlib.crc32(payload) & 0xffffffff:08x}",
            )

        self.contract = adapter.MaterializationContract(
            source_archive=self.source,
            source_pin=adapter.FilePin(
                len(source), hashlib.sha256(source).hexdigest()
            ),
            source_gzip_crc32=None,
            source_gzip_isize=None,
            image_csv_member="raw_data/camera.csv",
            image_csv_pin=pin(camera),
            imu_csv_member="raw_data/imu.csv",
            imu_csv_pin=pin(imu),
            image_member_prefix="raw_data/images/",
            source_camera_count=4,
            source_imu_count=8,
            camera_start_index=0,
            camera_end_index=2,
            camera_first_ns=1000,
            camera_last_ns=3000,
            width=968,
            height=608,
            png_bit_depth=8,
            png_color_type=0,
            imu_shift_ns=100,
            imu_first_index=0,
            imu_last_index=7,
            imu_first_raw_ns=800,
            imu_last_raw_ns=2950,
            imu_first_output_ns=900,
            imu_second_output_ns=1050,
            imu_penultimate_output_ns=2900,
            imu_last_output_ns=3050,
            expected_image_total_bytes=None,
            expected_source_image_inventory_sha256=None,
            expected_source_image_inventory_crc32=None,
            expected_renamed_image_inventory_sha256=None,
            expected_renamed_image_inventory_crc32=None,
            times_pin=adapter.FilePin(),
            camera_csv_pin=adapter.FilePin(),
            imu_output_pin=adapter.FilePin(),
            expected_payload_sha256=None,
            expected_payload_crc32=None,
        )

    def _provenance_patch(self):
        identity = {
            "path": "synthetic",
            "size_bytes": 1,
            "sha256": "synthetic",
            "crc32": "synthetic",
        }
        return mock.patch.object(
            adapter,
            "_require_provenance",
            return_value={
                "reused_a10_coldstart_adapter": identity,
                "reused_a06_adapter": identity,
                "reused_a06_sealed_core": identity,
                "reused_a06_independent_auditor": identity,
                "selector_freeze": identity,
                "archaeology_config": identity,
                "source_choice": {
                    "selected": "canonical_raw_archive_png_members",
                    "rejected_alternative": identity,
                },
            },
        )

    def _synthetic_score_patch(self):
        return mock.patch.multiple(
            adapter,
            SCORE_START_INDEX=1,
            SCORE_END_INDEX=2,
            SCORE_FIRST_NS=2000,
            SCORE_LAST_NS=3000,
        )

    def test_frozen_production_contract_and_selector(self) -> None:
        contract = adapter.PRODUCTION_CONTRACT
        self.assertEqual(
            (
                contract.camera_start_index,
                contract.camera_end_index,
                contract.camera_count,
            ),
            (0, 2800, 2801),
        )
        self.assertEqual(
            (contract.imu_first_index, contract.imu_last_index, contract.imu_count),
            (28, 28003, 27976),
        )
        self.assertEqual(contract.imu_shift_ns, 53_694_112)
        self.assertEqual(adapter.SCORE_START_INDEX, 2400)
        self.assertEqual(adapter.SCORE_END_INDEX, 2800)
        self.assertLessEqual(contract.imu_first_output_ns, contract.camera_first_ns)
        self.assertLess(contract.camera_first_ns, contract.imu_second_output_ns)
        self.assertLessEqual(contract.imu_penultimate_output_ns, contract.camera_last_ns)
        self.assertLess(contract.camera_last_ns, contract.imu_last_output_ns)
        selector = adapter.validate_selector(adapter.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(selector["sha256"], adapter.SELECTOR_FREEZE_SHA256)

    def test_synthetic_materialization_and_independent_audit(self) -> None:
        output = self.root / "fresh"
        with self._provenance_patch(), self._synthetic_score_patch():
            manifest = adapter.materialize(
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                output,
                self.contract,
            )
            audit = adapter.audit(
                output,
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                self.contract,
            )
        self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
        self.assertTrue(manifest["selection"]["warm_start"])
        self.assertFalse(manifest["selection"]["cold_start"])
        self.assertEqual(
            manifest["selection"]["score_camera_indices_inclusive"], [1, 2]
        )
        self.assertTrue(
            manifest["selection"]["initialization_and_preroll_excluded_from_score"]
        )
        self.assertEqual(
            manifest["publication"]["commit_marker"],
            "materialization_manifest.json",
        )
        self.assertTrue(
            manifest["publication"]["commit_marker_written_exclusive_last"]
        )
        self.assertTrue(
            manifest["publication"]["runner_requires_independent_audit_receipt"]
        )
        self.assertFalse(manifest["claims"]["hfnet_started"])
        self.assertEqual(
            audit["status"], "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        )
        self.assertEqual(audit["camera"]["source_members_compared"], 3)
        self.assertTrue(
            audit["publication"]["materialization_commit_marker_valid"]
        )
        self.assertEqual(
            (output / "mav0/cam0/data/1000.png").read_bytes(), self.images[0]
        )
        self.assertEqual(
            (output / "mav0/cam0/data/3000.png").read_bytes(), self.images[2]
        )
        stamps = [
            int(line.split(b",", 1)[0])
            for line in (output / "mav0/imu0/data.csv").read_bytes().splitlines()[1:]
        ]
        self.assertEqual(stamps, [900, 1050, 1150, 1900, 2050, 2150, 2900, 3050])

    def test_no_clobber_rejects_before_source_or_selector_work(self) -> None:
        output = self.root / "owned"
        output.mkdir()
        marker = output / "owner"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "NO_CLOBBER"):
            adapter.materialize(
                self.root / "missing-selector",
                self.root / "missing-source",
                self.root / "missing-bag",
                self.root / "missing-config",
                output,
                self.contract,
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_manifest_reservation_preserves_preexisting_target(self) -> None:
        target = self.root / "published"
        target.mkdir()
        (target / "owner").write_text("competitor", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "NO_CLOBBER"):
            with adapter.manifest_committed_directory(target):
                self.fail("preexisting target must not be yielded")
        self.assertEqual(
            (target / "owner").read_text(encoding="utf-8"), "competitor"
        )

    def test_manifest_reservation_blocks_second_mkdir_and_cleans_failure(self) -> None:
        target = self.root / "published"
        with self.assertRaisesRegex(RuntimeError, "injected-before-commit"):
            with adapter.manifest_committed_directory(target) as reservation:
                with self.assertRaises(FileExistsError):
                    os.mkdir(target)
                (reservation.path / "payload").write_text(
                    "uncommitted", encoding="utf-8"
                )
                raise RuntimeError("injected-before-commit")
        self.assertFalse(target.exists())

    def test_independent_audit_rejects_uncommitted_tree(self) -> None:
        target = self.root / "uncommitted"
        target.mkdir()
        (target / "payload").write_text("partial", encoding="utf-8")
        with self.assertRaisesRegex(
            adapter.ContractError, "AUDIT_COMMIT_MARKER_MISSING"
        ):
            adapter.audit(
                target,
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                self.contract,
            )

    def test_independent_audit_rejects_symlink_to_directory(self) -> None:
        output = self.root / "symlink-tree"
        with self._provenance_patch(), self._synthetic_score_patch():
            adapter.materialize(
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                output,
                self.contract,
            )
        external = self.root / "external"
        external.mkdir()
        (output / "escape").symlink_to(external, target_is_directory=True)
        with self._provenance_patch(), self._synthetic_score_patch():
            with self.assertRaisesRegex(
                adapter.ContractError, "AUDIT_OUTPUT_SYMLINK"
            ):
                adapter.audit(
                    output,
                    self.selector,
                    self.source,
                    self.short_bag,
                    self.config,
                    self.contract,
                )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires POSIX")
    def test_independent_audit_rejects_fifo_without_opening_it(self) -> None:
        output = self.root / "fifo-tree"
        with self._provenance_patch(), self._synthetic_score_patch():
            adapter.materialize(
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                output,
                self.contract,
            )
        os.mkfifo(output / "unexpected.fifo", 0o600)
        with self._provenance_patch(), self._synthetic_score_patch():
            with self.assertRaisesRegex(
                adapter.ContractError, "AUDIT_OUTPUT_NONREGULAR"
            ):
                adapter.audit(
                    output,
                    self.selector,
                    self.source,
                    self.short_bag,
                    self.config,
                    self.contract,
                )

    def test_script_has_no_process_launcher(self) -> None:
        text = Path(adapter.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", text)
        self.assertNotIn("from subprocess", text)
        self.assertNotIn("os.system(", text)
        self.assertNotIn("Popen(", text)
        self.assertNotIn("roslaunch", text)


if __name__ == "__main__":
    unittest.main()
