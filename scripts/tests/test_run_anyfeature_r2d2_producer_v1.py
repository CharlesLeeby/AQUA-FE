#!/usr/bin/env python3
"""Synthetic producer-runner tests; no official model or bag is executed."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from scripts import materialize_anyfeature_r2d2_bins_v1 as materializer
from scripts import run_anyfeature_r2d2_producer_v1 as runner


BASE_NS = 1_700_000_000_000_000_100


def _binding(path: Path) -> dict:
    path = path.resolve()
    return {
        "path": str(path),
        "sha256": runner.sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _seconds(stamp: int) -> str:
    return "%d.%09d" % (stamp // 1_000_000_000, stamp % 1_000_000_000)


def _write_sequence(
    root: Path,
    stamps: tuple,
    profile: runner.RunProfile,
    prefix_root: Path = None,
) -> None:
    (root / "rgb").mkdir(parents=True)
    rgb_payload = "".join(
        "%s rgb/%d.png\n" % (_seconds(stamp), stamp) for stamp in stamps
    ).encode("ascii")
    (root / "rgb.txt").write_bytes(rgb_payload)
    calibration = b"%YAML:1.0\nCamera.w: 968\nCamera.h: 608\n"
    (root / "calibration.yaml").write_bytes(calibration)
    rows = []
    tree = [
        ("rgb.txt", hashlib.sha256(rgb_payload).hexdigest()),
        ("calibration.yaml", hashlib.sha256(calibration).hexdigest()),
    ]
    for index, stamp in enumerate(stamps):
        path = root / "rgb" / ("%d.png" % stamp)
        if prefix_root is not None and index < profile.prefix_reuse_count:
            path.write_bytes(
                (prefix_root / "rgb" / ("%d.png" % stamp)).read_bytes()
            )
        else:
            path.write_bytes(("synthetic-png-%d" % index).encode("ascii"))
        digest = runner.sha256_file(path)
        row = {
            "source_index": index,
            "raw_header_ns": stamp,
            "record_ns": stamp,
            "relative_path": "rgb/%d.png" % stamp,
            "source_pixel_sha256": hashlib.sha256(
                ("synthetic-pixels-%d" % index).encode("ascii")
            ).hexdigest(),
            "png_sha256": digest,
            "png_size_bytes": path.stat().st_size,
            "pixel_identity_verified": True,
            "reused_from_prefix": index < profile.prefix_reuse_count,
        }
        rows.append(row)
        tree.append((row["relative_path"], digest))
    exporter = materializer.exporter_identity()
    manifest = {
        "adapter_version": materializer.EXPORT_ADAPTER_VERSION,
        "adapter_identity": exporter,
        "status": "EXPORTED",
        "profile": profile.sequence_profile,
        "source": {
            "sha256": "a" * 64,
            "calibration": {"sha256": "b" * 64},
        },
        "camera": {
            "count": len(stamps),
            "source_indices_inclusive": [0, len(stamps) - 1],
            "rgb_txt": {
                "sha256": hashlib.sha256(rgb_payload).hexdigest(),
                "row_count": len(stamps),
            },
            "images": rows,
        },
        "calibration": {
            "output_sha256": hashlib.sha256(calibration).hexdigest()
        },
        "payload_tree_sha256_excluding_manifest": runner._aggregate_rows(
            sorted(tree)
        ),
    }
    identity_record = materializer._sequence_identity_record(manifest, rows)
    manifest["sequence_identity"] = {
        "schema": materializer.EXPORT_SEQUENCE_IDENTITY_SCHEMA,
        "record": identity_record,
        "sha256": runner.sha256_bytes(
            runner.canonical_json(identity_record).encode("utf-8")
        ),
    }
    (root / "conversion_manifest.json").write_text(runner.canonical_json(manifest))


def _write_archive(path: Path, count: int = 2) -> None:
    keypoints = np.zeros((count, 3), dtype="<f4")
    if count:
        keypoints[:, 0] = np.arange(count, dtype=np.float32) + 1
        keypoints[:, 1] = np.arange(count, dtype=np.float32) + 2
        keypoints[:, 2] = 32.0
    descriptors = np.arange(count * 128, dtype=np.float32).reshape(count, 128)
    scores = np.linspace(0.2, 0.8, count, dtype=np.float32)
    with path.open("wb") as handle:
        np.savez(
            handle,
            imsize=np.asarray([968, 608]),
            keypoints=keypoints,
            descriptors=descriptors,
            scores=scores,
        )


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.identity = root / "identity"
        self.identity.mkdir()
        self.extract = self.identity / "extract.py"
        self.extract.write_text("# synthetic author extractor\n")
        self.checkpoint = self.identity / "checkpoint.pt"
        self.checkpoint.write_bytes(b"synthetic-checkpoint")
        self.license = self.identity / "LICENSE"
        self.license.write_text("synthetic license\n")
        self.readme = self.identity / "README.md"
        self.readme.write_text("synthetic AnyFeature VSLAM-LAB context\n")
        self.modules = {}
        for label in runner.RUNTIME_MODULES:
            path = self.identity / (label + ".py")
            path.write_text("# %s synthetic module\n" % label)
            self.modules[label] = {
                "version": "fixture-1",
                "module_file": _binding(path),
            }
        self.static = {
            "producer": {
                "origin": runner.R2D2_ORIGIN,
                "commit": runner.R2D2_COMMIT,
                "git_tree": runner.R2D2_TREE,
                "worktree_clean": True,
                "path": str(self.identity),
                "extract_py_sha256": runner.sha256_file(self.extract),
                "extract_py": _binding(self.extract),
                "license": _binding(self.license),
            },
            "checkpoint": _binding(self.checkpoint),
            "author_integration_context": {
                "anyfeature": {"readme": _binding(self.readme)},
                "vslam_lab": {
                    "origin": runner.VSLAM_LAB_ORIGIN,
                    "code_executed": False,
                },
                "official_r2d2_extract_py_is_sole_inference_entry_point": True,
            },
        }

    def runtime_provider(self, python: Path, cwd: Path, environment: dict) -> runner.RuntimeSeal:
        probe = {
            "schema": "anyfeature-r2d2-runtime-probe-v1",
            "python_version": "3.fixture",
            "python_implementation": "CPython",
            "python_executable": _binding(python),
            "sys_prefix": str(python.parent.parent),
            "sys_base_prefix": "/usr",
            "sys_path": ["", str(runner.RUNTIME_HOOK_DIRECTORY)],
            "cpu": "synthetic-cpu",
            "platform": "synthetic-platform",
            "byteorder": "little",
            "modules": copy.deepcopy(self.modules),
            "torch_status": {
                "cuda_available": False,
                "compiled_cuda": None,
                "device_count": 0,
                "num_threads": runner.CPU_INTRAOP_THREADS,
                "num_interop_threads": runner.CPU_INTEROP_THREADS,
            },
            "selected_environment": {
                key: environment.get(key) for key in runner.RUNTIME_ENVIRONMENT_KEYS
            },
        }
        return runner.RuntimeSeal(probe, b"fixture-package==1\n", b"")

    @staticmethod
    def process_success(
        argv, cwd, environment, stdout_path, stderr_path, frames
    ) -> runner.ProcessObservation:
        stdout_path.write_text("synthetic official stdout\n")
        stderr_path.write_bytes(b"")
        timing = []
        for offset, frame in enumerate(frames, 1):
            _write_archive(frame.archive_path)
            timing.append(
                {
                    "source_index": frame.source_index,
                    "image_relative": frame.image_relative,
                    "archive_first_observed_elapsed_seconds": float(offset),
                    "inter_completion_seconds": 1.0,
                }
            )
        return runner.ProcessObservation(
            0,
            "2026-08-11T00:00:00Z",
            "2026-08-11T00:00:02Z",
            float(len(frames)),
            tuple(timing),
        )


class R2D2ProducerRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.fixture = Fixture(self.root)
        self.python = Path(sys.executable).resolve()
        self.profile = runner.RunProfile(
            "synthetic-prefix", "synthetic-prefix", 2, 0, 1
        )
        self.stamps = (BASE_NS, BASE_NS + 50_000_000)
        self.sequence = self.root / "sequence"
        _write_sequence(self.sequence, self.stamps, self.profile)

    def config(self, **kwargs) -> runner.RunConfig:
        values = {
            "profile": self.profile,
            "sequence_root": self.sequence,
            "python_executable": self.python,
            "checkpoint": self.fixture.checkpoint,
            "formal_paths": False,
            "enforce_cache_contract": False,
        }
        values.update(kwargs)
        return runner.RunConfig(**values)

    def run_success(self, config=None, executor=None, static=None):
        return runner.run_producer(
            config or self.config(),
            runtime_provider=self.fixture.runtime_provider,
            process_executor=executor or self.fixture.process_success,
            static_identity_provider=static or (lambda _config: copy.deepcopy(self.fixture.static)),
        )

    def test_success_seals_canonical_argv_cpu_environment_and_npz_schema(self) -> None:
        captured = {}

        def process(argv, cwd, environment, stdout, stderr, frames):
            captured["argv"] = list(argv)
            captured["environment"] = dict(environment)
            return self.fixture.process_success(
                argv, cwd, environment, stdout, stderr, frames
            )

        result = self.run_success(executor=process)
        self.assertEqual(result.rc, 0)
        manifest = result.manifest
        expected = runner.canonical_argv(
            self.python,
            self.fixture.extract,
            self.fixture.checkpoint,
            (self.sequence / "producer_evidence/images.txt").resolve(),
        )
        self.assertEqual(captured["argv"], expected)
        for key, value in runner.EXECUTION_ENVIRONMENT.items():
            self.assertEqual(captured["environment"][key], value)
        self.assertTrue(manifest["runtime"]["cpu_only_verified"])
        self.assertEqual(manifest["runtime"]["torch_status"]["num_threads"], 6)
        self.assertEqual(manifest["runtime"]["torch_status"]["num_interop_threads"], 1)
        self.assertEqual([row["source_index"] for row in manifest["archives"]], [0, 1])
        self.assertEqual(manifest["archives"][0]["schema"]["descriptors"]["shape"], [2, 128])
        self.assertEqual(manifest["archives"][0]["schema"]["keypoints"]["dtype"], "<f4")
        self.assertEqual(manifest["invocation"]["flags"], runner.canonical_flags(
            self.fixture.checkpoint,
            (self.sequence / "producer_evidence/images.txt").resolve(),
        ))
        frame_specs = []
        for index, stamp in enumerate(self.stamps):
            image = self.sequence / "rgb" / ("%d.png" % stamp)
            frame_specs.append(
                materializer.FrameSpec(
                    index,
                    stamp,
                    _seconds(stamp),
                    "rgb/%d.png" % stamp,
                    image,
                    runner.sha256_file(image),
                    image.stat().st_size,
                    image.with_name(image.name + ".r2d2"),
                    "%d.bin" % stamp,
                )
            )
        with mock.patch.multiple(
            materializer,
            R2D2_EXTRACT_PY_SHA256=runner.sha256_file(self.fixture.extract),
            R2D2_CHECKPOINT_SHA256=runner.sha256_file(self.fixture.checkpoint),
            R2D2_CHECKPOINT_SIZE_BYTES=self.fixture.checkpoint.stat().st_size,
        ):
            audited_path, audited_hash, _audited = materializer.audit_producer_run(
                self.sequence, tuple(frame_specs), (0, 1), formal_profile=True
            )
        self.assertEqual(audited_path, self.sequence / "producer_run_manifest.json")
        self.assertEqual(audited_hash, runner.sha256_file(audited_path))

    def test_self_hashed_fake_argv_is_rejected(self) -> None:
        with mock.patch.object(
            materializer,
            "canonical_formal_r2d2_argv",
            return_value=[str(self.python), str(self.fixture.extract), "--gpu", "0"],
        ):
            with self.assertRaisesRegex(runner.ContractError, "CANONICAL_ARGV"):
                runner.canonical_argv(
                    self.python,
                    self.fixture.extract,
                    self.fixture.checkpoint,
                    self.root / "images.txt",
                )

    def test_non_cpu_runtime_stops_before_process_and_cleans_preflight_evidence(self) -> None:
        called = []

        def non_cpu(python, cwd, environment):
            seal = self.fixture.runtime_provider(python, cwd, environment)
            value = copy.deepcopy(seal.probe)
            value["torch_status"]["cuda_available"] = True
            value["torch_status"]["compiled_cuda"] = "12.1"
            value["torch_status"]["device_count"] = 1
            return runner.RuntimeSeal(value, seal.pip_freeze)

        with self.assertRaisesRegex(runner.ContractError, "NOT_CPU_ONLY"):
            runner.run_producer(
                self.config(),
                runtime_provider=non_cpu,
                process_executor=lambda *args: called.append(args),
                static_identity_provider=lambda _config: copy.deepcopy(self.fixture.static),
            )
        self.assertEqual(called, [])
        self.assertFalse((self.sequence / "producer_evidence").exists())
        self.assertFalse((self.sequence / "producer_run_manifest.json").exists())

    def test_post_process_identity_hash_drift_is_rc1_and_archives_are_cleaned(self) -> None:
        before = copy.deepcopy(self.fixture.static)
        after = copy.deepcopy(self.fixture.static)
        after["checkpoint"]["sha256"] = "0" * 64
        identities = mock.Mock(side_effect=[before, after])
        result = self.run_success(static=identities)
        self.assertEqual(result.rc, 1)
        self.assertEqual(result.manifest["status"], runner.STATUS_FAILED)
        self.assertIn("STATIC_IDENTITY_HASH_DRIFT", result.manifest["failure"]["reason"])
        self.assertTrue(result.manifest["failure"]["archive_cleanup"]["complete"])
        self.assertFalse(any((self.sequence / "rgb").glob("*.r2d2")))

    def test_executor_exception_removes_partial_archive_and_retains_failure_evidence(self) -> None:
        def exploding(argv, cwd, environment, stdout, stderr, frames):
            stdout.write_text("partial stdout\n")
            _write_archive(frames[0].archive_path)
            raise RuntimeError("fixture explosion")

        result = self.run_success(executor=exploding)
        self.assertEqual(result.rc, 1)
        self.assertEqual(result.manifest["process"]["return_code"], 127)
        self.assertFalse(any((self.sequence / "rgb").glob("*.r2d2")))
        self.assertTrue((self.sequence / "producer_evidence/stdout.log").is_file())
        self.assertTrue((self.sequence / "producer_run_manifest.json").is_file())

    def test_no_clobber_prevents_a_second_process(self) -> None:
        self.run_success()
        called = []
        with self.assertRaisesRegex(runner.ContractError, "ARCHIVE_ALREADY_EXISTS|OUTPUT_ALREADY_EXISTS"):
            runner.run_producer(
                self.config(),
                runtime_provider=self.fixture.runtime_provider,
                process_executor=lambda *args: called.append(args),
                static_identity_provider=lambda _config: copy.deepcopy(self.fixture.static),
            )
        self.assertEqual(called, [])

    def test_full_continuation_lists_and_infers_only_new_indices(self) -> None:
        prefix_profile = runner.RunProfile(
            "a02-prefix200", "synthetic-prefix", 2, 0, 1
        )
        prefix = self.root / "prefix"
        _write_sequence(prefix, self.stamps, prefix_profile)
        prefix_config = self.config(profile=prefix_profile, sequence_root=prefix)
        prefix_result = self.run_success(config=prefix_config)
        self.assertEqual(prefix_result.rc, 0)

        full_stamps = self.stamps + (
            BASE_NS + 100_000_000,
            BASE_NS + 150_000_000,
        )
        full_profile = runner.RunProfile(
            "a02-full-continuation", "synthetic-full", 4, 2, 3,
            prefix_reuse_count=2,
        )
        full = self.root / "full"
        _write_sequence(full, full_stamps, full_profile, prefix_root=prefix)
        observed = []

        def process(argv, cwd, environment, stdout, stderr, frames):
            observed.extend(frame.source_index for frame in frames)
            return self.fixture.process_success(
                argv, cwd, environment, stdout, stderr, frames
            )

        full_config = self.config(
            profile=full_profile,
            sequence_root=full,
            prefix_sequence_root=prefix,
        )
        result = self.run_success(config=full_config, executor=process)
        self.assertEqual(result.rc, 0)
        self.assertEqual(observed, [2, 3])
        self.assertEqual(
            result.manifest["invocation"]["image_list"]["entries"],
            ["rgb/%d.png" % full_stamps[2], "rgb/%d.png" % full_stamps[3]],
        )
        self.assertEqual(
            result.manifest["continuation"]["reused_indices_inclusive"], [0, 1]
        )
        self.assertTrue(result.manifest["continuation"]["inference_repeated"] is False)
        self.assertFalse((full / "rgb" / ("%d.png.r2d2" % full_stamps[0])).exists())
        self.assertFalse((full / "rgb" / ("%d.png.r2d2" % full_stamps[1])).exists())

    def test_regular_interpreter_copy_contract_records_cross_device_semantics(self) -> None:
        source = self.root / "venv" / "bin" / "python"
        source.parent.mkdir(parents=True)
        real = Path(sys.executable).resolve()
        source.symlink_to(real)
        (source.parent.parent / "pyvenv.cfg").write_text(
            "home = %s\ninclude-system-site-packages = true\nversion = %s\n"
            % (real.parent, platform.python_version())
        )
        target = source.with_name("python-anyfeature-r2d2-cpu-v1")
        config = self.config(python_executable=target, formal_paths=True)
        with mock.patch.multiple(
            runner,
            R2D2_PYTHON=target,
            R2D2_PYTHON_SYMLINK=source,
        ):
            executable, record = runner.prepare_python_executable(config)
        self.assertEqual(executable, target)
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), real.read_bytes())
        self.assertTrue(record["byte_identity_sha256_and_size"])
        self.assertFalse(record["same_device_inode_required"])
        self.assertTrue(record["created_by_this_run"])
        probe = subprocess.run(
            [
                str(target),
                "-c",
                "import json,sys; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix}))",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr.decode("utf-8", "replace"))
        identity = json.loads(probe.stdout)
        self.assertEqual(Path(identity["executable"]), target)
        self.assertEqual(Path(identity["prefix"]).resolve(), source.parent.parent.resolve())
        self.assertEqual(Path(identity["base_prefix"]).resolve(), Path(sys.base_prefix).resolve())
        with mock.patch.multiple(
            runner,
            R2D2_PYTHON=target,
            R2D2_PYTHON_SYMLINK=source,
        ):
            _executable, second = runner.prepare_python_executable(config)
        self.assertFalse(second["created_by_this_run"])


if __name__ == "__main__":
    unittest.main()
