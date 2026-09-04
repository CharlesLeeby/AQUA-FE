from __future__ import annotations

import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/formal_g0_child_bootstrap_v1.py"
SPEC = importlib.util.spec_from_file_location("formal_g0_child_bootstrap_v1", SOURCE)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def _sealed_memfd(name: str, content: bytes, *, executable: bool = False) -> int:
    fd = os.memfd_create(name, os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise AssertionError("short synthetic memfd write")
        view = view[written:]
    if executable:
        os.fchmod(fd, 0o500)
    os.lseek(fd, 0, os.SEEK_SET)
    seals = (
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL
    )
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
    return fd


def _environment_template(role: str = "runtime_probe") -> dict[str, str]:
    environment = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        bootstrap.ROLE_ENV: role,
        bootstrap.WRAPPER_ENV: "${EPOCH_WRAPPER_PROCFD}",
        bootstrap.BASE_ENV: "${EVALUATOR_BASE_PROCFD}",
        bootstrap.CORE_ENV: "${TRAJECTORY_CORE_PROCFD}",
        bootstrap.OUTPUT_ENV: "${ROLE_OUTPUT_DIRFD}",
        bootstrap.WRAPPER_BASE_ENV: "${EVALUATOR_BASE_PROCFD}",
        bootstrap.WRAPPER_CORE_ENV: "${TRAJECTORY_CORE_PROCFD}",
    }
    return environment


def _write_reference_bag(path: str) -> None:
    if "/opt/ros/noetic/lib/python3/dist-packages" not in sys.path:
        sys.path.insert(0, "/opt/ros/noetic/lib/python3/dist-packages")
    import rosbag
    from nav_msgs.msg import Odometry

    with rosbag.Bag(path, "w") as bag:
        message = Odometry()
        message.header.stamp.secs = 1
        bag.write("/reference", message, message.header.stamp)


def _run_probe() -> dict[str, object]:
    python_bytes = Path("/usr/bin/python3.8").read_bytes()
    wrapper_bytes = (
        b"import sys\n"
        b"sys.path.insert(0, '/opt/ros/noetic/lib/python3/dist-packages')\n"
        b"def main():\n    raise RuntimeError('probe called evaluator')\n"
    )
    descriptors = [
        _sealed_memfd("python", python_bytes, executable=True),
        _sealed_memfd("bootstrap", SOURCE.read_bytes()),
        _sealed_memfd("wrapper", wrapper_bytes),
        _sealed_memfd("base", b"# base\n"),
        _sealed_memfd("core", b"# core\n"),
    ]
    python_fd, bootstrap_fd, wrapper_fd, base_fd, core_fd = descriptors
    bag_temporary = tempfile.NamedTemporaryFile(suffix=".bag")
    _write_reference_bag(bag_temporary.name)
    bag_fd = os.open(bag_temporary.name, os.O_RDONLY | os.O_CLOEXEC)
    environment = _environment_template()
    replacements = {
        "${EPOCH_WRAPPER_PROCFD}": f"/proc/self/fd/{wrapper_fd}",
        "${EVALUATOR_BASE_PROCFD}": f"/proc/self/fd/{base_fd}",
        "${TRAJECTORY_CORE_PROCFD}": f"/proc/self/fd/{core_fd}",
    }
    for key, value in list(environment.items()):
        for original, replacement in replacements.items():
            value = value.replace(original, replacement)
        environment[key] = value
    environment.pop(bootstrap.OUTPUT_ENV)
    try:
        process = subprocess.run(
            [
                f"/proc/self/fd/{python_fd}",
                "-I",
                "-B",
                f"/proc/self/fd/{bootstrap_fd}",
                bootstrap.PROBE_ARGUMENT,
                f"/proc/self/fd/{bag_fd}",
                "/reference",
            ],
            env=environment,
            pass_fds=tuple([*descriptors, bag_fd]),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    finally:
        os.close(bag_fd)
        bag_temporary.close()
        for descriptor in descriptors:
            os.close(descriptor)
    if process.returncode != 0:
        raise AssertionError(process.stderr.decode("utf-8", "replace"))
    return json.loads(process.stdout)


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    payload[bootstrap.SELF_HASH_FIELD] = bootstrap._receipt_hash(payload)
    return payload


def _as_role(
    probe: dict[str, object], role: str, output_fd: int
) -> dict[str, object]:
    payload = copy.deepcopy(probe)
    payload["role"] = role
    payload["evaluator_called"] = True
    payload["evaluator_rc"] = 0
    payload["evaluator_error"] = None
    execution = payload["execution"]
    assert isinstance(execution, dict)
    environment = execution["environment"]
    assert isinstance(environment, dict)
    environment[bootstrap.ROLE_ENV] = role
    output = f"/proc/self/fd/{output_fd}"
    environment[bootstrap.OUTPUT_ENV] = output
    sealed = payload["sealed_sources"]
    assert isinstance(sealed, dict)
    reference_fd = "/proc/self/fd/997"
    sys_argv = [
        sealed["bootstrap"]["locator"],
        "--reference-bag",
        reference_fd,
        "--reference-topic",
        "/reference",
        "--output-dir",
        output,
    ]
    execution["sys_argv"] = sys_argv
    execution["process_argv"] = [
        sealed["python_interpreter"]["locator"], "-I", "-B", *sys_argv
    ]
    return _rehash(payload)


class FormalG0ChildBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = _run_probe()
        bootstrap.validate_freeze_runtime_static(cls.probe)

    def test_wrapper_source_executes_exactly_once(self) -> None:
        import builtins

        builtins._formal_g0_wrapper_counter = 0
        fd = _sealed_memfd(
            "wrapper-counter",
            b"import builtins\nbuiltins._formal_g0_wrapper_counter += 1\n",
        )
        try:
            bootstrap._load_wrapper(f"/proc/self/fd/{fd}")
            self.assertEqual(builtins._formal_g0_wrapper_counter, 1)
        finally:
            del builtins._formal_g0_wrapper_counter
            os.close(fd)

    def test_persistent_identity_regular_and_final_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.bin"
            target.write_bytes(b"bound-runtime\n")
            link = root / "link.bin"
            link.symlink_to(target.name)
            regular = bootstrap.persistent_file_identity(str(target))
            linked = bootstrap.persistent_file_identity(str(link))
            self.assertEqual(regular["sha256"], linked["sha256"])
            self.assertIsNone(regular["symlink"])
            self.assertEqual(linked["symlink"]["target"], target.name)
            self.assertEqual(linked["resolved_path"], str(target))

    def test_generated_genpy_identity_omits_random_path_and_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="genpy_", dir="/tmp") as temporary:
            source = Path(temporary) / "tmpabc123.py"
            source.write_text("# generated\n", encoding="utf-8")
            source.chmod(0o600)
            module = types.ModuleType("tmp_random_name")

            class Message:
                _type = "demo_msgs/Exact"
                _md5sum = "0123456789abcdef0123456789abcdef"
                _full_text = "int64 stamp_ns\n"

            module.Message = Message
            row = bootstrap._generated_module_identity(module, str(source))
            encoded = json.dumps(row, sort_keys=True)
            self.assertNotIn(str(source), encoded)
            self.assertNotIn(module.__name__, encoded)
            self.assertEqual(
                row["message_contracts"][0]["message_type"], "demo_msgs/Exact"
            )

    def test_proc_maps_canonical_rows_have_content_identity_not_address(self) -> None:
        with tempfile.NamedTemporaryFile() as handle:
            handle.write(b"mapped")
            handle.flush()
            info = os.stat(handle.name)
            text = (
                f"7f000000-7f001000 r--p 00000000 00:01 {info.st_ino} {handle.name}\n"
                "7f100000-7f101000 rw-p 00000000 00:00 0 [heap]\n"
            )
            result = bootstrap.capture_persistent_maps(text)
            self.assertEqual(len(result["rows"]), 1)
            self.assertNotIn("address", result["rows"][0])
            self.assertEqual(result["rows"][0]["file_sha256"], bootstrap._sha256_bytes(b"mapped"))

    def test_known_and_unknown_procfd_module_sources(self) -> None:
        known_fd = _sealed_memfd("known-module", b"# known\n")
        unknown_fd = _sealed_memfd("unknown-module", b"# unknown\n")
        known_name = "zz_formal_g0_known_procfd_module"
        unknown_name = "zz_formal_g0_unknown_procfd_module"
        known = types.ModuleType(known_name)
        known.__file__ = f"/proc/self/fd/{known_fd}"
        known.__spec__ = types.SimpleNamespace(origin=known.__file__)
        known.__cached__ = None
        unknown = types.ModuleType(unknown_name)
        unknown.__file__ = f"/proc/self/fd/{unknown_fd}"
        unknown.__spec__ = types.SimpleNamespace(origin=unknown.__file__)
        unknown.__cached__ = None
        authority = {
            "known": bootstrap.sealed_source_identity(known.__file__, "known")
        }
        try:
            persistent, _generated = bootstrap._capture_modules(
                authority, modules={known_name: known}
            )
            row = next(item for item in persistent if item["sys_modules_key"] == known_name)
            self.assertEqual(
                row["sealed_source_bindings"],
                {"module_file": "known", "spec_origin": "known"},
            )
            with self.assertRaises(bootstrap.FormalG0RuntimeError):
                bootstrap._capture_modules(
                    authority,
                    modules={known_name: known, unknown_name: unknown},
                )
        finally:
            os.close(known_fd)
            os.close(unknown_fd)

    def test_relative_module_origin_fails_except_explicit_sentinel(self) -> None:
        self.assertEqual(
            bootstrap._module_path_kind("spec_origin", "built-in"), "sentinel"
        )
        self.assertEqual(
            bootstrap._module_path_kind("spec_origin", "frozen"), "sentinel"
        )
        for field in bootstrap._MODULE_PATH_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(bootstrap.FormalG0RuntimeError):
                    bootstrap._module_path_kind(field, "relative/module.py")
        relative = types.ModuleType("zz_formal_g0_relative_module")
        relative.__file__ = "relative/module.py"
        relative.__spec__ = types.SimpleNamespace(origin=None)
        relative.__cached__ = None
        with self.assertRaises(bootstrap.FormalG0RuntimeError):
            bootstrap._capture_modules(
                {}, modules={relative.__name__: relative}
            )

    def test_known_and_unknown_memfd_mappings(self) -> None:
        descriptor = _sealed_memfd("known-map", b"\x7fELFsynthetic")
        try:
            locator = f"/proc/self/fd/{descriptor}"
            identity = bootstrap.sealed_source_identity(locator, "known")
            info = os.fstat(descriptor)
            device = f"{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}"
            line = (
                f"70000000-70001000 r-xp 00000000 {device} {info.st_ino} "
                "/memfd:random_non_authority_name (deleted)\n"
            )
            result = bootstrap.capture_persistent_maps(
                line, sealed_sources={"known": identity}
            )
            self.assertEqual(len(result["sealed_rows"]), 1)
            self.assertEqual(
                result["sealed_rows"][0]["sealed_source_role"], "known"
            )
            self.assertNotIn("random_non_authority_name", json.dumps(result))
            with self.assertRaises(bootstrap.FormalG0RuntimeError):
                bootstrap.capture_persistent_maps(line, sealed_sources={})
            unknown_line = line.replace(
                f" {info.st_ino} ", f" {info.st_ino + 1} "
            )
            with self.assertRaises(bootstrap.FormalG0RuntimeError):
                bootstrap.capture_persistent_maps(
                    unknown_line, sealed_sources={"known": identity}
                )
        finally:
            os.close(descriptor)

    def test_receipt_validation_is_self_hash_and_role_bound(self) -> None:
        payload = _as_role(self.probe, "primary", 998)
        bootstrap.validate_runtime_receipt(payload, expected_role="primary")
        payload["evaluator_rc"] = 1
        with self.assertRaises(bootstrap.FormalG0RuntimeError):
            bootstrap.validate_runtime_receipt(payload, expected_role="primary")

    def test_target_signal_mask_read_is_noop_and_nonempty_receipt_fails(self) -> None:
        before = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        captured = bootstrap._capture_target_signal_mask()
        after = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        self.assertEqual(before, after)
        self.assertEqual(captured["blocked_target_signals"], [])

        payload = copy.deepcopy(self.probe)
        payload["execution"]["target_signal_mask"][
            "blocked_target_signals"
        ] = [{"name": "SIGTERM", "number": int(signal.SIGTERM)}]
        _rehash(payload)
        with self.assertRaisesRegex(
            bootstrap.FormalG0RuntimeError, "target signal mask differs"
        ):
            bootstrap.validate_runtime_receipt(
                payload, expected_role="runtime_probe"
            )

    def test_frozen_runtime_is_subset_but_not_replacement_authority(self) -> None:
        actual = _as_role(self.probe, "primary", 998)
        extra = copy.deepcopy(actual["persistent_modules"][-1])
        extra["sys_modules_key"] = "zz_workload_only_alias"
        actual["persistent_modules"].append(extra)
        _rehash(actual)
        bootstrap.validate_runtime_receipt_static(
            actual, role="primary", expected_closure=self.probe
        )
        actual["persistent_modules"][0]["module_name"] += "_drift"
        _rehash(actual)
        with self.assertRaises(bootstrap.FormalG0RuntimeError):
            bootstrap.validate_runtime_receipt_static(
                actual, role="primary", expected_closure=self.probe
            )

    def test_nested_receipt_mutations_all_fail_closed(self) -> None:
        def mutate(path: list[object], value: object) -> dict[str, object]:
            payload = copy.deepcopy(self.probe)
            target: object = payload
            for item in path[:-1]:
                target = target[item]  # type: ignore[index]
            target[path[-1]] = value  # type: ignore[index]
            return _rehash(payload)

        first_module_index = next(
            index
            for index, row in enumerate(self.probe["persistent_modules"])
            if row["file_identities"]
        )
        first_module = self.probe["persistent_modules"][first_module_index]
        first_identity_key = sorted(first_module["file_identities"])[0]
        first_map = self.probe["persistent_proc_maps"]["rows"][0]
        sealed_module_index = next(
            index
            for index, row in enumerate(self.probe["persistent_modules"])
            if row["sealed_source_bindings"]
        )
        sealed_module_field = sorted(
            self.probe["persistent_modules"][sealed_module_index][
                "sealed_source_bindings"
            ]
        )[0]
        mutations = {
            "isolated": mutate(["isolated_python", "dont_write_bytecode_flag"], 0),
            "versions": mutate(["versions", "numpy"], ""),
            "sealed_stat": mutate(
                ["sealed_sources", "bootstrap", "stat"], {}
            ),
            "module_stat": mutate(
                [
                    "persistent_modules",
                    first_module_index,
                    "file_identities",
                    first_identity_key,
                    "stat",
                ],
                {},
            ),
            "module_missing_absolute": mutate(
                ["persistent_modules", first_module_index, "module_file"],
                "/definitely/absent/formal_g0_module.py",
            ),
            "genpy_random_path": copy.deepcopy(self.probe),
            "map_crossbind": mutate(
                ["persistent_proc_maps", "rows", 0, "inode"],
                first_map["inode"] + 1,
            ),
            "unknown_procfd_module": mutate(
                ["persistent_modules", sealed_module_index, sealed_module_field],
                "/proc/self/fd/995",
            ),
            "unknown_sealed_map_role": mutate(
                ["persistent_proc_maps", "sealed_rows", 0, "sealed_source_role"],
                "unknown",
            ),
            "native_not_exact": mutate(["native_loaded_elf_closure"], []),
            "execution_no_B": copy.deepcopy(self.probe),
            "outcome_crossbind": copy.deepcopy(self.probe),
        }
        mutations["genpy_random_path"]["generated_genpy_modules"][0][
            "random_path"
        ] = "/tmp/genpy_random/tmpbad.py"
        _rehash(mutations["genpy_random_path"])
        mutations["execution_no_B"]["execution"]["process_argv"].remove("-B")
        _rehash(mutations["execution_no_B"])
        mutations["outcome_crossbind"]["evaluator_called"] = True
        mutations["outcome_crossbind"]["evaluator_rc"] = 0
        _rehash(mutations["outcome_crossbind"])
        for label, payload in mutations.items():
            with self.subTest(label=label):
                with self.assertRaises(bootstrap.FormalG0RuntimeError):
                    bootstrap.validate_runtime_receipt(
                        payload, expected_role="runtime_probe"
                    )

    def test_semantic_identity_normalizes_only_role_output(self) -> None:
        primary = _as_role(self.probe, "primary", 998)
        verification = _as_role(self.probe, "verification", 999)
        self.assertEqual(
            bootstrap.runtime_semantic_identity(primary),
            bootstrap.runtime_semantic_identity(verification),
        )
        drift = copy.deepcopy(verification)
        for argv in (
            drift["execution"]["sys_argv"],
            drift["execution"]["process_argv"],
        ):
            reference_index = argv.index("--reference-bag") + 1
            argv[reference_index] = "/proc/self/fd/996"
        _rehash(drift)
        self.assertNotEqual(
            bootstrap.runtime_semantic_identity(primary),
            bootstrap.runtime_semantic_identity(drift),
        )

    def test_real_sealed_stub_dual_role_main_receipts(self) -> None:
        wrapper = (
            b"import sys\n"
            b"sys.path.insert(0, '/opt/ros/noetic/lib/python3/dist-packages')\n"
            b"import cv2, numpy, rosbag\n"
            b"def main():\n    return 0\n"
        )
        descriptors = [
            _sealed_memfd(
                "stub-python", Path("/usr/bin/python3.8").read_bytes(), executable=True
            ),
            _sealed_memfd("stub-bootstrap", SOURCE.read_bytes()),
            _sealed_memfd("stub-wrapper", wrapper),
            _sealed_memfd("stub-base", b"# base\n"),
            _sealed_memfd("stub-core", b"# core\n"),
            _sealed_memfd("stub-reference", b"reference\n"),
        ]
        python_fd, bootstrap_fd, wrapper_fd, base_fd, core_fd, reference_fd = descriptors
        receipts: dict[str, dict[str, object]] = {}
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for role in ("primary", "verification"):
                    role_dir = root / role
                    role_dir.mkdir()
                    role_fd = os.open(role_dir, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        environment = _environment_template(role)
                        replacements = {
                            "${EPOCH_WRAPPER_PROCFD}": f"/proc/self/fd/{wrapper_fd}",
                            "${EVALUATOR_BASE_PROCFD}": f"/proc/self/fd/{base_fd}",
                            "${TRAJECTORY_CORE_PROCFD}": f"/proc/self/fd/{core_fd}",
                            "${ROLE_OUTPUT_DIRFD}": f"/proc/self/fd/{role_fd}",
                        }
                        for key, value in list(environment.items()):
                            for original, replacement in replacements.items():
                                value = value.replace(original, replacement)
                            environment[key] = value
                        process = subprocess.run(
                            [
                                f"/proc/self/fd/{python_fd}",
                                "-I",
                                "-B",
                                f"/proc/self/fd/{bootstrap_fd}",
                                "--reference-bag",
                                f"/proc/self/fd/{reference_fd}",
                                "--reference-topic",
                                "/reference",
                                "--output-dir",
                                f"/proc/self/fd/{role_fd}",
                            ],
                            env=environment,
                            pass_fds=tuple([*descriptors, role_fd]),
                            check=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30,
                        )
                    finally:
                        os.close(role_fd)
                    self.assertEqual(
                        process.returncode,
                        0,
                        process.stderr.decode("utf-8", "replace"),
                    )
                    receipt_path = role_dir / bootstrap.RECEIPT_FILENAME
                    raw = receipt_path.read_bytes()
                    receipt = json.loads(raw)
                    self.assertEqual(raw, bootstrap.canonical_json_bytes(receipt))
                    bootstrap.validate_runtime_receipt(
                        receipt, expected_role=role
                    )
                    receipts[role] = receipt
                self.assertEqual(
                    bootstrap.runtime_semantic_identity(receipts["primary"]),
                    bootstrap.runtime_semantic_identity(receipts["verification"]),
                )
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    def test_static_runtime_apis_start_zero_subprocesses(self) -> None:
        primary = _as_role(self.probe, "primary", 998)
        verification = _as_role(self.probe, "verification", 999)
        with mock.patch.object(
            bootstrap.subprocess,
            "run",
            side_effect=AssertionError("static API started a process"),
        ), mock.patch.object(
            bootstrap.subprocess,
            "Popen",
            side_effect=AssertionError("static API started a process"),
        ):
            bootstrap.validate_freeze_runtime_static(self.probe)
            bootstrap.validate_runtime_receipt_static(
                primary, role="primary", expected_closure=self.probe
            )
            bootstrap.runtime_semantic_identity(primary)
            bootstrap.runtime_semantic_identity(verification)

    def test_all_four_public_runtime_apis_direct(self) -> None:
        bootstrap.validate_freeze_runtime_static(self.probe)
        primary = _as_role(self.probe, "primary", 998)
        bootstrap.validate_runtime_receipt_static(
            primary, role="primary", expected_closure=self.probe
        )
        bootstrap.runtime_semantic_identity(primary)
        with tempfile.NamedTemporaryFile(suffix=".bag") as bag:
            _write_reference_bag(bag.name)
            captured = bootstrap.capture_freeze_runtime(
                root=ROOT,
                python=Path("/usr/bin/python3.8"),
                wrapper=ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py",
                base=ROOT / "scripts/evaluate_vins_common_support.py",
                core=ROOT / "scripts/trajectory_eval_core.py",
                reference_bag=Path(bag.name),
                reference_topic="/reference",
                environment_template=_environment_template("primary"),
            )
        bootstrap.validate_freeze_runtime_static(captured)

    def test_exclusive_receipt_write_refuses_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory_fd = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY)
            try:
                bootstrap.write_runtime_receipt_exclusive(directory_fd, {"a": 1})
                with self.assertRaises(FileExistsError):
                    bootstrap.write_runtime_receipt_exclusive(directory_fd, {"a": 2})
            finally:
                os.close(directory_fd)
            self.assertEqual(
                (Path(temporary) / bootstrap.RECEIPT_FILENAME).read_bytes(),
                bootstrap.canonical_json_bytes({"a": 1}),
            )

    def test_isolated_sealed_runtime_probe_does_not_call_evaluator(self) -> None:
        payload = self.probe
        bootstrap.validate_runtime_receipt(payload, expected_role="runtime_probe")
        self.assertFalse(payload["evaluator_called"])
        self.assertIsNone(payload["evaluator_rc"])
        self.assertEqual(payload["isolated_python"]["isolated_flag"], 1)
        self.assertEqual(payload["isolated_python"]["dont_write_bytecode_flag"], 1)
        self.assertEqual(payload["isolated_python"]["hash_randomization_flag"], 1)
        self.assertIn("IGNORED_BY_-I", payload["isolated_python"]["hash_seed_policy"])
        self.assertEqual(payload["execution"]["process_argv"][1:3], ["-I", "-B"])
        self.assertEqual(
            payload["execution"]["target_signal_mask"],
            {
                "query": bootstrap._TARGET_SIGNAL_QUERY,
                "target_signals": [
                    {"name": "SIGHUP", "number": int(signal.SIGHUP)},
                    {"name": "SIGINT", "number": int(signal.SIGINT)},
                    {"name": "SIGTERM", "number": int(signal.SIGTERM)},
                ],
                "blocked_target_signals": [],
            },
        )
        self.assertEqual(payload["versions"]["numpy"], "1.17.4")
        self.assertTrue(payload["persistent_proc_maps"]["rows"])


if __name__ == "__main__":
    unittest.main()
