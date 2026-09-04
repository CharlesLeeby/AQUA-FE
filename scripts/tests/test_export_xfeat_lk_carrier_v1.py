from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import genpy
from geometry_msgs.msg import Point32
import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32, Image, Imu, PointCloud

from scripts import export_superpoint_lk_carrier_v1 as carrier
from scripts import export_xfeat_lk_carrier_v1 as xfeat


FEATURE_TOPIC = "/feature_tracker/feature"
IMAGE_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/imu"


def _time(nanoseconds: int) -> genpy.Time:
    return genpy.Time(
        nanoseconds // 1_000_000_000,
        nanoseconds % 1_000_000_000,
    )


def _image_message(stamp_ns: int, value: int) -> Image:
    message = Image()
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "cam0"
    message.height = 48
    message.width = 96
    message.encoding = "mono8"
    message.is_bigendian = 0
    message.step = 96
    message.data = bytes([value]) * (48 * 96)
    return message


def _feature_message(stamp_ns: int, seq: int) -> PointCloud:
    message = PointCloud()
    message.header.seq = seq
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "world"
    message.points = [Point32(0.0, 0.0, 1.0)]
    message.channels = [
        ChannelFloat32(name=name, values=[0.0]) for name in carrier.CHANNEL_NAMES
    ]
    return message


def _imu_message(stamp_ns: int) -> Imu:
    message = Imu()
    message.header.stamp = _time(stamp_ns)
    return message


def _identity_tracker(
    _previous: np.ndarray,
    _current: np.ndarray,
    points: np.ndarray,
) -> carrier.TrackResult:
    count = len(points)
    return carrier.TrackResult(
        points=np.asarray(points, dtype=np.float32).copy(),
        valid=np.ones((count,), dtype=bool),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
    )


def _identity_preprocess(image: np.ndarray) -> tuple[np.ndarray, bool]:
    return image.copy(), False


class FixedXFeatDetector:
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, _image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.calls += 1
        return (
            np.asarray([[20.25, 20.5]], dtype=np.float32),
            np.asarray([0.875], dtype=np.float32),
        )

    def artifact_metadata(self) -> dict[str, object]:
        return {
            "identity": (
                "official_verlab_XFeat_sparse_detectAndCompute_proposals_only"
            ),
            "injected_for_test": True,
            "detect_calls": self.calls,
        }


class XFeatDetectorContractTests(unittest.TestCase):
    def test_main_attests_the_frozen_xfeat_cli_factory_path(self) -> None:
        manifest = {
            "status": "FULL",
            "formal_eligible": True,
            "output_bag": {},
            "metrics": {},
            "runtime_profile": {},
        }
        argv = [
            "--source-feature-bag",
            "source.bag",
            "--raw-image-bag",
            "raw.bag",
            "--camera-yaml",
            "camera.yaml",
            "--output-bag",
            "output.bag",
            "--image-topic",
            IMAGE_TOPIC,
        ]
        with mock.patch.object(
            xfeat, "export_bag", return_value=manifest
        ) as export_call, mock.patch("builtins.print"):
            self.assertEqual(xfeat.main(argv), 0)
        self.assertIs(
            export_call.call_args.kwargs["_cli_production_factory_token"],
            xfeat._CLI_PRODUCTION_FACTORY_TOKEN,
        )
        self.assertNotIn("detector", export_call.call_args.kwargs)

    def test_absolute_cli_help_from_nonworkspace_without_workspace_pythonpath(
        self,
    ) -> None:
        script = Path(xfeat.__file__).resolve()
        workspace = script.parents[1]
        environment = os.environ.copy()
        pythonpath = []
        for entry in environment.get("PYTHONPATH", "").split(os.pathsep):
            if not entry:
                continue
            try:
                if Path(entry).resolve() == workspace:
                    continue
            except OSError:
                pass
            pythonpath.append(entry)
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        with tempfile.TemporaryDirectory() as foreign_cwd:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=foreign_cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("official-XFeat proposal", completed.stdout)
        self.assertIn("--source-feature-bag", completed.stdout)

    def test_method_contract_is_proposal_only_but_discloses_descriptor_compute(
        self,
    ) -> None:
        self.assertIn("needs carrier\nreplenishment", xfeat.__doc__)
        self.assertNotIn("Each preprocessed grayscale frame", xfeat.__doc__)
        contract = carrier._algorithm_contract(xfeat.XFEAT_METHOD_SPEC)
        self.assertEqual(contract["name"], "xfeat_detector_raw_frame_lk_carrier_v1")
        self.assertEqual(contract["publication"]["source_code"], 20)
        self.assertEqual(contract["xfeat"]["top_k"], 2048)
        self.assertEqual(contract["xfeat"]["detection_threshold"], 0.05)
        self.assertEqual(contract["xfeat"]["carrier_role"], "birth_proposals_only")
        self.assertIsNone(contract["xfeat"]["pairwise_matcher"])
        self.assertFalse(contract["xfeat"]["matcher_called"])
        self.assertFalse(contract["xfeat"]["descriptor_computation_skipped"])
        self.assertIn("64-D descriptors", contract["xfeat"]["descriptor_policy"])
        self.assertIn("multiples of 32", contract["xfeat"]["internal_size_mapping"])
        self.assertEqual(
            contract["xfeat"]["literature_frozen_input"],
            "single_channel_mono_divided_by_255",
        )
        self.assertIn(
            "averages channels",
            contract["xfeat"]["official_tensor_path_compatibility"],
        )
        self.assertNotIn("superpoint", contract)

    def test_loader_uses_only_pinned_official_modules_and_constructor(self) -> None:
        model = SimpleNamespace(dev="cpu")
        constructor = mock.Mock(return_value=model)
        modules = {
            "torch": SimpleNamespace(__version__="test", cuda=SimpleNamespace()),
            "modules.xfeat": SimpleNamespace(
                __file__=str(xfeat.XFEAT_SOURCE), XFeat=constructor
            ),
            "modules.model": SimpleNamespace(__file__=str(xfeat.XFEAT_MODEL_SOURCE)),
            "modules.interpolator": SimpleNamespace(
                __file__=str(xfeat.XFEAT_INTERPOLATOR_SOURCE)
            ),
        }
        detector = xfeat.XFeatDetector()
        with mock.patch.object(
            xfeat, "_validate_runtime_closure", return_value={}
        ), mock.patch.object(
            xfeat, "_repository_metadata", return_value={"commit": "test"}
        ), mock.patch.object(
            xfeat.importlib,
            "import_module",
            side_effect=lambda name: modules[name],
        ):
            detector._load()
        constructor.assert_called_once_with(
            weights=str(xfeat.XFEAT_WEIGHT.resolve()),
            top_k=2048,
            detection_threshold=0.05,
        )
        self.assertEqual(
            detector._imported_module_paths,
            {
                "modules.xfeat": str(xfeat.XFEAT_SOURCE.resolve()),
                "modules.model": str(xfeat.XFEAT_MODEL_SOURCE.resolve()),
                "modules.interpolator": str(
                    xfeat.XFEAT_INTERPOLATOR_SOURCE.resolve()
                ),
            },
        )

    def test_namespace_pollution_fails_before_model_construction(self) -> None:
        constructor = mock.Mock()
        modules = {
            "torch": SimpleNamespace(),
            "modules.xfeat": SimpleNamespace(
                __file__="/tmp/unrelated/modules/xfeat.py", XFeat=constructor
            ),
            "modules.model": SimpleNamespace(__file__=str(xfeat.XFEAT_MODEL_SOURCE)),
            "modules.interpolator": SimpleNamespace(
                __file__=str(xfeat.XFEAT_INTERPOLATOR_SOURCE)
            ),
        }
        detector = xfeat.XFeatDetector()
        with mock.patch.object(
            xfeat, "_validate_runtime_closure", return_value={}
        ), mock.patch.object(
            xfeat, "_repository_metadata", return_value={"commit": "test"}
        ), mock.patch.object(
            xfeat.importlib,
            "import_module",
            side_effect=lambda name: modules[name],
        ):
            with self.assertRaisesRegex(RuntimeError, "namespace pollution"):
                detector._load()
        constructor.assert_not_called()

    def test_detect_preserves_official_coordinates_scores_and_profiles_warmup(
        self,
    ) -> None:
        import torch

        class FakeModel:
            dev = torch.device("cpu")

            def __init__(self) -> None:
                self.inputs = []
                self.match = mock.Mock(side_effect=AssertionError("matcher called"))

            def detectAndCompute(self, tensor, top_k=None):
                self.inputs.append((tensor.clone(), top_k))
                return [
                    {
                        "keypoints": torch.tensor(
                            [[11.25, 7.5], [29.0, 15.125]], dtype=torch.float32
                        ),
                        "scores": torch.tensor([0.375, 0.9375], dtype=torch.float32),
                        "descriptors": torch.ones((2, 64), dtype=torch.float32),
                    }
                ]

        model = FakeModel()
        detector = xfeat.XFeatDetector()
        detector._torch = torch
        detector._model = model
        detector._device = "cpu"
        detector._closure_metadata = {
            "LICENSE": {"path": "LICENSE", "size_bytes": 1, "sha256": "0" * 64}
        }
        detector._repository_metadata = {"commit": "test", "dirty": False}
        detector._imported_module_paths = {
            "modules.xfeat": str(xfeat.XFEAT_SOURCE)
        }
        gray = np.asarray([[0, 64, 255], [32, 128, 192]], dtype=np.uint8)
        with mock.patch.object(
            xfeat.time,
            "perf_counter",
            side_effect=[1.0, 1.010, 2.0, 2.020],
        ):
            points1, scores1 = detector.detect(gray)
            points2, scores2 = detector.detect(gray)

        expected_points = np.asarray(
            [[11.25, 7.5], [29.0, 15.125]], dtype=np.float32
        )
        expected_scores = np.asarray([0.375, 0.9375], dtype=np.float32)
        np.testing.assert_array_equal(points1, expected_points)
        np.testing.assert_array_equal(points2, expected_points)
        np.testing.assert_array_equal(scores1, expected_scores)
        np.testing.assert_array_equal(scores2, expected_scores)
        self.assertEqual([top_k for _tensor, top_k in model.inputs], [2048, 2048])
        for tensor, _top_k in model.inputs:
            self.assertEqual(tuple(tensor.shape), (1, 3, 2, 3))
            np.testing.assert_allclose(
                tensor[0, 0].numpy(), gray.astype(np.float32) / 255.0
            )
            np.testing.assert_array_equal(tensor[0, 0], tensor[0, 1])
            np.testing.assert_array_equal(tensor[0, 1], tensor[0, 2])
        model.match.assert_not_called()

        metadata = detector.artifact_metadata()
        runtime = metadata["runtime"]
        self.assertEqual(runtime["detect_calls"], 2)
        self.assertEqual(runtime["gray_input_shapes_hw"], [[2, 3]])
        self.assertEqual(runtime["rgb_tensor_input_shapes_bchw"], [[1, 3, 2, 3]])
        self.assertEqual(runtime["detect_ms"]["warmup"]["count"], 1)
        self.assertEqual(runtime["detect_ms"]["steady_state"]["count"], 1)
        self.assertAlmostEqual(
            runtime["detect_ms"]["warmup"]["median_ms"], 10.0
        )
        self.assertAlmostEqual(
            runtime["detect_ms"]["steady_state"]["p90_ms"], 20.0
        )
        self.assertAlmostEqual(runtime["detect_ms"]["all"]["total_ms"], 30.0)
        self.assertFalse(metadata["api"]["matcher_called"])
        self.assertIn("computes 64-D descriptors", metadata["api"]["descriptor_computation"])

    def test_pinned_closure_weight_commit_license_and_mode_only_caveat(self) -> None:
        closure = xfeat._validate_runtime_closure()
        self.assertEqual(set(closure), set(xfeat.XFEAT_CLOSURE))
        self.assertEqual(closure["xfeat.pt"]["size_bytes"], 6_247_949)
        self.assertEqual(
            closure["xfeat.pt"]["sha256"],
            "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b",
        )
        self.assertEqual(
            closure["xfeat.py"]["sha256"],
            "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7",
        )
        repository = xfeat._repository_metadata()
        self.assertEqual(repository["commit"], xfeat.XFEAT_EXPECTED_COMMIT)
        self.assertEqual(repository["license_spdx"], "Apache-2.0")
        self.assertTrue(repository["dirty"])
        self.assertEqual(repository["dirty_classification"], "mode_bits_only")
        self.assertIn("mode bits only", repository["content_identity_caveat"])

        detector = xfeat.XFeatDetector()
        detector._torch = SimpleNamespace(__version__="test")
        detector._model = object()
        detector._device = "cpu"
        detector._closure_metadata = closure
        detector._repository_metadata = repository
        metadata = detector.artifact_metadata()
        self.assertEqual(metadata["repository"]["commit"], xfeat.XFEAT_EXPECTED_COMMIT)
        self.assertEqual(metadata["repository"]["dirty_classification"], "mode_bits_only")
        self.assertEqual(metadata["license"]["spdx"], "Apache-2.0")
        self.assertEqual(
            metadata["closure"]["model.py"]["sha256"],
            "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964",
        )
        self.assertEqual(
            metadata["closure"]["interpolator.py"]["sha256"],
            "d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da",
        )

    def test_weight_validation_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "xfeat.pt"
            wrong.write_bytes(b"wrong")
            closure = {
                "xfeat.pt": {
                    "path": wrong,
                    "size_bytes": 6_247_949,
                    "sha256": (
                        "0f5187fd7bedd26c7fe6acc9685444493"
                        "a165a35ecc087b33c2db3627f3ea10b"
                    ),
                }
            }
            with mock.patch.object(xfeat, "XFEAT_CLOSURE", closure):
                with self.assertRaisesRegex(RuntimeError, "size mismatch"):
                    xfeat._validate_runtime_closure()

    def test_content_plus_mode_change_cannot_be_misclassified_as_mode_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    ["git", "-C", str(repo), *arguments],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed.stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Unit Test")
            git("config", "user.email", "unit@test.invalid")
            git("config", "core.filemode", "true")
            tracked = repo / "tracked.txt"
            tracked.write_text("original\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-q", "-m", "fixture")
            commit = git("rev-parse", "HEAD")
            tracked.chmod(0o755)
            tracked.write_text("content changed too\n", encoding="utf-8")

            # ``git diff --summary`` reports the mode change even when content
            # also changed.  Classification must use blob equality, not that
            # summary alone.
            self.assertIn("mode change", git("diff", "--summary"))
            with mock.patch.object(xfeat, "XFEAT_REPO", repo), mock.patch.object(
                xfeat, "XFEAT_EXPECTED_COMMIT", commit
            ):
                metadata = xfeat._repository_metadata()
        self.assertTrue(metadata["dirty"])
        self.assertEqual(
            metadata["dirty_classification"],
            "content_or_index_or_untracked_changes",
        )
        proof = metadata["dirty_path_content_and_mode_proofs"][0]
        self.assertTrue(proof["mode_changed"])
        self.assertFalse(proof["bytes_equal_to_index"])
        self.assertFalse(proof["proved_mode_only"])


class XFeatSyntheticManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.bag"
        self.raw = self.root / "raw.bag"
        self.camera = self.root / "camera.yaml"
        self.raw_stamps = [1_000_000_000 + index * 10_000_000 for index in range(4)]
        with rosbag.Bag(str(self.source), "w") as bag:
            bag.write(IMU_TOPIC, _imu_message(self.raw_stamps[0]), _time(self.raw_stamps[0]))
            for seq, stamp_ns in enumerate(self.raw_stamps[1::2]):
                bag.write(
                    FEATURE_TOPIC,
                    _feature_message(stamp_ns, seq),
                    _time(stamp_ns),
                )
        with rosbag.Bag(str(self.raw), "w") as bag:
            for index, stamp_ns in enumerate(self.raw_stamps):
                bag.write(
                    IMAGE_TOPIC,
                    _image_message(stamp_ns, index),
                    _time(stamp_ns),
                )
        self.camera.write_text(
            "model_type: PINHOLE\n"
            "projection_parameters:\n"
            "  fx: 100.0\n  fy: 100.0\n  cx: 0.0\n  cy: 0.0\n"
            "distortion_parameters:\n"
            "  k1: 0.0\n  k2: 0.0\n  p1: 0.0\n  p2: 0.0\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_manifest_identity_hashes_schema_source20_and_wrapper_wall(self) -> None:
        output = self.root / "xfeat.bag"
        manifest_path = self.root / "xfeat.json"
        detector = FixedXFeatDetector()
        manifest = xfeat.export_bag(
            self.source,
            self.raw,
            self.camera,
            output,
            image_topic=IMAGE_TOPIC,
            feature_topic=FEATURE_TOPIC,
            manifest_json=manifest_path,
            detector=detector,
            tracker=_identity_tracker,
            preprocess=_identity_preprocess,
        )
        self.assertEqual(manifest["schema_version"], "xfeat-lk-carrier-export-v1")
        self.assertFalse(manifest["formal_eligible"])
        self.assertEqual(
            manifest["detector_origin"], "python_api_injected_detector"
        )
        self.assertEqual(
            manifest["formal_eligibility_reason"],
            "python_api_injected_detector_is_nonformal",
        )
        self.assertEqual(
            manifest["algorithm"]["name"],
            "xfeat_detector_raw_frame_lk_carrier_v1",
        )
        self.assertEqual(manifest["algorithm"]["publication"]["source_code"], 20)
        self.assertIn("xfeat", manifest["algorithm"])
        self.assertNotIn("superpoint", manifest["algorithm"])
        artifacts = manifest["code_artifacts"]
        self.assertEqual(
            Path(artifacts["exporter"]["path"]), Path(xfeat.__file__).resolve()
        )
        self.assertEqual(
            Path(artifacts["carrier_base"]["path"]), Path(carrier.__file__).resolve()
        )
        for name in (
            "xfeat_source",
            "xfeat_model_source",
            "xfeat_interpolator_source",
            "xfeat_weight",
            "xfeat_license",
        ):
            self.assertEqual(len(artifacts[name]["sha256"]), 64)
        self.assertEqual(
            artifacts["detector"]["identity"],
            "official_verlab_XFeat_sparse_detectAndCompute_proposals_only",
        )
        self.assertTrue(manifest["runtime_profile"]["component_profiler"])
        self.assertGreaterEqual(manifest["runtime_profile"]["profiled_wall_ms"], 0.0)
        stages = manifest["runtime_profile"]["stages"]
        self.assertEqual(set(stages), {"preprocess", "detect", "lk", "bag_io"})
        self.assertEqual(stages["preprocess"]["count"], 4)
        self.assertEqual(stages["detect"]["count"], 4)
        self.assertEqual(stages["lk"]["count"], 3)
        self.assertGreaterEqual(stages["bag_io"]["count"], 9)
        for stage in stages.values():
            self.assertGreaterEqual(stage["total_ms"], 0.0)
        self.assertTrue(
            any(
                "first sample includes lazy model loading" in note
                for note in manifest["runtime_profile"]["notes"]
            )
        )
        self.assertIn(
            "whole-file SHA256 reads of the source and raw bags",
            manifest["runtime_profile"]["scope"],
        )
        self.assertTrue(
            any(
                "must not be interpreted as per-frame I/O" in note
                for note in manifest["runtime_profile"]["notes"]
            )
        )
        self.assertEqual(
            json.loads(manifest_path.read_text(encoding="utf-8"))["schema_version"],
            "xfeat-lk-carrier-export-v1",
        )
        with rosbag.Bag(str(output), "r") as bag:
            features = list(bag.read_messages(topics=[FEATURE_TOPIC]))
        self.assertEqual(len(features), 2)
        for _topic, message, _stamp in features:
            channels = {channel.name: list(channel.values) for channel in message.channels}
            self.assertEqual(channels["source_code"], [20.0])
            self.assertEqual(channels["quality"], [1.0])
            self.assertEqual(channels["sigma"], [1.0])
            self.assertEqual(channels["is_learned"], [1.0])

    def test_xfeat_cli_factory_provenance_is_formal_but_api_factory_is_not(self) -> None:
        cli_detector = FixedXFeatDetector()
        with mock.patch.object(xfeat, "XFeatDetector", return_value=cli_detector):
            cli_manifest = xfeat.export_bag(
                self.source,
                self.raw,
                self.camera,
                self.root / "cli-factory.bag",
                image_topic=IMAGE_TOPIC,
                tracker=_identity_tracker,
                preprocess=_identity_preprocess,
                _cli_production_factory_token=xfeat._CLI_PRODUCTION_FACTORY_TOKEN,
            )
        self.assertTrue(cli_manifest["formal_eligible"])
        self.assertEqual(cli_manifest["detector_origin"], "cli_production_factory")

        api_detector = FixedXFeatDetector()
        with mock.patch.object(xfeat, "XFeatDetector", return_value=api_detector):
            api_manifest = xfeat.export_bag(
                self.source,
                self.raw,
                self.camera,
                self.root / "api-factory.bag",
                image_topic=IMAGE_TOPIC,
                tracker=_identity_tracker,
                preprocess=_identity_preprocess,
            )
        self.assertFalse(api_manifest["formal_eligible"])
        self.assertEqual(
            api_manifest["detector_origin"], "python_api_production_factory"
        )

    def test_export_api_cannot_override_xfeat_schema_or_source(self) -> None:
        common = (
            self.source,
            self.raw,
            self.camera,
            self.root / "unused.bag",
        )
        with self.assertRaisesRegex(TypeError, "method_spec"):
            xfeat.export_bag(
                *common,
                image_topic=IMAGE_TOPIC,
                method_spec=carrier.SUPERPOINT_METHOD_SPEC,
            )
        with self.assertRaisesRegex(TypeError, "source_code"):
            xfeat.export_bag(
                *common,
                image_topic=IMAGE_TOPIC,
                source_code=10,
            )

    def test_existing_output_is_not_clobbered_or_used_to_load_detector(self) -> None:
        output = self.root / "exists.bag"
        output.write_bytes(b"sentinel")
        detector = FixedXFeatDetector()
        with self.assertRaises(FileExistsError):
            xfeat.export_bag(
                self.source,
                self.raw,
                self.camera,
                output,
                image_topic=IMAGE_TOPIC,
                detector=detector,
                tracker=_identity_tracker,
                preprocess=_identity_preprocess,
            )
        self.assertEqual(output.read_bytes(), b"sentinel")
        self.assertEqual(detector.calls, 0)
        self.assertFalse((self.root / "exists.bag.manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
