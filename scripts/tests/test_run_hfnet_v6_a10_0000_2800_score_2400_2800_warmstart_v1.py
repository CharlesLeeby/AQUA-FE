#!/usr/bin/env python3
"""Process-free tests for the A10 HFNet warm-start one-shot runner."""

from __future__ import annotations

import os
from pathlib import Path
import json
from contextlib import ExitStack
import tempfile
import unittest
from unittest import mock

from scripts import run_hfnet_v6_a10_0000_2800_score_2400_2800_warmstart_v1 as runner


def _stamps() -> list[int]:
    return [1_000_000_000_000_000_000 + index * 50_000_000 for index in range(2801)]


def _pose_line(stamp: int) -> str:
    return f"{stamp} 0 0 0 0 0 0 1"


def _runtime_paths(root: Path) -> dict[str, Path]:
    result_dir = root / "result"
    result_dir.mkdir()
    return {
        "result_dir": result_dir,
        "stdout": root / "headless.stdout.log",
        "stderr": root / "headless.stderr.log",
        "score_trajectory": result_dir / "trajectory_score_2400_2800.txt",
    }


def _clean_value() -> dict[str, object]:
    return {
        "execution": {
            "raw_returncode": 0,
            "timed_out": False,
            "supervisor_error": None,
            "child_reaped_before_post_audit": True,
        },
        "integrity": {
            "selected_input_unchanged": True,
            "local_onnx_unchanged": True,
            "runtime_authority_unchanged": True,
            "local_cache_contract_valid": True,
            "all_post_audits_complete": True,
        },
    }


def _write_complete_outputs(paths: dict[str, Path], stamps: list[int], log: str) -> None:
    trajectory = paths["result_dir"] / "trajectory.txt"
    keyframes = paths["result_dir"] / "trajectory_keyframe.txt"
    trajectory.write_text(
        "\n".join(_pose_line(stamps[index]) for index in range(2399, 2801)) + "\n",
        encoding="ascii",
    )
    keyframes.write_text(_pose_line(stamps[2500]) + "\n", encoding="ascii")
    paths["stdout"].write_text(log, encoding="utf-8")
    paths["stderr"].write_bytes(b"")


class A10WarmstartRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_strict_score_pass_writes_exact_exclusive_crop(self) -> None:
        stamps = _stamps()
        paths = _runtime_paths(self.root)
        _write_complete_outputs(
            paths,
            stamps,
            "\n".join(
                (
                    "Init frame id: 0",
                    "Imu initialized",
                    "Saving trajectory to synthetic/result/trajectory.txt ...",
                    "There are 1 maps in the atlas",
                    "  Map 0 has 42 KFs",
                    "End of saving trajectory to synthetic/result/trajectory.txt ...",
                )
            ),
        )
        with mock.patch.object(
            runner, "selected_timestamps", return_value=stamps
        ), mock.patch.object(runner, "paths", return_value=paths):
            result = runner.score_adjudication(_clean_value())

        self.assertTrue(result["passed"])
        self.assertEqual(result["failure_codes"], [])
        self.assertEqual(result["score"]["pose_count"], 401)
        self.assertTrue(result["score"]["preroll_to_score_boundary_continuous"])
        self.assertTrue(result["runtime_log"]["pre_score_initialized"])
        crop = paths["score_trajectory"]
        self.assertTrue(crop.is_file())
        rows = crop.read_text(encoding="ascii").splitlines()
        self.assertEqual(len(rows), 401)
        self.assertTrue(rows[0].startswith(str(stamps[2400])))
        self.assertTrue(rows[-1].startswith(str(stamps[2800])))
        self.assertEqual(os.stat(crop).st_mode & 0o777, 0o444)
        with self.assertRaises(FileExistsError):
            runner._write_exclusive(crop, b"must-not-overwrite\n")

    def test_score_window_state_breaks_fail_closed(self) -> None:
        cases = (
            (
                "SYSTEM-> Reseting active map in monocular case\nmnFirstFrameId = 2500",
                "SCORE_WINDOW_ACTIVE_MAP_RESET",
            ),
            ("Init frame id: 2450", "SCORE_WINDOW_REINITIALIZATION"),
            (
                "SYSTEM-> Reseting active map in monocular case",
                "ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED",
            ),
        )
        for case_index, (extra_log, failure_code) in enumerate(cases):
            with self.subTest(failure_code=failure_code):
                case_root = self.root / str(case_index)
                case_root.mkdir()
                stamps = _stamps()
                paths = _runtime_paths(case_root)
                _write_complete_outputs(
                    paths,
                    stamps,
                    "\n".join(
                        (
                            "Init frame id: 0",
                            extra_log,
                            "Saving trajectory to synthetic/result/trajectory.txt ...",
                            "There are 1 maps in the atlas",
                            "  Map 0 has 42 KFs",
                            "End of saving trajectory to synthetic/result/trajectory.txt ...",
                        )
                    ),
                )
                with mock.patch.object(
                    runner, "selected_timestamps", return_value=stamps
                ), mock.patch.object(runner, "paths", return_value=paths):
                    result = runner.score_adjudication(_clean_value())

                self.assertFalse(result["passed"])
                self.assertIn(failure_code, result["failure_codes"])
                self.assertFalse(paths["score_trajectory"].exists())

    def test_inherited_controller_wiring_reaches_base(self) -> None:
        runner.configure_profile()
        a09 = runner.inherited
        a09.configure_profile()
        a10 = a09.profile
        a10.configure_base()

        self.assertEqual(a09.RUNNER, runner.RUNNER)
        self.assertEqual(a10.RUNNER, runner.RUNNER)
        self.assertEqual(a10.base.RUNNER, runner.RUNNER)
        self.assertEqual(a10.base.SOURCE_ROOT, runner.INPUT_ROOT)
        self.assertEqual(a09.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertEqual(a10.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertEqual(a10.base.TIMEOUT_SECONDS, runner.TIMEOUT_SECONDS)
        self.assertIs(a09.paths, runner.paths)
        self.assertIs(a10.paths, runner.paths)
        self.assertIs(a10.base.attempt_paths, runner.paths)
        self.assertIs(a10.base.atomic_json, runner.profile_atomic_json)
        self.assertIs(a10.bound_popen, a09.bound_popen)
        self.assertIs(a10.base.run, runner.run_once)
        self.assertIs(a10.run_with_watchdog, runner.warm_run_with_watchdog)

    def test_claimed_popen_exception_still_seals_terminal_failure(self) -> None:
        base = runner.inherited.profile.base
        attempt = self.root / "attempt"
        result_dir = attempt / "result"
        result_dir.mkdir(parents=True)
        prepared_path = attempt / "prepared_manifest.json"
        prepared_path.write_text("{}\n", encoding="utf-8")
        path_map = {
            "prepared": prepared_path,
            "claim": attempt / "process_start_claim.json",
            "result": attempt / "run_result.json",
            "stdout": attempt / "headless.stdout.log",
            "stderr": attempt / "headless.stderr.log",
            "result_dir": result_dir,
            "score_trajectory": result_dir / "trajectory_score_2400_2800.txt",
        }
        prepared = {
            "launch": {"argv": ["synthetic-hfnet"]},
            "input_inventory": {"synthetic": True},
            "selection": {"score_source_frame_indices_inclusive": [2400, 2800]},
            "scientific_role": "DEVELOPMENT_ONLY_SYNTHETIC_TEST",
        }
        stamps = _stamps()
        popen_calls: list[object] = []

        def fail_popen(*args: object, **kwargs: object) -> object:
            popen_calls.append((args, kwargs))
            runner.inherited._BOUND_POPEN_COUNT += 1
            raise RuntimeError("synthetic popen failure after bound count")

        old_count = runner.inherited._BOUND_POPEN_COUNT
        old_claim_state = runner._CLAIM_CREATED_THIS_PROCESS
        runner.inherited._BOUND_POPEN_COUNT = 0
        runner._CLAIM_CREATED_THIS_PROCESS = False
        self.addCleanup(setattr, runner.inherited, "_BOUND_POPEN_COUNT", old_count)
        self.addCleanup(setattr, runner, "_CLAIM_CREATED_THIS_PROCESS", old_claim_state)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner, "paths", return_value=path_map))
            stack.enter_context(
                mock.patch.object(runner, "check", return_value={"ready": True, "errors": []})
            )
            stack.enter_context(
                mock.patch.object(runner, "_validate_prepared_launch", return_value=None)
            )
            stack.enter_context(mock.patch.object(
                runner,
                "runtime_authority_snapshot",
                side_effect=lambda include_claim=False: {"include_claim": include_claim},
            ))
            stack.enter_context(mock.patch.object(
                runner,
                "local_cache_state",
                return_value={"identity": {"sha256": "seed"}, "isolated": True},
            ))
            stack.enter_context(mock.patch.object(runner, "selected_timestamps", return_value=stamps))
            stack.enter_context(mock.patch.object(base, "load_prepared", return_value=prepared))
            stack.enter_context(
                mock.patch.object(base, "input_inventory", return_value={"synthetic": True})
            )
            stack.enter_context(mock.patch.object(base, "runtime_environment", return_value={}))
            stack.enter_context(mock.patch.object(base.subprocess, "Popen", side_effect=fail_popen))
            value = runner.run_once(runner.AUTHORIZATION_TOKEN)

        self.assertEqual(len(popen_calls), 1)
        self.assertEqual(value["status"], "FAIL_DEVELOPMENT_RUNABILITY_RESCUE")
        self.assertIn("SUPERVISOR_EXCEPTION", value["failure_codes"])
        self.assertTrue(path_map["claim"].is_file())
        self.assertTrue(path_map["result"].is_file())
        persisted = json.loads(path_map["result"].read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "FAIL_DEVELOPMENT_RUNABILITY_RESCUE")
        self.assertFalse(persisted["terminal_contract"]["retry_after_pass_or_fail"])
        self.assertEqual(os.stat(path_map["stdout"]).st_mode & 0o777, 0o444)
        self.assertEqual(os.stat(path_map["stderr"]).st_mode & 0o777, 0o444)

    def test_regular_tree_closure_exposes_extra_empty_directory(self) -> None:
        (self.root / "mav0/cam0/data").mkdir(parents=True)
        (self.root / "mav0/imu0").mkdir(parents=True)
        (self.root / "mav0/cam0/data/frame.png").write_bytes(b"png")
        (self.root / "unexpected_empty").mkdir()

        files, directories = runner._regular_tree_closure(self.root)

        self.assertEqual(files, {"mav0/cam0/data/frame.png"})
        self.assertIn("unexpected_empty", directories)

    def test_total_wrapper_seals_unexpected_postclaim_exception(self) -> None:
        result = self.root / "run_result.json"
        path_map = {"result": result}
        old_claim_state = runner._CLAIM_CREATED_THIS_PROCESS
        runner._CLAIM_CREATED_THIS_PROCESS = False
        self.addCleanup(setattr, runner, "_CLAIM_CREATED_THIS_PROCESS", old_claim_state)

        def explode_after_claim(token: str) -> dict[str, object]:
            runner._CLAIM_CREATED_THIS_PROCESS = True
            raise RuntimeError(f"unexpected after {token}")

        with mock.patch.object(runner, "paths", return_value=path_map), mock.patch.object(
            runner, "_run_once_impl", side_effect=explode_after_claim
        ):
            value = runner.run_once("synthetic-token")

        self.assertEqual(value["status"], "FAIL_DEVELOPMENT_RUNABILITY_RESCUE")
        self.assertIn("UNCAUGHT_POSTCLAIM_EXCEPTION", value["failure_codes"])
        self.assertTrue(result.is_file())

    def test_regular_tree_closure_rejects_fifo_and_symlink(self) -> None:
        fifo_root = self.root / "fifo"
        fifo_root.mkdir()
        os.mkfifo(fifo_root / "special")
        with self.assertRaises(runner.inherited.profile.base.ContractError):
            runner._regular_tree_closure(fifo_root)

        link_root = self.root / "link"
        link_root.mkdir()
        (link_root / "target").write_bytes(b"x")
        (link_root / "alias").symlink_to("target")
        with self.assertRaises(runner.inherited.profile.base.ContractError):
            runner._regular_tree_closure(link_root)

    def test_atomic_no_replace_publisher_never_exposes_partial_final(self) -> None:
        destination = self.root / "terminal.json"
        with mock.patch.object(os, "link", side_effect=OSError("synthetic link failure")):
            with self.assertRaises(OSError):
                runner._publish_bytes_exclusive_atomic(destination, b"complete\n")
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".terminal.json.pending.*")), [])

        with self.assertRaises(TypeError):
            runner._publish_json_exclusive_atomic(destination, {"bad": object()})
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
