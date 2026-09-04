#!/usr/bin/python3
"""Small, non-estimator regression tests for the v11 coverage close scan."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESOURCE = load(
    "fair_stability_runtime_resource_monitor_v11_close_test",
    SCRIPTS / "fair_stability_runtime_resource_monitor_v11.py",
)


class ClosingProcProbeTests(unittest.TestCase):
    @staticmethod
    def bare_monitor() -> object:
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.process = SimpleNamespace(returncode=0)
        monitor.pid = 4242
        monitor.pgid = 4242
        monitor.supervisor_pid = os.getpid()
        monitor.leader_identity = (4242, 100)
        monitor.leader_record = None
        monitor.coverage_start_monotonic_ns = 0
        monitor.coverage_started_at_utc = "2026-08-30T00:00:00+00:00"
        monitor.coverage_end_monotonic_ns = None
        monitor.coverage_ended_at_utc = None
        monitor._lock = threading.RLock()
        monitor._probe_condition = threading.Condition(monitor._lock)
        monitor._stop = threading.Event()
        monitor._coverage_phase = "OPEN"
        monitor._coverage_close_recheck_in_progress = False
        monitor._active_probe_reservations = {}
        monitor._resolved_probe_reservations = set()
        monitor._proc_samples = []
        monitor._gpu_samples = []
        monitor._monitor_errors = []
        monitor._known_owned = set()
        monitor._active_owned = set()
        monitor._ownership_discovery_history = []
        monitor._latest_proc_records = []
        monitor._cleanup_actions = []
        monitor._final_receipt = None
        return monitor

    @staticmethod
    def proc_sample(
        sequence: int,
        started_ns: int,
        finished_ns: int,
    ) -> dict[str, object]:
        return {
            "sequence": sequence,
            "probe_role": RESOURCE.ORDINARY_PROC_PROBE_ROLE,
            "probe_started_at_utc": "2026-08-30T00:00:00+00:00",
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "process_count": 0,
            "owned_identities": [],
            "supervised_pgid": 4242,
            "process_group_members": [],
            "external_conflicting_processes": [],
            "probe_errors": [],
        }

    def sampling(self, monitor: object) -> dict[str, object]:
        return RESOURCE._sampling_gap_report(
            monitor._proc_samples,
            monitor.coverage_start_monotonic_ns,
            monitor.coverage_end_monotonic_ns,
            RESOURCE.PROC_TARGET_INTERVAL_SECONDS,
            RESOURCE.PROC_MAX_START_GAP_SECONDS,
        )

    def test_slow_reserved_probe_then_closing_scan_are_separate_samples(self) -> None:
        monitor = self.bare_monitor()
        prior = self.proc_sample(0, 10_000_000, 239_000_000)
        token = ("proc", 0)
        monitor._active_probe_reservations[token] = (
            9_000_000,
            "2026-08-30T00:00:00+00:00",
        )
        observed_during_scan: list[tuple[str, dict[object, object]]] = []

        def scan():
            observed_during_scan.append(
                (monitor._coverage_phase, dict(monitor._active_probe_reservations))
            )
            return [], []

        clock_values = iter((240_000_000, 440_000_000, 440_000_001))

        def clock() -> int:
            value = next(clock_values)
            if value == 440_000_001:
                # The end timestamp may only be read after closing publication.
                self.assertEqual(len(monitor._proc_samples), 2)
                self.assertEqual(
                    monitor._proc_samples[-1]["probe_role"],
                    RESOURCE.CLOSING_PROC_PROBE_ROLE,
                )
            return value

        with mock.patch.object(
            RESOURCE, "_scan_processes", side_effect=scan
        ) as close_scan, mock.patch.object(
            RESOURCE.time, "monotonic_ns", side_effect=clock
        ), mock.patch.object(
            RESOURCE,
            "_utc_now",
            return_value="2026-08-30T00:00:01+00:00",
        ):
            self.assertTrue(monitor._mark_coverage_end_if_empty([]))
            self.assertEqual(monitor._coverage_phase, "CLOSE_PENDING")
            self.assertIsNone(monitor.coverage_end_monotonic_ns)
            self.assertIsNone(monitor._reserve_probe_start("proc", 1))
            self.assertIsNone(monitor._reserve_probe_start("gpu", 0))
            monitor._resolve_probe_reservation(token, prior)

        close_scan.assert_called_once_with()
        self.assertEqual(observed_during_scan, [("CLOSE_PENDING", {})])
        self.assertEqual([row["sequence"] for row in monitor._proc_samples], [0, 1])
        closing = monitor._proc_samples[-1]
        self.assertEqual(closing["probe_role"], RESOURCE.CLOSING_PROC_PROBE_ROLE)
        self.assertTrue(closing["coverage_close_ownership_empty"])
        self.assertTrue(closing["coverage_close_recheck_proven"])
        self.assertLessEqual(
            closing["probe_finished_monotonic_ns"],
            monitor.coverage_end_monotonic_ns,
        )
        self.assertEqual(monitor._coverage_phase, "CLOSED")
        self.assertTrue(self.sampling(monitor)["proven"])

        # Without the evidence-bearing closing row, the old tail combines the
        # two probe durations and falsely exceeds the 0.25 s start-gap limit.
        old_shape = RESOURCE._sampling_gap_report(
            [prior],
            0,
            monitor.coverage_end_monotonic_ns,
            RESOURCE.PROC_TARGET_INTERVAL_SECONDS,
            RESOURCE.PROC_MAX_START_GAP_SECONDS,
        )
        self.assertFalse(old_shape["proven"])
        self.assertTrue(old_shape["tail_coverage_gap_violation"])

    def test_closing_scan_duration_boundary_is_still_enforced(self) -> None:
        for duration_ns, expected_proven in (
            (250_000_000, True),
            (250_000_001, False),
        ):
            with self.subTest(duration_ns=duration_ns):
                monitor = self.bare_monitor()
                monitor._proc_samples.append(
                    self.proc_sample(0, 10_000_000, 200_000_000)
                )
                start_ns = 240_000_000
                finish_ns = start_ns + duration_ns
                with mock.patch.object(
                    RESOURCE, "_scan_processes", return_value=([], [])
                ), mock.patch.object(
                    RESOURCE.time,
                    "monotonic_ns",
                    side_effect=(start_ns, finish_ns, finish_ns),
                ), mock.patch.object(
                    RESOURCE,
                    "_utc_now",
                    return_value="2026-08-30T00:00:01+00:00",
                ):
                    self.assertTrue(monitor._mark_coverage_end_if_empty([]))

                self.assertEqual(monitor.coverage_end_monotonic_ns, finish_ns)
                report = self.sampling(monitor)
                self.assertIs(report["proven"], expected_proven)
                self.assertIs(
                    report["tail_coverage_gap_violation"],
                    not expected_proven,
                )
                self.assertAlmostEqual(
                    report["tail_coverage_gap_seconds"],
                    duration_ns / 1e9,
                )

    def test_concurrent_close_runs_and_publishes_exactly_one_closing_scan(self) -> None:
        monitor = self.bare_monitor()
        callers_ready = threading.Barrier(3)
        scan_started = threading.Event()
        release_scan = threading.Event()
        one_returned = threading.Event()
        results: list[bool] = []
        failures: list[BaseException] = []

        def scan():
            scan_started.set()
            if not release_scan.wait(2.0):
                raise AssertionError("closing scan release timed out")
            return [], []

        def close() -> None:
            try:
                callers_ready.wait()
                results.append(monitor._mark_coverage_end_if_empty([]))
            except BaseException as error:
                failures.append(error)
            finally:
                one_returned.set()

        with mock.patch.object(
            RESOURCE, "_scan_processes", side_effect=scan
        ) as close_scan:
            callers = [threading.Thread(target=close) for _ in range(2)]
            for caller in callers:
                caller.start()
            callers_ready.wait()
            self.assertTrue(scan_started.wait(2.0))
            self.assertTrue(one_returned.wait(2.0))
            self.assertIsNone(monitor.coverage_end_monotonic_ns)
            release_scan.set()
            for caller in callers:
                caller.join(2.0)

        self.assertEqual(failures, [])
        self.assertEqual(results, [True, True])
        self.assertTrue(all(not caller.is_alive() for caller in callers))
        close_scan.assert_called_once_with()
        closing = [
            row
            for row in monitor._proc_samples
            if row.get("probe_role") == RESOURCE.CLOSING_PROC_PROBE_ROLE
        ]
        self.assertEqual(len(closing), 1)
        self.assertIs(closing[0], monitor._proc_samples[-1])
        self.assertEqual(monitor._coverage_phase, "CLOSED")

    def test_scan_exception_in_thread_is_published_and_fails_closed(self) -> None:
        monitor = self.bare_monitor()
        uncaught: list[BaseException] = []

        def close() -> None:
            try:
                monitor._mark_coverage_end_if_empty([])
            except BaseException as error:
                uncaught.append(error)

        with mock.patch.object(
            RESOURCE,
            "_scan_processes",
            side_effect=RuntimeError("deterministic-closing-fault"),
        ) as close_scan, mock.patch.object(
            RESOURCE.time, "monotonic_ns", side_effect=(100, 200)
        ), mock.patch.object(
            RESOURCE,
            "_utc_now",
            return_value="2026-08-30T00:00:01+00:00",
        ):
            thread = threading.Thread(target=close)
            thread.start()
            thread.join(2.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(uncaught, [])
            self.assertFalse(monitor._complete_coverage_close_if_ready())

        close_scan.assert_called_once_with()
        self.assertIsNone(monitor.coverage_end_monotonic_ns)
        self.assertEqual(monitor._coverage_phase, "CLOSE_PENDING")
        self.assertEqual(len(monitor._proc_samples), 1)
        closing = monitor._proc_samples[0]
        self.assertEqual(closing["probe_role"], RESOURCE.CLOSING_PROC_PROBE_ROLE)
        self.assertFalse(closing["coverage_close_recheck_proven"])
        self.assertTrue(
            any(
                error.startswith(
                    "COVERAGE_CLOSE_PROC_PROBE_EXCEPTION:RuntimeError:"
                )
                for error in closing["probe_errors"]
            )
        )
        self.assertIn(
            "COVERAGE_CLOSE_OWNERSHIP_RECHECK_UNPROVEN",
            monitor._monitor_errors,
        )

    def test_scan_error_and_ownership_recheck_exception_both_fail_closed(self) -> None:
        monitor = self.bare_monitor()
        with mock.patch.object(
            RESOURCE,
            "_scan_processes",
            return_value=([], ["PROC_SCAN_FAILED:deterministic"]),
        ), mock.patch.object(
            RESOURCE.time, "monotonic_ns", side_effect=(100, 200)
        ), mock.patch.object(
            RESOURCE,
            "_utc_now",
            return_value="2026-08-30T00:00:01+00:00",
        ):
            self.assertTrue(monitor._mark_coverage_end_if_empty([]))
        self.assertIsNone(monitor.coverage_end_monotonic_ns)
        self.assertIn(
            "PROC_SCAN_FAILED:deterministic",
            monitor._proc_samples[-1]["probe_errors"],
        )

        monitor = self.bare_monitor()
        original_refresh = monitor._refresh_owned
        calls = 0

        def refresh(records):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_refresh(records)
            raise OSError("ownership-recheck-fault")

        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([], [])
        ), mock.patch.object(
            monitor, "_refresh_owned", side_effect=refresh
        ), mock.patch.object(
            RESOURCE.time, "monotonic_ns", side_effect=(300, 400)
        ), mock.patch.object(
            RESOURCE,
            "_utc_now",
            return_value="2026-08-30T00:00:02+00:00",
        ):
            self.assertTrue(monitor._mark_coverage_end_if_empty([]))
        self.assertIsNone(monitor.coverage_end_monotonic_ns)
        self.assertFalse(monitor._proc_samples[-1]["coverage_close_recheck_proven"])
        self.assertTrue(
            any(
                "ownership-recheck-fault" in error
                for error in monitor._proc_samples[-1]["probe_errors"]
            )
        )

    def test_ownership_precheck_exception_does_not_kill_calling_thread(self) -> None:
        monitor = self.bare_monitor()
        monitor._owned_empty = mock.Mock(
            side_effect=OSError("ownership-precheck-fault")
        )
        results: list[bool] = []
        uncaught: list[BaseException] = []

        def close() -> None:
            try:
                results.append(monitor._mark_coverage_end_if_empty([]))
            except BaseException as error:
                uncaught.append(error)

        thread = threading.Thread(target=close)
        thread.start()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(uncaught, [])
        self.assertEqual(results, [False])
        self.assertEqual(monitor._coverage_phase, "OPEN")
        self.assertIsNone(monitor.coverage_end_monotonic_ns)
        self.assertTrue(
            any(
                error.startswith(
                    "COVERAGE_CLOSE_OWNERSHIP_PRECHECK_EXCEPTION:OSError:"
                )
                for error in monitor._monitor_errors
            )
        )

    def test_failed_closing_recheck_never_writes_forced_full_receipt(self) -> None:
        monitor = self.bare_monitor()
        with mock.patch.object(
            RESOURCE,
            "_scan_processes",
            side_effect=RuntimeError("closing-scan-fault"),
        ), mock.patch.object(
            RESOURCE.time, "monotonic_ns", side_effect=(100, 200)
        ), mock.patch.object(
            RESOURCE,
            "_utc_now",
            return_value="2026-08-30T00:00:01+00:00",
        ):
            self.assertTrue(monitor._mark_coverage_end_if_empty([]))

        monitor._proc_thread = mock.Mock()
        monitor._proc_thread.is_alive.return_value = False
        monitor._gpu_thread = mock.Mock()
        monitor._gpu_thread.is_alive.return_value = False
        with tempfile.TemporaryDirectory() as temporary:
            monitor.output_path = Path(temporary) / "runtime_resource_monitor.json"
            with mock.patch.object(
                RESOURCE, "_scan_processes", return_value=([], [])
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "CLEAN_COVERAGE_CLOSE_UNPROVEN",
                ):
                    monitor.finalize()
            self.assertFalse(monitor.output_path.exists())
        self.assertIsNone(monitor.coverage_end_monotonic_ns)
        self.assertEqual(monitor._coverage_phase, "CLOSE_PENDING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
