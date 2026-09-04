from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import allocate_p07_backend_replacement_v1 as allocator
from scripts import check_b0_vins_origin_identity_v1 as b0_identity
from scripts import p07_backend_replay_common_v1 as common
from scripts import run_p07_backend_replay_adapter_v1 as adapter
from scripts import run_p07_backend_replay_job_v1 as job
from scripts import run_p07_backend_serial_queue_v1 as controller


class P07BackendRuntimeIdentityV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_canonical_symlink_chain_and_target_are_both_frozen(self) -> None:
        target_root = self.root / "mounted-datasets"
        target = target_root / "fjord/frozen.bag"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"frozen play input\n")
        (self.root / "datasets").symlink_to(target_root, target_is_directory=True)
        final_link = self.root / "datasets/fjord/canonical.bag"
        final_link.symlink_to("frozen.bag")
        digest = common.sha256(target)
        record = common.capture_canonical_input_identity(
            self.root,
            "datasets/fjord/canonical.bag",
            expected_sha256=digest,
            verify_sha256=True,
        )
        self.assertEqual(record["path_kind"], "CANONICAL_SYMLINK_TARGET")
        self.assertEqual(len(record["symlink_components"]), 2)
        common.revalidate_canonical_input_identity(
            self.root, record, verify_sha256=False
        )

        final_link.unlink()
        replacement = target_root / "fjord/replacement.bag"
        replacement.write_bytes(b"frozen play input\n")
        final_link.symlink_to("replacement.bag")
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "identity drift"
        ):
            common.revalidate_canonical_input_identity(
                self.root, record, verify_sha256=False
            )

    def test_direct_formal_read_rejects_nested_symlink_ancestor(self) -> None:
        target = self.root / "mounted-formal"
        target.mkdir()
        (target / "lock.json").write_text("{}\n", encoding="utf-8")
        papers = self.root / "papers"
        papers.mkdir()
        (papers / "nested").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "read direct"
        ):
            common.read_direct_workspace_bytes(
                self.root,
                "papers/nested/lock.json",
                label="fixture formal lock",
            )

    def test_sealed_file_consumption_defeats_mutate_use_restore(self) -> None:
        source = self.root / "runtime.py"
        original = b"ORIGINAL_LOCKED_BYTES\n"
        source.write_bytes(original)
        original_stat = source.stat()
        original_mode = original_stat.st_mode & 0o777
        with common.SealedFileLease(
            source,
            common.sha256(source),
            role="fixture_runtime",
            label="fixture runtime",
        ) as lease:
            self.assertIsNotNone(lease.fd)
            source.write_bytes(b"ATTACKED_WORKSPACE_BYTES\n")
            completed = subprocess.run(
                [
                    "python3",
                    "-c",
                    "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
                    lease.proc_path,
                ],
                pass_fds=(int(lease.fd),),
                capture_output=True,
                check=False,
            )
            source.write_bytes(original)
            os.utime(
                source,
                ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
            )
            os.chmod(source, 0o600)
            os.chmod(source, original_mode)
            for _ in range(10000):
                if source.stat().st_ctime_ns != original_stat.st_ctime_ns:
                    break
                os.chmod(source, 0o600)
                os.chmod(source, original_mode)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, original)
            self.assertEqual(source.stat().st_mtime_ns, original_stat.st_mtime_ns)
            self.assertNotEqual(source.stat().st_ctime_ns, original_stat.st_ctime_ns)
            with self.assertRaisesRegex(
                common.BackendReplayViolation, "identity or hash changed"
            ):
                lease.verify_unchanged()

    def test_sealed_file_consumption_defeats_path_swap(self) -> None:
        source = self.root / "runner.sh"
        displaced = self.root / "runner.original"
        original = b"#!/usr/bin/env bash\necho original\n"
        source.write_bytes(original)
        with common.SealedFileLease(
            source,
            common.sha256(source),
            role="fixture_runner",
            label="fixture runner",
        ) as lease:
            self.assertIsNotNone(lease.fd)
            source.rename(displaced)
            source.write_bytes(b"#!/usr/bin/env bash\necho attacked\n")
            completed = subprocess.run(
                ["bash", lease.proc_path],
                pass_fds=(int(lease.fd),),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout.strip(), "original")
            with self.assertRaisesRegex(
                common.BackendReplayViolation, "identity or hash changed"
            ):
                lease.verify_unchanged()

    def test_sealed_bootstrap_never_falls_back_to_workspace_module(self) -> None:
        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "unbound_payload.py").write_text(
            "raise RuntimeError('workspace fallback executed')\n", encoding="utf-8"
        )
        bootstrap_bytes = (
            common.ROOT / "scripts/p07_backend_sealed_runtime_v1.py"
        ).read_bytes()
        target_bytes = (
            b"def main():\n"
            b"    import scripts.unbound_payload\n"
            b"    return 0\n"
        )
        with common.SealedBytesLease(
            bootstrap_bytes,
            role="sealed_runtime_bootstrap",
            label="sealed bootstrap fixture",
        ) as bootstrap:
            with common.SealedBytesLease(
                target_bytes,
                role="fixture_target",
                label="sealed target fixture",
            ) as target:
                self.assertIsNotNone(bootstrap.fd)
                self.assertIsNotNone(target.fd)
                entries = [
                    {
                        "role": "sealed_runtime_bootstrap",
                        "path": "scripts/p07_backend_sealed_runtime_v1.py",
                        "sha256": bootstrap.sha256,
                        "size_bytes": bootstrap.size_bytes,
                        "fd": int(bootstrap.fd),
                        "module": "scripts.p07_backend_sealed_runtime_v1",
                        "memfd_name": bootstrap.memfd_name,
                    },
                    {
                        "role": "fixture_target",
                        "path": "scripts/fixture_target.py",
                        "sha256": target.sha256,
                        "size_bytes": target.size_bytes,
                        "fd": int(target.fd),
                        "module": "scripts.fixture_target",
                        "memfd_name": target.memfd_name,
                    },
                ]
                payload = {
                    "schema_version": common.SEALED_RUNTIME_SCHEMA,
                    "execution_lock_sha256": "a" * 64,
                    "entries": entries,
                }
                environment = dict(os.environ)
                environment[common.SEALED_RUNTIME_ENVIRONMENT_KEY] = json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                )
                completed = subprocess.run(
                    [
                        "python3",
                        "-I",
                        bootstrap.proc_path,
                        "scripts.fixture_target",
                    ],
                    cwd=self.root,
                    env=environment,
                    pass_fds=(int(bootstrap.fd), int(target.fd)),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("No module named 'scripts.unbound_payload'", completed.stderr)
                self.assertNotIn("workspace fallback executed", completed.stderr)

    def test_sealed_interpreter_runs_bootstrap_with_sanitized_environment(self) -> None:
        bootstrap_path = common.ROOT / "scripts/p07_backend_sealed_runtime_v1.py"
        target_bytes = (
            b"import os,sys\n"
            b"def main():\n"
            b"    print(sys.executable)\n"
            b"    print(os.environ.get('PYTHONPATH', 'ABSENT'))\n"
            b"    print(os.environ['FIXTURE_ALLOWED'])\n"
            b"    return 0\n"
        )
        with common.SealedFileLease(
            common.PYTHON_INTERPRETER,
            common.sha256(common.PYTHON_INTERPRETER),
            role="python_interpreter",
            label="sealed Python interpreter fixture",
        ) as interpreter:
            with common.SealedFileLease(
                bootstrap_path,
                common.sha256(bootstrap_path),
                role="sealed_runtime_bootstrap",
                label="sealed bootstrap fixture",
            ) as bootstrap:
                with common.SealedBytesLease(
                    target_bytes,
                    role="fixture_target",
                    label="sealed target fixture",
                ) as target:
                    entries = {
                        "python_interpreter": {
                            "role": "python_interpreter",
                            "path": str(common.PYTHON_INTERPRETER),
                            "sha256": interpreter.before.sha256,
                            "size_bytes": interpreter.before.size_bytes,
                            "fd": int(interpreter.fd),
                            "module": None,
                            "memfd_name": interpreter.memfd_name,
                        },
                        "sealed_runtime_bootstrap": {
                            "role": "sealed_runtime_bootstrap",
                            "path": "scripts/p07_backend_sealed_runtime_v1.py",
                            "sha256": bootstrap.before.sha256,
                            "size_bytes": bootstrap.before.size_bytes,
                            "fd": int(bootstrap.fd),
                            "module": "scripts.p07_backend_sealed_runtime_v1",
                            "memfd_name": bootstrap.memfd_name,
                        },
                        "fixture_target": {
                            "role": "fixture_target",
                            "path": "scripts/fixture_target.py",
                            "sha256": target.sha256,
                            "size_bytes": target.size_bytes,
                            "fd": int(target.fd),
                            "module": "scripts.fixture_target",
                            "memfd_name": target.memfd_name,
                        },
                    }
                    context = common.RuntimeConsumptionContext(entries, "a" * 64)
                    environment = common.sealed_runtime_environment(
                        context, extra={"FIXTURE_ALLOWED": "yes"}
                    )
                    self.assertNotIn("PYTHONPATH", environment)
                    self.assertNotIn("PYTHONHOME", environment)
                    self.assertFalse(any(key.startswith("LD_") for key in environment))
                    completed = subprocess.run(
                        context.python_argv("fixture_target", []),
                        cwd=self.root,
                        env=environment,
                        pass_fds=context.pass_fds,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    lines = completed.stdout.splitlines()
                    self.assertEqual(lines[0], interpreter.proc_path)
                    self.assertEqual(lines[1:], ["ABSENT", "yes"])

    def test_sealed_environment_rejects_loader_or_python_path_override(self) -> None:
        context = common.RuntimeConsumptionContext({}, "a" * 64)
        for key in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    common.BackendReplayViolation, "forbidden overrides"
                ):
                    common.sealed_runtime_environment(
                        context, extra={key: "/tmp/attack"}
                    )

    def test_sanitized_child_environment_has_no_runtime_authority(self) -> None:
        environment = common.sanitized_child_environment(
            extra={"FIXTURE_ALLOWED": "yes"}
        )
        self.assertEqual(environment["FIXTURE_ALLOWED"], "yes")
        self.assertNotIn(common.SEALED_RUNTIME_ENVIRONMENT_KEY, environment)
        self.assertNotIn(common.SEALED_EXECUTION_LOCK_HASH_KEY, environment)
        for key in ("LD_PRELOAD", "PYTHONPATH"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    common.BackendReplayViolation, "forbidden overrides"
                ):
                    common.sanitized_child_environment(
                        extra={key: "/tmp/attack"}
                    )

    def test_runtime_import_closure_rejects_existing_unbound_module(self) -> None:
        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir()
        bound = scripts_dir / "bound.py"
        unbound = scripts_dir / "unbound.py"
        bound.write_text("import scripts.unbound\n", encoding="utf-8")
        unbound.write_text("VALUE = 'workspace attack'\n", encoding="utf-8")
        bindings = {
            "bound": {
                "path": "scripts/bound.py",
                "sha256": common.sha256(bound),
                "size_bytes": bound.stat().st_size,
            }
        }
        with self.assertRaisesRegex(
            common.BackendReplayViolation, "transitive import closure is incomplete"
        ):
            common.validate_runtime_import_closure(self.root, bindings)

    def test_external_runtime_rejects_symlink_or_non_elf_semantics(self) -> None:
        interpreter_link = self.root / "python-interpreter-link"
        interpreter_link.symlink_to(common.PYTHON_INTERPRETER)
        linked_record = {
            "path": str(interpreter_link),
            "sha256": common.sha256(interpreter_link),
            "size_bytes": interpreter_link.stat().st_size,
        }
        with mock.patch.object(
            common,
            "EXTERNAL_RUNTIME_BINDING_PATHS",
            {"python_interpreter": interpreter_link},
        ):
            with self.assertRaisesRegex(
                common.BackendReplayViolation, "not canonical"
            ):
                common._validate_external_runtime_bindings(  # noqa: SLF001
                    {"external_runtime_bindings": {"python_interpreter": linked_record}}
                )

        non_elf = self.root / "fake-python"
        non_elf.write_bytes(b"#!/bin/sh\nexit 0\n")
        non_elf.chmod(0o755)
        non_elf_record = {
            "path": str(non_elf),
            "sha256": common.sha256(non_elf),
            "size_bytes": non_elf.stat().st_size,
        }
        with mock.patch.object(
            common,
            "EXTERNAL_RUNTIME_BINDING_PATHS",
            {"python_interpreter": non_elf},
        ):
            with self.assertRaisesRegex(
                common.BackendReplayViolation, "ELF semantics"
            ):
                common._validate_external_runtime_bindings(  # noqa: SLF001
                    {"external_runtime_bindings": {"python_interpreter": non_elf_record}}
                )

    def test_formal_runners_do_not_consume_catkin_setup_paths(self) -> None:
        common.validate_frozen_ros_platform()
        for relative in (
            "scripts/run_ntnu_vins_eval.sh",
            "scripts/run_aqualoc_archaeo_vins_eval.sh",
            "scripts/run_aqualoc_real_vins_eval.sh",
            "scripts/run_afrl_cave_vins_eval.sh",
        ):
            text = (common.ROOT / relative).read_text(encoding="utf-8")
            formal = text.index('${BACKEND_REPLAY_ONLY:-0}')
            source = text.index("source /opt/ros/noetic/setup.bash")
            branch = text.rfind("else", formal, source)
            self.assertGreater(branch, formal, relative)
            self.assertIn("AQUAFE_P07_FROZEN_ROS_ENV", text[formal:source])
            self.assertIn("AQUAFE_P07_PYTHON_INTERPRETER", text[formal:source])
        replay_text = (
            common.ROOT / "scripts/run_p07_backend_replay_only_v1.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("setup.bash", replay_text)
        self.assertIn('"$AQUAFE_P07_PYTHON_INTERPRETER" "$AQUAFE_P07_ROSCORE"', replay_text)
        self.assertIn('"$AQUAFE_P07_PYTHON_INTERPRETER" "$AQUAFE_P07_ROSBAG"', replay_text)

    def test_setup_lease_detects_same_inode_restore_with_original_mtime(self) -> None:
        setup = self.root / "setup.bash"
        original = b"export FIXTURE=original\n"
        setup.write_bytes(original)
        before = setup.stat()
        with common.SealedFileLease(
            setup,
            common.sha256(setup),
            role="vins_devel_setup_fixture",
            label="VINS setup fixture",
        ) as lease:
            setup.write_bytes(b"export FIXTURE=attacked\n")
            setup.write_bytes(original)
            os.utime(setup, ns=(before.st_atime_ns, before.st_mtime_ns))
            setup.chmod(0o600)
            setup.chmod(before.st_mode & 0o777)
            for _ in range(10000):
                if setup.stat().st_ctime_ns != lease.before.ctime_ns:
                    break
                setup.chmod(0o600)
                setup.chmod(before.st_mode & 0o777)
            self.assertNotEqual(setup.stat().st_ctime_ns, lease.before.ctime_ns)
            with self.assertRaisesRegex(
                common.BackendReplayViolation, "identity or hash changed"
            ):
                lease.verify_unchanged()

    def test_formal_harbor_missing_cache_exits_before_converter(self) -> None:
        runner_source = (
            common.ROOT / "scripts/run_aqualoc_real_vins_eval.sh"
        ).read_text(encoding="utf-8")
        runner_source = runner_source.replace(
            'ROOT="/home/ma/AQUA-FE_WS"', f'ROOT="{self.root}"', 1
        ).replace(
            'source "$VINS_WS/devel/setup.bash"',
            'echo "SETUP_PATH_CONSUMED" >&2; exit 97',
            1,
        )
        runner = self.root / "harbor_runner.sh"
        runner.write_text(runner_source, encoding="utf-8")
        runner.chmod(0o755)
        raw_tar = self.root / "raw.tar.gz"
        ground_truth = self.root / "groundtruth.txt"
        missing_cache = self.root / "missing-cache.bag"
        raw_tar.write_bytes(b"synthetic raw archive marker\n")
        ground_truth.write_text("synthetic reference marker\n", encoding="utf-8")
        with common.SealedFileLease(
            common.PYTHON_INTERPRETER,
            common.sha256(common.PYTHON_INTERPRETER),
            role="python_interpreter",
            label="sealed Python interpreter fixture",
        ) as interpreter:
            environment = common.sanitized_child_environment(
                extra={
                    "BACKEND_REPLAY_ONLY": "1",
                    "AQUAFE_P07_FROZEN_ROS_ENV": "1",
                    "AQUAFE_P07_PYTHON_INTERPRETER": interpreter.proc_path,
                    "RAW_TAR": str(raw_tar),
                    "GT_TXT": str(ground_truth),
                    "RAW_BAG": str(missing_cache),
                    "RUN_VINS": "0",
                    "RUN_EVALUATION": "0",
                    "EXPORT_FEATURES": "0",
                    "FORCE_EXPORT": "0",
                    "FORCE_RAW": "0",
                }
            )
            environment.update(common.FROZEN_ROS_ENVIRONMENT)
            completed = subprocess.run(
                ["bash", str(runner), "external", "1", "2", "klt", "2"],
                cwd=self.root,
                env=environment,
                pass_fds=(int(interpreter.fd),),
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 66, completed.stderr)
        self.assertIn("pre-materialized AQUALOC harbor bag", completed.stderr)
        self.assertNotIn("SETUP_PATH_CONSUMED", completed.stderr)
        self.assertFalse(missing_cache.exists())

    def test_b0_identity_hashes_the_sealed_binary_not_workspace_path(self) -> None:
        canonical_binary = common.EXTERNAL_RUNTIME_BINDING_PATHS["vins_binary"]
        with common.SealedFileLease(
            canonical_binary,
            common.sha256(canonical_binary),
            role="vins_binary",
            label="sealed VINS binary fixture",
        ) as binary:
            decision = b0_identity.evaluate_b0_identity(
                contract_path=(
                    common.BUNDLE / "backend_quality_contract_v1.json"
                ),
                vins_workspace=common.VINS_ORIGIN,
                backend_root=(
                    common.VINS_ORIGIN / "src/VINS-Fusion-master"
                ),
                binary=Path(binary.proc_path),
                binary_authority_path=canonical_binary,
            )
        self.assertTrue(decision["contract_pass"], decision["reasons"])
        self.assertTrue(str(decision["binary"]).startswith("/proc/self/fd/"))
        self.assertEqual(
            decision["binary_authority_path"], str(canonical_binary)
        )

    def test_linux_exec_and_loader_consume_sealed_procfd_runtime(self) -> None:
        """Synthetic kernel check only: no ROS or VINS process is started."""

        binary_path = Path("/usr/bin/sleep")
        library_candidates = []
        for directory, pattern in (
            (Path("/lib/x86_64-linux-gnu"), "libz.so.*"),
            (Path("/lib/x86_64-linux-gnu"), "liblzma.so.*"),
        ):
            matches = [path for path in directory.glob(pattern) if not path.is_symlink()]
            self.assertTrue(matches, f"missing synthetic loader fixture: {pattern}")
            library_candidates.append(sorted(matches)[-1])
        with common.SealedFileLease(
            binary_path,
            common.sha256(binary_path),
            role="vins_binary",
            label="synthetic sealed executable",
        ) as binary:
            with common.SealedFileLease(
                library_candidates[0],
                common.sha256(library_candidates[0]),
                role="vins_shared_library",
                label="synthetic sealed library one",
            ) as library_one:
                with common.SealedFileLease(
                    library_candidates[1],
                    common.sha256(library_candidates[1]),
                    role="camera_models_shared_library",
                    label="synthetic sealed library two",
                ) as library_two:
                    fds = (
                        int(binary.fd),
                        int(library_one.fd),
                        int(library_two.fd),
                    )
                    environment = dict(os.environ)
                    environment["LD_PRELOAD"] = (
                        f"{library_one.proc_path}:{library_two.proc_path}"
                    )
                    process = subprocess.Popen(
                        [binary.proc_path, "5"],
                        env=environment,
                        pass_fds=fds,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    try:
                        deadline = time.monotonic() + 2.0
                        maps = ""
                        exe_link = ""
                        while time.monotonic() < deadline:
                            exe_link = os.readlink(f"/proc/{process.pid}/exe")
                            maps = Path(f"/proc/{process.pid}/maps").read_text(
                                encoding="utf-8"
                            )
                            if (
                                "memfd:aquafe_p07_vins_shared_library" in maps
                                and "memfd:aquafe_p07_camera_models_shared_library"
                                in maps
                            ):
                                break
                            time.sleep(0.01)
                        self.assertIn("memfd:aquafe_p07_vins_binary", exe_link)
                        self.assertEqual(
                            common.sha256(Path(f"/proc/{process.pid}/exe")),
                            binary.before.sha256,
                        )
                        self.assertIn(
                            "memfd:aquafe_p07_vins_shared_library", maps
                        )
                        self.assertIn(
                            "memfd:aquafe_p07_camera_models_shared_library", maps
                        )
                    finally:
                        process.terminate()
                        process.wait(timeout=5)

    def test_canonical_logs_mount_symlink_remains_freezable(self) -> None:
        mounted_logs = self.root / "mounted-logs"
        bag = mounted_logs / "frontend/features.bag"
        bag.parent.mkdir(parents=True)
        bag.write_bytes(b"frozen frontend bag\n")
        (self.root / "logs").symlink_to(mounted_logs, target_is_directory=True)
        record = common.capture_canonical_input_identity(
            self.root,
            "logs/frontend/features.bag",
            expected_sha256=common.sha256(bag),
            verify_sha256=True,
        )
        self.assertEqual(record["path_kind"], "CANONICAL_SYMLINK_TARGET")
        self.assertEqual(record["symlink_components"][0]["path"], "logs")
        common.revalidate_canonical_input_identity(
            self.root, record, verify_sha256=False
        )

    def test_b0_contract_binds_absolute_camera_window_and_detects_bytes(self) -> None:
        play = self.root / "datasets/p07_b0_cache/window.bag"
        play.parent.mkdir(parents=True)
        play.write_bytes(b"synthetic rosbag bytes\n")
        evidence = self.root / "papers/p07/window_evidence.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(
            json.dumps(
                {
                    "camera_topic": "/cam0/image_raw",
                    "start_ros_time_ns": 1_700_000_000_000_000_000,
                    "end_ros_time_ns": 1_700_000_001_000_000_000,
                }
            ),
            encoding="utf-8",
        )
        window_id = "ntnu:fjord_6:fixture"
        provenance_hash = "a" * 64
        row = {
            "queue_index": "1",
            "run_id": "fixture-b0",
            "window_id": window_id,
            "dataset_family": "ntnu",
            "sequence": "fjord_6",
            "runner_start": "10",
            "runner_end_or_duration": "20",
            "runner_unit": "second",
            "arm": common.B0_ARM,
            "source_run_id": f"B0_NATIVE_DATA:{window_id}",
            "source_provenance_kind": "B0_NATIVE_DATA_IDENTITY_V1",
            "source_provenance_hash": provenance_hash,
        }
        identity = common.capture_canonical_input_identity(
            self.root,
            play.relative_to(self.root).as_posix(),
            expected_sha256=common.sha256(play),
            verify_sha256=True,
        )
        entry = {
            "play_input_id": "b" * 64,
            "window_id": window_id,
            "dataset_family": "ntnu",
            "sequence": "fjord_6",
            "runner_start": "10",
            "runner_end_or_duration": "20",
            "runner_unit": "second",
            "expected_sha256": common.sha256(play),
            "source_provenance_hash": provenance_hash,
            "path_identity": identity,
            "derivation": {
                "kind": "DIRECT_RAW_WINDOW_PLAYBACK",
                "source_raw_path": play.relative_to(self.root).as_posix(),
                "source_raw_sha256": common.sha256(play),
                "derivation_hash": "c" * 64,
            },
            "evaluation_window": {
                "start_ros_time_ns": 1_700_000_000_000_000_000,
                "end_ros_time_ns": 1_700_000_001_000_000_000,
                "camera_topic": "/cam0/image_raw",
                "stamp_source": "sensor_msgs/Image.header.stamp",
                "boundary_rule": (
                    "FIRST_INCLUDED_CAMERA_STAMP_TO_LAST_INCLUDED_CAMERA_STAMP_INCLUSIVE"
                ),
                "derivation_evidence": {
                    "path": evidence.relative_to(self.root).as_posix(),
                    "sha256": common.sha256(evidence),
                    "size_bytes": evidence.stat().st_size,
                },
            },
        }
        binding = {
            "queue_index": 1,
            "run_id": row["run_id"],
            "play_input_id": entry["play_input_id"],
            "window_id": window_id,
            "dataset_family": "ntnu",
            "sequence": "fjord_6",
            "runner_start": "10",
            "runner_end_or_duration": "20",
            "runner_unit": "second",
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": provenance_hash,
        }
        payload = {
            "schema_version": common.B0_PLAY_INPUTS_SCHEMA,
            "status": common.B0_PLAY_INPUTS_STATUS,
            "materialization_lock_hash": "d" * 64,
            "materialization_intent_hash": "e" * 64,
            "materialization_receipt_hash": "f" * 64,
            "materialization_receipt": {
                "path": common.B0_MATERIALIZATION_RECEIPT_PATH,
                "sha256": "9" * 64,
                "size_bytes": 123,
            },
            "entries": [entry],
            "queue_bindings": [binding],
            "policy": {
                "all_b0_queue_rows_bound": True,
                "full_sha256_before_and_after_each_replay": True,
                "path_link_target_identity_before_and_after_each_replay": True,
                "preparation_must_not_create_or_replace_play_input": True,
                "derived_inputs_materialized_before_execution_lock": True,
                "trajectory_values_interpreted": False,
            },
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": common.B0_OUTCOME_BOUNDARY,
        }
        payload[common.B0_PLAY_INPUTS_SELF_HASH] = common.canonical_json_hash(
            payload, common.B0_PLAY_INPUTS_SELF_HASH
        )
        common.validate_b0_play_inputs_shape(payload, [row])
        for start_ns, end_ns in (
            (1, 2),
            (True, 1_700_000_001_000_000_000),
            ("1700000000000000000", 1_700_000_001_000_000_000),
            (
                1_700_000_000_000_000_000,
                common.MAX_ROS1_TIME_NS + 1,
            ),
        ):
            attacked = json.loads(json.dumps(payload))
            attacked_window = attacked["entries"][0]["evaluation_window"]
            attacked_window["start_ros_time_ns"] = start_ns
            attacked_window["end_ros_time_ns"] = end_ns
            attacked[common.B0_PLAY_INPUTS_SELF_HASH] = (
                common.canonical_json_hash(
                    attacked, common.B0_PLAY_INPUTS_SELF_HASH
                )
            )
            with self.assertRaisesRegex(
                common.BackendReplayViolation,
                "exact integers|absolute in-range",
            ):
                common.validate_b0_play_inputs_shape(attacked, [row])
        lock = {"b0_play_inputs": payload}
        report = common.revalidate_b0_play_input(
            self.root, lock, row, phase="PRE_REPLAY_LAUNCH"
        )
        self.assertTrue(report["content_sha256_reverified"])
        self.assertEqual(
            report["evaluation_window"]["start_ros_time_ns"],
            1_700_000_000_000_000_000,
        )

        play.write_bytes(b"mutated rosbag bytes\n")
        with self.assertRaises(common.BackendReplayViolation):
            common.revalidate_b0_play_input(
                self.root, lock, row, phase="POST_REPLAY"
            )

    def test_adapter_free_replacement_requires_durable_boundary_proof(self) -> None:
        payload = {
            "schema_version": allocator.INFRASTRUCTURE_EVIDENCE_SCHEMA,
            "status": "REPLACEMENT_ELIGIBLE",
            "queue_index": 7,
            "run_id": "fixture-run",
            "failure_class": "INFRASTRUCTURE",
            "failure_code": "EXECUTION_ENVELOPE_FAILURE",
            "infrastructure_category": "FILE_NOT_FOUND",
            "failure_phase": "PRE_ADAPTER",
            "infrastructure_failure": True,
            "replacement_eligible": True,
            "algorithmic_slot_consumed": False,
            "slot_consumption_boundary_crossed": False,
            "trajectory_outcome_read": False,
            "evaluation_invoked": False,
            "audit_artifact_created": False,
            "adapter_result": None,
            "pre_adapter_without_result_proven": True,
            "boundary_may_have_been_crossed": False,
            "active_recorded_process": False,
            "attempt_intent": {"path": "intent", "sha256": "a" * 64, "size_bytes": 1},
            "attempt_state_journal": {"path": "state", "sha256": "b" * 64, "size_bytes": 1},
        }
        allocator.validate_failure_evidence(
            payload, queue_index=7, failed_run_id="fixture-run"
        )
        payload["boundary_may_have_been_crossed"] = True
        with self.assertRaisesRegex(
            allocator.ReplacementAllocationError, "durable pre-adapter proof"
        ):
            allocator.validate_failure_evidence(
                payload, queue_index=7, failed_run_id="fixture-run"
            )

    def test_failed_popen_closes_launch_pending_journal(self) -> None:
        journal = self.root / "attempt_state_v1.jsonl"
        with mock.patch.object(
            subprocess, "Popen", side_effect=FileNotFoundError("fixture")
        ):
            with self.assertRaises(FileNotFoundError):
                adapter._run_process(
                    ["missing-fixture"],
                    environment={},
                    log=io.BytesIO(),
                    timeout_s=1,
                    pass_fds=(),
                    state_journal=journal,
                    state_context={"queue_index": 7, "run_id": "fixture-run"},
                    phase="PREPARATION",
                )
        events = common.read_hash_chain_jsonl(journal)
        self.assertEqual(
            [event["state"] for event in events],
            ["PROCESS_LAUNCH_PENDING", "PROCESS_LAUNCH_FAILED"],
        )
        analysis = common.analyze_attempt_state_events(
            events, queue_index=7, run_id="fixture-run"
        )
        self.assertFalse(analysis["boundary_may_have_been_crossed"])
        self.assertEqual(analysis["unpaired_launch_pending"], [])

    def test_serial_controller_stops_after_preflight_waiting(self) -> None:
        queue = self.root / "queue.csv"
        allocation = self.root / "allocation.csv"
        execution_lock = self.root / "execution_lock.json"
        for path in (queue, allocation, execution_lock):
            path.write_text("fixture\n", encoding="utf-8")
        action = {
            "schema_version": controller.SCHEMA,
            "status": "READY_NEXT_JOB",
            "queue_index": 1,
            "run_id": "fixture",
            "job_argv": [
                "python3",
                controller.JOB_ENTRYPOINT,
                "--queue-index",
                "1",
                "--execution-lock",
                common.DEFAULT_EXECUTION_LOCK_RELATIVE,
            ],
            "execution_lock_path": execution_lock.name,
            "execution_lock_sha256": common.sha256(execution_lock),
            "queue_path": queue.name,
            "allocation_path": allocation.name,
        }
        waiting = subprocess.CompletedProcess(
            action["job_argv"], 75, stdout="", stderr="P07_BACKEND_WAITING"
        )
        runtime = mock.Mock()
        runtime.pass_fds = ()
        runtime.environment.return_value = {}
        runtime.python_argv.return_value = [
            "python3",
            "-I",
            "/proc/self/fd/17",
            "scripts.run_p07_backend_replay_job_v1",
            *action["job_argv"][2:],
        ]
        bundle = mock.MagicMock()
        bundle.__enter__.return_value = runtime
        with mock.patch.object(subprocess, "run", return_value=waiting) as runner:
            with mock.patch.object(common, "validate_execution_lock", return_value={}):
                with mock.patch.object(
                    common, "SealedRuntimeBundle", return_value=bundle
                ):
                    result = controller.run_one(action, root=self.root)
        self.assertEqual(result["status"], "STOP_PREFLIGHT_WAITING")
        runner.assert_called_once()
        self.assertIn("--preflight-only", runner.call_args.args[0])
        self.assertIn("-I", runner.call_args.args[0])
        self.assertNotIn(controller.JOB_ENTRYPOINT, runner.call_args.args[0])

    def test_bare_completed_registry_event_never_consumes_a_slot(self) -> None:
        row = {
            "queue_index": "1",
            "run_id": "fixture",
            "window_id": "ntnu:fjord_6:fixture",
            "arm": common.B0_ARM,
            "expected_run_dir": "logs/fixture",
            "expected_attempt_dir": "papers/p07/fixture_attempt01",
        }
        for terminal in (
            {"status": "COMPLETED"},
            {
                "status": "COMPLETED",
                "run_id": "fixture",
                "infrastructure_failure": "false",
                "replay_hard_failure": "false",
                "algorithm_hard_failure": "false",
            },
        ):
            with self.assertRaises(job.JobViolation):
                job.terminal_slot_disposition(
                    root=self.root, row=row, latest=terminal
                )

        attempt = self.root / row["expected_attempt_dir"]
        attempt.mkdir(parents=True)
        unrelated = attempt / "unrelated.json"
        unrelated.write_text("{}\n", encoding="utf-8")
        manifest = attempt / "output_hash_manifest.sha256"
        unrelated_relative = unrelated.relative_to(self.root).as_posix()
        manifest.write_text(
            f"{common.sha256(unrelated)}  {unrelated_relative}\n",
            encoding="utf-8",
        )
        forged = {
            "status": "COMPLETED",
            "run_id": "fixture",
            "infrastructure_failure": "false",
            "replay_hard_failure": "false",
            "algorithm_hard_failure": "false",
            "run_dir": row["expected_run_dir"],
            "command_file": f"{row['expected_attempt_dir']}/command.json",
            "input_hash_manifest": (
                f"{row['expected_attempt_dir']}/input_hash_manifest.sha256"
            ),
            "output_hash_manifest": (
                f"{row['expected_attempt_dir']}/output_hash_manifest.sha256"
            ),
        }
        with self.assertRaisesRegex(job.JobViolation, "exact audit"):
            job.terminal_slot_disposition(
                root=self.root, row=row, latest=forged
            )

        audit = {
            "schema_version": job.auditor.SCHEMA_VERSION,
            "status": "PASS",
            "queue_index": 1,
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "arm": row["arm"],
            "terminal": True,
            "failure_code": None,
            "replay_hard_failure": False,
            "numeric_evaluation_candidate": True,
            "g0_evaluation_pending": True,
            "checks": {
                "job_only_governed_adapter": True,
                "job_authority_manifest_valid": True,
                "data_identity_manifest_link_target_revalidated": True,
                "durable_attempt_intent_and_state_chain_valid": True,
                "expected_run_no_clobber": True,
                "trajectory_values_read": False,
                "ape_rpe_values_read": False,
            },
            "outcome_boundary": (
                "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
            ),
        }
        audit_path = attempt / "audit_v1.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        audit_relative = audit_path.relative_to(self.root).as_posix()
        manifest.write_text(
            f"{common.sha256(audit_path)}  {audit_relative}\n",
            encoding="utf-8",
        )
        forged["notes"] = (
            f"fixture; audit={audit_relative}; "
            f"audit_sha256={common.sha256(audit_path)}; "
            f"output_manifest_sha256={common.sha256(manifest)}"
        )
        self.assertEqual(
            job.terminal_slot_disposition(
                root=self.root, row=row, latest=forged
            ),
            "COMPLETED",
        )
        audit["unbound_mutation"] = True
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        manifest.write_text(
            f"{common.sha256(audit_path)}  {audit_relative}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(job.JobViolation, "evidence-hash binding"):
            job.terminal_slot_disposition(
                root=self.root, row=row, latest=forged
            )

    def test_serial_controller_ignores_superseded_attempt_intent(self) -> None:
        base_run_id = "fixture-base"
        effective_run_id = "fixture-replacement"
        intent_root = self.root / controller.job.ATTEMPT_INTENT_ROOT_RELATIVE
        intent_root.mkdir(parents=True)
        old_token = common.sha256_bytes(base_run_id.encode("utf-8"))[:20]
        (intent_root / f"queue_001_{old_token}_attempt_intent_v1.json").write_text(
            "{}\n", encoding="utf-8"
        )
        base_row = {"queue_index": "1", "run_id": base_run_id}
        (self.root / "lock.json").write_text("{}\n", encoding="utf-8")
        with mock.patch.object(
            common, "validate_execution_lock", return_value={}
        ), mock.patch.object(
            controller.job, "_execution_order", return_value=[1]
        ), mock.patch.object(
            common, "indexed_row", return_value=base_row
        ), mock.patch.object(
                controller,
                "_replacement_for_index",
                return_value=(
                    {"queue_index": "1", "run_id": effective_run_id},
                    "papers/replacement.json",
                ),
        ), mock.patch.object(
                controller.job,
                "registry_chain",
                return_value=[{"status": "PLANNED"}],
        ):
            action = controller.plan_next_action(
                root=self.root,
                queue_path=self.root / "queue.csv",
                allocation_path=self.root / "allocation.csv",
                execution_lock_path=self.root / "lock.json",
                registry_path=self.root / "registry.csv",
                start_index=1,
                end_index=1,
            )
        self.assertEqual(action["status"], "READY_NEXT_JOB")
        self.assertEqual(action["run_id"], effective_run_id)
        self.assertEqual(action["replacement_lock"], "papers/replacement.json")


if __name__ == "__main__":
    unittest.main()
