from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence

from scripts.preflight_published_supervins_v1 import (
    CUDA_PROVIDER_TOKEN,
    CUDA_SOURCE,
    DEFAULT_A02_RAW,
    DEFAULT_REPOSITORY,
    OFFICIAL_FILE_SHA256,
    OFFICIAL_INPUT_IDENTITY,
    OFFICIAL_REPOSITORY,
    ONNXRUNTIME_EXPECTED_VERSION,
    PAPER_COMMIT,
    PAPER_COMMIT_ZERO_MEMORY_LIMIT_OCCURRENCES,
    PUBLISHED_DOI,
    RC_INTEGRITY_ERROR,
    RC_READY,
    RC_RUNTIME_BLOCKED,
    UPSTREAM_CUDA_MEMORY_LIMIT_ZERO,
    CommandResult,
    canonical_json,
    evaluate_preflight,
    main,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeRunner:
    def __init__(
        self,
        *,
        head: str = PAPER_COMMIT,
        origin: str = OFFICIAL_REPOSITORY,
        status: str = "",
        ros: CommandResult = CommandResult(0, "noetic\n", ""),
        gpu: CommandResult = CommandResult(0, "Mock GPU\n", ""),
        nvcc: CommandResult = CommandResult(
            0, "Cuda compilation tools, release 11.8, V11.8.0\n", ""
        ),
    ) -> None:
        self.head = head
        self.origin = origin
        self.status = status
        self.ros = ros
        self.gpu = gpu
        self.nvcc = nvcc
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str], cwd: Path | None) -> CommandResult:
        del cwd
        values = tuple(command)
        self.commands.append(values)
        if values[0] == "git":
            operation = values[3:]
            if operation == ("rev-parse", "--is-inside-work-tree"):
                return CommandResult(0, "true\n", "")
            if operation == ("rev-parse", "HEAD"):
                return CommandResult(0, self.head + "\n", "")
            if operation == ("config", "--get", "remote.origin.url"):
                return CommandResult(0, self.origin + "\n", "")
            if operation[:2] == ("status", "--porcelain=v1"):
                return CommandResult(0, self.status, "")
            return CommandResult(9, "", "unexpected git command")
        if values == ("rosversion", "-d"):
            return self.ros
        if values and values[0] == "nvidia-smi":
            return self.gpu
        if values == ("nvcc", "--version"):
            return self.nvcc
        return CommandResult(9, "", "unexpected command")


class FakeLibraryProbe:
    def __init__(
        self,
        *,
        core_version: str | None = ONNXRUNTIME_EXPECTED_VERSION,
        failures: Mapping[str, str] | None = None,
    ) -> None:
        self.core_version = core_version
        self.failures = dict(failures or {})

    def __call__(
        self, libraries: Sequence[tuple[str, Path]]
    ) -> Mapping[str, Mapping[str, object]]:
        observations: dict[str, dict[str, object]] = {}
        for relative_path, path in libraries:
            error = self.failures.get(relative_path)
            if not path.is_file() and error is None:
                error = f"{path.name}: cannot open shared object file: No such file"
            loaded = error is None
            missing_dependency = None
            if error is not None and ": cannot open shared object file" in error:
                missing_dependency = error.split(":", 1)[0]
            observations[relative_path] = {
                "error": error,
                "loaded": loaded,
                "missing_dependency": missing_dependency,
                "version": (
                    self.core_version
                    if loaded and relative_path == "lib/libonnxruntime.so"
                    else None
                ),
                "version_error": None,
            }
        return observations


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repository = root / "official"
        self.raw = root / "a02_raw.tar.gz"
        self.camera = root / "a02_camera.yaml"
        self.ort = root / "onnxruntime"
        self.output = root / "reserved_output"
        self.expected_files: dict[str, str] = {}

        source = (
            "prefix "
            + CUDA_PROVIDER_TOKEN
            + "\ncuda_options.gpu_mem_limit = 0;\n"
            + CUDA_PROVIDER_TOKEN
            + "\ncuda_options.gpu_mem_limit = 0;\nsuffix\n"
        ).encode("ascii")
        files: Mapping[str, bytes] = {
            CUDA_SOURCE: source,
            "supervins_estimator/weights_dpl/disk.onnx": b"disk-fixture",
            "supervins_estimator/weights_dpl/disk_lightglue_fused.onnx": (
                b"disk-lightglue-fixture"
            ),
            "supervins_estimator/weights_dpl/superpoint.onnx": b"superpoint-fixture",
            "supervins_estimator/weights_dpl/superpoint_lightglue_fused.onnx": (
                b"superpoint-lightglue-fixture"
            ),
        }
        for relative_path, data in files.items():
            path = self.repository / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.expected_files[relative_path] = _digest(data)

        self.raw.write_bytes(b"small raw fixture")
        self.camera.write_text("camera_model: mock\n", encoding="utf-8")
        self.expected_inputs: dict[str, dict[str, object]] = {
            "a02_raw": {
                "size_bytes": self.raw.stat().st_size,
                "sha256": _digest(self.raw.read_bytes()),
            },
            "a02_camera": {
                "size_bytes": self.camera.stat().st_size,
                "sha256": _digest(self.camera.read_bytes()),
            },
        }
        for relative_path in (
            "lib/libonnxruntime.so",
            "lib/libonnxruntime_providers_cuda.so",
            "lib/libonnxruntime_providers_shared.so",
        ):
            path = self.ort / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative_path.encode("ascii"))
        (self.ort / "VERSION_NUMBER").write_text(
            ONNXRUNTIME_EXPECTED_VERSION + "\n", encoding="utf-8"
        )

    def evaluate(self, runner: FakeRunner, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "repository": self.repository,
            "a02_raw": self.raw,
            "a02_camera": self.camera,
            "onnxruntime_root": self.ort,
            "output_directory": self.output,
            "runner": runner,
            "expected_files": self.expected_files,
            "expected_inputs": self.expected_inputs,
            "library_probe": FakeLibraryProbe(),
        }
        values.update(overrides)
        return evaluate_preflight(**values)  # type: ignore[arg-type]

    def remove_upstream_defect_and_repin_fixture_oracle(self) -> None:
        source = self.repository / CUDA_SOURCE
        data = source.read_bytes().replace(b"cuda_options.gpu_mem_limit = 0;", b"")
        source.write_bytes(data)
        self.expected_files[CUDA_SOURCE] = _digest(data)


class PublishedSuperVinsV1PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_frozen_publication_identity_and_oracle(self) -> None:
        self.assertEqual(PUBLISHED_DOI, "10.1109/JSEN.2025.3556257")
        self.assertEqual(
            PAPER_COMMIT, "91e85d72a3828844538715cc4b1cd4b86a2620db"
        )
        self.assertEqual(OFFICIAL_REPOSITORY, "https://github.com/luohongk/SuperVINS.git")
        self.assertEqual(
            DEFAULT_REPOSITORY, Path("/home/ma/SLAM/SuperVINS-paper-1.0-r1")
        )
        self.assertEqual(
            DEFAULT_A02_RAW,
            Path("/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"),
        )
        self.assertEqual(PAPER_COMMIT_ZERO_MEMORY_LIMIT_OCCURRENCES, 2)
        self.assertEqual(ONNXRUNTIME_EXPECTED_VERSION, "1.16.3")
        self.assertEqual(
            dict(OFFICIAL_INPUT_IDENTITY),
            {
                "a02_raw": {
                    "size_bytes": 222477260,
                    "sha256": (
                        "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"
                    ),
                },
                "a02_camera": {
                    "size_bytes": 337,
                    "sha256": (
                        "e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2"
                    ),
                },
            },
        )
        self.assertEqual(len(OFFICIAL_FILE_SHA256), 5)
        self.assertEqual(
            dict(OFFICIAL_FILE_SHA256),
            {
                CUDA_SOURCE: (
                    "dfae6b3fdcb0a588d26d527ef0043c1a77f089305523f02f9bcc0b16ba88428f"
                ),
                "supervins_estimator/weights_dpl/disk.onnx": (
                    "f02f18e254bd52d978981c715a4e7961f15afaa23290379b9b357f6745df12c4"
                ),
                "supervins_estimator/weights_dpl/disk_lightglue_fused.onnx": (
                    "eff867103123a64720a1209218ff4bfa351a2d9b21a04b667265d794e9462cc9"
                ),
                "supervins_estimator/weights_dpl/superpoint.onnx": (
                    "234d12c9f523292efb34e0ca513b011050b0c052700da9c01787b9356a1138d2"
                ),
                "supervins_estimator/weights_dpl/superpoint_lightglue_fused.onnx": (
                    "8463182c165254b8cf182def813160691a5f3a455d95b4346e1b3ebf8a7709cf"
                ),
            },
        )
        self.assertEqual(
            sum(path.endswith(".onnx") for path in OFFICIAL_FILE_SHA256), 4
        )

    def test_stock_source_is_runtime_blocked_by_upstream_zero_limit(self) -> None:
        decision = self.fixture.evaluate(FakeRunner())
        self.assertEqual(decision["status"], "RUNTIME_BLOCKED")
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        self.assertFalse(decision["ready"])
        self.assertEqual(decision["integrity_errors"], [])
        self.assertEqual(
            decision["runtime_blockers"], [UPSTREAM_CUDA_MEMORY_LIMIT_ZERO]
        )
        defect = decision["checks"]["runtime"]["upstream_runtime_defect"]
        self.assertFalse(defect["ok"])
        self.assertEqual(defect["reason"], UPSTREAM_CUDA_MEMORY_LIMIT_ZERO)
        self.assertEqual(
            defect["observed"]["gpu_mem_limit_zero_occurrences"], 2
        )

    def test_defect_free_mock_can_reach_ready(self) -> None:
        self.fixture.remove_upstream_defect_and_repin_fixture_oracle()
        decision = self.fixture.evaluate(FakeRunner())
        self.assertEqual(decision["status"], "READY")
        self.assertEqual(decision["return_code"], RC_READY)
        self.assertTrue(decision["ready"])
        self.assertEqual(decision["integrity_errors"], [])
        self.assertEqual(decision["runtime_blockers"], [])
        self.assertFalse(self.fixture.output.exists())
        self.assertTrue(
            decision["checks"]["runtime"]["onnxruntime_gpu_version"]["ok"]
        )
        for relative_path in (
            "lib/libonnxruntime.so",
            "lib/libonnxruntime_providers_shared.so",
            "lib/libonnxruntime_providers_cuda.so",
        ):
            self.assertTrue(
                decision["checks"]["runtime"][
                    "onnxruntime_gpu_dlopen:" + relative_path
                ]["ok"]
            )
        self.assertEqual(
            decision["probe_boundary"]["preflight_scope"],
            "identity_version_and_dlopen_only",
        )
        self.assertTrue(
            decision["probe_boundary"]["session_smoke_required_after_ready"]
        )

    def test_editing_stock_source_to_remove_defect_is_integrity_error(self) -> None:
        source = self.fixture.repository / CUDA_SOURCE
        source.write_bytes(
            source.read_bytes().replace(b"cuda_options.gpu_mem_limit = 0;", b"")
        )
        decision = self.fixture.evaluate(FakeRunner())
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertIn("file_sha256:" + CUDA_SOURCE, decision["integrity_errors"])
        self.assertTrue(
            decision["checks"]["runtime"]["upstream_runtime_defect"]["ok"]
        )

    def test_a02_input_existence_size_and_sha_are_integrity_gates(self) -> None:
        self.fixture.raw.unlink()
        original_camera = self.fixture.camera.read_bytes()
        self.fixture.camera.write_bytes(b"X" + original_camera[1:])
        decision = self.fixture.evaluate(FakeRunner())
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertIn(
            "input_identity:a02_raw:exists", decision["integrity_errors"]
        )
        self.assertIn(
            "input_identity:a02_raw:size_bytes", decision["integrity_errors"]
        )
        self.assertIn(
            "input_identity:a02_raw:sha256", decision["integrity_errors"]
        )
        self.assertNotIn(
            "input_identity:a02_camera:size_bytes", decision["integrity_errors"]
        )
        self.assertIn(
            "input_identity:a02_camera:sha256", decision["integrity_errors"]
        )
        self.assertNotIn("a02_raw_exists", decision["runtime_blockers"])
        self.assertNotIn("a02_camera_exists", decision["runtime_blockers"])

    def test_runtime_shortfalls_are_rc1_only_when_integrity_passes(self) -> None:
        (self.fixture.ort / "lib/libonnxruntime_providers_cuda.so").unlink()
        self.fixture.output.mkdir()
        runner = FakeRunner(
            gpu=CommandResult(9, "", "driver unavailable"),
            nvcc=CommandResult(127, "", "not found"),
        )
        decision = self.fixture.evaluate(runner)
        self.assertEqual(decision["status"], "RUNTIME_BLOCKED")
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        self.assertEqual(decision["integrity_errors"], [])
        self.assertIn("nvidia_gpu_available", decision["runtime_blockers"])
        self.assertNotIn("nvcc_available", decision["runtime_blockers"])
        self.assertFalse(decision["checks"]["informational"]["nvcc_available"]["ok"])
        self.assertIn(
            "onnxruntime_gpu_library:lib/libonnxruntime_providers_cuda.so",
            decision["runtime_blockers"],
        )
        self.assertIn(
            "onnxruntime_gpu_dlopen:lib/libonnxruntime_providers_cuda.so",
            decision["runtime_blockers"],
        )
        self.assertIn("output_directory_unreserved", decision["runtime_blockers"])
        self.assertIn(UPSTREAM_CUDA_MEMORY_LIMIT_ZERO, decision["runtime_blockers"])

    def test_missing_nvcc_is_informational_and_cannot_block_ready(self) -> None:
        self.fixture.remove_upstream_defect_and_repin_fixture_oracle()
        decision = self.fixture.evaluate(
            FakeRunner(nvcc=CommandResult(127, "", "not found"))
        )
        self.assertEqual(decision["status"], "READY")
        self.assertEqual(decision["runtime_blockers"], [])
        nvcc = decision["checks"]["informational"]["nvcc_available"]
        self.assertFalse(nvcc["ok"])
        self.assertEqual(nvcc["observed"]["returncode"], 127)

    def test_ort_version_and_each_dlopen_are_blocking_with_missing_dep(self) -> None:
        self.fixture.remove_upstream_defect_and_repin_fixture_oracle()
        cuda_library = "lib/libonnxruntime_providers_cuda.so"
        probe = FakeLibraryProbe(
            core_version="1.15.0",
            failures={
                cuda_library: (
                    "libcudnn.so.8: cannot open shared object file: No such file or directory"
                )
            },
        )
        decision = self.fixture.evaluate(FakeRunner(), library_probe=probe)
        self.assertEqual(decision["status"], "RUNTIME_BLOCKED")
        self.assertIn("onnxruntime_gpu_version", decision["runtime_blockers"])
        self.assertIn(
            "onnxruntime_gpu_dlopen:" + cuda_library,
            decision["runtime_blockers"],
        )
        version = decision["checks"]["runtime"]["onnxruntime_gpu_version"]
        self.assertEqual(version["expected"], "1.16.3")
        self.assertEqual(version["observed"]["unique_versions"], ["1.15.0", "1.16.3"])
        dlopen = decision["checks"]["runtime"][
            "onnxruntime_gpu_dlopen:" + cuda_library
        ]
        self.assertFalse(dlopen["ok"])
        self.assertEqual(dlopen["observed"]["missing_dependency"], "libcudnn.so.8")

    def test_ort_version_metadata_is_valid_fallback_when_symbol_unavailable(self) -> None:
        self.fixture.remove_upstream_defect_and_repin_fixture_oracle()
        decision = self.fixture.evaluate(
            FakeRunner(), library_probe=FakeLibraryProbe(core_version=None)
        )
        self.assertEqual(decision["status"], "READY")
        version = decision["checks"]["runtime"]["onnxruntime_gpu_version"]
        self.assertTrue(version["ok"])
        self.assertEqual(
            version["observed"]["sources"]["metadata:VERSION_NUMBER"], "1.16.3"
        )

    def test_identity_drift_is_rc2_and_takes_priority_over_runtime(self) -> None:
        model = self.fixture.repository / "supervins_estimator/weights_dpl/disk.onnx"
        model.write_bytes(b"mutated")
        runner = FakeRunner(
            head="0" * 40,
            origin="https://github.com/not-official/fork.git",
            status=" M supervins_estimator/src/featureTracker/feature_tracker_dpl.cpp\n",
            ros=CommandResult(127, "", "not found"),
        )
        decision = self.fixture.evaluate(runner)
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertFalse(decision["ready"])
        self.assertIn("repository_head", decision["integrity_errors"])
        self.assertIn("repository_origin", decision["integrity_errors"])
        self.assertIn("repository_clean", decision["integrity_errors"])
        self.assertIn(
            "file_sha256:supervins_estimator/weights_dpl/disk.onnx",
            decision["integrity_errors"],
        )
        self.assertIn("ros1_available", decision["runtime_blockers"])

    def test_cuda_provider_token_is_an_explicit_integrity_gate(self) -> None:
        source = self.fixture.repository / CUDA_SOURCE
        source.write_text("CPU-only fixture\n", encoding="utf-8")
        expected = dict(self.fixture.expected_files)
        expected[CUDA_SOURCE] = _digest(source.read_bytes())
        decision = self.fixture.evaluate(FakeRunner(), expected_files=expected)
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertIn(
            "official_source_registers_cuda_provider", decision["integrity_errors"]
        )

    def test_main_emits_one_canonical_json_line_and_writes_nothing(self) -> None:
        before = {
            str(path.relative_to(self.fixture.root)): (
                "directory" if path.is_dir() else _digest(path.read_bytes())
            )
            for path in self.fixture.root.rglob("*")
        }
        stdout = io.StringIO()
        argv = [
            "--repo",
            str(self.fixture.repository),
            "--a02-raw",
            str(self.fixture.raw),
            "--a02-camera",
            str(self.fixture.camera),
            "--onnxruntime-root",
            str(self.fixture.ort),
            "--output-dir",
            str(self.fixture.output),
        ]
        with contextlib.redirect_stdout(stdout):
            return_code = main(
                argv,
                runner=FakeRunner(),
                expected_files=self.fixture.expected_files,
                expected_inputs=self.fixture.expected_inputs,
                library_probe=FakeLibraryProbe(),
            )
        after = {
            str(path.relative_to(self.fixture.root)): (
                "directory" if path.is_dir() else _digest(path.read_bytes())
            )
            for path in self.fixture.root.rglob("*")
        }
        self.assertEqual(return_code, RC_RUNTIME_BLOCKED)
        self.assertEqual(before, after)
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(stdout.getvalue().count("\n"), 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["runtime_blockers"], [UPSTREAM_CUDA_MEMORY_LIMIT_ZERO])
        self.assertEqual(stdout.getvalue(), canonical_json(payload) + "\n")


if __name__ == "__main__":
    unittest.main()
