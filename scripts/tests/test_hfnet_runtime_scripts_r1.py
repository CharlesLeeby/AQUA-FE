from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FETCH = ROOT / "scripts/fetch_hfnet_runtime_r1.sh"
INSTALL = ROOT / "scripts/install_hfnet_runtime_r1.sh"
ACTIVATE = ROOT / "scripts/activate_hfnet_runtime_r1.sh"
BUILD = ROOT / "scripts/build_hfnet_slam_official_r1.sh"

PLUGIN_PACKAGE = "libnvinfer-plugin8_8.5.1-1+cuda11.8_amd64.deb"
PLUGIN_SHA256 = "a0760312c196ca5f8facaf98257518341ee6513bc770309d132e5d3878971fa0"


class RuntimeFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runtime = root / "runtime"
        self.source = root / "official-build-worktree"
        self.pangolin = root / "pangolin"
        self.build = root / "cmake-build"
        self.bin = root / "bin"
        self.marker = root / "cmake-was-executed"

        required_files = (
            "usr/local/cuda-11.6/bin/nvcc",
            "usr/local/cuda-11.6/include/cuda_runtime_api.h",
            "usr/local/cuda-11.6/lib64/libcudart.so.11.0",
            "usr/local/cuda-11.8/lib64/libcublas.so.11",
            "usr/local/cuda-11.8/lib64/libcublasLt.so.11",
            "usr/include/x86_64-linux-gnu/NvInfer.h",
            "usr/include/x86_64-linux-gnu/NvOnnxParser.h",
            "usr/include/x86_64-linux-gnu/cudnn_v8.h",
            "usr/include/x86_64-linux-gnu/cudnn_version_v8.h",
            "usr/lib/x86_64-linux-gnu/libnvinfer.so",
            "usr/lib/x86_64-linux-gnu/libnvinfer.so.8",
            "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8",
            "usr/lib/x86_64-linux-gnu/libnvonnxparser.so",
            "usr/lib/x86_64-linux-gnu/libnvonnxparser.so.8",
        )
        for relative in required_files:
            path = self.runtime / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode("ascii"))
        (self.runtime / "usr/local/cuda-11.6/bin/nvcc").chmod(0o755)
        (self.runtime / "usr/local/cuda-11.6/targets/x86_64-linux/lib").mkdir(
            parents=True
        )
        (self.runtime / "usr/local/cuda-11.8/targets/x86_64-linux/lib").mkdir(
            parents=True
        )

        (self.source / "Thirdparty/g2o/lib").mkdir(parents=True)
        (self.source / "Thirdparty/g2o/lib/libg2o.so").write_bytes(b"g2o")
        (self.source / "lib").mkdir()
        (self.source / "CMakeLists.txt").write_text(
            "project(fixture)\n", encoding="utf-8"
        )
        pangolin_cmake = self.pangolin / "lib/cmake/Pangolin"
        pangolin_cmake.mkdir(parents=True)
        (pangolin_cmake / "PangolinConfig.cmake").write_text(
            "# fixture\n", encoding="utf-8"
        )

        self.bin.mkdir()
        self.fake_git = self.bin / "git"
        self.fake_git.write_text(
            "#!/usr/bin/env bash\n"
            "case \"$*\" in\n"
            "  *\"rev-parse HEAD^{tree}\"*) "
            "echo 6619814aed4cd0e4baa2501341a48f753f8ba196 ;;\n"
            "  *\"rev-parse HEAD\"*) "
            "echo c354c72588a97bb6f6a9c7c8317530795956ec80 ;;\n"
            "  *\" diff \"*) exit 0 ;;\n"
            "  *) exit 9 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        self.fake_git.chmod(0o755)
        self.fake_cmake = self.bin / "cmake"
        self.fake_cmake.write_text(
            "#!/usr/bin/env bash\n"
            f"touch {self.marker}\n"
            "exit 91\n",
            encoding="utf-8",
        )
        self.fake_cmake.chmod(0o755)

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(
            {
                "HFNET_RUNTIME_ROOT": str(self.runtime),
                "HFNET_SOURCE_ROOT": str(self.source),
                "HFNET_PANGOLIN_ROOT": str(self.pangolin),
                "HFNET_GIT_BIN": str(self.fake_git),
                "HFNET_CMAKE_BIN": str(self.fake_cmake),
                "LD_LIBRARY_PATH": "/external/runtime",
            }
        )
        return environment


class HFNetRuntimeScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = RuntimeFixture(Path(temporary.name))

    def test_shell_scripts_parse_without_execution(self) -> None:
        for script in (FETCH, INSTALL, ACTIVATE, BUILD):
            with self.subTest(script=script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)

    def test_fetch_and_install_freeze_plugin_package_and_compile_contract(self) -> None:
        fetch = FETCH.read_text(encoding="utf-8")
        install = INSTALL.read_text(encoding="utf-8")
        package_pattern = re.compile(
            r'^  "([^"|]+\.deb)\|([0-9a-f]{64})"$', re.MULTILINE
        )
        fetch_packages = package_pattern.findall(fetch)
        install_packages = package_pattern.findall(install)
        self.assertEqual(len(fetch_packages), 14)
        self.assertEqual(len(set(fetch_packages)), 14)
        self.assertEqual(fetch_packages, install_packages)
        for content in (fetch, install):
            self.assertIn(PLUGIN_PACKAGE + "|" + PLUGIN_SHA256, content)
        self.assertIn("MIN_FREE_BYTES=2600000000", fetch)
        self.assertIn("MIN_FREE_BYTES=7600000000", install)
        self.assertNotIn('${stage_dir}/usr/include/cudnn.h', install)
        self.assertIn(
            '${stage_dir}/usr/include/x86_64-linux-gnu/cudnn_v8.h', install
        )
        self.assertIn(
            '${stage_dir}/usr/include/x86_64-linux-gnu/cudnn_version_v8.h',
            install,
        )
        self.assertIn('${stage_dir}/usr/include/x86_64-linux-gnu/NvOnnxParser.h', install)
        self.assertIn('${system_lib}/libnvinfer.so"', install)
        self.assertIn('${system_lib}/libnvonnxparser.so"', install)
        self.assertIn('${system_lib}/libnvinfer_plugin.so.8"', install)
        self.assertIn('${system_lib}/libnvinfer_plugin.so.8.5.1"', install)
        self.assertLess(
            install.index('"libnvinfer_plugin.so.8",'),
            install.index('"libnvonnxparser.so.8",'),
        )

    def test_activation_exports_cuda118_cublas_path_and_compile_paths(self) -> None:
        command = (
            "set -e; source \"$ACTIVATE\"; "
            "printf '%s\\n' \"$CUDA_TOOLKIT_ROOT_DIR\" "
            "\"$TENSORRT_INCLUDE_DIR\" \"$TENSORRT_LIBRARY_DIR\" "
            "\"$LD_LIBRARY_PATH\" \"$CMAKE_LIBRARY_PATH\""
        )
        environment = self.fixture.environment()
        environment["ACTIVATE"] = str(ACTIVATE)
        completed = subprocess.run(
            ["bash", "-c", command],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        values = completed.stdout.splitlines()
        self.assertEqual(
            values[0], str(self.fixture.runtime / "usr/local/cuda-11.6")
        )
        self.assertEqual(
            values[1], str(self.fixture.runtime / "usr/include/x86_64-linux-gnu")
        )
        self.assertEqual(
            (self.fixture.runtime / "usr/include/x86_64-linux-gnu/cudnn_v8.h").parent,
            Path(values[1]),
        )
        self.assertEqual(
            (
                self.fixture.runtime
                / "usr/include/x86_64-linux-gnu/cudnn_version_v8.h"
            ).parent,
            Path(values[1]),
        )
        self.assertEqual(
            values[2], str(self.fixture.runtime / "usr/lib/x86_64-linux-gnu")
        )
        cuda118 = str(self.fixture.runtime / "usr/local/cuda-11.8/lib64")
        self.assertIn(cuda118, values[3].split(":"))
        self.assertIn(cuda118, values[4].split(":"))
        self.assertTrue(values[3].endswith("/external/runtime"))

    def test_activation_fails_closed_without_tensorrt_plugin(self) -> None:
        plugin = (
            self.fixture.runtime
            / "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8"
        )
        plugin.unlink()
        environment = self.fixture.environment()
        environment["ACTIVATE"] = str(ACTIVATE)
        completed = subprocess.run(
            ["bash", "-c", 'source "$ACTIVATE"'],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("libnvinfer_plugin.so.8", completed.stderr)

    def test_build_dry_run_exposes_explicit_search_and_rpath_contract(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                str(BUILD),
                "--dry-run",
                "--source-root",
                str(self.fixture.source),
                "--runtime-root",
                str(self.fixture.runtime),
                "--pangolin-root",
                str(self.fixture.pangolin),
                "--build-dir",
                str(self.fixture.build),
            ],
            env=self.fixture.environment(),
            check=True,
            capture_output=True,
            text=True,
        )
        output = completed.stdout
        cuda116 = str(self.fixture.runtime / "usr/local/cuda-11.6")
        cuda118_lib = str(self.fixture.runtime / "usr/local/cuda-11.8/lib64")
        trt_include = str(
            self.fixture.runtime / "usr/include/x86_64-linux-gnu"
        )
        trt_lib = str(self.fixture.runtime / "usr/lib/x86_64-linux-gnu")
        self.assertIn("CUDA_TOOLKIT_ROOT_DIR=" + cuda116, output)
        self.assertIn("-DCUDA_TOOLKIT_ROOT_DIR=" + cuda116, output)
        self.assertIn("-DTENSORRT_INCLUDE_DIR=" + trt_include, output)
        self.assertIn("-DCMAKE_LIBRARY_PATH=" + trt_lib, output)
        self.assertIn(cuda118_lib, output)
        self.assertIn("-DCMAKE_BUILD_RPATH=", output)
        self.assertIn("-DCMAKE_INSTALL_RPATH=", output)
        self.assertIn("-DCMAKE_SHARED_LINKER_FLAGS=", output)
        self.assertIn("-L" + trt_lib, output)
        self.assertIn("LD_LIBRARY_PATH=", output)
        self.assertFalse(self.fixture.build.exists())
        self.assertFalse(self.fixture.marker.exists())


if __name__ == "__main__":
    unittest.main()
