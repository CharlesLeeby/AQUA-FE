#!/usr/bin/env python3
"""Synthetic tests for the A02-to-paper-era-AnyFeature camera adapter."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import cv2
import genpy
import numpy as np
import rosbag
from sensor_msgs.msg import Image

from scripts import export_aqualoc_to_anyfeature_v1 as adapter


BASE_NS = 1_700_000_000_000_000_000
CAMERA_STAMPS = (BASE_NS + 100, BASE_NS + 50_000_100, BASE_NS + 100_000_100)
PREFIX_PROFILE = adapter.ExportProfile(
    name="synthetic-prefix2",
    expected_total_images=3,
    first_index=0,
    last_index=1,
    expected_first_stamp_ns=CAMERA_STAMPS[0],
    expected_last_stamp_ns=CAMERA_STAMPS[1],
    evaluation_eligible_full_window=False,
)
FULL_PROFILE = adapter.ExportProfile(
    name="synthetic-full",
    expected_total_images=3,
    first_index=0,
    last_index=2,
    expected_first_stamp_ns=CAMERA_STAMPS[0],
    expected_last_stamp_ns=CAMERA_STAMPS[2],
    evaluation_eligible_full_window=True,
    prefix_reuse_count=2,
    prefix_profile_name=PREFIX_PROFILE.name,
)


def _time(stamp_ns: int) -> genpy.Time:
    return genpy.Time(stamp_ns // 1_000_000_000, stamp_ns % 1_000_000_000)


def _image(stamp_ns: int, index: int, *, bad_width: bool = False) -> Image:
    message = Image()
    message.header.stamp = _time(stamp_ns)
    message.height = adapter.CAMERA_HEIGHT
    message.width = adapter.CAMERA_WIDTH + (1 if bad_width else 0)
    message.encoding = adapter.CAMERA_ENCODING
    message.is_bigendian = 0
    message.step = message.width
    message.data = bytes([index + 1]) * (message.width * message.height)
    return message


def _build_bag(
    path: Path,
    *,
    nonmonotonic_header: bool = False,
    bad_width: bool = False,
) -> None:
    with rosbag.Bag(str(path), "w", chunk_threshold=1024) as bag:
        for index, record_ns in enumerate(CAMERA_STAMPS):
            header_ns = record_ns
            if nonmonotonic_header and index == 2:
                header_ns = CAMERA_STAMPS[0] - 1
            bag.write(
                adapter.CAMERA_TOPIC,
                _image(header_ns, index, bad_width=bad_width and index == 1),
                _time(record_ns),
            )


def _write_calibration(path: Path) -> None:
    path.write_text(
        """cam0:
  cam_overlaps: []
  camera_model: pinhole
  distortion_coeffs: [-0.1, 0.05, 0.0001, 0.0002]
  distortion_model: radtan
  intrinsics: [543.0, 542.0, 489.0, 305.0]
  resolution: [968, 608]
  rostopic: /camera/image_raw
""",
        encoding="utf-8",
    )


def _identity(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


class AqualocAnyFeatureAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bag = self.root / "source.bag"
        self.calibration = self.root / "camera.yaml"
        _write_calibration(self.calibration)

    def _prepare(self, profile: adapter.ExportProfile = PREFIX_PROFILE):
        bag_size, bag_hash = _identity(self.bag)
        calibration_size, calibration_hash = _identity(self.calibration)
        return adapter.prepare(
            self.bag,
            self.calibration,
            profile,
            expected_source_size=bag_size,
            expected_source_sha256=bag_hash,
            expected_calibration_size=calibration_size,
            expected_calibration_sha256=calibration_hash,
        )

    def _export_prefix(self, name: str = "prefix"):
        source_hash, calibration_hash, calibration, selection = self._prepare()
        root = self.root / name
        manifest = adapter.write_artifact(
            root,
            self.bag,
            source_hash,
            self.calibration,
            calibration_hash,
            calibration,
            selection,
            PREFIX_PROFILE,
        )
        return root, manifest

    def _full_inputs(self):
        return self._prepare(FULL_PROFILE)

    def test_production_contract_is_frozen_to_paper_era(self) -> None:
        self.assertEqual(
            adapter.ANYFEATURE_PAPER_COMMIT,
            "6aa014b724f7a61bcbff2f8f28f20836986a43dc",
        )
        self.assertEqual(adapter.SOURCE_SIZE_BYTES, 222_477_260)
        self.assertEqual(
            adapter.SOURCE_SHA256,
            "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8",
        )
        self.assertEqual(adapter.CALIBRATION_SIZE_BYTES, 337)
        self.assertEqual(len(adapter.ANYFEATURE_CONTRACT_FILE_SHA256), 5)
        self.assertEqual(adapter.PROFILES["a02-prefix200"].count, 200)
        self.assertEqual(adapter.PROFILES["a02-full"].count, 901)
        self.assertEqual(adapter.PROFILES["a02-full"].prefix_reuse_count, 200)
        self.assertEqual(
            adapter.PROFILES["a02-full"].prefix_profile_name, "a02-prefix200"
        )

    def test_timestamp_text_is_exact_integer_ns(self) -> None:
        text = adapter.timestamp_seconds_text(CAMERA_STAMPS[0])
        self.assertEqual(text, "1700000000.000000100")
        self.assertEqual(adapter.timestamp_text_to_ns(text), CAMERA_STAMPS[0])
        for malformed in (
            "1700000000.1",
            "1.7000000000000001e9",
            "+1700000000.000000100",
            "1700000000.0000001000",
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(
                    adapter.ContractError, "TIMESTAMP_NOT_CANONICAL"
                ):
                    adapter.timestamp_text_to_ns(malformed)

    def test_rgb_txt_rejects_noncanonical_spacing_precision_and_crlf(self) -> None:
        _build_bag(self.bag)
        _, _, _, selection = self._prepare()
        canonical = adapter.rgb_txt_bytes(selection.samples)
        variants = (
            canonical.replace(b" rgb/", b"  rgb/", 1),
            canonical.replace(b".000000100", b".00000010", 1),
            canonical.replace(b"\n", b"\r\n"),
            canonical[:-1],
        )
        for payload in variants:
            with self.subTest(payload=payload[:40]):
                with self.assertRaises(adapter.ContractError):
                    adapter.validate_rgb_txt_payload(payload, selection.samples)

    def test_synthetic_prefix_export_is_pixel_exact_and_headerless(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, selection = self._prepare()
        output = self.root / "sequence"
        manifest = adapter.write_artifact(
            output,
            self.bag,
            source_hash,
            self.calibration,
            calibration_hash,
            calibration,
            selection,
            PREFIX_PROFILE,
        )

        self.assertEqual(manifest["status"], adapter.STATUS_EXPORTED)
        self.assertFalse(manifest["evaluation_eligible_full_window"])
        expected_lines = [
            f"{adapter.timestamp_seconds_text(stamp)} rgb/{stamp}.png"
            for stamp in CAMERA_STAMPS[:2]
        ]
        rgb_payload = (output / "rgb.txt").read_bytes()
        self.assertTrue(rgb_payload.endswith(b"\n"))
        self.assertEqual(rgb_payload.decode("ascii").splitlines(), expected_lines)
        self.assertFalse(any(line.startswith("#") for line in expected_lines))

        for index, stamp in enumerate(CAMERA_STAMPS[:2]):
            decoded = cv2.imread(
                str(output / "rgb" / f"{stamp}.png"), cv2.IMREAD_UNCHANGED
            )
            expected = np.full(
                (adapter.CAMERA_HEIGHT, adapter.CAMERA_WIDTH), index + 1, np.uint8
            )
            self.assertTrue(np.array_equal(decoded, expected))

        calibration_text = (output / "calibration.yaml").read_text()
        self.assertTrue(calibration_text.startswith("%YAML:1.0\n"))
        self.assertIn("Camera.w: 968", calibration_text)
        self.assertIn("Camera.h: 608", calibration_text)
        self.assertIn("Camera.k3: 0", calibration_text)
        loaded_manifest = json.loads((output / "conversion_manifest.json").read_text())
        self.assertEqual(loaded_manifest["camera"]["count"], 2)
        self.assertEqual(
            loaded_manifest["adapter_identity"]["sha256"],
            adapter.sha256_file(Path(adapter.__file__).resolve()),
        )
        self.assertTrue(
            all(
                row["pixel_identity_verified"]
                for row in loaded_manifest["camera"]["images"]
            )
        )
        for row in loaded_manifest["camera"]["images"]:
            png = output / row["relative_path"]
            self.assertEqual(row["png_size_bytes"], png.stat().st_size)
            self.assertEqual(row["png_sha256"], adapter.sha256_file(png))
        identity = loaded_manifest["sequence_identity"]
        self.assertEqual(identity["record"]["images"], [
            {
                "source_index": row["source_index"],
                "raw_header_ns": row["raw_header_ns"],
                "relative_path": row["relative_path"],
                "source_pixel_sha256": row["source_pixel_sha256"],
                "png_sha256": row["png_sha256"],
                "png_size_bytes": row["png_size_bytes"],
            }
            for row in loaded_manifest["camera"]["images"]
        ])
        self.assertEqual(
            identity["sha256"],
            hashlib.sha256(
                adapter.canonical_json(identity["record"]).encode("utf-8")
            ).hexdigest(),
        )

    def test_synthetic_full_profile_exports_every_camera(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, prefix_selection = self._prepare()
        prefix = self.root / "prefix"
        adapter.write_artifact(
            prefix,
            self.bag,
            source_hash,
            self.calibration,
            calibration_hash,
            calibration,
            prefix_selection,
            PREFIX_PROFILE,
        )
        source_hash, calibration_hash, calibration, selection = self._prepare(
            FULL_PROFILE
        )
        output = self.root / "full"
        with mock.patch.object(
            adapter, "encode_lossless_png", wraps=adapter.encode_lossless_png
        ) as encode:
            manifest = adapter.write_artifact(
                output,
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=prefix,
            )
        self.assertTrue(manifest["evaluation_eligible_full_window"])
        self.assertEqual(len(list((output / "rgb").glob("*.png"))), 3)
        self.assertEqual(len((output / "rgb.txt").read_text().splitlines()), 3)
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(encode.call_args.args[0].source_index, 2)
        self.assertEqual(
            [row["reused_from_prefix"] for row in manifest["camera"]["images"]],
            [True, True, False],
        )
        for stamp in CAMERA_STAMPS[:2]:
            self.assertEqual(
                (prefix / "rgb" / f"{stamp}.png").read_bytes(),
                (output / "rgb" / f"{stamp}.png").read_bytes(),
            )
        prefix_manifest = prefix / "conversion_manifest.json"
        self.assertEqual(
            manifest["prefix_reuse"]["prefix_conversion_manifest_sha256"],
            adapter.sha256_file(prefix_manifest),
        )
        self.assertEqual(
            manifest["prefix_reuse"]["prefix_sequence_identity_sha256"],
            json.loads(prefix_manifest.read_text())["sequence_identity"]["sha256"],
        )

    def test_full_rejects_any_prefix_manifest_tampering(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        manifest_path = prefix / "conversion_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["claims"]["anyfeature_built"] = True
        manifest_path.write_text(adapter.canonical_json(manifest), encoding="utf-8")
        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        output = self.root / "full_manifest_tamper"
        with self.assertRaisesRegex(
            adapter.ContractError, "PREFIX_CONVERSION_MANIFEST_TAMPERED"
        ):
            adapter.write_artifact(
                output,
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=prefix,
            )
        self.assertFalse(output.exists())

    def test_full_rejects_prefix_png_replacement_and_extra_png(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, selection = self._full_inputs()

        replaced, _ = self._export_prefix("prefix_replaced")
        replaced_png = replaced / "rgb" / f"{CAMERA_STAMPS[0]}.png"
        replaced_png.write_bytes(replaced_png.read_bytes() + b"tamper")
        with self.assertRaisesRegex(adapter.ContractError, "IMAGE_ROW_MISMATCH"):
            adapter.write_artifact(
                self.root / "full_replaced",
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=replaced,
            )

        extra, _ = self._export_prefix("prefix_extra")
        (extra / "rgb" / "extra.png").write_bytes(b"not-an-image")
        with self.assertRaisesRegex(adapter.ContractError, "PNG_FILE_SET_MISMATCH"):
            adapter.write_artifact(
                self.root / "full_extra",
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=extra,
            )
        (extra / "rgb" / "extra.png").unlink()
        (extra / "unregistered-owner.txt").write_text("unknown", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "ENTRY_NOT_ALLOWED"):
            adapter.write_artifact(
                self.root / "full_extra_root",
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=extra,
            )

    def test_full_rejects_prefix_symlinks(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        manifest_path = prefix / "conversion_manifest.json"
        manifest_target = self.root / "manifest-target.json"
        manifest_target.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        manifest_path.symlink_to(manifest_target)
        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        with self.assertRaisesRegex(adapter.ContractError, "CAMERA_ROOT_ENTRY_SYMLINK"):
            adapter.write_artifact(
                self.root / "full",
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=prefix,
            )

    def test_full_allows_registered_downstream_r2d2_evidence(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        r2d2 = prefix / "r2d2"
        for name in ("keypoints", "scores", "descriptors"):
            directory = r2d2 / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{CAMERA_STAMPS[0]}.bin").write_bytes(b"learned")
        (r2d2 / "materialization_manifest.json").write_text(
            '{"owned_by":"materializer"}\n', encoding="utf-8"
        )
        (prefix / "producer_run_manifest.json").write_text(
            '{"owned_by":"producer"}\n', encoding="utf-8"
        )
        evidence = prefix / "producer_evidence"
        evidence.mkdir()
        (evidence / "environment.lock").write_text("frozen\n", encoding="utf-8")
        for stamp in CAMERA_STAMPS[:2]:
            (prefix / "rgb" / f"{stamp}.png.r2d2").write_bytes(
                f"archive-{stamp}".encode("ascii")
            )

        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        output = self.root / "full_after_r2d2"
        with mock.patch.object(
            adapter, "encode_lossless_png", wraps=adapter.encode_lossless_png
        ) as encode:
            manifest = adapter.write_artifact(
                output,
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=prefix,
            )
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(encode.call_args.args[0].source_index, 2)
        self.assertEqual(manifest["prefix_reuse"]["count"], 2)
        self.assertFalse((output / "r2d2").exists())
        self.assertFalse(any((output / "rgb").glob("*.r2d2")))

    def test_full_allows_partial_registered_learned_namespace(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        (prefix / "rgb" / f"{CAMERA_STAMPS[0]}.png.r2d2").write_bytes(
            b"partial-failed-producer-output"
        )
        (prefix / "producer_evidence").mkdir()
        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        manifest = adapter.write_artifact(
            self.root / "full_after_partial_learned_failure",
            self.bag,
            source_hash,
            self.calibration,
            calibration_hash,
            calibration,
            selection,
            FULL_PROFILE,
            prefix_root=prefix,
        )
        self.assertTrue(manifest["evaluation_eligible_full_window"])

    def test_full_existing_output_preserves_prefix_and_target(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        prefix_manifest_before = (prefix / "conversion_manifest.json").read_bytes()
        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        output = self.root / "full"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.write_artifact(
                output,
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
                prefix_root=prefix,
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(
            (prefix / "conversion_manifest.json").read_bytes(),
            prefix_manifest_before,
        )

    def test_full_requires_prefix_root_at_api_and_cli(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, selection = self._full_inputs()
        with self.assertRaisesRegex(adapter.ContractError, "PREFIX_ROOT_REQUIRED"):
            adapter.write_artifact(
                self.root / "full",
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                FULL_PROFILE,
            )
        stdout = io.StringIO()
        with mock.patch.object(adapter, "prepare") as prepare, redirect_stdout(stdout):
            rc = adapter.main(["--profile", "a02-full", "--action", "preflight"])
        self.assertEqual(rc, adapter.RC_INTEGRITY_ERROR)
        prepare.assert_not_called()
        self.assertIn("PREFIX_ROOT_REQUIRED_FOR_FULL_EXPORT", stdout.getvalue())

    def test_cli_full_preflight_audits_prefix(self) -> None:
        _build_bag(self.bag)
        prefix, _ = self._export_prefix()
        prepared = self._full_inputs()
        stdout = io.StringIO()
        with mock.patch.dict(
            adapter.PROFILES, {"a02-full": FULL_PROFILE}, clear=False
        ), mock.patch.object(adapter, "prepare", return_value=prepared), mock.patch.object(
            adapter,
            "validate_prefix_artifact",
            wraps=adapter.validate_prefix_artifact,
        ) as audit, redirect_stdout(stdout):
            rc = adapter.main(
                [
                    "--profile",
                    "a02-full",
                    "--action",
                    "preflight",
                    "--source-bag",
                    str(self.bag),
                    "--source-calibration",
                    str(self.calibration),
                    "--prefix-root",
                    str(prefix),
                ]
            )
        self.assertEqual(rc, adapter.RC_READY)
        audit.assert_called_once()
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], adapter.STATUS_PREFLIGHT_READY)
        self.assertTrue(result["prefix_reuse"]["png_bytes_audited"])

    def test_existing_output_is_not_clobbered(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, selection = self._prepare()
        output = self.root / "sequence"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.write_artifact(
                output,
                self.bag,
                source_hash,
                self.calibration,
                calibration_hash,
                calibration,
                selection,
                PREFIX_PROFILE,
            )
        self.assertEqual(marker.read_text(), "preserve")

    def test_png_failure_rolls_back_staging(self) -> None:
        _build_bag(self.bag)
        source_hash, calibration_hash, calibration, selection = self._prepare()
        output = self.root / "sequence"
        with mock.patch.object(
            adapter,
            "encode_lossless_png",
            side_effect=adapter.ContractError("PNG_ENCODE_FAILED:synthetic"),
        ):
            with self.assertRaisesRegex(adapter.ContractError, "PNG_ENCODE_FAILED"):
                adapter.write_artifact(
                    output,
                    self.bag,
                    source_hash,
                    self.calibration,
                    calibration_hash,
                    calibration,
                    selection,
                    PREFIX_PROFILE,
                )
        self.assertFalse(output.exists())

    def test_nonmonotonic_header_and_bad_schema_fail_closed(self) -> None:
        _build_bag(self.bag, nonmonotonic_header=True)
        with self.assertRaisesRegex(
            adapter.ContractError, "CAMERA_RECORD_HEADER_STAMP_MISMATCH"
        ):
            self._prepare(FULL_PROFILE)

        self.bag.unlink()
        _build_bag(self.bag, bad_width=True)
        with self.assertRaisesRegex(adapter.ContractError, "CAMERA_DIMENSION_MISMATCH"):
            self._prepare(FULL_PROFILE)

    def test_wrong_source_or_calibration_hash_fails_before_export(self) -> None:
        _build_bag(self.bag)
        bag_size, bag_hash = _identity(self.bag)
        calibration_size, calibration_hash = _identity(self.calibration)
        with self.assertRaisesRegex(adapter.ContractError, "SOURCE_BAG_SHA256_MISMATCH"):
            adapter.prepare(
                self.bag,
                self.calibration,
                PREFIX_PROFILE,
                expected_source_size=bag_size,
                expected_source_sha256="0" * 64,
                expected_calibration_size=calibration_size,
                expected_calibration_sha256=calibration_hash,
            )
        with self.assertRaisesRegex(
            adapter.ContractError, "SOURCE_CALIBRATION_SHA256_MISMATCH"
        ):
            adapter.prepare(
                self.bag,
                self.calibration,
                PREFIX_PROFILE,
                expected_source_size=bag_size,
                expected_source_sha256=bag_hash,
                expected_calibration_size=calibration_size,
                expected_calibration_sha256="0" * 64,
            )

    def test_report_publish_is_atomic_exclusive_and_no_clobber(self) -> None:
        report = self.root / "reports" / "result.json"
        adapter._write_report_atomic(report, "first\n")
        self.assertEqual(report.read_text(encoding="utf-8"), "first\n")
        with self.assertRaisesRegex(adapter.ContractError, "REPORT_ALREADY_EXISTS"):
            adapter._write_report_atomic(report, "second\n")
        self.assertEqual(report.read_text(encoding="utf-8"), "first\n")
        self.assertEqual(list(report.parent.glob(f".{report.name}.tmp-*")), [])

    def test_report_destination_rejects_all_evidence_and_staging_trees(self) -> None:
        bag = self.root / "bag_source" / "source.bag"
        calibration = self.root / "calibration_source" / "camera.yaml"
        prefix = self.root / "sealed_prefix"
        output = self.root / "planned_full"
        bag.parent.mkdir()
        calibration.parent.mkdir()
        prefix.mkdir()
        bag.write_bytes(b"bag")
        calibration.write_bytes(b"calibration")
        forbidden = (
            bag.parent / "report.json",
            calibration.parent / "report.json",
            prefix / "report.json",
            output / "report.json",
            output.parent / f".{output.name}.tmp-forged" / "report.json",
        )
        for report in forbidden:
            with self.subTest(report=report):
                with self.assertRaisesRegex(adapter.ContractError, "REPORT_PATH_INSIDE"):
                    adapter.validate_report_destination(
                        report,
                        source_bag=bag,
                        source_calibration=calibration,
                        prefix_root=prefix,
                        output_root=output,
                    )
        adapter.validate_report_destination(
            self.root / "reports" / "report.json",
            source_bag=bag,
            source_calibration=calibration,
            prefix_root=prefix,
            output_root=output,
        )

    def test_report_destination_rejects_symlink_and_cli_never_overwrites(self) -> None:
        target = self.root / "target.json"
        target.write_text("owner", encoding="utf-8")
        link = self.root / "report-link.json"
        link.symlink_to(target)
        with self.assertRaisesRegex(adapter.ContractError, "REPORT_ALREADY_EXISTS"):
            adapter.validate_report_destination(
                link,
                source_bag=self.root / "bag_source" / "source.bag",
                source_calibration=self.root / "calibration_source" / "camera.yaml",
                prefix_root=None,
                output_root=None,
            )

        with tempfile.TemporaryDirectory() as report_directory:
            report = Path(report_directory) / "failure.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                first_rc = adapter.main(
                    [
                        "--profile",
                        "a02-full",
                        "--action",
                        "preflight",
                        "--report-json",
                        str(report),
                    ]
                )
            self.assertEqual(first_rc, adapter.RC_INTEGRITY_ERROR)
            sealed = report.read_bytes()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                second_rc = adapter.main(
                    [
                        "--profile",
                        "a02-full",
                        "--action",
                        "preflight",
                        "--report-json",
                        str(report),
                    ]
                )
            self.assertEqual(second_rc, adapter.RC_INTEGRITY_ERROR)
            self.assertEqual(report.read_bytes(), sealed)
            self.assertIn("REPORT_ALREADY_EXISTS", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
