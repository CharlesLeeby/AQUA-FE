#!/usr/bin/python3
"""Deterministic v12 tests for the bounded watchdog PENDING_REAP state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import fair_stability_ordinal_common_v12 as COMMON
import fair_stability_runtime_resource_monitor_v12 as RESOURCE
import run_fair_stability_hfnet_openloop_v12 as HFNET


EXPECTED_EXECUTABLE = "/exact/hfnet"
EXPECTED_ARGV = [EXPECTED_EXECUTABLE]
EXIT_CODE = -6


class StepClock:
    """Coherent seconds/ns clock whose every ns observation advances by 1 ns."""

    def __init__(self, initial_ns: int = 1_000_000_000) -> None:
        self.value_ns = initial_ns
        self.last_observed_ns = initial_ns

    def monotonic(self) -> float:
        return self.value_ns / 1_000_000_000.0

    def monotonic_ns(self) -> int:
        observed = self.value_ns
        self.last_observed_ns = observed
        self.value_ns += 1
        return observed

    def advance_to(self, target_ns: int) -> None:
        self.value_ns = max(self.value_ns, int(target_ns))


class TimedProcess:
    def __init__(self, clock: StepClock) -> None:
        self.clock = clock
        self.returncode: int | None = None
        self.exit_at_ns: int | None = None
        self.wait_calls: list[float] = []
        self.wait_error: BaseException | None = None

    def poll(self) -> int | None:
        if (
            self.returncode is None
            and self.exit_at_ns is not None
            and self.clock.value_ns >= self.exit_at_ns
        ):
            self.returncode = EXIT_CODE
        return self.returncode

    def wait(self, timeout: float = 0.0) -> int:
        self.wait_calls.append(float(timeout))
        if self.wait_error is not None:
            raise self.wait_error
        if self.poll() is not None:
            return int(self.returncode)
        started_ns = self.clock.last_observed_ns
        target_ns = started_ns + int(round(float(timeout) * 1_000_000_000))
        if self.exit_at_ns is not None and self.exit_at_ns <= target_ns:
            self.clock.advance_to(self.exit_at_ns)
            self.returncode = EXIT_CODE
            return EXIT_CODE
        self.clock.advance_to(target_ns)
        raise subprocess.TimeoutExpired([EXPECTED_EXECUTABLE], timeout)


class PendingMonitor:
    def __init__(
        self,
        process: TimedProcess,
        clock: StepClock,
        *,
        entry_path: str,
        exit_delay_ns: int,
        initial_poll_delay_ns: int = 0,
        recheck_mode: str = "candidate",
        recheck_delay_ns: int = 0,
    ) -> None:
        self.process = process
        self.clock = clock
        self.pid = 7
        self.pgid = 7
        self.leader_identity = (7, 9)
        self.entry_path = entry_path
        self.exit_delay_ns = exit_delay_ns
        self.initial_poll_delay_ns = initial_poll_delay_ns
        self.recheck_mode = recheck_mode
        self.recheck_delay_ns = recheck_delay_ns
        self.group_calls = 0
        self.final_pending = False
        self.initial_anchor_ns: int | None = None
        self.signal_attempted = False

    def candidate(self, *, initial: bool = False) -> dict[str, object]:
        observed_ns = self.clock.monotonic_ns()
        if initial:
            self.initial_anchor_ns = observed_ns
            self.process.exit_at_ns = observed_ns + self.exit_delay_ns
            self.clock.advance_to(observed_ns + self.initial_poll_delay_ns)
        return {
            "observed_at_utc": "2026-08-30T03:34:00+00:00",
            "observed_monotonic_ns": observed_ns,
            "proven": False,
            "errors": ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"],
            "leader_pid": 7,
            "leader_start_ticks": 9,
            "expected_executable": EXPECTED_EXECUTABLE,
            "expected_argv": list(EXPECTED_ARGV),
            "pgid": 7,
            "session": 7,
            "members": [
                {
                    "pid": 7,
                    "start_ticks": 9,
                    "pgid": 7,
                    "session": 7,
                    "state": "R",
                    "executable": None,
                    "cmdline_sha256": RESOURCE.EMPTY_CMDLINE_SHA256,
                }
            ],
        }

    def proven(self) -> dict[str, object]:
        raw_cmdline = b"\0".join(value.encode() for value in EXPECTED_ARGV) + b"\0"
        return {
            "observed_at_utc": "2026-08-30T03:34:00+00:00",
            "observed_monotonic_ns": self.clock.monotonic_ns(),
            "proven": True,
            "errors": [],
            "leader_pid": 7,
            "leader_start_ticks": 9,
            "expected_executable": EXPECTED_EXECUTABLE,
            "expected_argv": list(EXPECTED_ARGV),
            "pgid": 7,
            "session": 7,
            "members": [
                {
                    "pid": 7,
                    "start_ticks": 9,
                    "pgid": 7,
                    "session": 7,
                    "state": "S",
                    "executable": EXPECTED_EXECUTABLE,
                    "cmdline_sha256": hashlib.sha256(raw_cmdline).hexdigest(),
                }
            ],
        }

    def recheck(self) -> dict[str, object]:
        self.clock.advance_to(self.clock.value_ns + self.recheck_delay_ns)
        value = self.candidate()
        if self.recheck_mode == "wrong_nonempty":
            value["errors"] = [
                "EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH",
                "EXACT_GROUP_LEADER_WRONG_NONEMPTY_IDENTITY_OBSERVED",
            ]
            value["members"][0]["executable"] = "/wrong/live/hfnet"
            value["members"][0]["cmdline_sha256"] = "a" * 64
        elif self.recheck_mode == "pid_reuse":
            value["errors"] = [
                "GLOBAL_FROZEN_LEADER_STABLE_IDENTITY_DRIFT",
                "EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH",
            ]
            value["leader_start_ticks"] = 10
            value["members"][0]["start_ticks"] = 10
        return value

    def watchdog_exact_group_snapshot(self, *_args) -> dict[str, object]:
        self.group_calls += 1
        if self.entry_path == "periodic":
            return self.candidate(initial=True) if self.group_calls == 1 else self.recheck()
        if self.final_pending:
            return self.recheck()
        return self.proven()

    def watchdog_sigterm_exact_group(self, *_args, **kwargs) -> dict[str, object]:
        self.final_pending = True
        transition = self.candidate(initial=True)
        started = float(kwargs["final_gate_started_monotonic"])
        return {
            "classification": "TERMINAL_TRANSITION_PENDING_REAP",
            "phase": "FIRST_FINAL_GROUP_PROOF",
            "terminal_transition_snapshot": transition,
            "signal_attempted": False,
            "signal_sent": False,
            "errors": list(transition["errors"]),
            "deadline_monotonic": float(kwargs["deadline_monotonic"]),
            "final_gate_started_monotonic": started,
            "maximum_final_gate_duration_seconds": float(
                kwargs["maximum_final_gate_duration_seconds"]
            ),
            "pre_signal_monotonic": started,
            "final_gate_elapsed_seconds": 0.0,
        }


class WatchdogPendingV12Tests(unittest.TestCase):
    @staticmethod
    def parser_evidence() -> dict[str, object]:
        return {"parser_proven": True, "confirmed": True, "errors": []}

    def run_pending(
        self,
        *,
        exit_seconds: float,
        entry_path: str = "periodic",
        initial_poll_delay_seconds: float = 0.0,
        recheck_mode: str = "candidate",
        total_timeout_seconds: float = 10.0,
        recheck_delay_seconds: float = 0.0,
        wait_error: BaseException | None = None,
    ) -> tuple[tuple[int | None, bool, bool, dict[str, object]], PendingMonitor]:
        clock = StepClock()
        process = TimedProcess(clock)
        process.wait_error = wait_error
        monitor = PendingMonitor(
            process,
            clock,
            entry_path=entry_path,
            exit_delay_ns=int(round(exit_seconds * 1_000_000_000)),
            initial_poll_delay_ns=int(
                round(initial_poll_delay_seconds * 1_000_000_000)
            ),
            recheck_mode=recheck_mode,
            recheck_delay_ns=int(round(recheck_delay_seconds * 1_000_000_000)),
        )
        grace = 0.0 if entry_path == "final" else HFNET.ZERO_KF_WATCHDOG_GRACE_SECONDS
        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value=self.parser_evidence(),
        ), mock.patch.object(HFNET, "ZERO_KF_WATCHDOG_GRACE_SECONDS", grace):
            result = HFNET.wait_with_zero_kf_watchdog(
                process,
                monitor,
                Path("stdout"),
                Path("trajectory"),
                Path("keyframes"),
                EXPECTED_EXECUTABLE,
                EXPECTED_ARGV,
                timeout=total_timeout_seconds,
                monotonic=clock.monotonic,
                monotonic_ns=clock.monotonic_ns,
            )
        self.assertFalse(monitor.signal_attempted)
        return result, monitor

    def assert_pending_success(
        self,
        result: tuple[int | None, bool, bool, dict[str, object]],
    ) -> dict[str, object]:
        returncode, reaped, timed_out, outcome = result
        self.assertEqual(returncode, EXIT_CODE)
        self.assertTrue(reaped)
        self.assertFalse(timed_out)
        self.assertTrue(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        passive = outcome["passive_exit_adjudication"]
        self.assertEqual(pending["status"], "PASSIVE_REAP_PROVEN")
        self.assertEqual(
            pending["classification"],
            "SAME_POPEN_REAPED_WITHIN_INCLUSIVE_DEADLINE",
        )
        self.assertEqual(pending["errors"], [])
        self.assertFalse(pending["signal_authorized"])
        self.assertFalse(pending["signal_attempted"])
        self.assertFalse(pending["signal_sent"])
        self.assertEqual(passive["phase"], pending["phase"])
        self.assertEqual(passive["evidence"], pending["candidate_evidence"])
        self.assertEqual(passive["reap"], pending["reap"])
        self.assertEqual(
            passive["adjudicated_monotonic_ns"],
            pending["adjudicated_monotonic_ns"],
        )
        self.assertLessEqual(
            pending["adjudicated_monotonic_ns"],
            pending["effective_deadline_monotonic_ns"],
        )
        self.assertTrue(
            all(event["requested_timeout_seconds"] > 0.0 for event in pending["wait_events"]),
            pending,
        )
        return pending

    def test_periodic_still_live_at_target_then_reaps_at_0227(self) -> None:
        result, _monitor = self.run_pending(exit_seconds=0.227)
        pending = self.assert_pending_success(result)
        self.assertEqual(pending["phase"], "PERIODIC_EXACT_GROUP_PROOF")
        self.assertEqual(
            [event["outcome"] for event in pending["wait_events"]],
            ["TIMEOUT", "RETURNED"],
        )
        self.assertGreaterEqual(
            pending["wait_events"][0]["completed_monotonic_ns"]
            - pending["anchor_completed_monotonic_ns"],
            200_000_000,
        )

    def test_late_initial_poll_at_0227_waits_only_remaining_window(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.240,
            initial_poll_delay_seconds=0.227,
        )
        pending = self.assert_pending_success(result)
        self.assertEqual(len(pending["wait_events"]), 1)
        self.assertEqual(pending["wait_events"][0]["outcome"], "RETURNED")
        self.assertGreater(pending["wait_events"][0]["requested_timeout_seconds"], 0.0)
        self.assertLessEqual(
            pending["wait_events"][0]["requested_timeout_seconds"],
            0.023000001,
        )

    def test_exact_025_boundary_is_inclusive_with_one_frozen_adjudication(self) -> None:
        result, _monitor = self.run_pending(exit_seconds=0.25)
        pending = self.assert_pending_success(result)
        self.assertEqual(
            pending["adjudicated_monotonic_ns"],
            pending["effective_deadline_monotonic_ns"],
        )
        self.assertEqual(
            pending["reap"]["wait_completed_monotonic_ns"],
            pending["effective_deadline_monotonic_ns"],
        )

    def test_beyond_025_still_live_fails_closed(self) -> None:
        result, _monitor = self.run_pending(exit_seconds=0.251)
        returncode, reaped, timed_out, outcome = result
        self.assertIsNone(returncode)
        self.assertFalse(reaped)
        self.assertFalse(timed_out)
        self.assertFalse(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        self.assertEqual(pending["status"], "FAIL_CLOSED")
        self.assertEqual(
            pending["classification"], "STILL_LIVE_AT_INCLUSIVE_DEADLINE"
        )
        self.assertIsNone(pending["reap"])
        self.assertIsNone(outcome["passive_exit_adjudication"])
        self.assertIsNone(pending["poll_events"][-1]["returncode"])
        self.assertGreaterEqual(
            pending["poll_events"][-1]["observed_monotonic_ns"],
            pending["effective_deadline_monotonic_ns"],
        )

    def test_wrong_nonempty_recheck_fails_immediately_without_second_wait(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.30,
            recheck_mode="wrong_nonempty",
        )
        outcome = result[3]
        self.assertFalse(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        self.assertEqual(pending["classification"], "UNPROVEN_PENDING_REAP")
        self.assertEqual(len(pending["wait_events"]), 1)
        self.assertIsNone(pending["reap"])
        self.assertTrue(
            any("WRONG_NONEMPTY" in error for error in pending["errors"]),
            pending,
        )

    def test_pid_start_tick_reuse_fails_closed(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.30,
            recheck_mode="pid_reuse",
        )
        outcome = result[3]
        self.assertFalse(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        self.assertEqual(pending["classification"], "UNPROVEN_PENDING_REAP")
        self.assertTrue(
            "PENDING_REAP_FROZEN_IDENTITY_CHANGED" in pending["errors"],
            pending,
        )
        self.assertIsNone(outcome["passive_exit_adjudication"])

    def test_pending_wait_exception_fails_closed_without_poll_or_reap(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.227,
            wait_error=OSError("synthetic pending wait fault"),
        )
        outcome = result[3]
        self.assertFalse(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        self.assertEqual(pending["classification"], "UNPROVEN_PENDING_REAP")
        self.assertEqual(pending["wait_events"][-1]["outcome"], "EXCEPTION")
        self.assertEqual(len(pending["poll_events"]), 1)
        self.assertIsNone(pending["reap"])
        self.assertTrue(
            any("WAIT_EXCEPTION" in error for error in pending["errors"]),
            pending,
        )

    def test_pending_recheck_poll_gap_fails_closed(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.30,
            recheck_delay_seconds=0.06,
        )
        outcome = result[3]
        self.assertFalse(outcome["monitor_proven"], outcome)
        pending = outcome["pending_reap_adjudication"]
        self.assertEqual(pending["classification"], "UNPROVEN_PENDING_REAP")
        self.assertIsNone(pending["reap"])
        self.assertTrue(
            any("POLL_GAP_EXCEEDED" in error for error in pending["errors"]),
            pending,
        )

    def test_final_gate_candidate_uses_same_bounded_reap_state(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.227,
            entry_path="final",
        )
        pending = self.assert_pending_success(result)
        self.assertEqual(
            pending["phase"], "FINAL_SIGNAL_GATE:FIRST_FINAL_GROUP_PROOF"
        )
        self.assertEqual(
            pending["anchor_source"],
            "candidate_evidence.terminal_transition_snapshot.observed_monotonic_ns",
        )
        self.assertEqual(
            pending["candidate_evidence"]["classification"],
            "TERMINAL_TRANSITION_PENDING_REAP",
        )

    def test_periodic_success_receipt_passes_common_validator(self) -> None:
        result, _monitor = self.run_pending(
            exit_seconds=0.227,
            total_timeout_seconds=1800.0,
        )
        self.assert_pending_success(result)
        outcome = result[3]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            (root / "result").mkdir(parents=True)
            contract = {
                "enabled": True,
                "fixed_grace_seconds": 30.0,
                "target_poll_interval_seconds": 0.20,
                "maximum_poll_interval_seconds": 0.25,
                "maximum_final_gate_duration_seconds": 0.25,
                "pending_reap_maximum_seconds": 0.25,
                "pending_reap_deadline_inclusive": True,
                "pending_reap_signal_authorized": False,
                "signal": "SIGTERM",
                "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
                "signal_attempt_limit": 1,
                "sigkill_authorized_by_watchdog": False,
                "estimator_total_timeout_seconds": 1800,
                "applies_to_all_hfnet_budgets_windows_and_repeats": True,
            }
            manifest = {
                "zero_kf_post_shutdown_watchdog": contract,
                "launch": {"argv": list(EXPECTED_ARGV)},
            }
            launch = {
                "schema_version": "aqua-fe-fair-stability-hfnet-launch-receipt-v12",
                "experiment_id": COMMON.EXPERIMENT_ID,
                "valid": True,
                "errors": [],
                "pid": 7,
                "start_ticks": 9,
                "pgid": 7,
                "session": 7,
                "executable": EXPECTED_EXECUTABLE,
                "argv": list(EXPECTED_ARGV),
                "expected_executable": EXPECTED_EXECUTABLE,
                "expected_argv": list(EXPECTED_ARGV),
            }
            runtime_receipt = {
                "schema_version": "aqua-fe-fair-stability-runtime-resource-monitor-v12",
                "experiment_id": COMMON.EXPERIMENT_ID,
                "monitor_proven": True,
                "intrusion_detected": False,
                "pipeline_failure_reasons": [],
                "pipeline_valid": True,
                "cleanup_actions": [],
                "supervised_process": {
                    "pid": 7,
                    "leader_identity": {"pid": 7, "start_ticks": 9},
                    "pgid": 7,
                    "returncode": EXIT_CODE,
                    "active_owned_identities_at_finalize": [],
                },
                "coverage": {"process_group_empty": True},
            }
            files = {
                "attempt_manifest.json": manifest,
                "start_claim.json": {},
                "launch_receipt.json": launch,
                "runtime_resource_monitor.json": runtime_receipt,
            }
            for name, value in files.items():
                (root / name).write_text(
                    json.dumps(value, sort_keys=True) + "\n", encoding="utf-8"
                )
            (root / "headless.stdout.log").write_bytes(b"shutdown\n")
            receipt = HFNET.build_zero_kf_watchdog_receipt(
                root,
                "case",
                675,
                1,
                1,
                manifest,
                outcome,
                EXIT_CODE,
                [],
            )
            watchdog_path = root / "zero_kf_post_shutdown_watchdog.json"
            watchdog_path.write_text(
                json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
            )
            result_receipt = {
                "zero_kf_post_shutdown_watchdog": HFNET.identity(watchdog_path),
                "zero_kf_post_shutdown_watchdog_decision": {
                    "monitor_proven": True,
                    "sigterm_sent": False,
                    "retry_permitted": False,
                    "pipeline_failure_code_if_unproven": (
                        "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
                    ),
                    "algorithm_failure_code_if_sent": (
                        "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                    ),
                },
                "pipeline_failure_codes": [],
                "algorithm_failure_codes": ["ESTIMATOR_EXIT_NONZERO"],
                "execution": {
                    "raw_returncode": EXIT_CODE,
                    "child_reaped": True,
                    "timed_out": False,
                    "supervised_process_group_empty_after_wait": True,
                },
                "runtime_resource_monitor_decision": {
                    "intrusion_detected": False,
                    "monitor_proven": True,
                    "pipeline_failure_reasons": [],
                },
            }
            COMMON.validate_hfnet_watchdog_evidence(
                root,
                manifest,
                result_receipt,
                {"case_id": "case", "arm": "hfnet_openloop_675", "repeat": 1},
                1,
            )


if __name__ == "__main__":
    unittest.main()
