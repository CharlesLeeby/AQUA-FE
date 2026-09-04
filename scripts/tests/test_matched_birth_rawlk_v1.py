#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

from scripts import export_matched_gftt_birth_rawlk_v1 as gftt
from scripts import export_matched_xfeat_birth_rawlk_v1 as xfeat
from scripts import matched_birth_rawlk_core_v1 as matched
from scripts import export_superpoint_lk_carrier_v1 as primitive
from scripts import run_matched_birth_arm_once_v1 as launcher


class _Stamp:
    def __init__(self, ns: int):
        self._ns = ns

    def to_nsec(self) -> int:
        return self._ns


class _Header:
    def __init__(self, ns: int):
        self.stamp = _Stamp(ns)
        self.seq = 1
        self.frame_id = "camera"


class MatchedBirthCoreTests(unittest.TestCase):
    @staticmethod
    def _make_genpy_directory() -> Path:
        path = Path(tempfile.mkdtemp(prefix="genpy_", dir="/tmp"))
        path.chmod(0o700)
        descriptor, source = tempfile.mkstemp(prefix="tmp", suffix=".py", dir=path)
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, b"# generated test message\n")
        os.close(descriptor)
        return path

    def test_fresh_exact_environment_module_entry_runtime_is_strict(self) -> None:
        """Exercise the real ``-m`` startup path in a clean subprocess."""

        if dict(os.environ) == launcher.FROZEN_ENVIRONMENT:
            matched._configure_runtime()
            observed = matched._runtime_identity(strict=True)
            workspace = str(matched.WORKSPACE_ROOT)
            self.assertEqual(observed["sys_path"], matched.EXPECTED_SYS_PATH)
            self.assertEqual(observed["sys_path"][:2], [workspace, workspace])
            self.assertEqual(
                observed["pycache_prefix"], str(launcher.PYCACHE_PREFIX)
            )
            return

        self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))
        result = subprocess.run(
            [
                "/usr/bin/python3.8",
                "-B",
                "-m",
                "unittest",
                (
                    "scripts.tests.test_matched_birth_rawlk_v1."
                    "MatchedBirthCoreTests."
                    "test_fresh_exact_environment_module_entry_runtime_is_strict"
                ),
            ],
            cwd=str(matched.WORKSPACE_ROOT),
            env=dict(launcher.FROZEN_ENVIRONMENT),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("OK", result.stderr)
        self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))

    def test_real_locked_bag_reads_restore_strict_runtime(self) -> None:
        """Read locked bags in a fresh process without retaining genpy paths."""

        if dict(os.environ) != launcher.FROZEN_ENVIRONMENT:
            self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))
            result = subprocess.run(
                [
                    "/usr/bin/python3.8",
                    "-B",
                    "-m",
                    "unittest",
                    (
                        "scripts.tests.test_matched_birth_rawlk_v1."
                        "MatchedBirthCoreTests."
                        "test_real_locked_bag_reads_restore_strict_runtime"
                    ),
                ],
                cwd=str(matched.WORKSPACE_ROOT),
                env=dict(launcher.FROZEN_ENVIRONMENT),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout}\nstderr={result.stderr}",
            )
            self.assertIn("OK", result.stderr)
            self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))
            return

        source = Path(
            "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_r1/"
            "features.bag"
        )
        raw = Path(
            "/mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/"
            "archaeo02_4500_6300.bag"
        )
        self.assertTrue(source.is_file())
        self.assertTrue(raw.is_file())
        matched._configure_runtime()
        before_path = list(matched.sys.path)
        before_runtime = matched._runtime_identity(strict=True)
        schedule, total = matched._call_trusted_rosbag_scoped(
            primitive.read_source_schedule,
            source,
            matched.FEATURE_TOPIC_DEFAULT,
            16,
        )
        self.assertEqual(total, 900)
        self.assertEqual(len(schedule), 16)
        self.assertEqual(matched.sys.path, before_path)
        frames = matched._call_trusted_rosbag_scoped(
            primitive.read_raw_frames,
            raw,
            "/camera/image_raw",
            schedule[0].header_stamp_ns,
            schedule[-1].header_stamp_ns,
        )
        self.assertEqual(len(frames), 32)
        self.assertEqual(matched.sys.path, before_path)
        digest = matched._call_trusted_rosbag_scoped(
            primitive._nonfeature_digest,
            source,
            matched.FEATURE_TOPIC_DEFAULT,
            schedule[-1].record_stamp_ns,
        )
        self.assertGreater(digest["message_count"], 0)
        self.assertEqual(matched.sys.path, before_path)
        self.assertEqual(matched._runtime_identity(strict=True), before_runtime)
        self.assertFalse(os.path.lexists(launcher.PYCACHE_PREFIX))

    def test_old_frozen_sources_remain_byte_identical(self) -> None:
        expected = {
            "scripts/export_superpoint_lk_carrier_v1.py": (
                "2419fddc561c3a5bb2742aa033c62aa24d7361806a975c09c7e25ecf5995a34c"
            ),
            "scripts/export_xfeat_lk_carrier_v1.py": (
                "d7b6a698b784e0cee1c432308eb6f7546251503f0b47f4eeed9651b8fe401aba"
            ),
            "scripts/audit_superpoint_lk_carrier_v1.py": (
                "f8a6abecb6c2253d8721befaccf1e49eb6e68013b6d1376cff8dbd71f579f1d1"
            ),
            "scripts/audit_xfeat_lk_carrier_v1.py": (
                "89998cacb929b00de08eb93cc21e36e7b64434a59acb3fc1b332f16822608935"
            ),
        }
        for relative, digest in expected.items():
            self.assertEqual(matched._sha256_file(Path(relative)), digest)

    def test_truthful_provenance_only_arm_contract(self) -> None:
        xa = matched.arm_contract(xfeat.XFEAT_METHOD_SPEC)
        ga = matched.arm_contract(gftt.GFTT_METHOD_SPEC)
        self.assertEqual(xa["provenance"]["source_code"], 20)
        self.assertEqual(xa["provenance"]["is_learned"], 1)
        self.assertEqual(ga["provenance"]["source_code"], 21)
        self.assertEqual(ga["provenance"]["is_learned"], 0)
        self.assertNotEqual(xa["detector"], ga["detector"])

    def test_requested_inputs_must_use_canonical_spelling(self) -> None:
        canonical = {
            "source_feature_bag": "/mnt/data/source.bag",
            "raw_image_bag": "/mnt/data/raw.bag",
            "camera_yaml": "/mnt/data/camera.yaml",
        }
        matched._require_canonical_requested_inputs(dict(canonical), canonical)
        lexical = dict(canonical)
        lexical["source_feature_bag"] = "/home/ma/AQUA-FE_WS/logs/source.bag"
        with self.assertRaisesRegex(ValueError, "canonical resolved spellings"):
            matched._require_canonical_requested_inputs(lexical, canonical)

    def test_stolen_formal_token_rejects_noncanonical_spec(self) -> None:
        fake = matched.MatchedMethodSpec(
            arm_id=xfeat.XFEAT_METHOD_SPEC.arm_id,
            detector_family=xfeat.XFEAT_METHOD_SPEC.detector_family,
            detector_implementation_id=(
                xfeat.XFEAT_METHOD_SPEC.detector_implementation_id
            ),
            detector_contract=dict(xfeat.XFEAT_METHOD_SPEC.detector_contract),
            source_code=20,
            is_learned=1,
            detector_factory=xfeat.MatchedXFeatDetector,
            wrapper_source=xfeat.XFEAT_METHOD_SPEC.wrapper_source,
            detector_code_artifacts=xfeat.XFEAT_METHOD_SPEC.detector_code_artifacts,
        )
        with self.assertRaises(RuntimeError):
            matched._validate_formal_method_spec(fake)

    def test_canonical_formal_method_specs_pass(self) -> None:
        matched._validate_formal_method_spec(xfeat.XFEAT_METHOD_SPEC)
        matched._validate_formal_method_spec(gftt.GFTT_METHOD_SPEC)

    def test_formal_xfeat_spec_requires_package_initializer_artifact(self) -> None:
        original = xfeat.XFEAT_METHOD_SPEC.detector_code_artifacts
        object.__setattr__(
            xfeat.XFEAT_METHOD_SPEC,
            "detector_code_artifacts",
            tuple(
                item
                for item in original
                if item[0] != "xfeat_modules_initializer"
            ),
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "artifact closure drift"):
                matched._validate_formal_method_spec(xfeat.XFEAT_METHOD_SPEC)
        finally:
            object.__setattr__(
                xfeat.XFEAT_METHOD_SPEC, "detector_code_artifacts", original
            )

    def test_mutated_gftt_global_is_rejected(self) -> None:
        original = gftt.GFTT_MAX_CORNERS
        try:
            gftt.GFTT_MAX_CORNERS = 1
            with self.assertRaises(RuntimeError):
                gftt.GFTTBirthDetector()
        finally:
            gftt.GFTT_MAX_CORNERS = original

    def test_mutated_xfeat_global_is_rejected(self) -> None:
        original = xfeat.legacy_xfeat.XFEAT_TOP_K
        try:
            xfeat.legacy_xfeat.XFEAT_TOP_K = 1
            with self.assertRaises(RuntimeError):
                xfeat.MatchedXFeatDetector()
        finally:
            xfeat.legacy_xfeat.XFEAT_TOP_K = original

    def test_message_publication_diff_is_only_provenance(self) -> None:
        schedule = primitive.ScheduleFrame(_Header(10), 10, 11)
        frame = primitive.PublishedFrame(
            ids=np.asarray([0, 1], dtype=np.int64),
            pixels=np.asarray([[10, 20], [30, 40]], dtype=np.float32),
            ages=np.asarray([2, 1], dtype=np.int32),
        )
        normalized = np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=np.float64)
        velocity = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        xm = matched.build_feature_message(
            schedule, frame, normalized, velocity, source_code=20, is_learned=1
        )
        gm = matched.build_feature_message(
            schedule, frame, normalized, velocity, source_code=21, is_learned=0
        )
        self.assertEqual([c.name for c in xm.channels], list(primitive.CHANNEL_NAMES))
        for index, name in enumerate(primitive.CHANNEL_NAMES):
            if name not in matched.PROVENANCE_CHANNELS:
                self.assertEqual(xm.channels[index].values, gm.channels[index].values)
        self.assertEqual(xm.channels[11].values, [20.0, 20.0])
        self.assertEqual(gm.channels[11].values, [21.0, 21.0])
        self.assertEqual(xm.channels[12].values, [1.0, 1.0])
        self.assertEqual(gm.channels[12].values, [0.0, 0.0])

    def test_processed_pixel_diagnostics_capture_common_stream(self) -> None:
        schedule = [primitive.ScheduleFrame(_Header(3), 3, 3)]
        raw = [
            primitive.RawFrame(1, np.zeros((32, 32), np.uint8)),
            primitive.RawFrame(3, np.ones((32, 32), np.uint8)),
        ]

        class Detector:
            def detect(self, _image):
                return (
                    np.asarray([[10.0, 10.0]], np.float32),
                    np.asarray([1.0], np.float32),
                )

        def tracker(_previous, _current, points):
            return primitive.TrackResult(
                points=points.copy(),
                valid=np.ones(len(points), bool),
                fb_errors=np.zeros(len(points), np.float32),
                ncc_scores=np.ones(len(points), np.float32),
            )

        run = matched.run_carrier(
            schedule,
            raw,
            Detector(),
            tracker=tracker,
            preprocess=lambda image: (image.copy(), False),
        )
        self.assertEqual(len(run.raw_diagnostics), 2)
        first = run.raw_diagnostics[0]
        self.assertEqual(first.raw_image_sha256, first.processed_image_sha256)
        self.assertTrue(first.detector_called)
        self.assertEqual(first.slots_before_detect, 350)
        rows = [matched.asdict(row) for row in run.raw_diagnostics]
        self.assertEqual(
            matched._diagnostics_common_stream(rows),
            matched._diagnostics_common_stream(rows),
        )

    def test_inplace_detector_mutation_cannot_change_carrier_input(self) -> None:
        schedule = [primitive.ScheduleFrame(_Header(3), 3, 3)]
        raw = [
            primitive.RawFrame(1, np.zeros((32, 32), np.uint8)),
            primitive.RawFrame(3, np.ones((32, 32), np.uint8)),
        ]

        class MutatingDetector:
            def detect(self, image):
                image[:] = 255
                return (
                    np.asarray([[10.0, 10.0]], np.float32),
                    np.asarray([1.0], np.float32),
                )

        def tracker(_previous, _current, points):
            return primitive.TrackResult(
                points=points.copy(),
                valid=np.ones(len(points), bool),
                fb_errors=np.zeros(len(points), np.float32),
                ncc_scores=np.ones(len(points), np.float32),
            )

        # The detector receives a private copy; its mutation cannot affect the
        # raw/common processed image or the next LK step.
        run = matched.run_carrier(
            schedule,
            raw,
            MutatingDetector(),
            tracker=tracker,
            preprocess=lambda image: (image.copy(), False),
        )
        self.assertEqual(
            run.raw_diagnostics[0].processed_image_sha256,
            matched._array_sha256(np.zeros((32, 32), np.uint8)),
        )

    def test_gftt_detector_parameters_and_scores(self) -> None:
        image = np.zeros((64, 64), dtype=np.uint8)
        image[16:48, 16:48] = 255
        detector = gftt.GFTTBirthDetector()
        points, scores = detector.detect(image)
        self.assertGreater(len(points), 0)
        self.assertEqual(points.shape, (len(scores), 2))
        self.assertTrue(np.all(np.isfinite(scores)))
        metadata = detector.artifact_metadata()
        self.assertFalse(metadata["api"]["matcher_called"])
        contract = gftt.GFTT_METHOD_SPEC.detector_contract
        self.assertEqual(contract["max_corners"], 2048)
        self.assertEqual(contract["internal_min_distance_px"], 1.0)

    def test_xfeat_lazy_load_restores_exact_sys_path(self) -> None:
        detector = xfeat.MatchedXFeatDetector()
        sentinel_model = types.SimpleNamespace(
            kornia_available=False, lighterglue=None
        )
        fake_torch = mock.Mock()
        fake_torch.get_num_threads.return_value = 1
        fake_torch.get_num_interop_threads.return_value = 1
        fake_torch.are_deterministic_algorithms_enabled.return_value = True

        def fake_legacy_load(_self) -> None:
            _self._model = sentinel_model
            _self._device = "cpu"
            _self._torch = fake_torch
            matched.sys.path.insert(0, "/tmp/fake-xfeat-repo")

        before = list(matched.sys.path)
        prefixes = ("tqdm", "kornia")
        saved = {
            name: module for name, module in list(xfeat.sys.modules.items())
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
        }
        for name in saved:
            del xfeat.sys.modules[name]
        try:
            with mock.patch.object(
                xfeat.importlib, "import_module", return_value=fake_torch
            ), mock.patch.object(
                xfeat.legacy_xfeat.XFeatDetector, "_load", fake_legacy_load
            ), mock.patch.object(
                xfeat, "observed_torch_import_origin_contract", return_value={}
            ), mock.patch.object(
                xfeat,
                "observed_tqdm_import_contract",
                return_value=xfeat.static_tqdm_import_contract(),
            ), mock.patch.object(
                xfeat,
                "observed_xfeat_package_initializer_contract",
                return_value=xfeat.static_xfeat_package_initializer_contract(),
            ):
                detector._load()
        finally:
            xfeat.sys.modules.update(saved)
        self.assertEqual(matched.sys.path, before)
        self.assertIs(detector._model, sentinel_model)

    def test_static_torch_closure_never_constructs_or_loads_detector(self) -> None:
        with mock.patch.object(
            xfeat.MatchedXFeatDetector,
            "__init__",
            side_effect=AssertionError("detector construction is forbidden"),
        ), mock.patch.object(
            xfeat.legacy_xfeat.XFeatDetector,
            "_load",
            side_effect=AssertionError("model load is forbidden"),
        ):
            observed = xfeat.static_torch_dependency_contract()
            import_origins = xfeat.static_torch_import_origin_contract()
            package_initializer = (
                xfeat.static_xfeat_package_initializer_contract()
            )
            tqdm_contract = xfeat.static_tqdm_import_contract()
            optional_matcher = (
                xfeat.expected_optional_matcher_dependency_contract()
            )
        self.assertEqual(
            set(observed["matched_torch_binary_contract"]),
            set(xfeat.FROZEN_TORCH_BINARY_FILES),
        )
        self.assertEqual(
            set(observed["matched_torch_python_contract"]),
            set(xfeat.FROZEN_TORCH_PYTHON_FILES),
        )
        self.assertEqual(set(import_origins), set(xfeat.FROZEN_TORCH_IMPORT_MODULES))
        self.assertEqual(package_initializer["module"], "modules")
        self.assertEqual(
            package_initializer["file"]["sha256"],
            xfeat.XFEAT_MODULES_INITIALIZER_SHA256,
        )
        self.assertEqual(set(tqdm_contract), set(xfeat.FROZEN_TQDM_FILES))
        self.assertEqual(optional_matcher["official_kornia_available"], False)

    def test_shared_package_initializer_contract_is_exact_and_fail_closed(self) -> None:
        observed = matched._shared_package_initializer_contract()
        self.assertEqual(
            set(observed), set(matched.EXPECTED_SHARED_PACKAGE_INITIALIZERS)
        )
        self.assertEqual(
            observed["uw_frontend"]["file"]["sha256"],
            "44c8ccc9ab0cd7e8637b0dd005f183fb7b250a539c8b22ea6d26889a394f0934",
        )
        bad = copy.deepcopy(matched.EXPECTED_SHARED_PACKAGE_INITIALIZERS)
        bad["uw_frontend_quality"]["sha256"] = "0" * 64
        with mock.patch.object(
            matched, "EXPECTED_SHARED_PACKAGE_INITIALIZERS", bad
        ), self.assertRaisesRegex(RuntimeError, "byte identity drift"):
            matched._shared_package_initializer_contract()
        module = matched.sys.modules["uw_frontend.quality"]
        with mock.patch.object(
            matched, "_runtime_identity", return_value={}
        ):
            common = matched.common_contract(strict_runtime=False)
        self.assertEqual(
            common["implementation"]["package_initializers"], observed
        )
        with mock.patch.object(
            module, "__file__", "/tmp/poisoned-init.py"
        ), self.assertRaisesRegex(RuntimeError, "origin drift"):
            matched._shared_package_initializer_contract()
        with mock.patch.object(
            module.__spec__, "origin", "/tmp/poisoned-init.py"
        ), self.assertRaisesRegex(RuntimeError, "origin drift"):
            matched._shared_package_initializer_contract()
        with mock.patch.object(
            module.__spec__, "loader", object()
        ), self.assertRaisesRegex(RuntimeError, "loader drift"):
            matched._shared_package_initializer_contract()
        with mock.patch.object(
            module, "__path__", ["/tmp/poisoned-package"]
        ), self.assertRaisesRegex(RuntimeError, "path drift"):
            matched._shared_package_initializer_contract()

    def test_xfeat_package_initializer_origin_and_path_are_exact(self) -> None:
        repo = str(xfeat.XFEAT_MODULES_INITIALIZER.resolve(strict=True).parent.parent)
        before = list(xfeat.sys.path)
        try:
            if repo not in xfeat.sys.path:
                xfeat.sys.path.insert(0, repo)
            xfeat.importlib.import_module("modules")
        finally:
            xfeat.sys.path[:] = before
        expected = xfeat.static_xfeat_package_initializer_contract()
        self.assertEqual(
            xfeat.observed_xfeat_package_initializer_contract(), expected
        )
        module = xfeat.sys.modules["modules"]
        alternate_file = str(Path(xfeat.__file__).resolve(strict=True))
        with mock.patch.object(
            module, "__file__", alternate_file
        ), self.assertRaisesRegex(RuntimeError, "import-origin drift"):
            xfeat.observed_xfeat_package_initializer_contract()
        with mock.patch.object(
            module.__spec__, "origin", alternate_file
        ), self.assertRaisesRegex(RuntimeError, "import-origin drift"):
            xfeat.observed_xfeat_package_initializer_contract()
        with mock.patch.object(
            module.__spec__, "loader", object()
        ), self.assertRaisesRegex(RuntimeError, "import-origin drift"):
            xfeat.observed_xfeat_package_initializer_contract()
        with mock.patch.object(
            module, "__path__", ["/tmp/poisoned-modules"]
        ), self.assertRaisesRegex(RuntimeError, "import-origin drift"):
            xfeat.observed_xfeat_package_initializer_contract()
        with mock.patch.object(
            xfeat,
            "XFEAT_MODULES_INITIALIZER_SIZE",
            xfeat.XFEAT_MODULES_INITIALIZER_SIZE + 1,
        ), self.assertRaisesRegex(RuntimeError, "byte identity drift"):
            xfeat.static_xfeat_package_initializer_contract()
        with mock.patch.object(
            xfeat, "XFEAT_MODULES_INITIALIZER_SHA256", "0" * 64
        ), self.assertRaisesRegex(RuntimeError, "byte identity drift"):
            xfeat.static_xfeat_package_initializer_contract()

    def test_tqdm_import_contract_is_exact_and_rejects_drift(self) -> None:
        __import__("torch")
        observed = xfeat.observed_tqdm_import_contract()
        self.assertEqual(observed, xfeat.static_tqdm_import_contract())
        package = xfeat.sys.modules["tqdm"]
        with mock.patch.object(
            package, "__path__", ["/tmp/poisoned-tqdm"]
        ), self.assertRaisesRegex(RuntimeError, "import-origin drift"):
            xfeat.observed_tqdm_import_contract()
        bad = copy.deepcopy(xfeat.FROZEN_TQDM_FILES)
        module, relative, size, _sha = bad["tqdm_init"]
        bad["tqdm_init"] = (module, relative, size, "0" * 64)
        with mock.patch.object(
            xfeat, "FROZEN_TQDM_FILES", bad
        ), self.assertRaisesRegex(RuntimeError, "dependency drift"):
            xfeat.static_tqdm_import_contract()

    def test_xfeat_load_rejects_preloaded_optional_dependency(self) -> None:
        detector = xfeat.MatchedXFeatDetector()
        saved_tqdm = {
            name: module for name, module in list(xfeat.sys.modules.items())
            if name == "tqdm" or name.startswith("tqdm.")
        }
        for name in saved_tqdm:
            del xfeat.sys.modules[name]
        try:
            with mock.patch.dict(
                xfeat.sys.modules, {"kornia.poison": object()}
            ), self.assertRaisesRegex(RuntimeError, "kornia namespace was preloaded"):
                detector._load()
        finally:
            xfeat.sys.modules.update(saved_tqdm)

    def test_xfeat_kornia_sentinel_restores_namespace_on_exception(self) -> None:
        detector = xfeat.MatchedXFeatDetector()
        fake_torch = mock.Mock()
        prefixes = ("tqdm", "kornia")
        saved = {
            name: module for name, module in list(xfeat.sys.modules.items())
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
        }
        for name in saved:
            del xfeat.sys.modules[name]

        def failing_legacy_load(_self) -> None:
            self.assertIsNone(xfeat.sys.modules["kornia"])
            raise ValueError("synthetic model-load failure")

        try:
            with mock.patch.object(
                xfeat.importlib, "import_module", return_value=fake_torch
            ), mock.patch.object(
                xfeat.legacy_xfeat.XFeatDetector,
                "_load",
                failing_legacy_load,
            ), mock.patch.object(
                xfeat,
                "observed_tqdm_import_contract",
                return_value=xfeat.static_tqdm_import_contract(),
            ), self.assertRaisesRegex(ValueError, "synthetic model-load failure"):
                detector._load()
            self.assertFalse(
                any(
                    name == "kornia" or name.startswith("kornia.")
                    for name in xfeat.sys.modules
                )
            )
        finally:
            xfeat.sys.modules.update(saved)

    def test_live_torch_import_origins_match_pinned_files(self) -> None:
        __import__("torch")
        observed = xfeat.observed_torch_import_origin_contract()
        self.assertEqual(observed, xfeat.static_torch_import_origin_contract())
        fake = types.SimpleNamespace(
            __file__="/tmp/fake-torch.py",
            __spec__=types.SimpleNamespace(origin="/tmp/fake-torch.py"),
        )
        with mock.patch.dict(xfeat.sys.modules, {"torch": fake}):
            with self.assertRaisesRegex(RuntimeError, "import origin drift"):
                xfeat.observed_torch_import_origin_contract()

    def test_canonical_json_rejects_nan(self) -> None:
        with self.assertRaises(ValueError):
            matched._canonical_bytes({"bad": float("nan")})
        encoded = matched._canonical_bytes({"z": 1, "a": 2})
        self.assertEqual(encoded, b'{"a":2,"z":1}\n')

    def test_patch_restores_primitive_functions_on_failure(self) -> None:
        original = (
            primitive.run_carrier,
            primitive.build_feature_message,
            primitive._algorithm_contract,
            primitive.read_source_schedule,
            primitive.read_raw_frames,
            primitive._nonfeature_digest,
            primitive._write_candidate_bag,
            primitive._verify_output_schedule,
        )
        with self.assertRaises(RuntimeError):
            with matched._patched_primitive(gftt.GFTT_METHOD_SPEC, {"x": 1}):
                raise RuntimeError("boom")
        self.assertEqual(
            original,
            (
                primitive.run_carrier,
                primitive.build_feature_message,
                primitive._algorithm_contract,
                primitive.read_source_schedule,
                primitive.read_raw_frames,
                primitive._nonfeature_digest,
                primitive._write_candidate_bag,
                primitive._verify_output_schedule,
            ),
        )

    def test_trusted_rosbag_scope_accepts_only_exact_genpy_append(self) -> None:
        before_object = matched.sys.path
        before = list(before_object)
        directory = self._make_genpy_directory()
        try:
            def append_genpy() -> str:
                matched.sys.path.append(str(directory))
                return "ok"

            self.assertEqual(
                matched._call_trusted_rosbag_scoped(append_genpy), "ok"
            )
            self.assertIs(matched.sys.path, before_object)
            self.assertEqual(matched.sys.path, before)
        finally:
            shutil.rmtree(directory)

    def test_trusted_rosbag_scope_restores_before_propagating_inner_error(self) -> None:
        before_object = matched.sys.path
        before = list(before_object)
        directory = self._make_genpy_directory()
        try:
            def append_then_fail() -> None:
                matched.sys.path.append(str(directory))
                raise ValueError("inner failure")

            with self.assertRaisesRegex(ValueError, "inner failure"):
                matched._call_trusted_rosbag_scoped(append_then_fail)
            self.assertIs(matched.sys.path, before_object)
            self.assertEqual(matched.sys.path, before)
        finally:
            shutil.rmtree(directory)

    def test_trusted_rosbag_scope_rejects_and_restores_malicious_mutations(self) -> None:
        before_object = matched.sys.path
        before = list(before_object)

        def inserted_entry() -> None:
            matched.sys.path.insert(0, "/tmp/not-genpy")

        with self.assertRaisesRegex(RuntimeError, "sealed sys.path prefix"):
            matched._call_trusted_rosbag_scoped(inserted_entry)
        self.assertIs(matched.sys.path, before_object)
        self.assertEqual(matched.sys.path, before)

        def arbitrary_suffix() -> None:
            matched.sys.path.append("/tmp/not-genpy")

        with self.assertRaisesRegex(RuntimeError, "non-genpy"):
            matched._call_trusted_rosbag_scoped(arbitrary_suffix)
        self.assertIs(matched.sys.path, before_object)
        self.assertEqual(matched.sys.path, before)

        def replaced_list() -> None:
            matched.sys.path = list(before)

        with self.assertRaisesRegex(RuntimeError, "replaced the sys.path list"):
            matched._call_trusted_rosbag_scoped(replaced_list)
        self.assertIs(matched.sys.path, before_object)
        self.assertEqual(matched.sys.path, before)

    def test_trusted_rosbag_scope_rejects_wrong_genpy_filesystem_shape(self) -> None:
        before = list(matched.sys.path)
        directory = self._make_genpy_directory()
        directory.chmod(0o755)
        try:
            with self.assertRaisesRegex(RuntimeError, "filesystem contract"):
                matched._call_trusted_rosbag_scoped(
                    lambda: matched.sys.path.append(str(directory))
                )
            self.assertEqual(matched.sys.path, before)
        finally:
            shutil.rmtree(directory)

    def test_invalid_rosbag_mutation_overrides_but_chains_inner_failure(self) -> None:
        before = list(matched.sys.path)

        def mutate_then_fail() -> None:
            matched.sys.path.append("/tmp/not-genpy")
            raise ValueError("inner rosbag failure")

        with self.assertRaisesRegex(RuntimeError, "non-genpy") as caught:
            matched._call_trusted_rosbag_scoped(mutate_then_fail)
        self.assertIsInstance(caught.exception.__context__, ValueError)
        self.assertIn("inner rosbag failure", str(caught.exception.__context__))
        self.assertEqual(matched.sys.path, before)

    def test_open_owned_rejects_hardlinked_work_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            alias = root / "alias"
            work.write_bytes(b"payload")
            os.link(work, alias)
            with self.assertRaisesRegex(RuntimeError, "extra hard links"):
                matched._open_owned_existing(work)

    def test_identity_rejects_hardlinked_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            alias = root / "alias"
            source.write_bytes(b"payload")
            os.link(source, alias)
            with self.assertRaisesRegex(ValueError, "exactly one hard link"):
                matched._file_identity(source)

    def test_publish_rebinds_inode_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"payload")
            work_owned = matched._open_owned_existing(work)
            identity = matched._owned_file_identity(
                work_owned, reported_path=final
            )
            matched._publish_owned(
                work,
                final,
                ownership,
                work_ownership=work_owned,
                expected_identity=identity,
            )
            self.assertEqual(final.read_bytes(), b"payload")
            ownership[final].close()

    def test_publish_rejects_wrong_expected_work_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"payload")
            work_owned = matched._open_owned_existing(work)
            identity = matched._owned_file_identity(
                work_owned, reported_path=final
            )
            identity["sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "held work bytes drift"):
                matched._publish_owned(
                    work,
                    final,
                    ownership,
                    work_ownership=work_owned,
                    expected_identity=identity,
                )
            self.assertTrue(work.is_file())
            self.assertFalse(final.exists())
            work_owned.close()

    def test_publish_rejects_foreign_reservation_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            final.write_bytes(b"foreign")
            work.write_bytes(b"ours")
            with self.assertRaises(FileExistsError):
                matched._publish_owned(work, final, ownership)
            self.assertEqual(final.read_bytes(), b"foreign")

    def test_noreplace_publish_never_clobbers_racing_foreign_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"ours")

            def racing_writer() -> None:
                final.write_bytes(b"foreign")

            with self.assertRaises(FileExistsError):
                matched._publish_owned(
                    work,
                    final,
                    ownership,
                    before_publish_hook=racing_writer,
                )
            self.assertEqual(final.read_bytes(), b"foreign")
            self.assertEqual(work.read_bytes(), b"ours")

    def test_source_replacement_is_detected_and_cannot_report_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"ours")
            work_owned = matched._open_owned_existing(work)
            identity = matched._owned_file_identity(
                work_owned, reported_path=final
            )

            def replace_source() -> None:
                work.unlink()
                work.write_bytes(b"foreign")

            with self.assertRaisesRegex(RuntimeError, "held work inode"):
                matched._publish_owned(
                    work,
                    final,
                    ownership,
                    work_ownership=work_owned,
                    expected_identity=identity,
                    before_publish_hook=replace_source,
                )
            self.assertEqual(final.read_bytes(), b"foreign")
            ownership[final].close()

    def test_cleanup_after_publish_preserves_later_foreign_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"ours")
            matched._publish_owned(work, final, ownership)
            final.unlink()
            final.write_bytes(b"later-foreign")
            self.assertEqual(final.read_bytes(), b"later-foreign")
            ownership[final].close()

    def test_replace_to_lstat_race_never_adopts_foreign_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            work = root / "work"
            ownership = {final: None}
            work.write_bytes(b"ours")

            def replace_with_foreign() -> None:
                final.unlink()
                final.write_bytes(b"foreign-after-replace")

            with self.assertRaises(RuntimeError):
                matched._publish_owned(
                    work,
                    final,
                    ownership,
                    after_replace_hook=replace_with_foreign,
                )
            self.assertEqual(final.read_bytes(), b"foreign-after-replace")
            ownership[final].close()

    def test_runtime_observer_does_not_repair_drift(self) -> None:
        matched._configure_runtime()
        before = matched._runtime_identity(strict=False)
        cv2 = __import__("cv2")
        cv2.setNumThreads(4)
        after = matched._runtime_identity(strict=False)
        self.assertNotEqual(before["opencv_threads"], after["opencv_threads"])
        self.assertEqual(after["opencv_threads"], 4)
        matched._configure_runtime()

    def test_configure_runtime_explicitly_disables_opencl(self) -> None:
        with mock.patch.object(matched.cv2.ocl, "setUseOpenCL") as disable:
            matched._configure_runtime()
        disable.assert_called_once_with(False)

    def test_detector_runtime_cross_field_binding(self) -> None:
        rows = [
            {"detector_called": True, "detector_candidates": 7},
            {"detector_called": False, "detector_candidates": 0},
        ]
        good = {
            "detect_calls": 1,
            "candidate_total": 7,
            "input_shapes": [[480, 640]],
        }
        matched._validate_detector_runtime(good, rows)
        for key, bad_value in (("detect_calls", 2), ("candidate_total", 8)):
            bad = dict(good)
            bad[key] = bad_value
            with self.assertRaisesRegex(RuntimeError, key):
                matched._validate_detector_runtime(bad, rows)
        with self.assertRaisesRegex(RuntimeError, "input_shapes"):
            matched._validate_detector_runtime(
                {**good, "input_shapes": [[480, 640], [1, 1]]}, rows
            )

    def test_runtime_rejects_pythonpath_or_sys_path_pollution(self) -> None:
        matched._configure_runtime()
        with mock.patch.dict(
            matched.os.environ,
            {"PYTHONPATH": "/tmp/pollution:" + matched.EXPECTED_PYTHONPATH},
        ):
            observed = matched._runtime_identity(strict=False)
        self.assertTrue(
            any("PYTHONPATH" in reason for reason in observed["contract_failures"])
        )
        with mock.patch.object(matched.sys, "path", ["/tmp/pollution"] + list(matched.sys.path)):
            observed = matched._runtime_identity(strict=False)
        self.assertTrue(
            any("sys.path=" in reason for reason in observed["contract_failures"])
        )

    def test_runtime_rejects_optimized_or_randomized_python(self) -> None:
        matched._configure_runtime()
        values = {
            name: getattr(matched.sys.flags, name)
            for name in dir(matched.sys.flags)
            if not name.startswith("_")
            and not callable(getattr(matched.sys.flags, name))
        }
        values.update({"optimize": 1, "hash_randomization": 1})
        with mock.patch.object(matched.sys, "flags", types.SimpleNamespace(**values)):
            observed = matched._runtime_identity(strict=False)
        self.assertTrue(
            any("python_flags=" in reason for reason in observed["contract_failures"])
        )

    def test_private_work_directory_identity_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "work"
            path.mkdir(mode=0o700)
            path.chmod(0o700)
            info = os.lstat(path)
            identity = (int(info.st_dev), int(info.st_ino))
            matched._assert_private_work_directory(path, identity)
            with self.assertRaisesRegex(RuntimeError, "identity drift"):
                matched._assert_private_work_directory(path, (identity[0], identity[1] + 1))

    def test_detect_runtime_mutation_is_observable(self) -> None:
        schedule = [primitive.ScheduleFrame(_Header(3), 3, 3)]
        raw = [
            primitive.RawFrame(1, np.zeros((32, 32), np.uint8)),
            primitive.RawFrame(3, np.ones((32, 32), np.uint8)),
        ]
        cv2 = __import__("cv2")

        class RuntimeMutator:
            def detect(self, _image):
                cv2.setNumThreads(4)
                return (
                    np.asarray([[10.0, 10.0]], np.float32),
                    np.asarray([1.0], np.float32),
                )

        def tracker(_previous, _current, points):
            return primitive.TrackResult(
                points=points.copy(),
                valid=np.ones(len(points), bool),
                fb_errors=np.zeros(len(points), np.float32),
                ncc_scores=np.ones(len(points), np.float32),
            )

        matched._configure_runtime()
        before = matched._runtime_identity(strict=False)
        matched.run_carrier(
            schedule,
            raw,
            RuntimeMutator(),
            tracker=tracker,
            preprocess=lambda image: (image.copy(), False),
        )
        after = matched._runtime_identity(strict=False)
        self.assertNotEqual(before, after)
        self.assertEqual(after["opencv_threads"], 4)
        matched._configure_runtime()


if __name__ == "__main__":
    unittest.main()
