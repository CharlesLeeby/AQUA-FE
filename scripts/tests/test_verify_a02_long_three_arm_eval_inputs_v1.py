from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as verify


def identity(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"path": str(path.resolve(strict=True)), "size_bytes": len(payload), "sha256": verify.sha256_bytes(payload)}


def frozen_vins_config(run: Path) -> str:
    return f'''%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 0

imu_topic: "/rtimulib_node/imu"
image0_topic: "/unused/image"
image1_topic: ""
output_path: "{run / "vins_output"}"

image_width: 968
image_height: 608
cam0_calib: "aqualoc_archaeo02_pinhole.yaml"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]

max_cnt: 150
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: 0.05
gyr_n: 0.003
acc_w: 0.0015
gyr_w: 0.0001
g_norm: 9.8100

loop_closure: 0
td: -0.053694112369382575
estimate_td: 0
rolling_shutter: 0
'''


def frozen_vins_env(feature: Path, raw: Path, binary: Path, port: int, tag: str) -> str:
    raw_root = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    values = {
        "timestamp_utc": "2026-08-12T00:00:00Z",
        "hostname": "synthetic",
        "pwd": str(verify.ROOT),
        "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "ROS_MASTER_URI": f"http://localhost:{port}",
        "ROS_DISTRO": "noetic",
        "CMAKE_PREFIX_PATH": "/opt/ros/noetic:/home/ma/SLAM/VINS-Fusion-origin/devel",
        "ROS_PACKAGE_PATH": "/opt/ros/noetic/share:/home/ma/SLAM/VINS-Fusion-origin/src",
        "LD_LIBRARY_PATH": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
        "PYTHONPATH": "/opt/ros/noetic/lib/python3/dist-packages",
        "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "CATKIN_SETUP_UTIL_ARGS": "--local --extend",
        "ROOT": str(verify.ROOT),
        "AQUALOC_ROOT": str(raw_root),
        "RAW_TAR": str(raw_root / "archaeo_sequence_2_raw_data.tar.gz"),
        "RAW_ROOT": "raw_data",
        "GT_TXT": str(raw_root / "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"),
        "RAW_BAG": str(raw.absolute()),
        "FEATURE_BAG_OVERRIDE": str(feature.absolute()),
        "FRONTEND_CONFIG": str(verify.ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
        "BACKEND_REPLAY_ONLY": "0",
        "RUN_VINS": "1",
        "FORCE_RAW": "0",
        "FORCE_EXPORT": "0",
        "EXPORT_FEATURES": "0",
        "VINS_MULTIPLE_THREAD": "0",
        "VINS_TD": "-0.053694112369382575",
        "VINS_ESTIMATE_TD": "0",
        "VINS_MAX_SOLVER_TIME": "0.04",
        "VINS_MAX_NUM_ITERATIONS": "8",
        "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
        "PLAY_RATE": "1.0",
        "POST_PLAY_SLEEP": "8",
        "ROSBAG_PLAY_DELAY": "3",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
        "ROSBAG_PLAY_TOPICS": "",
        "WAIT_FOR_VINS_SUBSCRIBERS": "0",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
        "PORT": str(port),
        "TAG": tag,
        "rospack_find_vins": "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator",
        "vins_binary": str(binary),
        "vins_binary_stat": "synthetic",
        "vins_binary_md5": f"{verify.hashlib.md5(binary.read_bytes()).hexdigest()}  {binary}",
    }
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


class PreEvalVerifierTests(unittest.TestCase):
    def test_reference_requires_46_rows_and_exact_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            rows = []
            mapping = []
            source_rows = []
            expected_poses = []
            first = verify.SCORE_FIRST_NS
            for offset, global_index in enumerate(range(5400, 6301, 20)):
                stamp = first + offset * 1_000_000_000
                if offset == 45:
                    stamp = verify.SCORE_LAST_NS
                rows.append(f"{stamp//10**9}.{stamp%10**9:09d} 0 0 0 0 0 0 1")
                mapping.append({"global_camera_index": global_index, "header_ns": stamp})
                source_rows.append(f"{global_index} 0 0 0 0 0 0 1")
                expected_poses.append(verify.shared_exporter.ReferencePose(global_camera_index=global_index, header_ns=stamp, position_xyz=(0.0, 0.0, 0.0), quaternion_xyzw=(0.0, 0.0, 0.0, 1.0)))
            source = root / "source_gt.txt"
            source.write_text("\n".join(source_rows) + "\n", encoding="ascii")
            (shared / "reference_proxy.tum").write_bytes(verify.shared_exporter.reference_tum_bytes(tuple(expected_poses)))
            manifest = {
                "schema_version": verify.SHARED_SCHEMA,
                "status": verify.SHARED_STATUS,
                "window": {"score_reference_count": 46, "score_reference_global_indices": list(range(5400, 6301, 20))},
                "views": {"reference_tum": "shared/reference_proxy.tum"},
                "reference": {"identity": identity(source), "target_rows": 46, "pose_convention": "world_T_camera", "mapping": mapping},
            }
            (root / "conversion_manifest.json").write_bytes(verify.canonical_json(manifest))
            reference, _ = verify.validate_reference(root)
            self.assertEqual(reference["path"], str((shared / "reference_proxy.tum").absolute()))
            tampered = (shared / "reference_proxy.tum").read_text(encoding="ascii").replace(" 0 0 0 ", " 1 0 0 ", 1)
            (shared / "reference_proxy.tum").write_text(tampered, encoding="ascii")
            with self.assertRaisesRegex(verify.VerificationError, "EXACT_DERIVATION"):
                verify.validate_reference(root)

    def test_bridge_chain_binds_output_source_and_v4_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "trajectory.txt"
            raw.write_text("1 0 0 0 0 0 0 1\n", encoding="ascii")
            output = root / "bridge.csv"
            output.write_text("1,0,0,0,1,0,0,0\n", encoding="ascii")
            run_result = {
                "schema_version": verify.V4_SCHEMA,
                "status": verify.V4_STATUS,
                "return_code": 0,
                "evaluable": True,
                "execution": {"command_started": True, "process_start_count": 1, "raw_returncode": 0, "timed_out": False},
                "gate": {
                    "trajectory": {"gate_pass": True, "identity": identity(raw)},
                    "keyframe_trajectory": {"gate_pass": True, "identity": identity(raw)},
                },
            }
            result_path = root / "run_result.json"
            result_path.write_bytes(verify.canonical_json(run_result))
            bridge = {
                "schema_version": verify.BRIDGE_SCHEMA,
                "status": "PASS",
                "producer": identity(verify.ROOT / "scripts/bridge_hfnet_world_body_to_vins_csv_v1.py"),
                "source": identity(raw),
                "output": identity(output),
                "v4_run_result": {"identity": identity(result_path), "trajectory_source_identity_match": True, "v4_profile_sha256": "profile"},
                "row_count": 1,
                "semantics": verify.bridge_semantics_contract(),
            }
            bridge_path = root / "bridge.csv.manifest.json"
            bridge_path.write_bytes(verify.canonical_json(bridge))
            with mock.patch.object(verify, "DEFAULT_HFNET_SOURCE", raw), mock.patch.object(
                verify,
                "validate_v4_contract_snapshot_and_profile",
                return_value=({"contract": 1}, {"snapshot": 1}, "profile"),
            ):
                observed, _, _, _, _ = verify.validate_bridge_chain(output, bridge_path, result_path)
            self.assertEqual(observed["sha256"], identity(output)["sha256"])
            output.write_text("1,1,0,0,1,0,0,0\n", encoding="ascii")
            bridge["output"] = identity(output)
            bridge_path.write_bytes(verify.canonical_json(bridge))
            with mock.patch.object(verify, "DEFAULT_HFNET_SOURCE", raw), mock.patch.object(
                verify,
                "validate_v4_contract_snapshot_and_profile",
                return_value=({"contract": 1}, {"snapshot": 1}, "profile"),
            ), self.assertRaisesRegex(verify.VerificationError, "INDEPENDENT_EXACT_REBUILD"):
                verify.validate_bridge_chain(output, bridge_path, result_path)
            output.write_text("1,0,0,0,1,0,0,0\n", encoding="ascii")
            bridge["output"] = identity(output)
            bridge["semantics"]["timestamp_scale_or_offset_applied"] = True
            bridge_path.write_bytes(verify.canonical_json(bridge))
            with mock.patch.object(verify, "DEFAULT_HFNET_SOURCE", raw), self.assertRaisesRegex(
                verify.VerificationError, "PRODUCER_OR_SEMANTICS"
            ):
                verify.validate_bridge_chain(output, bridge_path, result_path)
            bridge["semantics"] = verify.bridge_semantics_contract()
            bridge["producer"]["sha256"] = "0" * 64
            bridge_path.write_bytes(verify.canonical_json(bridge))
            with mock.patch.object(verify, "DEFAULT_HFNET_SOURCE", raw), self.assertRaisesRegex(
                verify.VerificationError, "PRODUCER_OR_SEMANTICS"
            ):
                verify.validate_bridge_chain(output, bridge_path, result_path)

    def test_bridge_output_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "bridge.csv"
            output.write_text("x", encoding="ascii")
            result_path = root / "run.json"
            result_path.write_bytes(verify.canonical_json({}))
            bridge_path = root / "bridge.json"
            bridge_path.write_bytes(verify.canonical_json({"schema_version": verify.BRIDGE_SCHEMA, "status": "PASS", "output": {}}))
            with self.assertRaises(verify.VerificationError):
                verify.validate_bridge_chain(output, bridge_path, result_path)

    def test_arm_requires_score_support(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.csv"
            rows = []
            for index in range(29):
                stamp = verify.SCORE_FIRST_NS + index * 100_000_000
                rows.append(f"{stamp},0,0,0,1,0,0,0")
            path.write_text("\n".join(rows) + "\n", encoding="ascii")
            with self.assertRaisesRegex(verify.VerificationError, "INSUFFICIENT"):
                verify.validate_arm(path, "SHORT")

    def test_arm_rejects_nonmonotonic_raw_order_without_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nonmonotonic.csv"
            rows = []
            for index in range(40):
                stamp = verify.SCORE_FIRST_NS + index * 100_000_000
                if index == 20:
                    stamp = verify.SCORE_FIRST_NS + 10 * 100_000_000
                rows.append(f"{stamp},0,0,0,1,0,0,0")
            path.write_text("\n".join(rows) + "\n", encoding="ascii")
            with self.assertRaisesRegex(verify.VerificationError, "POSE_VALIDATION"):
                verify.validate_arm(path, "NONMONOTONIC")

    def test_vins_log_allows_only_preinitialization_solver_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vins.log"
            path.write_bytes(
                b"Linear solver failure. pre-init\n"
                b"Initialization finish!\n"
                b"normal optimized frame\n"
            )
            report = verify.validate_vins_log(path, "PASS")
            self.assertEqual(report["initialization_success_count"], 1)
            self.assertEqual(
                report["marker_counts_total"]["linear_solver_failure"], 1
            )
            self.assertEqual(
                report["post_initialization_linear_solver_failure_count"], 0
            )

    def test_vins_log_rejects_postinitialization_solver_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vins.log"
            path.write_bytes(
                b"Initialization finish!\nLinear solver failure. post-init\n"
            )
            with self.assertRaisesRegex(
                verify.VerificationError, "POST_INITIALIZATION_LINEAR_SOLVER"
            ):
                verify.validate_vins_log(path, "SOLVER")

    def test_vins_log_rejects_duplicate_initialization_or_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.log"
            duplicate.write_bytes(
                b"Initialization finish!\nInitialization finish!\n"
            )
            with self.assertRaisesRegex(
                verify.VerificationError, "INITIALIZATION_SUCCESS_COUNT_2"
            ):
                verify.validate_vins_log(duplicate, "DUPLICATE")
            restart = root / "restart.log"
            restart.write_bytes(
                b"Initialization finish!\nfailure detection!\nsystem reboot!\n"
            )
            with self.assertRaisesRegex(
                verify.VerificationError, "POST_INITIALIZATION_RESTART_MARKERS_2"
            ):
                verify.validate_vins_log(restart, "RESTART")

    def test_capture_arm_seals_fail_record_instead_of_raising(self) -> None:
        report = verify.capture_arm(
            lambda: (_ for _ in ()).throw(verify.VerificationError("SCIENTIFIC_FAIL"))
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["reasons"], ["SCIENTIFIC_FAIL"])

    def test_raw_vins_writer_schema_and_order_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vio.csv"
            rows = [
                f"{verify.SCORE_FIRST_NS + index * 100000000},0,0,0,1,0,0,0,0,0,0,"
                for index in range(40)
            ]
            path.write_text("\n".join(rows) + "\n", encoding="ascii")
            report = verify.validate_vins_raw_csv_schema(path, "RAW")
            self.assertEqual(report["row_count"], 40)
            rows[20] = rows[10]
            path.write_text("\n".join(rows) + "\n", encoding="ascii")
            with self.assertRaisesRegex(verify.VerificationError, "NOT_STRICTLY"):
                verify.validate_vins_raw_csv_schema(path, "RAW")

    def test_quality_chain_rejects_swapped_constq_bag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native.bag"
            constq = root / "constq.bag"
            audit_path = root / "audit.json"
            native.write_bytes(b"native")
            constq.write_bytes(b"constq")
            audit = {
                "schema_version": verify.QUALITY_AUDIT_SCHEMA,
                "contract_pass": True,
                "input_bag": str(native.absolute()),
                "input_sha256": identity(native)["sha256"],
                "output_bag": str(constq.absolute()),
                "output_sha256": identity(constq)["sha256"],
                "feature_topic": "/feature_tracker/feature",
                "source_codes": [1],
                "quality": 1.0,
                "sigma": 1.0,
                "total_messages": 1900,
                "raw_equal_nonfeature_messages": 1000,
                "feature_frames": 900,
                "selected_observations": 315000,
                "changed_observations": 315000,
                "untouched_observations": 0,
            }
            audit_path.write_bytes(verify.canonical_json(audit))
            self.assertEqual(
                verify.validate_quality_chain(native, constq, audit_path)["status"],
                "PASS",
            )
            constq.write_bytes(b"swapped")
            with self.assertRaisesRegex(verify.VerificationError, "CONTRACT_MISMATCH"):
                verify.validate_quality_chain(native, constq, audit_path)

    def test_xfeat_chain_binds_manifest_audit_and_bag_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            raw = root / "raw.bag"
            camera = root / "camera.yaml"
            output = root / "xfeat.bag"
            manifest_path = root / "manifest.json"
            audit_path = root / "audit.json"
            for path, payload in ((source, b"source"), (raw, b"raw"), (camera, b"camera"), (output, b"output")):
                path.write_bytes(payload)
            official_files = verify.validate_xfeat_official_closure()["files"]
            static_artifacts = {
                label: {
                    **official_files[relative],
                    "path": str((verify.ROOT / relative).resolve()),
                }
                for label, relative in {
                    "xfeat_source": "external_tools/accelerated_features/modules/xfeat.py",
                    "xfeat_model_source": "external_tools/accelerated_features/modules/model.py",
                    "xfeat_interpolator_source": "external_tools/accelerated_features/modules/interpolator.py",
                    "xfeat_weight": "external_tools/accelerated_features/weights/xfeat.pt",
                    "xfeat_license": "external_tools/accelerated_features/LICENSE",
                }.items()
            }
            manifest = {
                "schema_version": verify.XFEAT_MANIFEST_SCHEMA,
                "status": "FULL",
                "formal_eligible": True,
                "detector_origin": "cli_production_factory",
                "prefix": {"requested_max_published_frames": None, "source_total_published_frames": 900, "selected_published_frames": 900},
                "inputs": {
                    "source_feature_bag": identity(source),
                    "raw_image_bag": identity(raw),
                    "camera_yaml": identity(camera),
                    "feature_topic": "/feature_tracker/feature",
                    "image_topic": "/camera/image_raw",
                },
                "algorithm": {"name": "xfeat_detector_raw_frame_lk_carrier_v1"},
                "code_artifacts": {
                    "exporter": {"sha256": verify.XFEAT_EXPORTER_SHA256},
                    "carrier_base": {"sha256": verify.XFEAT_CARRIER_BASE_SHA256},
                    "quality_reference_source": identity(verify.ROOT / "uw_frontend/quality/image_quality.py"),
                    **static_artifacts,
                    "detector": {
                        "identity": "official_verlab_XFeat_sparse_detectAndCompute_proposals_only",
                        "closure": {
                            "xfeat.py": official_files["external_tools/accelerated_features/modules/xfeat.py"],
                            "model.py": official_files["external_tools/accelerated_features/modules/model.py"],
                            "interpolator.py": official_files["external_tools/accelerated_features/modules/interpolator.py"],
                            "xfeat.pt": official_files["external_tools/accelerated_features/weights/xfeat.pt"],
                        },
                        "repository": {"commit": "e92685f57f8318b18725c5c8c0bd28c7fe188d9a"},
                        "license": {"spdx": "Apache-2.0", "file": official_files["external_tools/accelerated_features/LICENSE"]},
                        "runtime": {
                            "device": "cpu",
                            "torch_version": "2.2.2+cpu",
                            "opencv_version": "4.2.0",
                            "numpy_version": "1.24.4",
                            "imported_module_paths": {
                                "modules.xfeat": str((verify.ROOT / "external_tools/accelerated_features/modules/xfeat.py").resolve()),
                                "modules.model": str((verify.ROOT / "external_tools/accelerated_features/modules/model.py").resolve()),
                                "modules.interpolator": str((verify.ROOT / "external_tools/accelerated_features/modules/interpolator.py").resolve()),
                            },
                            "detect_calls": 900,
                            "gray_input_shapes_hw": [[608, 968]],
                            "rgb_tensor_input_shapes_bchw": [[1, 3, 608, 968]],
                        },
                    },
                },
                "output_bag": identity(output),
                "metrics": {"published_frames": 900, "observations": 315000, "observations_per_frame_min": 350, "observations_per_frame_max": 350},
            }
            manifest_path.write_bytes(verify.canonical_json(manifest))
            audit = {
                "schema_version": verify.XFEAT_AUDIT_SCHEMA,
                "status": "PASS",
                "pass": True,
                "input": {
                    "reference_bag": str(source.absolute()),
                    "candidate_bag": str(output.absolute()),
                    "camera_yaml": str(camera.absolute()),
                    "feature_topic": "/feature_tracker/feature",
                    "allow_candidate_prefix": False,
                },
                "method": {"method_id": "xfeat_detector_raw_frame_lk_carrier_v1", "expected_source_code": 20, "expected_observations_per_frame": 350},
                "audit_artifact": {
                    "entrypoint": {"sha256": verify.XFEAT_AUDITOR_SHA256},
                    "audit_base": {"sha256": verify.XFEAT_AUDIT_BASE_SHA256},
                },
            }
            audit_path.write_text(json.dumps(audit, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
            self.assertEqual(
                verify.validate_xfeat_chain(source_bag=source, raw_bag=raw, camera_yaml=camera, output_bag=output, manifest_path=manifest_path, audit_path=audit_path)["status"],
                "PASS",
            )
            manifest["inputs"]["source_feature_bag"] = identity(output)
            manifest_path.write_bytes(verify.canonical_json(manifest))
            with self.assertRaisesRegex(verify.VerificationError, "IDENTITY_MISMATCH"):
                verify.validate_xfeat_chain(source_bag=source, raw_bag=raw, camera_yaml=camera, output_bag=output, manifest_path=manifest_path, audit_path=audit_path)
            manifest["inputs"]["source_feature_bag"] = identity(source)
            manifest["code_artifacts"]["quality_reference_source"]["sha256"] = "0" * 64
            manifest_path.write_bytes(verify.canonical_json(manifest))
            with self.assertRaisesRegex(verify.VerificationError, "QUALITY_REFERENCE_SOURCE"):
                verify.validate_xfeat_chain(source_bag=source, raw_bag=raw, camera_yaml=camera, output_bag=output, manifest_path=manifest_path, audit_path=audit_path)
            manifest["code_artifacts"]["quality_reference_source"] = identity(verify.ROOT / "uw_frontend/quality/image_quality.py")
            manifest["code_artifacts"]["detector"]["runtime"]["device"] = "cuda:0"
            manifest_path.write_bytes(verify.canonical_json(manifest))
            with self.assertRaisesRegex(verify.VerificationError, "EXPORT_MANIFEST_CONTRACT"):
                verify.validate_xfeat_chain(source_bag=source, raw_bag=raw, camera_yaml=camera, output_bag=output, manifest_path=manifest_path, audit_path=audit_path)

    def test_shared_manifest_must_bind_current_canonical_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            window = root / "window.bag"
            window_manifest = root / "window.bag.manifest.json"
            window.write_bytes(b"bag")
            window_manifest.write_bytes(b"manifest")
            derived = identity(window)
            provenance = {
                "path": str(window_manifest.absolute()),
                "size_bytes": len(b"manifest"),
                "sha256": verify.sha256_bytes(b"manifest"),
                "producer_record": {
                    "provenance": {"raw_tar": {}, "gt": {}, "converter": {}},
                    "output": {},
                },
                "output_topic_counts": {"/camera/image_raw": 1801},
                "derived_window_bag": derived,
            }
            shared_manifest = {"source": {"provenance": provenance, "derived_window_bag": derived}}
            (root / "conversion_manifest.json").write_bytes(verify.canonical_json(shared_manifest))
            with mock.patch.object(verify.shared_exporter, "validate_provenance", return_value=provenance):
                report = verify.validate_shared_source_chain(root, window, window_manifest)
                self.assertEqual(report["canonical_window_bag_identity"], derived)
                shared_manifest["source"]["derived_window_bag"] = {"sha256": "wrong"}
                (root / "conversion_manifest.json").write_bytes(verify.canonical_json(shared_manifest))
                with self.assertRaisesRegex(verify.VerificationError, "DERIVED_WINDOW"):
                    verify.validate_shared_source_chain(root, window, window_manifest)

    def test_replay_manifest_rejects_wrong_feature_bag_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            (run / "vins_output").mkdir(parents=True)
            trajectory = run / "vins_output/vio.csv"
            trajectory.write_bytes(b"trajectory")
            feature = root / "feature.bag"
            raw = root / "raw.bag"
            feature.write_bytes(b"feature")
            raw.write_bytes(b"raw")
            eval_config = root / "eval.yaml"
            config = frozen_vins_config(run)
            eval_config.write_text(config, encoding="ascii")
            (run / "vins_aqualoc_archaeo_external.yaml").write_text(config, encoding="ascii")
            (run / "aqualoc_archaeo02_pinhole.yaml").write_bytes(b"camera")
            frozen_camera_identity = identity(run / "aqualoc_archaeo02_pinhole.yaml")
            binary = root / "vins_node"
            binary.write_bytes(b"binary")
            env = frozen_vins_env(
                feature,
                raw,
                binary,
                11531,
                "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1",
            )
            (run / "vins_env_manifest.txt").write_text(env, encoding="utf-8")
            replay = f"run_dir={run}\nraw_bag={raw}\nplay_bag={feature}\nvins_csv={trajectory}\n"
            (run / "replay_manifest.txt").write_text(replay, encoding="utf-8")
            receipt = verify.build_vins_process_receipt("B1_CONSTQ", 0)
            receipt["run_dir"] = str(run.absolute())
            receipt["feature_bag"] = str(feature.absolute())
            (run / "process_rc_receipt.json").write_bytes(verify.canonical_json(receipt))
            with mock.patch.object(verify, "VINS_BINARY", binary), mock.patch.object(verify, "exact_identity", side_effect=lambda path, expected, label: identity(Path(path))):
                with mock.patch.object(verify, "vins_process_receipt_contract", return_value={"run_dir": run, "feature_bag": feature, "port": 11531, "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1"}):
                    report = verify.validate_vins_replay_provenance(trajectory_path=trajectory, expected_feature_bag=identity(feature), expected_camera_config=frozen_camera_identity, raw_window_bag=raw, eval_config=eval_config, port=11531, label="B1_CONSTQ")
                self.assertEqual(report["ros_master_port"], 11531)
                nonzero_receipt = dict(receipt)
                nonzero_receipt["return_code"] = 2
                nonzero_receipt["status"] = "FAIL_PROCESS_NONZERO"
                (run / "process_rc_receipt.json").write_bytes(verify.canonical_json(nonzero_receipt))
                with self.assertRaisesRegex(verify.VerificationError, "PROCESS_RC_RECEIPT_NOT_EXACT_RC0"):
                    with mock.patch.object(verify, "vins_process_receipt_contract", return_value={"run_dir": run, "feature_bag": feature, "port": 11531, "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1"}):
                        verify.validate_vins_replay_provenance(trajectory_path=trajectory, expected_feature_bag=identity(feature), expected_camera_config=frozen_camera_identity, raw_window_bag=raw, eval_config=eval_config, port=11531, label="B1_CONSTQ")
                (run / "process_rc_receipt.json").write_bytes(verify.canonical_json(receipt))
                (run / "replay_manifest.txt").write_text(replay.replace(str(feature), str(raw)), encoding="utf-8")
                with self.assertRaisesRegex(verify.VerificationError, "REPLAY_MANIFEST_BINDING"):
                    with mock.patch.object(verify, "vins_process_receipt_contract", return_value={"run_dir": run, "feature_bag": feature, "port": 11531, "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1"}):
                        verify.validate_vins_replay_provenance(trajectory_path=trajectory, expected_feature_bag=identity(feature), expected_camera_config=frozen_camera_identity, raw_window_bag=raw, eval_config=eval_config, port=11531, label="B1_CONSTQ")
                (run / "replay_manifest.txt").write_text(replay, encoding="utf-8")
                (run / "aqualoc_archaeo02_pinhole.yaml").write_bytes(b"tampered-camera")
                with self.assertRaisesRegex(verify.VerificationError, "CAMERA_CONFIG_NOT_EXACT"):
                    with mock.patch.object(verify, "vins_process_receipt_contract", return_value={"run_dir": run, "feature_bag": feature, "port": 11531, "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1"}):
                        verify.validate_vins_replay_provenance(trajectory_path=trajectory, expected_feature_bag=identity(feature), expected_camera_config=frozen_camera_identity, raw_window_bag=raw, eval_config=eval_config, port=11531, label="B1_CONSTQ")
                (run / "aqualoc_archaeo02_pinhole.yaml").write_bytes(b"camera")
                (run / "vins_aqualoc_archaeo_external.yaml").write_text(
                    config.replace("max_solver_time: 0.04", "max_solver_time: 0.05"),
                    encoding="ascii",
                )
                with self.assertRaisesRegex(verify.VerificationError, "max_solver_time|FULL_NORMALIZED"):
                    with mock.patch.object(verify, "vins_process_receipt_contract", return_value={"run_dir": run, "feature_bag": feature, "port": 11531, "tag": "litcmp_a02_4500_6300_preroll_b1_constq_vins_r1"}):
                        verify.validate_vins_replay_provenance(trajectory_path=trajectory, expected_feature_bag=identity(feature), expected_camera_config=frozen_camera_identity, raw_window_bag=raw, eval_config=eval_config, port=11531, label="B1_CONSTQ")

    def test_post_eval_gate_requires_ape_rpe_and_grid45(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.tum"
            reference.write_bytes(b"reference")
            summary_path = root / "common_support_summary.json"
            summary = {
                "protocol": verify.frozen_evaluation_protocol(reference),
                "support": {"ape_valid": True, "rpe_valid": True, "grid_count": 45},
                "arms": {label: {"ape_rmse_m": 1.0, "rpe_rmse_m": 2.0} for label in verify.ARM_LABELS},
            }
            summary_path.write_bytes(verify.canonical_json(summary))
            _, gates = verify.validate_evaluation_summary(summary_path, reference)
            self.assertEqual(gates["grid_count"], 45)
            summary["support"]["grid_count"] = 44
            summary_path.write_bytes(verify.canonical_json(summary))
            with self.assertRaisesRegex(verify.VerificationError, "GRID45"):
                verify.validate_evaluation_summary(summary_path, reference)

    def test_b1_guard_governance_binds_unique_pass_decision_and_a02_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            decision_dir = Path(directory) / "decision"
            decision_dir.mkdir()
            contract = json.loads(verify.DEFAULT_B1_BACKEND_CONTRACT.read_text())
            records = contract["records"]
            decision = {
                "schema_version": verify.B1_GUARD_DECISION_SCHEMA,
                "status": "PASS",
                "contract_pass": True,
                "action": "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3",
                "result_label": "B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3",
                "counts_as_b1": True,
                "counts_as_proposed_result": False,
                "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
                "contract_path": str(verify.DEFAULT_B1_BACKEND_CONTRACT.absolute()),
                "contract_file_sha256": verify.B1_BACKEND_CONTRACT_SHA256,
                "contract_hash": verify.B1_BACKEND_CONTRACT_PAYLOAD_HASH,
                "base_contract_hash": verify.B1_BASE_BACKEND_CONTRACT_PAYLOAD_HASH,
                "exporter": records["current_exporter"],
                "transition_proof": records["transition_proof"],
                "backend_binary": records["vins_node"],
                "vins_ldd_core": contract["vins_ldd_core"],
                "algorithm_settings": contract["algorithm_settings"],
                "reasons": [],
            }
            decision_path = decision_dir / "b1_current_exporter_v3_decision.json"
            decision_path.write_bytes(verify.canonical_json(decision))
            raw_path = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
            gt_path = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
            linkage = verify.validate_vins_dynamic_linkage(verify.VINS_BINARY)
            report = verify.validate_b1_guard_governance(
                decision_dir=decision_dir,
                contract_path=verify.DEFAULT_B1_BACKEND_CONTRACT,
                eligibility_manifest=verify.DEFAULT_B1_ELIGIBILITY_MANIFEST,
                raw_tar_claim={"path": str(raw_path.resolve(strict=True))},
                gt_claim={"path": str(gt_path.resolve(strict=True))},
                frontend_exporter_identity=identity(verify.ROOT / "uw_frontend/ros/export_vins_features.py"),
                vins_binary_identity=identity(verify.VINS_BINARY),
                vins_dynamic_linkage=linkage,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["decision"]["sha256"], identity(decision_path)["sha256"])

    def test_b1_guard_governance_rejects_exporter_drift_and_multiple_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            decision_dir = Path(directory) / "decision"
            decision_dir.mkdir()
            contract = json.loads(verify.DEFAULT_B1_BACKEND_CONTRACT.read_text())
            records = contract["records"]
            decision = {
                "schema_version": verify.B1_GUARD_DECISION_SCHEMA,
                "status": "PASS",
                "contract_pass": True,
                "action": "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3",
                "result_label": "B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3",
                "counts_as_b1": True,
                "counts_as_proposed_result": False,
                "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
                "contract_path": str(verify.DEFAULT_B1_BACKEND_CONTRACT.absolute()),
                "contract_file_sha256": verify.B1_BACKEND_CONTRACT_SHA256,
                "contract_hash": verify.B1_BACKEND_CONTRACT_PAYLOAD_HASH,
                "base_contract_hash": verify.B1_BASE_BACKEND_CONTRACT_PAYLOAD_HASH,
                "exporter": records["current_exporter"],
                "transition_proof": records["transition_proof"],
                "backend_binary": records["vins_node"],
                "vins_ldd_core": contract["vins_ldd_core"],
                "algorithm_settings": contract["algorithm_settings"],
                "reasons": [],
            }
            first = decision_dir / "b1_current_exporter_v3_decision.json"
            first.write_bytes(verify.canonical_json(decision))
            raw_path = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
            gt_path = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
            kwargs = {
                "decision_dir": decision_dir,
                "contract_path": verify.DEFAULT_B1_BACKEND_CONTRACT,
                "eligibility_manifest": verify.DEFAULT_B1_ELIGIBILITY_MANIFEST,
                "raw_tar_claim": {"path": str(raw_path.absolute())},
                "gt_claim": {"path": str(gt_path.absolute())},
                "frontend_exporter_identity": {**identity(verify.ROOT / "uw_frontend/ros/export_vins_features.py"), "sha256": "0" * 64},
                "vins_binary_identity": identity(verify.VINS_BINARY),
                "vins_dynamic_linkage": verify.validate_vins_dynamic_linkage(verify.VINS_BINARY),
            }
            with self.assertRaisesRegex(verify.VerificationError, "IDENTITY_MISMATCH"):
                verify.validate_b1_guard_governance(**kwargs)
            second = decision_dir / "unexpected.json"
            second.write_bytes(verify.canonical_json(decision))
            kwargs["frontend_exporter_identity"] = identity(verify.ROOT / "uw_frontend/ros/export_vins_features.py")
            with self.assertRaisesRegex(verify.VerificationError, "FILE_COUNT_2"):
                verify.validate_b1_guard_governance(**kwargs)

    def test_vins_ldd_binding_rejects_wrong_library_path(self) -> None:
        output = (
            "libvins_lib.so => /tmp/wrong/libvins_lib.so (0x1)\n"
            f"libcamera_models.so => {verify.VINS_CAMERA_MODELS_LIBRARY} (0x2)\n"
        )
        completed = verify.subprocess.CompletedProcess(
            [str(verify.LDD), str(verify.VINS_BINARY)], 0, output, ""
        )
        with mock.patch.object(verify, "exact_identity", return_value={"path": str(verify.LDD), "size_bytes": 1, "sha256": verify.LDD_SHA256}), mock.patch.object(verify.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(verify.VerificationError, "PATH_MISMATCH"):
                verify.validate_vins_dynamic_linkage(verify.VINS_BINARY)

    def test_static_gate_rejects_incomplete_identity_set_before_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            freeze = Path(directory) / "freeze.json"
            freeze.write_bytes(
                verify.canonical_json(
                    {
                        "schema_version": verify.FREEZE_SCHEMA,
                        "status": verify.FREEZE_STATUS,
                        "identities": {},
                    }
                )
            )
            with self.assertRaisesRegex(verify.VerificationError, "IDENTITY_COUNT"):
                verify.validate_static_freeze(freeze)

    def test_window_contract_rejects_nanosecond_rounding(self) -> None:
        freeze = {"window": dict(verify.EXPECTED_WINDOW_CONTRACT)}
        self.assertEqual(
            verify.validate_frozen_window_contract(freeze)["status"],
            "PASS_EXACT_INTEGER_WINDOW_CONTRACT",
        )
        tampered = dict(verify.EXPECTED_WINDOW_CONTRACT)
        tampered["canonical_margin_imu_endpoints_ns"] = [
            1_542_829_016_456_083_700,
            1_542_829_106_933_121_500,
        ]
        with self.assertRaisesRegex(verify.VerificationError, "WINDOW_CONTRACT"):
            verify.validate_frozen_window_contract({"window": tampered})

    def test_evidence_is_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            verify.write_exclusive(path, b"first")
            with self.assertRaises(FileExistsError):
                verify.write_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")

    def test_frozen_tool_hashes_match(self) -> None:
        self.assertEqual(verify.exact_identity(verify.DEFAULT_EVALUATOR, verify.EVALUATOR_SHA256, "E")["sha256"], verify.EVALUATOR_SHA256)
        self.assertEqual(verify.exact_identity(verify.DEFAULT_CORE, verify.CORE_SHA256, "C")["sha256"], verify.CORE_SHA256)
        self.assertEqual(verify.exact_identity(verify.DEFAULT_EVAL_CONFIG, verify.CONFIG_SHA256, "Y")["sha256"], verify.CONFIG_SHA256)
        for path, expected, label in (
            (verify.DEFAULT_B1_BACKEND_CONTRACT, verify.B1_BACKEND_CONTRACT_SHA256, "BC"),
            (verify.DEFAULT_B1_BASE_BACKEND_CONTRACT, verify.B1_BASE_BACKEND_CONTRACT_SHA256, "BBC"),
            (verify.ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py", verify.B1_CONTRACT_CHECKER_SHA256, "B1C3"),
            (verify.ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py", verify.B1_V2_COMMON_CHECKER_SHA256, "B1C2"),
            (verify.ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py", verify.B1_LEGACY_CONTRACT_CHECKER_SHA256, "B1C1"),
            (verify.ROOT / "scripts/check_nativeq_backend_contract.py", verify.B1_NATIVEQ_CHECKER_CORE_SHA256, "NC"),
            (verify.ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v3.py", verify.B1_CONTRACT_BUILDER_SHA256, "BH3"),
            (verify.ROOT / "scripts/build_b1_klt_nativeq_current_exporter_contract_v2.py", verify.B1_V2_CONTRACT_BUILDER_SHA256, "BH2"),
            (verify.ROOT / "scripts/build_nativeq_backend_contract.py", verify.B1_LEGACY_CONTRACT_BUILDER_SHA256, "BH1"),
            (verify.ROOT / "scripts/prove_b1_klt_exporter_transition_v2.py", verify.B1_TRANSITION_PROVER_SHA256, "BP"),
            (verify.DEFAULT_B1_TRANSITION_PROOF, verify.B1_TRANSITION_PROOF_SHA256, "BPR"),
            (verify.ROOT / "scripts/tests/test_b1_klt_nativeq_current_exporter_contract_v3.py", verify.B1_V3_TESTS_SHA256, "BT"),
            (verify.DEFAULT_B1_ELIGIBILITY_MANIFEST, verify.B1_ELIGIBILITY_MANIFEST_SHA256, "DM"),
            (verify.ROOT / "uw_frontend/ros/export_vins_features.py", verify.B1_FRONTEND_EXPORTER_SHA256, "BE"),
            (verify.ROOT / "scripts/tests/test_run_hfnet_slam_a02_long1801_headless_v4.py", verify.HFNET_V4_TESTS_SHA256, "HF4T"),
        ):
            self.assertEqual(
                verify.exact_identity(path, expected, label)["sha256"], expected
            )
        linkage = verify.validate_vins_dynamic_linkage(verify.VINS_BINARY)
        self.assertEqual(linkage["status"], "PASS")
        self.assertEqual(
            linkage["resolved_libraries"]["libvins_lib.so"]["sha256"],
            verify.VINS_CORE_LIBRARY_SHA256,
        )
        self.assertEqual(
            linkage["resolved_libraries"]["libcamera_models.so"]["sha256"],
            verify.VINS_CAMERA_MODELS_LIBRARY_SHA256,
        )

    def test_live_direct_runtime_probes_are_not_dead_validators(self) -> None:
        self.assertEqual(verify.validate_xfeat_audit_runtime()["status"], "PASS")
        xfeat = verify.validate_xfeat_export_runtime()
        self.assertEqual(xfeat["status"], "PASS_FROZEN_CPU_RUNTIME")
        self.assertTrue(str(xfeat["probe"]["torch_c_file"]).endswith("torch/_C.cpython-38-x86_64-linux-gnu.so"))
        self.assertEqual(xfeat["probe"]["torch_num_threads"], 6)
        evaluation = verify.validate_evaluation_runtime()
        self.assertEqual(evaluation["status"], "PASS_FROZEN_NUMPY1244_EVO1311")
        self.assertEqual(evaluation["probe"]["rosbag_file"], "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py")
        self.assertEqual(evaluation["probe"]["evo_ape"], "/home/ma/.local/bin/evo_ape")
        self.assertEqual(
            verify.validate_b1_v4_ros_environment()["status"],
            "PASS_NOETIC_ORIGIN_ONLY_UNDER_NOUNSET",
        )

    def test_runtime_probe_or_hash_drift_is_rejected(self) -> None:
        original = verify.XFEAT_EXPORT_RUNTIME_FILES
        changed = dict(original)
        path = next(path for path in changed if "torch/_C." in path)
        size, digest = changed[path]
        changed[path] = (size, "0" * 64)
        with mock.patch.object(verify, "XFEAT_EXPORT_RUNTIME_FILES", changed):
            with self.assertRaisesRegex(verify.VerificationError, "FROZEN_SHA256"):
                verify.validate_xfeat_export_runtime()
        evaluation_changed = dict(verify.EVALUATION_RUNTIME_FILES)
        numpy_core = next(
            path for path in evaluation_changed if "_multiarray_umath." in path
        )
        size, digest = evaluation_changed[numpy_core]
        evaluation_changed[numpy_core] = (size, "0" * 64)
        with mock.patch.object(
            verify, "EVALUATION_RUNTIME_FILES", evaluation_changed
        ):
            with self.assertRaisesRegex(verify.VerificationError, "FROZEN_SHA256"):
                verify.validate_evaluation_runtime()
        completed = verify.subprocess.CompletedProcess(
            [str(verify.XFEAT_AUDIT_BASE_INTERPRETER)],
            0,
            json.dumps({"wrong": True}),
            "",
        )
        with mock.patch.object(verify.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(verify.VerificationError, "PROBE_IDENTITY"):
                verify.validate_evaluation_runtime()

    def test_authoritative_commands_bind_all_environments_and_branches(self) -> None:
        commands = verify.authoritative_commands()
        self.assertEqual(len(commands), 28)
        self.assertIn("--action check-start || exit $?", commands[0])
        self.assertIn("--action check-b1-decision || exit 42", commands[9])
        for index in (0, 1, 2, 3, 4, 7, 9, 10, 11, 12, 13, 15, 17, 20, 21, 22, 23, 24, 27):
            self.assertIn("/usr/bin/env -i", commands[index], index)
            self.assertIn("/usr/bin/python3.8", commands[index], index)
        self.assertIn("CUDA_VISIBLE_DEVICES=0", commands[14])
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", commands[14])
        self.assertIn("PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1", commands[14])
        self.assertIn("/usr/bin/mkdir", commands[10])
        self.assertIn("/usr/bin/mkdir", commands[14])
        self.assertIn("/tmp/aqua-fe-opencv-usac-v1/bin/python", commands[16])
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", commands[16])
        self.assertIn("test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1", commands[16])
        self.assertIn("ROS_DISTRO=noetic", commands[18])
        self.assertIn("ROS_MASTER_URI=http://localhost:11531", commands[18])
        self.assertIn("ROS_MASTER_URI=http://localhost:11532", commands[19])
        self.assertIn("OPENBLAS_NUM_THREADS=1", commands[27])
        self.assertNotIn("evaluate_vins_common_support.py", "\n".join(commands[:-1]))
        self.assertEqual(verify.EXPECTED_WORKING_DIRECTORY, "/home/ma/AQUA-FE_WS")
        verify.validate_frozen_command_protocol({"commands": commands})
        tampered = list(commands)
        tampered[14] = tampered[14].replace("PYTHONHASHSEED=0", "PYTHONHASHSEED=1", 1)
        with self.assertRaisesRegex(verify.VerificationError, "EXACT_MISMATCH_AT_14"):
            verify.validate_frozen_command_protocol({"commands": tampered})

    def test_scientific_nonzero_continues_but_global_gate_stops(self) -> None:
        scientific = (
            "b1_rc=0; /bin/false || b1_rc=$?; echo B1_DONE; "
            "xfeat_rc=0; /bin/false || xfeat_rc=$?; echo XFEAT_DONE; "
            "hfnet_rc=0; /bin/false || hfnet_rc=$?; echo HFNET_REACHED; exit 0"
        )
        completed = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", scientific],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("HFNET_REACHED", completed.stdout)
        stopped = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", "/bin/false || exit 42; echo EVALUATOR_REACHED"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(stopped.returncode, 42)
        self.assertNotIn("EVALUATOR_REACHED", stopped.stdout)

    def test_eval_dir_claim_failure_never_reaches_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            claimed = Path(directory) / "claimed"
            claimed.mkdir()
            marker = Path(directory) / "evaluator-called"
            with mock.patch.object(verify, "DEFAULT_EVAL_DIR", claimed):
                claim = verify.exclusive_eval_dir_claim_command()
            command = (
                f"claim_rc=0; {claim} || claim_rc=$?; "
                f"if [ \"$claim_rc\" -eq 0 ]; then /usr/bin/touch {marker}; fi; "
                "test \"$claim_rc\" -ne 0"
            )
            completed = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc", "-c", command],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())
            final = verify.expected_final_gate_command()
            self.assertLess(
                final.index(verify.exclusive_eval_dir_claim_command()),
                final.index("scripts/evaluate_vins_common_support.py"),
            )

    def test_start_gate_requires_exact_reserved_set_and_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reserved = tuple(str(root / f"reserved-{index}") for index in range(18))
            freeze = root / "freeze.json"
            freeze.write_bytes(verify.canonical_json({"reserved_paths_absent_at_freeze": list(reserved)}))
            with mock.patch.object(verify, "EXPECTED_RESERVED_PATHS", reserved), mock.patch.object(
                verify, "validate_static_freeze", return_value={"status": "PASS"}
            ):
                report = verify.validate_start_freeze(freeze)
                self.assertEqual(report["reserved_path_count"], 18)
                Path(reserved[3]).write_text("occupied", encoding="ascii")
                with self.assertRaisesRegex(verify.VerificationError, "NOT_ABSENT"):
                    verify.validate_start_freeze(freeze)
            wrong = tuple((*reserved[:-1], str(root / "wrong")))
            with mock.patch.object(verify, "EXPECTED_RESERVED_PATHS", wrong), mock.patch.object(
                verify, "validate_static_freeze", return_value={"status": "PASS"}
            ):
                with self.assertRaisesRegex(verify.VerificationError, "SET_OR_ORDER"):
                    verify.validate_start_freeze(freeze)

    def test_real_workspace_symlinks_canonicalise_evidence_paths(self) -> None:
        self.assertTrue(str(verify.DEFAULT_WINDOW_BAG.resolve(strict=False)).startswith("/mnt/data/AQUA-FE_WS/"))
        self.assertTrue(str(verify.DEFAULT_HFNET_SOURCE.resolve(strict=False)).startswith("/mnt/data/AQUA-FE_WS/"))
        raw = verify.ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
        _, raw_identity = verify.read_regular(raw, "REAL_CANONICAL_RAW_TAR")
        self.assertTrue(str(raw_identity["path"]).startswith("/mnt/data/AQUA-FE_WS/"))


if __name__ == "__main__":
    unittest.main()
