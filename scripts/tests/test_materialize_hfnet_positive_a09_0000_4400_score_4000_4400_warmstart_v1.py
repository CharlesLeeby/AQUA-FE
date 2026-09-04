#!/usr/bin/env python3
"""Process-free tests for the A09 0..4400 warm-start preparation."""

from __future__ import annotations

from dataclasses import replace
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
    materialize_hfnet_positive_a09_0000_4400_score_4000_4400_warmstart_v1
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


class A09WarmstartMaterializerTests(unittest.TestCase):
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

        self.camera_stamps = [1000, 2000, 3000, 4000]
        self.imu_stamps = [800, 950, 1050, 1800, 1950, 2050, 2800, 2950]
        self.camera_payload = (
            adapter.IMAGE_CSV_HEADER
            + "\n"
            + "\n".join(
                f"{stamp},frame{index:06d}.png"
                for index, stamp in enumerate(self.camera_stamps)
            )
            + "\n"
        ).encode()
        self.imu_payload = (
            adapter.IMU_CSV_HEADER
            + "\n"
            + "\n".join(f"{stamp},1,2,3,4,5,6" for stamp in self.imu_stamps)
            + "\n"
        ).encode()
        self.images = [_png(index + 1) for index in range(4)]
        self._write_source(self.source, self.images)
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
            image_csv_pin=pin(self.camera_payload),
            imu_csv_member="raw_data/imu.csv",
            imu_csv_pin=pin(self.imu_payload),
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

    def _write_source(self, path: Path, images) -> None:
        with tarfile.open(path, "w:gz") as tar:
            _add(tar, "raw_data/camera.csv", self.camera_payload)
            for index, payload in enumerate(images):
                _add(tar, f"raw_data/images/frame{index:06d}.png", payload)
            _add(tar, "raw_data/imu.csv", self.imu_payload)

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
                "reused_a09_coldstart_adapter": identity,
                "reused_a06_adapter": identity,
                "reused_a06_sealed_core": identity,
                "reused_a06_independent_auditor": identity,
                "selector_freeze": identity,
                "payload_pin_derivation_freeze": {
                    **identity,
                    "semantic_validation": (
                        "PASS_ALL_TARGET_PINS_MATCH_PRODUCTION_CONTRACT"
                    ),
                    "materialization_authority_created": False,
                    "process_launch_authority_created": False,
                },
                "runability_protocol": identity,
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
            PREROLL_LAST_NS=1000,
        )

    def _materialize_synthetic(self, output: Path):
        with self._provenance_patch(), self._synthetic_score_patch():
            return adapter.materialize(
                self.selector,
                self.source,
                self.short_bag,
                self.config,
                output,
                self.contract,
            )

    def _audit_synthetic(self, output: Path, source=None, contract=None):
        with self._provenance_patch(), self._synthetic_score_patch():
            return adapter.audit(
                output,
                self.selector,
                source or self.source,
                self.short_bag,
                self.config,
                contract or self.contract,
            )

    def test_frozen_production_contract_and_selector(self) -> None:
        contract = adapter.PRODUCTION_CONTRACT
        self.assertEqual(
            (
                contract.camera_start_index,
                contract.camera_end_index,
                contract.camera_count,
            ),
            (0, 4400, 4401),
        )
        self.assertEqual(
            (contract.camera_first_ns, contract.camera_last_ns),
            (1542888746071008208, 1542888966034698672),
        )
        self.assertEqual(
            (contract.imu_first_index, contract.imu_last_index, contract.imu_count),
            (5, 43964, 43960),
        )
        self.assertEqual(contract.imu_shift_ns, 53_694_112)
        self.assertEqual(
            (
                contract.imu_first_output_ns,
                contract.imu_second_output_ns,
                contract.imu_penultimate_output_ns,
                contract.imu_last_output_ns,
            ),
            (
                1542888746068186256,
                1542888746073476784,
                1542888966032163568,
                1542888966037387088,
            ),
        )
        self.assertEqual(contract.expected_image_total_bytes, 1_125_883_992)
        self.assertEqual(
            contract.expected_source_image_inventory_sha256,
            "b8f0a21731558e1694c09c23c05ce259fbd1dba83b3bf55bfebea88448a5d148",
        )
        self.assertEqual(
            contract.expected_renamed_image_inventory_sha256,
            "d065372862769e802a3236d297f14cdd8e8ec25fd6607beb3c25c6c6d10f594f",
        )
        self.assertEqual(
            (contract.times_pin.size_bytes, contract.times_pin.crc32),
            (88_020, "6aff1e64"),
        )
        self.assertEqual(
            (contract.camera_csv_pin.size_bytes, contract.camera_csv_pin.crc32),
            (193_669, "b6616fa8"),
        )
        self.assertEqual(
            (contract.imu_output_pin.size_bytes, contract.imu_output_pin.crc32),
            (4_911_770, "ff36467b"),
        )
        self.assertEqual(
            contract.expected_payload_sha256,
            "845bc56b0de8df58f0dedde3d22e7a6019ba3b02fa4edc7b6ceec395fdee5f52",
        )
        self.assertEqual(contract.expected_payload_crc32, "79183172")
        self.assertEqual(adapter.SCORE_START_INDEX, 4000)
        self.assertEqual(adapter.SCORE_END_INDEX, 4400)
        selector = adapter.validate_selector(adapter.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(selector["sha256"], adapter.SELECTOR_FREEZE_SHA256)
        derivation = adapter.validate_payload_pin_freeze(
            adapter.DEFAULT_PAYLOAD_PIN_FREEZE,
            adapter.DEFAULT_SELECTOR_FREEZE,
            adapter.DEFAULT_PROTOCOL,
            selector,
        )
        self.assertEqual(
            derivation["payload_pin_derivation_freeze"]["sha256"],
            adapter.PAYLOAD_PIN_FREEZE_SHA256,
        )
        self.assertFalse(
            derivation["payload_pin_derivation_freeze"][
                "materialization_authority_created"
            ]
        )

    def test_payload_pin_freeze_rejects_byte_drift(self) -> None:
        drifted = self.root / "drifted-pin-freeze.json"
        drifted.write_bytes(adapter.DEFAULT_PAYLOAD_PIN_FREEZE.read_bytes() + b" ")
        with self.assertRaisesRegex(
            adapter.ContractError, "PAYLOAD_PIN_DERIVATION_FREEZE_SIZE_MISMATCH"
        ):
            adapter.validate_payload_pin_freeze(
                drifted,
                adapter.DEFAULT_SELECTOR_FREEZE,
                adapter.DEFAULT_PROTOCOL,
            )

    def test_payload_pin_freeze_rejects_semantic_mismatch_after_valid_identity(self) -> None:
        import json

        value = json.loads(
            adapter.DEFAULT_PAYLOAD_PIN_FREEZE.read_text(encoding="utf-8")
        )
        value["status"] = "PASS_BUT_WRONG_SEMANTICS"
        mismatched = self.root / "semantic-mismatch-pin-freeze.json"
        payload = (
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        mismatched.write_bytes(payload)
        with mock.patch.multiple(
            adapter,
            PAYLOAD_PIN_FREEZE_SIZE=len(payload),
            PAYLOAD_PIN_FREEZE_SHA256=hashlib.sha256(payload).hexdigest(),
        ):
            with self.assertRaisesRegex(
                adapter.ContractError, "PAYLOAD_PIN_FREEZE_STATUS_MISMATCH"
            ):
                adapter.validate_payload_pin_freeze(
                    mismatched,
                    adapter.DEFAULT_SELECTOR_FREEZE,
                    adapter.DEFAULT_PROTOCOL,
                )

    def test_synthetic_materialization_and_independent_audit(self) -> None:
        output = self.root / "fresh"
        manifest = self._materialize_synthetic(output)
        audit = self._audit_synthetic(output)
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
            manifest["publication"]["exact_file_and_directory_closure_required"]
        )
        self.assertFalse(manifest["claims"]["hfnet_started"])
        self.assertEqual(
            audit["status"], "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        )
        self.assertEqual(audit["camera"]["source_members_compared"], 3)
        self.assertEqual(audit["directory_count_excluding_root"], 4)
        self.assertTrue(audit["publication"]["independent_source_rederivation_passed"])
        self.assertTrue(
            audit["publication"]["exact_file_and_directory_closure_passed"]
        )
        self.assertEqual(
            (output / "mav0/cam0/data/1000.png").read_bytes(), self.images[0]
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

    def test_no_clobber_rejects_dangling_symlink_target(self) -> None:
        target = self.root / "dangling"
        target.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(adapter.ContractError, "NO_CLOBBER"):
            adapter._require_output_absent(target)
        self.assertTrue(target.is_symlink())

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

    def test_precommit_rejects_unexpected_empty_directory(self) -> None:
        target = self.root / "precommit-extra-directory"
        with self.assertRaisesRegex(
            adapter.ContractError, "PRECOMMIT_PAYLOAD_DIRECTORY_SET_MISMATCH"
        ):
            with adapter.manifest_committed_directory(target) as reservation:
                (reservation.path / "payload").write_text("ok", encoding="utf-8")
                (reservation.path / "unexpected").mkdir()
                reservation.commit_manifest(b"{}\n", {"payload"})
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
        self._materialize_synthetic(output)
        external = self.root / "external"
        external.mkdir()
        (output / "escape").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(adapter.ContractError, "AUDIT_OUTPUT_SYMLINK"):
            self._audit_synthetic(output)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires POSIX")
    def test_independent_audit_rejects_fifo_without_opening_it(self) -> None:
        output = self.root / "fifo-tree"
        self._materialize_synthetic(output)
        os.mkfifo(output / "unexpected.fifo", 0o600)
        with self.assertRaisesRegex(adapter.ContractError, "AUDIT_OUTPUT_NONREGULAR"):
            self._audit_synthetic(output)

    def test_independent_audit_rejects_unexpected_empty_directory(self) -> None:
        output = self.root / "extra-directory-tree"
        self._materialize_synthetic(output)
        (output / "unexpected-empty-directory").mkdir()
        with self.assertRaisesRegex(
            adapter.ContractError, "AUDIT_OUTPUT_DIRECTORY_SET_MISMATCH"
        ):
            self._audit_synthetic(output)

    def test_independent_audit_rederives_pngs_from_source(self) -> None:
        output = self.root / "source-rederivation-tree"
        self._materialize_synthetic(output)
        changed_source = self.root / "changed-source.tar.gz"
        changed_images = list(self.images)
        changed_images[0] = _png(99)
        self._write_source(changed_source, changed_images)
        changed_bytes = changed_source.read_bytes()
        changed_contract = replace(
            self.contract,
            source_archive=changed_source,
            source_pin=adapter.FilePin(
                len(changed_bytes), hashlib.sha256(changed_bytes).hexdigest()
            ),
        )
        with self.assertRaisesRegex(
            adapter.ContractError, "AUDIT_SOURCE_OUTPUT_BYTES_DIFFER"
        ):
            self._audit_synthetic(output, changed_source, changed_contract)

    def test_script_has_no_process_launcher(self) -> None:
        text = Path(adapter.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", text)
        self.assertNotIn("from subprocess", text)
        self.assertNotIn("os.system(", text)
        self.assertNotIn("Popen(", text)
        self.assertNotIn("roslaunch", text)


if __name__ == "__main__":
    unittest.main()
