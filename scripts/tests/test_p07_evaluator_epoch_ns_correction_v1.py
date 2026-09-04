from __future__ import annotations

import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as builder
from scripts import evaluate_vins_common_support as base
from scripts import evaluate_vins_common_support_epoch_v2 as corrected
from scripts import p07_backend_formal_io_v1 as formal_io


ROOT = Path(__file__).resolve().parents[2]


class EpochNsAdapterTests(unittest.TestCase):
    def test_sealed_wrapper_loads_base_and_core_from_procfd(self) -> None:
        if not hasattr(os, "memfd_create"):
            self.skipTest("memfd_create unavailable")

        sources = (
            ("core", b"MARKER = 'SEALED_CORE_MARKER'\n"),
            (
                "base",
                b"from trajectory_eval_core import MARKER\n"
                b"import rosbag\n"
                b"def load_ros_reference(*args, **kwargs): return None\n"
                b"def main(): print(MARKER); print(rosbag.__file__); return 0\n",
            ),
            (
                "wrapper",
                (ROOT / builder.WRAPPER_RELATIVE).read_bytes(),
            ),
        )
        descriptors: list[int] = []
        try:
            paths: dict[str, str] = {}
            for label, content in sources:
                descriptor = os.memfd_create(
                    f"p07-{label}", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC
                )
                descriptors.append(descriptor)
                os.write(descriptor, content)
                fcntl.fcntl(
                    descriptor,
                    fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE
                    | fcntl.F_SEAL_GROW
                    | fcntl.F_SEAL_SHRINK
                    | fcntl.F_SEAL_SEAL,
                )
                paths[label] = f"/proc/self/fd/{descriptor}"
            with tempfile.TemporaryDirectory() as raw:
                injection = Path(raw)
                marker = injection / "sitecustomize-loaded"
                (injection / "sitecustomize.py").write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('loaded')\n",
                    encoding="utf-8",
                )
                environment = {
                    "HOME": os.fspath(injection),
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PYTHONPATH": os.fspath(injection),
                    corrected.SEALED_BASE_ENV: paths["base"],
                    corrected.SEALED_CORE_ENV: paths["core"],
                }
                completed = subprocess.run(
                    [sys.executable, "-I", paths["wrapper"]],
                    pass_fds=tuple(descriptors),
                    env=environment,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertFalse(marker.exists())
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout.strip().splitlines()
        self.assertEqual(output[0], "SEALED_CORE_MARKER")
        self.assertTrue(
            output[1].startswith(corrected.ROS_NOETIC_PYTHON_DIST_PACKAGES)
        )

    def test_epoch_nanoseconds_are_preserved_without_to_sec(self) -> None:
        class Stamp:
            secs = 1_700_000_000
            nsecs = 123_456_789

            def to_sec(self) -> float:
                raise AssertionError("Time.to_sec must not be called")

        observed = corrected.ros_stamp_to_longdouble(Stamp())
        self.assertEqual(
            int(observed * np.longdouble(1_000_000_000)),
            1_700_000_000_123_456_789,
        )
        following = corrected.ros_stamp_to_longdouble(
            type("Next", (), {"secs": Stamp.secs, "nsecs": Stamp.nsecs + 1})()
        )
        self.assertGreater(following, observed)
        lossy = np.longdouble(float(Stamp.secs + Stamp.nsecs / 1_000_000_000))
        self.assertNotEqual(observed, lossy)

    def test_noninteger_bool_and_noncanonical_nsec_are_rejected(self) -> None:
        invalid = (
            type("Missing", (), {})(),
            type("BoolSecs", (), {"secs": True, "nsecs": 0})(),
            type("StringSecs", (), {"secs": "1700000000", "nsecs": 0})(),
            type("Negative", (), {"secs": -1, "nsecs": 0})(),
            type("Overflow", (), {"secs": 1, "nsecs": 1_000_000_000})(),
        )
        for stamp in invalid:
            with self.subTest(kind=type(stamp).__name__):
                with self.assertRaises(ValueError):
                    corrected.ros_stamp_to_longdouble(stamp)

    def test_fake_rosbag_loader_uses_integer_stamp_fields(self) -> None:
        class Stamp:
            secs = 1_542_883_756
            nsecs = 512_375_401

            def to_sec(self) -> float:
                raise AssertionError("Time.to_sec must not be called")

        message = SimpleNamespace(
            header=SimpleNamespace(stamp=Stamp()),
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1, y=2, z=3),
                orientation=SimpleNamespace(x=0, y=0, z=0, w=1),
            ),
        )

        class Bag:
            def __init__(self, path: str) -> None:
                self.path = path

            def __enter__(self) -> "Bag":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read_messages(self, *, topics: list[str]):
                self.asserted_topics = topics
                yield topics[0], message, None

        fake_rosbag = SimpleNamespace(Bag=Bag)
        with mock.patch.dict(sys.modules, {"rosbag": fake_rosbag}):
            series = corrected.load_ros_reference(Path("fixture.bag"), "/pose")
        self.assertEqual(series.stamps.dtype, np.dtype(np.longdouble))
        self.assertEqual(
            int(series.stamps[0] * np.longdouble(1_000_000_000)),
            1_542_883_756_512_375_401,
        )
        np.testing.assert_array_equal(series.positions, [[1.0, 2.0, 3.0]])

    def test_base_loader_is_restored_even_when_base_main_raises(self) -> None:
        original = base.load_ros_reference

        def fail_after_check() -> int:
            self.assertIs(base.load_ros_reference, corrected.load_ros_reference)
            raise RuntimeError("synthetic evaluator failure")

        with mock.patch.object(base, "main", side_effect=fail_after_check):
            with self.assertRaisesRegex(RuntimeError, "synthetic evaluator failure"):
                corrected.main()
        self.assertIs(base.load_ros_reference, original)


class EpochNsCorrectionLockTests(unittest.TestCase):
    def _formal_payload(self) -> dict[str, object] | None:
        if not formal_io.destination_exists(ROOT, builder.OUTPUT_RELATIVE):
            return None
        content, _identity = formal_io.read_direct_bytes(
            ROOT, builder.OUTPUT_RELATIVE
        )
        value = json.loads(content)
        self.assertIsInstance(value, dict)
        return value

    def _build(self) -> dict[str, object]:
        frozen_at = "2026-08-08T12:00:00+08:00"
        formal_payload = self._formal_payload()
        if formal_payload is not None:
            frozen_at = str(formal_payload["frozen_at"])
        return builder.build_lock(
            root=ROOT,
            frozen_at=frozen_at,
            require_output_absent=formal_payload is None,
        )

    def test_read_only_build_binds_parent_base_core_wrapper_and_protocol(self) -> None:
        frozen_at = "2026-08-08T12:00:00+08:00"
        require_absent = True
        expected_formal = self._formal_payload()
        if expected_formal is not None:
            frozen_at = str(expected_formal["frozen_at"])
            require_absent = False
        payload = builder.build_lock(
            root=ROOT,
            frozen_at=frozen_at,
            require_output_absent=require_absent,
        )
        if expected_formal is not None:
            self.assertEqual(payload, expected_formal)
        digest = builder.validate_lock_payload(payload, root=ROOT, verify_files=True)
        self.assertEqual(digest, payload[builder.SELF_HASH_FIELD])
        self.assertEqual(
            payload["corrected_implementation_binding"]["entrypoint"],
            builder.WRAPPER_RELATIVE,
        )
        self.assertEqual(
            payload["corrected_implementation_binding"]["base_evaluator_sha256"],
            builder.BASE_SHA256,
        )
        self.assertEqual(
            payload["outcome_blind_audit"]["builder_allowed_read_paths"],
            list(builder.ALLOWED_READ_PATHS),
        )

    def test_rehashed_file_record_tamper_is_rejected(self) -> None:
        payload = self._build()
        altered = copy.deepcopy(payload)
        altered["corrected_implementation_binding"]["files"][2]["sha256"] = "0" * 64
        altered["corrected_implementation_binding"][
            "implementation_bundle_sha256"
        ] = builder._implementation_bundle_hash(
            altered["corrected_implementation_binding"]["files"]
        )
        altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            altered, builder.SELF_HASH_FIELD
        )
        with self.assertRaisesRegex(ValueError, "implementation records|file drift"):
            builder.validate_lock_payload(altered, root=ROOT, verify_files=True)

    def test_rehashed_semantic_tampering_is_rejected(self) -> None:
        original = self._build()
        mutations = {
            "parent_self_hash": lambda value: value[
                "parent_precision_correction_lock"
            ].__setitem__("correction_lock_hash", "0" * 64),
            "parent_schema": lambda value: value[
                "parent_precision_correction_lock"
            ].__setitem__("schema_version", "attacker-parent-v1"),
            "protocol_parent": lambda value: value["protocol_binding"].__setitem__(
                "parent_sha256", "0" * 64
            ),
            "protocol_identity": lambda value: value[
                "protocol_binding"
            ].__setitem__("protocol_identity", "attacker-protocol"),
            "audit_allowlist": lambda value: value[
                "outcome_blind_audit"
            ]["builder_allowed_read_paths"].pop(),
            "adapter_scope": lambda value: value[
                "corrected_implementation_binding"
            ].__setitem__("adapter_scope", "FULL_EVALUATOR_REPLACEMENT"),
            "base_main": lambda value: value[
                "corrected_implementation_binding"
            ].__setitem__("base_main_called", False),
            "finally_restore": lambda value: value[
                "corrected_implementation_binding"
            ].__setitem__("base_loader_restored_in_finally", False),
            "conversion": lambda value: value["epoch_ns_correction"].__setitem__(
                "new_ros_bag_conversion", "float(to_sec())"
            ),
        }
        for label, mutate in mutations.items():
            altered = copy.deepcopy(original)
            mutate(altered)
            altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
                altered, builder.SELF_HASH_FIELD
            )
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    builder.validate_lock_payload(
                        altered, root=ROOT, verify_files=True
                    )

    def test_default_cli_contract_has_no_implicit_write_flag(self) -> None:
        source = (ROOT / builder.BUILDER_RELATIVE).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--write", action="store_true")', source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn("os.replace(", source)


if __name__ == "__main__":
    unittest.main()
