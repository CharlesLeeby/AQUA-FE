from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Mapping, Optional, Sequence
from unittest import mock

from scripts.run_hfnet_rt_one_image_smoke_v1 import (
    BUILD_SCHEMA_VERSION,
    DEFAULT_HARNESS_SOURCE,
    DEFAULT_INPUT_IMAGE,
    DEFAULT_MODEL_DIRECTORY,
    DEFAULT_ONNX_MODEL,
    EXECUTION_COMMIT,
    EXECUTION_TREE,
    EXPECTED_IMAGE_IDENTITY,
    EXPECTED_IMAGE_PNG,
    EXPECTED_ONNX_IDENTITY,
    FEATURES,
    LEVELS,
    RAW_SCHEMA_VERSION,
    RC_CONTRACT_BLOCKED,
    RC_EXECUTION_FAILED,
    RC_PASS,
    RUNTIME_REQUIRED_RELATIVE,
    SCALE_FACTOR,
    SCHEMA_VERSION,
    THRESHOLD,
    CommandResult,
    SmokeContract,
    canonical_json,
    main,
    run_smoke,
)


def _identity(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _write_grayscale_png(path: Path, width: int = 968, height: int = 608) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes(width) for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def _success_raw(keypoints: int = 321) -> dict[str, object]:
    return {
        "detect_output": {
            "global_descriptor_cols": 1,
            "global_descriptor_rows": 4096,
            "keypoint_count": keypoints,
            "local_descriptor_cols": 256,
            "local_descriptor_rows": keypoints,
        },
        "fixed_parameters": {
            "features": FEATURES,
            "levels": LEVELS,
            "scale_factor": SCALE_FACTOR,
            "threshold": THRESHOLD,
        },
        "frontend_invocations": 1,
        "official_level_detect_invocations": 4,
        "ok": True,
        "schema_version": RAW_SCHEMA_VERSION,
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.official = root / "official"
        self.official_library = self.official / "lib/libHFNet_SLAM.so"
        self.runtime = root / "runtime"
        self.pangolin = root / "pangolin"
        self.model = root / "model/HFNet-RT"
        self.onnx = self.model / "HF-Net.onnx"
        self.cache = self.model / "HF-Net.cache"
        self.image = root / "prefix/mav0/cam0/data/frame0.png"
        self.harness_source = root / "project/hfnet_smoke.cc"
        self.build = root / "project/build/hfnet_smoke"
        self.harness = self.build / "hfnet_rt_one_image_smoke_v1"
        self.build_manifest = self.build / "build_manifest.json"
        self.output_root = root / "logs/model_smokes"

        self.official_library.parent.mkdir(parents=True)
        self.official_library.write_bytes(b"\x7fELFofficial-library")
        self.model.mkdir(parents=True)
        self.onnx.write_bytes(b"verified synthetic onnx")
        self.image.parent.mkdir(parents=True)
        _write_grayscale_png(self.image)
        self.harness_source.parent.mkdir(parents=True)
        self.harness_source.write_text("synthetic harness source\n", encoding="utf-8")
        self.build.mkdir(parents=True)
        self.harness.write_bytes(b"\x7fELFsynthetic-harness")
        self.harness.chmod(0o555)
        self.output_root.mkdir(parents=True)

        self.source_hashes: dict[str, str] = {}
        for index, relative in enumerate(
            (
                "CMakeLists.txt",
                "include/Extractors/BaseModel.h",
                "include/Extractors/HFNetRTModel.h",
                "include/Extractors/HFextractor.h",
                "src/Extractors/BaseModel.cc",
                "src/Extractors/HFNetRTModel.cc",
                "src/Extractors/HFextractor.cc",
            )
        ):
            path = self.official / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"official fixture {index}\n", encoding="utf-8")
            self.source_hashes[relative] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()

        self.runtime_libraries = {
            "libnvinfer.so.8": self.runtime
            / "usr/lib/x86_64-linux-gnu/libnvinfer.so.8.5.1",
            "libnvonnxparser.so.8": self.runtime
            / "usr/lib/x86_64-linux-gnu/libnvonnxparser.so.8.5.1",
            "libcudart.so.11.0": self.runtime
            / "usr/local/cuda-11.6/lib64/libcudart.so.11.0",
            "libpango_core.so": self.pangolin / "lib/libpango_core.so",
            "libpango-1.0.so.0": self.root / "system/lib/libpango-1.0.so.0",
            "libg2o.so": self.official / "Thirdparty/g2o/lib/libg2o.so",
        }
        for path in self.runtime_libraries.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture runtime library")
        for relative in RUNTIME_REQUIRED_RELATIVE:
            path = self.runtime / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(b"fixture required runtime artifact")

        manifest = {
            "binary": _identity(self.harness),
            "build_script": {
                "path": "/fixture/build.sh",
                "sha256": "a" * 64,
                "size_bytes": 1,
            },
            "compiler": {
                "path": "/usr/bin/g++",
                "version_first_line": "fixture compiler",
            },
            "compile_contract": {
                "defines": ["NDEBUG", "USE_TENSORRT"],
                "direct_shared_library": "libHFNet_SLAM.so",
                "language_standard": "c++14",
                "optimization": "O2",
            },
            "harness_source": _identity(self.harness_source),
            "official_library": _identity(self.official_library),
            "official_source": {
                "commit": EXECUTION_COMMIT,
                "files": {
                    relative: _identity(self.official / relative)
                    for relative in self.source_hashes
                },
                "root": str(self.official),
                "tree": EXECUTION_TREE,
                "tracked_worktree_clean": True,
            },
            "runtime_roots": {
                "isolated_cuda_tensorrt": str(self.runtime),
                "pangolin": str(self.pangolin),
            },
            "schema_version": BUILD_SCHEMA_VERSION,
        }
        self.build_manifest.write_text(
            canonical_json(manifest), encoding="utf-8"
        )

        self.contract = SmokeContract(
            official_root=self.official,
            official_library=self.official_library,
            runtime_root=self.runtime,
            pangolin_root=self.pangolin,
            model_directory=self.model,
            onnx_model=self.onnx,
            model_cache=self.cache,
            input_image=self.image,
            harness_source=self.harness_source,
            harness_binary=self.harness,
            build_manifest=self.build_manifest,
            allowed_output_root=self.output_root,
            expected_image={
                "size_bytes": self.image.stat().st_size,
                "sha256": hashlib.sha256(self.image.read_bytes()).hexdigest(),
            },
            expected_onnx={
                "size_bytes": self.onnx.stat().st_size,
                "sha256": hashlib.sha256(self.onnx.read_bytes()).hexdigest(),
            },
            expected_png={
                "bit_depth": 8,
                "color_type": 0,
                "height": 608,
                "width": 968,
            },
            expected_source_sha256=self.source_hashes,
        )

    def ldd_output(self) -> str:
        lines = [
            f"libHFNet_SLAM.so => {self.official_library} (0x1)",
        ]
        lines.extend(
            f"{name} => {path} (0x2)"
            for name, path in self.runtime_libraries.items()
        )
        return "\n".join(lines) + "\n"


class FakeProbe:
    def __init__(self, fixture: Fixture, *, dirty: bool = False) -> None:
        self.fixture = fixture
        self.dirty = dirty
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[Optional[Mapping[str, str]]] = []

    def __call__(
        self,
        command: Sequence[str],
        environment: Optional[Mapping[str, str]],
        cwd: Optional[Path],
    ) -> CommandResult:
        del cwd
        values = tuple(command)
        self.commands.append(values)
        self.environments.append(environment)
        if values[0] == "git":
            operation = values[3:]
            if operation == ("rev-parse", "HEAD^{commit}"):
                return CommandResult(0, EXECUTION_COMMIT + "\n", "")
            if operation == ("rev-parse", "HEAD^{tree}"):
                return CommandResult(0, EXECUTION_TREE + "\n", "")
            if operation == (
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ):
                return CommandResult(0, " M src/Tracking.cc\n" if self.dirty else "", "")
        if values[0] == "readelf":
            return CommandResult(
                0,
                " 0x0000000000000001 (NEEDED)             Shared library: [libHFNet_SLAM.so]\n",
                "",
            )
        if values[0] == "ldd":
            return CommandResult(0, self.fixture.ldd_output(), "")
        if values[0] == "nvidia-smi":
            return CommandResult(
                0,
                "0, NVIDIA GeForce GTX 1650, GPU-fixture, 535.183.01, 4096\n",
                "",
            )
        return CommandResult(99, "", "unexpected synthetic command")


class FakeExecute:
    def __init__(
        self,
        fixture: Fixture,
        *,
        returncode: int = 0,
        create_cache: bool = True,
        raw: object | None = None,
        mutate_input: bool = False,
    ) -> None:
        self.fixture = fixture
        self.returncode = returncode
        self.create_cache = create_cache
        self.raw = _success_raw() if raw is None else raw
        self.mutate_input = mutate_input
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        environment: Mapping[str, str],
        cwd: Optional[Path],
        timeout_seconds: int,
    ) -> CommandResult:
        del cwd
        values = tuple(command)
        self.calls.append(values)
        self.last_environment = dict(environment)
        self.last_timeout = timeout_seconds
        if self.create_cache:
            self.fixture.cache.write_bytes(b"synthetic GTX-1650 timing cache")
        if self.raw is not False:
            Path(values[3]).write_text(
                canonical_json(self.raw), encoding="utf-8"
            )
        if self.mutate_input:
            self.fixture.image.write_bytes(self.fixture.image.read_bytes() + b"drift")
        return CommandResult(
            self.returncode,
            "synthetic official stdout\n",
            "synthetic official stderr\n",
        )


class HFNetRTOneImageSmokeV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def run_fixture(
        self,
        name: str,
        *,
        probe: FakeProbe | None = None,
        execute: FakeExecute | None = None,
    ) -> tuple[dict[str, object], FakeExecute, Path]:
        output = self.fixture.output_root / name
        executor = execute or FakeExecute(self.fixture)
        decision = run_smoke(
            contract=self.fixture.contract,
            output_directory=output,
            probe_runner=probe or FakeProbe(self.fixture),
            execute_runner=executor,
            clock=lambda: "2026-08-11T00:00:00Z",
        )
        return decision, executor, output

    def test_default_contract_freezes_real_a02_image_and_verified_onnx(self) -> None:
        self.assertEqual(DEFAULT_MODEL_DIRECTORY.name, "HFNet-RT")
        self.assertEqual(DEFAULT_ONNX_MODEL.name, "HF-Net.onnx")
        self.assertEqual(
            DEFAULT_INPUT_IMAGE.name, "1542829016700435392.png"
        )
        self.assertEqual(
            EXPECTED_IMAGE_IDENTITY["sha256"],
            "4e325724a707046af87f9290c1da9fda32f74885532046b497b008f1b853f95a",
        )
        self.assertEqual(EXPECTED_IMAGE_PNG["width"], 968)
        self.assertEqual(EXPECTED_IMAGE_PNG["height"], 608)
        self.assertEqual(
            EXPECTED_ONNX_IDENTITY["sha256"],
            "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
        )
        self.assertEqual(EXECUTION_COMMIT, "c354c72588a97bb6f6a9c7c8317530795956ec80")
        self.assertEqual(EXECUTION_TREE, "6619814aed4cd0e4baa2501341a48f753f8ba196")

    def test_harness_is_minimal_and_has_no_random_gui_or_algorithm_copy(self) -> None:
        source = DEFAULT_HARNESS_SOURCE.read_text(encoding="utf-8")
        self.assertIn("ORB_SLAM3::InitAllModels", source)
        self.assertIn("ORB_SLAM3::kHFNetRTModel", source)
        self.assertIn("ORB_SLAM3::HFextractor extractor", source)
        self.assertEqual(source.count("extractor(image, keypoints"), 1)
        self.assertIn("constexpr int kLevels = 4", source)
        self.assertIn("constexpr int kFeatures = 675", source)
        for forbidden in (
            "imshow(",
            "waitKey(",
            "default_random_engine",
            "uniform_int_distribution",
            "getchar(",
            "VideoCapture",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("GetLocalFeaturesFromTensor", source)
        self.assertNotIn("ResamplerRT", source)

    def test_build_and_probe_gates_are_locale_stable_and_tracked_only(self) -> None:
        build_script = (
            DEFAULT_HARNESS_SOURCE.parents[1]
            / "build_hfnet_rt_one_image_smoke_v1.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("export LC_ALL=C", build_script)
        self.assertIn("readelf -dW", build_script)
        self.assertIn("diff --quiet --", build_script)
        self.assertNotIn("--untracked-files=all", build_script)

        probe = FakeProbe(self.fixture)
        decision, _, _ = self.run_fixture("locale_tracked", probe=probe)
        self.assertEqual(decision["return_code"], RC_PASS)
        status_commands = [
            command for command in probe.commands if "--porcelain=v1" in command
        ]
        self.assertTrue(status_commands)
        self.assertTrue(
            all("--untracked-files=no" in command for command in status_commands)
        )
        readelf_index = next(
            index
            for index, command in enumerate(probe.commands)
            if command and command[0] == "readelf"
        )
        self.assertEqual(probe.environments[readelf_index]["LC_ALL"], "C")  # type: ignore[index]
        self.assertIn("libpango-1.0.so.0", self.fixture.ldd_output())

    def test_synthetic_success_is_rc0_and_preserves_complete_artifacts(self) -> None:
        decision, executor, output = self.run_fixture("success")
        self.assertEqual(decision["status"], "PASS_MODEL_DETECT_SMOKE")
        self.assertEqual(decision["return_code"], RC_PASS)
        self.assertFalse(decision["evaluable"])
        self.assertFalse(decision["trajectory_generated"])
        self.assertEqual(len(executor.calls), 1)
        command = executor.calls[0]
        self.assertEqual(Path(command[1]), self.fixture.image.resolve())
        self.assertEqual(Path(command[2]), self.fixture.model.resolve())
        self.assertEqual(executor.last_environment["CUDA_VISIBLE_DEVICES"], "0")
        self.assertTrue((output / "result.json").is_file())
        self.assertTrue((output / "raw_harness_result.json").is_file())
        self.assertTrue((output / "HF-Net.cache").is_file())
        self.assertEqual(
            hashlib.sha256((output / "HF-Net.cache").read_bytes()).hexdigest(),
            hashlib.sha256(self.fixture.cache.read_bytes()).hexdigest(),
        )
        result_text = (output / "result.json").read_text(encoding="utf-8")
        self.assertEqual(result_text, canonical_json(json.loads(result_text)))
        self.assertEqual(json.loads(result_text)["schema_version"], SCHEMA_VERSION)
        self.assertIn("official_library", decision["hashes"])
        self.assertIn("official_source_files", decision["hashes"])

    def test_existing_output_is_rc2_and_never_touched_or_executed(self) -> None:
        output = self.fixture.output_root / "existing"
        output.mkdir()
        sentinel = output / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        executor = FakeExecute(self.fixture)
        decision = run_smoke(
            contract=self.fixture.contract,
            output_directory=output,
            probe_runner=FakeProbe(self.fixture),
            execute_runner=executor,
            clock=lambda: "2026-08-11T00:00:00Z",
        )
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(decision["status"], "NO_CLOBBER_BLOCKED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(sorted(path.name for path in output.iterdir()), ["sentinel"])

    def test_preexisting_cache_is_rc2_and_execution_never_starts(self) -> None:
        self.fixture.cache.write_bytes(b"foreign or prior cache")
        decision, executor, output = self.run_fixture("cache_block")
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(decision["status"], "CONTRACT_BLOCKED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.fixture.cache.read_bytes(), b"foreign or prior cache")
        self.assertTrue((output / "result.json").is_file())
        self.assertIn("onnx_only_model_directory", decision["failures"])

    def test_input_hash_drift_is_rc2_before_execution(self) -> None:
        self.fixture.image.write_bytes(self.fixture.image.read_bytes() + b"drift")
        decision, executor, _ = self.run_fixture("input_drift")
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(executor.calls, [])
        self.assertIn("fixed_input_identity", decision["failures"])

    def test_dirty_official_source_is_rc2_before_execution(self) -> None:
        executor = FakeExecute(self.fixture)
        decision, executor, _ = self.run_fixture(
            "dirty_source",
            probe=FakeProbe(self.fixture, dirty=True),
            execute=executor,
        )
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(executor.calls, [])
        self.assertIn("clean_official_execution_source", decision["failures"])

    def test_build_manifest_binary_mismatch_is_rc2(self) -> None:
        manifest = json.loads(self.fixture.build_manifest.read_text(encoding="utf-8"))
        manifest["binary"]["sha256"] = "0" * 64
        self.fixture.build_manifest.write_text(
            canonical_json(manifest), encoding="utf-8"
        )
        decision, executor, _ = self.run_fixture("manifest_drift")
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(executor.calls, [])
        self.assertIn(
            "canonical_build_manifest_matches_artifacts", decision["failures"]
        )

    def test_started_detect_failure_is_rc1_and_logs_are_preserved(self) -> None:
        raw_failure = {
            "error": "official_detect_output_contract_failed",
            "ok": False,
            "schema_version": RAW_SCHEMA_VERSION,
        }
        executor = FakeExecute(
            self.fixture, returncode=1, create_cache=True, raw=raw_failure
        )
        decision, executor, output = self.run_fixture(
            "detect_failure", execute=executor
        )
        self.assertEqual(decision["return_code"], RC_EXECUTION_FAILED)
        self.assertEqual(decision["status"], "EXECUTION_FAILED")
        self.assertEqual(len(executor.calls), 1)
        self.assertIn(
            "synthetic official stdout",
            (output / "harness.stdout.log").read_text(encoding="utf-8"),
        )
        self.assertTrue((output / "HF-Net.cache").is_file())

    def test_float32_parameter_rendering_does_not_false_fail_contract(self) -> None:
        raw = _success_raw()
        raw["fixed_parameters"]["scale_factor"] = 1.20000005  # type: ignore[index]
        raw["fixed_parameters"]["threshold"] = 0.00999999978  # type: ignore[index]
        decision, _, _ = self.run_fixture(
            "float32_rendering", execute=FakeExecute(self.fixture, raw=raw)
        )
        self.assertEqual(decision["return_code"], RC_PASS)

    def test_cache_artifact_copy_hash_drift_cannot_return_rc0(self) -> None:
        def corrupt_copy(source: Path, destination: Path) -> None:
            del source
            destination.write_bytes(b"corrupt copied cache")

        with mock.patch(
            "scripts.run_hfnet_rt_one_image_smoke_v1._copy_exclusive",
            side_effect=corrupt_copy,
        ):
            decision, _, _ = self.run_fixture("cache_copy_drift")
        self.assertEqual(decision["return_code"], RC_EXECUTION_FAILED)
        self.assertEqual(decision["status"], "EXECUTION_FAILED")
        self.assertIn("timing_cache_artifact_copy_exact", decision["failures"])

    def test_rc0_without_raw_result_or_cache_is_still_rc1(self) -> None:
        executor = FakeExecute(
            self.fixture, returncode=0, create_cache=False, raw=False
        )
        decision, _, output = self.run_fixture("missing_outputs", execute=executor)
        self.assertEqual(decision["return_code"], RC_EXECUTION_FAILED)
        self.assertEqual(decision["status"], "EXECUTION_FAILED")
        self.assertFalse((output / "HF-Net.cache").exists())
        self.assertIn("new_local_timing_cache_generated", decision["failures"])
        self.assertIn("official_detect_raw_result_contract", decision["failures"])

    def test_immutable_input_drift_during_execution_is_rc2(self) -> None:
        executor = FakeExecute(self.fixture, mutate_input=True)
        decision, _, _ = self.run_fixture("post_drift", execute=executor)
        self.assertEqual(decision["return_code"], RC_CONTRACT_BLOCKED)
        self.assertEqual(decision["status"], "POST_EXECUTION_INTEGRITY_ERROR")
        self.assertIn(
            "immutable_hashes_unchanged_after_execution", decision["failures"]
        )

    def test_main_prints_exactly_one_canonical_document(self) -> None:
        output = self.fixture.output_root / "main_success"
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            return_code = main(
                ["--output-dir", str(output)],
                contract=self.fixture.contract,
                probe_runner=FakeProbe(self.fixture),
                execute_runner=FakeExecute(self.fixture),
                clock=lambda: "2026-08-11T00:00:00Z",
            )
        self.assertEqual(return_code, RC_PASS)
        printed = stream.getvalue()
        self.assertEqual(printed, canonical_json(json.loads(printed)))


if __name__ == "__main__":
    unittest.main()
