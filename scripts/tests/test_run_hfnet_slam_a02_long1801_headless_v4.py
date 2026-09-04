#!/usr/bin/env python3
"""Static and synthetic-only tests; never export data or start HFNet-SLAM."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import export_aqualoc_a02_shared_4500_6300_v1 as exporter
from scripts import bridge_hfnet_world_body_to_vins_csv_v1 as bridge
from scripts import run_hfnet_slam_a02_long1801_headless_v4 as runner


CONFIG = """%YAML:1.0
Extractor.type: "HFNetRT"
Extractor.modelPath: "{model}/"
Extractor.scaleFactor: 1.2
Extractor.nLevels: 4
Extractor.nFeatures: 675
Extractor.threshold: 0.01
loopClosing: 1
"""


def png_header() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 968, 608) + bytes((8, 0, 0, 0, 0)) + b"\x00\x00\x00\x00"


def stamps() -> list[int]:
    first, boundary, last = exporter.EXPECTED_FIRST_CAMERA_NS, exporter.EXPECTED_BOUNDARY_CAMERA_NS, exporter.EXPECTED_LAST_CAMERA_NS
    return [first + (boundary - first) * index // 900 for index in range(901)] + [boundary + (last - boundary) * index // 900 for index in range(1, 901)]


def make_shared(root: Path) -> None:
    camera_stamps = stamps()
    canonical = root / "shared/cam0/data"
    hfnet = root / "hfnet/mav0/cam0/data"
    canonical.mkdir(parents=True)
    hfnet.mkdir(parents=True)
    template = root / "template.png"
    template.write_bytes(png_header())
    png_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    images = []
    for relative, stamp in enumerate(camera_stamps):
        canonical_path = canonical / f"{stamp}.png"
        hfnet_path = hfnet / f"{stamp}.png"
        os.link(template, canonical_path)
        os.link(template, hfnet_path)
        images.append({"relative_index": relative, "global_source_index": 4500 + relative, "raw_header_ns": stamp, "source_pixel_sha256": "0" * 64, "png_sha256": png_hash, "png_size_bytes": len(png_header()), "materialization": "hardlink" if relative < 901 else "encoded_new_lossless", "relative_path": f"shared/cam0/data/{stamp}.png"})
    template.unlink()
    times = ("\n".join(map(str, camera_stamps)) + "\n").encode("ascii")
    (root / "shared/cam0_times.txt").write_bytes(times)
    (root / "hfnet/cam0_times.txt").write_bytes(times)
    camera_csv = ["#timestamp [ns],filename"] + [f"{stamp},{stamp}.png" for stamp in camera_stamps]
    (root / "hfnet/mav0/cam0/data.csv").write_text("\n".join(camera_csv), encoding="ascii")

    imu_dir = root / "hfnet/mav0/imu0"
    imu_dir.mkdir(parents=True)
    imu_first = exporter.EXPECTED_FIRST_IMU_RAW_NS + exporter.IMU_SHIFT_NS
    imu_last = exporter.EXPECTED_LAST_IMU_RAW_NS + exporter.IMU_SHIFT_NS
    imu_stamps = [imu_first + (imu_last - imu_first) * index // (runner.EXPECTED_IMU_COUNT - 1) for index in range(runner.EXPECTED_IMU_COUNT)]
    imu_header = "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"
    (imu_dir / "data.csv").write_text("\n".join([imu_header] + [f"{stamp},0,0,0,0,0,9.8" for stamp in imu_stamps]), encoding="ascii")

    indices = list(range(5400, 6301, 20))
    mapping = [{"global_camera_index": index, "header_ns": camera_stamps[index - 4500]} for index in indices]
    (root / "shared/reference_mapping.csv").write_text("global_camera_index,header_ns,role\n" + "".join(f"{row['global_camera_index']},{row['header_ns']},SCORE\n" for row in mapping), encoding="ascii")
    reference_rows = []
    for row in mapping:
        seconds, fraction = divmod(row["header_ns"], 1_000_000_000)
        reference_rows.append(f"{seconds}.{fraction:09d} 0 0 0 0 0 0 1")
    (root / "shared/reference_proxy.tum").write_text("\n".join(reference_rows) + "\n", encoding="ascii")
    derived = {"path": "/synthetic/window.bag", "size_bytes": 123, "sha256": "a" * 64}
    topic_counts = {exporter.CAMERA_TOPIC: 1801, exporter.IMU_TOPIC: 17987}
    producer = {
        "schema_version": "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1",
        "status": "PASS",
        "provenance": {"raw_tar": {"size_bytes": exporter.RAW_TAR_SIZE_BYTES, "sha256": exporter.RAW_TAR_SHA256}, "gt": {"size_bytes": exporter.REFERENCE_SIZE_BYTES, "sha256": exporter.REFERENCE_SHA256}, "converter": {"path": f"/synthetic/{exporter.RAW_CONVERTER_RELATIVE}", "sha256": exporter.RAW_CONVERTER_SHA256}},
        "selection": {"camera_global_start_index": 4500, "camera_global_end_index_inclusive": 6300, "image_count_expected": 1801, "imu_margin_ns": 250_000_000, "imu_rule_closed_interval": "synthetic"},
        "semantics": {"header_stamp": "raw_csv_integer_ns", "record_stamp_equals_header": True, "no_time_shift": True, "image_encoding": "mono8", "gt_pose": "world_T_camera"},
        "output": {"compression": "bz2", "topic_counts": topic_counts},
        "checks": {"synthetic": True},
    }
    manifest = {
        "schema_version": exporter.SCHEMA_VERSION,
        "status": exporter.STATUS_EXPORTED,
        "source": {"derived_window_bag": derived, "provenance": {"producer_record": producer, "output_topic_counts": topic_counts, "derived_window_bag": derived}, "canonical_raw_archive": {"size_bytes": exporter.RAW_TAR_SIZE_BYTES, "sha256": exporter.RAW_TAR_SHA256, "converter_relative_path": exporter.RAW_CONVERTER_RELATIVE, "converter_sha256": exporter.RAW_CONVERTER_SHA256}, "known_full_bag_cross_source_catalog_not_producer_provenance": {"size_bytes": exporter.FULL_BAG_SIZE_BYTES, "sha256": exporter.FULL_BAG_SHA256, "topic_counts": exporter.FULL_BAG_TOPIC_COUNTS}},
        "window": {"feed_global_camera_indices_inclusive": [4500, 6300], "camera_count": 1801, "preroll_global_camera_indices_inclusive": [4500, 5399], "score_global_camera_indices_inclusive": [5400, 6300], "score_reference_global_indices": indices, "score_reference_count": 46},
        "camera": {"topic": exporter.CAMERA_TOPIC, "message_type": exporter.CAMERA_TYPE, "width": 968, "height": 608, "encoding": "mono8", "first_header_ns": camera_stamps[0], "boundary_header_ns": camera_stamps[900], "last_header_ns": camera_stamps[-1], "images": images, "prefix_reuse": {"manifest_sha256": exporter.PREFIX_MANIFEST_SHA256, "camera_count": 901}, "newly_encoded_relative_indices_inclusive": [901, 1800]},
        "imu": {"topic": exporter.IMU_TOPIC, "message_type": exporter.IMU_TYPE, "global_indices_inclusive": [exporter.GLOBAL_IMU_FIRST, exporter.GLOBAL_IMU_LAST], "count": 17987, "time_transform": f"output_ns=raw_header_ns+{exporter.IMU_SHIFT_NS}", "first_raw_header_ns": exporter.EXPECTED_FIRST_IMU_RAW_NS, "last_raw_header_ns": exporter.EXPECTED_LAST_IMU_RAW_NS, "first_output_header_ns": imu_first, "last_output_header_ns": imu_last, "brackets_camera": True},
        "reference": {"identity": {"size_bytes": exporter.REFERENCE_SIZE_BYTES, "sha256": exporter.REFERENCE_SHA256}, "pose_convention": "world_T_camera", "target_rows": 46, "mapping": mapping},
        "views": {"canonical_png_root": "shared/cam0/data", "canonical_times": "shared/cam0_times.txt", "reference_tum": "shared/reference_proxy.tum", "hfnet_euroc_root": "hfnet", "hfnet_camera_link_modes": {"hardlink": 1801}},
        "claims": {"hfnet_started": False, "anyfeature_started": False, "aqua_fe_started": False, "official_source_modified": False, "accuracy_result_generated": False},
        "topic_audit": {exporter.CAMERA_TOPIC: {"message_type": exporter.CAMERA_TYPE, "message_count": 1801}, exporter.IMU_TOPIC: {"message_type": exporter.IMU_TYPE, "message_count": 17987}},
    }
    (root / "conversion_manifest.json").write_bytes(exporter.canonical_json_bytes(manifest))


def pose_rows_for_indices(indices: list[int], offsets_ns: dict[int, int] | None = None) -> str:
    camera = stamps()
    offsets_ns = offsets_ns or {}
    return "".join(f"{camera[relative] + offsets_ns.get(relative, 0)}.000000 {row}.0 0 0 0 0 0 1\n" for row, relative in enumerate(indices))


class Long1801V4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shared_temp = tempfile.TemporaryDirectory()
        cls.shared_root = Path(cls.shared_temp.name) / "shared_artifact"
        make_shared(cls.shared_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared_temp.cleanup()

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.model = self.root / "model/HFNet-RT"
        self.model.mkdir(parents=True)
        (self.model / "HF-Net.onnx").write_bytes(b"synthetic onnx")
        (self.model / "HF-Net.cache").write_bytes(b"synthetic seed cache")
        config = self.root / "config.yaml"
        config.write_text(CONFIG.format(model=self.model.resolve()), encoding="utf-8")
        self.spec = replace(runner.DEFAULT_SPEC, config=config, onnx=self.model / "HF-Net.onnx", cache_seed=self.model / "HF-Net.cache", shared_root=self.shared_root, result=self.root / "result", evidence=self.root / "evidence", contract=self.root / "contract.json", bridge_output=self.root / "bridge/trajectory.csv")

    def test_strict_shared_view_audit_accepts_synthetic_contract(self) -> None:
        audit = runner.audit_shared_input(self.shared_root)
        self.assertEqual(audit["camera_count"], 1801)
        self.assertEqual(audit["imu_count"], 17987)
        self.assertEqual(audit["reference_count"], 46)
        self.assertEqual(audit["score_first_ns"], stamps()[900])

    def test_manifest_score_range_tamper_fails_closed(self) -> None:
        path = self.shared_root / "conversion_manifest.json"
        original = path.read_bytes()
        value = json.loads(original)
        value["window"]["score_global_camera_indices_inclusive"] = [5399, 6300]
        path.write_bytes(exporter.canonical_json_bytes(value))
        try:
            with self.assertRaisesRegex(runner.ContractError, "SHARED_WINDOW_CONTRACT_MISMATCH"):
                runner.audit_shared_input(self.shared_root)
        finally:
            path.write_bytes(original)

    def test_score_aware_trajectory_and_keyframe_gates(self) -> None:
        trajectory = self.root / "trajectory.txt"
        keyframes = self.root / "trajectory_keyframe.txt"
        trajectory_indices = list(range(900, 1201, 10))
        trajectory.write_text(pose_rows_for_indices(trajectory_indices), encoding="ascii")
        keyframes.write_text(pose_rows_for_indices([900, 920]), encoding="ascii")
        trajectory_audit = runner._parse_trajectory(trajectory, stamps(), keyframes=False)
        self.assertTrue(trajectory_audit["gate_pass"])
        self.assertEqual(trajectory_audit["identity"]["size_bytes"], trajectory.stat().st_size)
        self.assertEqual(trajectory_audit["identity"]["sha256"], hashlib.sha256(trajectory.read_bytes()).hexdigest())
        self.assertTrue(runner._parse_trajectory(keyframes, stamps(), keyframes=True)["gate_pass"])

    def test_real_logs_symlink_identity_matches_bridge_canonical_path(self) -> None:
        logs = Path(__file__).resolve().parents[2] / "logs"
        self.assertTrue(logs.is_symlink())
        with tempfile.TemporaryDirectory(prefix="hfnet-v4-path-", dir=logs) as directory:
            lexical = logs / Path(directory).name / "trajectory.txt"
            lexical.write_text(pose_rows_for_indices([900]), encoding="ascii")
            canonical = lexical.resolve(strict=True)
            self.assertTrue(str(canonical).startswith("/mnt/data/AQUA-FE_WS/logs/"))
            trajectory = runner._parse_trajectory(lexical, stamps(), keyframes=False)
            keyframe = runner._parse_trajectory(lexical, stamps(), keyframes=True)
            bridge_identity = bridge.file_identity(canonical)
            self.assertEqual(trajectory["identity"]["path"], str(canonical))
            self.assertEqual(keyframe["identity"]["path"], str(canonical))
            self.assertEqual(bridge_identity, trajectory["identity"])

    def test_hfnet_double_timestamp_quantisation_tolerance_is_frozen(self) -> None:
        positive = self.root / "positive.txt"
        # Reproduces the observed full901 endpoint: official output is +64 ns.
        positive.write_text(pose_rows_for_indices([1800], {1800: 64}), encoding="ascii")
        audit = runner._parse_trajectory(positive, stamps(), keyframes=True)
        self.assertEqual(audit["association_max_abs_error_ns"], 64)
        self.assertTrue(audit["all_rows_uniquely_associated_to_camera"])
        negative = self.root / "negative.txt"
        negative.write_text(pose_rows_for_indices([1800], {1800: 257}), encoding="ascii")
        rejected = runner._parse_trajectory(negative, stamps(), keyframes=True)
        self.assertFalse(rejected["all_rows_uniquely_associated_to_camera"])
        self.assertIn("gt_256ns", rejected["errors"][0])

    def test_one_shot_synthetic_run_passes_without_retry(self) -> None:
        profile = {"input": {"camera_timestamps_ns": stamps()}}
        self.spec.contract.write_text(runner.canonical_json(runner.build_contract(profile, self.spec)), encoding="utf-8")
        starts = []

        def execute(command, environment, cwd, timeout):
            starts.append(command)
            self.spec.result.mkdir()
            (self.spec.result / "trajectory.txt").write_text(pose_rows_for_indices(list(range(900, 1201, 10))), encoding="ascii")
            (self.spec.result / "trajectory_keyframe.txt").write_text(pose_rows_for_indices([900, 920]), encoding="ascii")
            (self.spec.evidence / "run_local_model/HFNet-RT/HF-Net.cache").write_bytes(b"runtime-mutated local cache")
            return runner.v3.CommandResult(0, "synthetic", "")

        with patch.object(runner, "audit_profile", return_value=profile):
            result = runner.run(self.spec, execute=execute)
        self.assertTrue(result["evaluable"])
        self.assertEqual(len(starts), 1)
        self.assertEqual(result["execution"]["process_start_count"], 1)
        self.assertFalse(result["supervision"]["retry_performed"])

    def test_nonzero_rc_is_not_retried_and_fails(self) -> None:
        profile = {"input": {"camera_timestamps_ns": stamps()}}
        self.spec.contract.write_text(runner.canonical_json(runner.build_contract(profile, self.spec)), encoding="utf-8")
        starts = []

        def execute(command, environment, cwd, timeout):
            starts.append(1)
            return runner.v3.CommandResult(7, "", "synthetic failure")

        with patch.object(runner, "audit_profile", return_value=profile):
            result = runner.run(self.spec, execute=execute)
        self.assertFalse(result["evaluable"])
        self.assertEqual(len(starts), 1)
        self.assertEqual(result["return_code"], runner.RC_FAILED)

    def test_frozen_dependency_hashes_match(self) -> None:
        self.assertEqual(runner.identity(runner.V3_RUNNER)["sha256"], runner.V3_RUNNER_SHA256)
        self.assertEqual(runner.identity(runner.SHARED_EXPORTER)["sha256"], runner.SHARED_EXPORTER_SHA256)
        self.assertEqual(runner.identity(runner.BRIDGE)["sha256"], runner.BRIDGE_SHA256)
        self.assertEqual(runner.identity(runner.EVALUATION_CONFIG)["sha256"], runner.EVALUATION_CONFIG_SHA256)


if __name__ == "__main__":
    unittest.main()
