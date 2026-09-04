#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_samehistory_positive_roster_v1 as frozen_runner
from scripts import run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1 as subject


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.attempt = root / "case/attempt_001"
        self.result = self.attempt / "result"
        self.result.mkdir(parents=True)
        self.binary = root / "mono_inertial_euroc_headless_v3"
        self.binary.write_bytes(b"synthetic hfnet")
        self.case_spec = root / "case.json"
        self.case_spec.write_text("{}\n", encoding="utf-8")
        self.prepared = self.attempt / "prepared_manifest.json"
        self.prepared.write_text("{}\n", encoding="utf-8")
        argv = (
            str(self.binary),
            str(self.attempt / "config.yaml"),
            str(self.result) + "/",
            str(root / "input"),
            str(root / "input/cam0_times.txt"),
        )
        self.contract = subject.CaseContract(
            case_id="a07_10800_11200",
            case_spec=self.case_spec,
            case_spec_identity={"path": str(self.case_spec), "size_bytes": 3, "sha256": "0" * 64},
            prepared_manifest=self.prepared,
            prepared_manifest_identity={"path": str(self.prepared), "size_bytes": 3, "sha256": "1" * 64},
            attempt_root=self.attempt,
            stdout_log=self.attempt / "headless.stdout.log",
            trajectory=self.result / "trajectory.txt",
            run_result=self.attempt / "run_result.json",
            receipt=root / "receipts/a07_10800_11200.json",
            expected_hfnet_argv=argv,
            expected_hfnet_executable=os.path.realpath(self.binary),
            expected_hfnet_binary_identity={
                "path": str(self.binary),
                "size_bytes": self.binary.stat().st_size,
                "sha256": subject._sha256(self.binary),
            },
            authorization_token="a" * 64,
        )

    def write_log(self, tail: str) -> None:
        self.contract.stdout_log.write_text(tail, encoding="utf-8")


class SignatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def valid_log(self, rows: str = "  Map 0 has 0 KFs\n") -> str:
        return (
            "ordinary output\n"
            "Shutdown\n\n"
            f"Saving trajectory to {self.fixture.contract.trajectory} ...\n"
            "There are 1 maps in the atlas\n"
            + rows
        )

    def test_complete_known_signature_is_confirmed(self) -> None:
        self.fixture.write_log(self.valid_log())
        observed = subject.parse_zero_kf_save_hang_signature(
            self.fixture.contract.stdout_log, self.fixture.contract.trajectory
        )
        self.assertTrue(observed["confirmed"])
        self.assertEqual(observed["map_keyframes_by_id"], [[0, 0]])
        self.assertTrue(observed["trajectory_absent"])

    def test_nonzero_missing_duplicate_or_incomplete_atlas_never_confirms(self) -> None:
        variants = (
            self.valid_log("  Map 0 has 3 KFs\n"),
            self.valid_log(""),
            self.valid_log("  Map 0 has 0 KFs\n  Map 0 has 0 KFs\n"),
            self.valid_log().replace("There are 1 maps", "There are 2 maps"),
        )
        for value in variants:
            with self.subTest(value=value[-80:]):
                self.fixture.write_log(value)
                observed = subject.parse_zero_kf_save_hang_signature(
                    self.fixture.contract.stdout_log,
                    self.fixture.contract.trajectory,
                )
                self.assertFalse(observed["confirmed"])

    def test_clean_save_or_present_trajectory_never_confirms(self) -> None:
        self.fixture.write_log(
            self.valid_log()
            + f"End of saving trajectory to {self.fixture.contract.trajectory} ...\n"
        )
        self.assertFalse(
            subject.parse_zero_kf_save_hang_signature(
                self.fixture.contract.stdout_log, self.fixture.contract.trajectory
            )["confirmed"]
        )
        self.fixture.write_log(self.valid_log())
        self.fixture.contract.trajectory.write_text("pose\n", encoding="ascii")
        self.assertFalse(
            subject.parse_zero_kf_save_hang_signature(
                self.fixture.contract.stdout_log, self.fixture.contract.trajectory
            )["confirmed"]
        )

    def test_shutdown_must_precede_exact_trajectory_save(self) -> None:
        self.fixture.write_log(self.valid_log().replace("Shutdown\n", ""))
        self.assertFalse(
            subject.parse_zero_kf_save_hang_signature(
                self.fixture.contract.stdout_log, self.fixture.contract.trajectory
            )["confirmed"]
        )


def make_stat(pid: int, ppid: int, starttime: int) -> str:
    # After the closing parenthesis: field 3 state, field 4 PPid, and field 22
    # starttime.  The subject parser indexes these as 0, 1, and 19.
    fields = ["S", str(ppid)] + ["0"] * 17 + [str(starttime)]
    return f"{pid} (hfnet synthetic) " + " ".join(fields) + "\n"


def install_proc(proc_root: Path, runner_pid: int, child: subject.ChildIdentity) -> None:
    runner_task = proc_root / str(runner_pid) / "task" / str(runner_pid)
    runner_task.mkdir(parents=True)
    (runner_task / "children").write_text(f"{child.pid}\n", encoding="ascii")
    child_root = proc_root / str(child.pid)
    child_root.mkdir(parents=True)
    (child_root / "stat").write_text(
        make_stat(child.pid, child.ppid, child.starttime_ticks), encoding="ascii"
    )
    (child_root / "exe").symlink_to(child.executable)
    (child_root / "cmdline").write_bytes(
        b"\0".join(value.encode("utf-8") for value in child.argv) + b"\0"
    )


class ExactChildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root / "fixture")
        self.proc = self.root / "proc"
        self.runner_pid = 4000
        self.child = subject.ChildIdentity(
            pid=5000,
            ppid=self.runner_pid,
            starttime_ticks=987654,
            executable=self.fixture.contract.expected_hfnet_executable,
            argv=self.fixture.contract.expected_hfnet_argv,
        )
        install_proc(self.proc, self.runner_pid, self.child)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discovery_binds_exact_ppid_starttime_exe_argv_to_pidfd(self) -> None:
        opened: list[int] = []
        handle = subject.discover_exact_child(
            self.proc,
            self.runner_pid,
            self.fixture.contract,
            open_pidfd=lambda pid: opened.append(pid) or 77,
        )
        self.assertIsNotNone(handle)
        self.assertEqual(opened, [self.child.pid])
        self.assertEqual(handle.identity, self.child)
        self.assertEqual(handle.pidfd, 77)

    def test_any_ppid_exe_or_argv_drift_prevents_discovery(self) -> None:
        child_root = self.proc / str(self.child.pid)
        mutations = (
            lambda: (child_root / "stat").write_text(
                make_stat(self.child.pid, 9999, self.child.starttime_ticks),
                encoding="ascii",
            ),
            lambda: (child_root / "cmdline").write_bytes(b"not-hfnet\0"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                install_root = self.root / f"proc-{id(mutate)}"
                install_proc(install_root, self.runner_pid, self.child)
                old_proc = self.proc
                self.proc = install_root
                child_root = self.proc / str(self.child.pid)
                mutate()
                self.assertIsNone(
                    subject.discover_exact_child(
                        self.proc,
                        self.runner_pid,
                        self.fixture.contract,
                        open_pidfd=lambda _pid: 77,
                    )
                )
                self.proc = old_proc

    def test_sigterm_revalidates_exact_child_and_audits_post_signal(self) -> None:
        handle = subject.ChildHandle(self.child, 77)
        sent: list[int] = []
        observed = subject.send_sigterm_to_exact_child(
            handle,
            self.runner_pid,
            self.fixture.contract,
            proc_root=self.proc,
            send_pidfd=lambda descriptor: sent.append(descriptor),
        )
        self.assertTrue(observed[0])
        self.assertEqual(sent, [77])
        self.assertEqual(
            observed[2],
            "SAME_EXACT_CHILD_STILL_OBSERVED_IMMEDIATELY_AFTER_SIGTERM",
        )

        (self.proc / str(self.child.pid) / "cmdline").write_bytes(b"other-process\0")
        sent.clear()
        refused = subject.send_sigterm_to_exact_child(
            handle,
            self.runner_pid,
            self.fixture.contract,
            proc_root=self.proc,
            send_pidfd=lambda descriptor: sent.append(descriptor),
        )
        self.assertFalse(refused[0])
        self.assertEqual(sent, [])
        self.assertEqual(refused[1], "PRE_SIGNAL_EXACT_CHILD_REVALIDATION_FAILED")


class FakeRunner:
    def __init__(self, clock: "Clock", exit_at: float, returncode: int = 0) -> None:
        self.pid = 1234
        self.clock = clock
        self.exit_at = exit_at
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode if self.clock.value >= self.exit_at else None

    def wait(self, timeout: float | None = None) -> int:
        if self.clock.value < self.exit_at:
            raise subprocess.TimeoutExpired("fake-runner", timeout)
        return self.returncode


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class MonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name))
        self.child = subject.ChildIdentity(
            pid=2222,
            ppid=1234,
            starttime_ticks=3333,
            executable=self.fixture.contract.expected_hfnet_executable,
            argv=self.fixture.contract.expected_hfnet_argv,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_clean_pass_path_never_signals(self) -> None:
        clock = Clock()
        signals: list[int] = []
        outcome = subject.monitor_runner(
            FakeRunner(clock, exit_at=2.0, returncode=0),
            self.fixture.contract,
            grace_seconds=1.0,
            poll_seconds=0.25,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            discover=lambda *_args, **_kwargs: subject.ChildHandle(self.child, 88),
            signature_parser=lambda *_args: {"confirmed": False},
            signal_sender=lambda *_args, **_kwargs: (
                signals.append(1) or True,
                "unexpected",
                "unexpected",
            ),
            close_fd=lambda _fd: None,
        )
        self.assertEqual(outcome.runner_returncode, 0)
        self.assertFalse(outcome.sigterm_sent)
        self.assertEqual(signals, [])

    def test_continuous_known_signature_signals_once_after_fixed_grace(self) -> None:
        clock = Clock()
        process = FakeRunner(clock, exit_at=100.0, returncode=-15)
        signals: list[float] = []

        def send(*_args, **_kwargs):
            signals.append(clock.value)
            process.exit_at = clock.value
            return True, "SIGTERM_SENT", "SAME_EXACT_CHILD_STILL_OBSERVED"

        outcome = subject.monitor_runner(
            process,
            self.fixture.contract,
            grace_seconds=2.0,
            poll_seconds=0.25,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            discover=lambda *_args, **_kwargs: subject.ChildHandle(self.child, 88),
            signature_parser=lambda *_args: {
                "confirmed": True,
                "every_reported_atlas_map_zero_keyframes": True,
            },
            signal_sender=send,
            close_fd=lambda _fd: None,
        )
        self.assertTrue(outcome.sigterm_sent)
        self.assertEqual(len(signals), 1)
        self.assertGreaterEqual(signals[0], 2.0)
        self.assertEqual(outcome.runner_returncode, -15)

    def test_transient_signature_resets_grace_and_does_not_signal(self) -> None:
        clock = Clock()
        signals: list[int] = []

        def parse(*_args):
            # True for less than the one-second grace, then permanently false.
            return {"confirmed": clock.value < 0.75}

        outcome = subject.monitor_runner(
            FakeRunner(clock, exit_at=2.0, returncode=1),
            self.fixture.contract,
            grace_seconds=1.0,
            poll_seconds=0.25,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            discover=lambda *_args, **_kwargs: subject.ChildHandle(self.child, 88),
            signature_parser=parse,
            signal_sender=lambda *_args, **_kwargs: (
                signals.append(1) or True,
                "unexpected",
                "unexpected",
            ),
            close_fd=lambda _fd: None,
        )
        self.assertFalse(outcome.sigterm_sent)
        self.assertEqual(signals, [])

    def test_failed_signal_revalidation_is_fail_closed_and_never_retried(self) -> None:
        clock = Clock()
        attempts: list[float] = []

        def refuse(*_args, **_kwargs):
            attempts.append(clock.value)
            return False, "PRE_SIGNAL_EXACT_CHILD_REVALIDATION_FAILED", "NOT_OBSERVED"

        outcome = subject.monitor_runner(
            FakeRunner(clock, exit_at=3.0, returncode=1),
            self.fixture.contract,
            grace_seconds=1.0,
            poll_seconds=0.25,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            discover=lambda *_args, **_kwargs: subject.ChildHandle(self.child, 88),
            signature_parser=lambda *_args: {"confirmed": True},
            signal_sender=refuse,
            close_fd=lambda _fd: None,
        )
        self.assertTrue(outcome.signal_attempted)
        self.assertFalse(outcome.sigterm_sent)
        self.assertEqual(len(attempts), 1)
        self.assertIn(
            "PRE_SIGNAL_EXACT_CHILD_REVALIDATION_FAILED",
            outcome.monitoring_errors,
        )


class SecrecyAndPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root / "fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_token_is_absent_from_os_argv_environment_and_receipt(self) -> None:
        token = self.fixture.contract.authorization_token
        argv = subject.runner_bootstrap_argv(9, self.fixture.contract.case_spec)
        environment = subject.runner_environment()
        self.assertNotIn(token, "\0".join(argv))
        self.assertNotIn(token, json.dumps(environment, sort_keys=True))

        outcome = subject.MonitorOutcome(
            runner_returncode=0,
            runner_reaped=True,
            child=None,
            child_discovered_at_utc=None,
            signature_first_observed_at_utc=None,
            signature_evidence=None,
            signal_attempted=False,
            sigterm_sent=False,
            sigterm_sent_at_utc=None,
            signal_delivery=None,
            post_signal_identity_state=None,
            runner_popen_invocations=1,
            monitoring_errors=[],
        )
        fake_identity = {"path": "/fixed", "size_bytes": 1, "sha256": "f" * 64}
        with mock.patch.object(subject, "identity", return_value=fake_identity), mock.patch.object(
            subject, "safe_identity", return_value=None
        ):
            receipt = subject.build_receipt(
                self.fixture.contract,
                outcome,
                started_at_utc="2026-01-01T00:00:00+00:00",
                token_pipe_delivery_error=None,
                supervisor_pre=fake_identity,
            )
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(token, serialized)
        self.assertFalse(receipt["execution"]["authorization_token_in_os_argv"])
        self.assertFalse(receipt["execution"]["authorization_token_in_environment"])

    def test_monitoring_or_token_pipe_error_has_fail_closed_receipt_status(self) -> None:
        outcome = subject.MonitorOutcome(
            runner_returncode=0,
            runner_reaped=True,
            child=None,
            child_discovered_at_utc=None,
            signature_first_observed_at_utc=None,
            signature_evidence=None,
            signal_attempted=False,
            sigterm_sent=False,
            sigterm_sent_at_utc=None,
            signal_delivery=None,
            post_signal_identity_state=None,
            runner_popen_invocations=1,
            monitoring_errors=["SYNTHETIC_MONITOR_ERROR"],
        )
        fake_identity = {"path": "/fixed", "size_bytes": 1, "sha256": "f" * 64}
        with mock.patch.object(subject, "identity", return_value=fake_identity), mock.patch.object(
            subject, "safe_identity", return_value=None
        ):
            receipt = subject.build_receipt(
                self.fixture.contract,
                outcome,
                started_at_utc="2026-01-01T00:00:00+00:00",
                token_pipe_delivery_error="SYNTHETIC_PIPE_ERROR",
                supervisor_pre=fake_identity,
            )
        self.assertEqual(receipt["status"], "WATCHDOG_SUPERVISION_ERROR_FAIL_CLOSED")
        self.assertEqual(
            receipt["observations"]["monitoring_errors"],
            ["SYNTHETIC_MONITOR_ERROR", "SYNTHETIC_PIPE_ERROR"],
        )

    def test_anonymous_pipe_bootstrap_keeps_token_out_of_real_proc_surfaces(self) -> None:
        token = self.fixture.contract.authorization_token
        observation = self.root / "bootstrap-observation.json"
        dummy = self.root / "dummy_runner.py"
        dummy.write_text(
            "import json,sys\n"
            "from pathlib import Path\n"
            "out=Path(sys.argv[sys.argv.index('--case-spec')+1])\n"
            "out.write_text(json.dumps({"
            "'os_cmdline':Path('/proc/self/cmdline').read_bytes().decode('utf-8'),"
            "'os_environ':Path('/proc/self/environ').read_bytes().decode('utf-8'),"
            "'python_argv':sys.argv}),encoding='utf-8')\n",
            encoding="utf-8",
        )
        read_fd, write_fd = os.pipe()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    subject.RUNNER_BOOTSTRAP,
                    str(read_fd),
                    str(dummy),
                    str(observation),
                ],
                env=subject.runner_environment(),
                pass_fds=(read_fd,),
                close_fds=True,
            )
            os.close(read_fd)
            read_fd = -1
            subject._write_all(write_fd, token.encode("ascii"))
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            os.close(write_fd)
        self.assertEqual(process.wait(timeout=10), 0)
        observed = json.loads(observation.read_text(encoding="utf-8"))
        self.assertNotIn(token, observed["os_cmdline"])
        self.assertNotIn(token, observed["os_environ"])
        self.assertIn(token, observed["python_argv"])

    def test_secure_launcher_performs_exactly_one_popen_and_one_pipe_delivery(self) -> None:
        token = self.fixture.contract.authorization_token
        calls: list[tuple[list[str], dict[str, object]]] = []
        duplicate_read_fd: list[int] = []
        fake_process = object()

        def fake_popen(argv, **kwargs):
            calls.append((list(argv), dict(kwargs)))
            duplicate_read_fd.append(os.dup(kwargs["pass_fds"][0]))
            return fake_process

        process, error = subject.launch_runner_once(
            self.fixture.contract.case_spec,
            token,
            popen=fake_popen,
        )
        self.assertIs(process, fake_process)
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(token, "\0".join(calls[0][0]))
        self.assertNotIn(token, json.dumps(calls[0][1]["env"], sort_keys=True))
        try:
            self.assertEqual(os.read(duplicate_read_fd[0], 4096).decode("ascii"), token)
            self.assertEqual(os.read(duplicate_read_fd[0], 1), b"")
        finally:
            os.close(duplicate_read_fd[0])

    def test_wrapper_and_bootstrap_are_not_forbidden_by_runner_resource_scan(self) -> None:
        records = (
            {
                "executable": subject.sys.executable,
                "comm": "python3",
                "command_tokens": [subject.sys.executable, str(subject.SUPERVISOR)],
            },
            {
                "executable": subject.sys.executable,
                "comm": "python3",
                "command_tokens": subject.runner_bootstrap_argv(
                    9, self.fixture.contract.case_spec
                ),
            },
        )
        for record in records:
            self.assertFalse(frozen_runner._is_forbidden_estimator_process(record))

    def test_receipt_publication_is_no_clobber(self) -> None:
        path = self.root / "roster-level/receipt.json"
        first = subject.canonical_json({"status": "FIRST"})
        subject.publish_exclusive(path, first)
        with self.assertRaisesRegex(subject.WatchdogContractError, "RECEIPT_ALREADY_EXISTS"):
            subject.publish_exclusive(path, subject.canonical_json({"status": "SECOND"}))
        self.assertEqual(path.read_bytes(), first)


class RealReadOnlyBindingTest(unittest.TestCase):
    def test_one_remaining_case_binds_to_current_seal_without_writes(self) -> None:
        pointer = json.loads(subject.PUBLICATION_POINTER.read_text(encoding="utf-8"))
        row = next(row for row in pointer["cases"] if row["case_id"] == "a02_7600_8000")
        contract = subject.load_case_contract(Path(row["spec"]["path"]))
        self.assertEqual(contract.case_id, "a02_7600_8000")
        self.assertNotIn(contract.attempt_root, contract.receipt.parents)
        self.assertFalse(contract.receipt.exists())

    def test_already_consumed_a05_is_prospectively_excluded(self) -> None:
        pointer = json.loads(subject.PUBLICATION_POINTER.read_text(encoding="utf-8"))
        row = next(row for row in pointer["cases"] if row["case_id"] == "a05_3300_3700")
        with self.assertRaisesRegex(subject.WatchdogContractError, "CASE_NOT_IN_REMAINING_NINE"):
            subject.load_case_contract(Path(row["spec"]["path"]))


if __name__ == "__main__":
    unittest.main()
