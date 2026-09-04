from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence

from scripts.preflight_published_hfnet_slam_v1 import (
    A02_PREFIX_CONTRACT,
    AUTHOR_BUILD_REPAIR_COMMIT,
    AUTHOR_BUILD_REPAIR_PATHS,
    AUTHOR_BUILD_REPAIR_TREE,
    CUDA_EXPECTED_NVCC_BUILD,
    CUDA_EXPECTED_RELEASE,
    CUDA118_CUBLAS_CANDIDATES,
    CUDA_HEADER_CANDIDATES,
    CUDA_NVCC_RELATIVE,
    CUDA_RUNTIME_CANDIDATES,
    CUDNN_EXPECTED_VERSION,
    CUDNN_LIBRARY_NAMES,
    CUDNN_VERSION_HEADER_CANDIDATES,
    DEFAULT_BINARY,
    DEFAULT_RUNTIME_ROOT,
    EXECUTION_COMMIT,
    EXECUTION_TREE,
    FROZEN_BUILD_DIRECTORY,
    OFFICIAL_INPUT_IDENTITY,
    OFFICIAL_CMAKE_OUTPUT_PATHS,
    OFFICIAL_MODEL_IDENTITY,
    OFFICIAL_REPOSITORY,
    PANGOLIN_VERSION_CANDIDATES,
    PAPER_COMMIT,
    PAPER_TREE,
    PUBLISHED_DOI,
    RC_INTEGRITY_ERROR,
    RC_READY,
    RC_RUNTIME_BLOCKED,
    TENSORRT_REQUIRED_FILES,
    TENSORRT_VERSION_HEADER_CANDIDATES,
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
        fixture: "Fixture",
        *,
        head: str = EXECUTION_COMMIT,
        tree: str = EXECUTION_TREE,
        origin: str = OFFICIAL_REPOSITORY,
        status: str = "",
        diff_paths: Sequence[str] = AUTHOR_BUILD_REPAIR_PATHS,
        nvcc: CommandResult | None = None,
        gpu: CommandResult = CommandResult(
            0, "Mock GTX 1650, 535.183.01, 4096 MiB\n", ""
        ),
        ldd: CommandResult | None = None,
    ) -> None:
        self.fixture = fixture
        self.head = head
        self.tree = tree
        self.origin = origin
        self.status = status
        self.diff_paths = tuple(diff_paths)
        self.nvcc = nvcc or CommandResult(
            0,
            (
                "Cuda compilation tools, release "
                + CUDA_EXPECTED_RELEASE
                + ", V"
                + CUDA_EXPECTED_NVCC_BUILD
                + "\n"
            ),
            "",
        )
        self.gpu = gpu
        self.ldd = ldd or CommandResult(0, fixture.ldd_output(), "")
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str], cwd: Path | None) -> CommandResult:
        del cwd
        values = tuple(command)
        self.commands.append(values)
        if values and values[0] == "git":
            operation = values[3:]
            if operation == ("rev-parse", "--is-inside-work-tree"):
                return CommandResult(0, "true\n", "")
            if operation == ("rev-parse", "HEAD"):
                return CommandResult(0, self.head + "\n", "")
            if operation == ("rev-parse", "HEAD^{tree}"):
                return CommandResult(0, self.tree + "\n", "")
            if operation == ("config", "--get", "remote.origin.url"):
                return CommandResult(0, self.origin + "\n", "")
            if operation[:2] == ("status", "--porcelain=v1"):
                return CommandResult(0, self.status, "")
            if operation[:2] == ("cat-file", "-p"):
                commit = operation[2]
                objects = {
                    PAPER_COMMIT: (
                        "tree "
                        + PAPER_TREE
                        + "\nparent 4e97abf00316139c6c3f6e714d965aa00ecc08ab\n"
                    ),
                    AUTHOR_BUILD_REPAIR_COMMIT: (
                        "tree "
                        + AUTHOR_BUILD_REPAIR_TREE
                        + "\nparent "
                        + PAPER_COMMIT
                        + "\n"
                    ),
                    EXECUTION_COMMIT: (
                        "tree "
                        + EXECUTION_TREE
                        + "\nparent "
                        + AUTHOR_BUILD_REPAIR_COMMIT
                        + "\n"
                    ),
                }
                if commit in objects:
                    return CommandResult(0, objects[commit], "")
                return CommandResult(128, "", "unknown object")
            if operation[:2] == ("diff", "--name-only"):
                return CommandResult(0, "\n".join(self.diff_paths) + "\n", "")
            return CommandResult(9, "", "unexpected git command")
        if values and values[0] == str(self.fixture.nvcc):
            return self.nvcc
        if values and values[0] == "nvidia-smi":
            return self.gpu
        if values and values[0] == "/usr/bin/env":
            return self.ldd
        return CommandResult(9, "", "unexpected command")


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repository = root / "official"
        self.repository.mkdir()
        self.model_archive = root / "hfnet-rt.tar.xz"
        self.onnx_model = root / "HF-Net.onnx"
        self.raw = root / "a02.bag"
        self.camera = root / "a02_camera.yaml"
        self.runtime = root / "isolated_runtime"
        self.pangolin = root / "pangolin"
        self.binary = (
            self.repository
            / "Examples/Monocular-Inertial/mono_inertial_euroc"
        )
        self.output = root / "reserved_output"

        self.model_archive.write_bytes(b"archive fixture")
        self.onnx_model.write_bytes(b"onnx fixture")
        self.raw.write_bytes(b"raw fixture")
        self.camera.write_bytes(b"camera fixture")
        self.expected_models: dict[str, dict[str, object]] = {
            "model_archive": {
                "size_bytes": self.model_archive.stat().st_size,
                "sha256": _digest(self.model_archive.read_bytes()),
            },
            "onnx_model": {
                "size_bytes": self.onnx_model.stat().st_size,
                "sha256": _digest(self.onnx_model.read_bytes()),
            },
        }
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

        self.nvcc = self.runtime / CUDA_NVCC_RELATIVE
        self.nvcc.parent.mkdir(parents=True)
        self.nvcc.write_text("fixture nvcc\n", encoding="utf-8")
        self.nvcc.chmod(0o755)
        cuda_header = self.runtime / CUDA_HEADER_CANDIDATES[0]
        cuda_header.parent.mkdir(parents=True, exist_ok=True)
        cuda_header.write_text("fixture\n", encoding="utf-8")
        cuda_runtime = self.runtime / CUDA_RUNTIME_CANDIDATES[0]
        cuda_runtime.parent.mkdir(parents=True, exist_ok=True)
        cuda_runtime.write_bytes(b"cudart")
        for candidates in CUDA118_CUBLAS_CANDIDATES:
            cublas_library = self.runtime / candidates[0]
            cublas_library.parent.mkdir(parents=True, exist_ok=True)
            cublas_library.write_bytes(candidates[0].encode("ascii"))

        library_dir = self.runtime / "usr/lib/x86_64-linux-gnu"
        library_dir.mkdir(parents=True, exist_ok=True)
        for name in CUDNN_LIBRARY_NAMES:
            (library_dir / name).write_bytes(name.encode("ascii"))
        cudnn_header = self.runtime / CUDNN_VERSION_HEADER_CANDIDATES[0]
        cudnn_header.parent.mkdir(parents=True, exist_ok=True)
        cudnn_header.write_text(
            "#define CUDNN_MAJOR 8\n"
            "#define CUDNN_MINOR 4\n"
            "#define CUDNN_PATCHLEVEL 1\n",
            encoding="utf-8",
        )

        for relative_path in TENSORRT_REQUIRED_FILES:
            path = self.runtime / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative_path.encode("ascii"))
        trt_header = self.runtime / TENSORRT_VERSION_HEADER_CANDIDATES[0]
        trt_header.parent.mkdir(parents=True, exist_ok=True)
        trt_header.write_text(
            "#define NV_TENSORRT_MAJOR 8\n"
            "#define NV_TENSORRT_MINOR 5\n"
            "#define NV_TENSORRT_PATCH 1\n",
            encoding="utf-8",
        )

        pangolin_version = self.pangolin / PANGOLIN_VERSION_CANDIDATES[0]
        pangolin_version.parent.mkdir(parents=True, exist_ok=True)
        pangolin_version.write_text(
            'set(PACKAGE_VERSION "0.7")\n', encoding="utf-8"
        )
        pangolin_library = self.pangolin / "lib/libpango_core.so"
        pangolin_library.parent.mkdir(parents=True, exist_ok=True)
        pangolin_library.write_bytes(b"pangolin")

        self.binary.parent.mkdir(parents=True, exist_ok=True)
        self.binary.write_bytes(b"\x7fELFfixture")
        self.binary.chmod(0o755)
        (self.repository / "lib").mkdir()
        (self.repository / "Thirdparty/g2o/lib").mkdir(parents=True)

    def ldd_output(self, *, external_tensorrt: bool = False) -> str:
        trt_root = Path("/usr/lib/x86_64-linux-gnu") if external_tensorrt else (
            self.runtime / "usr/lib/x86_64-linux-gnu"
        )
        lines = [
            f"libHFNet_SLAM.so => {self.repository}/lib/libHFNet_SLAM.so (0x1)",
            f"libpango_core.so => {self.pangolin}/lib/libpango_core.so (0x2)",
            f"libnvinfer.so.8 => {trt_root}/libnvinfer.so.8.5.1 (0x3)",
            (
                "libnvinfer_plugin.so.8 => "
                f"{trt_root}/libnvinfer_plugin.so.8.5.1 (0x4)"
            ),
            f"libnvonnxparser.so.8 => {trt_root}/libnvonnxparser.so.8.5.1 (0x5)",
            (
                "libcudart.so.11.0 => "
                f"{self.runtime}/usr/local/cuda-11.6/lib64/libcudart.so.11.0 (0x6)"
            ),
            (
                "libcublas.so.11 => "
                f"{self.runtime}/usr/local/cuda-11.8/lib64/libcublas.so.11 (0x7)"
            ),
            (
                "libcublasLt.so.11 => "
                f"{self.runtime}/usr/local/cuda-11.8/lib64/libcublasLt.so.11 (0x8)"
            ),
            (
                "libcudnn.so.8 => "
                f"{self.runtime}/usr/lib/x86_64-linux-gnu/libcudnn.so.8.4.1 (0x9)"
            ),
            "libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0xa)",
        ]
        return "\n".join(lines) + "\n"

    def evaluate(self, runner: FakeRunner | None = None, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "repository": self.repository,
            "model_archive": self.model_archive,
            "onnx_model": self.onnx_model,
            "a02_raw": self.raw,
            "a02_camera": self.camera,
            "runtime_root": self.runtime,
            "pangolin_root": self.pangolin,
            "binary": self.binary,
            "output_directory": self.output,
            "runner": runner or FakeRunner(self),
            "environment": {"DISPLAY": ":99"},
            "expected_models": self.expected_models,
            "expected_inputs": self.expected_inputs,
        }
        values.update(overrides)
        return evaluate_preflight(**values)  # type: ignore[arg-type]


class PublishedHFNetSlamV1PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_frozen_publication_model_and_a02_contract(self) -> None:
        self.assertEqual(PUBLISHED_DOI, "10.3390/s23042113")
        self.assertEqual(PAPER_COMMIT, "ecb8018f443e66aacf910bc9aaf17e308bc55570")
        self.assertEqual(EXECUTION_COMMIT, "c354c72588a97bb6f6a9c7c8317530795956ec80")
        self.assertEqual(EXECUTION_TREE, "6619814aed4cd0e4baa2501341a48f753f8ba196")
        self.assertEqual(DEFAULT_RUNTIME_ROOT, Path("/home/ma/opt/hfnet_cuda116_trt851_r1"))
        self.assertEqual(
            DEFAULT_BINARY,
            Path(
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-r1/Examples/Monocular-Inertial/mono_inertial_euroc"
            ),
        )
        self.assertEqual(
            OFFICIAL_MODEL_IDENTITY["onnx_model"],
            {
                "size_bytes": 132238602,
                "sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
            },
        )
        self.assertEqual(
            OFFICIAL_INPUT_IDENTITY["a02_raw"]["sha256"],
            "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8",
        )
        self.assertEqual(A02_PREFIX_CONTRACT["camera_count"], 200)
        self.assertEqual(A02_PREFIX_CONTRACT["imu_count"], 1990)
        self.assertEqual(
            A02_PREFIX_CONTRACT["raw_imu_to_camera_clock_offset_ns"], 53694112
        )

    def test_complete_fixture_is_ready_without_running_model_or_binary(self) -> None:
        runner = FakeRunner(self.fixture)
        decision = self.fixture.evaluate(runner)
        self.assertEqual(decision["status"], "READY")
        self.assertEqual(decision["return_code"], RC_READY)
        self.assertTrue(decision["ready"])
        self.assertEqual(decision["integrity_errors"], [])
        self.assertEqual(decision["runtime_blockers"], [])
        self.assertTrue(
            decision["checks"]["integrity"]["author_build_repair_commit_chain"]["ok"]
        )
        self.assertTrue(
            decision["checks"]["integrity"]["author_build_repair_changed_paths"]["ok"]
        )
        self.assertFalse(decision["probe_boundary"]["compile_or_build_performed"])
        self.assertFalse(decision["probe_boundary"]["model_or_engine_loaded"])
        commands = [value for command in runner.commands for value in command]
        self.assertNotIn("cmake", commands)
        self.assertNotIn("make", commands)
        self.assertNotIn(str(self.fixture.binary), [command[0] for command in runner.commands])

        ldd_commands = [command for command in runner.commands if command[0] == "/usr/bin/env"]
        self.assertEqual(len(ldd_commands), 1)
        ldd_environment = next(
            value for value in ldd_commands[0] if value.startswith("LD_LIBRARY_PATH=")
        )
        self.assertIn(
            str(self.fixture.runtime / "usr/local/cuda-11.8/lib64"),
            ldd_environment,
        )
        self.assertIn(
            str(
                self.fixture.runtime
                / "usr/local/cuda-11.8/targets/x86_64-linux/lib"
            ),
            ldd_environment,
        )

    def test_frozen_postbuild_generated_entries_are_allowed_and_recorded(self) -> None:
        status = (
            f"?? {FROZEN_BUILD_DIRECTORY}/CMakeCache.txt\n"
            f"?? {FROZEN_BUILD_DIRECTORY}/CMakeFiles/HFNet_SLAM.dir/src/Tracking.cc.o\n"
            f"?? {OFFICIAL_CMAKE_OUTPUT_PATHS[0]}\n"
            f"?? {OFFICIAL_CMAKE_OUTPUT_PATHS[6]}\n"
        )
        decision = self.fixture.evaluate(FakeRunner(self.fixture, status=status))
        self.assertEqual(decision["return_code"], RC_READY)
        self.assertTrue(decision["checks"]["integrity"]["repository_clean"]["ok"])
        inventory = decision["checks"]["informational"][
            "repository_allowed_generated_inventory"
        ]["observed"]
        self.assertEqual(inventory["entry_count"], 4)
        self.assertEqual(inventory["entries"], sorted(line[3:] for line in status.splitlines()))
        self.assertEqual(len(inventory["entries_sha256"]), 64)

    def test_rogue_untracked_entry_remains_rc2(self) -> None:
        status = (
            f"?? {FROZEN_BUILD_DIRECTORY}/CMakeCache.txt\n"
            "?? src/rogue_untracked.cc\n"
        )
        decision = self.fixture.evaluate(FakeRunner(self.fixture, status=status))
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertIn("repository_clean", decision["integrity_errors"])
        observed = decision["checks"]["integrity"]["repository_clean"]["observed"]
        self.assertEqual(observed["unexpected_untracked_entries"], ["src/rogue_untracked.cc"])

    def test_identity_drift_is_rc2_and_precedes_runtime_failures(self) -> None:
        self.fixture.onnx_model.write_bytes(b"mutated")
        self.fixture.output.mkdir()
        runner = FakeRunner(
            self.fixture,
            head="0" * 40,
            tree="1" * 40,
            origin="https://github.com/not-official/fork.git",
            status=" M src/Tracking.cc\n",
            gpu=CommandResult(9, "", "driver unavailable"),
        )
        decision = self.fixture.evaluate(runner)
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertIn("repository_head", decision["integrity_errors"])
        self.assertIn("repository_tree", decision["integrity_errors"])
        self.assertIn("repository_origin", decision["integrity_errors"])
        self.assertIn("repository_clean", decision["integrity_errors"])
        self.assertIn(
            "model_identity:onnx_model:sha256", decision["integrity_errors"]
        )
        self.assertIn("nvidia_gpu_available", decision["runtime_blockers"])
        self.assertIn("output_directory_unreserved", decision["runtime_blockers"])

    def test_author_repair_boundary_drift_is_rc2(self) -> None:
        changed = list(AUTHOR_BUILD_REPAIR_PATHS) + ["src/Tracking.cc"]
        decision = self.fixture.evaluate(FakeRunner(self.fixture, diff_paths=changed))
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertEqual(decision["status"], "INTEGRITY_ERROR")
        self.assertEqual(
            decision["integrity_errors"], ["author_build_repair_changed_paths"]
        )

    def test_missing_or_wrong_runtime_is_rc1_when_identity_is_intact(self) -> None:
        (self.fixture.runtime / TENSORRT_REQUIRED_FILES[-1]).unlink()
        trt_header = self.fixture.runtime / TENSORRT_VERSION_HEADER_CANDIDATES[0]
        trt_header.write_text(
            "#define NV_TENSORRT_MAJOR 9\n"
            "#define NV_TENSORRT_MINOR 0\n"
            "#define NV_TENSORRT_PATCH 0\n",
            encoding="utf-8",
        )
        self.fixture.binary.unlink()
        self.fixture.output.mkdir()
        decision = self.fixture.evaluate()
        self.assertEqual(decision["status"], "RUNTIME_BLOCKED")
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        self.assertEqual(decision["integrity_errors"], [])
        self.assertIn("tensorrt_layout_isolated", decision["runtime_blockers"])
        self.assertIn("tensorrt_version", decision["runtime_blockers"])
        self.assertIn("build_binary", decision["runtime_blockers"])
        self.assertIn("build_binary_dependency_isolation", decision["runtime_blockers"])
        self.assertIn("output_directory_unreserved", decision["runtime_blockers"])

    def test_tensorrt_compile_time_link_contract_is_required(self) -> None:
        for relative_path in (
            "usr/include/x86_64-linux-gnu/NvOnnxParser.h",
            "usr/lib/x86_64-linux-gnu/libnvinfer.so",
            "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8.5.1",
            "usr/lib/x86_64-linux-gnu/libnvonnxparser.so",
        ):
            with self.subTest(relative_path=relative_path):
                path = self.fixture.runtime / relative_path
                original = path.read_bytes()
                path.unlink()
                decision = self.fixture.evaluate()
                self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
                self.assertIn("tensorrt_layout_isolated", decision["runtime_blockers"])
                path.write_bytes(original)

    def test_cuda118_cublas_closure_is_required(self) -> None:
        cublas_lt = self.fixture.runtime / CUDA118_CUBLAS_CANDIDATES[1][0]
        cublas_lt.unlink()
        decision = self.fixture.evaluate()
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        self.assertIn(
            "cuda118_cublas_layout_isolated", decision["runtime_blockers"]
        )

    def test_dynamic_dependencies_must_resolve_inside_frozen_roots(self) -> None:
        runner = FakeRunner(
            self.fixture,
            ldd=CommandResult(
                0, self.fixture.ldd_output(external_tensorrt=True), ""
            ),
        )
        decision = self.fixture.evaluate(runner)
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        check = decision["checks"]["runtime"]["build_binary_dependency_isolation"]
        self.assertFalse(check["ok"])
        self.assertIn("libnvinfer.so.8", check["observed"]["isolation_violations"])
        self.assertIn(
            "libnvinfer_plugin.so.8", check["observed"]["isolation_violations"]
        )
        self.assertIn(
            "libnvonnxparser.so.8", check["observed"]["isolation_violations"]
        )

    def test_display_is_required_because_offline_entrypoint_forces_viewer(self) -> None:
        decision = self.fixture.evaluate(environment={})
        self.assertEqual(decision["return_code"], RC_RUNTIME_BLOCKED)
        self.assertEqual(decision["integrity_errors"], [])
        self.assertIn("viewer_display_declared", decision["runtime_blockers"])

    def test_a02_camera_and_raw_are_integrity_not_runtime_gates(self) -> None:
        self.fixture.raw.unlink()
        self.fixture.camera.write_bytes(b"changed fixture")
        decision = self.fixture.evaluate()
        self.assertEqual(decision["return_code"], RC_INTEGRITY_ERROR)
        self.assertIn("input_identity:a02_raw:exists", decision["integrity_errors"])
        self.assertIn("input_identity:a02_raw:size_bytes", decision["integrity_errors"])
        self.assertIn("input_identity:a02_raw:sha256", decision["integrity_errors"])
        self.assertIn("input_identity:a02_camera:sha256", decision["integrity_errors"])
        self.assertNotIn("a02_raw", " ".join(decision["runtime_blockers"]))

    def test_main_emits_one_json_line_and_writes_nothing(self) -> None:
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
            "--model-archive",
            str(self.fixture.model_archive),
            "--onnx-model",
            str(self.fixture.onnx_model),
            "--a02-raw",
            str(self.fixture.raw),
            "--a02-camera",
            str(self.fixture.camera),
            "--runtime-root",
            str(self.fixture.runtime),
            "--pangolin-root",
            str(self.fixture.pangolin),
            "--binary",
            str(self.fixture.binary),
            "--output-dir",
            str(self.fixture.output),
        ]
        with contextlib.redirect_stdout(stdout):
            return_code = main(
                argv,
                runner=FakeRunner(self.fixture),
                environment={"DISPLAY": ":99"},
                expected_models=self.fixture.expected_models,
                expected_inputs=self.fixture.expected_inputs,
            )
        after = {
            str(path.relative_to(self.fixture.root)): (
                "directory" if path.is_dir() else _digest(path.read_bytes())
            )
            for path in self.fixture.root.rglob("*")
        }
        self.assertEqual(return_code, RC_READY)
        self.assertEqual(before, after)
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(stdout.getvalue().count("\n"), 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(stdout.getvalue(), canonical_json(payload) + "\n")


if __name__ == "__main__":
    unittest.main()
