#!/usr/bin/env python3
"""Tests for the one-shot matched detector-birth producer launcher.

Every child process is mocked.  This suite must never run either producer.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts import run_matched_birth_arm_once_v1 as launcher


class FakeProcess:
    def __init__(self, returncode: int = 0, pid: int = 43123) -> None:
        self.pid = pid
        self._returncode = returncode
        self.wait_calls = 0

    def wait(self) -> int:
        self.wait_calls += 1
        return self._returncode


class InterruptedOnceProcess(FakeProcess):
    def wait(self) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise InterruptedError("synthetic EINTR")
        return self._returncode


class BrokenWaitProcess(FakeProcess):
    def wait(self) -> int:
        self.wait_calls += 1
        raise RuntimeError("synthetic supervision failure")


class MatchedBirthSealedLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source_features.bag"
        self.raw = self.root / "raw_images.bag"
        self.camera = self.root / "camera.yaml"
        self.source.write_bytes(b"source-feature-bag")
        self.raw.write_bytes(b"raw-image-bag")
        self.camera.write_bytes(b"camera-yaml")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def values(self, *, prefix: str = "run", limit: str | None = None):
        result = {
            "--source-feature-bag": str(self.source),
            "--raw-image-bag": str(self.raw),
            "--camera-yaml": str(self.camera),
            "--output-bag": str(self.root / f"{prefix}.features.bag"),
            "--image-topic": "/camera/image_raw",
            "--feature-topic": "/feature_tracker/feature",
            "--manifest-json": str(self.root / f"{prefix}.manifest.json"),
            "--diagnostics-csv": str(self.root / f"{prefix}.diagnostics.csv"),
            "--legacy-manifest-json": str(
                self.root / f"{prefix}.legacy-manifest.json"
            ),
            "--work-directory": str(self.root / f"{prefix}.private-work"),
            "--attempt-json": str(self.root / f"{prefix}.producer-attempt.json"),
        }
        if limit is not None:
            result[launcher.OPTIONAL_LIMIT] = limit
        return result

    def explicit_argv(
        self,
        *,
        arm: str = "GFTT_BIRTH_RAWLK_MATCHED_V1",
        prefix: str = "run",
        limit: str | None = None,
    ):
        start = self.root / f"{prefix}.launch-start.json"
        rc = self.root / f"{prefix}.launch-rc.json"
        values = self.values(prefix=prefix, limit=limit)
        argv = [
            "--start-receipt",
            str(start),
            "--rc-receipt",
            str(rc),
            "--arm",
            arm,
        ]
        for option in launcher.PRODUCER_OPTION_ORDER:
            argv.extend((option, values[option]))
        if launcher.OPTIONAL_LIMIT in values:
            argv.extend((launcher.OPTIONAL_LIMIT, values[launcher.OPTIONAL_LIMIT]))
        return argv, start, rc, values

    @staticmethod
    def load_canonical(path: Path):
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
        if payload != launcher._canonical_bytes(value):
            raise AssertionError(f"not canonical: {path}")
        return value

    def run_with_fake_process(self, argv, *, returncode: int = 0, pid: int = 43123):
        process = FakeProcess(returncode=returncode, pid=pid)
        with mock.patch.object(
            launcher.subprocess, "Popen", return_value=process
        ) as popen:
            observed = launcher.main(argv)
        return observed, process, popen

    def write_contract(
        self,
        contract: object,
        *,
        name: str = "command-contract.json",
    ) -> Path:
        path = self.root / name
        path.write_bytes(launcher._canonical_bytes(contract))
        return path

    def contract_argv(self, contract: object, *, prefix: str):
        start = self.root / f"{prefix}.launch-start.json"
        rc = self.root / f"{prefix}.launch-rc.json"
        path = self.write_contract(contract, name=f"{prefix}.contract.json")
        return [
            "--start-receipt",
            str(start),
            "--rc-receipt",
            str(rc),
            "--command-contract-json",
            str(path),
        ], start, rc, path

    def test_explicit_launch_uses_exact_subprocess_boundary_and_receipts(self):
        argv, start, rc, values = self.explicit_argv(limit="16")
        observed, process, popen = self.run_with_fake_process(
            argv, returncode=17, pid=81234
        )
        self.assertEqual(observed, 17)
        self.assertEqual(process.wait_calls, 1)
        popen.assert_called_once()
        positional, keyword = popen.call_args
        self.assertEqual(
            positional[0],
            launcher._build_producer_argv(
                "GFTT_BIRTH_RAWLK_MATCHED_V1", values
            ),
        )
        self.assertIsInstance(positional[0], list)
        self.assertEqual(keyword["cwd"], "/home/ma/AQUA-FE_WS")
        self.assertEqual(keyword["env"], launcher.FROZEN_ENVIRONMENT)
        self.assertIsNot(keyword["env"], launcher.FROZEN_ENVIRONMENT)
        self.assertIs(keyword["shell"], False)
        self.assertIs(keyword["close_fds"], True)
        self.assertIs(keyword["start_new_session"], False)

        start_payload = self.load_canonical(start)
        result = self.load_canonical(rc)
        invocation = start_payload["launcher_invocation"]
        self.assertEqual(invocation["working_directory"], os.getcwd())
        self.assertEqual(invocation["environment"], dict(os.environ))
        self.assertEqual(
            invocation["launcher_source"]["path"],
            str(Path(launcher.__file__).resolve(strict=True)),
        )
        self.assertTrue(invocation["process_command_line"])
        self.assertEqual(
            start_payload["status"], "START_NAMESPACE_CONSUMED_PREVALIDATION"
        )
        self.assertFalse(start_payload["producer_process_started_at_receipt"])
        self.assertEqual(start_payload["reserved_producer_process_start_count"], 1)
        self.assertEqual(result["status"], "PROCESS_ENDED")
        self.assertEqual(result["actual_execution"]["argv"], positional[0])
        self.assertEqual(
            result["actual_execution"]["environment"],
            launcher.FROZEN_ENVIRONMENT,
        )
        self.assertEqual(
            result["actual_execution"]["working_directory"],
            "/home/ma/AQUA-FE_WS",
        )
        producer = result["producer_process"]
        self.assertEqual(producer["pid"], 81234)
        self.assertEqual(producer["launch_attempt_count"], 1)
        self.assertEqual(producer["process_start_count"], 1)
        self.assertEqual(producer["producer_return_code"], 17)
        self.assertTrue(producer["natural_end_observed"])
        self.assertFalse(producer["terminated_by_signal"])
        self.assertIsNone(producer["signal_number"])
        self.assertFalse(producer["supervisor_sent_signal"])
        self.assertFalse(producer["timed_out"])
        self.assertFalse(producer["retry_performed"])
        self.assertTrue(result["pycache_contract"]["absent_pre"])
        self.assertTrue(result["pycache_contract"]["absent_post"])
        for receipt in (start, rc):
            observed_mode = stat.S_IMODE(os.lstat(receipt).st_mode)
            self.assertEqual(observed_mode, 0o444)
            self.assertEqual(os.lstat(receipt).st_nlink, 1)

    def test_canonical_command_contract_mode_launches_once(self):
        prefix = "contract-success"
        start = self.root / f"{prefix}.launch-start.json"
        rc = self.root / f"{prefix}.launch-rc.json"
        values = self.values(prefix=prefix)
        contract = launcher.build_command_contract(
            "XFEAT_BIRTH_RAWLK_MATCHED_V1",
            values,
            start_receipt=start,
            rc_receipt=rc,
        )
        contract_path = self.write_contract(
            contract, name=f"{prefix}.contract.json"
        )
        argv = [
            "--start-receipt",
            str(start),
            "--rc-receipt",
            str(rc),
            "--command-contract-json",
            str(contract_path),
        ]
        observed, process, popen = self.run_with_fake_process(argv)
        self.assertEqual(observed, 0)
        self.assertEqual(process.wait_calls, 1)
        popen.assert_called_once()
        result = self.load_canonical(rc)
        self.assertEqual(result["command_contract"]["path"], str(contract_path))
        self.assertEqual(
            result["command_contract"]["sha256"],
            launcher._sha256_bytes(contract_path.read_bytes()),
        )
        self.assertEqual(
            result["actual_execution"]["argv"][0:4],
            [
                "/usr/bin/python3.8",
                "-B",
                "-m",
                "scripts.export_matched_xfeat_birth_rawlk_v1",
            ],
        )

    def test_in_process_monkeypatched_producer_cannot_bypass_subprocess(self):
        argv, _start, _rc, _values = self.explicit_argv(prefix="no-bypass")
        fake_producer = SimpleNamespace(main=mock.Mock(side_effect=AssertionError))
        module_name = "scripts.export_matched_gftt_birth_rawlk_v1"
        with mock.patch.dict(sys.modules, {module_name: fake_producer}):
            observed, _process, popen = self.run_with_fake_process(argv)
        self.assertEqual(observed, 0)
        popen.assert_called_once()
        fake_producer.main.assert_not_called()

    def test_start_receipt_precedes_semantic_validation(self):
        argv, start, rc, _values = self.explicit_argv(prefix="invalid-after-start")
        missing_index = argv.index("--camera-yaml")
        del argv[missing_index : missing_index + 2]
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
        self.assertTrue(start.is_file())
        failure = self.load_canonical(rc)
        self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
        self.assertEqual(failure["producer_process"]["process_start_count"], 0)
        self.assertEqual(failure["producer_process"]["launch_attempt_count"], 0)
        popen.assert_not_called()

    def test_existing_start_receipt_is_permanent_no_clobber(self):
        argv, start, rc, _values = self.explicit_argv(prefix="existing-start")
        original = b"already-consumed\n"
        start.write_bytes(original)
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_NO_CLOBBER)
        self.assertEqual(start.read_bytes(), original)
        self.assertFalse(rc.exists())
        popen.assert_not_called()

    def test_duplicate_option_is_rejected_after_start_reservation(self):
        argv, start, rc, _values = self.explicit_argv(prefix="duplicate")
        argv.extend(("--image-topic", "/camera/image_raw"))
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
        self.assertTrue(start.exists())
        failure = self.load_canonical(rc)
        self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
        self.assertEqual(failure["producer_process"]["process_start_count"], 0)
        popen.assert_not_called()

    def test_mixed_help_is_terminal_after_start_reservation(self):
        argv, start, rc, _values = self.explicit_argv(prefix="mixed-help")
        argv.append("--help")
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
        self.assertTrue(start.exists())
        failure = self.load_canonical(rc)
        self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
        self.assertEqual(failure["producer_process"]["process_start_count"], 0)
        popen.assert_not_called()

    def test_bare_help_does_not_consume_a_namespace(self):
        with mock.patch.object(launcher, "_reserve_start_receipt") as reserve:
            self.assertEqual(launcher.main(["--help"]), 0)
        reserve.assert_not_called()

    def test_contract_rejects_wrong_argv_environment_cwd_and_entrypoint(self):
        mutations = {
            "argv": lambda contract: contract["argv"].__setitem__(0, "/usr/bin/python3"),
            "environment": lambda contract: contract["environment"].__setitem__(
                "EXTRA", "forbidden"
            ),
            "cwd": lambda contract: contract.__setitem__(
                "working_directory", "/tmp"
            ),
            "entrypoint": lambda contract: contract["argv"].__setitem__(
                3, "scripts.export_matched_gftt_birth_rawlk_v1"
            ),
        }
        for index, (label, mutate) in enumerate(mutations.items()):
            with self.subTest(label=label):
                prefix = f"wrong-{index}-{label}"
                start = self.root / f"{prefix}.launch-start.json"
                rc = self.root / f"{prefix}.launch-rc.json"
                contract = launcher.build_command_contract(
                    "XFEAT_BIRTH_RAWLK_MATCHED_V1",
                    self.values(prefix=prefix),
                    start_receipt=start,
                    rc_receipt=rc,
                )
                mutate(contract)
                contract_path = self.write_contract(
                    contract, name=f"{prefix}.contract.json"
                )
                argv = [
                    "--start-receipt",
                    str(start),
                    "--rc-receipt",
                    str(rc),
                    "--command-contract-json",
                    str(contract_path),
                ]
                with mock.patch.object(launcher.subprocess, "Popen") as popen:
                    observed = launcher.main(argv)
                self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
                self.assertTrue(start.exists())
                failure = self.load_canonical(rc)
                self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
                self.assertEqual(
                    failure["producer_process"]["process_start_count"], 0
                )
                popen.assert_not_called()

    def test_supervision_bool_cannot_be_replaced_by_integer(self):
        prefix = "typed-supervision"
        start = self.root / f"{prefix}.launch-start.json"
        rc = self.root / f"{prefix}.launch-rc.json"
        contract = launcher.build_command_contract(
            "GFTT_BIRTH_RAWLK_MATCHED_V1",
            self.values(prefix=prefix),
            start_receipt=start,
            rc_receipt=rc,
        )
        contract["supervision"]["no_retry"] = 1
        contract_path = self.write_contract(
            contract, name=f"{prefix}.contract.json"
        )
        argv = [
            "--start-receipt", str(start),
            "--rc-receipt", str(rc),
            "--command-contract-json", str(contract_path),
        ]
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
        self.assertEqual(
            self.load_canonical(rc)["status"], "TERMINAL_PRESTART_FAILURE"
        )
        popen.assert_not_called()

    def test_interrupted_wait_is_retried_without_second_process_start(self):
        argv, _start, rc, _values = self.explicit_argv(prefix="eintr-wait")
        process = InterruptedOnceProcess(returncode=0, pid=51234)
        with mock.patch.object(
            launcher.subprocess, "Popen", return_value=process
        ) as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, 0)
        self.assertEqual(process.wait_calls, 2)
        popen.assert_called_once()
        receipt = self.load_canonical(rc)
        self.assertTrue(receipt["producer_process"]["natural_end_observed"])
        self.assertEqual(receipt["producer_process"]["process_start_count"], 1)

    def test_unexpected_wait_failure_seals_global_stop_without_false_end(self):
        argv, _start, rc, _values = self.explicit_argv(prefix="broken-wait")
        process = BrokenWaitProcess(returncode=0, pid=61234)
        with mock.patch.object(
            launcher.subprocess, "Popen", return_value=process
        ) as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_LAUNCH_FAILURE)
        popen.assert_called_once()
        receipt = self.load_canonical(rc)
        self.assertEqual(
            receipt["status"],
            "SUPERVISION_FAILURE_PROCESS_END_UNCONFIRMED_GLOBAL_STOP",
        )
        producer = receipt["producer_process"]
        self.assertEqual(producer["process_start_count"], 1)
        self.assertFalse(producer["natural_end_observed"])
        self.assertFalse(producer["terminal_state_confirmed"])
        self.assertFalse(producer["authorizes_followup"])

    def test_noncanonical_contract_is_rejected(self):
        prefix = "noncanonical"
        start = self.root / f"{prefix}.launch-start.json"
        rc = self.root / f"{prefix}.launch-rc.json"
        contract = launcher.build_command_contract(
            "GFTT_BIRTH_RAWLK_MATCHED_V1",
            self.values(prefix=prefix),
            start_receipt=start,
            rc_receipt=rc,
        )
        contract_path = self.root / f"{prefix}.contract.json"
        contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
        argv = [
            "--start-receipt",
            str(start),
            "--rc-receipt",
            str(rc),
            "--command-contract-json",
            str(contract_path),
        ]
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
        self.assertTrue(start.exists())
        failure = self.load_canonical(rc)
        self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
        self.assertEqual(failure["producer_process"]["process_start_count"], 0)
        popen.assert_not_called()

    def test_symlink_hardlink_and_output_aliases_are_rejected(self):
        cases = []

        symlink_raw = self.root / "raw-link.bag"
        symlink_raw.symlink_to(self.raw)
        values = self.values(prefix="symlink")
        values["--raw-image-bag"] = str(symlink_raw)
        cases.append(("symlink", values))

        hardlink_source = self.root / "source-hardlink.bag"
        os.link(self.source, hardlink_source)
        values = self.values(prefix="hardlink")
        values["--raw-image-bag"] = str(hardlink_source)
        cases.append(("hardlink", values))

        values = self.values(prefix="alias")
        values["--manifest-json"] = values["--output-bag"]
        cases.append(("alias", values))

        for index, (label, values) in enumerate(cases):
            with self.subTest(label=label):
                start = self.root / f"path-{index}.start.json"
                rc = self.root / f"path-{index}.rc.json"
                argv = [
                    "--start-receipt",
                    str(start),
                    "--rc-receipt",
                    str(rc),
                    "--arm",
                    "GFTT_BIRTH_RAWLK_MATCHED_V1",
                ]
                for option in launcher.PRODUCER_OPTION_ORDER:
                    argv.extend((option, values[option]))
                with mock.patch.object(launcher.subprocess, "Popen") as popen:
                    observed = launcher.main(argv)
                self.assertEqual(observed, launcher.RC_CONTRACT_REJECTED)
                self.assertTrue(start.exists())
                failure = self.load_canonical(rc)
                self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
                self.assertEqual(
                    failure["producer_process"]["process_start_count"], 0
                )
                popen.assert_not_called()

    def test_popen_failure_gets_terminal_receipt_without_false_process_start(self):
        argv, start, rc, _values = self.explicit_argv(prefix="popen-failure")
        with mock.patch.object(
            launcher.subprocess,
            "Popen",
            side_effect=OSError("synthetic exec failure"),
        ) as popen:
            observed = launcher.main(argv)
        self.assertEqual(observed, launcher.RC_LAUNCH_FAILURE)
        popen.assert_called_once()
        self.assertTrue(start.exists())
        failure = self.load_canonical(rc)
        self.assertEqual(failure["status"], "TERMINAL_PRESTART_FAILURE")
        self.assertEqual(failure["failure"]["stage"], "producer_popen")
        self.assertEqual(failure["producer_process"]["launch_attempt_count"], 1)
        self.assertEqual(failure["producer_process"]["process_start_count"], 0)
        self.assertIsNone(failure["producer_process"]["pid"])
        self.assertIsNone(failure["producer_process"]["producer_return_code"])
        self.assertFalse(failure["producer_process"]["supervisor_sent_signal"])
        self.assertFalse(failure["producer_process"]["timed_out"])

    def test_write_all_handles_repeated_short_writes(self):
        receipt = self.root / "short-write.json"
        payload = {"schema_version": "test", "value": "x" * 1024}
        original_write = os.write
        counts = []

        def short_write(descriptor, remaining):
            count = max(1, len(remaining) // 5)
            counts.append(count)
            return original_write(descriptor, remaining[:count])

        with mock.patch.object(launcher.os, "write", side_effect=short_write):
            launcher._write_exclusive_receipt(receipt, payload)
        self.assertGreater(len(counts), 1)
        self.assertEqual(receipt.read_bytes(), launcher._canonical_bytes(payload))
        self.assertEqual(stat.S_IMODE(os.lstat(receipt).st_mode), 0o444)

    def test_zero_progress_write_fails_closed_and_keeps_claim(self):
        receipt = self.root / "zero-write.json"
        with mock.patch.object(launcher.os, "write", return_value=0):
            with self.assertRaisesRegex(OSError, "made no progress"):
                launcher._write_exclusive_receipt(receipt, {"value": 1})
        self.assertTrue(receipt.exists())
        self.assertEqual(receipt.read_bytes(), b"")
        self.assertEqual(stat.S_IMODE(os.lstat(receipt).st_mode), 0o444)

    def test_source_has_one_popen_call_and_no_producer_import_or_deletion(self):
        source = Path(launcher.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        popen_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "Popen"
        ]
        self.assertEqual(len(popen_calls), 1)
        self.assertNotIn("import_matched_xfeat", source)
        self.assertNotIn("from scripts import export_matched", source)
        self.assertNotIn("os.unlink", source)
        self.assertNotIn(".unlink(", source)
        self.assertNotIn("os.remove", source)

    def test_frozen_environment_and_entrypoints_are_exact(self):
        self.assertEqual(
            launcher.PYCACHE_PREFIX,
            Path("/tmp/aqua-fe-a02-matched-birth-rawlk-empty-pycache-v1"),
        )
        self.assertEqual(
            set(launcher.FROZEN_ENVIRONMENT),
            {
                "HOME",
                "USER",
                "LOGNAME",
                "SHELL",
                "PATH",
                "LANG",
                "LC_ALL",
                "PYTHONPATH",
                "PYTHONNOUSERSITE",
                "PYTHONHASHSEED",
                "PYTHONDONTWRITEBYTECODE",
                "PYTHONPYCACHEPREFIX",
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "CUDA_VISIBLE_DEVICES",
                "LD_LIBRARY_PATH",
            },
        )
        self.assertEqual(launcher.PYTHON_EXECUTABLE, "/usr/bin/python3.8")
        self.assertEqual(
            launcher.ARM_ENTRYPOINTS,
            {
                "XFEAT_BIRTH_RAWLK_MATCHED_V1": (
                    "scripts.export_matched_xfeat_birth_rawlk_v1"
                ),
                "GFTT_BIRTH_RAWLK_MATCHED_V1": (
                    "scripts.export_matched_gftt_birth_rawlk_v1"
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
